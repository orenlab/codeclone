# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The one rule for a path a repository's links may lead out of the repository.

A path spelled inside the analysed repository is the repository's ground: a
link the repository committed on the way to it -- the last component or any
directory before it -- must not carry a read or a write to a file elsewhere on
disk. A path spelled outside the repository is the caller's own word and is
left alone. Every surface asks this question through this module, so the CLI
and the MCP server cannot drift apart.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import NamedTuple


class RepositoryRoots(NamedTuple):
    """The repository root as the caller spelled it and as it resolves."""

    spelled: Path
    resolved: Path


class LinkLeavesRepositoryError(ValueError):
    """A path spelled inside the repository that a symbolic link leads out of it."""

    def __init__(self, path: Path, detail: str) -> None:
        super().__init__(
            f"{path} is inside the repository, but a symbolic link on the way "
            f"leaves it ({detail})"
        )
        self.path = path
        self.detail = detail


def spelled_inside_resolves_outside(
    spelled: Path, resolved: Path, roots: RepositoryRoots
) -> bool:
    """A path the caller spelled inside the repository that a link leads out of it.

    ``os.path.abspath`` anchors and normalises the spelling without following
    links; it is compared with both forms of the root, so a checkout that itself
    sits behind a linked ``/var`` or ``/tmp`` is judged by its real location.
    """

    anchored = Path(os.path.abspath(spelled))
    spelled_inside = anchored.is_relative_to(roots.spelled) or anchored.is_relative_to(
        roots.resolved
    )
    return spelled_inside and not resolved.is_relative_to(roots.resolved)


def link_on_the_way(path: Path) -> bool:
    """Whether any existing component of *path* is a link, or cannot be seen."""

    absolute = Path(os.path.abspath(path))
    for component in (*reversed(absolute.parents), absolute):
        try:
            mode = os.lstat(component).st_mode
        except FileNotFoundError:
            return False
        except OSError:
            return True
        if stat.S_ISLNK(mode):
            return True
    return False


def refuse_link_leaving_repository(path: Path, roots: RepositoryRoots) -> None:
    """Raise :class:`LinkLeavesRepositoryError` when a link leads *path* out.

    A path that cannot be resolved can only escape through a link: with no
    link on the way it stays where it is spelled; with a link that cannot be
    followed, a failed observation is not evidence that it stays inside.
    """

    try:
        resolved = path.resolve()
    except (OSError, RuntimeError):
        if link_on_the_way(path):
            raise LinkLeavesRepositoryError(
                path, "a link on the way cannot be resolved"
            ) from None
        return
    if spelled_inside_resolves_outside(path, resolved, roots):
        raise LinkLeavesRepositoryError(path, f"it leads to {resolved}")


__all__ = [
    "LinkLeavesRepositoryError",
    "RepositoryRoots",
    "link_on_the_way",
    "refuse_link_leaving_repository",
    "spelled_inside_resolves_outside",
]
