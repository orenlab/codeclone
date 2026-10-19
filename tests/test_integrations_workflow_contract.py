# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Configuration contract of the npm jobs in ``.github/workflows/integrations.yml``.

CI installs the Node extensions under two separate contracts, and one does not
replace the other:

* configuration, pinned here statically: both npm jobs install with exactly
  ``npm ci --ignore-scripts --include=optional``, check out without persisted
  credentials, the VS Code job runs the esbuild gate between the install and
  the build, and the token stays read-only.  The YAML is parsed; nothing runs.
* environment: ``extensions/vscode-codeclone/test/verifyToolchain.js`` proves on
  the runner that the locked esbuild is actually installed and works.  It runs
  in CI (or in the container sandbox), never from this module.

``--ignore-scripts`` stops npm lifecycle scripts during the install, and that
is all it does: the explicit ``npm run check`` and ``npm test`` steps still run
dependency code.  Nothing here claims those steps are safe.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Mapping
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "integrations.yml"

_VSCODE_JOB = "vscode-extension"
_NPM_JOBS = (_VSCODE_JOB, "claude-desktop-bundle")
_PINNED_INSTALL = "npm ci --ignore-scripts --include=optional"
_TOOLCHAIN_GATE = "node test/verifyToolchain.js linux-x64"
_TOOLCHAIN_GATE_SCRIPT = Path(shlex.split(_TOOLCHAIN_GATE)[1])
_VSCODE_BUILD = "npm run check"
_CHECKOUT_ACTION = "actions/checkout@"
_READ_ONLY_TOKEN = {"contents": "read"}

# npm subcommands that install packages or rerun their lifecycle scripts, with
# every alias npm accepts for them.  Over-matching only fails loudly.
_NPM_INSTALL_SUBCOMMANDS = frozenset(
    {
        "ci",
        "clean-install",
        "ic",
        "install-clean",
        "isntall-clean",
        "install",
        "add",
        "i",
        "in",
        "ins",
        "inst",
        "insta",
        "instal",
        "isnt",
        "isnta",
        "isntal",
        "isntall",
        "install-test",
        "it",
        "install-ci-test",
        "cit",
        "clean-install-test",
        "sit",
        "rebuild",
        "rb",
    }
)
_SHELL_SEPARATORS = frozenset({"&&", "||", ";", "|", "&"})
_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

_Node = Mapping[object, object]
_Command = tuple[str, ...]


def _mapping(value: object, what: str) -> _Node:
    assert isinstance(value, dict), f"{what} is not a mapping: {value!r}"
    return value


def _workflow() -> _Node:
    document: object = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    return _mapping(document, str(_WORKFLOW.relative_to(_REPO_ROOT)))


def _jobs(workflow: _Node) -> _Node:
    return _mapping(workflow.get("jobs"), "jobs")


def _steps(jobs: _Node, name: object) -> list[_Node]:
    job = _mapping(jobs.get(name), f"job {name!r}")
    steps = job.get("steps")
    assert isinstance(steps, list) and steps, f"job {name!r} declares no steps"
    return [_mapping(step, f"a step of job {name!r}") for step in steps]


def _commands(step: _Node) -> list[_Command]:
    """Every simple shell command a ``run`` step executes, in order."""
    script = step.get("run")
    if not isinstance(script, str):
        return []
    commands: list[_Command] = []
    for line in script.splitlines():
        lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        current: list[str] = []
        for token in lexer:
            if token in _SHELL_SEPARATORS:
                if current:
                    commands.append(tuple(current))
                current = []
            else:
                current.append(token)
        if current:
            commands.append(tuple(current))
    return commands


def _program(command: _Command) -> _Command:
    """The command without its leading ``NAME=value`` environment assignments."""
    index = 0
    while index < len(command) and _ENV_ASSIGNMENT.match(command[index]):
        index += 1
    return command[index:]


def _is_npm_install(command: _Command) -> bool:
    program = _program(command)
    return (
        bool(program)
        and program[0] == "npm"
        and any(token in _NPM_INSTALL_SUBCOMMANDS for token in program[1:])
    )


def _rendered(command: _Command) -> str:
    return " ".join(command)


def _kind(command: _Command) -> str:
    if _is_npm_install(command):
        return "install"
    if _rendered(command) == _TOOLCHAIN_GATE:
        return "gate"
    return "code"


def _install_commands(jobs: _Node, name: object) -> list[str]:
    return [
        _rendered(command)
        for step in _steps(jobs, name)
        for command in _commands(step)
        if _is_npm_install(command)
    ]


def _trigger_events(workflow: _Node) -> set[str]:
    # PyYAML follows YAML 1.1, where a bare ``on`` key loads as boolean True.
    triggers = workflow.get("on", workflow.get(True))
    return {str(event) for event in _mapping(triggers, "the workflow triggers")}


@pytest.mark.parametrize("job_name", _NPM_JOBS)
def test_npm_job_installs_without_lifecycle_scripts_keeping_optional_deps(
    job_name: str,
) -> None:
    assert _install_commands(_jobs(_workflow()), job_name) == [_PINNED_INSTALL]


def test_every_npm_install_in_the_workflow_is_the_pinned_command() -> None:
    jobs = _jobs(_workflow())
    unpinned = sorted(
        f"{name}: {command}"
        for name in jobs
        for command in _install_commands(jobs, name)
        if command != _PINNED_INSTALL
    )

    assert unpinned == []


@pytest.mark.parametrize("job_name", _NPM_JOBS)
def test_npm_job_checkout_does_not_persist_credentials(job_name: str) -> None:
    checkouts = [
        step
        for step in _steps(_jobs(_workflow()), job_name)
        if str(step.get("uses", "")).startswith(_CHECKOUT_ACTION)
    ]
    assert checkouts, f"job {job_name!r} has no {_CHECKOUT_ACTION} step"

    persisted = [
        _mapping(step.get("with", {}), "checkout inputs").get("persist-credentials")
        for step in checkouts
    ]
    assert persisted == [False] * len(checkouts)


def test_vscode_job_runs_the_esbuild_gate_after_the_install_and_before_the_build() -> (
    None
):
    sequence = [
        (_kind(command), _rendered(command))
        for step in _steps(_jobs(_workflow()), _VSCODE_JOB)
        for command in _commands(step)
    ]
    kinds = [label for label, _command in sequence]
    assert "install" in kinds, sequence

    after_install = sequence[kinds.index("install") :]
    assert [label for label, _command in after_install[:2]] == ["install", "gate"], (
        sequence
    )
    assert _VSCODE_BUILD in [command for _label, command in after_install[2:]], sequence


def test_vscode_esbuild_gate_runs_the_tracked_script_from_its_directory() -> None:
    jobs = _jobs(_workflow())
    job = _mapping(jobs.get(_VSCODE_JOB), f"job {_VSCODE_JOB!r}")
    defaults = _mapping(job.get("defaults", {}), "defaults")
    default_directory = _mapping(defaults.get("run", {}), "defaults.run").get(
        "working-directory", "."
    )
    directories = [
        str(step.get("working-directory", default_directory))
        for step in _steps(jobs, _VSCODE_JOB)
        if _TOOLCHAIN_GATE in map(_rendered, _commands(step))
    ]
    assert directories, f"job {_VSCODE_JOB!r} never runs {_TOOLCHAIN_GATE!r}"

    missing = [
        directory
        for directory in directories
        if not (_REPO_ROOT / directory / _TOOLCHAIN_GATE_SCRIPT).is_file()
    ]
    assert missing == []


def test_workflow_token_is_read_only() -> None:
    workflow = _workflow()
    jobs = {
        str(name): _mapping(spec, f"job {name!r}")
        for name, spec in _jobs(workflow).items()
    }
    job_overrides = {
        name: job["permissions"] for name, job in jobs.items() if "permissions" in job
    }

    assert (workflow.get("permissions"), job_overrides) == (_READ_ONLY_TOKEN, {})


def test_workflow_never_runs_on_pull_request_target() -> None:
    assert "pull_request_target" not in _trigger_events(_workflow())
