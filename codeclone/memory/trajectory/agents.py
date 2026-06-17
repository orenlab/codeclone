# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .anomalies import TrajectoryAnomaly, detect_trajectory_anomalies
from .models import Trajectory


@dataclass(frozen=True, slots=True)
class AgentTrajectoryRow:
    agent_label: str
    trajectory_count: int
    intent_count: int
    failed_outcome_count: int
    incident_total: int
    anomaly_count: int


def trajectory_agent_label(trajectory: Trajectory) -> str | None:
    for subject in trajectory.subjects:
        if subject.subject_kind == "agent" and subject.relation == "actor":
            text = subject.subject_key.strip()
            if text:
                return text
    return None


def aggregate_agent_rows(
    trajectories: Sequence[Trajectory],
    *,
    anomaly_by_id: Mapping[str, tuple[TrajectoryAnomaly, ...]] | None = None,
) -> tuple[AgentTrajectoryRow, ...]:
    buckets: dict[str, dict[str, int]] = {}
    intent_ids: dict[str, set[str]] = {}
    for trajectory in trajectories:
        label = trajectory_agent_label(trajectory)
        if not label:
            continue
        bucket = buckets.setdefault(
            label,
            {
                "trajectory_count": 0,
                "failed_outcome_count": 0,
                "incident_total": 0,
                "anomaly_count": 0,
            },
        )
        bucket["trajectory_count"] += 1
        if trajectory.outcome in {"violated", "blocked", "abandoned"}:
            bucket["failed_outcome_count"] += 1
        bucket["incident_total"] += trajectory.incident_count
        anomalies = (
            anomaly_by_id.get(trajectory.id)
            if anomaly_by_id is not None
            else detect_trajectory_anomalies(trajectory)
        )
        if anomalies:
            bucket["anomaly_count"] += len(anomalies)
        if trajectory.intent_id:
            intent_ids.setdefault(label, set()).add(trajectory.intent_id)

    rows = [
        AgentTrajectoryRow(
            agent_label=agent_label,
            trajectory_count=counts["trajectory_count"],
            intent_count=len(intent_ids.get(agent_label, set())),
            failed_outcome_count=counts["failed_outcome_count"],
            incident_total=counts["incident_total"],
            anomaly_count=counts["anomaly_count"],
        )
        for agent_label, counts in sorted(
            buckets.items(),
            key=lambda item: (-item[1]["trajectory_count"], item[0]),
        )
    ]
    return tuple(rows)


def serialize_agent_row(row: AgentTrajectoryRow) -> dict[str, object]:
    return {
        "agent_label": row.agent_label,
        "trajectory_count": row.trajectory_count,
        "intent_count": row.intent_count,
        "failed_outcome_count": row.failed_outcome_count,
        "incident_total": row.incident_total,
        "anomaly_count": row.anomaly_count,
    }


__all__ = [
    "AgentTrajectoryRow",
    "aggregate_agent_rows",
    "serialize_agent_row",
    "trajectory_agent_label",
]
