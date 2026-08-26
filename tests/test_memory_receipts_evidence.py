# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Attested finish identifiers must land as durable ``memory_evidence`` rows.

The finish(propose_memory=true) flow holds every attested identifier of the
finished change (receipt digest, patch-trail digest, commit sha, run id). Before
this fix those identifiers were discarded at the candidate builder and, at human
approval, a signature-shaped ``human_approval:<name>`` warrant with ``digest=None``
was backfilled as the only evidence. These tests pin that the builder now threads
the attested identifiers into durable evidence rows, and that a pre-fix store is
preserved byte-for-byte (no schema bump, no retro-backfill of old records).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from codeclone.memory.finish_workflow import execute_finish_memory_workflow
from codeclone.memory.governance import approve_record, record_candidate
from codeclone.memory.ingest.receipts import (
    _attach_attested_evidence,
    _read_attested_evidence,
    propose_memory_from_changed_paths,
    propose_memory_from_finish_payload,
)
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore

from .memory_fixtures import memory_store

_RECEIPT_DIGEST = "a" * 64
_PATCH_TRAIL_DIGEST = "b" * 64
_COMMIT = "c" * 40
_RUN_ID = "run-abc12345"


def _attested_bundle() -> dict[str, str]:
    return {
        "receipt_digest": _RECEIPT_DIGEST,
        "patch_trail_digest": _PATCH_TRAIL_DIGEST,
        "commit": _COMMIT,
        "run_id": _RUN_ID,
        "branch": "main",
    }


_CLAIMS = "Patch keeps the module surface stable."


def _carrier(candidates: list[dict[str, object]]) -> dict[str, object]:
    """The record the attested evidence hangs on.

    Evidence attaches to candidates that assert something. The scope walk used
    to also mint a contentless ``module_role`` echo and that echo was the
    carrier these pins read; it is gone, so the carrier is the claims-derived
    ``change_rationale``. The invariant under test is unchanged: the attested
    identifiers reach durable ``memory_evidence`` rows on a proposed candidate.
    """
    return next(
        item
        for item in candidates
        if isinstance(item, dict) and item.get("type") == "change_rationale"
    )


def test_finish_payload_candidate_carries_attested_evidence(tmp_path: Path) -> None:
    """A proposed finish candidate carries the change's evidence."""
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        candidates = propose_memory_from_finish_payload(
            store,
            project=project,
            finish_payload={
                "scope_check": {"declared_scope": ["pkg/mod.py"]},
                "claims_text": _CLAIMS,
                "attested_evidence": _attested_bundle(),
            },
            max_candidates=20,
            max_statement_chars=1000,
        )
        carrier = _carrier(candidates)
        rows = store.list_evidence_for_memory(str(carrier["id"]))

    kinds = {row.evidence_kind for row in rows}
    digests = {row.digest for row in rows}
    assert "receipt" in kinds
    assert "audit_event" in kinds
    assert "git_commit" in kinds
    assert _RECEIPT_DIGEST in digests
    assert _PATCH_TRAIL_DIGEST in digests
    # run_id rides the evidence ref/locator (it is context, not a digest).
    assert any(row.locator == _RUN_ID for row in rows)
    # commit sha is the git_commit ref, matching the existing evidence convention.
    assert any(row.evidence_kind == "git_commit" and row.ref == _COMMIT for row in rows)


def test_text_candidates_carry_attested_evidence(tmp_path: Path) -> None:
    """change_rationale/architecture_decision candidates also carry evidence."""
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        candidates = propose_memory_from_finish_payload(
            store,
            project=project,
            finish_payload={
                "scope_check": {"declared_scope": ["pkg/mod.py"]},
                "claims_text": "Patch keeps the module surface stable.",
                "review_text": "Reviewed blast radius before landing.",
                "attested_evidence": _attested_bundle(),
            },
            max_candidates=20,
            max_statement_chars=1000,
        )
        typed = {
            str(item["type"]): str(item["id"])
            for item in candidates
            if isinstance(item, dict) and "id" in item
        }
        for record_type in ("change_rationale", "architecture_decision"):
            rows = store.list_evidence_for_memory(typed[record_type])
            digests = {row.digest for row in rows}
            assert _RECEIPT_DIGEST in digests, record_type
            assert _PATCH_TRAIL_DIGEST in digests, record_type


def test_approved_finish_candidate_keeps_attested_evidence_not_stub(
    tmp_path: Path,
) -> None:
    """Approval preserves the real digests instead of a digest=None warrant.

    This encodes the reported defect: without threaded evidence, approving the
    candidate backfilled a ``human_approval:<name>`` audit_event with
    ``digest=None`` as its ONLY provenance.
    """
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        candidates = propose_memory_from_finish_payload(
            store,
            project=project,
            finish_payload={
                "scope_check": {"declared_scope": ["pkg/mod.py"]},
                "claims_text": _CLAIMS,
                "attested_evidence": _attested_bundle(),
            },
            max_candidates=20,
            max_statement_chars=1000,
        )
        carrier = _carrier(candidates)
        approve_record(store, record_id=str(carrier["id"]), approved_by="maintainer")
        rows = store.list_evidence_for_memory(str(carrier["id"]))

    refs = {row.ref for row in rows}
    digests = {row.digest for row in rows}
    assert _RECEIPT_DIGEST in digests
    assert not any(ref.startswith("human_approval:") for ref in refs)


def test_finish_payload_without_attested_evidence_writes_no_rows(
    tmp_path: Path,
) -> None:
    """Backward compatible: absent a bundle, no evidence rows are written."""
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        candidates = propose_memory_from_finish_payload(
            store,
            project=project,
            finish_payload={
                "scope_check": {"declared_scope": ["pkg/mod.py"]},
                "claims_text": _CLAIMS,
            },
            max_candidates=20,
            max_statement_chars=1000,
        )
        carrier = _carrier(candidates)
        assert store.count_evidence_for_memory(str(carrier["id"])) == 0


def test_changed_paths_forwards_attested_evidence(tmp_path: Path) -> None:
    """propose_memory_from_changed_paths forwards the bundle to the builder."""
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        candidates = propose_memory_from_changed_paths(
            store,
            project=project,
            changed_paths=["pkg/feature.py"],
            claims_text=_CLAIMS,
            review_text=None,
            verification_profile="python_structural",
            max_candidates=20,
            max_statement_chars=1000,
            attested_evidence=_attested_bundle(),
        )
        carrier = _carrier(candidates)
        digests = {
            row.digest for row in store.list_evidence_for_memory(str(carrier["id"]))
        }
    assert _RECEIPT_DIGEST in digests
    assert _PATCH_TRAIL_DIGEST in digests


def test_finish_workflow_forwards_attested_evidence(tmp_path: Path) -> None:
    """execute_finish_memory_workflow forwards the bundle to the builder."""
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        result = execute_finish_memory_workflow(
            store,
            project=project,
            changed_paths=["pkg/feature.py"],
            claims_text=_CLAIMS,
            review_text=None,
            verification_profile="python_structural",
            max_candidates=20,
            max_statement_chars=1000,
            attested_evidence=_attested_bundle(),
        )
        carrier = _carrier(result.candidates)
        rows = store.list_evidence_for_memory(str(carrier["id"]))
    digests = {row.digest for row in rows}
    commit_refs = {row.ref for row in rows if row.evidence_kind == "git_commit"}
    assert _RECEIPT_DIGEST in digests
    assert _PATCH_TRAIL_DIGEST in digests
    assert _COMMIT in commit_refs


def test_read_attested_evidence_needs_a_durable_identifier() -> None:
    """A bundle with only context (run_id/branch) and no digest yields None.

    Non-string / blank identifiers are ignored rather than written as evidence.
    """
    assert _read_attested_evidence({}) is None
    assert _read_attested_evidence({"attested_evidence": {"run_id": "run-1"}}) is None
    assert (
        _read_attested_evidence(
            {"attested_evidence": {"receipt_digest": "  ", "commit": 123}}
        )
        is None
    )
    bundle = _read_attested_evidence(
        {"attested_evidence": {"receipt_digest": _RECEIPT_DIGEST, "run_id": ""}}
    )
    assert bundle == {"receipt_digest": _RECEIPT_DIGEST}


def test_attach_attested_evidence_empty_bundle_writes_nothing(tmp_path: Path) -> None:
    """The writer no-ops on a bundle carrying no durable identifier."""
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        record = record_candidate(
            store,
            project=project,
            record_type="risk_note",
            statement="a record with no attested evidence",
            subject_path="pkg/mod.py",
            max_candidates=100,
        )
        _attach_attested_evidence(store, memory_id=record.id, bundle={})
        assert store.count_evidence_for_memory(record.id) == 0


def _snapshot(db_path: Path) -> tuple[dict[str, list[tuple[object, ...]]], str]:
    conn = sqlite3.connect(str(db_path))
    try:
        tables = (
            "memory_records",
            "memory_evidence",
            "memory_revisions",
            "memory_subjects",
        )
        snap: dict[str, list[tuple[object, ...]]] = {}
        for table in tables:
            rows = conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
            snap[table] = [tuple(row) for row in rows]
        version = conn.execute(
            "SELECT value FROM memory_meta WHERE key='schema_version'"
        ).fetchone()[0]
        return snap, str(version)
    finally:
        conn.close()


def test_prefix_store_survives_evidence_fix_untouched(tmp_path: Path) -> None:
    """A realistic pre-fix store loads and governs identically after the fix.

    Non-destructive migration proof: existing records (including a human-approved
    record whose only evidence is a digest=None ``human_approval`` warrant) are
    preserved byte-for-byte, the schema version is unchanged (no bump), and old
    records are NOT retro-backfilled with invented digests. New candidates still
    coexist carrying real attested evidence.
    """
    # 1. Build the pre-fix store via the canonical fixture: a human-approved
    #    record (digest=None warrant) plus a draft that stays a draft. The
    #    fixture closes the store on exit, leaving the on-disk db to reopen.
    with memory_store(tmp_path) as (_root, project, store, db_path):
        approved = record_candidate(
            store,
            project=project,
            record_type="change_rationale",
            statement="pre-fix approved rationale predating the evidence fix",
            subject_path="pkg/legacy.py",
            max_candidates=100,
        )
        approve_record(store, record_id=approved.id, approved_by="maintainer")
        record_candidate(
            store,
            project=project,
            record_type="risk_note",
            statement="pre-fix draft risk note",
            subject_path="pkg/other.py",
            max_candidates=100,
        )
        pre_fix_rows = store.list_evidence_for_memory(approved.id)

    # The approved record's sole provenance is the digest=None human_approval stub.
    assert len(pre_fix_rows) == 1
    assert pre_fix_rows[0].ref == "human_approval:maintainer"
    assert pre_fix_rows[0].digest is None

    before, before_version = _snapshot(db_path)
    assert before_version == "1.7"

    # 2. Reopen with the fixed code path (ensure_schema runs). This is the
    #    user-upgrade moment.
    store2 = SqliteEngineeringMemoryStore(db_path)
    after, after_version = _snapshot(db_path)

    # 3. Byte-for-byte preservation and no schema bump.
    assert after == before
    assert after_version == before_version == "1.7"

    # 4. The store still governs, and a NEW candidate carries real evidence while
    #    the old approved record stays untouched (no retro-backfill).
    try:
        candidates = propose_memory_from_finish_payload(
            store2,
            project=project,
            finish_payload={
                "scope_check": {"declared_scope": ["pkg/newmod.py"]},
                "claims_text": _CLAIMS,
                "attested_evidence": _attested_bundle(),
            },
            max_candidates=100,
            max_statement_chars=1000,
        )
        new_carrier_id = str(_carrier(candidates)["id"])
        new_digests = {
            row.digest for row in store2.list_evidence_for_memory(new_carrier_id)
        }
        preserved = store2.list_evidence_for_memory(approved.id)
    finally:
        store2.close()

    assert _RECEIPT_DIGEST in new_digests
    assert len(preserved) == 1
    assert preserved[0].ref == "human_approval:maintainer"
    assert preserved[0].digest is None
