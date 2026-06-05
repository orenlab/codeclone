# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from codeclone.audit.analysis_completed import (
    ANALYSIS_SOURCE_MCP,
    emit_analysis_completed,
)
from codeclone.audit.events import EVENT_ANALYSIS_COMPLETED, event_summary
from codeclone.audit.reader import read_latest_analysis_run
from codeclone.audit.schema import open_audit_db
from codeclone.audit.writer import SqliteAuditWriter


def _default_analysis_summary() -> dict[str, object]:
    return {
        "focus": "repository",
        "mode": "full",
        "schema": "2.11",
        "health": {"score": 91, "grade": "A"},
        "findings": {"total": 12, "new": 1},
        "inventory": {"files": 44, "lines": 1000, "functions": 200},
        "diff": {"new_clones": 0, "health_delta": None},
    }


def _write_analysis_completed_event(
    tmp_path: Path,
    *,
    summary: Mapping[str, object] | None = None,
    run_id: str = "run1234567890abcdef",
    agent_pid: int = 4242,
    agent_start_epoch: int = 1700000000,
    agent_label: str = "codeclone-mcp/test",
    report_digest: str = "d" * 64,
) -> Path:
    db_path = tmp_path / "audit.sqlite3"
    writer = SqliteAuditWriter(
        db_path=db_path,
        payloads="compact",
        retention_days=30,
    )
    emit_analysis_completed(
        root_path=tmp_path,
        summary=dict(summary or _default_analysis_summary()),
        source=ANALYSIS_SOURCE_MCP,
        report_digest=report_digest,
        run_id=run_id,
        agent_pid=agent_pid,
        agent_start_epoch=agent_start_epoch,
        agent_label=agent_label,
        writer=writer,
    )
    writer.close()
    return db_path


def _fetch_first_event_row(db_path: Path, sql: str) -> tuple[object, ...] | None:
    conn = open_audit_db(db_path)
    try:
        row = conn.execute(sql).fetchone()
    finally:
        conn.close()
    return None if row is None else tuple(row)


def test_analysis_completed_summary() -> None:
    summary = event_summary(
        EVENT_ANALYSIS_COMPLETED,
        {"source": "mcp", "health": {"score": 88}},
    )
    assert summary == "analysis completed (mcp): health=88"


def test_read_latest_analysis_run_prefers_audit_event(tmp_path: Path) -> None:
    db_path = _write_analysis_completed_event(tmp_path)

    snapshot = read_latest_analysis_run(db_path=db_path, repo_root=tmp_path)
    assert snapshot is not None
    assert snapshot.run_id == "run12345"
    assert snapshot.health == 91
    assert snapshot.findings == 12
    assert snapshot.files == 44
    assert snapshot.source == "audit_mcp"
    assert snapshot.age_seconds is not None
    assert snapshot.age_seconds >= 0


def test_open_audit_db_stores_agent_start_epoch(tmp_path: Path) -> None:
    db_path = _write_analysis_completed_event(
        tmp_path,
        summary={
            **_default_analysis_summary(),
            "health": {"score": 70, "grade": "B"},
            "findings": {"total": 1, "new": 0},
            "inventory": {"files": 2, "lines": 10, "functions": 1},
        },
        run_id="runabcdef",
        agent_pid=111,
        agent_start_epoch=123456,
        agent_label="agent",
        report_digest="e" * 64,
    )

    row = _fetch_first_event_row(
        db_path,
        "SELECT agent_start_epoch, payload_json FROM controller_events LIMIT 1",
    )
    assert row is not None
    assert row[0] == 123456
    payload = json.loads(str(row[1]))
    assert payload["source"] == "mcp"
    assert payload["health_score"] == 70
    assert payload["files"] == 2


def test_emit_accepts_mcp_internal_summary_shape(tmp_path: Path) -> None:
    db_path = _write_analysis_completed_event(
        tmp_path,
        summary={
            "analysis_mode": "full",
            "report_schema_version": "2.11",
            "health": {"score": 88, "grade": "A"},
            "findings_summary": {"total": 3, "new": 0},
            "inventory": {"files": 10, "lines": 100, "functions": 5},
            "baseline_diff": {"new_clone_groups_total": 0},
        },
        run_id="runmcpinternal",
        agent_label="cursor-vscode/test",
    )

    row = _fetch_first_event_row(
        db_path,
        "SELECT status, agent_label, payload_json FROM controller_events LIMIT 1",
    )
    assert row is not None
    assert row[0] == "full"
    assert row[1] == "cursor-vscode/test"
    payload = json.loads(str(row[2]))
    assert payload["mode"] == "full"
    assert payload["findings_total"] == 3
