# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from codeclone.audit.events import repo_root_digest
from codeclone.audit.schema import ensure_schema
from codeclone.audit.validation import DEFAULT_AUDIT_PATH, resolve_audit_path
from codeclone.config.memory import resolve_memory_config
from codeclone.memory.exceptions import MemoryContractError
from codeclone.memory.jobs.models import ProjectionJobRecord
from codeclone.memory.jobs.spawn import (
    SpawnWorkerResult,
    _run_once_argv,
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
    pending_projection_job,
    set_flush_claimed_by,
    try_claim_flush_slot,
    worker_claim_token,
)
from codeclone.memory.jobs.worker import run_projection_job, run_projection_jobs_once
from codeclone.memory.jobs.workflow import (
    _active_record_delta,
    _add_seconds_utc,
    _decide_flush,
    _flush_sleep_seconds,
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
    store = MagicMock()
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
            store,
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
            store,
            job_id="job-2",
            root_path=Path("/tmp"),
            config=config,
            project=project,
            stimulus={},
        )
    assert status == "skipped"
    assert reason == "all_steps_skipped"


def test_run_projection_jobs_once_handles_worker_exception(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, project, store):
        config = resolve_memory_config(root)
        stimulus = compute_projection_stimulus(
            conn=store.connection,
            project=project,
            root_path=root,
            config=config,
        )
        enqueue_projection_job(
            store.connection,
            project=project,
            trigger="cli",
            stimulus=stimulus,
        )
        with patch(
            "codeclone.memory.jobs.worker.run_projection_job",
            side_effect=RuntimeError("boom"),
        ):
            result = run_projection_jobs_once(
                store,
                root_path=root,
                config=config,
                project=project,
                running_timeout_seconds=60,
            )
        assert result.status == "failed"
        assert result.reason == "boom"


def test_execute_projection_rebuild_status_payload(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        payload = execute_projection_rebuild_status(root_path=root, limit=3)
        assert payload["action"] == "projection_rebuild_status"
        assert payload["policy"] == "off"
        assert isinstance(payload["jobs"], list)


def test_execute_enqueue_skips_when_stimulus_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "codeclone.memory.jobs.workflow.is_ci_environment",
        lambda: False,
    )
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


def test_execute_enqueue_enqueues_with_spawn_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "codeclone.memory.jobs.workflow.is_ci_environment",
        lambda: False,
    )
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
    with cli_memory_repo(tmp_path, with_draft=False) as (root, project, store):
        config = resolve_memory_config(root)
        stimulus = compute_projection_stimulus(
            conn=store.connection,
            project=project,
            root_path=root,
            config=config,
        )
        enqueue_projection_job(
            store.connection,
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
                store,
                root_path=root,
                config=config,
                project=project,
                running_timeout_seconds=60,
            )
        assert result.status == "done"
        assert result.job_id is not None


def test_maybe_auto_enqueue_returns_payload_when_enqueued(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "codeclone.memory.jobs.workflow.is_ci_environment",
        lambda: False,
    )
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


def test_worker_reason_classification_and_bootstrap_short_circuits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.memory.jobs import worker
    from codeclone.memory.trajectory.models import TRAJECTORY_PROJECTION_VERSION

    conn = sqlite3.connect(":memory:")
    try:
        assert (
            worker._trajectory_reason_kind(
                conn,
                project_id="p",
                watermark=1,
            )
            == "content_changed"
        )

        monkeypatch.setattr(
            "codeclone.memory.jobs.staleness.last_applied_stimulus",
            lambda _conn, *, project_id: None,
        )
        assert (
            worker._trajectory_reason_kind(
                conn,
                project_id="p",
                watermark=None,
            )
            == "first_index"
        )

        monkeypatch.setattr(
            "codeclone.memory.jobs.staleness.last_applied_stimulus",
            lambda _conn, *, project_id: {
                "trajectory_projection_version": f"{TRAJECTORY_PROJECTION_VERSION}-old"
            },
        )
        assert (
            worker._trajectory_reason_kind(
                conn,
                project_id="p",
                watermark=None,
            )
            == "schema_version_changed"
        )
    finally:
        conn.close()

    monkeypatch.setattr(worker, "is_observability_enabled", lambda: False)
    worker._emit_worker_bootstrap_span()
    monkeypatch.setattr(worker, "is_observability_enabled", lambda: True)
    monkeypatch.setattr(worker, "worker_bootstrap_sample", lambda: None)
    worker._emit_worker_bootstrap_span()


def test_workflow_auto_enqueue_and_job_payload_edges(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.memory.jobs import workflow

    monkeypatch.setattr(workflow, "is_ci_environment", lambda: True)
    assert workflow.maybe_auto_enqueue_projection_rebuild(root_path=tmp_path) is None

    monkeypatch.setattr(workflow, "is_ci_environment", lambda: False)
    config = replace(
        resolve_memory_config(tmp_path),
        projection_rebuild_policy="enqueue_when_stale",
    )
    monkeypatch.setattr(workflow, "resolve_memory_config", lambda _root: config)
    monkeypatch.setattr(
        workflow,
        "execute_enqueue_projection_rebuild",
        lambda **_kwargs: {"status": "skipped"},
    )
    assert workflow.maybe_auto_enqueue_projection_rebuild(root_path=tmp_path) is None

    record = ProjectionJobRecord(
        id="job-1",
        project_id="project",
        job_kind="projection_bundle",
        status="pending",
        trigger="cli",
        requested_at_utc="2026-01-01T00:00:00Z",
        started_at_utc=None,
        finished_at_utc=None,
        claimed_by=None,
        attempt=0,
        stimulus_json="{}",
        result_json=None,
        error_message=None,
    )
    payload = workflow._job_payload(record)
    assert payload is not None
    assert payload["id"] == "job-1"


def test_execute_worker_reuses_existing_observability_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.config.observability import ObservabilityConfig
    from codeclone.memory.jobs import workflow
    from codeclone.observability import bootstrap, shutdown

    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        bootstrap(ObservabilityConfig(enabled=True), root=root)
        shutdown_mock = MagicMock()
        monkeypatch.setattr(workflow, "shutdown", shutdown_mock)
        payload = workflow.execute_run_projection_jobs_once(root_path=root)
        assert payload["status"] == "nothing_to_do"
        shutdown_mock.assert_not_called()
        shutdown()


def test_store_reclaims_invalid_timestamp_and_blocks_parallel_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.memory.jobs import store as job_store

    with cli_memory_repo(tmp_path, with_draft=False) as (root, project, _store):
        config = resolve_memory_config(root)
        conn = open_memory_db(resolve_memory_db_path(root, config))
        try:
            conn.execute(
                "INSERT INTO memory_projection_jobs("
                "id, project_id, job_kind, status, trigger, requested_at_utc, "
                "started_at_utc, claimed_by, attempt, stimulus_json"
                ") VALUES (?, ?, 'projection_bundle', 'running', 'cli', ?, ?, ?, 1, ?)",
                (
                    "job-invalid-time",
                    project.id,
                    "2026-01-01T00:00:00Z",
                    "not-a-timestamp",
                    worker_claim_token(),
                    "{}",
                ),
            )
            conn.commit()
            monkeypatch.setattr(job_store, "_pid_alive", lambda _token: True)
            job_store._reclaim_stale_running_jobs(
                conn,
                project_id=project.id,
                running_timeout_seconds=60,
            )
            status = conn.execute(
                "SELECT status FROM memory_projection_jobs WHERE id=?",
                ("job-invalid-time",),
            ).fetchone()
            assert status is not None
            assert status[0] == "failed"

            conn.execute(
                "INSERT INTO memory_projection_jobs("
                "id, project_id, job_kind, status, trigger, requested_at_utc, "
                "started_at_utc, claimed_by, attempt, stimulus_json"
                ") VALUES (?, ?, 'projection_bundle', 'running', 'cli', ?, ?, ?, 1, ?)",
                (
                    "job-live",
                    project.id,
                    "2026-01-01T00:00:00Z",
                    "2999-01-01T00:00:00Z",
                    worker_claim_token(),
                    "{}",
                ),
            )
            conn.commit()
            assert (
                claim_next_projection_job(
                    conn,
                    project_id=project.id,
                    claimed_by=worker_claim_token(),
                    running_timeout_seconds=60,
                )
                is None
            )
        finally:
            conn.close()


def test_run_once_argv_omits_not_before_by_default() -> None:
    argv = _run_once_argv(Path("/repo"))
    assert argv[-2:] == ["--root", "/repo"]
    assert "--not-before" not in argv


def test_run_once_argv_appends_not_before_when_set() -> None:
    argv = _run_once_argv(Path("/repo"), not_before_utc="2026-06-14T00:00:00Z")
    assert argv[-2:] == ["--not-before", "2026-06-14T00:00:00Z"]


def test_spawn_projection_jobs_worker_passes_not_before(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    mock_proc = MagicMock()
    mock_proc.pid = 11
    with patch(
        "codeclone.memory.jobs.spawn.subprocess.Popen",
        return_value=mock_proc,
    ) as popen:
        spawn_projection_jobs_worker(
            root_path=root, not_before_utc="2026-06-14T01:02:03Z"
        )
    argv = popen.call_args.args[0]
    assert argv[-2:] == ["--not-before", "2026-06-14T01:02:03Z"]


def test_flush_sleep_seconds_zero_when_absent_or_past() -> None:
    now = datetime(2026, 6, 14, 12, 0, 0, tzinfo=timezone.utc)
    assert _flush_sleep_seconds(None, now=now) == 0.0
    assert _flush_sleep_seconds("", now=now) == 0.0
    past = (now - timedelta(seconds=30)).isoformat()
    assert _flush_sleep_seconds(past, now=now) == 0.0


def test_flush_sleep_seconds_malformed_is_zero() -> None:
    now = datetime(2026, 6, 14, 12, 0, 0, tzinfo=timezone.utc)
    assert _flush_sleep_seconds("not-a-timestamp", now=now) == 0.0


def test_flush_sleep_seconds_future_returns_remaining() -> None:
    now = datetime(2026, 6, 14, 12, 0, 0, tzinfo=timezone.utc)
    future = (now + timedelta(seconds=45)).isoformat()
    assert _flush_sleep_seconds(future, now=now) == pytest.approx(45.0)


def test_flush_sleep_seconds_naive_deadline_treated_as_utc() -> None:
    now = datetime(2026, 6, 14, 12, 0, 0, tzinfo=timezone.utc)
    naive_future = "2026-06-14T12:00:20"
    assert _flush_sleep_seconds(naive_future, now=now) == pytest.approx(20.0)


def test_flush_sleep_seconds_capped_at_max() -> None:
    now = datetime(2026, 6, 14, 12, 0, 0, tzinfo=timezone.utc)
    far = (now + timedelta(days=10)).isoformat()
    assert _flush_sleep_seconds(far, now=now) == 3600.0


def test_run_projection_job_suppresses_bootstrap_span_when_delayed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODECLONE_OBSERVABILITY_PARENT_OPERATION_ID", "op-parent")
    monkeypatch.setenv("CODECLONE_OBSERVABILITY_CORRELATION_ID", "corr-1")
    emit = MagicMock()
    monkeypatch.setattr(
        "codeclone.memory.jobs.worker._emit_worker_bootstrap_span", emit
    )
    project = MagicMock()
    project.id = "project"
    config = MagicMock()
    store = MagicMock()
    skipped = {"status": "skipped"}
    patches = (
        patch(
            "codeclone.memory.jobs.worker.execute_trajectory_rebuild",
            return_value=skipped,
        ),
        patch(
            "codeclone.memory.jobs.worker.execute_semantic_index_rebuild",
            return_value=skipped,
        ),
        patch(
            "codeclone.memory.jobs.worker.execute_experience_distillation",
            return_value=skipped,
        ),
    )
    with patches[0], patches[1], patches[2]:
        run_projection_job(
            store,
            job_id="job-delayed",
            root_path=Path("/tmp"),
            config=config,
            project=project,
            stimulus={},
            emit_bootstrap_span=False,
        )
    emit.assert_not_called()
    with patches[0], patches[1], patches[2]:
        run_projection_job(
            store,
            job_id="job-eager",
            root_path=Path("/tmp"),
            config=config,
            project=project,
            stimulus={},
            emit_bootstrap_span=True,
        )
    emit.assert_called_once()


def test_execute_run_projection_jobs_once_sleeps_until_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.memory.jobs import workflow

    sleeps: list[float] = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(workflow, "_flush_sleep_seconds", lambda *_a, **_k: 12.5)
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        payload = workflow.execute_run_projection_jobs_once(
            root_path=root, not_before_utc="2026-06-14T12:00:00Z"
        )
    assert sleeps == [12.5]
    assert payload["action"] == "run_projection_jobs_once"


def test_active_record_delta_counts_record_change_only() -> None:
    assert _active_record_delta({"active_record_count": 10}, None) == 0
    assert _active_record_delta({"active_record_count": 10}, {}) == 0
    assert (
        _active_record_delta({"active_record_count": 10}, {"active_record_count": 4})
        == 6
    )
    # Non-int / missing counts (e.g. audit-only stimulus) contribute nothing.
    assert _active_record_delta({"event_core_count": 9}, {"event_core_count": 1}) == 0


def test_add_seconds_utc_advances_and_tolerates_garbage() -> None:
    assert _add_seconds_utc("2026-06-14T00:00:00Z", 60).startswith(
        "2026-06-14T00:01:00"
    )
    # Malformed base falls back to now(); result is a parseable ISO string.
    assert isinstance(_add_seconds_utc("nonsense", 60), str)


def _seed_done_job(
    conn: sqlite3.Connection,
    project_id: str,
    *,
    applied_stimulus: dict[str, object],
    finished_at: str = "2026-06-14T00:00:00Z",
) -> None:
    conn.execute(
        "INSERT INTO memory_projection_jobs("
        "id, project_id, job_kind, status, trigger, requested_at_utc, "
        "finished_at_utc, attempt, stimulus_json, result_json"
        ") VALUES (?, ?, 'projection_bundle', 'done', 'cli', ?, ?, 0, '{}', ?)",
        (
            new_projection_job_id(),
            project_id,
            "2026-06-13T00:00:00Z",
            finished_at,
            json.dumps({"applied_stimulus": applied_stimulus}),
        ),
    )
    conn.commit()


def test_decide_flush_immediate_paths(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, project, store):
        conn = store.connection
        base = resolve_memory_config(root)
        stimulus = compute_projection_stimulus(
            conn=conn, project=project, root_path=root, config=base
        )
        # Window disabled -> immediate.
        disabled = replace(base, projection_rebuild_coalesce_window_seconds=0)
        assert (
            _decide_flush(
                conn,
                project=project,
                stimulus=stimulus,
                config=disabled,
                trigger="mcp_finish",
                force=False,
            ).immediate
            is True
        )
        # Explicit/cli trigger -> immediate even with a window.
        windowed = replace(base, projection_rebuild_coalesce_window_seconds=60)
        assert (
            _decide_flush(
                conn,
                project=project,
                stimulus=stimulus,
                config=windowed,
                trigger="cli",
                force=False,
            ).immediate
            is True
        )
        # force -> immediate.
        assert (
            _decide_flush(
                conn,
                project=project,
                stimulus=stimulus,
                config=windowed,
                trigger="mcp_finish",
                force=True,
            ).immediate
            is True
        )
        # No prior reindex (first index) -> immediate.
        assert (
            _decide_flush(
                conn,
                project=project,
                stimulus=stimulus,
                config=windowed,
                trigger="mcp_finish",
                force=False,
            ).immediate
            is True
        )


def test_decide_flush_defers_below_threshold(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, project, store):
        conn = store.connection
        config = replace(
            resolve_memory_config(root),
            projection_rebuild_coalesce_window_seconds=60,
            projection_rebuild_coalesce_min_delta=25,
        )
        stimulus = compute_projection_stimulus(
            conn=conn, project=project, root_path=root, config=config
        )
        current_count = stimulus["active_record_count"]
        _seed_done_job(
            conn, project.id, applied_stimulus={"active_record_count": current_count}
        )
        decision = _decide_flush(
            conn,
            project=project,
            stimulus=stimulus,
            config=config,
            trigger="mcp_finish",
            force=False,
        )
        assert decision.immediate is False
        assert decision.deadline_utc is not None
        assert decision.deadline_utc.startswith("2026-06-14T00:01:00")


def test_decide_flush_immediate_on_large_delta(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, project, store):
        conn = store.connection
        config = replace(
            resolve_memory_config(root),
            projection_rebuild_coalesce_window_seconds=60,
            projection_rebuild_coalesce_min_delta=25,
        )
        stimulus = compute_projection_stimulus(
            conn=conn, project=project, root_path=root, config=config
        )
        current_count = stimulus["active_record_count"]
        assert isinstance(current_count, int)
        _seed_done_job(
            conn,
            project.id,
            applied_stimulus={"active_record_count": current_count + 50},
        )
        decision = _decide_flush(
            conn,
            project=project,
            stimulus=stimulus,
            config=config,
            trigger="mcp_finish",
            force=False,
        )
        assert decision.immediate is True


def test_try_claim_flush_slot_lifecycle(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, project, store):
        conn = store.connection
        # No pending job yet.
        assert try_claim_flush_slot(conn, project_id=project.id, claimant="1@h") is None
        stimulus = compute_projection_stimulus(
            conn=conn,
            project=project,
            root_path=root,
            config=resolve_memory_config(root),
        )
        enqueue_projection_job(
            conn, project=project, trigger="mcp_finish", stimulus=stimulus
        )
        live = worker_claim_token(pid=os.getpid())
        # Free slot -> reserved by this caller.
        job_id = try_claim_flush_slot(conn, project_id=project.id, claimant=live)
        assert job_id is not None
        reserved = pending_projection_job(conn, project_id=project.id)
        assert reserved is not None and reserved.flush_claimed_by == live
        # Live holder -> second claim is refused (strict single sleeper).
        assert try_claim_flush_slot(conn, project_id=project.id, claimant="2@h") is None
        # Dead holder -> reclaimable.
        set_flush_claimed_by(conn, job_id=job_id, claimant="999999@h")
        assert (
            try_claim_flush_slot(conn, project_id=project.id, claimant=live) == job_id
        )
        # Release.
        set_flush_claimed_by(conn, job_id=job_id, claimant=None)
        released = pending_projection_job(conn, project_id=project.id)
        assert released is not None and released.flush_claimed_by is None


def test_enqueue_defers_and_guards_second_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "codeclone.memory.jobs.workflow.is_ci_environment", lambda: False
    )
    captured: list[str | None] = []

    def _fake_spawn(
        *, root_path: Path, not_before_utc: str | None = None
    ) -> SpawnWorkerResult:
        captured.append(not_before_utc)
        return SpawnWorkerResult(spawned=True, reason=None, pid=os.getpid())

    monkeypatch.setattr(
        "codeclone.memory.jobs.workflow.spawn_projection_jobs_worker", _fake_spawn
    )
    with cli_memory_repo(tmp_path, with_draft=False) as (root, project, store):
        config = replace(
            resolve_memory_config(root),
            projection_rebuild_policy="enqueue_when_stale",
            projection_rebuild_coalesce_window_seconds=60,
            projection_rebuild_coalesce_min_delta=25,
        )
        conn = store.connection
        stimulus = compute_projection_stimulus(
            conn=conn, project=project, root_path=root, config=config
        )
        # Prior reindex: stale (different digest) but no record delta -> deferred.
        _seed_done_job(
            conn,
            project.id,
            applied_stimulus={
                "repo_root_digest": "stale-digest",
                "active_record_count": stimulus["active_record_count"],
            },
        )
        store.close()

        first = execute_enqueue_projection_rebuild(
            root_path=root, config=config, trigger="mcp_finish", spawn_worker=True
        )
        assert first["status"] == "enqueued"
        assert first["flush_deferred"] is True
        assert first["spawned"] is True
        # The delayed worker was spawned with a future flush deadline.
        assert captured[0] is not None

        second = execute_enqueue_projection_rebuild(
            root_path=root, config=config, trigger="mcp_finish", spawn_worker=True
        )
        assert second["flush_deferred"] is True
        assert second["spawned"] is False
        assert second["spawn_skipped_reason"] == "flush_already_scheduled"
        assert second["coalesced"] is True


def test_projection_job_store_rolls_back_on_sqlite_errors(
    tmp_path: Path,
) -> None:
    from codeclone.memory.schema import ensure_schema as ensure_memory_schema

    conn = sqlite3.connect(":memory:")
    ensure_memory_schema(conn)

    class _BrokenConn:
        def __init__(self, inner: sqlite3.Connection) -> None:
            self._inner = inner
            self._fail_begin = True

        def execute(
            self, query: str, params: tuple[object, ...] = ()
        ) -> sqlite3.Cursor:
            if self._fail_begin and query.strip().upper().startswith("BEGIN"):
                self._fail_begin = False
                raise sqlite3.Error("begin failed")
            return self._inner.execute(query, params)

        def commit(self) -> None:
            self._inner.commit()

        def rollback(self) -> None:
            self._inner.rollback()

        def close(self) -> None:
            self._inner.close()

    broken = _BrokenConn(conn)
    with pytest.raises(sqlite3.Error, match="begin failed"):
        try_claim_flush_slot(broken, project_id="project", claimant="1@h")  # type: ignore[arg-type]

    broken2 = _BrokenConn(conn)
    with pytest.raises(sqlite3.Error, match="begin failed"):
        claim_next_projection_job(
            broken2,  # type: ignore[arg-type]
            project_id="project",
            claimed_by="1@h",
            running_timeout_seconds=60,
        )


def test_claim_next_projection_job_rolls_back_on_update_failure(
    tmp_path: Path,
) -> None:
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

            class _BrokenConn:
                def __init__(self, inner: sqlite3.Connection) -> None:
                    self._inner = inner
                    self._fail_update = True

                def execute(
                    self, query: str, params: tuple[object, ...] = ()
                ) -> sqlite3.Cursor:
                    if self._fail_update and query.strip().upper().startswith("UPDATE"):
                        self._fail_update = False
                        raise sqlite3.Error("update failed")
                    return self._inner.execute(query, params)

                def commit(self) -> None:
                    self._inner.commit()

                def rollback(self) -> None:
                    self._inner.rollback()

                def close(self) -> None:
                    self._inner.close()

            broken = _BrokenConn(conn)
            with pytest.raises(sqlite3.Error, match="update failed"):
                claim_next_projection_job(
                    broken,  # type: ignore[arg-type]
                    project_id=project.id,
                    claimed_by="1@h",
                    running_timeout_seconds=60,
                )
        finally:
            conn.close()


def test_try_claim_flush_slot_rolls_back_on_update_failure(
    tmp_path: Path,
) -> None:
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
            job_id = try_claim_flush_slot(conn, project_id=project.id, claimant="1@h")
            assert job_id is not None
            set_flush_claimed_by(conn, job_id=job_id, claimant=None)

            class _BrokenConn:
                def __init__(self, inner: sqlite3.Connection) -> None:
                    self._inner = inner
                    self._fail_update = True

                def execute(
                    self,
                    query: str,
                    params: tuple[object, ...] | dict[str, object] = (),
                ) -> sqlite3.Cursor:
                    if self._fail_update and "UPDATE memory_projection_jobs" in query:
                        self._fail_update = False
                        raise sqlite3.Error("flush update failed")
                    return self._inner.execute(query, params)

                def commit(self) -> None:
                    self._inner.commit()

                def rollback(self) -> None:
                    self._inner.rollback()

                def close(self) -> None:
                    self._inner.close()

            broken = _BrokenConn(conn)
            with pytest.raises(sqlite3.Error, match="flush update failed"):
                try_claim_flush_slot(
                    broken,  # type: ignore[arg-type]
                    project_id=project.id,
                    claimant="2@h",
                )
        finally:
            conn.close()


def test_run_flush_spawn_releases_slot_when_spawn_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.memory.jobs.spawn import SpawnWorkerResult
    from codeclone.memory.jobs.workflow import _FlushDecision, _run_flush_spawn

    with cli_memory_repo(tmp_path, with_draft=False) as (root, project, store):
        config = resolve_memory_config(root)
        conn = store.connection
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
        monkeypatch.setattr(
            "codeclone.memory.jobs.workflow.spawn_projection_jobs_worker",
            lambda **_kwargs: SpawnWorkerResult(
                spawned=False,
                reason="spawn denied",
                pid=None,
            ),
        )
        spawned, pid, reason = _run_flush_spawn(
            conn,
            project=project,
            root_path=root,
            decision=_FlushDecision(
                immediate=False,
                deadline_utc="2099-01-01T00:00:00+00:00",
            ),
        )
        assert spawned is False
        assert pid is None
        assert reason == "spawn denied"
        row = conn.execute(
            "SELECT flush_claimed_by FROM memory_projection_jobs LIMIT 1"
        ).fetchone()
        assert row is not None
        assert row[0] is None
