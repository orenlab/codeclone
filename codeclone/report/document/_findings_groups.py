# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from typing import TYPE_CHECKING, Literal

from ...domain.findings import (
    CLONE_KIND_BLOCK,
    CLONE_KIND_FUNCTION,
    CLONE_KIND_SEGMENT,
    FAMILY_CLONE,
    FAMILY_DEAD_CODE,
    FAMILY_STRUCTURAL,
)
from ...domain.quality import (
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    EFFORT_EASY,
    RISK_LOW,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_WARNING,
)
from ...findings.structural.detectors import normalize_structural_findings
from ...utils.coerce import as_float as _as_float
from ...utils.coerce import as_int as _as_int
from ...utils.coerce import as_mapping as _as_mapping
from ...utils.coerce import as_sequence as _as_sequence
from ..derived import (
    group_spread,
    report_location_from_group_item,
    report_location_from_structural_occurrence,
)
from ..suggestions import classify_clone_type

if TYPE_CHECKING:
    from ...models import (
        GroupItemLike,
        GroupMapLike,
        StructuralFindingGroup,
        SuppressedCloneGroup,
    )

from ...findings.ids import clone_group_id, dead_code_group_id, structural_group_id
from ._common import (
    _clone_novelty,
    _contract_report_location_path,
    _item_sort_key,
    _normalize_block_machine_facts,
    _priority,
    _source_scope_from_locations,
)


def _clone_group_assessment(
    *,
    count: int,
    clone_type: str,
) -> tuple[str, float]:
    match (count >= 4, clone_type in {"Type-1", "Type-2"}):
        case (True, _):
            severity = SEVERITY_CRITICAL
        case (False, True):
            severity = SEVERITY_WARNING
        case _:
            severity = SEVERITY_INFO
    effort = "easy" if clone_type in {"Type-1", "Type-2"} else "moderate"
    return severity, _priority(severity, effort)


def _build_clone_group_facts(
    *,
    group_key: str,
    kind: Literal["function", "block", "segment"],
    items: Sequence[GroupItemLike],
    block_facts: Mapping[str, Mapping[str, str]],
) -> tuple[dict[str, object], dict[str, str]]:
    base: dict[str, object] = {
        "group_key": group_key,
        "group_arity": len(items),
    }
    display_facts: dict[str, str] = {}
    match kind:
        case "function":
            loc_buckets = sorted(
                {
                    str(item.get("loc_bucket", ""))
                    for item in items
                    if str(item.get("loc_bucket", "")).strip()
                }
            )
            base["loc_buckets"] = loc_buckets
        case "block" if group_key in block_facts:
            typed_facts, block_display_facts = _normalize_block_machine_facts(
                group_key=group_key,
                group_arity=len(items),
                block_facts=block_facts[group_key],
            )
            base.update(typed_facts)
            display_facts.update(block_display_facts)
        case _:
            pass
    return base, display_facts


def _clone_item_payload(
    item: GroupItemLike,
    *,
    kind: Literal["function", "block", "segment"],
    scan_root: str,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "relative_path": _contract_report_location_path(
            str(item.get("filepath", "")),
            scan_root=scan_root,
        ),
        "qualname": str(item.get("qualname", "")),
        "start_line": _as_int(item.get("start_line", 0)),
        "end_line": _as_int(item.get("end_line", 0)),
    }
    match kind:
        case "function":
            payload.update(
                {
                    "loc": _as_int(item.get("loc", 0)),
                    "stmt_count": _as_int(item.get("stmt_count", 0)),
                    "fingerprint": str(item.get("fingerprint", "")),
                    "loc_bucket": str(item.get("loc_bucket", "")),
                    "cyclomatic_complexity": _as_int(
                        item.get("cyclomatic_complexity", 1)
                    ),
                    "nesting_depth": _as_int(item.get("nesting_depth", 0)),
                    "risk": str(item.get("risk", RISK_LOW)),
                    "raw_hash": str(item.get("raw_hash", "")),
                }
            )
        case "block":
            payload["size"] = _as_int(item.get("size", 0))
        case _:
            payload.update(
                {
                    "size": _as_int(item.get("size", 0)),
                    "segment_hash": str(item.get("segment_hash", "")),
                    "segment_sig": str(item.get("segment_sig", "")),
                }
            )
    return payload


def _build_clone_groups(
    *,
    groups: GroupMapLike,
    kind: Literal["function", "block", "segment"],
    baseline_trusted: bool,
    new_keys: Collection[str] | None,
    block_facts: Mapping[str, Mapping[str, str]],
    scan_root: str,
) -> list[dict[str, object]]:
    encoded_groups: list[dict[str, object]] = []
    new_key_set = set(new_keys) if new_keys is not None else None
    for group_key in sorted(groups):
        items = groups[group_key]
        clone_type = classify_clone_type(items=items, kind=kind)
        severity, priority = _clone_group_assessment(
            count=len(items),
            clone_type=clone_type,
        )
        novelty = _clone_novelty(
            group_key=group_key,
            baseline_trusted=baseline_trusted,
            new_keys=new_key_set,
        )
        locations = tuple(
            report_location_from_group_item(item, scan_root=scan_root) for item in items
        )
        source_scope = _source_scope_from_locations(
            [
                {
                    "source_kind": location.source_kind,
                }
                for location in locations
            ]
        )
        spread_files, spread_functions = group_spread(locations)
        rows = sorted(
            [
                _clone_item_payload(
                    item,
                    kind=kind,
                    scan_root=scan_root,
                )
                for item in items
            ],
            key=_item_sort_key,
        )
        facts, display_facts = _build_clone_group_facts(
            group_key=group_key,
            kind=kind,
            items=items,
            block_facts=block_facts,
        )
        encoded_groups.append(
            {
                "id": clone_group_id(kind, group_key),
                "family": FAMILY_CLONE,
                "category": kind,
                "kind": "clone_group",
                "severity": severity,
                "confidence": CONFIDENCE_HIGH,
                "priority": priority,
                "clone_kind": kind,
                "clone_type": clone_type,
                "novelty": novelty,
                "count": len(items),
                "source_scope": source_scope,
                "spread": {
                    "files": spread_files,
                    "functions": spread_functions,
                },
                "items": rows,
                "facts": facts,
                **({"display_facts": display_facts} if display_facts else {}),
            }
        )
    encoded_groups.sort(
        key=lambda group: (-_as_int(group.get("count")), str(group["id"]))
    )
    return encoded_groups


def _build_suppressed_clone_groups(
    *,
    groups: Sequence[SuppressedCloneGroup] | None,
    block_facts: Mapping[str, Mapping[str, str]],
    scan_root: str,
) -> dict[str, list[dict[str, object]]]:
    buckets: dict[str, list[dict[str, object]]] = {
        CLONE_KIND_FUNCTION: [],
        CLONE_KIND_BLOCK: [],
        CLONE_KIND_SEGMENT: [],
    }
    for group in groups or ():
        items = group.items
        clone_type = classify_clone_type(items=items, kind=group.kind)
        severity, priority = _clone_group_assessment(
            count=len(items),
            clone_type=clone_type,
        )
        locations = tuple(
            report_location_from_group_item(item, scan_root=scan_root) for item in items
        )
        source_scope = _source_scope_from_locations(
            [
                {
                    "source_kind": location.source_kind,
                }
                for location in locations
            ]
        )
        spread_files, spread_functions = group_spread(locations)
        rows = sorted(
            [
                _clone_item_payload(
                    item,
                    kind=group.kind,
                    scan_root=scan_root,
                )
                for item in items
            ],
            key=_item_sort_key,
        )
        facts, display_facts = _build_clone_group_facts(
            group_key=group.group_key,
            kind=group.kind,
            items=items,
            block_facts=block_facts,
        )
        encoded: dict[str, object] = {
            "id": clone_group_id(group.kind, group.group_key),
            "family": FAMILY_CLONE,
            "category": group.kind,
            "kind": "clone_group",
            "severity": severity,
            "confidence": CONFIDENCE_HIGH,
            "priority": priority,
            "clone_kind": group.kind,
            "clone_type": clone_type,
            "count": len(items),
            "source_scope": source_scope,
            "spread": {
                "files": spread_files,
                "functions": spread_functions,
            },
            "items": rows,
            "facts": facts,
            "suppression_rule": group.suppression_rule,
            "suppression_source": group.suppression_source,
            "matched_patterns": list(group.matched_patterns),
        }
        if display_facts:
            encoded["display_facts"] = display_facts
        buckets[group.kind].append(encoded)
    for bucket in buckets.values():
        bucket.sort(key=lambda group: (-_as_int(group.get("count")), str(group["id"])))
    return buckets


def _structural_group_assessment(
    *,
    finding_kind: str,
    count: int,
    spread_functions: int,
) -> tuple[str, float]:
    match finding_kind:
        case "clone_guard_exit_divergence" | "clone_cohort_drift":
            severity = SEVERITY_WARNING
            if count >= 3 or spread_functions > 1:
                severity = SEVERITY_CRITICAL
            return severity, _priority(severity, "moderate")
        case _:
            severity = (
                SEVERITY_WARNING
                if count >= 4 or spread_functions > 1
                else SEVERITY_INFO
            )
            return severity, _priority(severity, "moderate")


def _csv_values(value: object) -> list[str]:
    raw = str(value).strip()
    if not raw:
        return []
    return sorted({part.strip() for part in raw.split(",") if part.strip()})


def _build_structural_signature(
    finding_kind: str,
    signature: Mapping[str, str],
) -> dict[str, object]:
    debug = {str(key): str(signature[key]) for key in sorted(signature)}
    match finding_kind:
        case "clone_guard_exit_divergence":
            return {
                "version": "1",
                "stable": {
                    "family": "clone_guard_exit_divergence",
                    "cohort_id": str(signature.get("cohort_id", "")),
                    "majority_guard_count": _as_int(
                        signature.get("majority_guard_count")
                    ),
                    "majority_guard_terminal_profile": str(
                        signature.get("majority_guard_terminal_profile", "none")
                    ),
                    "majority_terminal_kind": str(
                        signature.get("majority_terminal_kind", "fallthrough")
                    ),
                    "majority_side_effect_before_guard": (
                        str(signature.get("majority_side_effect_before_guard", "0"))
                        == "1"
                    ),
                },
                "debug": debug,
            }
        case "clone_cohort_drift":
            return {
                "version": "1",
                "stable": {
                    "family": "clone_cohort_drift",
                    "cohort_id": str(signature.get("cohort_id", "")),
                    "drift_fields": _csv_values(signature.get("drift_fields")),
                    "majority_profile": {
                        "terminal_kind": str(
                            signature.get("majority_terminal_kind", "")
                        ),
                        "guard_exit_profile": str(
                            signature.get("majority_guard_exit_profile", "")
                        ),
                        "try_finally_profile": str(
                            signature.get("majority_try_finally_profile", "")
                        ),
                        "side_effect_order_profile": str(
                            signature.get("majority_side_effect_order_profile", "")
                        ),
                    },
                },
                "debug": debug,
            }
        case _:
            return {
                "version": "1",
                "stable": {
                    "family": "duplicated_branches",
                    "stmt_shape": str(signature.get("stmt_seq", "")),
                    "terminal_kind": str(signature.get("terminal", "")),
                    "control_flow": {
                        "has_loop": str(signature.get("has_loop", "0")) == "1",
                        "has_try": str(signature.get("has_try", "0")) == "1",
                        "nested_if": str(signature.get("nested_if", "0")) == "1",
                    },
                },
                "debug": debug,
            }


def _build_structural_facts(
    finding_kind: str,
    signature: Mapping[str, str],
    *,
    count: int,
) -> dict[str, object]:
    match finding_kind:
        case "clone_guard_exit_divergence":
            return {
                "cohort_id": str(signature.get("cohort_id", "")),
                "cohort_arity": _as_int(signature.get("cohort_arity")),
                "divergent_members": _as_int(signature.get("divergent_members"), count),
                "majority_entry_guard_count": _as_int(
                    signature.get("majority_guard_count"),
                ),
                "majority_guard_terminal_profile": str(
                    signature.get("majority_guard_terminal_profile", "none")
                ),
                "majority_terminal_kind": str(
                    signature.get("majority_terminal_kind", "fallthrough")
                ),
                "majority_side_effect_before_guard": (
                    str(signature.get("majority_side_effect_before_guard", "0")) == "1"
                ),
                "guard_count_values": _csv_values(signature.get("guard_count_values")),
                "guard_terminal_values": _csv_values(
                    signature.get("guard_terminal_values"),
                ),
                "terminal_values": _csv_values(signature.get("terminal_values")),
                "side_effect_before_guard_values": _csv_values(
                    signature.get("side_effect_before_guard_values"),
                ),
            }
        case "clone_cohort_drift":
            return {
                "cohort_id": str(signature.get("cohort_id", "")),
                "cohort_arity": _as_int(signature.get("cohort_arity")),
                "divergent_members": _as_int(signature.get("divergent_members"), count),
                "drift_fields": _csv_values(signature.get("drift_fields")),
                "stable_majority_profile": {
                    "terminal_kind": str(signature.get("majority_terminal_kind", "")),
                    "guard_exit_profile": str(
                        signature.get("majority_guard_exit_profile", "")
                    ),
                    "try_finally_profile": str(
                        signature.get("majority_try_finally_profile", "")
                    ),
                    "side_effect_order_profile": str(
                        signature.get("majority_side_effect_order_profile", "")
                    ),
                },
            }
        case _:
            return {
                "occurrence_count": count,
                "non_overlapping": True,
                "call_bucket": _as_int(signature.get("calls", "0")),
                "raise_bucket": _as_int(signature.get("raises", "0")),
            }


def _build_structural_groups(
    groups: Sequence[StructuralFindingGroup] | None,
    *,
    scan_root: str,
) -> list[dict[str, object]]:
    normalized_groups = normalize_structural_findings(groups or ())
    out: list[dict[str, object]] = []
    for group in normalized_groups:
        locations = tuple(
            report_location_from_structural_occurrence(item, scan_root=scan_root)
            for item in group.items
        )
        source_scope = _source_scope_from_locations(
            [{"source_kind": location.source_kind} for location in locations]
        )
        spread_files, spread_functions = group_spread(locations)
        severity, priority = _structural_group_assessment(
            finding_kind=group.finding_kind,
            count=len(group.items),
            spread_functions=spread_functions,
        )
        out.append(
            {
                "id": structural_group_id(group.finding_kind, group.finding_key),
                "family": FAMILY_STRUCTURAL,
                "category": group.finding_kind,
                "kind": group.finding_kind,
                "severity": severity,
                "confidence": (
                    CONFIDENCE_HIGH
                    if group.finding_kind
                    in {"clone_guard_exit_divergence", "clone_cohort_drift"}
                    else CONFIDENCE_MEDIUM
                ),
                "priority": priority,
                "count": len(group.items),
                "source_scope": source_scope,
                "spread": {
                    "files": spread_files,
                    "functions": spread_functions,
                },
                "signature": _build_structural_signature(
                    group.finding_kind,
                    group.signature,
                ),
                "items": sorted(
                    [
                        {
                            "relative_path": _contract_report_location_path(
                                item.file_path,
                                scan_root=scan_root,
                            ),
                            "qualname": item.qualname,
                            "start_line": item.start,
                            "end_line": item.end,
                        }
                        for item in group.items
                    ],
                    key=_item_sort_key,
                ),
                "facts": _build_structural_facts(
                    group.finding_kind,
                    group.signature,
                    count=len(group.items),
                ),
            }
        )
    out.sort(key=lambda group: (-_as_int(group.get("count")), str(group["id"])))
    return out


def _single_location_source_scope(
    filepath: str,
    *,
    scan_root: str,
) -> dict[str, object]:
    location = report_location_from_group_item(
        {
            "filepath": filepath,
            "qualname": "",
            "start_line": 0,
            "end_line": 0,
        },
        scan_root=scan_root,
    )
    return _source_scope_from_locations([{"source_kind": location.source_kind}])


def _build_dead_code_groups(
    metrics_payload: Mapping[str, object],
    *,
    scan_root: str,
) -> list[dict[str, object]]:
    families = _as_mapping(metrics_payload.get("families"))
    dead_code = _as_mapping(families.get(FAMILY_DEAD_CODE))
    groups: list[dict[str, object]] = []
    for item in _as_sequence(dead_code.get("items")):
        item_map = _as_mapping(item)
        qualname = str(item_map.get("qualname", ""))
        filepath = str(item_map.get("relative_path", ""))
        confidence = str(item_map.get("confidence", CONFIDENCE_MEDIUM))
        severity = SEVERITY_WARNING if confidence == CONFIDENCE_HIGH else SEVERITY_INFO
        groups.append(
            {
                "id": dead_code_group_id(qualname),
                "family": FAMILY_DEAD_CODE,
                "category": str(item_map.get("kind", "unknown")),
                "kind": "unused_symbol",
                "severity": severity,
                "confidence": confidence,
                "priority": _priority(severity, EFFORT_EASY),
                "count": 1,
                "source_scope": _single_location_source_scope(
                    filepath,
                    scan_root=scan_root,
                ),
                "spread": {"files": 1, "functions": 1 if qualname else 0},
                "items": [
                    {
                        "relative_path": _contract_report_location_path(
                            filepath,
                            scan_root=scan_root,
                        ),
                        "qualname": qualname,
                        "start_line": _as_int(item_map.get("start_line")),
                        "end_line": _as_int(item_map.get("end_line")),
                    }
                ],
                "facts": {
                    "kind": str(item_map.get("kind", "unknown")),
                    "confidence": confidence,
                },
            }
        )
    groups.sort(key=lambda group: (-_as_float(group["priority"]), str(group["id"])))
    return groups
