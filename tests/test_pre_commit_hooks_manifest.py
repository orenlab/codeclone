# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import importlib
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _project() -> dict[str, object]:
    toml = importlib.import_module(
        "tomllib" if sys.version_info >= (3, 11) else "tomli"
    )
    pyproject: dict[str, object] = toml.loads(
        (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    project = pyproject["project"]
    assert isinstance(project, dict)
    return project


def _manifest_hooks() -> dict[str, dict[str, object]]:
    clientlib = importlib.import_module("pre_commit.clientlib")
    hooks: object = clientlib.load_manifest(str(_REPO_ROOT / ".pre-commit-hooks.yaml"))
    assert isinstance(hooks, list)
    return {str(hook["id"]): hook for hook in hooks if isinstance(hook, dict)}


def test_pre_commit_manifest_exposes_the_codeclone_cli_hook() -> None:
    hooks = _manifest_hooks()
    scripts = _project()["scripts"]
    assert isinstance(scripts, dict)

    assert sorted(hooks) == ["codeclone"]
    hook = hooks["codeclone"]
    assert hook["language"] == "python"
    assert scripts[hook["entry"]] == "codeclone.main:main"
    assert (hook["args"], hook["pass_filenames"], hook["types"]) == (
        [".", "--ci"],
        False,
        ["python"],
    )


def test_readme_pre_commit_example_uses_the_release_tag() -> None:
    readme = (_REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert (
        "  - repo: https://github.com/orenlab/codeclone\n"
        f"    rev: v{_project()['version']}\n"
        "    hooks:\n"
        "      - id: codeclone\n"
    ) in readme
