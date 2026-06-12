# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

from codeclone.audit.events import AuditEvent, repo_root_digest
from codeclone.audit.validation import DEFAULT_AUDIT_PATH, resolve_audit_path
from codeclone.audit.writer import SqliteAuditWriter
from codeclone.contracts import ExitCode
from codeclone.surfaces.cli.memory import memory_main

from .memory_fixtures import cli_memory_repo


def _seed_cli_audit(root: Path) -> None:
    audit_db = resolve_audit_path(root_path=root, value=DEFAULT_AUDIT_PATH)
    root_digest = repo_root_digest(root.resolve())
    writer = SqliteAuditWriter(
        db_path=audit_db,
        payloads="compact",
        retention_days=30,
    )
    try:
        for event_type, status in (
            ("intent.declared", "active"),
            ("patch_contract.verified", "accepted"),
        ):
            writer.emit(
                AuditEvent(
                    event_type=event_type,
                    severity="info",
                    repo_root_digest=root_digest,
                    agent_pid=42,
                    agent_label="cli-test",
                    intent_id="intent-cli-001",
                    run_id="12345678",
                    report_digest="3" * 64,
                    status=status,
                    payload={
                        "intent_description": "exercise trajectory CLI",
                        "scope": {"allowed_files": ["pkg/mod.py"]},
                        "status": status,
                        "structural_delta": {
                            "regressions": [],
                            "improvements": [],
                            "health_delta": 0,
                        },
                        "contract_violations": [],
                        "baseline_abuse": {"detected": False},
                    },
                )
            )
    finally:
        writer.close()


def test_memory_trajectory_cli_status_rebuild_list_show(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, store):
        _seed_cli_audit(root)
        store.close()

    root_arg = str(root.resolve())
    assert memory_main(["trajectory", "status", "--root", root_arg]) == int(
        ExitCode.SUCCESS
    )
    assert memory_main(["trajectory", "rebuild", "--root", root_arg]) == int(
        ExitCode.SUCCESS
    )
    assert memory_main(["trajectory", "list", "--root", root_arg]) == int(
        ExitCode.SUCCESS
    )
    assert memory_main(["trajectory", "search", "exercise", "--root", root_arg]) == int(
        ExitCode.SUCCESS
    )

    with cli_memory_repo(tmp_path / "lookup", with_draft=False) as (
        root2,
        project2,
        store2,
    ):
        _seed_cli_audit(root2)
        result = store2.rebuild_trajectories_from_audit(
            project=project2,
            root_path=root2,
            audit_db_path=resolve_audit_path(root_path=root2, value=DEFAULT_AUDIT_PATH),
        )
        trajectory_id = result.trajectories[0].id
        store2.close()

    assert memory_main(
        ["trajectory", "show", trajectory_id, "--root", str(root2.resolve())]
    ) == int(ExitCode.SUCCESS)


def test_memory_trajectory_cli_export_and_missing_db(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, project, store):
        _seed_cli_audit(root)
        store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=resolve_audit_path(root_path=root, value=DEFAULT_AUDIT_PATH),
        )
        store.close()

    root_arg = str(root.resolve())
    out_path = root / "exports" / "trajectories.jsonl"
    assert memory_main(
        [
            "trajectory",
            "export",
            "--root",
            root_arg,
            "--profile",
            "agent-memory-retrieval-v1",
            "--out",
            str(out_path),
            "--force",
        ]
    ) == int(ExitCode.SUCCESS)
    assert out_path.is_file()

    missing_root = tmp_path / "missing"
    missing_root.mkdir()
    assert memory_main(["trajectory", "status", "--root", str(missing_root)]) == int(
        ExitCode.CONTRACT_ERROR
    )


def test_trajectory_renderers_handle_populated_and_empty_payloads(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    from codeclone.memory.trajectory.cli_render import (
        render_projection_run,
        render_trajectory_agents,
        render_trajectory_anomalies,
        render_trajectory_detail,
        render_trajectory_list,
        render_trajectory_search_results,
        render_trajectory_status,
    )
    from codeclone.memory.trajectory.models import TrajectoryListItem

    from .memory_fixtures import memory_store, seed_trajectory_audit_workflow

    class _CapturePrinter:
        def __init__(self) -> None:
            self.lines: list[str] = []

        def print(self, *objects: object, **_kwargs: object) -> None:
            self.lines.append(" ".join(str(item) for item in objects))

    with memory_store(tmp_path) as (root, project, store, _db_path):
        audit_db = tmp_path / "audit.sqlite3"
        seed_trajectory_audit_workflow(root=root, audit_db=audit_db)
        projection = store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        )
    run = replace(projection.run, legacy_event_count=3)
    trajectory = projection.trajectories[0]

    printer = _CapturePrinter()
    render_trajectory_status(
        console=printer,
        enabled=True,
        count=1,
        latest_run=run,
    )
    render_projection_run(console=printer, run=run)
    render_trajectory_list(console=printer, items=[])
    assert "No trajectories found." in printer.lines

    item = TrajectoryListItem(
        id=trajectory.id,
        workflow_id=trajectory.workflow_id,
        outcome=trajectory.outcome,
        quality_tier=trajectory.quality_tier,
        quality_score=trajectory.quality_score,
        event_count=trajectory.event_count,
        started_at_utc=trajectory.started_at_utc,
        finished_at_utc=trajectory.finished_at_utc,
        summary=trajectory.summary,
    )
    render_trajectory_list(console=printer, items=[item])
    render_trajectory_search_results(
        console=printer,
        query="recover",
        trajectories=[],
    )
    render_trajectory_agents(console=printer, payload={"agents": []})
    render_trajectory_agents(
        console=printer,
        payload={
            "agent_count": 1,
            "trajectory_count": 1,
            "unlabeled_trajectory_count": 0,
            "agents": [
                "not-a-mapping",
                {"agent_label": "agent", "trajectory_count": 1},
            ],
        },
    )
    render_trajectory_anomalies(
        console=printer,
        payload={
            "summary": {
                "trajectories_with_anomalies": 1,
                "anomaly_count": 1,
                "error_count": 1,
                "warn_count": 0,
            },
            "trajectories": [
                "skip",
                {
                    "trajectory_id": trajectory.id,
                    "agent_label": "agent",
                    "outcome": "violated",
                    "quality_tier": "incident",
                    "anomalies": [
                        "skip",
                        {
                            "severity": "error",
                            "kind": "scope_violation",
                            "message": "bad scope",
                        },
                    ],
                },
            ],
        },
    )
    render_trajectory_detail(console=printer, trajectory=trajectory)

    joined = "\n".join(printer.lines)
    assert trajectory.id in joined
    assert "No matching trajectories" in joined
    assert "No agent-labeled" in joined
    assert "scope_violation" in joined
    assert trajectory.summary in joined
