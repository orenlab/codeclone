# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Final

from ...domain.findings import (
    CATEGORY_COHESION,
    CATEGORY_COMPLEXITY,
    CATEGORY_COUPLING,
    CATEGORY_DEAD_CODE,
    CATEGORY_DEPENDENCY,
    CLONE_KIND_BLOCK,
    CLONE_KIND_FUNCTION,
    CLONE_KIND_SEGMENT,
    FAMILY_CLONE,
    FAMILY_CLONES,
    FAMILY_DEAD_CODE,
    FAMILY_DESIGN,
    FAMILY_STRUCTURAL,
)
from ...domain.quality import (
    SEVERITY_INFO,
    SEVERITY_ORDER,
)
from ...domain.source_scope import (
    IMPACT_SCOPE_MIXED,
    IMPACT_SCOPE_NON_RUNTIME,
    IMPACT_SCOPE_RUNTIME,
    SOURCE_KIND_FIXTURES,
    SOURCE_KIND_MIXED,
    SOURCE_KIND_OTHER,
    SOURCE_KIND_PRODUCTION,
    SOURCE_KIND_TESTS,
)
from ...findings.ids import (
    clone_group_id,
    dead_code_group_id,
    design_group_id,
    structural_group_id,
)
from ...metrics.dependencies import select_dependency_graph_nodes
from ...metrics.overloaded_modules import _score_quantile
from ...utils.coerce import as_float as _as_float
from ...utils.coerce import as_int as _as_int
from ...utils.coerce import as_mapping as _as_mapping
from ...utils.coerce import as_sequence as _as_sequence
from ..overview import build_directory_hotspots
from ._common import _contract_report_location_path, _is_absolute_path

if TYPE_CHECKING:
    from ...models import (
        Suggestion,
    )


def _sort_flat_finding_ids(
    groups: Sequence[Mapping[str, object]],
) -> list[str]:
    ordered = sorted(
        groups,
        key=lambda group: (
            -_as_float(group.get("priority")),
            SEVERITY_ORDER.get(str(group.get("severity", SEVERITY_INFO)), 9),
            -_as_int(_as_mapping(group.get("spread")).get("files")),
            -_as_int(_as_mapping(group.get("spread")).get("functions")),
            -_as_int(group.get("count")),
            str(group.get("id", "")),
        ),
    )
    return [str(group["id"]) for group in ordered]


def _sort_highest_spread_ids(
    groups: Sequence[Mapping[str, object]],
) -> list[str]:
    ordered = sorted(
        groups,
        key=lambda group: (
            -_as_int(_as_mapping(group.get("spread")).get("files")),
            -_as_int(_as_mapping(group.get("spread")).get("functions")),
            -_as_int(group.get("count")),
            -_as_float(group.get("priority")),
            str(group.get("id", "")),
        ),
    )
    return [str(group["id"]) for group in ordered]


def _health_snapshot(metrics_payload: Mapping[str, object]) -> dict[str, object]:
    health = _as_mapping(_as_mapping(metrics_payload.get("families")).get("health"))
    summary = _as_mapping(health.get("summary"))
    dimensions = {
        str(key): _as_int(value)
        for key, value in _as_mapping(summary.get("dimensions")).items()
    }
    strongest = None
    weakest = None
    if dimensions:
        strongest = min(
            sorted(dimensions),
            key=lambda key: (-dimensions[key], key),
        )
        weakest = min(
            sorted(dimensions),
            key=lambda key: (dimensions[key], key),
        )
    return {
        "score": _as_int(summary.get("score")),
        "grade": str(summary.get("grade", "")),
        "strongest_dimension": strongest,
        "weakest_dimension": weakest,
    }


def _combined_impact_scope(groups: Sequence[Mapping[str, object]]) -> str:
    impact_scopes = {
        str(
            _as_mapping(group.get("source_scope")).get(
                "impact_scope",
                IMPACT_SCOPE_NON_RUNTIME,
            )
        )
        for group in groups
    }
    if not impact_scopes:
        return IMPACT_SCOPE_NON_RUNTIME
    if len(impact_scopes) == 1:
        return next(iter(impact_scopes))
    return IMPACT_SCOPE_MIXED


def _top_risks(
    *,
    dead_code_groups: Sequence[Mapping[str, object]],
    design_groups: Sequence[Mapping[str, object]],
    structural_groups: Sequence[Mapping[str, object]],
    clone_groups: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    risks: list[dict[str, object]] = []

    if dead_code_groups:
        label = (
            "1 dead code item"
            if len(dead_code_groups) == 1
            else f"{len(dead_code_groups)} dead code items"
        )
        risks.append(
            {
                "kind": "family_summary",
                "family": FAMILY_DEAD_CODE,
                "count": len(dead_code_groups),
                "scope": IMPACT_SCOPE_MIXED
                if len(
                    {
                        _as_mapping(group.get("source_scope")).get("impact_scope")
                        for group in dead_code_groups
                    }
                )
                > 1
                else str(
                    _as_mapping(dead_code_groups[0].get("source_scope")).get(
                        "impact_scope",
                        IMPACT_SCOPE_NON_RUNTIME,
                    )
                ),
                "label": label,
            }
        )

    low_cohesion = [
        group
        for group in design_groups
        if str(group.get("category", "")) == CATEGORY_COHESION
    ]
    if low_cohesion:
        label = (
            "1 low cohesion class"
            if len(low_cohesion) == 1
            else f"{len(low_cohesion)} low cohesion classes"
        )
        risks.append(
            {
                "kind": "family_summary",
                "family": FAMILY_DESIGN,
                "category": CATEGORY_COHESION,
                "count": len(low_cohesion),
                "scope": _combined_impact_scope(low_cohesion),
                "label": label,
            }
        )

    production_structural = [
        group
        for group in structural_groups
        if str(_as_mapping(group.get("source_scope")).get("impact_scope"))
        in {IMPACT_SCOPE_RUNTIME, IMPACT_SCOPE_MIXED}
    ]
    if production_structural:
        label = (
            "1 structural finding in production code"
            if len(production_structural) == 1
            else (
                f"{len(production_structural)} structural findings in production code"
            )
        )
        risks.append(
            {
                "kind": "family_summary",
                "family": FAMILY_STRUCTURAL,
                "count": len(production_structural),
                "scope": SOURCE_KIND_PRODUCTION,
                "label": label,
            }
        )

    fixture_test_clones = [
        group
        for group in clone_groups
        if _as_mapping(group.get("source_scope")).get("impact_scope")
        == IMPACT_SCOPE_NON_RUNTIME
        and _as_mapping(group.get("source_scope")).get("dominant_kind")
        in {SOURCE_KIND_TESTS, SOURCE_KIND_FIXTURES}
    ]
    if fixture_test_clones:
        label = (
            "1 clone group in fixtures/tests"
            if len(fixture_test_clones) == 1
            else f"{len(fixture_test_clones)} clone groups in fixtures/tests"
        )
        risks.append(
            {
                "kind": "family_summary",
                "family": FAMILY_CLONE,
                "count": len(fixture_test_clones),
                "scope": IMPACT_SCOPE_NON_RUNTIME,
                "label": label,
            }
        )

    return risks[:6]


def _build_derived_overview(
    *,
    findings: Mapping[str, object],
    metrics_payload: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    groups = _as_mapping(findings.get("groups"))
    clones = _as_mapping(groups.get(FAMILY_CLONES))
    clone_groups = [
        *_as_sequence(clones.get("functions")),
        *_as_sequence(clones.get("blocks")),
        *_as_sequence(clones.get("segments")),
    ]
    structural_groups = _as_sequence(
        _as_mapping(groups.get(FAMILY_STRUCTURAL)).get("groups")
    )
    dead_code_groups = _as_sequence(
        _as_mapping(groups.get(FAMILY_DEAD_CODE)).get("groups")
    )
    design_groups = _as_sequence(_as_mapping(groups.get("design")).get("groups"))
    flat_groups = [
        *clone_groups,
        *structural_groups,
        *dead_code_groups,
        *design_groups,
    ]
    dominant_kind_counts: Counter[str] = Counter(
        str(
            _as_mapping(_as_mapping(group).get("source_scope")).get(
                "dominant_kind",
                SOURCE_KIND_OTHER,
            )
        )
        for group in flat_groups
    )
    summary = _as_mapping(findings.get("summary"))
    overview: dict[str, object] = {
        "families": dict(_as_mapping(summary.get("families"))),
        "top_risks": _top_risks(
            dead_code_groups=[_as_mapping(group) for group in dead_code_groups],
            design_groups=[_as_mapping(group) for group in design_groups],
            structural_groups=[_as_mapping(group) for group in structural_groups],
            clone_groups=[_as_mapping(group) for group in clone_groups],
        ),
        "source_scope_breakdown": {
            key: dominant_kind_counts[key]
            for key in (
                SOURCE_KIND_PRODUCTION,
                SOURCE_KIND_TESTS,
                SOURCE_KIND_FIXTURES,
                SOURCE_KIND_MIXED,
                SOURCE_KIND_OTHER,
            )
            if dominant_kind_counts[key] > 0
        },
        "health_snapshot": _health_snapshot(metrics_payload),
        "directory_hotspots": build_directory_hotspots(findings=findings),
    }
    hotlists: dict[str, object] = {
        "most_actionable_ids": _sort_flat_finding_ids(
            [
                group
                for group in map(_as_mapping, flat_groups)
                if str(group.get("severity")) != SEVERITY_INFO
            ]
        )[:5],
        "highest_spread_ids": _sort_highest_spread_ids(
            list(map(_as_mapping, flat_groups))
        )[:5],
        "production_hotspot_ids": _sort_flat_finding_ids(
            [
                group
                for group in map(_as_mapping, flat_groups)
                if str(_as_mapping(group.get("source_scope")).get("impact_scope"))
                in {IMPACT_SCOPE_RUNTIME, IMPACT_SCOPE_MIXED}
            ]
        )[:5],
        "test_fixture_hotspot_ids": _sort_flat_finding_ids(
            [
                group
                for group in map(_as_mapping, flat_groups)
                if str(_as_mapping(group.get("source_scope")).get("impact_scope"))
                == IMPACT_SCOPE_NON_RUNTIME
                and str(_as_mapping(group.get("source_scope")).get("dominant_kind"))
                in {SOURCE_KIND_TESTS, SOURCE_KIND_FIXTURES}
            ]
        )[:5],
    }
    return overview, hotlists


def _representative_location_rows(
    suggestion: Suggestion,
) -> list[dict[str, object]]:
    rows = [
        {
            "relative_path": (
                location.relative_path
                if (
                    location.relative_path
                    and not _is_absolute_path(location.relative_path)
                )
                else _contract_report_location_path(
                    location.filepath,
                    scan_root="",
                )
            ),
            "start_line": location.start_line,
            "end_line": location.end_line,
            "qualname": location.qualname,
            "source_kind": location.source_kind,
        }
        for location in suggestion.representative_locations
    ]
    rows.sort(
        key=lambda row: (
            str(row["relative_path"]),
            _as_int(row["start_line"]),
            _as_int(row["end_line"]),
            str(row["qualname"]),
        )
    )
    return rows[:3]


def _suggestion_finding_id(suggestion: Suggestion) -> str:
    if suggestion.finding_family == FAMILY_CLONES:
        if suggestion.fact_kind.startswith("Function"):
            return clone_group_id(CLONE_KIND_FUNCTION, suggestion.subject_key)
        if suggestion.fact_kind.startswith("Block"):
            return clone_group_id(CLONE_KIND_BLOCK, suggestion.subject_key)
        return clone_group_id(CLONE_KIND_SEGMENT, suggestion.subject_key)
    if suggestion.finding_family == FAMILY_STRUCTURAL:
        return structural_group_id(
            suggestion.finding_kind or "duplicated_branches",
            suggestion.subject_key,
        )
    if suggestion.category == CATEGORY_DEAD_CODE:
        return dead_code_group_id(suggestion.subject_key)
    if suggestion.category in {
        CATEGORY_COMPLEXITY,
        CATEGORY_COUPLING,
        CATEGORY_COHESION,
        CATEGORY_DEPENDENCY,
    }:
        return design_group_id(suggestion.category, suggestion.subject_key)
    return design_group_id(
        suggestion.category,
        suggestion.subject_key or suggestion.title,
    )


def _build_derived_suggestions(
    suggestions: Sequence[Suggestion] | None,
) -> list[dict[str, object]]:
    suggestion_rows = list(suggestions or ())
    suggestion_rows.sort(
        key=lambda suggestion: (
            -suggestion.priority,
            SEVERITY_ORDER.get(suggestion.severity, 9),
            suggestion.title,
            _suggestion_finding_id(suggestion),
        )
    )
    return [
        {
            "id": f"suggestion:{_suggestion_finding_id(suggestion)}",
            "finding_id": _suggestion_finding_id(suggestion),
            "title": suggestion.title,
            "summary": suggestion.fact_summary,
            "location_label": suggestion.location_label or suggestion.location,
            "representative_locations": _representative_location_rows(suggestion),
            "action": {
                "effort": suggestion.effort,
                "steps": list(suggestion.steps),
            },
        }
        for suggestion in suggestion_rows
    ]


_MODULE_MAP_SCHEMA_VERSION: Final = "1"
_MODULE_MAP_MAX_PACKAGE_NODES: Final = 28
_MODULE_MAP_MAX_MODULE_NODES: Final = 40
_MODULE_MAP_MAX_EDGES: Final = 120
_MODULE_MAP_UNWIND_CANDIDATE_CAP: Final = 25
_MODULE_MAP_OVERMERGE_MODULE_FLOOR: Final = 80
_MODULE_MAP_MONOLITH_PACKAGE_CEILING: Final = 2
_MODULE_MAP_OVERMERGE_PACKAGE_CEILING: Final = 3
_MODULE_MAP_CANDIDATE: Final = "candidate"
_MODULE_MAP_RANKED_ONLY: Final = "ranked_only"
_MODULE_MAP_NON_CANDIDATE: Final = "non_candidate"
_MODULE_MAP_SEED_POLICY: Final = "cycles_then_chains_then_degree"


def _module_prefix(module: str, depth: int) -> str:
    parts = module.split(".")
    if len(parts) <= depth:
        return module
    return ".".join(parts[:depth])


def _package_node_id(depth: int) -> Callable[[str], str]:
    def _to_package(module: str) -> str:
        return _module_prefix(module, depth)

    return _to_package


def _module_edges_from_items(edge_items: Sequence[object]) -> list[tuple[str, str]]:
    edges: list[tuple[str, str]] = []
    for item in edge_items:
        mapping = _as_mapping(item)
        source = str(mapping.get("source", "")).strip()
        target = str(mapping.get("target", "")).strip()
        if source and target:
            edges.append((source, target))
    return edges


def _string_paths(raw: Sequence[object]) -> list[list[str]]:
    return [[str(node) for node in _as_sequence(path)] for path in raw]


def _module_map_unavailable_shell(reason: str) -> dict[str, object]:
    def _empty_truncation() -> dict[str, object]:
        return {
            "truncated": False,
            "node_universe_count": 0,
            "node_shown_count": 0,
            "edge_universe_count": 0,
            "edge_shown_count": 0,
            "seed_policy": _MODULE_MAP_SEED_POLICY,
        }

    return {
        "schema_version": _MODULE_MAP_SCHEMA_VERSION,
        "scope": "report_only",
        "default_zoom": "packages",
        "summary": {
            "available": False,
            "reason": reason,
            "module_count": 0,
            "package_count_depth2": 0,
            "edge_count": 0,
            "unwind_candidate_count": 0,
            "overloaded_candidate_count": 0,
            "overloaded_population_status": "limited",
        },
        "graph_packages": {
            "zoom": "packages",
            "package_depth": None,
            "truncation": _empty_truncation(),
            "nodes": [],
            "edges": [],
        },
        "graph_modules": {
            "zoom": "modules",
            "package_depth": None,
            "truncation": _empty_truncation(),
            "nodes": [],
            "edges": [],
        },
        "unwind_candidates": [],
    }


def _module_map_zoom_decision(
    modules: Sequence[str], module_count: int
) -> tuple[str, int]:
    if module_count <= _MODULE_MAP_MAX_MODULE_NODES:
        return "modules", 2
    p1 = len({_module_prefix(module, 1) for module in modules})
    p2 = len({_module_prefix(module, 2) for module in modules})
    if p1 <= _MODULE_MAP_MONOLITH_PACKAGE_CEILING:
        return "packages", 2
    if (
        p2 <= _MODULE_MAP_OVERMERGE_PACKAGE_CEILING
        and module_count > _MODULE_MAP_OVERMERGE_MODULE_FLOOR
    ):
        return "packages", 3
    if p2 <= _MODULE_MAP_MAX_PACKAGE_NODES:
        return "packages", 2
    if p1 <= _MODULE_MAP_MAX_PACKAGE_NODES:
        return "packages", 1
    return "packages", 2


def _aggregate_node_overlay(
    members: Sequence[str],
    *,
    overloaded_by_module: Mapping[str, Mapping[str, object]],
    cycle_modules: frozenset[str],
) -> dict[str, object]:
    scores: list[float] = []
    statuses: set[str] = set()
    reasons: set[str] = set()
    source_kinds: set[str] = set()
    fan_in = 0
    fan_out = 0
    in_cycle = False
    for module in members:
        item = overloaded_by_module.get(module, {})
        scores.append(_as_float(item.get("score")))
        statuses.add(str(item.get("candidate_status", _MODULE_MAP_NON_CANDIDATE)))
        reasons.update(
            str(reason) for reason in _as_sequence(item.get("candidate_reasons"))
        )
        source_kinds.add(str(item.get("source_kind", "")))
        fan_in += _as_int(item.get("fan_in"))
        fan_out += _as_int(item.get("fan_out"))
        in_cycle = in_cycle or module in cycle_modules
    if _MODULE_MAP_CANDIDATE in statuses:
        candidate_status = _MODULE_MAP_CANDIDATE
    elif _MODULE_MAP_RANKED_ONLY in statuses:
        candidate_status = _MODULE_MAP_RANKED_ONLY
    else:
        candidate_status = _MODULE_MAP_NON_CANDIDATE
    return {
        "fan_in": fan_in,
        "fan_out": fan_out,
        "source_kinds": sorted(source_kinds),
        "in_cycle": in_cycle,
        "overloaded": {
            "score": max(scores) if scores else 0.0,
            "candidate_status": candidate_status,
            "candidate_reasons": sorted(reasons),
        },
    }


def _module_map_node(
    node_id: str,
    *,
    package_depth: int | None,
    overloaded_by_module: Mapping[str, Mapping[str, object]],
    cycle_modules: frozenset[str],
) -> dict[str, object]:
    if package_depth is not None:
        members = sorted(
            module
            for module in overloaded_by_module
            if _module_prefix(module, package_depth) == node_id
        )
        overlay = _aggregate_node_overlay(
            members,
            overloaded_by_module=overloaded_by_module,
            cycle_modules=cycle_modules,
        )
        fan_in = _as_int(overlay["fan_in"])
        fan_out = _as_int(overlay["fan_out"])
        source_kinds: object = overlay["source_kinds"]
        in_cycle = bool(overlay["in_cycle"])
        overloaded: object = overlay["overloaded"]
    else:
        item = overloaded_by_module.get(node_id, {})
        fan_in = _as_int(item.get("fan_in"))
        fan_out = _as_int(item.get("fan_out"))
        source_kinds = sorted({str(item.get("source_kind", ""))}) if item else []
        in_cycle = node_id in cycle_modules
        overloaded = {
            "score": _as_float(item.get("score")),
            "candidate_status": str(
                item.get("candidate_status", _MODULE_MAP_NON_CANDIDATE)
            ),
            "candidate_reasons": sorted(
                str(reason) for reason in _as_sequence(item.get("candidate_reasons"))
            ),
        }
    return {
        "id": node_id,
        "label": node_id,
        "fan_in": fan_in,
        "fan_out": fan_out,
        "total_degree": fan_in + fan_out,
        "source_kinds": source_kinds,
        "in_cycle": in_cycle,
        "overloaded": overloaded,
    }


def _build_module_graph_view(
    module_edges: Sequence[tuple[str, str]],
    *,
    zoom: str,
    package_depth: int | None,
    dep_cycles: Sequence[Sequence[str]],
    longest_chains: Sequence[Sequence[str]],
    max_nodes: int,
    overloaded_by_module: Mapping[str, Mapping[str, object]],
    cycle_modules: frozenset[str],
) -> dict[str, object]:
    weights: Counter[tuple[str, str]] = Counter()
    node_id_fn: Callable[[str], str] | None
    if package_depth is not None:
        node_id_fn = _package_node_id(package_depth)
        for source, target in module_edges:
            edge = (
                _module_prefix(source, package_depth),
                _module_prefix(target, package_depth),
            )
            if edge[0] != edge[1]:
                weights[edge] += 1
    else:
        node_id_fn = None
        for source, target in module_edges:
            if source != target:
                weights[(source, target)] += 1
    nodes, sampled_edges, truncation = select_dependency_graph_nodes(
        sorted(weights),
        dep_cycles=dep_cycles,
        longest_chains=longest_chains,
        max_nodes=max_nodes,
        max_edges=_MODULE_MAP_MAX_EDGES,
        node_id_fn=node_id_fn,
    )
    return {
        "zoom": zoom,
        "package_depth": package_depth,
        "truncation": truncation,
        "nodes": [
            _module_map_node(
                node_id,
                package_depth=package_depth,
                overloaded_by_module=overloaded_by_module,
                cycle_modules=cycle_modules,
            )
            for node_id in nodes
        ],
        "edges": [
            {"source": source, "target": target, "weight": weights[(source, target)]}
            for source, target in sampled_edges
        ],
    }


def _unwind_signals(
    item: Mapping[str, object],
    *,
    chain_modules: frozenset[str],
    p90_fan_in: float,
) -> list[str]:
    reasons = {str(reason) for reason in _as_sequence(item.get("candidate_reasons"))}
    fan_in = _as_int(item.get("fan_in"))
    fan_out = _as_int(item.get("fan_out"))
    instability = _as_float(item.get("instability"))
    signals: list[str] = []
    if "dependency_pressure" in reasons:
        signals.append("dependency_pressure")
    if "hub_like_shape" in reasons:
        signals.append("hub_like_shape")
    if "repeated_import_pressure" in reasons:
        signals.append("repeated_import_pressure")
    if str(item.get("module")) in chain_modules:
        signals.append("chain_bottleneck")
    if instability >= 0.75 and fan_out >= 3:
        signals.append("high_instability")
    if fan_in >= p90_fan_in and fan_in > 2 * fan_out + 1:
        signals.append("central_sink")
    return signals


def _module_map_unwind_candidates(
    overloaded_items: Sequence[Mapping[str, object]],
    *,
    longest_chains: Sequence[Sequence[str]],
) -> list[dict[str, object]]:
    chain_modules = frozenset(str(node) for chain in longest_chains for node in chain)
    fan_in_sorted = sorted(_as_int(item.get("fan_in")) for item in overloaded_items)
    p90_fan_in = (
        _score_quantile([float(value) for value in fan_in_sorted], 0.9)
        if fan_in_sorted
        else 0.0
    )
    rows: list[dict[str, object]] = []
    for item in overloaded_items:
        signals = _unwind_signals(
            item, chain_modules=chain_modules, p90_fan_in=p90_fan_in
        )
        candidate_status = str(item.get("candidate_status", _MODULE_MAP_NON_CANDIDATE))
        emit = bool(signals) and (
            candidate_status == _MODULE_MAP_CANDIDATE
            or "chain_bottleneck" in signals
            or "high_instability" in signals
            or "central_sink" in signals
        )
        if not emit:
            continue
        rows.append(
            {
                "module": str(item.get("module")),
                "filepath": str(item.get("filepath", "")),
                "source_kind": str(item.get("source_kind", "")),
                "fan_in": _as_int(item.get("fan_in")),
                "fan_out": _as_int(item.get("fan_out")),
                "score": _as_float(item.get("score")),
                "dependency_score": _as_float(item.get("dependency_score")),
                "candidate_status": candidate_status,
                "signals": signals,
            }
        )
    rows.sort(
        key=lambda row: (
            -len(_as_sequence(row["signals"])),
            -_as_float(row["dependency_score"]),
            -_as_int(row["fan_in"]),
            -_as_int(row["fan_out"]),
            str(row["module"]),
        )
    )
    return rows[:_MODULE_MAP_UNWIND_CANDIDATE_CAP]


def _build_derived_module_map(
    metrics_payload: Mapping[str, object],
) -> dict[str, object]:
    families = _as_mapping(metrics_payload.get("families"))
    dependencies = _as_mapping(families.get("dependencies"))
    module_edges = _module_edges_from_items(_as_sequence(dependencies.get("items")))
    if not dependencies or not module_edges:
        return _module_map_unavailable_shell("dependencies_skipped")
    modules = sorted({node for edge in module_edges for node in edge})
    module_count = len(modules)
    dep_cycles = _string_paths(_as_sequence(dependencies.get("cycles")))
    longest_chains = _string_paths(_as_sequence(dependencies.get("longest_chains")))
    cycle_modules = frozenset(node for cycle in dep_cycles for node in cycle)
    overloaded = _as_mapping(families.get("overloaded_modules"))
    overloaded_items = [
        _as_mapping(item) for item in _as_sequence(overloaded.get("items"))
    ]
    overloaded_summary = _as_mapping(overloaded.get("summary"))
    population_status = str(overloaded_summary.get("population_status") or "ok")
    overloaded_by_module: dict[str, Mapping[str, object]] = {
        str(item.get("module")): item for item in overloaded_items
    }
    zoom, package_depth = _module_map_zoom_decision(modules, module_count)
    unwind = _module_map_unwind_candidates(
        overloaded_items, longest_chains=longest_chains
    )
    overloaded_candidate_count = sum(
        1
        for item in overloaded_items
        if str(item.get("candidate_status")) == _MODULE_MAP_CANDIDATE
    )
    return {
        "schema_version": _MODULE_MAP_SCHEMA_VERSION,
        "scope": "report_only",
        "default_zoom": zoom,
        "summary": {
            "available": True,
            "module_count": module_count,
            "package_count_depth2": len(
                {_module_prefix(module, 2) for module in modules}
            ),
            "edge_count": len(set(module_edges)),
            "unwind_candidate_count": len(unwind),
            "overloaded_candidate_count": overloaded_candidate_count,
            "overloaded_population_status": population_status,
        },
        "graph_packages": _build_module_graph_view(
            module_edges,
            zoom="packages",
            package_depth=package_depth,
            dep_cycles=dep_cycles,
            longest_chains=longest_chains,
            max_nodes=_MODULE_MAP_MAX_PACKAGE_NODES,
            overloaded_by_module=overloaded_by_module,
            cycle_modules=cycle_modules,
        ),
        "graph_modules": _build_module_graph_view(
            module_edges,
            zoom="modules",
            package_depth=None,
            dep_cycles=dep_cycles,
            longest_chains=longest_chains,
            max_nodes=_MODULE_MAP_MAX_MODULE_NODES,
            overloaded_by_module=overloaded_by_module,
            cycle_modules=cycle_modules,
        ),
        "unwind_candidates": unwind,
    }
