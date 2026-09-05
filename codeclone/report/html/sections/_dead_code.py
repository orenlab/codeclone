# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Dead Code panel renderer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from codeclone.utils import coerce as _coerce

from ...messages.explain import plural_word
from ...messages.glossary import GLOSSARY_FAMILY_DEAD_CODE
from ...messages.sections import METRICS_SKIPPED
from ..primitives.escape import _escape_html
from ..widgets.badges import _micro_badges, _stat_card
from ..widgets.components import Tone, insight_block
from ..widgets.glossary import family_glossary_tip
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
# The family this panel speaks for. Bound once so every card, table
# and tab in this module asks the glossary as the same family.
_TIP = family_glossary_tip(GLOSSARY_FAMILY_DEAD_CODE)


_DEAD_CODE_ROW_LIMIT = 200

#: How a candidate's ``reason`` reads on the page. The document's vocabulary
#: is restated, never widened: an unknown reason is drawn as its own words.
_REASON_LABELS = {
    "test_only_reference": "test-only reference",
    "unreferenced": "unreferenced",
}

#: Tips for the cards whose label the glossary does not carry. ``{world}`` is
#: the document's own ``world_contract`` word.
_TIP_UNREACHABLE = "Statement regions no execution path can reach"
_TIP_UNRESOLVED_OVERRIDES = (
    "Overrides the analysis could not resolve: abstained, neither dead nor live"
)
_TIP_UNRESOLVED_REACH = (
    "Externally reachable with no internal evidence under the {world} world "
    "contract: abstained, neither dead nor live"
)
_ABSTENTIONS_NOTE = (
    "Abstentions are counted on the cards, not listed: neither dead nor live."
)


def _reason_label(reason: str) -> str:
    return _REASON_LABELS.get(reason, reason.replace("_", " "))


def _held_by_tests_html(sources: Sequence[str]) -> str:
    """The tests that hold a candidate, one chip per test module.

    This column answers "what breaks if I delete this", and it answered in
    the least readable way on the page: every dotted test id poured into a
    narrow column, one row swelling to fifteen visual lines. The reader's
    first question is which test *files* hold the symbol, so a chip per
    module carries that, with how many tests in it when more than one; the
    full ids stay in the cell, one click away, so nothing the document
    carries is lost -- the chips are the same list, grouped.
    """

    if not sources:
        return ""
    by_module: dict[str, list[str]] = {}
    for source in sources:
        module, _separator, test = source.partition(":")
        by_module.setdefault(module or source, []).append(test or source)
    chips: list[str] = []
    for module, tests in by_module.items():
        count = (
            f' <span class="held-test-count">&times;{len(tests)}</span>'
            if len(tests) > 1
            else ""
        )
        # A module name breaks at its dots, never mid-word, and is never
        # clipped: a chip that hid the end of the name would hide the one
        # segment that tells two test modules apart.
        module_html = _escape_html(module).replace(".", ".<wbr>")
        chips.append(
            f'<span class="held-test" title="{_escape_html(", ".join(tests))}">'
            f"{module_html}{count}</span>"
        )
    items = "".join(
        f"<li><code>{_escape_html(source)}</code></li>" for source in sources
    )
    return (
        f'<details class="held-tests"><summary>{"".join(chips)}</summary>'
        f'<ul class="held-tests-list">{items}</ul></details>'
    )


def _dead_row(
    item: Mapping[str, object], ctx: ReportContext
) -> tuple[str, str, str, str, str, str, str]:
    sources = [
        str(source) for source in _as_sequence(item.get("test_reference_sources"))
    ]
    return (
        str(item.get("qualname", "")),
        str(item.get("relative_path", "")),
        str(item.get("start_line", "")),
        str(item.get("kind", "")),
        str(item.get("confidence", "")),
        _reason_label(str(item.get("reason", "unreferenced"))),
        _held_by_tests_html(sources),
    )


def _active_dead_code_table(ctx: ReportContext, items_data: Sequence[object]) -> str:
    """The active candidates table, declaring what the row cut left behind."""

    shown = [_as_mapping(it) for it in items_data[:_DEAD_CODE_ROW_LIMIT]]
    return render_rows_table(
        family=GLOSSARY_FAMILY_DEAD_CODE,
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
        raw_html_headers=("Held by tests",),
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
        family=GLOSSARY_FAMILY_DEAD_CODE,
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
        raw_html_headers=("Held by tests",),
        column_types={"Source": "source_kind"},
        row_cut_note=row_cut_note_html(
            total=len(suppressed_data),
            shown=len(shown),
            ordering=ORDER_BY_LOCATION,
        ),
        ctx=ctx,
    )


def _dead_code_answer(
    *,
    dead_total: int,
    dead_high_conf: int,
    dead_unreachable_total: int,
    abstained: bool,
) -> tuple[str, Tone]:
    """The verdict in words; the breakdown is the cards' to draw.

    The banner used to restate every card under it in prose -- five numbers
    said twice on one screen. It now answers the question it asks and names
    the one figure a reader acts on; abstentions are pointed at, not counted
    again, because they are the analysis declining to claim a finding.
    """

    tone: Tone
    if dead_high_conf > 0 or dead_unreachable_total > 0:
        parts = [
            f"Yes: {dead_high_conf} high-confidence "
            f"{plural_word(dead_high_conf, 'candidate', 'candidates')}"
        ]
        if dead_unreachable_total > 0:
            parts.append(
                f"{dead_unreachable_total} unreachable statement "
                f"{plural_word(dead_unreachable_total, 'region', 'regions')}"
            )
        answer = " and ".join(parts) + "."
        tone = "risk"
    elif dead_total > 0:
        answer = (
            f"{dead_total} lower-confidence "
            f"{plural_word(dead_total, 'candidate', 'candidates')}; none "
            "high-confidence."
        )
        tone = "warn"
    else:
        answer = "No dead-code candidates."
        tone = "ok"
    if abstained:
        answer += f" {_ABSTENTIONS_NOTE}"
    return answer, tone


def render_dead_code_panel(ctx: ReportContext) -> str:
    summary = _as_mapping(ctx.dead_code_map.get("summary"))
    dead_total = _as_int(summary.get("total"))
    # ``critical`` was the raw metrics payload's spelling; the report document
    # renamed it to ``high_confidence`` and emits only that, so the fallback
    # could not fire in any configuration.
    dead_high_conf = _as_int(summary.get("high_confidence"))
    dead_suppressed_total = _as_int(summary.get("suppressed", 0))
    dead_unresolved_total = _as_int(summary.get("unresolved_external_override", 0))
    dead_unresolved_reach_total = _as_int(summary.get("unresolved", 0))
    dead_world_contract = str(summary.get("world_contract", ""))
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
        answer, tone = METRICS_SKIPPED, "info"
    else:
        answer, tone = _dead_code_answer(
            dead_total=dead_total,
            dead_high_conf=dead_high_conf,
            dead_unreachable_total=dead_unreachable_total,
            abstained=bool(dead_unresolved_total or dead_unresolved_reach_total),
        )

    active_panel = _active_dead_code_table(ctx, items_data)
    suppressed_panel = _suppressed_dead_code_table(ctx, suppressed_data)

    # Stat cards: every figure the summary publishes, each once. The largest
    # number on this page -- the unresolved external-reach abstentions -- used
    # to live only inside the banner's prose; the "hit rate" card that read
    # 100 % whenever every candidate was high-confidence is gone, because
    # "high of total" is what the Candidates caption already says.
    world = dead_world_contract or "declared"
    dead_cards = [
        _stat_card(
            "Candidates",
            dead_total,
            detail=_micro_badges(("high-confidence", dead_high_conf)),
            value_tone=(
                "bad" if dead_high_conf > 0 else ("warn" if dead_total > 0 else "good")
            ),
            glossary_tip_fn=_TIP,
        ),
        _stat_card(
            "Unreachable regions",
            dead_unreachable_total,
            tip=_TIP_UNREACHABLE,
            value_tone="bad" if dead_unreachable_total > 0 else "good",
        ),
        _stat_card(
            "Suppressed",
            dead_suppressed_total,
            value_tone="muted",
            glossary_tip_fn=_TIP,
        ),
        # Deliberately "muted", never "bad": an abstention is not a finding
        # the reader should act on, it is the analysis declining to claim one.
        _stat_card(
            "Unresolved overrides",
            dead_unresolved_total,
            tip=_TIP_UNRESOLVED_OVERRIDES,
            value_tone="muted",
        ),
        _stat_card(
            "Unresolved external reach",
            dead_unresolved_reach_total,
            subtext=f"{world} world contract",
            tip=_TIP_UNRESOLVED_REACH.format(world=world),
            value_tone="muted",
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
            family=GLOSSARY_FAMILY_DEAD_CODE,
            group_id="dead-code",
            tabs=(
                ("active", "Active", dead_total, active_panel),
                ("suppressed", "Suppressed", dead_suppressed_total, suppressed_panel),
            ),
        )
    )
