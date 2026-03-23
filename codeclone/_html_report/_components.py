# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

"""Shared UI components: insight banners, summary helpers, chip rows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

from .. import _coerce
from .._html_badges import _quality_badge_html, _source_kind_badge_html
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


def overview_summary_list_html(items: Sequence[str]) -> str:
    cleaned = [str(i).strip() for i in items if str(i).strip()]
    if not cleaned:
        return '<div class="overview-summary-value">none</div>'
    return (
        '<ul class="overview-summary-list">'
        + "".join(f"<li>{_escape_html(i)}</li>" for i in cleaned)
        + "</ul>"
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

_SUMMARY_ICONS: dict[str, str] = {
    "top risks": _ICON_ALERT,
    "source breakdown": _ICON_PIE,
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


def overview_row_html(card: Mapping[str, object]) -> str:
    severity = str(card.get("severity", "info"))
    source_kind = str(card.get("source_kind", "other"))
    title = str(card.get("title", ""))
    summary_text = str(card.get("summary", ""))
    spread = _as_mapping(card.get("spread"))
    spread_files = _as_int(spread.get("files"))
    spread_functions = _as_int(spread.get("functions"))
    clone_type = str(card.get("clone_type", "")).strip()
    count = _as_int(card.get("count"))

    # Badge row: severity + source kind + clone type + spread
    badges: list[str] = [
        _quality_badge_html(severity),
        _source_kind_badge_html(source_kind),
    ]
    if clone_type:
        badges.append(
            f'<span class="clone-type-badge">{_escape_html(clone_type)}</span>'
        )

    spread_html = ""
    if spread_files or spread_functions:
        parts: list[str] = []
        if count:
            parts.append(f"{count} occurrences")
        parts.append(f"{spread_functions} fn / {spread_files} files")
        spread_html = (
            '<span class="overview-row-spread">'
            f"{_escape_html(' · '.join(parts))}</span>"
        )

    return (
        '<article class="overview-row" '
        f'data-severity="{_escape_attr(severity)}" '
        f'data-source-kind="{_escape_attr(source_kind)}">'
        '<div class="overview-row-head">' + "".join(badges) + spread_html + "</div>"
        f'<div class="overview-row-title">{_escape_html(title)}</div>'
        f'<div class="overview-row-summary">{_escape_html(summary_text)}</div>'
        "</article>"
    )


def overview_section_html(
    *,
    title: str,
    subtitle: str,
    cards: Sequence[object],
    empty_message: str,
) -> str:
    typed_cards = [_as_mapping(c) for c in cards if _as_mapping(c)]
    if not typed_cards:
        return (
            '<section class="overview-cluster">'
            f"{overview_cluster_header(title, subtitle)}"
            '<div class="overview-cluster-empty">'
            f"{_EMPTY_ICON}"
            f"<div>{_escape_html(empty_message)}</div></div></section>"
        )
    return (
        '<section class="overview-cluster">'
        f"{overview_cluster_header(title, subtitle)}"
        '<div class="overview-list">'
        + "".join(overview_row_html(c) for c in typed_cards)
        + "</div></section>"
    )
