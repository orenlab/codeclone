# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Memory statements never drive the reviewer's terminal or Rich markup.

A statement reaches ``codeclone memory`` screens from two authors: an agent
through ``record_candidate``, and the repository itself through the records
ingestion builds from file names (``module_role``). The review screens are
where a human decides what to approve, so a statement that hides part of
itself (``[conceal]``), links somewhere (``[link=...]``, OSC 8) or rewrites
the line above it would decide that for them. Each test renders such a
statement through one screen and reads what the terminal receives.
"""

from __future__ import annotations

from dataclasses import replace
from io import StringIO
from typing import Any

import pytest
from rich.theme import Theme

from codeclone.surfaces.cli.console import PlainConsole, grid_console_class
from codeclone.surfaces.cli.memory_render import (
    render_draft_candidates,
    render_governance_result,
    render_search_results,
    render_stale_records,
)
from codeclone.ui_messages.styling import RICH_THEME_STYLES
from codeclone.utils.display_text import display_text

from .memory_fixtures import make_module_record

_ESC = "\x1b"
_HOSTILE_STATEMENTS = (
    "## Evidence note\nSee [link=pwn:rich]the evidence PWNLINK[/link] here.",
    "## Evidence note\nShown [conceal]PWNHIDDEN[/conceal] after.",
    "## Evidence note\nStatus [bold white on green]PWNSTATUS approved[/] ok.",
    f"## Evidence note\nRow one{_ESC}[2K{_ESC}[1A PWNCSI-overwrite",
    f"## Evidence note\nOpen {_ESC}]8;;pwn:osc8{_ESC}\\PWNOSC8{_ESC}]8;;{_ESC}\\ now.",
    "## Evidence note\nStatus [bold red]PWNRED[/bold red] and [dim]PWNDIM[/dim].",
)
_INJECTED = ("\x1b]8;", "\x1b[8m", "\x1b[2K", "\x1b[1A")


def _colour_console() -> tuple[Any, StringIO]:
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


def _record(statement: str) -> Any:
    return replace(make_module_record("proj-1", "pkg.alpha"), statement=statement)


def _shown_lines(statement: str) -> list[str]:
    """The statement's lines as the screen must show them, controls visible."""
    return display_text(statement, multiline=True).splitlines()


def _assert_shown_inert(output: str, statement: str) -> None:
    assert not [marker for marker in _INJECTED if marker in output]
    for line in _shown_lines(statement):
        assert line in output, line


@pytest.mark.parametrize("statement", _HOSTILE_STATEMENTS)
def test_search_table_shows_a_hostile_statement_as_text(statement: str) -> None:
    console, buffer = _colour_console()
    render_search_results(
        console=console,
        query="q",
        records=[{"type": "risk_note", "status": "draft", "statement": statement}],
    )

    _assert_shown_inert(buffer.getvalue(), statement)


@pytest.mark.parametrize("statement", _HOSTILE_STATEMENTS)
def test_review_candidates_table_shows_a_hostile_statement_as_text(
    statement: str,
) -> None:
    console, buffer = _colour_console()
    render_draft_candidates(console=console, records=[_record(statement)])

    _assert_shown_inert(buffer.getvalue(), statement)


@pytest.mark.parametrize("statement", _HOSTILE_STATEMENTS)
def test_stale_table_shows_a_hostile_statement_as_text(statement: str) -> None:
    console, buffer = _colour_console()
    render_stale_records(
        console=console,
        records=[{"type": "risk_note", "stale_reason": "r", "statement": statement}],
    )

    _assert_shown_inert(buffer.getvalue(), statement)


def test_governance_result_shows_a_hostile_detail_as_text() -> None:
    console, buffer = _colour_console()
    render_governance_result(
        console=console,
        action="approved",
        record_id="mem-1",
        detail=_HOSTILE_STATEMENTS[4],
    )

    _assert_shown_inert(buffer.getvalue(), _HOSTILE_STATEMENTS[4])


@pytest.mark.parametrize("statement", _HOSTILE_STATEMENTS)
def test_plain_memory_lines_keep_every_bracket_of_a_statement(
    statement: str, capsys: pytest.CaptureFixture[str]
) -> None:
    console = PlainConsole()
    render_search_results(
        console=console,
        query="q",
        records=[{"type": "risk_note", "status": "draft", "statement": statement}],
    )
    render_draft_candidates(console=console, records=[_record(statement)])
    render_stale_records(
        console=console,
        records=[{"type": "risk_note", "stale_reason": "r", "statement": statement}],
    )
    output = capsys.readouterr().out

    for line in _shown_lines(statement)[1:]:
        assert output.count(line) == 3, line


def test_memory_tables_keep_a_benign_statement() -> None:
    statement = "## Plain note\nUse `pkg.alpha:fn` for x[0] and y."
    console, buffer = _colour_console()
    render_search_results(
        console=console,
        query="q",
        records=[{"type": "risk_note", "status": "draft", "statement": statement}],
    )
    render_draft_candidates(console=console, records=[_record(statement)])

    output = buffer.getvalue()
    assert output.count("Use `pkg.alpha:fn` for x[0] and y.") == 2
