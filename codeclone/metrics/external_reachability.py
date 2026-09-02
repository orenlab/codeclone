# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""External reachability: does a public import path to a symbol exist?

The evidence layer under the dead-code evaluator (RULING 2026-09-01). One
central rule, stated as the language states it and read only from facts that
already ride the cache wire, so a warm run answers exactly as a cold one:

* a name is **publicly bound** in a module when the module defines it, when a
  wildcard import binds it there (``from x import *`` binds what the target's
  ``__all__`` rule says - the ``star_import_bound`` fact on the candidate),
  or when a package ``__init__`` imports it by name (PEP 8: the package
  re-exports what it imports; a plain module's imports are implementation
  detail);
* a module is **public** when no segment of its dotted name starts with an
  underscore, and a symbol is **public** when no segment of its local path
  does - the one privacy statement Python has;
* a public symbol publicly bound in a public module, or in a module a public
  module reaches through wildcard edges, is ``reachable``;
* a public method is reachable when its class is, when any project subclass
  of its class is (the subclass inherits it), or when any project ancestor of
  its class is exposed itself (a caller holding the ancestor's type dispatches
  into the override);
* the state is ``unresolved`` when the construct that decides exposure cannot
  be read statically: a public package with a module-level ``__getattr__``
  (PEP 562 can serve any name below it), a public package whose namespace
  ``lazy_loader`` builds from a stub the walk never reads, or a class whose
  base no edge binds.

Everything else is ``not_reachable``. Every rule over-approximates in the
same direction: a name the project could expose is called reachable, never
the reverse, because the failure this layer exists to prevent is a
high-confidence assertion that live public API is dead.

What is deliberately NOT decided here: ``__all__`` as a language beyond the
binding fact the walk already resolved (dynamic ``__all__``, concatenation,
imported ``__all__``) and the liveness question itself. Reachability is
evidence; the evaluator in :mod:`codeclone.metrics.dead_code` combines it with
liveness evidence and the world contract.
"""

from __future__ import annotations

import builtins
from collections import deque
from typing import TYPE_CHECKING, Final

from ..models import ExternalReachability

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

    from ..models import ClassMetrics, DeadCandidate, ModuleDep, ModuleRegistryHandle

    #: The one seam every exposure rule writes through: qualname, witness.
    _Expose = Callable[[str, str], None]

#: A base spelled as a builtin (``Exception``, ``dict``) binds outside the
#: project without an import edge; it is resolved, not unresolved.
_BUILTIN_NAMES: Final = frozenset(dir(builtins))
#: Bound on the named-binding walk: a re-export chain deeper than this is not
#: a package facade, and the walk must terminate on any input.
_BINDING_HOPS: Final = 32


def package_modules_from_registry(
    module_registry: ModuleRegistryHandle,
) -> frozenset[str]:
    """The package ``__init__`` modules of the analysis root."""

    return frozenset(
        module
        for module, entry in module_registry.entries_by_module.rows
        if (
            (identity := entry.identity.python_module) is not None
            and identity.is_package
        )
    )


def _is_public_module(module: str) -> bool:
    return bool(module) and not any(
        segment.startswith("_") for segment in module.split(".")
    )


def _is_public_path(local: str) -> bool:
    return bool(local) and not any(
        segment.startswith("_") for segment in local.split(".")
    )


def _closure(start: str, edges: dict[str, set[str]]) -> tuple[str, ...]:
    """Transitive closure over ``edges`` from ``start``, excluding ``start``."""

    seen: set[str] = set()
    queue: deque[str] = deque(sorted(edges.get(start, ())))
    while queue:
        node = queue.popleft()
        if node in seen or node == start:
            continue
        seen.add(node)
        queue.extend(sorted(edges.get(node, ())))
    return tuple(sorted(seen))


def _index_edges(
    module_deps: Sequence[ModuleDep],
) -> tuple[
    dict[str, set[str]],
    dict[str, set[tuple[str, str]]],
    dict[str, set[str]],
    set[str],
]:
    """Wildcard edges, named imports and every import target, by source."""

    star_edges: dict[str, set[str]] = {}
    named_imports: dict[str, set[tuple[str, str]]] = {}
    import_targets: dict[str, set[str]] = {}
    modules: set[str] = set()
    for dep in module_deps:
        if not dep.source or not dep.target:
            continue
        modules.add(dep.source)
        modules.add(dep.target)
        import_targets.setdefault(dep.source, set()).add(dep.target)
        for name in dep.requested_names:
            if name == "*":
                star_edges.setdefault(dep.source, set()).add(dep.target)
            else:
                named_imports.setdefault(dep.source, set()).add((dep.target, name))
    return star_edges, named_imports, import_targets, modules


def _index_definitions(
    dead_candidates: Sequence[DeadCandidate],
    class_metrics: Sequence[ClassMetrics],
) -> tuple[set[str], set[str], dict[str, set[str]], dict[str, set[str]]]:
    """Project classes and module-level definitions, by module and by leaf."""

    classes = {metric.qualname for metric in class_metrics} | {
        candidate.qualname for candidate in dead_candidates if candidate.kind == "class"
    }
    definitions = set(classes) | {
        candidate.qualname
        for candidate in dead_candidates
        if candidate.kind != "method"
    }
    definitions_by_module: dict[str, set[str]] = {}
    for qualname in definitions:
        definitions_by_module.setdefault(qualname.partition(":")[0], set()).add(
            qualname
        )
    classes_by_leaf: dict[str, set[str]] = {}
    for qualname in classes:
        leaf = qualname.partition(":")[2].rpartition(".")[2]
        classes_by_leaf.setdefault(leaf, set()).add(qualname)
    return classes, definitions, definitions_by_module, classes_by_leaf


def _dynamic_packages(
    dead_candidates: Sequence[DeadCandidate],
    *,
    package_modules: frozenset[str],
    public_modules: frozenset[str],
    import_targets: Mapping[str, set[str]],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Public packages whose namespace no static read can settle.

    A module-level ``def __getattr__`` (PEP 562) can serve any name below the
    package. ``import lazy_loader`` in a package ``__init__`` is the one wired
    trace of ``(__getattr__, __dir__, __all__) = lazy.attach_stub(...)``: the
    names it serves live in a ``.pyi`` stub the walk never reads, so that
    namespace is as dynamic as a spelled-out ``__getattr__``. Measured on
    mne-python: without the second rule ten documented ``Brain`` methods read
    as high-confidence dead under the open world.
    """

    public_packages = package_modules & public_modules
    getattr_packages = tuple(
        sorted(
            candidate.qualname.partition(":")[0]
            for candidate in dead_candidates
            if candidate.kind == "function"
            and candidate.local_name == "__getattr__"
            and candidate.qualname.partition(":")[0] in public_packages
        )
    )
    lazy_packages = tuple(
        sorted(
            module
            for module in public_packages
            if "lazy_loader" in import_targets.get(module, set())
        )
    )
    return getattr_packages, lazy_packages


class _Population:
    """The wired facts, indexed once; every rule below reads only these."""

    def __init__(
        self,
        *,
        dead_candidates: Sequence[DeadCandidate],
        module_deps: Sequence[ModuleDep],
        class_metrics: Sequence[ClassMetrics],
        package_modules: frozenset[str],
    ) -> None:
        self.candidates = {
            candidate.qualname: candidate for candidate in dead_candidates
        }
        (
            self.star_edges,
            self.named_imports,
            self.import_targets,
            modules,
        ) = _index_edges(module_deps)
        (
            self.classes,
            self.definitions,
            self.definitions_by_module,
            self.classes_by_leaf,
        ) = _index_definitions(dead_candidates, class_metrics)
        modules |= set(package_modules)
        modules.update(
            qualname.partition(":")[0] for qualname in (*self.candidates, *self.classes)
        )
        self.public_modules = frozenset(
            module for module in modules if _is_public_module(module)
        )
        self.package_modules = package_modules
        self.external_base_classes = frozenset(
            metric.qualname
            for metric in class_metrics
            if metric.has_unresolved_external_base
        )
        self.class_metrics = tuple(class_metrics)
        self.getattr_packages, self.lazy_packages = _dynamic_packages(
            dead_candidates,
            package_modules=package_modules,
            public_modules=self.public_modules,
            import_targets=self.import_targets,
        )

    def star_bound(self, qualname: str) -> bool:
        candidate = self.candidates.get(qualname)
        return candidate is not None and candidate.star_import_bound

    def resolve_binding(self, module: str, name: str) -> frozenset[str]:
        """The definitions ``<module>.<name>`` binds, by CPython's rules.

        A local definition wins; otherwise the name was imported - by name
        from one module, which is followed, or by a wildcard, which binds the
        target's definition only when the target's ``__all__`` rule says so.
        """

        found: set[str] = set()
        seen: set[tuple[str, str]] = set()
        stack: list[tuple[str, str, int]] = [(module, name, 0)]
        while stack:
            current, local, depth = stack.pop()
            if (current, local) in seen or depth > _BINDING_HOPS:
                continue
            seen.add((current, local))
            qualname = f"{current}:{local}"
            if qualname in self.definitions:
                found.add(qualname)
                continue
            for target, imported in sorted(self.named_imports.get(current, ())):
                if imported == local:
                    stack.append((target, local, depth + 1))
            for target in sorted(self.star_edges.get(current, ())):
                star_qualname = f"{target}:{local}"
                if star_qualname in self.definitions:
                    if self.star_bound(star_qualname):
                        found.add(star_qualname)
                else:
                    stack.append((target, local, depth + 1))
        return frozenset(found)

    def resolve_base(self, module: str, spelling: str) -> frozenset[str]:
        """Project classes a base spelling can bind to, over-approximated.

        A simple name is a local class, an imported binding or nothing. A
        dotted name goes through a module alias the dependency edge names
        without its alias, so the leaf is matched against the classes of the
        modules this module imports, then of any module whose last segment
        the prefix names, then anywhere: an ancestor the project could have
        meant is linked rather than dropped, because dropping one is the
        direction that asserts a live override dead.
        """

        if "." not in spelling:
            local = f"{module}:{spelling}"
            if local in self.classes:
                return frozenset({local})
            return frozenset(
                qualname
                for qualname in self.resolve_binding(module, spelling)
                if qualname in self.classes
            )
        nested = f"{module}:{spelling}"
        if nested in self.classes:
            return frozenset({nested})
        prefix, _, leaf = spelling.rpartition(".")
        prefix_leaf = prefix.rpartition(".")[2]
        named = self.classes_by_leaf.get(leaf, set())
        targets = self.import_targets.get(module, set())
        in_targets = {
            qualname for qualname in named if qualname.partition(":")[0] in targets
        }
        by_prefix = {
            qualname
            for qualname in (in_targets or named)
            if qualname.partition(":")[0].rpartition(".")[2] == prefix_leaf
        }
        return frozenset(by_prefix or in_targets or named)


def _expose_definitions(population: _Population, expose: _Expose) -> None:
    """E1: defined in a public module."""

    for qualname in sorted(population.definitions):
        module = qualname.partition(":")[0]
        if module in population.public_modules:
            expose(qualname, f"public_module:{module}")


def _expose_package_reexports(population: _Population, expose: _Expose) -> None:
    """E2: imported by name into a public package ``__init__``."""

    for package in sorted(population.public_modules & population.package_modules):
        for target, name in sorted(population.named_imports.get(package, ())):
            if name.startswith("_"):
                continue
            for qualname in sorted(population.resolve_binding(target, name)):
                expose(qualname, f"package_reexport:{package}")


def _star_frontier(population: _Population) -> dict[str, str]:
    """Every module a public module reaches through wildcard edges, hop by
    hop, with the first module whose edge carried it."""

    frontier: set[str] = set(population.public_modules)
    star_source: dict[str, str] = {}
    queue: deque[str] = deque(sorted(population.public_modules))
    while queue:
        source = queue.popleft()
        for target in sorted(population.star_edges.get(source, ())):
            star_source.setdefault(target, source)
            if target not in frontier:
                frontier.add(target)
                queue.append(target)
    return star_source


def _expose_star_chain(
    population: _Population,
    star_source: Mapping[str, str],
    expose: _Expose,
) -> None:
    """E3: carried outward by a wildcard edge from a public module."""

    for target in sorted(star_source):
        source = star_source[target]
        for qualname in sorted(population.definitions_by_module.get(target, ())):
            if "." not in qualname.partition(":")[2] and population.star_bound(
                qualname
            ):
                expose(qualname, f"star_reexport:{source}")
        # A module the wildcard reached re-exports what it imports by name on
        # the same terms; whether its own ``__all__`` narrows that is not on
        # the wire, so the name is carried (the over-approximating direction).
        for dep_target, name in sorted(population.named_imports.get(target, ())):
            if name.startswith("_"):
                continue
            for qualname in sorted(population.resolve_binding(dep_target, name)):
                expose(qualname, f"star_reexport:{target}")


def _expose_nested(
    population: _Population,
    exposed: Mapping[str, str],
    expose: _Expose,
) -> None:
    """A nested definition rides its root: ``pkg.mod.Outer.Inner`` is reached
    through whatever reaches ``Outer``."""

    for qualname in sorted(population.definitions):
        module, _, local = qualname.partition(":")
        if "." in local and qualname not in exposed:
            root_witness = exposed.get(f"{module}:{local.partition('.')[0]}")
            if root_witness is not None:
                expose(qualname, root_witness)


def _exposure(population: _Population) -> tuple[dict[str, str], frozenset[str]]:
    """Every definition on a public path, with the construct that puts it there.

    Rules apply in a fixed order so the witness is deterministic: the direct
    public module, then the package re-export, then the wildcard chain, then
    the roots of nested definitions. Returns the witness map and the modules
    a public module reaches through wildcard edges.
    """

    exposed: dict[str, str] = {}

    def expose(qualname: str, witness: str) -> None:
        if _is_public_path(qualname.partition(":")[2]):
            exposed.setdefault(qualname, witness)

    _expose_definitions(population, expose)
    _expose_package_reexports(population, expose)
    star_source = _star_frontier(population)
    _expose_star_chain(population, star_source, expose)
    _expose_nested(population, exposed, expose)
    return exposed, frozenset(star_source)


def _hierarchy(
    population: _Population,
) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, str]]:
    """Parent and child edges between project classes, plus the classes whose
    base no edge binds (and is neither external per the walk nor a builtin)."""

    parents: dict[str, set[str]] = {}
    children: dict[str, set[str]] = {}
    unresolved_base: dict[str, str] = {}
    for metric in sorted(population.class_metrics, key=lambda item: item.qualname):
        module = metric.qualname.partition(":")[0]
        for spelling in metric.base_names:
            resolved = population.resolve_base(module, spelling)
            if resolved:
                parents.setdefault(metric.qualname, set()).update(resolved)
                for base in resolved:
                    children.setdefault(base, set()).add(metric.qualname)
                continue
            root = spelling.partition(".")[0]
            if (
                metric.qualname in population.external_base_classes
                or root in _BUILTIN_NAMES
            ):
                continue
            unresolved_base.setdefault(metric.qualname, spelling)
    return parents, children, unresolved_base


def _dynamic_namespace(population: _Population, module: str) -> str | None:
    """The construct that makes ``module``'s public path unreadable, if any."""

    for package in population.getattr_packages:
        if module == package or module.startswith(f"{package}."):
            return f"module_getattr:{package}"
    for package in population.lazy_packages:
        if module == package or module.startswith(f"{package}."):
            return f"lazy_namespace:{package}"
    return None


def collect_external_reachability(
    *,
    dead_candidates: Sequence[DeadCandidate],
    module_deps: Sequence[ModuleDep],
    class_metrics: Sequence[ClassMetrics],
    package_modules: frozenset[str],
) -> tuple[ExternalReachability, ...]:
    """One reachability row per candidate, sorted by qualname."""

    population = _Population(
        dead_candidates=dead_candidates,
        module_deps=module_deps,
        class_metrics=class_metrics,
        package_modules=package_modules,
    )
    exposed, _star_reached = _exposure(population)
    parents, children, unresolved_base = _hierarchy(population)

    def type_witness(class_qualname: str) -> str | None:
        if class_qualname in exposed:
            return exposed[class_qualname]
        for descendant in _closure(class_qualname, children):
            if descendant in exposed:
                return f"exposed_subclass:{descendant}"
        return None

    def ancestor_witness(class_qualname: str) -> str | None:
        for ancestor in _closure(class_qualname, parents):
            if ancestor in exposed:
                return f"exposed_ancestor:{ancestor}"
        return None

    def unresolved_witness(module: str, class_qualname: str | None) -> str | None:
        if class_qualname is not None and class_qualname in unresolved_base:
            return f"unresolved_base:{unresolved_base[class_qualname]}"
        return _dynamic_namespace(population, module)

    def row(candidate: DeadCandidate) -> ExternalReachability:
        module, _, local = candidate.qualname.partition(":")
        if not _is_public_path(local):
            return ExternalReachability(candidate.qualname, "not_reachable", "")
        owner: str | None = None
        witness: str | None
        if candidate.kind == "method":
            owner = f"{module}:{local.rpartition('.')[0]}"
            witness = type_witness(owner) or ancestor_witness(owner)
        else:
            witness = exposed.get(candidate.qualname)
        if witness is not None:
            return ExternalReachability(candidate.qualname, "reachable", witness)
        unresolved = unresolved_witness(module, owner)
        if unresolved is not None:
            return ExternalReachability(candidate.qualname, "unresolved", unresolved)
        return ExternalReachability(candidate.qualname, "not_reachable", "")

    return tuple(
        row(candidate)
        for candidate in sorted(dead_candidates, key=lambda item: item.qualname)
    )


def reachability_by_qualname(
    rows: Iterable[ExternalReachability],
) -> dict[str, ExternalReachability]:
    return {row.qualname: row for row in rows}


__all__ = [
    "collect_external_reachability",
    "package_modules_from_registry",
    "reachability_by_qualname",
]
