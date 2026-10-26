# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Run the real CLI in-process from a chosen directory and read its exit code."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import codeclone.surfaces.cli.workflow as cli


def flat(text: str) -> str:
    """Console output with Rich's line wrapping undone."""

    return " ".join(text.split())


def run_cli(monkeypatch: pytest.MonkeyPatch, cwd: Path, *args: str) -> int:
    """Exit code of ``codeclone *args`` run from *cwd* (0 when it returns)."""

    # A wide console keeps long temporary paths on one line.
    monkeypatch.setenv("COLUMNS", "4000")
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(sys, "argv", ["codeclone", *args])
    try:
        cli.main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0
