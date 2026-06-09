# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ...config.memory import MemoryConfig
from ..experience.distillation_workflow import execute_experience_distillation
from ..models import MemoryProject
from ..semantic.rebuild_workflow import execute_semantic_index_rebuild
from ..trajectory.rebuild_workflow import execute_trajectory_rebuild
from .models import ProjectionJobStatus
from .store import claim_next_projection_job as _claim_next
from .store import (
    complete_projection_job,
    worker_claim_token,
)


@dataclass(frozen=True, slots=True)
class ProjectionWorkerResult:
    status: str
    job_id: str | None
    reason: str | None
    trajectory_status: str | None
    semantic_status: str | None
    experience_status: str | None = None


def _block_status(result: Mapping[str, object], key: str) -> str | None:
    block = result.get(key)
    return str(block.get("status")) if isinstance(block, dict) else None


def _trajectory_incremental_watermark(
    conn: sqlite3.Connection,
    *,
    project_id: str,
) -> int | None:
    """Event-core id to rebuild trajectories incrementally after, or None to
    force a full rebuild (first run, projection-version change, or no watermark).

    The watermark is the ``event_core_max_id`` of the last applied stimulus; the
    append-only audit trail guarantees workflows with no newer event are
    byte-identical, so they need not be re-projected.
    """
    from ..trajectory.models import TRAJECTORY_PROJECTION_VERSION
    from .staleness import last_applied_stimulus

    applied = last_applied_stimulus(conn, project_id=project_id)
    if applied is None:
        return None
    if applied.get("trajectory_projection_version") != TRAJECTORY_PROJECTION_VERSION:
        return None
    watermark = applied.get("event_core_max_id")
    return watermark if isinstance(watermark, int) else None


def run_projection_job(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    root_path: Path,
    config: MemoryConfig,
    project: MemoryProject,
    stimulus: Mapping[str, object],
) -> tuple[ProjectionJobStatus, dict[str, object], str | None]:
    trajectory_payload = execute_trajectory_rebuild(
        root_path=root_path,
        config=config,
        project=project,
        incremental_after_event_core_id=_trajectory_incremental_watermark(
            conn, project_id=project.id
        ),
    )
    semantic_payload = execute_semantic_index_rebuild(
        root_path=root_path,
        config=config,
        project=project,
    )
    # Experiences distill from the trajectories rebuilt above — same job, run
    # right after so the corpus is fresh.
    experience_payload = execute_experience_distillation(
        root_path=root_path,
        config=config,
        project=project,
    )
    result: dict[str, object] = {
        "trajectory": dict(trajectory_payload),
        "semantic": dict(semantic_payload),
        "experience": dict(experience_payload),
        "applied_stimulus": dict(stimulus),
    }
    trajectory_status = str(trajectory_payload.get("status", ""))
    semantic_status = str(semantic_payload.get("status", ""))
    experience_status = str(experience_payload.get("status", ""))
    if trajectory_status == "failed" or semantic_status == "failed":
        return "failed", result, "projection_step_failed"
    skipped = (
        trajectory_status == "skipped"
        and semantic_status == "skipped"
        and experience_status == "skipped"
    )
    final_status: ProjectionJobStatus = "skipped" if skipped else "done"
    return final_status, result, None if not skipped else "all_steps_skipped"


def run_projection_jobs_once(
    conn: sqlite3.Connection,
    *,
    root_path: Path,
    config: MemoryConfig,
    project: MemoryProject,
    running_timeout_seconds: int,
) -> ProjectionWorkerResult:
    claimed = _claim_next(
        conn,
        project_id=project.id,
        claimed_by=worker_claim_token(),
        running_timeout_seconds=running_timeout_seconds,
    )
    if claimed is None:
        return ProjectionWorkerResult(
            status="nothing_to_do",
            job_id=None,
            reason="no_pending_job_or_running",
            trajectory_status=None,
            semantic_status=None,
        )
    from .staleness import parse_stimulus_json

    stimulus = parse_stimulus_json(claimed.stimulus_json)
    try:
        final_status, result, error = run_projection_job(
            conn,
            job_id=claimed.id,
            root_path=root_path,
            config=config,
            project=project,
            stimulus=stimulus,
        )
    except Exception as exc:
        complete_projection_job(
            conn,
            job_id=claimed.id,
            status="failed",
            error_message=str(exc),
        )
        return ProjectionWorkerResult(
            status="failed",
            job_id=claimed.id,
            reason=str(exc),
            trajectory_status=None,
            semantic_status=None,
        )
    complete_projection_job(
        conn,
        job_id=claimed.id,
        status=final_status,
        result=result,
        error_message=error,
    )
    return ProjectionWorkerResult(
        status=final_status,
        job_id=claimed.id,
        reason=error,
        trajectory_status=_block_status(result, "trajectory"),
        semantic_status=_block_status(result, "semantic"),
        experience_status=_block_status(result, "experience"),
    )


__all__ = ["ProjectionWorkerResult", "run_projection_job", "run_projection_jobs_once"]
