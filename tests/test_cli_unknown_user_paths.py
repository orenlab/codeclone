# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A path that names an unknown user's home is a usage error, not a crash.

``Path("~nobody/x").expanduser()`` raises ``RuntimeError`` ("Could not
determine home directory."), not ``OSError``. Every path flag already turns an
``OSError`` into a typed contract error, so this one refusal slipped past all
of them: the main command died in the internal-error handler (exit 5) and the
``setup`` and ``memory`` subcommands with a raw traceback (exit 1). Each flag
must now refuse with exit 2 and say which path it could not use.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._cli_child import child_home, run_codeclone

_UNKNOWN_USER = "~codeclone_no_such_user_7f3a"


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "mod.py").write_text("VALUE = 1\n", "utf-8")
    return root


def _assert_typed_refusal(
    run_output: str, returncode: int, *, headline: str, raw_path: str
) -> None:
    assert returncode == 2, run_output
    assert "Traceback" not in run_output, run_output
    assert "INTERNAL ERROR" not in run_output, run_output
    assert headline in run_output, run_output
    assert raw_path in run_output, run_output


@pytest.mark.parametrize(
    ("flag", "filename", "headline"),
    [
        ("--baseline", "b.json", "Invalid baseline path"),
        ("--cache-path", "c.db", "Invalid cache path"),
        ("--html", "r.html", "Invalid HTML output path"),
        ("--json", "r.json", "Invalid JSON output path"),
    ],
)
def test_an_unknown_user_home_in_a_path_flag_is_a_contract_error(
    tmp_path: Path, flag: str, filename: str, headline: str
) -> None:
    root = _project(tmp_path)
    raw_path = f"{_UNKNOWN_USER}/{filename}"

    run = run_codeclone(tmp_path, str(root), flag, raw_path, "--no-progress")

    _assert_typed_refusal(
        run.stdout + run.stderr,
        run.returncode,
        headline=headline,
        raw_path=raw_path,
    )


@pytest.mark.parametrize("subcommand", ["setup", "memory"])
def test_an_unknown_user_home_as_a_subcommand_root_is_a_contract_error(
    tmp_path: Path, subcommand: str
) -> None:
    raw_path = f"{_UNKNOWN_USER}/repo"

    run = run_codeclone(tmp_path, subcommand, "status", "--root", raw_path)

    _assert_typed_refusal(
        run.stdout + run.stderr,
        run.returncode,
        headline="Repository root",
        raw_path=raw_path,
    )


def test_a_known_home_still_expands(tmp_path: Path) -> None:
    """Positive control: ``~/`` keeps meaning the operator's home."""

    root = _project(tmp_path)

    run = run_codeclone(tmp_path, str(root), "--json", "~/out.json", "--no-progress")

    assert run.returncode == 0, run.stdout + run.stderr
    assert (child_home(tmp_path) / "out.json").is_file()
    assert not (tmp_path / "~").exists()
