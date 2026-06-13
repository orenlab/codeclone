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

from .memory_fixtures import memory_store


def _write_workflow_events(
    root: Path, audit_db: Path, *, intent_id: str = "intent-test-001"
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
                agent_pid=100,
                agent_label="tester",
                intent_id=intent_id,
                run_id="abc12345",
                report_digest="1" * 64,
                status="active",
                payload={
                    "intent_description": "implement trajectory storage",
                    "scope": {
                        "allowed_files": ["codeclone/memory/trajectory/store.py"]
                    },
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
                agent_pid=100,
                agent_label="tester",
                intent_id=intent_id,
                run_id="def67890",
                report_digest="2" * 64,
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


def test_rebuild_trajectories_from_audit_is_idempotent(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, _db_path):
        audit_db = tmp_path / "audit.sqlite3"
        _write_workflow_events(root, audit_db)

        first = store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        )
        second = store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        )

        assert first.run.trajectories_created == 1
        assert second.run.trajectories_unchanged == 1
        assert store.count_trajectories(project_id=project.id) == 1
        items = store.list_trajectories(project_id=project.id)
        assert items[0].outcome == "accepted"

        trajectory = store.find_trajectory(items[0].id)
        assert trajectory is not None
        assert trajectory.workflow_id == "intent:intent-test-001"
        assert trajectory.report_digest == f"sha256:{'2' * 64}"
        assert [step.event_type for step in trajectory.steps] == [
            "intent.declared",
            "patch_contract.verified",
        ]
        assert store.latest_trajectory_projection_run(project_id=project.id) is not None


def test_find_trajectories_by_ids_batch_matches_single_path(tmp_path: Path) -> None:
    from codeclone.memory.trajectory import store as trajectory_store

    with memory_store(tmp_path) as (root, project, store, _db_path):
        audit_db = tmp_path / "audit.sqlite3"
        for intent_id in ("intent-test-001", "intent-test-002", "intent-test-003"):
            _write_workflow_events(root, audit_db, intent_id=intent_id)
        store.rebuild_trajectories_from_audit(
            project=project, root_path=root, audit_db_path=audit_db
        )

        conn = store._conn
        ids = [item.id for item in store.list_trajectories(project_id=project.id)]
        assert len(ids) == 3

        # Batch hydration is identical to the per-id single path, in input order.
        single = [trajectory_store.find_trajectory(conn, tid) for tid in ids]
        assert trajectory_store._find_trajectories_by_ids(conn, ids) == single

        # Order is preserved, missing ids are skipped, empty input yields [].
        reversed_ids = list(reversed(ids))
        assert trajectory_store._find_trajectories_by_ids(conn, reversed_ids) == [
            trajectory_store.find_trajectory(conn, tid) for tid in reversed_ids
        ]
        assert (
            trajectory_store._find_trajectories_by_ids(conn, ["missing", *ids])
            == single
        )
        assert trajectory_store._find_trajectories_by_ids(conn, []) == []


def test_rebuild_supersedes_duplicate_workflow_projection_rows(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, _db_path):
        audit_db = tmp_path / "audit.sqlite3"
        _write_workflow_events(root, audit_db)
        store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        )
        assert store.count_trajectories(project_id=project.id) == 1
        canonical = store.list_canonical_trajectories_for_export(project_id=project.id)
        assert len(canonical) == 1


def test_store_empty_inputs_invalid_patch_trails_and_stale_projection_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    from codeclone.memory.trajectory import store as trajectory_store
    from tests.memory_fixtures import seed_trajectory_audit_workflow

    with memory_store(tmp_path) as (root, project, store, _db_path):
        conn = store._conn
        assert (
            trajectory_store.list_trajectories_for_subjects(
                conn,
                project_id=project.id,
                subjects={},
            )
            == []
        )
        assert (
            trajectory_store.search_trajectories(
                conn,
                project_id=project.id,
                query="",
            )
            == []
        )
        assert (
            trajectory_store.load_trajectory_patch_trail(
                conn,
                trajectory_id="missing",
            )
            is None
        )

        audit_db = tmp_path / "audit.sqlite3"
        seed_trajectory_audit_workflow(root=root, audit_db=audit_db)
        base = store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        ).trajectories[0]
        old = replace(
            base,
            id="traj-old",
            workflow_id="intent:shared",
        )
        current = replace(
            old,
            id="traj-current",
            projection_version="3",
            trajectory_digest="e" * 64,
        )
        assert trajectory_store.upsert_trajectory(conn, old) == "created"
        assert trajectory_store.upsert_trajectory(conn, current) == "created"
        assert (
            trajectory_store.supersede_stale_projection_trajectories(
                conn,
                project_id=project.id,
                workflow_id=current.workflow_id,
                keep_trajectory_id=current.id,
                keep_trajectory_digest=current.trajectory_digest,
            )
            == 1
        )
        assert trajectory_store.find_trajectory(conn, old.id) is None

        trajectory_store.upsert_trajectory_patch_trail(
            conn,
            trajectory_id=current.id,
            patch_trail_json="[]",
            patch_trail_digest="f" * 64,
            schema_version="1",
            projected_at_utc=current.projected_at_utc,
        )
        assert (
            trajectory_store.load_trajectory_patch_trail(
                conn,
                trajectory_id=current.id,
            )
            is None
        )
        assert (
            trajectory_store.load_trajectory_patch_trails(
                conn,
                trajectory_ids=(current.id,),
            )
            == {}
        )

        monkeypatch.setattr(
            trajectory_store,
            "list_workflow_ids_with_events_after",
            lambda **_kwargs: ["intent:empty"],
        )
        monkeypatch.setattr(
            trajectory_store,
            "read_audit_event_core_records",
            lambda **_kwargs: [],
        )
        monkeypatch.setattr(
            trajectory_store,
            "count_audit_event_core_gaps",
            lambda **_kwargs: 0,
        )
        result = trajectory_store.rebuild_trajectories_incremental(
            conn=conn,
            project=project,
            root_path=root,
            audit_db_path=tmp_path / "audit-empty.sqlite3",
            after_event_core_id=10,
        )
        assert result.run.workflows_seen == 1
        assert result.trajectories == ()
