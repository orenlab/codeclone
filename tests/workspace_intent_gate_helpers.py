# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

from codeclone.surfaces.mcp import _workspace_intents as workspace_intents
from codeclone.surfaces.mcp._workspace_intents import WorkspaceIntentRecord
from codeclone.workspace_intent.gate import (
    WorkspaceEditGateDecision,
    evaluate_workspace_edit_gate,
)
from tests.test_workspace_intents import _record

CODEX_AGENT_LABEL = "codex-mcp-client/0.137.0-alpha.4"
CURSOR_AGENT_LABEL = "cursor-vscode/1.0.0"


def assert_gate_denied(
    root: Path,
    *,
    reason: str,
) -> WorkspaceEditGateDecision:
    decision = evaluate_workspace_edit_gate(root)
    assert decision.allowed is False
    assert decision.reason == reason
    return decision


def codex_foreign_record(
    *,
    intent_id: str = "intent-foreign-001",
    pid: int | None = None,
    start_epoch: int = 100,
    status: str = "active",
) -> WorkspaceIntentRecord:
    return replace(
        _record(
            intent_id=intent_id,
            pid=pid or (os.getpid() + 5000),
            start_epoch=start_epoch,
            status=status,
        ),
        agent_label=CODEX_AGENT_LABEL,
    )


def cursor_vscode_record(
    *,
    intent_id: str = "intent-abcdef12-001",
    pid: int | None = None,
    start_epoch: int = 100,
    status: str = "active",
) -> WorkspaceIntentRecord:
    return replace(
        _record(
            intent_id=intent_id,
            pid=pid,
            start_epoch=start_epoch,
            status=status,
        ),
        agent_label=CURSOR_AGENT_LABEL,
    )


def write_workspace_record(root: Path, record: WorkspaceIntentRecord) -> None:
    assert workspace_intents.write_workspace_intent(root=root, record=record)


def bind_hook_own_agent_env(
    monkeypatch: pytest.MonkeyPatch,
    record: WorkspaceIntentRecord,
) -> None:
    monkeypatch.setenv("CODECLONE_HOOK_OWN_AGENT_PID", str(record.agent_pid))
    monkeypatch.setenv(
        "CODECLONE_HOOK_OWN_AGENT_START_EPOCH",
        str(record.agent_start_epoch),
    )
