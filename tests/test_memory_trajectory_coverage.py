# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from codeclone.config.memory import resolve_memory_config
from codeclone.contracts import PATCH_TRAIL_SCHEMA_VERSION
from codeclone.memory.exceptions import MemoryContractError
from codeclone.memory.trajectory.cli_render import (
    render_projection_run,
    render_trajectory_agents,
    render_trajectory_anomalies,
    render_trajectory_detail,
    render_trajectory_list,
    render_trajectory_search_results,
    render_trajectory_status,
)
from codeclone.memory.trajectory.dto import (
    BlastRadiusSnapshot,
    HygieneSnapshot,
    PatchTrailEvidenceInput,
    PatchTrailInputs,
    VerifySnapshot,
)
from codeclone.memory.trajectory.export_context import (
    build_export_context,
    build_export_record,
    extract_trajectory_citations,
    projection_version_rank,
    resolve_export_scope_paths,
    select_canonical_trajectories,
    trajectory_path_subjects,
)
from codeclone.memory.trajectory.models import (
    TRAJECTORY_PROJECTION_VERSION_V1,
    TrajectoryListItem,
)
from codeclone.memory.trajectory.patch_trail import (
    compute_patch_trail,
    patch_trail_from_mapping,
    patch_trail_summary_line,
)
from codeclone.memory.trajectory.profiles import (
    EXPORT_PROFILES,
    resolve_export_profile,
    trajectory_eligible_for_export,
)
from codeclone.memory.trajectory.rebuild_workflow import execute_trajectory_rebuild
from codeclone.memory.trajectory.retrieval import (
    filter_trajectories_for_query,
    trajectory_subject_keys,
)

from .memory_fixtures import (
    memory_store,
    seed_path_subject_record,
    seed_trajectory_audit_workflow,
)


def _export_context(payload: dict[str, object]) -> dict[str, object]:
    context = payload["context"]
    assert isinstance(context, dict)
    return context


class _CapturePrinter:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def print(self, *objects: object, **kwargs: object) -> None:
        self.lines.append(" ".join(str(item) for item in objects))


def _patch_trail_inputs() -> PatchTrailInputs:
    return PatchTrailInputs(
        intent_id="intent-test",
        intent_description="x" * 600,
        declared_files=tuple(f"file{i}.py" for i in range(600)),
        declared_related=(),
        changed_files=("a.py",),
        unexpected_files=(),
        forbidden_touched=(),
        expanded_related_files=(),
        scope_check_status="clean",
        blast_radius=BlastRadiusSnapshot(
            do_not_touch_declared=("codeclone.baseline.json",),
            review_context_declared=("codeclone/core/pipeline.py",),
        ),
        verify=VerifySnapshot(
            verification_profile="python_structural",
            verification_status="accepted",
            verification_skipped=(),
            verification_failed=(),
        ),
        hygiene=HygieneSnapshot(
            blocks_finish=False,
            finish_block_reason=None,
            unacknowledged_dirty_in_scope=(),
            dirty_paths_outside_scope=(),
            attribution_counts={"in_scope": 1},
        ),
        evidence=PatchTrailEvidenceInput(
            repo_root_digest="abcd1234",
            report_digest="sha256:deadbeef",
            scope_check_audit_sequence=10,
            patch_verify_audit_sequence=11,
        ),
    )


def test_execute_trajectory_rebuild_skips_when_disabled(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    config = replace(resolve_memory_config(root), trajectories_enabled=False)
    payload = execute_trajectory_rebuild(root_path=root, config=config)
    assert payload["status"] == "skipped"
    assert payload["reason"] == "trajectories_disabled"


def test_execute_trajectory_rebuild_requires_memory_db(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    config = resolve_memory_config(root)
    with pytest.raises(MemoryContractError, match="database not found"):
        execute_trajectory_rebuild(root_path=root, config=config)


def test_execute_trajectory_rebuild_ok_with_audit(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, _db_path):
        audit_db = root / ".codeclone" / "db" / "audit.sqlite3"
        seed_trajectory_audit_workflow(root=root, audit_db=audit_db)
        config = resolve_memory_config(root)
        payload = execute_trajectory_rebuild(
            root_path=root,
            config=config,
            store=store,
            project=project,
        )
        assert payload["status"] == "ok"
        assert payload["workflows_seen"] >= 1


def test_resolve_export_profile_and_eligibility(tmp_path: Path) -> None:
    profile = resolve_export_profile("agent-change-control-v1")
    assert profile.name in EXPORT_PROFILES

    with pytest.raises(ValueError, match="Unsupported trajectory export profile"):
        resolve_export_profile("unknown-profile")

    with memory_store(tmp_path) as (root, project, store, _db_path):
        audit_db = tmp_path / "audit.sqlite3"
        seed_trajectory_audit_workflow(root=root, audit_db=audit_db)
        trajectory = store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        ).trajectories[0]
        assert trajectory_eligible_for_export(trajectory, profile=profile) is True
        assert (
            trajectory_eligible_for_export(
                replace(trajectory, quality_tier="routine"),
                profile=profile,
            )
            is False
        )
        recovery = EXPORT_PROFILES["agent-recovery-v1"]
        partial = replace(trajectory, outcome="partial", quality_tier="partial")
        assert trajectory_eligible_for_export(partial, profile=recovery) is True
        assert trajectory_eligible_for_export(partial, profile=profile) is False


def test_cli_render_helpers_cover_empty_and_populated_states(tmp_path: Path) -> None:
    printer = _CapturePrinter()
    render_trajectory_status(
        console=printer,
        enabled=False,
        count=0,
        latest_run=None,
    )
    assert "disabled" in printer.lines[0]

    with memory_store(tmp_path) as (root, project, store, _db_path):
        audit_db = tmp_path / "audit.sqlite3"
        seed_trajectory_audit_workflow(root=root, audit_db=audit_db)
        projection = store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        )
        run = projection.run
        trajectory = projection.trajectories[0]
        render_trajectory_status(
            console=printer,
            enabled=True,
            count=len(projection.trajectories),
            latest_run=run,
        )
        render_projection_run(console=printer, run=run)
        render_trajectory_list(console=printer, items=[])
        render_trajectory_list(
            console=printer,
            items=[
                TrajectoryListItem(
                    id=trajectory.id,
                    workflow_id=trajectory.workflow_id,
                    outcome=trajectory.outcome,
                    quality_tier=trajectory.quality_tier,
                    quality_score=trajectory.quality_score,
                    summary=trajectory.summary,
                    event_count=trajectory.event_count,
                    finished_at_utc=trajectory.finished_at_utc,
                    started_at_utc=trajectory.started_at_utc,
                )
            ],
        )
    render_trajectory_search_results(
        console=printer,
        query="service",
        trajectories=[],
    )
    render_trajectory_search_results(
        console=printer,
        query="service",
        trajectories=[
            {
                "trajectory_id": "traj-1",
                "outcome": "accepted",
                "quality_tier": "verified",
                "relevance_score": 0.9,
                "summary": "done",
            }
        ],
    )
    render_trajectory_detail(console=printer, trajectory=trajectory)
    assert any("trajectory:" in line for line in printer.lines)


def test_patch_trail_full_payload_truncation_and_summary() -> None:
    trail = compute_patch_trail(_patch_trail_inputs())
    full = trail.to_payload(detail_level="full")
    assert full["schema_version"] == PATCH_TRAIL_SCHEMA_VERSION
    assert trail.truncation["declared_files"] is True
    summary_line = patch_trail_summary_line(trail)
    assert "declared=" in summary_line
    assert patch_trail_from_mapping({"schema_version": "0"}) is None


def test_projection_version_rank_and_export_context(tmp_path: Path) -> None:
    assert projection_version_rank("trajectory-v2") == 2
    assert projection_version_rank("unknown") == 0

    with memory_store(tmp_path) as (root, project, store, _db_path):
        audit_db = tmp_path / "audit.sqlite3"
        seed_trajectory_audit_workflow(root=root, audit_db=audit_db)
        projection = store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        )
        trajectory = projection.trajectories[0]
        canonical = {
            item.workflow_id: item
            for item in select_canonical_trajectories([trajectory])
        }
        conn = store._conn
        context_payload = build_export_context(
            conn,
            project_id=project.id,
            trajectory=trajectory,
            scope_paths=("pkg/service.py",),
            patch_trail_payload=None,
            canonical_by_workflow=canonical,
        )
        assert "context" in context_payload
        profile = resolve_export_profile("agent-memory-retrieval-v1")
        record = build_export_record(
            trajectory=trajectory,
            profile=profile,
            project=project,
            include_payloads=False,
            enrichment=context_payload,
            scope_paths=("pkg/service.py",),
        )
        assert record["profile"] == profile.name
        legacy = replace(
            trajectory,
            id="traj-legacy",
            projection_version=TRAJECTORY_PROJECTION_VERSION_V1,
        )
        selected = select_canonical_trajectories([legacy, trajectory])
        assert selected[0].projection_version == trajectory.projection_version


def test_trajectory_retrieval_helpers_handle_empty_query_and_subjects(
    tmp_path: Path,
) -> None:
    with memory_store(tmp_path) as (root, project, store, _db_path):
        audit_db = tmp_path / "audit.sqlite3"
        seed_trajectory_audit_workflow(root=root, audit_db=audit_db)
        trajectory = store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        ).trajectories[0]

    assert filter_trajectories_for_query([trajectory], query="", match_mode="any") == ()
    keys = trajectory_subject_keys(
        scope_paths=("pkg/service.py",),
        symbols=("pkg.service", "  "),
    )
    assert "path" in keys
    assert keys["symbol"] == ("pkg.service",)


def test_cli_render_agents_and_anomalies_cover_populated_payloads() -> None:
    printer = _CapturePrinter()
    render_trajectory_agents(
        console=printer,
        payload={
            "agent_count": 1,
            "trajectory_count": 2,
            "unlabeled_trajectory_count": 0,
            "agents": [
                {
                    "agent_label": "test-agent",
                    "trajectory_count": 2,
                    "intent_count": 1,
                    "failed_outcome_count": 0,
                    "anomaly_count": 1,
                }
            ],
        },
    )
    render_trajectory_agents(console=printer, payload={"agents": []})
    render_trajectory_anomalies(
        console=printer,
        payload={
            "summary": {
                "trajectories_with_anomalies": 1,
                "anomaly_count": 2,
                "error_count": 1,
                "warn_count": 1,
            },
            "trajectories": [
                {
                    "trajectory_id": "traj-1",
                    "agent_label": "test-agent",
                    "outcome": "accepted",
                    "quality_tier": "verified",
                    "anomalies": [
                        {
                            "severity": "warn",
                            "kind": "scope_expanded",
                            "message": "expanded related files",
                        }
                    ],
                }
            ],
        },
    )
    render_trajectory_anomalies(console=printer, payload={"trajectories": []})
    assert any("Agents:" in line for line in printer.lines)
    assert any("Anomaly summary:" in line for line in printer.lines)


def test_export_context_record_citations_and_scope_paths(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, _db_path):
        audit_db = tmp_path / "audit.sqlite3"
        seed_trajectory_audit_workflow(root=root, audit_db=audit_db)
        projection = store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        )
        trajectory = projection.trajectories[0]
        profile = resolve_export_profile("agent-memory-retrieval-v1")
        record = build_export_record(
            trajectory=trajectory,
            profile=profile,
            project=project,
            include_payloads=True,
            enrichment={"context": "not-a-dict", "citations": "not-a-list"},
            scope_paths=("pkg/service.py",),
        )
        assert isinstance(record["context"], dict)
        assert record["citations"] == []
        assert "steps" in record
        citations = extract_trajectory_citations(trajectory)
        assert isinstance(citations, list)
        scope = resolve_export_scope_paths(trajectory, patch_trail_payload=None)
        assert scope
        conn = store._conn
        context_payload = build_export_context(
            conn,
            project_id=project.id,
            trajectory=trajectory,
            scope_paths=scope,
            patch_trail_payload=None,
            canonical_by_workflow={trajectory.workflow_id: trajectory},
        )
        assert _export_context(context_payload)["memory_precedents"] is not None


def test_export_scope_paths_and_precedents_from_patch_trail(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, _db_path):
        audit_db = tmp_path / "audit.sqlite3"
        seed_trajectory_audit_workflow(root=root, audit_db=audit_db)
        projection = store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        )
        trajectory = projection.trajectories[0]
        trail = compute_patch_trail(_patch_trail_inputs())
        scope = resolve_export_scope_paths(
            replace(trajectory, subjects=()),
            patch_trail_payload=trail.to_payload(detail_level="full"),
        )
        assert scope
        assert "pkg/service.py" in trajectory_path_subjects(
            trajectory, relations={"about"}
        )
        older = replace(
            trajectory,
            id="traj-older",
            workflow_id="intent:intent-older",
            finished_at_utc="2020-01-01T00:00:00Z",
            started_at_utc="2020-01-01T00:00:00Z",
        )
        context_payload = build_export_context(
            store._conn,
            project_id=project.id,
            trajectory=trajectory,
            scope_paths=("pkg/service.py",),
            patch_trail_payload=trail.to_payload(detail_level="summary"),
            canonical_by_workflow={
                trajectory.workflow_id: trajectory,
                older.workflow_id: older,
            },
        )
        export_ctx = _export_context(context_payload)
        trajectory_precedents = export_ctx["trajectory_precedents"]
        assert isinstance(trajectory_precedents, list)
        citations = extract_trajectory_citations(trajectory)
        assert isinstance(citations, list)
        profile = resolve_export_profile("agent-change-control-v1")
        enriched = build_export_record(
            trajectory=trajectory,
            profile=profile,
            project=project,
            include_payloads=False,
            enrichment={
                "patch_trail_summary": {"declared": 1, "changed": 1},
                "context": {"memory_precedents": [], "trajectory_precedents": []},
                "citations": [{"kind": "finding", "cited_id": "f-1"}],
            },
            scope_paths=("pkg/service.py",),
        )
        assert enriched["patch_trail_summary"] == {"declared": 1, "changed": 1}
        assert enriched["citations"] == [{"kind": "finding", "cited_id": "f-1"}]

        seed_path_subject_record(
            store,
            project_id=project.id,
            path="pkg/other.py",
            statement="overlap memory for export precedents",
        )
        overlap_context = build_export_context(
            store._conn,
            project_id=project.id,
            trajectory=trajectory,
            scope_paths=("pkg/service.py", "pkg/other.py"),
            patch_trail_payload=None,
            canonical_by_workflow={trajectory.workflow_id: trajectory},
        )
        memory_precedents = _export_context(overlap_context)["memory_precedents"]
        assert isinstance(memory_precedents, list)
        assert memory_precedents
