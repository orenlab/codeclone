# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from codeclone.memory.identity import make_identity_key
from codeclone.memory.models import MemoryRecord, MemorySubject, generate_memory_id
from codeclone.memory.search_index import (
    build_search_text,
    fts_match_expression,
    like_match_expression,
    tokenize_query,
)
from codeclone.report.meta import current_report_timestamp_utc


def _sample_record() -> MemoryRecord:
    now = current_report_timestamp_utc()
    return MemoryRecord(
        id=generate_memory_id(),
        project_id="proj-1",
        identity_key=make_identity_key(
            type="contract_note",
            subject_kind="contract",
            subject_key="CACHE_VERSION",
            discriminator="schema_constant",
        ),
        type="contract_note",
        status="active",
        confidence="verified",
        origin="system",
        ingest_source="contract",
        statement="memory search helpers",
        summary="summary text",
        payload={"tags": ["alpha", "beta"], "path": "pkg/mod.py"},
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


def test_tokenize_and_fts_match_modes() -> None:
    assert tokenize_query("  ") == ()
    assert tokenize_query("a") == ()
    any_expr = fts_match_expression("MCP change", match_mode="any")
    all_expr = fts_match_expression("MCP change", match_mode="all")
    assert any_expr is not None
    assert all_expr is not None
    assert " AND " in all_expr
    assert fts_match_expression("", match_mode="any") is None


def test_like_match_expression_all_and_any() -> None:
    any_clauses, any_params = like_match_expression("foo bar", match_mode="any")
    all_clauses, all_params = like_match_expression("foo bar", match_mode="all")
    assert any_clauses and any_params
    assert all_clauses and all_params
    assert len(all_params) == 2
    empty_clauses, empty_params = like_match_expression("x", match_mode="any")
    assert empty_clauses == []
    assert empty_params == []


def test_build_search_text_includes_subjects_and_payload() -> None:
    record = _sample_record()
    subjects = [
        MemorySubject(
            id="subj-1",
            memory_id=record.id,
            subject_kind="path",
            subject_key="codeclone/memory/search_index.py",
            relation="about",
        )
    ]
    text = build_search_text(record=record, subjects=subjects)
    assert "memory search helpers" in text
    assert "search_index.py" in text
    assert "alpha" in text
