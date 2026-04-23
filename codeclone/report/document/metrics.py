# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping

from ...analysis.suppressions import INLINE_CODECLONE_SUPPRESSION_SOURCE
from ...domain.findings import (
    CATEGORY_COHESION,
    CATEGORY_COMPLEXITY,
    CATEGORY_COUPLING,
    FAMILY_DEAD_CODE,
)
from ...domain.quality import (
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    RISK_LOW,
)
from ...domain.source_scope import (
    SOURCE_KIND_OTHER,
)
from ...metrics.registry import METRIC_FAMILIES
from ...utils.coerce import as_float as _as_float
from ...utils.coerce import as_int as _as_int
from ...utils.coerce import as_mapping as _as_mapping
from ...utils.coerce import as_sequence as _as_sequence
from ._common import (
    _contract_path,
    _normalize_nested_string_rows,
    _optional_str,
)

_OVERLOADED_MODULES_FAMILY = "overloaded_modules"

_COVERAGE_ADOPTION_FAMILY = "coverage_adoption"

_API_SURFACE_FAMILY = "api_surface"

_COVERAGE_JOIN_FAMILY = "coverage_join"


def _normalize_metrics_families(
    metrics: Mapping[str, object] | None,
    *,
    scan_root: str,
) -> dict[str, object]:
    metrics_map = _as_mapping(metrics)
    complexity = _as_mapping(metrics_map.get(CATEGORY_COMPLEXITY))
    complexity_items = sorted(
        (
            {
                "qualname": str(item_map.get("qualname", "")),
                "relative_path": _contract_path(
                    item_map.get("filepath", ""),
                    scan_root=scan_root,
                )[0]
                or "",
                "start_line": _as_int(item_map.get("start_line")),
                "end_line": _as_int(item_map.get("end_line")),
                "cyclomatic_complexity": _as_int(
                    item_map.get("cyclomatic_complexity"),
                    1,
                ),
                "nesting_depth": _as_int(item_map.get("nesting_depth")),
                "risk": str(item_map.get("risk", RISK_LOW)),
            }
            for item in _as_sequence(complexity.get("functions"))
            for item_map in (_as_mapping(item),)
        ),
        key=lambda item: (
            item["relative_path"],
            item["start_line"],
            item["end_line"],
            item["qualname"],
        ),
    )

    coupling = _as_mapping(metrics_map.get(CATEGORY_COUPLING))
    coupling_items = sorted(
        (
            {
                "qualname": str(item_map.get("qualname", "")),
                "relative_path": _contract_path(
                    item_map.get("filepath", ""),
                    scan_root=scan_root,
                )[0]
                or "",
                "start_line": _as_int(item_map.get("start_line")),
                "end_line": _as_int(item_map.get("end_line")),
                "cbo": _as_int(item_map.get("cbo")),
                "risk": str(item_map.get("risk", RISK_LOW)),
                "coupled_classes": sorted(
                    {
                        str(name)
                        for name in _as_sequence(item_map.get("coupled_classes"))
                        if str(name).strip()
                    }
                ),
            }
            for item in _as_sequence(coupling.get("classes"))
            for item_map in (_as_mapping(item),)
        ),
        key=lambda item: (
            item["relative_path"],
            item["start_line"],
            item["end_line"],
            item["qualname"],
        ),
    )

    cohesion = _as_mapping(metrics_map.get(CATEGORY_COHESION))
    cohesion_items = sorted(
        (
            {
                "qualname": str(item_map.get("qualname", "")),
                "relative_path": _contract_path(
                    item_map.get("filepath", ""),
                    scan_root=scan_root,
                )[0]
                or "",
                "start_line": _as_int(item_map.get("start_line")),
                "end_line": _as_int(item_map.get("end_line")),
                "lcom4": _as_int(item_map.get("lcom4")),
                "risk": str(item_map.get("risk", RISK_LOW)),
                "method_count": _as_int(item_map.get("method_count")),
                "instance_var_count": _as_int(item_map.get("instance_var_count")),
            }
            for item in _as_sequence(cohesion.get("classes"))
            for item_map in (_as_mapping(item),)
        ),
        key=lambda item: (
            item["relative_path"],
            item["start_line"],
            item["end_line"],
            item["qualname"],
        ),
    )

    dependencies = _as_mapping(metrics_map.get("dependencies"))
    dependency_edges = sorted(
        (
            {
                "source": str(item_map.get("source", "")),
                "target": str(item_map.get("target", "")),
                "import_type": str(item_map.get("import_type", "")),
                "line": _as_int(item_map.get("line")),
            }
            for item in _as_sequence(dependencies.get("edge_list"))
            for item_map in (_as_mapping(item),)
        ),
        key=lambda item: (
            item["source"],
            item["target"],
            item["import_type"],
            item["line"],
        ),
    )
    dependency_cycles = _normalize_nested_string_rows(dependencies.get("cycles"))
    longest_chains = _normalize_nested_string_rows(dependencies.get("longest_chains"))

    dead_code = _as_mapping(metrics_map.get(FAMILY_DEAD_CODE))

    def _normalize_suppressed_by(
        raw_bindings: object,
    ) -> list[dict[str, str]]:
        normalized_bindings = sorted(
            {
                (
                    str(binding_map.get("rule", "")).strip(),
                    str(binding_map.get("source", "")).strip(),
                )
                for binding in _as_sequence(raw_bindings)
                for binding_map in (_as_mapping(binding),)
                if str(binding_map.get("rule", "")).strip()
            },
            key=lambda item: (item[0], item[1]),
        )
        if not normalized_bindings:
            return []
        return [
            {
                "rule": rule,
                "source": source or INLINE_CODECLONE_SUPPRESSION_SOURCE,
            }
            for rule, source in normalized_bindings
        ]

    dead_items = sorted(
        (
            {
                "qualname": str(item_map.get("qualname", "")),
                "relative_path": _contract_path(
                    item_map.get("filepath", ""),
                    scan_root=scan_root,
                )[0]
                or "",
                "start_line": _as_int(item_map.get("start_line")),
                "end_line": _as_int(item_map.get("end_line")),
                "kind": str(item_map.get("kind", "")),
                "confidence": str(item_map.get("confidence", CONFIDENCE_MEDIUM)),
            }
            for item in _as_sequence(dead_code.get("items"))
            for item_map in (_as_mapping(item),)
        ),
        key=lambda item: (
            item["relative_path"],
            item["start_line"],
            item["end_line"],
            item["qualname"],
            item["kind"],
        ),
    )
    dead_suppressed_items = sorted(
        (
            {
                "qualname": str(item_map.get("qualname", "")),
                "relative_path": _contract_path(
                    item_map.get("filepath", ""),
                    scan_root=scan_root,
                )[0]
                or "",
                "start_line": _as_int(item_map.get("start_line")),
                "end_line": _as_int(item_map.get("end_line")),
                "kind": str(item_map.get("kind", "")),
                "confidence": str(item_map.get("confidence", CONFIDENCE_MEDIUM)),
                "suppressed_by": _normalize_suppressed_by(
                    item_map.get("suppressed_by")
                ),
            }
            for item in _as_sequence(dead_code.get("suppressed_items"))
            for item_map in (_as_mapping(item),)
        ),
        key=lambda item: (
            item["relative_path"],
            item["start_line"],
            item["end_line"],
            item["qualname"],
            item["kind"],
            item["confidence"],
            tuple(
                (
                    str(_as_mapping(binding).get("rule", "")),
                    str(_as_mapping(binding).get("source", "")),
                )
                for binding in _as_sequence(item.get("suppressed_by"))
            ),
        ),
    )
    for item in dead_suppressed_items:
        suppressed_by = _as_sequence(item.get("suppressed_by"))
        first_binding = _as_mapping(suppressed_by[0]) if suppressed_by else {}
        item["suppression_rule"] = str(first_binding.get("rule", ""))
        item["suppression_source"] = str(first_binding.get("source", ""))

    health = _as_mapping(metrics_map.get("health"))
    health_dimensions = {
        str(key): _as_int(value)
        for key, value in sorted(_as_mapping(health.get("dimensions")).items())
    }
    overloaded_modules = _as_mapping(metrics_map.get(_OVERLOADED_MODULES_FAMILY))
    overloaded_modules_detection = _as_mapping(overloaded_modules.get("detection"))
    overloaded_module_items = sorted(
        (
            {
                "module": str(item_map.get("module", "")).strip(),
                "relative_path": _contract_path(
                    item_map.get("filepath", ""),
                    scan_root=scan_root,
                )[0]
                or "",
                "source_kind": str(item_map.get("source_kind", SOURCE_KIND_OTHER)),
                "loc": _as_int(item_map.get("loc")),
                "functions": _as_int(item_map.get("functions")),
                "methods": _as_int(item_map.get("methods")),
                "classes": _as_int(item_map.get("classes")),
                "callable_count": _as_int(item_map.get("callable_count")),
                "complexity_total": _as_int(item_map.get("complexity_total")),
                "complexity_max": _as_int(item_map.get("complexity_max")),
                "fan_in": _as_int(item_map.get("fan_in")),
                "fan_out": _as_int(item_map.get("fan_out")),
                "total_deps": _as_int(item_map.get("total_deps")),
                "import_edges": _as_int(item_map.get("import_edges")),
                "reimport_edges": _as_int(item_map.get("reimport_edges")),
                "reimport_ratio": round(
                    _as_float(item_map.get("reimport_ratio")),
                    4,
                ),
                "instability": round(_as_float(item_map.get("instability")), 4),
                "hub_balance": round(_as_float(item_map.get("hub_balance")), 4),
                "size_score": round(_as_float(item_map.get("size_score")), 4),
                "dependency_score": round(
                    _as_float(item_map.get("dependency_score")),
                    4,
                ),
                "shape_score": round(_as_float(item_map.get("shape_score")), 4),
                "score": round(_as_float(item_map.get("score")), 4),
                "candidate_status": str(
                    item_map.get("candidate_status", "non_candidate")
                ),
                "candidate_reasons": [
                    str(reason)
                    for reason in _as_sequence(item_map.get("candidate_reasons"))
                    if str(reason).strip()
                ],
            }
            for item in _as_sequence(overloaded_modules.get("items"))
            for item_map in (_as_mapping(item),)
        ),
        key=lambda item: (
            {"candidate": 0, "ranked_only": 1, "non_candidate": 2}.get(
                str(item["candidate_status"]),
                3,
            ),
            -_as_float(item["score"]),
            -_as_float(item["size_score"]),
            -_as_float(item["dependency_score"]),
            item["relative_path"],
            item["module"],
        ),
    )

    complexity_summary = _as_mapping(complexity.get("summary"))
    coupling_summary = _as_mapping(coupling.get("summary"))
    cohesion_summary = _as_mapping(cohesion.get("summary"))
    dead_code_summary = _as_mapping(dead_code.get("summary"))
    overloaded_modules_summary = _as_mapping(overloaded_modules.get("summary"))
    coverage_adoption = _as_mapping(metrics_map.get(_COVERAGE_ADOPTION_FAMILY))
    coverage_adoption_summary = _as_mapping(coverage_adoption.get("summary"))
    coverage_adoption_items = sorted(
        (
            {
                "module": str(item_map.get("module", "")).strip(),
                "relative_path": _contract_path(
                    item_map.get("filepath", ""),
                    scan_root=scan_root,
                )[0]
                or "",
                "callable_count": _as_int(item_map.get("callable_count")),
                "params_total": _as_int(item_map.get("params_total")),
                "params_annotated": _as_int(item_map.get("params_annotated")),
                "param_permille": _as_int(item_map.get("param_permille")),
                "returns_total": _as_int(item_map.get("returns_total")),
                "returns_annotated": _as_int(item_map.get("returns_annotated")),
                "return_permille": _as_int(item_map.get("return_permille")),
                "any_annotation_count": _as_int(item_map.get("any_annotation_count")),
                "public_symbol_total": _as_int(item_map.get("public_symbol_total")),
                "public_symbol_documented": _as_int(
                    item_map.get("public_symbol_documented")
                ),
                "docstring_permille": _as_int(item_map.get("docstring_permille")),
            }
            for item in _as_sequence(coverage_adoption.get("items"))
            for item_map in (_as_mapping(item),)
        ),
        key=lambda item: (
            item["relative_path"],
            item["module"],
        ),
    )
    api_surface = _as_mapping(metrics_map.get(_API_SURFACE_FAMILY))
    api_surface_summary = _as_mapping(api_surface.get("summary"))
    api_surface_items = sorted(
        (
            {
                "record_kind": str(item_map.get("record_kind", "symbol")),
                "module": str(item_map.get("module", "")).strip(),
                "relative_path": _contract_path(
                    item_map.get("filepath", ""),
                    scan_root=scan_root,
                )[0]
                or "",
                "qualname": str(item_map.get("qualname", "")),
                "start_line": _as_int(item_map.get("start_line")),
                "end_line": _as_int(item_map.get("end_line")),
                "symbol_kind": str(item_map.get("symbol_kind", "")),
                "exported_via": _optional_str(item_map.get("exported_via")),
                "params_total": _as_int(item_map.get("params_total")),
                "params": [
                    {
                        "name": str(param_map.get("name", "")),
                        "kind": str(param_map.get("kind", "")),
                        "has_default": bool(param_map.get("has_default")),
                        "annotated": bool(param_map.get("annotated")),
                    }
                    for param in _as_sequence(item_map.get("params"))
                    for param_map in (_as_mapping(param),)
                ],
                "returns_annotated": bool(item_map.get("returns_annotated")),
                "change_kind": _optional_str(item_map.get("change_kind")),
                "detail": _optional_str(item_map.get("detail")),
            }
            for item in _as_sequence(api_surface.get("items"))
            for item_map in (_as_mapping(item),)
        ),
        key=lambda item: (
            item["relative_path"],
            item["start_line"],
            item["end_line"],
            item["qualname"],
            item["record_kind"],
        ),
    )
    coverage_join = _as_mapping(metrics_map.get(_COVERAGE_JOIN_FAMILY))
    coverage_join_summary = _as_mapping(coverage_join.get("summary"))
    coverage_join_items = sorted(
        (
            {
                "relative_path": _contract_path(
                    item_map.get("filepath", ""),
                    scan_root=scan_root,
                )[0]
                or "",
                "qualname": str(item_map.get("qualname", "")).strip(),
                "start_line": _as_int(item_map.get("start_line")),
                "end_line": _as_int(item_map.get("end_line")),
                "cyclomatic_complexity": _as_int(
                    item_map.get("cyclomatic_complexity"),
                    1,
                ),
                "risk": str(item_map.get("risk", RISK_LOW)).strip() or RISK_LOW,
                "executable_lines": _as_int(item_map.get("executable_lines")),
                "covered_lines": _as_int(item_map.get("covered_lines")),
                "coverage_permille": _as_int(item_map.get("coverage_permille")),
                "coverage_status": str(item_map.get("coverage_status", "")).strip(),
                "coverage_hotspot": bool(item_map.get("coverage_hotspot")),
                "scope_gap_hotspot": bool(item_map.get("scope_gap_hotspot")),
            }
            for item in _as_sequence(coverage_join.get("items"))
            for item_map in (_as_mapping(item),)
        ),
        key=lambda item: (
            0 if bool(item["coverage_hotspot"]) else 1,
            0 if bool(item["scope_gap_hotspot"]) else 1,
            {"high": 0, "medium": 1, "low": 2}.get(str(item["risk"]), 3),
            _as_int(item["coverage_permille"]),
            -_as_int(item["cyclomatic_complexity"]),
            item["relative_path"],
            _as_int(item["start_line"]),
            item["qualname"],
        ),
    )
    dead_high_confidence = sum(
        1
        for item in dead_items
        if str(_as_mapping(item).get("confidence", "")).strip().lower()
        == CONFIDENCE_HIGH
    )

    family_sections: dict[str, object] = {
        CATEGORY_COMPLEXITY: {
            "summary": {
                "total": len(complexity_items),
                "average": round(_as_float(complexity_summary.get("average")), 2),
                "max": _as_int(complexity_summary.get("max")),
                "high_risk": _as_int(complexity_summary.get("high_risk")),
            },
            "items": complexity_items,
            "items_truncated": False,
        },
        CATEGORY_COUPLING: {
            "summary": {
                "total": len(coupling_items),
                "average": round(_as_float(coupling_summary.get("average")), 2),
                "max": _as_int(coupling_summary.get("max")),
                "high_risk": _as_int(coupling_summary.get("high_risk")),
            },
            "items": coupling_items,
            "items_truncated": False,
        },
        CATEGORY_COHESION: {
            "summary": {
                "total": len(cohesion_items),
                "average": round(_as_float(cohesion_summary.get("average")), 2),
                "max": _as_int(cohesion_summary.get("max")),
                "low_cohesion": _as_int(cohesion_summary.get("low_cohesion")),
            },
            "items": cohesion_items,
            "items_truncated": False,
        },
        "dependencies": {
            "summary": {
                "modules": _as_int(dependencies.get("modules")),
                "edges": _as_int(dependencies.get("edges")),
                "cycles": len(dependency_cycles),
                "max_depth": _as_int(dependencies.get("max_depth")),
                "avg_depth": round(_as_float(dependencies.get("avg_depth")), 2),
                "p95_depth": _as_int(dependencies.get("p95_depth")),
            },
            "items": dependency_edges,
            "cycles": dependency_cycles,
            "longest_chains": longest_chains,
            "items_truncated": False,
        },
        FAMILY_DEAD_CODE: {
            "summary": {
                "total": len(dead_items),
                "high_confidence": dead_high_confidence
                or _as_int(
                    dead_code_summary.get(
                        "high_confidence", dead_code_summary.get("critical")
                    )
                ),
                "suppressed": len(dead_suppressed_items)
                or _as_int(dead_code_summary.get("suppressed")),
            },
            "items": dead_items,
            "suppressed_items": dead_suppressed_items,
            "items_truncated": False,
        },
        "health": {
            "summary": {
                "score": _as_int(health.get("score")),
                "grade": str(health.get("grade", "")),
                "dimensions": health_dimensions,
            },
            "items": [],
            "items_truncated": False,
        },
        _COVERAGE_ADOPTION_FAMILY: {
            "summary": {
                "modules": len(coverage_adoption_items),
                "params_total": _as_int(coverage_adoption_summary.get("params_total")),
                "params_annotated": _as_int(
                    coverage_adoption_summary.get("params_annotated")
                ),
                "param_permille": _as_int(
                    coverage_adoption_summary.get("param_permille")
                ),
                "baseline_diff_available": bool(
                    coverage_adoption_summary.get("baseline_diff_available")
                ),
                "param_delta": _as_int(coverage_adoption_summary.get("param_delta")),
                "returns_total": _as_int(
                    coverage_adoption_summary.get("returns_total")
                ),
                "returns_annotated": _as_int(
                    coverage_adoption_summary.get("returns_annotated")
                ),
                "return_permille": _as_int(
                    coverage_adoption_summary.get("return_permille")
                ),
                "return_delta": _as_int(coverage_adoption_summary.get("return_delta")),
                "public_symbol_total": _as_int(
                    coverage_adoption_summary.get("public_symbol_total")
                ),
                "public_symbol_documented": _as_int(
                    coverage_adoption_summary.get("public_symbol_documented")
                ),
                "docstring_permille": _as_int(
                    coverage_adoption_summary.get("docstring_permille")
                ),
                "docstring_delta": _as_int(
                    coverage_adoption_summary.get("docstring_delta")
                ),
                "typing_any_count": _as_int(
                    coverage_adoption_summary.get("typing_any_count")
                ),
            },
            "items": coverage_adoption_items,
            "items_truncated": False,
        },
        _API_SURFACE_FAMILY: {
            "summary": {
                "enabled": bool(api_surface_summary.get("enabled")),
                "baseline_diff_available": bool(
                    api_surface_summary.get("baseline_diff_available")
                ),
                "modules": _as_int(api_surface_summary.get("modules")),
                "public_symbols": _as_int(api_surface_summary.get("public_symbols")),
                "added": _as_int(api_surface_summary.get("added")),
                "breaking": _as_int(api_surface_summary.get("breaking")),
                "strict_types": bool(api_surface_summary.get("strict_types")),
            },
            "items": api_surface_items,
            "items_truncated": False,
        },
        _OVERLOADED_MODULES_FAMILY: {
            "summary": {
                "total": len(overloaded_module_items),
                "candidates": _as_int(overloaded_modules_summary.get("candidates")),
                "population_status": str(
                    overloaded_modules_summary.get("population_status", "limited")
                ),
                "top_score": round(
                    _as_float(overloaded_modules_summary.get("top_score")),
                    4,
                ),
                "average_score": round(
                    _as_float(overloaded_modules_summary.get("average_score")),
                    4,
                ),
                "candidate_score_cutoff": round(
                    _as_float(overloaded_modules_summary.get("candidate_score_cutoff")),
                    4,
                ),
            },
            "detection": {
                "version": str(overloaded_modules_detection.get("version", "1")),
                "scope": str(overloaded_modules_detection.get("scope", "report_only")),
                "strategy": str(
                    overloaded_modules_detection.get(
                        "strategy",
                        "project_relative_composite",
                    )
                ),
                "minimum_population": _as_int(
                    overloaded_modules_detection.get("minimum_population"),
                ),
                "size_signals": [
                    str(signal)
                    for signal in _as_sequence(
                        overloaded_modules_detection.get("size_signals")
                    )
                    if str(signal).strip()
                ],
                "dependency_signals": [
                    str(signal)
                    for signal in _as_sequence(
                        overloaded_modules_detection.get("dependency_signals")
                    )
                    if str(signal).strip()
                ],
                "shape_signals": [
                    str(signal)
                    for signal in _as_sequence(
                        overloaded_modules_detection.get("shape_signals")
                    )
                    if str(signal).strip()
                ],
            },
            "items": overloaded_module_items,
            "items_truncated": False,
        },
    }
    if coverage_join_summary or coverage_join_items or coverage_join:
        family_sections[_COVERAGE_JOIN_FAMILY] = {
            "summary": {
                "status": str(coverage_join_summary.get("status", "")),
                "source": _contract_path(
                    coverage_join_summary.get("source", ""),
                    scan_root=scan_root,
                )[0],
                "files": _as_int(coverage_join_summary.get("files")),
                "units": _as_int(coverage_join_summary.get("units")),
                "measured_units": _as_int(coverage_join_summary.get("measured_units")),
                "overall_executable_lines": _as_int(
                    coverage_join_summary.get("overall_executable_lines")
                ),
                "overall_covered_lines": _as_int(
                    coverage_join_summary.get("overall_covered_lines")
                ),
                "overall_permille": _as_int(
                    coverage_join_summary.get("overall_permille")
                ),
                "missing_from_report_units": _as_int(
                    coverage_join_summary.get("missing_from_report_units")
                ),
                "coverage_hotspots": _as_int(
                    coverage_join_summary.get("coverage_hotspots")
                ),
                "scope_gap_hotspots": _as_int(
                    coverage_join_summary.get("scope_gap_hotspots")
                ),
                "hotspot_threshold_percent": _as_int(
                    coverage_join_summary.get("hotspot_threshold_percent")
                ),
                "invalid_reason": _optional_str(
                    coverage_join_summary.get("invalid_reason")
                ),
            },
            "items": coverage_join_items,
            "items_truncated": False,
        }
    normalized: dict[str, object] = {}
    for family in METRIC_FAMILIES.values():
        section = family.report_section
        if section in family_sections:
            normalized[section] = family_sections[section]
    return normalized


def _build_metrics_payload(
    metrics: Mapping[str, object] | None,
    *,
    scan_root: str,
) -> dict[str, object]:
    families = _normalize_metrics_families(metrics, scan_root=scan_root)
    return {
        "summary": {
            family_name: _as_mapping(_as_mapping(family_payload).get("summary"))
            for family_name, family_payload in families.items()
        },
        "families": families,
    }
