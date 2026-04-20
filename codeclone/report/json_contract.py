# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from typing import TYPE_CHECKING

from ..findings.structural.detectors import normalize_structural_findings
from .document import (
    _build_design_groups,
    _clone_group_assessment,
    _collect_paths_from_metrics,
    _combined_impact_scope,
    _contract_path,
    _count_file_lines,
    _count_file_lines_for_path,
    _csv_values,
    _derive_inventory_code_counts,
    _findings_summary,
    _is_absolute_path,
    _normalize_block_machine_facts,
    _normalize_nested_string_rows,
    _parse_ratio_percent,
    _source_scope_from_filepaths,
    _source_scope_from_locations,
    _structural_group_assessment,
    _suggestion_finding_id,
    build_report_document,
    clone_group_id,
    dead_code_group_id,
    design_group_id,
    structural_group_id,
)
from .document import _common as _document_common

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ..models import GroupMapLike, StructuralFindingGroup, SuppressedCloneGroup


def _collect_report_file_list(
    *,
    inventory: Mapping[str, object] | None,
    func_groups: GroupMapLike,
    block_groups: GroupMapLike,
    segment_groups: GroupMapLike,
    suppressed_clone_groups: Sequence[SuppressedCloneGroup] | None = None,
    metrics: Mapping[str, object] | None,
    structural_findings: Sequence[StructuralFindingGroup] | None,
) -> list[str]:
    original = _document_common.normalize_structural_findings
    _document_common.normalize_structural_findings = normalize_structural_findings
    try:
        return _document_common._collect_report_file_list(
            inventory=inventory,
            func_groups=func_groups,
            block_groups=block_groups,
            segment_groups=segment_groups,
            suppressed_clone_groups=suppressed_clone_groups,
            metrics=metrics,
            structural_findings=structural_findings,
        )
    finally:
        _document_common.normalize_structural_findings = original


__all__ = [
    "_build_design_groups",
    "_clone_group_assessment",
    "_collect_paths_from_metrics",
    "_collect_report_file_list",
    "_combined_impact_scope",
    "_contract_path",
    "_count_file_lines",
    "_count_file_lines_for_path",
    "_csv_values",
    "_derive_inventory_code_counts",
    "_findings_summary",
    "_is_absolute_path",
    "_normalize_block_machine_facts",
    "_normalize_nested_string_rows",
    "_parse_ratio_percent",
    "_source_scope_from_filepaths",
    "_source_scope_from_locations",
    "_structural_group_assessment",
    "_suggestion_finding_id",
    "build_report_document",
    "clone_group_id",
    "dead_code_group_id",
    "design_group_id",
    "normalize_structural_findings",
    "structural_group_id",
]
