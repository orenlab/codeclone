# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .paths import normalize_memory_scope_paths
from .retrieval.service import path_has_memory
from .sqlite_store import SqliteEngineeringMemoryStore


@dataclass(frozen=True, slots=True)
class ScopeCoverageReport:
    scope_paths: tuple[str, ...]
    scope_paths_with_memory: int
    scope_paths_total: int
    scope_coverage_percent: int
    uncovered_paths: tuple[str, ...]


def compute_scope_coverage(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    scope_paths: Sequence[str],
) -> ScopeCoverageReport:
    normalized = normalize_memory_scope_paths(scope_paths)
    with_memory = 0
    uncovered: list[str] = []
    for scope_path in normalized:
        if path_has_memory(
            store,
            project_id=project_id,
            rel_path=scope_path,
        ):
            with_memory += 1
        else:
            uncovered.append(scope_path)
    total = len(normalized)
    percent = round(with_memory * 100 / total) if total else 100
    return ScopeCoverageReport(
        scope_paths=normalized,
        scope_paths_with_memory=with_memory,
        scope_paths_total=total,
        scope_coverage_percent=percent,
        uncovered_paths=tuple(uncovered),
    )


def coverage_delta(
    before: ScopeCoverageReport,
    after: ScopeCoverageReport,
) -> dict[str, object]:
    before_set = set(before.scope_paths) - set(before.uncovered_paths)
    after_set = set(after.scope_paths) - set(after.uncovered_paths)
    newly_uncovered = sorted(after_set - before_set)
    return {
        "scope_coverage_before": before.scope_coverage_percent,
        "scope_coverage_after": after.scope_coverage_percent,
        "new_uncovered_paths": newly_uncovered,
    }


__all__ = [
    "ScopeCoverageReport",
    "compute_scope_coverage",
    "coverage_delta",
]
