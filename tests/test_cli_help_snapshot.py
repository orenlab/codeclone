# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from tests._contract_snapshots import load_text_snapshot

_REPO_ROOT = Path(__file__).resolve().parents[1]

#: ``(argv before --help, committed golden)``. The subcommand screens are
#: snapshotted for the same reason the root screen is: argparse builds them
#: from data -- a command table for ``memory``, a chain of ``_command`` calls
#: for ``analytics`` -- so dropping a command removes both the row and any
#: parser-introspection assertion about it, and only a committed golden turns
#: that into a visible diff.
_HELP_SCREENS: tuple[tuple[tuple[str, ...], str], ...] = (
    ((), "cli_help.txt"),
    (("analytics",), "cli_help_analytics.txt"),
    (("memory",), "cli_help_memory.txt"),
)


def produce_help(argv: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    """Run the help producer: the module entry point, as the console script does.

    This function is also what regenerates the goldens, so a golden cannot
    drift from the producer by being written any other way.
    """

    env = os.environ.copy()
    env["PYTHONPATH"] = str(_REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    # The help banner mascot renders Unicode when stdout can encode it and ASCII
    # otherwise (see ui.mascot.mascot_use_unicode), so without pinning the
    # environment this snapshot would depend on the runner's stdout encoding.
    # NO_COLOR forces the deterministic ASCII frame that the committed golden
    # captures, keeping the contract stable across encodings and CI runners.
    env["NO_COLOR"] = "1"
    # argparse wraps to shutil.get_terminal_size(), which reads COLUMNS before
    # it looks at the original stdout. A pipe makes that lookup fall back to 80
    # -- unless the caller's shell exported COLUMNS, which would silently
    # rewrap every row and rewrite the golden.
    env["COLUMNS"] = "80"
    return subprocess.run(
        [sys.executable, "-m", "codeclone.main", *argv, "--help"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


@pytest.mark.parametrize(
    ("argv", "snapshot"),
    [pytest.param(argv, name, id=name) for argv, name in _HELP_SCREENS],
)
def test_cli_help_snapshot(argv: tuple[str, ...], snapshot: str) -> None:
    result = produce_help(argv)

    assert result.returncode == 0
    assert result.stderr == ""
    read = _help_reading(argv)
    actual = result.stdout.replace("\r\n", "\n")
    assert read(actual) == read(load_text_snapshot(snapshot))


def _help_reading(argv: tuple[str, ...]) -> Callable[[str], object]:
    """How a screen is compared on this interpreter: byte for byte, or by table.

    argparse before 3.12 lays a subcommand table out two columns narrower
    (the rows' extra indent was left out of the help column) and therefore
    wraps long descriptions at other words, so the goldens -- produced on
    3.12+ -- differ from these interpreters' output only in whitespace and
    line breaks inside that table. The contract these screens hold is the
    table itself: which commands exist and what each says. On 3.10 and 3.11
    that is what is compared; every other line still has to match. The root
    screen has no such table and is byte-exact everywhere.
    """

    if sys.version_info >= (3, 12) or not argv:
        return str
    return _subcommand_table


_TABLE_ROW = re.compile(r"^( {2}| {4})(\S.*?)(?: {2,}(\S.*))?$")
_CONTINUATION = re.compile(r"^ {6,}(\S.*)$")


def _subcommand_table(text: str) -> tuple[dict[str, str], tuple[str, ...]]:
    """``({entry: help joined by single spaces}, every other line)``.

    An entry is a subcommand row (four spaces) or an option row (two spaces):
    the name, then two or more spaces and its help -- or the name alone when
    argparse could not fit the help beside it, as 3.10 and 3.11 do for a long
    command name -- and the lines indented deeper right after it continue
    that help. Entries must exist for a screen that lists subcommands, so an
    empty table is a failure of this parser, never a pass.
    """

    rows: dict[str, str] = {}
    rest: list[str] = []
    current: str | None = None
    for line in text.split("\n"):
        row = _TABLE_ROW.match(line)
        if row is not None:
            current = f"{row.group(1)}{row.group(2)}"
            rows[current] = row.group(3) or ""
            continue
        if current is not None:
            continuation = _CONTINUATION.match(line)
            if continuation is not None:
                rows[current] = f"{rows[current]} {continuation.group(1)}".strip()
                continue
        current = None
        rest.append(line.rstrip())
    assert rows, "no table rows parsed: the table comparison saw nothing"
    return rows, tuple(rest)
