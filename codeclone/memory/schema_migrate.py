# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sqlite3

import orjson

from ..report.meta import current_report_timestamp_utc
from .enums import (
    validate_memory_confidence,
    validate_memory_ingest_source,
    validate_memory_origin,
    validate_memory_record_type,
    validate_memory_status,
)
from .exceptions import MemorySchemaError
from .models import MemoryRecord, validate_memory_record
from .schema_fts import CREATE_MEMORY_RECORDS_FTS_SQL
from .schema_meta import get_meta, set_meta

_SUPPORTED_LEGACY_RECORD_SCHEMA_VERSIONS = (
    "1.0",
    "1.1",
    "1.2",
    "1.3",
    "1.4",
    "1.5",
    "1.6",
)
_RECORD_SCHEMA_RECONCILE_SAVEPOINT = "memory_record_schema_reconcile"
_RECORD_COLUMNS = (
    "id",
    "project_id",
    "identity_key",
    "type",
    "status",
    "confidence",
    "origin",
    "ingest_source",
    "statement",
    "summary",
    "payload_json",
    "created_at_utc",
    "updated_at_utc",
    "last_verified_at_utc",
    "expires_at_utc",
    "created_by",
    "verified_by",
    "approved_by",
    "approved_at_utc",
    "report_digest",
    "code_fingerprint",
    "stale_reason",
    "created_on_branch",
    "created_at_commit",
    "verified_on_branch",
    "verified_at_commit",
    "schema_version",
)


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


def reconcile_memory_record_schema_versions(conn: sqlite3.Connection) -> int:
    """Promote supported legacy record rows only after current-contract validation.

    The per-row ``memory_records.schema_version`` is treated as the record format
    discriminator. Supported legacy rows are decoded, normalized to the current
    canonical record shape, and validated before their discriminator is updated.
    Unsupported or malformed rows stay on their original version and therefore
    remain quarantined by canonical read filters.
    """

    from ..contracts import ENGINEERING_MEMORY_SCHEMA_VERSION

    rows = _supported_legacy_record_rows(conn)
    if not rows:
        return 0

    migrated = 0
    conn.execute(f"SAVEPOINT {_RECORD_SCHEMA_RECONCILE_SAVEPOINT}")
    try:
        for row in rows:
            candidate = _current_record_from_supported_legacy_row(row)
            if candidate is None:
                continue
            _write_current_record_schema_version(
                conn,
                record_id=candidate.id,
                legacy_version=row["schema_version"],
                current_version=ENGINEERING_MEMORY_SCHEMA_VERSION,
            )
            migrated += 1
    except BaseException:
        conn.execute(f"ROLLBACK TO {_RECORD_SCHEMA_RECONCILE_SAVEPOINT}")
        conn.execute(f"RELEASE {_RECORD_SCHEMA_RECONCILE_SAVEPOINT}")
        raise
    conn.execute(f"RELEASE {_RECORD_SCHEMA_RECONCILE_SAVEPOINT}")
    return migrated


def _supported_legacy_record_rows(
    conn: sqlite3.Connection,
) -> list[dict[str, object]]:
    placeholders = ", ".join("?" for _ in _SUPPORTED_LEGACY_RECORD_SCHEMA_VERSIONS)
    rows = conn.execute(
        "SELECT "
        + ", ".join(_RECORD_COLUMNS)
        + f" FROM memory_records WHERE schema_version IN ({placeholders}) "
        "ORDER BY project_id ASC, identity_key ASC, id ASC",
        _SUPPORTED_LEGACY_RECORD_SCHEMA_VERSIONS,
    ).fetchall()
    return [dict(zip(_RECORD_COLUMNS, row, strict=True)) for row in rows]


def _current_record_from_supported_legacy_row(
    row: dict[str, object],
) -> MemoryRecord | None:
    from ..contracts import ENGINEERING_MEMORY_SCHEMA_VERSION

    try:
        record = MemoryRecord(
            id=_required_text(row, "id"),
            project_id=_required_text(row, "project_id"),
            identity_key=_required_text(row, "identity_key"),
            type=validate_memory_record_type(_required_text(row, "type")),
            status=validate_memory_status(_required_text(row, "status")),
            confidence=validate_memory_confidence(_required_text(row, "confidence")),
            origin=validate_memory_origin(_required_text(row, "origin")),
            ingest_source=validate_memory_ingest_source(
                _required_text(row, "ingest_source")
            ),
            statement=_required_text(row, "statement"),
            summary=_optional_text(row, "summary"),
            payload=_strict_payload_json(row["payload_json"]),
            created_at_utc=_required_text(row, "created_at_utc"),
            updated_at_utc=_required_text(row, "updated_at_utc"),
            last_verified_at_utc=_optional_text(row, "last_verified_at_utc"),
            expires_at_utc=_optional_text(row, "expires_at_utc"),
            created_by=_required_text(row, "created_by"),
            verified_by=_optional_text(row, "verified_by"),
            approved_by=_optional_text(row, "approved_by"),
            approved_at_utc=_optional_text(row, "approved_at_utc"),
            report_digest=_optional_text(row, "report_digest"),
            code_fingerprint=_optional_text(row, "code_fingerprint"),
            stale_reason=_optional_text(row, "stale_reason"),
            created_on_branch=_optional_text(row, "created_on_branch"),
            created_at_commit=_optional_text(row, "created_at_commit"),
            verified_on_branch=_optional_text(row, "verified_on_branch"),
            verified_at_commit=_optional_text(row, "verified_at_commit"),
            schema_version=ENGINEERING_MEMORY_SCHEMA_VERSION,
        )
        return validate_memory_record(record)
    except (KeyError, TypeError, ValueError, orjson.JSONDecodeError):
        return None


def _strict_payload_json(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("payload_json must be text or NULL")
    if not value.strip():
        return None
    loaded = orjson.loads(value)
    if not isinstance(loaded, dict):
        raise ValueError("payload_json must decode to an object")
    if not all(isinstance(key, str) for key in loaded):
        raise ValueError("payload_json object keys must be strings")
    return loaded


def _required_text(row: dict[str, object], key: str) -> str:
    value = row[key]
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be non-empty text")
    return value


def _optional_text(row: dict[str, object], key: str) -> str | None:
    value = row[key]
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be text or NULL")
    return value


def _write_current_record_schema_version(
    conn: sqlite3.Connection,
    *,
    record_id: str,
    legacy_version: object,
    current_version: str,
) -> None:
    conn.execute(
        """
        UPDATE memory_records
        SET schema_version=?
        WHERE id=? AND schema_version=?
        """,
        (current_version, record_id, legacy_version),
    )


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


__all__ = ["migrate_memory_schema", "reconcile_memory_record_schema_versions"]
