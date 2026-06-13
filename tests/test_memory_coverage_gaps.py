# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal, cast
from unittest.mock import patch

import pytest

from codeclone.config.memory import IngestConfig, resolve_memory_config
from codeclone.config.memory_defaults import (
    DEFAULT_MEMORY_SOFT_STATEMENT_CHARS,
    DEFAULT_MEMORY_TARGET_STATEMENT_CHARS,
)
from codeclone.memory.exceptions import MemoryContractError, MemorySchemaError
from codeclone.memory.governance import validate_memory_claims
from codeclone.memory.ingest import InitOptions
from codeclone.memory.ingest.runner import _registry_paths, build_init_batch
from codeclone.memory.models import (
    MemoryEvidence,
    MemoryProject,
    MemoryRecord,
    MemorySubject,
    RecordBatch,
    generate_memory_id,
    parse_payload_json,
)
from codeclone.memory.project import (
    GitProvenance,
    analysis_fingerprint_from_report,
    read_git_provenance,
    resolve_memory_db_path,
    resolve_project_identity,
)
from codeclone.memory.retrieval import get_relevant_memory
from codeclone.memory.retrieval import service as retrieval_service
from codeclone.memory.retrieval.ranking import RankingContext, relevance_score
from codeclone.memory.retrieval.semantic import audit_event_row
from codeclone.memory.schema import open_memory_db
from codeclone.memory.search_index import build_search_text
from codeclone.memory.semantic.models import SemanticHit
from codeclone.memory.semantic.sources import AuditIndexSource, MemoryIndexSource
from codeclone.memory.staleness import apply_refresh_staleness, apply_scope_staleness
from codeclone.report.meta import current_report_timestamp_utc
from tests.memory_fixtures import (
    cli_memory_repo,
    git_repo_with_cached_report,
    make_module_record,
    memory_store,
    seed_trajectory_audit_workflow,
)


def _tool_count_contradiction_repo(
    tmp_path: Path,
    *,
    tools_json: str,
    doc_name: str,
    doc_text: str,
) -> tuple[Path, MemoryProject, GitProvenance, IngestConfig]:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "tools.json").write_text(tools_json, encoding="utf-8")
    (root / doc_name).write_text(doc_text, encoding="utf-8")
    project = resolve_project_identity(root)
    git = read_git_provenance(root)
    ingest = IngestConfig(
        mcp_tool_schema_snapshot_path="tools.json",
        mcp_tool_count_doc_paths=(doc_name,),
    )
    return root, project, git, ingest


def test_resolve_doc_anchor_path_normalizes_registry_and_filesystem(
    tmp_path: Path,
) -> None:
    from codeclone.memory.ingest.extractors import _resolve_doc_anchor_path

    root = tmp_path / "repo"
    root.mkdir()
    target = root / "pkg" / "mod.py"
    target.parent.mkdir(parents=True)
    target.write_text("x = 1\n", encoding="utf-8")
    loose = root / "standalone.py"
    loose.write_text("pass\n", encoding="utf-8")
    registry = frozenset({"pkg/mod.py"})
    assert _resolve_doc_anchor_path("", root_path=root, registry_paths=registry) is None
    assert (
        _resolve_doc_anchor_path("pkg/mod.py", root_path=root, registry_paths=registry)
        == "pkg/mod.py"
    )
    assert (
        _resolve_doc_anchor_path(
            "missing/path", root_path=root, registry_paths=registry
        )
        is None
    )
    assert (
        _resolve_doc_anchor_path("mod.py", root_path=root, registry_paths=registry)
        == "pkg/mod.py"
    )
    ambiguous = frozenset({"pkg/a/mod.py", "pkg/b/mod.py"})
    assert (
        _resolve_doc_anchor_path("mod.py", root_path=root, registry_paths=ambiguous)
        is None
    )
    assert (
        _resolve_doc_anchor_path(
            "standalone.py",
            root_path=root,
            registry_paths=frozenset(),
        )
        == "standalone.py"
    )


def test_registry_paths_rejects_malformed_inventory_sections() -> None:
    assert _registry_paths({"inventory": 1}) == frozenset()
    assert _registry_paths({"inventory": {"file_registry": 1}}) == frozenset()
    assert (
        _registry_paths({"inventory": {"file_registry": {"items": "x"}}}) == frozenset()
    )


def test_build_init_batch_malformed_inventory_shapes(tmp_path: Path) -> None:
    root, _report_path, _report_document = git_repo_with_cached_report(
        tmp_path,
        py_sources={"pkg/a.py": "x = 1\n"},
        registry_items=["pkg/a.py"],
    )
    project = resolve_project_identity(root)
    git = read_git_provenance(root)
    for report_document in (
        {"inventory": "not-a-map"},
        {"inventory": {"file_registry": 1}},
        {"inventory": {"file_registry": {"items": "not-a-list"}}},
    ):
        batch = build_init_batch(
            root_path=root,
            project=project,
            report_document=report_document,
            git=git,
            report_digest=None,
            analysis_fingerprint=None,
            options=InitOptions(include_docs=True, include_tests=False),
        )
        assert batch.records == []


def test_build_init_batch_registry_paths_via_docs_extract(tmp_path: Path) -> None:
    root, _report_path, _report_document = git_repo_with_cached_report(
        tmp_path,
        py_sources={"pkg/a.py": "x = 1\n"},
        registry_items=["pkg/a.py"],
    )
    (root / "docs").mkdir()
    (root / "docs" / "guide.md").write_text("See pkg/a.py\n", encoding="utf-8")
    project = resolve_project_identity(root)
    git = read_git_provenance(root)
    batch = build_init_batch(
        root_path=root,
        project=project,
        report_document={"inventory": {"file_registry": {"items": 99}}},
        git=git,
        report_digest=None,
        analysis_fingerprint=None,
        options=InitOptions(include_docs=True, include_tests=False),
    )
    assert isinstance(batch.records, list)


def test_build_search_text_scalar_payload() -> None:
    now = current_report_timestamp_utc()
    record = replace(
        make_module_record("proj", "pkg.mod"),
        payload=cast(Any, 42),
        created_at_utc=now,
        updated_at_utc=now,
        last_verified_at_utc=now,
    )
    text = build_search_text(record=record, subjects=[])
    assert "42" in text


def test_parse_payload_json_rejects_non_object() -> None:
    with pytest.raises(TypeError, match="payload_json must decode to an object"):
        parse_payload_json("[1, 2]")


def test_analysis_fingerprint_from_meta_timestamp() -> None:
    fp = analysis_fingerprint_from_report(
        {"meta": {"report_generated_at_utc": "2026-06-02T12:00:00Z"}}
    )
    assert fp != "unknown"
    assert len(fp) == 16


def test_read_git_provenance_unavailable_without_branch_or_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    monkeypatch.setattr(
        "codeclone.memory.project._git_output_optional",
        lambda _root, args: (
            None
            if args == ["rev-parse", "--abbrev-ref", "HEAD"]
            else "deadbeef"
            if args == ["rev-parse", "HEAD"]
            else None
        ),
    )
    git = read_git_provenance(root)
    assert git.available is False


def test_record_candidate_requires_subject_path(tmp_path: Path) -> None:
    from codeclone.memory.governance import record_candidate

    with (
        memory_store(tmp_path) as (_root, project, store, _db_path),
        pytest.raises(MemoryContractError, match="subject_path"),
    ):
        record_candidate(
            store,
            project=project,
            record_type="change_rationale",
            statement="needs a path",
            subject_path="   ",
            max_candidates=5,
        )


def test_validate_memory_claims_warns_when_stale_records_exist(
    tmp_path: Path,
) -> None:
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        stale = replace(
            make_module_record(project.id, "pkg.stale"),
            status="stale",
            stale_reason="seed",
        )
        store.upsert_record(stale)
        result = validate_memory_claims(
            store,
            project_id=project.id,
            text="There are no stale memory records in this project.",
        )
    assert any("stale" in warning.lower() for warning in result.warnings)


def test_validate_memory_claims_statement_length_warnings(
    tmp_path: Path,
) -> None:
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        over_target = "x" * (DEFAULT_MEMORY_TARGET_STATEMENT_CHARS + 1)
        over_soft = "y" * (DEFAULT_MEMORY_SOFT_STATEMENT_CHARS + 1)
        target_result = validate_memory_claims(
            store, project_id=project.id, text=over_target
        )
        soft_result = validate_memory_claims(
            store, project_id=project.id, text=over_soft
        )
    assert any("target" in warning for warning in target_result.warnings)
    assert any("soft limit" in warning for warning in soft_result.warnings)


def test_get_relevant_memory_requires_scope_or_symbols(tmp_path: Path) -> None:
    with (
        memory_store(tmp_path) as (_root, project, store, _db_path),
        pytest.raises(MemoryContractError, match="scope"),
    ):
        get_relevant_memory(
            store,
            project_id=project.id,
            scope_paths=(),
            symbols=(),
            scope_resolved_from="test",
        )


def test_handle_semantic_search_disabled_block(tmp_path: Path) -> None:
    from codeclone.memory.retrieval.service import _handle_semantic_search_mode

    with memory_store(tmp_path) as (_root, project, store, _db_path):
        payload = _handle_semantic_search_mode(
            store,
            project_id=project.id,
            query="recover checkpoint",
            filter_types=(),
            statuses=("active",),
            filter_confidences=(),
            match_mode="any",
            max_results=5,
            detail_level="compact",
            include_stale=False,
            include_drafts=False,
            semantic_index=None,
            embedding_provider=None,
            provider_label=None,
            semantic_reason=None,
            audit_db_path=None,
        )
    semantic = cast(dict[str, object], payload["semantic"])
    assert semantic["used"] is False
    assert semantic["reason"] == "disabled"


def test_hydrate_audit_events_skips_missing_rows(tmp_path: Path) -> None:
    audit_db = tmp_path / "audit.sqlite3"
    hits = [SemanticHit(source_id="missing", source="audit", score=0.5)]
    events = retrieval_service._hydrate_audit_events(audit_db, hits)
    assert events == []


def test_relevance_score_symbol_boost() -> None:
    now = current_report_timestamp_utc()
    record = MemoryRecord(
        id="mem-sym",
        project_id="proj",
        identity_key="id-sym",
        type="contract_note",
        status="active",
        confidence="verified",
        origin="system",
        ingest_source="contract",
        statement="symbol match",
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
    subjects = [
        MemorySubject(
            id="subj-sym",
            memory_id=record.id,
            subject_kind="symbol",
            subject_key="pkg.mod.fn",
            relation="about",
        )
    ]
    context = RankingContext.from_scope(
        scope_paths=(),
        symbols=("pkg.mod.fn",),
        blast_dependents=(),
    )
    score = relevance_score(
        record=record,
        subjects=subjects,
        context=context,
        evidence_count=0,
    )
    assert score > 0.0


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


def test_apply_scope_staleness_prefix_directory_match(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        record = make_module_record(project.id, "pkg.nested")
        store.upsert_record(record)
        store.write_subject(
            MemorySubject(
                id="subj-nested",
                memory_id=record.id,
                subject_kind="path",
                subject_key="pkg/nested/deep.py",
                relation="about",
            )
        )
        report = apply_scope_staleness(
            store,
            project_id=project.id,
            changed_paths=["pkg/nested"],
        )
        loaded = store.find_record(record.id)
        assert report.records_marked_stale == 1
        assert loaded is not None
        assert loaded.status == "stale"


def test_memory_index_source_without_path_subject() -> None:
    project_id = "proj-no-path"
    record = replace(
        make_module_record(project_id, "pkg.mod"),
        type="contract_note",
        statement="recover semantic index without path subject",
    )
    subjects = [
        MemorySubject(
            id="s-test",
            memory_id=record.id,
            subject_kind="test",
            subject_key="tests/test_mod.py",
            relation="about",
        )
    ]
    store = type(
        "_Store",
        (),
        {
            "query_records": lambda self, query: [record][
                query.offset : query.offset + 250
            ],
            "list_subjects_for_memories": lambda self, memory_ids: dict.fromkeys(
                memory_ids, subjects
            ),
        },
    )()
    source = MemoryIndexSource(cast(Any, store), project_id=project_id)
    projections = list(source.iter_projections())
    assert len(projections) == 1
    assert projections[0].subject_path is None


def test_audit_index_source_connect_error(tmp_path: Path) -> None:
    db_path = tmp_path / "audit.sqlite3"
    db_path.mkdir()
    source = AuditIndexSource(enabled=True, db_path=db_path)
    assert source.name() == "audit"
    assert list(source.iter_projections()) == []


def test_audit_event_row_connect_and_query_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audit_db = tmp_path / "audit.sqlite3"
    audit_db.mkdir()
    assert audit_event_row(audit_db, "evt-1") is None

    audit_file = tmp_path / "audit2.sqlite3"
    audit_file.write_text("not sqlite", encoding="utf-8")

    real_connect = sqlite3.connect

    def _fail_connect(
        database: str,
        timeout: float = 5.0,
        detect_types: int = 0,
        isolation_level: Literal["DEFERRED", "EXCLUSIVE", "IMMEDIATE"] | None = None,
        check_same_thread: bool = True,
        cached_statements: int = 128,
        uri: bool = False,
    ) -> sqlite3.Connection:
        if database == str(audit_file):
            raise sqlite3.Error("connect failed")
        return real_connect(
            database,
            timeout=timeout,
            detect_types=detect_types,
            isolation_level=isolation_level,
            check_same_thread=check_same_thread,
            cached_statements=cached_statements,
            uri=uri,
        )

    monkeypatch.setattr(sqlite3, "connect", _fail_connect)
    assert audit_event_row(audit_file, "evt-1") is None


def test_ensure_schema_raises_on_unsupported_version(tmp_path: Path) -> None:
    from codeclone.memory.schema import create_schema_v1, ensure_schema, set_meta

    db_path = tmp_path / "memory.sqlite3"
    conn = sqlite3.connect(db_path)
    try:
        create_schema_v1(conn)
        set_meta(conn, "schema_version", "0.0")
        conn.commit()
        with (
            patch(
                "codeclone.memory.schema_migrate.migrate_memory_schema",
                lambda _conn: None,
            ),
            pytest.raises(MemorySchemaError, match="Unsupported engineering memory"),
        ):
            ensure_schema(conn)
    finally:
        conn.close()


def test_execute_mcp_memory_sync_skips_without_report_digest(tmp_path: Path) -> None:
    from codeclone.memory.ingest.mcp_sync import execute_mcp_memory_sync

    root = tmp_path / "repo"
    root.mkdir()
    payload = execute_mcp_memory_sync(
        root_path=root,
        report_document={},
        trigger="auto",
        run_id="run-no-digest",
        force=False,
    )
    assert payload["status"] == "skipped"
    assert payload["reason"] == "missing_report_digest"


def test_open_sqlite_db_rejects_invalid_synchronous(tmp_path: Path) -> None:
    from codeclone.utils.sqlite_store import open_sqlite_db

    def _schema(conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")

    with pytest.raises(ValueError, match="synchronous must be one of"):
        open_sqlite_db(
            tmp_path / "bad.sqlite3",
            ensure_schema=_schema,
            synchronous="invalid",
        )


def test_registry_paths_rejects_non_mapping_inventory() -> None:
    from codeclone.memory.ingest.runner import _registry_paths

    assert _registry_paths({}) == frozenset()
    assert _registry_paths({"inventory": "bad"}) == frozenset()
    assert _registry_paths({"inventory": {"file_registry": "bad"}}) == frozenset()


def test_project_trajectory_edge_outcomes_and_labels() -> None:
    from codeclone.memory.trajectory.projector import (
        TrajectoryProjectionError,
        project_trajectory,
    )

    from .test_memory_trajectory_projector import _record

    with pytest.raises(TrajectoryProjectionError, match="requires events"):
        project_trajectory(
            project_id="proj",
            repo_root_digest="digest",
            workflow_id="intent:intent-a-001",
            records=(),
        )

    blocked = project_trajectory(
        project_id="proj",
        repo_root_digest="digest",
        workflow_id="intent:intent-a-001",
        records=(
            _record(1, "intent.declared", status="active"),
            _record(2, "intent.queue_blocked", status="blocked"),
        ),
    )
    assert blocked.outcome == "blocked"

    conflict = project_trajectory(
        project_id="proj",
        repo_root_digest="digest",
        workflow_id="intent:intent-a-001",
        records=(
            _record(1, "intent.declared", status="active"),
            _record(2, "workspace.conflict_detected", status="blocked"),
        ),
    )
    assert conflict.outcome == "blocked"
    assert "foreign_conflict_seen" in conflict.labels

    external = project_trajectory(
        project_id="proj",
        repo_root_digest="digest",
        workflow_id="intent:intent-a-001",
        records=(
            _record(1, "intent.declared", status="active"),
            _record(
                2,
                "patch_contract.verified",
                status="accepted_with_external_changes",
            ),
        ),
    )
    assert external.outcome == "accepted_with_external_changes"
    assert "external_changes_accepted" in external.labels

    expanded = project_trajectory(
        project_id="proj",
        repo_root_digest="digest",
        workflow_id="intent:intent-a-001",
        records=(
            _record(1, "intent.declared", status="active"),
            _record(2, "intent.expanded", status="expanded"),
            _record(3, "patch_contract.verified", status="accepted"),
        ),
    )
    assert "scope_expanded" in expanded.labels

    queued = project_trajectory(
        project_id="proj",
        repo_root_digest="digest",
        workflow_id="intent:intent-a-001",
        records=(
            _record(1, "intent.declared", status="active"),
            _record(2, "intent.queued", status="queued"),
            _record(3, "intent.promoted", status="active"),
            _record(4, "patch_contract.verified", status="accepted"),
        ),
    )
    assert "queue_used" in queued.labels
    assert "recovered" in queued.labels

    claim_failed = project_trajectory(
        project_id="proj",
        repo_root_digest="digest",
        workflow_id="intent:intent-a-001",
        records=(
            _record(1, "intent.declared", status="active"),
            _record(2, "claim_validation.violated", status="violated"),
        ),
    )
    assert "claim_guard_failed" in claim_failed.labels

    broken = _record(1, "intent.declared", status="active")
    missing_seq = replace(broken, audit_sequence=None)
    with pytest.raises(TrajectoryProjectionError, match="audit_sequence"):
        project_trajectory(
            project_id="proj",
            repo_root_digest="digest",
            workflow_id="intent:intent-a-001",
            records=(missing_seq,),
        )

    wrong_workflow = replace(broken, workflow_id="intent:other")
    with pytest.raises(TrajectoryProjectionError, match="mixed workflow"):
        project_trajectory(
            project_id="proj",
            repo_root_digest="digest",
            workflow_id="intent:intent-a-001",
            records=(wrong_workflow,),
        )


def test_retrieval_service_semantic_helpers_and_scope_family() -> None:
    from codeclone.memory.embedding import DeterministicHashEmbeddingProvider
    from codeclone.memory.retrieval import service as retrieval_service
    from codeclone.memory.semantic.models import SemanticHit, SemanticIndexStatus

    class _Index:
        def search(
            self, vector: object, *, k: int, source: str | None = None
        ) -> list[SemanticHit]:
            hits = [
                SemanticHit(source_id="mem-1", source="memory", score=0.9),
                SemanticHit(source_id="evt-1", source="audit", score=0.8),
                SemanticHit(source_id="traj-1", source="trajectory", score=0.7),
            ]
            if source is not None:
                hits = [hit for hit in hits if hit.source == source]
            return hits[:k]

        def status(self) -> SemanticIndexStatus:
            return SemanticIndexStatus(available=True, indexed_count=3)

    proximity, audit_hits, trajectory_hits = retrieval_service._semantic_hits(
        index=_Index(),
        provider=DeterministicHashEmbeddingProvider(dimension=8),
        query="recover",
        k=5,
    )
    assert "mem-1" in proximity
    assert len(audit_hits) == 1
    assert len(trajectory_hits) == 1
    assert retrieval_service._scope_family("") is None
    assert retrieval_service._scope_family("pkg/mod.py") == "pkg"

    assert retrieval_service._scope_family("../escape") is None


def test_trajectory_anomalies_projector_and_export_helpers() -> None:
    from codeclone.memory.trajectory.anomalies import (
        anomaly_summary,
        detect_trajectory_anomalies,
        serialize_anomaly,
    )
    from codeclone.memory.trajectory.export_context import extract_trajectory_citations
    from codeclone.memory.trajectory.patch_trail import compute_patch_trail
    from codeclone.memory.trajectory.projector import (
        TrajectoryProjectionError,
        project_trajectory,
    )
    from codeclone.memory.trajectory.retrieval import (
        serialize_patch_trail_summary,
        serialize_trajectory_preview,
    )

    from .test_memory_trajectory_coverage import _patch_trail_inputs
    from .test_memory_trajectory_projector import _record

    blocked = project_trajectory(
        project_id="proj",
        repo_root_digest="digest",
        workflow_id="intent:intent-a-001",
        records=(
            _record(1, "intent.declared", status="active"),
            _record(2, "intent.queue_blocked", status="blocked"),
        ),
    )
    blocked_anomalies = detect_trajectory_anomalies(blocked)
    assert any(item.kind == "outcome_blocked" for item in blocked_anomalies)

    abandoned = project_trajectory(
        project_id="proj",
        repo_root_digest="digest",
        workflow_id="intent:intent-a-001",
        records=(
            _record(1, "intent.declared", status="active"),
            _record(2, "intent.expired", status="expired"),
        ),
    )
    assert any(
        item.kind == "outcome_abandoned"
        for item in detect_trajectory_anomalies(abandoned)
    )

    hook = project_trajectory(
        project_id="proj",
        repo_root_digest="digest",
        workflow_id="intent:intent-a-001",
        records=(
            replace(
                _record(1, "intent.declared", status="active"),
                surface="hook",
                severity="warn",
            ),
            _record(2, "patch_contract.verified", status="accepted"),
        ),
    )
    assert "hook_blocked" in hook.labels

    memory_tool = project_trajectory(
        project_id="proj",
        repo_root_digest="digest",
        workflow_id="intent:intent-a-001",
        records=(
            replace(
                _record(1, "intent.declared", status="active"),
                tool_name="manage_engineering_memory",
            ),
            _record(2, "patch_contract.verified", status="accepted"),
        ),
    )
    assert "memory_used" in memory_tool.labels

    missing_core = replace(
        _record(1, "intent.declared"), event_core_json="", event_core_sha256=""
    )
    with pytest.raises(TrajectoryProjectionError, match="missing event core"):
        project_trajectory(
            project_id="proj",
            repo_root_digest="digest",
            workflow_id="intent:intent-a-001",
            records=(missing_core,),
        )

    with_citations = project_trajectory(
        project_id="proj",
        repo_root_digest="digest",
        workflow_id="intent:intent-a-001",
        records=(
            _record(1, "intent.declared", status="active"),
            _record(
                2,
                "claim_validation.completed",
                status="accepted",
                citations=[
                    {"kind": "finding", "cited_id": "finding-1", "valid": True},
                    {"kind": "", "cited_id": "", "valid": False},
                ],
            ),
            _record(3, "patch_contract.verified", status="accepted"),
        ),
    )
    extracted = extract_trajectory_citations(with_citations)
    assert extracted
    assert extracted[0]["kind"] == "finding"

    trail = compute_patch_trail(_patch_trail_inputs())
    violated_trail = replace(
        trail,
        scope_check_status="violated",
        verification_status="not_reached",
    )
    partial = project_trajectory(
        project_id="proj",
        repo_root_digest="digest",
        workflow_id="intent:intent-a-001",
        records=(
            _record(1, "intent.declared", status="active"),
            _record(2, "intent.queue_blocked", status="blocked"),
        ),
    )
    trail_anomalies = detect_trajectory_anomalies(
        partial,
        patch_trail_payload=violated_trail.to_payload(detail_level="summary"),
    )
    assert any(item.kind == "scope_violation" for item in trail_anomalies)
    summary = anomaly_summary([(partial, trail_anomalies)])
    error_count = summary["error_count"]
    assert isinstance(error_count, int)
    assert error_count >= 1
    assert serialize_anomaly(trail_anomalies[0])["kind"]

    preview = serialize_trajectory_preview(
        replace(with_citations, summary="x" * 500),
        detail_level="compact",
    )
    assert len(str(preview["summary"])) < 500
    patch_summary = serialize_patch_trail_summary(
        violated_trail.to_payload(detail_level="full")
    )
    assert patch_summary is not None
    assert patch_summary["scope_check_status"] == "violated"


def test_hydrate_trajectory_hits_skips_foreign_project(tmp_path: Path) -> None:
    from codeclone.memory.retrieval import service as retrieval_service
    from codeclone.memory.semantic.models import SemanticHit

    with memory_store(tmp_path) as (root, project, store, _db_path):
        audit_db = tmp_path / "audit.sqlite3"
        seed_trajectory_audit_workflow(root=root, audit_db=audit_db)
        trajectory = store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        ).trajectories[0]
        hits = retrieval_service._hydrate_trajectory_hits(
            store,
            project_id=project.id,
            hits=[SemanticHit(source_id=trajectory.id, source="trajectory", score=0.5)],
            detail_level="compact",
        )
        assert hits
        assert hits[0]["semantic_score"] == 0.5
        missing = retrieval_service._hydrate_trajectory_hits(
            store,
            project_id="other-project",
            hits=[SemanticHit(source_id=trajectory.id, source="trajectory", score=0.5)],
            detail_level="compact",
        )
        assert missing == []


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


def test_projection_job_pid_alive_and_reclaim_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.memory.jobs.store import _pid_alive, _reclaim_stale_running_jobs

    assert _pid_alive(None) is False
    assert _pid_alive("not-a-pid@host") is False
    assert _pid_alive("0@host") is False
    assert _pid_alive(f"{__import__('os').getpid()}@host") is True

    with cli_memory_repo(tmp_path, with_draft=False) as (root, project, _store):
        config = resolve_memory_config(root)
        db_path = resolve_memory_db_path(root, config)
        conn = open_memory_db(db_path)
        try:
            now = current_report_timestamp_utc()
            conn.execute(
                "INSERT INTO memory_projection_jobs("
                "id, project_id, job_kind, status, trigger, requested_at_utc, "
                "started_at_utc, claimed_by, attempt, stimulus_json"
                ") VALUES (?, ?, 'projection_bundle', 'running', 'cli', ?, ?, ?, 1, ?)",
                (
                    "job-stale",
                    project.id,
                    now,
                    "not-a-timestamp",
                    "999999@dead",
                    "{}",
                ),
            )
            conn.commit()
            _reclaim_stale_running_jobs(
                conn,
                project_id=project.id,
                running_timeout_seconds=1,
            )
            row = conn.execute(
                "SELECT status FROM memory_projection_jobs WHERE id=?",
                ("job-stale",),
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert str(row[0]) == "failed"


def test_parse_contract_constants_and_patch_trail_projector_edges(
    tmp_path: Path,
) -> None:
    from codeclone.memory.ingest.extractors import _parse_contract_constants
    from codeclone.memory.trajectory.patch_trail_projector import (
        project_patch_trail_from_audit,
    )

    from .test_memory_trajectory_projector import _record

    broken = tmp_path / "broken.py"
    broken.write_text("def (\n", encoding="utf-8")
    assert _parse_contract_constants(broken) == {}

    constants = tmp_path / "constants.py"
    constants.write_text(
        "CACHE_VERSION = 2\nIGNORED = 1\n",
        encoding="utf-8",
    )
    parsed = _parse_contract_constants(constants)
    assert parsed.get("CACHE_VERSION") == "2"

    assert project_patch_trail_from_audit(records=(), repo_root_digest="digest") is None
    non_intent = replace(
        _record(1, "intent.declared", status="active", scope_paths=["pkg/a.py"]),
        workflow_id="analysis:run-1",
    )
    assert (
        project_patch_trail_from_audit(
            records=(non_intent,),
            repo_root_digest="digest",
        )
        is None
    )


def test_extract_contradictions_handles_broken_snapshot_and_docs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.memory.ingest.extractors import extract_contradictions

    root, project, git, ingest = _tool_count_contradiction_repo(
        tmp_path,
        tools_json="{bad",
        doc_name="docs.md",
        doc_text="The server exposes 3 MCP tools for agents.",
    )
    docs = root / "docs.md"
    broken = extract_contradictions(
        project=project,
        root_path=root,
        git=git,
        report_digest="digest",
        analysis_fingerprint="fp",
        ingest=ingest,
    )
    assert broken.records == []

    (root / "tools.json").write_text(
        '{"tools": {"a": {}, "b": {}}}',
        encoding="utf-8",
    )

    original_read_text = Path.read_text

    def _raise_oserror(self: Path, *args: object, **kwargs: object) -> str:
        if self == docs:
            raise OSError("unreadable")
        return original_read_text(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", _raise_oserror)
    skipped = extract_contradictions(
        project=project,
        root_path=root,
        git=git,
        report_digest="digest",
        analysis_fingerprint="fp",
        ingest=ingest,
    )
    assert skipped.records == []


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


def test_patch_trail_projector_additional_audit_branches() -> None:
    from codeclone.audit.events import EVENT_INTENT_DECLARED
    from codeclone.memory.trajectory.patch_trail_projector import (
        _apply_audit_record,
        _WorkflowAuditState,
        project_patch_trail_from_audit,
    )

    from .test_memory_trajectory_projector import _record

    state = _WorkflowAuditState()
    _apply_audit_record(
        state,
        replace(
            _record(1, EVENT_INTENT_DECLARED, status="active"), audit_sequence=None
        ),
    )
    assert state.declared_files == ()

    assert (
        project_patch_trail_from_audit(
            records=(_record(1, EVENT_INTENT_DECLARED, status="active"),),
            repo_root_digest="digest",
        )
        is None
    )


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


def test_trajectory_projector_and_retrieval_residual_edges(tmp_path: Path) -> None:
    import hashlib

    from codeclone.audit.events import EVENT_INTENT_DECLARED
    from codeclone.memory.trajectory.projector import (
        TrajectoryProjectionError,
        project_trajectory,
    )
    from codeclone.memory.trajectory.retrieval import (
        rank_trajectories_for_query,
        serialize_patch_trail_summary,
    )

    from .test_memory_trajectory_projector import _record

    list_core = '["not","object"]'
    list_sha = hashlib.sha256(list_core.encode("utf-8")).hexdigest()
    bad_core = replace(
        _record(1, EVENT_INTENT_DECLARED, status="active"),
        event_core_json=list_core,
        event_core_sha256=list_sha,
    )
    with pytest.raises(TrajectoryProjectionError, match="JSON object"):
        project_trajectory(
            project_id="proj",
            repo_root_digest="digest",
            workflow_id="intent:intent-a-001",
            records=[bad_core],
        )

    missing_sequence = replace(
        _record(1, EVENT_INTENT_DECLARED, status="active"),
        audit_sequence=None,
    )
    with pytest.raises(TrajectoryProjectionError, match="audit_sequence"):
        project_trajectory(
            project_id="proj",
            repo_root_digest="digest",
            workflow_id="intent:intent-a-001",
            records=[missing_sequence],
        )

    assert serialize_patch_trail_summary(None) is None
    assert serialize_patch_trail_summary({"not": "trail"}) is None

    empty_hits, truncated = rank_trajectories_for_query(
        [],
        query="",
        max_results=5,
        match_mode="any",
    )
    assert empty_hits == []
    assert truncated is False

    missing_core = replace(
        _record(1, EVENT_INTENT_DECLARED, status="active"),
        event_core_json=None,
        event_core_sha256=None,
    )
    with pytest.raises(TrajectoryProjectionError, match="missing event core"):
        project_trajectory(
            project_id="proj",
            repo_root_digest="digest",
            workflow_id="intent:intent-a-001",
            records=[missing_core],
        )

    from codeclone.audit.events import EVENT_PATCH_VERIFIED

    abused = project_trajectory(
        project_id="proj",
        repo_root_digest="digest",
        workflow_id="intent:intent-a-001",
        records=(
            _record(
                1, EVENT_INTENT_DECLARED, status="active", scope_paths=["pkg/a.py"]
            ),
            _record(2, EVENT_PATCH_VERIFIED, status="accepted", baseline_abuse=True),
        ),
    )
    assert abused.outcome == "violated"

    from codeclone.config.memory import IngestConfig, resolve_memory_config

    ingest = IngestConfig.model_validate(
        {
            "contract_constants_paths": "codeclone/contracts/__init__.py",
            "mcp_tool_count_doc_paths": ["docs/book/25-mcp-interface/index.md"],
            "mcp_tool_schema_snapshot_path": "",
        }
    )
    assert ingest.mcp_tool_schema_snapshot_path is None
    assert ingest.contract_constants_paths == ("codeclone/contracts/__init__.py",)

    root = tmp_path / "cfg-root"
    root.mkdir()
    outside_db = tmp_path / "outside.sqlite3"
    outside_db.write_text("", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        f'[tool.codeclone.memory]\ndb_path = "{outside_db}"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must stay under the repository root"):
        resolve_memory_config(root)


def test_trajectory_quality_timestamp_and_band_edges() -> None:
    from codeclone.audit.events import EVENT_INTENT_DECLARED, EVENT_PATCH_VERIFIED
    from codeclone.memory.trajectory.projector import project_trajectory
    from codeclone.memory.trajectory.quality import (
        _complexity_band_label,
        _parse_utc_timestamp,
        compute_trajectory_duration_seconds,
    )

    from .test_memory_trajectory_projector import _record

    trajectory = project_trajectory(
        project_id="proj",
        repo_root_digest="digest",
        workflow_id="intent:intent-a-001",
        records=(
            _record(
                1, EVENT_INTENT_DECLARED, status="active", scope_paths=["pkg/a.py"]
            ),
            _record(2, EVENT_PATCH_VERIFIED, status="accepted"),
        ),
    )
    broken_times = replace(
        trajectory,
        started_at_utc="not-a-timestamp",
        finished_at_utc="also-bad",
    )
    assert compute_trajectory_duration_seconds(broken_times) == 0
    assert _parse_utc_timestamp("") is None
    assert _parse_utc_timestamp("bad-ts") is None
    assert _parse_utc_timestamp("2026-01-01T00:00:00Z") is not None
    assert _complexity_band_label(70) == ("high", "High")
    assert _complexity_band_label(35) == ("moderate", "Moderate")
    assert _complexity_band_label(10) == ("low", "Low")
    naive = _parse_utc_timestamp("2026-01-01T00:00:00")
    assert naive is not None
    assert naive.tzinfo is not None


def test_project_trajectory_external_changes_outcome() -> None:
    from codeclone.audit.events import EVENT_INTENT_DECLARED, EVENT_PATCH_VERIFIED
    from codeclone.memory.trajectory.projector import project_trajectory

    from .test_memory_trajectory_projector import _record

    trajectory = project_trajectory(
        project_id="proj",
        repo_root_digest="digest",
        workflow_id="intent:intent-a-001",
        records=(
            _record(
                1, EVENT_INTENT_DECLARED, status="active", scope_paths=["pkg/a.py"]
            ),
            _record(
                2,
                EVENT_PATCH_VERIFIED,
                status="accepted_with_external_changes",
            ),
        ),
    )
    assert trajectory.outcome == "accepted_with_external_changes"


def test_extract_contradictions_records_tool_count_mismatch(tmp_path: Path) -> None:
    from codeclone.memory.ingest.extractors import extract_contradictions

    root, project, git, ingest = _tool_count_contradiction_repo(
        tmp_path,
        tools_json='{"tools": {"a": {}, "b": {}}}',
        doc_name="docs.md",
        doc_text="The bundle exposes 3 MCP tools.",
    )
    batch = extract_contradictions(
        project=project,
        root_path=root,
        git=git,
        report_digest="digest",
        analysis_fingerprint="fp",
        ingest=ingest,
    )
    assert len(batch.records) == 1
    assert batch.records[0].type == "contradiction_note"

    (root / "docs-match.md").write_text(
        "The bundle exposes 2 MCP tools.", encoding="utf-8"
    )
    matching = extract_contradictions(
        project=project,
        root_path=root,
        git=git,
        report_digest="digest",
        analysis_fingerprint="fp",
        ingest=IngestConfig(
            mcp_tool_schema_snapshot_path="tools.json",
            mcp_tool_count_doc_paths=("docs-match.md",),
        ),
    )
    assert matching.records == []


def test_project_trajectory_agent_fallback_and_noncanonical_digest() -> None:
    import hashlib
    import json

    from codeclone.audit.events import EVENT_INTENT_CHECKED, EVENT_INTENT_DECLARED
    from codeclone.memory.trajectory.projector import project_trajectory

    from .test_memory_trajectory_projector import _core, _record

    checked = project_trajectory(
        project_id="proj",
        repo_root_digest="digest",
        workflow_id="intent:intent-a-001",
        records=(
            replace(
                _record(
                    1, EVENT_INTENT_DECLARED, status="active", scope_paths=["pkg/a.py"]
                ),
                agent_label="   ",
            ),
            replace(
                _record(
                    2,
                    EVENT_INTENT_CHECKED,
                    status="clean",
                    declared_scope_paths=["pkg/a.py"],
                    changed_files=["pkg/a.py"],
                ),
                agent_label="backup-agent",
            ),
        ),
    )
    agent_subjects = {
        (subject.subject_kind, subject.subject_key)
        for subject in checked.subjects
        if subject.subject_kind == "agent"
    }
    assert agent_subjects == {("agent", "backup-agent")}

    bad_facts_core, _bad_facts_sha = _core(
        EVENT_INTENT_DECLARED,
        status="active",
        scope_paths=["pkg/a.py"],
    )
    broken_facts = json.loads(bad_facts_core)
    broken_facts["facts"] = "not-a-mapping"
    broken_text = json.dumps(broken_facts, sort_keys=True, separators=(",", ":"))
    broken_sha = hashlib.sha256(broken_text.encode("utf-8")).hexdigest()
    short_digest = project_trajectory(
        project_id="proj",
        repo_root_digest="digest",
        workflow_id="intent:intent-a-001",
        records=(
            replace(
                _record(
                    1, EVENT_INTENT_DECLARED, status="active", scope_paths=["pkg/a.py"]
                ),
                event_core_json=broken_text,
                event_core_sha256=broken_sha,
                report_digest="short-digest",
            ),
        ),
    )
    assert short_digest.report_digest == "short-digest"


def test_serialize_patch_trail_summary_from_computed_trail() -> None:
    from codeclone.memory.trajectory.patch_trail import compute_patch_trail
    from codeclone.memory.trajectory.retrieval import serialize_patch_trail_summary

    from .test_memory_trajectory_coverage import _patch_trail_inputs

    trail = compute_patch_trail(_patch_trail_inputs())
    summary = serialize_patch_trail_summary(
        trail.to_payload(detail_level="summary"),
    )
    assert summary is not None
    assert summary["verification_status"] == "accepted"


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


def test_experience_distillation_opens_store_when_not_passed(
    tmp_path: Path,
) -> None:
    from codeclone.memory.exceptions import MemoryContractError
    from codeclone.memory.experience.distillation_workflow import (
        execute_experience_distillation,
    )

    empty_root = tmp_path / "empty-repo"
    empty_root.mkdir()
    missing_config = resolve_memory_config(empty_root)
    with pytest.raises(MemoryContractError, match="not found"):
        execute_experience_distillation(
            root_path=empty_root,
            config=missing_config,
        )

    with memory_store(tmp_path) as (root, project, _store, db_path):
        config = replace(resolve_memory_config(root), db_path=db_path)
        payload = execute_experience_distillation(
            root_path=root,
            config=config,
            project=project,
        )
        assert payload["status"] == "ok"
        assert payload["experiences_distilled"] == 0


def test_observability_span_error_and_sql_classification(tmp_path: Path) -> None:
    from codeclone.config.observability import ObservabilityConfig
    from codeclone.observability import (
        bootstrap,
        operation,
        record_elapsed_span,
        shutdown,
        span,
    )
    from codeclone.observability.runtime import _classify_sql
    from codeclone.observability.store.schema import (
        observability_store_path,
        open_observability_store,
    )

    assert _classify_sql("   ") == ""

    bootstrap(ObservabilityConfig(enabled=True), root=tmp_path)
    with operation(name="job", surface="cli"):
        record_elapsed_span(
            "cold-start",
            started_at_utc="2026-01-01T00:00:00Z",
            duration_ms=12.5,
        )
        with pytest.raises(RuntimeError, match="boom"), span(name="failing-stage"):
            raise RuntimeError("boom")
    shutdown()

    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        span_row = conn.execute(
            "SELECT status FROM platform_spans WHERE name=?",
            ("failing-stage",),
        ).fetchone()
        elapsed_row = conn.execute(
            "SELECT name FROM platform_spans WHERE name=?",
            ("cold-start",),
        ).fetchone()
    finally:
        conn.close()
    assert span_row is not None
    assert str(span_row[0]) == "error"
    assert elapsed_row is not None


def test_ingest_config_validator_passthrough_non_dict() -> None:
    from codeclone.config.memory import IngestConfig

    assert IngestConfig._normalize_path_lists.__func__(IngestConfig, 42) == 42


def test_build_init_batch_rejects_invalid_project_and_git(
    tmp_path: Path,
) -> None:
    from codeclone.memory.ingest import InitOptions

    with pytest.raises(TypeError, match="project must be MemoryProject"):
        build_init_batch(
            root_path=tmp_path,
            project=object(),
            report_document={},
            git=read_git_provenance(tmp_path),
            report_digest=None,
            analysis_fingerprint=None,
            options=InitOptions(),
        )
