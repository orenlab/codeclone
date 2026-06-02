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

from codeclone.memory.ingest.extractors import (
    extract_contradictions,
    extract_git_hotspots,
    extract_module_roles,
    extract_public_surfaces,
    extract_risk_notes,
    extract_test_anchors,
)
from codeclone.memory.models import MemoryProject
from codeclone.memory.project import GitProvenance

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
    project = _project(tmp_path)
    git = GitProvenance(remote=None, branch="main", head="deadbeef", available=True)
    report_document: dict[str, object] = {
        "metrics": {
            "api_surface": {
                "items": [
                    {"qualname": "x.y.Exported", "file": "pkg/mod.py"},
                    {"name": "  Zed  ", "path": "pkg/zed.py"},
                    {"qualname": "   ", "file": "pkg/skip.py"},  # empty symbol => skip
                ]
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


def test_extract_risk_notes_complexity_and_security_categories(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    git = GitProvenance(remote=None, branch="main", head="deadbeef", available=True)
    report_document: dict[str, object] = {
        "metrics": {
            "design": {
                "complexity_hotspots": [
                    # valid via path key
                    {"path": "pkg/a.py", "value": 11, "threshold": 5},
                    # empty path => skip
                    {"path": "   ", "value": 1, "threshold": 1},
                    # both path/file absent => skip
                    {"value": 2, "threshold": 2},
                ]
            },
            "security_surfaces": {
                "items": [
                    {"path": "pkg/secure.py", "category": "  Critical  "},
                    {"path": "   "},  # empty => skip
                ]
            },
        }
    }
    batch = extract_risk_notes(
        project=project,
        report_document=report_document,
        git=git,
        report_digest="r1",
        analysis_fingerprint="f1",
    )

    risk_kind: list[str | None] = []
    for r in batch.records:
        assert r.payload is not None
        raw = r.payload.get("risk_kind")
        risk_kind.append(str(raw) if raw is not None else None)
    assert risk_kind.count("high_complexity") == 1
    assert risk_kind.count("security_surface") == 1

    security = next(
        r
        for r in batch.records
        if r.payload is not None and r.payload.get("risk_kind") == "security_surface"
    )
    assert security.payload is not None
    assert security.payload.get("category") == "Critical"


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

    # tools must be a dict
    _write_json(
        tmp_path
        / "tests"
        / "fixtures"
        / "contract_snapshots"
        / "mcp_tool_schemas.json",
        {"tools": ["not-a-dict"]},
    )
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "mcp.md").write_text(
        "1 MCP tools\n2 MCP tools\n", encoding="utf-8"
    )
    batch = extract_contradictions(
        project=project,
        root_path=tmp_path,
        git=git,
        report_digest="r1",
        analysis_fingerprint="f1",
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
    )
    assert len(batch.records) == 1
    record = batch.records[0]
    assert record.type == "contradiction_note"
    assert record.status == "draft"
