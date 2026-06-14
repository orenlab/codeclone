# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sqlite3
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from ...config.memory import MemoryConfig, resolve_memory_config
from ...config.observability import resolve_observability_config
from ...observability import (
    bootstrap,
    current_operation_context,
    is_observability_enabled,
    operation,
    shutdown,
)
from ...utils.ci import is_ci_environment
from ..exceptions import MemoryContractError
from ..models import MemoryProject
from ..project import resolve_memory_db_path, resolve_project_identity
from ..sqlite_store import SqliteEngineeringMemoryStore
from .models import ProjectionJobRecord
from .spawn import SpawnWorkerResult, spawn_projection_jobs_worker
from .staleness import (
    compute_projection_stimulus,
    last_applied_stimulus,
    projection_is_stale,
)
from .store import (
    enqueue_projection_job,
    has_live_running_job,
    latest_done_projection_job,
    list_projection_jobs,
    pending_projection_job,
    set_flush_claimed_by,
    try_claim_flush_slot,
    worker_claim_token,
)
from .worker import run_projection_jobs_once

ProjectionRebuildPolicy = Literal["off", "enqueue_when_stale"]


def _require_memory_store_session(
    root_path: Path,
    config: MemoryConfig | None = None,
) -> tuple[Path, MemoryConfig, MemoryProject, SqliteEngineeringMemoryStore]:
    resolved_root = root_path.resolve()
    resolved_config = config or resolve_memory_config(resolved_root)
    db_path = resolve_memory_db_path(resolved_root, resolved_config)
    if not db_path.exists():
        raise MemoryContractError(
            f"Engineering memory database not found: {db_path}. "
            "Run memory init or refresh_from_run first."
        )
    project = resolve_project_identity(resolved_root)
    store = SqliteEngineeringMemoryStore(db_path)
    return resolved_root, resolved_config, project, store


def execute_projection_rebuild_status(
    *,
    root_path: Path,
    config: MemoryConfig | None = None,
    limit: int = 10,
) -> dict[str, object]:
    resolved_root, resolved_config, project, store = _require_memory_store_session(
        root_path,
        config=config,
    )
    conn = store.connection
    try:
        current = compute_projection_stimulus(
            conn=conn,
            project=project,
            root_path=resolved_root,
            config=resolved_config,
        )
        applied = last_applied_stimulus(conn, project_id=project.id)
        active = pending_projection_job(conn, project_id=project.id)
        jobs = list_projection_jobs(conn, project_id=project.id, limit=limit)
    finally:
        store.close()
    return {
        "action": "projection_rebuild_status",
        "policy": resolved_config.projection_rebuild_policy,
        "ci_environment": is_ci_environment(),
        "stale": projection_is_stale(current=current, last_applied=applied),
        "current_stimulus": current,
        "last_applied_stimulus": applied,
        "active_job": _job_payload(active),
        "jobs": [_job_payload(job) for job in jobs],
    }


@dataclass(frozen=True, slots=True)
class _FlushDecision:
    immediate: bool
    deadline_utc: str | None


_FLUSH_WINDOW_MIN_SECONDS = 10
_FLUSH_WINDOW_MAX_SECONDS = 600


def _active_record_delta(
    current: Mapping[str, object], applied: Mapping[str, object] | None
) -> int:
    """Magnitude of the active-record count change since the last applied
    stimulus — the projection-affecting delta that bypasses the coalesce window.
    Audit-only events (no record change) deliberately count as 0 so a burst of
    service events never forces an immediate model load.
    """
    if not applied:
        return 0
    cur = current.get("active_record_count")
    prev = applied.get("active_record_count")
    if not isinstance(cur, int) or not isinstance(prev, int):
        return 0
    return abs(cur - prev)


def _add_seconds_utc(iso_utc: str, seconds: int) -> str:
    try:
        base = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    except ValueError:
        base = datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return (base + timedelta(seconds=max(1, seconds))).isoformat()


def _decide_flush(
    conn: sqlite3.Connection,
    *,
    project: MemoryProject,
    stimulus: Mapping[str, object],
    config: MemoryConfig,
    trigger: str,
    force: bool,
) -> _FlushDecision:
    """Spawn now, or defer behind a fixed last_reindex+window deadline.

    Deferral coalesces bursts of small mcp_finish/auto rebuilds into one model
    load. A disabled window (<=0), an explicit/cli/forced trigger, the first
    index, or a large active-record delta all spawn immediately. The deadline is
    last_reindex+window (fixed, not sliding) so a steady low-rate stream still
    drains every window rather than being deferred forever.
    """
    window = config.projection_rebuild_coalesce_window_seconds
    if window <= 0 or force or trigger in {"explicit", "cli"}:
        return _FlushDecision(immediate=True, deadline_utc=None)
    last_done = latest_done_projection_job(conn, project_id=project.id)
    if last_done is None or not last_done.finished_at_utc:
        return _FlushDecision(immediate=True, deadline_utc=None)
    applied = last_applied_stimulus(conn, project_id=project.id)
    if (
        _active_record_delta(stimulus, applied)
        >= config.projection_rebuild_coalesce_min_delta
    ):
        return _FlushDecision(immediate=True, deadline_utc=None)
    window = max(_FLUSH_WINDOW_MIN_SECONDS, min(_FLUSH_WINDOW_MAX_SECONDS, window))
    deadline = _add_seconds_utc(last_done.finished_at_utc, window)
    return _FlushDecision(immediate=False, deadline_utc=deadline)


def _spawn_with_operation(
    root_path: Path, *, not_before_utc: str | None
) -> SpawnWorkerResult:
    # Op B of the finish->spawn->worker chain (spec §4.3): the spawn decision
    # becomes the active operation, inheriting the finish op (A) as parent +
    # correlation so the env handoff in spawn.py parents the worker (C) under B.
    # Inert when observability is disabled.
    parent = current_operation_context()
    with operation(
        name="memory.projection.spawn",
        surface="memory",
        parent_operation_id=parent[0] if parent else None,
        correlation_id=parent[1] if parent else None,
    ):
        return spawn_projection_jobs_worker(
            root_path=root_path, not_before_utc=not_before_utc
        )


def _run_flush_spawn(
    conn: sqlite3.Connection,
    *,
    project: MemoryProject,
    root_path: Path,
    decision: _FlushDecision,
) -> tuple[bool, int | None, str | None]:
    """Spawn the rebuild worker per the flush decision. Immediate -> spawn now.
    Deferred -> reserve the single flush slot (strict guard) and spawn exactly
    one delayed worker, recording its PID so a concurrent enqueue coalesces
    instead of spawning a second sleeper. Returns (spawned, worker_pid, reason).
    """
    if decision.immediate:
        result = _spawn_with_operation(root_path, not_before_utc=None)
        return result.spawned, result.pid, None
    claimed_job_id = try_claim_flush_slot(
        conn, project_id=project.id, claimant=worker_claim_token()
    )
    if claimed_job_id is None:
        return False, None, "flush_already_scheduled"
    result = _spawn_with_operation(root_path, not_before_utc=decision.deadline_utc)
    if result.spawned:
        set_flush_claimed_by(
            conn, job_id=claimed_job_id, claimant=worker_claim_token(pid=result.pid)
        )
        return True, result.pid, None
    # Spawn failed: release the slot so the next enqueue retries the flush.
    set_flush_claimed_by(conn, job_id=claimed_job_id, claimant=None)
    return False, None, result.reason


def execute_enqueue_projection_rebuild(
    *,
    root_path: Path,
    config: MemoryConfig | None = None,
    trigger: Literal["auto", "explicit", "mcp_finish", "cli"] = "explicit",
    force: bool = False,
    spawn_worker: bool | None = None,
) -> dict[str, object]:
    if is_ci_environment():
        return {
            "action": "enqueue_projection_rebuild",
            "status": "skipped",
            "reason": "ci_environment",
            "job_id": None,
            "spawned": False,
        }
    resolved_config = config or resolve_memory_config(root_path.resolve())
    if resolved_config.projection_rebuild_policy == "off" and not force:
        return {
            "action": "enqueue_projection_rebuild",
            "status": "skipped",
            "reason": "policy_off",
            "job_id": None,
            "spawned": False,
        }
    resolved_root, resolved_config, project, store = _require_memory_store_session(
        root_path,
        config=resolved_config,
    )
    conn = store.connection
    try:
        stimulus = compute_projection_stimulus(
            conn=conn,
            project=project,
            root_path=resolved_root,
            config=resolved_config,
        )
        if (
            not force
            and resolved_config.projection_rebuild_policy == "enqueue_when_stale"
        ):
            applied = last_applied_stimulus(conn, project_id=project.id)
            if not projection_is_stale(current=stimulus, last_applied=applied):
                return {
                    "action": "enqueue_projection_rebuild",
                    "status": "unchanged",
                    "reason": "stimulus_unchanged",
                    "job_id": None,
                    "spawned": False,
                }
        enqueue_result = enqueue_projection_job(
            conn,
            project=project,
            trigger=trigger,
            stimulus=stimulus,
        )
        worker_running = has_live_running_job(
            conn,
            project_id=project.id,
            running_timeout_seconds=(
                resolved_config.projection_rebuild_running_timeout_seconds
            ),
        )
        base_should_spawn = (
            resolved_config.projection_rebuild_spawn_worker
            if spawn_worker is None
            else spawn_worker
        )
        spawned = False
        worker_pid: int | None = None
        spawn_skipped_reason: str | None = None
        flush_deferred = False
        if base_should_spawn and worker_running:
            # A worker is already processing; the pending job it leaves behind is
            # drained by the next spawn when none is running. Avoid the redundant
            # overlapping process.
            spawn_skipped_reason = "worker_already_running"
        elif base_should_spawn:
            decision = _decide_flush(
                conn,
                project=project,
                stimulus=stimulus,
                config=resolved_config,
                trigger=trigger,
                force=force,
            )
            flush_deferred = not decision.immediate
            spawned, worker_pid, spawn_skipped_reason = _run_flush_spawn(
                conn,
                project=project,
                root_path=resolved_root,
                decision=decision,
            )
        return {
            "action": "enqueue_projection_rebuild",
            "status": "enqueued",
            "reason": enqueue_result.reason,
            "job_id": enqueue_result.job_id,
            "coalesced": enqueue_result.coalesced,
            "spawned": spawned,
            "worker_pid": worker_pid,
            "spawn_skipped_reason": spawn_skipped_reason,
            "flush_deferred": flush_deferred,
        }
    finally:
        store.close()


# Defensive ceiling on the trailing-flush sleep so a malformed/runaway deadline
# can never park a worker indefinitely; the real window is clamped far lower at
# the enqueue layer.
_MAX_FLUSH_SLEEP_SECONDS = 3600


def _flush_sleep_seconds(
    not_before_utc: str | None, *, now: datetime | None = None
) -> float:
    """Seconds a delayed flush worker should sleep before draining, derived from
    the ISO-8601 ``not_before_utc`` deadline. 0 when absent/past/malformed;
    capped at ``_MAX_FLUSH_SLEEP_SECONDS``.
    """
    if not not_before_utc:
        return 0.0
    current = now or datetime.now(timezone.utc)
    try:
        deadline = datetime.fromisoformat(not_before_utc.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    remaining = (deadline - current).total_seconds()
    return min(max(0.0, remaining), float(_MAX_FLUSH_SLEEP_SECONDS))


def execute_run_projection_jobs_once(
    *,
    root_path: Path,
    config: MemoryConfig | None = None,
    not_before_utc: str | None = None,
) -> dict[str, object]:
    # Delayed single-shot flush: a coalescing spawn parks the worker until its
    # deadline BEFORE any bootstrap/store-open or model load, so the wait holds
    # no DB lock and is not counted as observed work. Sleeping here (not in the
    # worker body) keeps the bootstrap-before-store-open order below intact.
    delay = _flush_sleep_seconds(not_before_utc)
    if delay > 0:
        time.sleep(delay)
    # Bootstrap observability BEFORE opening the store: open_memory_db attaches
    # the per-span DB-query counter only while observability is enabled, so a
    # store opened pre-bootstrap stays uninstrumented and the worker's whole
    # query stream is invisible to the cockpit. owns_observability guards against
    # a caller that already bootstrapped (e.g. an MCP session).
    resolved_root = root_path.resolve()
    owns_observability = not is_observability_enabled()
    if owns_observability:
        bootstrap(resolve_observability_config(), root=resolved_root)
    try:
        resolved_root, resolved_config, project, store = _require_memory_store_session(
            resolved_root,
            config=config,
        )
        try:
            worker_result = run_projection_jobs_once(
                store,
                root_path=resolved_root,
                config=resolved_config,
                project=project,
                running_timeout_seconds=(
                    resolved_config.projection_rebuild_running_timeout_seconds
                ),
                # A delayed worker slept above; its spawn->job gap is intentional,
                # so suppress the cold-start bootstrap span (see worker.py).
                emit_bootstrap_span=not_before_utc is None,
            )
        finally:
            store.close()
    finally:
        if owns_observability:
            shutdown()
    return {
        "action": "run_projection_jobs_once",
        "status": worker_result.status,
        "job_id": worker_result.job_id,
        "reason": worker_result.reason,
        "trajectory_status": worker_result.trajectory_status,
        "semantic_status": worker_result.semantic_status,
    }


def maybe_auto_enqueue_projection_rebuild(
    *,
    root_path: Path,
    trigger: Literal["auto", "mcp_finish"] = "mcp_finish",
) -> dict[str, object] | None:
    if is_ci_environment():
        return None
    config = resolve_memory_config(root_path)
    if config.projection_rebuild_policy == "off":
        return None
    payload = execute_enqueue_projection_rebuild(
        root_path=root_path,
        config=config,
        trigger=trigger,
        force=False,
        spawn_worker=None,
    )
    if payload.get("status") in {"skipped", "unchanged"}:
        return None
    return payload


def _job_payload(job: ProjectionJobRecord | None) -> dict[str, object] | None:
    if job is None:
        return None
    return {
        "id": job.id,
        "job_kind": job.job_kind,
        "status": job.status,
        "trigger": job.trigger,
        "requested_at_utc": job.requested_at_utc,
        "started_at_utc": job.started_at_utc,
        "finished_at_utc": job.finished_at_utc,
        "claimed_by": job.claimed_by,
        "attempt": job.attempt,
        "error_message": job.error_message,
    }


__all__ = [
    "execute_enqueue_projection_rebuild",
    "execute_projection_rebuild_status",
    "execute_run_projection_jobs_once",
    "is_ci_environment",
    "maybe_auto_enqueue_projection_rebuild",
]
