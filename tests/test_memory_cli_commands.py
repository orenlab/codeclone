# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from codeclone.contracts import ENGINEERING_MEMORY_SCHEMA_VERSION, ExitCode
from codeclone.memory.governance import record_candidate
from codeclone.surfaces.cli.memory import memory_main

from .memory_fixtures import (
    cli_memory_repo,
    git_repo_with_cached_report,
    memory_project_db_paths,
    root_with_foreign_sqlite_at_memory_store_path,
    root_with_not_a_database_at_memory_store_path,
    root_with_old_engineering_memory_store,
)


def test_memory_main_rejects_missing_root(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    code = memory_main(["status", "--root", str(missing)])
    assert code == int(ExitCode.CONTRACT_ERROR)


def test_memory_cli_status_search_stale_vacuum_coverage(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path) as (root, project, store):
        record = record_candidate(
            store,
            project=project,
            record_type="risk_note",
            statement="stale risk note",
            subject_path="pkg/mod.py",
            max_candidates=100,
        )
        store.mark_stale(record.id, reason="test")
        store.close()

    root_str = str(root.resolve())
    assert memory_main(["status", "--root", root_str]) == int(ExitCode.SUCCESS)
    assert memory_main(
        ["search", "fixture", "--root", root_str, "--match", "all", "--limit", "5"]
    ) == int(ExitCode.SUCCESS)
    assert memory_main(["stale", "--root", root_str, "--limit", "5"]) == int(
        ExitCode.SUCCESS
    )
    assert memory_main(["vacuum", "--root", root_str]) == int(ExitCode.SUCCESS)
    assert memory_main(["coverage", "pkg/mod.py", "--root", root_str]) == int(
        ExitCode.SUCCESS
    )
    assert memory_main(["review-candidates", "--root", root_str]) == int(
        ExitCode.SUCCESS
    )


def test_memory_cli_for_path_and_governance(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path) as (root, project, store):
        draft = record_candidate(
            store,
            project=project,
            record_type="architecture_decision",
            statement="approve via CLI",
            subject_path="pkg/mod.py",
            max_candidates=100,
        )
        draft_id = draft.id
        store.close()

    root_str = str(root.resolve())
    assert memory_main(
        ["for-path", "pkg/mod.py", "--root", root_str, "--limit", "3"]
    ) == int(ExitCode.SUCCESS)
    assert memory_main(
        ["approve", draft_id, "--root", root_str, "--by", "tester"]
    ) == int(ExitCode.CONTRACT_ERROR)
    assert memory_main(
        [
            "approve",
            draft_id,
            "--root",
            root_str,
            "--by",
            "tester",
            "--i-know-what-im-doing",
        ]
    ) == int(ExitCode.SUCCESS)

    reject_parent = tmp_path / "reject"
    reject_parent.mkdir(parents=True, exist_ok=True)
    with cli_memory_repo(reject_parent) as (root2, project2, store2):
        rejected = record_candidate(
            store2,
            project=project2,
            record_type="change_rationale",
            statement="reject me",
            subject_path="pkg/mod.py",
            max_candidates=100,
        )
        reject_id = rejected.id
        store2.close()
    root2_str = str(root2.resolve())
    assert memory_main(
        [
            "reject",
            reject_id,
            "--root",
            root2_str,
            "--by",
            "tester",
            "--reason",
            "not needed",
            "--i-know-what-im-doing",
        ]
    ) == int(ExitCode.SUCCESS)

    archive_parent = tmp_path / "archive"
    archive_parent.mkdir(parents=True, exist_ok=True)
    with cli_memory_repo(archive_parent) as (root3, project3, store3):
        active = record_candidate(
            store3,
            project=project3,
            record_type="change_rationale",
            statement="archive me",
            subject_path="pkg/mod.py",
            max_candidates=100,
        )
        from codeclone.memory.governance import approve_record

        approve_record(store3, record_id=active.id, approved_by="tester")
        archive_id = active.id
        store3.close()
    root3_str = str(root3.resolve())
    assert memory_main(
        [
            "archive",
            archive_id,
            "--root",
            root3_str,
            "--by",
            "tester",
            "--i-know-what-im-doing",
        ]
    ) == int(ExitCode.SUCCESS)


def test_memory_cli_init_with_git_fixture(tmp_path: Path) -> None:
    root, report_path, _doc = git_repo_with_cached_report(
        tmp_path,
        py_sources={"pkg/x.py": "VALUE = 1\n"},
        registry_items=["pkg/x.py"],
    )
    code = memory_main(
        [
            "init",
            "--root",
            str(root.resolve()),
            "--from-report",
            str(report_path),
            "--dry-run",
            "--no-docs",
            "--no-tests",
        ]
    )
    assert code == int(ExitCode.SUCCESS)


def test_memory_cli_for_path_missing_db(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    code = memory_main(["for-path", "pkg/a.py", "--root", str(root)])
    assert code == int(ExitCode.CONTRACT_ERROR)


def test_memory_cli_missing_subcommand_returns_contract_error() -> None:
    with pytest.raises(SystemExit):
        memory_main([])


def test_memory_cli_status_on_mismatched_store_reports_cleanly(
    tmp_path: Path,
) -> None:
    """``codeclone memory status`` must not crash with a raw traceback, and
    must not migrate, when the store is behind this codeclone's schema --
    one of the maintainer's three named real read-path surfaces."""
    root = root_with_old_engineering_memory_store(tmp_path, version="1.7")
    _project, db_path = memory_project_db_paths(root)
    before = db_path.read_bytes()

    code = memory_main(["status", "--root", str(root)])

    assert code == int(ExitCode.CONTRACT_ERROR)
    assert db_path.read_bytes() == before, "status must not mutate a mismatched store"


def test_memory_cli_migrate_on_mismatched_store_migrates_exactly_once(
    tmp_path: Path,
) -> None:
    root = root_with_old_engineering_memory_store(tmp_path, version="1.7")
    _project, db_path = memory_project_db_paths(root)

    code = memory_main(["migrate", "--root", str(root)])
    assert code == int(ExitCode.SUCCESS)

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT value FROM memory_meta WHERE key='schema_version'"
        ).fetchone()
        assert row == (ENGINEERING_MEMORY_SCHEMA_VERSION,)
    finally:
        conn.close()

    # status now succeeds normally against the migrated store.
    assert memory_main(["status", "--root", str(root)]) == int(ExitCode.SUCCESS)

    # A second migrate on an already-current store is a clean no-op, not an
    # error -- the CLI verb is safe to run defensively / repeatedly.
    assert memory_main(["migrate", "--root", str(root)]) == int(ExitCode.SUCCESS)


def test_memory_cli_migrate_on_missing_store_reports_cleanly(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    code = memory_main(["migrate", "--root", str(root)])
    assert code == int(ExitCode.CONTRACT_ERROR)


def test_memory_cli_status_on_a_foreign_database_reports_cleanly_and_leaves_it_alone(
    tmp_path: Path,
) -> None:
    """``codeclone memory status`` on a SQLite file that is not a store: a
    non-zero, rendered diagnostic, and not one byte written into the file.

    Measured before this pin: the read initialized the memory schema inside
    the foreign database and exited 0 with the store reported ``ready``.
    """
    root = root_with_foreign_sqlite_at_memory_store_path(tmp_path)
    _project, db_path = memory_project_db_paths(root)
    before = db_path.read_bytes()

    code = memory_main(["status", "--root", str(root)])

    assert code == int(ExitCode.CONTRACT_ERROR)
    assert db_path.read_bytes() == before, (
        "status must not initialize a foreign database"
    )


def test_memory_cli_status_on_a_file_that_is_not_a_database_reports_cleanly(
    tmp_path: Path,
) -> None:
    """``codeclone memory status`` on corrupt bytes: a rendered non-zero
    diagnostic, no raw ``sqlite3.DatabaseError`` traceback, file untouched.

    Measured before this pin: the exception escaped ``memory_main`` unwrapped
    (``dispatch_subcommand`` runs ahead of the CLI's error envelope).
    """
    root = root_with_not_a_database_at_memory_store_path(tmp_path)
    _project, db_path = memory_project_db_paths(root)
    before = db_path.read_bytes()

    code = memory_main(["status", "--root", str(root)])

    assert code == int(ExitCode.CONTRACT_ERROR)
    assert db_path.read_bytes() == before
