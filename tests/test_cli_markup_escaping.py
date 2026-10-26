# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A path or an error text is data, never Rich markup.

Ten message builders interpolated a path or an exception text into a markup
template without ``esc()``. A well-formed tag inside the value was silently
eaten (``boom[bold]x`` printed as ``boomx``), and a stray closing tag made
Rich raise ``MarkupError`` while printing the message -- so a bracket in a
report file name turned a usage error into exit 5, and a bracket in a
``--root`` turned ``codeclone memory`` into a raw traceback.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path

import pytest

from codeclone import ui_messages as ui
from codeclone.surfaces.cli.console import make_console
from tests._cli_child import run_codeclone

_SWALLOWED = "boom[bold]x"
_CRASHING = "boom[/x]y"

_BUILDERS: dict[str, Callable[[str], str]] = {
    "invalid_output_extension": lambda value: ui.fmt_invalid_output_extension(
        label="HTML", path=Path(value), expected_suffix=".html"
    ),
    "html_report_open_failed": lambda value: ui.fmt_html_report_open_failed(
        path=Path(value), error=value
    ),
    "coverage_join_ignored": ui.fmt_coverage_join_ignored,
    "worker_failed": ui.fmt_worker_failed,
    "execution_unavailable": lambda value: ui.fmt_execution_unavailable(
        value, steps=(value,)
    ),
    "batch_item_failed": ui.fmt_batch_item_failed,
    "cache_save_failed": ui.fmt_cache_save_failed,
    "invalid_cache_path": lambda value: ui.fmt_invalid_cache_path(
        path=value, error=value
    ),
    "memory_db_not_found": lambda value: ui.fmt_memory_db_not_found(error=value),
    "memory_root_not_found": lambda value: ui.fmt_memory_root_not_found(path=value),
}


def _rendered(markup: str) -> str:
    console = make_console(no_color=True, width=400)
    console.file = io.StringIO()
    console.print(markup)
    rendered = console.file.getvalue()
    assert isinstance(rendered, str)
    return rendered


@pytest.mark.parametrize("value", [_SWALLOWED, _CRASHING], ids=["tag", "stray"])
@pytest.mark.parametrize("builder", sorted(_BUILDERS))
def test_a_bracketed_value_is_printed_as_written(builder: str, value: str) -> None:
    assert value in _rendered(_BUILDERS[builder](value))


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "mod.py").write_text("VALUE = 1\n", "utf-8")
    return root


def test_a_bracketed_report_name_is_a_contract_error(tmp_path: Path) -> None:
    root = _project(tmp_path)

    run = run_codeclone(tmp_path, ".", "--html", "out[/x].htm", cwd=root)

    output = run.stdout + run.stderr
    assert run.returncode == 2, output
    assert "out[/x].htm" in output, output


def test_a_bracketed_missing_root_is_a_contract_error(tmp_path: Path) -> None:
    missing = tmp_path / "no[/x]"

    run = run_codeclone(tmp_path, str(missing), "--no-progress")

    output = run.stdout + run.stderr
    assert run.returncode == 2, output
    assert "Root path does not exist" in output, output
    assert "no[/x]" in output, output


@pytest.mark.parametrize(
    ("command", "make_dir", "headline"),
    [
        ("status", False, "Repository root does not exist"),
        ("migrate", True, "Engineering memory database not found"),
    ],
)
def test_a_bracketed_memory_root_is_a_contract_error(
    tmp_path: Path, command: str, make_dir: bool, headline: str
) -> None:
    root = tmp_path / "p[/x]"
    if make_dir:
        root.mkdir(parents=True)

    run = run_codeclone(tmp_path, "memory", command, "--root", str(root))

    output = run.stdout + run.stderr
    assert run.returncode == 2, output
    assert "Traceback" not in output, output
    assert headline in output, output
    assert "p[/x]" in output, output
