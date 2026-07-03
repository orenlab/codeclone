# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from codeclone.memory.exceptions import MemoryContractError
from codeclone.memory.governance import record_candidate
from codeclone.memory.models import generate_memory_id
from codeclone.memory.retrieval import query_engineering_memory
from codeclone.memory.retrieval.service import get_relevant_memory
from codeclone.report.meta import current_report_timestamp_utc

from .memory_fixtures import memory_store, seed_path_subject_record


def _insert_legacy_memory_record_type(
    store: object,
    *,
    project_id: str,
    record_id: str,
    record_type: str,
    path: str,
) -> None:
    from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore

    assert isinstance(store, SqliteEngineeringMemoryStore)
    now = current_report_timestamp_utc()
    store._conn.execute(
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
            record_id,
            project_id,
            f"{record_type}:path:{path}:legacy",
            record_type,
            "active",
            "inferred",
            "agent",
            "agent",
            "legacy non-canonical memory record",
            None,
            None,
            now,
            now,
            None,
            None,
            "legacy-test",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            "1.7",
        ),
    )
    store._conn.execute(
        """
        INSERT INTO memory_subjects(id, memory_id, subject_kind, subject_key, relation)
        VALUES (?, ?, ?, ?, ?)
        """,
        (generate_memory_id(prefix="subj"), record_id, "path", path, "about"),
    )
    store._conn.commit()


def test_query_engineering_memory_get_stale_drafts_coverage(
    tmp_path: Path,
) -> None:
    with memory_store(tmp_path) as (root, project, store, db_path):
        active = seed_path_subject_record(
            store,
            project_id=project.id,
            path="pkg/active.py",
            statement="active path record",
        )
        draft = record_candidate(
            store,
            project=project,
            record_type="change_rationale",
            statement="draft for drafts mode",
            subject_path="pkg/active.py",
            max_candidates=100,
        )
        store.mark_stale(active.id, reason="test")

        get_payload = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="get",
            record_id=active.id,
        )
        stale_payload = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="stale",
            max_results=10,
        )
        drafts_payload = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="drafts",
            max_results=10,
        )
        coverage_payload = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="coverage",
            scope=["pkg/active.py", "pkg/missing.py"],
        )

    assert get_payload["status"] == "ok"
    get_result = get_payload["payload"]
    assert isinstance(get_result, dict)
    record_summary = get_result.get("record")
    assert isinstance(record_summary, dict)
    assert record_summary.get("id") == active.id

    stale_records = stale_payload["payload"]
    assert isinstance(stale_records, dict)
    assert stale_records.get("record_count", 0) >= 1

    draft_records = drafts_payload["payload"]
    assert isinstance(draft_records, dict)
    assert any(
        item.get("id") == draft.id
        for item in draft_records.get("records", [])
        if isinstance(item, dict)
    )

    coverage = coverage_payload["payload"]
    assert isinstance(coverage, dict)
    assert coverage.get("scope_paths_total") == 2


def test_query_engineering_memory_coverage_accepts_path_alias(
    tmp_path: Path,
) -> None:
    with memory_store(tmp_path) as (root, project, store, db_path):
        coverage_payload = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="coverage",
            path="pkg/active.py",
        )
    coverage = coverage_payload["payload"]
    assert isinstance(coverage, dict)
    assert coverage.get("scope_paths_total") == 1


def test_query_engineering_memory_get_missing_record(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, db_path):
        result = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="get",
            record_id="missing-id",
        )
    assert result["status"] == "not_found"


def test_memory_retrieval_quarantines_legacy_invalid_record_type(
    tmp_path: Path,
) -> None:
    with memory_store(tmp_path) as (root, project, store, db_path):
        record_id = "mem-legacy-invalid-type"
        _insert_legacy_memory_record_type(
            store,
            project_id=project.id,
            record_id=record_id,
            record_type="decision",
            path="pkg/legacy.py",
        )

        for_path = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="for_path",
            path="pkg/legacy.py",
            max_results=10,
            include_stale=True,
        )
        get_payload = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="get",
            record_id=record_id,
        )
        relevant = get_relevant_memory(
            store,
            project_id=project.id,
            scope_paths=("pkg/legacy.py",),
            scope_resolved_from="test",
            max_records=5,
            include_stale=True,
        )

    assert for_path["status"] == "ok"
    payload = for_path["payload"]
    assert isinstance(payload, dict)
    assert payload["record_count"] == 0
    assert get_payload["status"] == "not_found"
    assert relevant["record_count"] == 0


def test_query_engineering_memory_rejects_invalid_filter_literals(
    tmp_path: Path,
) -> None:
    with (
        memory_store(tmp_path) as (root, project, store, db_path),
        pytest.raises(MemoryContractError, match="record_type"),
    ):
        query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="search",
            query="legacy",
            filters={"types": ["decision"]},
        )


def test_handle_semantic_search_disabled_block(tmp_path: Path) -> None:
    from codeclone.memory.retrieval.service import _handle_semantic_search_mode

    with memory_store(tmp_path) as (_root, project, store, _db_path):
        payload = _handle_semantic_search_mode(
            store,
            project_id=project.id,
            query="recover checkpoint",
            filter_types=(),
            statuses=("active",),
            filter_confidences=(),
            match_mode="any",
            max_results=5,
            detail_level="compact",
            include_stale=False,
            include_drafts=False,
            semantic_index=None,
            embedding_provider=None,
            provider_label=None,
            semantic_reason=None,
            audit_db_path=None,
        )
    semantic = cast(dict[str, object], payload["semantic"])
    assert semantic["used"] is False
    assert semantic["reason"] == "disabled"
