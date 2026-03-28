# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

"""SVG icon constants for the HTML report (Lucide-style)."""

from __future__ import annotations


def _svg(size: int, sw: str, body: str) -> str:
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        f'stroke="currentColor" stroke-width="{sw}" '
        f'stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    )


BRAND_LOGO = (
    '<svg class="brand-logo" width="32" height="32" viewBox="0 0 32 32" fill="none">'
    '<rect x="9" y="3" width="18" height="23" rx="3.5" '
    'stroke="var(--accent-primary)" stroke-width="1.5" opacity="0.25"/>'
    '<rect x="5" y="6" width="18" height="23" rx="3.5" '
    'stroke="var(--accent-primary)" stroke-width="1.5"/>'
    '<path d="M11 14L7.5 17.5 11 21" stroke="var(--accent-primary)" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
    '<path d="M17 14l3.5 3.5L17 21" stroke="var(--accent-primary)" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
    "</svg>"
)

ICONS: dict[str, str] = {
    "search": _svg(
        16,
        "2.5",
        '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
    ),
    "clear": _svg(
        16,
        "2.5",
        '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
    ),
    "chev_down": _svg(
        16,
        "2.5",
        '<polyline points="6 9 12 15 18 9"/>',
    ),
    "theme": _svg(
        16,
        "2",
        '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>',
    ),
    "check": _svg(
        48,
        "2",
        '<polyline points="20 6 9 17 4 12"/>',
    ),
    "prev": _svg(
        16,
        "2",
        '<polyline points="15 18 9 12 15 6"/>',
    ),
    "next": _svg(
        16,
        "2",
        '<polyline points="9 18 15 12 9 6"/>',
    ),
    "sort_asc": _svg(
        12,
        "2",
        '<polyline points="6 15 12 9 18 15"/>',
    ),
    "sort_desc": _svg(
        12,
        "2",
        '<polyline points="6 9 12 15 18 9"/>',
    ),
    "ide": _svg(
        16,
        "2",
        '<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>',
    ),
}
