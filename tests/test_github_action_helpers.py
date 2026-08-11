# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import importlib.util
import re
import sys
from dataclasses import fields
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import yaml

from codeclone.config.argparse_builder import build_parser

#: The parser's option set does not depend on the version string the
#: ``--version`` action prints, and importing the package for it would pull an
#: r4 dependency into an otherwise r2-scoped test module.
_PARSER_PROBE_VERSION = "0.0.0"


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
        json_path=".codeclone/report.json",
        sarif=True,
        sarif_path=".codeclone/report.sarif",
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
        extra_args="--no-color --quiet",
        no_progress=True,
    )

    args = cast(list[str], action_impl.build_codeclone_args(inputs))

    assert args[:5] == [
        ".",
        "--json",
        ".codeclone/report.json",
        "--sarif",
        ".codeclone/report.sarif",
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
            "--no-color",
            "--quiet",
        ),
    )
    assert "--metrics-baseline" not in args


def test_render_pr_comment_uses_canonical_report_summary() -> None:
    action_impl = _load_action_impl()
    report = {
        "meta": {
            "codeclone_version": "2.0.0",
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
                },
                "complexity": {"max": 20, "high_risk": 0},
                "coupling": {"max": 10, "high_risk": 0},
                "cohesion": {"max": 3, "low_cohesion": 0},
                "dependencies": {
                    "avg_depth": 4.0,
                    "p95_depth": 13,
                    "max_depth": 16,
                    "cycles": 0,
                },
                "dead_code": {"high_confidence": 0, "suppressed": 2},
                "overloaded_modules": {"candidates": 13},
                "coverage_join": {
                    "status": "ok",
                    "overall_permille": 994,
                    "coverage_hotspots": 1,
                    "scope_gap_hotspots": 2,
                },
                "security_surfaces": {
                    "items": 58,
                    "category_count": 4,
                    "production": 28,
                },
                "api_surface": {
                    "enabled": True,
                    "public_symbols": 2119,
                    "modules": 208,
                    "breaking": 0,
                    "added": 0,
                },
            }
        },
    }

    body = cast(str, action_impl.render_pr_comment(report, exit_code=3))

    _assert_contains_all(
        body,
        (
            "<!-- codeclone-report -->",
            "CodeClone Review",
            "Review snapshot",
            "**81/100 (B)**",
            "**:x: Failed (gating)**",
            "8 total, 1 new, 7 known",
            "CC max 20, CBO max 10, LCOM4 max 3, overloaded 13",
            "avg 4.0, p95 13, max 16, cycles 0",
            "99.4% overall, 1 hotspots, 2 scope gaps",
            "58 surfaces, 4 categories, 28 production",
            "2119 symbols, 208 modules",
            "CI gates failed; start with rows marked as gating-sensitive.",
            "Security Surfaces are report-only capability inventory",
            "`2.0.0`",
        ),
    )


def test_mapping_returns_json_object_unchanged() -> None:
    action_impl = _load_action_impl()
    payload: dict[str, object] = {"status": "ok", "count": 1}

    assert action_impl._mapping(payload) is payload
    assert action_impl._mapping(None) == {}


def test_resolve_install_target_uses_repo_source_for_local_action_checkout(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "codeclone"
    action_path = repo_root / ".github" / "actions" / "codeclone"
    action_path.mkdir(parents=True)

    target = _resolve_install_target(
        action_path=action_path,
        workspace=repo_root,
        package_version="2.0.0",
    )

    assert target.source == "repo"
    assert target.requirement == str(repo_root.resolve())


def test_resolve_install_target_uses_pypi_for_remote_checkout(tmp_path: Path) -> None:
    action_impl = _load_action_impl()
    workspace_root = tmp_path / "consumer"
    action_repo = tmp_path / "_actions" / "orenlab" / "codeclone" / "main"
    action_path = action_repo / ".github" / "actions" / "codeclone"
    action_path.mkdir(parents=True)
    workspace_root.mkdir()

    pinned = _resolve_install_target(
        action_path=action_path,
        workspace=workspace_root,
        package_version="2.0.0",
    )
    default = _resolve_install_target(
        action_path=action_path,
        workspace=workspace_root,
        package_version="",
    )

    assert (
        pinned.source,
        pinned.requirement,
        default.source,
        default.requirement,
    ) == (
        "pypi-version",
        "codeclone==2.0.0",
        "pypi-default",
        f"codeclone=={action_impl.DEFAULT_CODECLONE_PACKAGE_VERSION}",
    )


def test_action_default_package_version_tracks_release_version() -> None:
    action_impl = _load_action_impl()
    action_metadata = Path(".github/actions/codeclone/action.yml").read_text(
        encoding="utf-8"
    )
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    version_match = re.search(r'^version = "([^"]+)"$', pyproject, re.MULTILINE)
    assert version_match is not None
    version = version_match.group(1)

    assert version == action_impl.DEFAULT_CODECLONE_PACKAGE_VERSION
    assert f'default: "{version}"' in action_metadata


def _action_metadata() -> dict[str, Any]:
    path = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "actions"
        / "codeclone"
        / "action.yml"
    )
    return cast(dict[str, Any], yaml.safe_load(path.read_text(encoding="utf-8")))


def _action_default_env() -> dict[str, str]:
    declared = cast(dict[str, Any], _action_metadata()["inputs"])
    return {
        f"INPUT_{name.upper().replace('-', '_')}": str(spec.get("default", ""))
        for name, spec in declared.items()
    }


def _maximal_action_inputs(action_impl: ModuleType) -> Any:
    """Populate every action input so no valued option stays unemitted."""

    values: dict[str, object] = {}
    for field in fields(cast(Any, action_impl.ActionInputs)):
        annotation = str(field.type)
        if field.name == "path":
            values[field.name] = "."
        elif field.name == "extra_args":
            # Free-form user text, not part of the action's own CLI contract.
            values[field.name] = ""
        elif annotation == "bool":
            values[field.name] = True
        elif annotation.startswith("int"):
            values[field.name] = 1
        elif annotation == "str":
            values[field.name] = f"{field.name}.value"
        else:
            raise AssertionError(f"Unhandled action input type: {annotation}")
    return action_impl.ActionInputs(**values)


def _unrecognized_cli_arguments(args: list[str]) -> list[str]:
    """Return the action arguments the real CodeClone parser does not know."""

    _namespace, extras = build_parser(_PARSER_PROBE_VERSION).parse_known_args(args)
    return list(extras)


def test_action_default_invocation_is_accepted_by_the_cli_parser() -> None:
    # The README quickstart overrides no input, so action.yml defaults alone
    # must produce a command line the shipped parser accepts. A CLI option
    # removed in a release but still emitted here fails every default run
    # before analysis starts.
    action_impl = _load_action_impl()
    inputs = action_impl.build_inputs_from_env(_action_default_env())
    args = cast(list[str], action_impl.build_codeclone_args(inputs))

    assert _unrecognized_cli_arguments(args) == []


def test_action_maximal_invocation_is_accepted_by_the_cli_parser() -> None:
    # Valued options are emitted only when their input is non-empty, so the
    # defaults alone cannot reach every branch. Populate all of them.
    action_impl = _load_action_impl()
    args = cast(
        list[str],
        action_impl.build_codeclone_args(_maximal_action_inputs(action_impl)),
    )

    assert _unrecognized_cli_arguments(args) == []
