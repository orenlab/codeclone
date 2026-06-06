# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sqlite3
from pathlib import Path

from .. import __version__
from ..report.meta import current_report_timestamp_utc
from ..utils.sqlite_store import (
    get_meta_value,
    initialize_schema_v1,
    open_sqlite_db,
)
from .validation import AUDIT_SCHEMA_VERSION, AuditSchemaError

_AUDIT_META_TABLE = "audit_meta"

_CREATE_EVENTS_SQL = """
CREATE TABLE IF NOT EXISTS controller_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id        TEXT    NOT NULL UNIQUE,
    event_type      TEXT    NOT NULL,
    severity        TEXT    NOT NULL DEFAULT 'info',
    created_at_utc  TEXT    NOT NULL,

    repo_root_digest TEXT   NOT NULL,
    run_id          TEXT,
    intent_id       TEXT,
    report_digest   TEXT,
    workflow_id     TEXT,
    surface         TEXT,
    tool_name       TEXT,
    event_core_json TEXT,
    event_core_sha256 TEXT,
    payload_sha256  TEXT,
    agent_label     TEXT    NOT NULL DEFAULT '',
    agent_pid       INTEGER NOT NULL,

    status          TEXT,
    payload_json    TEXT    NOT NULL DEFAULT '{}',
    agent_start_epoch   INTEGER,

    estimated_tokens    INTEGER,
    token_encoding      TEXT,
    payload_characters  INTEGER,
    summary             TEXT
)
"""

_CREATE_META_SQL = """
CREATE TABLE IF NOT EXISTS audit_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""

_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_events_intent ON controller_events(intent_id)",
    "CREATE INDEX IF NOT EXISTS idx_events_run ON controller_events(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_events_workflow ON controller_events(workflow_id)",
    "CREATE INDEX IF NOT EXISTS idx_events_surface_tool "
    "ON controller_events(surface, tool_name)",
    "CREATE INDEX IF NOT EXISTS idx_events_type_time "
    "ON controller_events(event_type, created_at_utc)",
    "CREATE INDEX IF NOT EXISTS idx_events_created "
    "ON controller_events(created_at_utc)",
    "CREATE INDEX IF NOT EXISTS idx_events_analysis_repo "
    "ON controller_events(event_type, repo_root_digest, created_at_utc)",
    "CREATE INDEX IF NOT EXISTS idx_events_agent_session "
    "ON controller_events(agent_pid, agent_start_epoch)",
)

# Schema versions this build can open: the current version plus any older
# version reachable by an idempotent in-place migration.
_MIGRATABLE_VERSIONS = frozenset({"1", "2", "3", "4"})

# Additive, nullable columns expected on controller_events. Declarative so a
# single idempotent pass upgrades any older database (pre-token, token-only)
# to the current shape. Order matches the CREATE TABLE tail and the ALTER
# append order, so fresh and migrated databases converge on the same layout.
_ADDITIVE_EVENT_COLUMNS = (
    ("workflow_id", "TEXT"),
    ("surface", "TEXT"),
    ("tool_name", "TEXT"),
    ("event_core_json", "TEXT"),
    ("event_core_sha256", "TEXT"),
    ("payload_sha256", "TEXT"),
    ("estimated_tokens", "INTEGER"),
    ("token_encoding", "TEXT"),
    ("payload_characters", "INTEGER"),
    ("summary", "TEXT"),
    ("agent_start_epoch", "INTEGER"),
)


def open_audit_db(path: Path) -> sqlite3.Connection:
    return open_sqlite_db(path, ensure_schema=ensure_schema)


def ensure_schema(conn: sqlite3.Connection) -> None:
    current = get_meta(conn, "schema_version")
    if current is None:
        create_schema_v2(conn)
        return
    if current not in _MIGRATABLE_VERSIONS:
        raise AuditSchemaError(f"Unsupported audit schema version: {current}")
    # Idempotent self-heal: bring any migratable database up to the current
    # column shape, then advance the recorded version. Safe on every open.
    _ensure_event_columns(conn)
    _ensure_event_indexes(conn)
    if current != AUDIT_SCHEMA_VERSION:
        _set_meta(conn, "schema_version", AUDIT_SCHEMA_VERSION)


def create_schema_v2(conn: sqlite3.Connection) -> None:
    for statement in (_CREATE_EVENTS_SQL, _CREATE_META_SQL):
        conn.execute(statement)
    _ensure_event_columns(conn)
    initialize_schema_v1(
        conn,
        ddl_statements=(),
        index_statements=_INDEX_SQL,
        meta_table=_AUDIT_META_TABLE,
        seed_meta={
            "schema_version": AUDIT_SCHEMA_VERSION,
            "generator": "codeclone",
            "codeclone_version": __version__,
            "created_at_utc": current_report_timestamp_utc(),
        },
    )


def _ensure_event_indexes(conn: sqlite3.Connection) -> None:
    for statement in _INDEX_SQL:
        conn.execute(statement)
    conn.commit()


def _ensure_event_columns(conn: sqlite3.Connection) -> None:
    """Idempotently add any missing additive columns to controller_events.

    Backward-compatible: an older database (pre-token, or token-only) gains
    exactly the columns it lacks and nothing else. Safe to call on every open.
    """
    existing = {
        row[1]
        for row in conn.execute("PRAGMA table_info(controller_events)").fetchall()
    }
    for col, col_type in _ADDITIVE_EVENT_COLUMNS:
        if col not in existing:
            conn.execute(f"ALTER TABLE controller_events ADD COLUMN {col} {col_type}")
    conn.commit()


def _set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        f"INSERT OR REPLACE INTO {_AUDIT_META_TABLE}(key, value) VALUES (?, ?)",
        (key, value),
    )
    conn.commit()


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    return get_meta_value(conn, meta_table=_AUDIT_META_TABLE, key=key)


__all__ = [
    "create_schema_v2",
    "ensure_schema",
    "get_meta",
    "open_audit_db",
]
