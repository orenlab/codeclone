# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from .renderers.json import render_json_report_document
from .renderers.text import (
    _append_clone_section,
    _append_single_item_findings,
    _append_structural_findings,
    _append_suggestions,
    _append_suppressed_dead_code_items,
    _as_int,
    _structural_kind_label,
    render_text_report_document,
)

__all__ = [
    "_append_clone_section",
    "_append_single_item_findings",
    "_append_structural_findings",
    "_append_suggestions",
    "_append_suppressed_dead_code_items",
    "_as_int",
    "_structural_kind_label",
    "render_json_report_document",
    "render_text_report_document",
]
