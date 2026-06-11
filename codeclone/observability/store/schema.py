# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Observability sqlite schema (Phase 29 §4.5).

Two tables — operations (surface-level) and spans (stage/subsystem) — plus a
meta row carrying the schema version. Profile columns are nullable
(populated only when ``profile=true`` with the ``codeclone[perf]`` extra).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ...contracts import PLATFORM_OBSERVABILITY_SCHEMA_VERSION

_OBSERVABILITY_DB_RELATIVE = ".codeclone/db/platform_observability.sqlite3"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS platform_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS platform_operations (
    operation_id TEXT PRIMARY KEY,
    parent_operation_id TEXT,
    correlation_id TEXT NOT NULL,
    surface TEXT NOT NULL,
    name TEXT NOT NULL,
    started_at_utc TEXT NOT NULL,
    duration_ms REAL NOT NULL,
    status TEXT NOT NULL,
    error_kind TEXT,
    session_id TEXT,
    repo_root_digest TEXT,
    request_bytes INTEGER,
    response_bytes INTEGER,
    request_tokens INTEGER,
    response_tokens INTEGER,
    rss_mb REAL,
    rss_delta_mb REAL,
    cpu_user_ms REAL,
    cpu_system_ms REAL,
    open_fds INTEGER,
    thread_count INTEGER
);

CREATE TABLE IF NOT EXISTS platform_spans (
    span_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL,
    parent_span_id TEXT,
    name TEXT NOT NULL,
    started_at_utc TEXT NOT NULL,
    duration_ms REAL NOT NULL,
    status TEXT NOT NULL,
    reason_kind TEXT,
    reason TEXT,
    dedupe_key TEXT,
    counters_json TEXT,
    db_fingerprints TEXT,
    rss_mb REAL,
    rss_delta_mb REAL,
    cpu_user_ms REAL,
    cpu_system_ms REAL,
    open_fds INTEGER,
    thread_count INTEGER
);

CREATE INDEX IF NOT EXISTS idx_platform_operations_session
    ON platform_operations (session_id, started_at_utc);
CREATE INDEX IF NOT EXISTS idx_platform_operations_correlation
    ON platform_operations (correlation_id);
CREATE INDEX IF NOT EXISTS idx_platform_operations_parent
    ON platform_operations (parent_operation_id);
CREATE INDEX IF NOT EXISTS idx_platform_spans_operation
    ON platform_spans (operation_id);
"""


def observability_store_path(root: Path) -> Path:
    return root.resolve() / _OBSERVABILITY_DB_RELATIVE


def _ensure_span_columns(conn: sqlite3.Connection) -> None:
    """Additive migration for stores created before a span column existed.

    ``CREATE TABLE IF NOT EXISTS`` never alters an existing table, so a store
    written by an older build keeps its old shape. This backfills the column
    with ``ALTER TABLE ... ADD COLUMN`` (a no-op on fresh stores, which already
    have it from ``_SCHEMA``) so writes/reads stay forward-compatible without a
    destructive rebuild of disposable telemetry.
    """
    existing = {row[1] for row in conn.execute("PRAGMA table_info(platform_spans)")}
    if "db_fingerprints" not in existing:
        conn.execute("ALTER TABLE platform_spans ADD COLUMN db_fingerprints TEXT")


def create_observability_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    _ensure_span_columns(conn)
    conn.execute(
        "INSERT OR REPLACE INTO platform_meta(key, value) VALUES('schema_version', ?)",
        (PLATFORM_OBSERVABILITY_SCHEMA_VERSION,),
    )
    conn.commit()


def open_observability_store(path: Path) -> sqlite3.Connection:
    """Open (creating the parent dir + schema) the observability store."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    create_observability_schema(conn)
    return conn


__all__ = [
    "create_observability_schema",
    "observability_store_path",
    "open_observability_store",
]
