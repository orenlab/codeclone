# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Did the after-run actually observe the edit it is offered as evidence for?

A repeated run id proves the analysis facts did not move. It does not, on its
own, prove *when* the analysis ran: a recompute taken between declaring the
intent and making the edit is equally fresh and equally identical, while
having read none of the change.

What settles it is what the run recorded about the files the patch claims to
have changed. Two lanes carry that, in decreasing strength:

* the analysis manifest — the stat of every source file the run actually
  read. A recorded stat that no longer matches disk is positive evidence the
  run predates the edit, so it is a refusal, not missing evidence.
* the run's own dirty snapshot — paths git reported as modified when the run
  was taken. Weaker: it proves the run postdates *an* edit to that path
  rather than pinning exact bytes, and it covers files analysis never reads,
  such as ``pyproject.toml``.

Paths in neither lane are simply unobserved. That is not a contradiction and
must not be treated as one: a change committed before the recompute is
legitimately absent from both. Callers report those paths as a limitation on
what the acceptance proves.

Manifest entries are read structurally rather than through the model store's
types: this module sits on the MCP surface and must not reach across into the
model layer for a two-field stat.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path


def observation_evidence(
    *,
    root: Path,
    changed_files: Sequence[str],
    manifest: Mapping[str, object] | None,
    dirty_paths: frozenset[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Classify each changed path by what the after-run recorded about it.

    Returns ``(contradicted, unobserved)``. A non-empty *contradicted* means
    the run demonstrably predates the edit and must be refused. *unobserved*
    is missing evidence, not counter-evidence, and belongs in the caller's
    stated limitations.
    """

    recorded = manifest or {}
    contradicted: list[str] = []
    unobserved: list[str] = []
    for path in sorted({_normalize(item) for item in changed_files if item}):
        entry = recorded.get(path)
        if entry is not None:
            if not _manifest_matches_disk(root=root, path=path, entry=entry):
                contradicted.append(path)
            continue
        if path not in dirty_paths:
            unobserved.append(path)
    return tuple(contradicted), tuple(unobserved)


def _manifest_matches_disk(*, root: Path, path: str, entry: object) -> bool:
    """Does the stat the run recorded still describe the file on disk?

    Anything unreadable — a malformed entry, a file that cannot be stat'd —
    counts as a mismatch. Absence of evidence is never evidence that nothing
    moved.
    """

    if not isinstance(entry, Mapping):
        return False
    recorded_mtime = entry.get("mtime_ns")
    recorded_size = entry.get("size")
    if not isinstance(recorded_mtime, int) or not isinstance(recorded_size, int):
        return False
    try:
        current = (root / path).stat()
    except OSError:
        return False
    return current.st_mtime_ns == recorded_mtime and current.st_size == recorded_size


def _normalize(path: str) -> str:
    text = path.replace("\\", "/").strip()
    if text.startswith("./"):
        text = text[2:]
    return text.rstrip("/")


__all__ = ["observation_evidence"]
