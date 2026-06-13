# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.config.memory import resolve_memory_config
from codeclone.memory.ingest import InitOptions
from codeclone.memory.ingest.runner import (
    _registry_paths,
    build_init_batch,
    enrich_batch_git_evidence,
    planned_type_counts,
    run_memory_init,
)
from codeclone.memory.models import RecordBatch
from codeclone.memory.project import (
    GitProvenance,
    analysis_fingerprint_from_report,
    read_git_provenance,
    report_digest_from_report,
    resolve_memory_db_path,
    resolve_project_identity,
)
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore
from codeclone.memory.vacuum import run_memory_vacuum

from .memory_fixtures import (
    REPO_ROOT,
    git_repo_with_cached_report,
    load_memory_init_report_document,
    make_module_record,
)


def test_build_init_batch_git_repo_with_docs_and_tests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _report_path, base_doc = git_repo_with_cached_report(
        tmp_path,
        py_sources={
            "pkg/mod.py": "def f():\n    return 1\n",
            "tests/test_mod.py": "def test_f():\n    assert f() == 1\n",
        },
        registry_items=["pkg/mod.py", "tests/test_mod.py"],
    )
    docs_dir = root / "docs"
    docs_dir.mkdir()
    (docs_dir / "guide.md").write_text(
        "See `pkg/mod.py` for the implementation.\n",
        encoding="utf-8",
    )
    report_document = load_memory_init_report_document(
        registry_items=["pkg/mod.py", "tests/test_mod.py"],
        fallback_root=root,
    )
    if "integrity" not in report_document:
        report_document = {**base_doc, **report_document}
    project = resolve_project_identity(root)
    git = read_git_provenance(root)
    batch = build_init_batch(
        root_path=root,
        project=project,
        report_document=report_document,
        git=git,
        report_digest=report_digest_from_report(report_document),
        analysis_fingerprint=analysis_fingerprint_from_report(report_document),
        options=InitOptions(include_docs=True, include_tests=True),
        git_hotspot_min_changes=1,
    )
    enrich_batch_git_evidence(batch, git)
    counts = planned_type_counts(batch)
    assert counts.get("module_role", 0) >= 1

    isolated_rel = ".codeclone/memory/ci-ingest-isolated.sqlite3"
    monkeypatch.setenv("CODECLONE_MEMORY_DB_PATH", isolated_rel)
    isolated_db = root / isolated_rel
    isolated_db.parent.mkdir(parents=True, exist_ok=True)
    if isolated_db.is_file():
        isolated_db.unlink()
    init_result = run_memory_init(
        root_path=root,
        report_document=report_document,
        options=InitOptions(include_docs=True, include_tests=True, refresh=True),
    )
    assert init_result.dry_run is False
    assert isolated_db.is_file()
    assert sum(init_result.stats.values()) > 0


def test_run_memory_init_dry_run_on_git_repo(tmp_path: Path) -> None:
    root, _report_path, report_document = git_repo_with_cached_report(
        tmp_path,
        py_sources={"pkg/a.py": "x = 1\n"},
        registry_items=["pkg/a.py"],
    )
    result = run_memory_init(
        root_path=root,
        report_document=report_document,
        options=InitOptions(dry_run=True, include_docs=False, include_tests=False),
    )
    assert result.dry_run is True
    assert result.project_id
    assert result.planned_counts


def test_run_memory_init_persists_and_vacuum(tmp_path: Path) -> None:
    root, _report_path, report_document = git_repo_with_cached_report(
        tmp_path,
        py_sources={"pkg/b.py": "y = 2\n"},
        registry_items=["pkg/b.py"],
    )
    result = run_memory_init(
        root_path=root,
        report_document=report_document,
        options=InitOptions(include_docs=False, include_tests=False),
    )
    assert result.dry_run is False
    assert result.stats.get("created", 0) + result.stats.get("updated", 0) >= 1
    config = resolve_memory_config(root)
    db_path = resolve_memory_db_path(root, config)
    store = SqliteEngineeringMemoryStore(db_path)
    try:
        vacuum_report = run_memory_vacuum(store, config)
    finally:
        store.close()
    assert vacuum_report.total_deleted >= 0


def test_build_init_batch_on_fixture_git_repo(tmp_path: Path) -> None:
    root, _report_path, report_document = git_repo_with_cached_report(
        tmp_path,
        py_sources={"pkg/mod.py": "def f():\n    return 1\n"},
        registry_items=["pkg/mod.py"],
    )
    project = resolve_project_identity(root)
    git = read_git_provenance(root)
    batch = build_init_batch(
        root_path=root,
        project=project,
        report_document=report_document,
        git=git,
        report_digest=report_digest_from_report(report_document),
        analysis_fingerprint=analysis_fingerprint_from_report(report_document),
        options=InitOptions(include_docs=False, include_tests=False),
    )
    counts = planned_type_counts(batch)
    assert counts.get("module_role", 0) >= 1


def test_build_init_batch_on_codeclone_repository() -> None:
    if not (REPO_ROOT / "codeclone" / "contracts" / "__init__.py").is_file():
        pytest.skip("not running inside codeclone checkout")
    project = resolve_project_identity(REPO_ROOT)
    git = read_git_provenance(REPO_ROOT)
    report_document = load_memory_init_report_document(
        registry_items=["codeclone/memory/ingest/runner.py"],
        fallback_root=REPO_ROOT,
    )
    batch = build_init_batch(
        root_path=REPO_ROOT,
        project=project,
        report_document=report_document,
        git=git,
        report_digest=report_digest_from_report(report_document),
        analysis_fingerprint=analysis_fingerprint_from_report(report_document),
        options=InitOptions(include_docs=True, include_tests=True),
    )
    counts = planned_type_counts(batch)
    assert counts.get("contract_note", 0) >= 1


def test_build_init_batch_rejects_invalid_project_and_git_types(
    tmp_path: Path,
) -> None:
    root, _report_path, report_document = git_repo_with_cached_report(
        tmp_path,
        py_sources={"pkg/a.py": "x = 1\n"},
        registry_items=["pkg/a.py"],
    )
    git = read_git_provenance(root)
    with pytest.raises(TypeError, match="MemoryProject"):
        build_init_batch(
            root_path=root,
            project=object(),
            report_document=report_document,
            git=git,
            report_digest=None,
            analysis_fingerprint=None,
            options=InitOptions(),
        )
    project = resolve_project_identity(root)
    with pytest.raises(TypeError, match="GitProvenance"):
        build_init_batch(
            root_path=root,
            project=project,
            report_document=report_document,
            git=object(),
            report_digest=None,
            analysis_fingerprint=None,
            options=InitOptions(),
        )


def test_build_init_batch_tolerates_sparse_report_inventory(tmp_path: Path) -> None:
    root, _report_path, _report_document = git_repo_with_cached_report(
        tmp_path,
        py_sources={"pkg/a.py": "x = 1\n"},
        registry_items=["pkg/a.py"],
    )
    project = resolve_project_identity(root)
    git = read_git_provenance(root)
    batch = build_init_batch(
        root_path=root,
        project=project,
        report_document={},
        git=git,
        report_digest=None,
        analysis_fingerprint=None,
        options=InitOptions(include_docs=False, include_tests=False),
    )
    assert batch.records == []


def test_enrich_batch_git_evidence_noop_when_git_unavailable() -> None:
    batch = RecordBatch()
    git = GitProvenance(remote=None, branch=None, head=None, available=False)
    enrich_batch_git_evidence(batch, git)
    assert batch.evidence == []


def test_enrich_batch_git_evidence_appends_head_for_records() -> None:
    record = make_module_record("proj-1", "pkg/mod.py")
    batch = RecordBatch(records=[record], evidence=[])
    git = GitProvenance(
        remote="origin",
        branch="main",
        head="abc123def456",
        available=True,
    )
    enrich_batch_git_evidence(batch, git)
    assert len(batch.evidence) == 1
    assert batch.evidence[0].memory_id == record.id
    assert batch.evidence[0].evidence_kind == "git_commit"


def test_enrich_batch_git_evidence_skips_when_head_missing() -> None:
    record = make_module_record("proj-1", "pkg/mod.py")
    batch = RecordBatch(records=[record], evidence=[])
    git = GitProvenance(
        remote="origin",
        branch="main",
        head=None,
        available=True,
    )
    enrich_batch_git_evidence(batch, git)
    assert batch.evidence == []


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


def test_registry_paths_rejects_non_mapping_inventory() -> None:
    from codeclone.memory.ingest.runner import _registry_paths

    assert _registry_paths({}) == frozenset()
    assert _registry_paths({"inventory": "bad"}) == frozenset()
    assert _registry_paths({"inventory": {"file_registry": "bad"}}) == frozenset()


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
