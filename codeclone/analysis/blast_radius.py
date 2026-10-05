# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Neutral blast-radius computation over the facts of one run.

The computation reads a :class:`~codeclone.canonical.blast_radius_facts.
BlastRadiusFacts` carrier and nothing else of the run.  The carrier has two
sources: :func:`blast_radius_facts` reads it off a canonical report document
(the parent's memory), and the run store's projection reads it off a stored
run (consumer migration C7).  :func:`compute_blast_radius` is the document
road kept whole: the carrier of the document, computed.

A file is matched to the import edges by the module the run's module
identity names for it (:func:`file_module`), on both roads -- the identity
that named the edges' endpoints.  ``src/pkg/core.py`` is ``pkg.core``; its
path's spelling, ``src.pkg.core``, is a module no edge names.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from ..canonical.blast_radius_facts import BlastRadiusFacts
from ..paths.workspace import FORBIDDEN_WORKSPACE_GLOBS
from ..utils.coerce import as_mapping as _as_mapping
from ..utils.coerce import as_sequence as _as_sequence
from ..utils.finding_groups import (
    iter_published_group_lists as _iter_published_group_lists,
)
from ..utils.mapping_paths import sections
from ..utils.suppressed_clone_groups import (
    suppressed_clone_container as _suppressed_clone_container,
)
from ..utils.suppressed_clone_groups import (
    suppressed_clone_groups_in as _suppressed_clone_groups_in,
)

BlastRadiusDepth = Literal["direct", "transitive"]

BOUNDARY_REASON_BASELINE_OR_STATE: Final = (
    "baseline, CodeClone state/cache, and generated artifacts "
    "require explicit separate changes"
)
BOUNDARY_REASON_EXPLICIT_FORBIDDEN: Final = "declared forbidden path"
REVIEW_REASON_KNOWN_BASELINE_DEBT: Final = "known baseline debt outside declared origin"
REVIEW_REASON_GOLDEN_FIXTURE_SURFACE: Final = "golden fixture clone suppression surface"
REVIEW_REASON_SECURITY_BOUNDARY: Final = "report-only security boundary inventory"
REVIEW_REASON_REPORT_ONLY_DESIGN: Final = "report-only design signal"
REVIEW_REASON_DYNAMIC_FRONTIER: Final = (
    "import frontier under-approximated at an opaque dynamic load"
)
BOUNDARY_REASON_AFFECTED_NOT_ALLOWED: Final = (
    "affected by blast radius but outside declared edit scope"
)

GUARDRAIL_REVIEW_DEPENDENTS: Final = (
    "review direct dependents before editing public behavior"
)
GUARDRAIL_CLONE_COHORT_CONTEXT: Final = (
    "treat clone cohort members as comparison context, not automatic edit targets"
)
GUARDRAIL_HIGH_RADIUS_APPROVAL: Final = (
    "high blast radius requires explicit human scope approval"
)
GUARDRAIL_DO_NOT_TOUCH_APPROVAL: Final = (
    "do-not-touch paths require separate explicit approval"
)

DEFAULT_DO_NOT_TOUCH_PATTERNS: Final[tuple[str, ...]] = (
    "codeclone.baseline.json",
    *FORBIDDEN_WORKSPACE_GLOBS,
)
MAX_CONTEXT_ITEMS: Final[int] = 20


@dataclass(frozen=True, slots=True)
class BlastRadiusResult:
    run_id: str
    origin: tuple[str, ...]
    depth: BlastRadiusDepth
    radius_level: str
    direct_dependents: tuple[str, ...]
    transitive_dependents: tuple[str, ...]
    clone_cohort_members: tuple[str, ...]
    in_dependency_cycle: tuple[str, ...]
    structural_risk: dict[str, list[str]]
    do_not_touch: tuple[dict[str, str], ...]
    review_context: tuple[dict[str, str], ...]
    guardrails: tuple[str, ...]


def _as_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


def _normalize_relative_path(path: object) -> str:
    """Normalize a document-derived path value; non-strings are not paths.

    ``None`` and other non-string values collapse to the empty skip
    sentinel every caller already handles — ``str(None)`` would leak the
    truthy literal ``"None"`` into path logic.
    """

    if not isinstance(path, str):
        return ""
    text = path.replace("\\", "/").strip()
    if text == ".":
        return ""
    if text.startswith("./"):
        text = text[2:]
    return text.rstrip("/")


def document_file_modules(
    report_document: Mapping[str, object],
) -> tuple[tuple[str, str], ...]:
    """The run's module identity, off a report document's module registry.

    Every ``(path, module)`` pair of ``source_facts.module_registry``
    (``entries_by_path``), sorted by path: the same pairs the run store holds
    as its FILE-MODULE relation (``core.canonical_snapshot._identity_index``),
    and the identity that named the endpoints of the run's import edges.  A
    file the identity gave no module -- not Python, outside every import
    mount, a name no import can spell -- is absent, never named by its path;
    a document without a registry has no pairs.  A served projection
    withholds ``source_facts`` and refuses the read: it carries these pairs
    lifted (``api.served_projection.ServingAnalysisContract.file_modules``).
    """

    source_facts = _as_mapping(report_document.get("source_facts"))
    registry = _as_mapping(source_facts.get("module_registry"))
    entries = _as_mapping(registry.get("entries_by_path"))
    return tuple(
        sorted(
            {
                pair
                for row in _as_sequence(entries.get("rows"))
                if (pair := _registry_pair(row)) is not None
            }
        )
    )


def _registry_pair(row: object) -> tuple[str, str] | None:
    """One ``[path, entry]`` registry row as ``(path, module)``, or ``None``
    when its identity names no module."""
    pair = _as_sequence(row)
    if len(pair) != 2:
        return None
    identity = _as_mapping(_as_mapping(pair[1]).get("identity"))
    path = _as_mapping(identity.get("file")).get("path")
    module = _as_mapping(identity.get("python_module")).get("module")
    if isinstance(path, str) and path and isinstance(module, str) and module:
        return path, module
    return None


def module_index(
    file_modules: Sequence[tuple[str, str]],
) -> tuple[dict[str, str], dict[str, str]]:
    """The run's module identity, both ways: each file's module, and each
    module's file (the first by path, should a module ever name two).

    ``file_modules`` is the identity's own ``(path, module)`` relation (the
    carrier's ``file_modules``): the identity that named the endpoints of the
    run's import edges.  Nothing here derives a module from a path's
    spelling -- ``src/pkg/core.py`` is ``pkg.core`` because the identity says
    so, and a file the identity names no module has none.
    """

    module_of = dict(file_modules)
    file_of: dict[str, str] = {}
    for path, module in sorted(file_modules):
        file_of.setdefault(module, path)
    return module_of, file_of


def file_module(path: str, module_of: Mapping[str, str]) -> str | None:
    """The module the run's module identity names for one requested path.

    A file stands for its own module.  A directory stands for its regular
    package: the module of its ``__init__.py`` (a declared directory tree,
    ``pkg/``, reaches the computation as ``pkg``).  Anything else -- a file
    that is not Python, outside every import mount, unknown to the run, or a
    namespace package's directory, which has no file to name -- has no
    module: ``None``, never a name made from the path.
    """

    normalized = _normalize_relative_path(path)
    if not normalized:
        return None
    module = module_of.get(normalized)
    if module is None:
        module = module_of.get(f"{normalized}/__init__.py")
    return module


# Path honesty: there is deliberately no module-to-candidate-path helper
# here. A module the run's identity cannot place keeps its dotted identity;
# ``module.replace(".", "/") + ".py"`` was the phantom-path bug (a package
# module projected to a file that does not exist). The single projection
# owner is ``codeclone.paths.module_identity.projection``.


def _dedupe_sorted(values: Sequence[str] | set[str]) -> tuple[str, ...]:
    return tuple(sorted({value for value in values if value}))


def _item_path(item: Mapping[str, object]) -> str:
    for key in ("relative_path", "path", "filepath", "file"):
        value = _normalize_relative_path(item.get(key, ""))
        if value:
            return value
    return ""


def _module_to_output(module: str, file_of: Mapping[str, str]) -> str:
    """A dependent as the answer names it: its file, or the endpoint itself
    -- the edges spell a file the identity names no module by its path."""
    return file_of.get(module, module)


def _build_reverse_import_graph(
    edges: Sequence[tuple[str, str]],
) -> dict[str, set[str]]:
    reverse: dict[str, set[str]] = {}
    for source, target in edges:
        reverse.setdefault(target, set()).add(source)
    return reverse


def _dependency_edges(
    report_document: Mapping[str, object],
) -> tuple[Mapping[str, object], ...]:
    metrics = _as_mapping(report_document.get("metrics"))
    families = _as_mapping(metrics.get("families"))
    dependencies = _as_mapping(families.get("dependencies"))
    return tuple(_as_mapping(item) for item in _as_sequence(dependencies.get("items")))


def _edge_pairs(
    edges: Sequence[Mapping[str, object]],
) -> tuple[tuple[str, str], ...]:
    """The ``(source, target)`` import edges, both ends named, sorted unique."""
    pairs = {
        (str(edge.get("source", "")).strip(), str(edge.get("target", "")).strip())
        for edge in edges
    }
    return tuple(
        sorted((source, target) for source, target in pairs if source and target)
    )


def _opaque_dynamic_load_paths(
    report_document: Mapping[str, object],
) -> tuple[str, ...]:
    """Files holding a dynamic load whose argument stayed opaque.

    Read straight from the document's own section; the frontier's
    under-approximation is decided once, upstream, never recomputed here.
    """

    metrics = _as_mapping(report_document.get("metrics"))
    families = _as_mapping(metrics.get("families"))
    dependencies = _as_mapping(families.get("dependencies"))
    paths: set[str] = set()
    for raw in _as_sequence(dependencies.get("dynamic_boundaries")):
        site = _as_mapping(raw)
        source = _as_mapping(site.get("source"))
        path = _normalize_relative_path(_as_mapping(source.get("file")).get("path"))
        if path:
            paths.add(path)
    return tuple(sorted(paths))


def _dependency_cycles(
    report_document: Mapping[str, object],
) -> tuple[tuple[str, ...], ...]:
    metrics = _as_mapping(report_document.get("metrics"))
    families = _as_mapping(metrics.get("families"))
    dependencies = _as_mapping(families.get("dependencies"))
    cycles: list[tuple[str, ...]] = []
    for raw_cycle in _as_sequence(dependencies.get("cycles")):
        cycle = tuple(
            str(module).strip()
            for module in _as_sequence(raw_cycle)
            if str(module).strip()
        )
        if cycle:
            cycles.append(cycle)
    return tuple(sorted(cycles, key=lambda item: (len(item), item)))


def _compute_direct_dependents(
    *,
    origin_modules: Sequence[str],
    reverse_graph: Mapping[str, set[str]],
) -> tuple[str, ...]:
    dependents: set[str] = set()
    for module in origin_modules:
        dependents.update(reverse_graph.get(module, set()))
    return _dedupe_sorted(dependents)


def _compute_transitive_dependents(
    *,
    origin_modules: Sequence[str],
    reverse_graph: Mapping[str, set[str]],
) -> tuple[str, ...]:
    seen: set[str] = set()
    queue: deque[str] = deque(origin_modules)
    origin_set = set(origin_modules)
    while queue:
        current = queue.popleft()
        for dependent in sorted(reverse_graph.get(current, set())):
            if dependent in seen or dependent in origin_set:
                continue
            seen.add(dependent)
            queue.append(dependent)
    return _dedupe_sorted(seen)


def _clone_group_buckets(
    report_document: Mapping[str, object],
) -> tuple[Mapping[str, object], ...]:
    findings = _as_mapping(report_document.get("findings"))
    groups = _as_mapping(findings.get("groups"))
    clones = _as_mapping(groups.get("clones"))
    buckets: list[Mapping[str, object]] = []
    for bucket_name in ("functions", "blocks", "segments"):
        buckets.extend(
            _as_mapping(item) for item in _as_sequence(clones.get(bucket_name))
        )
    return tuple(buckets)


def _suppressed_clone_buckets(
    report_document: Mapping[str, object],
) -> tuple[Mapping[str, object], ...]:
    """Every suppressed clone group the document publishes.

    Read through the shared law rather than here. This module used to navigate
    to the container and hedge across the singular *and* the plural bucket
    spelling, which is one document with two authorities over what "suppressed"
    means -- and a hedge is only ever as wide as the spellings its author knew.
    The report door cannot be called from this ring, so the reading moved to
    the ring both can reach instead.
    """

    return _suppressed_clone_groups_in(_suppressed_clone_container(report_document))


def _clone_group_paths(
    report_document: Mapping[str, object],
) -> tuple[tuple[str, ...], ...]:
    """Each active clone group's site paths, one entry per group."""
    return tuple(
        sorted(
            _dedupe_sorted(
                {
                    _item_path(_as_mapping(item))
                    for item in _as_sequence(group.get("items"))
                }
            )
            for group in _clone_group_buckets(report_document)
        )
    )


def _compute_clone_cohort_members(
    *,
    clone_groups: Sequence[Sequence[str]],
    origin_paths: Sequence[str],
) -> tuple[str, ...]:
    origin_set = set(origin_paths)
    cohort_paths: set[str] = set()
    for group in clone_groups:
        item_paths = set(group)
        if origin_set.intersection(item_paths):
            cohort_paths.update(item_paths - origin_set)
    return _dedupe_sorted(cohort_paths)


def _compute_cycle_membership(
    *,
    origin_modules: Sequence[str],
    origin_by_module: Mapping[str, str],
    cycles: Sequence[Sequence[str]],
) -> tuple[str, ...]:
    cycle_modules = {module for cycle in cycles for module in cycle}
    return _dedupe_sorted(
        {
            origin_by_module[module]
            for module in origin_modules
            if module in cycle_modules and origin_by_module.get(module)
        }
    )


def _compute_radius_level(
    *,
    direct_dependents: Sequence[str],
    clone_cohort_members: Sequence[str],
) -> str:
    total_affected = len(direct_dependents) + len(clone_cohort_members)
    if total_affected == 0:
        return "low"
    if total_affected <= 5:
        return "medium"
    return "high"


def _blast_zone(
    *,
    origin_paths: Sequence[str],
    direct_dependents: Sequence[str],
    transitive_dependents: Sequence[str],
    clone_cohort_members: Sequence[str],
) -> set[str]:
    return {
        *origin_paths,
        *direct_dependents,
        *transitive_dependents,
        *clone_cohort_members,
    }


def _item_paths_where(
    items: object,
    keep: Callable[[Mapping[str, object]], bool],
) -> tuple[str, ...]:
    """The path of every item ``keep`` selects, sorted unique."""
    return _dedupe_sorted(
        {
            _item_path(_as_mapping(item))
            for item in _as_sequence(items)
            if keep(_as_mapping(item))
        }
    )


def _high_risk(item: Mapping[str, object]) -> bool:
    return str(item.get("risk", "")).strip() == "high"


def _coverage_signal(item: Mapping[str, object]) -> bool:
    return bool(item.get("coverage_hotspot")) or bool(item.get("scope_gap_hotspot"))


def _overloaded_candidate(item: Mapping[str, object]) -> bool:
    return str(item.get("candidate_status", "")).strip() == "candidate"


def _risk_signal_paths(
    report_document: Mapping[str, object],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """High complexity, high coupling, low coverage and overloaded-candidate
    paths, run-wide: the blast zone cuts them in the computation."""
    complexity, coupling, coverage_join, overloaded_modules = sections(
        report_document,
        "metrics.families.complexity",
        "metrics.families.coupling",
        "metrics.families.coverage_join",
        "metrics.families.overloaded_modules",
    )
    return (
        _item_paths_where(complexity.get("items"), _high_risk),
        _item_paths_where(coupling.get("items"), _high_risk),
        _item_paths_where(coverage_join.get("items"), _coverage_signal),
        _item_paths_where(overloaded_modules.get("items"), _overloaded_candidate),
    )


def _in_zone(paths: Sequence[str], blast_zone_paths: set[str]) -> list[str]:
    return [path for path in paths if path in blast_zone_paths]


def _compute_risk_signals(
    *,
    facts: BlastRadiusFacts,
    blast_zone_paths: set[str],
) -> dict[str, list[str]]:
    return {
        "high_complexity_in_blast_zone": _in_zone(
            facts.high_complexity_paths, blast_zone_paths
        ),
        "high_coupling_in_blast_zone": _in_zone(
            facts.high_coupling_paths, blast_zone_paths
        ),
        "low_coverage_in_blast_zone": _in_zone(
            facts.low_coverage_paths, blast_zone_paths
        ),
        "overloaded_modules_in_blast_zone": _in_zone(
            facts.overloaded_candidate_paths, blast_zone_paths
        ),
    }


def _finding_paths(finding: Mapping[str, object]) -> tuple[str, ...]:
    return _dedupe_sorted(
        {_item_path(_as_mapping(item)) for item in _as_sequence(finding.get("items"))}
    )


def _all_finding_groups(
    report_document: Mapping[str, object],
) -> tuple[Mapping[str, object], ...]:
    """Every group the document publishes, whatever family it belongs to.

    Read through the shared structural walk rather than the declared
    five-family universe, and that is the point: review context must not go
    blind to a family the document gains later. What is excluded is stated
    where it is decided -- the caller keeps only groups the baseline calls
    ``known`` -- so an advisory tier, which reaches no baseline lane and can be
    neither ``new`` nor ``known``, is declined on a fact rather than missed on
    a hard-coded list.
    """

    return tuple(
        _as_mapping(item)
        for _family, _container_key, entries in _iter_published_group_lists(
            report_document
        )
        for item in entries
    )


def _append_boundary_entry(
    entries: dict[str, dict[str, str]],
    *,
    path: str,
    reason: str,
    category: str,
    severity: str,
) -> None:
    if not path:
        return
    entries.setdefault(
        path,
        {
            "path": path,
            "reason": reason,
            "category": category,
            "severity": severity,
        },
    )


def _append_review_entry(
    entries: dict[tuple[str, str, str], dict[str, str]],
    *,
    path: str,
    reason: str,
    category: str,
    severity: str = "context",
) -> None:
    if not path:
        return
    entries.setdefault(
        (path, category, reason),
        {
            "path": path,
            "reason": reason,
            "category": category,
            "severity": severity,
        },
    )


def _known_debt_paths(report_document: Mapping[str, object]) -> tuple[str, ...]:
    """Every site path of a group the baseline calls ``known``."""
    return _dedupe_sorted(
        {
            path
            for group in _all_finding_groups(report_document)
            if str(group.get("novelty", "")).strip() == "known"
            for path in _finding_paths(group)
        }
    )


def _suppressed_clone_paths(report_document: Mapping[str, object]) -> tuple[str, ...]:
    """Every site path of a suppressed clone group."""
    return _dedupe_sorted(
        {
            path
            for group in _suppressed_clone_buckets(report_document)
            for path in _finding_paths(group)
        }
    )


def _report_only_paths(
    report_document: Mapping[str, object],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The security-surface and the overloaded-module paths, in that order."""
    metrics = _as_mapping(report_document.get("metrics"))
    families = _as_mapping(metrics.get("families"))
    security_surfaces, overloaded_modules = (
        _item_paths_where(
            _as_mapping(families.get(family_name)).get("items"), _every_item
        )
        for family_name in ("security_surfaces", "overloaded_modules")
    )
    return security_surfaces, overloaded_modules


def _every_item(_item: Mapping[str, object]) -> bool:
    return True


def _review_entries(
    *,
    facts: BlastRadiusFacts,
    origin_paths: Sequence[str],
    blast_zone_paths: set[str],
) -> dict[tuple[str, str, str], dict[str, str]]:
    """Review context: advisory facts inside the zone, keyed for dedupe."""
    review_entries: dict[tuple[str, str, str], dict[str, str]] = {}
    origin_set = set(origin_paths)
    # (paths, reason, category, whether an origin path is excluded).  The
    # dynamic frontier is advisory only: an opaque site resolves to no target,
    # so it never entered the import graph and must not widen the radius here
    # either -- and it is reported on the origin too.
    for paths, reason, category, skip_origin in (
        (
            facts.dynamic_frontier_paths,
            REVIEW_REASON_DYNAMIC_FRONTIER,
            "dynamic_frontier_boundary",
            False,
        ),
        (
            facts.known_debt_paths,
            REVIEW_REASON_KNOWN_BASELINE_DEBT,
            "known_baseline_debt",
            True,
        ),
        (
            facts.suppressed_clone_paths,
            REVIEW_REASON_GOLDEN_FIXTURE_SURFACE,
            "golden_fixture_surface",
            False,
        ),
        (
            facts.security_surface_paths,
            REVIEW_REASON_SECURITY_BOUNDARY,
            "security_boundary_context",
            True,
        ),
        (
            facts.overloaded_module_paths,
            REVIEW_REASON_REPORT_ONLY_DESIGN,
            "report_only_context",
            True,
        ),
    ):
        for path in paths:
            if path in blast_zone_paths and not (skip_origin and path in origin_set):
                _append_review_entry(
                    review_entries, path=path, reason=reason, category=category
                )
    return review_entries


def _compute_change_boundaries(
    *,
    facts: BlastRadiusFacts,
    origin_paths: Sequence[str],
    blast_zone_paths: set[str],
    forbidden_patterns: Sequence[str],
    allowed_scope: Sequence[str] = (),
) -> tuple[tuple[dict[str, str], ...], tuple[dict[str, str], ...]]:
    do_not_touch_entries: dict[str, dict[str, str]] = {}
    allowed_set = set(allowed_scope)
    for pattern in DEFAULT_DO_NOT_TOUCH_PATTERNS:
        _append_boundary_entry(
            do_not_touch_entries,
            path=pattern,
            reason=BOUNDARY_REASON_BASELINE_OR_STATE,
            category="baseline_or_generated_state",
            severity="hard",
        )
    for pattern in forbidden_patterns:
        _append_boundary_entry(
            do_not_touch_entries,
            path=pattern,
            reason=BOUNDARY_REASON_EXPLICIT_FORBIDDEN,
            category="explicit_forbidden",
            severity="hard",
        )
    review_entries = _review_entries(
        facts=facts, origin_paths=origin_paths, blast_zone_paths=blast_zone_paths
    )
    if allowed_set:
        for path in blast_zone_paths:
            if path not in allowed_set:
                _append_boundary_entry(
                    do_not_touch_entries,
                    path=path,
                    reason=BOUNDARY_REASON_AFFECTED_NOT_ALLOWED,
                    category="affected_but_not_allowed",
                    severity="requires_expansion",
                )
    do_not_touch = tuple(
        do_not_touch_entries[path] for path in sorted(do_not_touch_entries) if path
    )
    review_context = tuple(
        entry
        for entry in sorted(
            review_entries.values(),
            key=lambda item: (item["path"], item["category"], item["reason"]),
        )
        if entry["path"] not in do_not_touch_entries
    )
    return do_not_touch, review_context


def _guardrails(
    *,
    radius_level: str,
    do_not_touch: Sequence[Mapping[str, str]],
) -> tuple[str, ...]:
    guardrails = [
        GUARDRAIL_REVIEW_DEPENDENTS,
        GUARDRAIL_CLONE_COHORT_CONTEXT,
    ]
    if radius_level == "high":
        guardrails.append(GUARDRAIL_HIGH_RADIUS_APPROVAL)
    if do_not_touch:
        guardrails.append(GUARDRAIL_DO_NOT_TOUCH_APPROVAL)
    return tuple(guardrails)


def blast_radius_facts(
    report_document: Mapping[str, object],
    file_modules: Sequence[tuple[str, str]] | None = None,
) -> BlastRadiusFacts:
    """The facts of one run a blast radius reads, off its report document.

    ``file_modules`` is the run's module identity.  Left out, it is read off
    the document's own module registry (:func:`document_file_modules`) -- a
    whole report document carries it; a served projection withholds it,
    refuses that read, and its caller hands the lifted pairs over instead.
    The identity is never re-derived from any other section of the document.
    """
    identity = (
        document_file_modules(report_document) if file_modules is None else file_modules
    )
    high_complexity, high_coupling, low_coverage, overloaded_candidates = (
        _risk_signal_paths(report_document)
    )
    security_surfaces, overloaded_modules = _report_only_paths(report_document)
    return BlastRadiusFacts(
        file_modules=tuple(sorted(set(identity))),
        dependency_edges=_edge_pairs(_dependency_edges(report_document)),
        dependency_cycles=_dependency_cycles(report_document),
        clone_groups=_clone_group_paths(report_document),
        suppressed_clone_paths=_suppressed_clone_paths(report_document),
        known_debt_paths=_known_debt_paths(report_document),
        dynamic_frontier_paths=_opaque_dynamic_load_paths(report_document),
        high_complexity_paths=high_complexity,
        high_coupling_paths=high_coupling,
        low_coverage_paths=low_coverage,
        overloaded_candidate_paths=overloaded_candidates,
        overloaded_module_paths=overloaded_modules,
        security_surface_paths=security_surfaces,
    )


def compute_blast_radius(
    *,
    run_id: str,
    report_document: Mapping[str, object],
    files: Sequence[str],
    depth: BlastRadiusDepth = "direct",
    forbidden_patterns: Sequence[str] = DEFAULT_DO_NOT_TOUCH_PATTERNS,
    allowed_scope: Sequence[str] = (),
    file_modules: Sequence[tuple[str, str]] | None = None,
) -> BlastRadiusResult:
    """The blast radius of ``files`` over one report document and the run's
    module identity (``file_modules``, see :func:`blast_radius_facts`)."""
    return compute_blast_radius_from_facts(
        run_id=run_id,
        facts=blast_radius_facts(report_document, file_modules),
        files=files,
        depth=depth,
        forbidden_patterns=forbidden_patterns,
        allowed_scope=allowed_scope,
    )


def compute_blast_radius_from_facts(
    *,
    run_id: str,
    facts: BlastRadiusFacts,
    files: Sequence[str],
    depth: BlastRadiusDepth = "direct",
    forbidden_patterns: Sequence[str] = DEFAULT_DO_NOT_TOUCH_PATTERNS,
    allowed_scope: Sequence[str] = (),
) -> BlastRadiusResult:
    """The blast radius of ``files`` over the facts of one run."""
    origin_paths = _dedupe_sorted(
        tuple(_normalize_relative_path(path) for path in files)
    )
    module_of, module_paths = module_index(facts.file_modules)
    origin_by_module = {
        module: path
        for path in origin_paths
        for module in (file_module(path, module_of),)
        if module is not None
    }
    origin_modules = tuple(sorted(origin_by_module))
    reverse_graph = _build_reverse_import_graph(facts.dependency_edges)
    direct_modules = _compute_direct_dependents(
        origin_modules=origin_modules,
        reverse_graph=reverse_graph,
    )
    transitive_modules = (
        _compute_transitive_dependents(
            origin_modules=origin_modules,
            reverse_graph=reverse_graph,
        )
        if depth == "transitive"
        else ()
    )
    direct_dependents = _dedupe_sorted(
        tuple(_module_to_output(module, module_paths) for module in direct_modules)
    )
    transitive_dependents = _dedupe_sorted(
        tuple(
            _module_to_output(module, module_paths)
            for module in transitive_modules
            if module not in set(direct_modules)
        )
    )
    clone_cohort_members = _compute_clone_cohort_members(
        clone_groups=facts.clone_groups,
        origin_paths=origin_paths,
    )
    dependency_cycle_members = _compute_cycle_membership(
        origin_modules=origin_modules,
        origin_by_module=origin_by_module,
        cycles=facts.dependency_cycles,
    )
    radius_level = _compute_radius_level(
        direct_dependents=direct_dependents,
        clone_cohort_members=clone_cohort_members,
    )
    zone = _blast_zone(
        origin_paths=origin_paths,
        direct_dependents=direct_dependents,
        transitive_dependents=transitive_dependents,
        clone_cohort_members=clone_cohort_members,
    )
    risk = _compute_risk_signals(facts=facts, blast_zone_paths=zone)
    do_not_touch, review_context = _compute_change_boundaries(
        facts=facts,
        origin_paths=origin_paths,
        blast_zone_paths=zone,
        forbidden_patterns=forbidden_patterns,
        allowed_scope=allowed_scope,
    )
    return BlastRadiusResult(
        run_id=run_id,
        origin=origin_paths,
        depth=depth,
        radius_level=radius_level,
        direct_dependents=direct_dependents,
        transitive_dependents=transitive_dependents,
        clone_cohort_members=clone_cohort_members,
        in_dependency_cycle=dependency_cycle_members,
        structural_risk=risk,
        do_not_touch=do_not_touch,
        review_context=review_context,
        guardrails=_guardrails(radius_level=radius_level, do_not_touch=do_not_touch),
    )


__all__ = [
    "BOUNDARY_REASON_AFFECTED_NOT_ALLOWED",
    "BOUNDARY_REASON_BASELINE_OR_STATE",
    "BOUNDARY_REASON_EXPLICIT_FORBIDDEN",
    "DEFAULT_DO_NOT_TOUCH_PATTERNS",
    "GUARDRAIL_CLONE_COHORT_CONTEXT",
    "GUARDRAIL_DO_NOT_TOUCH_APPROVAL",
    "GUARDRAIL_HIGH_RADIUS_APPROVAL",
    "GUARDRAIL_REVIEW_DEPENDENTS",
    "MAX_CONTEXT_ITEMS",
    "REVIEW_REASON_DYNAMIC_FRONTIER",
    "REVIEW_REASON_GOLDEN_FIXTURE_SURFACE",
    "REVIEW_REASON_KNOWN_BASELINE_DEBT",
    "REVIEW_REASON_REPORT_ONLY_DESIGN",
    "REVIEW_REASON_SECURITY_BOUNDARY",
    "BlastRadiusDepth",
    "BlastRadiusResult",
    "blast_radius_facts",
    "compute_blast_radius",
    "compute_blast_radius_from_facts",
    "document_file_modules",
    "file_module",
    "module_index",
]
