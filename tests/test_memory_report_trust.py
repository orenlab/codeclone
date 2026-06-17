# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

from codeclone.memory.report_trust import assess_cached_report_trust

from .memory_fixtures import git_repo_with_cached_report


def test_cached_report_rejected_when_missing_tracked_files(tmp_path: Path) -> None:
    root, report_path, report_document = git_repo_with_cached_report(
        tmp_path,
        py_sources={
            "pkg/mod.py": "x = 1\n",
            "pkg/new.py": "y = 2\n",
        },
        registry_items=["pkg/mod.py"],
    )

    trust = assess_cached_report_trust(
        root_path=root,
        report_path=report_path,
        report_document=report_document,
    )
    assert trust.trusted is False
    assert trust.reason is not None
    assert "missing" in trust.reason
    assert "pkg/new.py" in trust.reason


def test_cached_report_trusted_when_registry_covers_tracked_py(tmp_path: Path) -> None:
    root, report_path, report_document = git_repo_with_cached_report(
        tmp_path,
        py_sources={"pkg/mod.py": "x = 1\n"},
        registry_items=["pkg/mod.py"],
    )

    trust = assess_cached_report_trust(
        root_path=root,
        report_path=report_path,
        report_document=report_document,
    )
    assert trust.trusted is True
    assert trust.reason is None
