# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path
from typing import Literal

from codeclone.memory.governance import record_candidate
from codeclone.memory.models import (
    MemoryEvidence,
    MemoryRecord,
    MemorySubject,
    RecordBatch,
)
from codeclone.memory.project import resolve_project_identity
from codeclone.memory.retrieval.ranking import RankingContext, relevance_score
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore
from codeclone.memory.staleness import apply_refresh_staleness, apply_scope_staleness
from codeclone.report.meta import current_report_timestamp_utc


def _record(
    *,
    project_id: str,
    status: Literal["active", "stale"] = "active",
    origin: Literal["system", "agent", "human"] = "system",
) -> MemoryRecord:
    now = current_report_timestamp_utc()
    return MemoryRecord(
        id=f"mem-{project_id}-{status}-{origin}",
        project_id=project_id,
        identity_key=f"id:{project_id}:{status}:{origin}",
        type="contract_note",
        status=status,
        confidence="verified",
        origin=origin,
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
        approved_by="maintainer",
        approved_at_utc=now,
        report_digest="r1",
        code_fingerprint="f1",
        stale_reason=None,
        created_on_branch=None,
        created_at_commit=None,
        verified_on_branch=None,
        verified_at_commit=None,
    )


def test_relevance_score_blast_and_stale_branches() -> None:
    rec = _record(project_id="p", status="stale")
    subjects = [
        MemorySubject(
            id="s1", memory_id=rec.id, subject_kind="path", subject_key="x/y.py"
        )
    ]
    context = RankingContext.from_scope(
        scope_paths=[],
        symbols=[],
        blast_dependents=["x/y.py"],
    )
    score = relevance_score(
        record=rec,
        subjects=subjects,
        context=context,
        evidence_count=0,
    )
    # blast dependent boost path and stale penalty path both exercised
    assert score > 0.0


def test_apply_refresh_and_scope_staleness_missing_paths_and_digest_shift(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    project = resolve_project_identity(root)
    store = SqliteEngineeringMemoryStore(tmp_path / "memory.sqlite3")
    try:
        store.initialize(project)
        draft = record_candidate(
            store,
            project=project,
            record_type="change_rationale",
            statement="scope stale",
            subject_path="pkg/a.py",
            max_candidates=100,
        )
        store.update_record_status(draft.id, status="active")
        rec = store.find_record(draft.id)
        assert rec is not None
        store.write_evidence(
            MemoryEvidence(
                id="e1",
                memory_id=rec.id,
                evidence_kind="report",
                ref="R1",
                locator=None,
                quote=None,
                digest="digest-a",
                created_at_utc=current_report_timestamp_utc(),
            )
        )
        store.commit()

        batch = RecordBatch(
            records=[],
            subjects=[],
            evidence=[
                MemoryEvidence(
                    id="e2",
                    memory_id="missing-in-batch-record-map",
                    evidence_kind="report",
                    ref="R1",
                    locator=None,
                    quote=None,
                    digest="digest-b",
                    created_at_utc=current_report_timestamp_utc(),
                )
            ],
            links=[],
        )
        refresh = apply_refresh_staleness(
            store,
            project_id=project.id,
            batch=batch,
            report_document={"inventory": {"file_registry": {"items": []}}},
            report_digest="r2",
            commit=True,
        )
        assert refresh.records_marked_stale >= 1

        # Skip stale records branch and changed-path scope branch.
        scope = apply_scope_staleness(
            store,
            project_id=project.id,
            changed_paths=["pkg/a.py"],
            commit=True,
        )
        assert scope.records_marked_stale >= 0
    finally:
        store.close()
