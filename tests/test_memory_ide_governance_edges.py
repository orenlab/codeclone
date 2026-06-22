# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.memory.exceptions import MemoryContractError
from codeclone.memory.governance import approve_record, record_candidate
from codeclone.memory.ide_governance import (
    IDE_GOVERNANCE_PROTOCOL_VERSION,
    IdeGovernanceSessionState,
    commit_governance,
    compute_governance_proof,
    prepare_governance,
    register_ide_governance,
)
from codeclone.memory.project import resolve_project_identity
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore


def _valid_key_hex() -> str:
    # 32 bytes => 64 hex chars; keep it deterministic enough.
    return "00" * 32


def test_prepare_governance_rejects_when_channel_enabled_but_key_missing(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    project = resolve_project_identity(root)
    store = SqliteEngineeringMemoryStore(tmp_path / "memory.sqlite3")
    state = IdeGovernanceSessionState(channel_enabled=True)
    try:
        store.initialize(project)
        assert store.count_records() == 0
        draft = record_candidate(
            store,
            project=project,
            record_type="architecture_decision",
            statement="Use IDE governance.",
            subject_path="pkg/mod.py",
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
        assert payload["reason"] == "governance_key_missing"
    finally:
        store.close()


def test_register_ide_governance_rejects_invalid_hex_key(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    project = resolve_project_identity(root)
    store = SqliteEngineeringMemoryStore(tmp_path / "memory.sqlite3")
    state = IdeGovernanceSessionState(channel_enabled=True)
    try:
        store.initialize(project)
        with pytest.raises(MemoryContractError, match="hex length must be even"):
            register_ide_governance(
                state,
                ide_governance_key="0xabc",
                client_name="CodeClone VS Code",
                client_version="0.3.0",
            )
    finally:
        store.close()


@pytest.mark.parametrize(
    ("client_name", "client_version", "expected_status"),
    [
        ("Unknown IDE", "0.3.0", "rejected"),
        ("CodeClone JetBrains", "0.1.0", "ok"),
    ],
)
def test_register_ide_governance_client_allowlist(
    tmp_path: Path,
    client_name: str,
    client_version: str,
    expected_status: str,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    project = resolve_project_identity(root)
    store = SqliteEngineeringMemoryStore(tmp_path / "memory.sqlite3")
    state = IdeGovernanceSessionState(channel_enabled=True)
    try:
        store.initialize(project)
        payload = register_ide_governance(
            state,
            ide_governance_key=_valid_key_hex(),
            client_name=client_name,
            client_version=client_version,
        )
        assert payload["status"] == expected_status
        assert payload["action"] == "register_ide_governance"
        if expected_status == "ok":
            assert payload["client_name"] == client_name
    finally:
        store.close()


def test_commit_governance_returns_not_found_for_missing_record(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    project = resolve_project_identity(root)
    store = SqliteEngineeringMemoryStore(tmp_path / "memory.sqlite3")
    state = IdeGovernanceSessionState(channel_enabled=True)
    try:
        store.initialize(project)
        register_ide_governance(
            state,
            ide_governance_key=_valid_key_hex(),
            client_name="CodeClone VS Code",
            client_version="0.3.0",
        )

        payload = commit_governance(
            state,
            store,
            project_id=project.id,
            root_path=str(root),
            record_id="mem-does-not-exist",
            decision="approve",
            governance_ticket="ticket-missing",
            confirmation_nonce="nonce",
            proof="0" * 64,
            actor="vscode-test",
            protocol=IDE_GOVERNANCE_PROTOCOL_VERSION,
        )
        assert payload["status"] == "not_found"
    finally:
        store.close()


def test_commit_governance_archive_decision(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    project = resolve_project_identity(root)
    store = SqliteEngineeringMemoryStore(tmp_path / "memory.sqlite3")
    state = IdeGovernanceSessionState(channel_enabled=True)
    key_hex = _valid_key_hex()
    try:
        store.initialize(project)
        draft = record_candidate(
            store,
            project=project,
            record_type="change_rationale",
            statement="Archive via IDE governance.",
            subject_path="pkg/mod.py",
            max_candidates=100,
        )
        # archive is allowed only for active records
        approve_record(store, record_id=draft.id, approved_by="maintainer")

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
            decision="archive",
        )
        assert prepared["status"] == "ok"
        nonce = str(prepared["confirmation_nonce"])
        proof = compute_governance_proof(
            bytes.fromhex(key_hex),
            ticket_id=str(prepared["governance_ticket"]),
            record_id=draft.id,
            decision="archive",
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
            decision="archive",
            governance_ticket=str(prepared["governance_ticket"]),
            confirmation_nonce=nonce,
            proof=proof,
            actor="vscode-test",
            protocol=IDE_GOVERNANCE_PROTOCOL_VERSION,
        )
        assert committed["status"] == "ok"
        updated = store.find_record(draft.id)
        assert updated is not None
        assert updated.status == "archived"
    finally:
        store.close()
