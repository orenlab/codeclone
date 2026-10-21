# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import importlib
import itertools
import re
import shlex
import sys
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PUBLISH_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "publish.yml"
_ACTION_FILES = (
    ".github/actions/codeclone/action.yml",
    ".github/workflows/benchmark.yml",
    ".github/workflows/codeclone.yml",
    ".github/workflows/docs.yml",
    ".github/workflows/integrations.yml",
    ".github/workflows/publish.yml",
    ".github/workflows/tests.yml",
    ".github/workflows/validation-corpus.yml",
)
_ACTION_FILE_PATTERNS = (
    ".github/actions/*/action.yml",
    ".github/actions/*/action.yaml",
    ".github/workflows/*.yml",
    ".github/workflows/*.yaml",
)
_LOCAL_ACTION_PREFIX = "./"
_ACTION_METADATA_NAMES = ("action.yml", "action.yaml")
_USES_LINE = re.compile(r"^\s*(?:-\s+)?uses:\s+(?P<ref>\S+)(?P<comment>.*)$")
_FULL_SHA_REF = re.compile(r"^[\w.-]+/[\w.-]+(?:/[\w./-]+)?@[0-9a-f]{40}$")
_RELEASE_COMMENT = re.compile(r"^ # v\d+\.\d+\.\d+$")
_WITH_REQUIREMENT = re.compile(r"--with\s+(\S+)")
_BUILD_FRONTEND = ("python", "-m", "build")
_BUILD_FRONTEND_LINE = re.compile(r"\bpython\s+-m\s+build\b")
_SETUP_UV_ACTION = "astral-sh/setup-uv@"


def _locked_versions() -> dict[str, str]:
    toml = importlib.import_module(
        "tomllib" if sys.version_info >= (3, 11) else "tomli"
    )
    lock: dict[str, object] = toml.loads(
        (_REPO_ROOT / "uv.lock").read_text(encoding="utf-8")
    )
    packages = lock["package"]
    assert isinstance(packages, list)
    return {
        str(package["name"]): str(package["version"])
        for package in packages
        if isinstance(package, dict) and "version" in package
    }


def _is_pinned(ref: str, comment: str) -> bool:
    if ref.startswith(_LOCAL_ACTION_PREFIX):
        # A local action runs from the checked-out commit itself and takes no
        # ref: that commit pins it, provided the commit carries the action.
        action_dir = _REPO_ROOT / ref
        return any((action_dir / name).is_file() for name in _ACTION_METADATA_NAMES)
    return (
        _FULL_SHA_REF.match(ref) is not None
        and _RELEASE_COMMENT.match(comment) is not None
    )


def test_pinned_action_files_cover_every_workflow_and_composite_action() -> None:
    discovered = sorted(
        path.relative_to(_REPO_ROOT).as_posix()
        for pattern in _ACTION_FILE_PATTERNS
        for path in _REPO_ROOT.glob(pattern)
    )

    assert discovered == list(_ACTION_FILES)


@pytest.mark.parametrize("relative_path", _ACTION_FILES)
def test_every_action_is_pinned_to_a_full_commit_sha(relative_path: str) -> None:
    uses_lines = [
        line
        for line in (_REPO_ROOT / relative_path)
        .read_text(encoding="utf-8")
        .splitlines()
        if "uses:" in line
    ]
    assert uses_lines, f"{relative_path} declares no actions"

    unpinned = []
    for line in uses_lines:
        match = _USES_LINE.match(line)
        if match is None or not _is_pinned(match.group("ref"), match.group("comment")):
            unpinned.append(line.strip())

    assert unpinned == []


def test_publish_workflow_pins_build_tools_to_locked_versions() -> None:
    requested: dict[str, tuple[str, str]] = {}
    for requirement in _WITH_REQUIREMENT.findall(
        _PUBLISH_WORKFLOW.read_text(encoding="utf-8")
    ):
        name, separator, version = requirement.partition("==")
        requested[name] = (separator, version)
    locked = _locked_versions()

    assert {"build", "twine"} <= requested.keys()
    assert {
        name: pin
        for name, pin in sorted(requested.items())
        if pin != ("==", locked.get(name, ""))
    } == {}


def _publish_job_steps() -> dict[str, list[dict[str, object]]]:
    document: object = yaml.safe_load(_PUBLISH_WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    jobs = document.get("jobs")
    assert isinstance(jobs, dict)
    steps_by_job: dict[str, list[dict[str, object]]] = {}
    for name, job in jobs.items():
        assert isinstance(job, dict)
        steps = job.get("steps", [])
        assert isinstance(steps, list)
        steps_by_job[str(name)] = [step for step in steps if isinstance(step, dict)]
    return steps_by_job


def _build_frontend_arguments(script: str) -> list[list[str]]:
    """The arguments after every ``python -m build`` a ``run`` script executes."""
    found: list[list[str]] = []
    width = len(_BUILD_FRONTEND)
    for line in script.splitlines():
        if _BUILD_FRONTEND_LINE.search(line) is None:
            continue
        tokens = shlex.split(line, comments=True)
        found.extend(
            tokens[index + width :]
            for index in range(len(tokens) - width + 1)
            if tuple(tokens[index : index + width]) == _BUILD_FRONTEND
        )
    return found


def _selects_uv_installer(arguments: list[str]) -> bool:
    return "--installer=uv" in arguments or any(
        flag == "--installer" and value == "uv"
        for flag, value in itertools.pairwise(arguments)
    )


def test_publish_build_env_is_installed_by_uv_not_by_the_bundled_pip() -> None:
    """The release build never reaches PyPI through the interpreter's own pip.

    ``python -m build`` installs its isolated build requirements with pip by
    default, and the ``uv run`` environment of the build job carries no pip, so
    build falls back to ``venv(with_pip=True)``: the ensurepip wheel of the
    runner's CPython.  In October 2026 that pip (26.2.1 on CPython 3.14.8)
    vendored a certifi that still trusted the eMudhra chains revoked for key
    compromise, and setuptools and wheel were fetched through it.
    ``--installer uv`` hands that install to the uv binary ``setup-uv`` put on
    PATH, so the selection and the provisioning are pinned together: a build
    that asks for uv in a job that never installed it would fail, not fall back.
    """
    builds: list[tuple[str, list[str], bool]] = []
    for job, steps in _publish_job_steps().items():
        uv_provisioned = False
        for step in steps:
            if str(step.get("uses", "")).startswith(_SETUP_UV_ACTION):
                uv_provisioned = True
            script = step.get("run")
            if isinstance(script, str):
                builds.extend(
                    (job, arguments, uv_provisioned)
                    for arguments in _build_frontend_arguments(script)
                )

    assert builds, "publish.yml no longer runs `python -m build`"
    assert [
        (job, " ".join(arguments), uv_provisioned)
        for job, arguments, uv_provisioned in builds
        if not (uv_provisioned and _selects_uv_installer(arguments))
    ] == []
