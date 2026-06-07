# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from codeclone.audit.reader import AuditRecord
from codeclone.memory.trajectory.projector import (
    TrajectoryProjectionError,
    project_trajectory,
)


def _core(event_type: str, *, status: str = "", **facts: object) -> tuple[str, str]:
    payload = {
        "core_schema_version": "1",
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
    workflow_id: str = "intent:intent-a-001",
    status: str | None = None,
    run_id: str | None = None,
    report_digest: str | None = None,
    severity: str = "info",
    summary: str | None = None,
    payload_json: str | None = None,
    **facts: object,
) -> AuditRecord:
    core_json, core_sha = _core(event_type, status=status or "", **facts)
    return AuditRecord(
        audit_sequence=sequence,
        event_id=f"evt-{sequence}",
        event_type=event_type,
        severity=severity,
        created_at_utc=f"2026-01-01T00:00:0{sequence}Z",
        run_id=run_id,
        intent_id="intent-a-001",
        report_digest=report_digest,
        workflow_id=workflow_id,
        surface="mcp",
        tool_name=None,
        event_core_json=core_json,
        event_core_sha256=core_sha,
        payload_sha256=None,
        payload_json=payload_json,
        status=status,
        agent_label="agent",
        summary=summary,
    )


def test_project_trajectory_uses_payload_paths_when_event_core_lacks_them() -> None:
    core_json, core_sha = _core("intent.declared", status="active")
    payload = json.dumps(
        {
            "intent_description": "legacy declare without core paths",
            "scope": {"allowed_files": ["pkg/legacy.py"]},
            "workspace_registered": True,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    record = replace(
        _record(
            1,
            "intent.declared",
            status="active",
            summary="legacy declare without core paths",
        ),
        event_core_json=core_json,
        event_core_sha256=core_sha,
        payload_json=payload,
    )
    trajectory = project_trajectory(
        project_id="proj-test",
        repo_root_digest="digest",
        workflow_id="intent:intent-a-001",
        records=(record,),
    )
    path_subjects = [
        subject.subject_key
        for subject in trajectory.subjects
        if subject.subject_kind == "path"
    ]
    assert "pkg/legacy.py" in path_subjects


def test_project_trajectory_is_deterministic_and_canonicalizes_report_digest() -> None:
    digest = "A" * 64
    events = (
        _record(
            2,
            "patch_contract.verified",
            status="accepted",
            run_id="abcdef12",
            report_digest=f"sha256:{digest}",
            summary="verified",
        ),
        _record(
            1,
            "intent.declared",
            status="active",
            run_id="abcdef12",
            report_digest=digest,
            summary="implement phase",
            scope_paths=["pkg/a.py", "tests/test_a.py"],
        ),
    )

    first = project_trajectory(
        project_id="proj-test",
        repo_root_digest="root-digest",
        workflow_id="intent:intent-a-001",
        records=events,
        projected_at_utc="2026-01-01T00:00:10Z",
    )
    second = project_trajectory(
        project_id="proj-test",
        repo_root_digest="root-digest",
        workflow_id="intent:intent-a-001",
        records=tuple(reversed(events)),
        projected_at_utc="2026-01-01T00:00:10Z",
    )

    assert first.id == second.id
    assert first.trajectory_digest == second.trajectory_digest
    assert first.source_event_stream_digest == second.source_event_stream_digest
    assert first.outcome == "accepted"
    assert first.quality_tier == "verified"
    assert "change_control_workflow" in first.labels
    assert "verified_finish" in first.labels
    assert first.report_digest == f"sha256:{digest.lower()}"
    assert [step.audit_sequence for step in first.steps] == [1, 2]
    assert ("path", "pkg/a.py") in {
        (subject.subject_kind, subject.subject_key) for subject in first.subjects
    }
    assert ("path", "tests/test_a.py") in {
        (subject.subject_kind, subject.subject_key) for subject in first.subjects
    }


def test_project_trajectory_adds_touched_path_subjects_from_check_core() -> None:
    trajectory = project_trajectory(
        project_id="proj-test",
        repo_root_digest="root-digest",
        workflow_id="intent:intent-a-001",
        records=(
            _record(
                1,
                "intent.declared",
                status="active",
                scope_paths=["pkg/a.py"],
            ),
            _record(
                2,
                "intent.checked",
                status="clean",
                changed_files=["pkg/b.py"],
                declared_scope_paths=["pkg/a.py", "pkg/b.py"],
                untouched_in_declared=["pkg/a.py"],
            ),
            _record(3, "patch_contract.verified", status="accepted"),
        ),
        projected_at_utc="2026-01-01T00:00:10Z",
    )
    subject_map = {
        (subject.subject_kind, subject.subject_key, subject.relation)
        for subject in trajectory.subjects
    }
    assert ("path", "pkg/b.py", "touched") in subject_map
    assert ("path", "pkg/a.py", "untouched") in subject_map


def test_project_trajectory_labels_routine_change_control_cycle() -> None:
    trajectory = project_trajectory(
        project_id="proj-test",
        repo_root_digest="root-digest",
        workflow_id="intent:intent-a-001",
        records=(
            _record(1, "intent.declared", status="active"),
            _record(
                2,
                "intent.checked",
                status="clean",
                changed_files=["pkg/a.py"],
            ),
            _record(3, "patch_trail.computed", status="computed"),
            _record(4, "patch_contract.verified", status="accepted"),
            _record(5, "review_receipt.created", status="created"),
            _record(6, "claim_validation.completed", status="accepted"),
        ),
        projected_at_utc="2026-01-01T00:00:10Z",
    )
    assert trajectory.labels
    assert "change_control_workflow" in trajectory.labels
    assert "verified_finish" in trajectory.labels
    assert "scope_clean" in trajectory.labels
    assert "patch_trail_recorded" in trajectory.labels
    assert "receipt_issued" in trajectory.labels
    assert "claim_validated" in trajectory.labels


def test_project_trajectory_marks_incident_labels() -> None:
    trajectory = project_trajectory(
        project_id="proj-test",
        repo_root_digest="root-digest",
        workflow_id="intent:intent-a-001",
        records=(
            _record(1, "intent.declared", status="active"),
            _record(
                2,
                "baseline_abuse.detected",
                status="violated",
                severity="error",
                baseline_abuse=True,
            ),
        ),
        projected_at_utc="2026-01-01T00:00:10Z",
    )

    assert trajectory.outcome == "violated"
    assert trajectory.quality_tier == "incident"
    assert "baseline_abuse_detected" in trajectory.labels


def test_project_trajectory_rejects_event_core_digest_mismatch() -> None:
    record = _record(1, "intent.declared", status="active")
    broken = replace(record, event_core_sha256="0" * 64)

    with pytest.raises(TrajectoryProjectionError, match="digest mismatch"):
        project_trajectory(
            project_id="proj-test",
            repo_root_digest="root-digest",
            workflow_id="intent:intent-a-001",
            records=(broken,),
        )
