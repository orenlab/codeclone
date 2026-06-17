# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests._runpy_guard import assert_runpy_module_help_exits_zero


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
    assert_runpy_module_help_exits_zero(
        monkeypatch,
        module="codeclone.main",
        module_cache_key="codeclone.main",
        argv=["codeclone", "--help"],
    )
