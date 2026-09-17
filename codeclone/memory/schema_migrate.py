# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os
import socket
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Final

import orjson

from ..models import MemorySchemaMigrationOutcome, deadline_passed
from ..report.meta import current_report_timestamp_utc
from .enums import (
    validate_memory_epistemic_rung,
    validate_memory_ingest_source,
    validate_memory_origin,
    validate_memory_record_type,
    validate_memory_status,
)
from .exceptions import MemorySchemaError, MemorySchemaMigrationInProgressError
from .models import MemoryRecord, validate_memory_record
from .schema_fts import CREATE_MEMORY_RECORDS_FTS_SQL
from .schema_meta import MEMORY_META_TABLE, get_meta, set_meta

#: Meta-table key carrying the schema-migration lease (see
#: ``acquire_schema_migration_lease``). Lives in ``memory_meta``, present
#: since schema 1.0 -- before any versioned migration ever runs -- so no new
#: table and no schema bump are needed to gate migration authority.
_SCHEMA_MIGRATION_LEASE_META_KEY: Final = "schema_migration_lease"
DEFAULT_SCHEMA_MIGRATION_LEASE_TTL_SECONDS: Final[int] = 120

_SUPPORTED_LEGACY_RECORD_SCHEMA_VERSIONS = (
    "1.0",
    "1.1",
    "1.2",
    "1.3",
    "1.4",
    "1.5",
    "1.6",
    "1.7",
)
_RECORD_SCHEMA_RECONCILE_SAVEPOINT = "memory_record_schema_reconcile"
_RECORD_COLUMNS = (
    "id",
    "project_id",
    "identity_key",
    "type",
    "status",
    "epistemic_rung",
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


def _default_migration_holder() -> str:
    """Diagnostic-only label for who asked for the lease.

    Never read back for authority -- see ``acquire_schema_migration_lease``.
    """
    return f"{os.getpid()}@{socket.gethostname()}"


def _new_migration_lease_token() -> str:
    """A fresh, unguessable fencing token for one migration-lease grant."""
    return f"schema-migration-{uuid.uuid4().hex}"


def _migration_lease_deadline(payload: object) -> datetime | None:
    """The deadline past which a stored migration-lease grant is stale.

    Mirrors ``codeclone.memory.jobs.store._projection_job_lease_deadline``:
    anchor (``acquired_at_utc``) plus the TTL granted at that anchor,
    decided by ``codeclone.models.deadline_passed`` -- never by the
    recorded holder's OS PID. Returns ``None`` (an already-passed deadline,
    per that law) when the payload cannot be parsed at all.
    """
    grant: dict[str, object] = payload if isinstance(payload, dict) else {}
    ttl = grant.get("ttl_seconds")
    if isinstance(ttl, bool) or not isinstance(ttl, int):
        return None
    try:
        acquired = datetime.fromisoformat(
            str(grant["acquired_at_utc"]).replace("Z", "+00:00")
        )
    except (KeyError, ValueError):
        return None
    if acquired.tzinfo is None:
        acquired = acquired.replace(tzinfo=timezone.utc)
    return acquired + timedelta(seconds=max(1, ttl))


def acquire_schema_migration_lease(
    conn: sqlite3.Connection,
    *,
    holder: str,
    ttl_seconds: int = DEFAULT_SCHEMA_MIGRATION_LEASE_TTL_SECONDS,
) -> str | None:
    """Grant exclusive authority to migrate this store's schema.

    Same ownership law as ``codeclone.canonical.store.acquire_run_lease``
    and the ``memory_projection_jobs`` lease
    (``codeclone.memory.jobs.store.claim_next_projection_job``): a
    positive-TTL grant with an unguessable fencing token, decided purely by
    :func:`codeclone.models.deadline_passed`. ``holder`` (pid@host) is
    recorded for diagnostics only and is never read back for authority --
    a live process, a zombie, and a reused PID all read the same lease row
    the same way.

    ``BEGIN IMMEDIATE`` takes SQLite's write lock before this reads the
    existing grant, so the read-check-write is atomic against any other
    connection racing the same call on the same file: two concurrent
    callers cannot both observe "no live grant" and both proceed.

    Returns the fencing token on success. Returns ``None`` when a live
    grant is already held by a different token -- the caller MUST treat
    that as a typed refusal, never as "already migrated" (the store may
    still be behind; ask again once the current holder finishes or its
    lease expires).
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            f"SELECT value FROM {MEMORY_META_TABLE} WHERE key=?",
            (_SCHEMA_MIGRATION_LEASE_META_KEY,),
        ).fetchone()
        if row is not None:
            try:
                existing = orjson.loads(row[0])
            except orjson.JSONDecodeError:
                existing = None
            if not deadline_passed(
                _migration_lease_deadline(existing), datetime.now(timezone.utc)
            ):
                conn.execute("COMMIT")
                return None
        token = _new_migration_lease_token()
        payload = orjson.dumps(
            {
                "token": token,
                "holder": holder,
                "acquired_at_utc": current_report_timestamp_utc(),
                "ttl_seconds": ttl_seconds,
            }
        ).decode("utf-8")
        conn.execute(
            f"INSERT INTO {MEMORY_META_TABLE}(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (_SCHEMA_MIGRATION_LEASE_META_KEY, payload),
        )
        conn.execute("COMMIT")
        return token
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def release_schema_migration_lease(conn: sqlite3.Connection, *, token: str) -> bool:
    """Clear the migration lease iff *token* still holds it (fencing).

    False, never raised, when the lease already expired and was reclaimed
    by a new holder, or was already released -- both ordinary outcomes a
    caller that finished late (or twice) must expect. Fencing here is what
    stops a late/duplicate release from destroying a DIFFERENT holder's
    live grant.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            f"SELECT value FROM {MEMORY_META_TABLE} WHERE key=?",
            (_SCHEMA_MIGRATION_LEASE_META_KEY,),
        ).fetchone()
        if row is None:
            conn.execute("COMMIT")
            return False
        try:
            existing = orjson.loads(row[0])
        except orjson.JSONDecodeError:
            existing = None
        if not isinstance(existing, dict) or existing.get("token") != token:
            conn.execute("COMMIT")
            return False
        conn.execute(
            f"DELETE FROM {MEMORY_META_TABLE} WHERE key=?",
            (_SCHEMA_MIGRATION_LEASE_META_KEY,),
        )
        conn.execute("COMMIT")
        return True
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def migrate_memory_schema_authoritative(
    conn: sqlite3.Connection,
    *,
    holder: str | None = None,
    ttl_seconds: int = DEFAULT_SCHEMA_MIGRATION_LEASE_TTL_SECONDS,
) -> MemorySchemaMigrationOutcome:
    """The one sanctioned way to change an EXISTING store's schema version.

    Never called implicitly by opening the store for ordinary read or
    write -- see ``codeclone.memory.schema.ensure_schema``'s
    ``allow_migration`` gate, which raises
    ``MemorySchemaAuthorityError`` instead of reaching here unless the
    caller opted in. A brand new store (no ``schema_version`` meta row
    yet) is initialization, not migration, and is not this function's
    concern -- ``ensure_schema`` handles it before ``allow_migration`` is
    even consulted.

    Acquires :func:`acquire_schema_migration_lease`; raises
    :class:`MemorySchemaMigrationInProgressError` (a typed refusal, zero
    mutation) when a live grant is already held elsewhere. Otherwise
    re-reads the version UNDER the lease (so a caller that wins the lease
    after someone else already finished correctly reports ``migrated``
    False rather than falsely claiming credit), runs the existing
    :func:`migrate_memory_schema` chain unchanged, and releases the lease
    in a ``finally`` so a raised exception from the chain itself never
    leaves the lease dangling for its own TTL.
    """
    from ..contracts import ENGINEERING_MEMORY_SCHEMA_VERSION

    probe = get_meta(conn, "schema_version")
    if probe is None or probe == ENGINEERING_MEMORY_SCHEMA_VERSION:
        return MemorySchemaMigrationOutcome(
            from_version=probe,
            to_version=ENGINEERING_MEMORY_SCHEMA_VERSION,
            migrated=False,
        )
    token = acquire_schema_migration_lease(
        conn, holder=holder or _default_migration_holder(), ttl_seconds=ttl_seconds
    )
    if token is None:
        raise MemorySchemaMigrationInProgressError(
            "Engineering memory schema migration is already in progress "
            "(another process holds the migration lease); retry shortly."
        )
    try:
        before = get_meta(conn, "schema_version")
        migrate_memory_schema(conn)
        after = get_meta(conn, "schema_version")
        return MemorySchemaMigrationOutcome(
            from_version=before,
            to_version=ENGINEERING_MEMORY_SCHEMA_VERSION,
            migrated=before != after,
        )
    finally:
        release_schema_migration_lease(conn, token=token)


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
    later = {"1.3", "1.4", "1.5", "1.6", "1.7", "1.8", "1.9"}
    if current == "1.2" and ENGINEERING_MEMORY_SCHEMA_VERSION in later:
        _migrate_1_2_to_1_3(conn)
        current = "1.3"
    if current == "1.3" and ENGINEERING_MEMORY_SCHEMA_VERSION in later - {"1.3"}:
        _migrate_1_3_to_1_4(conn)
        current = "1.4"
    if current == "1.4" and ENGINEERING_MEMORY_SCHEMA_VERSION in {
        "1.5",
        "1.6",
        "1.7",
        "1.8",
        "1.9",
    }:
        _migrate_1_4_to_1_5(conn)
        current = "1.5"
    if current == "1.5" and ENGINEERING_MEMORY_SCHEMA_VERSION in {
        "1.6",
        "1.7",
        "1.8",
        "1.9",
    }:
        _migrate_1_5_to_1_6(conn)
        current = "1.6"
    if current == "1.6" and ENGINEERING_MEMORY_SCHEMA_VERSION in {"1.7", "1.8", "1.9"}:
        _migrate_1_6_to_1_7(conn)
        current = "1.7"
    if current == "1.7" and ENGINEERING_MEMORY_SCHEMA_VERSION in {"1.8", "1.9"}:
        _migrate_1_7_to_1_8(conn)
        current = "1.8"
    if current == "1.8" and ENGINEERING_MEMORY_SCHEMA_VERSION == "1.9":
        _migrate_1_8_to_1_9(conn)
        current = "1.9"
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
            epistemic_rung=validate_memory_epistemic_rung(
                _required_text(row, "epistemic_rung")
            ),
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


def _migrate_1_7_to_1_8(conn: sqlite3.Connection) -> None:
    """Rename the record rung column ``confidence`` -> ``epistemic_rung``.

    The column never measured confidence in anything. It records which
    extractor produced the row and how far its author was willing to vouch
    for his own extraction -- a denormalised provenance class, written as a
    literal at every producer and computed nowhere. It shared its old name
    with the unrelated ``high|medium|low`` analysis signal on reachability
    routes, dead-code items and report suggestions; that name stays with the
    analysis lane, which is older, wider and published in the report schema.

    Values are carried across untouched: this is a rename, not a
    reclassification, and no row changes rung.
    """
    existing = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(memory_records)").fetchall()
    }
    if "epistemic_rung" not in existing and "confidence" in existing:
        conn.execute(
            "ALTER TABLE memory_records RENAME COLUMN confidence TO epistemic_rung"
        )
    _record_schema_migration(conn, "1.8")


def _migrate_1_8_to_1_9(conn: sqlite3.Connection) -> None:
    """Add lease + fencing columns to ``memory_projection_jobs``.

    Replaces OS-PID liveness as the authority for reclaiming a running
    projection job with a renew-or-expire lease plus a fencing token -- the
    same one hold-deadline law already used by the canonical run-store lease
    (``codeclone.canonical.store.acquire_run_lease``) and the workspace-intent
    lease (``codeclone.workspace_intent.lifecycle.is_lease_expired``), both of
    which decide through ``codeclone.models.deadline_passed``. A PID can be a
    zombie, be reused by the OS, belong to a live-but-hung worker, or simply
    outlive the process that used to own it -- none of that is authority to
    keep or reclaim a job; only the lease is.

    A bare ``ALTER TABLE`` per column, same shape as the 1.6 -> 1.7 migration
    that added ``flush_claimed_by``: pre-existing rows get NULL lease columns,
    not a recreate, so no job history is lost. A 'running' row still on NULL
    lease columns after this migration (only possible for a claim already
    in flight at the moment of upgrade) falls back to its own
    ``started_at_utc`` plus the caller's configured timeout -- see
    ``_projection_job_lease_deadline`` in ``codeclone/memory/jobs/store.py`` --
    which is exactly the deadline that claim already had before the upgrade,
    so it is neither killed early nor trusted forever.
    """
    for column, ddl_type in (
        ("lease_token", "TEXT"),
        ("lease_renewed_at_utc", "TEXT"),
        ("lease_seconds", "INTEGER"),
    ):
        _add_column_if_missing(
            conn,
            table="memory_projection_jobs",
            column=column,
            ddl_type=ddl_type,
        )
    _record_schema_migration(conn, "1.9")


__all__ = [
    "DEFAULT_SCHEMA_MIGRATION_LEASE_TTL_SECONDS",
    "MemorySchemaMigrationOutcome",
    "acquire_schema_migration_lease",
    "migrate_memory_schema",
    "migrate_memory_schema_authoritative",
    "reconcile_memory_record_schema_versions",
    "release_schema_migration_lease",
]
