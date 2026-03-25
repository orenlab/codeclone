# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from ..extractor import _QualnameCollector
from ..grouping import build_block_groups, build_groups, build_segment_groups
from .blocks import merge_block_items as _merge_block_items
from .blocks import prepare_block_report_groups
from .explain import build_block_group_facts
from .markdown import render_markdown_report_document, to_markdown_report
from .sarif import render_sarif_report_document, to_sarif_report
from .segments import (
    _CONTROL_FLOW_STMTS,
    _FORBIDDEN_STMTS,
    SEGMENT_MIN_UNIQUE_STMT_TYPES,
    _SegmentAnalysis,
    prepare_segment_report_groups,
)
from .segments import (
    analyze_segment_statements as _analyze_segment_statements,
)
from .segments import (
    assign_targets_attribute_only as _assign_targets_attribute_only,
)
from .segments import (
    collect_file_functions as _collect_file_functions,
)
from .segments import (
    merge_segment_items as _merge_segment_items,
)
from .segments import (
    segment_statements as _segment_statements,
)
from .serialize import (
    format_meta_text_value as _format_meta_text_value,
)
from .serialize import (
    render_json_report_document,
    render_text_report_document,
)
from .suggestions import classify_clone_type, generate_suggestions
from .types import GroupItem, GroupMap

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
    "classify_clone_type",
    "generate_suggestions",
    "prepare_block_report_groups",
    "prepare_segment_report_groups",
    "render_json_report_document",
    "render_markdown_report_document",
    "render_sarif_report_document",
    "render_text_report_document",
    "to_markdown_report",
    "to_sarif_report",
]
