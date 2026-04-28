# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from typing import TYPE_CHECKING

from ...contracts import (
    REPORT_SCHEMA_VERSION,
)
from ...utils.coerce import as_mapping as _as_mapping

if TYPE_CHECKING:
    from ...models import (
        GroupMapLike,
        StructuralFindingGroup,
        Suggestion,
        SuppressedCloneGroup,
    )

from ._common import _collect_report_file_list
from .derived import _build_derived_overview, _build_derived_suggestions
from .findings import _build_findings_payload
from .integrity import _build_integrity_payload
from .inventory import (
    _baseline_is_trusted,
    _build_inventory_payload,
    _build_meta_payload,
)
from .metrics import _build_metrics_payload


def build_report_document(
    *,
    func_groups: GroupMapLike,
    block_groups: GroupMapLike,
    segment_groups: GroupMapLike,
    meta: Mapping[str, object] | None = None,
    inventory: Mapping[str, object] | None = None,
    block_facts: Mapping[str, Mapping[str, str]] | None = None,
    new_function_group_keys: Collection[str] | None = None,
    new_block_group_keys: Collection[str] | None = None,
    new_segment_group_keys: Collection[str] | None = None,
    suppressed_clone_groups: Sequence[SuppressedCloneGroup] | None = None,
    metrics: Mapping[str, object] | None = None,
    suggestions: Sequence[Suggestion] | None = None,
    structural_findings: Sequence[StructuralFindingGroup] | None = None,
) -> dict[str, object]:
    report_schema_version = REPORT_SCHEMA_VERSION
    scan_root = str(_as_mapping(meta).get("scan_root", ""))
    meta_payload = _build_meta_payload(meta, scan_root=scan_root)
    design_thresholds = _as_mapping(
        _as_mapping(meta_payload.get("analysis_thresholds")).get("design_findings")
    )
    metrics_payload = _build_metrics_payload(metrics, scan_root=scan_root)
    file_list = _collect_report_file_list(
        inventory=inventory,
        func_groups=func_groups,
        block_groups=block_groups,
        segment_groups=segment_groups,
        suppressed_clone_groups=suppressed_clone_groups,
        metrics=metrics,
        structural_findings=structural_findings,
    )
    inventory_payload = _build_inventory_payload(
        inventory=inventory,
        file_list=file_list,
        metrics_payload=metrics_payload,
        scan_root=scan_root,
    )
    findings_payload = _build_findings_payload(
        func_groups=func_groups,
        block_groups=block_groups,
        segment_groups=segment_groups,
        block_facts=block_facts or {},
        structural_findings=structural_findings,
        metrics_payload=metrics_payload,
        baseline_trusted=_baseline_is_trusted(meta_payload),
        new_function_group_keys=new_function_group_keys,
        new_block_group_keys=new_block_group_keys,
        new_segment_group_keys=new_segment_group_keys,
        suppressed_clone_groups=suppressed_clone_groups,
        design_thresholds=design_thresholds,
        scan_root=scan_root,
    )
    overview_payload, hotlists_payload = _build_derived_overview(
        findings=findings_payload,
        metrics_payload=metrics_payload,
    )
    derived_payload = {
        "suggestions": _build_derived_suggestions(suggestions),
        "overview": overview_payload,
        "hotlists": hotlists_payload,
    }
    integrity_payload = _build_integrity_payload(
        report_schema_version=report_schema_version,
        meta=meta_payload,
        inventory=inventory_payload,
        findings=findings_payload,
        metrics=metrics_payload,
    )
    return {
        "report_schema_version": report_schema_version,
        "meta": meta_payload,
        "inventory": inventory_payload,
        "findings": findings_payload,
        "metrics": metrics_payload,
        "derived": derived_payload,
        "integrity": integrity_payload,
    }
