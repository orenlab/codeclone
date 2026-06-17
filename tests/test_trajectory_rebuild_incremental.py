# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import codeclone.memory.jobs.staleness as staleness_mod
from codeclone.audit.events import AuditEvent, repo_root_digest
from codeclone.audit.reader import list_workflow_ids_with_events_after
from codeclone.audit.writer import SqliteAuditWriter
from codeclone.memory.jobs.worker import _trajectory_incremental_watermark
from codeclone.memory.trajectory.models import TRAJECTORY_PROJECTION_VERSION

from .memory_fixtures import memory_store


def _emit_workflow(root: Path, audit_db: Path, *, intent_id: str) -> None:
    """Emit a minimal two-event accepted workflow for ``intent_id``."""
    root_digest = repo_root_digest(root.resolve())
    writer = SqliteAuditWriter(db_path=audit_db, payloads="compact", retention_days=30)
    try:
        writer.emit(
            AuditEvent(
                event_type="intent.declared",
                severity="info",
                repo_root_digest=root_digest,
                agent_pid=100,
                agent_label="tester",
                intent_id=intent_id,
                run_id="aaaa1111",
                report_digest="1" * 64,
                status="active",
                payload={
                    "intent_description": f"work on {intent_id}",
                    "scope": {"allowed_files": ["pkg/a.py"]},
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
                run_id="bbbb2222",
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


def _max_event_id(audit_db: Path) -> int:
    conn = sqlite3.connect(str(audit_db))
    try:
        row = conn.execute("SELECT MAX(id) FROM controller_events").fetchone()
    finally:
        conn.close()
    return int(row[0]) if row and row[0] is not None else 0


def test_list_workflow_ids_with_events_after(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, _project, _store, _db):
        audit_db = tmp_path / "audit.sqlite3"
        _emit_workflow(root, audit_db, intent_id="intent-a")
        after_a = _max_event_id(audit_db)
        _emit_workflow(root, audit_db, intent_id="intent-b")
        digest = repo_root_digest(root.resolve())

        assert list_workflow_ids_with_events_after(
            db_path=audit_db, repo_root_digest=digest, after_id=after_a
        ) == ("intent:intent-b",)
        assert set(
            list_workflow_ids_with_events_after(
                db_path=audit_db, repo_root_digest=digest, after_id=0
            )
        ) == {"intent:intent-a", "intent:intent-b"}


def test_list_workflow_ids_after_missing_audit_db_is_empty(tmp_path: Path) -> None:
    assert (
        list_workflow_ids_with_events_after(
            db_path=tmp_path / "absent.sqlite3",
            repo_root_digest="digest",
            after_id=0,
        )
        == ()
    )


def test_incremental_reprojects_only_changed_workflows(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, _db):
        audit_db = tmp_path / "audit.sqlite3"
        _emit_workflow(root, audit_db, intent_id="intent-a")
        _emit_workflow(root, audit_db, intent_id="intent-b")
        full = store.rebuild_trajectories_from_audit(
            project=project, root_path=root, audit_db_path=audit_db
        )
        assert full.run.trajectories_created == 2

        watermark = _max_event_id(audit_db)
        _emit_workflow(root, audit_db, intent_id="intent-c")

        incremental = store.rebuild_trajectories_incremental(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
            after_event_core_id=watermark,
        )
        # Only the workflow with events after the watermark is re-projected.
        assert incremental.run.workflows_seen == 1
        assert incremental.run.trajectories_created == 1
        assert store.count_trajectories(project_id=project.id) == 3


def test_incremental_after_current_max_is_noop(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, _db):
        audit_db = tmp_path / "audit.sqlite3"
        _emit_workflow(root, audit_db, intent_id="intent-a")
        store.rebuild_trajectories_from_audit(
            project=project, root_path=root, audit_db_path=audit_db
        )
        watermark = _max_event_id(audit_db)

        incremental = store.rebuild_trajectories_incremental(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
            after_event_core_id=watermark,
        )
        assert incremental.run.workflows_seen == 0
        assert incremental.run.trajectories_created == 0
        assert incremental.run.trajectories_updated == 0


def test_worker_watermark_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = sqlite3.connect(":memory:")
    try:
        # No prior done job -> full rebuild.
        monkeypatch.setattr(
            staleness_mod, "last_applied_stimulus", lambda c, *, project_id: None
        )
        assert _trajectory_incremental_watermark(conn, project_id="p") is None

        # Projection-version change -> full rebuild (re-derive everything).
        monkeypatch.setattr(
            staleness_mod,
            "last_applied_stimulus",
            lambda c, *, project_id: {
                "trajectory_projection_version": "trajectory-v0",
                "event_core_max_id": 42,
            },
        )
        assert _trajectory_incremental_watermark(conn, project_id="p") is None

        # Same version + watermark -> incremental after the watermark.
        monkeypatch.setattr(
            staleness_mod,
            "last_applied_stimulus",
            lambda c, *, project_id: {
                "trajectory_projection_version": TRAJECTORY_PROJECTION_VERSION,
                "event_core_max_id": 42,
            },
        )
        assert _trajectory_incremental_watermark(conn, project_id="p") == 42

        # Missing watermark -> full rebuild.
        monkeypatch.setattr(
            staleness_mod,
            "last_applied_stimulus",
            lambda c, *, project_id: {
                "trajectory_projection_version": TRAJECTORY_PROJECTION_VERSION
            },
        )
        assert _trajectory_incremental_watermark(conn, project_id="p") is None
    finally:
        conn.close()


def test_execute_rebuild_reports_full_and_incremental_modes(tmp_path: Path) -> None:
    from codeclone.config.memory import resolve_memory_config
    from codeclone.memory.trajectory.rebuild_workflow import execute_trajectory_rebuild

    from .memory_fixtures import seed_trajectory_audit_workflow

    with memory_store(tmp_path) as (root, project, store, _db_path):
        audit_db = root / ".codeclone" / "db" / "audit.sqlite3"
        seed_trajectory_audit_workflow(root=root, audit_db=audit_db)
        config = resolve_memory_config(root)
        full = execute_trajectory_rebuild(
            root_path=root,
            config=config,
            store=store,
            project=project,
        )
        assert full["status"] == "ok"
        assert full["mode"] == "full"
        incremental = execute_trajectory_rebuild(
            root_path=root,
            config=config,
            store=store,
            project=project,
            incremental_after_event_core_id=1,
        )
        assert incremental["status"] == "ok"
        assert incremental["mode"] == "incremental"
