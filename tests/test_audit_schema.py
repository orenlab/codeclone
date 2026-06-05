# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from codeclone.audit.schema import ensure_schema, open_audit_db
from codeclone.audit.validation import (
    AUDIT_SCHEMA_VERSION,
    AuditConfigError,
    AuditSchemaError,
    resolve_audit_path,
    validate_payload_mode,
    validate_retention_days,
)


def test_open_audit_db_creates_schema_and_meta(tmp_path: Path) -> None:
    db_path = tmp_path / "audit.sqlite3"

    conn = open_audit_db(db_path)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        schema = conn.execute(
            "SELECT value FROM audit_meta WHERE key = 'schema_version'"
        ).fetchone()
    finally:
        conn.close()

    assert {"controller_events", "audit_meta"}.issubset(tables)
    assert schema == (AUDIT_SCHEMA_VERSION,)


def test_ensure_schema_rejects_unknown_version(tmp_path: Path) -> None:
    db_path = tmp_path / "audit.sqlite3"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE audit_meta(key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT INTO audit_meta(key, value) VALUES ('schema_version', '999')"
        )
        conn.commit()

        with pytest.raises(AuditSchemaError, match="Unsupported audit schema"):
            ensure_schema(conn)
    finally:
        conn.close()


def test_resolve_audit_path_accepts_repo_relative_sqlite_path(tmp_path: Path) -> None:
    resolved = resolve_audit_path(
        root_path=tmp_path,
        value=".codeclone/audit.db",
    )
    assert resolved == tmp_path / ".codeclone" / "audit.db"


@pytest.mark.parametrize(
    "value",
    ["/tmp/audit.sqlite3", "../audit.sqlite3", "audit.txt"],
)
def test_resolve_audit_path_rejects_unsafe_values(
    tmp_path: Path,
    value: str,
) -> None:
    with pytest.raises(AuditConfigError):
        resolve_audit_path(root_path=tmp_path, value=value)


def test_payload_mode_and_retention_validation() -> None:
    assert validate_payload_mode("off") == "off"
    assert validate_payload_mode("compact") == "compact"
    assert validate_payload_mode("full") == "full"
    assert validate_retention_days(30) == 30

    with pytest.raises(AuditConfigError):
        validate_payload_mode("verbose")
    with pytest.raises(AuditConfigError):
        validate_retention_days(0)


def test_fresh_database_is_v3_with_agent_start_epoch_column(tmp_path: Path) -> None:
    db_path = tmp_path / "audit.sqlite3"

    conn = open_audit_db(db_path)
    try:
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(controller_events)").fetchall()
        }
        version = conn.execute(
            "SELECT value FROM audit_meta WHERE key = 'schema_version'"
        ).fetchone()
    finally:
        conn.close()

    assert "summary" in columns
    assert "agent_start_epoch" in columns
    assert version == (AUDIT_SCHEMA_VERSION,)
    assert AUDIT_SCHEMA_VERSION == "3"


def test_v2_database_migrates_to_v3_preserving_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "audit.sqlite3"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
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
                payload_json TEXT NOT NULL DEFAULT '{}',
                estimated_tokens INTEGER,
                token_encoding TEXT,
                payload_characters INTEGER,
                summary TEXT
            )
            """
        )
        conn.execute(
            "CREATE TABLE audit_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO audit_meta(key, value) VALUES ('schema_version', '2')"
        )
        conn.execute(
            "INSERT INTO controller_events"
            "(event_id, event_type, severity, created_at_utc, "
            "repo_root_digest, agent_label, agent_pid, status, summary) "
            "VALUES ('evt_legacy', 'intent.declared', 'info', "
            "'2026-01-01T00:00:00Z', 'abc123', 'agent', 1, 'active', 'declare')"
        )
        conn.commit()

        ensure_schema(conn)

        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(controller_events)").fetchall()
        }
        version = conn.execute(
            "SELECT value FROM audit_meta WHERE key = 'schema_version'"
        ).fetchone()
        preserved = conn.execute(
            "SELECT event_id, status, summary, agent_start_epoch "
            "FROM controller_events WHERE event_id = 'evt_legacy'"
        ).fetchone()
    finally:
        conn.close()

    assert "agent_start_epoch" in columns
    assert version == (AUDIT_SCHEMA_VERSION,)
    assert preserved == ("evt_legacy", "active", "declare", None)


def test_v1_database_migrates_to_v2_preserving_rows(tmp_path: Path) -> None:
    # An existing v1 database (token columns, no summary) upgrades in place:
    # the summary column is added, the recorded version advances, and the
    # existing audit rows survive untouched.
    db_path = tmp_path / "audit.sqlite3"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
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
                payload_json TEXT NOT NULL DEFAULT '{}',
                estimated_tokens INTEGER,
                token_encoding TEXT,
                payload_characters INTEGER
            )
            """
        )
        conn.execute(
            "CREATE TABLE audit_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO audit_meta(key, value) VALUES ('schema_version', '1')"
        )
        conn.execute(
            "INSERT INTO controller_events"
            "(event_id, event_type, severity, created_at_utc, "
            "repo_root_digest, agent_label, agent_pid, status) "
            "VALUES ('evt_legacy', 'intent.declared', 'info', "
            "'2026-01-01T00:00:00Z', 'abc123', 'agent', 1, 'active')"
        )
        conn.commit()

        columns_before = {
            row[1]
            for row in conn.execute("PRAGMA table_info(controller_events)").fetchall()
        }
        assert "summary" not in columns_before

        ensure_schema(conn)

        columns_after = {
            row[1]
            for row in conn.execute("PRAGMA table_info(controller_events)").fetchall()
        }
        version = conn.execute(
            "SELECT value FROM audit_meta WHERE key = 'schema_version'"
        ).fetchone()
        preserved = conn.execute(
            "SELECT event_id, status, summary FROM controller_events "
            "WHERE event_id = 'evt_legacy'"
        ).fetchone()
    finally:
        conn.close()

    assert "summary" in columns_after
    assert "agent_start_epoch" in columns_after
    assert version == (AUDIT_SCHEMA_VERSION,)
    assert AUDIT_SCHEMA_VERSION != "1"
    assert preserved == ("evt_legacy", "active", None)
