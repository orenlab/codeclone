# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from ..models import CoverageJoinResult, ProjectMetrics
from ..utils.coerce import as_int, as_str


def _permille(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        return 0
    return round((1000.0 * float(numerator)) / float(denominator))


def _coverage_join_summary(
    coverage_join: CoverageJoinResult | None,
) -> dict[str, object]:
    if coverage_join is None:
        return {}
    return {
        "status": coverage_join.status,
        "source": coverage_join.coverage_xml,
        "files": coverage_join.files,
        "units": len(coverage_join.units),
        "measured_units": coverage_join.measured_units,
        "overall_executable_lines": coverage_join.overall_executable_lines,
        "overall_covered_lines": coverage_join.overall_covered_lines,
        "overall_permille": _permille(
            coverage_join.overall_covered_lines,
            coverage_join.overall_executable_lines,
        ),
        "missing_from_report_units": sum(
            1
            for fact in coverage_join.units
            if fact.coverage_status == "missing_from_report"
        ),
        "coverage_hotspots": coverage_join.coverage_hotspots,
        "scope_gap_hotspots": coverage_join.scope_gap_hotspots,
        "hotspot_threshold_percent": coverage_join.hotspot_threshold_percent,
        "invalid_reason": coverage_join.invalid_reason,
    }


def _coverage_join_rows(
    coverage_join: CoverageJoinResult | None,
) -> list[dict[str, object]]:
    if coverage_join is None or coverage_join.status != "ok":
        return []
    return sorted(
        (
            {
                "qualname": fact.qualname,
                "filepath": fact.filepath,
                "start_line": fact.start_line,
                "end_line": fact.end_line,
                "cyclomatic_complexity": fact.cyclomatic_complexity,
                "risk": fact.risk,
                "executable_lines": fact.executable_lines,
                "covered_lines": fact.covered_lines,
                "coverage_permille": fact.coverage_permille,
                "coverage_status": fact.coverage_status,
                "coverage_hotspot": (
                    fact.risk in {"medium", "high"}
                    and fact.coverage_status == "measured"
                    and (fact.coverage_permille / 10.0)
                    < float(coverage_join.hotspot_threshold_percent)
                ),
                "scope_gap_hotspot": (
                    fact.risk in {"medium", "high"}
                    and fact.coverage_status == "missing_from_report"
                ),
                "coverage_review_item": (
                    (
                        fact.risk in {"medium", "high"}
                        and fact.coverage_status == "measured"
                        and (fact.coverage_permille / 10.0)
                        < float(coverage_join.hotspot_threshold_percent)
                    )
                    or (
                        fact.risk in {"medium", "high"}
                        and fact.coverage_status == "missing_from_report"
                    )
                ),
            }
            for fact in coverage_join.units
        ),
        key=lambda item: (
            0 if bool(item.get("coverage_hotspot")) else 1,
            0 if bool(item.get("scope_gap_hotspot")) else 1,
            {"high": 0, "medium": 1, "low": 2}.get(as_str(item.get("risk")), 3),
            as_int(item.get("coverage_permille"), 0),
            -as_int(item.get("cyclomatic_complexity"), 0),
            as_str(item.get("filepath")),
            as_int(item.get("start_line")),
            as_str(item.get("qualname")),
        ),
    )


def _coverage_adoption_rows(project_metrics: ProjectMetrics) -> list[dict[str, object]]:
    docstring_by_module = {
        (item.filepath, item.module): item for item in project_metrics.docstring_modules
    }
    rows: list[dict[str, object]] = []
    seen_keys: set[tuple[str, str]] = set()
    for typing_item in project_metrics.typing_modules:
        key = (typing_item.filepath, typing_item.module)
        seen_keys.add(key)
        docstring_item = docstring_by_module.get(key)
        doc_total = docstring_item.public_symbol_total if docstring_item else 0
        doc_documented = (
            docstring_item.public_symbol_documented if docstring_item else 0
        )
        rows.append(
            {
                "module": typing_item.module,
                "filepath": typing_item.filepath,
                "callable_count": typing_item.callable_count,
                "params_total": typing_item.params_total,
                "params_annotated": typing_item.params_annotated,
                "param_permille": _permille(
                    typing_item.params_annotated,
                    typing_item.params_total,
                ),
                "returns_total": typing_item.returns_total,
                "returns_annotated": typing_item.returns_annotated,
                "return_permille": _permille(
                    typing_item.returns_annotated,
                    typing_item.returns_total,
                ),
                "any_annotation_count": typing_item.any_annotation_count,
                "public_symbol_total": doc_total,
                "public_symbol_documented": doc_documented,
                "docstring_permille": _permille(doc_documented, doc_total),
            }
        )
    for docstring_item in project_metrics.docstring_modules:
        key = (docstring_item.filepath, docstring_item.module)
        if key in seen_keys:
            continue
        rows.append(
            {
                "module": docstring_item.module,
                "filepath": docstring_item.filepath,
                "callable_count": 0,
                "params_total": 0,
                "params_annotated": 0,
                "param_permille": 0,
                "returns_total": 0,
                "returns_annotated": 0,
                "return_permille": 0,
                "any_annotation_count": 0,
                "public_symbol_total": docstring_item.public_symbol_total,
                "public_symbol_documented": docstring_item.public_symbol_documented,
                "docstring_permille": _permille(
                    docstring_item.public_symbol_documented,
                    docstring_item.public_symbol_total,
                ),
            }
        )
    return sorted(
        rows,
        key=lambda item: (
            as_int(item.get("param_permille")),
            as_int(item.get("docstring_permille")),
            as_int(item.get("return_permille")),
            as_str(item.get("module")),
        ),
    )
