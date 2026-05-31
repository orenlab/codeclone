# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

from codeclone.memory.coverage import compute_scope_coverage, coverage_delta
from codeclone.memory.identity import make_identity_key
from codeclone.memory.models import MemoryRecord, MemorySubject, generate_memory_id
from codeclone.memory.project import resolve_project_identity
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore
from codeclone.report.meta import current_report_timestamp_utc


def test_scope_coverage_counts_paths_with_memory(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    project = resolve_project_identity(root)
    store = SqliteEngineeringMemoryStore(tmp_path / "memory.sqlite3")
    try:
        store.initialize(project)
        now = current_report_timestamp_utc()
        record = MemoryRecord(
            id=generate_memory_id(),
            project_id=project.id,
            identity_key=make_identity_key(
                type="module_role",
                subject_kind="module",
                subject_key="pkg.mod",
                discriminator="inventory_module",
            ),
            type="module_role",
            status="active",
            confidence="supported",
            origin="system",
            ingest_source="analysis",
            statement="module",
            summary=None,
            payload=None,
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
        store.upsert_record(record)
        store.write_subject(
            MemorySubject(
                id=generate_memory_id(prefix="subj"),
                memory_id=record.id,
                subject_kind="path",
                subject_key="pkg/mod.py",
                relation="about",
            )
        )
        report = compute_scope_coverage(
            store,
            project_id=project.id,
            scope_paths=("pkg/mod.py", "pkg/other.py"),
        )
        assert report.scope_paths_total == 2
        assert report.scope_paths_with_memory == 1
        assert report.scope_coverage_percent == 50
        assert report.uncovered_paths == ("pkg/other.py",)
        delta = coverage_delta(report, report)
        assert delta["scope_coverage_before"] == 50
        assert delta["scope_coverage_after"] == 50
    finally:
        store.close()
