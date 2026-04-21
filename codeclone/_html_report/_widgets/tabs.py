# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Tab/subtab rendering helpers."""

from __future__ import annotations

from collections.abc import Sequence

from .._html_escape import _escape_html


def render_split_tabs(
    *,
    group_id: str,
    tabs: Sequence[tuple[str, str, int, str]],
    emit_clone_counters: bool = False,
) -> str:
    """Render sub-tab navigation + panels.

    Each tab tuple: ``(tab_id, label, count, panel_html)``.
    """
    if not tabs:
        return ""

    nav: list[str] = [
        '<nav class="clone-nav" role="tablist" '
        f'data-subtab-group="{_escape_html(group_id)}">'
    ]
    for idx, (tab_id, label, count, _) in enumerate(tabs):
        active = " active" if idx == 0 else ""
        if emit_clone_counters:
            badge = (
                f'<span class="tab-count" data-clone-tab-count="{tab_id}" '
                f'data-total-groups="{count}">{count}</span>'
            )
        else:
            badge = f'<span class="tab-count">{count}</span>'
        nav.append(
            f'<button class="clone-nav-btn{active}" '
            f'data-clone-tab="{tab_id}" '
            f'data-subtab-group="{_escape_html(group_id)}" '
            f'type="button">{_escape_html(label)} {badge}</button>'
        )
    nav.append("</nav>")

    panels: list[str] = []
    for idx, (tab_id, _, _, panel_html) in enumerate(tabs):
        active = " active" if idx == 0 else ""
        panels.append(
            f'<div class="clone-panel{active}" '
            f'data-clone-panel="{tab_id}" '
            f'data-subtab-group="{_escape_html(group_id)}">'
            f"{panel_html}</div>"
        )

    return f"{''.join(nav)}{''.join(panels)}"
