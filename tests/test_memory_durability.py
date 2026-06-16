# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
import sqlite3
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from codeclone.config.memory import resolve_memory_config
from codeclone.memory.governance import record_candidate
from codeclone.memory.identity import make_identity_key
from codeclone.memory.models import (
    MemoryLink,
    MemoryRecord,
    MemorySubject,
    RecordBatch,
    generate_memory_id,
)
from codeclone.memory.project import (
    read_git_provenance,
    subject_path_fingerprint,
)
from codeclone.memory.staleness import (
    SUBJECT_FINGERPRINT_DRIFT,
    apply_refresh_staleness,
)
from codeclone.memory.vacuum import run_memory_vacuum
from codeclone.report.meta import current_report_timestamp_utc
from tests.memory_fixtures import init_git_repo, memory_store


def _write_subject_file(root: Path, rel_path: str, content: str) -> None:
    file_path = root / rel_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")


def _git_commit_all(root: Path, message: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=root,
        check=True,
        capture_output=True,
    )


def _anchored_active_record(
    *,
    project_id: str,
    root: Path,
    rel_path: str,
    content: str,
) -> tuple[MemoryRecord, str]:
    init_git_repo(root)
    _write_subject_file(root, rel_path, content)
    _git_commit_all(root, "anchor subject")
    git = read_git_provenance(root)
    fingerprint = subject_path_fingerprint(root, rel_path)
    assert fingerprint is not None
    now = current_report_timestamp_utc()
    record = MemoryRecord(
        id=generate_memory_id(),
        project_id=project_id,
        identity_key=make_identity_key(
            type="change_rationale",
            subject_kind="path",
            subject_key=rel_path,
            discriminator="durability-test",
        ),
        type="change_rationale",
        status="active",
        confidence="supported",
        origin="agent",
        ingest_source="agent",
        statement="durability anchor test",
        summary=None,
        payload={"subject_path": rel_path},
        created_at_utc=now,
        updated_at_utc=now,
        last_verified_at_utc=now,
        expires_at_utc=None,
        created_by="test",
        verified_by=None,
        approved_by="human",
        approved_at_utc=now,
        report_digest=None,
        code_fingerprint=fingerprint,
        stale_reason=None,
        created_on_branch=git.branch,
        created_at_commit=git.head,
        verified_on_branch=git.branch,
        verified_at_commit=git.head,
    )
    return record, fingerprint


def test_non_python_subject_stays_active_when_not_in_inventory(
    tmp_path: Path,
) -> None:
    report = {"inventory": {"file_registry": {"items": ["pkg/kept.py"]}}}
    with memory_store(tmp_path) as (root, project, store, _db_path):
        rel = "docs/guide.md"
        record, _ = _anchored_active_record(
            project_id=project.id,
            root=root,
            rel_path=rel,
            content="# Guide\n",
        )
        store.upsert_record(record)
        store.write_subject(
            MemorySubject(
                id=generate_memory_id(prefix="subj"),
                memory_id=record.id,
                subject_kind="doc",
                subject_key=rel,
                relation="about",
            )
        )
        result = apply_refresh_staleness(
            store,
            project_id=project.id,
            batch=RecordBatch(records=[]),
            report_document=report,
            root_path=root,
        )
        loaded = store.find_record(record.id)
        assert result.records_marked_stale == 0
        assert loaded is not None
        assert loaded.status == "active"


def test_subject_content_change_marks_stale(tmp_path: Path) -> None:
    report: dict[str, object] = {"inventory": {"file_registry": {"items": []}}}
    with memory_store(tmp_path) as (root, project, store, _db_path):
        rel = "notes/plan.md"
        record, _ = _anchored_active_record(
            project_id=project.id,
            root=root,
            rel_path=rel,
            content="v1\n",
        )
        store.upsert_record(record)
        store.write_subject(
            MemorySubject(
                id=generate_memory_id(prefix="subj"),
                memory_id=record.id,
                subject_kind="doc",
                subject_key=rel,
                relation="about",
            )
        )
        _write_subject_file(root, rel, "v2\n")
        result = apply_refresh_staleness(
            store,
            project_id=project.id,
            batch=RecordBatch(records=[]),
            report_document=report,
            root_path=root,
        )
        loaded = store.find_record(record.id)
        assert result.records_marked_stale == 1
        assert loaded is not None
        assert loaded.status == "stale"
        assert loaded.stale_reason == SUBJECT_FINGERPRINT_DRIFT


def test_deleted_subject_becomes_historical_and_survives_vacuum(
    tmp_path: Path,
) -> None:
    report: dict[str, object] = {"inventory": {"file_registry": {"items": []}}}
    with memory_store(tmp_path) as (root, project, store, _db_path):
        rel = "assets/runtime.js"
        record, _ = _anchored_active_record(
            project_id=project.id,
            root=root,
            rel_path=rel,
            content="console.log('ok');\n",
        )
        store.upsert_record(record)
        store.write_subject(
            MemorySubject(
                id=generate_memory_id(prefix="subj"),
                memory_id=record.id,
                subject_kind="path",
                subject_key=rel,
                relation="about",
            )
        )
        (root / rel).unlink()
        apply_refresh_staleness(
            store,
            project_id=project.id,
            batch=RecordBatch(records=[]),
            report_document=report,
            root_path=root,
        )
        loaded = store.find_record(record.id)
        assert loaded is not None
        assert loaded.status == "historical"

        config = resolve_memory_config(root)
        config = replace(config, stale_retention_days=0, rejected_retention_days=365)
        vacuum = run_memory_vacuum(store, config)
        assert vacuum.total_deleted == 0
        assert store.find_record(record.id) is not None


def test_restored_matching_fingerprint_reactivates(tmp_path: Path) -> None:
    report: dict[str, object] = {"inventory": {"file_registry": {"items": []}}}
    with memory_store(tmp_path) as (root, project, store, _db_path):
        rel = "config/app.toml"
        original = "key = 1\n"
        record, fingerprint = _anchored_active_record(
            project_id=project.id,
            root=root,
            rel_path=rel,
            content=original,
        )
        store.upsert_record(record)
        store.write_subject(
            MemorySubject(
                id=generate_memory_id(prefix="subj"),
                memory_id=record.id,
                subject_kind="path",
                subject_key=rel,
                relation="about",
            )
        )
        (root / rel).unlink()
        apply_refresh_staleness(
            store,
            project_id=project.id,
            batch=RecordBatch(records=[]),
            report_document=report,
            root_path=root,
        )
        _write_subject_file(root, rel, original)
        result = apply_refresh_staleness(
            store,
            project_id=project.id,
            batch=RecordBatch(records=[]),
            report_document=report,
            root_path=root,
        )
        loaded = store.find_record(record.id)
        assert result.records_reactivated == 1
        assert loaded is not None
        assert loaded.status == "active"
        assert loaded.stale_reason is None
        assert fingerprint == subject_path_fingerprint(root, rel)


def test_unanchored_record_never_drift_stales(tmp_path: Path) -> None:
    report: dict[str, object] = {"inventory": {"file_registry": {"items": []}}}
    with memory_store(tmp_path) as (root, project, store, _db_path):
        from tests.memory_fixtures import make_module_record

        record = make_module_record(project.id, "pkg.orphan")
        store.upsert_record(record)
        store.write_subject(
            MemorySubject(
                id=generate_memory_id(prefix="subj"),
                memory_id=record.id,
                subject_kind="path",
                subject_key="pkg/missing.py",
                relation="about",
            )
        )
        result = apply_refresh_staleness(
            store,
            project_id=project.id,
            batch=RecordBatch(records=[record]),
            report_document=report,
            root_path=root,
        )
        loaded = store.find_record(record.id)
        assert result.records_marked_stale == 0
        assert loaded is not None
        assert loaded.status == "active"


def test_human_origin_anchor_drifts_on_content_change(tmp_path: Path) -> None:
    report: dict[str, object] = {"inventory": {"file_registry": {"items": []}}}
    with memory_store(tmp_path) as (root, project, store, _db_path):
        rel = "notes/human.md"
        record, _ = _anchored_active_record(
            project_id=project.id,
            root=root,
            rel_path=rel,
            content="v1\n",
        )
        human = replace(record, origin="human", ingest_source="human")
        store.upsert_record(human)
        store.write_subject(
            MemorySubject(
                id=generate_memory_id(prefix="subj"),
                memory_id=human.id,
                subject_kind="doc",
                subject_key=rel,
                relation="about",
            )
        )
        _write_subject_file(root, rel, "v2\n")
        result = apply_refresh_staleness(
            store,
            project_id=project.id,
            batch=RecordBatch(records=[]),
            report_document=report,
            root_path=root,
        )
        loaded = store.find_record(human.id)
        assert result.records_marked_stale == 1
        assert loaded is not None
        assert loaded.status == "stale"
        assert loaded.stale_reason == SUBJECT_FINGERPRINT_DRIFT


def test_record_candidate_writes_commit_anchor(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, _db_path):
        init_git_repo(root)
        rel = "docs/anchor.md"
        _write_subject_file(root, rel, "anchor\n")
        _git_commit_all(root, "anchor docs")
        config = resolve_memory_config(root)
        record = record_candidate(
            store,
            project=project,
            root_path=root,
            record_type="risk_note",
            statement="Anchor test note.",
            subject_path=rel,
            max_candidates=config.max_candidates,
        )
        assert record.created_at_commit is not None
        assert record.created_on_branch is not None
        assert (
            record.code_fingerprint
            == hashlib.sha1((root / rel).read_bytes()).hexdigest()
        )


def test_record_candidate_omits_commit_without_subject_fingerprint(
    tmp_path: Path,
) -> None:
    with memory_store(tmp_path) as (root, project, store, _db_path):
        init_git_repo(root)
        _write_subject_file(root, "README.md", "init\n")
        _git_commit_all(root, "init")
        config = resolve_memory_config(root)
        record = record_candidate(
            store,
            project=project,
            root_path=root,
            record_type="risk_note",
            statement="Missing subject file.",
            subject_path="docs/missing.md",
            max_candidates=config.max_candidates,
        )
        assert record.created_at_commit is None
        assert record.created_on_branch is None
        assert record.code_fingerprint is None


def test_persist_batch_rolls_back_atomically_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mid-batch failure must leave the store empty, not half-written.

    persist_batch participates in the caller's transaction (commit=False), so a
    failure after records and subjects are inserted must roll the whole batch
    back. Before the atomic-batch fix, upsert_record / write_subject committed
    mid-batch, so the surrounding transaction rollback could not undo them.
    """
    from tests.memory_fixtures import make_module_record

    with memory_store(tmp_path) as (_root, project, store, _db_path):
        record = make_module_record(project.id, "pkg.atomic")
        now = current_report_timestamp_utc()
        batch = RecordBatch(
            records=[record],
            subjects=[
                MemorySubject(
                    id=generate_memory_id(prefix="subj"),
                    memory_id=record.id,
                    subject_kind="module",
                    subject_key="pkg.atomic",
                    relation="about",
                )
            ],
            links=[
                MemoryLink(
                    id=generate_memory_id(prefix="link"),
                    project_id=project.id,
                    from_memory_id=record.id,
                    to_memory_id=record.id,
                    relation="related_to",
                    created_by="test",
                    created_at_utc=now,
                )
            ],
        )

        def _boom(_link: MemoryLink) -> None:
            raise sqlite3.Error("injected mid-batch failure")

        monkeypatch.setattr(store, "write_link", _boom)

        with (
            pytest.raises(sqlite3.Error, match="injected mid-batch failure"),
            store.transaction(),
        ):
            store.persist_batch(batch, commit=False)

        # Records inserted earlier in the batch must not survive the failure.
        assert store.count_records() == 0


def test_audit_reader_missing_db_and_connect_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.audit.reader import (
        count_audit_event_core_gaps,
        list_workflow_ids_with_events_after,
        read_audit_event_core_records,
        read_audit_summary,
    )
    from codeclone.audit.schema import ensure_schema
    from codeclone.audit.validation import AuditReadError

    missing = tmp_path / "missing.sqlite3"
    with pytest.raises(AuditReadError, match="no audit data"):
        read_audit_event_core_records(db_path=missing, repo_root_digest="digest")
    assert (
        list_workflow_ids_with_events_after(
            db_path=missing,
            repo_root_digest="digest",
            after_id=0,
        )
        == ()
    )
    assert count_audit_event_core_gaps(db_path=missing, repo_root_digest="digest") == 0

    audit_db = tmp_path / "audit.sqlite3"
    conn = sqlite3.connect(audit_db)
    try:
        ensure_schema(conn)
        conn.commit()
    finally:
        conn.close()

    def _fail_open(_path: Path) -> sqlite3.Connection:
        raise sqlite3.Error("connect failed")

    monkeypatch.setattr(
        "codeclone.audit.reader.open_audit_db_readonly",
        _fail_open,
    )
    with pytest.raises(AuditReadError, match="cannot open audit database"):
        list_workflow_ids_with_events_after(
            db_path=audit_db,
            repo_root_digest="digest",
            after_id=0,
        )
    with pytest.raises(AuditReadError, match="cannot open audit database"):
        count_audit_event_core_gaps(db_path=audit_db, repo_root_digest="digest")

    class _BrokenConn:
        def execute(self, *_args: object, **_kwargs: object) -> None:
            raise sqlite3.Error("query failed")

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        "codeclone.audit.reader.open_audit_db_readonly",
        lambda *_a, **_k: _BrokenConn(),
    )
    with pytest.raises(AuditReadError, match="cannot read audit database"):
        read_audit_summary(db_path=audit_db, limit=5)
