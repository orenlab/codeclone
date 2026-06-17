# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.config.memory import resolve_memory_config
from codeclone.memory.jobs import (
    compute_projection_stimulus,
    enqueue_projection_job,
    execute_enqueue_projection_rebuild,
    execute_run_projection_jobs_once,
    is_ci_environment,
    projection_is_stale,
)
from codeclone.memory.jobs.store import pending_projection_job
from codeclone.memory.project import resolve_memory_db_path
from codeclone.memory.schema import open_memory_db
from codeclone.report.meta import current_report_timestamp_utc

from .memory_fixtures import cli_memory_repo


def test_enqueue_coalesces_pending_jobs(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, project, _store):
        config = resolve_memory_config(root)
        db_path = resolve_memory_db_path(root, config)
        conn = open_memory_db(db_path)
        try:
            stimulus = compute_projection_stimulus(
                conn=conn,
                project=project,
                root_path=root,
                config=config,
            )
            first = enqueue_projection_job(
                conn,
                project=project,
                trigger="cli",
                stimulus=stimulus,
            )
            second = enqueue_projection_job(
                conn,
                project=project,
                trigger="explicit",
                stimulus=stimulus,
            )
            pending = pending_projection_job(conn, project_id=project.id)
        finally:
            conn.close()
        assert first.coalesced is False
        assert second.coalesced is True
        assert second.job_id == first.job_id
        assert pending is not None
        assert pending.status == "pending"


def test_projection_is_stale_when_no_done_job(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, project, _store):
        config = resolve_memory_config(root)
        db_path = resolve_memory_db_path(root, config)
        conn = open_memory_db(db_path)
        try:
            current = compute_projection_stimulus(
                conn=conn,
                project=project,
                root_path=root,
                config=config,
            )
        finally:
            conn.close()
        assert projection_is_stale(current=current, last_applied=None) is True


def test_execute_enqueue_skips_in_ci_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        monkeypatch.setenv("CI", "true")
        assert is_ci_environment() is True
        payload = execute_enqueue_projection_rebuild(
            root_path=root,
            force=True,
        )
        assert payload["status"] == "skipped"
        assert payload["reason"] == "ci_environment"


def test_worker_run_once_without_pending_job(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        payload = execute_run_projection_jobs_once(root_path=root)
        assert payload["status"] == "nothing_to_do"


def test_projection_job_pid_alive_and_reclaim_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.memory.jobs.store import _pid_alive, _reclaim_stale_running_jobs

    assert _pid_alive(None) is False
    assert _pid_alive("not-a-pid@host") is False
    assert _pid_alive("0@host") is False
    assert _pid_alive(f"{__import__('os').getpid()}@host") is True

    with cli_memory_repo(tmp_path, with_draft=False) as (root, project, _store):
        config = resolve_memory_config(root)
        db_path = resolve_memory_db_path(root, config)
        conn = open_memory_db(db_path)
        try:
            now = current_report_timestamp_utc()
            conn.execute(
                "INSERT INTO memory_projection_jobs("
                "id, project_id, job_kind, status, trigger, requested_at_utc, "
                "started_at_utc, claimed_by, attempt, stimulus_json"
                ") VALUES (?, ?, 'projection_bundle', 'running', 'cli', ?, ?, ?, 1, ?)",
                (
                    "job-stale",
                    project.id,
                    now,
                    "not-a-timestamp",
                    "999999@dead",
                    "{}",
                ),
            )
            conn.commit()
            _reclaim_stale_running_jobs(
                conn,
                project_id=project.id,
                running_timeout_seconds=1,
            )
            row = conn.execute(
                "SELECT status FROM memory_projection_jobs WHERE id=?",
                ("job-stale",),
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert str(row[0]) == "failed"
