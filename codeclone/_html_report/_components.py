# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

"""Shared UI components: insight banners, summary helpers, chip rows."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from .. import _coerce
from .._html_badges import _source_kind_badge_html
from .._html_escape import _escape_attr, _escape_html

_as_int = _coerce.as_int
_as_mapping = _coerce.as_mapping

Tone = Literal["ok", "warn", "risk", "info"]

_EMPTY_ICON = (
    '<svg class="empty-icon" width="40" height="40" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="1.5" stroke-linecap="round" '
    'stroke-linejoin="round">'
    '<circle cx="12" cy="12" r="10" opacity=".4"/>'
    '<path d="M8 12l3 3 5-6"/></svg>'
)


def insight_block(*, question: str, answer: str, tone: Tone = "info") -> str:
    return (
        f'<div class="insight-banner insight-{_escape_attr(tone)}">'
        f'<div class="insight-question">{_escape_html(question)}</div>'
        f'<div class="insight-answer">{_escape_html(answer)}</div>'
        "</div>"
    )


def overview_cluster_header(title: str, subtitle: str | None = None) -> str:
    sub = (
        f'<p class="overview-cluster-copy">{_escape_html(subtitle)}</p>'
        if subtitle
        else ""
    )
    return (
        '<div class="overview-cluster-header">'
        f'<h3 class="subsection-title">{_escape_html(title)}</h3>'
        f"{sub}"
        "</div>"
    )


_ICON_ALERT = (
    '<svg class="summary-icon summary-icon--risk" width="16" height="16" '
    'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86'
    'a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/>'
    '<line x1="12" y1="17" x2="12.01" y2="17"/></svg>'
)

_ICON_PIE = (
    '<svg class="summary-icon summary-icon--info" width="16" height="16" '
    'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M21.21 15.89A10 10 0 118 2.83"/>'
    '<path d="M22 12A10 10 0 0012 2v10z"/></svg>'
)

_ICON_RADAR = (
    '<svg class="summary-icon summary-icon--info" width="16" height="16" '
    'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round">'
    '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/>'
    '<circle cx="12" cy="12" r="2"/>'
    '<line x1="12" y1="2" x2="12" y2="6"/>'
    '<line x1="12" y1="18" x2="12" y2="22"/></svg>'
)

_ICON_BAR = (
    '<svg class="summary-icon summary-icon--info" width="16" height="16" '
    'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round">'
    '<rect x="3" y="3" width="18" height="4" rx="1"/>'
    '<rect x="3" y="10" width="13" height="4" rx="1"/>'
    '<rect x="3" y="17" width="8" height="4" rx="1"/></svg>'
)

_SUMMARY_ICONS: dict[str, str] = {
    "top risks": _ICON_ALERT,
    "source breakdown": _ICON_PIE,
    "health profile": _ICON_RADAR,
    "issue breakdown": _ICON_BAR,
}


def overview_summary_item_html(*, label: str, body_html: str) -> str:
    icon = _SUMMARY_ICONS.get(label.lower(), "")
    return (
        '<article class="overview-summary-item">'
        '<div class="overview-summary-label">'
        f"{icon}{_escape_html(label)}</div>"
        f"{body_html}"
        "</article>"
    )


def overview_source_breakdown_html(breakdown: Mapping[str, object]) -> str:
    sorted_items = sorted(
        ((str(k), _as_int(v)) for k, v in breakdown.items()),
        key=lambda item: -item[1],
    )
    rows = [(kind, count) for kind, count in sorted_items if count > 0]
    if not rows:
        return '<div class="overview-summary-value">n/a</div>'

    total = sum(c for _, c in rows)
    parts: list[str] = []
    for kind, count in rows:
        pct = round(count / total * 100) if total else 0
        parts.append(
            '<div class="breakdown-row">'
            f"{_source_kind_badge_html(kind)}"
            f'<span class="breakdown-count">{count}</span>'
            f'<span class="breakdown-bar-track">'
            f'<span class="breakdown-bar-fill" style="width:{pct}%"></span></span>'
            "</div>"
        )
    return '<div class="breakdown-list">' + "".join(parts) + "</div>"
