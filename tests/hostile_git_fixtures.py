# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Temporary git repositories whose own git state names a program.

Each repository is built under a pytest temporary directory. The only program
any of them names is a marker: a shell script that appends one line to a file
in the test's own marker directory and, where git expects output, prints the
smallest harmless answer. A test reads which markers appeared; nothing else
is ever executed.

The hostile wiring is armed only after the repository is built and its dirt
is laid down, so the setup's own ``git`` calls can never fire it. A twin
copied before arming is the clean control: same files, same index, same
mtimes, no program named. A copy taken after arming is the positive control:
plain ``git`` run there proves the mechanism was live.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import pytest

#: Tracked files are dated well before the index, so git reads them as clean
#: candidates whose stat data it trusts, not as racily clean entries.
_PAST_MTIME = 1_600_000_000

_SETUP_IDENTITY: Mapping[str, str] = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@e.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@e.invalid",
}


def isolate_git_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point ``HOME`` at an empty directory and drop every inherited ``GIT_*``.

    Global configuration then comes only from what a test writes into the
    returned home, and system configuration is off; nothing from the machine
    running the suite can arm or disarm a mechanism.
    """

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    for name in tuple(os.environ):
        if name.startswith("GIT_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    return home


def setup_git(
    repo: Path, *args: str, stdin: bytes | None = None
) -> subprocess.CompletedProcess[bytes]:
    """Plain ``git`` for building fixtures; never used by the code under test."""

    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        input=stdin,
        env={**os.environ, **_SETUP_IDENTITY},
    )


def marker_program(path: Path, markers: Path, name: str, body: str = "") -> str:
    """Write a program that records its own run as ``<markers>/<name>.marker``."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"#!/bin/sh\necho \"{name} $*\" >> '{markers / name}.marker'\n{body}\n",
        "utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(path)


def git_dir_digest(root: Path) -> dict[str, str]:
    """sha256 of every file under ``root/.git``: a write anywhere shows up."""

    git_dir = root / ".git"
    return {
        path.relative_to(git_dir).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(git_dir.rglob("*"))
        if path.is_file()
    }


@dataclass(frozen=True, slots=True)
class FixtureRepo:
    root: Path
    markers: Path
    programs: Path

    def fired(self) -> list[str]:
        return sorted(path.stem for path in self.markers.glob("*.marker"))

    def clear_markers(self) -> None:
        for path in self.markers.glob("*.marker"):
            path.unlink()

    def set_config(self, key: str, value: str, *, scope: str = "--local") -> None:
        setup_git(self.root, "config", scope, key, value)

    def program(self, name: str, body: str = "") -> str:
        return marker_program(self.programs / f"{name}.sh", self.markers, name, body)


def build_repo(
    base: Path,
    *,
    attributes: str = "",
    forged_signature: bool = False,
    split_index: bool = False,
) -> FixtureRepo:
    """One committed repository with every kind of dirt the callers read.

    ``a.py`` is modified with the same length (git must read its content),
    ``b.py`` is touched without a change (stat-only dirt: the one shape that
    makes ``git status`` and ``git diff`` refresh and rewrite the index),
    ``c.py`` has a staged modification, ``staged.py`` is a staged addition and
    ``untracked.py`` is untracked.
    """

    root, markers, programs = base / "repo", base / "markers", base / "programs"
    for directory in (root, markers, programs):
        directory.mkdir(parents=True)
    _commit_initial_tree(root, attributes=attributes, split_index=split_index)
    if forged_signature:
        _forge_signature_on_head(root)
    _lay_dirt(root)
    return FixtureRepo(root=root, markers=markers, programs=programs)


def _commit_initial_tree(root: Path, *, attributes: str, split_index: bool) -> None:
    setup_git(root, "init", "-q")
    if split_index:
        setup_git(root, "config", "core.splitIndex", "true")
        setup_git(root, "config", "splitIndex.maxPercentChange", "0")
    for name in ("a", "b", "c"):
        (root / f"{name}.py").write_text(f"def {name}(x):\n    return x + 1\n", "utf-8")
    if attributes:
        (root / ".gitattributes").write_text(attributes, "utf-8")
    setup_git(root, "add", "-A")
    setup_git(root, "commit", "-qm", "init")


def _lay_dirt(root: Path) -> None:
    (root / "c.py").write_text("def c(x):\n    return x + 3\n", "utf-8")
    setup_git(root, "add", "c.py")
    for name in ("a", "b", "c"):
        os.utime(root / f"{name}.py", (_PAST_MTIME, _PAST_MTIME))
    setup_git(root, "update-index", "--really-refresh")
    (root / "a.py").write_text("def a(x):\n    return x + 2\n", "utf-8")
    (root / "staged.py").write_text("def s():\n    return 1\n", "utf-8")
    setup_git(root, "add", "staged.py")
    (root / "untracked.py").write_text("x = 1\n", "utf-8")
    os.utime(root / "b.py", None)


def _forge_signature_on_head(root: Path) -> None:
    raw = setup_git(root, "cat-file", "commit", "HEAD").stdout.decode("utf-8")
    header, _, message = raw.partition("\n\n")
    forged = (
        header
        + "\ngpgsig -----BEGIN PGP SIGNATURE-----\n \n fake\n"
        + " -----END PGP SIGNATURE-----\n\n"
        + message
    )
    object_id = (
        setup_git(
            root, "hash-object", "-t", "commit", "-w", "--stdin", stdin=forged.encode()
        )
        .stdout.decode("ascii")
        .strip()
    )
    setup_git(root, "update-ref", "HEAD", object_id)


def drop_object(repo: FixtureRepo, revision: str) -> str:
    """Delete one loose object and return its id: a promisor remote is then
    the only way git can still answer for it."""

    object_id = setup_git(repo.root, "rev-parse", revision).stdout.decode().strip()
    (repo.root / ".git" / "objects" / object_id[:2] / object_id[2:]).unlink()
    return object_id


def arm_promisor_remote(repo: FixtureRepo) -> None:
    """Declare a promisor remote whose transport is a program of the
    repository's choosing: reading a missing object makes git run it."""

    program = repo.program("lazy_fetch")
    repo.set_config("core.repositoryformatversion", "1")
    repo.set_config("extensions.partialClone", "origin")
    repo.set_config("remote.origin.url", f"ext::{program} %S")
    repo.set_config("remote.origin.promisor", "true")
    repo.set_config("protocol.ext.allow", "always")


def twin_copy(repo: FixtureRepo, base: Path) -> FixtureRepo:
    """A byte-and-mtime copy of ``repo`` (index included) under ``base``."""

    root, markers = base / "repo", base / "markers"
    shutil.copytree(repo.root, root, symlinks=True)
    markers.mkdir(parents=True)
    return FixtureRepo(root=root, markers=markers, programs=base / "programs")


#: Clean populations: no git state names a program. ``stat_dirt`` is the one
#: whose answer a reader that writes the index changes for the next reader.
CLEAN_POPULATIONS = ("clean", "dirt", "stat_dirt")


def build_population(base: Path, population: str) -> FixtureRepo:
    repo = build_repo(base)
    if population == "dirt":
        os.utime(repo.root / "b.py", (_PAST_MTIME, _PAST_MTIME))
    elif population == "clean":
        setup_git(repo.root, "reset", "-q")
        setup_git(repo.root, "checkout", "-q", "HEAD", "--", "a.py", "c.py")
        for name in ("staged.py", "untracked.py"):
            (repo.root / name).unlink()
        for name in ("a", "b", "c"):
            os.utime(repo.root / f"{name}.py", (_PAST_MTIME, _PAST_MTIME))
        setup_git(repo.root, "update-index", "--really-refresh")
    return repo


def install_legacy_git(monkeypatch: pytest.MonkeyPatch) -> None:
    """Put back the call shape every caller used before the owner: plain
    ``git`` with the inherited environment, ``check=True``."""

    from codeclone.utils import git_process

    def run_git_bytes(
        root: Path,
        args: list[str],
        *,
        timeout: float,
        input_bytes: bytes | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            capture_output=True,
            input=input_bytes,
            timeout=timeout,
        )

    def run_git_text(
        root: Path, args: list[str], *, timeout: float
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    monkeypatch.setattr(git_process, "run_git_bytes", run_git_bytes)
    monkeypatch.setattr(git_process, "run_git_text", run_git_text)


def plain_git_fires(
    armed: FixtureRepo,
    control: FixtureRepo,
    args: tuple[str, ...],
    marker: str,
    *,
    stdin: bytes | None = None,
) -> bool:
    """Positive control: plain ``git`` in an armed copy runs the marker
    (the copy's configuration names the armed repository's programs)."""

    armed.clear_markers()
    subprocess.run(
        ["git", *args],
        cwd=control.root,
        capture_output=True,
        input=stdin,
        check=False,
    )
    return marker in armed.fired()


__all__ = [
    "CLEAN_POPULATIONS",
    "FixtureRepo",
    "arm_promisor_remote",
    "build_population",
    "build_repo",
    "drop_object",
    "git_dir_digest",
    "install_legacy_git",
    "isolate_git_environment",
    "marker_program",
    "plain_git_fires",
    "setup_git",
    "twin_copy",
]
