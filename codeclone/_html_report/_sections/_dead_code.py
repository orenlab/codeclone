# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

"""Dead Code panel renderer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ... import _coerce
from .._components import Tone, insight_block
from .._tables import render_rows_table
from .._tabs import render_split_tabs

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .._context import ReportContext

_as_int = _coerce.as_int
_as_mapping = _coerce.as_mapping
_as_sequence = _coerce.as_sequence


def _dead_row(
    item: Mapping[str, object], ctx: ReportContext
) -> tuple[str, str, str, str, str]:
    return (
        ctx.bare_qualname(str(item.get("qualname", "")), str(item.get("filepath", ""))),
        str(item.get("filepath", "")),
        str(item.get("start_line", "")),
        str(item.get("kind", "")),
        str(item.get("confidence", "")),
    )


def render_dead_code_panel(ctx: ReportContext) -> str:
    summary = _as_mapping(ctx.dead_code_map.get("summary"))
    dead_total = _as_int(summary.get("total"))
    dead_high_conf = _as_int(summary.get("high_confidence", summary.get("critical")))
    dead_suppressed_total = _as_int(summary.get("suppressed", 0))

    # Count high confidence from items if summary is 0 but items have them
    items_data = _as_sequence(ctx.dead_code_map.get("items"))
    suppressed_data = _as_sequence(ctx.dead_code_map.get("suppressed_items"))
    hi_conf_items = sum(
        1
        for it in items_data
        if str(_as_mapping(it).get("confidence", "")).strip().lower() == "high"
    )
    if dead_total > 0 and dead_high_conf == 0 and hi_conf_items > 0:
        dead_high_conf = min(dead_total, hi_conf_items)
    if dead_suppressed_total == 0:
        dead_suppressed_total = len(suppressed_data)

    # Rows
    active_rows = [_dead_row(_as_mapping(it), ctx) for it in items_data[:200]]
    suppressed_rows: list[tuple[str, str, str, str, str, str, str]] = []
    for it in suppressed_data[:200]:
        im = _as_mapping(it)
        suppressed_by = _as_sequence(im.get("suppressed_by"))
        first = _as_mapping(suppressed_by[0]) if suppressed_by else {}
        suppressed_rows.append(
            (
                *_dead_row(im, ctx),
                str(first.get("rule", "")),
                str(first.get("source", "")),
            )
        )

    # Insight
    answer: str
    tone: Tone
    if not ctx.metrics_available:
        answer, tone = "Metrics are skipped for this run.", "info"
    else:
        answer = (
            f"{dead_total} candidates total; "
            f"{dead_high_conf} high-confidence items; "
            f"{dead_suppressed_total} suppressed."
        )
        if dead_high_conf > 0:
            tone = "risk"
        elif dead_total > 0:
            tone = "warn"
        else:
            tone = "ok"

    active_panel = render_rows_table(
        headers=("Name", "File", "Line", "Kind", "Confidence"),
        rows=active_rows,
        empty_message="No dead code detected.",
        ctx=ctx,
    )
    suppressed_panel = render_rows_table(
        headers=("Name", "File", "Line", "Kind", "Confidence", "Rule", "Source"),
        rows=suppressed_rows,
        empty_message="No suppressed dead-code candidates.",
        ctx=ctx,
    )

    return insight_block(
        question="Do we have actionable unused code?",
        answer=answer,
        tone=tone,
    ) + render_split_tabs(
        group_id="dead-code",
        tabs=(
            ("active", "Active", dead_total, active_panel),
            ("suppressed", "Suppressed", dead_suppressed_total, suppressed_panel),
        ),
    )
