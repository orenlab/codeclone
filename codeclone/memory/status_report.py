# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..contracts import ENGINEERING_MEMORY_SCHEMA_VERSION
from .project import read_git_provenance, resolve_project_identity
from .sqlite_store import SqliteEngineeringMemoryStore


@dataclass(frozen=True, slots=True)
class MemoryStatusReport:
    db_path: Path
    schema_version: str | None
    project_id: str | None
    project_root: str | None
    backend: str
    git_available: bool
    git_branch: str | None
    git_head: str | None
    last_analysis_fingerprint: str | None
    last_init_run_id: str | None
    record_count: int
    records_by_type: dict[str, int]
    records_by_status: dict[str, int]
    db_exists: bool


def build_memory_status_report(
    *,
    root_path: Path,
    db_path: Path,
    backend: str = "sqlite",
) -> MemoryStatusReport:
    resolved_root = root_path.resolve()
    project = resolve_project_identity(resolved_root)
    git = read_git_provenance(resolved_root)
    if not db_path.exists():
        return MemoryStatusReport(
            db_path=db_path,
            schema_version=None,
            project_id=project.id,
            project_root=str(resolved_root),
            backend=backend,
            git_available=git.available,
            git_branch=git.branch,
            git_head=git.head,
            last_analysis_fingerprint=None,
            last_init_run_id=None,
            record_count=0,
            records_by_type={},
            records_by_status={},
            db_exists=False,
        )

    store = SqliteEngineeringMemoryStore(db_path)
    try:
        schema_version = store.get_meta("schema_version")
        project_id = store.get_meta("project_id") or project.id
        project_root = store.get_meta("project_root") or str(resolved_root)
        last_analysis_fingerprint = store.get_meta("last_analysis_fingerprint")
        last_init_run_id = store.get_meta("last_init_run_id")
        record_count = store.count_records()
        records_by_type = store.count_records_grouped(column="type")
        records_by_status = store.count_records_grouped(column="status")
    finally:
        store.close()

    return MemoryStatusReport(
        db_path=db_path,
        schema_version=schema_version or ENGINEERING_MEMORY_SCHEMA_VERSION,
        project_id=project_id,
        project_root=project_root,
        backend=backend,
        git_available=git.available,
        git_branch=git.branch,
        git_head=git.head,
        last_analysis_fingerprint=last_analysis_fingerprint,
        last_init_run_id=last_init_run_id,
        record_count=record_count,
        records_by_type=records_by_type,
        records_by_status=records_by_status,
        db_exists=True,
    )


__all__ = ["MemoryStatusReport", "build_memory_status_report"]
