# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from codeclone.memory.trajectory.models import Trajectory, TrajectoryStep
from codeclone.memory.trajectory.quality import (
    TRAJECTORY_QUALITY_SCORE_VERSION,
    compute_trajectory_quality_contract,
    compute_trajectory_quality_score,
    serialize_trajectory_quality_contract,
)

from .memory_fixtures import memory_store, seed_trajectory_audit_workflow


def _verified_patch_trail() -> dict[str, object]:
    return {
        "schema_version": "1",
        "scope_check_status": "clean",
        "verification_status": "accepted",
        "declared_files": ["a.py"],
        "changed_files": ["a.py"],
        "unexpected_files": [],
        "forbidden_touched": [],
        "patch_trail_digest": "f" * 64,
    }


def _verified_trajectory(*, incident_count: int = 0) -> Trajectory:
    steps = (
        TrajectoryStep(
            step_index=0,
            audit_sequence=1,
            event_id="evt-0",
            event_type="intent.cleared",
            status="accepted",
            run_id="run-after",
            report_digest="b" * 64,
            event_core_sha256="a" * 64,
            event_core_json="{}",
            summary="cleared",
            created_at_utc="2026-01-01T00:00:05Z",
        ),
        TrajectoryStep(
            step_index=1,
            audit_sequence=2,
            event_id="evt-1",
            event_type="patch_contract.verified",
            status="accepted",
            run_id="run-after",
            report_digest="b" * 64,
            event_core_sha256="c" * 64,
            event_core_json="{}",
            summary="accepted",
            created_at_utc="2026-01-01T00:00:10Z",
        ),
    )
    return Trajectory(
        id="traj-test",
        project_id="proj",
        repo_root_digest="digest",
        workflow_id="intent:test",
        intent_id="test",
        primary_run_id="run-after",
        first_run_id="run-before",
        last_run_id="run-after",
        report_digest="b" * 64,
        outcome="accepted",
        quality_tier="verified",
        quality_score=0,
        labels=(
            "change_control_workflow",
            "scope_clean",
            "verified_finish",
            "receipt_issued",
        ),
        summary="summary",
        trajectory_digest="d" * 64,
        source_event_stream_digest="e" * 64,
        projection_version="trajectory-v2",
        event_count=2,
        step_count=2,
        incident_count=incident_count,
        started_at_utc="2026-01-01T00:00:00Z",
        finished_at_utc="2026-01-01T00:00:10Z",
        projected_at_utc="2026-01-01T00:00:11Z",
        updated_at_utc="2026-01-01T00:00:11Z",
        steps=steps,
        subjects=(),
        evidence=(),
    )


def test_compute_trajectory_quality_score_is_deterministic(tmp_path: Path) -> None:
    audit_db = tmp_path / "audit.sqlite3"
    with memory_store(tmp_path) as (root, project, store, _db_path):
        seed_trajectory_audit_workflow(root=root, audit_db=audit_db)
        store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        )
        items = store.list_trajectories(project_id=project.id, limit=1)
        trajectory = store.find_trajectory(items[0].id)
        assert trajectory is not None
        patch_trail = store.load_trajectory_patch_trail(trajectory.id)
        assert 0 <= trajectory.quality_score <= 100
        first = compute_trajectory_quality_score(
            trajectory,
            patch_trail_payload=patch_trail,
        )
        second = compute_trajectory_quality_score(
            trajectory,
            patch_trail_payload=patch_trail,
        )
        assert first == second == trajectory.quality_score


def test_rebuild_persists_quality_score_column(tmp_path: Path) -> None:
    audit_db = tmp_path / "audit.sqlite3"
    with memory_store(tmp_path) as (root, project, store, db_path):
        seed_trajectory_audit_workflow(root=root, audit_db=audit_db)
        store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        )
        import sqlite3

        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT quality_score FROM memory_trajectories LIMIT 1"
            ).fetchone()
            assert row is not None
            assert int(row[0]) > 0
        finally:
            conn.close()


def test_quality_contract_penalizes_audit_incidents() -> None:
    patch_trail = _verified_patch_trail()
    baseline = compute_trajectory_quality_contract(
        _verified_trajectory(),
        patch_trail_payload=patch_trail,
    )
    assert baseline.quality_score == 100
    contract = compute_trajectory_quality_contract(
        _verified_trajectory(incident_count=1),
        patch_trail_payload=patch_trail,
    )
    assert contract.quality_score == 90
    incident_component = next(
        item for item in contract.components if item.component_id == "incidents"
    )
    assert incident_component.pass_gate is False
    payload = serialize_trajectory_quality_contract(contract)
    calculation = payload.get("calculation")
    assert isinstance(calculation, dict)
    assert calculation.get("limiting_component_ids") == ["incidents"]


def test_quality_contract_requires_all_gates_for_100() -> None:
    contract = compute_trajectory_quality_contract(
        _verified_trajectory(),
        patch_trail_payload=_verified_patch_trail(),
    )
    assert contract.score_version == TRAJECTORY_QUALITY_SCORE_VERSION
    assert contract.quality_score == 100
    assert all(component.pass_gate for component in contract.components)
    payload = serialize_trajectory_quality_contract(contract)
    calculation = payload.get("calculation")
    assert isinstance(calculation, dict)
    assert calculation.get("method") == "contract_min"
    assert calculation.get("quality_score") == 100
    assert calculation.get("limiting_component_ids") == [
        "outcome",
        "verification",
        "scope",
        "incidents",
        "anomalies",
        "receipt",
    ]


def test_quality_contract_exposes_complexity_separately() -> None:
    small = replace(
        _verified_trajectory(),
        id="traj-small",
        workflow_id="intent:small",
        intent_id="small",
        labels=("scope_clean",),
        steps=(),
        event_count=2,
        step_count=2,
        finished_at_utc="2026-01-01T00:00:01Z",
    )
    large_patch = {
        "schema_version": "1",
        "scope_check_status": "clean",
        "verification_status": "accepted",
        "declared_files": [f"file{i}.py" for i in range(20)],
        "changed_files": [f"file{i}.py" for i in range(20)],
        "unexpected_files": [],
        "forbidden_touched": [],
        "patch_trail_digest": "f" * 64,
    }
    small_contract = compute_trajectory_quality_contract(small)
    large_contract = compute_trajectory_quality_contract(
        small,
        patch_trail_payload=large_patch,
    )
    assert large_contract.complexity_score > small_contract.complexity_score
    assert large_contract.quality_score == small_contract.quality_score


def test_complexity_calculation_serialization() -> None:
    trajectory = replace(
        _verified_trajectory(),
        event_count=7,
        step_count=7,
    )
    patch_trail = {
        "schema_version": "1",
        "scope_check_status": "clean",
        "verification_status": "accepted",
        "declared_files": ["a.py", "b.py", "c.py", "d.py"],
        "changed_files": ["a.py", "b.py", "c.py", "d.py"],
        "unexpected_files": [],
        "forbidden_touched": [],
        "patch_trail_digest": "f" * 64,
    }
    contract = compute_trajectory_quality_contract(
        trajectory,
        patch_trail_payload=patch_trail,
    )
    payload = serialize_trajectory_quality_contract(
        contract,
        trajectory=trajectory,
        patch_trail_payload=patch_trail,
    )
    calculation = payload.get("complexity_calculation")
    assert isinstance(calculation, dict)
    assert calculation.get("method") == "weighted_sum"
    assert calculation.get("complexity_score") == contract.complexity_score
    assert calculation.get("band") == "moderate"
    assert calculation.get("band_label") == "Moderate"
    lines = calculation.get("lines")
    assert isinstance(lines, list)
    assert len(lines) == 3
    declared_line = lines[0]
    assert isinstance(declared_line, dict)
    assert declared_line.get("raw") == 4
    assert declared_line.get("contribution") == 8
    assert declared_line.get("cap") == 40
