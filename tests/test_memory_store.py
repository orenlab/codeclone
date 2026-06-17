# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from codeclone.memory.identity import make_identity_key
from codeclone.memory.models import (
    MemoryRecord,
    MemoryRevision,
    generate_memory_id,
)
from codeclone.memory.project import resolve_project_identity
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore
from codeclone.report.meta import current_report_timestamp_utc


def _sample_record(*, project_id: str, statement: str = "alpha") -> MemoryRecord:
    now = current_report_timestamp_utc()
    identity = make_identity_key(
        type="contract_note",
        subject_kind="contract",
        subject_key="CACHE_VERSION",
        discriminator="schema_constant",
    )
    return MemoryRecord(
        id=generate_memory_id(),
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
        updated_at_utc=now,
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


def test_store_crud_upsert_and_revision(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    project = resolve_project_identity(root)
    store = SqliteEngineeringMemoryStore(tmp_path / "memory.sqlite3")
    try:
        store.initialize(project)
        record = _sample_record(project_id=project.id)
        created = store.upsert_record(record)
        assert created.action == "created"

        unchanged = store.upsert_record(record)
        assert unchanged.action == "unchanged"

        updated_record = replace(record, statement="beta")
        updated = store.upsert_record(updated_record)
        assert updated.action == "updated"
        assert updated.revision_written is True

        loaded = store.find_by_identity_key(project.id, record.identity_key)
        assert loaded is not None
        assert loaded.statement == "beta"

        revision = MemoryRevision(
            id=generate_memory_id(prefix="rev"),
            memory_id=loaded.id,
            revision_number=99,
            previous_statement="alpha",
            new_statement="beta",
            previous_payload=None,
            new_payload={"contract_kind": "schema_constant"},
            reason="manual",
            changed_by="test",
            changed_at_utc=current_report_timestamp_utc(),
            branch=None,
            commit=None,
        )
        store.write_revision(revision)
        store.mark_stale(loaded.id, reason="test")
        reloaded = store.find_record(loaded.id)
        assert reloaded is not None
        assert reloaded.status == "stale"
    finally:
        store.close()


def test_write_subject_is_idempotent_and_prune_removes_duplicates(
    tmp_path: Path,
) -> None:
    from codeclone.memory.models import MemorySubject

    root = tmp_path / "repo"
    root.mkdir()
    project = resolve_project_identity(root)
    store = SqliteEngineeringMemoryStore(tmp_path / "memory.sqlite3")
    try:
        store.initialize(project)
        record = _sample_record(project_id=project.id)
        store.upsert_record(record)
        subject = MemorySubject(
            id=generate_memory_id(prefix="subj"),
            memory_id=record.id,
            subject_kind="path",
            subject_key="codeclone/memory/store.py",
            relation="about",
        )
        store.write_subject(subject)
        duplicate = MemorySubject(
            id=generate_memory_id(prefix="subj"),
            memory_id=record.id,
            subject_kind="path",
            subject_key="codeclone/memory/store.py",
            relation="about",
        )
        store.write_subject(duplicate)
        store.commit()
        assert len(store.list_subjects_for_memory(record.id)) == 1

        insert_subject = """
            INSERT INTO memory_subjects(
                id, memory_id, subject_kind, subject_key, relation
            )
            VALUES (?, ?, ?, ?, ?)
            """
        store._conn.execute(
            insert_subject,
            (
                generate_memory_id(prefix="subj"),
                record.id,
                "path",
                "codeclone/memory/other.py",
                "about",
            ),
        )
        store._conn.execute(
            insert_subject,
            (
                generate_memory_id(prefix="subj"),
                record.id,
                "path",
                "codeclone/memory/other.py",
                "about",
            ),
        )
        store.commit()
        row = store._conn.execute(
            "SELECT COUNT(*) FROM memory_subjects WHERE memory_id=?",
            (record.id,),
        ).fetchone()
        assert row is not None
        assert int(row[0]) == 3
        assert len(store.list_subjects_for_memory(record.id)) == 2
        removed = store.prune_duplicate_subjects()
        assert removed == 1
        assert len(store.list_subjects_for_memory(record.id)) == 2
    finally:
        store.close()
