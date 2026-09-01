# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import TypedDict

from ..contracts import CACHE_VERSION, DEFAULT_MAX_CACHE_SIZE_MB
from ..models import CacheEntryV3

MAX_CACHE_SIZE_BYTES = DEFAULT_MAX_CACHE_SIZE_MB * 1024 * 1024
LEGACY_CACHE_SECRET_FILENAME = ".cache_secret"
LEGACY_CACHE_MONOLITH_FILENAME = "cache.json"
_DEFAULT_WIRE_UNIT_FLOW_PROFILES = (
    0,
    "none",
    False,
    "fallthrough",
    "none",
    "none",
)


class CacheStatus(str, Enum):
    """Why a cache load did or did not warm the run.

    ``TOO_LARGE`` is deliberately absent.  It existed only while the cache was
    one JSON document that had to be read whole, and it named the pinned
    defect: a store past the cap lost the warm path on every later run.  Row
    addressing removed the premise, so no input can produce that verdict any
    more -- and a status nothing can reach is a claim the code does not keep.
    The size budget now lives on the write side (``Cache._enforce_budget``).

    ``CORRUPT`` is the former ``INVALID_JSON``, renamed with the format it
    describes: the store is not a readable cache database at all, as distinct
    from ``INVALID_TYPE``, a readable store whose contents do not decode.
    """

    OK = "ok"
    MISSING = "missing"
    UNREADABLE = "unreadable"
    CORRUPT = "corrupt"
    INVALID_TYPE = "invalid_type"
    VERSION_MISMATCH = "version_mismatch"
    PYTHON_TAG_MISMATCH = "python_tag_mismatch"
    FINGERPRINT_MISMATCH = "mismatch_fingerprint_version"
    INTEGRITY_FAILED = "integrity_failed"


class TrackedFiles(dict[str, CacheEntryV3]):
    """The loaded entry map, recording which keys a run actually changed.

    Row-addressed storage can write only what moved, but only if it knows what
    moved.  A plain ``dict`` cannot tell a caller's assignment from a load, so
    the store would have to re-encode every entry on every save just to
    discover that nothing changed -- paying the monolith's write amplification
    inside a row-shaped store.

    This stays a real ``dict`` on purpose.  It is the declared type of
    ``CacheData["files"]``, callers mutate it directly by subscript, and a
    ``Mapping`` wrapper would both break that type and miss the very
    assignments it needs to see.

    Only ``__setitem__`` and ``__delitem__`` are intercepted.  ``pop`` is
    deliberately NOT overridden: ``dict.pop`` is typed ``(key: object, ...)``
    and narrowing that to ``str`` is a Liskov violation both type checkers
    reject.  Callers that need tracked removal use ``del``; ``store.py`` is the
    only such caller.
    """

    __slots__ = ("deleted", "dirty")

    def __init__(self) -> None:
        super().__init__()
        self.dirty: set[str] = set()
        self.deleted: set[str] = set()

    def __setitem__(self, key: str, value: CacheEntryV3) -> None:
        super().__setitem__(key, value)
        self.dirty.add(key)
        self.deleted.discard(key)

    def __delitem__(self, key: str) -> None:
        super().__delitem__(key)
        self.dirty.discard(key)
        self.deleted.add(key)

    def mark_persisted(self) -> None:
        """Declare the in-memory map and the store to be in agreement."""

        self.dirty.clear()
        self.deleted.clear()


class CacheData(TypedDict):
    version: str
    python_tag: str
    fingerprint_version: str
    files: dict[str, CacheEntryV3]


def _empty_cache_data(
    *,
    version: str = CACHE_VERSION,
    python_tag: str,
    fingerprint_version: str,
) -> CacheData:
    return CacheData(
        version=version,
        python_tag=python_tag,
        fingerprint_version=fingerprint_version,
        files=TrackedFiles(),
    )


def new_tracked_files() -> TrackedFiles:
    """A fresh tracking map, built the way ``CacheData`` already is.

    ``Cache`` reaches its entry map through this factory rather than naming
    ``TrackedFiles`` itself, matching how it already reaches ``CacheData``
    through ``_empty_cache_data``: the store owns cache policy, this module
    owns the shapes that policy is expressed in.
    """

    return TrackedFiles()


def mark_deleted(data: CacheData, key: str) -> None:
    """Record a removal for a key that was never materialised in memory.

    Pruning works off the identity register, so it can name a row the
    in-memory map has never seen. Without this the save would keep a row for
    a file the repository no longer has.
    """

    files = data["files"]
    if isinstance(files, TrackedFiles):
        files.dirty.discard(key)
        files.deleted.add(key)


def tracked_files(data: CacheData) -> TrackedFiles | None:
    """The tracking map behind ``data['files']``, when it still is one."""

    files = data["files"]
    return files if isinstance(files, TrackedFiles) else None


def _resolve_root(root: str | Path | None) -> Path | None:
    if root is None:
        return None
    try:
        return Path(root).resolve(strict=False)
    except OSError:
        return None


__all__ = [
    "CACHE_VERSION",
    "LEGACY_CACHE_MONOLITH_FILENAME",
    "LEGACY_CACHE_SECRET_FILENAME",
    "MAX_CACHE_SIZE_BYTES",
    "_DEFAULT_WIRE_UNIT_FLOW_PROFILES",
    "CacheData",
    "CacheStatus",
    "TrackedFiles",
    "_empty_cache_data",
    "_resolve_root",
    "mark_deleted",
    "new_tracked_files",
    "tracked_files",
]
