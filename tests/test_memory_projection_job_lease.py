# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Acceptance suite for the projection-job lease + fencing redesign.

Replaces ``_pid_alive`` as reclaim authority for ``memory_projection_jobs``
with a renew-or-expire lease and a fencing token -- the same one
hold-deadline law already used by the canonical run-store lease
(``codeclone.canonical.store.acquire_run_lease``) and the workspace-intent
lease (``codeclone.workspace_intent.lifecycle.is_lease_expired``), both of
which decide through ``codeclone.models.deadline_passed``.

Each ``test_case*`` function below pins exactly one line of the maintainer's
acceptance table:

    fresh lease + live worker                        -> not reclaimed
    expired lease + absent PID                       -> reclaimed
    expired lease + zombie PID                       -> reclaimed
    expired lease + technically live PID             -> reclaimed
    reclaimed job + old worker later attempts finish -> fenced out
    new owner                                        -> can finish normally
    process crash between last renewal and expiry    -> eventual reclaim
    recovery/restart                                 -> persisted lease
                                                         semantics survive

``test_reclaim_never_consults_pid_alive`` is the direct proof for deliverable
#5: reclamation authority no longer touches the OS PID at all, positive or
negative. ``test_zombie_pid_is_a_positive_control_for_pid_alive`` is the
Probe Validity Law's positive control -- it proves the forked zombie is
genuinely observed as "alive" by the kernel probe the old code trusted,
before that zombie is used as a distinguishing case in test_case3.

The end-to-end proof that ``run_projection_jobs_once`` (worker.py) surfaces a
fenced-out completion lives in test_memory_jobs_coverage.py instead of here,
alongside its sibling worker-loop tests: it is the one scenario in this
defect that genuinely needs a real ``MemoryConfig``
(``codeclone.config.memory``), and that module is already an established,
allowlisted r2p->r2 edge for that file (not for this one) under the phase39s
architecture-boundary ratchet's shrink-only policy -- see
test_worker_run_once_surfaces_fenced_out_when_lease_lost_mid_job there.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import time
from contextlib import suppress
from pathlib import Path
from unittest.mock import patch

import pytest

from codeclone.memory.jobs.models import ProjectionJobRecord
from codeclone.memory.jobs.store import (
    _pid_alive,
    _reclaim_stale_running_jobs,
    claim_next_projection_job,
    complete_projection_job,
    enqueue_projection_job,
    worker_claim_token,
)
from codeclone.memory.models import MemoryProject
from codeclone.memory.schema import open_memory_db

from .memory_fixtures import cli_memory_repo

pytestmark = pytest.mark.skipif(
    not hasattr(os, "fork"), reason="zombie fixture needs os.fork (POSIX only)"
)

_LONG_PAST_UTC = "2020-01-01T00:00:00Z"
_ABSENT_PID_TOKEN = "999999999@dead"  # a fake claim token, not a secret
_STIMULUS = {"repo_root_digest": "lease-test"}


# --- zombie fixture ---------------------------------------------------------


def _spawn_zombie() -> int:
    """Fork a child that exits immediately without being reaped.

    The child does nothing but call ``os._exit(0)`` -- no imports, no sqlite,
    no pytest machinery, no shared file descriptors touched -- so it cannot
    corrupt the parent's state. Not reaping it (no ``waitpid``) leaves it a
    real unreaped zombie (``ps`` state ``Z``) until :func:`_reap_zombie` runs.
    """
    pid = os.fork()
    if pid == 0:
        os._exit(0)
    return pid


def _reap_zombie(pid: int) -> None:
    with suppress(ChildProcessError):
        os.waitpid(pid, 0)


def _wait_for_zombie_state(pid: int, *, timeout_s: float = 2.0) -> str:
    """Poll ``ps`` until the forked child is observed in state Z, or return
    whatever state was last seen when the timeout expires."""
    deadline = time.monotonic() + timeout_s
    state = ""
    while time.monotonic() < deadline:
        proc = subprocess.run(
            ["ps", "-o", "state=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
        )
        state = proc.stdout.strip()
        if state.startswith("Z"):
            return state
        time.sleep(0.02)
    return state


# --- shared test helpers -----------------------------------------------------


def _claim_one(
    conn: sqlite3.Connection,
    *,
    project: MemoryProject,
    claimed_by: str,
    running_timeout_seconds: int = 60,
) -> ProjectionJobRecord:
    """Enqueue and claim one job. The stimulus content is irrelevant to lease
    and fencing behaviour, so a literal placeholder stands in for a real
    ``compute_projection_stimulus`` computation (the same shortcut several
    existing store-level tests already take, e.g.
    test_store_claim_reclaims_stale_running_job).
    """
    enqueue_projection_job(conn, project=project, trigger="cli", stimulus=_STIMULUS)
    claimed = claim_next_projection_job(
        conn,
        project_id=project.id,
        claimed_by=claimed_by,
        running_timeout_seconds=running_timeout_seconds,
    )
    assert claimed is not None
    assert claimed.lease_token is not None
    return claimed


def _backdate_lease(
    conn: sqlite3.Connection, job_id: str, *, renewed_at_utc: str = _LONG_PAST_UTC
) -> None:
    conn.execute(
        "UPDATE memory_projection_jobs SET lease_renewed_at_utc=? WHERE id=?",
        (renewed_at_utc, job_id),
    )
    conn.commit()


def _status_of(conn: sqlite3.Connection, job_id: str) -> tuple[str, str | None]:
    row = conn.execute(
        "SELECT status, error_message FROM memory_projection_jobs WHERE id=?",
        (job_id,),
    ).fetchone()
    assert row is not None
    return str(row[0]), (str(row[1]) if row[1] is not None else None)


# --- Probe Validity: positive control ---------------------------------------


def test_zombie_pid_is_a_positive_control_for_pid_alive() -> None:
    """Positive control (Probe Validity Law): confirm the forked child is
    genuinely observed by the kernel as a zombie, and that _pid_alive --
    the exact OS-level check the old code trusted -- reports it alive. If
    this control ever failed, test_case3 below would be measuring nothing.
    """
    pid = _spawn_zombie()
    try:
        state = _wait_for_zombie_state(pid)
        if not state.startswith("Z"):
            pytest.skip(
                f"could not observe a zombie state for pid {pid} on this "
                f"platform (last observed state: {state!r}); test_case3 is "
                "inconclusive, not passing, without this control"
            )
        assert _pid_alive(f"{pid}@host") is True
    finally:
        _reap_zombie(pid)


# --- the eight acceptance cases ---------------------------------------------


def test_case1_fresh_lease_with_live_worker_is_not_reclaimed(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (_root, project, store):
        conn = store.connection
        claimed = _claim_one(
            conn,
            project=project,
            claimed_by=worker_claim_token(),
            running_timeout_seconds=3600,
        )
        _reclaim_stale_running_jobs(
            conn, project_id=project.id, running_timeout_seconds=3600
        )
        status, _ = _status_of(conn, claimed.id)
    assert status == "running"


def test_case2_expired_lease_with_absent_pid_is_reclaimed(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (_root, project, store):
        conn = store.connection
        # The claimant's absence is declared, not inherited from the pid
        # space (nothing reserves 999999999) -- moot anyway, since reclaim
        # below never asks the OS about this token either way.
        claimed = _claim_one(conn, project=project, claimed_by=_ABSENT_PID_TOKEN)
        _backdate_lease(conn, claimed.id)
        _reclaim_stale_running_jobs(
            conn, project_id=project.id, running_timeout_seconds=60
        )
        status, error = _status_of(conn, claimed.id)
    assert status == "failed"
    assert error == "stale_running_reclaimed"


def test_case3_expired_lease_with_zombie_pid_is_reclaimed(tmp_path: Path) -> None:
    """The measured defect, closed: os.kill(pid, 0) succeeds on an unreaped
    zombie, so the OLD _pid_alive-driven reclaim trusted it as live and
    would not reclaim until the full running_timeout_seconds elapsed from
    started_at_utc. The NEW reclaim decides off the lease alone and never
    asks the OS about the PID -- expired is expired, zombie or not.
    """
    pid = _spawn_zombie()
    try:
        state = _wait_for_zombie_state(pid)
        if not state.startswith("Z"):
            pytest.skip(
                f"could not observe a zombie state for pid {pid} on this "
                f"platform (last observed state: {state!r})"
            )
        with cli_memory_repo(tmp_path, with_draft=False) as (_root, project, store):
            conn = store.connection
            claimed = _claim_one(
                conn, project=project, claimed_by=worker_claim_token(pid=pid)
            )
            _backdate_lease(conn, claimed.id)
            _reclaim_stale_running_jobs(
                conn, project_id=project.id, running_timeout_seconds=60
            )
            status, error = _status_of(conn, claimed.id)
        assert status == "failed"
        assert error == "stale_running_reclaimed"
    finally:
        _reap_zombie(pid)


def test_case4_expired_lease_with_technically_live_pid_is_reclaimed(
    tmp_path: Path,
) -> None:
    """Even a fully healthy, definitely-alive process (the test's own PID)
    is reclaimed once its lease expires -- the property that distinguishes a
    lease from a liveness check: authority is time-bound, not aliveness-bound.
    """
    with cli_memory_repo(tmp_path, with_draft=False) as (_root, project, store):
        conn = store.connection
        claimed = _claim_one(
            conn,
            project=project,
            claimed_by=worker_claim_token(),  # this test process's own PID
        )
        assert _pid_alive(claimed.claimed_by) is True  # genuinely alive
        _backdate_lease(conn, claimed.id)
        _reclaim_stale_running_jobs(
            conn, project_id=project.id, running_timeout_seconds=60
        )
        status, error = _status_of(conn, claimed.id)
    assert status == "failed"
    assert error == "stale_running_reclaimed"


def test_case5_reclaimed_job_old_worker_finish_is_fenced_out(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (_root, project, store):
        conn = store.connection
        claimed = _claim_one(conn, project=project, claimed_by=worker_claim_token())
        old_token = claimed.lease_token
        assert old_token is not None
        _backdate_lease(conn, claimed.id)
        _reclaim_stale_running_jobs(
            conn, project_id=project.id, running_timeout_seconds=60
        )
        # The old worker, unaware it lost the lease, now tries to finish.
        completed = complete_projection_job(
            conn,
            job_id=claimed.id,
            lease_token=old_token,
            status="done",
            result={"trajectory": {"status": "done"}},
        )
        status, error = _status_of(conn, claimed.id)
    assert completed is False
    # The reclaimed outcome stands; the fenced-out write did not apply.
    assert status == "failed"
    assert error == "stale_running_reclaimed"


def test_case6_new_owner_can_finish_normally(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (_root, project, store):
        conn = store.connection
        old = _claim_one(conn, project=project, claimed_by=worker_claim_token())
        _backdate_lease(conn, old.id)
        _reclaim_stale_running_jobs(
            conn, project_id=project.id, running_timeout_seconds=60
        )
        assert _status_of(conn, old.id)[0] == "failed"

        # A new job is enqueued and claimed by a new owner.
        new_owner = _claim_one(conn, project=project, claimed_by=worker_claim_token())
        assert new_owner.id != old.id
        new_token = new_owner.lease_token
        assert new_token is not None
        assert new_token != old.lease_token
        completed = complete_projection_job(
            conn,
            job_id=new_owner.id,
            lease_token=new_token,
            status="done",
            result={"trajectory": {"status": "done"}},
        )
        status, _ = _status_of(conn, new_owner.id)
    assert completed is True
    assert status == "done"


def test_case7_process_crash_between_renewal_and_expiry_is_eventually_reclaimed(
    tmp_path: Path,
) -> None:
    """Real elapsed wall-clock time (not a backdated timestamp) between the
    one renewal a claim gets (at claim time) and its lease's expiry -- a
    'crash' is simply the absence of any further renewal in that window.
    """
    with cli_memory_repo(tmp_path, with_draft=False) as (_root, project, store):
        conn = store.connection
        claimed = _claim_one(
            conn,
            project=project,
            claimed_by=worker_claim_token(),
            running_timeout_seconds=1,
        )
        status, _ = _status_of(conn, claimed.id)
        assert status == "running"  # not yet expired
        time.sleep(1.2)  # the "crash": no renewal happens in this window
        _reclaim_stale_running_jobs(
            conn, project_id=project.id, running_timeout_seconds=1
        )
        status, error = _status_of(conn, claimed.id)
    assert status == "failed"
    assert error == "stale_running_reclaimed"


def test_case8_recovery_restart_lease_semantics_survive(tmp_path: Path) -> None:
    """Lease + fencing state lives in the durable row, not in any
    in-memory process state -- closing and reopening the connection (a
    stand-in for a process restart) must not change a single decision.
    """
    with cli_memory_repo(tmp_path, with_draft=False) as (_root, project, store):
        conn1 = store.connection
        db_path = store.db_path
        claimed = _claim_one(conn1, project=project, claimed_by=worker_claim_token())
        original_token = claimed.lease_token
        assert original_token is not None
        store.close()  # simulate the claiming process exiting ("restart")

        conn2 = open_memory_db(db_path)
        try:
            row = conn2.execute(
                "SELECT lease_token, lease_renewed_at_utc, lease_seconds, status "
                "FROM memory_projection_jobs WHERE id=?",
                (claimed.id,),
            ).fetchone()
            assert row is not None
            assert row[0] == original_token
            assert row[1] is not None
            assert row[2] == 60
            assert row[3] == "running"

            _backdate_lease(conn2, claimed.id)
            _reclaim_stale_running_jobs(
                conn2, project_id=project.id, running_timeout_seconds=60
            )
            status, error = _status_of(conn2, claimed.id)
            assert status == "failed"
            assert error == "stale_running_reclaimed"

            # The original worker's token, remembered only in its own
            # (now-gone) process memory from before the "restart", is fenced.
            completed = complete_projection_job(
                conn2,
                job_id=claimed.id,
                lease_token=original_token,
                status="done",
            )
        finally:
            conn2.close()
    assert completed is False


# --- direct proof: PID is no longer reclamation authority --------------------


def test_reclaim_never_consults_pid_alive(tmp_path: Path) -> None:
    """Deliverable #5's direct proof: poison _pid_alive to blow up on any
    call, then show every reclaim decision -- expired-lease reclaim AND
    fresh-lease retention alike -- is unaffected. If _reclaim_stale_running_jobs
    ever consulted the PID again, this test would error, not merely fail.
    """

    def _poisoned(_token: str | None) -> bool:
        raise AssertionError(
            "_pid_alive must not be called by _reclaim_stale_running_jobs"
        )

    with cli_memory_repo(tmp_path, with_draft=False) as (_root, project, store):
        conn = store.connection
        fresh = _claim_one(
            conn,
            project=project,
            claimed_by=worker_claim_token(),
            running_timeout_seconds=3600,
        )
        # A second project-scoped job can't be enqueued while one is
        # running, so directly insert a second, independently expired
        # 'running' row to exercise the reclaim path for BOTH outcomes in
        # one poisoned pass.
        conn.execute(
            "INSERT INTO memory_projection_jobs("
            "id, project_id, job_kind, status, trigger, requested_at_utc, "
            "started_at_utc, claimed_by, attempt, stimulus_json, "
            "lease_token, lease_renewed_at_utc, lease_seconds"
            ") VALUES ('job-expired', ?, 'projection_bundle', 'running', "
            "'cli', ?, ?, ?, 1, '{}', 'lease-expired-probe', ?, 60)",
            (
                project.id,
                _LONG_PAST_UTC,
                _LONG_PAST_UTC,
                _ABSENT_PID_TOKEN,
                _LONG_PAST_UTC,
            ),
        )
        conn.commit()

        with patch("codeclone.memory.jobs.store._pid_alive", side_effect=_poisoned):
            _reclaim_stale_running_jobs(
                conn, project_id=project.id, running_timeout_seconds=3600
            )

        fresh_status, _ = _status_of(conn, fresh.id)
        expired_status, expired_error = _status_of(conn, "job-expired")
    assert fresh_status == "running"
    assert expired_status == "failed"
    assert expired_error == "stale_running_reclaimed"
