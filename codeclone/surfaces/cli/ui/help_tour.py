# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Interactive CodeClone tour for ``codeclone --help --interactive-help``.

Each animated step uses a distinct ``AsterAnimation`` loop in the default tour.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ....ui_messages import help as help_ui
from ..console import make_query_console, supports_rich_console
from ..types import PrinterLike
from .mascot import Aster, mascot_use_unicode
from .mascot_frames import AsterAnimation, AsterState, resolve_animation
from .progress_presenter import ProgressPresenter
from .tour_panel import build_step_panel

if TYPE_CHECKING:
    from rich.console import Console as RichConsole

_TICK_INTERVAL = 0.05
_FRAME_INTERVAL = 0.14
_CHAR_INTERVAL = 0.022
_MIN_READ_PAUSE = 3.0
_CURSOR_BLINK_INTERVAL = 0.48
_READ_BONUS_PER_100_CHARS = 1.0
_READ_BONUS_CAP = 2.0

_DEMO_STATS_SCAN: tuple[str, ...] = (
    "Files      741 / 741",
    "Parsed     741",
    "Callables  8,665",
)

_DEMO_STATS_SUCCESS: tuple[str, ...] = (
    "741 files · 249,108 LOC · 10 known · 0 new",
    "HTML report: .codeclone/report.html",
)

_DEMO_STATS_REGRESSION: tuple[str, ...] = (
    "NEW clones: 2 · health delta: -3",
    "Review: .codeclone/report.html",
)


@dataclass(frozen=True, slots=True)
class HelpTourStep:
    state: AsterState
    title: str
    body: str
    animate: bool = False
    animation: AsterAnimation | None = None
    stats: tuple[str, ...] = ()


_DEFAULT_STEPS: tuple[HelpTourStep, ...] = (
    HelpTourStep(
        AsterState.IDLE,
        help_ui.HELP_TOUR_STEP_INTRO_TITLE,
        help_ui.HELP_TOUR_STEP_INTRO_BODY,
    ),
    HelpTourStep(
        AsterState.SCANNING,
        help_ui.HELP_TOUR_STEP_PIPELINE_TITLE,
        help_ui.HELP_TOUR_STEP_PIPELINE_BODY,
        animate=True,
        animation=AsterAnimation.SCANNING,
        stats=_DEMO_STATS_SCAN,
    ),
    HelpTourStep(
        AsterState.SCANNING,
        help_ui.HELP_TOUR_STEP_CLONES_TITLE,
        help_ui.HELP_TOUR_STEP_CLONES_BODY,
        animate=True,
        animation=AsterAnimation.GRAPH_PULSE,
    ),
    HelpTourStep(
        AsterState.CACHE,
        help_ui.HELP_TOUR_STEP_CACHE_TITLE,
        help_ui.HELP_TOUR_STEP_CACHE_BODY,
        animate=True,
        animation=AsterAnimation.CACHE_CHAIN,
    ),
    HelpTourStep(
        AsterState.DEPENDENCIES,
        help_ui.HELP_TOUR_STEP_DEPENDENCIES_TITLE,
        help_ui.HELP_TOUR_STEP_DEPENDENCIES_BODY,
        animate=True,
        animation=AsterAnimation.DEPENDENCIES,
    ),
    HelpTourStep(
        AsterState.BLAST_RADIUS,
        help_ui.HELP_TOUR_STEP_METRICS_TITLE,
        help_ui.HELP_TOUR_STEP_METRICS_BODY,
        animate=True,
        animation=AsterAnimation.BLAST_RIPPLE,
    ),
    HelpTourStep(
        AsterState.REPORTING,
        help_ui.HELP_TOUR_STEP_REPORTS_TITLE,
        help_ui.HELP_TOUR_STEP_REPORTS_BODY,
        animate=True,
        animation=AsterAnimation.REPORTING,
    ),
    HelpTourStep(
        AsterState.ATTENTION,
        help_ui.HELP_TOUR_STEP_BASELINE_TITLE,
        help_ui.HELP_TOUR_STEP_BASELINE_BODY,
    ),
    HelpTourStep(
        AsterState.CONTROL,
        help_ui.HELP_TOUR_STEP_CONTROLLER_TITLE,
        help_ui.HELP_TOUR_STEP_CONTROLLER_BODY,
        animate=True,
        animation=AsterAnimation.CONTROL_GATE,
    ),
    HelpTourStep(
        AsterState.IDLE,
        help_ui.HELP_TOUR_STEP_MEMORY_TITLE,
        help_ui.HELP_TOUR_STEP_MEMORY_BODY,
        animate=True,
        animation=AsterAnimation.ORIGIN_HUB,
    ),
    HelpTourStep(
        AsterState.ANALYSIS,
        help_ui.HELP_TOUR_STEP_INTEGRATIONS_TITLE,
        help_ui.HELP_TOUR_STEP_INTEGRATIONS_BODY,
        animate=True,
        animation=AsterAnimation.ANALYSIS_BRANCH,
    ),
    HelpTourStep(
        AsterState.SUCCESS,
        help_ui.HELP_TOUR_STEP_SUCCESS_TITLE,
        help_ui.HELP_TOUR_STEP_SUCCESS_BODY,
        stats=_DEMO_STATS_SUCCESS,
    ),
    HelpTourStep(
        AsterState.ATTENTION,
        help_ui.HELP_TOUR_STEP_REGRESSION_TITLE,
        help_ui.HELP_TOUR_STEP_REGRESSION_BODY,
        stats=_DEMO_STATS_REGRESSION,
    ),
    HelpTourStep(
        AsterState.BLOCKED,
        help_ui.HELP_TOUR_STEP_BLOCKED_TITLE,
        help_ui.HELP_TOUR_STEP_BLOCKED_BODY,
        animate=True,
        animation=AsterAnimation.BLOCKED_SPLIT,
    ),
    HelpTourStep(
        AsterState.SUCCESS,
        help_ui.HELP_TOUR_STEP_NEXT_TITLE,
        help_ui.HELP_TOUR_STEP_NEXT_BODY,
    ),
)


def _interactive_terminal_available() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _rich_console_or_none(console: PrinterLike) -> RichConsole | None:
    if not supports_rich_console(console):
        return None
    from rich.console import Console as RichConsoleType

    if isinstance(console, RichConsoleType):
        return console
    return None


def _read_pause_for(text: str, *, min_pause: float) -> float:
    bonus = min(_READ_BONUS_CAP, (len(text) / 100.0) * _READ_BONUS_PER_100_CHARS)
    return min_pause + bonus


def _show_frame(
    presenter: ProgressPresenter,
    step: HelpTourStep,
    *,
    frame_lines: tuple[str, ...] | None,
    visible_chars: int,
    cursor_on: bool,
    use_unicode: bool,
) -> None:
    presenter.set_mascot(step.state, message=step.title, frame_lines=frame_lines)
    presenter.set_extra(
        build_step_panel(
            body=step.body,
            visible_chars=visible_chars,
            cursor_on=cursor_on,
            use_unicode=use_unicode,
            stats=step.stats,
        )
    )


def _run_rich_step(
    presenter: ProgressPresenter,
    step: HelpTourStep,
    *,
    use_unicode: bool,
    sleep: Callable[[float], None],
    tick_interval: float,
    frame_interval: float,
    char_interval: float,
    min_read_pause: float,
    cursor_blink_interval: float,
) -> None:
    anim_frames = resolve_animation(
        step.state,
        animation=step.animation,
        animate=step.animate,
        use_unicode=use_unicode,
    )
    read_pause = _read_pause_for(step.body, min_pause=min_read_pause)
    total_chars = len(step.body)
    elapsed = 0.0
    typed = 0
    anim_index = 0
    cursor_on = True
    typing_done_at: float | None = None
    since_anim = 0.0
    since_char = 0.0
    since_blink = 0.0

    while True:
        frame_lines = None
        if anim_frames:
            frame_lines = anim_frames[anim_index % len(anim_frames)]

        _show_frame(
            presenter,
            step,
            frame_lines=frame_lines,
            visible_chars=typed,
            cursor_on=cursor_on,
            use_unicode=use_unicode,
        )

        sleep(tick_interval)
        elapsed += tick_interval

        if anim_frames:
            since_anim += tick_interval
            if since_anim >= frame_interval:
                anim_index += 1
                since_anim = 0.0

        if typed < total_chars:
            since_char += tick_interval
            if since_char >= char_interval:
                typed += 1
                since_char = 0.0

        if typed >= total_chars:
            if typing_done_at is None:
                typing_done_at = elapsed
            since_blink += tick_interval
            if since_blink >= cursor_blink_interval:
                cursor_on = not cursor_on
                since_blink = 0.0
            if elapsed - typing_done_at >= read_pause:
                break


def _render_plain_tour(
    steps: Sequence[HelpTourStep],
    printer: PrinterLike,
    *,
    sleep: Callable[[float], None],
    plain_step_pause: float,
) -> None:
    for step in steps:
        aster = Aster(step.state, message=step.title, use_unicode=False)
        for line in aster.plain_lines():
            printer.print(line)
        for stat in step.stats:
            printer.print(stat)
        printer.print(step.body)
        printer.print("")
        sleep(plain_step_pause)


def run_interactive_help_tour(
    *,
    console: PrinterLike | None = None,
    steps: Sequence[HelpTourStep] = _DEFAULT_STEPS,
    sleep: Callable[[float], None] = time.sleep,
    tick_interval: float = _TICK_INTERVAL,
    frame_interval: float = _FRAME_INTERVAL,
    char_interval: float = _CHAR_INTERVAL,
    min_read_pause: float = _MIN_READ_PAUSE,
    cursor_blink_interval: float = _CURSOR_BLINK_INTERVAL,
    plain_step_pause: float = 1.5,
) -> int:
    if console is None:
        console = make_query_console()

    rich_console = _rich_console_or_none(console)
    if not _interactive_terminal_available() or rich_console is None:
        _render_plain_tour(
            steps, console, sleep=sleep, plain_step_pause=plain_step_pause
        )
        return 0

    use_unicode = mascot_use_unicode(
        no_color=bool(getattr(rich_console, "no_color", False)),
    )

    presenter = ProgressPresenter(rich_console)
    first = steps[0]
    _show_frame(
        presenter,
        first,
        frame_lines=None,
        visible_chars=0,
        cursor_on=True,
        use_unicode=use_unicode,
    )
    with presenter.live_context(refresh_per_second=12, transient=False) as live:
        presenter.bind_live(live)
        for step in steps:
            _run_rich_step(
                presenter,
                step,
                use_unicode=use_unicode,
                sleep=sleep,
                tick_interval=tick_interval,
                frame_interval=frame_interval,
                char_interval=char_interval,
                min_read_pause=min_read_pause,
                cursor_blink_interval=cursor_blink_interval,
            )
        presenter.clear_live()

    return 0


__all__ = ["HelpTourStep", "run_interactive_help_tour"]
