# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

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


def test_projector_helpers_reject_incomplete_steps_and_cover_fallbacks() -> None:
    from codeclone.memory.trajectory import projector

    record = _record(1, "analysis.completed")
    with pytest.raises(TrajectoryProjectionError, match="missing audit_sequence"):
        projector._step_from_record(0, replace(record, audit_sequence=None))
    with pytest.raises(TrajectoryProjectionError, match="missing event core"):
        projector._step_from_record(
            0,
            replace(record, event_core_json=None, event_core_sha256=None),
        )

    corrected = projector._quality_tier(
        outcome="accepted",
        records=(_record(1, "patch_contract.violated"),),
        labels=(),
    )
    assert corrected == "corrected"
    assert projector._primary_agent_label((record,)) == "agent"
    assert projector._primary_agent_label((replace(record, agent_label=""),)) is None

    subjects = projector._subjects(
        workflow_id="run:one",
        intent_id=None,
        run_ids=(),
        report_digests=(),
        cores=(),
        agent_label=None,
    )
    assert {(item.subject_kind, item.subject_key) for item in subjects} == {
        ("workflow", "run:one")
    }


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


def test_patch_trail_projector_helper_and_status_fallback_edges() -> None:
    from codeclone.memory.trajectory import patch_trail_projector

    record = _record(1, "intent.checked", status="clean")
    with pytest.raises(TrajectoryProjectionError, match="missing audit_sequence"):
        patch_trail_projector._record_order_key(replace(record, audit_sequence=None))
    assert (
        patch_trail_projector._event_core(
            replace(record, event_core_json=None, event_core_sha256=None)
        )
        == {}
    )
    assert patch_trail_projector._facts_paths({}, "changed_files") == ()
    assert (
        patch_trail_projector._facts_paths(
            {"facts": {"changed_files": "pkg/a.py"}},
            "changed_files",
        )
        == ()
    )

    state = patch_trail_projector._WorkflowAuditState(scope_check_status="")
    patch_trail_projector._apply_audit_record(
        state,
        replace(record, status=None),
    )
    assert state.scope_check_status == "clean"
    patch_trail_projector._apply_audit_record(
        state,
        _record(2, "receipt.created"),
    )
    assert state.receipt_seq == 2


def test_project_trajectory_edge_outcomes_and_labels() -> None:
    from codeclone.memory.trajectory.projector import (
        TrajectoryProjectionError,
        project_trajectory,
    )

    with pytest.raises(TrajectoryProjectionError, match="requires events"):
        project_trajectory(
            project_id="proj",
            repo_root_digest="digest",
            workflow_id="intent:intent-a-001",
            records=(),
        )

    blocked = project_trajectory(
        project_id="proj",
        repo_root_digest="digest",
        workflow_id="intent:intent-a-001",
        records=(
            _record(1, "intent.declared", status="active"),
            _record(2, "intent.queue_blocked", status="blocked"),
        ),
    )
    assert blocked.outcome == "blocked"

    conflict = project_trajectory(
        project_id="proj",
        repo_root_digest="digest",
        workflow_id="intent:intent-a-001",
        records=(
            _record(1, "intent.declared", status="active"),
            _record(2, "workspace.conflict_detected", status="blocked"),
        ),
    )
    assert conflict.outcome == "blocked"
    assert "foreign_conflict_seen" in conflict.labels

    external = project_trajectory(
        project_id="proj",
        repo_root_digest="digest",
        workflow_id="intent:intent-a-001",
        records=(
            _record(1, "intent.declared", status="active"),
            _record(
                2,
                "patch_contract.verified",
                status="accepted_with_external_changes",
            ),
        ),
    )
    assert external.outcome == "accepted_with_external_changes"
    assert "external_changes_accepted" in external.labels

    expanded = project_trajectory(
        project_id="proj",
        repo_root_digest="digest",
        workflow_id="intent:intent-a-001",
        records=(
            _record(1, "intent.declared", status="active"),
            _record(2, "intent.expanded", status="expanded"),
            _record(3, "patch_contract.verified", status="accepted"),
        ),
    )
    assert "scope_expanded" in expanded.labels

    queued = project_trajectory(
        project_id="proj",
        repo_root_digest="digest",
        workflow_id="intent:intent-a-001",
        records=(
            _record(1, "intent.declared", status="active"),
            _record(2, "intent.queued", status="queued"),
            _record(3, "intent.promoted", status="active"),
            _record(4, "patch_contract.verified", status="accepted"),
        ),
    )
    assert "queue_used" in queued.labels
    assert "recovered" in queued.labels

    claim_failed = project_trajectory(
        project_id="proj",
        repo_root_digest="digest",
        workflow_id="intent:intent-a-001",
        records=(
            _record(1, "intent.declared", status="active"),
            _record(2, "claim_validation.violated", status="violated"),
        ),
    )
    assert "claim_guard_failed" in claim_failed.labels

    broken = _record(1, "intent.declared", status="active")
    missing_seq = replace(broken, audit_sequence=None)
    with pytest.raises(TrajectoryProjectionError, match="audit_sequence"):
        project_trajectory(
            project_id="proj",
            repo_root_digest="digest",
            workflow_id="intent:intent-a-001",
            records=(missing_seq,),
        )

    wrong_workflow = replace(broken, workflow_id="intent:other")
    with pytest.raises(TrajectoryProjectionError, match="mixed workflow"):
        project_trajectory(
            project_id="proj",
            repo_root_digest="digest",
            workflow_id="intent:intent-a-001",
            records=(wrong_workflow,),
        )


def test_trajectory_anomalies_projector_and_export_helpers() -> None:
    from codeclone.memory.trajectory.anomalies import (
        anomaly_summary,
        detect_trajectory_anomalies,
        serialize_anomaly,
    )
    from codeclone.memory.trajectory.export_context import extract_trajectory_citations
    from codeclone.memory.trajectory.patch_trail import compute_patch_trail
    from codeclone.memory.trajectory.projector import (
        TrajectoryProjectionError,
        project_trajectory,
    )
    from codeclone.memory.trajectory.retrieval import (
        serialize_patch_trail_summary,
        serialize_trajectory_preview,
    )

    from .test_memory_trajectory_coverage import _patch_trail_inputs

    blocked = project_trajectory(
        project_id="proj",
        repo_root_digest="digest",
        workflow_id="intent:intent-a-001",
        records=(
            _record(1, "intent.declared", status="active"),
            _record(2, "intent.queue_blocked", status="blocked"),
        ),
    )
    blocked_anomalies = detect_trajectory_anomalies(blocked)
    assert any(item.kind == "outcome_blocked" for item in blocked_anomalies)

    abandoned = project_trajectory(
        project_id="proj",
        repo_root_digest="digest",
        workflow_id="intent:intent-a-001",
        records=(
            _record(1, "intent.declared", status="active"),
            _record(2, "intent.expired", status="expired"),
        ),
    )
    assert any(
        item.kind == "outcome_abandoned"
        for item in detect_trajectory_anomalies(abandoned)
    )

    hook = project_trajectory(
        project_id="proj",
        repo_root_digest="digest",
        workflow_id="intent:intent-a-001",
        records=(
            replace(
                _record(1, "intent.declared", status="active"),
                surface="hook",
                severity="warn",
            ),
            _record(2, "patch_contract.verified", status="accepted"),
        ),
    )
    assert "hook_blocked" in hook.labels

    memory_tool = project_trajectory(
        project_id="proj",
        repo_root_digest="digest",
        workflow_id="intent:intent-a-001",
        records=(
            replace(
                _record(1, "intent.declared", status="active"),
                tool_name="manage_engineering_memory",
            ),
            _record(2, "patch_contract.verified", status="accepted"),
        ),
    )
    assert "memory_used" in memory_tool.labels

    missing_core = replace(
        _record(1, "intent.declared"), event_core_json="", event_core_sha256=""
    )
    with pytest.raises(TrajectoryProjectionError, match="missing event core"):
        project_trajectory(
            project_id="proj",
            repo_root_digest="digest",
            workflow_id="intent:intent-a-001",
            records=(missing_core,),
        )

    with_citations = project_trajectory(
        project_id="proj",
        repo_root_digest="digest",
        workflow_id="intent:intent-a-001",
        records=(
            _record(1, "intent.declared", status="active"),
            _record(
                2,
                "claim_validation.completed",
                status="accepted",
                citations=[
                    {"kind": "finding", "cited_id": "finding-1", "valid": True},
                    {"kind": "", "cited_id": "", "valid": False},
                ],
            ),
            _record(3, "patch_contract.verified", status="accepted"),
        ),
    )
    extracted = extract_trajectory_citations(with_citations)
    assert extracted
    assert extracted[0]["kind"] == "finding"

    trail = compute_patch_trail(_patch_trail_inputs())
    violated_trail = replace(
        trail,
        scope_check_status="violated",
        verification_status="not_reached",
    )
    partial = project_trajectory(
        project_id="proj",
        repo_root_digest="digest",
        workflow_id="intent:intent-a-001",
        records=(
            _record(1, "intent.declared", status="active"),
            _record(2, "intent.queue_blocked", status="blocked"),
        ),
    )
    trail_anomalies = detect_trajectory_anomalies(
        partial,
        patch_trail_payload=violated_trail.to_payload(detail_level="summary"),
    )
    assert any(item.kind == "scope_violation" for item in trail_anomalies)
    summary = anomaly_summary([(partial, trail_anomalies)])
    error_count = summary["error_count"]
    assert isinstance(error_count, int)
    assert error_count >= 1
    assert serialize_anomaly(trail_anomalies[0])["kind"]

    preview = serialize_trajectory_preview(
        replace(with_citations, summary="x" * 500),
        detail_level="compact",
    )
    assert len(str(preview["summary"])) < 500
    patch_summary = serialize_patch_trail_summary(
        violated_trail.to_payload(detail_level="full")
    )
    assert patch_summary is not None
    assert patch_summary["scope_check_status"] == "violated"


def test_trajectory_projector_and_retrieval_residual_edges(tmp_path: Path) -> None:
    import hashlib

    from codeclone.audit.events import EVENT_INTENT_DECLARED
    from codeclone.memory.trajectory.projector import (
        TrajectoryProjectionError,
        project_trajectory,
    )
    from codeclone.memory.trajectory.retrieval import (
        rank_trajectories_for_query,
        serialize_patch_trail_summary,
    )

    list_core = '["not","object"]'
    list_sha = hashlib.sha256(list_core.encode("utf-8")).hexdigest()
    bad_core = replace(
        _record(1, EVENT_INTENT_DECLARED, status="active"),
        event_core_json=list_core,
        event_core_sha256=list_sha,
    )
    with pytest.raises(TrajectoryProjectionError, match="JSON object"):
        project_trajectory(
            project_id="proj",
            repo_root_digest="digest",
            workflow_id="intent:intent-a-001",
            records=[bad_core],
        )

    missing_sequence = replace(
        _record(1, EVENT_INTENT_DECLARED, status="active"),
        audit_sequence=None,
    )
    with pytest.raises(TrajectoryProjectionError, match="audit_sequence"):
        project_trajectory(
            project_id="proj",
            repo_root_digest="digest",
            workflow_id="intent:intent-a-001",
            records=[missing_sequence],
        )

    assert serialize_patch_trail_summary(None) is None
    assert serialize_patch_trail_summary({"not": "trail"}) is None

    empty_hits, truncated = rank_trajectories_for_query(
        [],
        query="",
        max_results=5,
        match_mode="any",
    )
    assert empty_hits == []
    assert truncated is False

    missing_core = replace(
        _record(1, EVENT_INTENT_DECLARED, status="active"),
        event_core_json=None,
        event_core_sha256=None,
    )
    with pytest.raises(TrajectoryProjectionError, match="missing event core"):
        project_trajectory(
            project_id="proj",
            repo_root_digest="digest",
            workflow_id="intent:intent-a-001",
            records=[missing_core],
        )

    from codeclone.audit.events import EVENT_PATCH_VERIFIED

    abused = project_trajectory(
        project_id="proj",
        repo_root_digest="digest",
        workflow_id="intent:intent-a-001",
        records=(
            _record(
                1, EVENT_INTENT_DECLARED, status="active", scope_paths=["pkg/a.py"]
            ),
            _record(2, EVENT_PATCH_VERIFIED, status="accepted", baseline_abuse=True),
        ),
    )
    assert abused.outcome == "violated"

    from codeclone.config.memory import IngestConfig, resolve_memory_config

    ingest = IngestConfig.model_validate(
        {
            "contract_constants_paths": "codeclone/contracts/__init__.py",
            "mcp_tool_count_doc_paths": ["docs/book/25-mcp-interface/index.md"],
            "mcp_tool_schema_snapshot_path": "",
        }
    )
    assert ingest.mcp_tool_schema_snapshot_path is None
    assert ingest.contract_constants_paths == ("codeclone/contracts/__init__.py",)

    root = tmp_path / "cfg-root"
    root.mkdir()
    outside_db = tmp_path / "outside.sqlite3"
    outside_db.write_text("", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        f'[tool.codeclone.memory]\ndb_path = "{outside_db}"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must stay under the repository root"):
        resolve_memory_config(root)


def test_project_trajectory_external_changes_outcome() -> None:
    from codeclone.audit.events import EVENT_INTENT_DECLARED, EVENT_PATCH_VERIFIED
    from codeclone.memory.trajectory.projector import project_trajectory

    trajectory = project_trajectory(
        project_id="proj",
        repo_root_digest="digest",
        workflow_id="intent:intent-a-001",
        records=(
            _record(
                1, EVENT_INTENT_DECLARED, status="active", scope_paths=["pkg/a.py"]
            ),
            _record(
                2,
                EVENT_PATCH_VERIFIED,
                status="accepted_with_external_changes",
            ),
        ),
    )
    assert trajectory.outcome == "accepted_with_external_changes"


def test_project_trajectory_agent_fallback_and_noncanonical_digest() -> None:
    import hashlib
    import json

    from codeclone.audit.events import EVENT_INTENT_CHECKED, EVENT_INTENT_DECLARED
    from codeclone.memory.trajectory.projector import project_trajectory

    checked = project_trajectory(
        project_id="proj",
        repo_root_digest="digest",
        workflow_id="intent:intent-a-001",
        records=(
            replace(
                _record(
                    1, EVENT_INTENT_DECLARED, status="active", scope_paths=["pkg/a.py"]
                ),
                agent_label="   ",
            ),
            replace(
                _record(
                    2,
                    EVENT_INTENT_CHECKED,
                    status="clean",
                    declared_scope_paths=["pkg/a.py"],
                    changed_files=["pkg/a.py"],
                ),
                agent_label="backup-agent",
            ),
        ),
    )
    agent_subjects = {
        (subject.subject_kind, subject.subject_key)
        for subject in checked.subjects
        if subject.subject_kind == "agent"
    }
    assert agent_subjects == {("agent", "backup-agent")}

    bad_facts_core, _bad_facts_sha = _core(
        EVENT_INTENT_DECLARED,
        status="active",
        scope_paths=["pkg/a.py"],
    )
    broken_facts = json.loads(bad_facts_core)
    broken_facts["facts"] = "not-a-mapping"
    broken_text = json.dumps(broken_facts, sort_keys=True, separators=(",", ":"))
    broken_sha = hashlib.sha256(broken_text.encode("utf-8")).hexdigest()
    short_digest = project_trajectory(
        project_id="proj",
        repo_root_digest="digest",
        workflow_id="intent:intent-a-001",
        records=(
            replace(
                _record(
                    1, EVENT_INTENT_DECLARED, status="active", scope_paths=["pkg/a.py"]
                ),
                event_core_json=broken_text,
                event_core_sha256=broken_sha,
                report_digest="short-digest",
            ),
        ),
    )
    assert short_digest.report_digest == "short-digest"
