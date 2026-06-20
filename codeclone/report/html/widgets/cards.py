# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Shared finding/review card — one card chrome for the whole report.

``finding_card`` is the single source of truth for the visual shell of an
actionable item (a finding, a suggestion, a review-queue entry): a severity
stripe + severity badge, a title, optional eyebrow/location, a meta-badge row,
and slots for body, expandable details, and right-aligned actions. Each surface
supplies its own slot content, so the chrome stays identical everywhere without
duplicating markup.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..primitives.escape import _escape_html
from .badges import _quality_badge_html

if TYPE_CHECKING:
    from collections.abc import Sequence

_SEVERITIES = ("critical", "warning", "info")


def severity_key(severity: str) -> str:
    """Normalise an arbitrary severity string to a known stripe key."""
    key = severity.strip().lower()
    return key if key in _SEVERITIES else "info"


def meta_badge_html(text: str, *, tone: str = "") -> str:
    """A compact monospace meta badge (effort, priority, spread, signals…)."""
    tone_cls = f" finding-meta-badge--{_escape_html(tone)}" if tone else ""
    return f'<span class="finding-meta-badge{tone_cls}">{_escape_html(text)}</span>'


def finding_card(
    *,
    severity: str,
    title: str,
    eyebrow: str = "",
    location: str = "",
    meta_badges: Sequence[str] = (),
    body_html: str = "",
    details_html: str = "",
    actions_html: str = "",
    card_class: str = "",
    data_attrs: str = "",
) -> str:
    """Render the shared card shell. ``data_attrs`` is inserted verbatim and is
    expected to carry its own leading space when non-empty."""
    sev = severity_key(severity)
    extra_class = f" {card_class}" if card_class else ""
    eyebrow_html = (
        f'<div class="finding-card-eyebrow">{_escape_html(eyebrow)}</div>'
        if eyebrow
        else ""
    )
    location_html = (
        f'<div class="finding-card-loc">{_escape_html(location)}</div>'
        if location
        else ""
    )
    meta_html = (
        f'<div class="finding-card-meta">{"".join(meta_badges)}</div>'
        if meta_badges
        else ""
    )
    actions = (
        f'<div class="finding-card-actions">{actions_html}</div>'
        if actions_html
        else ""
    )
    body = f'<div class="finding-card-body">{body_html}</div>' if body_html else ""
    return (
        f'<article class="finding-card finding-card--{sev}{extra_class}"{data_attrs}>'
        '<span class="finding-card-stripe" aria-hidden="true"></span>'
        '<div class="finding-card-main">'
        '<div class="finding-card-head">'
        '<div class="finding-card-headings">'
        f"{eyebrow_html}"
        '<div class="finding-card-title">'
        f"{_quality_badge_html(sev)}"
        f'<span class="finding-card-title-text">{_escape_html(title)}</span>'
        "</div>"
        f"{location_html}"
        "</div>"
        f"{actions}"
        "</div>"
        f"{meta_html}{body}{details_html}"
        "</div></article>"
    )
