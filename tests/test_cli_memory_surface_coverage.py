# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from codeclone.audit.validation import DEFAULT_AUDIT_PATH, resolve_audit_path
from codeclone.contracts import ExitCode
from codeclone.memory.exceptions import MemoryContractError
from codeclone.surfaces.cli import memory as memory_cli
from codeclone.surfaces.cli.memory import memory_main

from .memory_fixtures import cli_memory_repo
from .test_cli_memory_trajectory import _seed_cli_audit


def _trajectory_repo(tmp_path: Path) -> tuple[Path, str]:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, project, store):
        _seed_cli_audit(root)
        store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=resolve_audit_path(root_path=root, value=DEFAULT_AUDIT_PATH),
        )
        trajectory_id = store.list_trajectories(project_id=project.id, limit=1)[0].id
        store.close()
    return root, trajectory_id


def test_trajectory_cli_agents_anomalies_dashboard_text_and_json(
    tmp_path: Path,
) -> None:
    root, _trajectory_id = _trajectory_repo(tmp_path)
    root_arg = str(root.resolve())
    for action in ("agents", "anomalies", "dashboard"):
        assert memory_main(["trajectory", action, "--root", root_arg]) == int(
            ExitCode.SUCCESS
        )
        assert memory_main(["trajectory", action, "--root", root_arg, "--json"]) == int(
            ExitCode.SUCCESS
        )
    assert memory_main(
        [
            "trajectory",
            "agents",
            "--root",
            root_arg,
            "--include-routine",
        ]
    ) == int(ExitCode.SUCCESS)


@pytest.mark.parametrize(
    "argv",
    [
        ["trajectory", "rebuild"],
        ["trajectory", "agents"],
        ["trajectory", "anomalies"],
        ["trajectory", "dashboard"],
        ["trajectory", "show", "traj-missing"],
        [
            "trajectory",
            "export",
            "--profile",
            "agent-memory-retrieval-v1",
            "--out",
            "out.jsonl",
        ],
    ],
)
def test_trajectory_cli_missing_db_reports_error(
    tmp_path: Path,
    argv: list[str],
) -> None:
    missing = tmp_path / "missing"
    missing.mkdir()
    assert memory_main([*argv, "--root", str(missing)]) == int(ExitCode.CONTRACT_ERROR)


def test_trajectory_cli_rebuild_disabled_and_missing_db(tmp_path: Path) -> None:
    disabled_root = tmp_path / "disabled"
    disabled_root.mkdir()
    (disabled_root / "pyproject.toml").write_text(
        "[tool.codeclone.memory]\ntrajectories_enabled = false\n",
        encoding="utf-8",
    )
    with cli_memory_repo(disabled_root, with_draft=False) as (root, _project, store):
        store.close()
    code = memory_main(["trajectory", "rebuild", "--root", str(root.resolve())])
    assert code == int(ExitCode.CONTRACT_ERROR)

    missing = tmp_path / "missing"
    missing.mkdir()
    assert memory_main(["trajectory", "list", "--root", str(missing)]) == int(
        ExitCode.CONTRACT_ERROR
    )
    assert memory_main(
        ["trajectory", "search", "exercise", "--root", str(missing)]
    ) == int(ExitCode.CONTRACT_ERROR)


def test_trajectory_cli_show_missing_and_export_json(tmp_path: Path) -> None:
    root, _trajectory_id = _trajectory_repo(tmp_path)
    root_arg = str(root.resolve())
    assert memory_main(
        ["trajectory", "show", "traj-missing", "--root", root_arg]
    ) == int(ExitCode.CONTRACT_ERROR)
    out_path = root / "exports" / "out.jsonl"
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
            "--json",
        ]
    ) == int(ExitCode.SUCCESS)


@pytest.mark.parametrize(
    "action, patch_return",
    [
        ("agents", {"payload": "not-a-dict"}),
        ("anomalies", {"payload": None}),
        ("dashboard", {}),
    ],
)
def test_trajectory_cli_payload_guards(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    patch_return: dict[str, object],
) -> None:
    root, _ = _trajectory_repo(tmp_path)
    root_arg = str(root.resolve())
    monkeypatch.setattr(
        "codeclone.surfaces.cli.memory.query_engineering_memory",
        lambda *_args, **_kwargs: patch_return,
    )
    code = memory_main(["trajectory", action, "--root", root_arg])
    assert code == int(ExitCode.INTERNAL_ERROR)


def test_trajectory_cli_rebuild_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, store):
        _seed_cli_audit(root)
        store.close()
    root_arg = str(root.resolve())

    class _BrokenStore:
        def rebuild_trajectories_from_audit(self, **_kwargs: object) -> None:
            raise RuntimeError("boom")

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        "codeclone.surfaces.cli.memory.SqliteEngineeringMemoryStore",
        lambda _path: _BrokenStore(),
    )
    code = memory_main(["trajectory", "rebuild", "--root", root_arg])
    assert code == int(ExitCode.CONTRACT_ERROR)


def test_trajectory_export_contract_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _ = _trajectory_repo(tmp_path)
    root_arg = str(root.resolve())

    def _raise(*_args: object, **_kwargs: object) -> None:
        raise MemoryContractError("export blocked")

    monkeypatch.setattr(
        "codeclone.surfaces.cli.memory.export_trajectories_jsonl",
        _raise,
    )
    code = memory_main(
        [
            "trajectory",
            "export",
            "--root",
            root_arg,
            "--profile",
            "agent-memory-retrieval-v1",
            "--out",
            "out.jsonl",
            "--force",
        ]
    )
    assert code == int(ExitCode.CONTRACT_ERROR)


def test_jobs_list_and_run_once(tmp_path: Path) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        root_arg = str(root.resolve())
        assert memory_main(["jobs", "list", "--root", root_arg]) == int(
            ExitCode.SUCCESS
        )
        assert memory_main(
            ["jobs", "list", "--root", root_arg, "--json", "--limit", "3"]
        ) == int(ExitCode.SUCCESS)
        assert memory_main(["jobs", "run-once", "--root", root_arg]) == int(
            ExitCode.SUCCESS
        )


def test_jobs_contract_error_renders_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        root_arg = str(root.resolve())

        def _raise(*_args: object, **_kwargs: object) -> dict[str, object]:
            raise MemoryContractError("jobs blocked")

        monkeypatch.setattr(
            "codeclone.surfaces.cli.memory.execute_run_projection_jobs_once",
            _raise,
        )
        code = memory_main(["jobs", "run-once", "--root", root_arg])
        assert code == int(ExitCode.CONTRACT_ERROR)


def test_jobs_list_contract_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        root_arg = str(root.resolve())
        monkeypatch.setattr(
            "codeclone.surfaces.cli.memory.execute_projection_rebuild_status",
            lambda **_kwargs: (_ for _ in ()).throw(
                MemoryContractError("jobs list blocked")
            ),
        )
        code = memory_main(["jobs", "list", "--root", root_arg])
        assert code == int(ExitCode.CONTRACT_ERROR)


def test_jobs_list_with_populated_queue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        root_arg = str(root.resolve())
        monkeypatch.setattr(
            "codeclone.surfaces.cli.memory.execute_projection_rebuild_status",
            lambda **_kwargs: {
                "status": "ok",
                "jobs": [
                    {
                        "id": "job-1",
                        "status": "completed",
                        "trigger": "cli",
                        "requested_at_utc": "2026-01-01T00:00:00Z",
                    }
                ],
            },
        )
        code = memory_main(["jobs", "list", "--root", root_arg])
        assert code == int(ExitCode.SUCCESS)


def test_search_semantic_advisory_when_provider_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with cli_memory_repo(tmp_path) as (root, _project, _store):
        root_arg = str(root.resolve())
        monkeypatch.setattr(
            "codeclone.surfaces.cli.memory.resolve_embedding_provider",
            lambda _cfg: (_ for _ in ()).throw(
                __import__(
                    "codeclone.memory.exceptions",
                    fromlist=["MemorySemanticUnavailableError"],
                ).MemorySemanticUnavailableError("no provider")
            ),
        )
        monkeypatch.setattr(
            "codeclone.surfaces.cli.memory.query_engineering_memory",
            lambda *_args, **_kwargs: {
                "payload": {"records": []},
                "semantic": {"used": False, "reason": "provider missing"},
            },
        )
        code = memory_main(["search", "fixture", "--root", root_arg, "--semantic"])
        assert code == int(ExitCode.SUCCESS)


def test_dashboard_json_payload_is_valid(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root, _ = _trajectory_repo(tmp_path)
    code = memory_main(
        ["trajectory", "dashboard", "--root", str(root.resolve()), "--json"]
    )
    assert code == int(ExitCode.SUCCESS)
    output = capsys.readouterr().out
    assert '"trajectory_count"' in output
    assert '"agents"' in output


def test_memory_operation_name_includes_subcommand_actions() -> None:
    assert (
        memory_cli._memory_operation_name(
            Namespace(command="semantic", semantic_action="rebuild")
        )
        == "cli.memory.semantic.rebuild"
    )
    assert (
        memory_cli._memory_operation_name(
            Namespace(command="trajectory", trajectory_action="show")
        )
        == "cli.memory.trajectory.show"
    )
    assert (
        memory_cli._memory_operation_name(Namespace(command="jobs", jobs_action="list"))
        == "cli.memory.jobs.list"
    )
    assert (
        memory_cli._memory_operation_name(Namespace(command="search"))
        == "cli.memory.search"
    )
