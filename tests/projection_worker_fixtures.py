# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A hostile analysed repository for the projection-worker isolation tests.

The repository opts its own projection rebuilds in through ``pyproject.toml``
and carries a top-level module named like a dependency every
``codeclone.main`` start imports. That module only appends one line to a
marker file in the test's temporary directory, then hands the importer the
real dependency, so a worker that imports it keeps working and the marker is
the only trace -- the shape a silent attack would take.

Every path these helpers touch lies under the test's ``tmp_path``; the
sandbox records every SQLite database the test process opens so a test can
refuse any store outside it.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import pytest

from codeclone.audit.schema import ensure_schema
from codeclone.audit.validation import DEFAULT_AUDIT_PATH, resolve_audit_path

from .memory_fixtures import cli_memory_repo

# Imported by every ``python -m codeclone.main`` start (measured: a module of
# this name in the working directory runs before ``--version`` prints).
SHADOWED_DEPENDENCY = "orjson"

_SHADOW_SOURCE = """\
import importlib
import os
import sys

with open({marker!r}, "a", encoding="utf-8") as _handle:
    _handle.write("shadow executed; cwd=%s\\n" % os.getcwd())
_here = os.path.dirname(os.path.abspath(__file__))
del sys.modules[__name__]
_saved = list(sys.path)
sys.path[:] = [p for p in sys.path if os.path.abspath(p or os.curdir) != _here]
try:
    importlib.import_module(__name__)
finally:
    sys.path[:] = _saved
"""

_OPT_IN_PYPROJECT = (
    "[project]\nname = 'victim'\nversion = '0'\n\n"
    "[tool.codeclone.memory]\nprojection_rebuild_policy = 'enqueue_when_stale'\n"
)

# A runner's interpreter-path switches would hide the shadow from the
# unprotected control start or add a directory to the worker's import path;
# CI markers would switch the projection rebuild off before any spawn.
_RUNNER_PATH_ENV = ("PYTHONPATH", "PYTHONSAFEPATH")
_CI_ENV = ("CI", "GITHUB_ACTIONS", "BUILDKITE", "TF_BUILD", "TEAMCITY_VERSION")


@dataclass(frozen=True, slots=True)
class HostileRepo:
    root: Path
    marker: Path

    def shadow_runs(self) -> list[str]:
        if not self.marker.exists():
            return []
        return self.marker.read_text(encoding="utf-8").splitlines()


@dataclass(frozen=True, slots=True)
class RecordedSpawn:
    argv: tuple[str, ...]
    cwd: str | None
    env: dict[str, str] | None
    process: subprocess.Popen[Any]

    @property
    def is_worker(self) -> bool:
        return "codeclone.main" in self.argv and "run-once" in self.argv


@contextmanager
def hostile_repo(tmp_path: Path) -> Iterator[HostileRepo]:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "pyproject.toml").write_text(_OPT_IN_PYPROJECT, encoding="utf-8")
    with cli_memory_repo(tmp_path, with_draft=False) as (repo_root, _project, _store):
        audit_db = resolve_audit_path(root_path=repo_root, value=DEFAULT_AUDIT_PATH)
        audit_db.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(audit_db))
        try:
            ensure_schema(conn)
            conn.commit()
        finally:
            conn.close()
        marker = tmp_path / "shadow-marker.txt"
        (repo_root / f"{SHADOWED_DEPENDENCY}.py").write_text(
            _SHADOW_SOURCE.format(marker=str(marker)), encoding="utf-8"
        )
        yield HostileRepo(root=repo_root.resolve(), marker=marker)


def sandbox_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    """Point every per-user location at ``tmp_path``, drop the runner's CI,
    interpreter-path and CodeClone switches, and return the live list of
    SQLite databases this process opens from here on."""

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(home / ".cache"))
    dropped = [
        name
        for name in os.environ
        if name.startswith("CODECLONE_") or name in _RUNNER_PATH_ENV or name in _CI_ENV
    ]
    for name in dropped:
        monkeypatch.delenv(name)
    opened: list[str] = []
    current_connect = sqlite3.connect

    def _recording_connect(database: Any, *args: Any, **kwargs: Any) -> Any:
        opened.append(os.fsdecode(database))
        return current_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", _recording_connect)
    return opened


def databases_outside(opened: list[str], tmp_path: Path) -> list[str]:
    """Every opened file database that does not live under ``tmp_path``."""

    base = tmp_path.resolve()
    outside: list[str] = []
    for database in opened:
        location = database
        if location in {"", ":memory:"}:
            continue
        if location.startswith("file:"):
            location = unquote(location[len("file:") :].split("?", 1)[0])
            location = location.removeprefix("//")
        if not Path(location).resolve().is_relative_to(base):
            outside.append(database)
    return sorted(outside)


@contextmanager
def recorded_spawns(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[RecordedSpawn]]:
    """Every process started through ``subprocess.Popen`` inside the block,
    with the argv, working directory and environment it was started with.
    The processes are real; the caller waits for the worker it needs."""

    spawned: list[RecordedSpawn] = []
    real_popen = subprocess.Popen

    def _recording_popen(*args: Any, **kwargs: Any) -> subprocess.Popen[Any]:
        process: subprocess.Popen[Any] = real_popen(*args, **kwargs)
        command = args[0] if args else kwargs["args"]
        cwd = kwargs.get("cwd")
        env = kwargs.get("env")
        spawned.append(
            RecordedSpawn(
                argv=tuple(os.fsdecode(part) for part in command),
                cwd=None if cwd is None else os.fsdecode(cwd),
                env=dict(env) if env is not None else None,
                process=process,
            )
        )
        return process

    with monkeypatch.context() as patch:
        patch.setattr(subprocess, "Popen", _recording_popen)
        yield spawned


def only_worker(spawned: list[RecordedSpawn]) -> RecordedSpawn:
    workers = [spawn for spawn in spawned if spawn.is_worker]
    assert len(workers) == 1, [spawn.argv for spawn in spawned]
    return workers[0]


__all__ = [
    "SHADOWED_DEPENDENCY",
    "HostileRepo",
    "RecordedSpawn",
    "databases_outside",
    "hostile_repo",
    "only_worker",
    "recorded_spawns",
    "sandbox_environment",
]
