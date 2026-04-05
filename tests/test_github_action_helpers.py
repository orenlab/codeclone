# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, cast


def _load_action_impl() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "actions"
        / "codeclone"
        / "_action_impl.py"
    )
    spec = importlib.util.spec_from_file_location("codeclone_action_impl", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _assert_contains_all(text: str, expected_parts: tuple[str, ...]) -> None:
    for expected in expected_parts:
        assert expected in text


def _resolve_install_target(
    *,
    action_path: Path,
    workspace: Path,
    package_version: str,
) -> Any:
    action_impl = _load_action_impl()
    return action_impl.resolve_install_target(
        action_path=str(action_path),
        workspace=str(workspace),
        package_version=package_version,
    )


def test_build_codeclone_args_includes_enabled_gates_and_paths() -> None:
    action_impl = _load_action_impl()
    inputs = action_impl.ActionInputs(
        path=".",
        json_path=".cache/codeclone/report.json",
        sarif=True,
        sarif_path=".cache/codeclone/report.sarif",
        fail_on_new=True,
        fail_on_new_metrics=True,
        fail_threshold=5,
        fail_complexity=20,
        fail_coupling=10,
        fail_cohesion=4,
        fail_cycles=True,
        fail_dead_code=True,
        fail_health=60,
        baseline_path="codeclone.baseline.json",
        metrics_baseline_path="codeclone.baseline.json",
        extra_args="--no-color --quiet",
        no_progress=True,
    )

    args = cast(list[str], action_impl.build_codeclone_args(inputs))

    assert args[:5] == [
        ".",
        "--json",
        ".cache/codeclone/report.json",
        "--sarif",
        ".cache/codeclone/report.sarif",
    ]
    _assert_contains_all(
        " ".join(args),
        (
            "--fail-on-new",
            "--fail-on-new-metrics",
            "--fail-cycles",
            "--fail-dead-code",
            "--no-progress",
            "--baseline",
            "--metrics-baseline",
            "--no-color",
            "--quiet",
        ),
    )


def test_render_pr_comment_uses_canonical_report_summary() -> None:
    action_impl = _load_action_impl()
    report = {
        "meta": {
            "codeclone_version": "2.0.0b4",
            "baseline": {"status": "ok"},
            "cache": {"used": True},
        },
        "findings": {
            "summary": {
                "families": {
                    "clones": 8,
                    "structural": 15,
                    "dead_code": 0,
                    "design": 3,
                },
                "clones": {
                    "new": 1,
                    "known": 7,
                },
            }
        },
        "metrics": {
            "summary": {
                "health": {
                    "score": 81,
                    "grade": "B",
                }
            }
        },
    }

    body = cast(str, action_impl.render_pr_comment(report, exit_code=3))

    _assert_contains_all(
        body,
        (
            "<!-- codeclone-report -->",
            "CodeClone Report",
            "**81/100 (B)**",
            ":x: Failed (gating)",
            "Clones: 8 (1 new, 7 known)",
            "Structural: 15",
            "Dead code: 0",
            "Design: 3",
            "`2.0.0b4`",
        ),
    )


def test_resolve_install_target_uses_repo_source_for_local_action_checkout(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "codeclone"
    action_path = repo_root / ".github" / "actions" / "codeclone"
    action_path.mkdir(parents=True)

    target = _resolve_install_target(
        action_path=action_path,
        workspace=repo_root,
        package_version="2.0.0b4",
    )

    assert target.source == "repo"
    assert target.requirement == str(repo_root.resolve())


def test_resolve_install_target_uses_pypi_for_remote_checkout(tmp_path: Path) -> None:
    workspace_root = tmp_path / "consumer"
    action_repo = tmp_path / "_actions" / "orenlab" / "codeclone" / "main"
    action_path = action_repo / ".github" / "actions" / "codeclone"
    action_path.mkdir(parents=True)
    workspace_root.mkdir()

    pinned = _resolve_install_target(
        action_path=action_path,
        workspace=workspace_root,
        package_version="2.0.0b4",
    )
    latest = _resolve_install_target(
        action_path=action_path,
        workspace=workspace_root,
        package_version="",
    )

    assert (
        pinned.source,
        pinned.requirement,
        latest.source,
        latest.requirement,
    ) == (
        "pypi-version",
        "codeclone==2.0.0b4",
        "pypi-latest",
        "codeclone",
    )
