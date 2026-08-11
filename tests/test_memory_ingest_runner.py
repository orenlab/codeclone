# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from codeclone.config.memory import resolve_memory_config
from codeclone.contracts import REPORT_SCHEMA_VERSION
from codeclone.memory.ingest import InitOptions
from codeclone.memory.ingest.extractors import extract_document_links
from codeclone.memory.ingest.run_fitness import RUN_FITNESS_EVIDENCE_KIND
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
from codeclone.report.document.integrity import _build_integrity_payload

from ._report_fixtures import build_test_report_document
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
        registry_items=[
            "codeclone/contracts/__init__.py",
            "codeclone/memory/ingest/runner.py",
        ],
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


def _integrity_document(
    *,
    observation: str = "obs-1",
    source_facts: dict[str, object] | None = None,
    baseline: dict[str, object] | None = None,
    evaluation: dict[str, object] | None = None,
    generated_at: str = "2026-06-02T12:00:00Z",
) -> dict[str, object]:
    """Build one report through the report's own integrity owner.

    The fingerprint rule is pinned against the producer, never against a
    literal digest: a hard-coded value would only move the magic number into
    the test and would stay green if the tier changed underneath it.
    """

    resolved_source_facts = (
        source_facts
        if source_facts is not None
        else {"analysis_scope": [{"path": "pkg/a.py"}]}
    )
    resolved_baseline = baseline if baseline is not None else {"state": "absent"}
    resolved_evaluation = (
        evaluation if evaluation is not None else {"outcome": {"exit_code": 0}}
    )
    return {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "meta": {"runtime": {"report_generated_at_utc": generated_at}},
        "source_facts": resolved_source_facts,
        "baseline": resolved_baseline,
        "evaluation": resolved_evaluation,
        "integrity": _build_integrity_payload(
            report_schema_version=REPORT_SCHEMA_VERSION,
            observation_digest=observation,
            source_facts=resolved_source_facts,
            baseline=resolved_baseline,
            evaluation=resolved_evaluation,
        ),
    }


def test_analysis_fingerprint_reads_the_analysis_facts_tier() -> None:
    document = _integrity_document()
    digests = document["integrity"]["digests"]  # type: ignore[index]

    assert (
        analysis_fingerprint_from_report(document) == digests["analysis_facts"]["value"]
    )


def test_analysis_fingerprint_is_stable_across_runs_over_one_tree() -> None:
    first = _integrity_document(generated_at="2026-06-02T12:00:00Z")
    second = _integrity_document(generated_at="2031-12-31T23:59:59Z")

    assert analysis_fingerprint_from_report(first) == analysis_fingerprint_from_report(
        second
    )


def test_analysis_fingerprint_changes_with_the_observed_source() -> None:
    before = _integrity_document(observation="obs-1")
    after = _integrity_document(observation="obs-2")

    assert analysis_fingerprint_from_report(before) != analysis_fingerprint_from_report(
        after
    )


def test_analysis_fingerprint_changes_with_the_analysed_scope() -> None:
    before = _integrity_document(source_facts={"analysis_scope": [{"path": "a.py"}]})
    after = _integrity_document(
        source_facts={"analysis_scope": [{"path": "a.py"}, {"path": "b.py"}]}
    )

    assert analysis_fingerprint_from_report(before) != analysis_fingerprint_from_report(
        after
    )


def test_analysis_fingerprint_ignores_baseline_and_gate_policy() -> None:
    before = _integrity_document(
        baseline={"state": "absent"},
        evaluation={"outcome": {"exit_code": 0}},
    )
    after = _integrity_document(
        baseline={"state": "trusted", "root_digest_or_null": "b" * 64},
        evaluation={"outcome": {"exit_code": 1, "reasons": ["health"]}},
    )

    assert analysis_fingerprint_from_report(before) == analysis_fingerprint_from_report(
        after
    )


def test_analysis_fingerprint_is_unknown_without_an_analysis_facts_digest() -> None:
    # A clock is not an identity of code, and the pre-v3 singular key is gone.
    assert (
        analysis_fingerprint_from_report(
            {"meta": {"report_generated_at_utc": "2026-06-02T12:00:00Z"}}
        )
        == "unknown"
    )
    assert (
        analysis_fingerprint_from_report(
            {"meta": {"runtime": {"report_generated_at_utc": "2026-06-02T12:00:00Z"}}}
        )
        == "unknown"
    )
    assert (
        analysis_fingerprint_from_report({"integrity": {"digest": {"value": "a" * 64}}})
        == "unknown"
    )


def test_analysis_fingerprint_is_reachable_from_a_produced_report() -> None:
    document = build_test_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
    )
    fingerprint = analysis_fingerprint_from_report(document)

    assert fingerprint != "unknown"
    assert (
        fingerprint
        == (
            document["integrity"]["digests"]["analysis_facts"]["value"]  # type: ignore[index]
        )
    )


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


def test_run_memory_init_dry_run_yields_null_db_path(tmp_path: Path) -> None:
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
    assert result.db_path is None
    assert result.planned_counts


def test_run_memory_init_refresh_records_vacuum_deletions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import dataclass

    root, _report_path, report_document = git_repo_with_cached_report(
        tmp_path,
        py_sources={"pkg/c.py": "z = 3\n"},
        registry_items=["pkg/c.py"],
    )
    run_memory_init(
        root_path=root,
        report_document=report_document,
        options=InitOptions(include_docs=False, include_tests=False),
    )

    @dataclass(frozen=True, slots=True)
    class _VacuumReport:
        total_deleted: int = 4

    monkeypatch.setattr(
        "codeclone.memory.ingest.runner.run_memory_vacuum",
        lambda *_args, **_kwargs: _VacuumReport(),
    )
    monkeypatch.setattr(
        "codeclone.memory.ingest.runner.apply_refresh_staleness",
        lambda *_args, **_kwargs: SimpleNamespace(records_marked_stale=2),
    )
    result = run_memory_init(
        root_path=root,
        report_document=report_document,
        options=InitOptions(refresh=True, include_docs=False, include_tests=False),
    )
    assert result.ingestion_mode == "refresh"
    assert result.records_marked_stale == 2
    assert result.vacuum_deleted == 4


def _doc_link_repo(
    tmp_path: Path,
    docs: dict[str, str],
) -> tuple[Path, dict[str, object]]:
    """A git repo whose docs reference one real module, plus its report."""

    root, _report_path, report_document = git_repo_with_cached_report(
        tmp_path,
        py_sources={"pkg/mod.py": "def f():\n    return 1\n"},
        registry_items=["pkg/mod.py"],
    )
    for rel, body in docs.items():
        doc_path = root / rel
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(body, encoding="utf-8")
    return root, report_document


def _document_link_batch(
    root: Path,
    report_document: dict[str, object],
) -> RecordBatch:
    project = resolve_project_identity(root)
    git = read_git_provenance(root)
    return extract_document_links(
        project=project,
        root_path=root,
        git=git,
        report_digest=None,
        analysis_fingerprint=None,
        registry_paths=frozenset({"pkg/mod.py"}),
    )


def test_document_links_emit_one_record_per_document_and_path(tmp_path: Path) -> None:
    """Repeated mentions of one path in one document are one link.

    The identity of a document link is the pair (document, anchored path), and
    the store enforces that with a UNIQUE constraint. The producer emitted a
    record for every occurrence and left the store to absorb the rest, so a
    document that mentions a module under several headings paid a revision per
    extra mention -- a rewrite of the same record with a different heading.
    """

    root, report_document = _doc_link_repo(
        tmp_path,
        {
            "README.md": (
                "# Overview\n"
                "See `pkg/mod.py` for the entry point.\n"
                "`pkg/mod.py` is also mentioned here.\n"
                "## Details\n"
                "And once more in `pkg/mod.py`.\n"
            )
        },
    )
    batch = _document_link_batch(root, report_document)

    payloads = [dict(record.payload or {}) for record in batch.records]

    assert [payload["anchored_symbols"] for payload in payloads] == [["pkg/mod.py"]]
    assert payloads[0]["heading"] == "Overview"
    assert len({record.identity_key for record in batch.records}) == len(batch.records)


def test_document_links_keep_distinct_pairs_apart(tmp_path: Path) -> None:
    """Collapsing must not merge links that are legitimately different.

    Two documents naming the same module are two links, and one document naming
    two modules is two links; only the (document, path) pair is the identity.
    """

    root, report_document = _doc_link_repo(
        tmp_path,
        {
            "README.md": "# R\n`pkg/mod.py` and `README.md` here.\n",
            "AGENTS.md": "# A\n`pkg/mod.py` again.\n",
        },
    )
    batch = _document_link_batch(root, report_document)

    pairs = sorted(
        (
            str(payload["doc_file"]),
            str(next(iter(cast("list[object]", payload["anchored_symbols"])))),
        )
        for payload in (dict(record.payload or {}) for record in batch.records)
    )
    assert pairs == [
        ("AGENTS.md", "pkg/mod.py"),
        ("README.md", "README.md"),
        ("README.md", "pkg/mod.py"),
    ]
    assert len({record.identity_key for record in batch.records}) == 3


def test_document_link_ingest_writes_no_revisions_for_repeated_mentions(
    tmp_path: Path,
) -> None:
    """One ingest of one unchanged tree must not revise its own records.

    Each surplus record collided on identity_key with a different statement, so
    the store rewrote the surviving record and wrote a revision -- an edit
    history manufactured by a single pass over a file nobody changed.
    """

    root, report_document = _doc_link_repo(
        tmp_path,
        {
            "README.md": (
                "# Overview\n"
                "`pkg/mod.py` here.\n"
                "## Details\n"
                "`pkg/mod.py` there.\n"
                "## More\n"
                "`pkg/mod.py` everywhere.\n"
            )
        },
    )
    run_memory_init(
        root_path=root,
        report_document=report_document,
        options=InitOptions(include_docs=True, include_tests=False),
    )
    config = resolve_memory_config(root)
    store = SqliteEngineeringMemoryStore(resolve_memory_db_path(root, config))
    try:
        revisions = store._conn.execute(
            "SELECT COUNT(*) FROM memory_revisions"
        ).fetchone()[0]
        links = store._conn.execute(
            "SELECT COUNT(*) FROM memory_records WHERE type='document_link'"
        ).fetchone()[0]
        evidence = store._conn.execute(
            "SELECT COUNT(*) FROM memory_evidence e "
            "JOIN memory_records r ON r.id = e.memory_id "
            "WHERE r.type='document_link' AND e.evidence_kind='git_commit'"
        ).fetchone()[0]
    finally:
        store.close()

    assert int(revisions) == 0
    assert int(links) == 1
    assert int(evidence) == 1


def test_document_link_records_bind_to_the_commit_they_were_read_at(
    tmp_path: Path,
) -> None:
    """A document link states when in the tree's history it was true.

    Two lanes carry that: the commit/branch columns on the record, and a
    ``git_commit`` evidence row that ``enrich_batch_git_evidence`` attaches to
    every record in the merged batch. Both must reach ``document_link`` -- a
    link between a document and a module that does not say which tree state it
    held for is an assertion nobody can re-check. The commit column is also a
    precondition of drift evaluation, so losing it silently disables staleness
    for these records rather than failing.
    """

    root, report_document = _doc_link_repo(
        tmp_path,
        {"README.md": "# Overview\nSee `pkg/mod.py`.\n"},
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    run_memory_init(
        root_path=root,
        report_document=report_document,
        options=InitOptions(include_docs=True, include_tests=False),
    )
    config = resolve_memory_config(root)
    store = SqliteEngineeringMemoryStore(resolve_memory_db_path(root, config))
    try:
        record_rows = store._conn.execute(
            "SELECT id, created_at_commit, verified_at_commit, created_on_branch "
            "FROM memory_records WHERE type='document_link'"
        ).fetchall()
        evidence_rows = store._conn.execute(
            "SELECT e.evidence_kind, e.ref, e.locator FROM memory_evidence e "
            "JOIN memory_records r ON r.id = e.memory_id "
            "WHERE r.type='document_link'"
        ).fetchall()
    finally:
        store.close()

    assert [tuple(row)[1:] for row in record_rows] == [(head, head, "main")]
    by_lane = {str(row[0]): tuple(row)[1:] for row in evidence_rows}
    assert by_lane["git_commit"] == (head, "main")
    # Exhaustive on purpose, and now two lanes: git provenance answers *when*
    # the link held, the run-fitness mark answers whether the run that read it
    # was fit to be believed. A third lane appearing here is a contract change.
    assert set(by_lane) == {"git_commit", RUN_FITNESS_EVIDENCE_KIND}
