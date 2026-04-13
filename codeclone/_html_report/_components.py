# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Shared UI components: insight banners, summary helpers, chip rows."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from .._coerce import as_int as _as_int
from .._html_badges import _source_kind_badge_html
from .._html_escape import _escape_html
from ._icons import section_icon_html

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
        f'<div class="insight-banner insight-{_escape_html(tone)}">'
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


_SUMMARY_ICON_KEYS: dict[str, tuple[str, str]] = {
    "top risks": ("top-risks", "summary-icon summary-icon--risk"),
    "issue breakdown": ("issue-breakdown", "summary-icon summary-icon--info"),
    "source breakdown": ("source-breakdown", "summary-icon summary-icon--info"),
    "all findings": ("all-findings", "summary-icon summary-icon--info"),
    "clone groups": ("clone-groups", "summary-icon summary-icon--info"),
    "low cohesion": ("low-cohesion", "summary-icon summary-icon--info"),
    "top candidates": ("quality", "summary-icon summary-icon--info"),
    "more candidates": ("quality", "summary-icon summary-icon--info"),
    "health profile": ("health-profile", "summary-icon summary-icon--info"),
    "adoption coverage": ("coverage-adoption", "summary-icon summary-icon--info"),
    "public api surface": ("api-surface", "summary-icon summary-icon--info"),
    "coverage join": ("quality", "summary-icon summary-icon--info"),
}


def overview_summary_item_html(*, label: str, body_html: str) -> str:
    icon_key, icon_class = _SUMMARY_ICON_KEYS.get(label.lower(), ("", ""))
    icon = (
        section_icon_html(icon_key, class_name=icon_class)
        if icon_key and icon_class
        else ""
    )
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
