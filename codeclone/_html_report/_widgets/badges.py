# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Shared HTML badge, label, and visual helpers for the report UI layer.

Naming conventions:
  - ``{domain}-badge`` for inline taxonomy labels (risk-badge, severity-badge,
    source-kind-badge, clone-type-badge)
  - ``meta-item`` is the **single** card pattern for all stat/KPI/meta cards
  - ``meta-label`` + ``meta-value`` are the **single** label+value pair
  - ``suggestion-card`` for suggestion grid items
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from ._html_escape import _escape_html
from .domain.quality import (
    EFFORT_EASY,
    EFFORT_HARD,
    EFFORT_MODERATE,
    RISK_HIGH,
    RISK_LOW,
    RISK_MEDIUM,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_WARNING,
)
from .report._source_kinds import normalize_source_kind, source_kind_label

__all__ = [
    "CHECK_CIRCLE_SVG",
    "INFO_CIRCLE_SVG",
    "_inline_empty",
    "_micro_badges",
    "_quality_badge_html",
    "_render_chain_flow",
    "_short_label",
    "_source_kind_badge_html",
    "_stat_card",
    "_tab_empty",
    "_tab_empty_info",
]

_EFFORT_CSS: dict[str, str] = {
    EFFORT_EASY: "success",
    EFFORT_MODERATE: "warning",
    EFFORT_HARD: "error",
}

CHECK_CIRCLE_SVG = (
    '<svg class="tab-empty-icon" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="1.5" stroke-linecap="round" '
    'stroke-linejoin="round">'
    '<circle cx="12" cy="12" r="10"/>'
    '<polyline points="16 9 10.5 15 8 12.5"/>'
    "</svg>"
)

INFO_CIRCLE_SVG = (
    '<svg class="tab-empty-icon" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="1.5" stroke-linecap="round" '
    'stroke-linejoin="round">'
    '<circle cx="12" cy="12" r="10"/>'
    '<line x1="12" y1="16" x2="12" y2="12"/>'
    '<line x1="12" y1="8" x2="12.01" y2="8"/>'
    "</svg>"
)


def _micro_badges(*pairs: tuple[str, object]) -> str:
    """Render compact label:value micro-badge pairs for stat card details."""
    return "".join(
        f'<span class="kpi-micro">'
        f'<span class="kpi-micro-val">{_escape_html(str(value))}</span>'
        f'<span class="kpi-micro-lbl">{_escape_html(label)}</span></span>'
        for label, value in pairs
        if value is not None and str(value) != "n/a"
    )


def _quality_badge_html(text: str) -> str:
    """Render a risk / severity / effort value as a styled badge."""
    r = text.strip().lower()
    if r in (RISK_LOW, RISK_HIGH, RISK_MEDIUM):
        return (
            f'<span class="risk-badge risk-{_escape_html(r)}">{_escape_html(r)}</span>'
        )
    if r in (SEVERITY_CRITICAL, SEVERITY_WARNING, SEVERITY_INFO):
        return (
            f'<span class="severity-badge severity-{_escape_html(r)}">'
            f"{_escape_html(r)}</span>"
        )
    if r in _EFFORT_CSS:
        return (
            f'<span class="risk-badge risk-{_escape_html(r)}">{_escape_html(r)}</span>'
        )
    return _escape_html(text)


def _source_kind_badge_html(source_kind: str) -> str:
    normalized = normalize_source_kind(source_kind)
    return (
        f'<span class="source-kind-badge source-kind-{_escape_html(normalized)}">'
        f"{_escape_html(source_kind_label(normalized))}</span>"
    )


_INLINE_EMPTY_ICONS: dict[str, str] = {
    "good": (
        '<svg class="inline-empty-icon" viewBox="0 0 24 24" width="22" height="22" '
        'fill="none" stroke="currentColor" stroke-width="1.6" '
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<circle cx="12" cy="12" r="9.5"/>'
        '<polyline points="16.5 9.5 10.5 15.5 7.5 12.5"/></svg>'
    ),
    "neutral": (
        '<svg class="inline-empty-icon" viewBox="0 0 24 24" width="22" height="22" '
        'fill="none" stroke="currentColor" stroke-width="1.6" '
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<circle cx="12" cy="12" r="9.5"/>'
        '<line x1="12" y1="16" x2="12" y2="11"/>'
        '<circle cx="12" cy="8" r=".45" fill="currentColor" stroke="none"/></svg>'
    ),
}


def _inline_empty(message: str, *, tone: str = "neutral") -> str:
    """Compact single-row empty-state for inline/card contexts.

    Use for summary items, breakdown panels, and other small cards where a
    full ``.tab-empty`` would be too heavy.

    *tone*:
      - ``"good"``  — green check (positive: "nothing to report").
      - ``"neutral"`` — muted info dot (missing or unavailable data).
    """
    tone_key = tone if tone in _INLINE_EMPTY_ICONS else "neutral"
    icon = _INLINE_EMPTY_ICONS[tone_key]
    return (
        f'<div class="inline-empty inline-empty--{tone_key}">'
        f"{icon}"
        f'<span class="inline-empty-text">{_escape_html(message)}</span>'
        "</div>"
    )


def _tab_empty(
    message: str,
    *,
    description: str | None = "Nothing to report - keep up the good work.",
) -> str:
    desc_html = (
        f'<div class="tab-empty-desc">{_escape_html(description)}</div>'
        if description
        else ""
    )
    return (
        '<div class="tab-empty">'
        f"{CHECK_CIRCLE_SVG}"
        f'<div class="tab-empty-title">{_escape_html(message)}</div>'
        f"{desc_html}"
        "</div>"
    )


def _tab_empty_info(
    message: str,
    *,
    description: str | None = None,
    detail_html: str | None = None,
) -> str:
    if detail_html:
        desc_block = (
            f'<div class="tab-empty-desc tab-empty-desc-detail">{detail_html}</div>'
        )
    elif description:
        desc_block = (
            f'<div class="tab-empty-desc tab-empty-desc-detail">'
            f"{_escape_html(description)}</div>"
        )
    else:
        desc_block = ""
    return (
        '<div class="tab-empty">'
        f"{INFO_CIRCLE_SVG}"
        f'<div class="tab-empty-title">{_escape_html(message)}</div>'
        f"{desc_block}"
        "</div>"
    )


def _short_label(name: str, max_len: int = 18) -> str:
    """Shorten a dotted name keeping the last segment, truncated if needed."""
    parts = name.rsplit(".", maxsplit=1)
    label = parts[-1] if len(parts) > 1 else name
    if len(label) > max_len:
        half = max_len // 2 - 1
        return f"{label[:half]}..{label[-half:]}"
    return label


def _render_chain_flow(
    parts: Sequence[str],
    *,
    arrows: bool = False,
) -> str:
    """Render a sequence of names as chain-node spans, optionally with arrows."""
    nodes: list[str] = []
    for i, mod in enumerate(parts):
        short = _short_label(str(mod))
        nodes.append(
            f'<span class="chain-node" title="{_escape_html(str(mod))}">'
            f"{_escape_html(short)}</span>"
        )
        if arrows and i < len(parts) - 1:
            nodes.append('<span class="chain-arrow">\u2192</span>')
    return f'<span class="chain-flow">{"".join(nodes)}</span>'


def _stat_card(
    label: str,
    value: object,
    *,
    detail: str = "",
    tip: str = "",
    value_tone: str = "",
    css_class: str = "meta-item",
    glossary_tip_fn: Callable[[str], str] | None = None,
    delta_new: int | None = None,
) -> str:
    """Unified stat-card renderer.

    Always emits the same HTML structure using ``.meta-item`` /
    ``.meta-label`` / ``.meta-value`` so every stat card shares the
    exact same design code.

    *value_tone* — semantic color for the main value:
      ``"good"`` → green (metric is clean), ``"bad"`` → red (metric has issues),
      ``"warn"`` → yellow, ``"muted"`` → dimmed, ``""`` → default text-primary.

    *delta_new* — if provided and > 0, renders a ``+N new`` badge
    inline with the label (top-right).  For "bad" metrics (complexity,
    coupling, etc.) positive delta means regression → red.
    """
    tip_html = ""
    if glossary_tip_fn is not None:
        tip_html = glossary_tip_fn(label)
    elif tip:
        tip_html = f'<span class="kpi-help" data-tip="{_escape_html(tip)}">?</span>'

    detail_html = ""
    if detail:
        detail_html = f'<div class="kpi-detail">{detail}</div>'

    delta_html = ""
    if delta_new is not None and delta_new > 0:
        delta_html = f'<span class="kpi-delta kpi-delta--bad">+{delta_new}</span>'

    value_cls = f" meta-value--{value_tone}" if value_tone else ""

    return (
        f'<div class="{_escape_html(css_class)}">'
        f'<div class="meta-label">{_escape_html(label)}{tip_html}{delta_html}</div>'
        f'<div class="meta-value{value_cls}">{_escape_html(str(value))}</div>'
        f"{detail_html}"
        "</div>"
    )
