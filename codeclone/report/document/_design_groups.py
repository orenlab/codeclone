# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping

from ...domain.findings import (
    CATEGORY_COHESION,
    CATEGORY_COMPLEXITY,
    CATEGORY_COUPLING,
    CATEGORY_COVERAGE,
    CATEGORY_DEPENDENCY,
    FAMILY_DESIGN,
)
from ...domain.quality import (
    CONFIDENCE_HIGH,
    EFFORT_HARD,
    EFFORT_MODERATE,
    RISK_LOW,
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
)
from ...findings.group_shapes import (
    DesignThresholds,
    cohesion_facts,
    cohesion_item_data,
    complexity_facts,
    complexity_item_data,
    coupling_facts,
    coupling_item_data,
    coverage_facts,
    coverage_group_kind,
    coverage_item_data,
    dependency_cycle_facts,
    dependency_member_item,
    is_cohesion_hotspot,
    is_complexity_hotspot,
    is_coupling_hotspot,
    module_classification_path,
)
from ...findings.group_shapes import design_thresholds as realized_design_thresholds
from ...findings.ids import design_group_id
from ...utils.coerce import as_float as _as_float
from ...utils.coerce import as_int as _as_int
from ...utils.coerce import as_mapping as _as_mapping
from ...utils.coerce import as_sequence as _as_sequence
from ._common import (
    _COVERAGE_JOIN_FAMILY,
    ENTITY_NOVELTY_DOMAIN_COMPLEXITY,
    ENTITY_NOVELTY_DOMAIN_COUPLING,
    ENTITY_NOVELTY_DOMAIN_DEPENDENCIES,
    _contract_report_location_path,
    _dependency_cycle_identity,
    _entity_novelty,
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
    novelty_domain: str,
    novelty_identity: str | None = None,
    entity_novelty_facts: Mapping[str, object] | None = None,
) -> dict[str, object]:
    novelty, novelty_reason = _entity_novelty(
        identity=qualname if novelty_identity is None else novelty_identity,
        domain=novelty_domain,
        entity_novelty_facts=entity_novelty_facts,
    )
    return {
        "id": design_group_id(category, qualname),
        "family": FAMILY_DESIGN,
        "category": category,
        "kind": kind,
        "severity": severity,
        "confidence": CONFIDENCE_HIGH,
        "priority": _priority(severity, EFFORT_MODERATE),
        "count": 1,
        "novelty": novelty,
        "novelty_reason": novelty_reason,
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
    thresholds: DesignThresholds,
    scan_root: str,
    entity_novelty_facts: Mapping[str, object] | None = None,
) -> dict[str, object] | None:
    cc = _as_int(item_map.get("cyclomatic_complexity"), 1)
    if not is_complexity_hotspot(cc, thresholds):
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
        item_data=complexity_item_data(
            cyclomatic_complexity=cc,
            nesting_depth=nesting_depth,
            risk=str(item_map.get("risk", RISK_LOW)),
        ),
        facts=complexity_facts(cyclomatic_complexity=cc, nesting_depth=nesting_depth),
        novelty_domain=ENTITY_NOVELTY_DOMAIN_COMPLEXITY,
        entity_novelty_facts=entity_novelty_facts,
    )


def _coupling_design_group(
    item_map: Mapping[str, object],
    *,
    thresholds: DesignThresholds,
    scan_root: str,
    entity_novelty_facts: Mapping[str, object] | None = None,
) -> dict[str, object] | None:
    cbo = _as_int(item_map.get("cbo"))
    if not is_coupling_hotspot(cbo, thresholds):
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
        item_data=coupling_item_data(
            cbo=cbo,
            risk=str(item_map.get("risk", RISK_LOW)),
            coupled_classes=coupled_classes,
        ),
        facts=coupling_facts(cbo=cbo, coupled_classes=coupled_classes),
        novelty_domain=ENTITY_NOVELTY_DOMAIN_COUPLING,
        entity_novelty_facts=entity_novelty_facts,
    )


def _cohesion_design_group(
    item_map: Mapping[str, object],
    *,
    thresholds: DesignThresholds,
    scan_root: str,
) -> dict[str, object] | None:
    lcom4 = _as_int(item_map.get("lcom4"))
    if not is_cohesion_hotspot(lcom4, thresholds):
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
        item_data=cohesion_item_data(
            lcom4=lcom4,
            risk=str(item_map.get("risk", RISK_LOW)),
            method_count=method_count,
            instance_var_count=instance_var_count,
        ),
        facts=cohesion_facts(
            lcom4=lcom4,
            method_count=method_count,
            instance_var_count=instance_var_count,
        ),
        # MetricsDiff carries no ``new_low_cohesion_classes`` term, so cohesion
        # has no per-entity baseline answer to report.
        novelty_domain=CATEGORY_COHESION,
    )


def _dependency_design_group(
    detail: Mapping[str, object],
    *,
    scan_root: str,
    entity_novelty_facts: Mapping[str, object] | None = None,
) -> dict[str, object] | None:
    modules = [
        str(module)
        for module in _as_sequence(detail.get("modules"))
        if str(module).strip()
    ]
    if not modules:
        return None
    raw_paths = list(_as_sequence(detail.get("member_paths")))
    member_paths: list[str | None] = [
        str(raw_paths[index]).strip() or None
        if index < len(raw_paths) and raw_paths[index] is not None
        else None
        for index in range(len(modules))
    ]
    # The binding law decided the kind upstream; this projection only styles
    # it. A deferred cycle is real but cannot crash at import time, so it is
    # a warning; an import-time cycle keeps the critical tier.
    kind = str(detail.get("kind", "import_cycle"))
    severity = SEVERITY_CRITICAL if kind == "import_cycle" else SEVERITY_WARNING
    cycle_key = _dependency_cycle_identity(modules)
    novelty, novelty_reason = _entity_novelty(
        identity=cycle_key,
        domain=ENTITY_NOVELTY_DOMAIN_DEPENDENCIES,
        entity_novelty_facts=entity_novelty_facts,
    )
    items = [
        dependency_member_item(module=module, member_path=member_path)
        for module, member_path in zip(modules, member_paths, strict=True)
    ]
    return {
        "id": design_group_id(CATEGORY_DEPENDENCY, cycle_key),
        "family": FAMILY_DESIGN,
        "category": CATEGORY_DEPENDENCY,
        "kind": kind,
        "severity": severity,
        "confidence": CONFIDENCE_HIGH,
        "priority": _priority(severity, EFFORT_HARD),
        "count": len(modules),
        "novelty": novelty,
        "novelty_reason": novelty_reason,
        "source_scope": _source_scope_from_filepaths(
            (
                module_classification_path(module, member_path)
                for module, member_path in zip(modules, member_paths, strict=True)
            ),
            scan_root=scan_root,
        ),
        "spread": {"files": len(modules), "functions": 0},
        "items": items,
        "facts": dependency_cycle_facts(kind=kind, cycle_length=len(modules)),
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
    kind, detail = coverage_group_kind(scope_gap_hotspot=scope_gap_hotspot)
    coverage_novelty, coverage_novelty_reason = _entity_novelty(
        identity=subject_key,
        domain=CATEGORY_COVERAGE,
        entity_novelty_facts=None,
    )
    return {
        "id": design_group_id(CATEGORY_COVERAGE, subject_key),
        "family": FAMILY_DESIGN,
        "category": CATEGORY_COVERAGE,
        "kind": kind,
        "severity": severity,
        "confidence": CONFIDENCE_HIGH,
        "priority": _priority(severity, EFFORT_MODERATE),
        "count": 1,
        # The coverage join is a current-run signal only; the baseline has no
        # coverage lane and therefore no comparison to report.
        "novelty": coverage_novelty,
        "novelty_reason": coverage_novelty_reason,
        "source_scope": _single_location_source_scope(
            filepath,
            scan_root=scan_root,
        ),
        "spread": {"files": 1, "functions": 1},
        "items": [
            coverage_item_data(
                relative_path=filepath,
                qualname=qualname,
                start_line=start_line,
                end_line=end_line,
                risk=risk,
                cyclomatic_complexity=complexity,
                coverage_permille=coverage_permille,
                coverage_status=coverage_status,
                covered_lines=covered_lines,
                executable_lines=executable_lines,
                coverage_hotspot=coverage_hotspot,
                scope_gap_hotspot=scope_gap_hotspot,
            )
        ],
        "facts": coverage_facts(
            coverage_permille=coverage_permille,
            hotspot_threshold_percent=threshold_percent,
            coverage_status=coverage_status,
            covered_lines=covered_lines,
            executable_lines=executable_lines,
            cyclomatic_complexity=complexity,
            coverage_hotspot=coverage_hotspot,
            scope_gap_hotspot=scope_gap_hotspot,
            detail=detail,
        ),
    }


def _build_design_groups(
    metrics_payload: Mapping[str, object],
    *,
    design_thresholds: Mapping[str, object] | None = None,
    scan_root: str,
    entity_novelty_facts: Mapping[str, object] | None = None,
) -> list[dict[str, object]]:
    families = _as_mapping(metrics_payload.get("families"))
    thresholds = realized_design_thresholds(design_thresholds)
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
            thresholds=thresholds,
            scan_root=scan_root,
            entity_novelty_facts=entity_novelty_facts,
        )
        if group is not None:
            groups.append(group)

    coupling = _as_mapping(families.get(CATEGORY_COUPLING))
    for item in _as_sequence(coupling.get("items")):
        group = _coupling_design_group(
            _as_mapping(item),
            thresholds=thresholds,
            scan_root=scan_root,
            entity_novelty_facts=entity_novelty_facts,
        )
        if group is not None:
            groups.append(group)

    cohesion = _as_mapping(families.get(CATEGORY_COHESION))
    for item in _as_sequence(cohesion.get("items")):
        group = _cohesion_design_group(
            _as_mapping(item),
            thresholds=thresholds,
            scan_root=scan_root,
        )
        if group is not None:
            groups.append(group)

    dependencies = _as_mapping(families.get("dependencies"))
    cycle_details = list(_as_sequence(dependencies.get("cycle_details")))
    if not cycle_details:
        # A document without details (older payload) still surfaces its
        # cycles under the pre-wave reading: import_cycle, no path claims.
        cycle_details = [
            {
                "modules": [str(module) for module in _as_sequence(cycle)],
                "kind": "import_cycle",
                "member_paths": [],
            }
            for cycle in _as_sequence(dependencies.get("cycles"))
        ]
    for detail in cycle_details:
        group = _dependency_design_group(
            _as_mapping(detail),
            scan_root=scan_root,
            entity_novelty_facts=entity_novelty_facts,
        )
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
