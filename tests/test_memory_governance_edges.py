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
    validate_memory_claims,
)
from codeclone.memory.models import MemoryEvidence
from codeclone.memory.project import resolve_project_identity
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore


class _StaleHitStore:
    def query_records(self, _query: object) -> list[object]:
        # validate_memory_claims only checks truthiness + reads warnings.
        return [object()]


def test_record_candidate_rejects_empty_statement(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    project = resolve_project_identity(root)
    store = SqliteEngineeringMemoryStore(tmp_path / "memory.sqlite3")
    try:
        store.initialize(project)
        with pytest.raises(MemoryContractError):
            record_candidate(
                store,
                project=project,
                record_type="risk_note",
                statement="   ",
                subject_path="pkg/mod.py",
                max_candidates=100,
            )
    finally:
        store.close()


def test_record_candidate_rejects_duplicate_identity(tmp_path: Path) -> None:
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
            statement="Same statement for duplicate identity.",
            subject_path="pkg/mod.py",
            max_candidates=100,
        )
        assert first.status == "draft"
        with pytest.raises(MemoryContractError, match="Candidate already exists"):
            record_candidate(
                store,
                project=project,
                record_type="risk_note",
                statement="Same statement for duplicate identity.",
                subject_path="pkg/mod.py",
                max_candidates=100,
            )
    finally:
        store.close()


def test_approve_record_skips_warrant_evidence_when_evidence_already_present(
    tmp_path: Path,
) -> None:
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
            statement="Pre-approved draft, evidence already present.",
            max_candidates=100,
        )
        evidence = MemoryEvidence(
            id="evid-1",
            memory_id=draft.id,
            evidence_kind="audit_event",
            ref="human_approval:seed",
            locator=None,
            quote=None,
            digest=None,
            created_at_utc="2026-01-01T00:00:00Z",
        )
        store.write_evidence(evidence)
        assert store.count_evidence_for_memory(draft.id) == 1

        approved = approve_record(store, record_id=draft.id, approved_by="maintainer")
        assert approved.status == "active"
        assert store.count_evidence_for_memory(draft.id) == 1
    finally:
        store.close()


def test_validate_memory_claims_warns_on_stale_hits_when_no_stale_in_text() -> None:
    store = _StaleHitStore()
    result = validate_memory_claims(
        store,  # type: ignore[arg-type]
        project_id="proj",
        text="The claim is constrained: no stale records exist in this scope.",
    )
    assert result.valid is True
    assert any("Active stale records exist" in w for w in result.warnings)
