# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""SVG icon constants for the HTML report (Lucide-style)."""

from __future__ import annotations


def _svg(size: int, sw: str, body: str) -> str:
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        f'stroke="currentColor" stroke-width="{sw}" '
        f'stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    )


def _svg_with_class(size: int, sw: str, body: str, *, class_name: str = "") -> str:
    class_attr = f' class="{class_name}"' if class_name else ""
    return (
        f'<svg{class_attr} width="{size}" height="{size}" viewBox="0 0 24 24" '
        f'fill="none" stroke="currentColor" stroke-width="{sw}" '
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

_SECTION_ICON_BODIES: dict[str, tuple[str, str]] = {
    "overview": (
        "2",
        '<rect x="3" y="4" width="8" height="7" rx="1.5"/>'
        '<rect x="13" y="4" width="8" height="7" rx="1.5"/>'
        '<rect x="3" y="13" width="8" height="7" rx="1.5"/>'
        '<rect x="13" y="13" width="8" height="7" rx="1.5"/>',
    ),
    "clones": (
        "2",
        '<rect x="9" y="9" width="10" height="10" rx="2"/>'
        '<rect x="5" y="5" width="10" height="10" rx="2"/>',
    ),
    "quality": (
        "2",
        '<path d="M4 19h16"/><rect x="5" y="11" width="3" height="6" rx="1"/>'
        '<rect x="10.5" y="7" width="3" height="10" rx="1"/>'
        '<rect x="16" y="4" width="3" height="13" rx="1"/>',
    ),
    "dependencies": (
        "2",
        '<circle cx="6" cy="6" r="2"/><circle cx="18" cy="6" r="2"/>'
        '<circle cx="12" cy="18" r="2"/><path d="M8 7.5l2.5 6.5"/>'
        '<path d="M16 7.5l-2.5 6.5"/>',
    ),
    "dead-code": (
        "2",
        '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/>'
        '<path d="M14 3v6h6"/><path d="M9 14l6 6"/><path d="M15 14l-6 6"/>',
    ),
    "suggestions": (
        "2",
        '<path d="M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8Z"/>'
        '<path d="M19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8Z"/>',
    ),
    "structural-findings": (
        "2",
        '<circle cx="6" cy="6" r="2"/><circle cx="18" cy="18" r="2"/>'
        '<circle cx="18" cy="6" r="2"/><path d="M8 6h8"/>'
        '<path d="M6 8v8a2 2 0 0 0 2 2h8"/>',
    ),
    "top-risks": (
        "2",
        '<path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86'
        'a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/>'
        '<line x1="12" y1="17" x2="12.01" y2="17"/>',
    ),
    "issue-breakdown": (
        "2",
        '<rect x="3" y="3" width="18" height="4" rx="1"/>'
        '<rect x="3" y="10" width="13" height="4" rx="1"/>'
        '<rect x="3" y="17" width="8" height="4" rx="1"/>',
    ),
    "source-breakdown": (
        "2",
        '<path d="M21.21 15.89A10 10 0 118 2.83"/>'
        '<path d="M22 12A10 10 0 0012 2v10z"/>',
    ),
    "health-profile": (
        "2",
        '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/>'
        '<circle cx="12" cy="12" r="2"/><line x1="12" y1="2" x2="12" y2="6"/>'
        '<line x1="12" y1="18" x2="12" y2="22"/>',
    ),
    "all-findings": (
        "2",
        '<circle cx="5" cy="6" r="1.5"/><circle cx="5" cy="12" r="1.5"/>'
        '<circle cx="5" cy="18" r="1.5"/><path d="M10 6h10"/><path d="M10 12h10"/>'
        '<path d="M10 18h10"/>',
    ),
    "clone-groups": (
        "2",
        '<rect x="9" y="9" width="10" height="10" rx="2"/>'
        '<rect x="5" y="5" width="10" height="10" rx="2"/>',
    ),
    "low-cohesion": (
        "2",
        '<rect x="4" y="5" width="6" height="14" rx="1.5"/>'
        '<rect x="14" y="5" width="6" height="14" rx="1.5"/>'
        '<path d="M10 12h4"/>',
    ),
}


def section_icon_html(
    key: str,
    *,
    class_name: str = "",
    size: int = 16,
) -> str:
    spec = _SECTION_ICON_BODIES.get(key.strip().lower())
    if spec is None:
        return ""
    stroke_width, body = spec
    return _svg_with_class(size, stroke_width, body, class_name=class_name)
