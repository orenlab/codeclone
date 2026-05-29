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
    agent_label     TEXT    NOT NULL DEFAULT '',
    agent_pid       INTEGER NOT NULL,

    status          TEXT,
    payload_json    TEXT    NOT NULL DEFAULT '{}',

    estimated_tokens    INTEGER,
    token_encoding      TEXT,
    payload_characters  INTEGER
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
    "CREATE INDEX IF NOT EXISTS idx_events_type_time "
    "ON controller_events(event_type, created_at_utc)",
    "CREATE INDEX IF NOT EXISTS idx_events_created "
    "ON controller_events(created_at_utc)",
)


def open_audit_db(path: Path) -> sqlite3.Connection:
    return open_sqlite_db(path, ensure_schema=ensure_schema)


def ensure_schema(conn: sqlite3.Connection) -> None:
    current = get_meta(conn, "schema_version")
    if current is None:
        create_schema_v1(conn)
        return
    if current != AUDIT_SCHEMA_VERSION:
        raise AuditSchemaError(f"Unsupported audit schema version: {current}")
    _migrate_v1_add_token_columns(conn)


def create_schema_v1(conn: sqlite3.Connection) -> None:
    initialize_schema_v1(
        conn,
        ddl_statements=(_CREATE_EVENTS_SQL, _CREATE_META_SQL),
        index_statements=_INDEX_SQL,
        meta_table=_AUDIT_META_TABLE,
        seed_meta={
            "schema_version": AUDIT_SCHEMA_VERSION,
            "generator": "codeclone",
            "codeclone_version": __version__,
            "created_at_utc": current_report_timestamp_utc(),
        },
    )


def _migrate_v1_add_token_columns(conn: sqlite3.Connection) -> None:
    """Add nullable token estimation columns to an existing v1 schema.

    Idempotent: checks which columns already exist before altering.
    """
    existing = {
        row[1]
        for row in conn.execute("PRAGMA table_info(controller_events)").fetchall()
    }
    for col, col_type in (
        ("estimated_tokens", "INTEGER"),
        ("token_encoding", "TEXT"),
        ("payload_characters", "INTEGER"),
    ):
        if col not in existing:
            conn.execute(f"ALTER TABLE controller_events ADD COLUMN {col} {col_type}")
    conn.commit()


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    return get_meta_value(conn, meta_table=_AUDIT_META_TABLE, key=key)


__all__ = [
    "create_schema_v1",
    "ensure_schema",
    "get_meta",
    "open_audit_db",
]
