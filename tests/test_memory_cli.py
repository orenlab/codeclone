# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

from codeclone.contracts import ExitCode
from codeclone.surfaces.cli.memory import memory_main
from codeclone.utils.json_io import read_json_object


def test_memory_status_without_db(tmp_path: Path) -> None:
    exit_code = memory_main(["status", "--root", str(tmp_path)])
    assert exit_code == int(ExitCode.SUCCESS)


def test_memory_init_dry_run_uses_fixture_report(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    report_path = repo_root / ".codeclone" / "report.json"
    if not report_path.is_file():
        return
    exit_code = memory_main(
        [
            "init",
            "--dry-run",
            "--root",
            str(repo_root),
            "--from-report",
            str(report_path),
        ]
    )
    assert exit_code == int(ExitCode.SUCCESS)


def test_memory_init_persists_and_for_path(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    report_path = repo_root / ".codeclone" / "report.json"
    if not report_path.is_file():
        return
    db_root = tmp_path / "work"
    db_root.mkdir()
    (db_root / "pyproject.toml").write_text("", encoding="utf-8")
    report_copy = db_root / "report.json"
    report_copy.write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")

    init_code = memory_main(
        [
            "init",
            "--root",
            str(repo_root),
            "--from-report",
            str(report_copy),
        ]
    )
    assert init_code == int(ExitCode.SUCCESS)

    payload = read_json_object(report_path)
    inventory = payload.get("inventory")
    assert isinstance(inventory, dict)
    file_registry = inventory.get("file_registry")
    assert isinstance(file_registry, dict)
    items = file_registry.get("items")
    assert isinstance(items, list)
    assert items
    sample_path = str(items[0]).replace("\\", "/")

    for_path_code = memory_main(
        ["for-path", sample_path, "--root", str(repo_root), "--limit", "5"]
    )
    assert for_path_code == int(ExitCode.SUCCESS)
