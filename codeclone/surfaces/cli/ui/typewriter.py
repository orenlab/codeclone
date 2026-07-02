# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Typewriter text panel with blinking cursor for interactive CLI tours."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.console import Console, ConsoleOptions, RenderResult


@dataclass(frozen=True, slots=True)
class TypewriterPanel:
    """Panel that reveals ``text`` progressively with an optional blinking cursor."""

    text: str
    visible_chars: int
    cursor_visible: bool = True
    cursor_on: bool = True
    use_unicode: bool = True
    border_style: str = "codeclone.primary"
    text_style: str = "codeclone.muted"
    cursor_style: str = "codeclone.primary"
    height: int | None = None

    @property
    def _cursor_char(self) -> str:
        if not self.cursor_visible:
            return ""
        if not self.cursor_on:
            return " "
        return "▌" if self.use_unicode else "|"

    def _render_parts(self) -> tuple[str, str]:
        clipped = max(0, min(self.visible_chars, len(self.text)))
        body = self.text[:clipped]
        cursor = self._cursor_char if self.cursor_visible else ""
        return body, cursor

    def __rich_console__(
        self,
        console: Console,
        options: ConsoleOptions,
    ) -> RenderResult:
        from rich.panel import Panel
        from rich.text import Text

        body, cursor = self._render_parts()
        content = Text(body, style=self.text_style)
        if cursor:
            content.append(cursor, style=self.cursor_style)
        yield Panel(
            content,
            border_style=self.border_style,
            height=self.height,
            padding=(0, 1),
        )


__all__ = ["TypewriterPanel"]
