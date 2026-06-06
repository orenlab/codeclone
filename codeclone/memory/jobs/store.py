# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
import os
import socket
import sqlite3
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from ...report.meta import current_report_timestamp_utc
from ..models import MemoryProject
from .models import (
    ProjectionJobKind,
    ProjectionJobRecord,
    ProjectionJobStatus,
    ProjectionJobTrigger,
)

PROJECTION_BUNDLE_KIND: ProjectionJobKind = "projection_bundle"


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


def _row_to_record(row: sqlite3.Row) -> ProjectionJobRecord:
    return ProjectionJobRecord(
        id=str(row["id"]),
        project_id=str(row["project_id"]),
        job_kind=cast(ProjectionJobKind, row["job_kind"]),
        status=cast(ProjectionJobStatus, row["status"]),
        trigger=cast(ProjectionJobTrigger, row["trigger"]),
        requested_at_utc=str(row["requested_at_utc"]),
        started_at_utc=row["started_at_utc"],
        finished_at_utc=row["finished_at_utc"],
        claimed_by=row["claimed_by"],
        attempt=int(row["attempt"]),
        stimulus_json=str(row["stimulus_json"]),
        result_json=row["result_json"],
        error_message=row["error_message"],
    )


def canonical_stimulus_json(stimulus: Mapping[str, object]) -> str:
    return json.dumps(stimulus, sort_keys=True, separators=(",", ":"))


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


def _reclaim_stale_running_jobs(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    running_timeout_seconds: int,
) -> None:
    rows = conn.execute(
        "SELECT id, claimed_by, started_at_utc FROM memory_projection_jobs "
        "WHERE project_id=? AND status='running'",
        (project_id,),
    ).fetchall()
    if not rows:
        return
    now = current_report_timestamp_utc()
    for row in rows:
        job_id = str(row[0])
        claimed_by = row[1]
        started_at = row[2]
        stale = not _pid_alive(claimed_by)
        if not stale and started_at:
            # Timestamp ordering is ISO-8601 UTC; lexicographic compare is safe.
            from datetime import datetime, timedelta, timezone

            try:
                started = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
            except ValueError:
                stale = True
            else:
                deadline = started + timedelta(seconds=max(1, running_timeout_seconds))
                stale = datetime.now(timezone.utc) >= deadline
        if not stale:
            continue
        conn.execute(
            "UPDATE memory_projection_jobs "
            "SET status='failed', finished_at_utc=?, error_message=? "
            "WHERE id=?",
            (now, "stale_running_reclaimed", job_id),
        )


def claim_next_projection_job(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    claimed_by: str,
    running_timeout_seconds: int,
) -> ProjectionJobRecord | None:
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
        conn.execute(
            "UPDATE memory_projection_jobs "
            "SET status='running', started_at_utc=?, claimed_by=?, attempt=? "
            "WHERE id=?",
            (now, claimed_by, attempt, row["id"]),
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
    status: ProjectionJobStatus,
    result: Mapping[str, object] | None = None,
    error_message: str | None = None,
) -> None:
    now = current_report_timestamp_utc()
    result_json = (
        json.dumps(result, sort_keys=True, separators=(",", ":"))
        if result is not None
        else None
    )
    conn.execute(
        "UPDATE memory_projection_jobs "
        "SET status=?, finished_at_utc=?, result_json=?, error_message=? "
        "WHERE id=?",
        (status, now, result_json, error_message, job_id),
    )
    conn.commit()


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
    "latest_done_projection_job",
    "list_projection_jobs",
    "new_projection_job_id",
    "pending_projection_job",
    "worker_claim_token",
]
