# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from ..grouping import build_block_groups, build_groups, build_segment_groups
from .blocks import prepare_block_report_groups
from .explain import build_block_group_facts
from .markdown import render_markdown_report_document, to_markdown_report
from .sarif import render_sarif_report_document, to_sarif_report
from .segments import (
    SEGMENT_MIN_UNIQUE_STMT_TYPES,
    prepare_segment_report_groups,
)
from .serialize import (
    render_json_report_document,
    render_text_report_document,
)
from .suggestions import classify_clone_type, generate_suggestions
from .types import GroupItem, GroupMap

__all__ = [
    "SEGMENT_MIN_UNIQUE_STMT_TYPES",
    "GroupItem",
    "GroupMap",
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
