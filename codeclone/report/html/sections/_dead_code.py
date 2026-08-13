# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Dead Code panel renderer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from codeclone.utils import coerce as _coerce

from ..widgets.badges import _micro_badges, _stat_card
from ..widgets.components import Tone, insight_block
from ..widgets.glossary import glossary_tip
from ..widgets.tables import (
    ORDER_BY_LOCATION,
    ORDER_WORST_FIRST,
    graded_coverage,
    render_rows_table,
    row_cut_note_html,
)
from ..widgets.tabs import render_split_tabs

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from .._context import ReportContext

_as_int = _coerce.as_int
_as_mapping = _coerce.as_mapping
_as_sequence = _coerce.as_sequence

#: Rows drawn per dead-code tab. Both tabs declare their cut, but for
#: different reasons: the active list is ranked by confidence, so the band can
#: also say how much of the high-confidence population is on screen, while the
#: suppressed list is ordered by file path -- there the cut keeps whatever
#: sorts first, which is a reason to state it louder, not quieter.
_DEAD_CODE_ROW_LIMIT = 200


def _dead_row(
    item: Mapping[str, object], ctx: ReportContext
) -> tuple[str, str, str, str, str, str, str]:
    test_reference_sources = ", ".join(
        str(source) for source in _as_sequence(item.get("test_reference_sources"))
    )
    return (
        str(item.get("qualname", "")),
        str(item.get("relative_path", "")),
        str(item.get("start_line", "")),
        str(item.get("kind", "")),
        str(item.get("confidence", "")),
        str(item.get("reason", "unreferenced")),
        test_reference_sources,
    )


def _active_dead_code_table(ctx: ReportContext, items_data: Sequence[object]) -> str:
    """The active candidates table, declaring what the row cut left behind."""

    shown = [_as_mapping(it) for it in items_data[:_DEAD_CODE_ROW_LIMIT]]
    return render_rows_table(
        headers=(
            "Name",
            "File",
            "Line",
            "Kind",
            "Confidence",
            "Reason",
            "Held by tests",
        ),
        rows=[_dead_row(item, ctx) for item in shown],
        empty_message="No dead code detected.",
        empty_description=(
            "An entry appears when a definition has no reference anywhere in "
            "the analysed set, so an empty list means every definition is used."
        ),
        row_cut_note=row_cut_note_html(
            total=len(items_data),
            shown=len(shown),
            ordering=ORDER_WORST_FIRST,
            covered=graded_coverage(
                "high-confidence",
                [_as_mapping(it) for it in items_data],
                shown,
                field="confidence",
                value="high",
            ),
        ),
        ctx=ctx,
    )


def _suppressed_dead_code_row(
    item: Mapping[str, object],
    ctx: ReportContext,
) -> tuple[str, str, str, str, str, str, str, str, str]:
    suppressed_by = _as_sequence(item.get("suppressed_by"))
    first = _as_mapping(suppressed_by[0]) if suppressed_by else {}
    return (
        *_dead_row(item, ctx),
        str(first.get("rule", "")),
        str(first.get("source", "")),
    )


def _suppressed_dead_code_table(
    ctx: ReportContext,
    suppressed_data: Sequence[object],
) -> str:
    """The suppressed candidates table, which cannot claim a useful ordering.

    No coverage claim and no "worst first": the document orders this list by
    path and line, so the two hundred rows drawn are the ones whose files sort
    first, not the ones worth reading first. Naming the ordering is the whole
    point -- a reader who assumed otherwise here would be wrong.
    """

    shown = [_as_mapping(it) for it in suppressed_data[:_DEAD_CODE_ROW_LIMIT]]
    return render_rows_table(
        headers=(
            "Name",
            "File",
            "Line",
            "Kind",
            "Confidence",
            "Reason",
            "Held by tests",
            "Rule",
            "Source",
        ),
        rows=[_suppressed_dead_code_row(item, ctx) for item in shown],
        empty_message="No suppressed dead-code candidates.",
        empty_description=(
            "Entries land here when a suppression rule in your configuration "
            "excludes a candidate, so this fills only once a rule matches."
        ),
        column_types={"Source": "source_kind"},
        row_cut_note=row_cut_note_html(
            total=len(suppressed_data),
            shown=len(shown),
            ordering=ORDER_BY_LOCATION,
        ),
        ctx=ctx,
    )


def render_dead_code_panel(ctx: ReportContext) -> str:
    summary = _as_mapping(ctx.dead_code_map.get("summary"))
    dead_total = _as_int(summary.get("total"))
    dead_high_conf = _as_int(summary.get("high_confidence", summary.get("critical")))
    dead_suppressed_total = _as_int(summary.get("suppressed", 0))
    dead_unresolved_total = _as_int(summary.get("unresolved_external_override", 0))
    # Published once by the metrics payload and read here, exactly as the
    # gate and the text/markdown surfaces read it. This panel used to say
    # "No dead code detected." beside ten published statement findings
    # because it only ever asked about unreferenced symbols.
    dead_unreachable_total = _as_int(summary.get("unreachable_statements", 0))

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

    # Insight
    answer: str
    tone: Tone
    if not ctx.metrics_available:
        answer, tone = "Metrics are skipped for this run.", "info"
    else:
        answer = (
            f"{dead_total} candidates total; "
            f"{dead_high_conf} high-confidence items; "
            f"{dead_unreachable_total} unreachable statement region(s); "
            f"{dead_suppressed_total} suppressed."
        )
        if dead_unresolved_total:
            answer += (
                f" {dead_unresolved_total} unresolved override(s) abstained:"
                " neither dead nor live."
            )
        if dead_high_conf > 0 or dead_unreachable_total > 0:
            tone = "risk"
        elif dead_total > 0:
            tone = "warn"
        else:
            tone = "ok"

    active_panel = _active_dead_code_table(ctx, items_data)
    suppressed_panel = _suppressed_dead_code_table(ctx, suppressed_data)

    # Stat cards
    pct = (dead_high_conf / max(1, dead_total)) * 100 if dead_total > 0 else 0
    dead_cards = [
        _stat_card(
            "Candidates",
            dead_total,
            detail=_micro_badges(("active", dead_total)),
            value_tone="warn" if dead_total > 0 else "good",
            glossary_tip_fn=glossary_tip,
        ),
        _stat_card(
            "High confidence",
            dead_high_conf,
            detail=_micro_badges(("of total", dead_total)),
            value_tone="bad" if dead_high_conf > 0 else "good",
            glossary_tip_fn=glossary_tip,
        ),
        _stat_card(
            "Suppressed",
            dead_suppressed_total,
            value_tone="muted",
            glossary_tip_fn=glossary_tip,
        ),
        # Deliberately "muted", never "bad": an abstention is not a finding
        # the reader should act on, it is the analysis declining to claim one.
        _stat_card(
            "Unresolved overrides",
            dead_unresolved_total,
            detail=_micro_badges(("abstained", dead_unresolved_total)),
            value_tone="muted",
            glossary_tip_fn=glossary_tip,
        ),
        _stat_card(
            "Hit rate",
            f"{pct:.0f}%",
            detail=_micro_badges(("high vs total", "")),
            value_tone="bad" if pct > 50 else "warn" if pct > 20 else "good",
            glossary_tip_fn=glossary_tip,
        ),
    ]
    cards_html = f'<div class="stat-cards">{"".join(dead_cards)}</div>'

    return (
        insight_block(
            question="Do we have actionable unused code?",
            answer=answer,
            tone=tone,
        )
        + cards_html
        + render_split_tabs(
            group_id="dead-code",
            tabs=(
                ("active", "Active", dead_total, active_panel),
                ("suppressed", "Suppressed", dead_suppressed_total, suppressed_panel),
            ),
        )
    )
