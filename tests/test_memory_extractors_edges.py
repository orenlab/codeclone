# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess
from typing import Any

import pytest

from codeclone.config.memory import IngestConfig
from codeclone.memory.ingest.extractors import (
    extract_contradictions,
    extract_git_hotspots,
    extract_module_roles,
    extract_public_surfaces,
    extract_risk_notes,
    extract_test_anchors,
)
from codeclone.memory.models import MemoryProject, MemoryRecord
from codeclone.memory.project import (
    GitProvenance,
    read_git_provenance,
    resolve_project_identity,
)

_NOW = "2026-01-01T00:00:00Z"


def _project(root: Path) -> MemoryProject:
    return MemoryProject(
        id="proj-test",
        root=str(root),
        git_remote=None,
        git_branch=None,
        git_head=None,
        python_tag="cp314",
        created_at_utc=_NOW,
        updated_at_utc=_NOW,
    )


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    import json

    path.write_text(json.dumps(payload), encoding="utf-8")


def test_extract_module_roles_dedup_and_skips_non_py(tmp_path: Path) -> None:
    project = _project(tmp_path)
    git = GitProvenance(remote=None, branch="main", head="deadbeef", available=True)
    report_document: dict[str, object] = {
        "inventory": {
            "file_registry": {
                "items": [
                    "pkg/a.py",
                    "pkg/a.py",  # dedup via seen
                    "README.md",  # skip non-.py
                    "pkg/__init__.py",  # __init__ -> module pkg
                ]
            }
        }
    }
    batch = extract_module_roles(
        project=project,
        root_path=tmp_path,
        report_document=report_document,
        git=git,
        report_digest="r1",
        analysis_fingerprint="f1",
    )

    assert [r.type for r in batch.records] == ["module_role", "module_role"]
    module_paths: set[str] = set()
    for record in batch.records:
        assert record.payload is not None
        module_paths.add(str(record.payload.get("module_path")))
    assert module_paths == {"pkg.a", "pkg"}


def test_extract_public_surfaces_skips_empty_symbol_and_reads_mcp_snapshot(
    tmp_path: Path,
) -> None:
    """Edge behaviour, on the shape the report builder actually emits.

    This fixture used to nest ``api_surface`` directly under ``metrics`` and
    locate rows with ``file``/``path``/``name``. The canonical ``metrics`` node
    carries only ``families`` and ``summary``, and the api-surface projection
    emits ``qualname`` and ``relative_path``, so the old fixture described a
    document no run has produced -- it was written to match the extractor
    rather than the contract, and it kept the lane's emptiness invisible.
    ``_risk_note_report_document`` below already stated the correct shape for
    its own lane; this one is now consistent with it.
    """

    project = _project(tmp_path)
    git = GitProvenance(remote=None, branch="main", head="deadbeef", available=True)
    report_document: dict[str, object] = {
        "metrics": {
            "families": {
                "api_surface": {
                    "items": [
                        {
                            "qualname": "x.y.Exported",
                            "relative_path": "pkg/mod.py",
                        },
                        {"qualname": "  Zed  ", "relative_path": "pkg/zed.py"},
                        # empty symbol => skip
                        {"qualname": "   ", "relative_path": "pkg/skip.py"},
                    ]
                }
            }
        }
    }

    _write_json(
        tmp_path
        / "tests"
        / "fixtures"
        / "contract_snapshots"
        / "mcp_tool_schemas.json",
        {"tools": {"toolB": {}, "toolA": {}}},
    )

    batch = extract_public_surfaces(
        project=project,
        root_path=tmp_path,
        report_document=report_document,
        git=git,
        report_digest="r1",
        analysis_fingerprint="f1",
        ingest=IngestConfig(
            mcp_tool_schema_snapshot_path=(
                "tests/fixtures/contract_snapshots/mcp_tool_schemas.json"
            ),
        ),
    )

    api_surface_names: set[str] = set()
    tool_surface_names: list[str] = []
    for record in batch.records:
        assert record.payload is not None
        kind = record.payload.get("surface_kind")
        name = str(record.payload.get("surface_name"))
        if kind == "api_symbol":
            api_surface_names.add(name)
        elif kind == "mcp_tool":
            tool_surface_names.append(name)
    assert api_surface_names == {"x.y.Exported", "Zed"}
    assert tool_surface_names == ["toolA", "toolB"]


def _risk_note_report_document() -> dict[str, object]:
    """One report in the shape the report builder actually emits.

    Metric families live under ``metrics.families`` and locate themselves with
    ``relative_path``; there is no ``metrics.design`` family and no flat
    ``metrics.security_surfaces`` key.
    """

    return {
        "source_facts": {
            "analysis_contract": {
                "design_findings": {
                    # Deliberately not the shipped default: a threshold that
                    # matched the default would keep a hard-coded reader green.
                    "complexity": {
                        "metric": "cyclomatic_complexity",
                        "operator": ">",
                        "value": 7,
                    }
                }
            }
        },
        "metrics": {
            "families": {
                "complexity": {
                    "items": [
                        {
                            "qualname": "pkg.a:wide",
                            "relative_path": "pkg/a.py",
                            "cyclomatic_complexity": 34,
                            "risk": "high",
                        },
                        {
                            "qualname": "pkg.a:wider",
                            "relative_path": "pkg/a.py",
                            "cyclomatic_complexity": 57,
                            "risk": "high",
                        },
                        # Above the printed threshold, yet the producer did not
                        # flag it: the classification is the report's, not ours.
                        {
                            "qualname": "pkg.b:calm",
                            "relative_path": "pkg/b.py",
                            "cyclomatic_complexity": 12,
                            "risk": "medium",
                        },
                        {
                            "qualname": "pkg.c:nameless",
                            "cyclomatic_complexity": 99,
                            "risk": "high",
                        },
                    ]
                },
                "security_surfaces": {
                    "items": [
                        {
                            "relative_path": "pkg/secure.py",
                            "category": "  process_boundary  ",
                            "source_kind": "production",
                        },
                        {
                            "relative_path": "pkg/secure.py",
                            "category": "database_boundary",
                            "source_kind": "production",
                        },
                        {
                            "relative_path": "tests/test_secure.py",
                            "category": "process_boundary",
                            "source_kind": "tests",
                        },
                        {
                            "relative_path": "   ",
                            "category": "network_boundary",
                            "source_kind": "production",
                        },
                    ]
                },
            }
        },
    }


def test_extract_risk_notes_reads_the_real_metric_families(tmp_path: Path) -> None:
    project = _project(tmp_path)
    git = GitProvenance(remote=None, branch="main", head="deadbeef", available=True)

    batch = extract_risk_notes(
        project=project,
        report_document=_risk_note_report_document(),
        git=git,
        report_digest="r1",
        analysis_fingerprint="f1",
        root_path=tmp_path,
    )

    by_kind: dict[str, list[MemoryRecord]] = {}
    for record in batch.records:
        assert record.payload is not None
        by_kind.setdefault(str(record.payload.get("risk_kind")), []).append(record)

    # One record per file: the worst offender the producer flagged, not one
    # record per function, and never a second row under the same identity.
    assert len(by_kind["high_complexity"]) == 1
    complexity = by_kind["high_complexity"][0]
    assert complexity.payload is not None
    assert complexity.payload.get("metric_value") == 57
    assert complexity.payload.get("threshold") == 7
    assert "pkg/a.py" in complexity.statement

    assert len(by_kind["security_surface"]) == 1
    security = by_kind["security_surface"][0]
    assert security.payload is not None
    assert security.payload.get("categories") == [
        "database_boundary",
        "process_boundary",
    ]

    identities = [record.identity_key for record in batch.records]
    assert len(identities) == len(set(identities))


def test_extract_risk_notes_ignores_surfaces_the_producer_did_not_flag(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    git = GitProvenance(remote=None, branch="main", head="deadbeef", available=True)

    batch = extract_risk_notes(
        project=project,
        report_document=_risk_note_report_document(),
        git=git,
        report_digest="r1",
        analysis_fingerprint="f1",
        root_path=tmp_path,
    )
    statements = {
        str(record.payload.get("risk_kind")): record.statement
        for record in batch.records
        if record.payload is not None
    }

    # medium-risk complexity, test-owned security surfaces and pathless rows
    # are inventory, not risk: ingesting them would assert a fact the report
    # never made.
    assert "pkg/b.py" not in statements["high_complexity"]
    assert "pkg/c" not in statements["high_complexity"]
    assert "tests/test_secure.py" not in statements["security_surface"]


def test_extract_risk_notes_ingests_nothing_from_absent_families(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    git = GitProvenance(remote=None, branch="main", head="deadbeef", available=True)
    # The pre-v3 imagined shape: a "design" family and flat family keys. None
    # of it exists in a produced report, so none of it may become memory.
    legacy_document: dict[str, object] = {
        "metrics": {
            "design": {
                "complexity_hotspots": [
                    {"path": "pkg/a.py", "value": 11, "threshold": 5}
                ]
            },
            "security_surfaces": {
                "items": [{"path": "pkg/secure.py", "category": "Critical"}]
            },
        }
    }

    batch = extract_risk_notes(
        project=project,
        report_document=legacy_document,
        git=git,
        report_digest="r1",
        analysis_fingerprint="f1",
        root_path=tmp_path,
    )

    assert batch.records == []


def test_extract_test_anchors_skips_unparseable_tests_file(tmp_path: Path) -> None:
    project = _project(tmp_path)
    git = GitProvenance(remote=None, branch="main", head="deadbeef", available=True)
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "test_bad.py").write_text(
        "def f(:\n    pass\n", encoding="utf-8"
    )

    batch = extract_test_anchors(
        project=project,
        root_path=tmp_path,
        git=git,
        report_digest="r1",
        analysis_fingerprint="f1",
    )
    assert batch.records == []
    assert batch.subjects == []


def test_extract_git_hotspots_git_available_false_returns_empty(tmp_path: Path) -> None:
    project = _project(tmp_path)
    git = GitProvenance(remote=None, branch="main", head="deadbeef", available=False)
    batch = extract_git_hotspots(
        project=project,
        root_path=tmp_path,
        git=git,
        report_digest="r1",
        analysis_fingerprint="f1",
        period_days=90,
        min_changes=2,
    )
    assert batch.records == []
    assert batch.evidence == []


def test_extract_git_hotspots_subprocess_failure_returns_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    git = GitProvenance(remote=None, branch="main", head="deadbeef", available=True)

    def _boom(*_args: object, **_kwargs: object) -> CompletedProcess[str]:
        raise OSError("git log failed")

    monkeypatch.setattr(
        "codeclone.memory.ingest.extractors.subprocess.run",
        _boom,
    )

    batch = extract_git_hotspots(
        project=project,
        root_path=tmp_path,
        git=git,
        report_digest="r1",
        analysis_fingerprint="f1",
        period_days=90,
        min_changes=2,
    )
    assert batch.records == []
    assert batch.evidence == []


def test_extract_git_hotspots_adds_git_commit_evidence_when_git_head_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    git = GitProvenance(remote=None, branch="main", head="deadbeef", available=True)

    def _run(*_args: object, **_kwargs: object) -> CompletedProcess[str]:
        return CompletedProcess(
            args=["git"],
            returncode=0,
            stdout="pkg/a.py\npkg/a.py\nother/b.md\n",
            stderr="",
        )

    monkeypatch.setattr(
        "codeclone.memory.ingest.extractors.subprocess.run",
        _run,
    )

    batch = extract_git_hotspots(
        project=project,
        root_path=tmp_path,
        git=git,
        report_digest="r1",
        analysis_fingerprint="f1",
        period_days=90,
        min_changes=2,
    )
    assert len(batch.records) == 1
    assert len(batch.evidence) == 1
    assert batch.evidence[0].evidence_kind == "git_commit"
    assert batch.evidence[0].ref == "deadbeef"


def test_extract_contradictions_tools_must_be_dict_and_claim_mismatch(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    git = GitProvenance(remote=None, branch="main", head=None, available=True)
    ingest = IngestConfig(
        mcp_tool_schema_snapshot_path=(
            "tests/fixtures/contract_snapshots/mcp_tool_schemas.json"
        ),
        mcp_tool_count_doc_paths=("docs/book/25-mcp-interface/index.md",),
    )

    # tools must be a dict
    _write_json(
        tmp_path
        / "tests"
        / "fixtures"
        / "contract_snapshots"
        / "mcp_tool_schemas.json",
        {"tools": ["not-a-dict"]},
    )
    (tmp_path / "docs" / "book" / "25-mcp-interface").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "book" / "25-mcp-interface" / "index.md").write_text(
        "1 MCP tools\n2 MCP tools\n", encoding="utf-8"
    )
    batch = extract_contradictions(
        project=project,
        root_path=tmp_path,
        git=git,
        report_digest="r1",
        analysis_fingerprint="f1",
        ingest=ingest,
    )
    assert batch.records == []

    # tools dict; actual_count=2, mismatch for claimed=1 should create one draft note
    _write_json(
        tmp_path
        / "tests"
        / "fixtures"
        / "contract_snapshots"
        / "mcp_tool_schemas.json",
        {"tools": {"toolA": {}, "toolB": {}}},
    )
    batch = extract_contradictions(
        project=project,
        root_path=tmp_path,
        git=git,
        report_digest="r1",
        analysis_fingerprint="f1",
        ingest=ingest,
    )
    assert len(batch.records) == 1
    record = batch.records[0]
    assert record.type == "contradiction_note"
    assert record.status == "draft"


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


def test_extract_contract_notes_skips_valueless_and_dynamic_constants(
    tmp_path: Path,
) -> None:
    from codeclone.memory.ingest.extractors import extract_contract_notes

    project = _project(tmp_path)
    git = GitProvenance(remote=None, branch="main", head="deadbeef", available=True)
    contracts = tmp_path / "contracts.py"
    contracts.write_text(
        "SCHEMA_VERSION: str\n"
        "DYNAMIC_VERSION: str = compute()\n"
        'REAL_VERSION: str = "3"\n',
        encoding="utf-8",
    )

    batch = extract_contract_notes(
        project=project,
        root_path=tmp_path,
        git=git,
        report_digest="r1",
        analysis_fingerprint="f1",
        ingest=IngestConfig(contract_constants_paths=("contracts.py",)),
    )
    names = sorted(
        subject.subject_key
        for subject in batch.subjects
        if subject.subject_kind == "contract"
    )
    assert names == ["REAL_VERSION"]


def test_extract_public_surfaces_tolerates_corrupt_tool_snapshot(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    git = GitProvenance(remote=None, branch="main", head="deadbeef", available=True)
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text("{not json", encoding="utf-8")

    batch = extract_public_surfaces(
        project=project,
        root_path=tmp_path,
        report_document={},
        git=git,
        report_digest="r1",
        analysis_fingerprint="f1",
        ingest=IngestConfig(mcp_tool_schema_snapshot_path="snapshot.json"),
    )
    kinds = {
        record.payload.get("surface_kind")
        for record in batch.records
        if record.payload is not None
    }
    assert "mcp_tool" not in kinds


def test_extract_git_hotspots_without_head_adds_no_commit_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    git = GitProvenance(remote=None, branch="main", head=None, available=True)

    def _run(*_args: object, **_kwargs: object) -> CompletedProcess[str]:
        return CompletedProcess(
            args=["git"],
            returncode=0,
            stdout="pkg/a.py\n" * 12,
            stderr="",
        )

    monkeypatch.setattr(
        "codeclone.memory.ingest.extractors.subprocess.run",
        _run,
    )
    batch = extract_git_hotspots(
        project=project,
        root_path=tmp_path,
        git=git,
        report_digest="r1",
        analysis_fingerprint="f1",
    )
    assert batch.records
    assert batch.evidence == []


def test_memory_project_fingerprints_and_subject_kinds(tmp_path: Path) -> None:
    from codeclone.memory.models import MemorySubject
    from codeclone.memory.project import (
        analysis_fingerprint_from_report,
        subject_fingerprint_for_subject,
        subject_path_fingerprint,
    )

    assert (
        analysis_fingerprint_from_report(
            {"integrity": {"digests": {"analysis_facts": {"value": "a" * 64}}}}
        )
        == "a" * 64
    )

    # A path that cannot normalize under the repo yields no fingerprint.
    assert subject_path_fingerprint(tmp_path, "../outside.py") is None

    symbol_subject = MemorySubject(
        id="subj-1",
        memory_id="mem-1",
        subject_kind="symbol",
        subject_key="pkg.mod:fn",
        relation="about",
    )
    assert subject_fingerprint_for_subject(tmp_path, symbol_subject) is None
