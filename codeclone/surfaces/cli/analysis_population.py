# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Which unanalysed files a gate may be evaluated without, and which it may not.

A file that was found and not analysed is missing from every finding and
metric a gate judges. In gating mode such a file fails the run with a contract
error, whatever the reason -- over the size limit, unreadable, failed inside
the worker, gone before its stat, or a reason nobody named. The one exception
is a file this interpreter rejected for its syntax, and only when the trusted
caller named that very file on the command line: it is then excluded, listed
by name, and counted apart from the verified files.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ...core._types import SKIP_KIND_SYNTAX_ERROR, FileFailure
from .startup import RepositoryRoots

#: The skip reasons the trusted caller may exclude from a gate, file by file.
#: This is the one per-reason decision: every reason not listed here -- and
#: every reason no module has proven -- fails a gate, and no exclusion moves it.
EXCLUDABLE_SKIP_KINDS: Final = frozenset({SKIP_KIND_SYNTAX_ERROR})


class ExclusionPathError(ValueError):
    """A ``--allow-syntax-error`` path that does not name one analysed file."""

    def __init__(self, path: str, reason: str) -> None:
        super().__init__(f"{path}: {reason}")
        self.path = path
        self.reason = reason


#: Why an exclusion path is refused before anything is excluded.
REASON_PARENT_COMPONENT = "a path with '..' is not accepted; name the file directly"
REASON_OUTSIDE_ROOT = "it is not inside the analysed root"
REASON_NOT_DISCOVERED = "it is not a file this run found in the analysed root"


@dataclass(frozen=True, slots=True)
class GatePopulation:
    """The unanalysed files of a run, sorted by what a gate may do with them."""

    #: Failure lines that fail a gate.
    blocking: tuple[str, ...]
    #: ``(root-relative path, skip kind)`` the caller excluded, each a proven
    #: syntax error of the file's own text.
    excluded: tuple[tuple[str, str], ...]
    #: Named by the caller, but skipped for a reason that cannot be excluded.
    not_excludable: tuple[tuple[str, str], ...]
    #: Named by the caller: a discovered file that was analysed after all.
    unused: tuple[str, ...]


def allowed_relative_paths(
    raw_paths: Iterable[str], roots: RepositoryRoots
) -> frozenset[str]:
    """The caller's ``--allow-syntax-error`` paths, relative to the root.

    A path is the user's word on the command line, so it is anchored at the
    current directory and never resolved through links. A ``..`` component is
    refused rather than normalised away, and the path must lie inside the
    analysed root.
    """

    relative: set[str] = set()
    for raw in raw_paths:
        spelled = Path(raw).expanduser()
        if ".." in spelled.parts:
            raise ExclusionPathError(raw, REASON_PARENT_COMPONENT)
        candidate = Path(os.path.abspath(spelled))
        for root in (roots.spelled, roots.resolved):
            if candidate.is_relative_to(root):
                relative.add(candidate.relative_to(root).as_posix())
                break
        else:
            raise ExclusionPathError(raw, REASON_OUTSIDE_ROOT)
    return frozenset(relative)


def resolve_gate_population(
    *,
    discovered: Sequence[str],
    failures: Sequence[FileFailure],
    traversal_failures: Sequence[str],
    allowed: frozenset[str],
    resolved_root: Path,
) -> GatePopulation:
    """Sort every unanalysed file into blocking or excluded.

    Each allowed path must be one file this run discovered, by its exact
    root-relative path: an exclusion that names nothing is a mistake the user
    must see, so it is refused (:class:`ExclusionPathError`).

    *traversal_failures* are discovery's skips: its only skip path is a failed
    ``stat`` of a walked file, a failure to observe the declared population,
    which no exclusion covers.
    """

    known = {_relative_to_root(path, resolved_root) for path in discovered}
    for path in sorted(allowed - known):
        raise ExclusionPathError(path, REASON_NOT_DISCOVERED)
    blocking: list[str] = list(traversal_failures)
    excluded: list[tuple[str, str]] = []
    not_excludable: list[tuple[str, str]] = []
    matched: set[str] = set()
    for failure in failures:
        relative = _relative_to_root(failure.filepath, resolved_root)
        if relative in allowed:
            matched.add(relative)
            if failure.kind in EXCLUDABLE_SKIP_KINDS:
                excluded.append((relative, failure.kind))
                continue
            not_excludable.append((relative, failure.kind))
        blocking.append(failure.message)
    return GatePopulation(
        blocking=tuple(blocking),
        excluded=tuple(sorted(excluded)),
        not_excludable=tuple(sorted(not_excludable)),
        unused=tuple(sorted(allowed - matched)),
    )


def _relative_to_root(filepath: str, resolved_root: Path) -> str:
    # The walk yields every file under the resolved root, so this never fails;
    # if it did, the ValueError would end the run rather than skip a file.
    return Path(filepath).relative_to(resolved_root).as_posix()


__all__ = [
    "EXCLUDABLE_SKIP_KINDS",
    "ExclusionPathError",
    "GatePopulation",
    "allowed_relative_paths",
    "resolve_gate_population",
]
