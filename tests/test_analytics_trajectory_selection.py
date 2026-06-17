# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from codeclone.analytics.corpus.trajectory_selection import select_trajectory_for_intent
from codeclone.contracts import TRAJECTORY_PROJECTION_VERSION
from codeclone.memory.trajectory.models import (
    Trajectory,
    TrajectoryEvidence,
    TrajectoryLabel,
    TrajectoryStep,
    TrajectorySubject,
)


def _trajectory(
    *,
    trajectory_id: str,
    labels: tuple[TrajectoryLabel, ...] = (),
    terminal_sequence: int = 10,
    projection_version: str = TRAJECTORY_PROJECTION_VERSION,
    terminal_event_type: str = "intent.cleared",
) -> Trajectory:
    step = TrajectoryStep(
        step_index=0,
        audit_sequence=terminal_sequence,
        event_id=f"evt-{trajectory_id}",
        event_type=terminal_event_type,
        status="accepted",
        run_id="run-1",
        report_digest=None,
        event_core_sha256="abc",
        event_core_json="{}",
        summary=None,
        created_at_utc="2026-01-01T00:00:00Z",
    )
    return Trajectory(
        id=trajectory_id,
        project_id="proj-1",
        repo_root_digest="digest",
        workflow_id="intent:intent-a",
        intent_id="intent-a",
        primary_run_id="run-1",
        first_run_id="run-1",
        last_run_id="run-1",
        report_digest=None,
        outcome="accepted",
        quality_tier="verified",
        quality_score=90,
        labels=labels,
        summary="done",
        trajectory_digest=f"digest-{trajectory_id}",
        source_event_stream_digest="stream",
        projection_version=projection_version,
        event_count=1,
        step_count=1,
        incident_count=0,
        started_at_utc="2026-01-01T00:00:00Z",
        finished_at_utc="2026-01-01T00:01:00Z",
        projected_at_utc="2026-01-01T00:01:00Z",
        updated_at_utc="2026-01-01T00:01:00Z",
        steps=(step,),
        subjects=(
            TrajectorySubject(
                subject_kind="agent",
                subject_key="cursor-agent",
                relation="actor",
            ),
        ),
        evidence=(
            TrajectoryEvidence(
                evidence_kind="audit",
                ref="evt-1",
                locator=None,
                digest=None,
                created_at_utc="2026-01-01T00:00:00Z",
            ),
        ),
    )


def test_trajectory_selection_deterministic() -> None:
    first = _trajectory(
        trajectory_id="traj-a",
        terminal_sequence=20,
        terminal_event_type="intent.declared",
    )
    second = _trajectory(
        trajectory_id="traj-b",
        labels=("verified_finish",),
        terminal_sequence=10,
    )
    legacy = _trajectory(
        trajectory_id="traj-legacy",
        projection_version="trajectory-v1",
    )
    result = select_trajectory_for_intent((first, second, legacy))
    assert result.selected is not None
    assert result.selected.id == "traj-b"
    assert set(result.discarded_ids) == {"traj-a"}


def test_trajectory_selection_uses_greatest_id_for_sequence_tie() -> None:
    result = select_trajectory_for_intent(
        (
            _trajectory(trajectory_id="traj-a", terminal_sequence=20),
            _trajectory(trajectory_id="traj-z", terminal_sequence=20),
        )
    )
    assert result.selected is not None
    assert result.selected.id == "traj-z"
