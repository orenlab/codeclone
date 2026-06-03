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
    MemoryRecord,
    MemorySubject,
    RecordBatch,
    parse_payload_json,
)
from codeclone.memory.project import (
    analysis_fingerprint_from_report,
    read_git_provenance,
    resolve_project_identity,
)
from codeclone.memory.retrieval import get_relevant_memory
from codeclone.memory.retrieval import service as retrieval_service
from codeclone.memory.retrieval.ranking import RankingContext, relevance_score
from codeclone.memory.retrieval.semantic import audit_event_row
from codeclone.memory.search_index import build_search_text
from codeclone.memory.semantic.models import SemanticHit
from codeclone.memory.semantic.sources import AuditIndexSource, MemoryIndexSource
from codeclone.memory.staleness import apply_refresh_staleness, apply_scope_staleness
from codeclone.report.meta import current_report_timestamp_utc
from tests.memory_fixtures import (
    git_repo_with_cached_report,
    make_module_record,
    memory_store,
)


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
    with memory_store(tmp_path) as (_root, project, store, _db_path):
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
        )
        loaded = store.find_record(existing.id)
        assert result.records_marked_stale >= 1
        assert loaded is not None
        assert loaded.stale_reason == "evidence_digest_mismatch"


def test_refresh_skips_human_origin_records(tmp_path: Path) -> None:
    report: dict[str, object] = {"inventory": {"file_registry": {"items": []}}}
    with memory_store(tmp_path) as (_root, project, store, _db_path):
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
    store = type(
        "_Store",
        (),
        {
            "query_records": lambda self, query: [record][
                query.offset : query.offset + 250
            ],
            "list_subjects_for_memory": lambda self, _mid: [
                MemorySubject(
                    id="s-test",
                    memory_id=record.id,
                    subject_kind="test",
                    subject_key="tests/test_mod.py",
                    relation="about",
                )
            ],
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
