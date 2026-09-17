# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sqlite3
from pathlib import Path
from urllib.parse import quote

from .. import __version__
from ..contracts import ENGINEERING_MEMORY_SCHEMA_VERSION
from ..report.meta import current_report_timestamp_utc
from ..utils.sqlite_store import (
    initialize_schema_v1,
)
from .exceptions import (
    MemorySchemaAuthorityError,
    MemorySchemaError,
    MemorySchemaUnrecognizedError,
)
from .schema_experience import (
    EXPERIENCE_DDL_STATEMENTS,
    EXPERIENCE_INDEX_SQL,
)
from .schema_fts import CREATE_MEMORY_RECORDS_FTS_SQL
from .schema_jobs import (
    PROJECTION_JOBS_DDL_STATEMENTS,
    PROJECTION_JOBS_INDEX_SQL,
)
from .schema_meta import MEMORY_META_TABLE, get_meta, set_meta
from .schema_trajectory import (
    TRAJECTORY_DDL_STATEMENTS,
    TRAJECTORY_INDEX_SQL,
    create_trajectory_schema,
)

_CREATE_META_SQL = f"""
CREATE TABLE IF NOT EXISTS {MEMORY_META_TABLE} (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""

_CREATE_MIGRATIONS_SQL = """
CREATE TABLE IF NOT EXISTS memory_schema_migrations (
    version        TEXT PRIMARY KEY,
    applied_at_utc TEXT NOT NULL
)
"""

_CREATE_PROJECTS_SQL = """
CREATE TABLE IF NOT EXISTS memory_projects (
    id              TEXT PRIMARY KEY,
    root            TEXT NOT NULL,
    git_remote      TEXT,
    git_branch      TEXT,
    git_head        TEXT,
    python_tag      TEXT,
    created_at_utc  TEXT NOT NULL,
    updated_at_utc  TEXT NOT NULL
)
"""

_CREATE_RECORDS_SQL = """
CREATE TABLE IF NOT EXISTS memory_records (
    id                    TEXT PRIMARY KEY,
    project_id            TEXT NOT NULL,
    identity_key          TEXT NOT NULL,
    type                  TEXT NOT NULL,
    status                TEXT NOT NULL DEFAULT 'active',
    epistemic_rung        TEXT NOT NULL DEFAULT 'supported',
    origin                TEXT NOT NULL DEFAULT 'system',
    ingest_source         TEXT NOT NULL,
    statement             TEXT NOT NULL,
    summary               TEXT,
    payload_json          TEXT,
    created_at_utc        TEXT NOT NULL,
    updated_at_utc        TEXT NOT NULL,
    last_verified_at_utc  TEXT,
    expires_at_utc        TEXT,
    created_by            TEXT NOT NULL,
    verified_by           TEXT,
    approved_by           TEXT,
    approved_at_utc       TEXT,
    report_digest         TEXT,
    code_fingerprint      TEXT,
    stale_reason          TEXT,
    created_on_branch     TEXT,
    created_at_commit     TEXT,
    verified_on_branch    TEXT,
    verified_at_commit    TEXT,
    schema_version        TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES memory_projects(id)
)
"""

_CREATE_SUBJECTS_SQL = """
CREATE TABLE IF NOT EXISTS memory_subjects (
    id            TEXT PRIMARY KEY,
    memory_id     TEXT NOT NULL,
    subject_kind  TEXT NOT NULL,
    subject_key   TEXT NOT NULL,
    relation      TEXT NOT NULL DEFAULT 'about',
    FOREIGN KEY(memory_id) REFERENCES memory_records(id) ON DELETE CASCADE
)
"""

_CREATE_EVIDENCE_SQL = """
CREATE TABLE IF NOT EXISTS memory_evidence (
    id              TEXT PRIMARY KEY,
    memory_id       TEXT NOT NULL,
    evidence_kind   TEXT NOT NULL,
    ref             TEXT NOT NULL,
    locator         TEXT,
    quote           TEXT,
    digest          TEXT,
    created_at_utc  TEXT NOT NULL,
    FOREIGN KEY(memory_id) REFERENCES memory_records(id) ON DELETE CASCADE
)
"""

_CREATE_LINKS_SQL = """
CREATE TABLE IF NOT EXISTS memory_links (
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL,
    from_memory_id  TEXT NOT NULL,
    to_memory_id    TEXT NOT NULL,
    relation        TEXT NOT NULL,
    created_by      TEXT NOT NULL DEFAULT 'system',
    created_at_utc  TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES memory_projects(id),
    FOREIGN KEY(from_memory_id) REFERENCES memory_records(id) ON DELETE CASCADE,
    FOREIGN KEY(to_memory_id) REFERENCES memory_records(id) ON DELETE CASCADE
)
"""

_CREATE_INGESTION_RUNS_SQL = """
CREATE TABLE IF NOT EXISTS memory_ingestion_runs (
    id                      TEXT PRIMARY KEY,
    project_id              TEXT NOT NULL,
    mode                    TEXT NOT NULL,
    started_at_utc          TEXT NOT NULL,
    finished_at_utc         TEXT,
    status                  TEXT NOT NULL DEFAULT 'running',
    analysis_fingerprint    TEXT,
    report_digest           TEXT,
    branch                  TEXT,
    "commit"                TEXT,
    records_created         INTEGER NOT NULL DEFAULT 0,
    records_updated         INTEGER NOT NULL DEFAULT 0,
    records_marked_stale    INTEGER NOT NULL DEFAULT 0,
    candidates_created      INTEGER NOT NULL DEFAULT 0,
    contradictions_found    INTEGER NOT NULL DEFAULT 0,
    message                 TEXT,
    FOREIGN KEY(project_id) REFERENCES memory_projects(id)
)
"""

_CREATE_REVISIONS_SQL = """
CREATE TABLE IF NOT EXISTS memory_revisions (
    id                  TEXT PRIMARY KEY,
    memory_id           TEXT NOT NULL,
    revision_number     INTEGER NOT NULL,
    previous_statement  TEXT,
    new_statement       TEXT NOT NULL,
    previous_payload    TEXT,
    new_payload         TEXT,
    reason              TEXT,
    changed_by          TEXT NOT NULL,
    changed_at_utc      TEXT NOT NULL,
    branch              TEXT,
    "commit"            TEXT,
    FOREIGN KEY(memory_id) REFERENCES memory_records(id) ON DELETE CASCADE
)
"""

_CREATE_BLAST_CACHE_SQL = """
CREATE TABLE IF NOT EXISTS memory_blast_radius_cache (
    id                   TEXT PRIMARY KEY,
    project_id           TEXT NOT NULL,
    subject_key          TEXT NOT NULL,
    subject_kind         TEXT NOT NULL,
    depth                TEXT NOT NULL DEFAULT 'direct',
    payload_json         TEXT NOT NULL,
    analysis_fingerprint TEXT NOT NULL,
    branch               TEXT,
    created_at_utc       TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES memory_projects(id)
)
"""

_DDL_STATEMENTS = (
    _CREATE_META_SQL,
    _CREATE_MIGRATIONS_SQL,
    _CREATE_PROJECTS_SQL,
    _CREATE_RECORDS_SQL,
    _CREATE_SUBJECTS_SQL,
    _CREATE_EVIDENCE_SQL,
    _CREATE_LINKS_SQL,
    _CREATE_INGESTION_RUNS_SQL,
    _CREATE_REVISIONS_SQL,
    _CREATE_BLAST_CACHE_SQL,
    *TRAJECTORY_DDL_STATEMENTS,
    *PROJECTION_JOBS_DDL_STATEMENTS,
    *EXPERIENCE_DDL_STATEMENTS,
)

_INDEX_SQL = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_records_identity "
    "ON memory_records(project_id, identity_key)",
    "CREATE INDEX IF NOT EXISTS idx_records_project_type "
    "ON memory_records(project_id, type)",
    "CREATE INDEX IF NOT EXISTS idx_records_status ON memory_records(status)",
    "CREATE INDEX IF NOT EXISTS idx_records_project_status "
    "ON memory_records(project_id, status, type)",
    "CREATE INDEX IF NOT EXISTS idx_records_origin ON memory_records(origin)",
    "CREATE INDEX IF NOT EXISTS idx_subjects_memory ON memory_subjects(memory_id)",
    "CREATE INDEX IF NOT EXISTS idx_subjects_kind_key "
    "ON memory_subjects(subject_kind, subject_key)",
    "CREATE INDEX IF NOT EXISTS idx_evidence_memory ON memory_evidence(memory_id)",
    "CREATE INDEX IF NOT EXISTS idx_links_from ON memory_links(from_memory_id)",
    "CREATE INDEX IF NOT EXISTS idx_links_to ON memory_links(to_memory_id)",
    "CREATE INDEX IF NOT EXISTS idx_ingestion_runs_project_time "
    "ON memory_ingestion_runs(project_id, started_at_utc)",
    "CREATE INDEX IF NOT EXISTS idx_revisions_memory ON memory_revisions(memory_id)",
    "CREATE INDEX IF NOT EXISTS idx_blast_cache_subject "
    "ON memory_blast_radius_cache(project_id, subject_kind, subject_key)",
    *TRAJECTORY_INDEX_SQL,
    *PROJECTION_JOBS_INDEX_SQL,
    *EXPERIENCE_INDEX_SQL,
)


def open_memory_db(path: Path, *, allow_migration: bool = False) -> sqlite3.Connection:
    """Open (creating if absent) the engineering-memory store at *path*.

    ``allow_migration`` defaults to False: opening a store whose on-disk
    ``schema_version`` differs from ``ENGINEERING_MEMORY_SCHEMA_VERSION`` in
    EITHER direction raises ``MemorySchemaAuthorityError`` instead of
    silently changing it -- see ``ensure_schema``. Initializing a brand new
    store is unaffected either way; only an EXISTING store's version change
    needs authority. Pass ``allow_migration=True`` only from the one
    sanctioned authoritative entry point
    (``codeclone.memory.sqlite_store.migrate_memory_db_authoritative``, or
    an equivalent explicit caller) -- never from an ordinary read, write,
    or status path.

    A present file that is not a store at all (a SQLite database with tables
    of its own and no ``memory_meta``) is refused with
    ``MemorySchemaUnrecognizedError`` BEFORE the read-write open, so it is not
    initialized into and not touched -- see ``_refuse_unrecognized_store``.
    """
    from ..observability.sqlite_access import open_instrumented_sqlite_db

    _refuse_unrecognized_store(path)

    def _ensure(conn: sqlite3.Connection) -> None:
        ensure_schema(conn, allow_migration=allow_migration)

    return open_instrumented_sqlite_db(
        path,
        ensure_schema=_ensure,
        foreign_keys=True,
        synchronous="FULL",
    )


def _holds_foreign_tables(conn: sqlite3.Connection) -> bool:
    """Whether *conn* is a database with tables of its own and no ``memory_meta``.

    The one predicate behind "may this database be initialized as a store":
    an EMPTY database (no tables at all -- a file ``sqlite3.connect`` just
    created, or one an interrupted first init left behind) may; a database
    already holding somebody's tables may not. A ``memory_meta`` table means
    the store is ours, and then its VERSION decides, never this predicate.
    """
    names = {
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    return bool(names) and MEMORY_META_TABLE not in names


def _unrecognized_message(where: str) -> str:
    return (
        f"{where} is not an Engineering Memory store: it is a SQLite database "
        f"with tables of its own and no {MEMORY_META_TABLE!r} table. codeclone "
        "does not initialize or migrate a database it does not recognize; move "
        "the file aside or configure a different memory store path. The file "
        "was not modified."
    )


def _refuse_unrecognized_store(path: Path) -> None:
    """Refuse a present file that is not a store BEFORE any read-write open.

    ``open_sqlite_db`` issues ``PRAGMA journal_mode=WAL`` ahead of
    ``ensure_schema``, and moving a rollback-journal file to WAL rewrites its
    header -- so a refusal raised from the schema check would already have
    altered somebody else's database. The look is therefore taken here,
    through a read-only URI, and only for a path that exists: a missing path
    is created as before, and an existing EMPTY database is a brand-new store
    and initializes as it always has.
    """
    if not path.is_file():
        return
    uri = f"file:{quote(str(path.resolve()), safe='/')}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        foreign = _holds_foreign_tables(conn)
    finally:
        conn.close()
    if foreign:
        raise MemorySchemaUnrecognizedError(
            _unrecognized_message(f"The file at {path}")
        )


def open_memory_db_readonly(path: Path) -> sqlite3.Connection:
    """Open an existing engineering-memory database without allowing writes."""
    from ..observability.sqlite_access import open_instrumented_sqlite_db_readonly

    conn = open_instrumented_sqlite_db_readonly(
        path,
        validate_schema=validate_schema_readonly,
    )
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema(conn: sqlite3.Connection, *, allow_migration: bool = False) -> None:
    """Bring *conn* to ``ENGINEERING_MEMORY_SCHEMA_VERSION``, or refuse.

    Creating a brand new store (no ``schema_version`` meta row yet, and no
    tables of anybody's) is initialization, not migration, and always
    proceeds -- there is no existing schema for anyone else to be relying
    on. A database that already holds tables and no ``memory_meta`` is not
    a brand new store but somebody else's database, and is refused with
    ``MemorySchemaUnrecognizedError`` instead. Changing an EXISTING
    store's version is a privileged mutation: without ``allow_migration``
    this raises ``MemorySchemaAuthorityError`` and leaves the store
    byte-for-byte unchanged, in EITHER direction (this checkout's code
    ahead of the store, or behind it) -- "whoever opened SQLite first"
    is no longer authority to migrate anything. See
    ``codeclone.memory.schema_migrate.migrate_memory_schema_authoritative``
    for the one sanctioned way to actually change an existing store.
    """
    current = get_meta(conn, "schema_version")
    if current is None:
        if _holds_foreign_tables(conn):
            raise MemorySchemaUnrecognizedError(
                _unrecognized_message("The opened database")
            )
        create_schema_v1(conn)
        return
    from .schema_migrate import reconcile_memory_record_schema_versions

    if current != ENGINEERING_MEMORY_SCHEMA_VERSION:
        if not allow_migration:
            raise MemorySchemaAuthorityError(
                "Engineering memory schema is "
                f"{current!r} on disk; this checkout expects "
                f"{ENGINEERING_MEMORY_SCHEMA_VERSION!r}. Opening here would "
                "change an EXISTING store's schema, which only an explicit "
                "authoritative migration may do -- run `codeclone memory "
                "migrate` (or "
                "codeclone.memory.sqlite_store.migrate_memory_db_authoritative) "
                "from one checkout, or use a codeclone checkout whose "
                "version matches this store. The store was not modified."
            )
        from .schema_migrate import migrate_memory_schema_authoritative

        migrate_memory_schema_authoritative(conn)
        current = get_meta(conn, "schema_version")
    if current != ENGINEERING_MEMORY_SCHEMA_VERSION:
        raise MemorySchemaError(
            "Unsupported engineering memory schema version: "
            f"{current!r}. Expected {ENGINEERING_MEMORY_SCHEMA_VERSION!r}."
        )
    reconcile_memory_record_schema_versions(conn)


def validate_schema_readonly(conn: sqlite3.Connection) -> None:
    """Validate an existing memory database without initializing or migrating."""

    current = get_meta(conn, "schema_version")
    if current != ENGINEERING_MEMORY_SCHEMA_VERSION:
        raise MemorySchemaError(
            "Engineering Memory requires writable schema initialization or migration: "
            f"found {current!r}, expected {ENGINEERING_MEMORY_SCHEMA_VERSION!r}."
        )


def create_schema_v1(conn: sqlite3.Connection) -> None:
    now = current_report_timestamp_utc()
    initialize_schema_v1(
        conn,
        ddl_statements=_DDL_STATEMENTS,
        index_statements=_INDEX_SQL,
        meta_table=MEMORY_META_TABLE,
        seed_meta={
            "schema_version": ENGINEERING_MEMORY_SCHEMA_VERSION,
            "created_at_utc": now,
            "updated_at_utc": now,
            "codeclone_version": __version__,
        },
    )
    conn.execute(
        "INSERT OR IGNORE INTO memory_schema_migrations(version, applied_at_utc) "
        "VALUES (?, ?)",
        (ENGINEERING_MEMORY_SCHEMA_VERSION, now),
    )
    conn.execute(CREATE_MEMORY_RECORDS_FTS_SQL)
    conn.commit()


__all__ = [
    "MemorySchemaAuthorityError",
    "MemorySchemaError",
    "MemorySchemaUnrecognizedError",
    "create_schema_v1",
    "create_trajectory_schema",
    "ensure_schema",
    "get_meta",
    "open_memory_db",
    "open_memory_db_readonly",
    "set_meta",
    "validate_schema_readonly",
]
