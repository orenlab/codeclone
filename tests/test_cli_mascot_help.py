# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
# ruff: noqa: RUF001

from __future__ import annotations

import io
import sys

import pytest

from codeclone.config.argparse_builder import build_parser
from codeclone.contracts import ExitCode
from codeclone.surfaces.cli import workflow as cli_workflow
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
    graph_pulse_animation_frames,
)
from codeclone.surfaces.cli.ui.progress_presenter import ProgressPresenter
from codeclone.surfaces.cli.ui.tour_panel import TourStatsLines, build_step_panel
from codeclone.surfaces.cli.ui.typewriter import TypewriterPanel


def test_static_help_mascot_lines_include_product_tagline() -> None:
    lines = static_help_mascot_lines(use_unicode=True)
    assert any("●" in line for line in lines)
    assert any("Structural Change Controller" in line for line in lines)
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
    assert "Structural Change Controller" in text
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
    assert "Structural Change Controller" in out
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
