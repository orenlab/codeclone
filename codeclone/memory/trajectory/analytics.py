# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Sequence

from ..sqlite_store import SqliteEngineeringMemoryStore
from .agents import aggregate_agent_rows, serialize_agent_row, trajectory_agent_label
from .anomalies import (
    TrajectoryAnomaly,
    anomaly_summary,
    detect_trajectory_anomalies,
    serialize_anomaly,
)
from .models import Trajectory
from .retrieval import (
    TrajectoryDetailLevel,
    filter_trajectories_for_default_retrieval,
    serialize_trajectory_preview,
    trajectory_list_item_to_preview,
    trajectory_status_payload,
)
from .store import list_canonical_trajectories_for_export

DEFAULT_ANALYTICS_LIMIT = 5000
DEFAULT_ANOMALY_PREVIEW_LIMIT = 25


def _load_trajectories(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    limit: int,
    include_routine: bool,
) -> tuple[Trajectory, ...]:
    trajectories = list_canonical_trajectories_for_export(
        store.connection,
        project_id=project_id,
        limit=limit,
    )
    return filter_trajectories_for_default_retrieval(
        trajectories,
        include_routine=include_routine,
    )


def _anomaly_map(
    store: SqliteEngineeringMemoryStore,
    trajectories: Sequence[Trajectory],
) -> dict[str, tuple[TrajectoryAnomaly, ...]]:
    mapped: dict[str, tuple[TrajectoryAnomaly, ...]] = {}
    for trajectory in trajectories:
        patch_trail = store.load_trajectory_patch_trail(trajectory.id)
        mapped[trajectory.id] = detect_trajectory_anomalies(
            trajectory,
            patch_trail_payload=patch_trail,
        )
    return mapped


def build_trajectory_agent_stats_payload(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    limit: int = DEFAULT_ANALYTICS_LIMIT,
    include_routine: bool = False,
) -> dict[str, object]:
    trajectories = _load_trajectories(
        store,
        project_id=project_id,
        limit=limit,
        include_routine=include_routine,
    )
    anomaly_by_id = _anomaly_map(store, trajectories)
    rows = aggregate_agent_rows(trajectories, anomaly_by_id=anomaly_by_id)
    unlabeled = sum(
        1 for trajectory in trajectories if trajectory_agent_label(trajectory) is None
    )
    return {
        "agent_count": len(rows),
        "trajectory_count": len(trajectories),
        "unlabeled_trajectory_count": unlabeled,
        "agents": [serialize_agent_row(row) for row in rows],
    }


def build_trajectory_anomalies_payload(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    max_results: int = DEFAULT_ANOMALY_PREVIEW_LIMIT,
    limit: int = DEFAULT_ANALYTICS_LIMIT,
    include_routine: bool = False,
    detail_level: TrajectoryDetailLevel = "full",
) -> dict[str, object]:
    trajectories = _load_trajectories(
        store,
        project_id=project_id,
        limit=limit,
        include_routine=include_routine,
    )
    hits: list[tuple[Trajectory, tuple[TrajectoryAnomaly, ...]]] = []
    for trajectory in trajectories:
        patch_trail = store.load_trajectory_patch_trail(trajectory.id)
        anomalies = detect_trajectory_anomalies(
            trajectory,
            patch_trail_payload=patch_trail,
        )
        if anomalies:
            hits.append((trajectory, anomalies))
    hits.sort(
        key=lambda item: (
            sum(1 for anomaly in item[1] if anomaly.severity == "error"),
            len(item[1]),
            item[0].finished_at_utc,
            item[0].id,
        ),
        reverse=True,
    )
    truncated = len(hits) > max_results
    selected = hits[: max(1, int(max_results))]
    payload_items: list[dict[str, object]] = []
    for trajectory, anomalies in selected:
        preview = serialize_trajectory_preview(
            trajectory,
            detail_level=detail_level,
        )
        preview["agent_label"] = trajectory_agent_label(trajectory)
        preview["anomalies"] = [serialize_anomaly(item) for item in anomalies]
        payload_items.append(preview)
    return {
        "trajectories": payload_items,
        "trajectory_count": len(payload_items),
        "truncated": truncated,
        "summary": anomaly_summary(hits),
    }


def build_trajectory_dashboard_payload(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    max_results: int = DEFAULT_ANOMALY_PREVIEW_LIMIT,
    include_routine: bool = False,
    detail_level: TrajectoryDetailLevel = "full",
) -> dict[str, object]:
    status = trajectory_status_payload(
        count=store.count_trajectories(project_id=project_id),
        latest_run=store.latest_trajectory_projection_run(project_id=project_id),
    )
    agents = build_trajectory_agent_stats_payload(
        store,
        project_id=project_id,
        include_routine=include_routine,
    )
    anomalies = build_trajectory_anomalies_payload(
        store,
        project_id=project_id,
        max_results=max_results,
        include_routine=include_routine,
        detail_level=detail_level,
    )
    recent_items = store.list_trajectories(
        project_id=project_id,
        limit=max_results,
    )
    return {
        "status": status,
        "agents": agents,
        "anomalies": anomalies,
        "recent_trajectories": [
            trajectory_list_item_to_preview(item) for item in recent_items
        ],
    }


__all__ = [
    "DEFAULT_ANALYTICS_LIMIT",
    "DEFAULT_ANOMALY_PREVIEW_LIMIT",
    "build_trajectory_agent_stats_payload",
    "build_trajectory_anomalies_payload",
    "build_trajectory_dashboard_payload",
]
