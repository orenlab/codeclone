# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.audit.events import AuditEvent, repo_root_digest
from codeclone.audit.writer import SqliteAuditWriter
from codeclone.memory.exceptions import MemoryContractError
from codeclone.memory.models import MemoryEvidence, generate_memory_id
from codeclone.memory.retrieval import get_relevant_memory, query_engineering_memory
from codeclone.report.meta import current_report_timestamp_utc

from .memory_fixtures import memory_store, seed_path_subject_record


def _seed_trajectory(
    *,
    root: Path,
    audit_db: Path,
    intent_id: str = "intent-traj-001",
    scope_path: str = "pkg/service.py",
    description: str = "recover stale intent before editing service",
) -> None:
    root_digest = repo_root_digest(root.resolve())
    writer = SqliteAuditWriter(
        db_path=audit_db,
        payloads="compact",
        retention_days=30,
    )
    try:
        writer.emit(
            AuditEvent(
                event_type="intent.declared",
                severity="info",
                repo_root_digest=root_digest,
                agent_pid=123,
                agent_label="test-agent",
                intent_id=intent_id,
                run_id="run-before",
                report_digest="a" * 64,
                status="active",
                payload={
                    "intent_description": description,
                    "scope": {"allowed_files": [scope_path]},
                    "workspace_registered": True,
                    "ttl_seconds": 3600,
                    "lease_seconds": 600,
                },
            )
        )
        writer.emit(
            AuditEvent(
                event_type="patch_contract.verified",
                severity="info",
                repo_root_digest=root_digest,
                agent_pid=123,
                agent_label="test-agent",
                intent_id=intent_id,
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


def test_get_relevant_memory_returns_scoped_trajectories(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, _db_path):
        audit_db = tmp_path / "audit.sqlite3"
        _seed_trajectory(root=root, audit_db=audit_db)
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


def test_query_engineering_memory_trajectory_modes(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, db_path):
        audit_db = tmp_path / "audit.sqlite3"
        _seed_trajectory(root=root, audit_db=audit_db)
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
        _seed_trajectory(root=root, audit_db=audit_db)
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
