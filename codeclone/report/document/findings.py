# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from typing import TYPE_CHECKING

from ...contracts import (
    CLONE_KIND_BLOCK,
    CLONE_KIND_FUNCTION,
    CLONE_KIND_SEGMENT,
    FAMILY_CLONES,
)
from ...domain.findings import (
    CLONE_NOVELTY_KNOWN,
    CLONE_NOVELTY_NEW,
    CLONE_NOVELTY_UNAVAILABLE,
    FAMILY_AUTHORITY,
    FAMILY_DEAD_CODE,
    FAMILY_STRUCTURAL,
    FINDING_KIND_AUTHORITY_VIOLATION,
)
from ...domain.quality import (
    CONFIDENCE_HIGH,
    EFFORT_MODERATE,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_WARNING,
)
from ...domain.source_scope import (
    IMPACT_SCOPE_MIXED,
    IMPACT_SCOPE_NON_RUNTIME,
    IMPACT_SCOPE_RUNTIME,
)
from ...findings.ids import authority_group_id
from ...utils.coerce import as_int as _as_int
from ...utils.coerce import as_mapping as _as_mapping
from ...utils.coerce import as_sequence as _as_sequence
from ..derived import classify_source_kind

if TYPE_CHECKING:
    from ...models import (
        GroupMapLike,
        NearMissPair,
        RenamedStructureGroup,
        StructuralFindingGroup,
        SuppressedCloneGroup,
    )

from ._common import _priority, _source_scope_from_locations
from ._design_groups import _build_design_groups
from ._findings_groups import (
    _build_clone_groups,
    _build_dead_code_groups,
    _build_structural_groups,
    _build_suppressed_clone_groups,
    build_near_miss_payload,
    build_renamed_structure_payload,
)

_SEMANTIC_AUTHORITY_METRICS_FAMILY = "semantic_authority"


def _build_authority_groups(
    metrics_payload: Mapping[str, object],
) -> tuple[list[dict[str, object]], int]:
    authority = _as_mapping(
        _as_mapping(metrics_payload.get("families")).get(
            _SEMANTIC_AUTHORITY_METRICS_FAMILY
        )
    )
    groups: list[dict[str, object]] = []
    suppressed = 0
    for item in _as_sequence(authority.get("items")):
        violation = _as_mapping(item)
        if str(violation.get("item_kind", "")) != "violation":
            continue
        if bool(violation.get("suppressed", False)):
            suppressed += 1
            continue
        locations = [
            {
                "relative_path": str(location.get("relative_path", "")),
                "qualname": str(location.get("qualname", "")),
                "start_line": _as_int(location.get("start_line")),
                "end_line": _as_int(location.get("end_line")),
                "source_kind": classify_source_kind(
                    str(location.get("relative_path", ""))
                ),
            }
            for location in (
                _as_mapping(raw_location)
                for raw_location in _as_sequence(violation.get("locations"))
            )
        ]
        contract_id = str(violation.get("contract_id", ""))
        violation_id = str(violation.get("violation_id", ""))
        kind = str(violation.get("kind", ""))
        groups.append(
            {
                "id": authority_group_id(contract_id, violation_id),
                "family": FAMILY_AUTHORITY,
                "category": kind,
                "kind": FINDING_KIND_AUTHORITY_VIOLATION,
                "severity": SEVERITY_WARNING,
                "confidence": CONFIDENCE_HIGH,
                "priority": _priority(SEVERITY_WARNING, EFFORT_MODERATE),
                "count": len(locations),
                "novelty": CLONE_NOVELTY_UNAVAILABLE,
                "novelty_reason": "semantic_authority_comparison_unavailable",
                "source_scope": _source_scope_from_locations(locations),
                "spread": {
                    "files": len(
                        {
                            str(location.get("relative_path", ""))
                            for location in locations
                        }
                    ),
                    "functions": len(
                        {
                            str(location.get("qualname", ""))
                            for location in locations
                            if str(location.get("qualname", ""))
                        }
                    ),
                },
                "items": locations,
                "facts": {
                    "violation_id": violation_id,
                    "contract_id": contract_id,
                    "violation_kind": kind,
                    "sink_identity": str(violation.get("sink_identity", "")),
                    "canonical_owner": str(violation.get("canonical_owner", "")),
                    "authority_status": str(
                        violation.get("authority_status", "unavailable")
                    ),
                    "producer_root_ids": sorted(
                        str(value)
                        for value in _as_sequence(violation.get("producer_root_ids"))
                    ),
                    "effect_signature": str(violation.get("effect_signature", "")),
                    "resolution_state": str(
                        violation.get("resolution_state", "unavailable")
                    ),
                    "producers": sorted(
                        str(value) for value in _as_sequence(violation.get("producers"))
                    ),
                    "algorithm_revision": str(violation.get("algorithm_revision", "")),
                },
            }
        )
    groups.sort(key=lambda group: str(group["id"]))
    return groups, suppressed


def _findings_summary(
    *,
    clone_functions: Sequence[Mapping[str, object]],
    clone_blocks: Sequence[Mapping[str, object]],
    clone_segments: Sequence[Mapping[str, object]],
    structural_groups: Sequence[Mapping[str, object]],
    dead_code_groups: Sequence[Mapping[str, object]],
    design_groups: Sequence[Mapping[str, object]],
    authority_groups: Sequence[Mapping[str, object]] = (),
    suppressed_clone_groups: Mapping[str, Sequence[Mapping[str, object]]] | None = None,
    dead_code_suppressed: int = 0,
    authority_suppressed: int = 0,
) -> dict[str, object]:
    flat_groups = [
        *clone_functions,
        *clone_blocks,
        *clone_segments,
        *structural_groups,
        *dead_code_groups,
        *design_groups,
        *authority_groups,
    ]
    severity_counts = dict.fromkeys(
        (SEVERITY_CRITICAL, SEVERITY_WARNING, SEVERITY_INFO),
        0,
    )
    source_scope_counts = dict.fromkeys(
        (IMPACT_SCOPE_RUNTIME, IMPACT_SCOPE_NON_RUNTIME, IMPACT_SCOPE_MIXED),
        0,
    )
    for group in flat_groups:
        severity = str(group.get("severity", SEVERITY_INFO))
        if severity in severity_counts:
            severity_counts[severity] += 1
        impact_scope = str(
            _as_mapping(group.get("source_scope")).get(
                "impact_scope",
                IMPACT_SCOPE_NON_RUNTIME,
            )
        )
        if impact_scope in source_scope_counts:
            source_scope_counts[impact_scope] += 1
    clone_groups = [*clone_functions, *clone_blocks, *clone_segments]
    clone_suppressed_map = _as_mapping(suppressed_clone_groups)
    suppressed_functions = len(
        _as_sequence(clone_suppressed_map.get(CLONE_KIND_FUNCTION))
    )
    suppressed_blocks = len(_as_sequence(clone_suppressed_map.get(CLONE_KIND_BLOCK)))
    suppressed_segments = len(
        _as_sequence(clone_suppressed_map.get(CLONE_KIND_SEGMENT))
    )
    suppressed_clone_total = (
        suppressed_functions + suppressed_blocks + suppressed_segments
    )
    clones_summary: dict[str, object] = {
        "functions": len(clone_functions),
        "blocks": len(clone_blocks),
        "segments": len(clone_segments),
        "instances": sum(_as_int(group.get("count")) for group in clone_groups),
        CLONE_NOVELTY_NEW: sum(
            1
            for group in clone_groups
            if str(group.get("novelty", "")) == CLONE_NOVELTY_NEW
        ),
        CLONE_NOVELTY_KNOWN: sum(
            1
            for group in clone_groups
            if str(group.get("novelty", "")) == CLONE_NOVELTY_KNOWN
        ),
        CLONE_NOVELTY_UNAVAILABLE: sum(
            1
            for group in clone_groups
            if str(group.get("novelty", "")) == CLONE_NOVELTY_UNAVAILABLE
        ),
    }
    if suppressed_clone_total > 0:
        clones_summary.update(
            {
                "suppressed": suppressed_clone_total,
                "suppressed_functions": suppressed_functions,
                "suppressed_blocks": suppressed_blocks,
                "suppressed_segments": suppressed_segments,
            }
        )
    suppressed_summary = {FAMILY_DEAD_CODE: max(0, dead_code_suppressed)}
    if authority_suppressed > 0:
        suppressed_summary[FAMILY_AUTHORITY] = authority_suppressed
    if suppressed_clone_total > 0:
        suppressed_summary[FAMILY_CLONES] = suppressed_clone_total
    return {
        "total": len(flat_groups),
        "families": {
            FAMILY_CLONES: len(clone_groups),
            FAMILY_STRUCTURAL: len(structural_groups),
            FAMILY_DEAD_CODE: len(dead_code_groups),
            "design": len(design_groups),
            FAMILY_AUTHORITY: len(authority_groups),
        },
        "severity": severity_counts,
        "impact_scope": source_scope_counts,
        "clones": clones_summary,
        "suppressed": suppressed_summary,
    }


def _build_findings_payload(
    *,
    func_groups: GroupMapLike,
    block_groups: GroupMapLike,
    segment_groups: GroupMapLike,
    block_facts: Mapping[str, Mapping[str, str]],
    structural_findings: Sequence[StructuralFindingGroup] | None,
    metrics_payload: Mapping[str, object],
    function_lane_trusted: bool,
    block_lane_trusted: bool,
    new_function_group_keys: Collection[str] | None,
    new_block_group_keys: Collection[str] | None,
    new_segment_group_keys: Collection[str] | None,
    suppressed_clone_groups: Sequence[SuppressedCloneGroup] | None,
    design_thresholds: Mapping[str, object] | None,
    scan_root: str,
    near_miss_pairs: Sequence[NearMissPair] | None = None,
    renamed_structure_groups: Sequence[RenamedStructureGroup] | None = None,
    entity_novelty_facts: Mapping[str, object] | None = None,
) -> dict[str, object]:
    clone_functions = _build_clone_groups(
        groups=func_groups,
        kind=CLONE_KIND_FUNCTION,
        lane_trusted=function_lane_trusted,
        new_keys=new_function_group_keys,
        block_facts=block_facts,
        scan_root=scan_root,
    )
    clone_blocks = _build_clone_groups(
        groups=block_groups,
        kind=CLONE_KIND_BLOCK,
        lane_trusted=block_lane_trusted,
        new_keys=new_block_group_keys,
        block_facts=block_facts,
        scan_root=scan_root,
    )
    clone_segments = _build_clone_groups(
        groups=segment_groups,
        kind=CLONE_KIND_SEGMENT,
        lane_trusted=False,
        new_keys=new_segment_group_keys,
        block_facts={},
        scan_root=scan_root,
    )
    structural_groups = _build_structural_groups(
        structural_findings,
        scan_root=scan_root,
    )
    dead_code_groups = _build_dead_code_groups(
        metrics_payload,
        scan_root=scan_root,
        entity_novelty_facts=entity_novelty_facts,
    )
    dead_code_family = _as_mapping(
        _as_mapping(metrics_payload.get("families")).get(FAMILY_DEAD_CODE)
    )
    dead_code_summary = _as_mapping(dead_code_family.get("summary"))
    dead_code_suppressed = _as_int(
        dead_code_summary.get(
            "suppressed",
            len(_as_sequence(dead_code_family.get("suppressed_items"))),
        )
    )
    design_groups = _build_design_groups(
        metrics_payload,
        design_thresholds=design_thresholds,
        scan_root=scan_root,
        entity_novelty_facts=entity_novelty_facts,
    )
    authority_groups, authority_suppressed = _build_authority_groups(metrics_payload)
    suppressed_clone_payload = _build_suppressed_clone_groups(
        groups=suppressed_clone_groups,
        block_facts=block_facts,
        scan_root=scan_root,
    )
    clone_groups_payload: dict[str, object] = {
        "functions": clone_functions,
        "blocks": clone_blocks,
        "segments": clone_segments,
    }
    if any(suppressed_clone_payload.values()):
        clone_groups_payload["suppressed"] = {
            "functions": suppressed_clone_payload[CLONE_KIND_FUNCTION],
            "blocks": suppressed_clone_payload[CLONE_KIND_BLOCK],
            "segments": suppressed_clone_payload[CLONE_KIND_SEGMENT],
        }
    return {
        "summary": _findings_summary(
            clone_functions=clone_functions,
            clone_blocks=clone_blocks,
            clone_segments=clone_segments,
            structural_groups=structural_groups,
            dead_code_groups=dead_code_groups,
            design_groups=design_groups,
            authority_groups=authority_groups,
            suppressed_clone_groups=suppressed_clone_payload,
            dead_code_suppressed=dead_code_suppressed,
            authority_suppressed=authority_suppressed,
        ),
        "groups": {
            FAMILY_CLONES: clone_groups_payload,
            FAMILY_STRUCTURAL: {
                "groups": structural_groups,
            },
            FAMILY_DEAD_CODE: {
                "groups": dead_code_groups,
            },
            "design": {
                "groups": design_groups,
            },
            FAMILY_AUTHORITY: {
                "groups": authority_groups,
            },
            # Sibling of the clone lane, never a member of it: near-miss pairs
            # must not become clone-lane keys, because those keys feed the
            # baseline lane, novelty and the gates (39Y Y8).
            "near_miss": build_near_miss_payload(
                near_miss_pairs,
                scan_root=scan_root,
            ),
            # Wave C rides beside near_miss with the same confinement: an
            # advisory channel outside every baseline lane and every gate.
            "renamed_structure": build_renamed_structure_payload(
                renamed_structure_groups,
                scan_root=scan_root,
            ),
        },
    }
