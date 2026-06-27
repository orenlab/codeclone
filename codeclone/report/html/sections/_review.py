# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Review hub panel — the prioritized, cross-family finding-review queue.

Render-only: reads the precomputed ``derived.review_queue`` and draws each
actionable item with the shared :func:`finding_card`. A per-item reviewed toggle
and the progress bar are wired client-side (localStorage keyed by finding id);
no projection logic lives here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from codeclone.utils import coerce as _coerce

from ..primitives.escape import _escape_html
from ..primitives.filters import _render_filter_chips
from ..widgets.badges import _tab_empty
from ..widgets.cards import finding_card, meta_badge_html
from ..widgets.components import Tone, insight_block

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .._context import ReportContext

_as_int = _coerce.as_int
_as_float = _coerce.as_float
_as_mapping = _coerce.as_mapping
_as_sequence = _coerce.as_sequence

_EMPTY_MESSAGE = "No findings to review."
_METRICS_SKIPPED = "Metrics are skipped for this run."
_REVIEW_INSIGHT = (
    "Findings to review, highest priority first. Mark items reviewed as you go — "
    "progress is saved in your browser. Report-only triage: verify in source "
    "before editing."
)
_FAMILY_LABELS = {
    "clones": "Clones",
    "structural": "Structural",
    "dead_code": "Dead code",
    "design": "Quality",
    "metrics": "Quality",
}
_SEVERITIES = ("critical", "warning", "info")

_REVIEW_TOGGLE = (
    '<button type="button" class="review-toggle" data-review-toggle '
    'aria-pressed="false" aria-label="Mark reviewed" title="Mark reviewed">'
    '<svg viewBox="0 0 16 16" width="13" height="13" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round"><polyline points="3.5 8.5 6.5 11.5 12.5 5"/>'
    "</svg></button>"
)


def _family_label(family: str) -> str:
    return _FAMILY_LABELS.get(family, family or "other")


def _render_review_item(item: Mapping[str, object]) -> str:
    finding_id = str(item.get("finding_id"))
    family = str(item.get("family"))
    severity = str(item.get("severity"))
    effort = str(item.get("effort"))
    novelty = str(item.get("novelty"))
    meta_badges = [meta_badge_html(f"priority {_as_float(item.get('priority')):.2f}")]
    if effort:
        meta_badges.append(meta_badge_html(effort, tone=effort))
    meta_badges.append(meta_badge_html(_family_label(family)))
    if novelty == "new":
        meta_badges.append(meta_badge_html("new", tone="new"))
    data_attrs = (
        ' data-review-card="true" '
        f'data-finding-id="{_escape_html(finding_id)}" '
        f'data-severity="{_escape_html(severity)}" '
        f'data-family="{_escape_html(family)}" '
        f'data-novelty="{_escape_html(novelty)}"'
    )
    return finding_card(
        severity=severity,
        title=str(item.get("title")),
        eyebrow=f"{_family_label(family)} · {item.get('source_kind')}",
        location=str(item.get("location")),
        meta_badges=tuple(meta_badges),
        body_html=_escape_html(str(item.get("summary"))),
        actions_html=_REVIEW_TOGGLE,
        card_class="review-card",
        data_attrs=data_attrs,
    )


def _review_progress(total: int) -> str:
    return (
        '<div class="review-progress" data-review-progress>'
        '<div class="review-progress-head">'
        '<span class="review-progress-title">Progress</span>'
        '<span class="review-progress-label">'
        f"<b data-review-progress-label>0 / {total}</b> reviewed</span></div>"
        '<div class="review-progress-track">'
        '<div class="review-progress-bar" data-review-progress-bar '
        'style="width:0%"></div></div></div>'
    )


def _review_toolbar(summary: Mapping[str, object], total: int) -> str:
    """Inline density of the shared filter system: one-click chips + count."""
    by_severity = _as_mapping(summary.get("by_severity"))
    by_family = _as_mapping(summary.get("by_family"))
    sev_opts = tuple(
        (severity, severity.title(), _as_int(by_severity.get(severity)))
        for severity in _SEVERITIES
        if _as_int(by_severity.get(severity)) > 0
    )
    fam_opts = tuple(
        (family, _family_label(family), _as_int(count))
        for family, count in sorted(by_family.items())
    )
    return (
        '<div class="toolbar toolbar--filters" role="toolbar" '
        'aria-label="Review filters" data-review-filters>'
        '<div class="toolbar-left">'
        + _render_filter_chips(dim="severity", options=sev_opts)
        + _render_filter_chips(dim="family", options=fam_opts)
        + "</div>"
        '<div class="toolbar-right">'
        '<button type="button" class="btn filter-reset" data-filter-reset hidden>'
        "Clear</button>"
        f'<span class="toolbar-count-label" data-review-count>{total} shown</span>'
        "</div></div>"
    )


def render_review_panel(ctx: ReportContext) -> str:
    queue = _as_mapping(ctx.derived_map.get("review_queue"))
    summary = _as_mapping(queue.get("summary"))
    items = [_as_mapping(item) for item in _as_sequence(queue.get("items"))]

    answer = _REVIEW_INSIGHT if ctx.metrics_available else _METRICS_SKIPPED
    tone: Tone = "info"
    insight = insight_block(
        question="What needs review, and in what order?",
        answer=answer,
        tone=tone,
    )
    if not items:
        return insight + _tab_empty(_EMPTY_MESSAGE)

    cards = "".join(_render_review_item(item) for item in items)
    return (
        "<div data-review-panel>"
        + insight
        + _review_progress(len(items))
        + _review_toolbar(summary, len(items))
        + f'<div class="review-queue" data-review-body>{cards}</div></div>'
    )
