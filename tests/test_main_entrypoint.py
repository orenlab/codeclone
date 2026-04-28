# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest


def test_main_module_guard_runs() -> None:
    root_dir = Path(__file__).parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root_dir) + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-m", "codeclone.main", "--help"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0


def test_main_module_guard_runpy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, "codeclone.main", raising=False)
    monkeypatch.setattr(sys, "argv", ["codeclone", "--help"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("codeclone.main", run_name="__main__")
    assert exc.value.code == 0
