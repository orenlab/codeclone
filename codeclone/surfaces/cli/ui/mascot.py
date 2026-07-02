# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Rich renderable for the CodeClone CLI mascot."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .mascot_frames import AsterFrame, AsterState, frame_for_state

if TYPE_CHECKING:
    from rich.console import Console, ConsoleOptions, RenderResult


def mascot_use_unicode(*, no_color: bool = False) -> bool:
    if no_color or os.environ.get("NO_COLOR"):
        return False
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        "●".encode(encoding)
    except (LookupError, UnicodeEncodeError):
        return False
    return True


@dataclass(frozen=True, slots=True)
class Aster:
    state: AsterState
    message: str | None = None
    frame_lines: tuple[str, ...] | None = None
    style: str | None = None
    use_unicode: bool = True
    min_frame_lines: int = 0

    def resolved_frame(self) -> AsterFrame:
        base = frame_for_state(self.state, use_unicode=self.use_unicode)
        lines = self.frame_lines if self.frame_lines is not None else base.lines
        message = self.message if self.message is not None else base.message
        style = self.style if self.style is not None else base.style
        return AsterFrame(lines=lines, message=message, style=style)

    def _display_lines(self, lines: tuple[str, ...]) -> tuple[str, ...]:
        stripped = tuple(line.rstrip() for line in lines)
        if self.min_frame_lines <= len(stripped):
            return stripped
        missing = self.min_frame_lines - len(stripped)
        top_padding = missing // 2
        bottom_padding = missing - top_padding
        return ("",) * top_padding + stripped + ("",) * bottom_padding

    def plain_lines(self) -> tuple[str, ...]:
        frame = self.resolved_frame()
        lines = self._display_lines(frame.lines)
        body = f"{frame.message}  CodeClone · Structural Change Controller"
        if len(lines) >= 2:
            middle = lines[1]
            padded = f"{middle}  {body}" if len(middle) < 24 else body
            return (lines[0], padded.rstrip(), *lines[2:])
        return (*lines, body)

    def __rich_console__(
        self,
        console: Console,
        options: ConsoleOptions,
    ) -> RenderResult:
        from rich.text import Text

        frame = self.resolved_frame()
        lines = self._display_lines(frame.lines)
        message_line = len(lines) // 2
        for index, line in enumerate(lines):
            text = Text(line, style=frame.style)
            if index == message_line:
                text.append("  ")
                text.append(frame.message, style="codeclone.muted")
            yield text


__all__ = ["Aster", "mascot_use_unicode"]
