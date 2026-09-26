# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The README quick start, run as written.

Step 2 of the quick start is the first thing a new user runs against their own
repository. When the sequence stops working -- a configuration key the command
now requires, a renamed subcommand -- the reader meets an exit code where the
README promised a baseline. So the commands are read out of ``README.md`` and
run, in order, on a temporary project: the text is the test input, and a
README edit that breaks the sequence fails here.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

from codeclone.ui_messages.runtime import HINT_SCOPE_ID_SETUP_COMMAND

_REPO_ROOT = Path(__file__).resolve().parents[1]
_README = _REPO_ROOT / "README.md"
_SECTION_HEADING = "### 2. Record the current structural baseline"

#: The quick start exactly as a new user types it. Changing the README block
#: means changing this too -- and then the sequence below has to run.
_EXPECTED_COMMANDS = (
    "codeclone setup apply -y",
    "codeclone . --update-baseline",
    "git add pyproject.toml .gitignore codeclone.baseline.json",
    'git commit -m "chore: add CodeClone structural baseline"',
)

# A throwaway identity with no user or system git configuration, so a signing
# key, a global hook or a template on the host cannot change what the quick
# start does here.
_GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Quick Start",
    "GIT_AUTHOR_EMAIL": "quickstart@example.invalid",
    "GIT_COMMITTER_NAME": "Quick Start",
    "GIT_COMMITTER_EMAIL": "quickstart@example.invalid",
}


def _readme_commands() -> tuple[str, ...]:
    text = _README.read_text(encoding="utf-8")
    start = text.index(_SECTION_HEADING)
    end = text.index("\n### ", start + len(_SECTION_HEADING))
    block = re.search(r"```bash\n(.*?)```", text[start:end], re.DOTALL)
    assert block is not None, f"no bash block under {_SECTION_HEADING!r}"
    return tuple(line.strip() for line in block.group(1).splitlines() if line.strip())


def _argv(command: str, *, cache_path: Path) -> list[str]:
    """Run ``codeclone`` from this checkout; keep analysis caches in tmp."""

    argv = shlex.split(command)
    if argv[0] != "codeclone":
        return argv
    runnable = [sys.executable, "-m", "codeclone.main", *argv[1:]]
    if argv[1] == "setup":
        return runnable
    return [*runnable, "--cache-path", str(cache_path)]


def test_readme_quick_start_sequence_is_pinned() -> None:
    commands = _readme_commands()

    assert commands == _EXPECTED_COMMANDS
    # The refusal of ``--update-baseline`` names the same first step.
    assert commands[0] == HINT_SCOPE_ID_SETUP_COMMAND


def _new_git_project(root: Path, *, env: dict[str, str]) -> Path:
    """A reader's repository before the quick start: one module, no config."""

    root.mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    (root / "demo.py").write_text(
        "def answer() -> int:\n    return 42\n", encoding="utf-8"
    )
    subprocess.run(["git", "init", "-q"], cwd=root, env=env, check=True)
    return root


def test_readme_quick_start_runs_as_written(tmp_path: Path) -> None:
    env = {**os.environ, **_GIT_ENV}
    project = _new_git_project(tmp_path / "project", env=env)
    cache_path = tmp_path / "cache" / "cache.sqlite3"

    for command in _readme_commands():
        completed = subprocess.run(
            _argv(command, cache_path=cache_path),
            cwd=project,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, (
            f"{command!r} exited {completed.returncode}\n"
            f"{completed.stdout}\n{completed.stderr}"
        )

    assert (project / "codeclone.baseline.json").is_file()
    tracked = subprocess.run(
        ["git", "ls-files"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert {"pyproject.toml", ".gitignore", "codeclone.baseline.json"} <= set(tracked)
