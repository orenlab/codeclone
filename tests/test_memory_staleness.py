# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from codeclone.memory.models import (
    MemoryEvidence,
    MemoryRecord,
    MemorySubject,
    RecordBatch,
    generate_memory_id,
)
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore
from codeclone.memory.staleness import (
    apply_refresh_staleness,
    apply_scope_staleness,
    inventory_paths_from_report,
)
from codeclone.report.meta import current_report_timestamp_utc
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


def test_refresh_marks_evidence_digest_mismatch_when_batch_differs(
    tmp_path: Path,
) -> None:
    report = {"inventory": {"file_registry": {"items": ["pkg/mod.py"]}}}
    with memory_store(tmp_path) as (root, project, store, _db_path):
        existing = make_module_record(project.id, "pkg.mod")
        store.upsert_record(existing)
        store.write_evidence(
            MemoryEvidence(
                id="ev-old",
                memory_id=existing.id,
                evidence_kind="report",
                ref="run-1",
                locator=None,
                quote=None,
                digest="digest-a",
                created_at_utc=current_report_timestamp_utc(),
            )
        )
        store.commit()
        incoming = replace(existing, statement="updated")
        batch = RecordBatch(
            records=[incoming],
            evidence=[
                MemoryEvidence(
                    id="ev-new",
                    memory_id=incoming.id,
                    evidence_kind="report",
                    ref="run-1",
                    locator=None,
                    quote=None,
                    digest="digest-b",
                    created_at_utc=current_report_timestamp_utc(),
                )
            ],
        )
        result = apply_refresh_staleness(
            store,
            project_id=project.id,
            batch=batch,
            report_document=report,
            root_path=root,
        )
        loaded = store.find_record(existing.id)
        assert result.records_marked_stale >= 1
        assert loaded is not None
        assert loaded.stale_reason == "evidence_digest_mismatch"


def test_refresh_human_origin_unanchored_stays_active_without_system_signals(
    tmp_path: Path,
) -> None:
    report: dict[str, object] = {"inventory": {"file_registry": {"items": []}}}
    with memory_store(tmp_path) as (root, project, store, _db_path):
        human = replace(
            make_module_record(project.id, "pkg.human"),
            origin="human",
        )
        store.upsert_record(human)
        result = apply_refresh_staleness(
            store,
            project_id=project.id,
            batch=RecordBatch(records=[]),
            report_document=report,
            root_path=root,
        )
        assert result.records_marked_stale == 0
        loaded = store.find_record(human.id)
        assert loaded is not None
        assert loaded.status == "active"


def test_staleness_audit_validation_and_events_edges(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.audit.events import (
        EVENT_INTENT_CHECKED,
        EVENT_WORKSPACE_CONFLICT,
        event_core_for_event,
        event_summary,
    )
    from codeclone.audit.reader import (
        count_audit_event_core_gaps,
        list_workflow_ids_with_events_after,
        read_audit_event_core_records,
    )
    from codeclone.audit.validation import (
        AuditReadError,
        AuditValidationError,
        EventRow,
        validate_event_row,
    )
    from codeclone.memory.staleness import (
        _batch_evidence_index,
        apply_refresh_staleness,
    )

    from .memory_fixtures import memory_store
    from .test_audit_events_coverage import _event, _facts

    orphan_evidence = MemoryEvidence(
        id=generate_memory_id(prefix="evid"),
        memory_id="missing-record",
        evidence_kind="report",
        ref="digest",
        locator=None,
        quote=None,
        digest="abc",
        created_at_utc="2026-01-01T00:00:00Z",
    )
    assert _batch_evidence_index(RecordBatch(evidence=[orphan_evidence])) == {}

    conflict_core = event_core_for_event(
        _event(EVENT_WORKSPACE_CONFLICT, concurrent_intents=[{"intent_id": "a"}])
    )
    assert _facts(conflict_core)["concurrent_intents"] == 1

    many_declared = [f"pkg/file_{index}.py" for index in range(60)]
    check_payload = event_core_for_event(
        _event(
            EVENT_INTENT_CHECKED,
            declared_scope=[*many_declared, 123, "../escape", "/abs"],
            actual_changed_files=["pkg/file_0.py"],
            status="clean",
        )
    )
    check_facts = check_payload["facts"]
    assert isinstance(check_facts, dict)
    assert check_facts.get("paths_truncated") is True
    assert check_facts.get("untouched_in_declared")

    summary = event_summary(
        "analysis.completed",
        {"source": "mcp", "health": {"score": "high"}},
    )
    assert summary == "analysis completed (mcp)"

    base_row = EventRow(
        event_id="evt_val",
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
    )
    with pytest.raises(AuditValidationError, match="event_core_json must be JSON"):
        validate_event_row(
            replace(
                base_row,
                event_core_json="{bad",
                event_core_sha256="c" * 64,
            )
        )
    with pytest.raises(AuditValidationError, match="must be a JSON object"):
        validate_event_row(
            replace(
                base_row,
                event_core_json='["list"]',
                event_core_sha256="d" * 64,
            )
        )
    import hashlib
    import json

    bad_version = json.dumps(
        {
            "core_schema_version": "0",
            "event_family": "analysis",
            "event_type": "analysis.completed",
            "facts": {},
            "status": "",
            "truncated": False,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    with pytest.raises(AuditValidationError, match="unsupported core_schema_version"):
        validate_event_row(
            replace(
                base_row,
                event_core_json=bad_version,
                event_core_sha256=hashlib.sha256(bad_version.encode()).hexdigest(),
            )
        )
    good_core = json.dumps(
        {
            "core_schema_version": "2",
            "event_family": "analysis",
            "event_type": "analysis.completed",
            "facts": {},
            "status": "",
            "truncated": False,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    with pytest.raises(AuditValidationError, match="does not match event_core_json"):
        validate_event_row(
            replace(
                base_row,
                event_core_json=good_core,
                event_core_sha256="f" * 64,
            )
        )
    with pytest.raises(AuditValidationError, match="must be lowercase sha256 hex"):
        validate_event_row(
            replace(
                base_row,
                event_core_json=good_core,
                event_core_sha256="G" * 64,
            )
        )

    report: dict[str, object] = {"inventory": {"file_registry": {"items": []}}}
    memory_root = tmp_path / "memory"
    memory_root.mkdir()
    with memory_store(memory_root) as (root, project, store, _db_path):
        draft = MemoryRecord(
            id=generate_memory_id(),
            project_id=project.id,
            identity_key="draft:note:1",
            type="risk_note",
            status="draft",
            confidence="inferred",
            origin="agent",
            ingest_source="agent",
            statement="draft only",
            summary=None,
            payload={},
            created_at_utc="2026-01-01T00:00:00Z",
            updated_at_utc="2026-01-01T00:00:00Z",
            last_verified_at_utc=None,
            expires_at_utc=None,
            created_by="agent",
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
        store.write_record(draft)
        stale = replace(
            draft, id=generate_memory_id(), status="stale", identity_key="stale:1"
        )
        store.write_record(stale)
        store.commit()
        draft_result = apply_refresh_staleness(
            store,
            project_id=project.id,
            batch=RecordBatch(records=[]),
            report_document=report,
            root_path=root,
        )
        assert draft_result.records_marked_stale == 0

    audit_db = tmp_path / "audit-read.sqlite3"
    conn = sqlite3.connect(audit_db)
    try:
        from codeclone.audit.schema import ensure_schema

        ensure_schema(conn)
        conn.commit()
    finally:
        conn.close()

    class _BrokenConn:
        def execute(self, *_args: object, **_kwargs: object) -> None:
            raise sqlite3.Error("query failed")

        def close(self) -> None:
            return None

    def _broken_open(_path: Path) -> _BrokenConn:
        return _BrokenConn()

    monkeypatch.setattr(
        "codeclone.audit.reader.open_audit_db_readonly",
        _broken_open,
    )
    audit_db_error = "cannot .* audit database"
    with pytest.raises(AuditReadError, match=audit_db_error):
        read_audit_event_core_records(db_path=audit_db, repo_root_digest="digest")
    with pytest.raises(AuditReadError, match=audit_db_error):
        list_workflow_ids_with_events_after(
            db_path=audit_db,
            repo_root_digest="digest",
            after_id=0,
        )
    with pytest.raises(AuditReadError, match=audit_db_error):
        count_audit_event_core_gaps(db_path=audit_db, repo_root_digest="digest")


def test_refresh_stale_primary_reason_skips_stale_records(tmp_path: Path) -> None:
    from codeclone.memory.staleness import _refresh_stale_primary_reason

    with memory_store(tmp_path) as (_root, project, store, _db_path):
        stale = MemoryRecord(
            id=generate_memory_id(),
            project_id=project.id,
            identity_key="risk_note:stale:1",
            type="risk_note",
            status="stale",
            confidence="supported",
            origin="system",
            ingest_source="analysis",
            statement="already stale",
            summary=None,
            payload={},
            created_at_utc="2026-01-01T00:00:00Z",
            updated_at_utc="2026-01-01T00:00:00Z",
            last_verified_at_utc=None,
            expires_at_utc=None,
            created_by="test",
            verified_by=None,
            approved_by=None,
            approved_at_utc=None,
            report_digest="digest-a",
            code_fingerprint=None,
            stale_reason="missing_from_refresh",
            created_on_branch=None,
            created_at_commit=None,
            verified_on_branch=None,
            verified_at_commit=None,
        )
        store.write_record(stale)
        store.commit()
        assert (
            _refresh_stale_primary_reason(
                store,
                stale,
                batch_identity_keys=frozenset(),
                batch_by_identity={},
                batch_evidence={},
                report_digest="digest-b",
            )
            is None
        )


def test_experience_distiller_path_and_signal_helpers() -> None:
    from codeclone.memory.experience.distiller import (
        _agent_family,
        _path_family,
        _signals,
        pattern_keys,
    )
    from codeclone.memory.trajectory.models import Trajectory, TrajectorySubject

    assert _agent_family("cursor/cli") == "cursor"
    assert _path_family("not-valid-repo-path!") is None
    assert _path_family("mod.py") is None

    trajectory = Trajectory(
        id="traj-1",
        project_id="project",
        repo_root_digest="digest",
        workflow_id="workflow",
        intent_id="intent-1",
        primary_run_id=None,
        first_run_id=None,
        last_run_id=None,
        report_digest=None,
        outcome="partial",
        quality_tier="incident",
        quality_score=10,
        labels=("scope_expanded",),
        summary="summary",
        trajectory_digest="traj-digest",
        source_event_stream_digest="stream",
        projection_version="trajectory-v3",
        event_count=1,
        step_count=1,
        incident_count=2,
        started_at_utc="2026-01-01T00:00:00Z",
        finished_at_utc="2026-01-01T00:00:01Z",
        projected_at_utc="2026-01-01T00:00:02Z",
        updated_at_utc="2026-01-01T00:00:02Z",
        steps=(),
        subjects=(
            TrajectorySubject("agent", "codex/cli", "actor"),
            TrajectorySubject("path", "codeclone/memory/store.py", "about"),
        ),
        evidence=(),
    )
    signals = _signals(trajectory)
    assert "incident_present" in signals
    keys = pattern_keys(trajectory)
    assert keys


def test_read_intent_declared_records_wraps_open_failure(tmp_path: Path) -> None:
    from codeclone.audit.reader import read_intent_declared_records
    from codeclone.audit.validation import AuditReadError

    audit_db = tmp_path / "audit.sqlite3"
    audit_db.write_text("not-a-database", encoding="utf-8")
    with pytest.raises(AuditReadError, match="cannot open audit database"):
        read_intent_declared_records(db_path=audit_db, repo_root_digest="digest")


def test_read_intent_declared_records_wraps_read_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sqlite3

    from codeclone.audit.reader import read_intent_declared_records
    from codeclone.audit.validation import AuditReadError

    audit_db = tmp_path / "audit.sqlite3"
    conn = sqlite3.connect(audit_db)
    conn.execute("CREATE TABLE controller_events (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

    class _BrokenConn:
        def execute(self, *_args: object, **_kwargs: object) -> None:
            raise sqlite3.Error("read failed")

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        "codeclone.audit.reader.open_audit_db_readonly",
        lambda _path: _BrokenConn(),
    )
    with pytest.raises(AuditReadError, match="cannot read audit database"):
        read_intent_declared_records(db_path=audit_db, repo_root_digest="digest")
