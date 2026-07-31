# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Semantic-authority panel projected from canonical metric facts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from codeclone.utils.coerce import as_int as _as_int
from codeclone.utils.coerce import as_mapping as _as_mapping
from codeclone.utils.coerce import as_sequence as _as_sequence

from ..widgets.components import Tone, insight_block
from ..widgets.tables import render_rows_table
from ..widgets.tabs import render_split_tabs

if TYPE_CHECKING:
    from .._context import ReportContext


#: Contract IR failure kinds, in the words a reader can act on.
_UNRESOLVED_REASON_LABELS = {
    "unresolved_call": "unresolved call",
    "unresolved_flow": "unresolved flow",
}


def _unresolved_reason_text(item: Mapping[str, object]) -> str:
    """Say why a sink abstained; an abstention without a reason is not a fact."""

    reasons = [
        _UNRESOLVED_REASON_LABELS.get(text, text)
        for value in _as_sequence(item.get("unresolved_reasons"))
        for text in (str(value).strip(),)
        if text
    ]
    return ", ".join(reasons) if reasons else "-"


def _authority_answer(
    *,
    enabled: bool,
    active: int,
    suppressed: int,
    registry_contracts: int,
    governed_total: int,
    unresolved_total: int,
) -> tuple[str, Tone]:
    """Decide what the panel claims, worst-known first.

    An empty violation list over an unresolved population is not a clean
    result: nothing could have been found there. Abstention is reported as
    abstention rather than counted as zero.
    """

    if not enabled:
        return (
            "Semantic-authority discovery is report-only; no registry is configured.",
            "info",
        )
    if active:
        return (
            f"{active} active violations across {registry_contracts} governed "
            f"contracts; {suppressed} findings suppressed.",
            "risk",
        )
    if unresolved_total:
        return (
            f"Authority cannot be asserted: {unresolved_total} of {governed_total} "
            "governed owners are unresolved.",
            "info",
        )
    return (
        f"{active} active violations across {registry_contracts} governed "
        f"contracts; {suppressed} findings suppressed.",
        "ok",
    )


def render_authority_panel(ctx: ReportContext) -> str:
    authority = _as_mapping(ctx.metrics_map.get("semantic_authority"))
    summary = _as_mapping(authority.get("summary"))
    items = tuple(_as_mapping(item) for item in _as_sequence(authority.get("items")))
    governed = tuple(
        item for item in items if str(item.get("item_kind", "")) == "governed_sink"
    )
    violations = tuple(
        item for item in items if str(item.get("item_kind", "")) == "violation"
    )
    active = tuple(item for item in violations if not bool(item.get("suppressed")))
    suppressed = tuple(item for item in violations if bool(item.get("suppressed")))

    governed_rows = [
        (
            str(item.get("contract_id", "")),
            str(item.get("sink_identity", "")),
            str(item.get("authority_status", "")),
            str(item.get("resolution_state", "")),
            _unresolved_reason_text(item),
        )
        for item in governed
    ]
    violation_rows = [
        (
            str(item.get("contract_id", "")),
            str(item.get("kind", "")),
            str(item.get("sink_identity", "")),
            str(item.get("canonical_owner", "")),
        )
        for item in active
    ]
    suppressed_rows = [
        (
            str(item.get("contract_id", "")),
            str(item.get("kind", "")),
            str(item.get("sink_identity", "")),
            "duplicate-responsibility",
        )
        for item in suppressed
    ]

    enabled = bool(summary.get("enforcement_enabled"))
    unresolved_governed = sum(
        1
        for item in governed
        if str(item.get("authority_status", "")).strip() == "unavailable"
    )
    answer, tone = _authority_answer(
        enabled=enabled,
        active=len(active),
        suppressed=len(suppressed),
        registry_contracts=_as_int(summary.get("registry_contracts")),
        governed_total=len(governed),
        unresolved_total=unresolved_governed,
    )
    governed_panel = render_rows_table(
        headers=("Contract", "Sink", "Status", "Resolution", "Why"),
        rows=governed_rows,
        empty_message="No governed semantic sinks.",
        column_types={"Status": "status"},
        ctx=ctx,
    )
    active_panel = render_rows_table(
        headers=("Contract", "Kind", "Sink", "Canonical owner"),
        rows=violation_rows,
        empty_message="No semantic-authority violations.",
        ctx=ctx,
    )
    suppressed_panel = render_rows_table(
        headers=("Contract", "Kind", "Sink", "Rule"),
        rows=suppressed_rows,
        empty_message="No suppressed semantic-authority findings.",
        ctx=ctx,
    )
    return insight_block(
        question="Is each governed semantic contract owned by one authority?",
        answer=answer,
        tone=tone,
    ) + render_split_tabs(
        group_id="semantic-authority",
        tabs=(
            ("violations", "Violations", len(active), active_panel),
            ("governed", "Governed sinks", len(governed), governed_panel),
            ("suppressed", "Suppressed", len(suppressed), suppressed_panel),
        ),
    )


__all__ = ["render_authority_panel"]
