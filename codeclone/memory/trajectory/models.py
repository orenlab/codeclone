# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TRAJECTORY_PROJECTION_VERSION = "trajectory-v2"
TRAJECTORY_PROJECTION_VERSION_V1 = "trajectory-v1"

TrajectoryOutcome = Literal[
    "accepted",
    "accepted_with_external_changes",
    "violated",
    "blocked",
    "abandoned",
    "partial",
]
TrajectoryQualityTier = Literal[
    "corrected",
    "verified",
    "incident",
    "partial",
    "routine",
]
TrajectoryLabel = Literal[
    "baseline_abuse_detected",
    "claim_guard_failed",
    "external_changes_accepted",
    "foreign_conflict_seen",
    "hook_blocked",
    "memory_used",
    "recovered",
]


@dataclass(frozen=True, slots=True)
class TrajectoryStep:
    step_index: int
    audit_sequence: int
    event_id: str
    event_type: str
    status: str | None
    run_id: str | None
    report_digest: str | None
    event_core_sha256: str
    event_core_json: str
    summary: str | None
    created_at_utc: str


@dataclass(frozen=True, slots=True)
class TrajectorySubject:
    subject_kind: str
    subject_key: str
    relation: str = "about"


@dataclass(frozen=True, slots=True)
class TrajectoryEvidence:
    evidence_kind: str
    ref: str
    locator: str | None
    digest: str | None
    created_at_utc: str


@dataclass(frozen=True, slots=True)
class Trajectory:
    id: str
    project_id: str
    repo_root_digest: str
    workflow_id: str
    intent_id: str | None
    primary_run_id: str | None
    first_run_id: str | None
    last_run_id: str | None
    report_digest: str | None
    outcome: TrajectoryOutcome
    quality_tier: TrajectoryQualityTier
    labels: tuple[TrajectoryLabel, ...]
    summary: str
    trajectory_digest: str
    source_event_stream_digest: str
    projection_version: str
    event_count: int
    step_count: int
    incident_count: int
    started_at_utc: str
    finished_at_utc: str
    projected_at_utc: str
    updated_at_utc: str
    steps: tuple[TrajectoryStep, ...]
    subjects: tuple[TrajectorySubject, ...]
    evidence: tuple[TrajectoryEvidence, ...]


@dataclass(frozen=True, slots=True)
class TrajectoryProjectionRun:
    id: str
    project_id: str
    repo_root_digest: str
    projection_version: str
    started_at_utc: str
    finished_at_utc: str
    status: str
    workflows_seen: int
    trajectories_created: int
    trajectories_updated: int
    trajectories_unchanged: int
    legacy_event_count: int
    message: str | None


@dataclass(frozen=True, slots=True)
class TrajectoryProjectionResult:
    run: TrajectoryProjectionRun
    trajectories: tuple[Trajectory, ...]


@dataclass(frozen=True, slots=True)
class TrajectoryListItem:
    id: str
    workflow_id: str
    outcome: str
    quality_tier: str
    event_count: int
    started_at_utc: str
    finished_at_utc: str
    summary: str


__all__ = [
    "TRAJECTORY_PROJECTION_VERSION",
    "Trajectory",
    "TrajectoryEvidence",
    "TrajectoryLabel",
    "TrajectoryListItem",
    "TrajectoryOutcome",
    "TrajectoryProjectionResult",
    "TrajectoryProjectionRun",
    "TrajectoryQualityTier",
    "TrajectoryStep",
    "TrajectorySubject",
]
