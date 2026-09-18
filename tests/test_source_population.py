# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Pins for the one source-population owner.

The population an analysis reads is derived from git -- tracked files that
exist plus untracked files git does not ignore -- pruned by the hard-safety
names, with a typed filesystem fallback when git cannot answer. Provenance
(``scope_source`` / ``fallback_reason``) explains how the population was
obtained and never keys any digest: the same population from either source
is one identity.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

import codeclone.paths.population as population_mod
from codeclone.baseline.container_digest import compute_analysis_scope_digest
from codeclone.cache.reuse import source_content_digest
from codeclone.cache.store import Cache, file_stat_signature
from codeclone.models import (
    ContentIdentityVerdict,
    GitWorkspaceListing,
    ModuleRegistryHandle,
)
from codeclone.paths.git_snapshot import list_git_workspace_paths
from codeclone.paths.module_identity.inventory import build_module_registry
from codeclone.paths.population import derive_source_population
from codeclone.scanner import discover_python_files

_TRACKED = (
    "pkg/__init__.py",
    "pkg/tracked.py",
    "pkg/tracked_then_ignored.py",
    "build/gen.py",
)
_STUB = "pkg/stub.pyi"
_UNTRACKED_VISIBLE = "pkg/untracked_visible.py"
_UNTRACKED_IGNORED = "pkg/untracked_ignored.py"
_TOOL_IGNORED = ".claude/tool.py"
_IGNORE_RULES = "pkg/tracked_then_ignored.py\npkg/untracked_ignored.py\n.claude/\n"


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _git_rc(root: Path, *args: str) -> int:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        capture_output=True,
    ).returncode


def _write(root: Path, relative: str, source: str = "value = 1\n") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, "utf-8")
    return path


def _init_repository(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "population@example.invalid")
    _git(root, "config", "user.name", "population")


def _analyzed_paths(registry: ModuleRegistryHandle) -> frozenset[str]:
    return frozenset(
        path for path, entry in registry.entries_by_path.rows if entry.analyzed
    )


@pytest.fixture
def population_tree(tmp_path: Path) -> Path:
    """The F p1 tree plus the measured git edges, with probe-validity checks.

    Tracked files are committed before the ignore rules, so one of them is
    tracked *and* matches an ignore pattern. Two untracked files are ignored,
    one is not. ``build/gen.py`` is committed on purpose: git lists it and only
    the hard-safety prune can remove it.
    """

    root = tmp_path / "repo"
    root.mkdir()
    _init_repository(root)
    for relative in _TRACKED:
        _write(root, relative)
    _write(root, _STUB, "value: int\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "tracked")
    (root / ".gitignore").write_text(_IGNORE_RULES, "utf-8")
    _git(root, "add", ".gitignore")
    _git(root, "commit", "-q", "-m", "ignore")
    for relative in (_UNTRACKED_VISIBLE, _UNTRACKED_IGNORED, _TOOL_IGNORED):
        _write(root, relative)

    # Probe validity: the fixture must contain every distinguishing case, or a
    # green pin below would measure an empty population. A tracked file is
    # reported ignored only with --no-index (git 2.54: rc 1 without it).
    assert _git_rc(root, "check-ignore", "-q", "--no-index", _TRACKED[2]) == 0
    assert _git_rc(root, "check-ignore", "-q", _UNTRACKED_IGNORED) == 0
    assert _git_rc(root, "check-ignore", "-q", _TOOL_IGNORED) == 0
    status = _git(root, "status", "--porcelain")
    assert f"?? {_UNTRACKED_VISIBLE}" in status
    assert "untracked_ignored" not in status
    return root


@pytest.fixture
def congruent_tree(tmp_path: Path) -> Path:
    """A repository whose git population equals its walk population.

    No ``.py`` is ignored, so the only thing that can differ between the two
    sources is provenance -- which is exactly what must not move a digest.
    """

    root = tmp_path / "repo"
    root.mkdir()
    _init_repository(root)
    for relative in ("pkg/__init__.py", "pkg/tracked.py", "build/gen.py"):
        _write(root, relative)
    _write(root, _STUB, "value: int\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "tracked")
    _write(root, _UNTRACKED_VISIBLE)
    return root


# --- pin 1: a .gitignore edit moves the population and the registry digest ---


def test_gitignore_edit_moves_the_population_and_the_registry_digest(
    population_tree: Path,
) -> None:
    root = population_tree
    base = build_module_registry(root=root)
    assert _UNTRACKED_VISIBLE in _analyzed_paths(base)

    with (root / ".gitignore").open("a", encoding="utf-8") as handle:
        handle.write(f"{_UNTRACKED_VISIBLE}\n")
    moved = build_module_registry(root=root)

    assert _UNTRACKED_VISIBLE not in _analyzed_paths(moved)
    assert moved.digest != base.digest

    population = derive_source_population(root)
    assert population.scope_source == "git"
    assert str(root / _UNTRACKED_VISIBLE) not in population.paths


# --- pin 1b (the opposite boundary of decision 7): bytes alone move nothing ---


def test_gitignore_edit_that_keeps_the_population_keeps_the_dependent_lane(
    population_tree: Path,
    tmp_path: Path,
) -> None:
    root = population_tree
    source = root / "pkg" / "tracked.py"
    before = build_module_registry(root=root)
    cache = Cache(tmp_path / "cache.json", root=root)
    cache.bind_module_registry(before)
    cache.put_file_entry(
        str(source),
        file_stat_signature(str(source)),
        [],
        [],
        [],
        source_content_digest=source_content_digest(source.read_bytes()),
    )
    entry = cache.get_file_entry(str(source))
    assert entry is not None

    with (root / ".gitignore").open("a", encoding="utf-8") as handle:
        handle.write("# a comment moves the bytes and not one unit\n")
    after = build_module_registry(root=root)

    assert after.digest == before.digest
    cache.bind_module_registry(after)
    decision = cache.reuse_decision(
        runtime_path=str(source),
        content=ContentIdentityVerdict(
            hit=True,
            reason="digest_hit",
            git_fallback_reason=None,
            digest_verify_cost_us=0,
            stat_fast_reject=False,
        ),
        entry=entry,
    )
    assert decision.neutral.reason == "hit"
    assert decision.dependent.reason == "hit"


# --- pin 2: untracked and not ignored is a unit; untracked and ignored is not ---


def test_untracked_unignored_python_is_in_the_git_population(
    population_tree: Path,
) -> None:
    root = population_tree

    population = derive_source_population(root)

    assert population.scope_source == "git"
    assert population.fallback_reason is None
    assert str(root / _UNTRACKED_VISIBLE) in population.paths
    # The complementary boundary (table B-12): an ignored untracked file is not
    # a unit, and the tool never asks git a second question to count it.
    assert str(root / _UNTRACKED_IGNORED) not in population.paths
    assert str(root / _TOOL_IGNORED) not in population.paths

    registry = build_module_registry(root=root)
    assert registry.entries_by_path[_UNTRACKED_VISIBLE].analyzed is True
    assert _UNTRACKED_IGNORED not in registry.entries_by_path


def test_git_population_still_prunes_hard_safety_names(
    population_tree: Path,
) -> None:
    root = population_tree

    # Positive control: git itself lists the committed file under ``build/``,
    # so its absence below is the prune's doing and nothing else's.
    listing = list_git_workspace_paths(root)
    assert listing.available is True
    assert "build/gen.py" in listing.paths

    population = derive_source_population(root)

    assert population.scope_source == "git"
    assert str(root / "build" / "gen.py") not in population.paths
    assert population.hard_excluded == 1


def test_git_population_edges_are_measured_on_the_real_listing(
    population_tree: Path,
) -> None:
    root = population_tree
    # B-3: tracked but deleted from the tree -- git still prints it.
    (root / "pkg" / "tracked.py").unlink()
    # B-5: a symlink escaping the root -- git prints the link.
    os.symlink("/etc/hosts", root / "pkg" / "escaping_link.py")
    # B-13: a nested repository -- git prints ``nested/`` as one directory.
    nested = root / "nested"
    nested.mkdir()
    _init_repository(nested)
    _write(nested, "inner.py")
    _git(nested, "add", "inner.py")
    _git(nested, "commit", "-q", "-m", "inner")
    listing = list_git_workspace_paths(root)
    assert "pkg/tracked.py" in listing.paths
    assert "pkg/escaping_link.py" in listing.paths
    assert "nested/" in listing.paths

    population = derive_source_population(root)

    assert str(root / "pkg" / "tracked.py") not in population.paths
    assert str(root / "pkg" / "escaping_link.py") not in population.paths
    assert not any("inner.py" in path for path in population.paths)
    assert population.hard_excluded == 2
    assert population.unreadable == ()


# --- P-prov (I1): the same population from either source is one identity ---


def test_same_population_from_git_and_fallback_shares_every_digest(
    congruent_tree: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = congruent_tree
    from_git = derive_source_population(root)
    assert from_git.scope_source == "git"

    monkeypatch.setattr(
        population_mod,
        "list_git_workspace_paths",
        lambda _root: GitWorkspaceListing(
            available=False,
            paths=(),
            fallback_reason="git_unavailable",
        ),
    )
    from_walk = derive_source_population(root)

    assert from_walk.scope_source == "filesystem_fallback"
    assert from_walk.fallback_reason == "git_unavailable"
    assert from_walk.paths == from_git.paths
    assert from_walk.stub_paths == from_git.stub_paths == (str(root / _STUB),)

    git_registry = build_module_registry(root=root, population=from_git)
    walk_registry = build_module_registry(root=root, population=from_walk)
    assert git_registry.digest == walk_registry.digest
    assert compute_analysis_scope_digest(
        tuple(git_registry.entries_by_path.values())
    ) == compute_analysis_scope_digest(tuple(walk_registry.entries_by_path.values()))
    assert _STUB not in git_registry.entries_by_path


# --- P-fallback: no git is not "no code" ---


def test_non_git_tree_falls_back_to_the_walk_with_typed_reason(
    tmp_path: Path,
) -> None:
    for relative in ("pkg/__init__.py", "pkg/mod.py", "build/gen.py"):
        _write(tmp_path, relative)
    _write(tmp_path, _STUB, "value: int\n")
    # Probe validity: the premise is a tree outside any repository.
    assert _git_rc(tmp_path, "rev-parse", "--is-inside-work-tree") != 0

    population = derive_source_population(tmp_path)

    assert population.scope_source == "filesystem_fallback"
    assert population.fallback_reason == "not_a_repository"
    assert population.paths == discover_python_files(str(tmp_path))[0]
    assert population.paths == (
        str(tmp_path / "pkg" / "__init__.py"),
        str(tmp_path / "pkg" / "mod.py"),
    )
    assert population.stub_paths == (str(tmp_path / _STUB),)


_FakeRun = Callable[..., "subprocess.CompletedProcess[bytes]"]
_LsFiles = Callable[[list[str]], "subprocess.CompletedProcess[bytes]"]


def _git_that_answers(ls_files: _LsFiles) -> _FakeRun:
    def _run(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        if command[1] == "rev-parse":
            return subprocess.CompletedProcess(command, 0, stdout=b"true\n", stderr=b"")
        return ls_files(command)

    return _run


def _raise(error: BaseException) -> _LsFiles:
    def _fail(_command: list[str]) -> subprocess.CompletedProcess[bytes]:
        raise error

    return _fail


def _git_that_cannot_start(error: OSError) -> _FakeRun:
    def _run(
        _command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        raise error

    return _run


@pytest.mark.parametrize(
    ("fake_run", "expected_reason"),
    [
        pytest.param(
            _git_that_cannot_start(OSError("git missing")),
            "git_unavailable",
            id="A-1-git-binary-missing",
        ),
        pytest.param(
            _git_that_answers(
                _raise(subprocess.CalledProcessError(128, ["git", "ls-files"]))
            ),
            "git_listing_failed",
            id="A-3-ls-files-nonzero",
        ),
        pytest.param(
            _git_that_answers(
                _raise(subprocess.TimeoutExpired(["git", "ls-files"], 30))
            ),
            "git_listing_failed",
            id="A-3-ls-files-timeout",
        ),
        pytest.param(
            _git_that_answers(
                lambda command: subprocess.CompletedProcess(
                    command, 0, stdout=b"pkg/a.py\npkg/b.py\n", stderr=b""
                )
            ),
            "git_listing_unparseable",
            id="A-4-not-nul-framed",
        ),
    ],
)
def test_each_git_refusal_is_a_typed_fallback_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_run: _FakeRun,
    expected_reason: str,
) -> None:
    _write(tmp_path, "pkg/mod.py")
    monkeypatch.setattr(subprocess, "run", fake_run)

    listing = list_git_workspace_paths(tmp_path)
    assert listing.available is False
    assert listing.fallback_reason == expected_reason
    assert listing.paths == ()

    population = derive_source_population(tmp_path)
    assert population.scope_source == "filesystem_fallback"
    assert population.fallback_reason == expected_reason
    assert population.paths == (str(tmp_path / "pkg" / "mod.py"),)


def test_an_empty_git_listing_is_an_answer_and_not_a_refusal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Table A-6: a repository root with no listed source is the empty population."""

    _write(tmp_path, "pkg/mod.py")
    monkeypatch.setattr(
        subprocess,
        "run",
        _git_that_answers(
            lambda command: subprocess.CompletedProcess(
                command, 0, stdout=b"", stderr=b""
            )
        ),
    )

    population = derive_source_population(tmp_path)

    assert population.scope_source == "git"
    assert population.fallback_reason is None
    assert population.paths == ()
