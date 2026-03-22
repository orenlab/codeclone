# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

"""Suggestions panel renderer."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from ... import _coerce
from ..._html_badges import _tab_empty
from ..._html_data_attrs import _build_data_attrs
from ..._html_escape import _escape_html
from ..._html_filters import SPREAD_OPTIONS, _render_select
from ...domain.findings import (
    CATEGORY_CLONE,
    CATEGORY_COHESION,
    CATEGORY_COMPLEXITY,
    CATEGORY_COUPLING,
    CATEGORY_DEAD_CODE,
    CATEGORY_DEPENDENCY,
    CATEGORY_STRUCTURAL,
    FAMILY_CLONES,
    FAMILY_METRICS,
    FAMILY_STRUCTURAL,
)
from ...domain.quality import SEVERITY_CRITICAL, SEVERITY_INFO, SEVERITY_WARNING
from ...report._source_kinds import SOURCE_KIND_FILTER_VALUES, source_kind_label
from .._components import insight_block, summary_chip_row

if TYPE_CHECKING:
    from ...models import Suggestion
    from .._context import ReportContext

_as_int = _coerce.as_int


def _format_source_breakdown(
    source_breakdown: Mapping[str, object] | Sequence[object],
) -> str:
    rows: list[tuple[str, int]] = []
    if isinstance(source_breakdown, Mapping):
        rows = [
            (str(k), _as_int(v)) for k, v in source_breakdown.items() if _as_int(v) > 0
        ]
    else:
        rows = [
            (str(pair[0]), _as_int(pair[1]))
            for pair in source_breakdown
            if isinstance(pair, Sequence) and len(pair) == 2 and _as_int(pair[1]) > 0
        ]
    rows.sort(key=lambda item: (item[0], item[1]))
    return " \u00b7 ".join(f"{source_kind_label(k)} {c}" for k, c in rows if c > 0)


def _suggestion_locations_html(suggestion: Suggestion, ctx: ReportContext) -> str:
    if not suggestion.representative_locations:
        return '<div class="suggestion-empty">No representative locations.</div>'
    count = len(suggestion.representative_locations)
    items_html = "".join(
        "<li>"
        f'<span class="suggestion-location-path">'
        f"{_escape_html(loc.relative_path)}:{loc.start_line}-{loc.end_line}</span>"
        f'<span class="suggestion-location-qualname">'
        f"{_escape_html(ctx.bare_qualname(loc.qualname, loc.filepath))}</span>"
        "</li>"
        for loc in suggestion.representative_locations
    )
    return (
        '<details class="suggestion-disclosure suggestion-location-details">'
        "<summary><span>Example locations</span>"
        f'<span class="suggestion-disclosure-count">{count}</span></summary>'
        f'<ul class="suggestion-location-list">{items_html}</ul>'
        "</details>"
    )


def _render_card(s: Suggestion, ctx: ReportContext) -> str:
    actionable = "true" if s.severity != "info" else "false"
    spread_bucket = "high" if s.spread_files > 1 or s.spread_functions > 1 else "low"
    breakdown_text = _format_source_breakdown(s.source_breakdown)
    facts_title = _escape_html(s.fact_kind or s.category)
    facts_summary = _escape_html(s.fact_summary)
    facts_spread = f"{s.spread_functions} functions / {s.spread_files} files"
    facts_source = _escape_html(breakdown_text or source_kind_label(s.source_kind))
    facts_location = _escape_html(s.location_label or s.location)
    ctx_parts = [
        s.severity,
        source_kind_label(s.source_kind),
        s.category.replace("_", " "),
    ]
    if s.clone_type:
        ctx_parts.append(s.clone_type)
    ctx_text = " \u00b7 ".join(p for p in ctx_parts if p)
    stats = summary_chip_row(
        (
            f"count={s.fact_count}",
            f"spread={s.spread_functions} fn / {s.spread_files} files",
            f"confidence={s.confidence}",
            f"priority={s.priority:.2f}",
            f"effort={s.effort}",
        ),
        css_class="suggestion-card-stats",
    )
    next_step = (
        _escape_html(s.steps[0])
        if s.steps
        else "No explicit refactoring steps provided."
    )
    steps_html = "".join(f"<li>{_escape_html(step)}</li>" for step in s.steps)
    steps_disclosure = (
        '<details class="suggestion-disclosure">'
        "<summary><span>Refactoring steps</span>"
        f'<span class="suggestion-disclosure-count">{len(s.steps)}</span></summary>'
        f'<ol class="suggestion-steps">{steps_html}</ol>'
        "</details>"
        if s.steps
        else ""
    )
    return (
        f'<article class="suggestion-card"'
        f"{_build_data_attrs({'data-suggestion-card': 'true', 'data-severity': s.severity, 'data-category': s.category, 'data-family': s.finding_family, 'data-source-kind': s.source_kind, 'data-clone-type': s.clone_type, 'data-actionable': actionable, 'data-spread-bucket': spread_bucket, 'data-count': str(s.fact_count)})}"
        ">"
        '<div class="suggestion-card-head">'
        f'<div class="suggestion-card-title">{_escape_html(s.title)}</div>'
        f'<div class="suggestion-card-context">{_escape_html(ctx_text)}</div>'
        "</div>"
        f'<div class="suggestion-card-summary">{facts_summary}</div>'
        f"{stats}"
        '<div class="suggestion-sections">'
        '<section class="suggestion-section">'
        '<div class="suggestion-section-title">Facts</div>'
        '<dl class="suggestion-fact-list">'
        f"<div><dt>Finding</dt><dd>{facts_title}</dd></div>"
        f"<div><dt>Spread</dt><dd>{_escape_html(facts_spread)}</dd></div>"
        f"<div><dt>Source breakdown</dt><dd>{facts_source}</dd></div>"
        f"<div><dt>Representative scope</dt><dd>{facts_location}</dd></div>"
        "</dl></section>"
        '<section class="suggestion-section">'
        '<div class="suggestion-section-title">Assessment</div>'
        '<dl class="suggestion-fact-list">'
        f"<div><dt>Severity</dt><dd>{_escape_html(s.severity)}</dd></div>"
        f"<div><dt>Confidence</dt><dd>{_escape_html(s.confidence)}</dd></div>"
        f"<div><dt>Priority</dt><dd>{_escape_html(f'{s.priority:.2f}')}</dd></div>"
        f"<div><dt>Family</dt><dd>{_escape_html(s.finding_family)}</dd></div>"
        "</dl></section>"
        '<section class="suggestion-section">'
        '<div class="suggestion-section-title">Suggested action</div>'
        '<dl class="suggestion-fact-list">'
        f"<div><dt>Effort</dt><dd>{_escape_html(s.effort)}</dd></div>"
        f"<div><dt>Next step</dt><dd>{next_step}</dd></div>"
        "</dl></section></div>"
        '<div class="suggestion-disclosures">'
        f"{_suggestion_locations_html(s, ctx)}"
        f"{steps_disclosure}"
        "</div></article>"
    )


def render_suggestions_panel(ctx: ReportContext) -> str:
    rows = list(ctx.suggestions)
    if not rows:
        return insight_block(
            question="What should be prioritized next?",
            answer="No suggestions were generated for this run.",
            tone="ok",
        ) + _tab_empty("No suggestions generated.")

    critical = sum(1 for s in rows if s.severity == "critical")
    warning = sum(1 for s in rows if s.severity == "warning")
    info = sum(1 for s in rows if s.severity == "info")
    intro = insight_block(
        question="What should be prioritized next?",
        answer=f"{len(rows)} suggestions: {critical} critical, {warning} warning, {info} info.",
        tone="risk" if critical > 0 else "warn",
    )

    cards_html = "".join(_render_card(s, ctx) for s in rows)
    sev_opts = tuple(
        (s, s) for s in (SEVERITY_CRITICAL, SEVERITY_WARNING, SEVERITY_INFO)
    )
    cat_opts = tuple(
        (c, c)
        for c in (
            CATEGORY_CLONE,
            CATEGORY_COMPLEXITY,
            CATEGORY_COUPLING,
            CATEGORY_COHESION,
            CATEGORY_DEAD_CODE,
            CATEGORY_DEPENDENCY,
            CATEGORY_STRUCTURAL,
        )
    )
    fam_opts = tuple((f, f) for f in (FAMILY_CLONES, FAMILY_STRUCTURAL, FAMILY_METRICS))
    sk_opts = tuple((k, k) for k in SOURCE_KIND_FILTER_VALUES)

    return (
        intro
        + '<div class="toolbar suggestions-toolbar" role="toolbar" aria-label="Suggestion filters">'
        '<div class="suggestions-toolbar-row">'
        '<label class="muted" for="suggestions-severity">Severity:</label>'
        + _render_select(
            element_id="suggestions-severity",
            data_attr="data-suggestions-severity",
            options=sev_opts,
            all_label="All",
        )
        + '<label class="muted" for="suggestions-category">Category:</label>'
        + _render_select(
            element_id="suggestions-category",
            data_attr="data-suggestions-category",
            options=cat_opts,
            all_label="All",
        )
        + '<label class="muted" for="suggestions-family">Family:</label>'
        + _render_select(
            element_id="suggestions-family",
            data_attr="data-suggestions-family",
            options=fam_opts,
            all_label="All",
        )
        + '<label class="inline-check"><input type="checkbox" data-suggestions-actionable/><span>Only actionable</span></label>'
        "</div>"
        '<div class="suggestions-toolbar-row suggestions-toolbar-row--secondary">'
        '<label class="muted" for="suggestions-source-kind">Context:</label>'
        + _render_select(
            element_id="suggestions-source-kind",
            data_attr="data-suggestions-source-kind",
            options=sk_opts,
            all_label="All",
        )
        + '<label class="muted" for="suggestions-spread">Spread:</label>'
        + _render_select(
            element_id="suggestions-spread",
            data_attr="data-suggestions-spread",
            options=SPREAD_OPTIONS,
            all_label="All",
        )
        + f'<span class="suggestions-count-label" data-suggestions-count>{len(rows)} shown</span>'
        "</div></div>"
        f'<div class="suggestions-grid" data-suggestions-body>{cards_html}</div>'
    )
