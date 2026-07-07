# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Single owner for Live + mascot + progress renderables during CLI analysis.

``AsterAnimation`` in ``mascot_frames`` selects phase loops (scanning, graph pulse,
dependencies, reporting) for help tour and future analysis progress wiring.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .mascot import Aster, mascot_use_unicode
from .mascot_frames import AsterState

if TYPE_CHECKING:
    from rich.console import Console, RenderableType
    from rich.live import Live

_MASCOT_FRAME_HEIGHT = 5


@dataclass
class ProgressPresenter:
    """Coordinates mascot state with a shared Rich Live container."""

    console: Console
    mascot_state: AsterState = AsterState.SCANNING
    mascot_message: str | None = None
    mascot_frame_lines: tuple[str, ...] | None = None
    extra_renderables: tuple[RenderableType, ...] = field(default_factory=tuple)
    _live: Live | None = field(default=None, init=False, repr=False)

    def set_mascot(
        self,
        state: AsterState,
        *,
        message: str | None = None,
        frame_lines: tuple[str, ...] | None = None,
    ) -> None:
        self.mascot_state = state
        self.mascot_message = message
        self.mascot_frame_lines = frame_lines
        self.refresh()

    def set_extra(self, *renderables: RenderableType) -> None:
        self.extra_renderables = renderables
        self.refresh()

    def build_renderable(self) -> RenderableType:
        from rich.console import Group

        mascot = Aster(
            self.mascot_state,
            message=self.mascot_message,
            frame_lines=self.mascot_frame_lines,
            use_unicode=mascot_use_unicode(
                no_color=bool(getattr(self.console, "no_color", False)),
            ),
            min_frame_lines=_MASCOT_FRAME_HEIGHT,
        )
        if self.extra_renderables:
            return Group(mascot, *self.extra_renderables)
        return mascot

    def refresh(self) -> None:
        if self._live is not None:
            self._live.update(self.build_renderable(), refresh=True)

    def live_context(
        self,
        *,
        refresh_per_second: float = 8,
        transient: bool = False,
    ) -> Live:
        from rich.live import Live

        return Live(
            self.build_renderable(),
            console=self.console,
            refresh_per_second=refresh_per_second,
            transient=transient,
        )

    def bind_live(self, live: Live) -> None:
        self._live = live

    def clear_live(self) -> None:
        self._live = None


__all__ = ["ProgressPresenter"]
