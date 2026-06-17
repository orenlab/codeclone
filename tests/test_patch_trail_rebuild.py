# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from codeclone.audit.events import (
    EVENT_INTENT_CHECKED,
    EVENT_INTENT_DECLARED,
    EVENT_PATCH_TRAIL_COMPUTED,
    EVENT_PATCH_VERIFIED,
    AuditEvent,
    repo_root_digest,
)
from codeclone.audit.reader import AuditRecord
from codeclone.audit.writer import SqliteAuditWriter
from codeclone.memory.trajectory.patch_trail_projector import (
    project_patch_trail_from_audit,
)
from codeclone.memory.trajectory.store import load_trajectory_patch_trail

from .memory_fixtures import memory_store


def _core(event_type: str, *, status: str = "", **facts: object) -> tuple[str, str]:
    payload = {
        "core_schema_version": "2",
        "event_family": event_type.partition(".")[0],
        "event_type": event_type,
        "facts": facts,
        "status": status,
        "truncated": False,
    }
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()


def _record(
    sequence: int,
    event_type: str,
    *,
    status: str | None = None,
    summary: str | None = None,
    **facts: object,
) -> AuditRecord:
    core_json, core_sha = _core(event_type, status=status or "", **facts)
    return AuditRecord(
        audit_sequence=sequence,
        event_id=f"evt-{sequence}",
        event_type=event_type,
        severity="info",
        created_at_utc=f"2026-01-01T00:00:0{sequence}Z",
        run_id="run-test",
        intent_id="intent-test-001",
        report_digest="a" * 64,
        workflow_id="intent:intent-test-001",
        surface="mcp",
        tool_name=None,
        event_core_json=core_json,
        event_core_sha256=core_sha,
        payload_sha256=None,
        status=status,
        agent_label="agent",
        summary=summary,
    )


def test_project_patch_trail_from_audit_uses_check_core_paths() -> None:
    root_digest = "root-digest"
    records = (
        _record(
            1,
            EVENT_INTENT_DECLARED,
            status="active",
            summary="implement patch trail rebuild",
            scope_paths=["pkg/a.py", "pkg/b.py"],
        ),
        _record(
            2,
            EVENT_INTENT_CHECKED,
            status="clean",
            declared_scope_paths=["pkg/a.py", "pkg/b.py"],
            changed_files=["pkg/a.py"],
            unexpected_files_list=[],
            forbidden_touched_list=[],
        ),
        _record(
            3,
            EVENT_PATCH_VERIFIED,
            status="accepted",
        ),
        _record(
            4,
            EVENT_PATCH_TRAIL_COMPUTED,
            status="clean",
            patch_trail_digest="ignored",
            untouched_in_declared=1,
        ),
    )

    trail = project_patch_trail_from_audit(
        records=records,
        repo_root_digest=root_digest,
    )

    assert trail is not None
    assert trail.declared_files == ("pkg/a.py", "pkg/b.py")
    assert trail.changed_files == ("pkg/a.py",)
    assert trail.untouched_in_declared == ("pkg/b.py",)
    assert trail.verification_status == "accepted"
    assert trail.evidence["scope_check_audit_sequence"] == 2
    assert trail.evidence["patch_trail_audit_sequence"] == 4


def test_rebuild_trajectories_persist_patch_trail(tmp_path: Path) -> None:
    audit_db = tmp_path / "audit.sqlite3"
    with memory_store(tmp_path) as (root, project, store, _db_path):
        root_digest = repo_root_digest(root.resolve())
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
                    intent_id="intent-test-001",
                    run_id="abc12345",
                    report_digest="1" * 64,
                    status="active",
                    payload={
                        "intent_description": "implement patch trail storage",
                        "scope": {
                            "allowed_files": ["pkg/a.py", "pkg/b.py"],
                        },
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
                    agent_pid=100,
                    agent_label="tester",
                    intent_id="intent-test-001",
                    run_id="abc12345",
                    report_digest="1" * 64,
                    status="clean",
                    payload={
                        "status": "clean",
                        "declared_scope": ["pkg/a.py", "pkg/b.py"],
                        "actual_changed_files": ["pkg/a.py"],
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
        assert loaded["untouched_in_declared"] == ["pkg/b.py"]
        assert loaded["changed_files"] == ["pkg/a.py"]
        assert trajectory.trajectory_digest
        assert loaded["patch_trail_digest"]
