# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A nested worktree of the same repository is a second copy of the project.

Measured on this repository, one nested linked worktree inside the analysis
root moved the run from 1177 files / 0 clones / health 91 to 2325 files /
15378 clones / health 58, silently. The walk excludes ``.git`` by *name*, and
a linked worktree's ``.git`` is a FILE, so the marker was excluded and the
checkout holding it was not.

Phase 1 warns and changes nothing about the source universe. The universe pin
below is therefore part of the contract, not a leftover: a fix that started
dropping files would be a different, unratified change wearing this one's
name.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from codeclone.models import GitCheckoutTopology, NestedWorktreeReport
from codeclone.paths.worktree_topology import (
    NESTED_WORKTREE_WARNING_MARKER,
    nested_worktree_warnings,
    resolve_git_topology,
    scan_nested_worktrees,
    topology_warnings,
)
from codeclone.scanner import discover_python_files
from tests._pipeline_fixtures import analysis_boot, discover_and_process

# Real worktrees, not simulated ones: a ``.git`` file dropped by hand proves
# nothing about a detector whose whole subject is git's own topology.
pytestmark = pytest.mark.skipif(
    shutil.which("git") is None,
    reason="the fixture needs real git worktrees, not a hand-written .git file",
)

_MODULE_SOURCE = """\
def alpha(first, second):
    total = 0
    for index in range(first):
        total += index * second
    return total


def beta(first, second):
    total = 0
    for index in range(first):
        total += index * second
    return total
"""


def _git(*args: str, cwd: Path) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def _init_repo(root: Path, *, module_name: str = "mod.py") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", "-b", "main", ".", cwd=root)
    _git("config", "user.email", "fixture@example.invalid", cwd=root)
    _git("config", "user.name", "fixture", cwd=root)
    package = root / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("", "utf-8")
    (package / module_name).write_text(_MODULE_SOURCE, "utf-8")
    _git("add", "-A", cwd=root)
    _git("commit", "-q", "-m", "init", cwd=root)
    return root


def _add_linked_worktree(*, repo: Path, path: Path) -> Path:
    _git("worktree", "add", "-q", "--detach", str(path), "HEAD", cwd=repo)
    return path


@pytest.fixture
def nested_worktree_tree(tmp_path: Path) -> tuple[Path, Path]:
    """A main checkout with one REAL linked worktree of itself inside it."""

    main = _init_repo(tmp_path / "main")
    nested = _add_linked_worktree(repo=main, path=main / "vendored" / "wt")
    return main, nested


# ── witness: the fixture is a genuine linked worktree, and it is analysed ──


def test_fixture_nested_worktree_is_a_real_linked_worktree(
    nested_worktree_tree: tuple[Path, Path],
) -> None:
    """Before any detector claim: prove the fixture is what it says it is.

    Every downstream assertion in this module is vacuous if this fails --- a
    directory that merely looks like a worktree would make a broken detector
    and a correct one indistinguishable.
    """

    main, nested = nested_worktree_tree

    marker = nested / ".git"
    assert marker.is_file(), "a linked worktree's .git is a file, not a directory"
    assert marker.read_text("utf-8").startswith("gitdir: ")

    listed = _git("worktree", "list", "--porcelain", cwd=main)
    worktree_lines = sorted(
        Path(line.removeprefix("worktree ")).resolve()
        for line in listed.splitlines()
        if line.startswith("worktree ")
    )
    assert worktree_lines == sorted({main.resolve(), nested.resolve()})

    assert (
        Path(_git("rev-parse", "--git-common-dir", cwd=nested).strip()).resolve()
        == (main / ".git").resolve()
    )


def test_nested_worktree_sources_are_analysed_today(
    nested_worktree_tree: tuple[Path, Path],
) -> None:
    """The inclusion is observable: the second copy reaches the file walk."""

    main, nested = nested_worktree_tree

    found = sorted(Path(path).resolve() for path in discover_python_files(str(main))[0])

    assert (nested / "pkg" / "mod.py").resolve() in found
    assert len(found) == 4  # two modules, each counted twice


# ── the detector fires, and its warning carries the witness ──


def test_nested_linked_worktree_is_detected_with_its_common_git_dir(
    nested_worktree_tree: tuple[Path, Path],
) -> None:
    main, nested = nested_worktree_tree

    report = scan_nested_worktrees(main)

    assert [item.path for item in report.nested] == [nested.resolve()]
    assert [item.relative_path for item in report.nested] == ["vendored/wt"]
    # The witness, not a name heuristic: both checkouts answer to one git dir.
    assert [item.common_git_dir for item in report.nested] == [
        (main / ".git").resolve()
    ]
    assert report.unresolved == ()
    assert report.root_topology_unresolved is None


def test_warning_is_blunt_names_the_path_and_says_what_to_do(
    nested_worktree_tree: tuple[Path, Path],
) -> None:
    """ "May affect results" is too soft after 15378 fabricated clones."""

    main, _nested = nested_worktree_tree

    (warning,) = nested_worktree_warnings(main)

    assert warning.startswith(NESTED_WORKTREE_WARNING_MARKER)
    assert "vendored/wt" in warning
    assert str((main / ".git").resolve()) in warning
    lowered = warning.lower()
    assert "include" in lowered
    assert "distorted" in lowered
    assert "move" in lowered and "exclude" in lowered


def test_analysis_root_that_is_itself_a_linked_worktree_still_detects(
    tmp_path: Path,
) -> None:
    """Every wave in this project runs inside a linked worktree, so this is
    the ordinary case, not an edge case: comparing common git dirs is what
    makes a linked root behave like a main one."""

    main = _init_repo(tmp_path / "main")
    root = _add_linked_worktree(repo=main, path=tmp_path / "outer")
    nested = _add_linked_worktree(repo=main, path=root / "inner")

    report = scan_nested_worktrees(root)

    assert [item.path for item in report.nested] == [nested.resolve()]
    assert [item.common_git_dir for item in report.nested] == [
        (main / ".git").resolve()
    ]


def test_copy_of_a_worktree_directory_is_reported(tmp_path: Path) -> None:
    """A directory copied out of a worktree keeps that worktree's ``.git``
    file, so it answers to the SAME git dir as the checkout it came from ---
    including the analysis root itself. It is still a second copy of the
    project, and the earlier ``git_dir != root.git_dir`` half suppressed
    exactly this one. The witness is the repository, not the git dir.
    """

    main = _init_repo(tmp_path / "main")
    root = _add_linked_worktree(repo=main, path=tmp_path / "outer")
    copied = root / "copied"
    shutil.copytree(root / "pkg", copied / "pkg")
    shutil.copyfile(root / ".git", copied / ".git")

    root_topology = resolve_git_topology(root)
    copied_topology = resolve_git_topology(copied)
    assert isinstance(root_topology, GitCheckoutTopology)
    assert isinstance(copied_topology, GitCheckoutTopology)
    assert copied_topology.git_dir == root_topology.git_dir  # the suppressed case

    report = scan_nested_worktrees(root)

    assert [item.relative_path for item in report.nested] == ["copied"]


def test_the_analysis_root_never_reports_itself(tmp_path: Path) -> None:
    """A linked root carries a ``.git`` file and so matches its own witness.
    Distinctness is decided in the walk, and this is what decides it."""

    main = _init_repo(tmp_path / "main")
    root = _add_linked_worktree(repo=main, path=tmp_path / "outer")

    report = scan_nested_worktrees(root)

    assert report.nested == ()
    assert report.unresolved == ()


# ── the detector stays silent where it must ──


def test_independent_nested_repository_is_not_reported(tmp_path: Path) -> None:
    """A separate repository checked out inside the root is a different
    contract with a different default, and this wave does not touch it."""

    main = _init_repo(tmp_path / "main")
    _init_repo(main / "vendor" / "other", module_name="other.py")

    report = scan_nested_worktrees(main)

    assert report.nested == ()
    assert report.unresolved == ()


def test_worktree_of_a_different_repository_is_not_reported(tmp_path: Path) -> None:
    """A real linked worktree whose common git dir is somebody else's."""

    ours = _init_repo(tmp_path / "ours")
    theirs = _init_repo(tmp_path / "theirs")
    foreign = _add_linked_worktree(repo=theirs, path=ours / "vendor" / "theirs-wt")

    assert (foreign / ".git").is_file()  # witness: a real linked worktree

    report = scan_nested_worktrees(ours)

    assert report.nested == ()
    assert report.unresolved == ()


def test_submodule_is_not_reported(tmp_path: Path) -> None:
    """A submodule can be a deliberate part of the project; its git dir is
    ``.git/modules/<name>`` and never the repository's common git dir."""

    upstream = _init_repo(tmp_path / "upstream", module_name="up.py")
    main = _init_repo(tmp_path / "main")
    _git(
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "-q",
        str(upstream),
        "vendor/up",
        cwd=main,
    )

    marker = main / "vendor" / "up" / ".git"
    assert marker.is_file()  # witness: the submodule is wired, not copied

    report = scan_nested_worktrees(main)

    assert report.nested == ()


# ── malformed topology is typed, never a guess ──


@pytest.mark.parametrize(
    ("marker_text", "reason"),
    [
        ("not a gitdir line\n", "git_marker_malformed"),
        ("gitdir: \n", "git_marker_malformed"),
        ("gitdir: ./nowhere-at-all\n", "git_dir_missing"),
    ],
)
def test_malformed_git_marker_is_unresolved_not_a_silent_verdict(
    tmp_path: Path,
    marker_text: str,
    reason: str,
) -> None:
    main = _init_repo(tmp_path / "main")
    candidate = main / "vendored" / "wt"
    candidate.mkdir(parents=True)
    (candidate / "mod.py").write_text(_MODULE_SOURCE, "utf-8")
    (candidate / ".git").write_text(marker_text, "utf-8")

    report = scan_nested_worktrees(main)

    assert report.nested == ()
    assert [item.reason for item in report.unresolved] == [reason]
    assert [item.checkout_root for item in report.unresolved] == [candidate.resolve()]
    (warning,) = topology_warnings(report)
    assert "vendored/wt" in warning
    assert reason in warning


def test_unresolvable_root_topology_is_reported_not_assumed(tmp_path: Path) -> None:
    """Failing open about the universe is honest; a silent verdict is not."""

    root = tmp_path / "plain"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "mod.py").write_text(_MODULE_SOURCE, "utf-8")
    (root / ".git").write_text("gitdir: ./missing\n", "utf-8")

    report = scan_nested_worktrees(root)

    assert report.nested == ()
    assert report.root_topology_unresolved is not None
    assert report.root_topology_unresolved.reason == "git_dir_missing"
    assert any("analysis root" in warning for warning in topology_warnings(report))


def test_root_outside_any_repository_is_silent(tmp_path: Path) -> None:
    """No git anywhere is not a topology problem and must not warn."""

    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text(_MODULE_SOURCE, "utf-8")

    report = scan_nested_worktrees(tmp_path)

    assert report == NestedWorktreeReport(
        root_topology_unresolved=None,
        nested=(),
        unresolved=(),
    )
    assert topology_warnings(report) == ()


def test_git_marker_naming_a_file_is_unresolved(tmp_path: Path) -> None:
    """The second half of the resolve guard: the target exists, and is not a
    git directory."""

    main = _init_repo(tmp_path / "main")
    candidate = main / "vendored" / "wt"
    candidate.mkdir(parents=True)
    (candidate / "decoy").write_text("", "utf-8")
    (candidate / ".git").write_text("gitdir: ./decoy\n", "utf-8")

    report = scan_nested_worktrees(main)

    assert report.nested == ()
    assert [item.reason for item in report.unresolved] == ["git_dir_missing"]


def test_unreadable_git_marker_is_unresolved(tmp_path: Path) -> None:
    """Bytes no decoder accepts are an unread marker, not a verdict."""

    main = _init_repo(tmp_path / "main")
    candidate = main / "vendored" / "wt"
    candidate.mkdir(parents=True)
    (candidate / ".git").write_bytes(b"gitdir: \xff\xfe\n")

    report = scan_nested_worktrees(main)

    assert report.nested == ()
    assert [item.reason for item in report.unresolved] == ["git_marker_unreadable"]


def test_dangling_git_marker_symlink_is_not_a_checkout(tmp_path: Path) -> None:
    """``.git`` is listed by the walk yet is neither a file nor a directory."""

    main = _init_repo(tmp_path / "main")
    candidate = main / "vendored" / "wt"
    candidate.mkdir(parents=True)
    (candidate / ".git").symlink_to(candidate / "nowhere")

    report = scan_nested_worktrees(main)

    assert report.nested == ()
    assert report.unresolved == ()


@pytest.mark.parametrize(
    "commondir_bytes",
    [
        pytest.param(b"\n", id="empty"),
        pytest.param(b"\xff\xfe\n", id="undecodable"),
        pytest.param(b"../../nowhere-at-all\n", id="names-nothing"),
    ],
)
def test_unusable_commondir_is_unresolved_not_a_match(
    nested_worktree_tree: tuple[Path, Path],
    commondir_bytes: bytes,
) -> None:
    """Without a readable common git dir there is no witness, so there is no
    verdict -- in either direction."""

    main, nested = nested_worktree_tree
    topology = resolve_git_topology(nested)
    assert isinstance(topology, GitCheckoutTopology)
    (topology.git_dir / "commondir").write_bytes(commondir_bytes)

    report = scan_nested_worktrees(main)

    assert report.nested == ()
    assert [item.reason for item in report.unresolved] == ["common_dir_unreadable"]


def test_missing_root_is_an_empty_report_not_an_exception(tmp_path: Path) -> None:
    """The scan is advisory; it may never be the thing that ends a run."""

    report = scan_nested_worktrees(tmp_path / "not-there")

    assert report == NestedWorktreeReport(
        root_topology_unresolved=None,
        nested=(),
        unresolved=(),
    )


# ── the resolved-vs-lexical comparison is the load-bearing step ──


def test_common_git_dir_is_compared_resolved_not_lexically(
    nested_worktree_tree: tuple[Path, Path],
) -> None:
    """``commondir`` holds ``../..``; a lexical comparison of the two paths
    cannot match, so this is the step that decides the whole detector."""

    main, nested = nested_worktree_tree

    root_topology = resolve_git_topology(main)
    nested_topology = resolve_git_topology(nested)
    assert isinstance(root_topology, GitCheckoutTopology)
    assert isinstance(nested_topology, GitCheckoutTopology)
    raw_commondir = (nested_topology.git_dir / "commondir").read_text("utf-8").strip()

    # The un-normalized join is what a lexical comparison would see.
    lexical = nested_topology.git_dir / raw_commondir
    assert ".." in lexical.parts
    assert str(lexical) != str(root_topology.common_git_dir)

    assert nested_topology.common_git_dir == root_topology.common_git_dir


# ── phase-1 boundary: nothing is excluded from the run ──


def test_detection_does_not_change_the_source_universe(
    nested_worktree_tree: tuple[Path, Path],
) -> None:
    """The wave adds a warning. It must not quietly start losing sources."""

    main, nested = nested_worktree_tree
    boot = analysis_boot(main, min_loc=1, min_stmt=1, skip_metrics=True)

    _cache, discovery, _processing = discover_and_process(
        boot,
        main / "cache.json",
        root=main,
        warm=False,
    )

    analysed = {Path(path).resolve() for path in discovery.all_file_paths}
    assert (nested / "pkg" / "mod.py").resolve() in analysed
    assert discovery.files_skipped == 0


def test_discovery_carries_the_warning_to_the_run(
    nested_worktree_tree: tuple[Path, Path],
) -> None:
    """The producer both surfaces read is ``discover``; a detector nobody
    calls is theatre."""

    main, _nested = nested_worktree_tree
    boot = analysis_boot(main, min_loc=1, min_stmt=1, skip_metrics=True)

    _cache, discovery, _processing = discover_and_process(
        boot,
        main / "cache.json",
        root=main,
        warm=False,
    )

    matching = [
        warning
        for warning in discovery.skipped_warnings
        if warning.startswith(NESTED_WORKTREE_WARNING_MARKER)
    ]
    assert len(matching) == 1
    assert "vendored/wt" in matching[0]


def test_discovery_is_silent_without_a_nested_worktree(tmp_path: Path) -> None:
    """The opposite error: a clean repository must never carry this warning."""

    main = _init_repo(tmp_path / "main")
    boot = analysis_boot(main, min_loc=1, min_stmt=1, skip_metrics=True)

    _cache, discovery, _processing = discover_and_process(
        boot,
        main / "cache.json",
        root=main,
        warm=False,
    )

    assert not [
        warning
        for warning in discovery.skipped_warnings
        if warning.startswith(NESTED_WORKTREE_WARNING_MARKER)
    ]
