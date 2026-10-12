# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The CI signal crosses the MCP launchers unchanged.

CodeClone reads CI from its own environment to choose behaviour
(``codeclone/utils/ci.py`` is the one owner of the keys and the rule). The
plugin launchers, the VS Code extension and the Claude Desktop extension start
``codeclone-mcp`` with an environment rebuilt from an allowlist, so a key
missing from that allowlist is a signal the launcher silently destroys. They
run before the package is importable and cannot import the owner's list: each
holds a copy, and this module holds every copy equal to the owner, carries each
key through a real launcher into a real process, and proves the launcher
invents nothing.
"""

from __future__ import annotations

import json
import os
import re
import runpy
import stat
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

from codeclone.utils.ci import _CI_ENV_KEYS

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SHARED_LAUNCHER = _REPO_ROOT / "plugins" / "codeclone" / "scripts" / "launch_mcp.py"
_VSCODE_SUPPORT = _REPO_ROOT / "extensions" / "vscode-codeclone" / "src" / "support.js"
_DESKTOP_LAUNCHER = (
    _REPO_ROOT / "extensions" / "claude-desktop-codeclone" / "src" / "launcher.js"
)

#: Every monorepo entrypoint an MCP host spawns. The Claude Code and Cursor
#: entrypoints delegate to the shared launcher here, and their storefront
#: releases ship its bytes (``scripts/sync_integrations.py``).
_ENTRYPOINTS = (
    "plugins/codeclone/scripts/launch_mcp.py",
    "plugins/codeclone/scripts/launch_mcp",
    "plugins/claude-code-codeclone/scripts/launch_mcp.py",
    "plugins/cursor-codeclone/scripts/launch_mcp.py",
    "scripts/launch_mcp",
)

#: Stands in for ``codeclone-mcp``: it asks the package's own CI owner what
#: the launched process sees, and names every variable it received.
_PROBE_SERVER = """\
#!{interpreter}
import json
import os
import sys

from codeclone.utils.ci import _CI_ENV_KEYS, is_ci_environment

markers = {{key: os.environ[key] for key in _CI_ENV_KEYS if key in os.environ}}
json.dump(
    {{
        "argv": sys.argv[1:],
        "ci": is_ci_environment(),
        "markers": markers,
        "names": sorted(os.environ),
    }},
    sys.stdout,
)
"""

_launcher = runpy.run_path(
    str(_SHARED_LAUNCHER), run_name="codeclone_launcher_ci_signal"
)


def _child_env(parent: Mapping[str, str]) -> dict[str, str]:
    child = _launcher["minimal_child_env"](parent, None)
    assert isinstance(child, dict)
    return child


def _declared_ci_keys(launcher: Path) -> tuple[str, ...]:
    source = launcher.read_text(encoding="utf-8")
    declaration = re.search(
        r"const SPAWN_ENV_CI_KEYS = Object\.freeze\(\[(?P<body>[^\]]*)\]\);",
        source,
    )
    assert declaration is not None, f"{launcher.name} declares no SPAWN_ENV_CI_KEYS"
    return tuple(re.findall(r'"([^"]*)"', declaration.group("body")))


@pytest.mark.parametrize("key", _CI_ENV_KEYS)
def test_every_ci_key_the_owner_reads_reaches_the_child(key: str) -> None:
    assert _child_env({"PATH": "/bin", key: "true"}) == {"PATH": "/bin", key: "true"}


@pytest.mark.parametrize("value", ["false", "", " 1 "])
def test_a_ci_value_reaches_the_child_exactly_as_the_parent_set_it(
    value: str,
) -> None:
    assert _child_env({"CI": value}) == {"CI": value}


def test_the_launcher_invents_no_ci_key() -> None:
    child = _launcher["minimal_child_env"](
        {"PATH": "/bin", "HOME": "/home/user"}, Path("/workspace/repo")
    )
    assert child == {
        "PATH": "/bin",
        "HOME": "/home/user",
        "CODECLONE_WORKSPACE_ROOT": str(Path("/workspace/repo")),
    }


def test_a_variable_outside_the_allowlist_is_still_stripped() -> None:
    child = _child_env(
        {
            "CI": "true",
            "GITLAB_CI": "true",
            "JENKINS_URL": "https://ci.example",
            "SECRET_TOKEN": "hidden",
        }
    )
    assert child == {"CI": "true"}


def test_the_python_launcher_carries_exactly_the_owner_keys() -> None:
    assert _launcher["_SPAWN_ENV_CI_KEYS"] == frozenset(_CI_ENV_KEYS)


@pytest.mark.parametrize(
    "launcher",
    [_VSCODE_SUPPORT, _DESKTOP_LAUNCHER],
    ids=["vscode", "claude-desktop"],
)
def test_each_extension_launcher_carries_exactly_the_owner_keys(
    launcher: Path,
) -> None:
    assert sorted(_declared_ci_keys(launcher)) == sorted(_CI_ENV_KEYS)


def _probe_workspace(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    server = workspace / ".venv" / "bin" / "codeclone-mcp"
    server.parent.mkdir(parents=True)
    server.write_text(
        _PROBE_SERVER.format(interpreter=sys.executable), encoding="utf-8"
    )
    server.chmod(server.stat().st_mode | stat.S_IXUSR)
    home = tmp_path / "home"
    home.mkdir()
    return workspace, home


def _launch(
    tmp_path: Path, entrypoint: str, extra: Mapping[str, str]
) -> dict[str, object]:
    workspace, home = _probe_workspace(tmp_path)
    parent = {
        "PATH": os.environ.get("PATH", os.defpath),
        "HOME": str(home),
        "CODECLONE_WORKSPACE_ROOT": str(workspace),
        **extra,
    }
    completed = subprocess.run(
        [sys.executable, str(_REPO_ROOT / entrypoint)],
        cwd=workspace,
        env=parent,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    # The probe reached the mechanism: the launcher chose the probe server.
    server = workspace / ".venv" / "bin" / "codeclone-mcp"
    assert f"source=workspaceLocal command={server.resolve()}" in completed.stderr
    report = json.loads(completed.stdout)
    assert isinstance(report, dict)
    assert report["argv"] == ["--transport", "stdio"]
    return report


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX exec of a script")
@pytest.mark.parametrize("entrypoint", _ENTRYPOINTS)
def test_ci_reaches_the_server_through_every_launcher_entrypoint(
    tmp_path: Path, entrypoint: str
) -> None:
    report = _launch(
        tmp_path,
        entrypoint,
        {"CI": "true", "GITHUB_ACTIONS": "true", "SECRET_TOKEN": "hidden"},
    )
    assert report["ci"] is True
    assert report["markers"] == {"CI": "true", "GITHUB_ACTIONS": "true"}
    names = report["names"]
    assert isinstance(names, list)
    assert "SECRET_TOKEN" not in names


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX exec of a script")
@pytest.mark.parametrize("entrypoint", _ENTRYPOINTS)
def test_without_ci_the_server_sees_none_through_every_launcher_entrypoint(
    tmp_path: Path, entrypoint: str
) -> None:
    report = _launch(tmp_path, entrypoint, {"GITLAB_CI": "true"})
    assert report["ci"] is False
    assert report["markers"] == {}


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX exec of a script")
def test_ci_false_reaches_the_server_unchanged_and_the_owner_reads_it_as_ci(
    tmp_path: Path,
) -> None:
    report = _launch(tmp_path, _ENTRYPOINTS[0], {"CI": "false"})
    assert report["markers"] == {"CI": "false"}
    assert report["ci"] is True
