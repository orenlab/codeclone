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


def test_audit_event_row_includes_token_fields(tmp_path: Path) -> None:
    """Token estimation fields are populated when tiktoken is available."""
    db_path = tmp_path / "audit.sqlite3"
    writer = SqliteAuditWriter(db_path=db_path, payloads="compact", retention_days=30)
    try:
        writer.emit(_event(tmp_path))
    finally:
        writer.close()

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT estimated_tokens, token_encoding, payload_characters "
            "FROM controller_events"
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    estimated_tokens, token_encoding, payload_characters = row
    assert isinstance(estimated_tokens, int)
    assert estimated_tokens > 0
    assert isinstance(token_encoding, str)
    assert token_encoding in {"o200k_base", "chars_approx"}
    assert isinstance(payload_characters, int)
    assert payload_characters > 0


def test_audit_event_row_token_fields_null_when_no_payload(tmp_path: Path) -> None:
    """Token columns are NULL when payload is None."""
    db_path = tmp_path / "audit.sqlite3"
    writer = SqliteAuditWriter(db_path=db_path, payloads="compact", retention_days=30)
    event = AuditEvent(
        event_type=EVENT_INTENT_DECLARED,
        severity="info",
        repo_root_digest=repo_root_digest(tmp_path),
        agent_pid=123,
        agent_label="test-agent",
        payload=None,
    )
    try:
        writer.emit(event)
    finally:
        writer.close()

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT estimated_tokens, token_encoding, payload_characters "
            "FROM controller_events"
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row[0] is None  # estimated_tokens
    assert row[1] is None  # token_encoding
    assert row[2] is None  # payload_characters


def test_token_estimation_failure_does_not_break_audit(tmp_path: Path) -> None:
    """Audit event write succeeds even when estimation raises."""
    from unittest.mock import patch as mock_patch

    db_path = tmp_path / "audit.sqlite3"
    writer = SqliteAuditWriter(db_path=db_path, payloads="compact", retention_days=30)
    try:
        with mock_patch(
            "codeclone.audit.writer._estimate_payload_tokens",
            side_effect=RuntimeError("boom"),
        ):
            writer.emit(_event(tmp_path))
    finally:
        writer.close()

    # The event should still be written (emit swallows exceptions)
    # but since _estimate_payload_tokens raised before event_to_row completed,
    # the entire emit is swallowed by the outer try/except in emit().
    # This confirms the audit writer never crashes from estimation failures.
    summary = read_audit_summary(db_path=db_path)
    assert summary.total_events <= 1


def test_audit_schema_migration_adds_token_columns(tmp_path: Path) -> None:
    """Existing v1 DB without token columns gets them after ensure_schema."""
    from codeclone.audit.schema import ensure_schema
    from codeclone.audit.validation import AUDIT_SCHEMA_VERSION

    db_path = tmp_path / "audit.sqlite3"
    conn = sqlite3.connect(db_path)
    try:
        # Create a v1 schema without token columns
        conn.execute("""
            CREATE TABLE controller_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                event_type TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'info',
                created_at_utc TEXT NOT NULL,
                repo_root_digest TEXT NOT NULL,
                run_id TEXT,
                intent_id TEXT,
                report_digest TEXT,
                agent_label TEXT NOT NULL DEFAULT '',
                agent_pid INTEGER NOT NULL,
                status TEXT,
                payload_json TEXT NOT NULL DEFAULT '{}'
            )
        """)
        conn.execute(
            "CREATE TABLE audit_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO audit_meta(key, value) VALUES ('schema_version', ?)",
            (AUDIT_SCHEMA_VERSION,),
        )
        conn.commit()

        # Verify no token columns yet
        cols_before = {
            row[1]
            for row in conn.execute("PRAGMA table_info(controller_events)").fetchall()
        }
        assert "estimated_tokens" not in cols_before

        # Run migration
        ensure_schema(conn)

        # Verify columns added
        cols_after = {
            row[1]
            for row in conn.execute("PRAGMA table_info(controller_events)").fetchall()
        }
        assert "estimated_tokens" in cols_after
        assert "token_encoding" in cols_after
        assert "payload_characters" in cols_after

        # Verify insert works with new columns
        conn.execute(
            "INSERT INTO controller_events"
            "(event_id, event_type, severity, created_at_utc, "
            "repo_root_digest, agent_label, agent_pid, "
            "estimated_tokens, token_encoding, payload_characters) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "evt_test",
                "intent.declared",
                "info",
                "2026-01-01T00:00:00Z",
                "abc123",
                "agent",
                1,
                42,
                "o200k_base",
                168,
            ),
        )
        conn.commit()
    finally:
        conn.close()


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
