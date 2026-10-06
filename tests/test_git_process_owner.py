# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The git owner's own contract: what it withholds from git, what it refuses,
and what its callers see when git fails.

The owner lives in the lowest ring, so it cannot import the MCP owner of the
auth-token name or ask git which variables are repository-local at import
time; both bindings are held here instead, against the real owners.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from codeclone.api.workspace import is_codeclone_service_path
from codeclone.surfaces.mcp.auth import MCP_AUTH_TOKEN_ENV
from codeclone.utils import git_process

from .hostile_git_fixtures import (
    build_repo,
    isolate_git_environment,
    marker_program,
    setup_git,
    twin_copy,
)


@pytest.fixture(autouse=True)
def _isolated_git(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    isolate_git_environment(monkeypatch, tmp_path)


def test_owner_drops_every_variable_git_drops_before_entering_another_repository(
    tmp_path: Path,
) -> None:
    listed = subprocess.run(
        ["git", "rev-parse", "--local-env-vars"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert "GIT_DIR" in listed, "positive control: git listed its variables"
    assert set(listed) <= git_process._REPOSITORY_LOCAL_ENV


def test_owner_withholds_the_mcp_auth_token_by_the_mcp_owners_name() -> None:
    assert MCP_AUTH_TOKEN_ENV in git_process._WITHHELD_ENV


def test_verb_without_a_call_form_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="git push has no call form"):
        git_process.run_git_text(tmp_path, ["push"], timeout=5)


def test_a_call_without_a_verb_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="git needs a verb"):
        git_process.run_git_bytes(tmp_path, [], timeout=5)


@pytest.mark.parametrize(
    "args",
    [("status", "--porcelain=v1"), ("diff", "--name-only", "HEAD", "--")],
    ids=["status", "worktree-diff"],
)
def test_outside_a_repository_git_fails_on_its_own_terms(
    tmp_path: Path, args: tuple[str, ...]
) -> None:
    """Outside a repository git can list no repository configuration and
    locate no index; the owner adds nothing and git refuses the call itself,
    under the command as asked."""

    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(subprocess.CalledProcessError) as raised:
        git_process.run_git_text(plain, list(args), timeout=10)
    assert raised.value.cmd == ["git", *args]
    assert sorted(path.name for path in plain.iterdir()) == []


def test_a_missing_index_stays_missing(tmp_path: Path) -> None:
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    setup_git(fresh, "init", "-q")
    (fresh / "a.py").write_text("x = 1\n", "utf-8")
    answer = git_process.run_git_text(fresh, ["diff", "--name-only", "--"], timeout=10)
    assert answer.stdout == ""
    assert not (fresh / ".git" / "index").exists()


def test_a_linked_worktree_keeps_its_own_index_unwritten(tmp_path: Path) -> None:
    """A linked worktree's index lives in the common directory, at the
    absolute path git prints for it."""

    repo = build_repo(tmp_path / "repo")
    setup_git(repo.root, "worktree", "add", "-q", str(tmp_path / "linked"))
    linked = tmp_path / "linked"
    (linked / "a.py").write_text("def a(x):\n    return x + 5\n", "utf-8")
    os.utime(linked / "b.py", None)
    index = repo.root / ".git" / "worktrees" / "linked" / "index"
    before = index.read_bytes()
    answer = git_process.run_git_text(
        linked, ["diff", "--name-only", "HEAD", "--"], timeout=10
    )
    assert answer.stdout.split() == ["a.py"]
    assert index.read_bytes() == before


@pytest.mark.parametrize("failing", ["mkdtemp", "copy2"])
def test_no_private_index_means_no_diff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failing: str
) -> None:
    repo = build_repo(tmp_path / "repo")
    before = (repo.root / ".git" / "index").read_bytes()
    made: list[Path] = []
    real_mkdtemp = tempfile.mkdtemp

    def mkdtemp(*args: object, **kwargs: object) -> str:
        if failing == "mkdtemp":
            raise PermissionError("no temporary directory")
        made.append(
            Path(real_mkdtemp(prefix="index-", dir=git_process._private_index_parent()))
        )
        return str(made[-1])

    def copy2(*_args: object, **_kwargs: object) -> None:
        raise PermissionError("no copy")

    monkeypatch.setattr(tempfile, "mkdtemp", mkdtemp)
    if failing == "copy2":
        monkeypatch.setattr(shutil, "copy2", copy2)
    with pytest.raises(git_process.GitInvocationRefused, match="no private index"):
        git_process.run_git_text(
            repo.root, ["diff", "--name-only", "HEAD", "--"], timeout=10
        )
    assert (repo.root / ".git" / "index").read_bytes() == before
    assert [path.exists() for path in made] == ([False] if failing == "copy2" else [])


_WORKTREE_DIFF = ["diff", "--name-only", "HEAD", "--"]


def _watched_os_temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty directory standing in for the OS temporary directory."""

    os_temp = tmp_path / "os-temp"
    os_temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(os_temp))
    return os_temp


def test_the_owner_cache_directory_is_a_codeclone_service_directory(
    tmp_path: Path,
) -> None:
    """The owner spells the per-user cache directory itself (its ring cannot
    import the layout module); the layout module's boundary must admit it."""

    private_parent = (
        Path(git_process._USER_CACHE_DIR).expanduser() / git_process._PRIVATE_INDEX_DIR
    )
    assert is_codeclone_service_path(private_parent, root=tmp_path)
    assert not is_codeclone_service_path(tmp_path / "elsewhere", root=tmp_path)


def test_private_index_lives_in_the_per_user_cache_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = build_repo(tmp_path / "repo")
    os_temp = _watched_os_temp(tmp_path, monkeypatch)
    copies: list[tuple[Path, list[str]]] = []
    real_copy2 = shutil.copy2

    def copy2(src: Path, dst: Path, **kwargs: bool) -> object:
        copies.append((Path(dst), sorted(path.name for path in os_temp.iterdir())))
        return real_copy2(src, dst, **kwargs)

    monkeypatch.setattr(shutil, "copy2", copy2)
    answer = git_process.run_git_text(repo.root, _WORKTREE_DIFF, timeout=10)

    assert answer.stdout.split() == ["a.py", "c.py", "staged.py"]
    ((private, os_temp_during_the_call),) = copies
    parent = Path("~/.cache/codeclone/git-index").expanduser()
    assert private.is_relative_to(parent)
    assert is_codeclone_service_path(private, root=repo.root)
    assert os_temp_during_the_call == []
    assert sorted(os_temp.iterdir()) == []
    assert sorted(parent.iterdir()) == [], "the copy outlived its call"


@pytest.mark.parametrize("failure", ["not-a-directory", "home-unresolved"])
def test_an_unusable_cache_directory_refuses_the_worktree_diff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """No other place may take the copy: the diff is refused, the same typed
    road a driver git cannot be kept from running takes."""

    repo = build_repo(tmp_path / "repo")
    os_temp = _watched_os_temp(tmp_path, monkeypatch)
    before = (repo.root / ".git" / "index").read_bytes()
    if failure == "not-a-directory":
        (Path(os.environ["HOME"]) / ".cache").write_text("", "utf-8")
    else:
        monkeypatch.setattr(os.path, "expanduser", lambda path: path)
    with pytest.raises(git_process.GitInvocationRefused, match="no private index"):
        git_process.run_git_text(repo.root, _WORKTREE_DIFF, timeout=10)
    assert sorted(os_temp.iterdir()) == []
    assert (repo.root / ".git" / "index").read_bytes() == before


def test_failure_reports_the_command_asked_for(tmp_path: Path) -> None:
    repo = build_repo(tmp_path / "repo")
    with pytest.raises(subprocess.CalledProcessError) as raised:
        git_process.run_git_text(
            repo.root, ["rev-parse", "--verify", "no-such-ref"], timeout=10
        )
    assert raised.value.cmd == ["git", "rev-parse", "--verify", "no-such-ref"]
    assert raised.value.returncode == 128


def test_timeout_reports_the_command_asked_for(tmp_path: Path) -> None:
    """An operator's global driver is still run; a slow one times out the
    call, and the timeout names the call as asked."""

    repo = build_repo(tmp_path / "repo", attributes="*.py filter=slow\n")
    slow = marker_program(repo.programs / "slow.sh", repo.markers, "slow", "sleep 3")
    repo.set_config("filter.slow.clean", slow, scope="--global")
    with pytest.raises(subprocess.TimeoutExpired) as raised:
        git_process.run_git_text(repo.root, ["status", "--porcelain=v1"], timeout=1)
    assert raised.value.cmd == ["git", "status", "--porcelain=v1"]


def test_private_index_keeps_the_racy_answer_of_the_real_index(tmp_path: Path) -> None:
    """An entry written in the same second as its index is racily clean: git
    must read its content. A private copy dated now would make the entry look
    settled and hide a same-size edit that kept its mtime."""

    repo = build_repo(tmp_path / "repo")
    repo.set_config("core.trustctime", "false")
    moment = 1_700_000_000
    os.utime(repo.root / "b.py", (moment, moment))
    setup_git(repo.root, "update-index", "-q", "--refresh")
    os.utime(repo.root / ".git" / "index", (moment, moment))
    (repo.root / "b.py").write_text("def b(x):\n    return x + 7\n", "utf-8")
    os.utime(repo.root / "b.py", (moment, moment))
    control = twin_copy(repo, tmp_path / "control")

    plain = setup_git(control.root, "diff", "--name-only", "HEAD", "--")
    assert "b.py" in plain.stdout.decode().split(), "positive control: not racy"
    answer = git_process.run_git_text(
        repo.root, ["diff", "--name-only", "HEAD", "--"], timeout=10
    )
    assert "b.py" in answer.stdout.split()
