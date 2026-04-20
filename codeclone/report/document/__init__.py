# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from ...findings.ids import (
    clone_group_id,
    dead_code_group_id,
    design_group_id,
    structural_group_id,
)
from ._common import (
    _collect_paths_from_metrics,
    _collect_report_file_list,
    _contract_path,
    _count_file_lines,
    _count_file_lines_for_path,
    _is_absolute_path,
    _normalize_block_machine_facts,
    _normalize_nested_string_rows,
    _parse_ratio_percent,
    _source_scope_from_filepaths,
    _source_scope_from_locations,
)
from ._design_groups import _build_design_groups
from ._findings_groups import (
    _clone_group_assessment,
    _csv_values,
    _structural_group_assessment,
)
from .builder import build_report_document
from .derived import _combined_impact_scope, _suggestion_finding_id
from .findings import _findings_summary
from .inventory import _derive_inventory_code_counts

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
    "structural_group_id",
]
