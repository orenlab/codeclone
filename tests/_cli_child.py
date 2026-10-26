# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Run the real ``codeclone`` CLI in a child process with a throwaway home.

The suites that use this pin what a user sees: the exit code, and whether a
refusal arrived as a typed contract error or as a crash. Only a child process
shows that faithfully -- the top-level internal-error handler and a raw
traceback both live above anything an in-process call returns.

The child gets a minimal environment: ``PATH`` and the interpreter, plus a
home, XDG directories and ``TMPDIR`` under the test's own temporary directory,
so no run can read or write the operator's real stores or settings.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
CHILD_TIMEOUT_SECONDS = 300.0


def child_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return home


def child_env(tmp_path: Path, extra: Mapping[str, str] | None = None) -> dict[str, str]:
    home = child_home(tmp_path)
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_DATA_HOME": str(home / ".local" / "share"),
        "XDG_STATE_HOME": str(home / ".local" / "state"),
        # The scanner refuses roots under ``/private/var`` unless they sit
        # under the temporary directory; a project under ``tmp_path`` does.
        "TMPDIR": str(tmp_path),
        "LANG": "en_US.UTF-8",
        "LC_ALL": "en_US.UTF-8",
        "PYTHONPATH": str(_REPO_ROOT),
        "PYTHONDONTWRITEBYTECODE": "1",
        "GIT_CONFIG_NOSYSTEM": "1",
        "NO_COLOR": "1",
        "COLUMNS": "200",
    }
    if extra:
        env.update(extra)
    return env


def run_codeclone(
    tmp_path: Path,
    *args: str,
    cwd: Path | None = None,
    extra_env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "codeclone.main", *args],
        cwd=str(cwd or tmp_path),
        env=child_env(tmp_path, extra_env),
        capture_output=True,
        text=True,
        check=False,
        timeout=CHILD_TIMEOUT_SECONDS,
    )
