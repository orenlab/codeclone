# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The one owner of a run's source population.

Git is the default source: ``git ls-files -z --cached --others
--exclude-standard`` answers "tracked, or untracked and not ignored", and the
hard-safety names prune what git would happily list -- a committed ``build/``,
a venv nobody ignored. When git cannot answer (no binary, no repository, a
failed or unparseable listing) the tree walk stands in with the same prune,
and the population says so through a typed ``fallback_reason``. Half of
``.gitignore`` is never re-implemented here: either git reads it, or nobody
does.

Two populations share this one derivation rule and differ only by moment:
the analysis population, frozen into the module registry at the start of a
run, and the drift population the MCP surface derives afresh on every
``compute_drift``. Neither the provenance nor the diagnostics enter any
digest -- see ``SourcePopulation``.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Literal

from ..contracts import ScopeFallbackReason
from ..contracts.errors import ValidationError
from ..models import GitWorkspaceListing, SourcePopulation
from ..scanner import HARD_SAFETY_EXCLUDES, discover_python_files, validate_scan_root
from ..utils.repo_paths import has_python_suffix
from .git_snapshot import list_git_workspace_paths


def derive_source_population(
    root: Path,
    *,
    hard_excludes: tuple[str, ...] = HARD_SAFETY_EXCLUDES,
    max_files: int = 100_000,
) -> SourcePopulation:
    """Derive the population of ``root``: git first, the walk as typed fallback.

    Root validation (existence, directory, sensitive prefixes) precedes any
    git call, for both sources alike. The root's own name being a hard-safety
    name is decided after the listing, so that the empty population it yields
    still says truthfully which source answered.
    """

    rootp = validate_scan_root(str(root))
    listing = list_git_workspace_paths(rootp)
    if listing.available:
        return _population_from_git(
            rootp=rootp,
            listing=listing,
            hard_excludes=hard_excludes,
            max_files=max_files,
        )
    return _population_from_walk(
        rootp=rootp,
        fallback_reason=listing.fallback_reason,
        hard_excludes=hard_excludes,
        max_files=max_files,
    )


def _population_from_git(
    *,
    rootp: Path,
    listing: GitWorkspaceListing,
    hard_excludes: tuple[str, ...],
    max_files: int,
) -> SourcePopulation:
    """Table B, column GIT: the fate of every name git printed."""

    excludes_set = set(hard_excludes)
    if rootp.name in excludes_set:
        # Parity with the walk's short circuit: a root that is itself a
        # hard-excluded name (``<repo>/__pycache__``) is empty and counted.
        return SourcePopulation(
            root=str(rootp),
            paths=(),
            stub_paths=(),
            hard_excluded=1,
            unreadable=(),
            scope_source="git",
            fallback_reason=None,
        )
    paths: list[str] = []
    stub_paths: list[str] = []
    hard_excluded = 0
    unreadable: list[str] = []
    for relative in listing.paths:
        parts = relative.split("/")
        if not has_python_suffix(parts[-1], include_stubs=True):
            # B-1: not a source unit -- a data file, a nested repository git
            # prints as one directory, a symlinked directory.
            continue
        candidate = rootp.joinpath(*parts)
        fate = _git_candidate_fate(
            candidate,
            parts=parts,
            rootp=rootp,
            excludes_set=excludes_set,
        )
        if fate == "hard_excluded":
            hard_excluded += 1
        elif fate == "unreadable":
            unreadable.append(str(candidate))
        elif fate == "stub":
            stub_paths.append(str(candidate))
        elif fate == "source":
            paths.append(str(candidate))
        if len(paths) + len(stub_paths) > max_files:
            raise ValidationError(
                f"File count exceeds limit of {max_files}. "
                "Use more specific root or increase limit."
            )
    return SourcePopulation(
        root=str(rootp),
        paths=tuple(sorted(paths)),
        stub_paths=tuple(sorted(stub_paths)),
        hard_excluded=hard_excluded,
        unreadable=tuple(sorted(unreadable)),
        scope_source="git",
        fallback_reason=None,
    )


#: What becomes of one source-unit name git printed (table B, column GIT).
#: ``absent`` covers every silent drop: a tracked file deleted from the tree
#: (the index is older than the tree, so nothing was lost) and anything that
#: is not a regular file once looked at -- a gitlink, a FIFO, a link to a
#: directory.
_GitCandidateFate = Literal["source", "stub", "hard_excluded", "unreadable", "absent"]


def _git_candidate_fate(
    candidate: Path,
    *,
    parts: list[str],
    rootp: Path,
    excludes_set: set[str],
) -> _GitCandidateFate:
    if any(part in excludes_set for part in parts):
        # B-2: git lists it, hard safety refuses it. Counted, like the walk
        # counts what it prunes.
        return "hard_excluded"
    try:
        mode = os.lstat(candidate).st_mode
    except FileNotFoundError:
        return "absent"  # B-3
    except OSError:
        # B-4: the file exists and cannot be read. Unlike the walk, git
        # names the file, so the diagnostic is per file.
        return "unreadable"
    if stat.S_ISLNK(mode):
        # B-5: a link that escapes the root or cannot resolve is refused
        # like a hard-excluded name; B-6: a link to a regular file inside
        # the root is accepted by its link path, as the walk accepts it.
        resolved = _resolved_inside_root(candidate, rootp)
        return (
            "hard_excluded"
            if resolved is None
            else _regular_file_fate(resolved.is_file(), parts[-1])
        )
    return _regular_file_fate(stat.S_ISREG(mode), parts[-1])


def _regular_file_fate(regular: bool, name: str) -> _GitCandidateFate:
    """B-7 versus B-8/B-9: only a regular file is a unit, and its suffix says which."""

    if not regular:
        return "absent"
    return "source" if has_python_suffix(name) else "stub"


def _resolved_inside_root(candidate: Path, rootp: Path) -> Path | None:
    """Resolve a symlink candidate; ``None`` when it escapes or cannot resolve."""

    try:
        resolved = candidate.resolve()
        resolved.relative_to(rootp)
    except (OSError, ValueError):
        return None
    return resolved


def _population_from_walk(
    *,
    rootp: Path,
    fallback_reason: ScopeFallbackReason | None,
    hard_excludes: tuple[str, ...],
    max_files: int,
) -> SourcePopulation:
    """Table B, column FS: one walk, stubs partitioned out afterwards."""

    walked, hard_excluded, unreadable = discover_python_files(
        str(rootp),
        hard_excludes=hard_excludes,
        max_files=max_files,
        include_stubs=True,
    )
    paths = tuple(path for path in walked if has_python_suffix(Path(path).name))
    stub_paths = tuple(
        path for path in walked if not has_python_suffix(Path(path).name)
    )
    return SourcePopulation(
        root=str(rootp),
        paths=paths,
        stub_paths=stub_paths,
        hard_excluded=hard_excluded,
        unreadable=unreadable,
        scope_source="filesystem_fallback",
        fallback_reason=fallback_reason,
    )


__all__ = ["derive_source_population"]
