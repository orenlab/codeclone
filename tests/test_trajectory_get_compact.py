# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path
from typing import cast

from codeclone.audit.events import (
    EVENT_INTENT_CHECKED,
    EVENT_INTENT_DECLARED,
    EVENT_PATCH_TRAIL_COMPUTED,
    EVENT_PATCH_VERIFIED,
    AuditEvent,
    repo_root_digest,
)
from codeclone.audit.reader import lookup_patch_trail
from codeclone.audit.writer import SqliteAuditWriter
from codeclone.memory.retrieval import query_engineering_memory
from codeclone.memory.trajectory.patch_trail import compute_patch_trail
from codeclone.memory.trajectory.store import load_trajectory_patch_trail

from .memory_fixtures import memory_store, seed_trajectory_audit_workflow
from .test_memory_trajectory_coverage import _patch_trail_inputs


def _emit_patch_trail_workflow(audit_db: Path, *, root: Path) -> str:
    root_digest = repo_root_digest(root.resolve())
    trail = compute_patch_trail(_patch_trail_inputs())
    audit_payload = trail.audit_payload()
    run_id = "finish1234"
    writer = SqliteAuditWriter(
        db_path=audit_db,
        payloads="compact",
        retention_days=30,
    )
    try:
        writer.emit(
            AuditEvent(
                event_type=EVENT_INTENT_DECLARED,
                severity="info",
                repo_root_digest=root_digest,
                agent_pid=100,
                agent_label="tester",
                intent_id="intent-sync-001",
                run_id="before12",
                report_digest="1" * 64,
                status="active",
                payload={
                    "intent_description": "sync patch trail digest",
                    "scope": {"allowed_files": ["pkg/a.py"]},
                },
            )
        )
        writer.emit(
            AuditEvent(
                event_type=EVENT_INTENT_CHECKED,
                severity="info",
                repo_root_digest=root_digest,
                agent_pid=100,
                agent_label="tester",
                intent_id="intent-sync-001",
                run_id="before12",
                report_digest="1" * 64,
                status="clean",
                payload={
                    "status": "clean",
                    "declared_scope": ["pkg/a.py"],
                    "actual_changed_files": ["pkg/a.py"],
                    "unexpected_files": [],
                    "forbidden_touched": [],
                },
            )
        )
        writer.emit(
            AuditEvent(
                event_type=EVENT_PATCH_VERIFIED,
                severity="info",
                repo_root_digest=root_digest,
                agent_pid=100,
                agent_label="tester",
                intent_id="intent-sync-001",
                run_id=run_id,
                report_digest="2" * 64,
                status="accepted",
                payload={"status": "accepted"},
            )
        )
        writer.emit(
            AuditEvent(
                event_type=EVENT_PATCH_TRAIL_COMPUTED,
                severity="info",
                repo_root_digest=root_digest,
                agent_pid=100,
                agent_label="tester",
                intent_id="intent-sync-001",
                run_id=run_id,
                report_digest="2" * 64,
                status=trail.scope_check_status,
                payload=audit_payload,
            )
        )
    finally:
        writer.close()
    return trail.patch_trail_digest


def test_trajectory_projection_digest_matches_durable_lookup(tmp_path: Path) -> None:
    audit_db = tmp_path / "audit.sqlite3"
    with memory_store(tmp_path) as (root, project, store, _db_path):
        digest = _emit_patch_trail_workflow(audit_db, root=root)
        projection = store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        )
        trajectory = projection.trajectories[0]
        loaded = load_trajectory_patch_trail(
            store._conn,
            trajectory_id=trajectory.id,
        )
        assert loaded is not None
        assert loaded["patch_trail_digest"] == digest

        lookup = lookup_patch_trail(
            audit_db,
            run_id="finish1234",
            patch_trail_digest=digest,
        )
        assert lookup.status == "ok"
        assert lookup.patch_trail is not None
        assert lookup.patch_trail.patch_trail_digest == digest


def test_trajectory_get_compact_omits_full_steps(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, db_path):
        audit_db = tmp_path / "audit.sqlite3"
        seed_trajectory_audit_workflow(root=root, audit_db=audit_db)
        projection = store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        )
        trajectory_id = projection.trajectories[0].id

        compact = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="trajectory_get",
            record_id=trajectory_id,
            detail_level="compact",
        )
        full = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="trajectory_get",
            record_id=trajectory_id,
            detail_level="full",
        )

    assert compact["detail_level"] == "compact"
    compact_trajectory = cast(
        "dict[str, object]",
        cast("dict[str, object]", compact["payload"])["trajectory"],
    )
    full_trajectory = cast(
        "dict[str, object]",
        cast("dict[str, object]", full["payload"])["trajectory"],
    )
    assert "steps" not in compact_trajectory
    assert "evidence" not in compact_trajectory
    assert compact_trajectory.get("subjects_truncated") is not None
    assert full_trajectory.get("steps") is not None
    assert full_trajectory.get("evidence") is not None
