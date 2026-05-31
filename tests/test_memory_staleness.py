# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from codeclone.memory.models import MemorySubject, RecordBatch, generate_memory_id
from codeclone.memory.staleness import apply_refresh_staleness
from tests.memory_fixtures import make_module_record, memory_store


def test_refresh_marks_missing_system_records_stale(tmp_path: Path) -> None:
    report = {
        "inventory": {
            "file_registry": {"items": ["pkg/kept.py"]},
        }
    }
    with memory_store(tmp_path) as (_root, project, store, _db_path):
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
    with memory_store(tmp_path) as (_root, project, store, _db_path):
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
        )
        loaded = store.find_by_identity_key(project.id, existing.identity_key)
        assert loaded is not None
        assert loaded.statement == "pkg.mod module"
        assert loaded.status == "stale"
        assert loaded.stale_reason == "refresh_content_contradiction"


def test_refresh_does_not_stale_batch_records_on_digest_shift(tmp_path: Path) -> None:
    report = {"inventory": {"file_registry": {"items": ["pkg/mod.py"]}}}
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        existing = make_module_record(project.id, "pkg.mod", report_digest="digest-a")
        store.upsert_record(existing)
        incoming = replace(existing, report_digest="digest-b")
        batch = RecordBatch(records=[incoming])
        report_result = apply_refresh_staleness(
            store,
            project_id=project.id,
            batch=batch,
            report_document=report,
            report_digest="digest-b",
        )
        assert report_result.records_marked_stale == 0
        loaded = store.find_by_identity_key(project.id, existing.identity_key)
        assert loaded is not None
        assert loaded.status == "active"
