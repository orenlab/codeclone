# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
from pathlib import Path

import pytest

from codeclone.contracts import ExitCode
from codeclone.surfaces.cli.memory import memory_main

from .memory_fixtures import REPO_ROOT, git_repo_with_cached_report

_ISOLATED_MEMORY_DB = ".codeclone/memory/test-isolated.sqlite3"


def test_memory_status_without_db(tmp_path: Path) -> None:
    exit_code = memory_main(["status", "--root", str(tmp_path)])
    assert exit_code == int(ExitCode.SUCCESS)


def test_memory_init_dry_run_uses_fixture_report(tmp_path: Path) -> None:
    root, _report_path, report_document = git_repo_with_cached_report(
        tmp_path,
        py_sources={"pkg/a.py": "x = 1\n"},
        registry_items=["pkg/a.py"],
    )
    report_copy = tmp_path / "fixture-report.json"
    report_copy.write_text(
        json.dumps(report_document, sort_keys=True),
        encoding="utf-8",
    )
    exit_code = memory_main(
        [
            "init",
            "--dry-run",
            "--root",
            str(root),
            "--from-report",
            str(report_copy),
        ]
    )
    assert exit_code == int(ExitCode.SUCCESS)


def test_memory_init_persists_and_for_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _report_path, report_document = git_repo_with_cached_report(
        tmp_path,
        py_sources={"pkg/a.py": "x = 1\n"},
        registry_items=["pkg/a.py"],
    )
    report_copy = tmp_path / "fixture-report.json"
    report_copy.write_text(
        json.dumps(report_document, sort_keys=True),
        encoding="utf-8",
    )
    (root / ".codeclone" / "memory").mkdir(parents=True, exist_ok=True)
    isolated_db = root / _ISOLATED_MEMORY_DB
    if isolated_db.is_file():
        isolated_db.unlink()
    monkeypatch.setenv("CODECLONE_MEMORY_DB_PATH", _ISOLATED_MEMORY_DB)

    init_code = memory_main(
        [
            "init",
            "--root",
            str(root),
            "--from-report",
            str(report_copy),
        ]
    )
    assert init_code == int(ExitCode.SUCCESS)
    assert isolated_db.is_file()

    for_path_code = memory_main(
        ["for-path", "pkg/a.py", "--root", str(root), "--limit", "5"]
    )
    assert for_path_code == int(ExitCode.SUCCESS)


def test_memory_init_dry_run_on_checkout_report(tmp_path: Path) -> None:
    """Optional: reuse checkout report.json without writing the default memory DB."""
    if not (REPO_ROOT / "codeclone").is_dir():
        pytest.skip("not running inside codeclone checkout")
    report_path = REPO_ROOT / ".codeclone" / "report.json"
    if not report_path.is_file():
        pytest.skip("cached report.json not available")
    root, _report_path, _report_document = git_repo_with_cached_report(
        tmp_path,
        py_sources={"pkg/a.py": "y = 2\n"},
        registry_items=["pkg/a.py"],
    )
    exit_code = memory_main(
        [
            "init",
            "--dry-run",
            "--root",
            str(root),
            "--from-report",
            str(report_path),
        ]
    )
    assert exit_code == int(ExitCode.SUCCESS)
