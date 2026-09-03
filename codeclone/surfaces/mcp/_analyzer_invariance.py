# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Did the after-run actually read the bytes it is offered as evidence for?

A repeated run id proves the analysis facts did not move. It does not, on its
own, prove *when* the analysis ran: a recompute taken between declaring the
intent and making the edit is equally fresh and equally identical, while
having read none of the change.

What settles it is what the run recorded about the files the patch claims to
have changed. Two lanes carry that, in decreasing strength:

* the run's content manifest — the sha256 of every source file whose facts
  the run holds, taken from the bytes the worker parsed, or proven against a
  cache entry before its facts were reused. A recorded digest that no longer
  matches disk is positive evidence the run did not read these bytes, so it
  is a refusal, not missing evidence. The stat manifest is consulted only for
  membership: a file the run scanned but holds no digest for was never
  analysis input, and is refused the same way. Stat is never evidence.
  ``(mtime_ns, size)`` survives a same-size rewrite followed by ``os.utime``,
  and ``cp -p``, ``rsync -t``, ``tar -x`` and restore-from-snapshot harnesses
  leave exactly that pair behind; measured 2026-09-02, a structural rewrite
  padded to the recorded size was accepted as analyzer_invariant while the
  very next analysis moved the run id.
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
model layer for a digest string.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path


def observation_evidence(
    *,
    root: Path,
    changed_files: Sequence[str],
    manifest: Mapping[str, object] | None,
    content_manifest: Mapping[str, object] | None,
    dirty_paths: frozenset[str],
    before_content_manifest: Mapping[str, object] | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Classify each changed path by what the after-run recorded about it.

    Returns ``(contradicted, unobserved)``. A non-empty *contradicted* means
    the run demonstrably did not read the bytes now on disk and must be
    refused. *unobserved* is missing evidence, not counter-evidence, and
    belongs in the caller's stated limitations.

    With the before-run's content witness, a path both executions recorded
    under the same digest is *unobserved* as well: the after-run read the
    bytes on disk, but so did the before-run, so the pair witnessed no change
    there -- the edit either never reached this file or predates the
    before-run, and neither is evidence about this patch.
    """

    scanned = manifest or {}
    recorded = content_manifest or {}
    recorded_before = before_content_manifest or {}
    contradicted: list[str] = []
    unobserved: list[str] = []
    for path in sorted({_normalize(item) for item in changed_files if item}):
        digest = recorded.get(path)
        if digest is not None or path in scanned:
            if not _recorded_content_matches_disk(root=root, path=path, digest=digest):
                contradicted.append(path)
            elif digest is not None and recorded_before.get(path) == digest:
                unobserved.append(path)
            continue
        if path not in dirty_paths:
            unobserved.append(path)
    return tuple(contradicted), tuple(unobserved)


def _recorded_content_matches_disk(*, root: Path, path: str, digest: object) -> bool:
    """Are the bytes on disk the bytes the run recorded a digest for?

    Anything unreadable — a missing digest, a malformed one, a file that
    cannot be read — counts as a mismatch. Absence of evidence is never
    evidence that nothing moved.
    """

    try:
        current = hashlib.sha256((root / path).read_bytes()).hexdigest()
    except OSError:
        return False
    return current == digest


def _normalize(path: str) -> str:
    text = path.replace("\\", "/").strip()
    if text.startswith("./"):
        text = text[2:]
    return text.rstrip("/")


__all__ = ["observation_evidence"]
