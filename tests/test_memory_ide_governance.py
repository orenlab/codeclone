# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import secrets
from pathlib import Path

import pytest

from codeclone.memory.exceptions import MemoryContractError
from codeclone.memory.governance import record_candidate
from codeclone.memory.ide_governance import (
    GOVERNANCE_MODE_UNAVAILABLE_NEXT_STEP,
    IDE_GOVERNANCE_PROTOCOL_VERSION,
    IdeGovernanceSessionState,
    commit_governance,
    compute_governance_proof,
    prepare_governance,
    register_ide_governance,
)
from codeclone.memory.project import resolve_project_identity
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore
from codeclone.surfaces.mcp.service import CodeCloneMCPService


def _governance_key_hex() -> str:
    return secrets.token_hex(32)


def test_agent_approve_action_rejected_by_mcp(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    service = CodeCloneMCPService()
    payload = service.manage_engineering_memory(
        root=str(root),
        action="approve",
        record_id="mem-1",
    )
    assert payload["status"] == "rejected"
    assert payload["reason"] == "governance_mode_unavailable"
    next_step = payload["next_step"]
    assert isinstance(next_step, str)
    assert "codeclone memory approve" not in next_step.lower()
    assert GOVERNANCE_MODE_UNAVAILABLE_NEXT_STEP in next_step


def test_ide_governance_prepare_and_commit_approve(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    project = resolve_project_identity(root)
    store = SqliteEngineeringMemoryStore(tmp_path / "memory.sqlite3")
    state = IdeGovernanceSessionState(channel_enabled=True)
    key_hex = _governance_key_hex()
    try:
        store.initialize(project)
        draft = record_candidate(
            store,
            project=project,
            record_type="architecture_decision",
            statement="Use IDE governance for human approval.",
            max_candidates=100,
        )
        registered = register_ide_governance(
            state,
            ide_governance_key=key_hex,
            client_name="CodeClone VS Code",
            client_version="0.3.0",
        )
        assert registered["status"] == "ok"
        prepared = prepare_governance(
            state,
            store,
            project_id=project.id,
            root_path=str(root),
            record_id=draft.id,
            decision="approve",
        )
        assert prepared["status"] == "ok"
        ticket_id = str(prepared["governance_ticket"])
        nonce = str(prepared["confirmation_nonce"])
        proof = compute_governance_proof(
            bytes.fromhex(key_hex),
            ticket_id=ticket_id,
            record_id=draft.id,
            decision="approve",
            confirmation_nonce=nonce,
            project_id=project.id,
            statement_digest=str(prepared["statement_digest"]),
            protocol=IDE_GOVERNANCE_PROTOCOL_VERSION,
        )
        committed = commit_governance(
            state,
            store,
            project_id=project.id,
            root_path=str(root),
            record_id=draft.id,
            decision="approve",
            governance_ticket=ticket_id,
            confirmation_nonce=nonce,
            proof=proof,
            actor="vscode-test",
            protocol=IDE_GOVERNANCE_PROTOCOL_VERSION,
        )
        assert committed["status"] == "ok"
        assert committed["record_status"] == "active"
        updated = store.find_record(draft.id)
        assert updated is not None
        assert updated.status == "active"
    finally:
        store.close()


def test_ide_governance_rejects_without_channel(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    project = resolve_project_identity(root)
    store = SqliteEngineeringMemoryStore(tmp_path / "memory.sqlite3")
    state = IdeGovernanceSessionState(channel_enabled=False)
    try:
        store.initialize(project)
        draft = record_candidate(
            store,
            project=project,
            record_type="change_rationale",
            statement="Draft only.",
            max_candidates=100,
        )
        payload = prepare_governance(
            state,
            store,
            project_id=project.id,
            root_path=str(root),
            record_id=draft.id,
            decision="approve",
        )
        assert payload["status"] == "rejected"
        assert payload["reason"] == "governance_mode_unavailable"
    finally:
        store.close()


def test_ide_governance_commit_rejects_bad_proof(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    project = resolve_project_identity(root)
    store = SqliteEngineeringMemoryStore(tmp_path / "memory.sqlite3")
    state = IdeGovernanceSessionState(channel_enabled=True)
    key_hex = _governance_key_hex()
    try:
        store.initialize(project)
        draft = record_candidate(
            store,
            project=project,
            record_type="change_rationale",
            statement="Needs valid proof.",
            max_candidates=100,
        )
        register_ide_governance(
            state,
            ide_governance_key=key_hex,
            client_name="CodeClone VS Code",
            client_version="0.3.0",
        )
        prepared = prepare_governance(
            state,
            store,
            project_id=project.id,
            root_path=str(root),
            record_id=draft.id,
            decision="approve",
        )
        with pytest.raises(MemoryContractError, match="Invalid IDE governance proof"):
            commit_governance(
                state,
                store,
                project_id=project.id,
                root_path=str(root),
                record_id=draft.id,
                decision="approve",
                governance_ticket=str(prepared["governance_ticket"]),
                confirmation_nonce=str(prepared["confirmation_nonce"]),
                proof="0" * 64,
                actor="vscode-test",
                protocol=IDE_GOVERNANCE_PROTOCOL_VERSION,
            )
    finally:
        store.close()


def test_ide_governance_prepare_and_commit_reject(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    project = resolve_project_identity(root)
    store = SqliteEngineeringMemoryStore(tmp_path / "memory.sqlite3")
    state = IdeGovernanceSessionState(channel_enabled=True)
    key_hex = _governance_key_hex()
    try:
        store.initialize(project)
        draft = record_candidate(
            store,
            project=project,
            record_type="change_rationale",
            statement="Reject after review.",
            max_candidates=100,
        )
        register_ide_governance(
            state,
            ide_governance_key=key_hex,
            client_name="CodeClone VS Code",
            client_version="0.3.0",
        )
        prepared = prepare_governance(
            state,
            store,
            project_id=project.id,
            root_path=str(root),
            record_id=draft.id,
            decision="reject",
        )
        proof = compute_governance_proof(
            bytes.fromhex(key_hex),
            ticket_id=str(prepared["governance_ticket"]),
            record_id=draft.id,
            decision="reject",
            confirmation_nonce=str(prepared["confirmation_nonce"]),
            project_id=project.id,
            statement_digest=str(prepared["statement_digest"]),
            protocol=IDE_GOVERNANCE_PROTOCOL_VERSION,
        )
        committed = commit_governance(
            state,
            store,
            project_id=project.id,
            root_path=str(root),
            record_id=draft.id,
            decision="reject",
            governance_ticket=str(prepared["governance_ticket"]),
            confirmation_nonce=str(prepared["confirmation_nonce"]),
            proof=proof,
            actor="vscode-test",
            protocol=IDE_GOVERNANCE_PROTOCOL_VERSION,
        )
        assert committed["status"] == "ok"
        updated = store.find_record(draft.id)
        assert updated is not None
        assert updated.status == "rejected"
    finally:
        store.close()
