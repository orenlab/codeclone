# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

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
            doc_file="docs/mcp.md",
            ref_path="codeclone/surfaces/mcp/server.py",
            statement="docs/mcp.md (Phase 5: Change control) references MCP workflow.",
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
