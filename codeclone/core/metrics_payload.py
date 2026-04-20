# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from ..domain.findings import CATEGORY_COHESION, CATEGORY_COMPLEXITY, CATEGORY_COUPLING
from ..domain.quality import CONFIDENCE_HIGH, RISK_LOW
from ..metrics import build_overloaded_modules_payload
from ..models import (
    ClassMetrics,
    CoverageJoinResult,
    DeadItem,
    GroupItemLike,
    MetricsDiff,
    ModuleDep,
    ProjectMetrics,
)
from ..suppressions import DEAD_CODE_RULE_ID, INLINE_CODECLONE_SUPPRESSION_SOURCE
from ..utils.coerce import as_int, as_str
from .api_surface_payload import (
    _api_surface_rows,
    _api_surface_summary,
    _breaking_api_surface_rows,
)
from .coverage_payload import (
    _coverage_adoption_rows,
    _coverage_join_rows,
    _coverage_join_summary,
    _permille,
)


def _enrich_metrics_report_payload(
    *,
    metrics_payload: Mapping[str, object],
    metrics_diff: MetricsDiff | None,
    coverage_adoption_diff_available: bool,
    api_surface_diff_available: bool,
) -> dict[str, object]:
    enriched = {
        key: (dict(value) if isinstance(value, Mapping) else value)
        for key, value in metrics_payload.items()
    }
    coverage_adoption = dict(
        cast("Mapping[str, object]", enriched.get("coverage_adoption", {}))
    )
    coverage_summary = dict(
        cast("Mapping[str, object]", coverage_adoption.get("summary", {}))
    )
    if coverage_summary:
        coverage_summary["baseline_diff_available"] = coverage_adoption_diff_available
        coverage_summary["param_delta"] = (
            int(metrics_diff.typing_param_permille_delta)
            if metrics_diff is not None and coverage_adoption_diff_available
            else 0
        )
        coverage_summary["return_delta"] = (
            int(metrics_diff.typing_return_permille_delta)
            if metrics_diff is not None and coverage_adoption_diff_available
            else 0
        )
        coverage_summary["docstring_delta"] = (
            int(metrics_diff.docstring_permille_delta)
            if metrics_diff is not None and coverage_adoption_diff_available
            else 0
        )
        coverage_adoption["summary"] = coverage_summary
        enriched["coverage_adoption"] = coverage_adoption

    api_surface = dict(cast("Mapping[str, object]", enriched.get("api_surface", {})))
    api_summary = dict(cast("Mapping[str, object]", api_surface.get("summary", {})))
    api_items = list(cast("Sequence[object]", api_surface.get("items", ())))
    if api_summary:
        api_summary["baseline_diff_available"] = api_surface_diff_available
        api_summary["added"] = (
            len(metrics_diff.new_api_symbols)
            if metrics_diff is not None and api_surface_diff_available
            else 0
        )
        api_summary["breaking"] = (
            len(metrics_diff.new_api_breaking_changes)
            if metrics_diff is not None and api_surface_diff_available
            else 0
        )
        api_surface["summary"] = api_summary
    if (
        metrics_diff is not None
        and api_surface_diff_available
        and metrics_diff.new_api_breaking_changes
    ):
        api_items.extend(
            _breaking_api_surface_rows(metrics_diff.new_api_breaking_changes)
        )
    api_surface["items"] = api_items
    if api_surface:
        enriched["api_surface"] = api_surface
    return enriched


def build_metrics_report_payload(
    *,
    scan_root: str = "",
    project_metrics: ProjectMetrics,
    coverage_join: CoverageJoinResult | None = None,
    units: Sequence[GroupItemLike],
    class_metrics: Sequence[ClassMetrics],
    module_deps: Sequence[ModuleDep] = (),
    source_stats_by_file: Sequence[tuple[str, int, int, int, int]] = (),
    suppressed_dead_code: Sequence[DeadItem] = (),
) -> dict[str, object]:
    sorted_units = sorted(
        units,
        key=lambda item: (
            as_int(item.get("cyclomatic_complexity"), 0),
            as_int(item.get("nesting_depth"), 0),
            as_str(item.get("qualname")),
        ),
        reverse=True,
    )
    complexity_rows = [
        {
            "qualname": as_str(item.get("qualname")),
            "filepath": as_str(item.get("filepath")),
            "start_line": as_int(item.get("start_line"), 0),
            "end_line": as_int(item.get("end_line"), 0),
            "cyclomatic_complexity": as_int(item.get("cyclomatic_complexity"), 1),
            "nesting_depth": as_int(item.get("nesting_depth"), 0),
            "risk": as_str(item.get("risk"), RISK_LOW),
        }
        for item in sorted_units
    ]
    classes_sorted = sorted(
        class_metrics,
        key=lambda item: (item.cbo, item.lcom4, item.qualname),
        reverse=True,
    )
    coupling_rows = [
        {
            "qualname": metric.qualname,
            "filepath": metric.filepath,
            "start_line": metric.start_line,
            "end_line": metric.end_line,
            "cbo": metric.cbo,
            "risk": metric.risk_coupling,
            "coupled_classes": list(metric.coupled_classes),
        }
        for metric in classes_sorted
    ]
    cohesion_rows = [
        {
            "qualname": metric.qualname,
            "filepath": metric.filepath,
            "start_line": metric.start_line,
            "end_line": metric.end_line,
            "lcom4": metric.lcom4,
            "risk": metric.risk_cohesion,
            "method_count": metric.method_count,
            "instance_var_count": metric.instance_var_count,
        }
        for metric in classes_sorted
    ]
    active_dead_items = tuple(project_metrics.dead_code)
    suppressed_dead_items = tuple(suppressed_dead_code)
    coverage_adoption_rows = _coverage_adoption_rows(project_metrics)
    api_surface_summary = _api_surface_summary(project_metrics.api_surface)
    api_surface_items = _api_surface_rows(project_metrics.api_surface)
    coverage_join_summary = _coverage_join_summary(coverage_join)
    coverage_join_items = _coverage_join_rows(coverage_join)

    def _serialize_dead_item(
        item: DeadItem,
        *,
        suppressed: bool = False,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "qualname": item.qualname,
            "filepath": item.filepath,
            "start_line": item.start_line,
            "end_line": item.end_line,
            "kind": item.kind,
            "confidence": item.confidence,
        }
        if suppressed:
            payload["suppressed_by"] = [
                {
                    "rule": DEAD_CODE_RULE_ID,
                    "source": INLINE_CODECLONE_SUPPRESSION_SOURCE,
                }
            ]
        return payload

    payload = {
        CATEGORY_COMPLEXITY: {
            "functions": complexity_rows,
            "summary": {
                "total": len(complexity_rows),
                "average": round(project_metrics.complexity_avg, 2),
                "max": project_metrics.complexity_max,
                "high_risk": len(project_metrics.high_risk_functions),
            },
        },
        CATEGORY_COUPLING: {
            "classes": coupling_rows,
            "summary": {
                "total": len(coupling_rows),
                "average": round(project_metrics.coupling_avg, 2),
                "max": project_metrics.coupling_max,
                "high_risk": len(project_metrics.high_risk_classes),
            },
        },
        CATEGORY_COHESION: {
            "classes": cohesion_rows,
            "summary": {
                "total": len(cohesion_rows),
                "average": round(project_metrics.cohesion_avg, 2),
                "max": project_metrics.cohesion_max,
                "low_cohesion": len(project_metrics.low_cohesion_classes),
            },
        },
        "dependencies": {
            "modules": project_metrics.dependency_modules,
            "edges": project_metrics.dependency_edges,
            "max_depth": project_metrics.dependency_max_depth,
            "cycles": [list(cycle) for cycle in project_metrics.dependency_cycles],
            "longest_chains": [
                list(chain) for chain in project_metrics.dependency_longest_chains
            ],
            "edge_list": [
                {
                    "source": edge.source,
                    "target": edge.target,
                    "import_type": edge.import_type,
                    "line": edge.line,
                }
                for edge in project_metrics.dependency_edge_list
            ],
        },
        "dead_code": {
            "items": [_serialize_dead_item(item) for item in active_dead_items],
            "suppressed_items": [
                _serialize_dead_item(item, suppressed=True)
                for item in suppressed_dead_items
            ],
            "summary": {
                "total": len(active_dead_items),
                "critical": sum(
                    1
                    for item in active_dead_items
                    if item.confidence == CONFIDENCE_HIGH
                ),
                "high_confidence": sum(
                    1
                    for item in active_dead_items
                    if item.confidence == CONFIDENCE_HIGH
                ),
                "suppressed": len(suppressed_dead_items),
            },
        },
        "health": {
            "score": project_metrics.health.total,
            "grade": project_metrics.health.grade,
            "dimensions": dict(project_metrics.health.dimensions),
        },
        "coverage_adoption": {
            "summary": {
                "modules": len(coverage_adoption_rows),
                "params_total": project_metrics.typing_param_total,
                "params_annotated": project_metrics.typing_param_annotated,
                "param_permille": _permille(
                    project_metrics.typing_param_annotated,
                    project_metrics.typing_param_total,
                ),
                "returns_total": project_metrics.typing_return_total,
                "returns_annotated": project_metrics.typing_return_annotated,
                "return_permille": _permille(
                    project_metrics.typing_return_annotated,
                    project_metrics.typing_return_total,
                ),
                "public_symbol_total": project_metrics.docstring_public_total,
                "public_symbol_documented": project_metrics.docstring_public_documented,
                "docstring_permille": _permille(
                    project_metrics.docstring_public_documented,
                    project_metrics.docstring_public_total,
                ),
                "typing_any_count": project_metrics.typing_any_count,
            },
            "items": coverage_adoption_rows,
        },
        "api_surface": {
            "summary": dict(api_surface_summary),
            "items": api_surface_items,
        },
        "overloaded_modules": build_overloaded_modules_payload(
            scan_root=scan_root,
            source_stats_by_file=source_stats_by_file,
            units=units,
            class_metrics=class_metrics,
            module_deps=module_deps,
        ),
    }
    if coverage_join is not None:
        payload["coverage_join"] = {
            "summary": dict(coverage_join_summary),
            "items": coverage_join_items,
        }
    return payload
