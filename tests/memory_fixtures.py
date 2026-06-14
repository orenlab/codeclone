# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from codeclone.audit.events import AuditEvent, repo_root_digest
from codeclone.audit.schema import open_audit_db
from codeclone.audit.writer import SqliteAuditWriter
from codeclone.config.memory import resolve_memory_config
from codeclone.memory.governance import record_candidate
from codeclone.memory.identity import make_identity_key
from codeclone.memory.models import (
    MemoryProject,
    MemoryRecord,
    MemorySubject,
    RecordBatch,
    generate_memory_id,
)
from codeclone.memory.project import (
    resolve_memory_db_path,
    resolve_project_identity,
)
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore
from codeclone.report.meta import current_report_timestamp_utc
from codeclone.utils.json_io import read_json_object

REPO_ROOT = Path(__file__).resolve().parents[1]


def insert_audit_event(
    audit_db: Path,
    *,
    event_id: str,
    event_type: str,
    status: str,
    summary: str,
    created_at_utc: str = "2026-01-01T00:00:00Z",
) -> None:
    """Insert one controller_events row (type/status/summary) for tests.

    Shared by the semantic audit-hydration tests so the controlled-row setup
    lives in one place instead of being copy-pasted (which trips the clone gate).
    """
    conn = open_audit_db(audit_db)
    try:
        conn.execute(
            "INSERT INTO controller_events (event_id, event_type, created_at_utc, "
            "repo_root_digest, agent_pid, status, summary) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (event_id, event_type, created_at_utc, "digest", 1, status, summary),
        )
        conn.commit()
    finally:
        conn.close()


def seed_trajectory_audit_workflow(
    *,
    audit_db: Path,
    root: Path,
    intent_id: str = "intent-traj-001",
    scope_path: str = "pkg/service.py",
    untouched_path: str | None = "pkg/helper.py",
    description: str = "recover stale intent before editing service",
    include_scope_check: bool = True,
) -> None:
    """Emit a minimal intent workflow into audit for trajectory projection tests."""
    root_digest = repo_root_digest(root.resolve())
    declared = [scope_path]
    if untouched_path:
        declared.append(untouched_path)
    changed = [scope_path]
    writer = SqliteAuditWriter(
        db_path=audit_db,
        payloads="compact",
        retention_days=30,
    )
    try:
        writer.emit(
            AuditEvent(
                event_type="intent.declared",
                severity="info",
                repo_root_digest=root_digest,
                agent_pid=123,
                agent_label="test-agent",
                intent_id=intent_id,
                run_id="run-before",
                report_digest="a" * 64,
                status="active",
                payload={
                    "intent_description": description,
                    "scope": {"allowed_files": declared},
                    "workspace_registered": True,
                    "ttl_seconds": 3600,
                    "lease_seconds": 600,
                },
            )
        )
        if include_scope_check:
            writer.emit(
                AuditEvent(
                    event_type="intent.checked",
                    severity="info",
                    repo_root_digest=root_digest,
                    agent_pid=123,
                    agent_label="test-agent",
                    intent_id=intent_id,
                    run_id="run-before",
                    report_digest="a" * 64,
                    status="clean",
                    payload={
                        "status": "clean",
                        "declared_scope": declared,
                        "actual_changed_files": changed,
                        "unexpected_files": [],
                        "forbidden_touched": [],
                        "required_action": None,
                        "message": "clean",
                    },
                )
            )
        writer.emit(
            AuditEvent(
                event_type="patch_contract.verified",
                severity="info",
                repo_root_digest=root_digest,
                agent_pid=123,
                agent_label="test-agent",
                intent_id=intent_id,
                run_id="run-after",
                report_digest="b" * 64,
                status="accepted",
                payload={
                    "status": "accepted",
                    "structural_delta": {
                        "regressions": [],
                        "improvements": [],
                        "health_delta": 0,
                    },
                    "contract_violations": [],
                    "baseline_abuse": {"detected": False},
                },
            )
        )
    finally:
        writer.close()


def seed_routine_analysis_audit(
    *,
    audit_db: Path,
    root: Path,
    run_id: str = "run-routine",
) -> None:
    from codeclone.audit.events import EVENT_ANALYSIS_COMPLETED

    writer = SqliteAuditWriter(
        db_path=audit_db,
        payloads="compact",
        retention_days=30,
    )
    try:
        writer.emit(
            AuditEvent(
                event_type=EVENT_ANALYSIS_COMPLETED,
                severity="info",
                repo_root_digest=repo_root_digest(root.resolve()),
                agent_pid=123,
                agent_label="test-agent",
                run_id=run_id,
                report_digest="c" * 64,
                status="ok",
                payload={
                    "source": "mcp",
                    "mode": "full",
                    "focus": "repository",
                    "health": {"score": 90, "grade": "A"},
                    "findings": {"total": 0, "new": 0},
                    "inventory": {"files": 1},
                },
            )
        )
    finally:
        writer.close()


def memory_project_db_paths(root: Path) -> tuple[MemoryProject, Path]:
    config = resolve_memory_config(root)
    db_path = resolve_memory_db_path(root, config)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    project = resolve_project_identity(root)
    resolved_root = root.resolve()
    if not db_path.resolve().is_relative_to(resolved_root):
        msg = f"memory db path must stay under test root: {db_path}"
        raise ValueError(msg)
    return project, db_path


def load_memory_init_report_document(
    *,
    registry_items: list[str] | None = None,
    fallback_root: Path | None = None,
    use_repo_cached_report: bool = False,
) -> dict[str, object]:
    if use_repo_cached_report:
        report_path = REPO_ROOT / ".codeclone" / "report.json"
        if report_path.is_file():
            loaded = read_json_object(report_path)
            if registry_items is not None:
                inventory = loaded.get("inventory")
                if isinstance(inventory, dict):
                    registry = inventory.get("file_registry")
                    if isinstance(registry, dict):
                        registry["items"] = registry_items
            return loaded
    if fallback_root is None:
        msg = "fallback_root is required for isolated memory ingest tests"
        raise ValueError(msg)
    items = registry_items or ["pkg/a.py"]
    first_item = items[0]
    return {
        "meta": {"scan_root": str(fallback_root.resolve())},
        "integrity": {
            "digest": {
                "value": "a" * 64,
                "algorithm": "sha256",
                "verified": True,
            }
        },
        "inventory": {"file_registry": {"items": items}},
        "metrics": {
            "api_surface": {
                "items": [
                    {
                        "path": first_item,
                        "symbol": "f",
                        "kind": "function",
                    }
                ]
            }
        },
        "findings": {"groups": {}},
    }


def init_git_repo(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=root,
        check=True,
        capture_output=True,
    )


def git_repo_with_cached_report(
    tmp_path: Path,
    *,
    py_sources: Mapping[str, str],
    registry_items: list[str],
) -> tuple[Path, Path, dict[str, object]]:
    root = tmp_path / "repo"
    root.mkdir()
    init_git_repo(root)
    for rel_path, content in py_sources.items():
        file_path = root / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=root,
        check=True,
        capture_output=True,
    )

    report_path = root / ".codeclone" / "report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("{}", encoding="utf-8")
    report_document: dict[str, object] = {
        "meta": {"scan_root": str(root.resolve())},
        "inventory": {"file_registry": {"items": registry_items}},
    }
    digest_payload = json.dumps(report_document, sort_keys=True, separators=(",", ":"))
    digest_value = hashlib.sha256(digest_payload.encode("utf-8")).hexdigest()
    report_document["integrity"] = {
        "digest": {
            "value": digest_value,
            "algorithm": "sha256",
            "verified": True,
        }
    }
    return root, report_path, report_document


def registry_items_from_report(report_document: Mapping[str, object]) -> list[str]:
    inventory = report_document.get("inventory")
    if not isinstance(inventory, dict):
        return []
    registry = inventory.get("file_registry")
    if not isinstance(registry, dict):
        return []
    raw_items = registry.get("items")
    if not isinstance(raw_items, list):
        return []
    return [str(item) for item in raw_items]


def enrich_report_with_api_surface(
    report_document: Mapping[str, object],
    *,
    module_path: str,
    symbol: str = "f",
) -> dict[str, object]:
    enriched = dict(report_document)
    enriched["metrics"] = {
        "api_surface": {
            "items": [
                {
                    "path": module_path,
                    "symbol": symbol,
                    "kind": "function",
                }
            ]
        }
    }
    return enriched


def run_memory_extractor_smoke(
    *,
    root: Path,
    extractor: Callable[..., RecordBatch],
    report_document: Mapping[str, object],
) -> dict[str, int]:
    from codeclone.config.memory import resolve_memory_config
    from codeclone.memory.ingest.extractors import (
        extract_contract_notes,
        extract_contradictions,
        extract_document_links,
        extract_git_hotspots,
        extract_module_roles,
        extract_public_surfaces,
        extract_risk_notes,
        extract_test_anchors,
        merge_batches,
    )
    from codeclone.memory.ingest.runner import planned_type_counts
    from codeclone.memory.project import (
        analysis_fingerprint_from_report,
        read_git_provenance,
        report_digest_from_report,
        resolve_project_identity,
    )

    project = resolve_project_identity(root)
    git = read_git_provenance(root)
    report_dict = dict(report_document)
    digest = report_digest_from_report(report_dict)
    fingerprint = analysis_fingerprint_from_report(report_dict)
    ingest = resolve_memory_config(root).ingest
    registry = frozenset(registry_items_from_report(report_document))
    kwargs: dict[str, object] = {
        "project": project,
        "git": git,
        "report_digest": digest,
        "analysis_fingerprint": fingerprint,
    }
    if extractor in {extract_contract_notes, extract_contradictions}:
        kwargs["root_path"] = root
        kwargs["ingest"] = ingest
        if extractor is extract_contract_notes:
            kwargs["registry_paths"] = registry
    elif extractor is extract_public_surfaces:
        kwargs["root_path"] = root
        kwargs["report_document"] = report_document
        kwargs["ingest"] = ingest
    elif extractor in {
        extract_git_hotspots,
        extract_test_anchors,
        extract_document_links,
        extract_module_roles,
        extract_risk_notes,
    }:
        kwargs["root_path"] = root
        if extractor is extract_document_links:
            kwargs["registry_paths"] = registry
            kwargs["ingest"] = ingest
        if extractor in {extract_module_roles, extract_risk_notes}:
            kwargs["report_document"] = report_document
    else:
        kwargs["report_document"] = report_document

    batch = extractor(**kwargs)
    merged = merge_batches([batch])
    return planned_type_counts(merged)


def make_module_record(
    project_id: str,
    module_path: str,
    *,
    report_digest: str | None = None,
    code_fingerprint: str | None = None,
) -> MemoryRecord:
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
        report_digest=report_digest,
        code_fingerprint=code_fingerprint,
        stale_reason=None,
        created_on_branch=None,
        created_at_commit=None,
        verified_on_branch=None,
        verified_at_commit=None,
    )


def seed_document_link(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    doc_file: str,
    ref_path: str,
    statement: str,
    heading: str = "section",
) -> MemoryRecord:
    now = current_report_timestamp_utc()
    record = MemoryRecord(
        id=generate_memory_id(),
        project_id=project_id,
        identity_key=make_identity_key(
            type="document_link",
            subject_kind="doc",
            subject_key=doc_file,
            discriminator=f"path:{ref_path}",
        ),
        type="document_link",
        status="active",
        confidence="supported",
        origin="system",
        ingest_source="doc",
        statement=statement,
        summary=None,
        payload={
            "doc_file": doc_file,
            "heading": heading,
            "anchored_symbols": [ref_path],
        },
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
            subject_kind="doc",
            subject_key=doc_file,
            relation="documents",
        )
    )
    return record


@contextmanager
def memory_store(
    tmp_path: Path,
) -> Iterator[tuple[Path, MemoryProject, SqliteEngineeringMemoryStore, Path]]:
    root = tmp_path / "repo"
    root.mkdir()
    project = resolve_project_identity(root)
    db_path = tmp_path / "memory.sqlite3"
    store = SqliteEngineeringMemoryStore(db_path)
    store.initialize(project)
    try:
        yield root, project, store, db_path
    finally:
        store.close()


def seed_module_role(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    file_path: str,
    statement: str = "module",
) -> MemoryRecord:
    now = current_report_timestamp_utc()
    module_key = file_path.replace("/", ".").removesuffix(".py")
    record = MemoryRecord(
        id=generate_memory_id(),
        project_id=project_id,
        identity_key=make_identity_key(
            type="module_role",
            subject_kind="module",
            subject_key=module_key,
            discriminator="inventory_module",
        ),
        type="module_role",
        status="active",
        confidence="supported",
        origin="system",
        ingest_source="analysis",
        statement=statement,
        summary=None,
        payload={"module_path": module_key},
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
            subject_kind="module",
            subject_key=module_key,
            relation="about",
        )
    )
    return record


def seed_path_linked_module_role(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    file_path: str,
    statement: str = "module",
) -> MemoryRecord:
    record = seed_module_role(
        store,
        project_id=project_id,
        file_path=file_path,
        statement=statement,
    )
    store.write_subject(
        MemorySubject(
            id=generate_memory_id(prefix="subj"),
            memory_id=record.id,
            subject_kind="path",
            subject_key=file_path,
            relation="about",
        )
    )
    return record


def seed_path_subject_record(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    path: str,
    statement: str,
) -> MemoryRecord:
    now = current_report_timestamp_utc()
    module_key = path.replace("/", ".").removesuffix(".py")
    record = MemoryRecord(
        id=generate_memory_id(),
        project_id=project_id,
        identity_key=make_identity_key(
            type="module_role",
            subject_kind="module",
            subject_key=module_key,
            discriminator="inventory_module",
        ),
        type="module_role",
        status="active",
        confidence="supported",
        origin="system",
        ingest_source="analysis",
        statement=statement,
        summary=None,
        payload={"module_path": module_key},
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
            subject_key=path,
            relation="about",
        )
    )
    return record


@contextmanager
def cli_memory_repo(
    tmp_path: Path,
    *,
    with_draft: bool = True,
) -> Iterator[tuple[Path, MemoryProject, SqliteEngineeringMemoryStore]]:
    """Repository root with engineering memory DB at the configured default path."""
    root = tmp_path / "repo"
    root.mkdir(parents=True, exist_ok=True)
    project, db_path = memory_project_db_paths(root)
    config = resolve_memory_config(root)
    store = SqliteEngineeringMemoryStore(db_path)
    store.initialize(project)
    try:
        seed_path_linked_module_role(
            store,
            project_id=project.id,
            file_path="pkg/mod.py",
            statement="fixture module for CLI coverage",
        )
        if with_draft:
            record_candidate(
                store,
                project=project,
                record_type="change_rationale",
                statement="draft candidate for review-candidates CLI",
                subject_path="pkg/mod.py",
                max_candidates=config.max_candidates,
            )
        yield root, project, store
    finally:
        store.close()
