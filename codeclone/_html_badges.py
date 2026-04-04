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
    "_quality_badge_html",
    "_render_chain_flow",
    "_short_label",
    "_source_kind_badge_html",
    "_stat_card",
    "_tab_empty",
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


def _tab_empty(message: str) -> str:
    return (
        '<div class="tab-empty">'
        f"{CHECK_CIRCLE_SVG}"
        f'<div class="tab-empty-title">{_escape_html(message)}</div>'
        '<div class="tab-empty-desc">'
        "Nothing to report - keep up the good work."
        "</div>"
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
