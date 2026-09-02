# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from ..metrics.dead_code import classify_liveness
from ..models import (
    ClassMetrics,
    DeadCandidate,
    ModuleDep,
    ModuleRegistryHandle,
    RuntimeReachabilityFact,
)
from ..utils.coerce import as_mapping

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class _EntryPointRef:
    module: str
    local: str


def _load_toml_payload(path: Path) -> Mapping[str, object]:
    if not path.exists():
        return {}

    # Treat project metadata as repo-local input; symlink escapes are ignored.
    try:
        resolved = path.resolve()
        resolved.relative_to(path.parent.resolve())
    except (OSError, ValueError):
        return {}

    if sys.version_info >= (3, 11):
        import tomllib

        try:
            with path.open("rb") as config_file:
                payload = tomllib.load(config_file)
        except (OSError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

    try:
        tomli_module = importlib.import_module("tomli")
    except ModuleNotFoundError:
        return {}
    load_fn = getattr(tomli_module, "load", None)
    if not callable(load_fn):
        return {}
    try:
        with path.open("rb") as config_file:
            payload = load_fn(config_file)
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _entrypoint_ref(value: object) -> _EntryPointRef | None:
    if not isinstance(value, str):
        return None
    ref = value.strip().split(maxsplit=1)[0]
    module, separator, local = ref.partition(":")
    if not separator or not module or not local:
        return None
    if not _is_dotted_identifier(module) or not _is_dotted_identifier(local):
        return None
    return _EntryPointRef(module=module, local=local)


def _is_dotted_identifier(value: str) -> bool:
    return all(part.isidentifier() for part in value.split("."))


def _iter_project_entrypoint_refs(
    payload: Mapping[str, object],
) -> Iterable[_EntryPointRef]:
    project = as_mapping(payload.get("project"))
    for table_name in ("scripts", "gui-scripts"):
        for value in as_mapping(project.get(table_name)).values():
            ref = _entrypoint_ref(value)
            if ref is not None:
                yield ref

    for group in as_mapping(project.get("entry-points")).values():
        for value in as_mapping(group).values():
            ref = _entrypoint_ref(value)
            if ref is not None:
                yield ref

    poetry = as_mapping(as_mapping(payload.get("tool")).get("poetry"))
    for value in as_mapping(poetry.get("scripts")).values():
        ref = _entrypoint_ref(value)
        if ref is not None:
            yield ref


def collect_project_entrypoint_qualnames(
    *,
    root: Path,
    dead_candidates: Sequence[DeadCandidate],
) -> frozenset[str]:
    """Resolve package entry points to exact known dead-code candidate qualnames."""
    refs = tuple(
        _iter_project_entrypoint_refs(_load_toml_payload(root / "pyproject.toml"))
    )
    if not refs:
        return frozenset()

    candidate_qualnames = frozenset(candidate.qualname for candidate in dead_candidates)
    resolved: set[str] = set()
    for ref in refs:
        exact = f"{ref.module}:{ref.local}"
        if exact in candidate_qualnames:
            resolved.add(exact)
            continue

        suffix_matches = {
            qualname
            for qualname in candidate_qualnames
            if _matches_entrypoint_suffix(qualname, ref)
        }
        if len(suffix_matches) == 1:
            resolved.update(suffix_matches)

    return frozenset(sorted(resolved))


def already_live_candidate_qualnames(
    *,
    dead_candidates: Sequence[DeadCandidate],
    referenced_names: frozenset[str],
    referenced_qualnames: frozenset[str],
    runtime_reachability: Sequence[RuntimeReachabilityFact] = (),
    class_metrics: Sequence[ClassMetrics] = (),
    module_registry: ModuleRegistryHandle | None = None,
) -> frozenset[str]:
    """Candidates the project holds live WITHOUT any export-root evidence.

    The one population an export root has to be measured against, and it is
    read from the liveness owner rather than restated here. Restating it was
    the defect: the export-root rule excluded a candidate only when its
    QUALNAME was already referenced, while an ordinary ``obj.method()`` call
    reaches the liveness decision as a bare name and never as a qualname. The
    comparison could therefore not match an attribute-called method in any
    configuration, and the rule recorded "live because exported" for symbols a
    call site already held live.

    An abstention is deliberately NOT already-live: a method whose owner
    inherits an opaque external base is neither dead nor live, so an export
    root remains a real contribution there.
    """

    classification = classify_liveness(
        definitions=tuple(dead_candidates),
        referenced_names=referenced_names,
        referenced_qualnames=referenced_qualnames,
        runtime_reachability=tuple(runtime_reachability),
        module_registry=module_registry,
        class_metrics=tuple(class_metrics),
    )
    undecided = {item.qualname for item in classification.dead_items} | {
        item.qualname for item in classification.unresolved_overrides
    }
    return frozenset(
        candidate.qualname
        for candidate in dead_candidates
        if candidate.qualname not in undecided
    )


def collect_project_export_root_qualnames(
    *,
    module_deps: Sequence[ModuleDep],
    referenced_qualnames: frozenset[str],
    dead_candidates: Sequence[DeadCandidate],
    module_registry: ModuleRegistryHandle,
    already_live_qualnames: frozenset[str],
) -> frozenset[str]:
    """Resolve the public methods reached through a package-boundary export."""
    return frozenset(
        qualname
        for qualname, _reason in collect_project_export_root_evidence(
            module_deps=module_deps,
            referenced_qualnames=referenced_qualnames,
            dead_candidates=dead_candidates,
            module_registry=module_registry,
            already_live_qualnames=already_live_qualnames,
        )
    )


def _wildcard_reexported_classes(
    *,
    module_deps: Sequence[ModuleDep],
    reexporting_modules: frozenset[str],
    dead_candidates: Sequence[DeadCandidate],
    referenced_qualnames: frozenset[str],
) -> set[str]:
    """Classes a re-exporter carries out through ``from <target> import *``.

    The sources are the re-export frontier, not only the package ``__init__``
    files on it: a wildcard edge re-exports whatever the next module holds, so
    the chain does not end where the package directory does.

    A wildcard names no symbol, so the named export chain sees only
    ``target:*`` and roots nothing - which is how a package spelled with
    ``import *`` came to assert, with high confidence, that its own public
    methods were dead.

    What such an edge binds is decided by the TARGET, and only by the target:
    a module declaring ``__all__`` binds exactly the names it lists. That fact
    rides each candidate as ``star_import_bound``, because a dependency edge
    names the module and never the symbol, so it cannot answer the question on
    its own. Being referenced is a separate condition and stays a separate
    condition: a name the star does not bind is not carried out no matter who
    else holds it live, which is how a class excluded from its target's
    ``__all__`` used to have its uncalled member rooted as externally
    reachable while ``hasattr(package, name)`` was executably False.

    A repository with no wildcard re-export has no such edge and gets the
    empty set, so this rule cannot move a verdict outside its own class.
    """

    wildcard_targets = {
        dependency.target
        for dependency in module_deps
        if dependency.source in reexporting_modules
        and dependency.target
        and "*" in dependency.requested_names
    }
    return {
        candidate.qualname
        for candidate in dead_candidates
        if candidate.kind == "class"
        and candidate.star_import_bound
        and candidate.qualname.partition(":")[0] in wildcard_targets
        and candidate.qualname in referenced_qualnames
    }


def _reexporting_modules(
    *,
    module_deps: Sequence[ModuleDep],
    package_modules: set[str],
) -> frozenset[str]:
    """The re-export frontier: from the package boundary outward along ``*``.

    A package ``__init__`` re-exports what it imports - the declared Y2 rule.
    ``from <target> import *`` carries the target's whole public namespace, so
    a module the chain reached through such an edge re-exports on exactly the
    same terms, and its own imports carry those names one hop further.

    Stopping at the first non-package hop let the SPELLING of the intermediary
    decide the verdict: a subpackage ``__init__`` kept the export alive, while
    a plain module in the same position left the public method of the same live
    re-exported class asserted dead with high confidence.

    Only a wildcard edge extends the chain. A named import into a plain module
    binds one name for that module's own use; it re-exports only once something
    carries that module's namespace outward, which is the wildcard edge this
    walk follows. A repository whose packages hold no wildcard re-export gets
    ``package_modules`` back unchanged, so this owner cannot move a verdict
    outside the construction it is about.
    """
    wildcard_edges: dict[str, set[str]] = {}
    for dependency in module_deps:
        if dependency.target and "*" in dependency.requested_names:
            wildcard_edges.setdefault(dependency.source, set()).add(dependency.target)
    reached = set(package_modules)
    frontier = sorted(reached)
    while frontier:
        for target in sorted(wildcard_edges.get(frontier.pop(), ())):
            if target not in reached:
                reached.add(target)
                frontier.append(target)
    return frozenset(reached)


def collect_project_export_root_evidence(
    *,
    module_deps: Sequence[ModuleDep],
    referenced_qualnames: frozenset[str],
    dead_candidates: Sequence[DeadCandidate],
    module_registry: ModuleRegistryHandle,
    already_live_qualnames: frozenset[str],
) -> tuple[tuple[str, Literal["export_root"]], ...]:
    """Resolve export roots that nothing upstream already holds live.

    The declared Y2 export rule - ``__all__`` membership plus the package
    ``__init__`` re-export chain - is resolved by the module walk, which binds
    every exported function and class into ``referenced_qualnames``. Emitting
    those qualnames again would be a provable no-op, because the result is
    unioned back into the very set it was drawn from. This owner therefore adds
    only the roots the chain implies but nothing records: the public methods
    reached through a class that the export chain made live.

    "Nothing already holds live" is measured against
    ``already_live_qualnames`` - the liveness owner's own verdict, taken
    before any export root exists - and not against ``referenced_qualnames``,
    which cannot contain an attribute-called method by construction. The
    result is an evidence lane that explains the verdict the tool actually
    reached: a root here is the reason the symbol is live, not a second
    description of a symbol something else already holds.

    The parameter carries no default on purpose. A caller that forgets it
    would silently restore the old, unmatchable comparison, and the rule would
    go on recording roots for symbols it does not root.
    """
    package_modules = {
        module
        for module, entry in module_registry.entries_by_module.rows
        if (
            (identity := entry.identity.python_module) is not None
            and identity.is_package
        )
    }
    reexporting_modules = _reexporting_modules(
        module_deps=module_deps,
        package_modules=package_modules,
    )
    # The export chain is a set of NAMES, not a set of modules: a re-exporting
    # module re-exports the symbols it names in the import (which is also what
    # its ``__all__`` lists). Widening this to "every symbol living in a module
    # some re-exporter imports" would root any class the project happens to
    # reference from anywhere - including one only a sibling module imports.
    #
    # A package ``__init__`` carries every name it imports, underscore included:
    # ``pkg._Private`` genuinely exists after ``from ._x import _Private``. A
    # module the chain merely REACHED carries only what put it on the chain -
    # a wildcard edge, which skips underscore names - so its private imports
    # are filtered out. Measured on ``qutip``: without this split the chain
    # rooted the methods of ``_SolverOptions``, a private class no wildcard
    # ever binds, and silently retired a true finding.
    exported_names = {
        f"{dependency.target}:{name}"
        for dependency in module_deps
        if dependency.source in reexporting_modules and dependency.target
        for name in dependency.requested_names
        if dependency.source in package_modules or not name.startswith("_")
    }
    exported_classes = {
        candidate.qualname
        for candidate in dead_candidates
        if candidate.kind == "class" and candidate.qualname in exported_names
    } | _wildcard_reexported_classes(
        module_deps=module_deps,
        reexporting_modules=reexporting_modules,
        dead_candidates=dead_candidates,
        referenced_qualnames=referenced_qualnames,
    )
    roots: set[str] = set()
    for candidate in dead_candidates:
        if candidate.kind != "method" or candidate.local_name.startswith("_"):
            continue
        owner, separator, _method = candidate.qualname.rpartition(".")
        if (
            separator
            and owner in exported_classes
            and candidate.qualname not in already_live_qualnames
        ):
            roots.add(candidate.qualname)
    return tuple((qualname, "export_root") for qualname in sorted(roots))


def _matches_entrypoint_suffix(qualname: str, ref: _EntryPointRef) -> bool:
    module, separator, local = qualname.partition(":")
    return bool(separator) and local == ref.local and module.endswith(f".{ref.module}")


__all__ = [
    "already_live_candidate_qualnames",
    "collect_project_entrypoint_qualnames",
    "collect_project_export_root_evidence",
    "collect_project_export_root_qualnames",
]
