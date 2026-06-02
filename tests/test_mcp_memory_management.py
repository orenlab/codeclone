# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import secrets
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import codeclone.surfaces.mcp._session_memory_mixin as mcp_memory_mixin_mod
from codeclone.memory.exceptions import MemoryCapacityError, MemoryContractError
from codeclone.memory.ide_governance import (
    IDE_GOVERNANCE_PROTOCOL_VERSION,
    compute_governance_proof,
)
from codeclone.surfaces.mcp._session_shared import (
    MCPRunNotFoundError,
    MCPServiceContractError,
)
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


def test_mcp_finish_propose_memory_returns_empty_when_store_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    service = CodeCloneMCPService(history_limit=2)

    def _raise_store(_root_path: Path) -> object:
        raise MCPServiceContractError("missing db")

    monkeypatch.setattr(service, "_open_memory_store", _raise_store)
    payload = service.finish_propose_memory(
        root_path=root,
        changed_files=("pkg/mod.py",),
        claims_text=None,
        review_text=None,
        verification_profile="python_structural",
    )
    assert payload == {}


def test_mcp_finish_propose_memory_happy_path(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        service = CodeCloneMCPService(history_limit=2)
        payload = service.finish_propose_memory(
            root_path=root,
            changed_files=("pkg/mod.py",),
            claims_text="No structural regressions in pkg/mod.py.",
            review_text="reviewed",
            verification_profile="python_structural",
        )
        assert "memory_candidates" in payload
        assert "memory_staleness" in payload
        assert "memory_coverage_delta" in payload


def test_mcp_memory_run_record_rejects_foreign_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        foreign_root = tmp_path / "foreign"
        foreign_root.mkdir()
        service = CodeCloneMCPService(history_limit=2)

        def _fake_get(_run_id: str | None = None) -> Any:
            return SimpleNamespace(root=root)

        monkeypatch.setattr(
            service._runs,
            "get",
            _fake_get,
        )
        with pytest.raises(
            MCPServiceContractError,
            match="different repository root",
        ):
            service._memory_run_record(foreign_root)


def test_mcp_memory_auto_sync_policy_off_returns_none(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        service = CodeCloneMCPService(history_limit=2)
        monkeypatch.setattr(
            mcp_memory_mixin_mod,
            "resolve_memory_config",
            lambda _root: SimpleNamespace(mcp_sync_policy="off"),
        )
        assert service._maybe_auto_sync_memory(root) is None


def test_mcp_open_memory_store_requires_db_after_auto_sync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    service = CodeCloneMCPService(history_limit=2)
    db_path = root / ".cache" / "codeclone" / "memory" / "engineering_memory.sqlite3"
    monkeypatch.setattr(
        mcp_memory_mixin_mod,
        "resolve_memory_db_path",
        lambda _root, _cfg: db_path,
    )
    monkeypatch.setattr(service, "_maybe_auto_sync_memory", lambda _root: None)
    with pytest.raises(MCPServiceContractError, match="database not found"):
        service._open_memory_store(root)


def test_mcp_manage_memory_prepare_and_commit_validation_errors(
    tmp_path: Path,
) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        service = CodeCloneMCPService(history_limit=2)
        root_str = str(root.resolve())
        with pytest.raises(
            MCPServiceContractError,
            match="prepare_governance requires record_id and decision",
        ):
            service.manage_engineering_memory(
                root=root_str,
                action="prepare_governance",
                record_id="mem-1",
            )
        with pytest.raises(
            MCPServiceContractError,
            match="commit_governance requires",
        ):
            service.manage_engineering_memory(
                root=root_str,
                action="commit_governance",
                record_id="mem-1",
                decision="approve",
            )


def test_mcp_manage_memory_converts_memory_exceptions_to_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        service = CodeCloneMCPService(history_limit=2)
        root_str = str(root.resolve())

        monkeypatch.setattr(
            service,
            "_manage_memory_record_candidate",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                MemoryCapacityError("capacity reached")
            ),
        )
        with pytest.raises(MCPServiceContractError, match="capacity reached"):
            service.manage_engineering_memory(
                root=root_str,
                action="record_candidate",
                record_type="change_rationale",
                statement="s",
            )

        monkeypatch.setattr(
            service,
            "_manage_memory_validate_claims",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                MemoryContractError("claims invalid")
            ),
        )
        with pytest.raises(MCPServiceContractError, match="claims invalid"):
            service.manage_engineering_memory(
                root=root_str,
                action="validate_claims",
                text="x",
            )


def test_mcp_memory_scope_resolution_prefers_explicit_scope(tmp_path: Path) -> None:
    service = CodeCloneMCPService(history_limit=2)
    resolved, source = service._resolve_memory_scope_paths(
        scope=("tests/test_a.py",),
        intent_id="intent-123",
    )
    assert resolved == ("tests/test_a.py",)
    assert source == "explicit"


@pytest.mark.parametrize("action", ["approve", "reject", "archive"])
def test_mcp_manage_memory_governance_actions_rejected(
    tmp_path: Path,
    action: str,
) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        service = CodeCloneMCPService(history_limit=2)
        payload = service.manage_engineering_memory(
            root=str(root.resolve()),
            action=action,
        )
        assert payload["status"] == "rejected"


def test_mcp_resolve_memory_scope_paths_and_blast_dependents_edges(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        service = CodeCloneMCPService(history_limit=2)
        assert service._resolve_memory_scope_paths(scope=None, intent_id=None) == (
            (),
            "project_summary",
        )
        with pytest.raises(MCPServiceContractError, match="is not active"):
            service._resolve_memory_scope_paths(scope=None, intent_id="intent-missing")

        assert service._memory_blast_dependents(root, ()) == frozenset()

        monkeypatch.setattr(
            service._runs,
            "get",
            lambda _run_id=None: (_ for _ in ()).throw(MCPRunNotFoundError("missing")),
        )
        assert service._memory_blast_dependents(root, ("pkg/mod.py",)) == frozenset()

        monkeypatch.setattr(
            service._runs,
            "get",
            lambda _run_id=None: SimpleNamespace(root=tmp_path / "foreign"),
        )
        assert service._memory_blast_dependents(root, ("pkg/mod.py",)) == frozenset()

        monkeypatch.setattr(
            service._runs,
            "get",
            lambda _run_id=None: SimpleNamespace(root=root),
        )
        monkeypatch.setattr(
            service,
            "_blast_radius_result",
            lambda **_kwargs: (_ for _ in ()).throw(
                MCPServiceContractError("blast unavailable")
            ),
        )
        assert service._memory_blast_dependents(root, ("pkg/mod.py",)) == frozenset()
