# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from codeclone.contracts import ENGINEERING_MEMORY_SCHEMA_VERSION
from codeclone.memory.exceptions import MemorySchemaError
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
from codeclone.memory.schema_migrate import migrate_memory_schema
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore
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
        confidence="verified",
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
            id, project_id, identity_key, type, status, confidence, origin,
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
            record.confidence,
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
    db_path = tmp_path / "memory.sqlite3"
    conn = sqlite3.connect(db_path)
    try:
        create_schema_v1(conn)
        set_meta(conn, "schema_version", "1.0")
        conn.commit()
        ensure_schema(conn)
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

        ensure_schema(conn)
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
    db_path = tmp_path / "memory.sqlite3"
    conn = open_memory_db(db_path)
    try:
        conn.execute(
            "UPDATE memory_meta SET value=? WHERE key='schema_version'",
            ("9.9",),
        )
        conn.commit()
        with pytest.raises(MemorySchemaError, match="Unsupported engineering memory"):
            ensure_schema(conn)
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
            ensure_schema(conn)
    finally:
        conn.close()
