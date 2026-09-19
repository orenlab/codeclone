# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

import os
import subprocess
import sys
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
    assert result.stdout.replace("\r\n", "\n") == load_text_snapshot(snapshot)
