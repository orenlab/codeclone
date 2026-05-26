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
from .validation import AUDIT_SCHEMA_VERSION, AuditSchemaError

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
    payload_json    TEXT    NOT NULL DEFAULT '{}'
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
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), isolation_level="DEFERRED", timeout=5.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("PRAGMA busy_timeout=5000")
        ensure_schema(conn)
    except Exception:
        conn.close()
        raise
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    current = get_meta(conn, "schema_version")
    if current is None:
        create_schema_v1(conn)
        return
    if current == AUDIT_SCHEMA_VERSION:
        return
    raise AuditSchemaError(f"Unsupported audit schema version: {current}")


def create_schema_v1(conn: sqlite3.Connection) -> None:
    conn.execute(_CREATE_EVENTS_SQL)
    conn.execute(_CREATE_META_SQL)
    for statement in _INDEX_SQL:
        conn.execute(statement)
    now = current_report_timestamp_utc()
    seed_meta = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "generator": "codeclone",
        "codeclone_version": __version__,
        "created_at_utc": now,
    }
    conn.executemany(
        "INSERT OR IGNORE INTO audit_meta(key, value) VALUES (?, ?)",
        sorted(seed_meta.items()),
    )
    conn.commit()


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    try:
        row = conn.execute(
            "SELECT value FROM audit_meta WHERE key = ?",
            (key,),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None:
        return None
    value = row[0]
    return value if isinstance(value, str) else None


__all__ = [
    "create_schema_v1",
    "ensure_schema",
    "get_meta",
    "open_audit_db",
]
