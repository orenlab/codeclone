# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from codeclone.memory.models import MemorySubject, RecordBatch, generate_memory_id
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore
from codeclone.memory.staleness import (
    apply_refresh_staleness,
    apply_scope_staleness,
    inventory_paths_from_report,
)
from tests.memory_fixtures import make_module_record, memory_store


def test_refresh_marks_missing_system_records_stale(tmp_path: Path) -> None:
    report = {
        "inventory": {
            "file_registry": {"items": ["pkg/kept.py"]},
        }
    }
    with memory_store(tmp_path) as (root, project, store, _db_path):
        kept = make_module_record(project.id, "pkg.kept")
        removed = make_module_record(project.id, "pkg.removed")
        store.upsert_record(removed)
        store.write_subject(
            MemorySubject(
                id=generate_memory_id(prefix="subj"),
                memory_id=removed.id,
                subject_kind="path",
                subject_key="pkg/removed.py",
                relation="about",
            )
        )
        batch = RecordBatch(records=[kept])
        report_result = apply_refresh_staleness(
            store,
            project_id=project.id,
            batch=batch,
            report_document=report,
            root_path=root,
        )
        assert report_result.records_marked_stale >= 1
        loaded = store.find_by_identity_key(project.id, removed.identity_key)
        assert loaded is not None
        assert loaded.status == "stale"
        assert loaded.stale_reason == "missing_from_refresh"


def test_refresh_preserves_approved_statement_on_contradiction(
    tmp_path: Path,
) -> None:
    report = {"inventory": {"file_registry": {"items": ["pkg/mod.py"]}}}
    with memory_store(tmp_path) as (root, project, store, _db_path):
        existing = make_module_record(project.id, "pkg.mod")
        approved = replace(
            existing, approved_by="human", approved_at_utc=existing.created_at_utc
        )
        store.upsert_record(approved)
        incoming = replace(existing, statement="changed module role text")
        batch = RecordBatch(records=[incoming])
        apply_refresh_staleness(
            store,
            project_id=project.id,
            batch=batch,
            report_document=report,
            root_path=root,
        )
        loaded = store.find_by_identity_key(project.id, existing.identity_key)
        assert loaded is not None
        assert loaded.statement == "pkg.mod module"
        assert loaded.status == "stale"
        assert loaded.stale_reason == "refresh_content_contradiction"


def test_refresh_does_not_stale_batch_records_on_digest_shift(tmp_path: Path) -> None:
    report = {"inventory": {"file_registry": {"items": ["pkg/mod.py"]}}}
    with memory_store(tmp_path) as (root, project, store, _db_path):
        existing = make_module_record(project.id, "pkg.mod", report_digest="digest-a")
        store.upsert_record(existing)
        incoming = replace(existing, report_digest="digest-b")
        batch = RecordBatch(records=[incoming])
        report_result = apply_refresh_staleness(
            store,
            project_id=project.id,
            batch=batch,
            report_document=report,
            root_path=root,
            report_digest="digest-b",
        )
        assert report_result.records_marked_stale == 0
        loaded = store.find_by_identity_key(project.id, existing.identity_key)
        assert loaded is not None
        assert loaded.status == "active"


def test_refresh_marks_evidence_digest_mismatch_and_digest_shift(
    tmp_path: Path,
) -> None:
    report = {"inventory": {"file_registry": {"items": ["pkg/mod.py"]}}}
    with memory_store(tmp_path) as (root, project, store, _db_path):
        existing = make_module_record(project.id, "pkg.mod", report_digest="digest-a")
        store.upsert_record(existing)
        for evidence in RecordBatch(records=[existing]).evidence:
            store.write_evidence(evidence)

        report_result = apply_refresh_staleness(
            store,
            project_id=project.id,
            batch=RecordBatch(records=[]),
            report_document=report,
            root_path=root,
            report_digest="digest-b",
        )
        assert report_result.records_marked_stale >= 1


def test_scope_staleness_skips_already_stale_records(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        rec = make_module_record(project.id, "pkg.mod")
        store.upsert_record(rec)
        store.mark_stale(rec.id, "seed", commit=True)
        result = apply_scope_staleness(
            store,
            project_id=project.id,
            changed_paths=("pkg/mod.py",),
        )
        assert result.records_marked_stale == 0


def test_inventory_paths_from_report_normalizes_and_skips_blanks() -> None:
    paths = inventory_paths_from_report(
        {
            "inventory": {
                "file_registry": {
                    "items": ["", "pkg\\a.py", "pkg/b.py"],
                }
            }
        }
    )
    assert paths == frozenset({"pkg/a.py", "pkg/b.py"})


def test_anchor_drift_status_handles_missing_path_and_existing_stale_state(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    from codeclone.memory.models import MemorySubject, generate_memory_id
    from codeclone.memory.staleness import _evaluate_anchor_drift_status

    from .memory_fixtures import make_module_record, memory_store

    with memory_store(tmp_path) as (root, project, store, _db_path):
        record = replace(
            make_module_record(project.id, "pkg.mod"),
            created_at_commit="abc123",
            code_fingerprint="fp-1",
            status="active",
        )
        store.upsert_record(record)
        subject = MemorySubject(
            id=generate_memory_id(prefix="subj"),
            memory_id=record.id,
            subject_kind="path",
            subject_key="pkg/missing.py",
            relation="about",
        )
        store.write_subject(subject)
        assert (
            _evaluate_anchor_drift_status(
                record,
                anchor_subject=subject,
                root_path=root,
            )
            == "historical"
        )
        historical = replace(record, status="historical")
        assert (
            _evaluate_anchor_drift_status(
                historical,
                anchor_subject=subject,
                root_path=root,
            )
            is None
        )
        stale_record = replace(
            record, status="stale", stale_reason="subject_fingerprint_drift"
        )
        assert (
            _evaluate_anchor_drift_status(
                stale_record,
                anchor_subject=subject,
                root_path=root,
            )
            == "historical"
        )


def test_staleness_internal_noop_and_commit_edges(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from codeclone.memory import staleness
    from codeclone.memory.models import MemoryEvidence

    with memory_store(tmp_path) as (root, project, store, _db_path):
        record = make_module_record(project.id, "pkg.mod")
        subject = MemorySubject(
            id="subject",
            memory_id=record.id,
            subject_kind="path",
            subject_key="pkg/mod.py",
            relation="about",
        )

    monkeypatch.setattr(
        staleness,
        "_evaluate_anchor_drift_status",
        lambda *_args, **_kwargs: record.status,
    )
    outcome = staleness._apply_anchor_drift_for_record(
        store,
        record,
        anchor_subject=subject,
        root_path=root,
    )
    assert outcome.handled is True

    evidence = MemoryEvidence(
        id="evidence",
        memory_id=record.id,
        evidence_kind="report",
        ref="report",
        locator=None,
        quote=None,
        digest=None,
        created_at_utc=record.created_at_utc,
    )
    assert (
        staleness._evidence_stale_reasons(
            record,
            (evidence,),
            {(record.identity_key, "report", "report"): "new"},
        )
        == []
    )
    historical = replace(record, status="historical")
    assert (
        staleness._refresh_stale_primary_reason(
            cast("SqliteEngineeringMemoryStore", SimpleNamespace()),
            historical,
            batch_identity_keys=frozenset(),
            batch_by_identity={},
            batch_evidence={},
            report_digest=None,
        )
        is None
    )
    assert (
        staleness._refresh_staleness_for_record(
            cast("SqliteEngineeringMemoryStore", SimpleNamespace()),
            replace(record, status="draft"),
            resolved_root=root,
            batch_identity_keys=frozenset(),
            batch_by_identity={},
            batch_evidence={},
            report_digest=None,
        )
        == staleness._RefreshStalenessDelta()
    )

    commits: list[bool] = []
    fake_store = SimpleNamespace(
        list_records_for_project=lambda *_args, **_kwargs: (
            replace(record, status="stale"),
            record,
        ),
        list_subjects_for_memory=lambda _record_id: (),
        commit=lambda: commits.append(True),
    )
    result = staleness.apply_scope_staleness(
        cast("SqliteEngineeringMemoryStore", fake_store),
        project_id=project.id,
        changed_paths=("pkg/mod.py",),
        commit=True,
    )
    assert result.records_marked_stale == 0
    assert commits == [True]
