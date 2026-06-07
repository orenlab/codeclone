# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from codeclone.memory.governance import record_candidate
from codeclone.memory.retrieval import query_engineering_memory
from tests.memory_fixtures import (
    make_module_record,
    memory_store,
    seed_document_link,
)


def test_fts_search_matches_any_token(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, db_path):
        seed_document_link(
            store,
            project_id=project.id,
            doc_file="docs/guide/mcp/workflows/change-control.md",
            ref_path="codeclone/surfaces/mcp/server.py",
            statement=(
                "docs/guide/mcp/workflows/change-control.md references MCP workflow."
            ),
            heading="Phase 5: Change control",
        )
        store.rebuild_project_fts(project.id)

        result = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="search",
            query="MCP change control",
            filters={"match_mode": "any"},
        )

    payload = result["payload"]
    assert isinstance(payload, dict)
    records = payload.get("records")
    assert isinstance(records, list)
    assert records
    assert records[0]["type"] == "document_link"


def test_search_finds_agent_draft_after_record_candidate(tmp_path: Path) -> None:
    unique = "long agent draft phrase about paths normalization policy"
    with memory_store(tmp_path) as (root, project, store, db_path):
        record_candidate(
            store,
            project=project,
            record_type="change_rationale",
            statement=unique,
            subject_path="codeclone/memory/paths.py",
            max_candidates=10,
        )
        result = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="search",
            query=unique,
            include_drafts=True,
            filters={"match_mode": "all"},
        )

    payload = result["payload"]
    assert isinstance(payload, dict)
    records = payload.get("records")
    assert isinstance(records, list)
    assert any(
        item.get("statement") == unique for item in records if isinstance(item, dict)
    )


def test_upsert_reactivates_unchanged_record_on_digest_shift(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        record = make_module_record(
            project.id,
            "pkg.mod",
            report_digest="digest-a",
            code_fingerprint="fp-a",
        )
        store.upsert_record(record)
        store.mark_stale(record.id, "report_digest_shift")
        incoming = replace(
            record,
            id=record.id,
            report_digest="digest-b",
            code_fingerprint="fp-b",
        )
        result = store.upsert_record(incoming)
        assert result.action == "unchanged"
        loaded = store.find_by_identity_key(project.id, record.identity_key)
        assert loaded is not None
        assert loaded.status == "active"
        assert loaded.report_digest == "digest-b"
        assert loaded.stale_reason is None


def test_search_like_fallback_when_fts_unavailable(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        seed_document_link(
            store,
            project_id=project.id,
            doc_file="docs/guide.md",
            ref_path="pkg/mod.py",
            statement="like fallback search token alpha",
        )
        with patch.object(store, "_fts_available", return_value=False):
            hits = store.search_records(
                project_id=project.id,
                statement_query="fallback alpha",
                match_mode="all",
                limit=5,
            )
    assert hits
    assert hits[0].statement.startswith("like fallback")
