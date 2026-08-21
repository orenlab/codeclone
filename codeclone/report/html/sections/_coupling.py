# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Coupling + Cohesion panel renderer (unified Quality tab)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from codeclone.utils import coerce as _coerce

from ...messages.coverage_join import COVERAGE_JOIN_UNAVAILABLE
from ..widgets.badges import _micro_badges, _render_chain_flow, _stat_card
from ..widgets.components import Tone, insight_block
from ..widgets.glossary import glossary_tip
from ..widgets.tables import (
    ORDER_WORST_FIRST,
    graded_coverage,
    render_rows_table,
    row_cut_note_html,
)
from ..widgets.tabs import render_split_tabs
from ._coverage_join import (
    coverage_join_quality_count,
    coverage_join_quality_summary,
    render_coverage_join_panel,
)
from ._security_surfaces import (
    render_security_surfaces_panel,
    security_surfaces_quality_count,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from .._context import ReportContext

_as_float = _coerce.as_float
_as_int = _coerce.as_int
_as_mapping = _coerce.as_mapping
_as_sequence = _coerce.as_sequence

#: Rows drawn per quality sub-tab. The three families arrive at the scale of
#: the whole tree -- twelve thousand functions on this repository -- so the
#: table shows the head of the document's own ranking and states the rest.
#:
#: Every one of these three tables takes the *declaring* branch of the choice
#: rather than the silent one: the document does rank them worst-first
#: (``_operational_sort_key``: risk descending, then the metric that earned
#: the rank), so the cut demonstrably keeps the worst rows -- but that alone
#: cannot promise the card above the table is covered. The high-risk
#: population is not bounded by fifty on any repository, so a panel that
#: leaned on the ordering alone would be silently wrong exactly on the
#: repositories where it matters. The band therefore says both: how much of
#: the table is drawn, and how much of the graded population reached it.
_QUALITY_TABLE_ROW_LIMIT = 50


def _render_coupled_cell(row_data: Mapping[str, object]) -> str:
    raw = _as_sequence(row_data.get("coupled_classes"))
    names = sorted(
        {str(v).strip() for v in raw if isinstance(v, str) and str(v).strip()}
    )
    if not names:
        return "-"
    if len(names) <= 3:
        return _render_chain_flow(names)
    preview = _render_chain_flow(names[:3])
    full = _render_chain_flow(names)
    rem = len(names) - 3
    return (
        '<details class="coupled-details">'
        '<summary class="coupled-summary">'
        f'{preview}<span class="coupled-more">(+{rem} more)</span>'
        "</summary>"
        f'<div class="coupled-expanded">{full}</div>'
        "</details>"
    )


def _quality_high_risk_coverage(
    all_rows: Sequence[object],
    shown_rows: Sequence[Mapping[str, object]],
) -> tuple[str, int, int] | None:
    """How many of the family's high-risk rows the fifty-row cut kept.

    All three quality families publish ``risk`` on every row, so the answer is
    the document's own verdict counted twice over the same list -- once over
    what the panel held, once over what it drew.
    """

    return graded_coverage(
        "high-risk",
        [_as_mapping(row) for row in all_rows],
        shown_rows,
        field="risk",
        value="high",
    )


def _summary_card_inputs(
    summary: Mapping[str, object],
    *,
    max_key: str,
) -> tuple[int, int, int, float]:
    """The four figures a metric card band shows, all read from the document.

    The average and the population used to be re-derived here from the rendered
    rows, over the rows with a positive value only. That divided by the classes
    that happen to be coupled rather than by the measured population, so the
    HTML answered a metric question differently from the same run's text,
    Markdown, SARIF and CLI output -- 2.9 against the document's 1.41 on this
    repository. The presentation layer shows what the document carries; it does
    not recompute it.
    """

    return (
        _as_int(summary.get("high_risk")),
        _as_int(summary.get("total")),
        _as_int(summary.get(max_key)),
        _as_float(summary.get("average")),
    )


def _complexity_cards(
    summary: Mapping[str, object],
    rows_data: Sequence[object],
) -> str:
    high_risk, total, max_cc, avg_cc = _summary_card_inputs(summary, max_key="max")
    deep = sum(1 for r in rows_data if _as_int(_as_mapping(r).get("nesting_depth")) > 4)
    cards = [
        _stat_card(
            "High-risk functions",
            high_risk,
            detail=_micro_badges(("total", total)),
            value_tone="bad" if high_risk > 0 else "good",
            glossary_tip_fn=glossary_tip,
        ),
        _stat_card(
            "Max CC",
            max_cc,
            detail=_micro_badges(("target", "< 10")),
            value_tone="bad" if max_cc > 15 else "warn" if max_cc > 10 else "good",
            glossary_tip_fn=glossary_tip,
        ),
        _stat_card(
            "Avg CC",
            f"{avg_cc:.1f}",
            detail=_micro_badges(("functions", total)),
            # No tone, deliberately. The product calibrates bands for a row's
            # ``risk``; it publishes none for an average, so the five this card
            # used to grade against ("warn" above it, "good" below) was the
            # renderer's own invention -- a verdict on a scale that exists
            # nowhere in the document, the contracts or any reference
            # population. The figure is printed; grading it is not
            # presentation's to do, and a threshold that moves a user-facing
            # verdict is a calibration decision, not a rendering one.
            glossary_tip_fn=glossary_tip,
        ),
        _stat_card(
            "Deep nesting",
            deep,
            detail=_micro_badges(("threshold", "> 4")),
            value_tone="warn" if deep > 0 else "good",
            glossary_tip_fn=glossary_tip,
        ),
    ]
    return f'<div class="stat-cards">{"".join(cards)}</div>'


def _coupling_cards(summary: Mapping[str, object]) -> str:
    high_risk, total, max_cbo, avg_cbo = _summary_card_inputs(summary, max_key="max")
    cards = [
        _stat_card(
            "High-coupling classes",
            high_risk,
            detail=_micro_badges(("total", total)),
            value_tone="bad" if high_risk > 0 else "good",
            glossary_tip_fn=glossary_tip,
        ),
        _stat_card(
            "Max CBO",
            max_cbo,
            detail=_micro_badges(("target", "< 8")),
            value_tone="bad" if max_cbo > 12 else "warn" if max_cbo > 8 else "good",
            glossary_tip_fn=glossary_tip,
        ),
        _stat_card(
            "Avg CBO",
            f"{avg_cbo:.1f}",
            detail=_micro_badges(("classes", total)),
            # Neutral for the same reason as Avg CC above: no band for an
            # average is published, so this card states the measured figure
            # and leaves the verdict to the values the document does band.
            glossary_tip_fn=glossary_tip,
        ),
        # No fourth card. This band used to draw a "Medium risk" count read
        # from ``summary["medium_risk"]`` -- a key no metric family emits, in
        # this document or any other. ``_as_int`` turned the absence into 0,
        # so the card had reported zero medium-risk classes in every report
        # ever built, on every repository, and a reader could not tell that
        # from a measurement. The product bands a row's ``risk`` and publishes
        # the high-risk population; the medium tail is not published, so it is
        # not drawn. Adding the field to the document to make the read valid
        # would be a schema change, and inventing the count here from the rows
        # would be a second classifier beside the one the document owns.
    ]
    return f'<div class="stat-cards">{"".join(cards)}</div>'


def _cohesion_cards(summary: Mapping[str, object]) -> str:
    """The figures the cohesion summary publishes, and nothing else.

    This band used to end in "High risk" and "Medium risk", read from
    ``high_risk`` and ``medium_risk``. Cohesion publishes neither: its summary
    carries ``{total, average, max, low_cohesion}``, so both cards drew
    ``_as_int(None)`` and half of this tab's figures were a zero nobody had
    measured, in every report ever built.

    Neither card comes back under another name, and the difference between
    them is worth stating. ``low_cohesion`` *is* this family's high-risk
    population -- the registry fills it from the ``risk_cohesion`` band, the
    same band that fills ``high_risk`` for complexity and coupling -- so the
    first card above already showed exactly what "High risk" was asking for,
    and restoring it would print one number twice under two labels. The medium
    tail is not published at all; drawing it would need either a new field in
    the document or a second classifier here over the rows, and the document
    owns that classification.
    """

    low_cohesion = _as_int(summary.get("low_cohesion"))
    total = _as_int(summary.get("total"))
    max_lcom4 = _as_int(summary.get("max"))
    cards = [
        _stat_card(
            "Low-cohesion classes",
            low_cohesion,
            detail=_micro_badges(("total", total)),
            value_tone="bad" if low_cohesion > 0 else "good",
            glossary_tip_fn=glossary_tip,
        ),
        _stat_card(
            "Max LCOM4",
            max_lcom4,
            detail=_micro_badges(("target", "= 1")),
            value_tone="bad" if max_lcom4 > 3 else "warn" if max_lcom4 > 1 else "good",
            glossary_tip_fn=glossary_tip,
        ),
    ]
    return f'<div class="stat-cards">{"".join(cards)}</div>'


def render_quality_panel(ctx: ReportContext) -> str:
    """Build the unified Quality tab (Complexity + Coupling + Cohesion sub-tabs)."""
    coupling_summary = _as_mapping(ctx.coupling_map.get("summary"))
    cohesion_summary = _as_mapping(ctx.cohesion_map.get("summary"))
    complexity_summary = _as_mapping(ctx.complexity_map.get("summary"))
    coverage_join_summary = coverage_join_quality_summary(ctx)
    coupling_high_risk = _as_int(coupling_summary.get("high_risk"))
    cohesion_low = _as_int(cohesion_summary.get("low_cohesion"))
    complexity_high_risk = _as_int(complexity_summary.get("high_risk"))
    coverage_review_items = coverage_join_quality_count(ctx)
    security_surface_items = security_surfaces_quality_count(ctx)
    coverage_hotspots = _as_int(coverage_join_summary.get("coverage_hotspots"))
    coverage_scope_gaps = _as_int(coverage_join_summary.get("scope_gap_hotspots"))
    coverage_join_status = str(coverage_join_summary.get("status", "")).strip()
    cc_max = _as_int(complexity_summary.get("max"))

    # Insight
    answer: str
    tone: Tone
    if not ctx.metrics_available:
        answer = "Metrics are skipped for this run."
        tone = "info"
    else:
        answer = (
            f"High-complexity: {complexity_high_risk}; "
            f"high-coupling: {coupling_high_risk}; "
            f"low-cohesion: {cohesion_low}; "
            f"security surfaces: {security_surface_items}; "
            f"max CC {cc_max}; "
            f"max CBO {coupling_summary.get('max', 'n/a')}; "
            f"max LCOM4 {cohesion_summary.get('max', 'n/a')}."
        )
        if coverage_join_summary:
            if coverage_join_status == "ok":
                answer += (
                    f" Coverage hotspots: {coverage_hotspots}; "
                    f"scope gaps: {coverage_scope_gaps}."
                )
            else:
                # The absence sentence is borrowed from the vocabulary owner,
                # never respelled: one fact, one wording, on every surface.
                answer += f" {COVERAGE_JOIN_UNAVAILABLE}"
        if coupling_high_risk > 0 and cohesion_low > 0:
            tone = "risk"
        elif (
            coupling_high_risk > 0
            or cohesion_low > 0
            or complexity_high_risk > 0
            or coverage_review_items > 0
        ):
            tone = "warn"
        else:
            tone = "ok"

    # Complexity sub-tab
    cx_rows_data = _as_sequence(ctx.complexity_map.get("functions"))
    cx_shown = [_as_mapping(r) for r in cx_rows_data[:_QUALITY_TABLE_ROW_LIMIT]]
    cx_rows = [
        (
            str(r.get("qualname", "")),
            str(r.get("relative_path", "")),
            str(r.get("cyclomatic_complexity", "")),
            str(r.get("nesting_depth", "")),
            str(r.get("risk", "")),
        )
        for r in cx_shown
    ]
    cx_panel = _complexity_cards(complexity_summary, cx_rows_data) + render_rows_table(
        headers=("Function", "File", "CC", "Nesting", "Risk"),
        rows=cx_rows,
        empty_message="Complexity metrics are not available.",
        empty_description=(
            "Cyclomatic complexity is measured when metrics run, so this stays "
            "empty for a clones-only analysis or a tree with no callables."
        ),
        column_types={"CC": "meter", "Nesting": "meter"},
        row_cut_note=row_cut_note_html(
            total=len(cx_rows_data),
            shown=len(cx_shown),
            ordering=ORDER_WORST_FIRST,
            covered=_quality_high_risk_coverage(cx_rows_data, cx_shown),
        ),
        ctx=ctx,
    )

    # Coupling sub-tab
    cp_rows_data = _as_sequence(ctx.coupling_map.get("classes"))
    cp_shown = [_as_mapping(r) for r in cp_rows_data[:_QUALITY_TABLE_ROW_LIMIT]]
    cp_rows = [
        (
            str(r.get("qualname", "")),
            str(r.get("relative_path", "")),
            str(r.get("cbo", "")),
            str(r.get("risk", "")),
            _render_coupled_cell(r),
        )
        for r in cp_shown
    ]
    cp_panel = _coupling_cards(coupling_summary) + render_rows_table(
        headers=("Class", "File", "CBO", "Risk", "Coupled classes"),
        rows=cp_rows,
        empty_message="Coupling metrics are not available.",
        empty_description=(
            "Coupling between objects is measured when metrics run, so this "
            "stays empty for a clones-only analysis or a tree with no classes."
        ),
        raw_html_headers=("Coupled classes",),
        column_types={"CBO": "meter"},
        row_cut_note=row_cut_note_html(
            total=len(cp_rows_data),
            shown=len(cp_shown),
            ordering=ORDER_WORST_FIRST,
            covered=_quality_high_risk_coverage(cp_rows_data, cp_shown),
        ),
        ctx=ctx,
    )

    # Cohesion sub-tab
    ch_rows_data = _as_sequence(ctx.cohesion_map.get("classes"))
    ch_shown = [_as_mapping(r) for r in ch_rows_data[:_QUALITY_TABLE_ROW_LIMIT]]
    ch_rows = [
        (
            str(r.get("qualname", "")),
            str(r.get("relative_path", "")),
            str(r.get("lcom4", "")),
            str(r.get("risk", "")),
            str(r.get("method_count", "")),
            str(r.get("instance_var_count", "")),
        )
        for r in ch_shown
    ]
    ch_panel = _cohesion_cards(cohesion_summary) + render_rows_table(
        headers=("Class", "File", "LCOM4", "Risk", "Methods", "Fields"),
        rows=ch_rows,
        empty_message="Cohesion metrics are not available.",
        empty_description=(
            "LCOM4 is measured when metrics run, so this stays empty for a "
            "clones-only analysis or a tree with no classes."
        ),
        column_types={"LCOM4": "meter", "Methods": "meter", "Fields": "meter"},
        # The tab badge counts low-cohesion classes, a population the document
        # publishes only as a summary figure; the coverage half of the band
        # therefore answers for ``risk``, which every row carries, rather than
        # re-deriving the badge's own rule here from LCOM4.
        row_cut_note=row_cut_note_html(
            total=len(ch_rows_data),
            shown=len(ch_shown),
            ordering=ORDER_WORST_FIRST,
            covered=_quality_high_risk_coverage(ch_rows_data, ch_shown),
        ),
        ctx=ctx,
    )

    sub_tabs: list[tuple[str, str, int, str]] = [
        ("complexity", "Complexity", complexity_high_risk, cx_panel),
        ("coupling", "Coupling (CBO)", coupling_high_risk, cp_panel),
        ("cohesion", "Cohesion (LCOM4)", cohesion_low, ch_panel),
    ]
    coverage_join_panel = render_coverage_join_panel(ctx)
    if coverage_join_panel:
        sub_tabs.append(
            (
                "coverage-join",
                "Coverage Join",
                coverage_review_items,
                coverage_join_panel,
            )
        )
    security_surfaces_panel = render_security_surfaces_panel(ctx)
    if security_surfaces_panel:
        sub_tabs.append(
            (
                "security-surfaces",
                "Security Surfaces",
                security_surface_items,
                security_surfaces_panel,
            )
        )

    return insight_block(
        question="Are there quality hotspots in the codebase?",
        answer=answer,
        tone=tone,
    ) + render_split_tabs(group_id="quality", tabs=sub_tabs)
