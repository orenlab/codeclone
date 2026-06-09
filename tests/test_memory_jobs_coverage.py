# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
import sqlite3
import subprocess
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from codeclone.audit.events import repo_root_digest
from codeclone.audit.schema import ensure_schema
from codeclone.audit.validation import DEFAULT_AUDIT_PATH, resolve_audit_path
from codeclone.config.memory import resolve_memory_config
from codeclone.memory.exceptions import MemoryContractError
from codeclone.memory.jobs.spawn import (
    run_projection_jobs_worker_sync,
    spawn_projection_jobs_worker,
)
from codeclone.memory.jobs.staleness import (
    compute_projection_stimulus,
    last_applied_stimulus,
    parse_stimulus_json,
    projection_is_stale,
    stimulus_digest,
)
from codeclone.memory.jobs.store import (
    claim_next_projection_job,
    complete_projection_job,
    enqueue_projection_job,
    latest_done_projection_job,
    list_projection_jobs,
    new_projection_job_id,
    worker_claim_token,
)
from codeclone.memory.jobs.worker import run_projection_job, run_projection_jobs_once
from codeclone.memory.jobs.workflow import (
    execute_enqueue_projection_rebuild,
    execute_projection_rebuild_status,
    execute_run_projection_jobs_once,
    is_ci_environment,
    maybe_auto_enqueue_projection_rebuild,
)
from codeclone.memory.project import resolve_memory_db_path
from codeclone.memory.schema import open_memory_db
from codeclone.report.meta import current_report_timestamp_utc

from .memory_fixtures import cli_memory_repo


def test_spawn_projection_jobs_worker_success(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    mock_proc = MagicMock()
    mock_proc.pid = 4242
    with patch(
        "codeclone.memory.jobs.spawn.subprocess.Popen",
        return_value=mock_proc,
    ) as popen:
        result = spawn_projection_jobs_worker(root_path=root)
    assert result.spawned is True
    assert result.pid == 4242
    popen.assert_called_once()


def test_spawn_projection_jobs_worker_os_error(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    with patch(
        "codeclone.memory.jobs.spawn.subprocess.Popen",
        side_effect=OSError("exec failed"),
    ):
        result = spawn_projection_jobs_worker(root_path=root)
    assert result.spawned is False
    assert result.reason == "exec failed"


def test_run_projection_jobs_worker_sync_invokes_subprocess(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    completed = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="ok", stderr=""
    )
    with patch(
        "codeclone.memory.jobs.spawn.subprocess.run",
        return_value=completed,
    ) as run:
        result = run_projection_jobs_worker_sync(root_path=root)
    assert result.returncode == 0
    run.assert_called_once()


def test_parse_stimulus_json_handles_invalid_and_empty() -> None:
    assert parse_stimulus_json(None) == {}
    assert parse_stimulus_json("{not-json") == {}
    assert parse_stimulus_json("[]") == {}


def test_projection_is_stale_and_stimulus_digest() -> None:
    current = {"repo_root_digest": "a", "event_core_count": 1}
    applied = {"repo_root_digest": "a", "event_core_count": 1}
    assert projection_is_stale(current=current, last_applied=applied) is False
    assert stimulus_digest(current) == stimulus_digest(applied)


def test_compute_projection_stimulus_reads_audit_db(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, project, _store):
        config = resolve_memory_config(root)
        audit_db = resolve_audit_path(root_path=root, value=DEFAULT_AUDIT_PATH)
        audit_db.parent.mkdir(parents=True, exist_ok=True)
        root_digest = repo_root_digest(root.resolve())
        conn_audit = sqlite3.connect(str(audit_db))
        try:
            ensure_schema(conn_audit)
            conn_audit.execute(
                "INSERT INTO controller_events "
                "(event_id, event_type, created_at_utc, repo_root_digest, agent_pid, "
                "workflow_id, event_core_json, event_core_sha256, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "evt-core",
                    "intent.declared",
                    "2026-01-01T00:00:00Z",
                    root_digest,
                    1,
                    "intent:intent-1",
                    "{}",
                    "a" * 64,
                    "active",
                ),
            )
            conn_audit.commit()
        finally:
            conn_audit.close()
        db_path = resolve_memory_db_path(root, config)
        conn = open_memory_db(db_path)
        try:
            stimulus = compute_projection_stimulus(
                conn=conn,
                project=project,
                root_path=root,
                config=config,
                audit_db_path=audit_db,
            )
        finally:
            conn.close()
        assert stimulus["event_core_count"] == 1
        assert stimulus["trajectories_enabled"] is True


def test_last_applied_stimulus_prefers_result_applied_block(tmp_path: Path) -> None:
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
            enqueue = enqueue_projection_job(
                conn,
                project=project,
                trigger="cli",
                stimulus=stimulus,
            )
            complete_projection_job(
                conn,
                job_id=enqueue.job_id,
                status="done",
                result={
                    "applied_stimulus": {"repo_root_digest": "applied-only"},
                    "trajectory": {"status": "skipped"},
                },
            )
            applied = last_applied_stimulus(conn, project_id=project.id)
        finally:
            conn.close()
        assert applied == {"repo_root_digest": "applied-only"}


def test_store_claim_reclaims_stale_running_job(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, project, _store):
        config = resolve_memory_config(root)
        db_path = resolve_memory_db_path(root, config)
        conn = open_memory_db(db_path)
        try:
            job_id = new_projection_job_id()
            now = current_report_timestamp_utc()
            conn.execute(
                "INSERT INTO memory_projection_jobs("
                "id, project_id, job_kind, status, trigger, requested_at_utc, "
                "started_at_utc, claimed_by, attempt, stimulus_json"
                ") VALUES (?, ?, 'projection_bundle', 'running', 'cli', ?, ?, ?, 1, ?)",
                (
                    job_id,
                    project.id,
                    now,
                    "2020-01-01T00:00:00Z",
                    worker_claim_token(),
                    json.dumps({"repo_root_digest": "x"}),
                ),
            )
            conn.commit()
            pending = enqueue_projection_job(
                conn,
                project=project,
                trigger="cli",
                stimulus={"repo_root_digest": "pending"},
            )
            claimed = claim_next_projection_job(
                conn,
                project_id=project.id,
                claimed_by=worker_claim_token(),
                running_timeout_seconds=60,
            )
            row = conn.execute(
                "SELECT status, error_message FROM memory_projection_jobs WHERE id=?",
                (job_id,),
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row[0] == "failed"
        assert row[1] == "stale_running_reclaimed"
        assert claimed is not None
        assert claimed.id == pending.job_id


def test_store_list_and_latest_done_projection_job(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, project, _store):
        config = resolve_memory_config(root)
        db_path = resolve_memory_db_path(root, config)
        conn = open_memory_db(db_path)
        try:
            stimulus = {"repo_root_digest": "digest"}
            first = enqueue_projection_job(
                conn,
                project=project,
                trigger="cli",
                stimulus=stimulus,
            )
            complete_projection_job(
                conn,
                job_id=first.job_id,
                status="done",
                result={"applied_stimulus": stimulus},
            )
            jobs = list_projection_jobs(conn, project_id=project.id, limit=5)
            latest = latest_done_projection_job(conn, project_id=project.id)
        finally:
            conn.close()
        assert len(jobs) == 1
        assert latest is not None
        assert latest.id == first.job_id


def test_run_projection_job_failed_and_skipped() -> None:
    project = MagicMock()
    config = MagicMock()
    conn = MagicMock()
    with (
        patch(
            "codeclone.memory.jobs.worker.execute_trajectory_rebuild",
            return_value={"status": "failed"},
        ),
        patch(
            "codeclone.memory.jobs.worker.execute_semantic_index_rebuild",
            return_value={"status": "ok"},
        ),
        patch(
            "codeclone.memory.jobs.worker.execute_experience_distillation",
            return_value={"status": "ok"},
        ),
    ):
        status, _payload, reason = run_projection_job(
            conn,
            job_id="job-1",
            root_path=Path("/tmp"),
            config=config,
            project=project,
            stimulus={},
        )
    assert status == "failed"
    assert reason == "projection_step_failed"

    with (
        patch(
            "codeclone.memory.jobs.worker.execute_trajectory_rebuild",
            return_value={"status": "skipped"},
        ),
        patch(
            "codeclone.memory.jobs.worker.execute_semantic_index_rebuild",
            return_value={"status": "skipped"},
        ),
        patch(
            "codeclone.memory.jobs.worker.execute_experience_distillation",
            return_value={"status": "skipped"},
        ),
    ):
        status, _payload, reason = run_projection_job(
            conn,
            job_id="job-2",
            root_path=Path("/tmp"),
            config=config,
            project=project,
            stimulus={},
        )
    assert status == "skipped"
    assert reason == "all_steps_skipped"


def test_run_projection_jobs_once_handles_worker_exception(tmp_path: Path) -> None:
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
            enqueue_projection_job(
                conn,
                project=project,
                trigger="cli",
                stimulus=stimulus,
            )
            with patch(
                "codeclone.memory.jobs.worker.run_projection_job",
                side_effect=RuntimeError("boom"),
            ):
                result = run_projection_jobs_once(
                    conn,
                    root_path=root,
                    config=config,
                    project=project,
                    running_timeout_seconds=60,
                )
        finally:
            conn.close()
        assert result.status == "failed"
        assert result.reason == "boom"


def test_execute_projection_rebuild_status_payload(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        payload = execute_projection_rebuild_status(root_path=root, limit=3)
        assert payload["action"] == "projection_rebuild_status"
        assert payload["policy"] == "off"
        assert isinstance(payload["jobs"], list)


def test_execute_enqueue_skips_when_stimulus_unchanged(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, project, _store):
        config = replace(
            resolve_memory_config(root),
            projection_rebuild_policy="enqueue_when_stale",
        )
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
            complete_projection_job(
                conn,
                job_id=first.job_id,
                status="done",
                result={"applied_stimulus": stimulus},
            )
        finally:
            conn.close()
        payload = execute_enqueue_projection_rebuild(
            root_path=root,
            config=config,
            force=False,
            spawn_worker=False,
        )
        assert payload["status"] == "unchanged"
        assert payload["reason"] == "stimulus_unchanged"


def test_execute_enqueue_enqueues_with_spawn_disabled(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        payload = execute_enqueue_projection_rebuild(
            root_path=root,
            force=True,
            spawn_worker=False,
        )
        assert payload["status"] == "enqueued"
        assert payload["spawned"] is False


def test_execute_run_projection_jobs_once_delegates(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        payload = execute_run_projection_jobs_once(root_path=root)
        assert payload["action"] == "run_projection_jobs_once"
        assert payload["status"] == "nothing_to_do"


def test_maybe_auto_enqueue_returns_none_when_policy_off(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        assert maybe_auto_enqueue_projection_rebuild(root_path=root) is None


def test_is_ci_environment_detects_common_keys() -> None:
    assert is_ci_environment({"CI": "true"}) is True
    assert is_ci_environment({"GITHUB_ACTIONS": "true"}) is True
    assert is_ci_environment({}) is False


def test_run_projection_jobs_once_completes_pending_job(tmp_path: Path) -> None:
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
            enqueue_projection_job(
                conn,
                project=project,
                trigger="cli",
                stimulus=stimulus,
            )
            with patch(
                "codeclone.memory.jobs.worker.run_projection_job",
                return_value=(
                    "done",
                    {
                        "trajectory": {"status": "ok"},
                        "semantic": {"status": "skipped"},
                        "applied_stimulus": stimulus,
                    },
                    None,
                ),
            ):
                result = run_projection_jobs_once(
                    conn,
                    root_path=root,
                    config=config,
                    project=project,
                    running_timeout_seconds=60,
                )
        finally:
            conn.close()
        assert result.status == "done"
        assert result.job_id is not None


def test_maybe_auto_enqueue_returns_payload_when_enqueued(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        config = replace(
            resolve_memory_config(root),
            projection_rebuild_policy="enqueue_when_stale",
        )
        with (
            patch(
                "codeclone.memory.jobs.workflow.resolve_memory_config",
                return_value=config,
            ),
            patch(
                "codeclone.memory.jobs.workflow.execute_enqueue_projection_rebuild",
                return_value={
                    "action": "enqueue_projection_rebuild",
                    "status": "enqueued",
                    "job_id": "projjob-test",
                },
            ),
        ):
            payload = maybe_auto_enqueue_projection_rebuild(
                root_path=root,
            )
        assert payload is not None
        assert payload["status"] == "enqueued"


def test_execute_projection_rebuild_status_requires_existing_db(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    with pytest.raises(MemoryContractError, match="database not found"):
        execute_projection_rebuild_status(root_path=root)
