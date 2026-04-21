# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Data-driven filter dropdown renderer for report toolbars."""

from __future__ import annotations

from collections.abc import Sequence

from ._html_escape import _escape_html

__all__ = [
    "CLONE_TYPE_OPTIONS",
    "SPREAD_OPTIONS",
    "_render_select",
]

CLONE_TYPE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Type-1", "Type-1"),
    ("Type-2", "Type-2"),
    ("Type-3", "Type-3"),
    ("Type-4", "Type-4"),
)

SPREAD_OPTIONS: tuple[tuple[str, str], ...] = (
    ("high", "high"),
    ("low", "low"),
)


def _render_select(
    *,
    element_id: str,
    data_attr: str,
    options: Sequence[tuple[str, str]],
    all_label: str = "all",
    selected: str | None = None,
) -> str:
    """Render a ``<select>`` dropdown with an *all* option followed by *options*.

    Each option is ``(value, display_text)``.  The *data_attr* is placed
    directly on the element (e.g. ``data-source-kind-filter="functions"``).
    """
    parts = [
        f'<select class="select" id="{_escape_html(element_id)}" '
        f"{data_attr}>"
        f'<option value="">{_escape_html(all_label)}</option>',
    ]
    for value, display in options:
        sel = " selected" if selected == value else ""
        parts.append(
            f'<option value="{_escape_html(value)}"{sel}>'
            f"{_escape_html(display)}</option>"
        )
    parts.append("</select>")
    return "".join(parts)
