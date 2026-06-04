# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import io
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest

from codeclone.memory.coverage import ScopeCoverageReport
from codeclone.memory.models import MemoryQuery
from codeclone.memory.status_report import MemoryStatusReport
from codeclone.memory.vacuum import VacuumReport
from codeclone.surfaces.cli import memory_render
from codeclone.surfaces.cli.console import PlainConsole
from tests.memory_fixtures import cli_memory_repo


def _render_coverage_report_rich(report: ScopeCoverageReport) -> str:
    from rich.console import Console

    from codeclone.surfaces.cli.types import PrinterLike

    output = io.StringIO()
    rich_console = Console(file=output, force_terminal=True, color_system=None)
    with patch.object(memory_render, "supports_rich_console", return_value=True):
        memory_render.render_coverage_report(
            console=cast(PrinterLike, rich_console),
            report=report,
        )
    return output.getvalue()


def test_memory_render_plain_console_paths(capsys: pytest.CaptureFixture[str]) -> None:
    console = PlainConsole()
    records = [
        {
            "id": "mem-1",
            "type": "module_role",
            "status": "active",
            "statement": "plain path",
        }
    ]
    status = MemoryStatusReport(
        db_path=Path("/tmp/repo/.codeclone/memory/engineering_memory.sqlite3"),
        schema_version="1.1",
        project_id="proj-1",
        project_root="/tmp/repo",
        backend="sqlite",
        git_available=False,
        git_branch=None,
        git_head=None,
        last_analysis_fingerprint=None,
        last_init_run_id=None,
        record_count=1,
        records_by_type={"module_role": 1},
        records_by_status={"active": 1},
        db_exists=True,
    )
    coverage = ScopeCoverageReport(
        scope_paths=("pkg/mod.py", "pkg/missing.py"),
        scope_paths_total=2,
        scope_paths_with_memory=1,
        scope_coverage_percent=50,
        uncovered_paths=("pkg/missing.py",),
    )
    with patch.object(memory_render, "supports_rich_console", return_value=False):
        memory_render.render_search_results(
            console=console,
            query="plain",
            records=records,
        )
        memory_render.render_path_results(
            console=console,
            rel_path="pkg/mod.py",
            records=[],
        )
        memory_render.render_status_report(console=console, report=status)
        memory_render.render_init_note(console=console, message="plain note")
        memory_render.render_init_result(
            console=console,
            dry_run=False,
            project_id="proj-1",
            db_path="/tmp/db.sqlite3",
            analysis_fingerprint="fp",
            stats={"created": 2, "updated": 1},
            planned_counts={"module_role": 2},
        )
        memory_render.render_init_result(
            console=console,
            dry_run=True,
            project_id="proj-1",
            db_path=None,
            analysis_fingerprint="fp",
            stats=None,
            planned_counts={"module_role": 2},
        )
        memory_render.render_stale_records(console=console, records=records)
        memory_render.render_vacuum_report(
            console=console,
            report=VacuumReport(deleted_by_status={"draft": 2}, total_deleted=2),
        )
        memory_render.render_coverage_report(console=console, report=coverage)
        memory_render.render_draft_candidates(console=console, records=[])
        memory_render.render_governance_result(
            console=console,
            action="rejected",
            record_id="mem-1",
            detail="rejected mem-1",
        )
    output = capsys.readouterr().out
    assert "Engineering Memory search" in output
    assert "Engineering Memory initialized" in output
    assert "pkg/missing.py" in output


def test_memory_render_plain_extra_branches(
    tmp_path: Path,
) -> None:
    messages: list[str] = []

    class _CaptureConsole:
        def print(self, *objects: object, **kwargs: object) -> None:
            _sep = str(kwargs.get("sep", " "))
            _end = str(kwargs.get("end", "\n"))
            messages.append(_sep.join(str(item) for item in objects) + _end)

    console = _CaptureConsole()
    with cli_memory_repo(tmp_path) as (_root, project, store):
        drafts = [
            rec
            for rec in store.query_records(
                MemoryQuery(
                    project_id=project.id,
                    statuses=("draft",),
                    limit=20,
                    offset=0,
                )
            )
            if rec.status == "draft"
        ]
        assert drafts
        draft_records = drafts[:1]

    with patch.object(memory_render, "supports_rich_console", return_value=False):
        memory_render.render_stale_records(console=console, records=[])
        memory_render.render_draft_candidates(
            console=console,
            records=draft_records,
        )

    assert memory_render._status_style("stale") == "yellow"
    assert memory_render._status_style("draft") == "magenta"

    output = "".join(messages)
    assert output.count("(none)") == 1
    assert "Stale engineering memory records" in output
    assert "Draft memory candidates" in output


def test_memory_render_coverage_lists_uncovered_paths_rich(
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = ScopeCoverageReport(
        scope_paths=("pkg/a.py", "pkg/b.py"),
        scope_paths_total=2,
        scope_paths_with_memory=1,
        scope_coverage_percent=50,
        uncovered_paths=("pkg/missing.py",),
    )
    rendered = _render_coverage_report_rich(report)
    assert "pkg/missing.py" in rendered


def test_memory_render_coverage_all_paths_covered_plain_and_rich(
    capsys: pytest.CaptureFixture[str],
) -> None:
    full_coverage = ScopeCoverageReport(
        scope_paths=("pkg/mod.py",),
        scope_paths_total=1,
        scope_paths_with_memory=1,
        scope_coverage_percent=100,
        uncovered_paths=(),
    )
    console = PlainConsole()
    with patch.object(memory_render, "supports_rich_console", return_value=False):
        memory_render.render_coverage_report(console=console, report=full_coverage)
    plain_out = capsys.readouterr().out
    assert "uncovered" not in plain_out

    assert "all scoped paths covered" in _render_coverage_report_rich(full_coverage)


def test_memory_render_status_without_type_breakdown(
    capsys: pytest.CaptureFixture[str],
) -> None:
    status = MemoryStatusReport(
        db_path=Path("/tmp/db.sqlite3"),
        schema_version="1.1",
        project_id="proj-1",
        project_root="/tmp/repo",
        backend="sqlite",
        git_available=False,
        git_branch=None,
        git_head=None,
        last_analysis_fingerprint=None,
        last_init_run_id=None,
        record_count=0,
        records_by_type={},
        records_by_status={},
        db_exists=True,
    )
    console = PlainConsole()
    with patch.object(memory_render, "supports_rich_console", return_value=False):
        memory_render.render_status_report(console=console, report=status)
    out = capsys.readouterr().out
    assert "records_by_type" not in out


def test_memory_render_init_dry_run_skips_empty_count_maps(
    capsys: pytest.CaptureFixture[str],
) -> None:
    console = PlainConsole()
    with patch.object(memory_render, "supports_rich_console", return_value=False):
        memory_render.render_init_result(
            console=console,
            dry_run=True,
            project_id="proj-1",
            db_path=None,
            analysis_fingerprint="fp",
            stats=None,
            planned_counts=None,
        )
    out = capsys.readouterr().out
    assert "planned records" not in out
