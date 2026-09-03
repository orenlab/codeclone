# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""External reachability: does a public import path to a symbol exist?

The evidence layer under the dead-code evaluator (RULING 2026-09-01), and the
binding oracle under the api-surface evaluator: the rule is the language's and
the same for both, only the population and the namespaces are the caller's.
One central rule, stated as the language states it and read only from facts
that already ride the cache wire, so a warm run answers exactly as a cold one:

* a name is **publicly bound** in a module when the module defines it, when a
  wildcard import binds it there (``from x import *`` binds what the target's
  ``__all__`` rule says - the ``star_import_bound`` fact on the candidate),
  when a package ``__init__`` imports it by name (PEP 8: the package
  re-exports what it imports), or when a plain module imports it by name AND
  lists it in its own static ``__all__`` (PEP 8: an imported name is API
  exactly where the module documents it as such, and ``__all__`` is that
  documentation - the ``declared_exports`` fact on the wire, liveness policy
  v4); a plain module's undeclared import stays implementation detail;
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
  be read statically: a reachable package with a module-level ``__getattr__``
  (PEP 562 can serve any name below it), a reachable package whose namespace
  ``lazy_loader`` builds from a stub the walk never reads, a reached plain
  module whose ``__getattr__`` serves a name its ``__all__`` declares or a
  name some namespace imports from it by name (nothing static binds it, so
  every top-level definition of that name is what it might serve), or a
  class whose base no edge binds - and whatever such a namespace carries
  outward is unresolved too.

The order is the algorithm, and it is forced (RULING 2026-09-02): the raw
binding graph carries no verdict; the seeds are the namespaces provably
external by construction and they do not depend on the world contract; the
graph is closed to a fixed point in which a namespace is ``reachable``,
``unresolved`` or neither and can only rise; and only after convergence is a
definition's exposure read off the edges whose importer namespace converged.
Whether a package ``__init__`` is an export surface is therefore decided by
the graph, never by its syntax or its privacy alone, and ``unresolved`` is a
front of its own: a plain least fixed point would read everything it never
reached as ``not_reachable``, which is confidence laundering built into the
algorithm.

Everything else is ``not_reachable``. Every rule over-approximates in the
same direction: a name the project could expose is called reachable, never
the reverse, because the failure this layer exists to prevent is a
high-confidence assertion that live public API is dead - or, on the api lane,
a gate that goes confidently silent where its data is insufficient.

The population is whatever definitions the caller hands in: the dead-code
evaluator passes the walk's candidates, the api-surface evaluator passes the
same candidates plus its public symbols (a module-level constant is never a
candidate and is api surface), and both are read through the four facts
every definition carries. The namespaces are the caller's too. By default a
module is a public namespace when the language says so, which is the
dead-code evaluator's open world; the api evaluator names the product's
public paths instead, because a public-named module of an unshipped tree or
of the test track is a Python module and not a place the project promises a
name at.

What is deliberately NOT decided here: ``__all__`` as a language beyond the
two facts the walk already resolved - the star binding and the declared
names - so a dynamic, concatenated or imported ``__all__`` reads as the
literal part it has and an absent one as nothing; the liveness question
itself; and what counts as a namespace. Reachability is evidence; the evaluator in
:mod:`codeclone.metrics.dead_code` combines it with liveness evidence and the
world contract, and :mod:`codeclone.metrics.api_population` combines it with
the surface kind.
"""

from __future__ import annotations

import builtins
from collections import deque
from typing import TYPE_CHECKING, Final

from ..models import ExternalReachability, ReachabilityState

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence
    from typing import Protocol

    from ..models import ClassMetrics, ModuleDep, ModuleRegistryHandle

    #: The one seam every exposure rule writes through: qualname, rank, witness.
    _Expose = Callable[[str, int, str], None]

    class _Definition(Protocol):
        """The four facts every exposure rule reads off a definition.

        ``DeadCandidate`` carries them as it rides the cache wire;
        ``SymbolDefinition`` is the shape a caller adapts anything else into.
        A rule that needed a fifth fact would be a rule one population could
        not answer, so none may.
        """

        @property
        def qualname(self) -> str: ...

        @property
        def local_name(self) -> str: ...

        @property
        def kind(self) -> str: ...

        @property
        def star_import_bound(self) -> bool: ...


#: A base spelled as a builtin (``Exception``, ``dict``) binds outside the
#: project without an import edge; it is resolved, not unresolved.
_BUILTIN_NAMES: Final = frozenset(dir(builtins))
#: Bound on the named-binding walk: a re-export chain deeper than this is not
#: a package facade, and the walk must terminate on any input.
_BINDING_HOPS: Final = 32
#: The three states, ordered: a proven path beats an unreadable one, which
#: beats none. Ranks only rise during the fixed point, which is what makes it
#: one, and what keeps the answer independent of the order edges are read in.
_NOT_REACHED: Final = 0
_UNRESOLVED: Final = 1
_REACHABLE: Final = 2
_STATE_OF_RANK: Final[dict[int, ReachabilityState]] = {
    _UNRESOLVED: "unresolved",
    _REACHABLE: "reachable",
}


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


def _is_public_path(local: str, public_leaves: frozenset[str] = frozenset()) -> bool:
    """The underscore rule over a local path, except a leaf the caller's
    population calls public: a protocol dunder method (``__init__``,
    ``__call__``) is dispatched to from outside its class by the language, so
    an api population counts its signature as the class's contract. The
    default is the plain rule, which is the dead-code evaluator's reading."""

    if not local:
        return False
    *owners, leaf = local.split(".")
    if any(segment.startswith("_") for segment in owners):
        return False
    return not leaf.startswith("_") or leaf in public_leaves


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
    definitions_in: Sequence[_Definition],
    class_metrics: Sequence[ClassMetrics],
) -> tuple[
    set[str],
    set[str],
    dict[str, set[str]],
    dict[str, set[str]],
    dict[str, set[str]],
]:
    """Project classes and module-level definitions, by module, by class leaf
    and - top-level definitions only - by local name."""

    classes = {metric.qualname for metric in class_metrics} | {
        definition.qualname
        for definition in definitions_in
        if definition.kind == "class"
    }
    definitions = set(classes) | {
        definition.qualname
        for definition in definitions_in
        if definition.kind != "method"
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
    # What a name served through a module-level ``__getattr__`` might be: a
    # top-level definition of that name, anywhere. Nested definitions are
    # reached through their root and are not what ``<module>.<name>`` serves.
    definitions_by_name: dict[str, set[str]] = {}
    for qualname in definitions:
        local = qualname.partition(":")[2]
        if "." not in local:
            definitions_by_name.setdefault(local, set()).add(qualname)
    return (
        classes,
        definitions,
        definitions_by_module,
        classes_by_leaf,
        definitions_by_name,
    )


def _dynamic_packages(
    definitions: Sequence[_Definition],
    *,
    package_modules: frozenset[str],
    import_targets: Mapping[str, set[str]],
) -> dict[str, str]:
    """Packages whose namespace no static read can settle, with the witness.

    A module-level ``def __getattr__`` (PEP 562) can serve any name below the
    package. ``import lazy_loader`` in a package ``__init__`` is the one wired
    trace of ``(__getattr__, __dir__, __all__) = lazy.attach_stub(...)``: the
    names it serves live in a ``.pyi`` stub the walk never reads, so that
    namespace is as dynamic as a spelled-out ``__getattr__``. Measured on
    mne-python: without the second rule ten documented ``Brain`` methods read
    as high-confidence dead under the open world.

    This is an input to the graph, not a verdict: a dynamic package marks what
    sits below it only once the fixed point has reached the package itself.
    """

    dynamic: dict[str, str] = {}
    for package in sorted(package_modules):
        if "lazy_loader" in import_targets.get(package, set()):
            dynamic[package] = f"lazy_namespace:{package}"
    for definition in definitions:
        package = definition.qualname.partition(":")[0]
        if (
            definition.kind == "function"
            and definition.local_name == "__getattr__"
            and package in package_modules
        ):
            dynamic[package] = f"module_getattr:{package}"
    return dynamic


def _dynamic_modules(
    definitions: Sequence[_Definition],
    *,
    package_modules: frozenset[str],
) -> dict[str, str]:
    """Plain modules whose namespace a module-level ``__getattr__`` extends.

    The package rule above marks a whole subtree, because that is what a
    package's ``__getattr__`` characteristically serves. A plain module has
    no subtree, so its handle is the NAMES: what its ``__all__`` declares
    (the declared-dynamic rule) and what a namespace imports from it by name
    (the binding walk's dynamic hop). Neither binding can be read, and both
    are exposed as unresolved - never as dead.
    """

    dynamic: dict[str, str] = {}
    for definition in definitions:
        module, _, local = definition.qualname.partition(":")
        if (
            definition.kind == "function"
            and local == "__getattr__"
            and module not in package_modules
        ):
            dynamic[module] = f"module_getattr:{module}"
    return dynamic


class _Population:
    """The wired facts, indexed once; every rule below reads only these."""

    def __init__(
        self,
        *,
        definitions: Sequence[_Definition],
        module_deps: Sequence[ModuleDep],
        class_metrics: Sequence[ClassMetrics],
        package_modules: frozenset[str],
        public_modules: frozenset[str] | None,
        public_leaves: frozenset[str],
        declared_exports: Iterable[str],
    ) -> None:
        self.public_leaves = public_leaves
        # Two populations may name one definition (a class is both a walk
        # candidate and a public symbol); the star-binding fact is the same
        # language rule read by both, and a name either calls bound is bound -
        # the over-approximating direction, and order-independent.
        self.star_bound_qualnames = frozenset(
            definition.qualname
            for definition in definitions
            if definition.star_import_bound
        )
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
            self.definitions_by_name,
        ) = _index_definitions(definitions, class_metrics)
        modules |= set(package_modules)
        modules.update(
            qualname.partition(":")[0]
            for qualname in (*self.definitions, *self.classes)
        )
        self.modules = frozenset(modules)
        # The namespaces are the caller's: absent a set, the language's own
        # privacy rule over every module the facts name.
        self.public_modules = (
            frozenset(module for module in modules if _is_public_module(module))
            if public_modules is None
            else public_modules
        )
        self.package_modules = package_modules
        self.external_base_classes = frozenset(
            metric.qualname
            for metric in class_metrics
            if metric.has_unresolved_external_base
        )
        self.class_metrics = tuple(class_metrics)
        self.dynamic_packages = _dynamic_packages(
            definitions,
            package_modules=package_modules,
            import_targets=self.import_targets,
        )
        self.dynamic_modules = _dynamic_modules(
            definitions,
            package_modules=package_modules,
        )
        # The declaration fact by declaring module (liveness policy v4): the
        # names a static ``__all__`` lists, read for a plain module's
        # re-exports and for what a dynamic plain module serves. A package
        # needs no declaration to re-export (E2), so it is never read here.
        declared: dict[str, set[str]] = {}
        for entry in declared_exports:
            module, separator, name = entry.partition(":")
            if separator and module and name:
                declared.setdefault(module, set()).add(name)
        self.declared_exports: dict[str, frozenset[str]] = {
            module: frozenset(names) for module, names in declared.items()
        }

    def star_bound(self, qualname: str) -> bool:
        return qualname in self.star_bound_qualnames

    def resolve_binding(
        self,
        module: str,
        name: str,
        *,
        dynamic: list[str] | None = None,
    ) -> frozenset[str]:
        """The definitions ``<module>.<name>`` binds, by CPython's rules.

        A local definition wins; otherwise the name was imported - by name
        from one module, which is followed, or by a wildcard, which binds the
        target's definition only when the target's ``__all__`` rule says so.

        A hop that lands on a plain module with a module-level ``__getattr__``
        and finds nothing static to follow is a binding the walk cannot read:
        the module serves the name at runtime (PEP 562) or not at all. That
        construct's witness is appended to ``dynamic`` when the caller offers
        one, so the caller can expose what the name might be as unresolved;
        the walk never guesses a definition on the caller's behalf.
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
            followed = False
            for target, imported in sorted(self.named_imports.get(current, ())):
                if imported == local:
                    stack.append((target, local, depth + 1))
                    followed = True
            for target in sorted(self.star_edges.get(current, ())):
                star_qualname = f"{target}:{local}"
                if star_qualname in self.definitions:
                    if self.star_bound(star_qualname):
                        found.add(star_qualname)
                        followed = True
                else:
                    stack.append((target, local, depth + 1))
                    followed = True
            if not followed and dynamic is not None:
                served_by = self.dynamic_modules.get(current)
                if served_by is not None:
                    dynamic.append(served_by)
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


class _Namespaces:
    """The fixed point: every namespace's rank, and how it got there.

    ``path`` holds the seeds - the public paths a caller can spell by
    construction. ``star`` holds every module a wildcard edge carried, with
    the rank of the namespace that carried it and, for a proven carry, the
    first module whose edge did (deterministic: seeds in sorted order, then
    breadth-first). ``dynamic`` holds every module under a dynamic package
    the fixed point reached, with that package's witness. A rank only rises,
    so the closure is order-independent and terminates.
    """

    def __init__(self, population: _Population) -> None:
        self.rank: dict[str, int] = {}
        self.star: dict[str, tuple[int, str]] = {}
        self.dynamic: dict[str, str] = {}
        self._population = population
        # Two fronts, drained proven-first: a namespace the proven front
        # reaches later is upgraded, and its witness is then the first proven
        # carrier, exactly as a single proven walk would have recorded it.
        self._fronts: dict[int, deque[str]] = {
            _REACHABLE: deque(),
            _UNRESOLVED: deque(),
        }
        for module in sorted(population.public_modules):
            self._raise(module, _REACHABLE)
        self._close()

    def _raise(self, module: str, rank: int) -> None:
        if self.rank.get(module, _NOT_REACHED) < rank:
            self.rank[module] = rank
            self._fronts[rank].append(module)

    def _pop(self) -> str | None:
        for rank in (_REACHABLE, _UNRESOLVED):
            if self._fronts[rank]:
                return self._fronts[rank].popleft()
        return None

    def _close(self) -> None:
        population = self._population
        while (module := self._pop()) is not None:
            rank = self.rank[module]
            for target in sorted(population.star_edges.get(module, ())):
                if self.star.get(target, (_NOT_REACHED, ""))[0] < rank:
                    self.star[target] = (rank, self._carry_witness(module, rank))
                    self._raise(target, rank)
            witness = population.dynamic_packages.get(module)
            if witness is None:
                continue
            for below in sorted(population.modules):
                if below != module and not below.startswith(f"{module}."):
                    continue
                if below not in self.dynamic:
                    self.dynamic[below] = witness
                    self._raise(below, _UNRESOLVED)

    def _carry_witness(self, module: str, rank: int) -> str:
        """What a wildcard edge from ``module`` stamps on its target: the
        proven carrier, or the construct that left ``module`` unreadable -
        its own dynamic package, or the unreadable carrier that reached it."""

        if rank == _REACHABLE:
            return f"star_reexport:{module}"
        dynamic = self.dynamic.get(module)
        if dynamic is not None:
            return dynamic
        # The only other way a rank is raised to unresolved is a wildcard
        # from an unreadable namespace; the carrier's own witness travels on.
        return self.star[module][1]

    def unresolved_witness(self, module: str) -> str | None:
        """Why every definition in ``module`` is unreadable, if it is: the
        module sits under a dynamic package the fixed point reached.

        A wildcard that reached the module at the unresolved rank is NOT
        that: it carries the module's star-bound names and nothing else,
        exactly as a proven wildcard does, and those names are stamped one
        by one by the chain rule. Reading the whole module as unresolved
        here would turn a name ``import *`` never binds into API.
        """

        return self.dynamic.get(module)


def _expose_binding(
    population: _Population,
    *,
    target: str,
    name: str,
    rank: int,
    witness: str,
    expose: _Expose,
) -> None:
    """Expose what ``<target>.<name>`` binds, at ``rank`` through ``witness``.

    A hop through a plain module's ``__getattr__`` binds unreadably: every
    top-level definition of that name is what it might serve, so each is
    exposed as unresolved with that module as the witness - the direction
    that never asserts a served symbol dead, and never proves one reachable.
    """

    served: list[str] = []
    for qualname in sorted(population.resolve_binding(target, name, dynamic=served)):
        expose(qualname, rank, witness)
    for construct in sorted(set(served)):
        for qualname in sorted(population.definitions_by_name.get(name, ())):
            expose(qualname, _UNRESOLVED, construct)


def _expose_definitions(
    population: _Population, namespaces: _Namespaces, expose: _Expose
) -> None:
    """E1: defined in a public path."""

    for qualname in sorted(population.definitions):
        module = qualname.partition(":")[0]
        if module in population.public_modules:
            expose(qualname, _REACHABLE, f"public_module:{module}")


def _expose_package_reexports(
    population: _Population, namespaces: _Namespaces, expose: _Expose
) -> None:
    """E2: imported by name into a package ``__init__`` whose namespace the
    fixed point reached - a public path, or a package a dynamic namespace
    could serve. Which of the two it is decides the rank, not the syntax."""

    for package in sorted(population.package_modules):
        if package in population.public_modules:
            rank, witness = _REACHABLE, f"package_reexport:{package}"
        elif package in namespaces.dynamic:
            rank, witness = _UNRESOLVED, namespaces.dynamic[package]
        else:
            continue
        for target, name in sorted(population.named_imports.get(package, ())):
            if name.startswith("_"):
                continue
            _expose_binding(
                population,
                target=target,
                name=name,
                rank=rank,
                witness=witness,
                expose=expose,
            )


def _expose_declared_reexports(
    population: _Population, namespaces: _Namespaces, expose: _Expose
) -> None:
    """E2': imported by name into a plain module whose own static ``__all__``
    lists the name (liveness policy v4).

    PEP 8 makes an imported name API exactly where the module documents it
    as such, and ``__all__`` is that documentation - the one construct that
    turns a plain module's import from implementation detail into a public
    re-export. Rank as E2: a public path, or a module a dynamic package could
    serve. A package needs no declaration (E2), and a plain module a wildcard
    reached is carried by E3 whatever it declares.
    """

    for module in sorted(population.declared_exports):
        if module in population.package_modules:
            continue
        if module in population.public_modules:
            rank, witness = _REACHABLE, f"declared_reexport:{module}"
        elif module in namespaces.dynamic:
            rank, witness = _UNRESOLVED, namespaces.dynamic[module]
        else:
            continue
        declared = population.declared_exports[module]
        for target, name in sorted(population.named_imports.get(module, ())):
            if name.startswith("_") or name not in declared:
                continue
            _expose_binding(
                population,
                target=target,
                name=name,
                rank=rank,
                witness=witness,
                expose=expose,
            )


def _expose_star_chain(
    population: _Population, namespaces: _Namespaces, expose: _Expose
) -> None:
    """E3: carried outward by a wildcard edge from a namespace the fixed
    point reached, at that namespace's rank."""

    for target in sorted(namespaces.star):
        rank, witness = namespaces.star[target]
        for qualname in sorted(population.definitions_by_module.get(target, ())):
            if "." not in qualname.partition(":")[2] and population.star_bound(
                qualname
            ):
                expose(qualname, rank, witness)
        # A module the wildcard reached re-exports what it imports by name on
        # the same terms; whether its own ``__all__`` narrows that is not on
        # the wire, so the name is carried (the over-approximating direction).
        carried = f"star_reexport:{target}" if rank == _REACHABLE else witness
        for dep_target, name in sorted(population.named_imports.get(target, ())):
            if name.startswith("_"):
                continue
            _expose_binding(
                population,
                target=dep_target,
                name=name,
                rank=rank,
                witness=carried,
                expose=expose,
            )


def _expose_declared_dynamic(
    population: _Population, namespaces: _Namespaces, expose: _Expose
) -> None:
    """E4: declared by a reached plain module and served by its ``__getattr__``.

    The module lists the name in its static ``__all__`` and binds it neither
    by definition, by import nor by wildcard, so its module-level
    ``__getattr__`` is what ``from <module> import *`` and ``<module>.<name>``
    reach. Which definition it serves cannot be read, so every top-level
    definition of that name is unresolved through that construct - at that
    rank whatever the module's own, because a proven path to an unreadable
    binding is unresolved, never proven. An unreached module serves nobody,
    and an undeclared name is not a handle this layer has: the declaration
    is what bounds the served set.
    """

    for module in sorted(population.dynamic_modules):
        if namespaces.rank.get(module, _NOT_REACHED) == _NOT_REACHED:
            continue
        witness = population.dynamic_modules[module]
        for name in sorted(population.declared_exports.get(module, ())):
            if name.startswith("_") or population.resolve_binding(module, name):
                continue
            for qualname in sorted(population.definitions_by_name.get(name, ())):
                expose(qualname, _UNRESOLVED, witness)


def _expose_nested(
    population: _Population,
    exposed: Mapping[str, tuple[int, str]],
    expose: _Expose,
) -> None:
    """A nested definition rides its root: ``pkg.mod.Outer.Inner`` is reached
    through whatever reaches ``Outer``."""

    for qualname in sorted(population.definitions):
        module, _, local = qualname.partition(":")
        if "." in local and qualname not in exposed:
            root = exposed.get(f"{module}:{local.partition('.')[0]}")
            if root is not None:
                expose(qualname, *root)


def _exposure(
    population: _Population, namespaces: _Namespaces
) -> dict[str, tuple[int, str]]:
    """Every definition a converged namespace exposes, with its rank and the
    construct that puts it there.

    Read only after the fixed point, in a fixed order so the witness is
    deterministic: the direct public path, then the package re-export, then
    the declared re-export of a plain module, then the wildcard chain, then
    the declared names a plain module's ``__getattr__`` serves, then the
    roots of nested definitions. A higher rank replaces a lower one; at
    equal rank the first construct stands.
    """

    exposed: dict[str, tuple[int, str]] = {}

    def expose(qualname: str, rank: int, witness: str) -> None:
        if not _is_public_path(qualname.partition(":")[2], population.public_leaves):
            return
        if exposed.get(qualname, (_NOT_REACHED, ""))[0] < rank:
            exposed[qualname] = (rank, witness)

    _expose_definitions(population, namespaces, expose)
    _expose_package_reexports(population, namespaces, expose)
    _expose_declared_reexports(population, namespaces, expose)
    _expose_star_chain(population, namespaces, expose)
    _expose_declared_dynamic(population, namespaces, expose)
    _expose_nested(population, exposed, expose)
    return exposed


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


def _best(candidates: Iterable[tuple[int, str]]) -> tuple[int, str] | None:
    """The highest rank, and at equal rank the first construct offered."""

    best: tuple[int, str] | None = None
    for candidate in candidates:
        if best is None or candidate[0] > best[0]:
            best = candidate
    return best


def collect_external_reachability(
    *,
    definitions: Sequence[_Definition],
    module_deps: Sequence[ModuleDep],
    class_metrics: Sequence[ClassMetrics],
    package_modules: frozenset[str],
    public_modules: frozenset[str] | None = None,
    public_leaves: frozenset[str] = frozenset(),
    declared_exports: Iterable[str] = (),
) -> tuple[ExternalReachability, ...]:
    """One reachability row per definition, sorted by qualname.

    ``definitions`` is the binding universe and the population answered for,
    in one: a name is found by a re-export only if it is defined here, and
    every definition given gets a row. A qualname two callers both hand in
    gets one row, from the first definition that named it. ``public_modules``
    is the seed set; ``None`` derives the language's privacy rule over every
    module the facts name. Seeds are world-invariant: a world contract may
    refuse exposure as a basis for liveness, it never empties them.
    ``public_leaves`` names the underscore leaves the caller's population
    calls public - the protocol dunder methods an api collector admits - and
    is empty under the plain rule. ``declared_exports`` is the walk's
    declaration fact, ``<module>:<name>`` for every name a module's static
    ``__all__`` lists (liveness policy v4); a caller with none passes none,
    and no plain module then re-exports or serves anything by declaration.
    """

    population = _Population(
        definitions=definitions,
        module_deps=module_deps,
        class_metrics=class_metrics,
        package_modules=package_modules,
        public_modules=public_modules,
        public_leaves=public_leaves,
        declared_exports=declared_exports,
    )
    namespaces = _Namespaces(population)
    exposed = _exposure(population, namespaces)
    parents, children, unresolved_base = _hierarchy(population)

    def type_witness(class_qualname: str) -> tuple[int, str] | None:
        own = exposed.get(class_qualname)
        if own is not None and own[0] == _REACHABLE:
            return own
        through_subclass = _best(
            (rank, f"exposed_subclass:{descendant}")
            for descendant in _closure(class_qualname, children)
            if (rank := exposed.get(descendant, (_NOT_REACHED, ""))[0])
        )
        return _best(item for item in (own, through_subclass) if item is not None)

    def ancestor_witness(class_qualname: str) -> tuple[int, str] | None:
        return _best(
            (rank, f"exposed_ancestor:{ancestor}")
            for ancestor in _closure(class_qualname, parents)
            if (rank := exposed.get(ancestor, (_NOT_REACHED, ""))[0])
        )

    def row(definition: _Definition) -> ExternalReachability:
        module, _, local = definition.qualname.partition(":")
        qualname = definition.qualname
        if not _is_public_path(local, population.public_leaves):
            return ExternalReachability(qualname, "not_reachable", "")
        owner: str | None = None
        if definition.kind == "method":
            owner = f"{module}:{local.rpartition('.')[0]}"
            found = _best(
                item
                for item in (type_witness(owner), ancestor_witness(owner))
                if item is not None
            )
        else:
            found = exposed.get(qualname)
        if found is not None and found[0] == _REACHABLE:
            return ExternalReachability(qualname, "reachable", found[1])
        if owner is not None and owner in unresolved_base:
            witness = f"unresolved_base:{unresolved_base[owner]}"
            return ExternalReachability(qualname, "unresolved", witness)
        if found is not None:
            return ExternalReachability(qualname, _STATE_OF_RANK[found[0]], found[1])
        unresolved = namespaces.unresolved_witness(module)
        if unresolved is not None:
            return ExternalReachability(qualname, "unresolved", unresolved)
        return ExternalReachability(qualname, "not_reachable", "")

    subjects: dict[str, _Definition] = {}
    for definition in definitions:
        subjects.setdefault(definition.qualname, definition)
    return tuple(row(subjects[qualname]) for qualname in sorted(subjects))


def reachability_by_qualname(
    rows: Iterable[ExternalReachability],
) -> dict[str, ExternalReachability]:
    return {row.qualname: row for row in rows}


__all__ = [
    "collect_external_reachability",
    "package_modules_from_registry",
    "reachability_by_qualname",
]
