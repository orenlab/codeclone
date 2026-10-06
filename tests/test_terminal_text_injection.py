# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Repository text never drives the reader's terminal or Rich markup.

A file name, a directory name or a pyproject key reaches the terminal through
three writers: Rich markup with the value escaped (``esc``), plain strings
printed with ``markup=False``, and Rich renderables (the banner rule). Each
test here feeds such text to one writer and looks at what the terminal
receives: a raw escape sequence (cursor moves, line erase, OSC 8 link, window
title), a Rich tag the value opened, a line the value forged. Every hostile
value carries ``pwn``/``PWN``; benign twins pin the bytes an ordinary value
keeps.

Rich 15.0.0 strips only BEL, BS, VT, FF and CR when it builds a ``Text``; ESC,
NUL, DEL and C1 reach every console it drives, coloured or not, which is why
the control filter cannot be left to Rich.
"""

from __future__ import annotations

from argparse import Namespace
from contextlib import AbstractContextManager, nullcontext
from io import StringIO
from typing import Any, cast

import pytest
from rich.console import Console
from rich.text import Text
from rich.theme import Theme

import codeclone.surfaces.cli.state as cli_state
from codeclone.contracts.errors import DiagnosedUserError
from codeclone.surfaces.cli.console import (
    PlainConsole,
    _print_gating_failure_block,
    _render_banner,
    grid_console_class,
    make_console,
)
from codeclone.surfaces.cli.execution import enforce_gating
from codeclone.surfaces.cli.runtime import print_failed_files
from codeclone.ui_messages import fmt_diagnosed_user_error
from codeclone.ui_messages.styling import RICH_THEME_STYLES, esc, strip_markup
from codeclone.utils.display_text import display_text, rich_text

_ESC = "\x1b"
_HOSTILE_RICH = (
    "x\\[link=pwn:bs]PWNBS",
    "[link=pwn:rich]PWNLINK[/link]",
    "[conceal]PWNHIDE[/conceal]",
    "[bold red]PWNBOLD",
    "[/]",
    "a\\",
    "a\\\\",
    "a\\\\\\",
    "x\\\\[bold]y",
    "p\\q",
    "[Errno 2] kept",
)
_HOSTILE_CONTROL = f"bad{_ESC}[2K{_ESC}[1APWNCSI{_ESC}]8;;pwn:osc8{_ESC}\\PWNOSC8"
_HOSTILE_NEWLINE = "k\n  ✔ PWNFORGED all gates passed"
_INJECTED = ("\x1b]8;", "\x1b[2K", "\x1b[1A", "\x1b[8m", "\x1b]0;")


class _Recorder:
    """A status console that keeps exactly the text each writer handed it."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def print(self, *objects: object, **kwargs: object) -> None:
        self.calls.append((" ".join(str(item) for item in objects), kwargs))

    @staticmethod
    def status(*_: object, **__: object) -> AbstractContextManager[None]:
        return nullcontext()

    @property
    def text(self) -> str:
        return "\n".join(text for text, _ in self.calls)


def _colour_console() -> tuple[Any, StringIO]:
    """The CLI's own console class on a colour terminal, as a user sees it."""
    buffer = StringIO()
    console = grid_console_class()(
        theme=Theme(RICH_THEME_STYLES),
        file=buffer,
        force_terminal=True,
        color_system="truecolor",
        width=200,
        highlight=False,
    )
    return console, buffer


def _plain_rich_console() -> tuple[Any, StringIO]:
    buffer = StringIO()
    console = make_console(no_color=True, width=200)
    console.file = buffer
    return console, buffer


# --- E-03: esc is the owner's Rich escaping ---------------------------------


@pytest.mark.parametrize("value", (*_HOSTILE_RICH, _HOSTILE_CONTROL, "pkg/alpha.py"))
def test_esc_is_the_owners_rich_text(value: str) -> None:
    assert esc(value) == rich_text(value)


def test_esc_keeps_a_backslashed_bracket_literal_text() -> None:
    value = "x\\[link=pwn:bs]PWNBS"
    text = Text.from_markup(f"[bold]{esc(value)}[/bold]")

    assert text.plain == "x\\[link=pwn:bs]PWNBS"
    assert [str(span.style) for span in text.spans] == ["bold"]


def test_esc_replaces_control_characters_and_line_breaks() -> None:
    shown = Text.from_markup(f"[dim]{esc(_HOSTILE_CONTROL + _HOSTILE_NEWLINE)}[/dim]")

    assert _ESC not in shown.plain
    assert "\n" not in shown.plain
    assert shown.plain == display_text(_HOSTILE_CONTROL + _HOSTILE_NEWLINE)


# --- E-03: strip_markup is the exact inverse of Rich's markup ----------------

_TEMPLATES = (
    "[bold]{}[/bold]",
    "{}[dim]tail[/dim]",
    "  [warning]⚠ {}[/warning]",
    "pre {} post",
    "end {}",
)


@pytest.mark.parametrize("value", _HOSTILE_RICH)
@pytest.mark.parametrize("template", _TEMPLATES)
def test_strip_markup_shows_what_rich_shows(value: str, template: str) -> None:
    markup = template.format(esc(value))

    assert strip_markup(markup) == Text.from_markup(markup).plain


def test_strip_markup_keeps_payload_brackets_and_removes_only_style_tags() -> None:
    markup = "[bold]x[/bold] [Errno 2] [unknown] \\[dim] [/dim]"

    assert strip_markup(markup) == "x [Errno 2] [unknown] [dim] "


# --- E-03: the banner title is text, never markup ---------------------------


@pytest.mark.parametrize(
    "name",
    [
        "[link=pwn:root]PWNROOT",
        "x\\[link=pwn:bsroot]PWNBSROOT",
        f"{_ESC}]8;;pwn:dir\x07PWNDIR{_ESC}]8;;\x07",
    ],
)
def test_banner_shows_a_hostile_directory_name_as_text(name: str) -> None:
    console, buffer = _colour_console()
    _render_banner(console=console, banner_title="T", project_name=name)
    output = buffer.getvalue()

    assert not [marker for marker in _INJECTED if marker in output]
    assert display_text(name) in output


def test_banner_keeps_a_benign_directory_name() -> None:
    console, buffer = _plain_rich_console()
    _render_banner(console=console, banner_title="T", project_name="plainroot")

    assert " plainroot " in buffer.getvalue()


# --- E-02: every console filters control characters it prints ---------------


def test_rich_console_prints_raw_controls_as_visible_pictures() -> None:
    console, buffer = _plain_rich_console()
    console.print(f"  • {_HOSTILE_CONTROL}", markup=False)
    console.print(f"  [dim]{_HOSTILE_CONTROL}[/dim]")
    output = buffer.getvalue()

    assert _ESC not in output
    assert output.count(display_text(_HOSTILE_CONTROL)) == 2


def test_plain_console_prints_raw_controls_as_visible_pictures(
    capsys: pytest.CaptureFixture[str],
) -> None:
    PlainConsole().print(f"  • {_HOSTILE_CONTROL}\r", markup=False)
    PlainConsole().print(f"  [dim]{_HOSTILE_CONTROL}[/dim]")
    output = capsys.readouterr().out

    assert _ESC not in output
    assert "\r" not in output
    assert output.count(display_text(_HOSTILE_CONTROL)) == 2


def test_consoles_keep_their_own_line_breaks(
    capsys: pytest.CaptureFixture[str],
) -> None:
    console, buffer = _plain_rich_console()
    console.print("a\n  b")
    PlainConsole().print("a\n  b\tc")

    assert buffer.getvalue() == "a\n  b\n"
    assert capsys.readouterr().out == "a\n  b\tc\n"


# --- E-02: the named writers show one value on one line ----------------------


def test_failed_files_list_shows_each_name_on_its_own_line() -> None:
    recorder = _Recorder()
    print_failed_files(
        failed_files=(f"{_HOSTILE_CONTROL}.py: bad", f"{_HOSTILE_NEWLINE}.py: bad"),
        console=recorder,
    )
    items = [text for text, _ in recorder.calls[1:]]

    assert items == [
        f"    • {display_text(_HOSTILE_CONTROL)}.py: bad",
        f"    • {display_text(_HOSTILE_NEWLINE)}.py: bad",
    ]


def test_failed_files_list_keeps_a_benign_name() -> None:
    recorder = _Recorder()
    print_failed_files(failed_files=("pkg/mod.py: bad",), console=recorder)

    assert recorder.calls[1][0] == "    • pkg/mod.py: bad"


def test_unreadable_source_list_shows_each_name_on_its_own_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _Recorder()
    monkeypatch.setattr(cli_state, "console", recorder)

    with pytest.raises(SystemExit):
        enforce_gating(
            args=Namespace(ci=False),
            analysis=cast(Any, None),
            processing=cast(
                Any,
                Namespace(
                    source_read_failures=[
                        f"{_HOSTILE_CONTROL}.py: unreadable",
                        f"{_HOSTILE_NEWLINE}.py: unreadable",
                        "pkg/mod.py: unreadable",
                    ]
                ),
            ),
            source_read_contract_failure=True,
            baseline_failure_code=None,
            metrics_baseline_failure_code=None,
            new_func=set(),
            new_block=set(),
            gate_result=cast(Any, None),
            html_report_path=None,
            parse_metric_reason_entry_fn=lambda reason: (reason, ""),
            print_gating_failure_block_fn=lambda **_: None,
            print_verbose_clone_hashes_fn=lambda *_, **__: None,
        )
    items = [text for text, kwargs in recorder.calls if kwargs.get("markup") is False]

    assert items == [
        f"    • {display_text(_HOSTILE_CONTROL)}.py: unreadable",
        f"    • {display_text(_HOSTILE_NEWLINE)}.py: unreadable",
        "    • pkg/mod.py: unreadable",
    ]


def test_gating_failure_values_show_one_value_on_one_line() -> None:
    recorder = _Recorder()
    _print_gating_failure_block(
        console=recorder,
        code="metrics",
        entries=[("dead_code_items", _HOSTILE_CONTROL + _HOSTILE_NEWLINE), ("x", 36)],
        args=cast(Any, Namespace(ci=True)),
    )
    rows = [text for text, _ in recorder.calls[2:]]

    assert rows[1].endswith(f"  {display_text(_HOSTILE_CONTROL + _HOSTILE_NEWLINE)}")
    assert rows[2].endswith("  36")


# --- E-02/E-03: the CONTRACT ERROR echo of a pyproject key -------------------


@pytest.mark.parametrize(
    "key",
    [_HOSTILE_CONTROL, _HOSTILE_NEWLINE, "x\\[link=pwn:bs]PWNBS", "[link=pwn:k]K"],
)
def test_contract_error_echoes_a_hostile_key_as_one_inert_line(key: str) -> None:
    error = DiagnosedUserError(f"Unknown key(s) in tool.codeclone: {key}")
    rendered = fmt_diagnosed_user_error(error)
    console, buffer = _colour_console()
    console.print(rendered)
    output = buffer.getvalue()
    plain = strip_markup(rendered)

    assert not [marker for marker in _INJECTED if marker in output]
    expected = f"Unknown key(s) in tool.codeclone: {display_text(key)}"
    assert expected in output
    # The key stays on the line it was echoed on: nothing it carries starts
    # a line of its own under the error.
    assert [line for line in plain.splitlines() if "pwn" in line.lower()] == [
        f"    {expected}"
    ]


def test_contract_error_keeps_a_benign_key() -> None:
    rendered = fmt_diagnosed_user_error(
        DiagnosedUserError("Unknown key(s) in tool.codeclone: badkey")
    )

    assert "    Unknown key(s) in tool.codeclone: badkey" in strip_markup(rendered)


def test_plain_console_and_rich_console_print_the_same_contract_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rendered = fmt_diagnosed_user_error(
        DiagnosedUserError("Unknown key(s) in tool.codeclone: x\\[link=pwn:bs]PWNBS")
    )
    console, buffer = _plain_rich_console()
    console.print(rendered)
    PlainConsole().print(rendered)

    assert capsys.readouterr().out == buffer.getvalue()


def test_rich_console_object_is_the_real_rich_console() -> None:
    # The colour helpers above reach into a real Rich console; this pins that
    # the console under test is Rich's, so a refactor cannot hollow them out.
    console, _ = _colour_console()

    assert isinstance(console, Console)
    assert console.is_terminal
