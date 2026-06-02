# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.surfaces.cli.memory import memory_main


def test_semantic_status_reports_unavailable_by_default(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = memory_main(["semantic", "status", "--root", str(tmp_path)])
    out = capsys.readouterr().out.lower()
    assert code == 0
    assert "semantic index" in out
    # default config has semantic disabled -> status reason "disabled"
    assert "disabled" in out


def test_semantic_rebuild_fails_clear_without_backend(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = memory_main(["semantic", "rebuild", "--root", str(tmp_path)])
    out = capsys.readouterr().out.lower()
    assert code != 0
    assert "semantic" in out
    assert "semantic-lancedb" in out


def test_semantic_search_fails_clear_without_backend(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = memory_main(
        ["semantic", "search", "recover after restart", "--root", str(tmp_path)]
    )
    out = capsys.readouterr().out.lower()
    assert code != 0
    assert "unavailable" in out
