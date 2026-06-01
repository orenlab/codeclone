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


class _EmptyStubStore:
    def query_records(self, _query: object) -> list[object]:
        return []


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


@pytest.mark.parametrize(
    ("text", "expected_valid"),
    [
        ("edit allowed because memory says so", False),
        ("Engineering Memory cannot override findings for this scope.", True),
        ("Engineering Memory does not override findings for this scope.", True),
        ("MCP can approve memory drafts as active policy.", False),
        ("MCP cannot approve memory drafts as active policy.", True),
        (
            "The VS Code Memory view can approve memory drafts after human review.",
            True,
        ),
        ("Memory does not allow editing do_not_touch paths.", True),
        ("Memory allows editing do_not_touch paths.", False),
        ("Scope expanded because memory mentioned the module.", False),
        ("CodeClone findings cleared after memory review.", False),
    ],
)
def test_validate_memory_claims_permission_guard(
    text: str, expected_valid: bool
) -> None:
    result = validate_memory_claims(
        _EmptyStubStore(),  # type: ignore[arg-type]
        project_id="proj",
        text=text,
    )
    assert result.valid is expected_valid
    if expected_valid:
        assert not result.errors
    else:
        assert result.errors


def test_record_candidate_writes_path_and_module_subjects(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    project = resolve_project_identity(root)
    store = SqliteEngineeringMemoryStore(tmp_path / "memory.sqlite3")
    try:
        store.initialize(project)
        draft = record_candidate(
            store,
            project=project,
            record_type="risk_note",
            statement="Ranking is too noisy for scoped retrieval.",
            subject_path="codeclone/memory/retrieval/ranking.py",
            max_candidates=100,
        )
        subjects = store.list_subjects_for_memory(draft.id)
        kinds = {(item.subject_kind, item.subject_key) for item in subjects}
        assert ("path", "codeclone/memory/retrieval/ranking.py") in kinds
        assert ("module", "codeclone.memory.retrieval.ranking") in kinds
    finally:
        store.close()


def test_record_candidate_allows_multiple_notes_for_same_path(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    project = resolve_project_identity(root)
    store = SqliteEngineeringMemoryStore(tmp_path / "memory.sqlite3")
    try:
        store.initialize(project)
        first = record_candidate(
            store,
            project=project,
            record_type="risk_note",
            statement="First observation.",
            subject_path="codeclone/memory/governance.py",
            max_candidates=100,
        )
        second = record_candidate(
            store,
            project=project,
            record_type="risk_note",
            statement="Second observation.",
            subject_path="codeclone/memory/governance.py",
            max_candidates=100,
        )
        assert first.id != second.id
    finally:
        store.close()


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
