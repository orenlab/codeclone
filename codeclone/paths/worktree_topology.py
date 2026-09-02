# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Detect a git worktree of the analysed repository nested inside its root.

The analysis walk excludes ``.git`` by NAME. In a linked worktree ``.git`` is
a FILE holding ``gitdir: <path>``, so the marker is excluded and the checkout
holding it is not: a second, complete copy of the project is read as project
source. Measured on this repository, one nested worktree took a run from
1177 files / 0 clone groups / health 91 to 2325 / 15378 / health 58, with
nothing in the run saying why.

Two properties of this module are deliberate.

*It never runs git.* ``paths.git_snapshot`` pays the one subprocess cost this
analysis allows, and it treats a missing git executable as a first-class
``git_available=False`` state that degrades an advisory signal. A topology
question that decided what a run contains must not acquire that dependency,
so every fact here is read from the filesystem: the ``.git`` marker, the
``gitdir:`` line inside it, and the ``commondir`` file beside it.

*It never decides membership.* The detector reports; the source universe is
unchanged. Warning about a second copy and silently dropping one are opposite
failures, and only the first is honest about what it did.

The witness is git's own topology, never a name: two checkouts belong to the
same repository exactly when they resolve to the same common git directory.
``.worktrees/`` today is ``tmp/foo`` tomorrow, and the analysis root of every
wave in this project is itself a linked worktree -- which the same comparison
handles, because a linked root resolves to the same common git dir its main
checkout does.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

from ..models import (
    GitCheckoutTopology,
    NestedWorktree,
    NestedWorktreeReport,
    UnresolvedGitTopology,
    UnresolvedGitTopologyReason,
)
from ..scanner import HARD_SAFETY_EXCLUDES

GIT_MARKER_NAME: Final = ".git"
GITDIR_LINE_PREFIX: Final = "gitdir: "
COMMON_DIR_FILE_NAME: Final = "commondir"

NESTED_WORKTREE_WARNING_MARKER: Final = (
    "Nested git worktree of this repository is INCLUDED in this analysis:"
)
UNRESOLVED_TOPOLOGY_WARNING_MARKER: Final = "Git topology unresolved:"


def fmt_nested_worktree(item: NestedWorktree) -> str:
    """The blunt sentence. "May affect results" was not enough.

    It has to say three things a reader can act on without a second question:
    that this run's numbers ALREADY contain a second copy of the project,
    which directory it is, and what to do about it. The witness rides along
    because the claim is falsifiable: two checkouts, one git directory.
    """

    return (
        f"{NESTED_WORKTREE_WARNING_MARKER} '{item.relative_path}'. Its files "
        f"were read as project source, so this run's clone counts, metrics and "
        f"health score cover TWO copies of the project and may be badly "
        f"distorted. Move that worktree outside the analysis root, or exclude "
        f"it from analysis, then re-run. Same-repository witness: both "
        f"checkouts resolve to git directory {item.common_git_dir}"
    )


def fmt_unresolved_topology(item: UnresolvedGitTopology) -> str:
    return (
        f"{UNRESOLVED_TOPOLOGY_WARNING_MARKER} '{item.checkout_root}' carries a "
        f"git marker CodeClone could not resolve ({item.reason}). It was "
        f"analysed as project source, and CodeClone cannot say whether it is a "
        f"second copy of this repository. Check it by hand."
    )


def fmt_unresolved_root_topology(item: UnresolvedGitTopology) -> str:
    return (
        f"{UNRESOLVED_TOPOLOGY_WARNING_MARKER} the analysis root's own git "
        f"marker could not be resolved ({item.reason}), so this run was not "
        f"checked for a nested copy of the repository."
    )


def topology_warnings(report: NestedWorktreeReport) -> tuple[str, ...]:
    """Render one scan as the run's warning strings, in a fixed order."""

    messages: list[str] = []
    if report.root_topology_unresolved is not None:
        messages.append(fmt_unresolved_root_topology(report.root_topology_unresolved))
    messages.extend(fmt_nested_worktree(item) for item in report.nested)
    messages.extend(fmt_unresolved_topology(item) for item in report.unresolved)
    return tuple(messages)


def _read_git_marker_target(marker: Path) -> Path | UnresolvedGitTopologyReason:
    try:
        text = marker.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "git_marker_unreadable"
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) != 1 or not lines[0].startswith(GITDIR_LINE_PREFIX):
        return "git_marker_malformed"
    target = lines[0].removeprefix(GITDIR_LINE_PREFIX).strip()
    if not target:
        return "git_marker_malformed"
    candidate = Path(target)
    return candidate if candidate.is_absolute() else marker.parent / candidate


def _resolve_common_git_dir(git_dir: Path) -> Path | UnresolvedGitTopologyReason:
    common_dir_file = git_dir / COMMON_DIR_FILE_NAME
    if not common_dir_file.is_file():
        return git_dir
    try:
        raw = common_dir_file.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return "common_dir_unreadable"
    if not raw:
        return "common_dir_unreadable"
    candidate = Path(raw)
    resolved = candidate if candidate.is_absolute() else git_dir / candidate
    # Resolved, never lexical: ``commondir`` normally holds ``../..``, so the
    # joined path is ``<git dir>/worktrees/<name>/../..`` and matches the main
    # checkout's ``.git`` only after normalization. A string comparison here
    # would silently never fire -- a guard no input can reach.
    try:
        return resolved.resolve(strict=True)
    except (OSError, RuntimeError):
        return "common_dir_unreadable"


def resolve_git_topology(
    location: Path,
) -> GitCheckoutTopology | UnresolvedGitTopology | None:
    """Read one directory's git topology, or say why it could not be read.

    ``None`` means the directory is not a git checkout at all, which is a
    fact and not a failure.
    """

    marker = location / GIT_MARKER_NAME
    if marker.is_dir():
        git_dir: Path = marker
        linked = False
    elif marker.is_file():
        target = _read_git_marker_target(marker)
        if isinstance(target, str):
            return UnresolvedGitTopology(checkout_root=location, reason=target)
        git_dir = target
        linked = True
    else:
        return None
    # Resolve first, then ask what it is: ordered the other way round, the
    # ``resolve`` guard is reachable only by a race, and a guard no input can
    # reach is theatre. This order gives both halves a real input -- a marker
    # naming nothing, and a marker naming a file.
    try:
        git_dir = git_dir.resolve(strict=True)
    except (OSError, RuntimeError):
        return UnresolvedGitTopology(
            checkout_root=location,
            reason="git_dir_missing",
        )
    if not git_dir.is_dir():
        return UnresolvedGitTopology(
            checkout_root=location,
            reason="git_dir_missing",
        )
    common_git_dir = _resolve_common_git_dir(git_dir)
    if isinstance(common_git_dir, str):
        return UnresolvedGitTopology(
            checkout_root=location,
            reason=common_git_dir,
        )
    return GitCheckoutTopology(
        checkout_root=location,
        git_dir=git_dir,
        common_git_dir=common_git_dir,
        linked=linked,
    )


def _is_nested_worktree_of(
    candidate: GitCheckoutTopology,
    *,
    root: GitCheckoutTopology,
) -> bool:
    """Same repository. One condition, and it is the whole witness.

    It rejects an unrelated repository and a submodule alike: a submodule's
    git dir is ``<root>/.git/modules/<name>`` and carries no ``commondir``, so
    it answers to itself and never to the repository's common git dir.

    A second half -- ``candidate.git_dir != root.git_dir`` -- was written here
    and removed after the mutation battery: the mutant that dropped it
    survived the whole suite, because git never gives two worktrees one git
    dir, so no input reached it. It was also wrong in the one case that CAN
    produce that equality: a directory copied out of a worktree keeps that
    worktree's ``.git`` file, and that copy is exactly the second copy of the
    project this warning exists to name. Distinctness from the analysis root
    is decided where it is actually decidable, in the walk.
    """

    return candidate.common_git_dir == root.common_git_dir


def _candidate_verdict(
    candidate: Path,
    *,
    root_path: Path,
    root_topology: GitCheckoutTopology,
) -> NestedWorktree | UnresolvedGitTopology | None:
    """Decide one directory that carries a ``.git`` file.

    ``None`` is "nothing to say about this directory" and covers two unrelated
    reasons on purpose, because the caller acts identically on both: the
    analysis root itself, and a checkout of some other repository.
    """

    # The analysis root of every wave in this project is itself a linked
    # worktree, so the root carries a ``.git`` file of its own and answers to
    # its own witness. This is the load-bearing half of "a DISTINCT worktree
    # root", and the only half a real topology can reach.
    if candidate == root_path:
        return None
    topology = resolve_git_topology(candidate)
    if topology is None or isinstance(topology, UnresolvedGitTopology):
        return topology
    if not _is_nested_worktree_of(topology, root=root_topology):
        return None
    return NestedWorktree(
        path=candidate,
        relative_path=candidate.relative_to(root_path).as_posix(),
        common_git_dir=topology.common_git_dir,
    )


def scan_nested_worktrees(
    root: Path,
    *,
    excludes: tuple[str, ...] = HARD_SAFETY_EXCLUDES,
) -> NestedWorktreeReport:
    """Report every linked worktree of ``root``'s repository nested inside it.

    The walk prunes the same directory names the analysis walk prunes, so what
    is reported is what was actually read. Directories the walk cannot enter
    are not reported here: the analysis walk could not enter them either, so
    nothing inside one reached this run, and that absence already rides the
    skipped-file counters.
    """

    try:
        root_path = root.resolve(strict=True)
    except (OSError, RuntimeError):
        return NestedWorktreeReport(
            root_topology_unresolved=None,
            nested=(),
            unresolved=(),
        )
    root_topology = resolve_git_topology(root_path)
    if isinstance(root_topology, UnresolvedGitTopology):
        return NestedWorktreeReport(
            root_topology_unresolved=root_topology,
            nested=(),
            unresolved=(),
        )
    if root_topology is None:
        # No repository at the root means no repository to be a second copy
        # of. Whether an enclosing checkout above the root owns a nested
        # worktree below it is a question this predicate does not ask.
        return NestedWorktreeReport(
            root_topology_unresolved=None,
            nested=(),
            unresolved=(),
        )

    excludes_set = set(excludes)
    nested: list[NestedWorktree] = []
    unresolved: list[UnresolvedGitTopology] = []
    for dirpath, dirnames, filenames in os.walk(
        root_path,
        topdown=True,
        followlinks=False,
    ):
        dirnames[:] = sorted(name for name in dirnames if name not in excludes_set)
        # Only a linked worktree or a submodule spells ``.git`` as a file. A
        # nested INDEPENDENT repository spells it as a directory, and its own
        # git dir can never equal this repository's common git dir, so it is
        # not a candidate by construction rather than by exemption. Measured:
        # admitting those directories too changes no verdict, so this gate
        # bounds the work and the witness alone decides.
        if GIT_MARKER_NAME not in filenames:
            continue
        verdict = _candidate_verdict(
            Path(dirpath),
            root_path=root_path,
            root_topology=root_topology,
        )
        if isinstance(verdict, UnresolvedGitTopology):
            unresolved.append(verdict)
        elif verdict is not None:
            nested.append(verdict)
            # A worktree holds the whole project again, so descending into one
            # doubles the walk to restate the same verdict. Moving the
            # outermost one out of the root removes everything below it too.
            dirnames[:] = []
    return NestedWorktreeReport(
        root_topology_unresolved=None,
        nested=tuple(sorted(nested, key=lambda item: item.relative_path)),
        unresolved=tuple(sorted(unresolved, key=lambda item: str(item.checkout_root))),
    )


def nested_worktree_warnings(root: Path) -> tuple[str, ...]:
    """One topology scan, rendered as the run's warning strings."""

    return topology_warnings(scan_nested_worktrees(root))


__all__ = [
    "COMMON_DIR_FILE_NAME",
    "GITDIR_LINE_PREFIX",
    "GIT_MARKER_NAME",
    "NESTED_WORKTREE_WARNING_MARKER",
    "UNRESOLVED_TOPOLOGY_WARNING_MARKER",
    "fmt_nested_worktree",
    "fmt_unresolved_root_topology",
    "fmt_unresolved_topology",
    "nested_worktree_warnings",
    "resolve_git_topology",
    "scan_nested_worktrees",
    "topology_warnings",
]
