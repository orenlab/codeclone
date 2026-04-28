# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from typing import TYPE_CHECKING

from ...domain.findings import (
    CLONE_KIND_BLOCK,
    CLONE_KIND_FUNCTION,
    CLONE_KIND_SEGMENT,
    CLONE_NOVELTY_KNOWN,
    CLONE_NOVELTY_NEW,
    FAMILY_CLONES,
    FAMILY_DEAD_CODE,
    FAMILY_STRUCTURAL,
)
from ...domain.quality import (
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_WARNING,
)
from ...domain.source_scope import (
    IMPACT_SCOPE_MIXED,
    IMPACT_SCOPE_NON_RUNTIME,
    IMPACT_SCOPE_RUNTIME,
)
from ...utils.coerce import as_int as _as_int
from ...utils.coerce import as_mapping as _as_mapping
from ...utils.coerce import as_sequence as _as_sequence

if TYPE_CHECKING:
    from ...models import (
        GroupMapLike,
        StructuralFindingGroup,
        SuppressedCloneGroup,
    )

from ._design_groups import _build_design_groups
from ._findings_groups import (
    _build_clone_groups,
    _build_dead_code_groups,
    _build_structural_groups,
    _build_suppressed_clone_groups,
)


def _findings_summary(
    *,
    clone_functions: Sequence[Mapping[str, object]],
    clone_blocks: Sequence[Mapping[str, object]],
    clone_segments: Sequence[Mapping[str, object]],
    structural_groups: Sequence[Mapping[str, object]],
    dead_code_groups: Sequence[Mapping[str, object]],
    design_groups: Sequence[Mapping[str, object]],
    suppressed_clone_groups: Mapping[str, Sequence[Mapping[str, object]]] | None = None,
    dead_code_suppressed: int = 0,
) -> dict[str, object]:
    flat_groups = [
        *clone_functions,
        *clone_blocks,
        *clone_segments,
        *structural_groups,
        *dead_code_groups,
        *design_groups,
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
    suppressed_functions = len(_as_sequence(clone_suppressed_map.get("function")))
    suppressed_blocks = len(_as_sequence(clone_suppressed_map.get("block")))
    suppressed_segments = len(_as_sequence(clone_suppressed_map.get("segment")))
    suppressed_clone_total = (
        suppressed_functions + suppressed_blocks + suppressed_segments
    )
    clones_summary: dict[str, object] = {
        "functions": len(clone_functions),
        "blocks": len(clone_blocks),
        "segments": len(clone_segments),
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
    suppressed_summary = {
        FAMILY_DEAD_CODE: max(0, dead_code_suppressed),
    }
    if suppressed_clone_total > 0:
        suppressed_summary[FAMILY_CLONES] = suppressed_clone_total
    return {
        "total": len(flat_groups),
        "families": {
            FAMILY_CLONES: len(clone_groups),
            FAMILY_STRUCTURAL: len(structural_groups),
            FAMILY_DEAD_CODE: len(dead_code_groups),
            "design": len(design_groups),
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
    baseline_trusted: bool,
    new_function_group_keys: Collection[str] | None,
    new_block_group_keys: Collection[str] | None,
    new_segment_group_keys: Collection[str] | None,
    suppressed_clone_groups: Sequence[SuppressedCloneGroup] | None,
    design_thresholds: Mapping[str, object] | None,
    scan_root: str,
) -> dict[str, object]:
    clone_functions = _build_clone_groups(
        groups=func_groups,
        kind=CLONE_KIND_FUNCTION,
        baseline_trusted=baseline_trusted,
        new_keys=new_function_group_keys,
        block_facts=block_facts,
        scan_root=scan_root,
    )
    clone_blocks = _build_clone_groups(
        groups=block_groups,
        kind=CLONE_KIND_BLOCK,
        baseline_trusted=baseline_trusted,
        new_keys=new_block_group_keys,
        block_facts=block_facts,
        scan_root=scan_root,
    )
    clone_segments = _build_clone_groups(
        groups=segment_groups,
        kind=CLONE_KIND_SEGMENT,
        baseline_trusted=baseline_trusted,
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
    )
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
            suppressed_clone_groups=suppressed_clone_payload,
            dead_code_suppressed=dead_code_suppressed,
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
        },
    }
