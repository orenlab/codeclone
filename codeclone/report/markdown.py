# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from typing import TYPE_CHECKING

from .document import build_report_document
from .renderers.markdown import (
    MARKDOWN_SCHEMA_VERSION,
    _append_findings_section,
    _append_metric_items,
    _as_float,
    _location_text,
    render_markdown_report_document,
)

if TYPE_CHECKING:
    from ..models import StructuralFindingGroup, Suggestion, SuppressedCloneGroup
    from .types import GroupMapLike


def to_markdown_report(
    *,
    report_document: Mapping[str, object] | None = None,
    meta: Mapping[str, object],
    inventory: Mapping[str, object] | None = None,
    func_groups: GroupMapLike,
    block_groups: GroupMapLike,
    segment_groups: GroupMapLike,
    block_facts: Mapping[str, Mapping[str, str]] | None = None,
    new_function_group_keys: Collection[str] | None = None,
    new_block_group_keys: Collection[str] | None = None,
    new_segment_group_keys: Collection[str] | None = None,
    suppressed_clone_groups: Sequence[SuppressedCloneGroup] | None = None,
    metrics: Mapping[str, object] | None = None,
    suggestions: Collection[Suggestion] | None = None,
    structural_findings: Sequence[StructuralFindingGroup] | None = None,
) -> str:
    payload = report_document or build_report_document(
        func_groups=func_groups,
        block_groups=block_groups,
        segment_groups=segment_groups,
        meta=meta,
        inventory=inventory,
        block_facts=block_facts or {},
        new_function_group_keys=new_function_group_keys,
        new_block_group_keys=new_block_group_keys,
        new_segment_group_keys=new_segment_group_keys,
        suppressed_clone_groups=suppressed_clone_groups,
        metrics=metrics,
        suggestions=tuple(suggestions or ()),
        structural_findings=tuple(structural_findings or ()),
    )
    return render_markdown_report_document(payload)


__all__ = [
    "MARKDOWN_SCHEMA_VERSION",
    "_append_findings_section",
    "_append_metric_items",
    "_as_float",
    "_location_text",
    "render_markdown_report_document",
    "to_markdown_report",
]
