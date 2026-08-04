# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Repository identity anchored at the git common directory.

A linked ``git worktree`` checkout keeps its git state inside the main
checkout: its ``.git`` entry is a *gitfile* whose ``gitdir:`` pointer leads
to ``<main>/.git/worktrees/<name>``, and that directory's ``commondir`` file
leads back to ``<main>/.git``. Durable per-repository state — the
Engineering Memory store and the project identity derived from it — anchors
at the main checkout so every worktree of one repository reads and writes
the same knowledge.

Resolution is a lexical read of the git plumbing files (gitfile +
``commondir``), never a ``git`` subprocess: pure functions over file
contents stay deterministic, cheap enough for config resolution, and free
of process-spawn failure modes.

Resolution decision table (total — every input maps to exactly one row):

| git state at root                                   | classification     |
|-----------------------------------------------------|--------------------|
| ``.git`` directory                                  | ``main_checkout``  |
| no ``.git`` entry                                   | ``no_git``         |
| gitfile + ``commondir`` -> marked ``<main>/.git``   | ``linked_worktree`` |
| gitfile without ``commondir``, marked git dir       | ``main_checkout``  |
| gitfile unreadable/malformed or target missing      | ``git_unresolvable`` |
| ``commondir`` target missing, not ``.git``-named, or unmarked | ``git_unresolvable`` |

"Marked" is the result witness: acceptance is derived from what the joined
path actually contains — git-common plumbing markers (``HEAD`` and
``config`` files) — never from which code branch computed it. A joined path
that exists but carries no markers is an existing-but-wrong directory and
lands in ``git_unresolvable``.

A gitfile without ``commondir`` whose target is a marked git dir is a
checkout with an external git directory (a submodule, or
``--separate-git-dir``): that checkout is its own repository's only work
tree, so per-root anchoring is correct and healthy. ``git_unresolvable``
is the degraded class: git state is present, but the main checkout cannot
be reached lexically, so shared repository knowledge may be invisible from
this root.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final, Literal

RepoIdentityResolution = Literal[
    "main_checkout",
    "linked_worktree",
    "no_git",
    "git_unresolvable",
]

_GITFILE_PREFIX: Final = "gitdir:"


def resolve_repository_anchor_root(root_path: Path) -> Path:
    """Root that owns durable repository state for *root_path*.

    Equals the resolved *root_path* for every classification except
    ``linked_worktree``, where it is the main checkout root.
    """

    return _resolve_repository_identity(root_path)[0]


def classify_repository_checkout(root_path: Path) -> RepoIdentityResolution:
    """Classify *root_path* per the module decision table."""

    return _resolve_repository_identity(root_path)[1]


def _resolve_repository_identity(
    root_path: Path,
) -> tuple[Path, RepoIdentityResolution]:
    """Single lexical walk producing (anchor_root, classification).

    Total and non-raising by construction: every filesystem or parse
    failure lands in a typed fallback row of the decision table.
    """

    resolved_root = root_path.resolve()
    gitfile = resolved_root / ".git"
    try:
        if gitfile.is_dir():
            return resolved_root, "main_checkout"
        if not gitfile.is_file():
            return resolved_root, "no_git"
        gitdir_target = _read_gitfile_target(gitfile)
        if gitdir_target is None:
            return resolved_root, "git_unresolvable"
        gitdir_path = _resolve_lexical(resolved_root, gitdir_target)
        if not gitdir_path.is_dir():
            return resolved_root, "git_unresolvable"
        commondir_file = gitdir_path / "commondir"
        if not commondir_file.is_file():
            # External git dir (submodule / --separate-git-dir): this root is
            # its own repository's only work tree. Accept only a marked git
            # dir — an existing-but-unmarked target is wrongness, not health.
            if _is_marked_git_dir(gitdir_path):
                return resolved_root, "main_checkout"
            return resolved_root, "git_unresolvable"
        common_raw = commondir_file.read_text(
            encoding="utf-8", errors="replace"
        ).strip()
        if not common_raw:
            return resolved_root, "git_unresolvable"
        # The join base is the GITDIR directory (where the commondir file
        # lives), never the worktree root and never cwd: a relative
        # ``../..`` joined against a wrong base almost always lands on a
        # path that exists and is wrong.
        common_dir = _resolve_lexical(gitdir_path, common_raw)
        if common_dir.name != ".git" or not _is_marked_git_dir(common_dir):
            return resolved_root, "git_unresolvable"
        main_root = common_dir.parent
        if not main_root.is_dir():
            return resolved_root, "git_unresolvable"
        if main_root == resolved_root:
            return resolved_root, "main_checkout"
        return main_root, "linked_worktree"
    except OSError:
        return resolved_root, "git_unresolvable"


def _is_marked_git_dir(path: Path) -> bool:
    """Result witness: does *path* carry git-common plumbing markers?

    A real git common directory always contains ``HEAD`` and ``config``
    files; a linked worktree's private gitdir does not carry ``config``.
    Deriving acceptance from these markers — instead of from the branch
    that computed the path — turns an existing-but-wrong join result into
    a typed ``git_unresolvable`` outcome rather than a silently wrong one.
    """

    return (path / "HEAD").is_file() and (path / "config").is_file()


def _read_gitfile_target(gitfile: Path) -> str | None:
    """Parse the ``gitdir: <path>`` pointer from a gitfile, or None."""

    content = gitfile.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines()
    first = lines[0].strip() if lines else ""
    if not first.startswith(_GITFILE_PREFIX):
        return None
    target = first[len(_GITFILE_PREFIX) :].strip()
    return target or None


def _resolve_lexical(base: Path, raw: str) -> Path:
    """Resolve *raw* (absolute, or relative to *base*) to a canonical path.

    ``Path.resolve()`` normalizes ``..`` segments and follows symlinks, which
    also collapses macOS ``/tmp`` -> ``/private/tmp`` aliasing. ``~`` is never
    expanded: git plumbing never writes it, so a literal ``~`` stays a
    relative segment and lands in the ``git_unresolvable`` row.
    """

    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = base / candidate
    return candidate.resolve()


__all__ = [
    "RepoIdentityResolution",
    "classify_repository_checkout",
    "resolve_repository_anchor_root",
]
