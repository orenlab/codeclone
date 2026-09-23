# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

import pytest

import codeclone.surfaces.mcp.server as mcp_server

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Runs the `codeclone` entry point in a fresh interpreter without the optional
# `mcp` package and reports which MCP modules that run imported.
_IMPORT_PROBE = """
import contextlib, io, json, sys
sys.modules["mcp"] = None
sys.argv = ["codeclone", *sys.argv[1:]]
from codeclone.main import main
code = None
with contextlib.redirect_stdout(io.StringIO()):
    try:
        main()
    except SystemExit as exc:
        code = exc.code
loaded = sorted(name for name, module in sys.modules.items() if module is not None)
print(json.dumps({
    "code": code,
    "server_modules": [n for n in loaded if n.startswith("codeclone.surfaces.mcp")],
    "mcp_modules": [n for n in loaded if n == "mcp" or n.startswith("mcp.")],
}))
"""

_Outcome = tuple[object, str, str]


def _console_script(name: str) -> Callable[[], None]:
    toml = importlib.import_module(
        "tomllib" if sys.version_info >= (3, 11) else "tomli"
    )
    pyproject = toml.loads((_REPO_ROOT / "pyproject.toml").read_text("utf-8"))
    module_name, _, attribute = pyproject["project"]["scripts"][name].partition(":")
    entry: Callable[[], None] = getattr(importlib.import_module(module_name), attribute)
    return entry


def _run(
    script: str,
    argv: Sequence[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> _Outcome:
    monkeypatch.setattr(sys, "argv", [script, *argv])
    code: object = None
    try:
        _console_script(script)()
    except SystemExit as exc:
        code = exc.code
    captured = capsys.readouterr()
    return code, captured.out, captured.err


@pytest.fixture
def without_mcp_extra(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in ("mcp", "mcp.server", "mcp.server.fastmcp", "mcp.types"):
        monkeypatch.setitem(sys.modules, name, None)
    yield


def test_codeclone_mcp_flag_passes_the_remaining_argv_to_the_server_main(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    received: list[object] = []

    def _server_main(argv: Sequence[str] | None = None) -> None:
        received.append(argv)

    monkeypatch.setattr(mcp_server, "main", _server_main)

    outcomes = [
        _run("codeclone", argv, monkeypatch, capsys)
        for argv in (
            ["--mcp", "--transport", "streamable-http", "--port", "9000"],
            ["--mcp"],
        )
    ]

    assert outcomes == [(None, "", ""), (None, "", "")]
    assert received == [["--transport", "streamable-http", "--port", "9000"], []]


def test_codeclone_mcp_flag_help_is_the_codeclone_mcp_help(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    direct = _run("codeclone-mcp", ["--help"], monkeypatch, capsys)
    alias = _run("codeclone", ["--mcp", "--help"], monkeypatch, capsys)

    assert direct[0] == 0
    assert direct[1].startswith("usage: codeclone-mcp ")
    assert alias == direct


def test_codeclone_mcp_flag_refuses_like_codeclone_mcp_without_the_mcp_extra(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    without_mcp_extra: None,
) -> None:
    direct = _run("codeclone-mcp", [], monkeypatch, capsys)
    alias = _run("codeclone", ["--mcp"], monkeypatch, capsys)

    assert direct == (2, "", f"{mcp_server._MCP_INSTALL_HINT}\n")
    assert alias == direct


@pytest.mark.parametrize(
    ("argv", "loads_server"),
    [
        (["--version"], False),
        (["--help"], False),
        (["mcp", "--help"], False),
        (["--mcp", "--help"], True),
    ],
)
def test_codeclone_imports_the_mcp_server_only_for_the_mcp_flag(
    argv: list[str],
    loads_server: bool,
) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-c", _IMPORT_PROBE, *argv],
        capture_output=True,
        text=True,
        env=env,
        cwd=_REPO_ROOT,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    probe = json.loads(result.stdout)
    assert (probe["code"], probe["mcp_modules"]) == (0, [])
    assert bool(probe["server_modules"]) is loads_server
    if loads_server:
        assert "codeclone.surfaces.mcp.server" in probe["server_modules"]


def test_codeclone_mcp_word_analyses_a_directory_named_mcp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    served: list[object] = []

    def _server_main(argv: Sequence[str] | None = None) -> None:
        served.append(argv)

    monkeypatch.setattr(mcp_server, "main", _server_main)
    package = tmp_path / "mcp"
    package.mkdir()
    (package / "tool.py").write_text(
        "def handler(value):\n    return value + 1\n", "utf-8"
    )
    monkeypatch.chdir(tmp_path)

    def _analyse(root: str, label: str) -> tuple[object, object, object]:
        report = tmp_path / f"{label}.json"
        code, _, _ = _run(
            "codeclone",
            [
                root,
                "--no-progress",
                "--json",
                str(report),
                "--cache-path",
                str(tmp_path / f"{label}.cache.json"),
            ],
            monkeypatch,
            capsys,
        )
        assert served == []
        payload = json.loads(report.read_text("utf-8"))
        inventory = payload["inventory"]
        assert inventory["file_registry"]["items"] == ["tool.py"]
        return code, payload["meta"]["runtime"]["scan_root_absolute"], inventory

    word = _analyse("mcp", "word")
    path = _analyse("./mcp", "path")

    assert word[1] == str(package.resolve())
    assert word == path


@pytest.mark.parametrize(
    "argv",
    [[".", "--mcp"], ["--no-progress", "--mcp", "--transport", "stdio"]],
    ids=["after-the-root", "after-an-option"],
)
def test_codeclone_mcp_flag_launches_the_server_only_as_the_first_argument(
    argv: list[str],
) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-c", _IMPORT_PROBE, *argv],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        env=env,
        cwd=_REPO_ROOT,
        timeout=120,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    probe = json.loads(result.stdout)
    assert (probe["code"], probe["server_modules"], probe["mcp_modules"]) == (2, [], [])
    assert result.stderr.startswith("usage: codeclone [")
    assert result.stderr.splitlines()[-1].startswith(
        "CONTRACT ERROR: unrecognized arguments: --mcp"
    )
