# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import cast

import pytest

from codeclone.memory.exceptions import MemoryContractError
from codeclone.memory.experience.models import Experience
from codeclone.memory.models import MemoryEvidence, MemoryRecord, MemorySubject
from codeclone.memory.retrieval import service as retrieval_service
from codeclone.memory.retrieval.ranking import RankingContext
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore
from codeclone.report.meta import current_report_timestamp_utc


def _record(*, status: str = "active", confidence: str = "verified") -> MemoryRecord:
    now = current_report_timestamp_utc()
    return MemoryRecord(
        id="mem-1",
        project_id="proj",
        identity_key="id-1",
        type="contract_note",
        status=status,  # type: ignore[arg-type]
        confidence=confidence,  # type: ignore[arg-type]
        origin="system",
        ingest_source="analysis",
        statement="hello",
        summary=None,
        payload=None,
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


def _stub_store(records: list[MemoryRecord]) -> object:
    return SimpleNamespace(
        find_record=lambda _record_id: None,
        list_subjects_for_memory=lambda _record_id: [],
        count_evidence_for_memory=lambda _record_id: 0,
        query_records=lambda _query: records,
    )


def test_record_visible_serialize_and_parse_filters_branches() -> None:
    assert (
        retrieval_service._record_visible(
            _record(status="stale"),
            include_stale=False,
            include_drafts=False,
        )
        is False
    )
    assert (
        retrieval_service._record_visible(
            _record(status="active", confidence="inferred"),
            include_stale=False,
            include_drafts=False,
        )
        is False
    )

    evidence = MemoryEvidence(
        id="e1",
        memory_id="mem-1",
        evidence_kind="report",
        ref="ref-1",
        locator=None,
        quote=None,
        digest=None,
        created_at_utc=current_report_timestamp_utc(),
    )
    payload = retrieval_service._serialize_evidence(evidence)
    assert payload["evidence_kind"] == "report"

    types, statuses, confidences, mode, include_routine = (
        retrieval_service._parse_filters(
            {
                "types": ["contract_note"],
                "statuses": ["active"],
                "confidences": ["verified"],
                "match_mode": "all",
            }
        )
    )
    assert types == ("contract_note",)
    assert statuses == ("active",)
    assert confidences == ("verified",)
    assert mode == "all"
    assert include_routine is False


def test_retrieval_service_error_and_fallback_branches() -> None:
    with pytest.raises(TypeError, match="Path instances"):
        retrieval_service._handle_status_mode(
            mode="status",
            root_path="bad",
            db_path="bad",
            backend="sqlite",
        )

    with pytest.raises(MemoryContractError, match="mode=get requires record_id"):
        retrieval_service._handle_get_mode(
            _stub_store([]),  # type: ignore[arg-type]
            mode="get",
            project_id="proj",
            record_id=None,
        )

    assert retrieval_service._search_statuses_for_mode(
        "search",
        filter_statuses=("active",),
        include_stale=True,
        include_drafts=True,
    ) == ("active",)

    with pytest.raises(MemoryContractError, match="requires query"):
        retrieval_service._require_query_field("   ", mode="search", field="query")


def test_for_symbol_and_unknown_mode_paths() -> None:
    store_with_records = _stub_store([_record()])
    got = retrieval_service._fetch_for_symbol_mode_records(
        store_with_records,  # type: ignore[arg-type]
        project_id="proj",
        symbol="pkg.mod.symbol",
        filter_types=(),
        statuses=("active",),
        max_results=10,
    )
    assert len(got) == 1

    empty = retrieval_service._fetch_for_symbol_mode_records(
        _stub_store([]),  # type: ignore[arg-type]
        project_id="proj",
        symbol="nosplit",
        filter_types=(),
        statuses=("active",),
        max_results=10,
    )
    assert empty == ()

    fallback = retrieval_service._records_for_list_mode(
        _stub_store([]),  # type: ignore[arg-type]
        mode="unknown",
        project_id="proj",
        path=None,
        symbol=None,
        query=None,
        filter_types=(),
        statuses=("active",),
        filter_confidences=(),
        max_results=10,
        match_mode="any",
    )
    assert fallback == ()


def test_normalize_detail_level_and_compact_serialization() -> None:
    assert retrieval_service._normalize_detail_level("full") == "full"
    assert retrieval_service._normalize_detail_level("compact") == "compact"
    assert retrieval_service._normalize_detail_level("summary") == "compact"

    with pytest.raises(MemoryContractError, match="detail_level must be"):
        retrieval_service._normalize_detail_level("verbose")

    record = replace(_record(), statement="x" * 200)
    compact = retrieval_service._serialize_record_summary(
        record=record,
        subjects=[],
        evidence_count=0,
        detail_level="compact",
    )
    full = retrieval_service._serialize_record_summary(
        record=record,
        subjects=[],
        evidence_count=0,
        detail_level="full",
    )
    assert compact["statement_length"] == 200
    assert compact["statement_truncated"] is True
    assert "payload" not in compact
    assert full["statement"] == "x" * 200
    assert full["payload"] is None


def test_compact_record_subjects_are_bounded_and_scope_relevant() -> None:
    record = _record()
    subjects = [
        MemorySubject(
            id=f"subject-{index}",
            memory_id=record.id,
            subject_kind="path",
            subject_key=f"noise/path_{index}.py",
            relation="about",
        )
        for index in range(10)
    ]
    subjects.append(
        MemorySubject(
            id="subject-relevant",
            memory_id=record.id,
            subject_kind="path",
            subject_key="pkg/service.py",
            relation="about",
        )
    )
    context = RankingContext.from_scope(
        scope_paths=("pkg/service.py",),
        symbols=(),
        blast_dependents=(),
    )

    compact = retrieval_service._serialize_record_summary(
        record=record,
        subjects=subjects,
        evidence_count=0,
        detail_level="compact",
        context=context,
    )
    full = retrieval_service._serialize_record_summary(
        record=record,
        subjects=subjects,
        evidence_count=0,
        detail_level="full",
        context=context,
    )

    assert {
        "subject_count": compact["subject_count"],
        "subjects_truncated": compact["subjects_truncated"],
    } == {
        "subject_count": 11,
        "subjects_truncated": True,
    }
    compact_subjects = compact["subjects"]
    assert isinstance(compact_subjects, list)
    assert len(compact_subjects) == retrieval_service.COMPACT_MEMORY_SUBJECT_LIMIT
    assert compact_subjects[0]["subject_key"] == "pkg/service.py"
    full_subjects = full.get("subjects")
    assert isinstance(full_subjects, list)
    assert len(full_subjects) == 11
    assert {"subject_count", "subjects_truncated"}.isdisjoint(full)


def test_visibility_experience_and_subject_priority_edges() -> None:
    assert (
        retrieval_service._record_visible(
            _record(status="historical"),
            include_stale=False,
            include_drafts=False,
        )
        is True
    )

    compact = retrieval_service._experience_detail_payload(
        cast(
            "Experience",
            SimpleNamespace(evidence=[SimpleNamespace(trajectory_id="traj-1")]),
        ),
        detail_level="compact",
        statement_length=20,
        statement="short",
        agent_facets=[{"agent_family": "codex"}, {"agent_family": "claude"}],
    )
    assert compact["dominant_agent_facet"] == {"agent_family": "codex"}
    assert compact["statement_truncated"] is True
    assert compact["multi_agent"] is True

    subject = MemorySubject(
        id="subject",
        memory_id="mem-1",
        subject_kind="symbol",
        subject_key="pkg.mod.run",
        relation="about",
    )
    symbol_context = RankingContext.from_scope(
        scope_paths=(),
        symbols=("pkg.mod.run",),
        blast_dependents=(),
    )
    blast_context = RankingContext.from_scope(
        scope_paths=(),
        symbols=(),
        blast_dependents=("pkg/mod.py",),
    )
    assert retrieval_service._memory_subject_priority(
        subject,
        context=symbol_context,
    )[:2] == (0, -1.0)
    assert retrieval_service._memory_subject_priority(
        replace(subject, subject_kind="path", subject_key="pkg/mod.py"),
        context=blast_context,
    )[:2] == (2, -0.7)


def test_record_relations_filters_external_endpoints_and_trajectory_not_found() -> None:
    from codeclone.memory.models import MemoryLink

    now = current_report_timestamp_utc()
    links = [
        MemoryLink(
            id="link-1",
            project_id="proj",
            from_memory_id="mem-1",
            to_memory_id="external",
            relation="contradicts",
            created_by="test",
            created_at_utc=now,
        )
    ]
    store = SimpleNamespace(
        list_links_for_records=lambda **_kwargs: links,
        find_trajectory=lambda _trajectory_id: None,
    )
    relations = retrieval_service._record_relations(
        cast("SqliteEngineeringMemoryStore", store),
        project_id="proj",
        record_ids=("mem-1",),
    )
    assert relations == {"mem-1": {"contradicted_by": ["external"]}}
    assert retrieval_service._handle_trajectory_get_mode(
        cast("SqliteEngineeringMemoryStore", store),
        mode="trajectory_get",
        project_id="proj",
        record_id="missing",
    ) == {
        "mode": "trajectory_get",
        "status": "not_found",
        "payload": {"trajectory_id": "missing"},
    }
