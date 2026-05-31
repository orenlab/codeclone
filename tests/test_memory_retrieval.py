# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

from codeclone.memory.identity import make_identity_key
from codeclone.memory.models import MemoryRecord, MemorySubject, generate_memory_id
from codeclone.memory.project import resolve_project_identity
from codeclone.memory.retrieval import get_relevant_memory, query_engineering_memory
from codeclone.memory.retrieval.ranking import RankingContext, relevance_score
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore
from codeclone.report.meta import current_report_timestamp_utc


def _seed_record(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    path: str,
    statement: str,
) -> MemoryRecord:
    now = current_report_timestamp_utc()
    record = MemoryRecord(
        id=generate_memory_id(),
        project_id=project_id,
        identity_key=make_identity_key(
            type="module_role",
            subject_kind="module",
            subject_key=path.replace("/", ".").removesuffix(".py"),
            discriminator="inventory_module",
        ),
        type="module_role",
        status="active",
        confidence="supported",
        origin="system",
        ingest_source="analysis",
        statement=statement,
        summary=None,
        payload={"module_path": path.replace("/", ".").removesuffix(".py")},
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
    store.upsert_record(record)
    store.write_subject(
        MemorySubject(
            id=generate_memory_id(prefix="subj"),
            memory_id=record.id,
            subject_kind="path",
            subject_key=path,
            relation="about",
        )
    )
    return record


def test_relevance_score_prefers_scope_path_match() -> None:
    now = current_report_timestamp_utc()
    record = MemoryRecord(
        id="mem-1",
        project_id="proj-1",
        identity_key="k1",
        type="contract_note",
        status="active",
        confidence="verified",
        origin="system",
        ingest_source="contract",
        statement="test",
        summary=None,
        payload=None,
        created_at_utc=now,
        updated_at_utc=now,
        last_verified_at_utc=now,
        expires_at_utc=None,
        created_by="test",
        verified_by="human",
        approved_by="human",
        approved_at_utc=now,
        report_digest=None,
        code_fingerprint=None,
        stale_reason=None,
        created_on_branch=None,
        created_at_commit=None,
        verified_on_branch=None,
        verified_at_commit=None,
    )
    subjects = [
        MemorySubject(
            id="subj-1",
            memory_id="mem-1",
            subject_kind="path",
            subject_key="codeclone/memory/sqlite_store.py",
            relation="about",
        )
    ]
    score = relevance_score(
        record=record,
        subjects=subjects,
        context=RankingContext(
            scope_paths=frozenset({"codeclone/memory/sqlite_store.py"}),
            symbols=frozenset(),
            blast_dependents=frozenset(),
        ),
        evidence_count=2,
    )
    assert score > 1.5


def test_get_relevant_memory_ranks_scope_records(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    project = resolve_project_identity(root)
    store = SqliteEngineeringMemoryStore(tmp_path / "memory.sqlite3")
    try:
        store.initialize(project)
        _seed_record(
            store,
            project_id=project.id,
            path="codeclone/memory/sqlite_store.py",
            statement="sqlite store module",
        )
        _seed_record(
            store,
            project_id=project.id,
            path="codeclone/other.py",
            statement="other module",
        )
        result = get_relevant_memory(
            store,
            project_id=project.id,
            scope_paths=("codeclone/memory/sqlite_store.py",),
            scope_resolved_from="explicit",
            max_records=5,
        )
    finally:
        store.close()

    assert result["scope_resolved_from"] == "explicit"
    records = result["records"]
    assert isinstance(records, list)
    assert records
    assert records[0]["statement"] == "sqlite store module"


def test_query_engineering_memory_search_and_status(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    project = resolve_project_identity(root)
    db_path = tmp_path / "memory.sqlite3"
    store = SqliteEngineeringMemoryStore(db_path)
    try:
        store.initialize(project)
        _seed_record(
            store,
            project_id=project.id,
            path="codeclone/memory/service.py",
            statement="engineering memory retrieval service",
        )
        search = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="search",
            query="retrieval",
        )
        status = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="status",
        )
    finally:
        store.close()

    search_payload = search["payload"]
    assert isinstance(search_payload, dict)
    assert search_payload["record_count"] >= 1
    status_payload = status["payload"]
    assert isinstance(status_payload, dict)
    assert status_payload["db_exists"] is True
