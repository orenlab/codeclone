# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from codeclone.audit.events import (
    EVENT_CLAIM_COMPLETED,
    AuditEvent,
    event_core_for_event,
)
from codeclone.config.memory import resolve_memory_config
from codeclone.memory.models import MemoryEvidence, MemoryRecord, generate_memory_id
from codeclone.memory.trajectory.export import export_trajectories_jsonl
from codeclone.memory.trajectory.export_context import select_canonical_trajectories
from codeclone.memory.trajectory.models import TRAJECTORY_PROJECTION_VERSION_V1
from codeclone.report.meta import current_report_timestamp_utc

from .memory_fixtures import (
    memory_store,
    seed_path_subject_record,
    seed_trajectory_audit_workflow,
)


def test_claim_event_core_includes_bounded_citations() -> None:
    core = event_core_for_event(
        AuditEvent(
            event_type=EVENT_CLAIM_COMPLETED,
            severity="info",
            repo_root_digest="digest",
            agent_pid=1,
            agent_label="agent",
            status="valid",
            payload={
                "valid": True,
                "citations_found": 1,
                "violations": [],
                "warnings": [],
                "validated_citations": [
                    {"cited_id": "finding-abc", "kind": "finding", "valid": True}
                ],
            },
        )
    )
    facts = core["facts"]
    assert isinstance(facts, dict)
    citations = facts.get("citations")
    assert isinstance(citations, list)
    assert citations[0]["cited_id"] == "finding-abc"


def test_select_canonical_trajectories_prefers_newer_projection_version(
    tmp_path: Path,
) -> None:
    with memory_store(tmp_path) as (root, project, store, _db_path):
        audit_db = tmp_path / "audit.sqlite3"
        seed_trajectory_audit_workflow(root=root, audit_db=audit_db)
        projection = store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        )
        current = projection.trajectories[0]
        legacy = replace(
            current,
            id="traj-legacy-test-id",
            projection_version=TRAJECTORY_PROJECTION_VERSION_V1,
            trajectory_digest="legacy-digest",
        )
        selected = select_canonical_trajectories([legacy, current])
        assert len(selected) == 1
        assert selected[0].projection_version == current.projection_version


def test_export_record_includes_context_citations_and_patch_trail(
    tmp_path: Path,
) -> None:
    with memory_store(tmp_path) as (root, project, store, _db_path):
        audit_db = tmp_path / "audit.sqlite3"
        seed_trajectory_audit_workflow(
            root=root,
            audit_db=audit_db,
            scope_path="pkg/service.py",
        )
        store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        )
        trajectory = store.list_canonical_trajectories_for_export(
            project_id=project.id
        )[0]
        record = seed_path_subject_record(
            store,
            project_id=project.id,
            path="pkg/service.py",
            statement="active memory for export context",
        )
        store.write_evidence(
            MemoryEvidence(
                id=generate_memory_id(prefix="evid"),
                memory_id=record.id,
                evidence_kind="trajectory",
                ref=trajectory.id,
                locator=None,
                quote=None,
                digest=trajectory.trajectory_digest,
                created_at_utc=current_report_timestamp_utc(),
            )
        )
        store.commit()
        config = resolve_memory_config(root)
        enabled = replace(config, trajectory_export_enabled=True)
        out = tmp_path / "export.jsonl"
        result = export_trajectories_jsonl(
            store=store,
            project=project,
            root_path=root,
            config=enabled,
            profile_name="agent-change-control-v1",
            output_path=out,
        )
        payload = json.loads(out.read_text(encoding="utf-8").strip())
        assert payload["schema_version"] == "2"
        assert "pkg/service.py" in payload["task"]["scope"]["paths"]
        assert payload["context"]["memory_precedents"]
        assert payload["context"]["memory_precedents"][0]["memory_id"] == record.id
        assert "patch_trail_summary" in payload
        assert result.manifest["deduplicated_workflows"] == 1


def test_export_context_helper_rejection_and_deduplication_edges(
    tmp_path: Path,
) -> None:
    from codeclone.memory.trajectory import export_context

    assert export_context.projection_version_rank("trajectory-vnext") == 0

    with memory_store(tmp_path) as (root, project, store, _db_path):
        audit_db = tmp_path / "audit.sqlite3"
        seed_trajectory_audit_workflow(root=root, audit_db=audit_db)
        current = store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        ).trajectories[0]

    legacy = replace(
        current,
        id="traj-legacy-later",
        projection_version=TRAJECTORY_PROJECTION_VERSION_V1,
    )
    assert select_canonical_trajectories([current, legacy]) == [current]

    citations: list[dict[str, object]] = []
    seen: set[tuple[str, str, int]] = set()
    for _ in range(2):
        export_context._append_trajectory_citation(
            citations,
            seen,
            kind="finding",
            cited_id="finding-1",
            valid=True,
            source_event_type="claim_validation.completed",
            audit_sequence=1,
            dedupe_sequence=1,
        )
    assert len(citations) == 1

    assert (
        export_context._trajectory_precedent_match(
            replace(
                current,
                id="traj-prior",
                workflow_id="intent:prior",
                started_at_utc="2025-01-01T00:00:00Z",
                finished_at_utc="2025-01-01T00:01:00Z",
                subjects=(),
            ),
            trajectory=current,
            scope_set={"pkg/missing.py"},
        )
        is None
    )


def test_export_context_observability_and_audit_validation_edges(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.audit.events import (
        EVENT_INTENT_CHECKED,
        EVENT_INTENT_DECLARED,
        EVENT_PATCH_VERIFIED,
    )
    from codeclone.audit.reader import read_audit_event_core_records
    from codeclone.audit.validation import (
        AuditReadError,
        AuditValidationError,
        EventRow,
        validate_event_row,
    )
    from codeclone.contracts import PLATFORM_OBSERVABILITY_SCHEMA_VERSION
    from codeclone.memory.trajectory.export_context import (
        _effective_scope_paths,
        _load_event_core,
        _prefer_trajectory_projection,
        _preview_text,
        build_export_context,
        extract_trajectory_citations,
        select_canonical_trajectories,
    )
    from codeclone.memory.trajectory.patch_trail_projector import (
        project_patch_trail_from_audit,
    )
    from codeclone.memory.trajectory.projector import TrajectoryProjectionError
    from codeclone.observability.models import OperationRecord
    from codeclone.observability.store.reader import (
        build_trace_view,
        open_observability_store_readonly,
    )
    from codeclone.observability.store.schema import (
        observability_store_path,
        open_observability_store,
    )
    from codeclone.observability.store.writer import write_operation
    from codeclone.report.meta import current_report_timestamp_utc

    from .memory_fixtures import memory_store, seed_trajectory_audit_workflow
    from .test_memory_trajectory_projector import _core, _record

    assert _load_event_core("{not-json") == {}
    assert _load_event_core('["list"]') == {}
    assert _preview_text("x" * 500).endswith("...")

    with memory_store(tmp_path) as (root, project, store, _db_path):
        audit_db = tmp_path / "audit.sqlite3"
        seed_trajectory_audit_workflow(root=root, audit_db=audit_db)
        projection = store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        )
        trajectory = projection.trajectories[0]
        dup_subject = replace(
            trajectory,
            subjects=(
                *trajectory.subjects,
                trajectory.subjects[0],
            ),
        )
        assert extract_trajectory_citations(dup_subject)
        assert (
            _effective_scope_paths(
                trajectory,
                scope_paths=(),
                patch_trail_payload=None,
            )
            == ()
        )
        no_precedents = build_export_context(
            store._conn,
            project_id=project.id,
            trajectory=trajectory,
            scope_paths=(),
            patch_trail_payload=None,
            canonical_by_workflow={trajectory.workflow_id: trajectory},
        )
        no_precedents_context = no_precedents["context"]
        assert isinstance(no_precedents_context, dict)
        assert no_precedents_context["trajectory_precedents"] == []

        for index in range(8):
            note = MemoryRecord(
                id=generate_memory_id(),
                project_id=project.id,
                identity_key=f"risk_note:test:{index}",
                type="risk_note",
                status="active",
                confidence="supported",
                origin="system",
                ingest_source="analysis",
                statement=f"linked precedent {index}",
                summary=None,
                payload={},
                created_at_utc=current_report_timestamp_utc(),
                updated_at_utc=current_report_timestamp_utc(),
                last_verified_at_utc=current_report_timestamp_utc(),
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
            store.write_record(note)
            store.write_evidence(
                MemoryEvidence(
                    id=generate_memory_id(prefix="evid"),
                    memory_id=note.id,
                    evidence_kind="trajectory",
                    ref=trajectory.id,
                    locator=None,
                    quote=None,
                    digest=trajectory.trajectory_digest,
                    created_at_utc=current_report_timestamp_utc(),
                )
            )
        store.commit()
        capped = build_export_context(
            store._conn,
            project_id=project.id,
            trajectory=trajectory,
            scope_paths=("pkg/service.py",),
            patch_trail_payload=None,
            canonical_by_workflow={trajectory.workflow_id: trajectory},
        )
        capped_context = capped["context"]
        assert isinstance(capped_context, dict)
        assert len(capped_context["memory_precedents"]) == 8

        older = replace(
            trajectory,
            id="traj-older-export",
            finished_at_utc="2020-01-01T00:00:00Z",
            started_at_utc="2020-01-01T00:00:00Z",
        )
        newer_same_version = replace(
            trajectory,
            id="traj-newer-export",
            finished_at_utc="2026-06-01T00:00:00Z",
        )
        canonical = select_canonical_trajectories([older, newer_same_version])
        assert len(canonical) == 1
        assert canonical[0].id == "traj-newer-export"
        assert _prefer_trajectory_projection(newer_same_version, older) is True
        tie_a = replace(
            newer_same_version,
            finished_at_utc=trajectory.finished_at_utc,
            id="traj-a",
        )
        tie_b = replace(
            newer_same_version,
            finished_at_utc=trajectory.finished_at_utc,
            id="traj-b",
        )
        assert _prefer_trajectory_projection(tie_b, tie_a) is True

    core_json, core_sha = _core(
        EVENT_INTENT_CHECKED,
        status="partial",
        declared_scope_paths=["pkg/a.py"],
        changed_files=["pkg/a.py"],
    )
    partial_check = replace(
        _record(
            2,
            EVENT_INTENT_CHECKED,
            declared_scope_paths=["pkg/a.py"],
            changed_files=["pkg/a.py"],
        ),
        status=None,
        event_core_json=core_json,
        event_core_sha256=core_sha,
    )
    declared_only = _record(1, EVENT_INTENT_DECLARED, status="active")
    trail = project_patch_trail_from_audit(
        records=(
            declared_only,
            partial_check,
            _record(3, "receipt.created"),
            _record(4, EVENT_PATCH_VERIFIED),
        ),
        repo_root_digest="digest",
    )
    assert trail is None or trail.scope_check_status == "partial"

    bad_digest = replace(
        _record(1, EVENT_INTENT_DECLARED, status="active", scope_paths=["pkg/a.py"]),
        event_core_sha256="0" * 64,
    )
    with pytest.raises(TrajectoryProjectionError, match="digest mismatch"):
        project_patch_trail_from_audit(
            records=(bad_digest,),
            repo_root_digest="digest",
        )

    audit_db = tmp_path / "broken-audit.sqlite3"
    audit_db.write_text("not sqlite", encoding="utf-8")
    real_connect = sqlite3.connect

    def _fail_event_core_connect(
        database: str, *args: Any, **kwargs: Any
    ) -> sqlite3.Connection:
        if database == str(audit_db):
            raise sqlite3.Error("connect failed")
        return cast(sqlite3.Connection, real_connect(database, *args, **kwargs))

    monkeypatch.setattr(sqlite3, "connect", _fail_event_core_connect)
    with pytest.raises(AuditReadError, match="cannot open audit database"):
        read_audit_event_core_records(db_path=audit_db, repo_root_digest="digest")

    row = EventRow(
        event_id="evt_surface",
        event_type="analysis.completed",
        severity="info",
        created_at_utc="2026-05-25T00:00:00Z",
        repo_root_digest="a" * 16,
        run_id="run1234567890abcdef",
        intent_id=None,
        report_digest="b" * 64,
        agent_label="agent",
        agent_pid=1,
        agent_start_epoch=None,
        status="full",
        payload_json="{}",
        surface="bogus",
    )
    with pytest.raises(AuditValidationError, match="invalid surface"):
        validate_event_row(row)

    row_sha_only = EventRow(
        event_id="evt_core",
        event_type="analysis.completed",
        severity="info",
        created_at_utc="2026-05-25T00:00:00Z",
        repo_root_digest="a" * 16,
        run_id="run1234567890abcdef",
        intent_id=None,
        report_digest="b" * 64,
        agent_label="agent",
        agent_pid=1,
        agent_start_epoch=None,
        status="full",
        payload_json="{}",
        event_core_json=None,
        event_core_sha256="c" * 64,
    )
    with pytest.raises(AuditValidationError, match="event_core_sha256 requires"):
        validate_event_row(row_sha_only)

    conn = open_observability_store(observability_store_path(tmp_path / "obs"))
    try:
        write_operation(
            conn,
            OperationRecord(
                operation_id="missing-op",
                correlation_id="missing-op",
                surface="mcp",
                name="mcp.check_patch_contract",
                started_at_utc="not-a-timestamp",
                duration_ms=10.0,
                status="ok",
                session_id="sess-1",
            ),
        )
        write_operation(
            conn,
            OperationRecord(
                operation_id="analyze-op",
                correlation_id="analyze-op",
                surface="mcp",
                name="mcp.analyze_repository",
                started_at_utc="2026-06-09T00:00:01Z",
                duration_ms=20.0,
                status="ok",
                session_id="sess-1",
            ),
        )
        write_operation(
            conn,
            OperationRecord(
                operation_id="query-op",
                correlation_id="query-op",
                surface="mcp",
                name="mcp.get_finding",
                started_at_utc="2026-06-09T00:00:02Z",
                duration_ms=15.0,
                status="ok",
            ),
        )
    finally:
        conn.close()

    read_conn = open_observability_store_readonly(tmp_path / "obs")
    assert read_conn is not None
    try:
        missing = build_trace_view(read_conn, operation_id="does-not-exist")
        assert missing.operation_tree == ()
        by_session = build_trace_view(read_conn, session_id="sess-1")
        assert by_session.aggregates.operation_count == 2
        recent = build_trace_view(read_conn, last=1)
        assert recent.schema_version == PLATFORM_OBSERVABILITY_SCHEMA_VERSION
        pipe = {group.name for group in recent.aggregates.pipeline}
        assert {"controller", "analysis", "mcp query"} & pipe
        assert recent.waterfall
    finally:
        read_conn.close()
