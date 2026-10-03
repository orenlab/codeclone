# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The projection worker never runs code from the repository it analyses.

The worker is ``python -m codeclone.main memory jobs run-once --root <repo>``.
``python -m`` puts the working directory first on ``sys.path``, and the worker
used to start with the analysed repository as its working directory, so a
module in that repository named like a worker dependency was imported and
executed by the worker. A repository can switch the rebuild on by itself
through its own ``pyproject.toml``.

Each test drives the real spawn owner against a temporary repository whose
shadow module only appends to a marker file (``projection_worker_fixtures``).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import codeclone.memory.jobs.spawn as spawn
from codeclone.memory.jobs import (
    execute_enqueue_projection_rebuild,
    execute_projection_rebuild_status,
    maybe_auto_enqueue_projection_rebuild,
)

from .projection_worker_fixtures import (
    HostileRepo,
    databases_outside,
    hostile_repo,
    only_worker,
    recorded_spawns,
    sandbox_environment,
)

_WORKER_TIMEOUT_SECONDS = 120


@pytest.fixture(autouse=True)
def opened_databases(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[list[str]]:
    opened = sandbox_environment(monkeypatch, tmp_path)
    yield opened
    assert databases_outside(opened, tmp_path) == []


def _enqueue_pending_job(repo: HostileRepo) -> str:
    payload = execute_enqueue_projection_rebuild(
        root_path=repo.root, trigger="cli", force=True, spawn_worker=False
    )
    job_id = payload["job_id"]
    assert isinstance(job_id, str)
    return job_id


def _job(repo: HostileRepo, job_id: str) -> dict[str, Any]:
    jobs = execute_projection_rebuild_status(root_path=repo.root)["jobs"]
    assert isinstance(jobs, list)
    (job,) = [job for job in jobs if job["id"] == job_id]
    return dict(job)


def _unprotected_start(repo: HostileRepo) -> subprocess.CompletedProcess[str]:
    """The worker's interpreter started the way it used to be: ``-m`` with the
    analysed repository as working directory and no isolation switch."""

    return subprocess.run(
        [sys.executable, "-m", "codeclone.main", "--version"],
        cwd=repo.root,
        capture_output=True,
        text=True,
        check=False,
        timeout=_WORKER_TIMEOUT_SECONDS,
    )


def test_sync_worker_does_not_import_a_module_of_the_analysed_repository(
    tmp_path: Path, opened_databases: list[str]
) -> None:
    with hostile_repo(tmp_path) as repo:
        job_id = _enqueue_pending_job(repo)

        completed = spawn.run_projection_jobs_worker_sync(root_path=repo.root)

        assert repo.shadow_runs() == []
        payload = json.loads(completed.stdout)
        assert (payload["job_id"], payload["status"]) == (job_id, "done")
        # Positive control: the same shadow, reached through a start that keeps
        # the repository on the import path, does run -- so the probe can see it.
        control = _unprotected_start(repo)
        assert control.returncode == 0
        assert len(repo.shadow_runs()) == 1
    assert any(str(repo.root) in database for database in opened_databases)


def test_spawned_worker_does_not_import_a_module_of_the_analysed_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with hostile_repo(tmp_path) as repo:
        job_id = _enqueue_pending_job(repo)

        with recorded_spawns(monkeypatch) as spawned:
            result = spawn.spawn_projection_jobs_worker(root_path=repo.root)
        worker = only_worker(spawned)
        worker.process.wait(timeout=_WORKER_TIMEOUT_SECONDS)

        assert repo.shadow_runs() == []
        job = _job(repo, job_id)
        assert (result.pid, job["status"]) == (worker.process.pid, "done")
        assert job["claimed_by"].startswith(f"{worker.process.pid}@")


def test_finish_hook_worker_does_not_import_a_module_of_the_analysed_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with hostile_repo(tmp_path) as repo:
        with recorded_spawns(monkeypatch) as spawned:
            payload = maybe_auto_enqueue_projection_rebuild(
                root_path=repo.root, trigger="mcp_finish"
            )
        assert payload is not None
        worker = only_worker(spawned)
        worker.process.wait(timeout=_WORKER_TIMEOUT_SECONDS)

        assert repo.shadow_runs() == []
        job = _job(repo, str(payload["job_id"]))
        assert (payload["worker_pid"], job["status"]) == (worker.process.pid, "done")


def _run_sync_twin(repo: HostileRepo, _monkeypatch: pytest.MonkeyPatch) -> None:
    completed = spawn.run_projection_jobs_worker_sync(root_path=repo.root)
    assert completed.returncode == 0


def _run_spawn_twin(repo: HostileRepo, monkeypatch: pytest.MonkeyPatch) -> None:
    with recorded_spawns(monkeypatch) as spawned:
        spawn.spawn_projection_jobs_worker(root_path=repo.root)
    assert only_worker(spawned).process.wait(timeout=_WORKER_TIMEOUT_SECONDS) == 0


@pytest.mark.parametrize(
    "start_worker", [_run_sync_twin, _run_spawn_twin], ids=["sync", "spawn"]
)
def test_worker_working_directory_is_not_the_repository_the_server_runs_in(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    start_worker: Callable[[HostileRepo, pytest.MonkeyPatch], None],
) -> None:
    # An empty PYTHONPATH entry means "the working directory" to the
    # interpreter and survives -P (measured on 3.11-3.15); client launchers
    # start the server inside the workspace. Neither may put the analysed
    # repository on the worker's import path.
    monkeypatch.setenv("PYTHONPATH", os.pathsep)
    with hostile_repo(tmp_path) as repo:
        job_id = _enqueue_pending_job(repo)
        monkeypatch.chdir(repo.root)

        start_worker(repo, monkeypatch)

        assert repo.shadow_runs() == []
        assert _job(repo, job_id)["status"] == "done"


def test_worker_argv_alone_keeps_the_repository_off_the_import_path(
    tmp_path: Path,
) -> None:
    # The interpreter switch, isolated from the working-directory choice: the
    # owner's argv started inside the analysed repository still never
    # imports from it.
    with hostile_repo(tmp_path) as repo:
        job_id = _enqueue_pending_job(repo)

        completed = subprocess.run(
            spawn._run_once_argv(repo.root),
            cwd=repo.root,
            capture_output=True,
            text=True,
            check=False,
            timeout=_WORKER_TIMEOUT_SECONDS,
        )

        assert repo.shadow_runs() == []
        assert json.loads(completed.stdout)["job_id"] == job_id


class _CapturedStart:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> Any:
        self.calls.append((argv, kwargs))
        return SimpleNamespace(pid=7, returncode=0, stdout="{}", stderr="")


def test_both_twins_start_outside_the_repository_with_its_root_and_no_mcp_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("CODECLONE_MCP_AUTH_TOKEN", "t" * 40)
    monkeypatch.setenv("CODECLONE_SPAWN_SENTINEL", "kept")
    captured = _CapturedStart()
    monkeypatch.setattr(subprocess, "Popen", captured)
    monkeypatch.setattr(subprocess, "run", captured)

    spawn.spawn_projection_jobs_worker(root_path=repo)
    spawn.run_projection_jobs_worker_sync(root_path=repo)

    assert len(captured.calls) == 2
    for argv, kwargs in captured.calls:
        cwd = Path(kwargs["cwd"]).resolve()
        assert repo.resolve() not in (cwd, *cwd.parents)
        assert argv[argv.index("--root") + 1] == str(repo.resolve())
        # No ``env`` means the child inherits this process's environment.
        child_env = os.environ if kwargs.get("env") is None else kwargs["env"]
        assert child_env.get("CODECLONE_SPAWN_SENTINEL") == "kept"
        assert "CODECLONE_MCP_AUTH_TOKEN" not in child_env


def test_isolation_flag_is_safe_path_where_the_interpreter_has_it() -> None:
    assert spawn._isolation_flag(SimpleNamespace(safe_path=False)) == "-P"
    assert spawn._isolation_flag(SimpleNamespace()) == "-I"


def test_isolation_flag_matches_what_the_running_interpreter_accepts() -> None:
    def accepts(flag: str) -> bool:
        probe = subprocess.run(
            [sys.executable, flag, "-c", "pass"],
            capture_output=True,
            check=False,
            timeout=_WORKER_TIMEOUT_SECONDS,
        )
        return probe.returncode == 0

    chosen = spawn._isolation_flag(sys.flags)
    assert chosen == ("-P" if accepts("-P") else "-I")
    assert accepts(chosen)
    assert spawn._run_once_argv(Path("/repo"))[1:3] == [chosen, "-m"]


def test_store_guard_reports_databases_outside_the_temporary_root(
    tmp_path: Path,
) -> None:
    inside = tmp_path / "inside.sqlite3"
    opened = [
        ":memory:",
        str(inside),
        f"file:{inside}?mode=ro",
        "/elsewhere/engineering_memory.sqlite3",
        "file:/elsewhere/audit.sqlite3?mode=ro",
    ]
    assert databases_outside(opened, tmp_path) == [
        "/elsewhere/engineering_memory.sqlite3",
        "file:/elsewhere/audit.sqlite3?mode=ro",
    ]
