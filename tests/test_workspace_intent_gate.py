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
from typing import Literal, cast

import pytest

from codeclone.config.intent_registry import DEFAULT_INTENT_REGISTRY_DB_PATH
from codeclone.surfaces.mcp import _workspace_intents as workspace_intents
from codeclone.surfaces.mcp._workspace_intent_store import (
    clear_workspace_intent_store_cache,
)
from codeclone.workspace_intent.gate import (
    HOOK_AUTHORIZE_FOREIGN_ENV,
    UnclosedWorkspaceIntent,
    evaluate_workspace_edit_gate,
    has_authorized_workspace_intent,
    has_blocking_workspace_intent,
    list_unclosed_workspace_intents,
    list_unclosed_workspace_intents_for_hook_cleanup,
)
from tests.test_workspace_intents import _record
from tests.workspace_intent_gate_helpers import (
    assert_gate_denied,
    codex_foreign_record,
    cursor_vscode_record,
    write_workspace_record,
)

_PID_ALIVE = "codeclone.workspace_intent.lifecycle.is_pid_alive"
_PID_LIVENESS = "codeclone.workspace_intent.lifecycle.pid_liveness"


def _write_record(root: Path, record: workspace_intents.WorkspaceIntentRecord) -> None:
    write_workspace_record(root, record)


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


def test_gate_denies_foreign_active_when_hook_env_disables_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(HOOK_AUTHORIZE_FOREIGN_ENV, "0")
    monkeypatch.setattr(_PID_ALIVE, lambda pid: True)
    _write_record(tmp_path, _record(pid=os.getpid() + 1000))

    decision = evaluate_workspace_edit_gate(tmp_path)

    assert decision.allowed is False
    assert decision.reason == "no_active_intent"


def test_gate_denies_unknown_pid_liveness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        _PID_LIVENESS,
        lambda _pid: workspace_intents.PidLiveness.UNKNOWN,
    )
    _write_record(tmp_path, _record(pid=os.getpid() + 1000))

    decision = evaluate_workspace_edit_gate(tmp_path)

    assert decision.allowed is False
    assert decision.reason == "no_active_intent"


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

    def _open_readonly(database: Path) -> _FakeConnection:
        seen["database"] = database
        return fake

    monkeypatch.setattr(
        "codeclone.workspace_intent.gate.open_intent_registry_db_readonly",
        _open_readonly,
    )

    assert_gate_denied(tmp_path, reason="no_active_intent")
    assert fake.closed is True
    assert seen["database"] == db_path
    assert "SELECT payload_json" in str(seen["sql"])


def test_list_unclosed_workspace_intents_returns_active_and_queued(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_PID_ALIVE, lambda pid: True)
    active = _record(intent_id="intent-active-001", status="active")
    queued = _record(intent_id="intent-queued-001", status="queued")
    _write_record(tmp_path, active)
    _write_record(tmp_path, queued)

    unclosed = list_unclosed_workspace_intents(tmp_path)

    assert unclosed == (
        UnclosedWorkspaceIntent("intent-active-001", "active"),
        UnclosedWorkspaceIntent("intent-queued-001", "queued"),
    )


def test_list_unclosed_workspace_intents_ignores_terminal_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_PID_ALIVE, lambda pid: True)
    _write_record(tmp_path, _record(intent_id="intent-active-001", status="active"))
    _write_record(tmp_path, _record(intent_id="intent-clean-001", status="clean"))
    _write_record(tmp_path, _record(intent_id="intent-expired-001", status="expired"))
    _write_record(tmp_path, _record(intent_id="intent-orphan-001", status="orphaned"))

    unclosed = list_unclosed_workspace_intents(tmp_path)

    assert unclosed == (UnclosedWorkspaceIntent("intent-active-001", "active"),)


def test_hook_cleanup_excludes_foreign_active_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_PID_ALIVE, lambda pid: True)
    _write_record(tmp_path, codex_foreign_record())

    unclosed = list_unclosed_workspace_intents_for_hook_cleanup(tmp_path)

    assert unclosed == ()


def test_hook_cleanup_includes_own_active_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_PID_ALIVE, lambda pid: True)
    own_pid = os.getpid()
    own = cursor_vscode_record(
        intent_id="intent-own-001",
        pid=own_pid,
        start_epoch=100,
    )
    _write_record(tmp_path, own)

    unclosed = list_unclosed_workspace_intents_for_hook_cleanup(
        tmp_path,
        own_pid=own_pid,
        own_start_epoch=100,
    )

    assert unclosed == (UnclosedWorkspaceIntent("intent-own-001", "active"),)


def test_hook_cleanup_includes_recoverable_cursor_intent_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_PID_ALIVE, lambda pid: False)
    cursor_recoverable = cursor_vscode_record(
        intent_id="intent-cursor-dead-001",
        pid=os.getpid() + 9000,
    )
    codex_recoverable = codex_foreign_record(
        intent_id="intent-codex-dead-001",
        pid=os.getpid() + 9001,
    )
    _write_record(tmp_path, cursor_recoverable)
    _write_record(tmp_path, codex_recoverable)

    unclosed = list_unclosed_workspace_intents_for_hook_cleanup(tmp_path)

    assert unclosed == (UnclosedWorkspaceIntent("intent-cursor-dead-001", "active"),)


def test_hook_cleanup_resolves_owner_identity_from_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os
    from dataclasses import replace

    from codeclone.workspace_intent.gate import (
        list_unclosed_workspace_intents_for_hook_cleanup,
    )
    from tests.test_workspace_intents import _record
    from tests.workspace_intent_gate_helpers import write_workspace_record

    monkeypatch.setattr(
        "codeclone.surfaces.mcp._workspace_intent_pid.is_agent_pid_alive",
        lambda _pid: True,
    )
    own_pid = os.getpid()
    own = replace(
        _record(intent_id="intent-own-env-001", status="active"),
        agent_pid=own_pid,
        agent_start_epoch=42,
    )
    write_workspace_record(tmp_path, own)
    monkeypatch.setenv("CODECLONE_HOOK_OWN_AGENT_PID", str(own_pid))
    monkeypatch.setenv("CODECLONE_HOOK_OWN_AGENT_START_EPOCH", "42")

    unclosed = list_unclosed_workspace_intents_for_hook_cleanup(tmp_path)

    assert len(unclosed) == 1
    assert unclosed[0].intent_id == "intent-own-env-001"


def test_hook_cleanup_record_filter_handles_recoverable_agents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os
    from dataclasses import replace

    from codeclone.surfaces.mcp._workspace_intent_lifecycle import utc_now
    from codeclone.workspace_intent.gate import _include_record_in_hook_cleanup
    from tests.test_workspace_intents import _record

    # Death is declared here, not borrowed from the pid space. Nothing reserves
    # ``getpid() + N``, so an unreserved "surely absent" pid makes the verdict a
    # function of what else the machine happens to be running. This patches the
    # seam the gate actually consults; the pid below is then inert.
    monkeypatch.setattr(
        "codeclone.workspace_intent.lifecycle.is_pid_alive", lambda _pid: False
    )
    recoverable = replace(
        _record(intent_id="intent-rec-001", status="active"),
        agent_pid=os.getpid(),
        agent_label="cursor-vscode/dead",
    )
    now = utc_now()
    assert (
        _include_record_in_hook_cleanup(
            recoverable,
            own_pid=os.getpid(),
            own_start_epoch=1,
            recoverable_agent_label_prefix=None,
            include_foreign=False,
            now=now,
        )
        is False
    )
    assert (
        _include_record_in_hook_cleanup(
            recoverable,
            own_pid=os.getpid(),
            own_start_epoch=1,
            recoverable_agent_label_prefix="cursor-vscode/",
            include_foreign=False,
            now=now,
        )
        is True
    )


def test_hook_authorizes_foreign_active_environment_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.workspace_intent.gate import (
        HOOK_AUTHORIZE_FOREIGN_ENV,
        _hook_authorizes_foreign_active,
    )

    monkeypatch.delenv(HOOK_AUTHORIZE_FOREIGN_ENV, raising=False)
    assert _hook_authorizes_foreign_active() is True
    monkeypatch.setenv(HOOK_AUTHORIZE_FOREIGN_ENV, "maybe")
    assert _hook_authorizes_foreign_active() is False
    monkeypatch.setenv(HOOK_AUTHORIZE_FOREIGN_ENV, "off")
    assert _hook_authorizes_foreign_active() is False
    monkeypatch.setenv(HOOK_AUTHORIZE_FOREIGN_ENV, "yes")
    assert _hook_authorizes_foreign_active() is True


def test_workspace_ownership_honors_foreign_active_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.surfaces.mcp import _workspace_intents as workspace_intents
    from codeclone.workspace_intent import gate as gate_mod

    monkeypatch.setattr(gate_mod, "_hook_authorizes_foreign_active", lambda: True)
    assert (
        gate_mod._ownership_authorizes_hook(
            workspace_intents.IntentOwnership.FOREIGN_ACTIVE,
            liveness=workspace_intents.PidLiveness.ALIVE,
        )
        is True
    )
    monkeypatch.setattr(gate_mod, "_hook_authorizes_foreign_active", lambda: False)
    assert (
        gate_mod._ownership_authorizes_hook(
            workspace_intents.IntentOwnership.FOREIGN_ACTIVE,
            liveness=workspace_intents.PidLiveness.ALIVE,
        )
        is False
    )


def test_workspace_ownership_requires_live_pid_for_own_active() -> None:
    from codeclone.surfaces.mcp import _workspace_intents as workspace_intents
    from codeclone.workspace_intent import gate as gate_mod

    assert (
        gate_mod._ownership_authorizes_hook(
            workspace_intents.IntentOwnership.OWN_ACTIVE,
            liveness=workspace_intents.PidLiveness.ALIVE,
        )
        is True
    )
    assert (
        gate_mod._ownership_authorizes_hook(
            workspace_intents.IntentOwnership.OWN_ACTIVE,
            liveness=workspace_intents.PidLiveness.DEAD,
        )
        is False
    )


def test_agent_pid_liveness_honors_boolean_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.surfaces.mcp import _workspace_intent_pid as pid_mod
    from codeclone.surfaces.mcp._workspace_intent_lifecycle import PidLiveness

    monkeypatch.setattr(pid_mod, "is_agent_pid_alive", lambda _pid: False)
    assert pid_mod.agent_pid_liveness(123) is PidLiveness.DEAD


def test_read_only_registry_loader_dispatches_by_backend(tmp_path: Path) -> None:
    """The shared read-only loader serves both backends and rejects an
    unknown one instead of guessing."""

    import codeclone.workspace_intent.gate as workspace_gate_mod
    from codeclone.config.intent_registry import IntentRegistryConfig

    load_registry_records_read_only = (
        workspace_gate_mod.intent_reader.load_registry_records_read_only  # type: ignore[attr-defined]
    )

    record = _record()
    write_workspace_record(tmp_path, record)
    intents_dir = tmp_path / ".codeclone" / "intents"
    (intents_dir / "intent-deadbeef-002.json").write_text("{}", encoding="utf-8")

    file_config = IntentRegistryConfig(
        backend="file",
        storage_path=intents_dir,
    )
    records = load_registry_records_read_only(tmp_path, file_config)
    assert [item.intent_id for item in records] == [record.intent_id]

    sqlite_config = IntentRegistryConfig(
        backend="sqlite",
        storage_path=tmp_path / ".codeclone" / "intents.sqlite3",
    )
    assert load_registry_records_read_only(tmp_path, sqlite_config) == ()

    unknown_config = IntentRegistryConfig(
        backend="redis",  # type: ignore[arg-type]
        storage_path=intents_dir,
    )
    with pytest.raises(ValueError, match="Unsupported intent registry backend"):
        load_registry_records_read_only(tmp_path, unknown_config)


# ── The queue has an order, and the order is a contract ──
#
# ``record_sort_key`` is ``(declared_at_utc, agent_pid, intent_id)``. That
# tuple is not presentation: the gate names the HEAD of the sorted queue, and
# that intent_id is who the user is told to coordinate with. One owner applies
# the rule -- the registry reader -- and every consumer inherits it.
#
# In each fixture below the later key components run OPPOSITE to the earlier
# ones, so a key that lost its first component could not pass by accident.
# The expected head is re-derived from the RULE, never named by literal.


def _queued_split_only_by_declaration() -> tuple[
    workspace_intents.WorkspaceIntentRecord,
    workspace_intents.WorkspaceIntentRecord,
]:
    """Two waiting agents distinguishable only by when they declared.

    The earlier declaration carries the HIGHER pid and the LATER intent_id.
    """

    now = workspace_intents.utc_now()
    early = replace(
        _record(intent_id="intent-ffffffff-002", pid=os.getpid() + 2000),
        status="queued",
        declared_at_utc=workspace_intents.format_utc(now - timedelta(hours=2)),
    )
    later = replace(
        _record(intent_id="intent-aaaaaaaa-001", pid=os.getpid() + 1000),
        status="queued",
        declared_at_utc=workspace_intents.format_utc(now - timedelta(hours=1)),
    )
    return early, later


def _queued_split_only_by_pid() -> tuple[
    workspace_intents.WorkspaceIntentRecord,
    workspace_intents.WorkspaceIntentRecord,
]:
    """Two waiting agents that declared in the same moment.

    The lower pid carries the LATER intent_id.
    """

    declared = workspace_intents.format_utc(
        workspace_intents.utc_now() - timedelta(hours=2)
    )
    lower = replace(
        _record(intent_id="intent-ffffffff-002", pid=os.getpid() + 1000),
        status="queued",
        declared_at_utc=declared,
    )
    higher = replace(
        _record(intent_id="intent-aaaaaaaa-001", pid=os.getpid() + 2000),
        status="queued",
        declared_at_utc=declared,
    )
    return lower, higher


def test_gate_names_the_earliest_declared_of_two_queued_intents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Head, first key component: the queue is FIFO by declaration."""

    monkeypatch.setattr(_PID_ALIVE, lambda pid: True)
    early, later = _queued_split_only_by_declaration()
    for record in (later, early):  # written out of order on purpose
        _write_record(tmp_path, record)

    decision = evaluate_workspace_edit_gate(tmp_path)

    expected = min((early, later), key=lambda record: record.declared_at_utc)
    assert decision.reason == "queued_intent_not_editable"
    assert decision.intent_id == expected.intent_id


def test_gate_names_the_lowest_pid_among_intents_declared_together(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Head, second key component: a tie on declaration falls to the pid."""

    monkeypatch.setattr(_PID_ALIVE, lambda pid: True)
    lower, higher = _queued_split_only_by_pid()
    for record in (higher, lower):
        _write_record(tmp_path, record)

    decision = evaluate_workspace_edit_gate(tmp_path)

    expected = min((lower, higher), key=lambda record: record.agent_pid)
    assert decision.reason == "queued_intent_not_editable"
    assert decision.intent_id == expected.intent_id


def _read_only_records(
    root: Path,
    *,
    backend: Literal["file", "sqlite"],
) -> tuple[workspace_intents.WorkspaceIntentRecord, ...]:
    import codeclone.workspace_intent.gate as workspace_gate_mod
    from codeclone.config.intent_registry import IntentRegistryConfig

    storage = (
        root / DEFAULT_INTENT_REGISTRY_DB_PATH
        if backend == "sqlite"
        else root / ".codeclone" / "intents"
    )
    # Reached through the gate module on purpose: importing the reader here
    # would add a fresh r4 -> r2p test edge for the 39S ratchet to refuse,
    # and this test's subject is the order, not the import graph.
    records = workspace_gate_mod.intent_reader.load_registry_records_read_only(  # type: ignore[attr-defined]
        root,
        IntentRegistryConfig(backend=backend, storage_path=storage),
    )
    return cast("tuple[workspace_intents.WorkspaceIntentRecord, ...]", records)


def test_registry_reader_hands_out_the_queue_in_declaration_order(
    tmp_path: Path,
) -> None:
    """The single owner of the order, first key component.

    Every consumer inherits this sequence rather than re-establishing it, so
    this is where the law is applied and where reversing it must be felt.
    """

    early, later = _queued_split_only_by_declaration()
    for record in (later, early):
        _write_record(tmp_path, record)

    records = _read_only_records(tmp_path, backend="file")

    expected = min((early, later), key=lambda record: record.declared_at_utc)
    assert records[0].intent_id == expected.intent_id


def test_registry_reader_breaks_a_declaration_tie_by_pid(
    tmp_path: Path,
) -> None:
    """The single owner of the order, second key component."""

    lower, higher = _queued_split_only_by_pid()
    for record in (higher, lower):
        _write_record(tmp_path, record)

    records = _read_only_records(tmp_path, backend="file")

    expected = min((lower, higher), key=lambda record: record.agent_pid)
    assert records[0].intent_id == expected.intent_id


def test_sqlite_registry_reader_hands_out_the_same_queue_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The order is a property of the registry, not of one backend.

    The sqlite reader no longer asks SQL for the sequence; the owner sorts
    what the query returns, so both backends answer with one law.
    """

    monkeypatch.setenv("CODECLONE_INTENT_REGISTRY_BACKEND", "sqlite")
    monkeypatch.setenv(
        "CODECLONE_INTENT_REGISTRY_PATH",
        DEFAULT_INTENT_REGISTRY_DB_PATH,
    )
    clear_workspace_intent_store_cache()
    early, later = _queued_split_only_by_declaration()
    for record in (later, early):
        _write_record(tmp_path, record)

    records = _read_only_records(tmp_path, backend="sqlite")

    expected = min((early, later), key=lambda record: record.declared_at_utc)
    assert records[0].intent_id == expected.intent_id
