# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

from codeclone.memory.models import MemoryEvidence, MemorySubject, generate_memory_id
from codeclone.memory.retrieval import service as retrieval_service
from codeclone.memory.retrieval.ranking import RankingContext
from codeclone.report.meta import current_report_timestamp_utc

from .memory_fixtures import (
    memory_store,
    seed_module_role,
    seed_trajectory_audit_workflow,
)


def test_store_batch_loaders_preserve_empty_and_populated_results(
    tmp_path: Path,
) -> None:
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        first = seed_module_role(
            store,
            project_id=project.id,
            file_path="pkg/first.py",
        )
        second = seed_module_role(
            store,
            project_id=project.id,
            file_path="pkg/second.py",
        )
        store.write_evidence(
            MemoryEvidence(
                id=generate_memory_id(prefix="evid"),
                memory_id=first.id,
                evidence_kind="report",
                ref="report-a",
                locator=None,
                quote=None,
                digest=None,
                created_at_utc=current_report_timestamp_utc(),
            )
        )
        missing_id = "mem-missing"

        subjects = store.list_subjects_for_memories(
            (second.id, first.id, first.id, missing_id)
        )
        evidence = store.count_evidence_for_memories(
            (second.id, first.id, first.id, missing_id)
        )

    assert list(subjects) == sorted({first.id, second.id, missing_id})
    assert all(isinstance(item, MemorySubject) for item in subjects[first.id])
    assert subjects[missing_id] == []
    assert evidence[first.id] == 1
    assert evidence[second.id] == 0
    assert evidence[missing_id] == 0


def test_rank_records_uses_bounded_batch_queries(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        records = [
            seed_module_role(
                store,
                project_id=project.id,
                file_path=f"pkg/mod_{index}.py",
            )
            for index in range(20)
        ]
        statements: list[str] = []
        store.connection.set_trace_callback(statements.append)
        try:
            payload, truncated = retrieval_service._rank_records(
                store,
                project_id=project.id,
                candidates=records,
                context=RankingContext.from_scope(
                    scope_paths=(),
                    symbols=(),
                    blast_dependents=(),
                ),
                max_records=20,
                detail_level="compact",
            )
        finally:
            store.connection.set_trace_callback(None)

    subject_queries = [
        statement for statement in statements if "FROM memory_subjects" in statement
    ]
    evidence_queries = [
        statement for statement in statements if "FROM memory_evidence" in statement
    ]
    assert len(payload) == 20
    assert truncated is False
    assert len(subject_queries) == 1
    assert len(evidence_queries) == 1


def test_patch_trails_load_in_one_batch(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, _db_path):
        audit_db = tmp_path / "audit.sqlite3"
        seed_trajectory_audit_workflow(root=root, audit_db=audit_db)
        trajectory = store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        ).trajectories[0]
        statements: list[str] = []
        store.connection.set_trace_callback(statements.append)
        try:
            trails = retrieval_service._load_patch_trails_for_trajectories(
                store,
                trajectory_ids=(trajectory.id, trajectory.id, "traj-missing"),
            )
        finally:
            store.connection.set_trace_callback(None)

    patch_trail_queries = [
        statement
        for statement in statements
        if "FROM memory_trajectory_patch_trails" in statement
    ]
    assert set(trails) == {trajectory.id}
    assert len(patch_trail_queries) == 1
