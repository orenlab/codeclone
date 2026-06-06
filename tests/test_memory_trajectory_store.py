# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

from codeclone.audit.events import AuditEvent, repo_root_digest
from codeclone.audit.writer import SqliteAuditWriter

from .memory_fixtures import memory_store


def _write_workflow_events(root: Path, audit_db: Path) -> None:
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
                intent_id="intent-test-001",
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
                intent_id="intent-test-001",
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
