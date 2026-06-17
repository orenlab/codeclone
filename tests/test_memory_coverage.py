# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.memory.coverage import compute_scope_coverage, coverage_delta
from codeclone.memory.exceptions import MemoryContractError

from .memory_fixtures import (
    memory_store,
    seed_module_role,
    seed_path_linked_module_role,
)


def test_scope_coverage_counts_paths_with_memory(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        seed_path_linked_module_role(
            store,
            project_id=project.id,
            file_path="pkg/mod.py",
        )
        report = compute_scope_coverage(
            store,
            project_id=project.id,
            scope_paths=("pkg/mod.py", "pkg/other.py"),
        )
        assert report.scope_paths_total == 2
        assert report.scope_paths_with_memory == 1
        assert report.scope_coverage_percent == 50
        assert report.uncovered_paths == ("pkg/other.py",)
        delta = coverage_delta(report, report)
        assert delta["scope_coverage_before"] == 50
        assert delta["scope_coverage_after"] == 50


def test_scope_coverage_falls_back_to_module_subject(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        seed_module_role(
            store,
            project_id=project.id,
            file_path="pkg/mod.py",
        )
        report = compute_scope_coverage(
            store,
            project_id=project.id,
            scope_paths=("pkg/mod.py",),
        )
        assert report.scope_paths_with_memory == 1
        assert report.uncovered_paths == ()


def test_scope_coverage_rejects_empty_scope(tmp_path: Path) -> None:
    with (
        memory_store(tmp_path) as (_root, project, store, _db_path),
        pytest.raises(MemoryContractError, match="requires one or more"),
    ):
        compute_scope_coverage(
            store,
            project_id=project.id,
            scope_paths=(),
        )
