# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.memory.governance import record_candidate
from codeclone.memory.ingest.extractors import extract_module_roles
from codeclone.memory.ingest.receipts import (
    propose_memory_from_changed_paths,
    propose_memory_from_finish_payload,
)
from codeclone.memory.project import GitProvenance

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
    assert "change_rationale" in types
    assert "architecture_decision" in types
    assert "contract_note" in types
    # The declared scope elects the subject path; it no longer mints a record of
    # its own. See test_receipt_ingest_mints_no_contentless_module_role.
    assert "module_role" not in types


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


def test_try_append_text_candidate_counts_dropped_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A swallowed best-effort proposal stays non-fatal (returns None) but is no
    longer silent: it increments the memory.propose_candidate_dropped counter.
    The lazy import resolves record_counter from the patched module attribute."""
    from codeclone.memory.ingest import receipts as receipts_mod

    counters: list[tuple[str, int]] = []
    monkeypatch.setattr(
        "codeclone.observability.record_counter",
        lambda key, value=1: counters.append((key, value)),
    )

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
    assert ("memory.propose_candidate_dropped", 1) in counters


def test_receipt_ingest_mints_no_contentless_module_role(tmp_path: Path) -> None:
    """The finish hook must not mint a module_role that asserts nothing.

    The receipt path used to stamp one ``module_role`` draft per ``.py`` path in
    the declared scope, with the fixed statement "Patch touched scope includes
    <path>; review module role after change." That sentence carries no
    proposition about the module's role: the only variable is the path, which the
    record already carries as its subject and which the patch trail already
    records. Confidence was ``inferred`` and the retriever demoted the row to the
    ``workflow_context`` lane, so every one of them was pure retrieval noise that
    still had to be governed by a human.

    Pinned here on the typical finish input (Python scope plus claims and review
    text), against both surfaces: the returned candidate list AND the store, so
    a variant that hides the row from the response while still writing it fails.
    """
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        candidates = propose_memory_from_finish_payload(
            store,
            project=project,
            finish_payload={
                "scope_check": {
                    "declared_scope": ["pkg/mod.py", "pkg/other.py", "README.md"]
                },
                "claims_text": "Patch keeps module surface stable.",
                "review_text": "Reviewed blast radius for pkg/mod.py.",
                "verification": {"verification_profile": "python_structural"},
            },
            max_candidates=20,
            max_statement_chars=1000,
        )
        stored_types = [
            record.type
            for record in store.list_records_for_project(project.id, limit=100)
        ]

    candidate_types = [item["type"] for item in candidates if isinstance(item, dict)]
    assert "module_role" not in candidate_types
    assert "module_role" not in stored_types
    assert not any(
        "review module role after change" in str(item.get("statement", ""))
        for item in candidates
        if isinstance(item, dict)
    )


def test_analysis_ingest_still_produces_substantive_module_roles(
    tmp_path: Path,
) -> None:
    """The analysis extractor keeps producing module_role; only receipts stopped.

    Two different producers write this record type and they must not be confused:
    ``extract_module_roles`` states a fact about the module ("<module> is an
    analyzed Python module in project inventory", confidence ``supported``),
    while the removed receipt branch stated nothing. This pin fails if the
    boilerplate fix is over-cut into the substantive producer.
    """
    project = GitProvenance(remote=None, branch="main", head="deadbeef", available=True)
    with memory_store(tmp_path) as (root, memory_project, _store, _db_path):
        batch = extract_module_roles(
            project=memory_project,
            root_path=root,
            report_document={"inventory": {"file_registry": {"items": ["pkg/mod.py"]}}},
            git=project,
            report_digest="r1",
            analysis_fingerprint="f1",
        )

    assert [record.type for record in batch.records] == ["module_role"]
    assert batch.records[0].confidence == "supported"
    assert "analyzed Python module" in batch.records[0].statement


def test_receipt_ingest_keeps_scope_subject_for_text_candidates(
    tmp_path: Path,
) -> None:
    """Dropping the boilerplate must not drop the scope-derived subject path.

    The declared-scope walk also elects the first ``.py`` path as the subject for
    the claims/review candidates. Without it ``_try_append_text_candidate``
    returns ``None`` and the substantive finish candidates disappear silently, so
    this pin guards the over-cut: it asserts both candidates exist and that they
    are filed against the first Python path in the declared scope.
    """
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        candidates = propose_memory_from_finish_payload(
            store,
            project=project,
            finish_payload={
                "scope_check": {
                    "declared_scope": ["docs/guide.md", "pkg/first.py", "pkg/second.py"]
                },
                "claims_text": "Patch keeps module surface stable.",
                "review_text": "Reviewed blast radius before landing.",
            },
            max_candidates=20,
            max_statement_chars=1000,
        )
        by_type = {
            str(item["type"]): str(item["id"])
            for item in candidates
            if isinstance(item, dict) and "id" in item
        }
        subjects = {
            record_type: {
                subject.subject_key
                for subject in store.list_subjects_for_memory(record_id)
            }
            for record_type, record_id in by_type.items()
        }

    assert set(by_type) == {"change_rationale", "architecture_decision"}
    for record_type in ("change_rationale", "architecture_decision"):
        assert "pkg/first.py" in subjects[record_type], record_type


def test_receipt_ingest_tolerates_malformed_scope_check(tmp_path: Path) -> None:
    """A ``scope_check`` that is not a mapping elects no subject, and no record.

    ``propose_memory_from_finish_payload`` takes a transport-neutral payload, so
    the type guard on ``scope_check`` has to survive a caller that fills the key
    with something else. This is the input that reaches that guard: without it
    the branch is unreachable across the whole suite and is untested theatre.
    """
    from codeclone.memory.ingest import receipts as receipts_mod

    assert receipts_mod._elect_subject_path({"scope_check": "pkg/mod.py"}) is None
    assert receipts_mod._elect_subject_path({}) is None
    assert receipts_mod._elect_subject_path({"scope_check": {}}) is None

    with memory_store(tmp_path) as (_root, project, store, _db_path):
        candidates = propose_memory_from_finish_payload(
            store,
            project=project,
            finish_payload={
                "scope_check": "pkg/mod.py",
                "claims_text": "Claims with nowhere to be filed.",
            },
            max_candidates=20,
            max_statement_chars=1000,
        )
        assert store.list_records_for_project(project.id, limit=100) == []
    assert candidates == []


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
