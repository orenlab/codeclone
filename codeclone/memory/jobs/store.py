# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os
import socket
import sqlite3
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TypeVar

from ...models import deadline_passed
from ...report.meta import current_report_timestamp_utc
from ...utils.json_io import json_text
from ..models import MemoryProject
from .models import (
    ProjectionJobKind,
    ProjectionJobRecord,
    ProjectionJobStatus,
    ProjectionJobTrigger,
)

PROJECTION_BUNDLE_KIND: ProjectionJobKind = "projection_bundle"
_LiteralT = TypeVar("_LiteralT", bound=str)

_JOB_KIND_VALUES: tuple[ProjectionJobKind, ...] = ("projection_bundle",)
_JOB_STATUS_VALUES: tuple[ProjectionJobStatus, ...] = (
    "pending",
    "running",
    "done",
    "failed",
    "skipped",
)
_JOB_TRIGGER_VALUES: tuple[ProjectionJobTrigger, ...] = (
    "auto",
    "explicit",
    "mcp_finish",
    "cli",
)
_JOB_KINDS: Mapping[str, ProjectionJobKind] = {
    value: value for value in _JOB_KIND_VALUES
}
_JOB_STATUSES: Mapping[str, ProjectionJobStatus] = {
    value: value for value in _JOB_STATUS_VALUES
}
_JOB_TRIGGERS: Mapping[str, ProjectionJobTrigger] = {
    value: value for value in _JOB_TRIGGER_VALUES
}


@dataclass(frozen=True, slots=True)
class EnqueueProjectionJobResult:
    job_id: str
    status: LiteralEnqueueStatus
    coalesced: bool
    reason: str | None = None


LiteralEnqueueStatus = str  # pending | skipped


def worker_claim_token(*, pid: int | None = None) -> str:
    active_pid = pid if pid is not None else os.getpid()
    host = socket.gethostname()
    return f"{active_pid}@{host}"


def _new_job_id() -> str:
    return f"projjob-{uuid.uuid4().hex}"


def _literal_from_row(
    row: sqlite3.Row,
    column: str,
    *,
    field: str,
    allowed: Mapping[str, _LiteralT],
) -> _LiteralT:
    value = row[column]
    if isinstance(value, str):
        literal = allowed.get(value)
        if literal is not None:
            return literal
    raise ValueError(f"Invalid Engineering Memory projection job {field}: {value!r}")


def _row_to_record(row: sqlite3.Row) -> ProjectionJobRecord:
    return ProjectionJobRecord(
        id=str(row["id"]),
        project_id=str(row["project_id"]),
        job_kind=_literal_from_row(
            row,
            "job_kind",
            field="job_kind",
            allowed=_JOB_KINDS,
        ),
        status=_literal_from_row(
            row,
            "status",
            field="status",
            allowed=_JOB_STATUSES,
        ),
        trigger=_literal_from_row(
            row,
            "trigger",
            field="trigger",
            allowed=_JOB_TRIGGERS,
        ),
        requested_at_utc=str(row["requested_at_utc"]),
        started_at_utc=row["started_at_utc"],
        finished_at_utc=row["finished_at_utc"],
        claimed_by=row["claimed_by"],
        attempt=int(row["attempt"]),
        stimulus_json=str(row["stimulus_json"]),
        result_json=row["result_json"],
        error_message=row["error_message"],
        flush_claimed_by=row["flush_claimed_by"],
        lease_token=row["lease_token"],
        lease_renewed_at_utc=row["lease_renewed_at_utc"],
        lease_seconds=(
            int(row["lease_seconds"]) if row["lease_seconds"] is not None else None
        ),
    )


def canonical_stimulus_json(stimulus: Mapping[str, object]) -> str:
    return json_text(stimulus, sort_keys=True)


def _use_row_factory(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row


def enqueue_projection_job(
    conn: sqlite3.Connection,
    *,
    project: MemoryProject,
    trigger: ProjectionJobTrigger,
    stimulus: Mapping[str, object],
    job_kind: ProjectionJobKind = PROJECTION_BUNDLE_KIND,
) -> EnqueueProjectionJobResult:
    _use_row_factory(conn)
    now = current_report_timestamp_utc()
    stimulus_json = canonical_stimulus_json(stimulus)
    pending = conn.execute(
        "SELECT id FROM memory_projection_jobs "
        "WHERE project_id=? AND job_kind=? AND status='pending'",
        (project.id, job_kind),
    ).fetchone()
    if pending is not None:
        job_id = str(pending[0])
        conn.execute(
            "UPDATE memory_projection_jobs "
            "SET trigger=?, requested_at_utc=?, stimulus_json=? "
            "WHERE id=?",
            (trigger, now, stimulus_json, job_id),
        )
        conn.commit()
        return EnqueueProjectionJobResult(
            job_id=job_id,
            status="pending",
            coalesced=True,
            reason="coalesced_pending",
        )
    job_id = _new_job_id()
    conn.execute(
        "INSERT INTO memory_projection_jobs("
        "id, project_id, job_kind, status, trigger, requested_at_utc, "
        "attempt, stimulus_json"
        ") VALUES (?, ?, ?, 'pending', ?, ?, 0, ?)",
        (job_id, project.id, job_kind, trigger, now, stimulus_json),
    )
    conn.commit()
    return EnqueueProjectionJobResult(
        job_id=job_id,
        status="pending",
        coalesced=False,
        reason=None,
    )


def _pid_alive(token: str | None) -> bool:
    """Raw OS-PID liveness probe: True iff ``os.kill(pid, 0)`` succeeds.

    Telemetry-grade only. ``os.kill(pid, 0)`` succeeds on an unreaped zombie
    (the PID entry survives until the parent calls ``wait()``), can hit a PID
    the OS has since reused, and says nothing about whether a live process is
    hung. None of that is authority to keep or reclaim a running projection
    job -- see :func:`_reclaim_stale_running_jobs` and
    :func:`complete_projection_job`, which decide through the lease instead
    and never call this function. The one remaining caller is
    :func:`try_claim_flush_slot`'s delayed-flush single-slot gate, a distinct,
    narrower mechanism (documented there) that this change does not touch.
    """
    if not token:
        return False
    head = token.split("@", 1)[0]
    if not head.isdigit():
        return False
    pid = int(head)
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _new_lease_token() -> str:
    """A fresh, unguessable fencing token for one lease grant.

    Minted on every claim -- a first claim and a reclaim-and-reassign alike --
    so a worker that presents a stale token in :func:`complete_projection_job`
    is provably not the current owner, never merely unlucky in a race.
    """
    return f"lease-{uuid.uuid4().hex}"


def _projection_job_lease_deadline(
    *,
    lease_renewed_at_utc: object,
    lease_seconds: object,
    started_at_utc: object,
    fallback_timeout_seconds: int,
) -> datetime | None:
    """The deadline past which a 'running' claim is reclaimable.

    A row carrying lease fields -- every claim made by
    :func:`claim_next_projection_job` from the 1.9 schema onward -- is judged
    purely by its own lease: last renewal plus the TTL granted at that
    renewal. A claiming worker's OS PID is never read here: a PID can be a
    zombie, be reused by the OS, belong to a live-but-hung worker, or simply
    outlive the process that used to own it, so it is never authority to
    continue holding the job.

    A row still missing lease fields -- possible only for a claim already in
    flight at the moment of the 1.8 -> 1.9 upgrade -- falls back to its own
    ``started_at_utc`` plus the caller's configured timeout: exactly the
    deadline that claim already had before the upgrade, so it is neither
    killed early nor trusted forever by the migration.

    Returns None when no deadline can be read at all (both the lease and the
    legacy anchor are absent, or the anchor timestamp is unparsable); the
    caller decides that case through :func:`codeclone.models.deadline_passed`,
    whose law is that a deadline that cannot be read has already passed --
    collectable, never immortal. The same law and the same function decide
    the canonical run-store lease sweep and the workspace-intent lease.
    """
    anchor: object
    ttl: int
    if lease_renewed_at_utc is not None and isinstance(lease_seconds, int):
        anchor, ttl = lease_renewed_at_utc, lease_seconds
    elif started_at_utc is not None:
        anchor, ttl = started_at_utc, fallback_timeout_seconds
    else:
        return None
    try:
        renewed_at = datetime.fromisoformat(str(anchor).replace("Z", "+00:00"))
    except ValueError:
        return None
    if renewed_at.tzinfo is None:
        renewed_at = renewed_at.replace(tzinfo=timezone.utc)
    return renewed_at + timedelta(seconds=max(1, ttl))


def _reclaim_stale_running_jobs(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    running_timeout_seconds: int,
) -> None:
    """Fail every running job whose lease has expired.

    Authority to keep running is the lease alone, decided by
    :func:`_projection_job_lease_deadline` and
    :func:`codeclone.models.deadline_passed` -- the same one hold-deadline
    law the canonical run-store lease sweep and the workspace-intent lease
    already use. A claiming worker's PID is never consulted: see
    :func:`_pid_alive`'s docstring for why a PID cannot serve as authority
    here. ``lease_token`` is cleared on reclaim so a worker that wakes up
    after losing its lease is fenced out of :func:`complete_projection_job`
    instead of silently overwriting whatever ran next (see that function's
    docstring for the fencing contract).
    """
    rows = conn.execute(
        "SELECT id, started_at_utc, lease_renewed_at_utc, lease_seconds "
        "FROM memory_projection_jobs WHERE project_id=? AND status='running'",
        (project_id,),
    ).fetchall()
    if not rows:
        return
    now = current_report_timestamp_utc()
    now_dt = datetime.now(timezone.utc)
    for row in rows:
        job_id = str(row[0])
        deadline = _projection_job_lease_deadline(
            started_at_utc=row[1],
            lease_renewed_at_utc=row[2],
            lease_seconds=row[3],
            fallback_timeout_seconds=running_timeout_seconds,
        )
        if not deadline_passed(deadline, now_dt):
            continue
        conn.execute(
            "UPDATE memory_projection_jobs "
            "SET status='failed', finished_at_utc=?, error_message=?, "
            "lease_token=NULL "
            "WHERE id=?",
            (now, "stale_running_reclaimed", job_id),
        )


def has_live_running_job(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    running_timeout_seconds: int,
) -> bool:
    """True if a worker is actively processing a job for this project.

    Stale (dead-PID / timed-out) running jobs are reclaimed first, so a crashed
    worker never blocks future spawns. Used by the spawn guard to avoid
    launching a second worker while one is already running.
    """
    _reclaim_stale_running_jobs(
        conn,
        project_id=project_id,
        running_timeout_seconds=running_timeout_seconds,
    )
    conn.commit()
    row = conn.execute(
        "SELECT 1 FROM memory_projection_jobs "
        "WHERE project_id=? AND status='running' LIMIT 1",
        (project_id,),
    ).fetchone()
    return row is not None


def try_claim_flush_slot(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    claimant: str,
    job_kind: ProjectionJobKind = PROJECTION_BUNDLE_KIND,
) -> str | None:
    """Atomically reserve the single delayed-flush worker slot on the pending
    job. Returns the pending job id when THIS caller reserved it (the slot was
    free or held by a dead worker); None when a live flush worker is already
    scheduled or there is no pending job. The BEGIN IMMEDIATE guards against two
    concurrent enqueues each spawning a sleeper for the same job.
    """
    _use_row_factory(conn)
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT id, flush_claimed_by FROM memory_projection_jobs "
            "WHERE project_id=? AND job_kind=? AND status='pending'",
            (project_id, job_kind),
        ).fetchone()
        if row is None or _pid_alive(row["flush_claimed_by"]):
            conn.execute("COMMIT")
            return None
        job_id = str(row["id"])
        conn.execute(
            "UPDATE memory_projection_jobs SET flush_claimed_by=? WHERE id=?",
            (claimant, job_id),
        )
        conn.execute("COMMIT")
        return job_id
    except sqlite3.Error:
        conn.execute("ROLLBACK")
        raise


def set_flush_claimed_by(
    conn: sqlite3.Connection, *, job_id: str, claimant: str | None
) -> None:
    """Overwrite the flush-slot holder for a job (the spawned worker's PID@host
    after a successful spawn, or None to release the slot on spawn failure)."""
    conn.execute(
        "UPDATE memory_projection_jobs SET flush_claimed_by=? WHERE id=?",
        (claimant, job_id),
    )
    conn.commit()


def claim_next_projection_job(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    claimed_by: str,
    running_timeout_seconds: int,
) -> ProjectionJobRecord | None:
    """Claim the next pending job, granting it a fresh lease.

    ``running_timeout_seconds`` is the lease TTL granted to this claim
    (``lease_seconds``), renewed from ``now`` (``lease_renewed_at_utc``); a
    fresh, unguessable ``lease_token`` is minted for every claim, including a
    reclaim-and-reassign, so a superseded worker can be told apart from the
    current owner in :func:`complete_projection_job`. ``claimed_by`` (PID@host)
    is still recorded for diagnostics/receipts, but the OS PID it carries is
    never read back for authority -- see :func:`_pid_alive`'s docstring.
    """
    _use_row_factory(conn)
    conn.execute("BEGIN IMMEDIATE")
    try:
        _reclaim_stale_running_jobs(
            conn,
            project_id=project_id,
            running_timeout_seconds=running_timeout_seconds,
        )
        running = conn.execute(
            "SELECT id FROM memory_projection_jobs "
            "WHERE project_id=? AND status='running' LIMIT 1",
            (project_id,),
        ).fetchone()
        row: sqlite3.Row | None = None
        if running is None:
            row = conn.execute(
                "SELECT * FROM memory_projection_jobs "
                "WHERE project_id=? AND status='pending' "
                "ORDER BY requested_at_utc ASC, id ASC LIMIT 1",
                (project_id,),
            ).fetchone()
        if running is not None or row is None:
            conn.execute("COMMIT")
            return None
        now = current_report_timestamp_utc()
        attempt = int(row["attempt"]) + 1
        lease_token = _new_lease_token()
        conn.execute(
            "UPDATE memory_projection_jobs "
            "SET status='running', started_at_utc=?, claimed_by=?, attempt=?, "
            "lease_token=?, lease_renewed_at_utc=?, lease_seconds=? "
            "WHERE id=?",
            (
                now,
                claimed_by,
                attempt,
                lease_token,
                now,
                running_timeout_seconds,
                row["id"],
            ),
        )
        conn.execute("COMMIT")
    except sqlite3.Error:
        conn.execute("ROLLBACK")
        raise
    updated = conn.execute(
        "SELECT * FROM memory_projection_jobs WHERE id=?",
        (row["id"],),
    ).fetchone()
    assert updated is not None
    return _row_to_record(updated)


def complete_projection_job(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    lease_token: str,
    status: ProjectionJobStatus,
    result: Mapping[str, object] | None = None,
    error_message: str | None = None,
) -> bool:
    """Finalize a claimed job, fencing out a superseded owner.

    Fencing is mandatory, not optional: the write applies only when
    ``lease_token`` still matches the job's current lease. A lease alone
    would be more dangerous than the PID check it replaces, because a
    worker that merely hung (rather than died) can wake up after its lease
    expired and try to publish a result for work that was already
    reassigned -- the fencing token is what forbids that write, even though
    reclaiming the lease is what permitted the reassignment.

    Returns True when this call's token matched and the outcome was written;
    False when the caller has been fenced out (its lease already expired and
    :func:`_reclaim_stale_running_jobs` cleared ``lease_token``, or a new
    owner has since claimed and possibly already completed the job) -- the
    caller no longer holds authority to write an outcome and MUST NOT retry
    the write or treat the in-memory result as applied.
    """
    now = current_report_timestamp_utc()
    result_json = json_text(result, sort_keys=True) if result is not None else None
    cursor = conn.execute(
        "UPDATE memory_projection_jobs "
        "SET status=?, finished_at_utc=?, result_json=?, error_message=?, "
        "lease_token=NULL "
        "WHERE id=? AND lease_token=?",
        (status, now, result_json, error_message, job_id, lease_token),
    )
    conn.commit()
    return cursor.rowcount == 1


def list_projection_jobs(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    limit: int = 20,
) -> tuple[ProjectionJobRecord, ...]:
    _use_row_factory(conn)
    rows = conn.execute(
        "SELECT * FROM memory_projection_jobs "
        "WHERE project_id=? "
        "ORDER BY requested_at_utc DESC, id DESC LIMIT ?",
        (project_id, max(1, int(limit))),
    ).fetchall()
    return tuple(_row_to_record(row) for row in rows)


def _fetch_projection_job(
    conn: sqlite3.Connection,
    sql: str,
    params: tuple[object, ...],
) -> ProjectionJobRecord | None:
    _use_row_factory(conn)
    row = conn.execute(sql, params).fetchone()
    if row is None:
        return None
    return _row_to_record(row)


def latest_done_projection_job(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    job_kind: ProjectionJobKind = PROJECTION_BUNDLE_KIND,
) -> ProjectionJobRecord | None:
    return _fetch_projection_job(
        conn,
        "SELECT * FROM memory_projection_jobs "
        "WHERE project_id=? AND job_kind=? AND status='done' "
        "ORDER BY finished_at_utc DESC, id DESC LIMIT 1",
        (project_id, job_kind),
    )


def pending_projection_job(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    job_kind: ProjectionJobKind = PROJECTION_BUNDLE_KIND,
) -> ProjectionJobRecord | None:
    return _fetch_projection_job(
        conn,
        "SELECT * FROM memory_projection_jobs "
        "WHERE project_id=? AND job_kind=? AND status IN ('pending', 'running') "
        "ORDER BY CASE status WHEN 'running' THEN 0 ELSE 1 END, "
        "requested_at_utc DESC LIMIT 1",
        (project_id, job_kind),
    )


def new_projection_job_id() -> str:
    return _new_job_id()


__all__ = [
    "PROJECTION_BUNDLE_KIND",
    "EnqueueProjectionJobResult",
    "canonical_stimulus_json",
    "claim_next_projection_job",
    "complete_projection_job",
    "enqueue_projection_job",
    "has_live_running_job",
    "latest_done_projection_job",
    "list_projection_jobs",
    "new_projection_job_id",
    "pending_projection_job",
    "set_flush_claimed_by",
    "try_claim_flush_slot",
    "worker_claim_token",
]
