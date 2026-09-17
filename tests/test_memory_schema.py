# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

import codeclone.memory.schema as schema_module
from codeclone.contracts import ENGINEERING_MEMORY_SCHEMA_VERSION
from codeclone.memory import schema_migrate
from codeclone.memory.exceptions import (
    MemorySchemaAuthorityError,
    MemorySchemaError,
    MemorySchemaMigrationInProgressError,
)
from codeclone.memory.identity import make_identity_key
from codeclone.memory.models import (
    MemoryRecord,
    generate_memory_id,
    payload_json_text,
)
from codeclone.memory.project import resolve_project_identity
from codeclone.memory.schema import (
    create_schema_v1,
    ensure_schema,
    get_meta,
    open_memory_db,
)
from codeclone.memory.schema_meta import set_meta
from codeclone.memory.schema_migrate import (
    MemorySchemaMigrationOutcome,
    acquire_schema_migration_lease,
    migrate_memory_schema,
    migrate_memory_schema_authoritative,
    release_schema_migration_lease,
)
from codeclone.memory.sqlite_store import (
    SqliteEngineeringMemoryStore,
    migrate_memory_db_authoritative,
)
from codeclone.report.meta import current_report_timestamp_utc


def _memory_record(
    *,
    project_id: str,
    record_id: str = "mem-legacy-supported",
    path: str = "pkg/legacy.py",
    discriminator: str = "legacy-supported",
    statement: str = "legacy migration statement",
) -> MemoryRecord:
    now = current_report_timestamp_utc()
    return MemoryRecord(
        id=record_id,
        project_id=project_id,
        identity_key=make_identity_key(
            type="risk_note",
            subject_kind="path",
            subject_key=path,
            discriminator=discriminator,
        ),
        type="risk_note",
        status="active",
        epistemic_rung="verified",
        origin="agent",
        ingest_source="agent",
        statement=statement,
        summary=None,
        payload={"path": path},
        created_at_utc=now,
        updated_at_utc=now,
        last_verified_at_utc=now,
        expires_at_utc=None,
        created_by="legacy-test",
        verified_by=None,
        approved_by=None,
        approved_at_utc=None,
        report_digest=None,
        code_fingerprint=None,
        stale_reason=None,
        created_on_branch=None,
        created_at_commit=None,
        verified_on_branch=None,
        verified_at_commit=None,
    )


def _insert_project(conn: sqlite3.Connection, *, project_id: str, root: Path) -> None:
    now = current_report_timestamp_utc()
    conn.execute(
        """
        INSERT INTO memory_projects(
            id, root, git_remote, git_branch, git_head, python_tag,
            created_at_utc, updated_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (project_id, str(root), None, None, None, None, now, now),
    )


def _insert_record_row(
    conn: sqlite3.Connection,
    record: MemoryRecord,
    *,
    schema_version: str,
    payload_json: str | None = None,
    include_fts: bool = True,
) -> None:
    conn.execute(
        """
        INSERT INTO memory_records(
            id, project_id, identity_key, type, status, epistemic_rung, origin,
            ingest_source, statement, summary, payload_json, created_at_utc,
            updated_at_utc, last_verified_at_utc, expires_at_utc, created_by,
            verified_by, approved_by, approved_at_utc, report_digest,
            code_fingerprint, stale_reason, created_on_branch, created_at_commit,
            verified_on_branch, verified_at_commit, schema_version
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?
        )
        """,
        (
            record.id,
            record.project_id,
            record.identity_key,
            record.type,
            record.status,
            record.epistemic_rung,
            record.origin,
            record.ingest_source,
            record.statement,
            record.summary,
            (
                payload_json
                if payload_json is not None
                else payload_json_text(record.payload)
            ),
            record.created_at_utc,
            record.updated_at_utc,
            record.last_verified_at_utc,
            record.expires_at_utc,
            record.created_by,
            record.verified_by,
            record.approved_by,
            record.approved_at_utc,
            record.report_digest,
            record.code_fingerprint,
            record.stale_reason,
            record.created_on_branch,
            record.created_at_commit,
            record.verified_on_branch,
            record.verified_at_commit,
            schema_version,
        ),
    )
    conn.execute(
        """
        INSERT INTO memory_subjects(id, memory_id, subject_kind, subject_key, relation)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            generate_memory_id(prefix="subj"),
            record.id,
            "path",
            "pkg/legacy.py",
            "about",
        ),
    )
    if include_fts:
        conn.execute(
            """
            INSERT INTO memory_records_fts(
                memory_id, project_id, record_type, ingest_source, status, search_text
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                record.id,
                record.project_id,
                record.type,
                record.ingest_source,
                record.status,
                f"{record.statement} pkg/legacy.py",
            ),
        )
    conn.commit()


def _record_schema_test_connection(tmp_path: Path) -> tuple[str, sqlite3.Connection]:
    root = tmp_path / "repo"
    root.mkdir()
    project = resolve_project_identity(root)
    conn = sqlite3.connect(tmp_path / "memory.sqlite3")
    create_schema_v1(conn)
    _insert_project(conn, project_id=project.id, root=root)
    return project.id, conn


def test_open_memory_db_enables_foreign_keys(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.sqlite3"
    conn = open_memory_db(db_path)
    try:
        row = conn.execute("PRAGMA foreign_keys").fetchone()
        assert row is not None
        assert int(row[0]) == 1
        assert get_meta(conn, "schema_version") == ENGINEERING_MEMORY_SCHEMA_VERSION
    finally:
        conn.close()


def test_create_schema_v1_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.sqlite3"
    conn = sqlite3.connect(db_path)
    try:
        create_schema_v1(conn)
        create_schema_v1(conn)
        assert get_meta(conn, "schema_version") == ENGINEERING_MEMORY_SCHEMA_VERSION
    finally:
        conn.close()


def test_ensure_schema_migrates_1_0_to_1_1(tmp_path: Path) -> None:
    """``allow_migration=True`` is what an authoritative caller passes;
    see test_ensure_schema_default_refuses_older_store_without_mutating for
    the (now default) refusal this same fixture hits without the flag."""
    db_path = tmp_path / "memory.sqlite3"
    conn = sqlite3.connect(db_path)
    try:
        create_schema_v1(conn)
        set_meta(conn, "schema_version", "1.0")
        conn.commit()
        ensure_schema(conn, allow_migration=True)
        assert get_meta(conn, "schema_version") == ENGINEERING_MEMORY_SCHEMA_VERSION
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE name='memory_records_fts'"
        ).fetchone()
        assert row is not None
    finally:
        conn.close()


def test_ensure_schema_reconciles_supported_legacy_record_rows(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    project = resolve_project_identity(root)
    db_path = tmp_path / "memory.sqlite3"
    record = _memory_record(project_id=project.id)
    conn = sqlite3.connect(db_path)
    try:
        create_schema_v1(conn)
        _insert_project(conn, project_id=project.id, root=root)
        _insert_record_row(conn, record, schema_version="1.6")
        set_meta(conn, "schema_version", "1.6")
        conn.commit()

        # First call needs authority (1.6 -> current); second is already at
        # current and takes the no-authority-needed fast path either way.
        ensure_schema(conn, allow_migration=True)
        ensure_schema(conn)

        assert get_meta(conn, "schema_version") == ENGINEERING_MEMORY_SCHEMA_VERSION
        row = conn.execute(
            "SELECT schema_version FROM memory_records WHERE id=?",
            (record.id,),
        ).fetchone()
        assert row == (ENGINEERING_MEMORY_SCHEMA_VERSION,)
    finally:
        conn.close()

    store = SqliteEngineeringMemoryStore(db_path)
    try:
        loaded = store.find_record(record.id)
        assert loaded is not None
        assert loaded.statement == "legacy migration statement"
        by_identity = store.find_by_identity_key(project.id, record.identity_key)
        assert by_identity is not None
        assert by_identity.id == record.id

        search_hits = store.search_records(
            project_id=project.id,
            statement_query="legacy migration",
            limit=5,
        )
        assert [hit.id for hit in search_hits] == [record.id]

        active_records = store.list_records_for_project(
            project.id,
            statuses=("active",),
        )
        assert [item.id for item in active_records] == [record.id]

        updated = store.upsert_record(
            replace(record, statement="legacy migration revised")
        )
        assert updated.action == "updated"
        assert updated.revision_written is True
        count, schema_version = store.connection.execute(
            """
            SELECT COUNT(*), MIN(schema_version)
            FROM memory_records
            WHERE project_id=? AND identity_key=?
            """,
            (project.id, record.identity_key),
        ).fetchone()
        assert count == 1
        assert schema_version == ENGINEERING_MEMORY_SCHEMA_VERSION

        store.mark_stale(record.id, reason="migration-test")
        stale_records = store.list_records_for_project(
            project.id,
            statuses=("stale",),
        )
        assert [item.id for item in stale_records] == [record.id]
    finally:
        store.close()

    reopened = SqliteEngineeringMemoryStore(db_path)
    try:
        rows = reopened.connection.execute(
            """
            SELECT id, schema_version
            FROM memory_records
            WHERE project_id=? AND identity_key=?
            """,
            (project.id, record.identity_key),
        ).fetchall()
        assert [tuple(row) for row in rows] == [
            (record.id, ENGINEERING_MEMORY_SCHEMA_VERSION)
        ]
    finally:
        reopened.close()


def test_ensure_schema_reconciles_current_meta_legacy_record_rows(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    project = resolve_project_identity(root)
    db_path = tmp_path / "memory.sqlite3"
    record = _memory_record(project_id=project.id)
    conn = sqlite3.connect(db_path)
    try:
        create_schema_v1(conn)
        _insert_project(conn, project_id=project.id, root=root)
        _insert_record_row(conn, record, schema_version="1.5")

        ensure_schema(conn)

        row = conn.execute(
            "SELECT schema_version FROM memory_records WHERE id=?",
            (record.id,),
        ).fetchone()
        assert row == (ENGINEERING_MEMORY_SCHEMA_VERSION,)
    finally:
        conn.close()


def test_record_schema_reconcile_keeps_unsupported_and_malformed_rows_quarantined(
    tmp_path: Path,
) -> None:
    from codeclone.memory.schema_migrate import reconcile_memory_record_schema_versions

    project_id, conn = _record_schema_test_connection(tmp_path)
    unsupported = _memory_record(
        project_id=project_id,
        record_id="mem-unsupported",
        discriminator="unsupported",
    )
    malformed = _memory_record(
        project_id=project_id,
        record_id="mem-malformed",
        discriminator="malformed",
    )
    try:
        _insert_record_row(conn, unsupported, schema_version="0")
        _insert_record_row(conn, malformed, schema_version="1.6", payload_json="[]")

        assert reconcile_memory_record_schema_versions(conn) == 0

        rows = conn.execute(
            """
            SELECT id, schema_version
            FROM memory_records
            ORDER BY id ASC
            """
        ).fetchall()
        assert rows == [("mem-malformed", "1.6"), ("mem-unsupported", "0")]
    finally:
        conn.close()


def test_record_schema_reconcile_rolls_back_on_unexpected_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.memory import schema_migrate

    project_id, conn = _record_schema_test_connection(tmp_path)
    first = _memory_record(
        project_id=project_id,
        record_id="mem-first",
        discriminator="first",
    )
    second = _memory_record(
        project_id=project_id,
        record_id="mem-second",
        discriminator="second",
    )
    try:
        _insert_record_row(conn, first, schema_version="1.6")
        _insert_record_row(conn, second, schema_version="1.6")

        real_write = schema_migrate._write_current_record_schema_version
        calls = 0

        def fail_after_first_write(
            inner_conn: sqlite3.Connection,
            *,
            record_id: str,
            legacy_version: object,
            current_version: str,
        ) -> None:
            nonlocal calls
            real_write(
                inner_conn,
                record_id=record_id,
                legacy_version=legacy_version,
                current_version=current_version,
            )
            calls += 1
            if calls == 1:
                raise RuntimeError("forced migration write failure")

        monkeypatch.setattr(
            schema_migrate,
            "_write_current_record_schema_version",
            fail_after_first_write,
        )
        with pytest.raises(RuntimeError, match="forced migration write failure"):
            schema_migrate.reconcile_memory_record_schema_versions(conn)

        rows = conn.execute(
            """
            SELECT id, schema_version
            FROM memory_records
            ORDER BY id ASC
            """
        ).fetchall()
        assert rows == [("mem-first", "1.6"), ("mem-second", "1.6")]
    finally:
        conn.close()


def test_ensure_schema_rejects_unsupported_version(tmp_path: Path) -> None:
    """With authority granted, a version the migration chain cannot reach
    (newer than anything ``migrate_memory_schema`` knows how to walk to)
    still fails -- authority is not a bypass of the chain's own ceiling.

    Without authority the SAME fixture is refused earlier, by
    ``MemorySchemaAuthorityError``, before ``migrate_memory_schema`` is even
    consulted; see test_ensure_schema_default_refuses_newer_store_too.
    """
    db_path = tmp_path / "memory.sqlite3"
    conn = open_memory_db(db_path)
    try:
        conn.execute(
            "UPDATE memory_meta SET value=? WHERE key='schema_version'",
            ("9.9",),
        )
        conn.commit()
        with pytest.raises(MemorySchemaError, match="Unsupported engineering memory"):
            ensure_schema(conn, allow_migration=True)
    finally:
        conn.close()


def test_migrate_memory_schema_noop_without_meta(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.sqlite3"
    conn = sqlite3.connect(db_path)
    try:
        migrate_memory_schema(conn)
        assert get_meta(conn, "schema_version") is None
    finally:
        conn.close()


def test_migrate_memory_schema_noop_when_already_current(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.sqlite3"
    conn = open_memory_db(db_path)
    try:
        migrate_memory_schema(conn)
        assert get_meta(conn, "schema_version") == ENGINEERING_MEMORY_SCHEMA_VERSION
    finally:
        conn.close()


def test_ensure_schema_raises_on_unsupported_version(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.sqlite3"
    conn = sqlite3.connect(db_path)
    try:
        create_schema_v1(conn)
        set_meta(conn, "schema_version", "0.0")
        conn.commit()
        with (
            patch(
                "codeclone.memory.schema_migrate.migrate_memory_schema",
                lambda _conn: None,
            ),
            pytest.raises(MemorySchemaError, match="Unsupported engineering memory"),
        ):
            ensure_schema(conn, allow_migration=True)
    finally:
        conn.close()


def _legacy_1_7_records_table(conn: sqlite3.Connection) -> None:
    """Rebuild memory_records as it stood at 1.7: the rung column named
    ``confidence``. create_schema_v1 now emits the 1.8 spelling, so a genuine
    pre-rename store has to be reconstructed to migrate one."""
    conn.execute("DROP TABLE memory_records")
    conn.execute(
        """
        CREATE TABLE memory_records (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
            identity_key TEXT NOT NULL, type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            confidence TEXT NOT NULL DEFAULT 'supported',
            origin TEXT NOT NULL DEFAULT 'system',
            ingest_source TEXT NOT NULL, statement TEXT NOT NULL, summary TEXT,
            payload_json TEXT, created_at_utc TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL, last_verified_at_utc TEXT,
            expires_at_utc TEXT, created_by TEXT NOT NULL, verified_by TEXT,
            approved_by TEXT, approved_at_utc TEXT, report_digest TEXT,
            code_fingerprint TEXT, stale_reason TEXT, created_on_branch TEXT,
            created_at_commit TEXT, verified_on_branch TEXT,
            verified_at_commit TEXT, schema_version TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES memory_projects(id)
        )
        """
    )


def test_migrate_1_7_to_1_8_renames_the_rung_column_and_keeps_every_value(
    tmp_path: Path,
) -> None:
    """The rename carries values across untouched.

    Two unrelated things were called ``confidence``: this column, and the
    ``high|medium|low`` analysis signal. The analysis name is older, wider and
    published in the report schema, so the memory column is the one that moved.
    It never measured confidence -- it records which extractor wrote the row --
    but the migration must not reclassify a single record while renaming it.
    """
    db_path = tmp_path / "memory.sqlite3"
    conn = sqlite3.connect(db_path)
    try:
        create_schema_v1(conn)
        _legacy_1_7_records_table(conn)
        _insert_project(conn, project_id="proj-legacy", root=tmp_path)
        rungs = ("inferred", "supported", "verified")
        for index, rung in enumerate(rungs):
            conn.execute(
                "INSERT INTO memory_records(id, project_id, identity_key, type,"
                " status, confidence, origin, ingest_source, statement,"
                " created_at_utc, updated_at_utc, created_by, schema_version)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    f"mem-{index}",
                    "proj-legacy",
                    f"key-{index}",
                    "risk_note",
                    "active",
                    rung,
                    "system",
                    "analysis",
                    f"statement {index}",
                    "2026-01-01T00:00:00Z",
                    "2026-01-01T00:00:00Z",
                    "test",
                    "1.7",
                ),
            )
        set_meta(conn, "schema_version", "1.7")
        conn.commit()

        migrate_memory_schema(conn)

        # migrate_memory_schema always lands at the current contract version
        # (now 1.9, past this step's own 1.7 -> 1.8 rung rename), never at a
        # hardcoded intermediate; the assertions below still pin that specific
        # leg of the chain.
        assert get_meta(conn, "schema_version") == "1.9"
        columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(memory_records)").fetchall()
        }
        # Both halves matter: the new name arrived AND the old name is gone.
        # Without the second assertion a store carrying both columns passes.
        assert "epistemic_rung" in columns
        assert "confidence" not in columns
        carried = conn.execute(
            "SELECT id, epistemic_rung FROM memory_records ORDER BY id"
        ).fetchall()
        assert carried == [(f"mem-{i}", rung) for i, rung in enumerate(rungs)]
    finally:
        conn.close()


def test_fresh_store_has_no_column_named_confidence(tmp_path: Path) -> None:
    """The separation is real in storage, not only in the Python attribute.

    A fresh store must never grow the old name back: if it did, two lanes would
    once again answer to one word in the same database.
    """
    db_path = tmp_path / "memory.sqlite3"
    conn = sqlite3.connect(db_path)
    try:
        create_schema_v1(conn)
        columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(memory_records)").fetchall()
        }
        assert "epistemic_rung" in columns
        assert "confidence" not in columns
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Migration authority: acceptance battery for the maintainer's seven cases.
#
#   A. non-authoritative checkout opens an older store -> NO migration
#   B. explicit authoritative migration -> migration allowed exactly once
#   C/D covered structurally in the delivery report (out of this file's
#      scope: the finish-path intent-loss mechanism lives in
#      codeclone/surfaces/mcp/_session_*, which this patch does not touch).
#   F. a mere read or status operation never mutates the schema
#
# Direction-B (store newer than this checkout's code) is pinned alongside
# direction-A so a regression to a "current < target only" guard -- which
# would silently let the OTHER direction through -- reds under a dedicated
# test, per the mutation-discipline "comprehensive = both boundaries" rule.
# ---------------------------------------------------------------------------


def _old_store(tmp_path: Path, *, version: str) -> Path:
    db_path = tmp_path / "memory.sqlite3"
    conn = sqlite3.connect(db_path)
    try:
        create_schema_v1(conn)
        set_meta(conn, "schema_version", version)
        conn.commit()
    finally:
        conn.close()
    return db_path


def _old_store_primed_through_open_memory_db(tmp_path: Path, *, version: str) -> Path:
    """Same shape as ``_old_store``, but for tests whose "before" hash must
    be taken through ``open_memory_db``/``SqliteEngineeringMemoryStore``.

    ``open_sqlite_db`` sets ``PRAGMA journal_mode=WAL`` on every open; going
    from SQLite's default rollback-journal mode to WAL rewrites the file
    header regardless of schema content, which would make a naive
    before/after hash comparison see a "mutation" that has nothing to do
    with migration authority. Priming through a real ``open_memory_db``
    call first (then downgrading the meta version with a bare connection,
    which does not touch journal mode) isolates the hash comparison to
    exactly what the REFUSED call itself does.
    """
    db_path = tmp_path / "memory.sqlite3"
    open_memory_db(db_path).close()
    conn = sqlite3.connect(db_path)
    try:
        set_meta(conn, "schema_version", version)
        conn.commit()
    finally:
        conn.close()
    return db_path


def _status_report_facts(
    tmp_path: Path, db_path: Path
) -> tuple[str, str | None, str, bool]:
    """The four facts every store-state test reads, from the REAL producer.

    Returns ``(state, schema_version, supported_schema_version, db_exists)``
    out of ``build_memory_status_report`` -- the single call behind both
    ``codeclone memory status`` and ``codeclone setup status``. Shared by the
    three tests that each point that one producer at a different store shape,
    so what differs between them is the store and the fact asserted, not the
    call. Returning the facts rather than the report keeps the annotation free
    of a module-level ``codeclone.memory.status_report`` import, which this
    file has never carried (see ``tests/test_architecture.py``'s shrink-only
    ``test_import:r4->r2p`` ratchet).
    """
    from codeclone.memory.status_report import build_memory_status_report

    root = tmp_path / "repo"
    root.mkdir(exist_ok=True)
    report = build_memory_status_report(root_path=root, db_path=db_path)
    return (
        report.state,
        report.schema_version,
        report.supported_schema_version,
        report.db_exists,
    )


def test_ensure_schema_default_refuses_older_store_without_mutating(
    tmp_path: Path,
) -> None:
    """Case A. Store behind this checkout's code: refused, zero mutation.

    The byte-for-byte hash (not just the meta row) is the mutation witness:
    a refusal that touched an unrelated page, or bumped SQLite's own
    change-counter via an aborted write, would still show here.
    """
    db_path = _old_store(tmp_path, version="1.7")
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()

    conn = sqlite3.connect(db_path)
    try:
        with pytest.raises(MemorySchemaAuthorityError) as excinfo:
            ensure_schema(conn)
        assert "1.7" in str(excinfo.value)
        assert ENGINEERING_MEMORY_SCHEMA_VERSION in str(excinfo.value)
    finally:
        conn.close()

    after = hashlib.sha256(db_path.read_bytes()).hexdigest()
    assert after == before, "a refused open must not change a single byte"


def test_ensure_schema_default_refuses_newer_store_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Case A, other boundary: this checkout's code older than the store.

    Simulated by lowering the module-level target the SAME way an older
    installed codeclone would carry a lower constant; the store is built at
    the real current version by ``create_schema_v1`` (unpatched), so this is
    a genuine "store ahead of code" shape, not a synthetic version string.
    A guard written as ``current < target`` (instead of ``!=``) would pass
    test_ensure_schema_default_refuses_older_store_without_mutating while
    silently missing this direction -- this test is what reds that mutant.
    """
    db_path = tmp_path / "memory.sqlite3"
    conn = sqlite3.connect(db_path)
    try:
        create_schema_v1(conn)  # stamps the REAL current version, e.g. 1.9
    finally:
        conn.close()
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()

    monkeypatch.setattr(schema_module, "ENGINEERING_MEMORY_SCHEMA_VERSION", "1.8")
    conn = sqlite3.connect(db_path)
    try:
        with pytest.raises(MemorySchemaAuthorityError) as excinfo:
            ensure_schema(conn)
        assert "1.8" in str(excinfo.value)
    finally:
        conn.close()

    after = hashlib.sha256(db_path.read_bytes()).hexdigest()
    assert after == before, "a refused open must not change a single byte"


def test_allow_migration_true_is_the_positive_control_for_the_refusal(
    tmp_path: Path,
) -> None:
    """Probe Validity Law positive control for the two tests above: the
    IDENTICAL fixture that gets refused by default proceeds to completion
    when authority is granted, proving the refusal is what stood in the
    way -- not an unrelated failure the default-refusal tests would pass
    for the wrong reason (e.g. a broken connection or a typo'd version).
    """
    db_path = _old_store(tmp_path, version="1.7")
    conn = sqlite3.connect(db_path)
    try:
        ensure_schema(conn, allow_migration=True)
        assert get_meta(conn, "schema_version") == ENGINEERING_MEMORY_SCHEMA_VERSION
    finally:
        conn.close()


def test_open_memory_db_default_refuses_and_allow_migration_true_migrates(
    tmp_path: Path,
) -> None:
    """The public entry point (not the lower ``ensure_schema`` helper)
    carries the same contract end to end."""
    db_path = _old_store_primed_through_open_memory_db(tmp_path, version="1.7")
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()

    with pytest.raises(MemorySchemaAuthorityError):
        open_memory_db(db_path)
    after = hashlib.sha256(db_path.read_bytes()).hexdigest()
    assert after == before

    conn = open_memory_db(db_path, allow_migration=True)
    try:
        assert get_meta(conn, "schema_version") == ENGINEERING_MEMORY_SCHEMA_VERSION
    finally:
        conn.close()


def test_sqlite_engineering_memory_store_default_never_mutates_a_mismatched_store(
    tmp_path: Path,
) -> None:
    """Case F, the real read-path proxy.

    ``SqliteEngineeringMemoryStore(path)`` with no ``allow_migration`` is
    EXACTLY what ``codeclone/memory/status_report.py::build_memory_status_report``
    (``codeclone memory status`` / ``codeclone setup status``) and
    ``codeclone/surfaces/mcp/_session_memory_mixin.py::_open_memory_store``
    (every MCP memory-retrieval tool: get_relevant_memory,
    query_engineering_memory, ...) call -- same class, same single
    positional argument, same default. Proving the constructor never
    mutates on a mismatch is proving those two real surfaces never do,
    without needing to boot a full MCP session or CLI process.
    """
    db_path = _old_store_primed_through_open_memory_db(tmp_path, version="1.7")
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()

    with pytest.raises(MemorySchemaAuthorityError):
        SqliteEngineeringMemoryStore(db_path)

    after = hashlib.sha256(db_path.read_bytes()).hexdigest()
    assert after == before


def test_status_report_calls_a_present_unreadable_store_incompatible(
    tmp_path: Path,
) -> None:
    """A store that exists and cannot be opened is ``incompatible``.

    Not ``absent``: calling it absent would report a store that may be full of
    records as "never created", and send the reader to ``memory init`` when the
    remediation is ``memory migrate``. The mismatch that produces this state is
    real (an on-disk 1.7 against this checkout's version), and both versions
    have to survive into the report or the diagnostic says nothing actionable.
    """
    db_path = _old_store_primed_through_open_memory_db(tmp_path, version="1.7")

    facts = _status_report_facts(tmp_path, db_path)

    # db_exists is derived from state, so the store IS there: it must not deny it.
    assert facts == ("incompatible", "1.7", ENGINEERING_MEMORY_SCHEMA_VERSION, True)


def test_status_report_calls_a_missing_store_absent(tmp_path: Path) -> None:
    """No file, no store: ``absent``, and never ``incompatible``.

    The opposite boundary of the test above. An absent store reported as
    incompatible would send the reader to ``memory migrate`` for a store that
    was never created, and would claim a schema mismatch that no file exhibits.
    """
    db_path = tmp_path / "not-created.sqlite3"
    assert not db_path.exists()

    state, found, _supported, exists = _status_report_facts(tmp_path, db_path)

    assert (state, found, exists) == ("absent", None, False)


def test_build_memory_status_report_never_mutates_a_mismatched_store(
    tmp_path: Path,
) -> None:
    """Case F, exercised through the actual producer behind both
    ``codeclone memory status`` and ``codeclone setup status`` -- not a
    synthetic stand-in for it.

    The report now answers instead of raising (see the two state tests above),
    so what is pinned here is the part that never changed: describing a store
    this checkout cannot read leaves that store byte-for-byte alone.
    """
    db_path = _old_store_primed_through_open_memory_db(tmp_path, version="1.7")
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()

    state, *_rest = _status_report_facts(tmp_path, db_path)
    assert state == "incompatible"

    after = hashlib.sha256(db_path.read_bytes()).hexdigest()
    assert after == before


def test_migrate_memory_db_authoritative_initializes_a_brand_new_store(
    tmp_path: Path,
) -> None:
    """Initialization is not migration and needs no lease: a brand new
    store is created directly, same as any ordinary first open."""
    db_path = tmp_path / "memory.sqlite3"
    outcome = migrate_memory_db_authoritative(db_path)
    assert outcome.migrated is False
    assert outcome.from_version is None
    assert outcome.to_version == ENGINEERING_MEMORY_SCHEMA_VERSION
    conn = sqlite3.connect(db_path)
    try:
        assert get_meta(conn, "schema_version") == ENGINEERING_MEMORY_SCHEMA_VERSION
    finally:
        conn.close()


def test_migrate_memory_db_authoritative_migrates_an_existing_store(
    tmp_path: Path,
) -> None:
    db_path = _old_store(tmp_path, version="1.7")
    outcome = migrate_memory_db_authoritative(db_path)
    assert outcome.migrated is True
    assert outcome.from_version == "1.7"
    assert outcome.to_version == ENGINEERING_MEMORY_SCHEMA_VERSION

    # Idempotent: a second authoritative call on an already-current store
    # reports honestly that it did nothing.
    outcome2 = migrate_memory_db_authoritative(db_path)
    assert outcome2.migrated is False
    assert outcome2.from_version == ENGINEERING_MEMORY_SCHEMA_VERSION


def test_acquire_schema_migration_lease_refuses_while_a_live_grant_is_held(
    tmp_path: Path,
) -> None:
    """Direct mechanism proof: a second acquire on a LIVE (unexpired) grant
    is refused; the SAME store with the grant released or expired accepts
    a new one. Both directions of the guard, one test each."""
    db_path = _old_store(tmp_path, version="1.7")
    conn_a = sqlite3.connect(db_path)
    conn_b = sqlite3.connect(db_path)
    try:
        token_a = acquire_schema_migration_lease(conn_a, holder="A", ttl_seconds=30)
        assert token_a is not None

        # Positive control: the identical call from a second connection,
        # while A's grant is live, must be refused -- proving the refusal
        # observed below is the fencing check, not some unrelated failure.
        refused = acquire_schema_migration_lease(conn_b, holder="B", ttl_seconds=30)
        assert refused is None

        assert release_schema_migration_lease(conn_a, token=token_a) is True

        # Permitted-path control: once released, a fresh acquire succeeds.
        token_b = acquire_schema_migration_lease(conn_b, holder="B", ttl_seconds=30)
        assert token_b is not None
        assert token_b != token_a
    finally:
        conn_a.close()
        conn_b.close()


def test_expired_lease_is_reclaimable_and_stale_release_is_fenced(
    tmp_path: Path,
) -> None:
    """A crashed authoritative caller's grant is reclaimable once its TTL
    passes (never wedges the store); its late release must NOT be able to
    clear whoever holds the CURRENT grant (fencing on release, not just
    acquire) -- mutated the other way (an unconditional DELETE), this test
    reds: D would then be able to acquire while C's lease is still live."""
    db_path = _old_store(tmp_path, version="1.7")
    conn_a = sqlite3.connect(db_path)
    conn_c = sqlite3.connect(db_path)
    conn_d = sqlite3.connect(db_path)
    try:
        token_a = acquire_schema_migration_lease(conn_a, holder="A", ttl_seconds=1)
        assert token_a is not None
        time.sleep(1.2)

        token_c = acquire_schema_migration_lease(conn_c, holder="C", ttl_seconds=30)
        assert token_c is not None, "an expired grant must be reclaimable"

        stale_release = release_schema_migration_lease(conn_a, token=token_a)
        assert stale_release is False, "a stale release must report failure"

        # Fencing proof: C's lease must still be live -- D is refused.
        token_d = acquire_schema_migration_lease(conn_d, holder="D", ttl_seconds=30)
        assert token_d is None, "A's stale release corrupted C's live grant"
    finally:
        conn_a.close()
        conn_c.close()
        conn_d.close()


def test_concurrent_authoritative_migration_is_exactly_once_with_typed_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The maintainer's concurrency claim, proven with real OS threads and
    real separate sqlite3 connections against one file -- not by reading
    the acquire/release code and reasoning about it.

    ``migrate_memory_schema`` is widened (via monkeypatch, same idiom as
    test_record_schema_reconcile_rolls_back_on_unexpected_failure above) to
    hold the lease for 0.3s so the barrier-released contenders reliably
    overlap the winner's window instead of trickling through sequentially;
    the mutual exclusion itself is unmodified production code (SQLite's own
    ``BEGIN IMMEDIATE`` write lock plus the meta-table fencing check).

    Asserts BOTH halves the maintainer named: exactly one migration NOT
    two-or-zero, and at least one typed refusal NOT a silent no-op -- a
    mutant that let two threads both migrate, or that resolved the race
    with no refusal ever observed, reds here.
    """
    db_path = _old_store(tmp_path, version="1.7")

    original_migrate = schema_migrate.migrate_memory_schema

    def slow_migrate(conn: sqlite3.Connection) -> None:
        time.sleep(0.3)
        original_migrate(conn)

    monkeypatch.setattr(schema_migrate, "migrate_memory_schema", slow_migrate)

    thread_count = 6
    barrier = threading.Barrier(thread_count)
    outcomes: list[object] = [None] * thread_count

    def attempt(index: int) -> None:
        conn = sqlite3.connect(db_path)
        try:
            barrier.wait(timeout=5)
            try:
                outcomes[index] = migrate_memory_schema_authoritative(
                    conn, holder=f"thread-{index}", ttl_seconds=30
                )
            except MemorySchemaMigrationInProgressError as exc:
                outcomes[index] = exc
        finally:
            conn.close()

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(thread_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive(), "a contender thread hung"

    migrated = [
        outcome
        for outcome in outcomes
        if isinstance(outcome, MemorySchemaMigrationOutcome) and outcome.migrated
    ]
    refusals = [
        outcome
        for outcome in outcomes
        if isinstance(outcome, MemorySchemaMigrationInProgressError)
    ]
    assert outcomes.count(None) == 0, "every contender must have a recorded outcome"
    assert len(migrated) == 1, f"expected exactly one migration, saw {outcomes!r}"
    assert len(refusals) >= 1, (
        "expected at least one typed refusal -- no real overlap was observed, "
        f"outcomes={outcomes!r}"
    )

    conn = sqlite3.connect(db_path)
    try:
        assert get_meta(conn, "schema_version") == ENGINEERING_MEMORY_SCHEMA_VERSION
        migration_rows = conn.execute(
            "SELECT version FROM memory_schema_migrations"
        ).fetchall()
        versions = [row[0] for row in migration_rows]
        assert len(versions) == len(set(versions)), (
            "duplicate migration-step rows indicate the chain ran twice"
        )
    finally:
        conn.close()
