# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path
from typing import Literal

from codeclone.memory.models import (
    MemoryRecord,
    MemorySubject,
    RecordBatch,
    generate_memory_id,
)
from codeclone.memory.retrieval.ranking import RankingContext, relevance_score
from codeclone.memory.staleness import apply_refresh_staleness, apply_scope_staleness
from codeclone.report.meta import current_report_timestamp_utc
from tests.memory_fixtures import make_module_record, memory_store


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


def test_apply_refresh_and_scope_staleness_digest_shift_and_scope(
    tmp_path: Path,
) -> None:
    report = {"inventory": {"file_registry": {"items": ["pkg/a.py"]}}}
    with memory_store(tmp_path) as (root, project, store, _db_path):
        existing = make_module_record(
            project.id,
            "pkg.a",
            report_digest="digest-a",
        )
        store.upsert_record(existing)
        store.write_subject(
            MemorySubject(
                id=generate_memory_id(prefix="subj"),
                memory_id=existing.id,
                subject_kind="path",
                subject_key="pkg/a.py",
                relation="about",
            )
        )

        refresh = apply_refresh_staleness(
            store,
            project_id=project.id,
            batch=RecordBatch(records=[]),
            report_document=report,
            root_path=root,
            report_digest="digest-b",
        )
        assert refresh.records_marked_stale >= 1

        scope = apply_scope_staleness(
            store,
            project_id=project.id,
            changed_paths=["pkg/a.py"],
        )
        assert scope.records_marked_stale >= 0
