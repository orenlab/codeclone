# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""``git diff`` on an analysed repository runs no program that repository names.

Changed-path review (CLI ``--diff-against``, MCP ``analyze_changed_paths``)
runs ``git diff --name-only REF --`` inside a repository whose ``.git`` may
come from someone else (an archive, a shared volume). Its configuration can
name a filesystem monitor, hooks and filter drivers that git runs on its own,
and an inherited ``GIT_DIR`` can point the question at another repository.
Each test plants a marker program and proves, with a plain ``git`` call on the
same repository as the positive control, that the probe reaches it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

import codeclone.surfaces.cli.changed_scope as cli_changed_scope
import codeclone.surfaces.mcp._session_shared as mcp_shared_mod

pytestmark = [
    pytest.mark.skipif(shutil.which("git") is None, reason="git is required"),
    pytest.mark.skipif(os.name == "nt", reason="marker programs are shell scripts"),
]

ChangedPaths = Callable[[Path, str], tuple[str, ...]]


@pytest.fixture(autouse=True)
def _hermetic_git_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No system or user git configuration reaches the code under test."""

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def _cli_changed_paths(root: Path, ref: str) -> tuple[str, ...]:
    return cli_changed_scope._git_diff_changed_paths(root_path=root, git_diff_ref=ref)


def _mcp_changed_paths(root: Path, ref: str) -> tuple[str, ...]:
    return mcp_shared_mod._git_diff_lines_payload(root_path=root, git_diff_ref=ref)


_SURFACES = (
    pytest.param(_cli_changed_paths, id="cli-diff-against"),
    pytest.param(_mcp_changed_paths, id="mcp-analyze-changed-paths"),
)


def _clean_git_env() -> dict[str, str]:
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    return env


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        env=_clean_git_env(),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )


def _repository(path: Path) -> Path:
    _git(path.parent, "init", "-q", str(path))
    _git(path, "config", "user.email", "probe@example.invalid")
    _git(path, "config", "user.name", "probe")
    _git(path, "config", "commit.gpgsign", "false")
    (path / "a.py").write_text("x = 1\n", encoding="utf-8")
    _git(path, "add", "a.py")
    _git(path, "commit", "-qm", "one")
    (path / "b.py").write_text("y = 2\n", encoding="utf-8")
    _git(path, "add", "b.py")
    _git(path, "commit", "-qm", "two")
    return path


def _marker_program(path: Path, marker: Path, *, passes_stdin: bool) -> str:
    body = "exec cat" if passes_stdin else "exit 0"
    path.write_text(
        f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{marker}"\n{body}\n', encoding="utf-8"
    )
    path.chmod(0o755)
    return str(path)


def _plant_clean_filter(repo: Path, tmp_path: Path, driver: str, marker: Path) -> None:
    """Name a clean filter in the repository's own config and attributes."""

    (repo / ".git" / "info" / "attributes").write_text(
        f"*.py filter={driver}\n", encoding="utf-8"
    )
    _git(
        repo,
        "config",
        f"filter.{driver}.clean",
        _marker_program(tmp_path / "filter.sh", marker, passes_stdin=True),
    )


def _plain_name_only(repo: Path) -> list[str]:
    """The control: the unhardened call this module replaced."""

    completed = subprocess.run(
        ["git", "diff", "--name-only", "HEAD~1", "--"],
        cwd=repo,
        env=_clean_git_env(),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return sorted(line for line in completed.stdout.splitlines() if line)


@pytest.mark.parametrize("changed_paths", _SURFACES)
def test_filesystem_monitor_named_by_the_repository_does_not_run(
    tmp_path: Path, changed_paths: ChangedPaths
) -> None:
    repo = _repository(tmp_path / "repo")
    marker = tmp_path / "FSMONITOR_RAN"
    _git(
        repo,
        "config",
        "core.fsmonitor",
        _marker_program(tmp_path / "fsmonitor.sh", marker, passes_stdin=False),
    )

    assert changed_paths(repo, "HEAD~1") == ("b.py",)
    assert not marker.exists()

    # Positive control: the same repository runs it under a plain git diff.
    _plain_name_only(repo)
    assert marker.exists()


@pytest.mark.parametrize("changed_paths", _SURFACES)
@pytest.mark.parametrize("dirt", ["content", "stat-only"])
def test_clean_filter_named_by_the_repository_does_not_run(
    tmp_path: Path, changed_paths: ChangedPaths, dirt: str
) -> None:
    repo = _repository(tmp_path / "repo")
    marker = tmp_path / "FILTER_RAN"
    _plant_clean_filter(repo, tmp_path, "planted", marker)
    expected: tuple[str, ...]
    if dirt == "content":
        (repo / "a.py").write_text("x = 3\n", encoding="utf-8")
        expected = ("a.py", "b.py")
    else:
        os.utime(repo / "a.py", (1_577_840_000, 1_577_840_000))
        expected = ("b.py",)

    assert changed_paths(repo, "HEAD~1") == expected
    assert not marker.exists()

    # Positive control on fresh stat dirt: the hardened call may have
    # refreshed the index entry the plain call would otherwise re-hash.
    os.utime(repo / "a.py", (1_577_850_000, 1_577_850_000))
    _plain_name_only(repo)
    assert marker.exists()


@pytest.mark.parametrize("changed_paths", _SURFACES)
def test_post_index_change_hook_of_the_repository_does_not_run(
    tmp_path: Path, changed_paths: ChangedPaths
) -> None:
    # With stat-only dirt, ``git diff`` refreshes and rewrites the index even
    # under --no-optional-locks, and git then runs post-index-change.
    repo = _repository(tmp_path / "repo")
    marker = tmp_path / "HOOK_RAN"
    _marker_program(
        repo / ".git" / "hooks" / "post-index-change", marker, passes_stdin=False
    )
    os.utime(repo / "a.py", (1_577_840_000, 1_577_840_000))

    assert changed_paths(repo, "HEAD~1") == ("b.py",)
    assert not marker.exists()

    # Positive control: the hardened call refreshed the index, so dirty the
    # stat data again before the plain call that must run the hook.
    os.utime(repo / "a.py", (1_577_850_000, 1_577_850_000))
    _plain_name_only(repo)
    assert marker.exists()


@pytest.mark.parametrize("changed_paths", _SURFACES)
@pytest.mark.parametrize("variable", ["GIT_DIR", "GIT_WORK_TREE"])
def test_inherited_git_environment_cannot_redirect_the_answer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed_paths: ChangedPaths,
    variable: str,
) -> None:
    analysed = _repository(tmp_path / "analysed")
    other = _repository(tmp_path / "other")
    (other / "only_in_other.py").write_text("z = 1\n", encoding="utf-8")
    _git(other, "add", "only_in_other.py")
    _git(other, "commit", "-qm", "three")
    (other / "a.py").write_text("x = 99\n", encoding="utf-8")
    value = {"GIT_DIR": str(other / ".git"), "GIT_WORK_TREE": str(other)}[variable]
    monkeypatch.setenv(variable, value)

    assert changed_paths(analysed, "HEAD~1") == ("b.py",)

    # Positive control: inherited by a plain git call, it changes the answer.
    redirected = subprocess.run(
        ["git", "diff", "--name-only", "HEAD~1", "--"],
        cwd=analysed,
        env={**_clean_git_env(), variable: value},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert sorted(redirected.stdout.split()) != ["b.py"]


@pytest.mark.parametrize("changed_paths", _SURFACES)
def test_ordinary_repository_answer_is_unchanged(
    tmp_path: Path, changed_paths: ChangedPaths
) -> None:
    repo = _repository(tmp_path / "repo")
    (repo / "a.py").write_text("x = 5\n", encoding="utf-8")
    (repo / "pkg").mkdir()
    (repo / "pkg" / "c.py").write_text("c = 1\n", encoding="utf-8")
    _git(repo, "add", "pkg/c.py")

    assert changed_paths(repo, "HEAD~1") == tuple(_plain_name_only(repo))
    assert changed_paths(repo, "HEAD~1") == ("a.py", "b.py", "pkg/c.py")


def test_filter_driver_that_cannot_be_switched_off_refuses_the_call(
    tmp_path: Path,
) -> None:
    # ``-c filter.a=b.process=`` would set ``filter.a`` instead, so a driver
    # whose name holds ``=`` cannot be blanked: git is not run at all.
    repo = _repository(tmp_path / "repo")
    marker = tmp_path / "UNBLANKABLE_FILTER_RAN"
    _plant_clean_filter(repo, tmp_path, "a=b", marker)
    (repo / "a.py").write_text("x = 3\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        _cli_changed_paths(repo, "HEAD~1")
    assert exc.value.code == 2
    with pytest.raises(mcp_shared_mod.MCPGitDiffError):
        _mcp_changed_paths(repo, "HEAD~1")
    assert not marker.exists()

    _plain_name_only(repo)
    assert marker.exists()


def test_unreadable_repository_configuration_refuses_the_call(tmp_path: Path) -> None:
    # Without a readable configuration the filter drivers cannot be listed, so
    # git diff is not run unprotected.
    repo = _repository(tmp_path / "repo")
    with (repo / ".git" / "config").open("a", encoding="utf-8") as handle:
        handle.write("[broken\n")

    with pytest.raises(SystemExit) as exc:
        _cli_changed_paths(repo, "HEAD~1")
    assert exc.value.code == 2
    with pytest.raises(mcp_shared_mod.MCPGitDiffError):
        _mcp_changed_paths(repo, "HEAD~1")
