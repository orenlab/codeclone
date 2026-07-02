# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Combined tour panels: typewriter body plus optional metric lines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .typewriter import TypewriterPanel

if TYPE_CHECKING:
    from rich.console import Console, ConsoleOptions, RenderableType, RenderResult

TOUR_STATS_HEIGHT = 2
TOUR_BODY_PANEL_HEIGHT = 8


@dataclass(frozen=True, slots=True)
class TourStatsLines:
    """Compact metric lines shown under the mascot during a tour step."""

    lines: tuple[str, ...]
    style: str = "codeclone.muted"
    height: int = TOUR_STATS_HEIGHT

    def __rich_console__(
        self,
        console: Console,
        options: ConsoleOptions,
    ) -> RenderResult:
        from rich.text import Text

        visible = self.lines[: self.height]
        padded = visible + ("",) * max(0, self.height - len(visible))
        for line in padded:
            yield Text(line, style=self.style)


def build_step_panel(
    *,
    body: str,
    visible_chars: int,
    cursor_on: bool,
    use_unicode: bool,
    stats: tuple[str, ...] = (),
) -> RenderableType:
    from rich.console import Group

    stats_block = TourStatsLines(lines=stats)
    typewriter = TypewriterPanel(
        text=body,
        visible_chars=visible_chars,
        cursor_on=cursor_on,
        use_unicode=use_unicode,
        height=TOUR_BODY_PANEL_HEIGHT,
    )
    return Group(stats_block, typewriter)


__all__ = [
    "TOUR_BODY_PANEL_HEIGHT",
    "TOUR_STATS_HEIGHT",
    "TourStatsLines",
    "build_step_panel",
]
