# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sqlite3

from ..report.meta import current_report_timestamp_utc
from .exceptions import MemorySchemaError
from .schema_fts import CREATE_MEMORY_RECORDS_FTS_SQL
from .schema_meta import get_meta, set_meta


def migrate_memory_schema(conn: sqlite3.Connection) -> None:
    from ..contracts import ENGINEERING_MEMORY_SCHEMA_VERSION

    current = get_meta(conn, "schema_version")
    if current is None:
        return
    if current == ENGINEERING_MEMORY_SCHEMA_VERSION:
        return
    if current == "1.0":
        _migrate_1_0_to_1_1(conn)
        current = "1.1"
    if current == "1.1":
        _migrate_1_1_to_1_2(conn)
        current = "1.2"
    later = {"1.3", "1.4", "1.5", "1.6", "1.7"}
    if current == "1.2" and ENGINEERING_MEMORY_SCHEMA_VERSION in later:
        _migrate_1_2_to_1_3(conn)
        current = "1.3"
    if current == "1.3" and ENGINEERING_MEMORY_SCHEMA_VERSION in later - {"1.3"}:
        _migrate_1_3_to_1_4(conn)
        current = "1.4"
    if current == "1.4" and ENGINEERING_MEMORY_SCHEMA_VERSION in {"1.5", "1.6", "1.7"}:
        _migrate_1_4_to_1_5(conn)
        current = "1.5"
    if current == "1.5" and ENGINEERING_MEMORY_SCHEMA_VERSION in {"1.6", "1.7"}:
        _migrate_1_5_to_1_6(conn)
        current = "1.6"
    if current == "1.6" and ENGINEERING_MEMORY_SCHEMA_VERSION == "1.7":
        _migrate_1_6_to_1_7(conn)
        current = "1.7"
    if current == ENGINEERING_MEMORY_SCHEMA_VERSION:
        return
    msg = (
        f"Unsupported engineering memory schema migration: {current!r} "
        f"→ {ENGINEERING_MEMORY_SCHEMA_VERSION!r}"
    )
    raise MemorySchemaError(msg)


def _migrate_1_0_to_1_1(conn: sqlite3.Connection) -> None:
    conn.execute(CREATE_MEMORY_RECORDS_FTS_SQL)
    now = current_report_timestamp_utc()
    set_meta(conn, "schema_version", "1.1")
    conn.execute(
        "INSERT OR IGNORE INTO memory_schema_migrations(version, applied_at_utc) "
        "VALUES (?, ?)",
        ("1.1", now),
    )
    conn.commit()


def _migrate_1_1_to_1_2(conn: sqlite3.Connection) -> None:
    from .schema_trajectory import create_trajectory_schema

    create_trajectory_schema(conn)
    now = current_report_timestamp_utc()
    set_meta(conn, "schema_version", "1.2")
    conn.execute(
        "INSERT OR IGNORE INTO memory_schema_migrations(version, applied_at_utc) "
        "VALUES (?, ?)",
        ("1.2", now),
    )
    conn.commit()


def _migrate_1_2_to_1_3(conn: sqlite3.Connection) -> None:
    from .schema_jobs import create_projection_jobs_schema

    create_projection_jobs_schema(conn)
    now = current_report_timestamp_utc()
    set_meta(conn, "schema_version", "1.3")
    conn.execute(
        "INSERT OR IGNORE INTO memory_schema_migrations(version, applied_at_utc) "
        "VALUES (?, ?)",
        ("1.3", now),
    )
    conn.commit()


def _migrate_1_3_to_1_4(conn: sqlite3.Connection) -> None:
    from .schema_trajectory import create_patch_trails_schema

    create_patch_trails_schema(conn)
    now = current_report_timestamp_utc()
    set_meta(conn, "schema_version", "1.4")
    conn.execute(
        "INSERT OR IGNORE INTO memory_schema_migrations(version, applied_at_utc) "
        "VALUES (?, ?)",
        ("1.4", now),
    )
    conn.commit()


def _add_column_if_missing(
    conn: sqlite3.Connection, *, table: str, column: str, ddl_type: str
) -> None:
    existing = {
        str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")


def _record_schema_migration(conn: sqlite3.Connection, version: str) -> None:
    now = current_report_timestamp_utc()
    set_meta(conn, "schema_version", version)
    conn.execute(
        "INSERT OR IGNORE INTO memory_schema_migrations(version, applied_at_utc) "
        "VALUES (?, ?)",
        (version, now),
    )
    conn.commit()


def _migrate_1_4_to_1_5(conn: sqlite3.Connection) -> None:
    _add_column_if_missing(
        conn,
        table="memory_trajectories",
        column="quality_score",
        ddl_type="INTEGER NOT NULL DEFAULT 0",
    )
    _record_schema_migration(conn, "1.5")


def _migrate_1_5_to_1_6(conn: sqlite3.Connection) -> None:
    from .schema_experience import create_experience_schema

    create_experience_schema(conn)
    now = current_report_timestamp_utc()
    set_meta(conn, "schema_version", "1.6")
    conn.execute(
        "INSERT OR IGNORE INTO memory_schema_migrations(version, applied_at_utc) "
        "VALUES (?, ?)",
        ("1.6", now),
    )
    conn.commit()


def _migrate_1_6_to_1_7(conn: sqlite3.Connection) -> None:
    _add_column_if_missing(
        conn,
        table="memory_projection_jobs",
        column="flush_claimed_by",
        ddl_type="TEXT",
    )
    _record_schema_migration(conn, "1.7")


__all__ = ["migrate_memory_schema"]
