# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from ...contracts import (
    DEFAULT_REPORT_DESIGN_COHESION_THRESHOLD,
    DEFAULT_REPORT_DESIGN_COMPLEXITY_THRESHOLD,
    DEFAULT_REPORT_DESIGN_COUPLING_THRESHOLD,
)
from ...domain.findings import (
    CATEGORY_COHESION,
    CATEGORY_COMPLEXITY,
    CATEGORY_COUPLING,
    CATEGORY_COVERAGE,
    CATEGORY_DEPENDENCY,
    FAMILY_DESIGN,
    FINDING_KIND_COVERAGE_HOTSPOT,
    FINDING_KIND_COVERAGE_SCOPE_GAP,
)
from ...domain.quality import (
    CONFIDENCE_HIGH,
    EFFORT_HARD,
    EFFORT_MODERATE,
    RISK_LOW,
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
)
from ...utils.coerce import as_float as _as_float
from ...utils.coerce import as_int as _as_int
from ...utils.coerce import as_mapping as _as_mapping
from ...utils.coerce import as_sequence as _as_sequence
from ..derived import (
    report_location_from_group_item,
)

if TYPE_CHECKING:
    pass

from ...findings.ids import design_group_id
from ._common import (
    _COVERAGE_JOIN_FAMILY,
    _coerced_nonnegative_threshold,
    _contract_report_location_path,
    _priority,
    _source_scope_from_filepaths,
)
from ._findings_groups import _single_location_source_scope


def _design_singleton_group(
    *,
    category: str,
    kind: str,
    severity: str,
    qualname: str,
    filepath: str,
    start_line: int,
    end_line: int,
    scan_root: str,
    item_data: Mapping[str, object],
    facts: Mapping[str, object],
) -> dict[str, object]:
    return {
        "id": design_group_id(category, qualname),
        "family": FAMILY_DESIGN,
        "category": category,
        "kind": kind,
        "severity": severity,
        "confidence": CONFIDENCE_HIGH,
        "priority": _priority(severity, EFFORT_MODERATE),
        "count": 1,
        "source_scope": _single_location_source_scope(
            filepath,
            scan_root=scan_root,
        ),
        "spread": {"files": 1, "functions": 1},
        "items": [
            {
                "relative_path": _contract_report_location_path(
                    filepath,
                    scan_root=scan_root,
                ),
                "qualname": qualname,
                "start_line": start_line,
                "end_line": end_line,
                **item_data,
            }
        ],
        "facts": dict(facts),
    }


def _complexity_design_group(
    item_map: Mapping[str, object],
    *,
    threshold: int,
    scan_root: str,
) -> dict[str, object] | None:
    cc = _as_int(item_map.get("cyclomatic_complexity"), 1)
    if cc <= threshold:
        return None
    qualname = str(item_map.get("qualname", ""))
    filepath = str(item_map.get("relative_path", ""))
    nesting_depth = _as_int(item_map.get("nesting_depth"))
    severity = SEVERITY_CRITICAL if cc > 40 else SEVERITY_WARNING
    return _design_singleton_group(
        category=CATEGORY_COMPLEXITY,
        kind="function_hotspot",
        severity=severity,
        qualname=qualname,
        filepath=filepath,
        start_line=_as_int(item_map.get("start_line")),
        end_line=_as_int(item_map.get("end_line")),
        scan_root=scan_root,
        item_data={
            "cyclomatic_complexity": cc,
            "nesting_depth": nesting_depth,
            "risk": str(item_map.get("risk", RISK_LOW)),
        },
        facts={
            "cyclomatic_complexity": cc,
            "nesting_depth": nesting_depth,
        },
    )


def _coupling_design_group(
    item_map: Mapping[str, object],
    *,
    threshold: int,
    scan_root: str,
) -> dict[str, object] | None:
    cbo = _as_int(item_map.get("cbo"))
    if cbo <= threshold:
        return None
    qualname = str(item_map.get("qualname", ""))
    filepath = str(item_map.get("relative_path", ""))
    coupled_classes = list(_as_sequence(item_map.get("coupled_classes")))
    return _design_singleton_group(
        category=CATEGORY_COUPLING,
        kind="class_hotspot",
        severity=SEVERITY_WARNING,
        qualname=qualname,
        filepath=filepath,
        start_line=_as_int(item_map.get("start_line")),
        end_line=_as_int(item_map.get("end_line")),
        scan_root=scan_root,
        item_data={
            "cbo": cbo,
            "risk": str(item_map.get("risk", RISK_LOW)),
            "coupled_classes": coupled_classes,
        },
        facts={
            "cbo": cbo,
            "coupled_classes": coupled_classes,
        },
    )


def _cohesion_design_group(
    item_map: Mapping[str, object],
    *,
    threshold: int,
    scan_root: str,
) -> dict[str, object] | None:
    lcom4 = _as_int(item_map.get("lcom4"))
    if lcom4 < threshold:
        return None
    qualname = str(item_map.get("qualname", ""))
    filepath = str(item_map.get("relative_path", ""))
    method_count = _as_int(item_map.get("method_count"))
    instance_var_count = _as_int(item_map.get("instance_var_count"))
    return _design_singleton_group(
        category=CATEGORY_COHESION,
        kind="class_hotspot",
        severity=SEVERITY_WARNING,
        qualname=qualname,
        filepath=filepath,
        start_line=_as_int(item_map.get("start_line")),
        end_line=_as_int(item_map.get("end_line")),
        scan_root=scan_root,
        item_data={
            "lcom4": lcom4,
            "risk": str(item_map.get("risk", RISK_LOW)),
            "method_count": method_count,
            "instance_var_count": instance_var_count,
        },
        facts={
            "lcom4": lcom4,
            "method_count": method_count,
            "instance_var_count": instance_var_count,
        },
    )


def _dependency_design_group(
    cycle: object,
    *,
    scan_root: str,
) -> dict[str, object] | None:
    modules = [str(module) for module in _as_sequence(cycle) if str(module).strip()]
    if not modules:
        return None
    cycle_key = " -> ".join(modules)
    return {
        "id": design_group_id(CATEGORY_DEPENDENCY, cycle_key),
        "family": FAMILY_DESIGN,
        "category": CATEGORY_DEPENDENCY,
        "kind": "cycle",
        "severity": SEVERITY_CRITICAL,
        "confidence": CONFIDENCE_HIGH,
        "priority": _priority(SEVERITY_CRITICAL, EFFORT_HARD),
        "count": len(modules),
        "source_scope": _source_scope_from_filepaths(
            (module.replace(".", "/") + ".py" for module in modules),
            scan_root=scan_root,
        ),
        "spread": {"files": len(modules), "functions": 0},
        "items": [
            {
                "module": module,
                "relative_path": module.replace(".", "/") + ".py",
                "source_kind": report_location_from_group_item(
                    {
                        "filepath": module.replace(".", "/") + ".py",
                        "qualname": "",
                        "start_line": 0,
                        "end_line": 0,
                    }
                ).source_kind,
            }
            for module in modules
        ],
        "facts": {
            "cycle_length": len(modules),
        },
    }


def _coverage_design_group(
    item_map: Mapping[str, object],
    *,
    threshold_percent: int,
    scan_root: str,
) -> dict[str, object] | None:
    coverage_hotspot = bool(item_map.get("coverage_hotspot"))
    scope_gap_hotspot = bool(item_map.get("scope_gap_hotspot"))
    if not coverage_hotspot and not scope_gap_hotspot:
        return None
    qualname = str(item_map.get("qualname", "")).strip()
    filepath = str(item_map.get("relative_path", "")).strip()
    if not filepath:
        return None
    start_line = _as_int(item_map.get("start_line"))
    end_line = _as_int(item_map.get("end_line"))
    subject_key = qualname or f"{filepath}:{start_line}:{end_line}"
    risk = str(item_map.get("risk", RISK_LOW)).strip() or RISK_LOW
    coverage_status = str(item_map.get("coverage_status", "")).strip()
    coverage_permille = _as_int(item_map.get("coverage_permille"))
    covered_lines = _as_int(item_map.get("covered_lines"))
    executable_lines = _as_int(item_map.get("executable_lines"))
    complexity = _as_int(item_map.get("cyclomatic_complexity"), 1)
    severity = SEVERITY_CRITICAL if risk == "high" else SEVERITY_WARNING
    if scope_gap_hotspot:
        kind = FINDING_KIND_COVERAGE_SCOPE_GAP
        detail = "The supplied coverage.xml did not map to this function's file."
    else:
        kind = FINDING_KIND_COVERAGE_HOTSPOT
        detail = "Joined line coverage is below the configured hotspot threshold."
    return {
        "id": design_group_id(CATEGORY_COVERAGE, subject_key),
        "family": FAMILY_DESIGN,
        "category": CATEGORY_COVERAGE,
        "kind": kind,
        "severity": severity,
        "confidence": CONFIDENCE_HIGH,
        "priority": _priority(severity, EFFORT_MODERATE),
        "count": 1,
        "source_scope": _single_location_source_scope(
            filepath,
            scan_root=scan_root,
        ),
        "spread": {"files": 1, "functions": 1},
        "items": [
            {
                "relative_path": filepath,
                "qualname": qualname,
                "start_line": start_line,
                "end_line": end_line,
                "risk": risk,
                "cyclomatic_complexity": complexity,
                "coverage_permille": coverage_permille,
                "coverage_status": coverage_status,
                "covered_lines": covered_lines,
                "executable_lines": executable_lines,
                "coverage_hotspot": coverage_hotspot,
                "scope_gap_hotspot": scope_gap_hotspot,
            }
        ],
        "facts": {
            "coverage_permille": coverage_permille,
            "hotspot_threshold_percent": threshold_percent,
            "coverage_status": coverage_status,
            "covered_lines": covered_lines,
            "executable_lines": executable_lines,
            "cyclomatic_complexity": complexity,
            "coverage_hotspot": coverage_hotspot,
            "scope_gap_hotspot": scope_gap_hotspot,
            "detail": detail,
        },
    }


def _build_design_groups(
    metrics_payload: Mapping[str, object],
    *,
    design_thresholds: Mapping[str, object] | None = None,
    scan_root: str,
) -> list[dict[str, object]]:
    families = _as_mapping(metrics_payload.get("families"))
    thresholds = _as_mapping(design_thresholds)
    complexity_threshold = _coerced_nonnegative_threshold(
        _as_mapping(thresholds.get(CATEGORY_COMPLEXITY)).get("value"),
        default=DEFAULT_REPORT_DESIGN_COMPLEXITY_THRESHOLD,
    )
    coupling_threshold = _coerced_nonnegative_threshold(
        _as_mapping(thresholds.get(CATEGORY_COUPLING)).get("value"),
        default=DEFAULT_REPORT_DESIGN_COUPLING_THRESHOLD,
    )
    cohesion_threshold = _coerced_nonnegative_threshold(
        _as_mapping(thresholds.get(CATEGORY_COHESION)).get("value"),
        default=DEFAULT_REPORT_DESIGN_COHESION_THRESHOLD,
    )
    coverage_join = _as_mapping(families.get(_COVERAGE_JOIN_FAMILY))
    coverage_threshold = _as_int(
        _as_mapping(coverage_join.get("summary")).get("hotspot_threshold_percent"),
        50,
    )
    groups: list[dict[str, object]] = []

    complexity = _as_mapping(families.get(CATEGORY_COMPLEXITY))
    for item in _as_sequence(complexity.get("items")):
        group = _complexity_design_group(
            _as_mapping(item),
            threshold=complexity_threshold,
            scan_root=scan_root,
        )
        if group is not None:
            groups.append(group)

    coupling = _as_mapping(families.get(CATEGORY_COUPLING))
    for item in _as_sequence(coupling.get("items")):
        group = _coupling_design_group(
            _as_mapping(item),
            threshold=coupling_threshold,
            scan_root=scan_root,
        )
        if group is not None:
            groups.append(group)

    cohesion = _as_mapping(families.get(CATEGORY_COHESION))
    for item in _as_sequence(cohesion.get("items")):
        group = _cohesion_design_group(
            _as_mapping(item),
            threshold=cohesion_threshold,
            scan_root=scan_root,
        )
        if group is not None:
            groups.append(group)

    dependencies = _as_mapping(families.get("dependencies"))
    for cycle in _as_sequence(dependencies.get("cycles")):
        group = _dependency_design_group(cycle, scan_root=scan_root)
        if group is not None:
            groups.append(group)

    for item in _as_sequence(coverage_join.get("items")):
        group = _coverage_design_group(
            _as_mapping(item),
            threshold_percent=coverage_threshold,
            scan_root=scan_root,
        )
        if group is not None:
            groups.append(group)

    groups.sort(key=lambda group: (-_as_float(group["priority"]), str(group["id"])))
    return groups
