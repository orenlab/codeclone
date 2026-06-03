# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.memory.governance import record_candidate
from codeclone.memory.ingest.receipts import (
    propose_memory_from_changed_paths,
    propose_memory_from_finish_payload,
)

from .memory_fixtures import cli_memory_repo, memory_store


def test_propose_memory_from_finish_payload_with_scope_and_text(
    tmp_path: Path,
) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (_root, project, store):
        candidates = propose_memory_from_finish_payload(
            store,
            project=project,
            finish_payload={
                "scope_check": {"declared_scope": ["pkg/mod.py", "README.md"]},
                "claims_text": "Patch keeps module surface stable.",
                "review_text": "Reviewed blast radius for pkg/mod.py.",
                "verification": {"verification_profile": "python_structural"},
            },
            max_candidates=20,
            max_statement_chars=1000,
        )
    assert candidates
    types = {item["type"] for item in candidates if isinstance(item, dict)}
    assert "module_role" in types
    assert "change_rationale" in types
    assert "architecture_decision" in types
    assert "contract_note" in types


def test_propose_memory_from_changed_paths(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        candidates = propose_memory_from_changed_paths(
            store,
            project=project,
            changed_paths=["pkg/feature.py"],
            claims_text="Claims about feature module.",
            review_text=None,
            verification_profile="documentation_only",
            max_candidates=10,
            max_statement_chars=1000,
        )
    assert any(
        isinstance(item, dict) and item.get("type") == "contract_note"
        for item in candidates
    )


def test_propose_memory_skips_invalid_text_candidates(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        candidates = propose_memory_from_finish_payload(
            store,
            project=project,
            finish_payload={
                "scope_check": {"declared_scope": []},
                "claims_text": "   ",
                "review_text": 42,
            },
            max_candidates=5,
            max_statement_chars=1000,
        )
    assert candidates == []


def test_try_append_text_candidate_returns_none_on_record_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from codeclone.memory.ingest import receipts as receipts_mod

    with memory_store(tmp_path) as (_root, project, store, _db_path):

        def _boom(*_args: object, **_kwargs: object) -> object:
            raise RuntimeError("draft limit")

        monkeypatch.setattr(receipts_mod, "record_candidate", _boom)
        result = receipts_mod._try_append_text_candidate(
            store,
            project=project,
            record_type="change_rationale",
            text="Claims after patch.",
            subject_path="pkg/mod.py",
            created_by="finish_hook",
            max_candidates=5,
            max_statement_chars=1000,
        )
    assert result is None


def test_propose_memory_module_role_from_py_scope(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        record = record_candidate(
            store,
            project=project,
            record_type="architecture_decision",
            statement="existing draft",
            subject_path="pkg/mod.py",
            max_candidates=100,
        )
        candidates = propose_memory_from_finish_payload(
            store,
            project=project,
            finish_payload={
                "scope_check": {"declared_scope": ["pkg/mod.py"]},
            },
            max_candidates=1,
            max_statement_chars=1000,
        )
    assert candidates == [] or candidates[0]["id"] != record.id
