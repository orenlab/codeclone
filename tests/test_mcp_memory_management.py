# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import asyncio
import re
import secrets
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import codeclone.memory.finish_workflow as finish_workflow
import codeclone.surfaces.mcp._session_memory_mixin as mcp_memory_mixin_mod
from codeclone.memory.coverage import ScopeCoverageReport
from codeclone.memory.exceptions import MemoryCapacityError, MemoryContractError
from codeclone.memory.finish_workflow import FinishMemoryWorkflowResult
from codeclone.memory.governance import record_candidate
from codeclone.memory.ide_governance import (
    IDE_GOVERNANCE_PROTOCOL_VERSION,
    compute_governance_proof,
)
from codeclone.memory.staleness import StalenessReport
from codeclone.surfaces.mcp._context_governance import (
    passive_drill_down_reachability,
)
from codeclone.surfaces.mcp._session_shared import (
    MCPAnalysisRequest,
    MCPRunNotFoundError,
    MCPRunRecord,
    MCPServiceContractError,
)
from codeclone.surfaces.mcp.server import build_mcp_server
from codeclone.surfaces.mcp.service import CodeCloneMCPService

from .memory_fixtures import cli_memory_repo


def _memory_test_run_record(root: Path, run_id: str) -> MCPRunRecord:
    """A minimal stored run for root-binding tests on the memory surface."""

    return MCPRunRecord(
        run_id=run_id,
        root=root,
        request=MCPAnalysisRequest(root=str(root), respect_pyproject=False),
        comparison_settings=(),
        report_document={},
        summary={"run_id": run_id, "health": {"score": 0, "grade": "N/A"}},
        changed_paths=(),
        changed_projection=None,
        warnings=(),
        failures=(),
        func_clones_count=0,
        block_clones_count=0,
        project_metrics=None,
        coverage_join=None,
        suggestions=(),
        new_func=frozenset(),
        new_block=frozenset(),
        metrics_diff=None,
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


def _parse_published_route(route: str) -> tuple[str, frozenset[str]]:
    """Split a published route into the tool it names and the arguments it names."""

    match = _ROUTE_PATTERN.match(route.strip())
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


def test_published_drill_down_routes_name_exactly_what_the_server_accepts() -> None:
    """Every published route MUST be complete AND callable against its tool.

    One rule, both boundaries, re-derived from the live ``list_tools()`` schema
    rather than from these spellings: a route has to name every argument the
    registered tool marks required -- or the server refuses the very call the
    surface just instructed -- and it must not name an argument the tool does
    not accept, which the server refuses for the opposite reason.

    The rule reads every entry the table publishes, not a named subset. Naming
    the rows kept the rule from noticing the rows nobody had fixed: four routes
    omitted ``root`` while the three listed here were complete, and a rule that
    checks three of seven rows is a rule with a hole.
    """
    pytest.importorskip("mcp.server.fastmcp")
    server = build_mcp_server(history_limit=2)
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    reachability = passive_drill_down_reachability()

    published = [
        (f"{entry}.{key}", route)
        for entry, body in sorted(reachability.items())
        for key, route in sorted(body.items())
        if key.endswith("route") and isinstance(route, str) and route
    ]
    assert published, reachability

    unserved: dict[str, dict[str, list[str]]] = {}
    demanded: set[str] = set()
    for label, route in published:
        tool_name, named = _parse_published_route(route)
        assert tool_name in tools, route
        schema = tools[tool_name].inputSchema
        required = frozenset(cast("list[str]", schema["required"]))
        accepted = frozenset(cast("dict[str, object]", schema["properties"]))
        demanded |= required
        defect = {
            "missing_required": sorted(required - named),
            "not_accepted": sorted(named - accepted),
        }
        if any(defect.values()):
            unserved[label] = defect

    assert unserved == {}
    assert demanded, published


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
