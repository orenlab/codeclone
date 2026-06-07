# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from typing import Protocol

from .models import Trajectory, TrajectoryListItem, TrajectoryProjectionRun
from .step_labels import step_display_name


class PrinterLike(Protocol):
    def print(self, *objects: object, **kwargs: object) -> None: ...


def render_trajectory_status(
    *,
    console: PrinterLike,
    enabled: bool,
    count: int,
    latest_run: TrajectoryProjectionRun | None,
) -> None:
    state = "enabled" if enabled else "disabled"
    console.print(f"trajectory memory: {state}")
    console.print(f"  trajectories: {count}")
    if latest_run is None:
        console.print("  latest projection: none")
        return
    console.print(
        "  latest projection: "
        f"{latest_run.finished_at_utc} "
        f"({latest_run.workflows_seen} workflows, "
        f"+{latest_run.trajectories_created}/"
        f"~{latest_run.trajectories_updated}/"
        f"={latest_run.trajectories_unchanged})",
        markup=False,
    )
    if latest_run.legacy_event_count:
        console.print(f"  legacy events without core: {latest_run.legacy_event_count}")


def render_projection_run(
    *,
    console: PrinterLike,
    run: TrajectoryProjectionRun,
) -> None:
    console.print(
        "Rebuilt trajectories: "
        f"{run.workflows_seen} workflows "
        f"({run.trajectories_created} created, "
        f"{run.trajectories_updated} updated, "
        f"{run.trajectories_unchanged} unchanged).",
        markup=False,
    )
    if run.legacy_event_count:
        console.print(
            f"Skipped legacy audit events without event core: {run.legacy_event_count}",
            markup=False,
        )


def render_trajectory_list(
    *,
    console: PrinterLike,
    items: list[TrajectoryListItem],
) -> None:
    if not items:
        console.print("No trajectories found.")
        return
    for item in items:
        console.print(
            f"{item.id}  {item.outcome}/{item.quality_tier}  "
            f"{item.event_count} events  {item.workflow_id}",
            markup=False,
        )
        console.print(f"  {item.summary}", markup=False)


def render_trajectory_search_results(
    *,
    console: PrinterLike,
    query: str,
    trajectories: list[dict[str, object]],
) -> None:
    console.print(f"Trajectory matches for: {query}", markup=False)
    if not trajectories:
        console.print("  No matching trajectories.")
        return
    for item in trajectories:
        trajectory_id = str(item.get("trajectory_id", ""))
        outcome = str(item.get("outcome", ""))
        tier = str(item.get("quality_tier", ""))
        score = item.get("relevance_score")
        score_text = f" score={score}" if score is not None else ""
        console.print(
            f"  {trajectory_id}  {outcome}/{tier}{score_text}",
            markup=False,
        )
        console.print(f"    {item.get('summary', '')}", markup=False)


def render_trajectory_agents(
    *,
    console: PrinterLike,
    payload: dict[str, object],
) -> None:
    agents = payload.get("agents")
    if not isinstance(agents, list) or not agents:
        console.print("No agent-labeled trajectories found.")
        return
    console.print(
        f"Agents: {payload.get('agent_count', 0)} · "
        f"trajectories: {payload.get('trajectory_count', 0)} · "
        f"unlabeled: {payload.get('unlabeled_trajectory_count', 0)}",
        markup=False,
    )
    for item in agents:
        if not isinstance(item, dict):
            continue
        console.print(
            f"  {item.get('agent_label', '?')}  "
            f"trajectories={item.get('trajectory_count', 0)}  "
            f"intents={item.get('intent_count', 0)}  "
            f"failed={item.get('failed_outcome_count', 0)}  "
            f"anomalies={item.get('anomaly_count', 0)}",
            markup=False,
        )


def render_trajectory_anomalies(
    *,
    console: PrinterLike,
    payload: dict[str, object],
) -> None:
    summary = payload.get("summary")
    if isinstance(summary, dict):
        console.print(
            "Anomaly summary: "
            f"{summary.get('trajectories_with_anomalies', 0)} trajectories · "
            f"{summary.get('anomaly_count', 0)} tags "
            f"({summary.get('error_count', 0)} error / "
            f"{summary.get('warn_count', 0)} warn)",
            markup=False,
        )
    trajectories = payload.get("trajectories")
    if not isinstance(trajectories, list) or not trajectories:
        console.print("No trajectory anomalies detected.")
        return
    for item in trajectories:
        if not isinstance(item, dict):
            continue
        trajectory_id = str(item.get("trajectory_id", ""))
        agent = item.get("agent_label")
        agent_text = f" agent={agent}" if agent else ""
        console.print(
            f"  {trajectory_id}{agent_text}  "
            f"{item.get('outcome', '')}/{item.get('quality_tier', '')}",
            markup=False,
        )
        anomalies = item.get("anomalies")
        if isinstance(anomalies, list):
            for anomaly in anomalies:
                if isinstance(anomaly, dict):
                    console.print(
                        f"    [{anomaly.get('severity', '?')}] "
                        f"{anomaly.get('kind', '?')}: "
                        f"{anomaly.get('message', '')}",
                        markup=False,
                    )


def render_trajectory_detail(
    *,
    console: PrinterLike,
    trajectory: Trajectory,
) -> None:
    console.print(f"trajectory: {trajectory.id}")
    console.print(f"  workflow: {trajectory.workflow_id}")
    console.print(f"  outcome: {trajectory.outcome}")
    console.print(
        f"  quality: {trajectory.quality_tier} ({trajectory.quality_score}/100)"
    )
    if trajectory.labels:
        console.print(f"  labels: {', '.join(trajectory.labels)}", markup=False)
    console.print(f"  digest: {trajectory.trajectory_digest}")
    console.print(f"  source stream: {trajectory.source_event_stream_digest}")
    if trajectory.report_digest:
        console.print(f"  report digest: {trajectory.report_digest}")
    console.print(f"  summary: {trajectory.summary}", markup=False)
    console.print("  steps:")
    for step in trajectory.steps:
        label = step_display_name(event_type=step.event_type, status=step.status)
        console.print(
            f"    {step.step_index + 1}. #{step.audit_sequence} {label}",
            markup=False,
        )
        if step.summary:
            console.print(f"       {step.summary[:120]}", markup=False)
    if trajectory.subjects:
        console.print("  subjects:")
        for subject in trajectory.subjects:
            console.print(
                f"    {subject.subject_kind}:{subject.subject_key} "
                f"({subject.relation})",
                markup=False,
            )


__all__ = [
    "render_projection_run",
    "render_trajectory_agents",
    "render_trajectory_anomalies",
    "render_trajectory_detail",
    "render_trajectory_list",
    "render_trajectory_search_results",
    "render_trajectory_status",
]
