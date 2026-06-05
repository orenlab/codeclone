# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest

from codeclone.audit.analysis_completed import ANALYSIS_SOURCE_CLI
from codeclone.audit.reader import (
    _analysis_payload_from_json,
    _analysis_run_source_label,
    _short_run_id,
    read_audit_summary,
    read_latest_analysis_run,
)
from codeclone.audit.validation import (
    AuditConfigError,
    AuditReadError,
    AuditValidationError,
    EventRow,
    resolve_audit_path,
    validate_event_row,
)

from .audit_fixtures import write_compact_analysis_completed_event


def _write_cli_analysis_event(tmp_path: Path) -> Path:
    return write_compact_analysis_completed_event(
        tmp_path,
        summary={
            "mode": "full",
            "health": {"score": 77, "grade": "B"},
            "findings": {"total": 5, "new": 1},
            "inventory": {"files": 9, "lines": 100, "functions": 3},
            "diff": {"new_clones": 0, "health_delta": None},
        },
        source=ANALYSIS_SOURCE_CLI,
        report_digest="c" * 64,
        run_id="runcli1234567890",
        agent_pid=100,
        agent_start_epoch=999,
        agent_label="codeclone-cli/test",
    )


def test_read_latest_analysis_run_missing_db(tmp_path: Path) -> None:
    assert (
        read_latest_analysis_run(
            db_path=tmp_path / "missing.sqlite3",
            repo_root=tmp_path,
        )
        is None
    )


def test_read_latest_analysis_run_connect_error(tmp_path: Path) -> None:
    db_path = tmp_path / "audit.sqlite3"
    db_path.write_text("x", encoding="utf-8")
    with (
        patch("sqlite3.connect", side_effect=sqlite3.Error("disk I/O error")),
        pytest.raises(AuditReadError, match="cannot open audit database"),
    ):
        read_latest_analysis_run(db_path=db_path, repo_root=tmp_path)


def test_read_latest_analysis_run_read_error(tmp_path: Path) -> None:
    db_path = _write_cli_analysis_event(tmp_path)
    with (
        patch(
            "codeclone.audit.reader.ensure_schema",
            side_effect=sqlite3.Error("query failed"),
        ),
        pytest.raises(AuditReadError, match="cannot read audit database"),
    ):
        read_latest_analysis_run(db_path=db_path, repo_root=tmp_path)


def test_read_latest_analysis_run_cli_source_label(tmp_path: Path) -> None:
    db_path = _write_cli_analysis_event(tmp_path)
    snapshot = read_latest_analysis_run(db_path=db_path, repo_root=tmp_path)
    assert snapshot is not None
    assert snapshot.source == "audit_cli"
    assert snapshot.run_id == "runcli12"
    assert snapshot.health == 77
    assert snapshot.findings == 5
    assert snapshot.files == 9


def test_analysis_payload_from_json_edge_cases() -> None:
    assert _analysis_payload_from_json(None) == {}
    assert _analysis_payload_from_json("") == {}
    assert _analysis_payload_from_json("{not-json") == {}
    assert _analysis_payload_from_json("[]") == {}


def test_analysis_run_source_label_unknown() -> None:
    assert _analysis_run_source_label("other") == "audit_unknown"


def test_short_run_id_edge_cases() -> None:
    assert _short_run_id(None, {}) is None
    assert _short_run_id("   ", {}) is None
    assert _short_run_id("abc", {}) == "abc"


def test_read_latest_analysis_run_compact_payload_fallbacks(tmp_path: Path) -> None:
    db_path = write_compact_analysis_completed_event(
        tmp_path,
        summary={
            "mode": "full",
            "health": {"score": 88, "grade": "A"},
            "findings": {"total": 3, "new": 0},
            "inventory": {"files": 10, "lines": 100, "functions": 5},
            "diff": {"new_clones": 0, "health_delta": None},
        },
        source=ANALYSIS_SOURCE_CLI,
        report_digest="c" * 64,
        run_id="runcompact123456",
        agent_pid=100,
        agent_start_epoch=999,
        agent_label="codeclone-cli/test",
    )
    snapshot = read_latest_analysis_run(db_path=db_path, repo_root=tmp_path)
    assert snapshot is not None
    assert snapshot.health == 88
    assert snapshot.findings == 3
    assert snapshot.files == 10


def test_read_audit_summary_without_token_columns_branch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = _write_cli_analysis_event(tmp_path)
    monkeypatch.setattr(
        "codeclone.audit.reader._has_token_columns",
        lambda _conn: False,
    )
    summary = read_audit_summary(db_path=db_path, limit=5)
    assert summary.total_events == 1
    assert summary.payload_footprint is None


def test_resolve_audit_path_wraps_repo_path_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.utils.repo_paths import RepoPathError

    def _boom(*_args: object, **_kwargs: object) -> Path:
        raise RepoPathError("cannot resolve path")

    monkeypatch.setattr(
        "codeclone.audit.validation.resolve_under_repo_root",
        _boom,
    )
    with pytest.raises(AuditConfigError, match="invalid audit_path"):
        resolve_audit_path(root_path=tmp_path, value=".codeclone/db/audit.sqlite3")


def test_validate_event_row_rejects_invalid_agent_start_epoch() -> None:
    row = EventRow(
        event_id="evt_1",
        event_type="analysis.completed",
        severity="info",
        created_at_utc="2026-05-25T00:00:00Z",
        repo_root_digest="a" * 16,
        run_id="run1234567890abcdef",
        intent_id=None,
        report_digest="b" * 64,
        agent_label="agent",
        agent_pid=1,
        agent_start_epoch=cast(int | None, True),
        status="full",
        payload_json="{}",
    )
    with pytest.raises(
        AuditValidationError, match="agent_start_epoch must be an integer"
    ):
        validate_event_row(row)

    row_negative = EventRow(
        event_id="evt_2",
        event_type="analysis.completed",
        severity="info",
        created_at_utc="2026-05-25T00:00:00Z",
        repo_root_digest="a" * 16,
        run_id="run1234567890abcdef",
        intent_id=None,
        report_digest="b" * 64,
        agent_label="agent",
        agent_pid=1,
        agent_start_epoch=-1,
        status="full",
        payload_json="{}",
    )
    with pytest.raises(
        AuditValidationError,
        match="agent_start_epoch must be non-negative",
    ):
        validate_event_row(row_negative)
