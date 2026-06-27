# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path
from typing import cast

from codeclone.memory.governance import record_candidate
from codeclone.memory.retrieval import query_engineering_memory

from .memory_fixtures import memory_store, seed_path_subject_record


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
