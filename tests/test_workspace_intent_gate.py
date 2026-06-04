# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

import os
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from codeclone.config.intent_registry import DEFAULT_INTENT_REGISTRY_DB_PATH
from codeclone.surfaces.mcp import _workspace_intents as workspace_intents
from codeclone.surfaces.mcp._workspace_intent_store import (
    clear_workspace_intent_store_cache,
)
from codeclone.workspace_intent.gate import (
    evaluate_workspace_edit_gate,
    has_authorized_workspace_intent,
    has_blocking_workspace_intent,
)
from tests.test_workspace_intents import _record
from tests.workspace_intent_gate_helpers import assert_gate_denied

_PID_ALIVE = "codeclone.surfaces.mcp._workspace_intent_pid.is_agent_pid_alive"


def _write_record(root: Path, record: workspace_intents.WorkspaceIntentRecord) -> None:
    assert workspace_intents.write_workspace_intent(root=root, record=record)


def test_gate_allows_active_file_registry_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_PID_ALIVE, lambda pid: True)
    _write_record(tmp_path, _record(pid=os.getpid() + 1000))

    decision = evaluate_workspace_edit_gate(tmp_path)

    assert decision.allowed is True
    assert decision.reason == "active_intent"
    assert decision.status == "active"
    assert decision.ownership == "foreign_active"
    assert decision.registry_backend == "file"
    assert has_authorized_workspace_intent(tmp_path) is True
    assert has_blocking_workspace_intent(tmp_path) is True


def test_gate_allows_active_sqlite_registry_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODECLONE_INTENT_REGISTRY_BACKEND", "sqlite")
    monkeypatch.setenv(
        "CODECLONE_INTENT_REGISTRY_PATH",
        DEFAULT_INTENT_REGISTRY_DB_PATH,
    )
    clear_workspace_intent_store_cache()
    monkeypatch.setattr(_PID_ALIVE, lambda pid: True)
    _write_record(tmp_path, _record(pid=os.getpid() + 1000))

    decision = evaluate_workspace_edit_gate(tmp_path)

    assert decision.allowed is True
    assert decision.reason == "active_intent"
    assert decision.registry_backend == "sqlite"
    assert decision.registry_path == DEFAULT_INTENT_REGISTRY_DB_PATH


def test_gate_denies_queued_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_PID_ALIVE, lambda pid: True)
    queued = replace(_record(), status="queued")
    _write_record(tmp_path, queued)

    decision = evaluate_workspace_edit_gate(tmp_path)

    assert decision.allowed is False
    assert decision.reason == "queued_intent_not_editable"
    assert decision.intent_id == queued.intent_id


def test_gate_denies_expired_ttl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_PID_ALIVE, lambda pid: True)
    _write_record(tmp_path, _record(expires_delta=timedelta(seconds=-1)))

    decision = evaluate_workspace_edit_gate(tmp_path)

    assert decision.allowed is False
    assert decision.reason == "no_active_intent"


def test_gate_denies_orphaned_active_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_PID_ALIVE, lambda pid: False)
    _write_record(tmp_path, _record(pid=999999))

    decision = evaluate_workspace_edit_gate(tmp_path)

    assert decision.allowed is False
    assert decision.reason == "no_active_intent"


def test_gate_denies_live_foreign_stale_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_PID_ALIVE, lambda pid: True)
    stale_live = _record(
        pid=os.getpid() + 1000,
        lease_renewed_delta=timedelta(minutes=-20),
        lease_seconds=workspace_intents.MIN_LEASE_SECONDS,
    )
    _write_record(tmp_path, stale_live)

    decision = evaluate_workspace_edit_gate(tmp_path)

    assert decision.allowed is False
    assert decision.reason == "no_active_intent"


def test_gate_does_not_create_missing_sqlite_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODECLONE_INTENT_REGISTRY_BACKEND", "sqlite")
    monkeypatch.setenv(
        "CODECLONE_INTENT_REGISTRY_PATH",
        DEFAULT_INTENT_REGISTRY_DB_PATH,
    )
    clear_workspace_intent_store_cache()
    db_path = tmp_path / DEFAULT_INTENT_REGISTRY_DB_PATH

    decision = evaluate_workspace_edit_gate(tmp_path)

    assert decision.allowed is False
    assert decision.reason == "no_active_intent"
    assert not db_path.exists()


def test_gate_closes_sqlite_read_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODECLONE_INTENT_REGISTRY_BACKEND", "sqlite")
    monkeypatch.setenv(
        "CODECLONE_INTENT_REGISTRY_PATH",
        DEFAULT_INTENT_REGISTRY_DB_PATH,
    )
    clear_workspace_intent_store_cache()
    db_path = tmp_path / DEFAULT_INTENT_REGISTRY_DB_PATH
    db_path.parent.mkdir(parents=True)
    db_path.touch()
    seen: dict[str, object] = {}

    class _FakeConnection:
        closed = False

        def execute(self, sql: str) -> _FakeConnection:
            seen["sql"] = sql
            return self

        def fetchall(self) -> list[tuple[str]]:
            return []

        def close(self) -> None:
            self.closed = True

    fake = _FakeConnection()

    def _connect(database: str, *, uri: bool) -> _FakeConnection:
        seen["uri"] = database
        seen["uri_flag"] = uri
        return fake

    monkeypatch.setattr("codeclone.workspace_intent.gate.sqlite3.connect", _connect)

    assert_gate_denied(tmp_path, reason="no_active_intent")
    assert fake.closed is True
    assert seen["uri_flag"] is True
    assert str(seen["uri"]).endswith("?mode=ro")
    assert "SELECT payload_json" in str(seen["sql"])
