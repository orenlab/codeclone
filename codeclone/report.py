"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

from ._report_blocks import _merge_block_items, prepare_block_report_groups
from ._report_explain import build_block_group_facts
from ._report_grouping import build_block_groups, build_groups, build_segment_groups
from ._report_segments import (
    _CONTROL_FLOW_STMTS,
    _FORBIDDEN_STMTS,
    SEGMENT_MIN_UNIQUE_STMT_TYPES,
    _analyze_segment_statements,
    _assign_targets_attribute_only,
    _collect_file_functions,
    _merge_segment_items,
    _QualnameCollector,
    _segment_statements,
    _SegmentAnalysis,
    prepare_segment_report_groups,
)
from ._report_serialize import (
    _format_meta_text_value,
    to_json,
    to_json_report,
    to_text,
    to_text_report,
)
from ._report_types import GroupItem, GroupMap

__all__ = [
    "SEGMENT_MIN_UNIQUE_STMT_TYPES",
    "_CONTROL_FLOW_STMTS",
    "_FORBIDDEN_STMTS",
    "GroupItem",
    "GroupMap",
    "_QualnameCollector",
    "_SegmentAnalysis",
    "_analyze_segment_statements",
    "_assign_targets_attribute_only",
    "_collect_file_functions",
    "_format_meta_text_value",
    "_merge_block_items",
    "_merge_segment_items",
    "_segment_statements",
    "build_block_group_facts",
    "build_block_groups",
    "build_groups",
    "build_segment_groups",
    "prepare_block_report_groups",
    "prepare_segment_report_groups",
    "to_json",
    "to_json_report",
    "to_text",
    "to_text_report",
]
