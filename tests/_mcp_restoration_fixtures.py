# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A temporary repository whose MCP runs are published, registered and found
again -- spelled once for the restoration suites.

Every store is the root's own (``.codeclone/db/runs.sqlite3`` under a
``tmp_path`` root, the MCP write boundary), the rollout and the serving switch
are set by the test's ``monkeypatch``, and the registry is read with plain
``sqlite3`` -- never a production store, never the hosting checkout's.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests._run_store_paths import name_run_store, run_store_service_path

#: A pyproject that switches the semantic-authority lane on, so a run carries
#: a measured authority-candidate population the store can state.
AUTHORITY_LANE_ON = "[tool.codeclone]\nsemantic_authority = true\n"


def git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@e.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@e.com",
        },
    )


def module_source(functions: int, *, tag: str = "") -> str:
    """A module of ``functions`` small functions; ``tag`` varies their body,
    so two tags are two analyses of the same paths."""
    return "".join(
        f"def f{n}(x: int) -> int:\n    return x * {n}{tag}\n\n"
        for n in range(functions)
    )


@dataclass(frozen=True, slots=True)
class Repo:
    root: Path
    store: Path

    def write(self, functions: int, *, tag: str = "") -> None:
        self.root.joinpath("pkg", "m.py").write_text(
            module_source(functions, tag=tag), "utf-8"
        )

    def rows(
        self, sql: str, params: tuple[object, ...] = ()
    ) -> list[tuple[object, ...]]:
        with closing(sqlite3.connect(self.store)) as raw:
            return list(raw.execute(sql, params))


def make_repo(tmp_path: Path, *, authority: bool = False) -> Repo:
    """A committed git repository under ``tmp_path`` with one package."""
    root = tmp_path / "repo"
    root.joinpath("pkg").mkdir(parents=True)
    root.joinpath("pkg", "__init__.py").write_text("", "utf-8")
    root.joinpath("pkg", "m.py").write_text(module_source(3), "utf-8")
    root.joinpath("README.md").write_text("stable\n", "utf-8")
    if authority:
        root.joinpath("pyproject.toml").write_text(AUTHORITY_LANE_ON, "utf-8")
    for args in (("init", "-q"), ("add", "."), ("commit", "-qm", "init")):
        git(root, *args)
    return Repo(root=root, store=run_store_service_path(root))


def enable_store(monkeypatch: pytest.MonkeyPatch, repo: Repo) -> None:
    """The rollout on (CI neutralised), the root's own store named the way a
    user names it, and the migrated readings served from the store."""
    monkeypatch.setenv("CODECLONE_RUN_STORE_ENABLED", "1")
    monkeypatch.setenv("CODECLONE_RUN_STORE_FORCE", "1")
    monkeypatch.setenv("CODECLONE_SERVE_FROM", "run_store")
    name_run_store(monkeypatch, repo.store)


__all__ = [
    "AUTHORITY_LANE_ON",
    "Repo",
    "enable_store",
    "git",
    "make_repo",
    "module_source",
]
