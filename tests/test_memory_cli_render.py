# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

from codeclone.memory.coverage import compute_scope_coverage
from codeclone.memory.status_report import build_memory_status_report
from codeclone.memory.vacuum import VacuumReport
from codeclone.surfaces.cli.memory_render import (
    memory_console,
    render_coverage_report,
    render_draft_candidates,
    render_governance_result,
    render_init_note,
    render_init_result,
    render_path_results,
    render_search_results,
    render_stale_records,
    render_status_report,
    render_vacuum_report,
)
from tests.memory_fixtures import cli_memory_repo


def test_memory_render_helpers_smoke(tmp_path: Path) -> None:
    console = memory_console()
    with cli_memory_repo(tmp_path) as (root, project, store):
        from codeclone.config.memory import resolve_memory_config
        from codeclone.memory.project import resolve_memory_db_path
        from codeclone.memory.retrieval import query_records_for_repo_path

        config = resolve_memory_config(root)
        db_path = resolve_memory_db_path(root, config)
        records = query_records_for_repo_path(
            store,
            project_id=project.id,
            rel_path="pkg/mod.py",
            limit=5,
        )
        status = build_memory_status_report(
            root_path=root,
            db_path=db_path,
            backend=config.backend,
        )
        coverage = compute_scope_coverage(
            store,
            project_id=project.id,
            scope_paths=("pkg/mod.py",),
        )
        store.close()

    render_search_results(
        console=console,
        query="fixture",
        records=[{"id": "mem-1", "type": "module_role", "statement": "x"}],
    )
    render_path_results(console=console, rel_path="pkg/mod.py", records=records)
    render_status_report(console=console, report=status)
    render_init_note(console=console, message="running analysis")
    render_init_result(
        console=console,
        dry_run=True,
        project_id=project.id,
        db_path=str(db_path),
        analysis_fingerprint="abc",
        stats={"created": 1},
        planned_counts={"module_role": 1},
    )
    render_stale_records(console=console, records=[])
    render_vacuum_report(
        console=console,
        report=VacuumReport(deleted_by_status={"stale": 1}, total_deleted=1),
    )
    render_coverage_report(console=console, report=coverage)
    render_draft_candidates(console=console, records=[])
    render_governance_result(
        console=console,
        action="approved",
        record_id="mem-1",
        detail="approved mem-1 -> active",
    )
