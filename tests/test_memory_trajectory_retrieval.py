# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from codeclone.audit.events import repo_root_digest
from codeclone.memory.exceptions import MemoryContractError
from codeclone.memory.models import MemoryEvidence, generate_memory_id
from codeclone.memory.retrieval import get_relevant_memory, query_engineering_memory
from codeclone.memory.retrieval.context_coverage import build_context_coverage
from codeclone.memory.trajectory.models import TrajectorySubject
from codeclone.memory.trajectory.retrieval import (
    rank_trajectories_for_scope,
    serialize_trajectory_preview,
)
from codeclone.report.meta import current_report_timestamp_utc

from .memory_fixtures import (
    memory_store,
    seed_path_subject_record,
    seed_routine_analysis_audit,
    seed_trajectory_audit_workflow,
)


def test_get_relevant_memory_returns_scoped_trajectories(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, _db_path):
        audit_db = tmp_path / "audit.sqlite3"
        seed_trajectory_audit_workflow(root=root, audit_db=audit_db)
        seed_path_subject_record(
            store,
            project_id=project.id,
            path="pkg/service.py",
            statement="service memory record",
        )
        store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        )

        result = get_relevant_memory(
            store,
            project_id=project.id,
            scope_paths=("pkg/service.py",),
            scope_resolved_from="explicit",
            max_records=5,
        )

    records = result["records"]
    trajectories = result["trajectories"]
    assert isinstance(records, list)
    assert isinstance(trajectories, list)
    assert records[0]["statement"] == "service memory record"
    assert trajectories
    assert trajectories[0]["type"] == "trajectory"
    assert trajectories[0]["trajectory_id"].startswith("traj-")
    assert trajectories[0]["relevance_score"] > 1.0
    assert "quality_contract" not in trajectories[0]
    assert isinstance(trajectories[0]["subjects_truncated"], bool)
    coverage = result["coverage"]
    assert isinstance(coverage, dict)
    assert coverage["trajectory_coverage"] == {
        "scope_paths_with_trajectories": 1,
        "scope_paths_total": 1,
        "coverage_percent": 100,
    }
    assert coverage["agent_diversity"] == {
        "trajectory_agent_labels": ["test-agent"],
        "trajectory_agent_label_count": 1,
        "experience_agent_families": [],
        "experience_agent_family_count": 0,
    }
    assert coverage["observation_confidence"]["level"] == "supported"


def test_compact_trajectory_preview_preserves_scope_subjects_and_slims_payload(
    tmp_path: Path,
) -> None:
    with memory_store(tmp_path) as (root, project, store, _db_path):
        audit_db = tmp_path / "audit.sqlite3"
        seed_trajectory_audit_workflow(root=root, audit_db=audit_db)
        projection = store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        )
        trajectory = replace(
            projection.trajectories[0],
            subjects=(
                *(
                    TrajectorySubject("path", f"pkg/noise_{index}.py", "about")
                    for index in range(12)
                ),
                TrajectorySubject("path", "pkg/service.py", "about"),
                TrajectorySubject("path", "pkg/service.py", "touched"),
            ),
        )

        compact_results, _truncated = rank_trajectories_for_scope(
            (trajectory,),
            scope_paths=("pkg/service.py",),
            symbols=(),
            detail_level="compact",
        )

    compact = compact_results[0]
    full = serialize_trajectory_preview(trajectory, detail_level="full")
    assert full == serialize_trajectory_preview(trajectory)
    assert "quality_contract" not in compact
    assert "quality_contract" in full
    assert compact["subject_count"] == 14
    assert compact["matched_subject_count"] == 2
    assert compact["subjects_truncated"] is True
    compact_subjects = compact["subjects"]
    assert isinstance(compact_subjects, list)
    assert len(compact_subjects) == 8
    assert [
        subject["subject_key"]
        for subject in compact_subjects
        if isinstance(subject, dict)
    ][:2] == ["pkg/service.py", "pkg/service.py"]
    full_subjects = full["subjects"]
    assert isinstance(full_subjects, list)
    assert len(full_subjects) == 14
    assert "subjects_truncated" not in full
    compact_size = len(json.dumps(compact, sort_keys=True, separators=(",", ":")))
    full_size = len(json.dumps(full, sort_keys=True, separators=(",", ":")))
    assert compact_size < full_size * 0.6


def test_context_coverage_matches_trajectory_module_subject(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, _db_path):
        audit_db = tmp_path / "audit.sqlite3"
        seed_trajectory_audit_workflow(root=root, audit_db=audit_db)
        projection = store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        )
        trajectory = replace(
            projection.trajectories[0],
            subjects=(
                TrajectorySubject("module", "pkg.service", "about"),
                TrajectorySubject("agent", "test-agent/1", "actor"),
            ),
        )

    coverage = build_context_coverage(
        record_coverage={
            "scope_paths_with_memory": 0,
            "scope_paths_total": 1,
            "coverage_percent": 0,
            "coverage_kind": "record_subject_coverage",
        },
        scope_paths=("pkg/service.py", "pkg/other.py"),
        scope_families=frozenset({"pkg"}),
        trajectories=(trajectory,),
        experiences=(),
    )

    assert coverage["trajectory_coverage"] == {
        "scope_paths_with_trajectories": 1,
        "scope_paths_total": 2,
        "coverage_percent": 50,
    }
    observation_confidence = coverage["observation_confidence"]
    assert isinstance(observation_confidence, dict)
    assert observation_confidence["level"] == "partial"


def test_get_relevant_memory_returns_patch_trail_summary(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, _db_path):
        audit_db = tmp_path / "audit.sqlite3"
        root_digest = repo_root_digest(root.resolve())
        writer = __import__(
            "codeclone.audit.writer", fromlist=["SqliteAuditWriter"]
        ).SqliteAuditWriter(
            db_path=audit_db,
            payloads="compact",
            retention_days=30,
        )
        from codeclone.audit.events import (
            EVENT_INTENT_CHECKED,
            EVENT_INTENT_DECLARED,
            EVENT_PATCH_VERIFIED,
            AuditEvent,
        )

        try:
            writer.emit(
                AuditEvent(
                    event_type=EVENT_INTENT_DECLARED,
                    severity="info",
                    repo_root_digest=root_digest,
                    agent_pid=123,
                    agent_label="test-agent",
                    intent_id="intent-traj-001",
                    run_id="run-before",
                    report_digest="a" * 64,
                    status="active",
                    payload={
                        "intent_description": "recover service",
                        "scope": {"allowed_files": ["pkg/service.py", "pkg/helper.py"]},
                        "workspace_registered": True,
                        "ttl_seconds": 3600,
                        "lease_seconds": 600,
                    },
                )
            )
            writer.emit(
                AuditEvent(
                    event_type=EVENT_INTENT_CHECKED,
                    severity="info",
                    repo_root_digest=root_digest,
                    agent_pid=123,
                    agent_label="test-agent",
                    intent_id="intent-traj-001",
                    run_id="run-before",
                    report_digest="a" * 64,
                    status="clean",
                    payload={
                        "status": "clean",
                        "declared_scope": ["pkg/service.py", "pkg/helper.py"],
                        "actual_changed_files": ["pkg/service.py"],
                        "unexpected_files": [],
                        "forbidden_touched": [],
                        "required_action": None,
                        "message": "clean",
                    },
                )
            )
            writer.emit(
                AuditEvent(
                    event_type=EVENT_PATCH_VERIFIED,
                    severity="info",
                    repo_root_digest=root_digest,
                    agent_pid=123,
                    agent_label="test-agent",
                    intent_id="intent-traj-001",
                    run_id="run-after",
                    report_digest="b" * 64,
                    status="accepted",
                    payload={
                        "status": "accepted",
                        "structural_delta": {
                            "regressions": [],
                            "improvements": [],
                            "health_delta": 0,
                        },
                        "contract_violations": [],
                        "baseline_abuse": {"detected": False},
                    },
                )
            )
        finally:
            writer.close()

        store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        )

        result = get_relevant_memory(
            store,
            project_id=project.id,
            scope_paths=("pkg/helper.py",),
            scope_resolved_from="explicit",
            max_records=5,
        )

    trajectories = result["trajectories"]
    assert isinstance(trajectories, list)
    assert trajectories
    assert trajectories[0].get("patch_trail_summary") is not None
    summary = result.get("patch_trail_summary")
    assert isinstance(summary, dict)
    assert summary.get("counts", {}).get("untouched_in_declared") == 1


def test_query_engineering_memory_trajectory_modes(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, db_path):
        audit_db = tmp_path / "audit.sqlite3"
        seed_trajectory_audit_workflow(root=root, audit_db=audit_db)
        projection = store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        )
        trajectory_id = projection.trajectories[0].id

        status = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="trajectory_status",
        )
        search = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="trajectory_search",
            query="recover service",
        )
        detail = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="trajectory_get",
            record_id=trajectory_id,
        )

    assert status["status"] == "ok"
    assert search["status"] == "ok"
    search_payload = search["payload"]
    assert isinstance(search_payload, dict)
    assert search_payload["trajectory_count"] == 1
    detail_payload = detail["payload"]
    assert isinstance(detail_payload, dict)
    trajectory = detail_payload["trajectory"]
    assert isinstance(trajectory, dict)
    assert trajectory["trajectory_id"] == trajectory_id
    assert "event_core_json" not in str(trajectory)
    assert trajectory.get("patch_trail") is not None


def test_trajectory_search_requires_query(tmp_path: Path) -> None:
    with (
        memory_store(tmp_path) as (root, project, store, db_path),
        pytest.raises(MemoryContractError, match="requires query"),
    ):
        query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="trajectory_search",
        )


def test_memory_evidence_can_cite_trajectory_without_digest_change(
    tmp_path: Path,
) -> None:
    with memory_store(tmp_path) as (root, project, store, _db_path):
        audit_db = tmp_path / "audit.sqlite3"
        seed_trajectory_audit_workflow(root=root, audit_db=audit_db)
        projection = store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        )
        trajectory = projection.trajectories[0]
        record = seed_path_subject_record(
            store,
            project_id=project.id,
            path="pkg/service.py",
            statement="service memory record",
        )
        stored_before = store.find_trajectory(trajectory.id)
        assert stored_before is not None
        before_digest = stored_before.trajectory_digest
        store.write_evidence(
            MemoryEvidence(
                id=generate_memory_id(prefix="evid"),
                memory_id=record.id,
                evidence_kind="trajectory",
                ref=trajectory.id,
                locator=None,
                quote=None,
                digest=trajectory.trajectory_digest,
                created_at_utc=current_report_timestamp_utc(),
            )
        )
        store.commit()
        evidence = store.list_evidence_for_memory(record.id)
        stored_after = store.find_trajectory(trajectory.id)
        assert stored_after is not None
        after_digest = stored_after.trajectory_digest

    assert evidence[0].evidence_kind == "trajectory"
    assert evidence[0].ref == trajectory.id
    assert after_digest == before_digest


def test_trajectory_search_excludes_run_only_routine_by_default(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, db_path):
        audit_db = tmp_path / "audit.sqlite3"
        seed_routine_analysis_audit(root=root, audit_db=audit_db)
        store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        )
        default_search = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="trajectory_search",
            query="analysis completed",
        )
        include_routine = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="trajectory_search",
            query="analysis completed",
            filters={"include_routine": True},
        )

    default_payload = default_search["payload"]
    include_payload = include_routine["payload"]
    assert isinstance(default_payload, dict)
    assert isinstance(include_payload, dict)
    assert default_payload.get("trajectory_count") == 0
    assert (include_payload.get("trajectory_count") or 0) >= 1
