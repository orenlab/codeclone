# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

import pytest

from codeclone.config.memory import MemoryConfig, _memory_choice, _memory_int
from codeclone.memory.exceptions import MemoryContractError
from codeclone.memory.governance import (
    _contains_unnegated_phrase,
    _is_vscode_human_approval_descriptor,
    _pattern_matches_unnegated,
    archive_record,
    record_candidate,
    reject_record,
    validate_memory_claims,
)
from codeclone.memory.ide_governance import (
    IDE_GOVERNANCE_ALLOWED_CLIENTS,
    IdeGovernanceSessionState,
    _governance_key_or_reject,
    commit_governance,
)
from codeclone.memory.project import resolve_project_identity
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore
from codeclone.memory.vacuum import run_memory_vacuum


def _memory_config() -> MemoryConfig:
    return MemoryConfig(
        backend="sqlite",
        db_path=Path(".cache/codeclone/memory.sqlite3"),
        active_retention_days=30,
        stale_retention_days=30,
        draft_retention_days=7,
        rejected_retention_days=7,
        archived_retention_days=30,
        receipt_retention_days=30,
        max_records=1000,
        max_candidates=100,
        max_evidence_per_record=10,
        max_statement_chars=4000,
        max_blast_radius_cache_entries=200,
        git_hotspot_period_days=30,
        git_hotspot_min_changes=2,
        mcp_sync_policy="off",
    )


def test_governance_phrase_and_pattern_negation_helpers() -> None:
    assert _is_vscode_human_approval_descriptor(
        "Use VS Code Memory view; human review can approve draft records."
    )
    assert not _is_vscode_human_approval_descriptor(
        "VS Code channel only, no draft mention"
    )
    assert not _is_vscode_human_approval_descriptor(
        "Use VS Code Memory view for review only."
    )
    assert _contains_unnegated_phrase(
        "memory can approve draft records", "approve draft"
    )

    pattern = re.compile(r"approve draft", re.IGNORECASE)
    assert not _pattern_matches_unnegated("do not approve draft", pattern)
    assert _pattern_matches_unnegated("please approve draft now", pattern)

    no_anchor_pattern = re.compile(r"this phrase", re.IGNORECASE)
    assert _pattern_matches_unnegated("this phrase appears", no_anchor_pattern)
    assert not _pattern_matches_unnegated("do not this phrase", no_anchor_pattern)


def test_governance_reject_and_archive_invalid_status_branches(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    project = resolve_project_identity(root)
    store = SqliteEngineeringMemoryStore(tmp_path / "memory.sqlite3")
    try:
        store.initialize(project)
        draft = record_candidate(
            store,
            project=project,
            record_type="change_rationale",
            statement="status validation",
            max_candidates=10,
        )
        with pytest.raises(
            MemoryContractError, match="Cannot archive record in status"
        ):
            archive_record(store, record_id=draft.id, archived_by="maintainer")

        missing = "mem-missing"
        with pytest.raises(
            MemoryContractError, match=f"Memory record not found: {missing}"
        ):
            reject_record(store, record_id=missing, rejected_by="maintainer")

        active = store.find_record(draft.id)
        assert active is not None
        store.update_record_status(draft.id, status="active")
        with pytest.raises(MemoryContractError, match="Cannot reject record in status"):
            reject_record(store, record_id=draft.id, rejected_by="maintainer")
    finally:
        store.close()


def test_validate_memory_claims_inferred_warning_branch() -> None:
    class _EmptyStore:
        def query_records(self, _query: object) -> list[object]:
            return []

    result = validate_memory_claims(
        _EmptyStore(),  # type: ignore[arg-type]
        project_id="proj",
        text="This inferred item is an established fact.",
    )
    assert result.valid is True
    assert any("hypothesis" in warning for warning in result.warnings)


def test_memory_choice_invalid_value_error() -> None:
    with pytest.raises(ValueError, match="expected one of"):
        _memory_choice("bad", key="backend", valid=frozenset({"sqlite"}))
    assert _memory_int("42", key="max_records") == 42


def test_memory_vacuum_respects_negative_retention_and_deleted_status_counts() -> None:
    class _FakeStore:
        def __init__(self) -> None:
            self.calls: list[tuple[str, bool]] = []
            self.committed = False

        def delete_records_older_than(
            self,
            *,
            status: str,
            updated_before_utc: str,
            commit: bool,
        ) -> int:
            del updated_before_utc
            self.calls.append((status, commit))
            if status == "stale":
                return 2
            if status == "rejected":
                return 1
            return 0

        def commit(self) -> None:
            self.committed = True

    config = _memory_config()
    config = replace(
        config,
        draft_retention_days=-1,  # skip draft branch in _retention_days_for_status
    )
    store = _FakeStore()
    report = run_memory_vacuum(store, config, commit=True)  # type: ignore[arg-type]
    assert store.committed is True
    assert ("draft", False) not in store.calls
    assert report.deleted_by_status == {"rejected": 1, "stale": 2}
    assert report.total_deleted == 3


def test_ide_governance_key_or_reject_and_commit_dict_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _StoreStub:
        def find_record(self, _record_id: str) -> object | None:
            return None

    rejected = _governance_key_or_reject(
        IdeGovernanceSessionState(channel_enabled=True, governance_key=None),
        action="commit_governance",
    )
    assert isinstance(rejected, dict)
    assert rejected["reason"] == "governance_key_missing"

    state = IdeGovernanceSessionState(channel_enabled=True, governance_key=None)
    payload = commit_governance(
        state,
        store=_StoreStub(),  # type: ignore[arg-type]
        project_id="proj",
        root_path=".",
        record_id="mem",
        decision="approve",
        governance_ticket="t",
        confirmation_nonce="n",
        proof="p",
        actor="a",
        protocol=2,
    )
    assert payload["status"] == "rejected"
    assert payload["reason"] == "governance_key_missing"

    # Force the isinstance(dict) early-return branch in commit_governance.
    monkeypatch.setattr(
        "codeclone.memory.ide_governance._governance_key_or_reject",
        lambda _state, *, action: {"action": action, "status": "rejected"},
    )
    state2 = IdeGovernanceSessionState(
        channel_enabled=True,
        governance_key=b"x" * 32,
        client_name=next(iter(IDE_GOVERNANCE_ALLOWED_CLIENTS)),
    )
    payload2 = commit_governance(
        state2,
        store=_StoreStub(),  # type: ignore[arg-type]
        project_id="proj",
        root_path=".",
        record_id="mem",
        decision="approve",
        governance_ticket="t",
        confirmation_nonce="n",
        proof="p",
        actor="a",
        protocol=2,
    )
    assert payload2["status"] == "rejected"
