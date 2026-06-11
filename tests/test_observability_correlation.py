# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
import sqlite3
import subprocess
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import codeclone.memory.jobs.spawn as spawn
import codeclone.memory.jobs.worker as worker
from codeclone.config.observability import ObservabilityConfig
from codeclone.observability import (
    bootstrap,
    current_operation_context,
    instrument_db_connection,
    operation,
    shutdown,
    span,
)
from codeclone.observability.store.schema import (
    observability_store_path,
    open_observability_store,
)


@pytest.fixture(autouse=True)
def _reset_runtime() -> Iterator[None]:
    yield
    shutdown()


def test_current_operation_context(tmp_path: Path) -> None:
    assert current_operation_context() is None  # disabled
    bootstrap(ObservabilityConfig(enabled=True), root=tmp_path)
    assert current_operation_context() is None  # enabled, outside an operation
    with operation(name="finish", surface="mcp", correlation_id="corr-A") as op:
        assert current_operation_context() == (op.operation_id, "corr-A")


def test_run_projection_job_links_under_finish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CODECLONE_OBSERVABILITY_CORRELATION_ID", "A-corr")
    monkeypatch.setenv("CODECLONE_OBSERVABILITY_PARENT_OPERATION_ID", "A-op")
    monkeypatch.setattr(
        worker, "execute_trajectory_rebuild", lambda **_k: {"status": "ok"}
    )
    monkeypatch.setattr(
        worker, "execute_semantic_index_rebuild", lambda **_k: {"status": "ok"}
    )
    monkeypatch.setattr(
        worker, "execute_experience_distillation", lambda **_k: {"status": "ok"}
    )

    bootstrap(ObservabilityConfig(enabled=True), root=tmp_path)
    worker.run_projection_job(
        MagicMock(),
        job_id="j1",
        root_path=tmp_path,
        config=MagicMock(),
        project=MagicMock(),
        stimulus={},
    )
    shutdown()

    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        row = conn.execute(
            "SELECT name, correlation_id, parent_operation_id FROM platform_operations"
        ).fetchone()
        boot = conn.execute(
            "SELECT name, duration_ms FROM platform_spans "
            "WHERE name='memory.projection.worker_bootstrap'"
        ).fetchone()
    finally:
        conn.close()
    assert row == ("memory.projection.job", "A-corr", "A-op")
    # The spawned worker (env handoff present) attributes its cold-start as a
    # span, so the spawn->job gap is labelled in the waterfall.
    assert boot is not None
    assert boot[1] >= 0.0


def test_spawn_injects_correlation_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def _fake_popen(argv: object, **kwargs: object) -> object:
        captured["env"] = kwargs.get("env")
        proc = MagicMock()
        proc.pid = 4321
        return proc

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)
    bootstrap(ObservabilityConfig(enabled=True), root=tmp_path)
    with operation(
        name="finish_controlled_change", surface="mcp", correlation_id="A"
    ) as op:
        result = spawn.spawn_projection_jobs_worker(root_path=tmp_path)

    assert result.spawned is True
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["CODECLONE_OBSERVABILITY_CORRELATION_ID"] == "A"
    assert env["CODECLONE_OBSERVABILITY_PARENT_OPERATION_ID"] == op.operation_id


def test_spawn_without_operation_inherits_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def _fake_popen(argv: object, **kwargs: object) -> object:
        captured["env"] = kwargs.get("env")
        proc = MagicMock()
        proc.pid = 1
        return proc

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)
    # Observability disabled -> no active operation -> inherit parent env.
    spawn.spawn_projection_jobs_worker(root_path=tmp_path)
    assert captured["env"] is None


def test_mcp_analyze_repository_emits_pipeline_spans(tmp_path: Path) -> None:
    from codeclone.surfaces.mcp.service import CodeCloneMCPService
    from codeclone.surfaces.mcp.session import MCPAnalysisRequest

    (tmp_path / "module.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8"
    )
    service = CodeCloneMCPService(history_limit=4)
    bootstrap(ObservabilityConfig(enabled=True), root=tmp_path)
    try:
        # The registrar opens this op around each MCP tool; emulate it so the
        # session's stage spans have an operation to attach to.
        with operation(name="mcp.analyze_repository", surface="mcp") as op:
            op_id = op.operation_id
            service.analyze_repository(
                MCPAnalysisRequest(root=str(tmp_path), respect_pyproject=False)
            )
    finally:
        shutdown()

    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        rows = conn.execute(
            "SELECT name FROM platform_spans WHERE operation_id=?", (op_id,)
        ).fetchall()
    finally:
        conn.close()
    names = {row[0] for row in rows}
    assert {"pipeline.discover", "pipeline.process", "pipeline.analyze"} <= names


def test_db_query_counter_attaches_to_active_span(tmp_path: Path) -> None:
    bootstrap(ObservabilityConfig(enabled=True), root=tmp_path)
    try:
        with (
            operation(name="memory.projection.job", surface="memory"),
            span(name="memory.semantic.reindex"),
        ):
            conn = sqlite3.connect(":memory:")
            instrument_db_connection(conn)
            conn.execute("CREATE TABLE t (a INTEGER)")
            conn.execute("INSERT INTO t VALUES (1)")
            conn.execute("INSERT INTO t VALUES (2)")
            conn.execute("SELECT * FROM t").fetchall()
            conn.close()
    finally:
        shutdown()

    obs = open_observability_store(observability_store_path(tmp_path))
    try:
        row = obs.execute(
            "SELECT counters_json FROM platform_spans "
            "WHERE name='memory.semantic.reindex'"
        ).fetchone()
    finally:
        obs.close()
    counters = json.loads(row[0]) if row and row[0] else {}
    # create + 2 inserts + select all land on the active span; only the inserts
    # are writes.
    assert counters.get("db_queries", 0) >= 4
    assert counters.get("db_writes", 0) == 2


def test_instrument_db_connection_is_inert_when_disabled() -> None:
    # Disabled process: no trace callback, no counting, no error, zero overhead.
    conn = sqlite3.connect(":memory:")
    try:
        instrument_db_connection(conn)
        conn.execute("CREATE TABLE t (a)")
        assert current_operation_context() is None
    finally:
        conn.close()
