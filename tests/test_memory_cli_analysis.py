# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from codeclone.contracts import DEFAULT_JSON_REPORT_PATH
from codeclone.memory.report_trust import CachedReportTrust
from codeclone.surfaces.cli.memory_analysis import (
    load_report_for_memory_init,
    run_memory_analysis_report,
)

from .memory_fixtures import git_repo_with_cached_report


def test_load_report_explicit_path(tmp_path: Path) -> None:
    root, _report_path, document = git_repo_with_cached_report(
        tmp_path,
        py_sources={"pkg/a.py": "x = 1\n"},
        registry_items=["pkg/a.py"],
    )
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
    target = root / DEFAULT_JSON_REPORT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document), encoding="utf-8")
    loaded = load_report_for_memory_init(root_path=root, from_report=None)
    assert loaded.source in {"trusted_cache", "fresh_analysis"}


def test_load_report_rejected_cache_runs_fresh(tmp_path: Path) -> None:
    root, _report_path, document = git_repo_with_cached_report(
        tmp_path,
        py_sources={"pkg/c.py": "z = 3\n"},
        registry_items=["pkg/c.py"],
    )
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
            return_value={"meta": {"scan_root": str(root)}},
        ) as fresh,
    ):
        loaded = load_report_for_memory_init(root_path=root, from_report=None)
    assert loaded.source == "fresh_analysis"
    assert loaded.rejected_cache_reason == "digest_mismatch"
    fresh.assert_called_once()


def test_run_memory_analysis_report_on_small_repo(tmp_path: Path) -> None:
    root, _report_path, _document = git_repo_with_cached_report(
        tmp_path,
        py_sources={"pkg/mod.py": "def f():\n    return 1\n"},
        registry_items=["pkg/mod.py"],
    )
    document = run_memory_analysis_report(root_path=root)
    assert isinstance(document.get("meta"), dict)
