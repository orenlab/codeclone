# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

"""Shared UI components: insight banners, summary helpers, chip rows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

from .. import _coerce
from .._html_escape import _escape_attr, _escape_html
from ..report._source_kinds import source_kind_label

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


def overview_summary_item_html(*, label: str, body_html: str) -> str:
    return (
        '<article class="overview-summary-item">'
        f'<div class="overview-summary-label">{_escape_html(label)}</div>'
        f"{body_html}"
        "</article>"
    )


def overview_source_breakdown_html(breakdown: Mapping[str, object]) -> str:
    rows = tuple(
        f"{source_kind_label(str(kind))} {_as_int(count)}"
        for kind, count in sorted(
            breakdown.items(), key=lambda item: (str(item[0]), _as_int(item[1]))
        )
        if _as_int(count) > 0
    )
    if rows:
        return overview_summary_list_html(rows)
    return '<div class="overview-summary-value">n/a</div>'


def overview_row_html(card: Mapping[str, object]) -> str:
    severity = str(card.get("severity", "info"))
    source_kind = str(card.get("source_kind", "other"))
    category = str(card.get("category", ""))
    title = str(card.get("title", ""))
    summary_text = str(card.get("summary", ""))
    location_text = str(card.get("location", ""))
    spread = _as_mapping(card.get("spread"))
    spread_files = _as_int(spread.get("files"))
    spread_functions = _as_int(spread.get("functions"))
    clone_type = str(card.get("clone_type", "")).strip()

    # Compact context line: severity · source · category [· clone_type]
    ctx_parts = [
        severity,
        source_kind_label(source_kind),
        category.replace("_", " "),
    ]
    if clone_type:
        ctx_parts.append(clone_type)
    context_text = " \u00b7 ".join(p for p in ctx_parts if p)

    # Compact metadata: spread + location on one line
    meta_parts: list[str] = []
    if spread_files or spread_functions:
        meta_parts.append(f"{spread_functions} fn / {spread_files} files")
    if location_text:
        meta_parts.append(location_text)
    meta_text = " \u00b7 ".join(meta_parts)

    return (
        '<article class="overview-row" '
        f'data-severity="{_escape_attr(severity)}" '
        f'data-source-kind="{_escape_attr(source_kind)}">'
        '<div class="overview-row-main">'
        f'<div class="overview-row-title">{_escape_html(title)}</div>'
        f'<div class="overview-row-summary">{_escape_html(summary_text)}</div>'
        "</div>"
        '<div class="overview-row-side">'
        f'<div class="overview-row-context">{_escape_html(context_text)}</div>'
        f'<div class="overview-row-meta">{_escape_html(meta_text)}</div>'
        "</div>"
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
