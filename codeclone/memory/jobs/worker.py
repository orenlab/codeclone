# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ...config.memory import MemoryConfig
from ...observability import (
    is_observability_enabled,
    operation,
    record_elapsed_span,
    span,
)
from ...observability.profile import worker_bootstrap_sample
from ..experience.distillation_workflow import execute_experience_distillation
from ..models import MemoryProject
from ..semantic.rebuild_workflow import execute_semantic_index_rebuild
from ..sqlite_store import SqliteEngineeringMemoryStore
from ..trajectory.rebuild_workflow import execute_trajectory_rebuild
from .models import ProjectionJobStatus
from .store import claim_next_projection_job as _claim_next
from .store import (
    complete_projection_job,
    worker_claim_token,
)

if TYPE_CHECKING:
    from ...observability.reason_kind import ReasonKind


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


def _payload_int(payload: Mapping[str, object], key: str) -> int:
    """Read a non-negative integer counter from a step payload, defaulting to 0.

    Tolerant of partial payloads (failed/skipped steps may omit the key).
    """
    value = payload.get(key, 0)
    return value if isinstance(value, int) else 0


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


def _trajectory_reason_kind(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    watermark: int | None,
) -> ReasonKind:
    """Classify *why* the trajectory rebuild runs (deterministic, spec §6.4).

    An integer watermark is an incremental content-change rebuild and needs no
    extra query. A ``None`` watermark forces a full rebuild; one cheap lookup
    then distinguishes a projection-version bump from a first index.
    """
    if watermark is not None:
        return "content_changed"
    from ..trajectory.models import TRAJECTORY_PROJECTION_VERSION
    from .staleness import last_applied_stimulus

    applied = last_applied_stimulus(conn, project_id=project_id)
    if applied is None:
        return "first_index"
    if applied.get("trajectory_projection_version") != TRAJECTORY_PROJECTION_VERSION:
        return "schema_version_changed"
    return "first_index"


def _correlation_handoff() -> tuple[str | None, str | None]:
    """Read the cross-process observability handoff the spawner injected, so the
    worker operation links under the finish operation that triggered it. Returns
    ``(correlation_id, parent_operation_id)``, both None for a standalone run.
    """
    return (
        os.environ.get("CODECLONE_OBSERVABILITY_CORRELATION_ID") or None,
        os.environ.get("CODECLONE_OBSERVABILITY_PARENT_OPERATION_ID") or None,
    )


def _emit_worker_bootstrap_span() -> None:
    """Record the worker cold-start (process spawn -> first job instrumentation)
    as a ``memory.projection.worker_bootstrap`` span, positioned at the process
    creation time so the spawn->job gap in the waterfall is labelled rather than
    left as empty space. No-op when disabled or psutil is unavailable.
    """
    if not is_observability_enabled():
        return
    sample = worker_bootstrap_sample()
    if sample is None:
        return
    started_at_utc, elapsed_ms = sample
    record_elapsed_span(
        "memory.projection.worker_bootstrap",
        started_at_utc=started_at_utc,
        duration_ms=elapsed_ms,
    )


def run_projection_job(
    store: SqliteEngineeringMemoryStore,
    *,
    job_id: str,
    root_path: Path,
    config: MemoryConfig,
    project: MemoryProject,
    stimulus: Mapping[str, object],
    emit_bootstrap_span: bool = True,
) -> tuple[ProjectionJobStatus, dict[str, object], str | None]:
    conn = store.connection
    correlation_id, parent_operation_id = _correlation_handoff()
    with operation(
        name="memory.projection.job",
        surface="memory",
        correlation_id=correlation_id,
        parent_operation_id=parent_operation_id,
    ):
        # Only a spawned worker (one that carries the env handoff) has a real
        # cold-start to attribute; an in-process run shares the caller's process.
        # A delayed flush worker slept before this point, so its "bootstrap" gap
        # is intentional idle time, not cold-start — suppress it to avoid a
        # multi-second phantom span in the waterfall.
        if parent_operation_id is not None and emit_bootstrap_span:
            _emit_worker_bootstrap_span()
        watermark = _trajectory_incremental_watermark(conn, project_id=project.id)
        with span(
            name="memory.trajectory.rebuild",
            reason_kind=_trajectory_reason_kind(
                conn, project_id=project.id, watermark=watermark
            ),
        ) as trajectory_span:
            trajectory_payload = execute_trajectory_rebuild(
                root_path=root_path,
                config=config,
                store=store,
                project=project,
                incremental_after_event_core_id=watermark,
            )
            trajectory_span.set_counter(
                "workflows_seen", _payload_int(trajectory_payload, "workflows_seen")
            )
        with span(name="memory.semantic.reindex") as semantic_span:
            semantic_payload = execute_semantic_index_rebuild(
                root_path=root_path,
                config=config,
                store=store,
                project=project,
            )
            semantic_span.set_counter(
                "embedded", _payload_int(semantic_payload, "embedded")
            )
            semantic_span.set_counter(
                "skipped_unchanged",
                _payload_int(semantic_payload, "skipped_unchanged"),
            )
        # Experiences distill from the trajectories rebuilt above — same job, run
        # right after so the corpus is fresh.
        with span(name="memory.experience.distill") as experience_span:
            experience_payload = execute_experience_distillation(
                root_path=root_path,
                config=config,
                store=store,
                project=project,
            )
            experience_span.set_counter(
                "experiences_distilled",
                _payload_int(experience_payload, "experiences_distilled"),
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
    store: SqliteEngineeringMemoryStore,
    *,
    root_path: Path,
    config: MemoryConfig,
    project: MemoryProject,
    running_timeout_seconds: int,
    emit_bootstrap_span: bool = True,
) -> ProjectionWorkerResult:
    conn = store.connection
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
            store,
            job_id=claimed.id,
            root_path=root_path,
            config=config,
            project=project,
            stimulus=stimulus,
            emit_bootstrap_span=emit_bootstrap_span,
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
