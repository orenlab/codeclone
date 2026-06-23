# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Neutral blast-radius computation over canonical report dicts."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from ..paths.workspace import FORBIDDEN_WORKSPACE_GLOBS
from ..utils.coerce import as_mapping as _as_mapping
from ..utils.coerce import as_sequence as _as_sequence

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
    text = str(path).replace("\\", "/").strip()
    if text == ".":
        return ""
    if text.startswith("./"):
        text = text[2:]
    return text.rstrip("/")


def _path_to_module(path: str) -> str:
    normalized = _normalize_relative_path(path)
    if not normalized.endswith(".py"):
        return normalized.replace("/", ".")
    without_suffix = normalized[:-3]
    if without_suffix.endswith("/__init__"):
        without_suffix = without_suffix[: -len("/__init__")]
    if without_suffix == "__init__":
        without_suffix = ""
    return without_suffix.replace("/", ".").strip(".")


def _module_to_candidate_path(module: str) -> str:
    return f"{module.replace('.', '/')}.py" if module else ""


def _dedupe_sorted(values: Sequence[str] | set[str]) -> tuple[str, ...]:
    return tuple(sorted({value for value in values if value}))


def _item_path(item: Mapping[str, object]) -> str:
    for key in ("relative_path", "path", "filepath", "file"):
        value = _normalize_relative_path(item.get(key, ""))
        if value:
            return value
    return ""


def _module_path_index(report_document: Mapping[str, object]) -> dict[str, str]:
    modules: dict[str, str] = {}
    inventory = _as_mapping(report_document.get("inventory"))
    file_registry = _as_mapping(inventory.get("file_registry"))
    for raw_path in _as_sequence(file_registry.get("items")):
        path = _normalize_relative_path(raw_path)
        module = _path_to_module(path)
        if module and path:
            modules.setdefault(module, path)
    metrics = _as_mapping(report_document.get("metrics"))
    families = _as_mapping(metrics.get("families"))
    for family_name in (
        "complexity",
        "coupling",
        "cohesion",
        "coverage_join",
        "overloaded_modules",
        "security_surfaces",
        "api_surface",
        "coverage_adoption",
    ):
        family = _as_mapping(families.get(family_name))
        for raw_item in _as_sequence(family.get("items")):
            item = _as_mapping(raw_item)
            path = _item_path(item)
            module = str(item.get("module", "")).strip() or _path_to_module(path)
            if module and path:
                modules.setdefault(module, path)
    return modules


def _module_to_output(module: str, module_paths: Mapping[str, str]) -> str:
    return module_paths.get(module, _module_to_candidate_path(module) or module)


def _build_reverse_import_graph(
    edges: Sequence[Mapping[str, object]],
) -> dict[str, set[str]]:
    reverse: dict[str, set[str]] = {}
    for edge in edges:
        source = str(edge.get("source", "")).strip()
        target = str(edge.get("target", "")).strip()
        if source and target:
            reverse.setdefault(target, set()).add(source)
    return reverse


def _dependency_edges(
    report_document: Mapping[str, object],
) -> tuple[Mapping[str, object], ...]:
    metrics = _as_mapping(report_document.get("metrics"))
    families = _as_mapping(metrics.get("families"))
    dependencies = _as_mapping(families.get("dependencies"))
    return tuple(_as_mapping(item) for item in _as_sequence(dependencies.get("items")))


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
    findings = _as_mapping(report_document.get("findings"))
    groups = _as_mapping(findings.get("groups"))
    clones = _as_mapping(groups.get("clones"))
    suppressed = _as_mapping(clones.get("suppressed"))
    buckets: list[Mapping[str, object]] = []
    for bucket_name in (
        "function",
        "block",
        "segment",
        "functions",
        "blocks",
        "segments",
    ):
        buckets.extend(
            _as_mapping(item) for item in _as_sequence(suppressed.get(bucket_name))
        )
    return tuple(buckets)


def _compute_clone_cohort_members(
    *,
    report_document: Mapping[str, object],
    origin_paths: Sequence[str],
) -> tuple[str, ...]:
    origin_set = set(origin_paths)
    cohort_paths: set[str] = set()
    for group in _clone_group_buckets(report_document):
        item_paths = {
            _item_path(_as_mapping(item)) for item in _as_sequence(group.get("items"))
        }
        item_paths.discard("")
        if origin_set.intersection(item_paths):
            cohort_paths.update(item_paths - origin_set)
    return _dedupe_sorted(cohort_paths)


def _compute_cycle_membership(
    *,
    origin_modules: Sequence[str],
    origin_by_module: Mapping[str, str],
    report_document: Mapping[str, object],
) -> tuple[str, ...]:
    cycle_modules = {
        module for cycle in _dependency_cycles(report_document) for module in cycle
    }
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


def _compute_risk_signals(
    *,
    report_document: Mapping[str, object],
    blast_zone_paths: set[str],
) -> dict[str, list[str]]:
    metrics = _as_mapping(report_document.get("metrics"))
    families = _as_mapping(metrics.get("families"))
    complexity = _as_mapping(families.get("complexity"))
    coupling = _as_mapping(families.get("coupling"))
    coverage_join = _as_mapping(families.get("coverage_join"))
    overloaded_modules = _as_mapping(families.get("overloaded_modules"))

    high_complexity = {
        _item_path(_as_mapping(item))
        for item in _as_sequence(complexity.get("items"))
        if str(_as_mapping(item).get("risk", "")).strip() == "high"
        and _item_path(_as_mapping(item)) in blast_zone_paths
    }
    high_coupling = {
        _item_path(_as_mapping(item))
        for item in _as_sequence(coupling.get("items"))
        if str(_as_mapping(item).get("risk", "")).strip() == "high"
        and _item_path(_as_mapping(item)) in blast_zone_paths
    }
    low_coverage = {
        _item_path(_as_mapping(item))
        for item in _as_sequence(coverage_join.get("items"))
        if (
            bool(_as_mapping(item).get("coverage_hotspot"))
            or bool(_as_mapping(item).get("scope_gap_hotspot"))
        )
        and _item_path(_as_mapping(item)) in blast_zone_paths
    }
    overloaded = {
        _item_path(_as_mapping(item))
        for item in _as_sequence(overloaded_modules.get("items"))
        if str(_as_mapping(item).get("candidate_status", "")).strip() == "candidate"
        and _item_path(_as_mapping(item)) in blast_zone_paths
    }
    return {
        "high_complexity_in_blast_zone": list(_dedupe_sorted(high_complexity)),
        "high_coupling_in_blast_zone": list(_dedupe_sorted(high_coupling)),
        "low_coverage_in_blast_zone": list(_dedupe_sorted(low_coverage)),
        "overloaded_modules_in_blast_zone": list(_dedupe_sorted(overloaded)),
    }


def _finding_paths(finding: Mapping[str, object]) -> tuple[str, ...]:
    return _dedupe_sorted(
        {_item_path(_as_mapping(item)) for item in _as_sequence(finding.get("items"))}
    )


def _all_finding_groups(
    report_document: Mapping[str, object],
) -> tuple[Mapping[str, object], ...]:
    findings = _as_mapping(report_document.get("findings"))
    groups = _as_mapping(findings.get("groups"))
    result: list[Mapping[str, object]] = []
    for family_payload in groups.values():
        family_map = _as_mapping(family_payload)
        for value in family_map.values():
            result.extend(_as_mapping(item) for item in _as_sequence(value))
    return tuple(result)


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


def _compute_change_boundaries(
    *,
    report_document: Mapping[str, object],
    origin_paths: Sequence[str],
    blast_zone_paths: set[str],
    forbidden_patterns: Sequence[str],
    allowed_scope: Sequence[str] = (),
) -> tuple[tuple[dict[str, str], ...], tuple[dict[str, str], ...]]:
    do_not_touch_entries: dict[str, dict[str, str]] = {}
    review_entries: dict[tuple[str, str, str], dict[str, str]] = {}
    origin_set = set(origin_paths)
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
    for group in _all_finding_groups(report_document):
        if str(group.get("novelty", "")).strip() != "known":
            continue
        for path in _finding_paths(group):
            if path in blast_zone_paths and path not in origin_set:
                _append_review_entry(
                    review_entries,
                    path=path,
                    reason=REVIEW_REASON_KNOWN_BASELINE_DEBT,
                    category="known_baseline_debt",
                )
    for group in _suppressed_clone_buckets(report_document):
        for path in _finding_paths(group):
            if path in blast_zone_paths:
                _append_review_entry(
                    review_entries,
                    path=path,
                    reason=REVIEW_REASON_GOLDEN_FIXTURE_SURFACE,
                    category="golden_fixture_surface",
                )
    metrics = _as_mapping(report_document.get("metrics"))
    families = _as_mapping(metrics.get("families"))
    for family_name, reason, category in (
        (
            "security_surfaces",
            REVIEW_REASON_SECURITY_BOUNDARY,
            "security_boundary_context",
        ),
        (
            "overloaded_modules",
            REVIEW_REASON_REPORT_ONLY_DESIGN,
            "report_only_context",
        ),
    ):
        family = _as_mapping(families.get(family_name))
        for raw_item in _as_sequence(family.get("items")):
            path = _item_path(_as_mapping(raw_item))
            if path in blast_zone_paths and path not in origin_set:
                _append_review_entry(
                    review_entries,
                    path=path,
                    reason=reason,
                    category=category,
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


def compute_blast_radius(
    *,
    run_id: str,
    report_document: Mapping[str, object],
    files: Sequence[str],
    depth: BlastRadiusDepth = "direct",
    forbidden_patterns: Sequence[str] = DEFAULT_DO_NOT_TOUCH_PATTERNS,
    allowed_scope: Sequence[str] = (),
) -> BlastRadiusResult:
    origin_paths = _dedupe_sorted(
        tuple(_normalize_relative_path(path) for path in files)
    )
    module_paths = _module_path_index(report_document)
    origin_by_module = {
        module: path
        for path in origin_paths
        for module in (_path_to_module(path),)
        if module
    }
    origin_modules = tuple(sorted(origin_by_module))
    reverse_graph = _build_reverse_import_graph(_dependency_edges(report_document))
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
        report_document=report_document,
        origin_paths=origin_paths,
    )
    dependency_cycle_members = _compute_cycle_membership(
        origin_modules=origin_modules,
        origin_by_module=origin_by_module,
        report_document=report_document,
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
    risk = _compute_risk_signals(
        report_document=report_document,
        blast_zone_paths=zone,
    )
    do_not_touch, review_context = _compute_change_boundaries(
        report_document=report_document,
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
    "REVIEW_REASON_GOLDEN_FIXTURE_SURFACE",
    "REVIEW_REASON_KNOWN_BASELINE_DEBT",
    "REVIEW_REASON_REPORT_ONLY_DESIGN",
    "REVIEW_REASON_SECURITY_BOUNDARY",
    "BlastRadiusDepth",
    "BlastRadiusResult",
    "compute_blast_radius",
]
