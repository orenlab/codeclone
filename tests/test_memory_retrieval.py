# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from codeclone.memory.exceptions import MemoryContractError
from codeclone.memory.governance import record_candidate
from codeclone.memory.identity import make_identity_key
from codeclone.memory.models import MemoryRecord, MemorySubject, generate_memory_id
from codeclone.memory.retrieval import get_relevant_memory, query_engineering_memory
from codeclone.memory.retrieval import service as retrieval_service
from codeclone.memory.retrieval.ranking import RankingContext, relevance_score
from codeclone.report.meta import current_report_timestamp_utc

from .memory_fixtures import (
    make_module_record,
    memory_store,
    seed_module_role,
    seed_path_subject_record,
)


def _score_scoped_record(
    record: MemoryRecord,
    *,
    path: str = "pkg/service.py",
    evidence_count: int = 0,
) -> tuple[float, dict[str, object]]:
    subjects = [
        MemorySubject(
            id=f"subj-{record.id}",
            memory_id=record.id,
            subject_kind="path",
            subject_key=path,
            relation="about",
        )
    ]
    score = relevance_score(
        record=record,
        subjects=subjects,
        context=RankingContext.from_scope(
            scope_paths=(path,),
            symbols=(),
            blast_dependents=(),
        ),
        evidence_count=evidence_count,
    )
    summary = retrieval_service._serialize_record_summary(
        record=record,
        subjects=subjects,
        evidence_count=evidence_count,
        relevance_score=score,
    )
    return score, summary


def test_relevance_score_prefers_scope_path_match() -> None:
    now = current_report_timestamp_utc()
    record = MemoryRecord(
        id="mem-1",
        project_id="proj-1",
        identity_key="k1",
        type="contract_note",
        status="active",
        epistemic_rung="verified",
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


def test_relevance_score_boosts_agent_drafts() -> None:
    now = current_report_timestamp_utc()
    record = MemoryRecord(
        id="mem-draft",
        project_id="proj-1",
        identity_key="draft-1",
        type="change_rationale",
        status="draft",
        epistemic_rung="inferred",
        origin="agent",
        ingest_source="agent",
        statement="draft note",
        summary=None,
        payload=None,
        created_at_utc=now,
        updated_at_utc=now,
        last_verified_at_utc=now,
        expires_at_utc=None,
        created_by="agent",
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
    score = relevance_score(
        record=record,
        subjects=[],
        context=RankingContext(
            scope_paths=frozenset(),
            symbols=frozenset(),
            blast_dependents=frozenset(),
        ),
        evidence_count=0,
    )
    assert score >= 0.35


def test_relevance_score_filters_global_contract_notes_for_scope() -> None:
    now = current_report_timestamp_utc()
    record = MemoryRecord(
        id="mem-global",
        project_id="proj-1",
        identity_key="global-contract",
        type="contract_note",
        status="active",
        epistemic_rung="verified",
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


def test_relevance_score_keeps_git_hotspot_below_durable_scope_context() -> None:
    module_record = make_module_record("proj-1", "pkg.service")
    hotspot_record = replace(
        module_record,
        id="mem-hotspot",
        identity_key="hotspot",
        type="risk_note",
        epistemic_rung="verified",
        ingest_source="git",
        statement="pkg/service.py changed 12 times in the last 90 days.",
        payload={
            "risk_kind": "change_hotspot",
            "change_count": 12,
            "period_days": 90,
        },
    )
    module_score, _module_summary = _score_scoped_record(
        module_record,
        evidence_count=7,
    )
    hotspot_score, summary = _score_scoped_record(
        hotspot_record,
        evidence_count=7,
    )

    assert 0.0 < hotspot_score < module_score
    assert summary["retrieval_lane"] == "hotspot_context"


def test_finish_hook_module_role_is_bounded_workflow_context() -> None:
    module_record = make_module_record("proj-1", "pkg.service")
    substantive_record = replace(
        module_record,
        id="mem-rationale",
        identity_key="rationale",
        type="change_rationale",
        status="draft",
        origin="agent",
        ingest_source="agent",
        statement="Keep retrieval provenance separate from durable assertions.",
        created_by="agent",
    )
    workflow_record = replace(
        module_record,
        id="mem-workflow",
        identity_key="workflow",
        status="draft",
        origin="agent",
        ingest_source="agent",
        statement="Patch touched scope includes pkg/service.py.",
        created_by="finish_hook",
    )
    substantive_score, _substantive_summary = _score_scoped_record(substantive_record)
    workflow_score, summary = _score_scoped_record(workflow_record)

    assert 0.0 < workflow_score < substantive_score
    assert summary["retrieval_lane"] == "workflow_context"


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
            epistemic_rung="verified",
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
    coverage = result["coverage"]
    assert isinstance(coverage, dict)
    assert coverage["record_coverage"]["coverage_kind"] == "record_subject_coverage"
    assert coverage["observation_confidence"] == {
        "level": "partial",
        "basis": ["records"],
        "note": (
            "Evidence availability only; not correctness, approval, or edit "
            "authorization."
        ),
    }


def test_get_relevant_memory_reports_unknown_observation_coverage(
    tmp_path: Path,
) -> None:
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        result = get_relevant_memory(
            store,
            project_id=project.id,
            scope_paths=("pkg/unknown.py",),
            scope_resolved_from="explicit",
        )

    coverage = result["coverage"]
    assert isinstance(coverage, dict)
    assert coverage["record_coverage"] == {
        "scope_paths_with_memory": 0,
        "scope_paths_total": 1,
        "coverage_percent": 0,
        "coverage_kind": "record_subject_coverage",
    }
    assert coverage["trajectory_coverage"] == {
        "scope_paths_with_trajectories": 0,
        "scope_paths_total": 1,
        "coverage_percent": 0,
    }
    assert coverage["experience_coverage"] == {
        "scope_families_with_experiences": 0,
        "scope_families_total": 1,
        "coverage_percent": 0,
    }
    assert coverage["observation_confidence"]["level"] == "unknown"


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


def test_get_relevant_memory_includes_scoped_draft_agent_note(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        seed_path_subject_record(
            store,
            project_id=project.id,
            path="codeclone/memory/retrieval/ranking.py",
            statement="approved active note",
        )
        record_candidate(
            store,
            project=project,
            record_type="risk_note",
            statement="agent draft for ranking module",
            subject_path="codeclone/memory/retrieval/ranking.py",
            max_candidates=100,
        )
        result = get_relevant_memory(
            store,
            project_id=project.id,
            scope_paths=("codeclone/memory/retrieval/ranking.py",),
            scope_resolved_from="explicit",
            max_records=5,
        )

    policy = result["retrieval_policy"]
    assert isinstance(policy, dict)
    assert policy["drafts_included"] is True
    assert policy["memory_does_not_authorize_edits"] is True
    records = result["records"]
    assert isinstance(records, list)
    statements = [item["statement"] for item in records if isinstance(item, dict)]
    assert "agent draft for ranking module" in statements


def test_query_for_path_includes_draft_without_include_drafts_flag(
    tmp_path: Path,
) -> None:
    with memory_store(tmp_path) as (root, project, store, db_path):
        record_candidate(
            store,
            project=project,
            record_type="change_rationale",
            statement="draft note on sqlite store",
            subject_path="codeclone/memory/sqlite_store.py",
            max_candidates=100,
        )
        result = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="for_path",
            path="codeclone/memory/sqlite_store.py",
            include_drafts=False,
        )

    payload = result["payload"]
    assert isinstance(payload, dict)
    records = payload.get("records")
    assert isinstance(records, list)
    assert any(
        item.get("statement") == "draft note on sqlite store"
        for item in records
        if isinstance(item, dict)
    )


def test_get_relevant_memory_requires_scope_or_symbols(tmp_path: Path) -> None:
    with (
        memory_store(tmp_path) as (_root, project, store, _db_path),
        pytest.raises(MemoryContractError, match="scope"),
    ):
        get_relevant_memory(
            store,
            project_id=project.id,
            scope_paths=(),
            symbols=(),
            scope_resolved_from="test",
        )


def _agent_draft_record(
    *,
    record_id: str,
    payload: dict[str, object],
) -> MemoryRecord:
    """Two records identical but for their payload: the laundering comparison.

    Everything the ranking formula reads other than the payload is held equal,
    so a score difference can only come from the evidence lever under test.
    """
    now = current_report_timestamp_utc()
    return MemoryRecord(
        id=record_id,
        project_id="proj-1",
        identity_key=f"k-{record_id}",
        type="risk_note",
        status="draft",
        epistemic_rung="inferred",
        origin="agent",
        ingest_source="agent",
        statement="Measured, X = 42.",
        summary=None,
        payload=payload,
        created_at_utc=now,
        updated_at_utc=now,
        last_verified_at_utc=now,
        expires_at_utc=None,
        created_by="agent",
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


def test_evidence_reference_buys_no_served_score_or_rung() -> None:
    """The laundering case: a genuine but irrelevant run reference buys nothing.

    An agent writes "Measured, X = 42", attaches a real run_id that has nothing
    to do with the claim, and the reference validates -- because the store can
    only check that the artifact exists, never that it entails the statement.
    So the record must rank and read exactly as it would with no reference at
    all. Held equal: type, status, origin, epistemic_rung, subjects, scope.
    """
    bare = _agent_draft_record(
        record_id="mem-bare", payload={"subject_path": "pkg/service.py"}
    )
    laundered = _agent_draft_record(
        record_id="mem-laundered",
        payload={
            "subject_path": "pkg/service.py",
            "evidence_status": "validated_reference",
        },
    )

    bare_score, bare_summary = _score_scoped_record(bare, evidence_count=0)
    laundered_score, laundered_summary = _score_scoped_record(
        laundered, evidence_count=3
    )

    assert laundered_score == bare_score, (
        "a valid-but-irrelevant evidence reference moved the served relevance "
        f"score: {laundered_score} vs {bare_score}"
    )
    assert laundered_summary["relevance_score"] == bare_summary["relevance_score"]
    assert laundered_summary["epistemic_rung"] == "inferred"
    assert bare_summary["epistemic_rung"] == "inferred"
    # The reference is still visible -- unmoved is not the same as hidden.
    assert laundered_summary["evidence_count"] == 3


def test_attested_evidence_without_a_reference_marker_keeps_its_ranking_bonus() -> None:
    """The opposite boundary: the guard must not be a blanket kill.

    Evidence written by finish(propose_memory=true) carries no evidence_status
    marker, and its ranking bonus is exactly what it was before typed refs
    existed. This is what makes "no existing served score moves" true rather
    than merely asserted -- and it proves the P1 guard is reachable by SOME
    input and dead for others, not dead for all.
    """
    attested = _agent_draft_record(
        record_id="mem-attested", payload={"subject_path": "pkg/service.py"}
    )
    with_evidence, _ = _score_scoped_record(attested, evidence_count=3)
    without_evidence, _ = _score_scoped_record(attested, evidence_count=0)
    assert with_evidence == round(without_evidence + 0.06, 4), (
        "unmarked attested evidence lost its pre-existing ranking bonus: "
        f"{with_evidence} vs {without_evidence}"
    )


def test_served_summary_distinguishes_attached_from_validated_reference() -> None:
    """A reader can tell an unchecked ref from one resolved against a real run."""
    attached = _agent_draft_record(
        record_id="mem-attached",
        payload={"subject_path": "pkg/service.py", "evidence_status": "attached"},
    )
    validated = _agent_draft_record(
        record_id="mem-validated",
        payload={
            "subject_path": "pkg/service.py",
            "evidence_status": "validated_reference",
        },
    )
    plain = _agent_draft_record(
        record_id="mem-plain", payload={"subject_path": "pkg/service.py"}
    )

    _, attached_summary = _score_scoped_record(attached, evidence_count=1)
    _, validated_summary = _score_scoped_record(validated, evidence_count=1)
    _, plain_summary = _score_scoped_record(plain, evidence_count=1)

    assert attached_summary["evidence_status"] == "attached"
    assert validated_summary["evidence_status"] == "validated_reference"
    assert "evidence_status" not in plain_summary
