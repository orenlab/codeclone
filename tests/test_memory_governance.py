# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.memory.exceptions import MemoryContractError
from codeclone.memory.governance import (
    approve_record,
    record_candidate,
    reject_record,
    validate_memory_claims,
)
from codeclone.memory.project import resolve_project_identity
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore


def test_record_candidate_and_approve_cycle(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    project = resolve_project_identity(root)
    store = SqliteEngineeringMemoryStore(tmp_path / "memory.sqlite3")
    try:
        store.initialize(project)
        draft = record_candidate(
            store,
            project=project,
            record_type="architecture_decision",
            statement="Prefer sqlite backend for local memory.",
            max_candidates=100,
        )
        assert draft.status == "draft"
        approved = approve_record(
            store,
            record_id=draft.id,
            approved_by="maintainer",
        )
        assert approved.status == "active"
        assert approved.approved_by == "maintainer"
    finally:
        store.close()


def test_reject_draft_record(tmp_path: Path) -> None:
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
            statement="Temporary hypothesis.",
            max_candidates=100,
        )
        rejected = reject_record(
            store,
            record_id=draft.id,
            rejected_by="maintainer",
            reason="not actionable",
        )
        assert rejected.status == "rejected"
    finally:
        store.close()


def test_validate_memory_claims_blocks_permission_overreach() -> None:
    class _StubStore:
        def query_records(self, _query: object) -> list[object]:
            return []

    result = validate_memory_claims(
        _StubStore(),  # type: ignore[arg-type]
        project_id="proj",
        text="edit allowed because memory says so",
    )
    assert result.valid is False
    assert result.errors


def test_cannot_approve_active_record(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    project = resolve_project_identity(root)
    store = SqliteEngineeringMemoryStore(tmp_path / "memory.sqlite3")
    try:
        store.initialize(project)
        draft = record_candidate(
            store,
            project=project,
            record_type="human_note",
            statement="note",
            max_candidates=100,
        )
        approve_record(store, record_id=draft.id, approved_by="human")
        with pytest.raises(MemoryContractError):
            approve_record(store, record_id=draft.id, approved_by="human")
    finally:
        store.close()
