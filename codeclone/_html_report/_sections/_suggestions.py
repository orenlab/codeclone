# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

"""Suggestions panel renderer."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from ... import _coerce
from ..._html_badges import _tab_empty
from ..._html_data_attrs import _build_data_attrs
from ..._html_escape import _escape_attr, _escape_html
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
from .._components import insight_block

if TYPE_CHECKING:
    from ...models import Suggestion
    from .._context import ReportContext

_as_int = _coerce.as_int


def _render_fact_summary(raw: str) -> str:
    """Render fact_summary as a styled inline chip."""
    if not raw:
        return ""
    # Humanize key=value pairs: "cyclomatic_complexity=15" → "cyclomatic complexity: 15"
    segments = [s.strip() for s in raw.split(",")]
    parts: list[str] = []
    for seg in segments:
        if "=" in seg:
            key, _, val = seg.partition("=")
            parts.append(f"{key.strip().replace('_', ' ')}: {val.strip()}")
        else:
            parts.append(seg)
    text = ", ".join(parts)
    return f'<div class="suggestion-summary">{_escape_html(text)}</div>'


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


def _render_card(s: Suggestion, ctx: ReportContext) -> str:
    actionable = "true" if s.severity != "info" else "false"
    spread_bucket = "high" if s.spread_files > 1 or s.spread_functions > 1 else "low"
    breakdown_text = _format_source_breakdown(s.source_breakdown)
    facts_source = _escape_html(breakdown_text or source_kind_label(s.source_kind))
    facts_location = _escape_html(s.location_label or s.location)

    # Context chips — more visible than a single muted line
    ctx_chips: list[str] = []
    sk = source_kind_label(s.source_kind)
    if sk:
        ctx_chips.append(f'<span class="suggestion-chip">{_escape_html(sk)}</span>')
    cat = s.category.replace("_", " ")
    if cat:
        ctx_chips.append(f'<span class="suggestion-chip">{_escape_html(cat)}</span>')
    if s.clone_type:
        ctx_chips.append(
            f'<span class="suggestion-chip">{_escape_html(s.clone_type)}</span>'
        )
    ctx_html = f'<div class="suggestion-context">{"".join(ctx_chips)}</div>'

    # Next step — primary actionable CTA
    next_step = _escape_html(s.steps[0]) if s.steps else ""
    next_step_html = (
        '<div class="suggestion-action">'
        '<svg class="suggestion-action-icon" viewBox="0 0 16 16" width="12" height="12">'
        '<path d="M1 8h12M9 4l4 4-4 4" fill="none" stroke="currentColor" '
        'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>'
        f"{next_step}</div>"
        if next_step
        else ""
    )

    # Effort badge — color-coded
    effort_cls = f" suggestion-effort--{_escape_html(s.effort)}"

    # Priority — clean display (drop trailing zeros)
    priority_str = f"{s.priority:g}"

    # Locations inside details
    locs_html = ""
    if s.representative_locations:
        locs_items = "".join(
            '<li><span class="suggestion-loc-path">'
            f'<a class="ide-link" data-file="{_escape_attr(loc.filepath)}" data-line="{loc.start_line}">'
            f"{_escape_html(loc.relative_path)}"
            f'<span class="suggestion-loc-lines">:{loc.start_line}\u2013{loc.end_line}</span>'
            "</a></span>"
            f'<span class="suggestion-loc-name">{_escape_html(ctx.bare_qualname(loc.qualname, loc.filepath))}</span>'
            "</li>"
            for loc in s.representative_locations
        )
        locs_html = (
            f'<div class="suggestion-sub-title">Locations ({len(s.representative_locations)})</div>'
            f'<ul class="suggestion-locations">{locs_items}</ul>'
        )

    # Steps inside details
    steps_html = ""
    if s.steps:
        steps_items = "".join(f"<li>{_escape_html(step)}</li>" for step in s.steps)
        steps_html = (
            '<div class="suggestion-sub-title">Refactoring steps</div>'
            f'<ol class="suggestion-steps">{steps_items}</ol>'
        )

    # Severity dd — colored to match header badge
    sev_dd = (
        f'<span class="suggestion-sev-inline suggestion-sev--{_escape_html(s.severity)}">'
        f"{_escape_html(s.severity)}</span>"
    )

    return (
        f'<article class="suggestion-card"'
        f"{_build_data_attrs({'data-suggestion-card': 'true', 'data-severity': s.severity, 'data-category': s.category, 'data-family': s.finding_family, 'data-source-kind': s.source_kind, 'data-clone-type': s.clone_type, 'data-actionable': actionable, 'data-spread-bucket': spread_bucket, 'data-count': str(s.fact_count)})}"
        ">"
        # -- header row --
        '<div class="suggestion-head">'
        f'<span class="suggestion-sev suggestion-sev--{_escape_html(s.severity)}">{_escape_html(s.severity)}</span>'
        f'<span class="suggestion-title">{_escape_html(s.title)}</span>'
        '<span class="suggestion-meta">'
        f'<span class="suggestion-meta-badge{effort_cls}">{_escape_html(s.effort)}</span>'
        f'<span class="suggestion-meta-badge">P{priority_str}</span>'
        f'<span class="suggestion-meta-badge">{s.spread_functions} fn / {s.spread_files} files</span>'
        "</span></div>"
        # -- body --
        '<div class="suggestion-body">'
        f"{ctx_html}"
        f"{_render_fact_summary(s.fact_summary)}"
        f"{next_step_html}"
        "</div>"
        # -- expandable details --
        '<details class="suggestion-details">'
        "<summary>Details</summary>"
        '<div class="suggestion-details-body">'
        '<div class="suggestion-facts">'
        '<div class="suggestion-fact-group">'
        '<div class="suggestion-fact-group-title">Facts</div>'
        '<dl class="suggestion-dl">'
        f"<div><dt>Finding</dt><dd>{_escape_html(s.fact_kind or s.category)}</dd></div>"
        f"<div><dt>Spread</dt><dd>{s.spread_functions} fn / {s.spread_files} files</dd></div>"
        f"<div><dt>Source</dt><dd>{facts_source}</dd></div>"
        f"<div><dt>Scope</dt><dd>{facts_location}</dd></div>"
        "</dl></div>"
        '<div class="suggestion-fact-group">'
        '<div class="suggestion-fact-group-title">Assessment</div>'
        '<dl class="suggestion-dl">'
        f"<div><dt>Severity</dt><dd>{sev_dd}</dd></div>"
        f"<div><dt>Confidence</dt><dd>{_escape_html(s.confidence)}</dd></div>"
        f"<div><dt>Priority</dt><dd>{priority_str}</dd></div>"
        f"<div><dt>Family</dt><dd>{_escape_html(s.finding_family)}</dd></div>"
        "</dl></div>"
        "</div>"
        f"{locs_html}"
        f"{steps_html}"
        "</div></details>"
        "</article>"
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
        f'<div class="suggestions-list" data-suggestions-body>{cards_html}</div>'
    )
