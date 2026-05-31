# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from codeclone.memory.identity import make_identity_key
from codeclone.memory.models import (
    MemoryRecord,
    MemorySubject,
    RecordBatch,
    generate_memory_id,
)
from codeclone.memory.project import resolve_project_identity
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore
from codeclone.memory.staleness import apply_refresh_staleness
from codeclone.report.meta import current_report_timestamp_utc


def _module_record(project_id: str, module_path: str) -> MemoryRecord:
    now = current_report_timestamp_utc()
    return MemoryRecord(
        id=generate_memory_id(),
        project_id=project_id,
        identity_key=make_identity_key(
            type="module_role",
            subject_kind="module",
            subject_key=module_path,
            discriminator="inventory_module",
        ),
        type="module_role",
        status="active",
        confidence="supported",
        origin="system",
        ingest_source="analysis",
        statement=f"{module_path} module",
        summary=None,
        payload={"module_path": module_path},
        created_at_utc=now,
        updated_at_utc=now,
        last_verified_at_utc=now,
        expires_at_utc=None,
        created_by="test",
        verified_by=None,
        approved_by=None,
        approved_at_utc=None,
        report_digest=None,
        code_fingerprint=None,
        stale_reason=None,
        created_on_branch=None,
        created_at_commit=None,
        verified_on_branch=None,
        verified_at_commit=None,
    )


def test_refresh_marks_missing_system_records_stale(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    project = resolve_project_identity(root)
    store = SqliteEngineeringMemoryStore(tmp_path / "memory.sqlite3")
    report = {
        "inventory": {
            "file_registry": {"items": ["pkg/kept.py"]},
        }
    }
    try:
        store.initialize(project)
        kept = _module_record(project.id, "pkg.kept")
        removed = _module_record(project.id, "pkg.removed")
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
    finally:
        store.close()


def test_refresh_preserves_approved_statement_on_contradiction(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    project = resolve_project_identity(root)
    store = SqliteEngineeringMemoryStore(tmp_path / "memory.sqlite3")
    report = {"inventory": {"file_registry": {"items": ["pkg/mod.py"]}}}
    try:
        store.initialize(project)
        existing = _module_record(project.id, "pkg.mod")
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
    finally:
        store.close()
