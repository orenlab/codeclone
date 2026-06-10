# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from codeclone.config.memory import MemoryConfig, resolve_memory_config
from codeclone.config.observability import ObservabilityConfig
from codeclone.memory.jobs import compute_projection_stimulus
from codeclone.memory.jobs import workflow as jobs_workflow
from codeclone.memory.jobs.spawn import SpawnWorkerResult
from codeclone.memory.jobs.store import (
    enqueue_projection_job,
    has_live_running_job,
    worker_claim_token,
)
from codeclone.memory.jobs.workflow import execute_enqueue_projection_rebuild
from codeclone.memory.models import MemoryProject
from codeclone.memory.project import resolve_memory_db_path
from codeclone.memory.schema import open_memory_db
from codeclone.observability import (
    bootstrap,
    current_operation_context,
    operation,
    shutdown,
)
from codeclone.observability.store.schema import (
    observability_store_path,
    open_observability_store,
)
from codeclone.report.meta import current_report_timestamp_utc

from .memory_fixtures import cli_memory_repo


def _mark_running(
    conn: sqlite3.Connection,
    job_id: str,
    *,
    claimed_by: str,
    started_at_utc: str,
) -> None:
    conn.execute(
        "UPDATE memory_projection_jobs "
        "SET status='running', claimed_by=?, started_at_utc=? WHERE id=?",
        (claimed_by, started_at_utc, job_id),
    )
    conn.commit()


def _enqueue_one(
    conn: sqlite3.Connection,
    *,
    project: MemoryProject,
    root: Path,
    config: MemoryConfig,
) -> str:
    stimulus = compute_projection_stimulus(
        conn=conn, project=project, root_path=root, config=config
    )
    return enqueue_projection_job(
        conn, project=project, trigger="cli", stimulus=stimulus
    ).job_id


def test_has_live_running_job_false_when_none(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, project, _store):
        config = resolve_memory_config(root)
        conn = open_memory_db(resolve_memory_db_path(root, config))
        try:
            assert (
                has_live_running_job(
                    conn, project_id=project.id, running_timeout_seconds=3600
                )
                is False
            )
        finally:
            conn.close()


def test_has_live_running_job_true_for_live_worker(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, project, _store):
        config = resolve_memory_config(root)
        conn = open_memory_db(resolve_memory_db_path(root, config))
        try:
            job_id = _enqueue_one(conn, project=project, root=root, config=config)
            _mark_running(
                conn,
                job_id,
                claimed_by=worker_claim_token(),
                started_at_utc=current_report_timestamp_utc(),
            )
            assert (
                has_live_running_job(
                    conn, project_id=project.id, running_timeout_seconds=3600
                )
                is True
            )
        finally:
            conn.close()


def test_has_live_running_job_reclaims_timed_out_worker(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, project, _store):
        config = resolve_memory_config(root)
        conn = open_memory_db(resolve_memory_db_path(root, config))
        try:
            job_id = _enqueue_one(conn, project=project, root=root, config=config)
            # Live PID but a long-past start: the timeout makes it stale.
            _mark_running(
                conn,
                job_id,
                claimed_by=worker_claim_token(),
                started_at_utc="2020-01-01T00:00:00Z",
            )
            assert (
                has_live_running_job(
                    conn, project_id=project.id, running_timeout_seconds=1
                )
                is False
            )
            status = conn.execute(
                "SELECT status FROM memory_projection_jobs WHERE id=?", (job_id,)
            ).fetchone()[0]
            assert status == "failed"  # reclaimed
        finally:
            conn.close()


def test_enqueue_skips_spawn_when_worker_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(jobs_workflow, "is_ci_environment", lambda: False)
    with cli_memory_repo(tmp_path, with_draft=False) as (root, project, _store):
        config = resolve_memory_config(root)
        conn = open_memory_db(resolve_memory_db_path(root, config))
        try:
            job_id = _enqueue_one(conn, project=project, root=root, config=config)
            _mark_running(
                conn,
                job_id,
                claimed_by=worker_claim_token(),
                started_at_utc=current_report_timestamp_utc(),
            )
        finally:
            conn.close()

        payload = execute_enqueue_projection_rebuild(
            root_path=root,
            config=config,
            trigger="explicit",
            force=True,
            spawn_worker=True,
        )
        # A worker is already running, so no second process is spawned.
        assert payload["spawned"] is False
        assert payload["spawn_skipped_reason"] == "worker_already_running"
        assert payload["status"] == "enqueued"


def test_enqueue_records_spawn_op_b_under_finish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(jobs_workflow, "is_ci_environment", lambda: False)
    captured: dict[str, tuple[str, str] | None] = {}

    def _fake_spawn(*, root_path: Path) -> SpawnWorkerResult:
        # The spawn handoff reads the active operation here; under op B it must
        # see B (not the finish op A), so the worker links parent=B.
        captured["ctx"] = current_operation_context()
        return SpawnWorkerResult(spawned=True, reason=None, pid=4242)

    monkeypatch.setattr(jobs_workflow, "spawn_projection_jobs_worker", _fake_spawn)
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        config = resolve_memory_config(root)
        bootstrap(ObservabilityConfig(enabled=True), root=root)
        try:
            with operation(
                name="finish_controlled_change",
                surface="mcp",
                correlation_id="A-corr",
            ) as finish_op:
                finish_op_id = finish_op.operation_id
                payload = execute_enqueue_projection_rebuild(
                    root_path=root,
                    config=config,
                    trigger="mcp_finish",
                    force=True,
                    spawn_worker=True,
                )
        finally:
            shutdown()

        assert payload["spawned"] is True
        ctx = captured["ctx"]
        assert ctx is not None
        spawn_op_id, spawn_corr = ctx
        assert spawn_corr == "A-corr"  # B inherits A's correlation
        assert spawn_op_id != finish_op_id  # B is its own operation, not A

        obs = open_observability_store(observability_store_path(root))
        try:
            row = obs.execute(
                "SELECT operation_id, parent_operation_id, correlation_id "
                "FROM platform_operations WHERE name='memory.projection.spawn'"
            ).fetchone()
        finally:
            obs.close()
        # Op B persisted, parented to the finish op (A) with A's correlation.
        assert row is not None
        assert row[0] == spawn_op_id
        assert row[1] == finish_op_id
        assert row[2] == "A-corr"
