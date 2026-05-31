# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

from codeclone.memory.identity import make_identity_key
from codeclone.memory.models import MemoryRecord, MemorySubject, generate_memory_id
from codeclone.memory.retrieval import get_relevant_memory, query_engineering_memory
from codeclone.memory.retrieval.ranking import RankingContext, relevance_score
from codeclone.report.meta import current_report_timestamp_utc

from .memory_fixtures import (
    memory_store,
    seed_module_role,
    seed_path_subject_record,
)


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
    assert score > 1.0


def test_relevance_score_filters_global_contract_notes_for_scope() -> None:
    now = current_report_timestamp_utc()
    record = MemoryRecord(
        id="mem-global",
        project_id="proj-1",
        identity_key="global-contract",
        type="contract_note",
        status="active",
        confidence="verified",
        origin="system",
        ingest_source="contract",
        statement="CACHE_VERSION is 2.8",
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
            id="subj-global",
            memory_id="mem-global",
            subject_kind="config_key",
            subject_key="CACHE_VERSION",
            relation="about",
        )
    ]
    score = relevance_score(
        record=record,
        subjects=subjects,
        context=RankingContext.from_scope(
            scope_paths=("codeclone/memory/ingest/mcp_sync.py",),
            symbols=(),
            blast_dependents=(),
        ),
        evidence_count=2,
    )
    assert score == 0.0


def test_get_relevant_memory_ranks_module_role_for_scoped_path(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        seed_module_role(
            store,
            project_id=project.id,
            file_path="codeclone/memory/ingest/mcp_sync.py",
            statement="mcp sync ingest module",
        )
        now = current_report_timestamp_utc()
        global_record = MemoryRecord(
            id=generate_memory_id(),
            project_id=project.id,
            identity_key=make_identity_key(
                type="contract_note",
                subject_kind="config_key",
                subject_key="CACHE_VERSION",
                discriminator="cache_version",
            ),
            type="contract_note",
            status="active",
            confidence="verified",
            origin="system",
            ingest_source="contract",
            statement="CACHE_VERSION constant",
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
        store.upsert_record(global_record)
        store.write_subject(
            MemorySubject(
                id=generate_memory_id(prefix="subj"),
                memory_id=global_record.id,
                subject_kind="config_key",
                subject_key="CACHE_VERSION",
                relation="about",
            )
        )
        result = get_relevant_memory(
            store,
            project_id=project.id,
            scope_paths=("codeclone/memory/ingest/mcp_sync.py",),
            scope_resolved_from="explicit",
            max_records=5,
        )

    records = result["records"]
    assert isinstance(records, list)
    assert records
    assert records[0]["statement"] == "mcp sync ingest module"


def test_query_engineering_memory_for_symbol_falls_back_to_module_role(
    tmp_path: Path,
) -> None:
    with memory_store(tmp_path) as (root, project, store, db_path):
        seed_module_role(
            store,
            project_id=project.id,
            file_path="codeclone/memory/ingest/mcp_sync.py",
            statement="module role for mcp sync",
        )
        result = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="for_symbol",
            symbol="codeclone.memory.ingest.mcp_sync.execute_mcp_memory_sync",
        )

    payload = result["payload"]
    assert isinstance(payload, dict)
    records = payload.get("records")
    assert isinstance(records, list)
    assert records
    assert records[0]["type"] == "module_role"


def test_get_relevant_memory_ranks_scope_records(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        seed_path_subject_record(
            store,
            project_id=project.id,
            path="codeclone/memory/sqlite_store.py",
            statement="sqlite store module",
        )
        seed_path_subject_record(
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

    assert result["scope_resolved_from"] == "explicit"
    records = result["records"]
    assert isinstance(records, list)
    assert records
    assert records[0]["statement"] == "sqlite store module"


def test_query_engineering_memory_search_and_status(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, db_path):
        seed_path_subject_record(
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

    search_payload = search["payload"]
    assert isinstance(search_payload, dict)
    assert search_payload["record_count"] >= 1
    status_payload = status["payload"]
    assert isinstance(status_payload, dict)
    assert status_payload["db_exists"] is True


def test_query_engineering_memory_for_path_finds_module_role(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, db_path):
        seed_module_role(
            store,
            project_id=project.id,
            file_path="codeclone/memory/sqlite_store.py",
            statement="codeclone.memory.sqlite_store is an analyzed Python module.",
        )
        result = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="for_path",
            path="codeclone/memory/sqlite_store.py",
        )

    payload = result["payload"]
    assert isinstance(payload, dict)
    records = payload.get("records")
    assert isinstance(records, list)
    assert records
    assert records[0]["type"] == "module_role"
    subjects = records[0].get("subjects")
    assert isinstance(subjects, list)
    keys = {
        (item["subject_kind"], item["subject_key"], item["relation"])
        for item in subjects
        if isinstance(item, dict)
    }
    assert len(subjects) == len(keys)
