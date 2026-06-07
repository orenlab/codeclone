# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

import dataclasses
import sqlite3
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
from codeclone.memory.semantic.sources import (
    AuditIndexSource,
    MemoryIndexSource,
    TrajectoryIndexSource,
)
from codeclone.memory.trajectory.models import (
    Trajectory,
    TrajectoryEvidence,
    TrajectoryListItem,
    TrajectoryStep,
    TrajectorySubject,
)
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


class _FakeTrajectoryStore:
    def __init__(self, trajectories: list[Trajectory]) -> None:
        self._trajectories = {trajectory.id: trajectory for trajectory in trajectories}

    def list_trajectories(
        self,
        *,
        project_id: str,
        limit: int = 20,
    ) -> list[TrajectoryListItem]:
        items = [
            TrajectoryListItem(
                id=trajectory.id,
                workflow_id=trajectory.workflow_id,
                outcome=trajectory.outcome,
                quality_tier=trajectory.quality_tier,
                quality_score=trajectory.quality_score,
                event_count=trajectory.event_count,
                started_at_utc=trajectory.started_at_utc,
                finished_at_utc=trajectory.finished_at_utc,
                summary=trajectory.summary,
            )
            for trajectory in self._trajectories.values()
            if trajectory.project_id == project_id
        ]
        return items[:limit]

    def find_trajectory(self, trajectory_id: str) -> Trajectory | None:
        return self._trajectories.get(trajectory_id)


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


def test_audit_index_source_skips_whitespace_only_summary(tmp_path: Path) -> None:
    from codeclone.audit.schema import ensure_schema

    db_path = tmp_path / "audit.sqlite3"
    conn = sqlite3.connect(str(db_path))
    try:
        ensure_schema(conn)
        conn.execute(
            "INSERT INTO controller_events "
            "(event_id, event_type, severity, created_at_utc, "
            "repo_root_digest, agent_label, agent_pid, status, summary) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "evt-ws",
                EVENT_INTENT_DECLARED,
                "info",
                "2026-06-02T10:00:00Z",
                "digest",
                "agent",
                1,
                "active",
                "   ",
            ),
        )
        conn.commit()
    finally:
        conn.close()
    source = AuditIndexSource(enabled=True, db_path=db_path)
    assert list(source.iter_projections()) == []


def test_audit_index_source_tolerates_sqlite_errors(tmp_path: Path) -> None:
    db_path = tmp_path / "audit.sqlite3"
    db_path.write_text("not sqlite", encoding="utf-8")
    source = AuditIndexSource(enabled=True, db_path=db_path)
    assert source.available() is True
    assert list(source.iter_projections()) == []


def test_memory_index_source_paginates_records() -> None:
    project_id = "proj-page"
    records = [
        _prose(project_id, statement=f"recover note {index}") for index in range(250)
    ]
    subjects = {
        record.id: [
            MemorySubject(
                id=f"s-{record.id}",
                memory_id=record.id,
                subject_kind="path",
                subject_key=f"codeclone/p{record.id}.py",
            )
        ]
        for record in records
    }
    store = _FakeStore(records, subjects)
    projections = list(
        MemoryIndexSource(store, project_id=project_id).iter_projections()
    )
    assert len(projections) == 250


def test_trajectory_index_source_projects_bounded_text() -> None:
    trajectory = _trajectory("proj-traj")
    source = TrajectoryIndexSource(
        _FakeTrajectoryStore([trajectory]),
        project_id="proj-traj",
    )

    projections = list(source.iter_projections())

    assert len(projections) == 1
    projection = projections[0]
    assert projection.source == "trajectory"
    assert projection.source_id == trajectory.id
    assert projection.subject_path == "pkg/service.py"
    assert "recover stale intent" in projection.text
    assert "pkg/service.py" in projection.text
    assert "intent.declared" in projection.text
    assert "event_core_json" not in projection.text
    assert '{"secret"' not in projection.text


def _trajectory(project_id: str) -> Trajectory:
    return Trajectory(
        id="traj-1",
        project_id=project_id,
        repo_root_digest="root",
        workflow_id="intent:intent-1",
        intent_id="intent-1",
        primary_run_id="run-after",
        first_run_id="run-before",
        last_run_id="run-after",
        report_digest="sha256:" + "a" * 64,
        outcome="accepted",
        quality_tier="verified",
        quality_score=95,
        labels=("recovered",),
        summary="recover stale intent before editing service",
        trajectory_digest="d" * 64,
        source_event_stream_digest="e" * 64,
        projection_version="trajectory-v1",
        event_count=2,
        step_count=2,
        incident_count=0,
        started_at_utc="2026-01-01T00:00:00Z",
        finished_at_utc="2026-01-01T00:00:01Z",
        projected_at_utc="2026-01-01T00:00:02Z",
        updated_at_utc="2026-01-01T00:00:02Z",
        steps=(
            TrajectoryStep(
                step_index=0,
                audit_sequence=1,
                event_id="evt-1",
                event_type="intent.declared",
                status="active",
                run_id="run-before",
                report_digest=None,
                event_core_sha256="1" * 64,
                event_core_json='{"secret":"not indexed"}',
                summary="recover stale intent",
                created_at_utc="2026-01-01T00:00:00Z",
            ),
        ),
        subjects=(
            TrajectorySubject(
                subject_kind="path",
                subject_key="pkg/service.py",
                relation="about",
            ),
        ),
        evidence=(
            TrajectoryEvidence(
                evidence_kind="audit_event_stream",
                ref="intent:intent-1",
                locator="1",
                digest="e" * 64,
                created_at_utc="2026-01-01T00:00:02Z",
            ),
        ),
    )
