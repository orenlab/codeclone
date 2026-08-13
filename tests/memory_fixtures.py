# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from codeclone.audit.events import AuditEvent, repo_root_digest
from codeclone.audit.schema import open_audit_db
from codeclone.audit.writer import SqliteAuditWriter
from codeclone.config.memory import resolve_memory_config
from codeclone.memory.application import MemoryApplicationContext
from codeclone.memory.exceptions import UnfitAnalysisRunError
from codeclone.memory.governance import record_candidate
from codeclone.memory.identity import make_identity_key
from codeclone.memory.ingest.run_fitness import (
    REFUSAL_REASONS,
    refusal_message,
    unmeasured_refusal_message,
)
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
from codeclone.models import BaselineContainerV3, TrustVector
from codeclone.report.meta import current_report_timestamp_utc
from codeclone.utils.json_io import read_json_object
from tests._report_fixtures import (
    build_test_report_document,
    health_family_for_population,
)

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


def unfit_run_refusal(root: Path) -> UnfitAnalysisRunError:
    """The exact refusal a memory init raises for a run that measured nothing.

    Built here so a CLI test can raise the real typed outcome carrying the
    real wording without importing the memory ingest package itself: ingest
    sits at ring r2p and a CLI test module sits at r4, which the architecture
    ratchet does not allow to reach across.
    """

    return UnfitAnalysisRunError(
        unmeasured_refusal_message(root=str(root), surface="cli")
    )


def mcp_refusal_next_steps() -> tuple[str, ...]:
    """Every refusal remedy, rendered as an MCP caller receives it.

    Lives here because the two halves of the check sit in different rings: a
    memory test may not import the MCP surface, and an MCP test may not import
    memory ingest. A fixture module is not a ``test_*.py``, so it is the
    subject of neither ring rule, and this module already owns the CLI-side
    refusal — the seam is where it already was, not one cut open for this.
    """

    return tuple(
        step
        for reason in sorted(REFUSAL_REASONS)
        if (step := refusal_message(reason=reason, root="/repo", surface="mcp"))
        is not None
    )


def tool_calls_named_in(step: str) -> tuple[str, ...]:
    """The tools a step tells its reader to call, read out of the step itself.

    Taken from the artifact rather than listed beside it. A list of "tools we
    mention" is a second record of one fact, and it rots exactly where it
    hurts: silently, while the guard consulting it stays green and blesses a
    step naming something nobody can call. Nothing here needs keeping in sync,
    because the step is the only copy.
    """

    return tuple(sorted(set(re.findall(r"\b([a-z][a-z0-9_]*)\s*\(", step))))


def memory_application_context(root: Path) -> MemoryApplicationContext:
    """The context a memory read path needs, resolved from a repository root.

    Keeps the memory-configuration lookup on this side of the fixture seam so
    that ring-r2p test modules do not have to import the r2 configuration
    package to ask a retrieval question.
    """

    config = resolve_memory_config(root)
    return MemoryApplicationContext(
        config=config,
        db_path=resolve_memory_db_path(root, config),
        project=resolve_project_identity(root),
    )


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
        "meta": {"runtime": {"scan_root_absolute": str(fallback_root.resolve())}},
        "integrity": {
            "digests": {
                "comparison": {
                    "value": "a" * 64,
                    "algorithm": "sha256",
                    "digest_version": "1",
                    "kind": "comparison",
                }
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
    """A repository whose branch, identity, and history come from this fixture.

    ``git init`` takes the first branch name from the host's
    ``init.defaultBranch``, so a test that reads the branch back was really
    reading the developer's machine: ``main`` on a workstation configured for
    it, ``master`` on a stock runner. Writing ``HEAD`` here makes the name a
    property of the fixture instead of the environment, and ``symbolic-ref``
    does it on every git version without consulting configuration at all.
    """

    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "symbolic-ref", "HEAD", "refs/heads/main"],
        cwd=root,
        check=True,
        capture_output=True,
    )
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
    report_document = build_test_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        meta={"scan_root": str(root.resolve())},
        inventory={"file_list": registry_items},
    )
    report_path.write_text(
        json.dumps(report_document, sort_keys=True),
        encoding="utf-8",
    )
    return root, report_path, report_document


def report_document_for_counters(
    root: Path,
    *,
    found: int,
    analyzed: int,
    registry_items: list[str],
    baseline_container: BaselineContainerV3 | None = None,
    baseline_trust: TrustVector | None = None,
) -> dict[str, object]:
    """A report of a run that found ``found`` files and read ``analyzed``.

    Those two counters are the whole input the population classifier reads, so
    a fixture that states them describes the run's fitness without naming it —
    which keeps callers free of the vocabulary and of its renames.

    Shared rather than copied: the run-fitness tests and the memory-sync tests
    both need such a run, and a second assembly would be a second thing to
    keep true. A scope with nothing to find lists nothing, because an
    inventory that contradicted its own counters would be a fixture no real
    run produces.
    """

    return build_test_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        meta={"scan_root": str(root.resolve())},
        inventory={
            "file_list": list(registry_items) if found else [],
            "files": {
                "total_found": found,
                "analyzed": analyzed,
                "skipped": max(0, found - analyzed),
            },
        },
        metrics={
            "health": health_family_for_population(found=found, analyzed=analyzed)
        },
        baseline_container=baseline_container,
        baseline_trust=baseline_trust,
    )


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
