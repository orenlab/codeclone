# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from collections.abc import Sequence
from math import floor

from .._coerce import as_float, as_int, as_sequence, as_str
from ..domain.source_scope import (
    SOURCE_KIND_FIXTURES,
    SOURCE_KIND_OTHER,
    SOURCE_KIND_PRODUCTION,
    SOURCE_KIND_TESTS,
)
from ..models import ClassMetrics, GroupItemLike, ModuleDep
from ..scanner import module_name_from_path

_CANDIDATE = "candidate"
_NON_CANDIDATE = "non_candidate"
_RANKED_ONLY = "ranked_only"
_POPULATION_STATUS_OK = "ok"
_POPULATION_STATUS_LIMITED = "limited"
_MINIMUM_POPULATION = 20

_SIZE_PRESSURE = "size_pressure"
_DEPENDENCY_PRESSURE = "dependency_pressure"
_HUB_LIKE_SHAPE = "hub_like_shape"
_REPEATED_IMPORT_PRESSURE = "repeated_import_pressure"


def _normalize_path(value: str) -> str:
    return value.replace("\\", "/").strip()


def _source_kind(filepath: str, *, scan_root: str) -> str:
    normalized_path = _normalize_path(filepath)
    normalized_root = _normalize_path(scan_root).rstrip("/")
    if normalized_root:
        prefix = normalized_root + "/"
        if normalized_path.startswith(prefix):
            normalized_path = normalized_path[len(prefix) :]
    parts = [
        part for part in normalized_path.lower().split("/") if part and part != "."
    ]
    if not parts:
        return SOURCE_KIND_OTHER
    for idx, part in enumerate(parts):
        if part != SOURCE_KIND_TESTS:
            continue
        if idx + 1 < len(parts) and parts[idx + 1] == SOURCE_KIND_FIXTURES:
            return SOURCE_KIND_FIXTURES
        return SOURCE_KIND_TESTS
    return SOURCE_KIND_PRODUCTION


def _score_quantile(sorted_values: Sequence[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    clamped_q = min(1.0, max(0.0, q))
    position = clamped_q * float(len(sorted_values) - 1)
    lower = floor(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    lower_value = float(sorted_values[lower])
    upper_value = float(sorted_values[upper])
    if lower == upper:
        return lower_value
    fraction = position - float(lower)
    return lower_value + (upper_value - lower_value) * fraction


def _percentile_rank(value: float, values: Sequence[float]) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return 1.0
    sorted_values = sorted(float(item) for item in values)
    left = bisect_left(sorted_values, float(value))
    right = bisect_right(sorted_values, float(value))
    averaged_rank = (left + right - 1) / 2.0
    return round(averaged_rank / float(len(sorted_values) - 1), 4)


def _round_score(value: float) -> float:
    return round(float(value), 4)


def build_god_modules_payload(
    *,
    scan_root: str,
    source_stats_by_file: Sequence[tuple[str, int, int, int, int]],
    units: Sequence[GroupItemLike],
    class_metrics: Sequence[ClassMetrics],
    module_deps: Sequence[ModuleDep],
) -> dict[str, object]:
    del class_metrics
    module_rows: dict[str, dict[str, object]] = {}
    filepath_to_module: dict[str, str] = {}

    for filepath, lines, functions, methods, classes in sorted(source_stats_by_file):
        module_name = module_name_from_path(scan_root, filepath)
        filepath_to_module[filepath] = module_name
        module_rows[module_name] = {
            "module": module_name,
            "filepath": filepath,
            "source_kind": _source_kind(filepath, scan_root=scan_root),
            "loc": max(0, lines),
            "functions": max(0, functions),
            "methods": max(0, methods),
            "classes": max(0, classes),
            "callable_count": max(0, functions + methods),
            "complexity_total": 0,
            "complexity_max": 0,
            "fan_in": 0,
            "fan_out": 0,
            "total_deps": 0,
            "import_edges": 0,
            "reimport_edges": 0,
            "reimport_ratio": 0.0,
            "instability": 0.0,
            "hub_balance": 0.0,
            "size_score": 0.0,
            "dependency_score": 0.0,
            "shape_score": 0.0,
            "score": 0.0,
            "candidate_status": _NON_CANDIDATE,
            "candidate_reasons": [],
        }

    for unit in units:
        filepath = as_str(unit.get("filepath")) or ""
        module_key = filepath_to_module.get(filepath)
        if module_key:
            row = module_rows[module_key]
            complexity = max(0, as_int(unit.get("cyclomatic_complexity"), 1))
            row["complexity_total"] = as_int(row.get("complexity_total")) + complexity
            row["complexity_max"] = max(as_int(row.get("complexity_max")), complexity)

    if not module_rows:
        return {
            "summary": {
                "total": 0,
                "candidates": 0,
                "population_status": _POPULATION_STATUS_LIMITED,
                "top_score": 0.0,
                "average_score": 0.0,
                "candidate_score_cutoff": 0.0,
            },
            "detection": {
                "version": "1",
                "scope": "report_only",
                "strategy": "project_relative_composite",
                "minimum_population": _MINIMUM_POPULATION,
                "size_signals": ["loc", "callable_count", "complexity_total"],
                "dependency_signals": [
                    "fan_in",
                    "fan_out",
                    "total_deps",
                    "import_edges",
                ],
                "shape_signals": ["hub_balance", "reimport_ratio"],
            },
            "items": [],
        }

    module_names = set(module_rows)
    incoming: dict[str, set[str]] = defaultdict(set)
    outgoing: dict[str, set[str]] = defaultdict(set)
    import_edges: Counter[str] = Counter()

    for dep in module_deps:
        if dep.source in module_names and dep.target in module_names:
            outgoing[dep.source].add(dep.target)
            incoming[dep.target].add(dep.source)
            import_edges[dep.source] += 1

    for module_name, row in module_rows.items():
        fan_in = len(incoming[module_name])
        fan_out = len(outgoing[module_name])
        total_deps = fan_in + fan_out
        edge_count = int(import_edges[module_name])
        reimport_edges = max(edge_count - fan_out, 0)
        row["fan_in"] = fan_in
        row["fan_out"] = fan_out
        row["total_deps"] = total_deps
        row["import_edges"] = edge_count
        row["reimport_edges"] = reimport_edges
        row["reimport_ratio"] = _round_score(
            reimport_edges / float(edge_count) if edge_count > 0 else 0.0
        )
        row["instability"] = _round_score(
            fan_out / float(total_deps) if total_deps > 0 else 0.0
        )
        row["hub_balance"] = _round_score(
            1.0 - (abs(fan_in - fan_out) / float(total_deps)) if total_deps > 0 else 0.0
        )

    rows = list(module_rows.values())
    loc_values = [float(as_int(row.get("loc"))) for row in rows]
    callable_values = [float(as_int(row.get("callable_count"))) for row in rows]
    complexity_total_values = [
        float(as_int(row.get("complexity_total"))) for row in rows
    ]
    fan_in_values = [float(as_int(row.get("fan_in"))) for row in rows]
    fan_out_values = [float(as_int(row.get("fan_out"))) for row in rows]
    total_dep_values = [float(as_int(row.get("total_deps"))) for row in rows]
    import_edge_values = [float(as_int(row.get("import_edges"))) for row in rows]
    reimport_ratio_values = [as_float(row.get("reimport_ratio")) for row in rows]

    for row in rows:
        loc_score = _percentile_rank(float(as_int(row.get("loc"))), loc_values)
        callable_score = _percentile_rank(
            float(as_int(row.get("callable_count"))),
            callable_values,
        )
        complexity_total_score = _percentile_rank(
            float(as_int(row.get("complexity_total"))),
            complexity_total_values,
        )
        size_score = max(loc_score, callable_score, complexity_total_score)

        fan_in_score = _percentile_rank(float(as_int(row.get("fan_in"))), fan_in_values)
        fan_out_score = _percentile_rank(
            float(as_int(row.get("fan_out"))),
            fan_out_values,
        )
        total_dep_score = _percentile_rank(
            float(as_int(row.get("total_deps"))),
            total_dep_values,
        )
        import_edge_score = _percentile_rank(
            float(as_int(row.get("import_edges"))),
            import_edge_values,
        )
        dependency_score = max(
            fan_in_score,
            fan_out_score,
            total_dep_score,
            import_edge_score,
        )
        hub_like_score = _round_score(
            as_float(row.get("hub_balance")) * dependency_score
        )
        repeated_import_score = _percentile_rank(
            as_float(row.get("reimport_ratio")),
            reimport_ratio_values,
        )
        shape_score = max(hub_like_score, repeated_import_score)
        score = _round_score(
            0.45 * size_score + 0.35 * dependency_score + 0.20 * shape_score
        )
        row["size_score"] = _round_score(size_score)
        row["dependency_score"] = _round_score(dependency_score)
        row["shape_score"] = _round_score(shape_score)
        row["score"] = score

    scores = sorted(as_float(row.get("score")) for row in rows)
    q3 = _score_quantile(scores, 0.75)
    q1 = _score_quantile(scores, 0.25)
    iqr = max(q3 - q1, 0.0)
    dynamic_score_cutoff = _round_score(
        min(1.0, max(_score_quantile(scores, 0.90), q3 + (1.5 * iqr)))
    )

    population_status = (
        _POPULATION_STATUS_OK
        if len(rows) >= _MINIMUM_POPULATION
        else _POPULATION_STATUS_LIMITED
    )
    candidate_count = 0
    for row in rows:
        reasons: list[str] = []
        size_score = as_float(row.get("size_score"))
        dependency_score = as_float(row.get("dependency_score"))
        shape_score = as_float(row.get("shape_score"))
        hub_like_score = _round_score(
            as_float(row.get("hub_balance")) * dependency_score
        )
        repeated_import_score = _percentile_rank(
            as_float(row.get("reimport_ratio")),
            reimport_ratio_values,
        )
        if size_score >= 0.90:
            reasons.append(_SIZE_PRESSURE)
        if dependency_score >= 0.90:
            reasons.append(_DEPENDENCY_PRESSURE)
        if hub_like_score >= 0.75:
            reasons.append(_HUB_LIKE_SHAPE)
        if repeated_import_score >= 0.90:
            reasons.append(_REPEATED_IMPORT_PRESSURE)

        if population_status != _POPULATION_STATUS_OK:
            row["candidate_status"] = _RANKED_ONLY
        else:
            is_candidate = (
                size_score >= 0.90
                and dependency_score >= 0.90
                and (
                    shape_score >= 0.75
                    or as_float(row.get("score")) >= dynamic_score_cutoff
                )
            )
            row["candidate_status"] = _CANDIDATE if is_candidate else _NON_CANDIDATE
            if is_candidate:
                candidate_count += 1
        row["candidate_reasons"] = reasons

    status_order = {_CANDIDATE: 0, _RANKED_ONLY: 1, _NON_CANDIDATE: 2}
    rows.sort(
        key=lambda row: (
            status_order[str(row.get("candidate_status", _NON_CANDIDATE))],
            -as_float(row.get("score")),
            -as_float(row.get("size_score")),
            -as_float(row.get("dependency_score")),
            str(row.get("filepath", "")),
            str(row.get("module", "")),
        )
    )

    normalized_rows = [
        {
            "module": str(row["module"]),
            "filepath": str(row["filepath"]),
            "source_kind": str(row["source_kind"]),
            "loc": as_int(row["loc"]),
            "functions": as_int(row["functions"]),
            "methods": as_int(row["methods"]),
            "classes": as_int(row["classes"]),
            "callable_count": as_int(row["callable_count"]),
            "complexity_total": as_int(row["complexity_total"]),
            "complexity_max": as_int(row["complexity_max"]),
            "fan_in": as_int(row["fan_in"]),
            "fan_out": as_int(row["fan_out"]),
            "total_deps": as_int(row["total_deps"]),
            "import_edges": as_int(row["import_edges"]),
            "reimport_edges": as_int(row["reimport_edges"]),
            "reimport_ratio": _round_score(as_float(row.get("reimport_ratio"))),
            "instability": _round_score(as_float(row.get("instability"))),
            "hub_balance": _round_score(as_float(row.get("hub_balance"))),
            "size_score": _round_score(as_float(row.get("size_score"))),
            "dependency_score": _round_score(as_float(row.get("dependency_score"))),
            "shape_score": _round_score(as_float(row.get("shape_score"))),
            "score": _round_score(as_float(row.get("score"))),
            "candidate_status": str(row["candidate_status"]),
            "candidate_reasons": [
                str(reason)
                for reason in as_sequence(row.get("candidate_reasons"))
                if str(reason).strip()
            ],
        }
        for row in rows
    ]

    return {
        "summary": {
            "total": len(normalized_rows),
            "candidates": candidate_count,
            "population_status": population_status,
            "top_score": _round_score(max(scores) if scores else 0.0),
            "average_score": _round_score(
                (sum(scores) / float(len(scores))) if scores else 0.0
            ),
            "candidate_score_cutoff": dynamic_score_cutoff,
        },
        "detection": {
            "version": "1",
            "scope": "report_only",
            "strategy": "project_relative_composite",
            "minimum_population": _MINIMUM_POPULATION,
            "size_signals": ["loc", "callable_count", "complexity_total"],
            "dependency_signals": [
                "fan_in",
                "fan_out",
                "total_deps",
                "import_edges",
            ],
            "shape_signals": ["hub_balance", "reimport_ratio"],
        },
        "items": normalized_rows,
    }
