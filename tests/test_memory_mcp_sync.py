# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.config.memory import resolve_memory_config
from codeclone.memory.ingest.mcp_sync import (
    decide_mcp_memory_sync,
    execute_mcp_memory_sync,
    read_stored_report_digest,
)
from codeclone.memory.project import resolve_memory_db_path


def test_decide_mcp_memory_sync_bootstrap_when_missing_db(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    config = resolve_memory_config(root)
    db_path = resolve_memory_db_path(root, config)
    decision = decide_mcp_memory_sync(
        policy="bootstrap_if_missing",
        db_path=db_path,
        report_digest="digest-a",
        stored_digest=None,
    )
    assert decision.action == "bootstrap"
    assert decision.reason == "missing_db"


@pytest.mark.parametrize(
    ("report_digest", "stored_digest", "expected_action", "expected_reason"),
    [
        ("digest-b", "digest-a", "refresh", "digest_changed"),
        ("digest-a", "digest-a", "none", "digest_unchanged"),
    ],
)
def test_decide_mcp_memory_sync_refresh_when_stale_policy(
    tmp_path: Path,
    report_digest: str,
    stored_digest: str,
    expected_action: str,
    expected_reason: str,
) -> None:
    db_path = tmp_path / "memory.sqlite3"
    db_path.write_text("", encoding="utf-8")
    decision = decide_mcp_memory_sync(
        policy="refresh_when_stale",
        db_path=db_path,
        report_digest=report_digest,
        stored_digest=stored_digest,
    )
    assert decision.action == expected_action
    assert decision.reason == expected_reason


def test_execute_mcp_memory_sync_auto_skips_when_unchanged(
    tmp_path: Path,
) -> None:
    from tests.memory_fixtures import git_repo_with_cached_report

    root, _report_path, report_document = git_repo_with_cached_report(
        tmp_path,
        py_sources={"pkg/mod.py": "def f():\n    return 1\n"},
        registry_items=["pkg/mod.py"],
    )
    config = resolve_memory_config(root)
    db_path = resolve_memory_db_path(root, config)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    first = execute_mcp_memory_sync(
        root_path=root,
        report_document=report_document,
        config=config,
        trigger="explicit",
        run_id="run-first",
        force=True,
    )
    assert first["status"] == "completed"

    second = execute_mcp_memory_sync(
        root_path=root,
        report_document=report_document,
        config=config,
        trigger="auto",
        run_id="run-first",
        force=False,
    )
    assert second["status"] == "unchanged"
    assert read_stored_report_digest(db_path) is not None


def test_execute_mcp_memory_sync_rejects_invalid_policy(tmp_path: Path) -> None:
    from dataclasses import replace

    from tests.memory_fixtures import git_repo_with_cached_report

    root, _report_path, report_document = git_repo_with_cached_report(
        tmp_path,
        py_sources={"pkg/mod.py": "pass\n"},
        registry_items=["pkg/mod.py"],
    )
    config = replace(resolve_memory_config(root), mcp_sync_policy="off")
    payload = execute_mcp_memory_sync(
        root_path=root,
        report_document=report_document,
        config=config,
        trigger="auto",
        run_id="run-off",
        force=False,
    )
    assert payload["status"] == "unchanged"
    assert payload["reason"] == "policy_off"


def test_execute_mcp_memory_sync_skips_without_report_digest(tmp_path: Path) -> None:
    from codeclone.memory.ingest.mcp_sync import execute_mcp_memory_sync

    root = tmp_path / "repo"
    root.mkdir()
    payload = execute_mcp_memory_sync(
        root_path=root,
        report_document={},
        trigger="auto",
        run_id="run-no-digest",
        force=False,
    )
    assert payload["status"] == "skipped"
    assert payload["reason"] == "missing_report_digest"
