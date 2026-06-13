# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from codeclone.memory.identity import make_identity_key
from codeclone.memory.models import (
    MemoryLink,
    MemoryQuery,
    MemoryRecord,
    MemorySubject,
    RecordBatch,
    generate_memory_id,
)
from codeclone.memory.project import resolve_project_identity
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore
from codeclone.report.meta import current_report_timestamp_utc


def _sample_record(
    *,
    project_id: str,
    statement: str,
    updated_at_utc: str,
    discriminator: str = "schema_constant",
) -> MemoryRecord:
    identity = make_identity_key(
        type="contract_note",
        subject_kind="contract",
        subject_key="CACHE_VERSION",
        discriminator=discriminator,
    )
    now = current_report_timestamp_utc()
    return MemoryRecord(
        id=generate_memory_id(prefix="mem"),
        project_id=project_id,
        identity_key=identity,
        type="contract_note",
        status="active",
        confidence="verified",
        origin="system",
        ingest_source="contract",
        statement=statement,
        summary=None,
        payload={"contract_kind": "schema_constant"},
        created_at_utc=now,
        updated_at_utc=updated_at_utc,
        last_verified_at_utc=now,
        expires_at_utc=None,
        created_by="test",
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


def test_sqlite_store_query_records_filters_and_db_path(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    project = resolve_project_identity(root)
    store = SqliteEngineeringMemoryStore(tmp_path / "memory.sqlite3")
    try:
        store.initialize(project)
        assert store.db_path == tmp_path / "memory.sqlite3"

        rec = _sample_record(
            project_id=project.id,
            statement="alpha beta",
            updated_at_utc=current_report_timestamp_utc(),
        )
        store.upsert_record(rec)

        store.write_subject(
            MemorySubject(
                id=generate_memory_id(prefix="subj"),
                memory_id=rec.id,
                subject_kind="path",
                subject_key="codeclone/memory/sqlite_store.py",
                relation="about",
            )
        )
        store.write_subject(
            MemorySubject(
                id=generate_memory_id(prefix="subj"),
                memory_id=rec.id,
                subject_kind="path",
                subject_key="codeclone/memory/other.py",
                relation="about",
            )
        )

        query_key = MemoryQuery(
            project_id=project.id,
            types=("contract_note",),
            subject_kind="path",
            subject_key="codeclone/memory/sqlite_store.py",
            limit=10,
            offset=0,
        )
        hit_key = store.query_records(query_key)
        assert len(hit_key) == 1
        assert hit_key[0].id == rec.id

        query_prefix = MemoryQuery(
            project_id=project.id,
            subject_kind="path",
            subject_key_prefix="codeclone/memory/",
            limit=10,
            offset=0,
        )
        hit_prefix = store.query_records(query_prefix)
        assert len(hit_prefix) == 1
        assert hit_prefix[0].id == rec.id
    finally:
        store.close()


def test_sqlite_store_search_empty_tokens_and_confidence_filter_branches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    project = resolve_project_identity(root)
    store = SqliteEngineeringMemoryStore(tmp_path / "memory.sqlite3")
    try:
        store.initialize(project)
        rec = _sample_record(
            project_id=project.id,
            statement="alpha beta",
            updated_at_utc=current_report_timestamp_utc(),
        )
        store.upsert_record(rec)
        store.write_subject(
            MemorySubject(
                id=generate_memory_id(prefix="subj"),
                memory_id=rec.id,
                subject_kind="path",
                subject_key="codeclone/memory/sqlite_store.py",
                relation="about",
            )
        )

        # Cover FTS path where fts_match_expression() returns None for empty tokens.
        hits_fts = store.search_records(
            project_id=project.id,
            statement_query="a",  # token length < 2 => no tokens
            limit=10,
        )
        assert hits_fts == []

        # Cover confidence_via_subquery=True path in FTS search filtering.
        hits_fts_conf = store.search_records(
            project_id=project.id,
            statement_query="alpha",
            confidences=("verified",),
            limit=10,
        )
        assert hits_fts_conf

        # Cover branch where FTS returns None and search falls back to LIKE.
        monkeypatch.setattr(store, "_fts_available", lambda: True)
        monkeypatch.setattr(store, "_search_records_fts", lambda **_kwargs: None)
        hits_from_fallback = store.search_records(
            project_id=project.id,
            statement_query="alpha",
            limit=10,
        )
        assert hits_from_fallback

        # Force LIKE fallback and hit the empty-tokens branch.
        monkeypatch.setattr(store, "_fts_available", lambda: False)
        hits_like_empty = store.search_records(
            project_id=project.id,
            statement_query="a",
            limit=10,
        )
        assert hits_like_empty == []

        # Cover confidence-via-subquery=False (LIKE) and exercise the confidence filter.
        hits_like_conf = store.search_records(
            project_id=project.id,
            statement_query="alpha",
            confidences=("verified",),
            limit=10,
        )
        assert hits_like_conf  # not empty
    finally:
        store.close()


def test_sqlite_store_fts_sync_rebuild_links_commits_and_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    project = resolve_project_identity(root)
    store = SqliteEngineeringMemoryStore(tmp_path / "memory.sqlite3")
    try:
        store.initialize(project)

        rec_active = _sample_record(
            project_id=project.id,
            statement="alpha beta gamma",
            updated_at_utc=current_report_timestamp_utc(),
        )
        store.upsert_record(rec_active)
        store.write_subject(
            MemorySubject(
                id=generate_memory_id(prefix="subj"),
                memory_id=rec_active.id,
                subject_kind="path",
                subject_key="codeclone/memory/sqlite_store.py",
                relation="about",
            )
        )

        # sync_fts_record early return when FTS is unavailable.
        monkeypatch.setattr(store, "_fts_available", lambda: False)
        store.sync_fts_record(rec_active.id)

        # sync_fts_record delete+return when record doesn't exist but FTS is available.
        monkeypatch.setattr(store, "_fts_available", lambda: True)
        store.sync_fts_record("mem-nonexistent")

        # rebuild_project_fts when FTS is unavailable.
        monkeypatch.setattr(store, "_fts_available", lambda: False)
        assert store.rebuild_project_fts(project.id) == 0

        # update_record_status with commit=False (no commit).
        monkeypatch.setattr(store, "_fts_available", lambda: True)
        store.update_record_status(
            rec_active.id, status="stale", stale_reason="x", commit=False
        )

        # delete_records_older_than with commit=True.
        old_rec = _sample_record(
            project_id=project.id,
            statement="old",
            updated_at_utc="2000-01-01T00:00:00Z",
            discriminator="old-record",
        )
        store.upsert_record(old_rec)
        removed = store.delete_records_older_than(
            status="archived",
            updated_before_utc="9999-01-01T00:00:00Z",
            commit=True,
        )
        assert removed == 0

        # persist_batch executes link-writing and sync_fts_record.
        rec2 = _sample_record(
            project_id=project.id,
            statement="second",
            updated_at_utc=current_report_timestamp_utc(),
            discriminator="second-record",
        )
        store.upsert_record(rec2)
        link = MemoryLink(
            id=generate_memory_id(prefix="lnk"),
            project_id=project.id,
            from_memory_id=rec_active.id,
            to_memory_id=rec2.id,
            relation="depends_on",
            created_by="test",
            created_at_utc=current_report_timestamp_utc(),
        )
        store.persist_batch(
            RecordBatch(
                records=[],
                subjects=[],
                evidence=[],
                links=[link],
            )
        )

        # delete_records_older_than loop with actual ids (line 731 path).
        stale_rec = _sample_record(
            project_id=project.id,
            statement="stale-delete",
            updated_at_utc="2000-01-01T00:00:00Z",
            discriminator="stale-delete",
        )
        store.upsert_record(stale_rec)
        store.mark_stale(stale_rec.id, reason="stale-delete")
        deleted = store.delete_records_older_than(
            status="stale",
            updated_before_utc="9999-01-01T00:00:00Z",
            commit=True,
        )
        assert deleted >= 1

        # Invalid count column.
        with pytest.raises(ValueError, match="unsupported count column"):
            store.count_records_grouped(column="bad")

        # Transaction rollback: commit=False update inside transaction then exception.
        # Re-insert a known record and verify its status doesn't change after rollback.
        rec_rb = _sample_record(
            project_id=project.id,
            statement="rollback test",
            updated_at_utc=current_report_timestamp_utc(),
            discriminator="rollback-record",
        )
        store.upsert_record(rec_rb)
        loaded = store.find_record(rec_rb.id)
        assert loaded is not None
        initial_status = loaded.status
        with pytest.raises(RuntimeError), store.transaction():
            store.update_record_status(
                rec_rb.id, status="stale", stale_reason=None, commit=False
            )
            raise RuntimeError("boom")
        reloaded = store.find_record(rec_rb.id)
        assert reloaded is not None
        assert reloaded.status == initial_status
    finally:
        store.close()


def test_upsert_skips_human_origin_record(tmp_path: Path) -> None:
    project = resolve_project_identity(tmp_path)
    db_path = tmp_path / ".codeclone" / "memory.sqlite3"
    store = SqliteEngineeringMemoryStore(db_path)
    try:
        store.initialize(project)
        human = replace(
            _sample_record(
                project_id=project.id,
                statement="human approved fact",
                updated_at_utc=current_report_timestamp_utc(),
                discriminator="human-record",
            ),
            origin="human",
            status="active",
            approved_by="maintainer",
        )
        store.upsert_record(human)
        incoming = replace(
            human,
            statement="agent tried to overwrite",
            updated_at_utc=current_report_timestamp_utc(),
            origin="system",
        )
        result = store.upsert_record(incoming)
        assert result.action == "skipped"
        loaded = store.find_record(human.id)
        assert loaded is not None
        assert loaded.statement == "human approved fact"
    finally:
        store.close()


def test_open_sqlite_db_rejects_invalid_synchronous(tmp_path: Path) -> None:
    from codeclone.utils.sqlite_store import open_sqlite_db

    def _schema(conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")

    with pytest.raises(ValueError, match="synchronous must be one of"):
        open_sqlite_db(
            tmp_path / "bad.sqlite3",
            ensure_schema=_schema,
            synchronous="invalid",
        )
