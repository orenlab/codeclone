# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from ...audit.events import (
    EVENT_INTENT_CLEARED,
    EVENT_PATCH_VERIFIED,
)
from .models import Trajectory, TrajectoryLabel
from .patch_trail import patch_trail_from_mapping

TrajectoryAnomalySeverity = Literal["warn", "error"]

INCIDENT_LABELS: frozenset[TrajectoryLabel] = frozenset(
    {
        "baseline_abuse_detected",
        "claim_guard_failed",
        "foreign_conflict_seen",
        "hook_blocked",
        "recovered",
    }
)

ELEVATED_INCIDENT_THRESHOLD = 2


@dataclass(frozen=True, slots=True)
class TrajectoryAnomaly:
    kind: str
    severity: TrajectoryAnomalySeverity
    message: str


def detect_trajectory_anomalies(
    trajectory: Trajectory,
    *,
    patch_trail_payload: Mapping[str, object] | None = None,
) -> tuple[TrajectoryAnomaly, ...]:
    """Return deterministic anomaly tags for one stored trajectory."""
    anomalies: list[TrajectoryAnomaly] = []
    label_set = set(trajectory.labels)
    event_types = {step.event_type for step in trajectory.steps}

    if trajectory.outcome == "violated":
        anomalies.append(
            TrajectoryAnomaly(
                kind="outcome_violated",
                severity="error",
                message="Trajectory outcome is violated.",
            )
        )
    elif trajectory.outcome == "blocked":
        anomalies.append(
            TrajectoryAnomaly(
                kind="outcome_blocked",
                severity="error",
                message="Trajectory outcome is blocked.",
            )
        )
    elif trajectory.outcome == "abandoned":
        anomalies.append(
            TrajectoryAnomaly(
                kind="outcome_abandoned",
                severity="warn",
                message="Trajectory outcome is abandoned.",
            )
        )

    if trajectory.quality_tier == "incident":
        anomalies.append(
            TrajectoryAnomaly(
                kind="quality_incident",
                severity="error",
                message="Trajectory quality tier is incident.",
            )
        )

    if trajectory.incident_count >= ELEVATED_INCIDENT_THRESHOLD:
        anomalies.append(
            TrajectoryAnomaly(
                kind="elevated_incidents",
                severity="warn",
                message=(
                    f"Trajectory recorded {trajectory.incident_count} audit incidents."
                ),
            )
        )

    for label in sorted(label_set & INCIDENT_LABELS):
        severity: TrajectoryAnomalySeverity = (
            "error"
            if label in {"baseline_abuse_detected", "claim_guard_failed"}
            else "warn"
        )
        anomalies.append(
            TrajectoryAnomaly(
                kind=f"label_{label}",
                severity=severity,
                message=f"Incident label present: {label}.",
            )
        )

    if (
        "change_control_workflow" in label_set
        and "verified_finish" not in label_set
        and trajectory.outcome not in {"accepted", "accepted_with_external_changes"}
    ):
        anomalies.append(
            TrajectoryAnomaly(
                kind="incomplete_change_cycle",
                severity="warn",
                message="Change-control workflow did not reach verified finish.",
            )
        )

    if EVENT_INTENT_CLEARED not in event_types and EVENT_PATCH_VERIFIED in event_types:
        anomalies.append(
            TrajectoryAnomaly(
                kind="missing_intent_clear",
                severity="warn",
                message="Patch verified without intent.cleared in the audit stream.",
            )
        )

    trail = (
        patch_trail_from_mapping(patch_trail_payload)
        if patch_trail_payload is not None
        else None
    )
    if trail is not None:
        if trail.scope_check_status == "violated":
            anomalies.append(
                TrajectoryAnomaly(
                    kind="scope_violation",
                    severity="error",
                    message="Patch trail scope check is violated.",
                )
            )
        if trail.verification_status in {"violated", "not_reached"} and (
            trajectory.outcome in {"partial", "violated", "blocked"}
        ):
            anomalies.append(
                TrajectoryAnomaly(
                    kind="verification_gap",
                    severity="warn",
                    message=(
                        f"Patch verification status is {trail.verification_status}."
                    ),
                )
            )

    return tuple(anomalies)


def serialize_anomaly(anomaly: TrajectoryAnomaly) -> dict[str, str]:
    return {
        "kind": anomaly.kind,
        "severity": anomaly.severity,
        "message": anomaly.message,
    }


def anomaly_summary(
    items: Sequence[tuple[Trajectory, tuple[TrajectoryAnomaly, ...]]],
) -> dict[str, object]:
    by_kind: dict[str, int] = {}
    error_count = 0
    warn_count = 0
    for _trajectory, anomalies in items:
        for anomaly in anomalies:
            by_kind[anomaly.kind] = by_kind.get(anomaly.kind, 0) + 1
            if anomaly.severity == "error":
                error_count += 1
            else:
                warn_count += 1
    return {
        "trajectories_with_anomalies": len(items),
        "anomaly_count": error_count + warn_count,
        "error_count": error_count,
        "warn_count": warn_count,
        "by_kind": dict(sorted(by_kind.items())),
    }


__all__ = [
    "ELEVATED_INCIDENT_THRESHOLD",
    "INCIDENT_LABELS",
    "TrajectoryAnomaly",
    "TrajectoryAnomalySeverity",
    "anomaly_summary",
    "detect_trajectory_anomalies",
    "serialize_anomaly",
]
