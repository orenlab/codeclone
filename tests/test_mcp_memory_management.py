# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import secrets
from pathlib import Path
from typing import cast

import pytest

from codeclone.memory.ide_governance import (
    IDE_GOVERNANCE_PROTOCOL_VERSION,
    compute_governance_proof,
)
from codeclone.surfaces.mcp._session_shared import MCPServiceContractError
from codeclone.surfaces.mcp.service import CodeCloneMCPService

from .memory_fixtures import cli_memory_repo


def test_mcp_manage_memory_record_candidate_and_validate(
    tmp_path: Path,
) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        service = CodeCloneMCPService(history_limit=2)
        recorded = service.manage_engineering_memory(
            root=str(root.resolve()),
            action="record_candidate",
            record_type="change_rationale",
            statement="MCP recorded candidate",
            subject_path="pkg/mod.py",
        )
        assert recorded["action"] == "record_candidate"
        validated = service.manage_engineering_memory(
            root=str(root.resolve()),
            action="validate_claims",
            text="No structural regressions in pkg/mod.py.",
        )
        assert validated["action"] == "validate_claims"
        assert "valid" in validated


def test_mcp_manage_memory_propose_from_receipt(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        service = CodeCloneMCPService(history_limit=4)
        started = service.start_controlled_change(
            root=str(root.resolve()),
            scope={"allowed_files": ["pkg/mod.py"]},
            intent="memory propose",
        )
        intent_id = str(started["intent_id"])
        proposed = service.manage_engineering_memory(
            root=str(root.resolve()),
            action="propose_from_receipt",
            text="Scoped change to pkg/mod.py.",
            intent_id=intent_id,
        )
        candidates = cast("list[object]", proposed.get("memory_candidates"))
        assert isinstance(candidates, list)


def test_mcp_manage_memory_ide_governance_flow(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        service = CodeCloneMCPService(
            history_limit=2,
            ide_governance_channel=True,
        )
        recorded = service.manage_engineering_memory(
            root=str(root.resolve()),
            action="record_candidate",
            record_type="architecture_decision",
            statement="IDE governance via MCP",
        )
        record_id = str(recorded["record_id"])
        key_hex = secrets.token_hex(32)
        registered = service.manage_engineering_memory(
            root=str(root.resolve()),
            action="register_ide_governance",
            ide_governance_key=key_hex,
            client_name="CodeClone VS Code",
            client_version="1.0",
        )
        assert registered["status"] == "ok"
        prepared = service.manage_engineering_memory(
            root=str(root.resolve()),
            action="prepare_governance",
            record_id=record_id,
            decision="approve",
        )
        ticket = str(prepared["governance_ticket"])
        nonce = str(prepared["confirmation_nonce"])
        proof = compute_governance_proof(
            bytes.fromhex(key_hex),
            ticket_id=ticket,
            record_id=record_id,
            decision="approve",
            confirmation_nonce=nonce,
            project_id=str(prepared["project_id"]),
            statement_digest=str(prepared["statement_digest"]),
            protocol=IDE_GOVERNANCE_PROTOCOL_VERSION,
        )
        committed = service.manage_engineering_memory(
            root=str(root.resolve()),
            action="commit_governance",
            record_id=record_id,
            decision="approve",
            governance_ticket=ticket,
            confirmation_nonce=nonce,
            proof=proof,
            protocol=IDE_GOVERNANCE_PROTOCOL_VERSION,
            actor="mcp-test",
        )
        assert committed["status"] == "ok"


def test_mcp_manage_memory_validation_errors(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        service = CodeCloneMCPService(history_limit=2)
        root_str = str(root.resolve())
        with pytest.raises(MCPServiceContractError, match="record_type"):
            service.manage_engineering_memory(
                root=root_str,
                action="record_candidate",
                statement="missing type",
            )
        with pytest.raises(MCPServiceContractError, match="validate_claims requires"):
            service.manage_engineering_memory(
                root=root_str,
                action="validate_claims",
            )
        with pytest.raises(MCPServiceContractError, match="register_ide_governance"):
            service.manage_engineering_memory(
                root=root_str,
                action="register_ide_governance",
                client_name="x",
            )


def test_mcp_manage_memory_rejects_unknown_action(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        service = CodeCloneMCPService(history_limit=2)
        with pytest.raises(
            MCPServiceContractError, match="Unknown manage_engineering_memory"
        ):
            service.manage_engineering_memory(
                root=str(root.resolve()),
                action="not-a-real-action",
            )
