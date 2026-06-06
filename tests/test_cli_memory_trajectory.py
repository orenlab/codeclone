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
