# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
# ruff: noqa: RUF001

from __future__ import annotations

import argparse
import importlib.abc
import importlib.machinery
import inspect
import io
import os
import re
import sys
from collections.abc import Callable, Sequence
from typing import Any, cast
from unittest.mock import patch

import pytest

from codeclone import ui_messages
from codeclone.config.argparse_builder import build_parser
from codeclone.contracts import ExitCode, cli_help_epilog
from codeclone.surfaces.cli import workflow as cli_workflow
from codeclone.surfaces.cli.console import PlainConsole, make_query_console
from codeclone.surfaces.cli.ui import help_tour as help_tour_mod
from codeclone.surfaces.cli.ui.help_presenter import (
    interactive_help_requested,
    static_help_mascot_lines,
)
from codeclone.surfaces.cli.ui.help_tour import HelpTourStep, run_interactive_help_tour
from codeclone.surfaces.cli.ui.mascot import Aster
from codeclone.surfaces.cli.ui.mascot_frames import (
    AsterAnimation,
    AsterState,
    animation_frames_for_kind,
    animation_frames_for_state,
    frame_for_state,
    graph_pulse_animation_frames,
)
from codeclone.surfaces.cli.ui.progress_presenter import ProgressPresenter
from codeclone.surfaces.cli.ui.tour_panel import TourStatsLines, build_step_panel
from codeclone.surfaces.cli.ui.typewriter import TypewriterPanel


def _run_animated_rich_step(
    *,
    body: str,
    tick_interval: float,
    frame_interval: float,
    char_interval: float,
    min_read_pause: float,
    cursor_blink_interval: float,
) -> list[float]:
    from rich.console import Console

    from codeclone.surfaces.cli.console import make_query_console
    from codeclone.surfaces.cli.ui import help_tour as help_tour_mod

    sleeps: list[float] = []
    step = HelpTourStep(
        AsterState.SCANNING,
        "Animated",
        body,
        animate=True,
        animation=AsterAnimation.GRAPH_PULSE,
    )
    presenter = ProgressPresenter(cast(Console, make_query_console(no_color=False)))
    help_tour_mod._run_rich_step(
        presenter,
        step,
        use_unicode=True,
        sleep=lambda seconds: sleeps.append(seconds),
        tick_interval=tick_interval,
        frame_interval=frame_interval,
        char_interval=char_interval,
        min_read_pause=min_read_pause,
        cursor_blink_interval=cursor_blink_interval,
    )
    return sleeps


def test_static_help_mascot_lines_include_product_tagline() -> None:
    lines = static_help_mascot_lines(use_unicode=True)
    assert any("●" in line for line in lines)
    assert any(ui_messages.BANNER_SUBTITLE in line for line in lines)
    assert lines[-1].startswith("Run `codeclone --help --interactive-help`")


def test_interactive_help_requested_detects_flags() -> None:
    assert interactive_help_requested(["--help", "--interactive-help"])
    assert interactive_help_requested(["--interactive-help", "--help"])
    assert not interactive_help_requested(["--help"])
    assert not interactive_help_requested(["--interactive"])
    assert not interactive_help_requested(["-i"])


def test_build_parser_print_help_prepends_mascot() -> None:
    parser = build_parser("9.9.9")
    buffer = io.StringIO()
    parser.print_help(file=buffer)
    text = buffer.getvalue()
    assert ui_messages.BANNER_SUBTITLE in text
    assert "--interactive-help" in text
    assert "usage: codeclone" in text
    assert "\x1b[" not in text


def test_help_action_runs_interactive_tour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def _fake_tour() -> int:
        calls.append("tour")
        return 0

    monkeypatch.setattr(
        "codeclone.surfaces.cli.ui.help_tour.run_interactive_help_tour",
        _fake_tour,
    )
    with pytest.raises(SystemExit) as exc:
        build_parser("9.9.9").parse_args(["--help", "--interactive-help"])
    assert exc.value.code == 0
    assert calls == ["tour"]


def test_interactive_flag_requires_help() -> None:
    with pytest.raises(SystemExit) as exc:
        build_parser("9.9.9").parse_args(["--interactive-help"])
    assert exc.value.code == int(ExitCode.CONTRACT_ERROR)


def test_run_interactive_help_tour_plain_fallback() -> None:
    from codeclone.surfaces.cli.console import PlainConsole

    console = PlainConsole()
    assert run_interactive_help_tour(console=console, sleep=lambda _s: None) == 0


def test_run_interactive_help_tour_non_tty_plain_fallback_does_not_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.surfaces.cli.console import PlainConsole
    from codeclone.surfaces.cli.ui import help_tour

    sleeps: list[float] = []
    monkeypatch.setattr(help_tour, "_interactive_terminal_available", lambda: False)

    rc = help_tour.run_interactive_help_tour(
        console=PlainConsole(),
        steps=(
            HelpTourStep(
                AsterState.IDLE,
                "Short",
                "Plain fallback",
                animate=False,
            ),
        ),
        sleep=lambda seconds: sleeps.append(seconds),
    )

    assert rc == 0
    assert sleeps == []


def test_progress_presenter_builds_group_with_mascot() -> None:
    pytest.importorskip("rich")
    from rich.console import Console

    console = Console(record=True, width=80, force_terminal=True)
    presenter = ProgressPresenter(
        console,
        mascot_state=AsterState.SCANNING,
    )
    renderable = presenter.build_renderable()
    with console.capture() as capture:
        console.print(renderable)
    assert "Mapping repository structure" in capture.get()


def test_progress_presenter_keeps_mascot_height_stable() -> None:
    pytest.importorskip("rich")
    from codeclone.surfaces.cli.console import make_console

    console = make_console(no_color=False, width=80)
    console.record = True
    rendered_heights: set[int] = set()
    for state in (
        AsterState.REPORTING,
        AsterState.DEPENDENCIES,
        AsterState.ANALYSIS,
        AsterState.SUCCESS,
    ):
        presenter = ProgressPresenter(console, mascot_state=state)
        with console.capture() as capture:
            console.print(presenter.build_renderable())
        rendered_heights.add(len(capture.get().splitlines()))
    assert rendered_heights == {5}


def test_cli_module_help_includes_mascot(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["codeclone", "--help"])
    with pytest.raises(SystemExit) as exc:
        cli_workflow.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert ui_messages.BANNER_SUBTITLE in out
    assert "\x1b[" not in out


def test_help_tour_step_dataclass() -> None:
    step = HelpTourStep(AsterState.IDLE, "Title", "Body", animate=False)
    assert step.title == "Title"


def test_progress_presenter_live_session_updates() -> None:
    pytest.importorskip("rich")
    from rich.console import Console
    from rich.text import Text

    console = Console(record=True, width=80, force_terminal=True)
    presenter = ProgressPresenter(
        console,
        mascot_state=AsterState.SCANNING,
    )
    with presenter.live_context(transient=True) as live:
        presenter.bind_live(live)
        presenter.set_extra(Text("phase metrics"))
        presenter.set_mascot(
            AsterState.REPORTING,
            message="Compiling reports…",
        )
        presenter.clear_live()
    assert presenter.mascot_state is AsterState.REPORTING


def test_aster_plain_lines_ascii_fallback() -> None:
    lines = Aster(AsterState.SUCCESS, use_unicode=False).plain_lines()
    assert any("Analysis complete" in line for line in lines)


def test_mascot_use_unicode_respects_no_color_and_encoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.surfaces.cli.ui import mascot as mascot_mod

    monkeypatch.setenv("NO_COLOR", "1")
    assert mascot_mod.mascot_use_unicode() is False

    monkeypatch.delenv("NO_COLOR", raising=False)
    assert mascot_mod.mascot_use_unicode(no_color=True) is False

    class _BrokenStdout:
        encoding = "ascii"

    monkeypatch.setattr(os, "environ", {})
    monkeypatch.setattr(sys, "stdout", _BrokenStdout())
    assert mascot_mod.mascot_use_unicode() is False


def test_aster_plain_lines_carry_the_message_and_not_the_product_identity() -> None:
    """A mascot states its own message; the product identity is the screen's.

    ``plain_lines`` used to append ``product_identity()`` to whatever message
    the caller passed. On the help banner that printed the idle frame's
    wording and the identity side by side -- the same claim twice -- and on
    the plain tour it restated the identity under all fifteen step titles.
    Callers that want the identity now pass it as the message, which is what
    ``static_help_mascot_lines`` does.
    """

    lines = Aster(
        AsterState.IDLE,
        message="Hi",
        frame_lines=("top", "x", "bottom"),
        use_unicode=False,
    ).plain_lines()

    # Short middle row: the frame column survives and the message hangs off it.
    assert lines[1] == "x  Hi"
    assert not any(ui_messages.BANNER_SUBTITLE in line for line in lines)


def test_aster_plain_lines_wide_middle_row_yields_to_the_message() -> None:
    """The other side of the same branch, so neither can be flipped unseen."""

    lines = Aster(
        AsterState.IDLE,
        message="Hi",
        frame_lines=("top", "x" * 24, "bottom"),
        use_unicode=False,
    ).plain_lines()

    assert lines[1] == "Hi"


def test_help_tour_rich_console_or_none_returns_none_for_non_rich_printer() -> None:
    from codeclone.surfaces.cli.ui import help_tour as help_tour_mod

    class _RichCapablePlain(PlainConsole):
        pass

    with patch.object(help_tour_mod, "supports_rich_console", return_value=True):
        assert help_tour_mod._rich_console_or_none(_RichCapablePlain()) is None


def test_typewriter_panel_reveals_partial_text_with_cursor() -> None:
    pytest.importorskip("rich")
    from codeclone.surfaces.cli.console import make_console

    panel = TypewriterPanel(
        text="hello", visible_chars=3, cursor_on=True, use_unicode=True
    )
    console = make_console(no_color=False, width=80)
    console.record = True
    with console.capture() as capture:
        console.print(panel)
    rendered = capture.get()
    assert "hel" in rendered
    assert "▌" in rendered
    panel_off = TypewriterPanel(
        text="hello", visible_chars=3, cursor_on=False, use_unicode=True
    )
    with console.capture() as capture_off:
        console.print(panel_off)
    assert "▌" not in capture_off.get()


def test_animation_frames_for_state_includes_analysis_phases() -> None:
    scanning = animation_frames_for_state(AsterState.SCANNING, use_unicode=True)
    analysis = animation_frames_for_state(AsterState.ANALYSIS, use_unicode=True)
    cache = animation_frames_for_state(AsterState.CACHE, use_unicode=True)
    control = animation_frames_for_state(AsterState.CONTROL, use_unicode=True)
    blast = animation_frames_for_state(AsterState.BLAST_RADIUS, use_unicode=True)
    assert scanning is not None and len(scanning) >= 4
    assert analysis is not None and len(analysis) >= 4
    assert cache is not None and len(cache) >= 3
    assert control is not None and "◉" in control[0][1]
    assert blast is not None and "◉" in blast[0][1]
    assert animation_frames_for_state(AsterState.IDLE, use_unicode=True) is None


def test_new_animation_kinds_are_distinct() -> None:
    control = animation_frames_for_kind(AsterAnimation.CONTROL_GATE, use_unicode=True)
    blast = animation_frames_for_kind(AsterAnimation.BLAST_RIPPLE, use_unicode=True)
    branch = animation_frames_for_kind(AsterAnimation.ANALYSIS_BRANCH, use_unicode=True)
    hub = animation_frames_for_kind(AsterAnimation.ORIGIN_HUB, use_unicode=True)
    assert control is not None and "┌" in control[0][0]
    assert blast is not None and "·" in blast[0][0]
    assert branch is not None and "╱╲" in branch[-1][-1]
    assert hub is not None and "╵" in hub[0][-1]


def test_help_tour_animated_steps_use_unique_animations() -> None:
    from codeclone.surfaces.cli.ui.help_tour import _DEFAULT_STEPS

    seen: set[AsterAnimation] = set()
    for step in _DEFAULT_STEPS:
        if not step.animate or step.animation is None:
            continue
        assert step.animation not in seen, step.animation
        seen.add(step.animation)


def test_graph_pulse_animation_has_four_frames() -> None:
    frames = graph_pulse_animation_frames(use_unicode=True)
    assert len(frames) == 4
    assert frames[0][0].strip() == "●─○─○─○"
    assert frames[3][0].strip() == "○─○─○─●"


def test_scanning_animation_matches_canonical_four_frames() -> None:
    from codeclone.surfaces.cli.ui.mascot_frames import scanning_animation_frames

    frames = scanning_animation_frames(use_unicode=True)
    assert len(frames) == 4
    assert frames[0] == ("   ●   ", "  ╱│   ", " ○     ")
    assert frames[1] == ("   ●   ", "  ╱│╲  ", " ○ ○   ")
    assert frames[2] == ("   ●   ", "  │╲   ", " ○     ")
    assert frames[3] == ("   ●   ", "  ╱│╲  ", " ○ ○ ○ ")


def test_resolve_animation_graph_pulse_four_frames() -> None:
    from codeclone.surfaces.cli.ui.mascot_frames import (
        AsterAnimation,
        AsterState,
        resolve_animation,
    )

    frames = resolve_animation(
        AsterState.SCANNING,
        animation=AsterAnimation.GRAPH_PULSE,
        animate=True,
        use_unicode=True,
    )
    assert frames is not None
    assert len(frames) == 4
    assert frames[0][0].strip() == "●─○─○─○"
    assert frames[3][0].strip() == "○─○─○─●"


def test_default_help_tour_has_comprehensive_step_count() -> None:
    from codeclone.surfaces.cli.ui.help_tour import _DEFAULT_STEPS

    assert len(_DEFAULT_STEPS) >= 14


def test_tour_stats_lines_render() -> None:
    pytest.importorskip("rich")
    from codeclone.surfaces.cli.console import make_console

    console = make_console(no_color=False, width=80)
    console.record = True
    panel = TourStatsLines(lines=("Files  741",))
    with console.capture() as capture:
        console.print(panel)
    assert "741" in capture.get()


def test_tour_step_panel_height_is_stable_with_or_without_stats() -> None:
    pytest.importorskip("rich")
    from codeclone.surfaces.cli.console import make_console

    console = make_console(no_color=False, width=80)
    console.record = True
    heights: set[int] = set()
    for stats in ((), ("Files  741", "Parsed  741")):
        panel = build_step_panel(
            body="line one\nline two",
            visible_chars=99,
            cursor_on=False,
            use_unicode=True,
            stats=stats,
        )
        with console.capture() as capture:
            console.print(panel)
        heights.add(len(capture.get().splitlines()))
    assert heights == {10}


def test_run_rich_step_advances_animation_and_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("rich")
    sleeps = _run_animated_rich_step(
        body="abc",
        tick_interval=0.01,
        frame_interval=0.01,
        char_interval=0.01,
        min_read_pause=0.02,
        cursor_blink_interval=0.01,
    )
    assert len(sleeps) >= 8


def test_run_interactive_help_tour_rich_step_uses_typewriter_ticks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("rich")
    from codeclone.surfaces.cli.console import make_query_console

    sleeps: list[float] = []
    steps = (
        HelpTourStep(
            AsterState.IDLE,
            "Short",
            "ab",
            animate=False,
        ),
    )
    console = make_query_console(no_color=False)
    monkeypatch.setattr(
        "codeclone.surfaces.cli.ui.help_tour._interactive_terminal_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "codeclone.surfaces.cli.ui.help_tour.supports_rich_console",
        lambda _c: True,
    )
    run_interactive_help_tour(
        console=console,
        steps=steps,
        sleep=lambda seconds: sleeps.append(seconds),
        tick_interval=0.01,
        char_interval=0.01,
        min_read_pause=0.05,
        cursor_blink_interval=0.02,
    )
    assert len(sleeps) > 5


def test_render_plain_tour_sleeps_when_interactive_without_rich(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.surfaces.cli.console import PlainConsole
    from codeclone.surfaces.cli.ui import help_tour as help_tour_mod

    sleeps: list[float] = []
    monkeypatch.setattr(help_tour_mod, "_interactive_terminal_available", lambda: True)

    help_tour_mod._render_plain_tour(
        (
            HelpTourStep(
                AsterState.IDLE,
                "Plain pause",
                "Body",
                animate=False,
            ),
        ),
        PlainConsole(),
        sleep=lambda seconds: sleeps.append(seconds),
        plain_step_pause=0.25,
    )

    assert sleeps == [0.25]


def test_run_rich_step_animation_frame_and_char_intervals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("rich")
    sleeps = _run_animated_rich_step(
        body="abcd",
        tick_interval=0.05,
        frame_interval=0.05,
        char_interval=0.05,
        min_read_pause=0.05,
        cursor_blink_interval=0.05,
    )
    assert len(sleeps) >= 6


def test_mascot_frames_ascii_catalog_paths() -> None:
    from codeclone.surfaces.cli.ui.mascot_frames import (
        AsterAnimation,
        AsterState,
        animation_frames_for_kind,
        animation_frames_for_state,
        graph_pulse_animation_frames,
        resolve_animation,
        scanning_animation_frames,
    )

    assert scanning_animation_frames(use_unicode=False)
    assert graph_pulse_animation_frames(use_unicode=False)
    assert animation_frames_for_kind(
        AsterAnimation.GRAPH_PULSE,
        use_unicode=False,
    )
    assert animation_frames_for_state(AsterState.SCANNING, use_unicode=False)
    assert resolve_animation(
        AsterState.SCANNING,
        animation=AsterAnimation.GRAPH_PULSE,
        animate=True,
        use_unicode=False,
    )


def test_run_interactive_help_tour_default_console_respects_no_color(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.surfaces.cli.console import PlainConsole
    from codeclone.surfaces.cli.ui import help_tour

    calls: list[bool | None] = []

    def _fake_console(*, no_color: bool | None = None) -> PlainConsole:
        calls.append(no_color)
        return PlainConsole()

    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr(help_tour, "make_query_console", _fake_console)
    monkeypatch.setattr(help_tour, "_interactive_terminal_available", lambda: False)

    rc = help_tour.run_interactive_help_tour(
        steps=(
            HelpTourStep(
                AsterState.IDLE,
                "Short",
                "Plain fallback",
                animate=False,
            ),
        ),
        sleep=lambda _seconds: None,
    )

    assert rc == 0
    assert calls == [None]


def test_mascot_animation_none_resolves_to_no_frames() -> None:
    from codeclone.surfaces.cli.ui.mascot_frames import (
        AsterAnimation,
        AsterState,
        animation_frames_for_kind,
        resolve_animation,
    )

    assert animation_frames_for_kind(AsterAnimation.NONE) is None
    assert (
        resolve_animation(
            AsterState.IDLE,
            animation=AsterAnimation.NONE,
            animate=True,
        )
        is None
    )
    assert (
        resolve_animation(
            AsterState.IDLE,
            animation=AsterAnimation.SCANNING,
            animate=True,
        )
        is not None
    )


# ---------------------------------------------------------------------------
# One owner for the product's one-line self-description
# ---------------------------------------------------------------------------
#
# ``BANNER_SUBTITLE`` declares itself "one line, on every screen, that says
# what the product does for the reader", and ``--help`` is a screen. It was
# not reading it: the help mascot carried its own literal, so when the owner
# moved -- ce5418cf, after a blind reading filed the previous wording as a
# linter -- the help screen stayed behind and the two first screens a user
# sees began naming the product differently. A second copy drifts again; the
# pins below are what make that impossible rather than merely repaired.


def test_the_help_screen_names_the_product_as_the_run_banner_does() -> None:
    """The two first screens carry one self-description, not two."""

    help_text = "\n".join(static_help_mascot_lines(use_unicode=True))
    banner = ui_messages.strip_markup(ui_messages.banner_title("9.9.9"))

    assert ui_messages.BANNER_SUBTITLE in banner
    assert ui_messages.BANNER_SUBTITLE in help_text


def test_the_help_screen_reads_the_subtitle_rather_than_repeating_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Derivation, not coincidence: move the owner and the help line moves.

    Two literals that happen to agree today satisfy the pin above and drift
    tomorrow, which is exactly what happened. Reverting the help line to a
    literal turns this red while the agreement test stays green.
    """

    monkeypatch.setattr(ui_messages, "BANNER_SUBTITLE", "a wholly different claim")

    help_text = "\n".join(static_help_mascot_lines(use_unicode=True))

    assert "a wholly different claim" in help_text


# ===========================================================================
# The ``--help`` surface: leaving the tour, and the shape of the screen
# ===========================================================================
#
# Every pin below was shown red under a targeted mutation of the behaviour it
# holds; a pin that cannot be turned red by breaking its subject is not a pin.
# The interrupt pins are taken at five different points -- the tour module's
# import, the frame before the Live starts, a sleep inside a step, the gap
# between two steps, and the plain fallback -- because a guard around the
# sleep alone passes a test that only ever interrupts the sleep. That is not
# hypothetical: the "guard_covers_only_the_sleep" mutation leaves the other
# four green and reds only the import pin.

_TOUR_MODULE = "codeclone.surfaces.cli.ui.help_tour"
_TWO_STEPS: tuple[HelpTourStep, ...] = (
    HelpTourStep(AsterState.IDLE, "First", "ab", animate=False),
    HelpTourStep(AsterState.IDLE, "Second", "cd", animate=False),
)


# ---------------------------------------------------------------------------
# Leaving the tour
# ---------------------------------------------------------------------------
#
# ``codeclone --help --interactive-help`` then Ctrl+C printed the interpreter's
# own stack over the last animation frame: five files of CodeClone internals
# handed to somebody who had asked for help. Nothing caught it -- and nothing
# could have by accident, because ``KeyboardInterrupt`` is a ``BaseException``
# and ``surfaces.cli.workflow.main`` guards ``Exception``.


def _interrupt_run(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tour: Callable[[], int],
) -> None:
    monkeypatch.setattr(help_tour_mod, "run_interactive_help_tour", tour)


def _rich_tour(
    monkeypatch: pytest.MonkeyPatch,
    *,
    sleep: Callable[[float], None],
    steps: Sequence[HelpTourStep] = _TWO_STEPS,
) -> Callable[[], int]:
    """The real tour, on the real rich path, with a sleep we control."""

    monkeypatch.setattr(help_tour_mod, "_interactive_terminal_available", lambda: True)
    monkeypatch.setattr(help_tour_mod, "supports_rich_console", lambda _c: True)
    console = make_query_console(no_color=False)

    def _run() -> int:
        return run_interactive_help_tour(
            console=console,
            steps=steps,
            sleep=sleep,
            tick_interval=0.01,
            char_interval=0.01,
            min_read_pause=0.02,
            cursor_blink_interval=0.01,
        )

    return _run


def _assert_left_cleanly(
    excinfo: pytest.ExceptionInfo[SystemExit],
    captured: str,
) -> None:
    assert excinfo.value.code == int(ExitCode.SUCCESS)
    assert ui_messages.help.HELP_TOUR_INTERRUPTED in captured
    assert "Traceback" not in captured
    assert "KeyboardInterrupt" not in captured


def test_interrupting_a_sleep_inside_a_step_leaves_no_stack(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The measured point: ``sleep(tick_interval)`` inside ``_run_rich_step``."""

    ticks: list[float] = []

    def _sleep(seconds: float) -> None:
        ticks.append(seconds)
        if len(ticks) == 2:
            raise KeyboardInterrupt

    _interrupt_run(monkeypatch, tour=_rich_tour(monkeypatch, sleep=_sleep))
    with pytest.raises(SystemExit) as exc:
        build_parser("9.9.9").parse_args(["--help", "--interactive-help"])

    # Probe validity: the interrupt has to have come from inside a step, not
    # from a tour that never started.
    assert len(ticks) == 2
    _assert_left_cleanly(exc, capsys.readouterr().out)


def test_interrupting_before_the_first_frame_leaves_no_stack(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Ctrl+C after the console exists and before the Live is entered."""

    frames: list[object] = []

    def _show_frame(*args: object, **kwargs: object) -> None:
        frames.append(args)
        raise KeyboardInterrupt

    monkeypatch.setattr(help_tour_mod, "_show_frame", _show_frame)
    _interrupt_run(
        monkeypatch,
        tour=_rich_tour(monkeypatch, sleep=lambda _s: None),
    )
    with pytest.raises(SystemExit) as exc:
        build_parser("9.9.9").parse_args(["--help", "--interactive-help"])

    assert len(frames) == 1, "the interrupt must land on the pre-Live frame"
    _assert_left_cleanly(exc, capsys.readouterr().out)


def test_interrupting_between_two_steps_leaves_no_stack(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Ctrl+C in the gap: step one finished, step two has not begun."""

    started: list[str] = []
    real_step = help_tour_mod._run_rich_step

    def _step(presenter: Any, step: HelpTourStep, **kwargs: Any) -> None:
        started.append(step.title)
        if len(started) == 2:
            raise KeyboardInterrupt
        real_step(presenter, step, **kwargs)

    monkeypatch.setattr(help_tour_mod, "_run_rich_step", _step)
    _interrupt_run(
        monkeypatch,
        tour=_rich_tour(monkeypatch, sleep=lambda _s: None),
    )
    with pytest.raises(SystemExit) as exc:
        build_parser("9.9.9").parse_args(["--help", "--interactive-help"])

    assert started == ["First", "Second"]
    _assert_left_cleanly(exc, capsys.readouterr().out)


def test_interrupting_the_plain_tour_leaves_no_stack(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The fallback path sleeps between steps too, and is not a second case."""

    monkeypatch.setattr(help_tour_mod, "_interactive_terminal_available", lambda: True)

    def _raise(_seconds: float) -> None:
        raise KeyboardInterrupt

    _interrupt_run(
        monkeypatch,
        tour=lambda: run_interactive_help_tour(
            console=PlainConsole(),
            steps=_TWO_STEPS,
            sleep=_raise,
            plain_step_pause=0.01,
        ),
    )
    with pytest.raises(SystemExit) as exc:
        build_parser("9.9.9").parse_args(["--help", "--interactive-help"])

    _assert_left_cleanly(exc, capsys.readouterr().out)


class _InterruptingFinder(importlib.abc.MetaPathFinder):
    """Turns importing one named module into a Ctrl+C."""

    def __init__(self, name: str) -> None:
        self.name = name

    def find_spec(
        self,
        fullname: str,
        path: object = None,
        target: object = None,
    ) -> importlib.machinery.ModuleSpec | None:
        if fullname == self.name:
            raise KeyboardInterrupt
        return None


def test_interrupting_while_the_tour_module_loads_leaves_no_stack(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The earliest point of all, and the reason the guard is not in the tour.

    ``help_tour`` imports rich, its animation catalogue and the presenter. A
    guard living inside ``run_interactive_help_tour`` cannot cover its own
    module's import; this one can, and this is what proves it.
    """

    monkeypatch.delitem(sys.modules, _TOUR_MODULE, raising=False)
    monkeypatch.setattr(
        sys, "meta_path", [_InterruptingFinder(_TOUR_MODULE), *sys.meta_path]
    )

    with pytest.raises(SystemExit) as exc:
        build_parser("9.9.9").parse_args(["--help", "--interactive-help"])

    _assert_left_cleanly(exc, capsys.readouterr().out)


def test_a_completed_tour_still_exits_with_its_own_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard must not swallow the return value of a tour that finished.

    Without this, an ``except KeyboardInterrupt`` that returned SUCCESS
    unconditionally -- or a guard that returned SUCCESS from the ``try`` --
    would look identical to a correct one.
    """

    _interrupt_run(monkeypatch, tour=lambda: 7)
    with pytest.raises(SystemExit) as exc:
        build_parser("9.9.9").parse_args(["--help", "--interactive-help"])
    assert exc.value.code == 7


# ---------------------------------------------------------------------------
# The shape of the screen
# ---------------------------------------------------------------------------

# argparse's own cap, read rather than restated: a literal 24 here would
# move the magic number into the test instead of pinning what sets it.
_HELP_POSITION = (
    inspect.signature(argparse.HelpFormatter).parameters["max_help_position"].default
)
_LONG_OPTION = re.compile(r"(--[a-z0-9][a-z0-9-]*)")


def _help_text() -> str:
    import io

    buffer = io.StringIO()
    build_parser("9.9.9").print_help(file=buffer)
    return buffer.getvalue()


def test_no_help_line_leaves_the_cli_layout_grid() -> None:
    """The screen fits the width the rest of the CLI is already held to.

    ``CLI_LAYOUT_MAX_WIDTH`` is read, not restated: raise or lower the owner
    and this pin follows it, which a literal 80 here would not. Before this,
    55 lines ran past it and the widest was 213 columns, so at a default
    terminal the two-column grid folded back to column zero on every one.
    """

    over = [
        (number, len(line))
        for number, line in enumerate(_help_text().splitlines(), start=1)
        if len(line) > ui_messages.CLI_LAYOUT_MAX_WIDTH
    ]
    assert not over, over


def _option_section_lines() -> list[str]:
    """The argument groups only.

    The mascot banner above the usage line and the epilog below the last group
    are free-form blocks that own their own indentation; the grid claim is
    about the two-column option rows between them.
    """

    text = _help_text()
    epilog = cli_help_epilog()
    assert epilog in text, "the epilog moved; this split is no longer valid"
    lines = text.split(epilog)[0].splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("usage:"))
    body = lines[start + 1 :]
    assert any(line.startswith("  --") for line in body), "empty option population"
    return body


def test_flag_help_hangs_from_one_column() -> None:
    """Every wrapped flag body lands on the same column, and only that one."""

    columns: set[int] = set()
    continuations: set[int] = set()
    for line in _option_section_lines():
        if not line.startswith("  ") or not line.strip():
            continue
        if re.match(r"^ {2}(-|[a-z])", line):
            split = re.split(r" {2,}", line[2:], maxsplit=1)
            if len(split) == 2 and split[1]:
                columns.add(len(line) - len(split[1]))
        else:
            continuations.add(len(line) - len(line.lstrip(" ")))
    assert columns == {_HELP_POSITION}, sorted(columns)
    assert continuations == {_HELP_POSITION}, sorted(continuations)


def test_the_usage_line_is_one_line() -> None:
    """argparse's generated grammar spelled all 64 flags across 40 lines.

    It was the largest block on the screen and a strict subset of the option
    sections below it. ``parser.error`` prints the usage as well, so this also
    stops a contract error burying its own message.
    """

    lines = _help_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("usage:"))
    assert lines[start + 1] == "", lines[start : start + 3]


# The flag inventory is NOT re-pinned here. Sourcing the population from
# ``parser._actions`` compares the parser with itself: dropping an argument
# group removes the actions and the printed rows together, and the
# "option_group_dropped" mutation SURVIVED against it. Sourcing it from
# ``config.spec`` instead would cross the r4->r2 architecture ratchet for this
# module. The claim is held by the committed help golden, which reds on that
# same mutation -- measured, not assumed.


def test_no_tour_step_loses_words_on_a_narrow_terminal() -> None:
    """The panel is six rows tall; a body that needs seven is silently cut.

    Step bodies used to carry hard newlines wrapped for a wide screen, so at a
    72-column terminal rich honoured the breaks, ran out of the fixed panel
    height and dropped the tail: 15 words at 72 columns, 24 at 60, never shown
    and never reported. A body with no hard breaks is filled to whatever width
    the reader has, which is the narrowest shape that fits.

    Probe validity: the control below is measured, not assumed -- a body the
    panel certainly cannot hold must come back short, or a zero here means the
    probe is blind rather than the tour intact.
    """

    from codeclone.surfaces.cli.console import make_console
    from codeclone.surfaces.cli.ui.help_tour import _DEFAULT_STEPS

    def _words_lost(body: str, width: int) -> int:
        console = make_console(no_color=True, width=width)
        console.record = True
        panel = build_step_panel(
            body=body,
            visible_chars=len(body),
            cursor_on=True,
            use_unicode=True,
            stats=(),
        )
        with console.capture() as capture:
            console.print(panel)
        inner = [
            line[1:-1]
            for line in capture.get().splitlines()
            if not set(line) <= set("\u256d\u256e\u2570\u256f\u2500\u2502 ")
        ]
        shown = " ".join(" ".join(inner).split()).replace("\u258c", "")
        return len(" ".join(body.split()).split()) - len(shown.split())

    assert _words_lost(" ".join(["word"] * 120), 72) > 0, (
        "the probe cannot see cropping"
    )

    cropped = {
        step.title: _words_lost(step.body, width)
        for step in _DEFAULT_STEPS
        for width in (72, 60)
        if _words_lost(step.body, width)
    }
    assert not cropped, cropped


def test_the_banner_names_the_product_once() -> None:
    """One self-description per screen -- the rule ``35ebec25`` established.

    The banner line used to print the idle frame's own message beside the
    product identity, so it read "Deterministic structural change control.
    CodeClone . structural change control for Python": the same claim twice,
    two spaces apart, on the first line a user ever sees.
    """

    banner = "\n".join(static_help_mascot_lines(use_unicode=False))
    idle_message = frame_for_state(AsterState.IDLE, use_unicode=False).message

    assert banner.count(ui_messages.BANNER_SUBTITLE) == 1
    assert idle_message is not None
    assert idle_message not in banner


# ===========================================================================
# What the tour costs, and whether the help row says so
# ===========================================================================
#
# ``--interactive-help`` reads no key: the tour's only use of stdin is
# ``isatty``. It is a timed animation -- fifteen steps typed out and held
# for a reading pause -- and Ctrl+C is the one control a reader has. The
# help row used to call it "the guided CodeClone product tour", a name that
# promised a hand on the wheel; it now states the measured cost and the one
# way out. The figures in that row are re-derived below from the tour's own
# loop and constants, never trusted as literals: change a pause, add a step,
# and the row is wrong until the text moves with it.
#
# The cost itself had a defect. ``_CHAR_INTERVAL`` is 0.022 s and the tick
# is 0.05 s, and the loop advanced at most one character per tick, so the
# constant could not take effect for any value at or below the tick: the
# typewriter ran at 20 characters a second while the constant said 45, and
# the tour's 3,400 characters cost 170 s of typing instead of 75. Both
# directions of that error are pinned separately -- a loop that types
# slower than its interval and one that dumps the body in a tick are
# opposite mistakes, and one inequality cannot see both.


def _ticks_to_type(
    monkeypatch: pytest.MonkeyPatch,
    *,
    body: str,
    tick_interval: float,
    char_interval: float,
) -> int:
    """Ticks ``_run_rich_step`` spends before the whole body is on screen."""

    from rich.console import Console

    frames: list[int] = []
    real_panel = build_step_panel

    def _recording(**kwargs: Any) -> Any:
        frames.append(int(kwargs["visible_chars"]))
        return real_panel(**kwargs)

    monkeypatch.setattr(help_tour_mod, "build_step_panel", _recording)
    presenter = ProgressPresenter(cast(Console, make_query_console(no_color=False)))
    help_tour_mod._run_rich_step(
        presenter,
        HelpTourStep(AsterState.IDLE, "Typed", body, animate=False),
        use_unicode=True,
        sleep=lambda _seconds: None,
        tick_interval=tick_interval,
        frame_interval=tick_interval,
        char_interval=char_interval,
        min_read_pause=0.0,
        cursor_blink_interval=1.0,
    )
    return frames.index(len(body))


_TYPING_BODY = "x" * 100
_TYPING_TICK = 0.05
_TYPING_CHAR = 0.022
_TYPING_EXPECTED_TICKS = len(_TYPING_BODY) * _TYPING_CHAR / _TYPING_TICK


def test_the_typewriter_is_no_slower_than_its_character_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One character per tick is the measured defect; the interval must win."""

    pytest.importorskip("rich")
    ticks = _ticks_to_type(
        monkeypatch,
        body=_TYPING_BODY,
        tick_interval=_TYPING_TICK,
        char_interval=_TYPING_CHAR,
    )
    assert ticks <= _TYPING_EXPECTED_TICKS + 1, ticks


def test_the_typewriter_is_no_faster_than_its_character_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The opposite error: a body dumped in a tick is not a typewriter."""

    pytest.importorskip("rich")
    ticks = _ticks_to_type(
        monkeypatch,
        body=_TYPING_BODY,
        tick_interval=_TYPING_TICK,
        char_interval=_TYPING_CHAR,
    )
    assert ticks >= _TYPING_EXPECTED_TICKS - 1, ticks


def _simulated_tour_seconds() -> float:
    """The default tour's forced watching time, from its own loop and constants.

    Every ``sleep`` the rich path would make is summed instead of slept; the
    frames are not rendered because they cost no reader time.
    """

    from rich.console import Console

    seconds = 0.0

    def _sleep(interval: float) -> None:
        nonlocal seconds
        seconds += interval

    presenter = ProgressPresenter(cast(Console, make_query_console(no_color=False)))
    for step in help_tour_mod._DEFAULT_STEPS:
        help_tour_mod._run_rich_step(
            presenter,
            step,
            use_unicode=True,
            sleep=_sleep,
            tick_interval=help_tour_mod._TICK_INTERVAL,
            frame_interval=help_tour_mod._FRAME_INTERVAL,
            char_interval=help_tour_mod._CHAR_INTERVAL,
            min_read_pause=help_tour_mod._MIN_READ_PAUSE,
            cursor_blink_interval=help_tour_mod._CURSOR_BLINK_INTERVAL,
        )
    return seconds


def test_the_help_row_states_the_tours_measured_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Minutes to the nearest half, and the step count, both re-derived."""

    pytest.importorskip("rich")
    monkeypatch.setattr(help_tour_mod, "_show_frame", lambda *_a, **_k: None)

    minutes = round(_simulated_tour_seconds() / 30) / 2
    steps = len(help_tour_mod._DEFAULT_STEPS)

    assert f"about {minutes:g} minutes" in ui_messages.HELP_INTERACTIVE
    assert f"({steps} timed steps)" in ui_messages.HELP_INTERACTIVE


def test_the_help_row_names_the_one_control_the_tour_has() -> None:
    """Ctrl+C is the only input the tour honours, so the row names it."""

    assert "Ctrl+C" in ui_messages.HELP_INTERACTIVE
    assert "guided" not in ui_messages.HELP_INTERACTIVE
