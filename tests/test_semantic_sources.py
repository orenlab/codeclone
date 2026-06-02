# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from pathlib import Path

from codeclone.audit.events import EVENT_INTENT_DECLARED, AuditEvent, repo_root_digest
from codeclone.audit.writer import SqliteAuditWriter
from codeclone.memory.enums import MemoryStatus
from codeclone.memory.models import (
    MemoryQuery,
    MemoryRecord,
    MemorySubject,
    generate_memory_id,
)
from codeclone.memory.semantic.sources import AuditIndexSource, MemoryIndexSource
from tests.memory_fixtures import make_module_record


class _FakeStore:
    def __init__(
        self,
        records: list[MemoryRecord],
        subjects: dict[str, list[MemorySubject]],
    ) -> None:
        self._records = records
        self._subjects = subjects

    def query_records(self, query: MemoryQuery) -> Sequence[MemoryRecord]:
        return self._records[query.offset : query.offset + query.limit]

    def list_subjects_for_memory(self, memory_id: str) -> list[MemorySubject]:
        return self._subjects.get(memory_id, [])


def _prose(
    project_id: str,
    *,
    statement: str,
    status: MemoryStatus = "active",
) -> MemoryRecord:
    # Reuse the fixture builder + replace -> avoids a duplicated 25-field literal.
    base = make_module_record(project_id, "codeclone/sample.py")
    return dataclasses.replace(
        base,
        id=generate_memory_id(),
        type="contract_note",
        status=status,
        statement=statement,
    )


def test_memory_index_source_filters_type_and_status() -> None:
    project_id = "proj-1"
    indexed = _prose(project_id, statement="recover keeps the checkpoint")
    rejected = _prose(project_id, statement="rejected note", status="rejected")
    structural = make_module_record(project_id, "codeclone/mod.py")  # module_role
    subjects = {
        indexed.id: [
            MemorySubject(
                id="s1",
                memory_id=indexed.id,
                subject_kind="path",
                subject_key="codeclone/sample.py",
            )
        ]
    }
    store = _FakeStore([structural, indexed, rejected], subjects)
    source = MemoryIndexSource(store, project_id=project_id)

    assert source.available() is True
    projections = list(source.iter_projections())
    assert len(projections) == 1  # module_role + rejected skipped
    assert projections[0].source_id == indexed.id
    assert projections[0].kind == "contract_note"
    assert projections[0].subject_path == "codeclone/sample.py"


def test_audit_index_source_gating(tmp_path: Path) -> None:
    db_path = tmp_path / "audit.sqlite3"
    # Disabled -> unavailable regardless of file presence.
    assert AuditIndexSource(enabled=False, db_path=db_path).available() is False
    # Enabled but file absent -> unavailable, and iteration is empty (no raise).
    absent = AuditIndexSource(enabled=True, db_path=db_path)
    assert absent.available() is False
    assert list(absent.iter_projections()) == []


def test_audit_index_source_projects_summary_column(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    db_path = tmp_path / "audit.sqlite3"
    # payloads="off" still populates the summary column (Bug B).
    writer = SqliteAuditWriter(db_path=db_path, payloads="off", retention_days=30)
    try:
        writer.emit(
            AuditEvent(
                event_type=EVENT_INTENT_DECLARED,
                severity="info",
                repo_root_digest=repo_root_digest(root),
                agent_pid=1,
                agent_label="test",
                payload={"intent_description": "recover after MCP restart"},
            )
        )
    finally:
        writer.close()

    source = AuditIndexSource(enabled=True, db_path=db_path)
    assert source.available() is True
    projections = list(source.iter_projections())
    assert len(projections) == 1
    assert projections[0].source == "audit"
    assert projections[0].kind == "intent.declared"
    assert "recover after MCP restart" in projections[0].text
