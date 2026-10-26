# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""``setup apply --json`` never asks: it applies with ``--yes`` or refuses.

On a terminal, ``apply --json`` without ``--yes`` or ``--dry-run`` printed the
plan preview to stdout, waited for an answer, and then wrote the JSON after
the preview -- or, on "no", printed "Apply aborted" and no JSON at all. A
caller asking for JSON got a document no parser accepts, and an interactive
prompt it could not see. Maintainer ruling 2026-10-23: ``--json``
without ``--yes`` or ``--dry-run`` is a usage error, exit 2, before anything
is shown or written -- the same refusal a run without a terminal already got.
"""

from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests._cli_child import child_env, run_codeclone

pty = pytest.importorskip("pty")

_PTY_DEADLINE_SECONDS = 120.0
# A plan with two ready actions, so a confirmed apply would write both files.
_PYPROJECT = '[project]\nname = "demo"\n'


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "mod.py").write_text("VALUE = 1\n", "utf-8")
    (root / ".gitignore").write_text("venv/\n", "utf-8")
    (root / "pyproject.toml").write_text(_PYPROJECT, "utf-8")
    return root


def _run_on_a_terminal(
    tmp_path: Path, args: list[str], reply: str
) -> tuple[int, str, str]:
    """Run the CLI with stdin and stdout on a pseudo-terminal."""

    master, slave = pty.openpty()
    process = subprocess.Popen(
        [sys.executable, "-m", "codeclone.main", *args],
        stdin=slave,
        stdout=slave,
        stderr=subprocess.PIPE,
        env=child_env(tmp_path),
        cwd=str(tmp_path),
        close_fds=True,
    )
    os.close(slave)
    # The line discipline holds the reply until ``input()`` reads it.
    os.write(master, reply.encode())
    chunks: list[bytes] = []
    deadline = time.monotonic() + _PTY_DEADLINE_SECONDS
    while time.monotonic() < deadline:
        ready, _, _ = select.select([master], [], [], 0.5)
        if ready:
            try:
                data = os.read(master, 65536)
            except OSError:
                break
            if not data:
                break
            chunks.append(data)
        elif process.poll() is not None:
            break
    if process.poll() is None:
        process.kill()
    process.wait(timeout=60)
    os.close(master)
    assert process.stderr is not None
    stderr = process.stderr.read().decode()
    terminal = b"".join(chunks).decode(errors="replace").replace("\r\n", "\n")
    # The pty echoes what was typed; it is input, not output.
    terminal = terminal.replace(reply.replace("\r\n", "\n"), "", 1)
    return process.returncode, terminal, stderr


@pytest.mark.parametrize("reply", ["y\n", "n\n"], ids=["yes", "no"])
def test_apply_json_on_a_terminal_without_yes_is_refused(
    tmp_path: Path, reply: str
) -> None:
    root = _project(tmp_path)

    code, terminal, stderr = _run_on_a_terminal(
        tmp_path, ["setup", "apply", "--json", "--root", str(root)], reply
    )

    assert code == 2, (terminal, stderr)
    assert terminal.strip() == "", terminal
    assert "--yes" in stderr and "--dry-run" in stderr, stderr
    assert (root / ".gitignore").read_text("utf-8") == "venv/\n"
    assert (root / "pyproject.toml").read_text("utf-8") == _PYPROJECT


@pytest.mark.parametrize("flag", ["--yes", "--dry-run"])
def test_apply_json_with_an_explicit_choice_prints_one_document(
    tmp_path: Path, flag: str
) -> None:
    """Positive control: the refusal is about the missing choice only."""

    root = _project(tmp_path)

    run = run_codeclone(tmp_path, "setup", "apply", "--json", flag, "--root", str(root))

    payload = json.loads(run.stdout)
    assert isinstance(payload, dict) and "status" in payload, run.stdout
