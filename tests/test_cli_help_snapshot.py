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

from tests._contract_snapshots import load_text_snapshot


def test_cli_help_snapshot() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root_dir) + os.pathsep + env.get("PYTHONPATH", "")
    # The help banner mascot renders Unicode when stdout can encode it and ASCII
    # otherwise (see ui.mascot.mascot_use_unicode), so without pinning the
    # environment this snapshot would depend on the runner's stdout encoding.
    # NO_COLOR forces the deterministic ASCII frame that the committed golden
    # captures, keeping the contract stable across encodings and CI runners.
    env["NO_COLOR"] = "1"
    result = subprocess.run(
        [sys.executable, "-m", "codeclone.main", "--help"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.replace("\r\n", "\n") == load_text_snapshot("cli_help.txt")
