# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

from codeclone.memory.models import MemoryRecord
from codeclone.memory.semantic.projection import (
    is_indexed_audit_event,
    is_indexed_memory_type,
    project_audit_event,
    project_memory_record,
    text_hash,
)


def _record(*, statement: str, summary: str | None = None) -> MemoryRecord:
    return MemoryRecord(
        id="mem-1",
        project_id="proj-1",
        identity_key="key-1",
        type="contract_note",
        status="active",
        confidence="verified",
        origin="system",
        ingest_source="contract",
        statement=statement,
        summary=summary,
        payload=None,
        created_at_utc="2026-01-01T00:00:00Z",
        updated_at_utc="2026-01-01T00:00:00Z",
        last_verified_at_utc=None,
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


def test_text_hash_is_idempotent_and_distinguishing() -> None:
    assert text_hash("same") == text_hash("same")
    assert text_hash("a") != text_hash("b")


def test_indexed_type_predicates() -> None:
    assert is_indexed_memory_type("contract_note") is True
    assert is_indexed_memory_type("change_rationale") is True
    # structural records are not semantically indexed
    assert is_indexed_memory_type("module_role") is False
    assert is_indexed_memory_type("test_anchor") is False
    assert is_indexed_audit_event("intent.declared") is True
    assert is_indexed_audit_event("workspace.gc_completed") is False


def test_project_memory_record_is_deterministic() -> None:
    record = _record(statement="recover keeps the checkpoint as before-run")
    first = project_memory_record(record, subject_path="codeclone/x.py")
    second = project_memory_record(record, subject_path="codeclone/x.py")
    assert first == second
    assert first.text_hash == second.text_hash
    assert first.source == "memory"
    assert first.source_id == "mem-1"
    assert first.kind == "contract_note"
    assert first.subject_path == "codeclone/x.py"
    assert first.status == "active"
    assert "contract_note" in first.text
    assert "codeclone/x.py" in first.text
    assert "recover keeps the checkpoint" in first.text


def test_project_memory_record_text_hash_tracks_content() -> None:
    base = project_memory_record(_record(statement="alpha"))
    changed_statement = project_memory_record(_record(statement="beta"))
    assert base.text_hash != changed_statement.text_hash
    # summary participates in the projected text
    with_summary = project_memory_record(
        _record(statement="alpha", summary="one-line essence")
    )
    assert with_summary.text_hash != base.text_hash
    assert "one-line essence" in with_summary.text


def test_project_audit_event_is_deterministic() -> None:
    first = project_audit_event(
        event_id="evt_1",
        event_type="intent.declared",
        summary="Fix audit gap: capture intent description",
    )
    second = project_audit_event(
        event_id="evt_1",
        event_type="intent.declared",
        summary="Fix audit gap: capture intent description",
    )
    assert first == second
    assert first.source == "audit"
    assert first.kind == "intent.declared"
    assert first.subject_path is None
    assert "intent.declared" in first.text
    assert "Fix audit gap" in first.text
