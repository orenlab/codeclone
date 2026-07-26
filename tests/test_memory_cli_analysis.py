# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

import codeclone.surfaces.cli.memory_analysis as memory_analysis_mod
from codeclone.api.report import ReportArtifactFailure
from codeclone.contracts import DEFAULT_JSON_REPORT_PATH
from codeclone.memory.report_trust import CachedReportTrust
from codeclone.surfaces.cli.console import _rich_progress_symbols
from codeclone.surfaces.cli.memory_analysis import (
    load_report_for_memory_init,
    run_memory_analysis_report,
)
from tests._report_fixtures import build_test_report_document

from .memory_fixtures import git_repo_with_cached_report


def _memory_report(root: Path, relative_path: str) -> dict[str, object]:
    return build_test_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        meta={"scan_root": str(root)},
        inventory={
            "files": {
                "total_found": 1,
                "analyzed": 1,
                "cached": 0,
                "skipped": 0,
            },
            "file_list": [str(root / relative_path)],
        },
    )


def test_load_report_explicit_path(tmp_path: Path) -> None:
    root, _report_path, document = git_repo_with_cached_report(
        tmp_path,
        py_sources={"pkg/a.py": "x = 1\n"},
        registry_items=["pkg/a.py"],
    )
    document = _memory_report(root, "pkg/a.py")
    sidecar = root / "sidecar-report.json"
    sidecar.write_text(json.dumps(document), encoding="utf-8")
    loaded = load_report_for_memory_init(
        root_path=root,
        from_report=sidecar,
    )
    assert loaded.source == "explicit_report"
    assert isinstance(loaded.document, dict)
    assert loaded.document.get("inventory")


def test_load_report_trusted_cache(tmp_path: Path) -> None:
    root, _report_path, document = git_repo_with_cached_report(
        tmp_path,
        py_sources={"pkg/b.py": "y = 2\n"},
        registry_items=["pkg/b.py"],
    )
    document = _memory_report(root, "pkg/b.py")
    target = root / DEFAULT_JSON_REPORT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document), encoding="utf-8")
    with patch(
        "codeclone.surfaces.cli.memory_analysis.assess_cached_report_trust",
        return_value=CachedReportTrust(trusted=True, reason=None),
    ):
        loaded = load_report_for_memory_init(root_path=root, from_report=None)
    assert loaded.source == "trusted_cache"
    assert loaded.rejected_cache_reason is None
    assert isinstance(loaded.document, dict)


def test_load_report_rejected_cache_runs_fresh(tmp_path: Path) -> None:
    root, _report_path, document = git_repo_with_cached_report(
        tmp_path,
        py_sources={"pkg/c.py": "z = 3\n"},
        registry_items=["pkg/c.py"],
    )
    document = _memory_report(root, "pkg/c.py")
    target = root / DEFAULT_JSON_REPORT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document), encoding="utf-8")
    with (
        patch(
            "codeclone.surfaces.cli.memory_analysis.assess_cached_report_trust",
            return_value=CachedReportTrust(trusted=False, reason="digest_mismatch"),
        ),
        patch(
            "codeclone.surfaces.cli.memory_analysis.run_memory_analysis_report",
            return_value={"meta": {"runtime": {"scan_root_absolute": str(root)}}},
        ) as fresh,
    ):
        loaded = load_report_for_memory_init(root_path=root, from_report=None)
    assert loaded.source == "fresh_analysis"
    assert loaded.rejected_cache_reason == "digest_mismatch"
    fresh.assert_called_once()


def test_explicit_report_rejects_duplicate_key_before_shape(tmp_path: Path) -> None:
    report = tmp_path / "duplicate.json"
    report.write_text(
        '{"report_schema_version":"3.0","report_schema_version":"3.0"}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate_key"):
        load_report_for_memory_init(root_path=tmp_path, from_report=report)


def test_explicit_report_rejects_shape_before_compatibility(tmp_path: Path) -> None:
    report = tmp_path / "malformed.json"
    report.write_text('{"report_schema_version":"2.12"}', encoding="utf-8")
    with pytest.raises(ValueError, match="invalid_shape"):
        load_report_for_memory_init(root_path=tmp_path, from_report=report)


def test_explicit_report_rejects_unknown_reader_result(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    with (
        patch.object(
            memory_analysis_mod,
            "load_report_artifact",
            return_value=object(),
        ),
        pytest.raises(
            TypeError,
            match="stored report reader returned an unknown result",
        ),
    ):
        load_report_for_memory_init(root_path=tmp_path, from_report=report)


def test_default_report_reader_failure_runs_fresh_analysis(tmp_path: Path) -> None:
    report = tmp_path / DEFAULT_JSON_REPORT_PATH
    report.parent.mkdir(parents=True)
    report.write_text("{}", encoding="utf-8")
    fresh_document = {"meta": {"runtime": {"scan_root_absolute": str(tmp_path)}}}
    with (
        patch.object(
            memory_analysis_mod,
            "load_report_artifact",
            return_value=ReportArtifactFailure(
                reason="invalid_json",
                detail="broken",
            ),
        ),
        patch.object(
            memory_analysis_mod,
            "run_memory_analysis_report",
            return_value=fresh_document,
        ) as fresh,
    ):
        loaded = load_report_for_memory_init(
            root_path=tmp_path,
            from_report=None,
        )

    assert loaded.document is fresh_document
    assert loaded.source == "fresh_analysis"
    assert loaded.rejected_cache_reason == "report_reader:invalid_json"
    fresh.assert_called_once_with(root_path=tmp_path)


def test_default_report_rejects_unknown_reader_result(tmp_path: Path) -> None:
    report = tmp_path / DEFAULT_JSON_REPORT_PATH
    report.parent.mkdir(parents=True)
    report.write_text("{}", encoding="utf-8")
    with (
        patch.object(
            memory_analysis_mod,
            "load_report_artifact",
            return_value=object(),
        ),
        pytest.raises(
            TypeError,
            match="stored report reader returned an unknown result",
        ),
    ):
        load_report_for_memory_init(root_path=tmp_path, from_report=None)


def test_run_memory_analysis_report_on_small_repo(tmp_path: Path) -> None:
    root, _report_path, _document = git_repo_with_cached_report(
        tmp_path,
        py_sources={"pkg/mod.py": "def f():\n    return 1\n"},
        registry_items=["pkg/mod.py"],
    )
    document = run_memory_analysis_report(root_path=root)
    assert isinstance(document.get("meta"), dict)


def test_load_report_without_cached_file_runs_fresh(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    with patch(
        "codeclone.surfaces.cli.memory_analysis.run_memory_analysis_report",
        return_value={"meta": {"runtime": {"scan_root_absolute": str(root)}}},
    ) as fresh:
        loaded = load_report_for_memory_init(root_path=root, from_report=None)
    assert loaded.source == "fresh_analysis"
    assert loaded.rejected_cache_reason is None
    fresh.assert_called_once_with(root_path=root)


def test_memory_analysis_reuses_console_rich_progress_symbols() -> None:
    symbols = _rich_progress_symbols()
    assert len(symbols) == 5
    assert memory_analysis_mod._rich_progress_symbols is _rich_progress_symbols
    assert symbols == _rich_progress_symbols()


def test_run_memory_analysis_report_raises_when_document_missing(
    tmp_path: Path,
) -> None:
    root, _report_path, _document = git_repo_with_cached_report(
        tmp_path,
        py_sources={"pkg/mod.py": "def f():\n    return 1\n"},
        registry_items=["pkg/mod.py"],
    )
    with (
        patch(
            "codeclone.surfaces.cli.memory_analysis.report",
            return_value=type("Artifacts", (), {"report_document": None})(),
        ),
        pytest.raises(
            RuntimeError,
            match="did not produce a canonical report document",
        ),
    ):
        run_memory_analysis_report(root_path=root)
