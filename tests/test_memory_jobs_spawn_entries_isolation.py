# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The CLI and MCP rebuild entries start an isolated projection worker.

``codeclone memory jobs enqueue`` and MCP
``manage_engineering_memory(action="enqueue_projection_rebuild")`` both reach
the one spawn owner. Driven end to end against a hostile temporary repository
(``projection_worker_fixtures``), each starts a real worker that processes the
repository's job without importing the repository's shadow module, and
without the MCP server's HTTP auth token in its environment.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from codeclone.contracts import ExitCode
from codeclone.surfaces.cli.memory import memory_main
from codeclone.surfaces.mcp.auth import MCP_AUTH_TOKEN_ENV
from codeclone.surfaces.mcp.service import CodeCloneMCPService

from .projection_worker_fixtures import (
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


def _cli_enqueue(root: Path) -> None:
    code = memory_main(["jobs", "enqueue", "--force", "--root", str(root)])
    assert code == int(ExitCode.SUCCESS)


def _mcp_enqueue(root: Path) -> None:
    payload = CodeCloneMCPService(history_limit=2).manage_engineering_memory(
        root=str(root), action="enqueue_projection_rebuild"
    )
    assert payload["status"] == "enqueued"


@pytest.mark.parametrize("enqueue", [_cli_enqueue, _mcp_enqueue], ids=["cli", "mcp"])
def test_rebuild_entry_starts_a_worker_isolated_from_the_analysed_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    enqueue: Callable[[Path], None],
) -> None:
    monkeypatch.setenv(MCP_AUTH_TOKEN_ENV, "t" * 40)
    monkeypatch.setenv("CODECLONE_SPAWN_SENTINEL", "kept")
    with hostile_repo(tmp_path) as repo:
        with recorded_spawns(monkeypatch) as spawned:
            enqueue(repo.root)
        worker = only_worker(spawned)
        worker.process.wait(timeout=_WORKER_TIMEOUT_SECONDS)

        assert repo.shadow_runs() == []
        status = CodeCloneMCPService(history_limit=2).manage_engineering_memory(
            root=str(repo.root), action="projection_rebuild_status"
        )
        jobs = status["jobs"]
        assert isinstance(jobs, list)
        assert [(job["status"], job["claimed_by"].split("@")[0]) for job in jobs] == [
            ("done", str(worker.process.pid))
        ]
        assert worker.env is not None
        assert MCP_AUTH_TOKEN_ENV not in worker.env
        assert worker.env["CODECLONE_SPAWN_SENTINEL"] == "kept"
