# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The cache store's collector, under the unified GC protocol.

The cache does not get its own cleanup mechanism.  It answers the same
protocol the run store answers -- one dispatcher, different jobs -- so that
one report shape, one closed reason vocabulary and one telemetry dialect
describe every collection this process performs.  A cache that swept itself
on the side would be a second collector nobody could see from the first.

What it collects, and why each reason is the reason it is:

``corrupt``
    The identity row no longer verifies.  Nothing can be served from it and
    nothing will repair it, so it goes.

``orphaned``
    The repository no longer has that file.  Only offered when the caller
    knows the live set; a job asked without one does not guess.

``expired``
    Untouched for longer than the TTL, or the least recently used row in a
    store over its size bound.  Both are the same decision -- aged out --
    and the ``detail`` lane keeps them apart for whoever is debugging,
    because the closed vocabulary is the protocol's and the breakdown is
    this surface's.

What it never collects: a row the current generation wrote.  That is not a
policy knob.  Taking back the entries this run just produced is precisely
the defect the whole migration exists to remove, so the candidate query
excludes them and the exclusion is proved by mutation.

The size bound is served here rather than inside ``save`` for the same
reason: a bound enforced in two places is two policies that will disagree.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from ..models import (
    GC_COLLECT_CORRUPT,
    GC_COLLECT_EXPIRED,
    GC_COLLECT_ORPHANED,
    GC_HOLD_RETAINED,
    GcJobReport,
)
from ..observability import span
from .backend import CacheBackend, CacheBackendUnusable

GC_JOB_NAME: Final = "cache_store"


def collect_cache_garbage(
    *,
    path: Path,
    version: str,
    generation: int,
    now_epoch: int,
    max_bytes: int = 0,
    ttl_seconds: int = 0,
    live_wire_paths: frozenset[str] | None = None,
) -> GcJobReport:
    """Sweep the cache store once and answer with a typed report.

    Every candidate is attributed to exactly one outcome, so the report's
    arithmetic balances by construction: an entry this job cannot explain is
    an entry it does not claim to have handled.
    """

    try:
        with (
            span(name="cache.backend.prune") as prune_span,
            CacheBackend(path) as backend,
        ):
            candidates = backend.entry_count()
            corrupt = set(backend.corrupt_ids(version))
            orphaned = (
                set()
                if live_wire_paths is None
                else set(backend.orphan_ids(live_wire_paths)) - corrupt
            )
            expired: set[int] = set()
            if ttl_seconds > 0:
                expired = (
                    set(backend.expired_ids(older_than_epoch=now_epoch - ttl_seconds))
                    - corrupt
                    - orphaned
                )
            already = corrupt | orphaned | expired
            evicted = _evict_to_budget(
                backend,
                max_bytes=max_bytes,
                generation=generation,
                already=already,
            )
            expired |= evicted
            doomed = corrupt | orphaned | expired
            if doomed:
                backend.delete_by_ids(sorted(doomed))
                backend.reclaim()
            prune_span.set_counter("cache_backend_pruned", len(doomed))
            prune_span.set_counter("cache_backend_orphans", len(orphaned))
            prune_span.set_counter("db_queries", backend.queries)
            prune_span.set_counter("db_writes", backend.writes)
            prune_span.set_counter("db_rows", backend.rows)
    except CacheBackendUnusable as error:
        # The cache's own storage rolled the sweep back, so no count beside
        # this refusal could be true.
        return GcJobReport.refused(job=GC_JOB_NAME, refusal=str(error))

    return GcJobReport.build(
        job=GC_JOB_NAME,
        candidates=candidates,
        held={GC_HOLD_RETAINED: candidates - len(doomed)},
        collected={
            GC_COLLECT_CORRUPT: len(corrupt),
            GC_COLLECT_ORPHANED: len(orphaned),
            GC_COLLECT_EXPIRED: len(expired),
        },
        detail={
            "expired_by_ttl": len(expired) - len(evicted),
            "evicted_for_budget": len(evicted),
        },
    )


def _evict_to_budget(
    backend: CacheBackend,
    *,
    max_bytes: int,
    generation: int,
    already: set[int],
) -> set[int]:
    """Take the least recently written rows until the store fits its bound.

    Returns the ids it chose; the caller deletes once, so an entry counted
    under two reasons cannot be deleted twice or attributed twice.
    """

    if max_bytes <= 0:
        return set()
    remaining = backend.payload_bytes()
    if remaining <= max_bytes:
        return set()
    chosen: set[int] = set()
    for file_id, _wire_path, size in backend.eviction_candidates(generation=generation):
        if remaining <= max_bytes:
            break
        if file_id in already or file_id in chosen:
            continue
        chosen.add(file_id)
        remaining -= size
    return chosen


class CacheStoreGcJob:
    """The cache store's job under the unified GC protocol.

    Deliberately not a dataclass: the Phase 39S ratchet places every dataclass
    in the model store, and a job is behaviour with a policy attached rather
    than a record worth putting there.

    The policy is injected at construction so the orchestrator stays
    surface-blind -- it dispatches jobs and observes answers, and never learns
    that one of them is a cache.
    """

    __slots__ = (
        "_live_wire_paths",
        "_max_bytes",
        "_now_epoch",
        "_path",
        "_ttl",
        "_version",
    )

    def __init__(
        self,
        *,
        path: Path,
        version: str,
        now_epoch: int,
        max_bytes: int = 0,
        ttl_seconds: int = 0,
        live_wire_paths: frozenset[str] | None = None,
    ) -> None:
        self._path = path
        self._version = version
        self._now_epoch = now_epoch
        self._max_bytes = max_bytes
        self._ttl = ttl_seconds
        self._live_wire_paths = live_wire_paths

    @property
    def name(self) -> str:
        return GC_JOB_NAME

    def collect(self) -> GcJobReport:
        return collect_cache_garbage(
            path=self._path,
            version=self._version,
            # A job dispatched by the orchestrator is outside any save, so no
            # generation is in flight and every row is a fair candidate.
            generation=_UNBOUNDED_GENERATION,
            now_epoch=self._now_epoch,
            max_bytes=self._max_bytes,
            ttl_seconds=self._ttl,
            live_wire_paths=self._live_wire_paths,
        )


#: Larger than any generation a store can reach, so the candidate query
#: admits every row when no save is in flight.
_UNBOUNDED_GENERATION: Final = 1 << 62


__all__ = [
    "GC_JOB_NAME",
    "CacheStoreGcJob",
    "collect_cache_garbage",
]
