# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import asyncio
import json
import re
import secrets
import sqlite3
from collections.abc import Iterator, Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import codeclone.memory.finish_workflow as finish_workflow
import codeclone.surfaces.mcp._session_memory_mixin as mcp_memory_mixin_mod
from codeclone.memory.coverage import ScopeCoverageReport
from codeclone.memory.exceptions import MemoryCapacityError, MemoryContractError
from codeclone.memory.finish_workflow import FinishMemoryWorkflowResult
from codeclone.memory.governance import (
    GOVERNANCE_RECORD_IMMUTABLE_CODE,
    GOVERNANCE_STALE_AMENDMENT_CODE,
    GOVERNANCE_TICKET_MISMATCH_CODE,
    STATEMENT_ORIGIN_AGENT,
    STATEMENT_ORIGIN_HUMAN_AMENDED,
    record_candidate,
)
from codeclone.memory.ide_governance import (
    AMEND_AND_APPROVE,
    GOVERNANCE_DECISION_PROTOCOL_CODE,
    IDE_GOVERNANCE_AMENDMENT_PROTOCOLS,
    IDE_GOVERNANCE_PROTOCOL_VERSION,
    compute_governance_proof,
)
from codeclone.memory.staleness import StalenessReport
from codeclone.surfaces.mcp._context_governance import (
    passive_drill_down_reachability,
)
from codeclone.surfaces.mcp._session_shared import (
    ExecutionEvent,
    MCPAnalysisRequest,
    MCPRunNotFoundError,
    MCPRunRecord,
    MCPServiceContractError,
    build_served_projection,
    mint_execution_event_id,
)
from codeclone.surfaces.mcp.server import build_mcp_server
from codeclone.surfaces.mcp.service import CodeCloneMCPService

from .memory_fixtures import cli_memory_repo, memory_project_db_paths


def _memory_test_run_record(root: Path, run_id: str) -> MCPRunRecord:
    """A minimal stored run for root-binding tests on the memory surface."""

    return MCPRunRecord(
        run_id=run_id,
        root=root,
        request=MCPAnalysisRequest(root=str(root), respect_pyproject=False),
        comparison_settings=(),
        served_report=build_served_projection({}),
        summary={"run_id": run_id, "health": {"score": 0, "grade": "N/A"}},
        changed_paths=(),
        changed_projection=None,
        func_clones_count=0,
        block_clones_count=0,
        reachable_qualnames=frozenset(),
        coverage_join=None,
        suggestions=(),
        new_func=frozenset(),
        new_block=frozenset(),
        metrics_diff=None,
        execution=ExecutionEvent(
            execution_event_id=mint_execution_event_id(),
            root=root,
            semantic_report_id=run_id,
        ),
    )


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
            subject_path="pkg/mod.py",
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
        with pytest.raises(
            MCPServiceContractError,
            match="Invalid Engineering Memory record_type",
        ):
            service.manage_engineering_memory(
                root=root_str,
                action="record_candidate",
                record_type="decision",
                statement="bad type",
                subject_path="pkg/mod.py",
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


def test_mcp_finish_propose_memory_delegates_with_payload_parity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        service = CodeCloneMCPService(history_limit=2)
        before = ScopeCoverageReport(("pkg/mod.py",), 0, 1, 0, ("pkg/mod.py",))
        after = ScopeCoverageReport(("pkg/mod.py",), 1, 1, 100, ())
        candidates: list[dict[str, object]] = [{"id": "mem-1", "status": "draft"}]
        staleness = StalenessReport(1, 0, 0, {"scope_changed": 1})
        delta: dict[str, object] = {
            "scope_coverage_before": 0,
            "scope_coverage_after": 100,
            "new_uncovered_paths": ["pkg/mod.py"],
        }

        def _execute(*args: Any, **kwargs: Any) -> FinishMemoryWorkflowResult:
            assert kwargs["changed_paths"] == ("pkg/mod.py",)
            assert kwargs["claims_text"] == "claim"
            assert kwargs["review_text"] == "review"
            assert kwargs["verification_profile"] == "python_structural"
            return FinishMemoryWorkflowResult(
                candidates=candidates,
                staleness=staleness,
                coverage_before=before,
                coverage_after=after,
                coverage_delta=delta,
            )

        monkeypatch.setattr(
            finish_workflow,
            "execute_finish_memory_workflow",
            _execute,
        )
        payload = service.finish_propose_memory(
            root_path=root,
            changed_files=("pkg/mod.py",),
            claims_text="claim",
            review_text="review",
            verification_profile="python_structural",
        )

        assert payload == {
            "memory_candidates": candidates,
            "memory_staleness": {
                "records_marked_stale": 1,
                "reasons": {"scope_changed": 1},
            },
            "memory_coverage_delta": delta,
        }


def test_mcp_memory_run_record_rejects_foreign_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        foreign_root = tmp_path / "foreign"
        foreign_root.mkdir()
        service = CodeCloneMCPService(history_limit=2)
        # Real store, real key: the run is held only under `root`, so a lookup
        # bound to `foreign_root` refuses with the typed rejection instead of
        # resolving globally and post-checking the root.
        service._runs.register(_memory_test_run_record(root, "memoryrun1234567"))
        with pytest.raises(
            MCPServiceContractError,
            match="different repository root",
        ):
            service._memory_run_record(foreign_root, "memoryrun1234567")


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
    db_path = root / ".codeclone" / "memory" / "engineering_memory.sqlite3"
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
        with pytest.raises(
            MCPServiceContractError, match="requires scope or intent_id"
        ):
            service._resolve_memory_scope_paths(scope=None, intent_id=None)
        with pytest.raises(MCPServiceContractError, match="is not active"):
            service._resolve_memory_scope_paths(scope=None, intent_id="intent-missing")

        assert service._memory_blast_dependents(root, ()) == frozenset()

        monkeypatch.setattr(
            service._runs,
            "resolve_any_root",
            lambda _run_id=None: (_ for _ in ()).throw(MCPRunNotFoundError("missing")),
        )
        assert service._memory_blast_dependents(root, ("pkg/mod.py",)) == frozenset()

        monkeypatch.setattr(
            service._runs,
            "resolve_any_root",
            lambda _run_id=None: SimpleNamespace(root=tmp_path / "foreign"),
        )
        assert service._memory_blast_dependents(root, ("pkg/mod.py",)) == frozenset()

        monkeypatch.setattr(
            service._runs,
            "resolve_any_root",
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


def test_mcp_get_relevant_memory_requires_scope_intent_or_symbols(
    tmp_path: Path,
) -> None:
    service = CodeCloneMCPService(history_limit=2)
    with pytest.raises(
        MCPServiceContractError, match="requires scope, intent_id, or symbols"
    ):
        service.get_relevant_memory(root=str(tmp_path.resolve()))


def test_mcp_get_relevant_memory_symbols_only(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, project, _store):
        service = CodeCloneMCPService(history_limit=2)
        payload = service.get_relevant_memory(
            root=str(root.resolve()),
            symbols=["codeclone.memory"],
            max_records=5,
        )
        assert payload["scope_resolved_from"] == "symbols"
        assert payload["project_id"] == project.id


def test_mcp_get_memory_projection_page_continues_relevant_memory_tail(
    tmp_path: Path,
) -> None:
    with cli_memory_repo(tmp_path, with_draft=True) as (root, _project, _store):
        service = CodeCloneMCPService(history_limit=2)
        payload = service.get_relevant_memory(
            root=str(root.resolve()),
            scope=["pkg/mod.py"],
            max_records=1,
        )
        continuation = cast("dict[str, object]", payload["continuation"])
        lanes = cast("dict[str, object]", continuation["lanes"])
        records = cast("dict[str, object]", lanes["records"])
        page_ref = cast("dict[str, object]", records["page"])
        page = service.get_memory_projection_page(
            root=str(root.resolve()),
            cursor=str(page_ref["cursor"]),
            page_size=10,
        )

    assert page["status"] == "ok"
    assert page["lane"] == "records"
    assert page["response_complete"] is True
    assert cast("list[object]", page["items"])
    governance = cast("dict[str, object]", page["context_governance"])
    response = cast("dict[str, object]", governance["response"])
    assert {
        "tool": response["tool"],
        "policy": response["evidence_policy"],
        "mode": governance["mode"],
        "enforcement": governance["enforcement"],
        "truncated": governance["truncated"],
    } == {
        "tool": "get_memory_projection_page",
        "policy": "digest_bound_continuation_page",
        "mode": "observe",
        "enforcement": {
            "response_budget": False,
            "nested_budget": False,
            "omission": False,
        },
        "truncated": False,
    }


def test_mcp_get_relevant_memory_compact_enforces_response_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        mcp_memory_mixin_mod,
        "DEFAULT_RESPONSE_CONTEXT_UNIT_LIMIT",
        1700,
    )
    with cli_memory_repo(tmp_path, with_draft=False) as (root, project, store):
        for index in range(8):
            record_candidate(
                store,
                project=project,
                record_type="change_rationale",
                subject_path="pkg/mod.py",
                max_candidates=20,
                statement=f"budgeted memory record {index} " + "s" * 400,
            )
        service = CodeCloneMCPService(history_limit=2)
        payload = service.get_relevant_memory(
            root=str(root.resolve()),
            scope=["pkg/mod.py"],
            max_records=6,
        )

    governance = _nested_dict(payload, "context_governance")
    records_omitted = _nested_dict(governance, "omitted", "records")
    page = _nested_dict(payload, "continuation", "lanes", "records", "page")
    estimated = governance["estimated"]
    limit = governance["limit"]
    record_count = payload["record_count"]

    assert governance["mode"] == "partial_enforce"
    assert cast("dict[str, bool]", governance["enforcement"])["response_budget"]
    assert isinstance(estimated, int)
    assert isinstance(limit, int)
    assert estimated <= limit
    assert isinstance(record_count, int)
    assert record_count < 6
    assert records_omitted["reason"] == "response_budget"
    assert page["offset"] == record_count


def _nested_dict(payload: dict[str, object], *keys: str) -> dict[str, object]:
    current: object = payload
    for key in keys:
        assert isinstance(current, dict)
        current = current[key]
    return cast("dict[str, object]", current)


def test_mcp_get_relevant_memory_wraps_memory_contract_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        service = CodeCloneMCPService(history_limit=2)
        monkeypatch.setattr(
            "codeclone.surfaces.mcp._session_memory_mixin.get_relevant_memory",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                MemoryContractError("scope path invalid")
            ),
        )
        with pytest.raises(MCPServiceContractError, match="scope path invalid"):
            service.get_relevant_memory(
                root=str(root.resolve()),
                scope=("pkg/mod.py",),
            )


def test_mcp_manage_memory_governance_requires_a_full_record_id(
    tmp_path: Path,
) -> None:
    """D5: read paths resolve short ids, write paths do not.

    Approving a prefix-resolved target is a wrong-target hazard, so governance
    keeps exact matching. The failure must be the plain exact-lookup miss —
    proof that no prefix scan was attempted on a mutation path.
    """
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        service = CodeCloneMCPService(
            history_limit=2,
            ide_governance_channel=True,
        )
        root_str = str(root.resolve())
        recorded = service.manage_engineering_memory(
            root=root_str,
            action="record_candidate",
            record_type="architecture_decision",
            statement="governance rejects short ids",
            subject_path="pkg/mod.py",
        )
        record_id = str(recorded["record_id"])
        short_id = record_id[: len("mem-") + 8]
        assert short_id != record_id
        service.manage_engineering_memory(
            root=root_str,
            action="register_ide_governance",
            ide_governance_key=secrets.token_hex(32),
            client_name="CodeClone VS Code",
            client_version="1.0",
        )
        refused = service.manage_engineering_memory(
            root=root_str,
            action="prepare_governance",
            record_id=short_id,
            decision="approve",
        )
        assert refused["status"] == "not_found"
        assert refused["record_id"] == short_id
        # The full id still works, so the refusal is about the short form.
        prepared = service.manage_engineering_memory(
            root=root_str,
            action="prepare_governance",
            record_id=record_id,
            decision="approve",
        )
        assert prepared["status"] == "ok"


def test_mcp_manage_memory_promote_experience_requires_a_full_id(
    tmp_path: Path,
) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        service = CodeCloneMCPService(history_limit=2)
        with pytest.raises(MCPServiceContractError, match="not found"):
            service.manage_engineering_memory(
                root=str(root.resolve()),
                action="promote_experience",
                experience_id="exp-abcd1234",
            )


def test_mcp_manage_memory_propose_scope_check_variants(tmp_path: Path) -> None:
    """The declared scope files the proposal; without one there is nothing to file.

    ``propose_from_receipt`` records only text the caller authored. The live
    intent's declared scope elects the subject path that text is filed against,
    so with no intent (and no text) the batch is empty, and with both the
    candidate exists and is subjected to the scoped file. It used to also mint a
    contentless ``module_role`` echo reading "Patch touched scope includes
    <path>; review module role after change." — the string this pin read. That
    echo is gone; the pin now reads the surviving, substantive candidate and
    asserts the echo does not come back.
    """

    from codeclone.surfaces.mcp._session_shared import MCPAnalysisRequest

    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        service = CodeCloneMCPService(history_limit=4)

        bare = service.manage_engineering_memory(
            root=str(root.resolve()),
            action="propose_from_receipt",
            text=None,
        )
        assert bare.get("memory_candidates") == []

        service.analyze_repository(
            MCPAnalysisRequest(
                root=str(root.resolve()),
                respect_pyproject=False,
            )
        )
        started = service.start_controlled_change(
            root=str(root.resolve()),
            scope={"allowed_files": ["pkg/mod.py"]},
            intent="memory propose scope",
        )
        assert started["status"] == "active"
        scoped = service.manage_engineering_memory(
            root=str(root.resolve()),
            action="propose_from_receipt",
            text="Scoped change to pkg/mod.py.",
            intent_id=str(started["intent_id"]),
        )
        candidates = cast("list[dict[str, object]]", scoped["memory_candidates"])
        statements = [str(item["statement"]) for item in candidates]
        types = {str(item["type"]) for item in candidates}
    assert types == {"change_rationale"}
    assert any("Scoped change to pkg/mod.py." in statement for statement in statements)
    assert not any("review module role after change" in text for text in statements)


def test_mcp_record_candidate_markdown_security_reject_is_typed(
    tmp_path: Path,
) -> None:
    """Security-class markdown rejects surface as typed contract errors with
    the in-band procedure (next_step + help mention) intact."""
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        service = CodeCloneMCPService(history_limit=2)
        with pytest.raises(MCPServiceContractError, match="memory_md_image") as excinfo:
            service.manage_engineering_memory(
                root=str(root.resolve()),
                action="record_candidate",
                record_type="risk_note",
                statement="Probe ![shot](https://evil.example/x.png) captured.",
                subject_path="pkg/mod.py",
            )
        message = str(excinfo.value)
        assert "next_step" in message
        assert 'help(topic="engineering_memory")' in message


def test_mcp_record_candidate_surfaces_markdown_warnings(tmp_path: Path) -> None:
    """Discipline-class issues warn in the response instead of rejecting."""
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        service = CodeCloneMCPService(history_limit=2)
        recorded = service.manage_engineering_memory(
            root=str(root.resolve()),
            action="record_candidate",
            record_type="risk_note",
            statement="# Wrong level title\nbody of the durable fact",
            subject_path="pkg/mod.py",
        )
        assert recorded["status"] == "draft"
        warnings = cast("list[str]", recorded.get("warnings", []))
        assert any("memory_md_heading_level" in item for item in warnings)


def test_mcp_propose_from_receipt_warns_on_batch_mean(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The average-size gate rides propose batches: mean > limit warns."""
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        service = CodeCloneMCPService(history_limit=2)
        oversized = "x" * 260

        def fake_propose(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
            return [
                {
                    "id": "a",
                    "type": "risk_note",
                    "status": "draft",
                    "statement": oversized,
                },
                {
                    "id": "b",
                    "type": "risk_note",
                    "status": "draft",
                    "statement": oversized,
                },
            ]

        monkeypatch.setattr(
            "codeclone.memory.ingest.receipts.propose_memory_from_finish_payload",
            fake_propose,
        )
        proposed = service.manage_engineering_memory(
            root=str(root.resolve()),
            action="propose_from_receipt",
            text="claims text",
        )
        warnings = cast("list[str]", proposed.get("warnings", []))
        assert any("batch mean" in item.lower() for item in warnings)


def test_mcp_get_relevant_memory_envelope_states_the_level_it_returned(
    tmp_path: Path,
) -> None:
    """`normal` is an alias of `compact`, and the response says so, once.

    The envelope's ``response.detail_level`` echoed the raw request, so one
    message said ``normal`` there and ``compact`` in the payload under the
    same field name. The envelope now describes the response; the request
    survives, named as a request, in ``detail_level_resolution``.
    """

    with cli_memory_repo(tmp_path, with_draft=False) as (root, project, store):
        record_candidate(
            store,
            project=project,
            record_type="change_rationale",
            subject_path="pkg/mod.py",
            max_candidates=20,
            statement="Aliased detail level must not read as two answers.",
        )
        service = CodeCloneMCPService(history_limit=2)
        payload = service.get_relevant_memory(
            root=str(root.resolve()),
            scope=["pkg/mod.py"],
            max_records=6,
            detail_level="normal",
        )

    records = payload["records"]
    assert isinstance(records, list)
    assert records, "empty record lane: the assertions below would compare nothing"
    assert payload["detail_level"] == "compact"
    response = _nested_dict(payload, "context_governance", "response")
    assert response["detail_level"] == "compact"
    resolution = _nested_dict(payload, "detail_level_resolution")
    assert resolution["requested"] == "normal"
    assert resolution["effective"] == "compact"
    assert resolution["reason"] == "requested_level_is_an_alias_of_compact"
    assert "detail_level='full'" in str(resolution["next_step"])
    first = records[0]
    assert isinstance(first, dict)
    assert isinstance(first["created_at_utc"], str)
    assert isinstance(first["updated_at_utc"], str)


# --------------------------------------------------------------------------
# Defect 1 — query_engineering_memory published no context_governance at all
# --------------------------------------------------------------------------


_ENVELOPE_BASE_KEYS: frozenset[str] = frozenset(
    {
        "contract_version",
        "estimator",
        "limit",
        "estimated",
        "truncated",
        "mandatory_overflow",
        "mode",
        "enforcement",
        "enforcement_blocked",
        "response",
    }
)


def test_mcp_query_engineering_memory_publishes_the_sibling_envelope(
    tmp_path: Path,
) -> None:
    """A bounded memory response MUST say what it measured and against what.

    ``query_engineering_memory`` shipped with no ``context_governance`` at
    all: no contract version, no estimator, no limit. A caller could not tell
    which contract the answer was written against, nor how close it came to
    the budget. The envelope is the one ``get_relevant_memory`` already
    publishes -- the same dialect, read off the sibling here so the two cannot
    drift into describing the same thing differently.
    """
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        service = CodeCloneMCPService(history_limit=2)
        queried = service.query_engineering_memory(
            root=str(root.resolve()),
            mode="for_path",
            path="pkg/mod.py",
        )
        sibling_payload = service.get_relevant_memory(
            root=str(root.resolve()),
            scope=["pkg/mod.py"],
        )

    governance = _nested_dict(queried, "context_governance")
    sibling = _nested_dict(sibling_payload, "context_governance")
    response = _nested_dict(governance, "response")
    estimated = governance["estimated"]

    assert set(governance) == _ENVELOPE_BASE_KEYS
    assert {
        "contract_version": governance["contract_version"],
        "estimator": governance["estimator"],
        "limit": governance["limit"],
    } == {
        "contract_version": sibling["contract_version"],
        "estimator": sibling["estimator"],
        "limit": sibling["limit"],
    }
    assert response["tool"] == "query_engineering_memory"
    assert response["mode"] == "for_path"
    assert isinstance(estimated, int)
    assert estimated > 0


def test_mcp_query_engineering_memory_envelope_names_the_capped_tail(
    tmp_path: Path,
) -> None:
    """A response that omits MUST say it omits, why, and where the rest is.

    ``max_results`` caps the list and the payload flag says only that a tail
    exists. The envelope has to carry the omission the way every other
    governed response does, and the continuation index has to name a route the
    caller can actually execute -- here a wider re-query, because this surface
    mints no cursor.
    """
    with cli_memory_repo(tmp_path, with_draft=False) as (root, project, store):
        for index in range(4):
            record_candidate(
                store,
                project=project,
                record_type="change_rationale",
                subject_path="pkg/mod.py",
                max_candidates=20,
                statement=f"capped tail record {index}",
            )
        service = CodeCloneMCPService(history_limit=2)
        payload = service.query_engineering_memory(
            root=str(root.resolve()),
            mode="for_path",
            path="pkg/mod.py",
            max_results=1,
        )

    body = _nested_dict(payload, "payload")
    governance = _nested_dict(payload, "context_governance")
    omitted = _nested_dict(governance, "omitted", "records")
    continuation = _nested_dict(payload, "_continuation")
    lanes = cast("list[dict[str, object]]", continuation["lanes"])

    assert body["truncated"] is True
    assert governance["truncated"] is True
    assert {
        "shown": omitted["shown"],
        "reason": omitted["reason"],
        "evaluation": omitted["evaluation"],
    } == {
        "shown": 1,
        "reason": "max_results_cap",
        "evaluation": "unmeasured",
    }
    assert "total" not in omitted
    assert "omitted" not in omitted
    assert [lane["lane"] for lane in lanes] == ["records"]
    assert lanes[0]["tool"] == "query_engineering_memory"
    assert "max_results" in str(lanes[0]["route"])


def test_mcp_query_engineering_memory_envelope_claims_nothing_when_complete(
    tmp_path: Path,
) -> None:
    """The opposite boundary: a complete answer MUST NOT report an omission.

    A truncation flag that is always on is as useless as one that is never
    on. This pins the other side, so a fix that hard-codes the omission dies
    here.
    """
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        service = CodeCloneMCPService(history_limit=2)
        payload = service.query_engineering_memory(
            root=str(root.resolve()),
            mode="for_path",
            path="pkg/mod.py",
            max_results=20,
        )

    body = _nested_dict(payload, "payload")
    governance = _nested_dict(payload, "context_governance")

    assert body["truncated"] is False
    assert governance["truncated"] is False
    assert "omitted" not in governance
    assert "_continuation" not in payload


# --------------------------------------------------------------------------
# Defect 3 — a published continuation route the server refuses
# --------------------------------------------------------------------------


_ROUTE_PATTERN = re.compile(r"^(?P<tool>[A-Za-z_][A-Za-z0-9_]*)\((?P<args>.*)\)$")


def _published_call(value: object) -> re.Match[str] | None:
    """Decide whether a published value IS a call, from its shape alone.

    A key name is a convention, and a convention cannot carry a semantic
    question. Selecting keys that end in ``route`` left a broken route
    published as ``tail_lookup_path`` invisible to the rule -- the same hole
    the table itself had, one level up: a name standing in for a meaning, and
    blind by construction to anything named outside it.

    The value decides instead. What parses as ``tool(args)`` is an instruction
    to call something, whatever the key is called, and the status words, dotted
    payload paths and prose identity recipes that share this table are left
    alone because they are not calls.
    """

    if not isinstance(value, str) or not value.strip():
        return None
    return _ROUTE_PATTERN.match(value.strip())


def _parse_published_route(route: str) -> tuple[str, frozenset[str]]:
    """Split a published route into the tool it names and the arguments it names."""

    match = _published_call(route)
    assert match is not None, route
    body = match.group("args").strip()
    named = {
        part.split("=", 1)[0].strip()
        for part in body.split(",")
        if "=" in part and part.strip()
    }
    return match.group("tool"), frozenset(named)


def _structured_result(result: object) -> dict[str, object]:
    if isinstance(result, dict):
        return cast("dict[str, object]", result)
    assert isinstance(result, tuple)
    payload = result[1]
    assert isinstance(payload, dict)
    return cast("dict[str, object]", payload)


def _dotted(payload: Mapping[str, object], path: str) -> object:
    current: object = payload
    for key in path.split("."):
        assert isinstance(current, Mapping), path
        current = current[key]
    return current


@pytest.mark.parametrize(
    ("value", "is_call"),
    [
        ("get_memory_projection_page(root=..., cursor=...)", True),
        ("query_engineering_memory(root=..., mode='get', record_id=...)", True),
        ("get_review_receipt(root=..., receipt_digest=..., format='structured')", True),
        ("available", False),
        ("blocked", False),
        ("receipt.receipt", False),
        ("patch_trail", False),
        ("memory continuation cursor + lane identity digest + request digest", False),
        ("blast_artifact_id + run_id + projection_digest", False),
        ("   ", False),
        (True, False),
        (None, False),
    ],
)
def test_published_value_is_a_call_only_when_it_parses_as_one(
    value: object, is_call: bool
) -> None:
    """The mirror boundary: widening selection must stop at values that are not calls.

    Selecting by shape decides what the schema rule is allowed to resolve. Erring
    the other way is the mirror defect: a status word, a dotted payload path, a
    bare lane name or a prose identity recipe swept in as a route would fail to
    resolve to any tool and redden rows that are perfectly correct. The table
    carries all four kinds beside its routes, so the classifier has to admit
    calls and leave the rest alone.
    """

    assert (_published_call(value) is not None) is is_call


def test_published_drill_down_routes_name_exactly_what_the_server_accepts() -> None:
    """Every published route MUST be complete AND callable against its tool.

    One rule, both boundaries, re-derived from the live ``list_tools()`` schema
    rather than from these spellings: a route has to name every argument the
    registered tool marks required -- or the server refuses the very call the
    surface just instructed -- and it must not name an argument the tool does
    not accept, which the server refuses for the opposite reason.

    The rule reads every value the table publishes, selected by shape rather
    than by key name or by a named subset of rows. Both narrower selections had
    the same hole: naming the rows hid four routes that omitted ``root``, and
    keying on ``endswith("route")`` hid a broken route published under
    ``tail_lookup_path``. Each row is verified individually -- every call-shaped
    value reaches the schema comparison, and each one is measured against a tool
    that actually demands and accepts arguments, so no row passes vacuously.
    """
    pytest.importorskip("mcp.server.fastmcp")
    server = build_mcp_server(history_limit=2)
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    reachability = passive_drill_down_reachability()

    published = {
        f"{entry}.{key}": str(value)
        for entry, body in sorted(reachability.items())
        for key, value in sorted(body.items())
        if _published_call(value) is not None
    }
    assert published, reachability

    unserved: dict[str, dict[str, list[str]]] = {}
    checked: dict[str, tuple[frozenset[str], frozenset[str]]] = {}
    for label, route in published.items():
        tool_name, named = _parse_published_route(route)
        assert tool_name in tools, route
        schema = tools[tool_name].inputSchema
        required = frozenset(cast("list[str]", schema["required"]))
        accepted = frozenset(cast("dict[str, object]", schema["properties"]))
        checked[label] = (required, accepted)
        defect = {
            "missing_required": sorted(required - named),
            "not_accepted": sorted(named - accepted),
        }
        if any(defect.values()):
            unserved[label] = defect

    assert unserved == {}
    assert set(checked) == set(published), sorted(set(published) - set(checked))
    assert all(required and accepted for required, accepted in checked.values()), (
        checked
    )


def test_published_memory_tail_route_is_callable_exactly_as_published(
    tmp_path: Path,
) -> None:
    """The effected behaviour: a caller who obeys the response MUST be served.

    Not "the parameter is accepted" -- the whole published loop, over the real
    MCP tool surface: retrieve, read the continuation the response advertises,
    take the cursor from the ``cursor_path`` it names, call the tool named by
    ``route`` with exactly the arguments that route names, and get a page.
    """
    pytest.importorskip("mcp.server.fastmcp")
    with cli_memory_repo(tmp_path, with_draft=False) as (root, project, store):
        for index in range(4):
            record_candidate(
                store,
                project=project,
                record_type="change_rationale",
                subject_path="pkg/mod.py",
                max_candidates=20,
                statement=f"published route record {index}",
            )
        root_str = str(root.resolve())
        server = build_mcp_server(history_limit=2)
        retrieved = _structured_result(
            asyncio.run(
                server.call_tool(
                    "get_relevant_memory",
                    {"root": root_str, "scope": ["pkg/mod.py"], "max_records": 1},
                )
            )
        )
        lanes = cast(
            "list[dict[str, object]]",
            _dotted(retrieved, "_continuation.lanes"),
        )
        lane = next(lane for lane in lanes if lane["lane"] == "records")
        tool_name, named = _parse_published_route(str(lane["route"]))
        cursor = _dotted(retrieved, str(lane["cursor_path"]))
        available: dict[str, object] = {"root": root_str, "cursor": cursor}
        assert named <= set(available), named
        page = _structured_result(
            asyncio.run(
                server.call_tool(tool_name, {key: available[key] for key in named})
            )
        )

    assert lane["tool"] == tool_name
    assert page["status"] == "ok"
    assert page["lane"] == "records"
    assert cast("list[object]", page["items"])


def test_query_engineering_memory_tail_route_is_callable_exactly_as_published(
    tmp_path: Path,
) -> None:
    """The capped-tail route MUST be executable as published, and reach the tail.

    Same law as the cursor route next door: the surface may only name a way
    forward it can honour. Here the way forward is a wider re-query, so the
    pin drives it -- parse the published route, check it against the tool's
    own required arguments, execute it, and see the record the capped answer
    withheld.
    """
    pytest.importorskip("mcp.server.fastmcp")
    with cli_memory_repo(tmp_path, with_draft=False) as (root, project, store):
        for index in range(4):
            record_candidate(
                store,
                project=project,
                record_type="change_rationale",
                subject_path="pkg/mod.py",
                max_candidates=20,
                statement=f"published requery record {index}",
            )
        root_str = str(root.resolve())
        server = build_mcp_server(history_limit=2)
        tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
        capped = _structured_result(
            asyncio.run(
                server.call_tool(
                    "query_engineering_memory",
                    {
                        "root": root_str,
                        "mode": "for_path",
                        "path": "pkg/mod.py",
                        "max_results": 1,
                    },
                )
            )
        )
        lanes = cast("list[dict[str, object]]", _dotted(capped, "_continuation.lanes"))
        tool_name, named = _parse_published_route(str(lanes[0]["route"]))
        required = frozenset(
            cast("list[str]", tools[tool_name].inputSchema["required"])
        )
        widened = _structured_result(
            asyncio.run(
                server.call_tool(
                    tool_name,
                    {
                        "root": root_str,
                        "mode": "for_path",
                        "path": "pkg/mod.py",
                        "max_results": 20,
                    },
                )
            )
        )

    capped_count = _dotted(capped, "payload.record_count")
    widened_count = _dotted(widened, "payload.record_count")

    assert tool_name == "query_engineering_memory"
    assert required <= named, sorted(required - named)
    assert capped_count == 1
    assert isinstance(widened_count, int)
    assert widened_count > 1
    assert _dotted(widened, "payload.truncated") is False


def test_mcp_query_engineering_memory_envelope_attributes_the_trajectory_lane(
    tmp_path: Path,
) -> None:
    """Lane attribution MUST follow the answer, not a default.

    ``records`` is the lane most modes cap, so a selector that always said
    ``records`` would look right on every record-shaped mode. Reachability is
    established in two measured halves rather than asserted: the live router
    is asked which count key a trajectory mode publishes beside ``truncated``,
    and the selector is then given exactly that shape with the flag raised.
    Neither half is a reading of the source.
    """
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        service = CodeCloneMCPService(history_limit=2)
        router_shape = service.query_engineering_memory(
            root=str(root.resolve()),
            mode="trajectory_search",
            query="no trajectory answers this",
            max_results=1,
        )

    body = _nested_dict(router_shape, "payload")
    capped = dict(body)
    capped["truncated"] = True
    omitted = mcp_memory_mixin_mod._memory_query_omitted(
        capped,
        mode="trajectory_search",
        max_results=1,
    )
    lane = cast("dict[str, object]", omitted["trajectories"])

    assert "trajectory_count" in body
    assert "record_count" not in body
    assert body["truncated"] is False
    assert _nested_dict(router_shape, "context_governance")["truncated"] is False
    assert set(omitted) == {"trajectories"}
    assert lane["shown"] == body["trajectory_count"]
    assert lane["reason"] == "max_results_cap"


# ===========================================================================
# The amendment bridge, reached the way an IDE client reaches it.
#
# tests/test_memory_ide_governance*.py drive codeclone.memory directly and
# prove the record layer and the governance channel. They cannot prove that an
# IDE client can reach either one, because they never cross the MCP surface.
# The dispatch on that surface passes ``decision`` and ``statement`` straight
# through, so ``amend_and_approve`` appears nowhere in it by name -- grep is
# blind here by construction, and a live round trip is the only honest probe.
#
# These live in this module, rather than in one of their own, because the
# phase 39S boundary allowlist already carries this module's edges to
# codeclone.memory.governance and codeclone.memory.ide_governance. The policy
# is shrink-only: a new module would have opened a new r4->r2p edge for the
# same imports. Everything the store API would otherwise provide is read or
# written here over raw sqlite, on a separate connection.
# ===========================================================================

_OLD_WIRE = 2
_AMENDMENT_WIRE = min(IDE_GOVERNANCE_AMENDMENT_PROTOCOLS)
_HUMAN_WORDING = "Human-corrected wording published from the approval view."


def _governed_row(db_path: Path, record_id: str) -> tuple[str, str, int]:
    """Committed state on a SEPARATE connection: status, statement, revisions.

    The service opens and closes its own store per call, so asserting against
    the service's echo would be reading the writer's own account of itself.
    This reads what a second process would find on disk.
    """
    conn = sqlite3.connect(db_path)
    try:
        status, statement = conn.execute(
            "SELECT status, statement FROM memory_records WHERE id=?",
            (record_id,),
        ).fetchone()
        (revisions,) = conn.execute(
            "SELECT COUNT(*) FROM memory_revisions WHERE memory_id=?",
            (record_id,),
        ).fetchone()
        return str(status), str(statement), int(revisions)
    finally:
        conn.close()


def _foreign_write(db_path: Path, sql: str, params: tuple[object, ...]) -> None:
    """A second writer, on its own connection, committing before we commit."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


class _GovernedSurface:
    """One registered IDE governance channel, driven only through MCP."""

    def __init__(self, root: Path, db_path: Path, *, channel: bool = True) -> None:
        self.root = str(root.resolve())
        self.db_path = db_path
        self.service = CodeCloneMCPService(
            history_limit=4,
            ide_governance_channel=channel,
        )
        self.key_hex = secrets.token_hex(32)
        self._drafts = 0
        self.registered = self.call(
            action="register_ide_governance",
            ide_governance_key=self.key_hex,
            client_name="CodeClone VS Code",
            client_version="0.3.0",
        )

    def call(self, **params: object) -> dict[str, object]:
        return self.service.manage_engineering_memory(root=self.root, **params)

    def draft(self, statement: str | None = None) -> str:
        # Candidate identity folds the statement in, so each draft needs its
        # own wording or the second write is refused as a duplicate.
        self._drafts += 1
        recorded = self.call(
            action="record_candidate",
            record_type="architecture_decision",
            statement=statement or f"Agent wording {self._drafts} awaiting review.",
            subject_path="pkg/mod.py",
        )
        return str(recorded["record_id"])

    def prepare(
        self,
        record_id: str,
        decision: str = AMEND_AND_APPROVE,
    ) -> dict[str, object]:
        return self.call(
            action="prepare_governance",
            record_id=record_id,
            decision=decision,
        )

    def pending(
        self,
        statement: str,
        decision: str = AMEND_AND_APPROVE,
    ) -> tuple[str, dict[str, object]]:
        """A draft, plus a ticket prepared over exactly that wording."""
        record_id = self.draft(statement)
        return record_id, self.prepare(record_id, decision)

    def commit(
        self,
        record_id: str,
        prepared: dict[str, object],
        *,
        decision: str = AMEND_AND_APPROVE,
        protocol: int = _AMENDMENT_WIRE,
        statement: str | None = _HUMAN_WORDING,
        actor: str = "den",
    ) -> dict[str, object]:
        ticket = str(prepared["governance_ticket"])
        nonce = str(prepared["confirmation_nonce"])
        return self.call(
            action="commit_governance",
            record_id=record_id,
            decision=decision,
            governance_ticket=ticket,
            confirmation_nonce=nonce,
            proof=compute_governance_proof(
                bytes.fromhex(self.key_hex),
                ticket_id=ticket,
                record_id=record_id,
                decision=decision,
                confirmation_nonce=nonce,
                project_id=str(prepared["project_id"]),
                statement_digest=str(prepared["statement_digest"]),
                protocol=protocol,
            ),
            protocol=protocol,
            actor=actor,
            statement=statement,
        )

    def settled(self, record_id: str) -> tuple[str, str, int]:
        return _governed_row(self.db_path, record_id)


@pytest.fixture
def governed(tmp_path: Path) -> Iterator[_GovernedSurface]:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        _identity, db_path = memory_project_db_paths(root)
        yield _GovernedSurface(root, db_path)


# --- 1. the whole round trip ----------------------------------------------


def test_amend_and_approve_completes_through_the_mcp_surface(
    governed: _GovernedSurface,
) -> None:
    """Edit and approve in one operation, as the maintainer performs it."""
    record_id = governed.draft("Agent wording the human will correct.")
    assert governed.settled(record_id) == (
        "draft",
        "Agent wording the human will correct.",
        0,
    )

    prepared = governed.prepare(record_id)
    assert prepared["status"] == "ok"
    assert prepared["statement_origin"] == STATEMENT_ORIGIN_AGENT

    committed = governed.commit(record_id, prepared)

    assert committed["status"] == "ok"
    assert committed["record_status"] == "active"
    assert committed["statement_origin"] == STATEMENT_ORIGIN_HUMAN_AMENDED
    assert committed["approved_by"] == "den"

    receipt = committed["proof"]
    assert isinstance(receipt, dict)
    assert receipt["operation"] == AMEND_AND_APPROVE
    assert receipt["protocol"] == _AMENDMENT_WIRE
    assert receipt["shown_statement_digest"] == prepared["statement_digest"]
    assert receipt["submitted_statement_digest"] != prepared["statement_digest"]
    assert receipt["expected_revision_matched"] is True

    status, statement, revisions = governed.settled(record_id)
    assert (status, statement) == ("active", _HUMAN_WORDING)
    assert revisions == 1


def test_the_amended_record_keeps_the_agent_as_its_author(
    governed: _GovernedSurface,
) -> None:
    """Two provenance facts, deliberately not one.

    ``created_by`` is immutable historical fact about who produced the
    observation; ``statement_origin`` answers whose words the CURRENT wording
    is. A test that only checked the origin would let the author be
    overwritten by the person who edited a sentence.
    """
    record_id = governed.draft()
    governed.commit(record_id, governed.prepare(record_id))

    conn = sqlite3.connect(governed.db_path)
    try:
        created_by, approved_by, payload_json = conn.execute(
            "SELECT created_by, approved_by, payload_json "
            "FROM memory_records WHERE id=?",
            (record_id,),
        ).fetchone()
    finally:
        conn.close()

    assert created_by == "agent"
    assert approved_by == "den"
    assert json.loads(payload_json)["statement_origin"] == (
        STATEMENT_ORIGIN_HUMAN_AMENDED
    )


def test_the_registered_tool_forwards_the_amended_wording(tmp_path: Path) -> None:
    """The service is not the last mile: the tool signature is.

    A tool that accepted ``statement`` and dropped it on the floor would leave
    every service-level test here green while publishing the agent's original
    wording. So this one round-trips through the registered FastMCP tool.
    """
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        _identity, db_path = memory_project_db_paths(root)
        mcp = build_mcp_server(history_limit=2, ide_governance_channel=True)
        root_str = str(root.resolve())
        key_hex = secrets.token_hex(32)

        def call(**params: object) -> dict[str, object]:
            _content, payload = asyncio.run(
                mcp.call_tool(
                    "manage_engineering_memory",
                    {"root": root_str, **params},
                )
            )
            assert isinstance(payload, dict)
            return payload

        recorded = call(
            action="record_candidate",
            record_type="architecture_decision",
            statement="Agent wording reaching the tool layer.",
            subject_path="pkg/mod.py",
        )
        record_id = str(recorded["record_id"])
        assert (
            call(
                action="register_ide_governance",
                ide_governance_key=key_hex,
                client_name="CodeClone VS Code",
                client_version="0.3.0",
            )["status"]
            == "ok"
        )
        prepared = call(
            action="prepare_governance",
            record_id=record_id,
            decision=AMEND_AND_APPROVE,
        )
        ticket = str(prepared["governance_ticket"])
        nonce = str(prepared["confirmation_nonce"])
        committed = call(
            action="commit_governance",
            record_id=record_id,
            decision=AMEND_AND_APPROVE,
            governance_ticket=ticket,
            confirmation_nonce=nonce,
            proof=compute_governance_proof(
                bytes.fromhex(key_hex),
                ticket_id=ticket,
                record_id=record_id,
                decision=AMEND_AND_APPROVE,
                confirmation_nonce=nonce,
                project_id=str(prepared["project_id"]),
                statement_digest=str(prepared["statement_digest"]),
                protocol=_AMENDMENT_WIRE,
            ),
            protocol=_AMENDMENT_WIRE,
            actor="den",
            statement=_HUMAN_WORDING,
        )

        assert committed["status"] == "ok"
        assert _governed_row(db_path, record_id)[:2] == ("active", _HUMAN_WORDING)


# --- 2. atomicity survives the surface ------------------------------------


def test_a_failure_under_the_surface_call_leaves_the_record_untouched(
    governed: _GovernedSurface,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Injected between the MCP call and the commit: neither half may land.

    The seam is the surface's own ``_open_memory_store``: the service opens a
    store per call, so the failure is armed on the very object it is about to
    write through -- not on a store this test built, which the surface would
    never have touched. ``write_revision`` runs after both the statement write
    and the status write, so reaching it proves the transaction body executed
    and that the rollback is what undid it.
    """
    original = "Wording that must survive the injected failure."
    record_id, prepared = governed.pending(original)

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("injected failure mid-transaction")

    open_store = governed.service._open_memory_store

    def _arm(root_path: Path) -> tuple[Any, Path, Any, Any]:
        store, db_path, config, project = open_store(root_path)
        store.write_revision = _boom  # type: ignore[method-assign]
        return store, db_path, config, project

    monkeypatch.setattr(governed.service, "_open_memory_store", _arm)
    with pytest.raises(RuntimeError, match="injected failure"):
        governed.commit(record_id, prepared)

    assert governed.settled(record_id) == ("draft", original, 0)


# --- 3. the compare-and-swap reaches the surface --------------------------


def test_a_statement_that_moved_under_the_ticket_is_refused_at_the_surface(
    governed: _GovernedSurface,
) -> None:
    """Digest axis. A real second writer, not a hand-set field."""
    record_id, prepared = governed.pending("First author wording.")

    _foreign_write(
        governed.db_path,
        "UPDATE memory_records SET statement=? WHERE id=?",
        ("Second writer got here first.", record_id),
    )

    with pytest.raises(MCPServiceContractError) as excinfo:
        governed.commit(record_id, prepared)
    assert str(excinfo.value).startswith(f"{GOVERNANCE_STALE_AMENDMENT_CODE}:")
    assert governed.settled(record_id) == (
        "draft",
        "Second writer got here first.",
        0,
    )


def test_a_status_move_the_revision_axis_cannot_see_is_refused_at_the_surface(
    governed: _GovernedSurface,
) -> None:
    """Status axis, measured on the decision that can actually reach it.

    ``amend_and_approve`` admits only a draft, so a record that moved to
    ``stale`` is turned away earlier, by amendability (see the complement
    below) -- the CAS status axis is never consulted on that path. ``approve``
    admits ``{draft, stale}``, so it is where a status move survives long
    enough to meet the compare-and-swap.

    The accounting is asserted rather than assumed: the statement bytes are
    unchanged and the revision count does not move across the stale write, so
    neither of the other two axes could have produced this refusal. That the
    store's own ``mark_stale`` moves a record this way -- row written, no
    revision -- is pinned at the record layer by
    ``test_stale_move_leaves_the_revision_axis_blind``.
    """
    record_id, prepared = governed.pending("Wording nobody touched.", "approve")
    _status_before, statement_before, revisions_before = governed.settled(record_id)

    _foreign_write(
        governed.db_path,
        "UPDATE memory_records SET status='stale', stale_reason=? WHERE id=?",
        ("superseded by a later run", record_id),
    )

    status, statement, revisions_after = governed.settled(record_id)
    assert (status, statement) == ("stale", statement_before)
    assert revisions_before == revisions_after, "revision axis must stay blind here"
    assert prepared["record_status"] == "draft"

    with pytest.raises(MCPServiceContractError) as excinfo:
        governed.commit(record_id, prepared, decision="approve", statement=None)
    assert str(excinfo.value).startswith(f"{GOVERNANCE_STALE_AMENDMENT_CODE}:")
    assert governed.settled(record_id) == ("stale", "Wording nobody touched.", 0)


def test_amend_turns_a_moved_status_away_before_the_compare_and_swap(
    governed: _GovernedSurface,
) -> None:
    """The complement, so the pin above is not read as the whole rule.

    On the amend decision the same move is refused as immutability, not as a
    stale amendment. Both refusals write nothing; they differ in the remedy
    they hand the human, and that difference is the thing worth keeping.
    """
    original = "Wording that goes stale under the ticket."
    record_id, prepared = governed.pending(original)

    _foreign_write(
        governed.db_path,
        "UPDATE memory_records SET status='stale', stale_reason=? WHERE id=?",
        ("superseded by a later run", record_id),
    )

    with pytest.raises(MCPServiceContractError) as excinfo:
        governed.commit(record_id, prepared)
    message = str(excinfo.value)
    assert message.startswith(f"{GOVERNANCE_RECORD_IMMUTABLE_CODE}:")
    assert GOVERNANCE_STALE_AMENDMENT_CODE not in message
    assert governed.settled(record_id) == ("stale", original, 0)


# --- 4. the protocol gate, both boundaries --------------------------------


def test_amend_on_an_old_wire_refuses_as_a_version_problem_at_the_surface(
    governed: _GovernedSurface,
) -> None:
    """A client that is merely old must not be told its decision does not exist."""
    original = "Wording an old client tried to amend."
    record_id, prepared = governed.pending(original)

    with pytest.raises(MCPServiceContractError) as excinfo:
        governed.commit(record_id, prepared, protocol=_OLD_WIRE)
    message = str(excinfo.value)
    assert message.startswith(f"{GOVERNANCE_DECISION_PROTOCOL_CODE}:")
    assert "Unknown governance decision" not in message
    assert str(_AMENDMENT_WIRE) in message
    assert governed.settled(record_id) == ("draft", original, 0)


def test_the_old_wire_still_approves_through_the_surface(
    governed: _GovernedSurface,
) -> None:
    """The gate's other boundary: it must not fire on the three old decisions.

    A gate that refused every decision at protocol 2 would pass the test above
    and silently break every shipped client.
    """
    original = "Wording an old client approves unchanged."
    record_id, prepared = governed.pending(original, "approve")
    committed = governed.commit(
        record_id,
        prepared,
        decision="approve",
        protocol=_OLD_WIRE,
        statement=None,
    )
    assert committed["status"] == "ok"
    assert governed.settled(record_id)[:2] == ("active", original)


def test_a_misspelled_decision_on_a_good_wire_is_still_unknown(
    governed: _GovernedSurface,
) -> None:
    """The version gate must not swallow the spelling refusal it sits beside."""
    record_id = governed.draft("Wording behind a misspelled decision.")
    with pytest.raises(MCPServiceContractError) as excinfo:
        governed.prepare(record_id, "amend")
    message = str(excinfo.value)
    assert "Unknown governance decision" in message
    assert GOVERNANCE_DECISION_PROTOCOL_CODE not in message


# --- 5. an approved statement is immutable through the surface ------------


def test_amending_an_approved_record_is_refused_at_the_surface(
    governed: _GovernedSurface,
) -> None:
    """Published wording is never edited in place, and the refusal says why.

    The remedy has to name the successor path, or the human is left with a
    true statement and no way forward.
    """
    published = "Wording published for other agents to read."
    record_id = governed.draft(published)
    governed.commit(
        record_id,
        governed.prepare(record_id, "approve"),
        decision="approve",
        statement=None,
    )
    assert governed.settled(record_id)[:2] == ("active", published)

    with pytest.raises(MCPServiceContractError) as excinfo:
        governed.prepare(record_id)
    message = str(excinfo.value)
    assert message.startswith(f"{GOVERNANCE_RECORD_IMMUTABLE_CODE}:")
    assert "supersedes" in message
    assert governed.settled(record_id)[:2] == ("active", published)


# --- 6. the content rules apply to the human ------------------------------


@pytest.mark.parametrize(
    ("code", "submitted"),
    [
        ("memory_md_html", "## Title\nRaw <b>markup</b> in the amended note."),
        # One admitted tag makes the render surface parse author markup, so
        # <code> is refused exactly like any other tag rather than waved
        # through as the harmless-looking one.
        ("memory_md_html", "## Title\nA <code>span</code> in the amended note."),
        ("memory_md_image", "## Title\n![shot](https://example.com/a.png)"),
        ("memory_md_link", "## Title\nSee [the doc](https://example.com/doc)."),
    ],
)
def test_human_submitted_markup_is_refused_with_a_step_the_human_can_run(
    governed: _GovernedSurface,
    code: str,
    submitted: str,
) -> None:
    """Same rules as an agent gets; a remedy the approval view can execute.

    Telling a human at an approval button to "retry record_candidate" is an
    instruction they have no way to perform, so the audience of the next_step
    is as load-bearing as the refusal itself.
    """
    original = f"Wording behind the {code} attempt {len(submitted)}."
    record_id, prepared = governed.pending(original)

    with pytest.raises(MCPServiceContractError) as excinfo:
        governed.commit(record_id, prepared, statement=submitted)
    message = str(excinfo.value)
    assert message.startswith(f"{code}:")
    assert "in the Memory view" in message
    assert "record_candidate" not in message
    assert governed.settled(record_id) == ("draft", original, 0)


def test_amend_without_a_statement_is_refused_at_the_surface(
    governed: _GovernedSurface,
) -> None:
    """The decision that carries wording, committed with none.

    Reachable from any client that sends the decision and forgets the field.
    Without this the refusal is production code no test has ever executed,
    and the only thing standing between it and an AttributeError on ``None``.
    """
    original = "Wording a client tried to amend with nothing."
    record_id, prepared = governed.pending(original)

    with pytest.raises(MCPServiceContractError) as excinfo:
        governed.commit(record_id, prepared, statement=None)
    message = str(excinfo.value)
    assert message.startswith(f"{GOVERNANCE_TICKET_MISMATCH_CODE}:")
    assert "next_step:" in message
    assert "decision=approve" in message
    assert governed.settled(record_id) == ("draft", original, 0)


# --- 7. agents still cannot approve ---------------------------------------


def test_an_agent_session_cannot_reach_the_governance_channel(
    tmp_path: Path,
) -> None:
    """A process boundary, not a name check.

    The same code, the same calls, the same arguments -- refused because this
    server was not launched with --ide-governance-channel. Registration is
    refused first, so an agent cannot even acquire the key the rest needs.
    """
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        _identity, db_path = memory_project_db_paths(root)
        agent = _GovernedSurface(root, db_path, channel=False)
        original = "Wording an agent would like to approve itself."
        record_id = agent.draft(original)

        assert agent.registered["status"] == "rejected"
        assert agent.registered["reason"] == "governance_mode_unavailable"

        prepared = agent.prepare(record_id)
        assert prepared["status"] == "rejected"
        assert prepared["reason"] == "governance_mode_unavailable"

        committed = agent.call(
            action="commit_governance",
            record_id=record_id,
            decision=AMEND_AND_APPROVE,
            governance_ticket="ticket",
            confirmation_nonce="nonce",
            proof="proof",
            protocol=_AMENDMENT_WIRE,
            actor="agent",
            statement=_HUMAN_WORDING,
        )
        assert committed["status"] == "rejected"
        assert committed["reason"] == "governance_mode_unavailable"

        assert agent.settled(record_id) == ("draft", original, 0)
