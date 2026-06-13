# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ...audit.events import EVENT_INTENT_CLEARED, EVENT_PATCH_VERIFIED
from ...contracts import TRAJECTORY_PROJECTION_VERSION
from ...memory.trajectory.models import Trajectory, TrajectoryLabel

TRAJECTORY_SELECTION_RULE_VERSION = "1"


@dataclass(frozen=True, slots=True)
class TrajectorySelectionResult:
    selected: Trajectory | None
    discarded_ids: tuple[str, ...]


def _has_verified_finish(trajectory: Trajectory) -> bool:
    if "verified_finish" in trajectory.labels:
        return True
    for step in trajectory.steps:
        if step.event_type == EVENT_INTENT_CLEARED:
            return True
        if step.event_type == EVENT_PATCH_VERIFIED and step.status in {
            "accepted",
            "accepted_with_external_changes",
        }:
            return True
    return False


def _terminal_audit_sequence(trajectory: Trajectory) -> int:
    if not trajectory.steps:
        return -1
    return max(step.audit_sequence for step in trajectory.steps)


def select_trajectory_for_intent(
    trajectories: Sequence[Trajectory],
) -> TrajectorySelectionResult:
    """Deterministic trajectory selection per spec §4.4."""
    candidates = [
        trajectory
        for trajectory in trajectories
        if trajectory.projection_version == TRAJECTORY_PROJECTION_VERSION
    ]
    if not candidates:
        return TrajectorySelectionResult(selected=None, discarded_ids=())

    finish_candidates = [item for item in candidates if _has_verified_finish(item)]
    pool = finish_candidates if finish_candidates else list(candidates)
    pool.sort(
        key=lambda item: (
            -_terminal_audit_sequence(item),
            item.id,
        )
    )
    selected = pool[0]
    discarded = tuple(
        sorted(
            trajectory.id for trajectory in candidates if trajectory.id != selected.id
        )
    )
    return TrajectorySelectionResult(selected=selected, discarded_ids=discarded)


def scope_expanded_from_labels(labels: Sequence[TrajectoryLabel | str]) -> bool:
    return "scope_expanded" in labels


__all__ = [
    "TRAJECTORY_SELECTION_RULE_VERSION",
    "TrajectorySelectionResult",
    "scope_expanded_from_labels",
    "select_trajectory_for_intent",
]
