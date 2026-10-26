# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""``setup apply`` says why an action failed, not only that it did.

Each apply result carries a ``message`` -- the reason an action failed or was
skipped. The plain renderer printed it; the rich one, which is what the CLI
uses with and without a terminal, showed only an Action / Target / Result
table. A failed apply ended with ``failed`` and no reason anywhere on screen.
"""

from __future__ import annotations

from pathlib import Path

from tests._cli_child import run_codeclone


def test_a_failed_action_prints_its_reason(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "mod.py").write_text("VALUE = 1\n", "utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "demo"\n', "utf-8")
    # A directory where the file belongs: the append cannot be written.
    (root / ".gitignore").mkdir()

    run = run_codeclone(tmp_path, "setup", "apply", "--yes", "--root", str(root))

    output = run.stdout + run.stderr
    assert "failed" in output, output
    assert "Is a directory" in output, output


def test_a_clean_apply_prints_no_reason_line(tmp_path: Path) -> None:
    """Positive control: an applied action has no message to print."""

    root = tmp_path / "proj"
    root.mkdir()
    (root / "mod.py").write_text("VALUE = 1\n", "utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "demo"\n', "utf-8")
    (root / ".gitignore").write_text("venv/\n", "utf-8")

    run = run_codeclone(tmp_path, "setup", "apply", "--yes", "--root", str(root))

    assert run.returncode == 0, run.stdout + run.stderr
    assert "gitignore_append .gitignore:" not in run.stdout, run.stdout
