# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from codeclone.memory.exceptions import MemoryContractError
from codeclone.memory.models import MemoryEvidence, MemoryRecord
from codeclone.memory.retrieval import service as retrieval_service
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

    types, statuses, confidences, mode = retrieval_service._parse_filters(
        {
            "types": ["contract_note"],
            "statuses": ["active"],
            "confidences": ["verified"],
            "match_mode": "all",
        }
    )
    assert types == ("contract_note",)
    assert statuses == ("active",)
    assert confidences == ("verified",)
    assert mode == "all"


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
