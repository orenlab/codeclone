from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from codeclone.audit.events import EVENT_INTENT_DECLARED, AuditEvent, repo_root_digest
from codeclone.audit.reader import read_audit_summary
from codeclone.audit.validation import (
    AuditValidationError,
    EventRow,
    validate_event_row,
)
from codeclone.audit.writer import NullAuditWriter, SqliteAuditWriter


def _event(root: Path, *, event_type: str = EVENT_INTENT_DECLARED) -> AuditEvent:
    return AuditEvent(
        event_type=event_type,
        severity="info",
        repo_root_digest=repo_root_digest(root),
        agent_pid=123,
        agent_label="test-agent",
        run_id="run12345",
        intent_id="intent-run12345-001",
        report_digest="a" * 64,
        status="active",
        payload={
            "scope": {"allowed_files": ["pkg/a.py", "tests/test_a.py"]},
            "concurrent_intents": [],
            "workspace_registered": True,
            "ttl_seconds": 3600,
        },
    )


def _payloads(db_path: Path) -> list[dict[str, object]]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT payload_json FROM controller_events").fetchall()
    finally:
        conn.close()
    return [json.loads(row[0]) for row in rows]


def test_sqlite_writer_creates_db_and_emits_compact_event(tmp_path: Path) -> None:
    db_path = tmp_path / "audit.sqlite3"
    writer = SqliteAuditWriter(db_path=db_path, payloads="compact", retention_days=30)
    try:
        writer.emit(_event(tmp_path))
    finally:
        writer.close()

    summary = read_audit_summary(db_path=db_path)
    assert summary.total_events == 1
    assert summary.intent_events == 1
    assert summary.events[0].event_type == EVENT_INTENT_DECLARED
    assert _payloads(db_path)[0]["scope_file_count"] == 2


def test_sqlite_writer_payload_modes(tmp_path: Path) -> None:
    off_path = tmp_path / "off.sqlite3"
    full_path = tmp_path / "full.sqlite3"
    off_writer = SqliteAuditWriter(db_path=off_path, payloads="off", retention_days=30)
    full_writer = SqliteAuditWriter(
        db_path=full_path,
        payloads="full",
        retention_days=30,
    )
    try:
        off_writer.emit(_event(tmp_path))
        full_writer.emit(_event(tmp_path))
    finally:
        off_writer.close()
        full_writer.close()

    assert _payloads(off_path) == [{}]
    assert "scope" in _payloads(full_path)[0]


def test_sqlite_writer_emit_never_raises_for_invalid_event(tmp_path: Path) -> None:
    db_path = tmp_path / "audit.sqlite3"
    writer = SqliteAuditWriter(db_path=db_path, payloads="compact", retention_days=30)
    try:
        writer.emit(_event(tmp_path, event_type="unknown.event"))
    finally:
        writer.close()

    assert read_audit_summary(db_path=db_path).total_events == 0


def test_null_writer_is_noop(tmp_path: Path) -> None:
    writer = NullAuditWriter()
    writer.emit(_event(tmp_path))
    writer.close()


def test_event_validation_rejects_unknown_type() -> None:
    row = EventRow(
        event_id="evt_1",
        event_type="unknown.event",
        severity="info",
        created_at_utc="2026-05-25T00:00:00Z",
        repo_root_digest="a" * 16,
        run_id=None,
        intent_id=None,
        report_digest=None,
        agent_label="agent",
        agent_pid=1,
        status=None,
        payload_json="{}",
    )

    with pytest.raises(AuditValidationError, match="unknown event_type"):
        validate_event_row(row)
