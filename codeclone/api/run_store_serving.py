# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The R3 door through which a surface serves one run out of the run store.

The consumer is the MCP surface (ring ``r4``), which may not import the
canonical package or the core producer edge (both ``r2``); the store, the
projection and the rollout resolver all live there.  This door carries the
one operation the surface needs — *give me this execution's served slices
out of the store, or tell me typed why not* — and the DTO that answers it.

**The answer is always typed, and it never takes the tool down.**  A store
that is not there, a run it does not hold, a file written by another
generation, a corrupted row, a stored row the projection cannot express:
each is a REASON the caller can branch on and count, and each is the
producer's own typed refusal underneath — nothing here classifies an
arbitrary exception.  A defect that is none of those propagates raw, as a
defect should.

**The rollout flag stays the kill switch.**  The store path is resolved
here, from the same resolver the publish path used
(:func:`~codeclone.core.canonical_snapshot.resolve_run_store_config`), so a
flag turned off after an execution published makes the surface serve from
memory with ``store_disabled`` — nobody reads a store the rollout does not
name.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ..canonical.errors import (
    UNKNOWN_RUN_STORE_ABSENT,
    CanonicalModelError,
    StoreCompatibilityError,
    StoreIntegrityError,
    UnknownRunError,
)
from ..canonical.serving import (
    ServedRunSlices,
    ServedUnitLocation,
    read_served_run_slices,
)
from ..canonical.store import RunStore
from ..core.canonical_snapshot import resolve_run_store_config
from ..models import RunSnapshotLink

SERVING_SOURCE_RUN_STORE: Final = "run_store"
SERVING_SOURCE_MEMORY: Final = "memory"
SERVING_SOURCES: Final[tuple[str, ...]] = (
    SERVING_SOURCE_MEMORY,
    SERVING_SOURCE_RUN_STORE,
)

#: Why the served slices came from where they came from.  ``served`` is the
#: one store-backed reason; every other reason names a memory-backed answer
#: and says which gate closed the store, so a rollout can be read off the
#: distribution of reasons rather than guessed from a single source flag.
SERVING_REASON_SERVED: Final = "served"
SERVING_REASON_NOT_PUBLISHED: Final = "not_published"
SERVING_REASON_STORE_DISABLED: Final = "store_disabled"
SERVING_REASON_STORE_ABSENT: Final = "store_absent"
SERVING_REASON_RUN_NOT_PUBLISHED: Final = "run_not_published"
SERVING_REASON_INCOMPATIBLE_GENERATION: Final = "incompatible_generation"
SERVING_REASON_INTEGRITY: Final = "integrity"
SERVING_REASON_UNEXPRESSIBLE: Final = "unexpressible"
SERVING_REASON_DIVERGENT: Final = "divergent"
SERVING_REASONS: Final[tuple[str, ...]] = (
    SERVING_REASON_DIVERGENT,
    SERVING_REASON_INCOMPATIBLE_GENERATION,
    SERVING_REASON_INTEGRITY,
    SERVING_REASON_NOT_PUBLISHED,
    SERVING_REASON_RUN_NOT_PUBLISHED,
    SERVING_REASON_SERVED,
    SERVING_REASON_STORE_ABSENT,
    SERVING_REASON_STORE_DISABLED,
    SERVING_REASON_UNEXPRESSIBLE,
)

#: The reasons under which memory is the RIGHT answer rather than a fallback:
#: nothing was published for this execution, or the rollout is off.  Every
#: other memory-backed reason is a fallback and is counted as one.
MEMORY_BY_DESIGN_REASONS: Final[frozenset[str]] = frozenset(
    {SERVING_REASON_NOT_PUBLISHED, SERVING_REASON_STORE_DISABLED}
)


@dataclass(frozen=True, slots=True, kw_only=True)
class RunStoreServingOutcome:
    """Where one execution's served slices came from, and why."""

    source: str
    reason: str
    store_run_id: str = ""
    detail: str = ""

    def __post_init__(self) -> None:
        if self.source not in SERVING_SOURCES:
            raise ValueError(f"unknown serving source: {self.source!r}")
        if self.reason not in SERVING_REASONS:
            raise ValueError(f"unknown serving reason: {self.reason!r}")
        if (self.source == SERVING_SOURCE_RUN_STORE) != (
            self.reason == SERVING_REASON_SERVED
        ):
            raise ValueError("a store-backed answer is served and nothing else is")

    def as_payload(self) -> dict[str, object]:
        """The provenance block a served response carries."""
        payload: dict[str, object] = {"source": self.source, "reason": self.reason}
        if self.store_run_id:
            payload["store_run_id"] = self.store_run_id
        if self.detail:
            payload["detail"] = self.detail
        return payload


def _memory(
    reason: str, *, store_run_id: str = "", detail: str = ""
) -> tuple[None, RunStoreServingOutcome]:
    return None, RunStoreServingOutcome(
        source=SERVING_SOURCE_MEMORY,
        reason=reason,
        store_run_id=store_run_id,
        detail=detail,
    )


def read_run_store_slices(
    *, root: Path, link: RunSnapshotLink | None
) -> tuple[ServedRunSlices | None, RunStoreServingOutcome]:
    """The store's answer for one execution, or a typed reason for none.

    ``link`` is the execution's own publication witness: an execution that
    stored nothing has no run to read, and that is ``not_published`` — the
    memory answer by design, not a fallback.  The store is opened with
    ``create=False``: a read must never bring a store into existence to
    answer that it holds nothing.
    """
    if link is None or not link.store_run_id:
        return _memory(
            SERVING_REASON_NOT_PUBLISHED,
            detail="" if link is None else link.outcome,
        )
    config = resolve_run_store_config(root=root)
    if not config.enabled or config.path is None:
        return _memory(SERVING_REASON_STORE_DISABLED, store_run_id=link.store_run_id)
    try:
        with RunStore(config.path, create=False) as store:
            slices = read_served_run_slices(store, link.store_run_id, root=root)
    except UnknownRunError as refusal:
        reason = (
            SERVING_REASON_STORE_ABSENT
            if refusal.reason == UNKNOWN_RUN_STORE_ABSENT
            else SERVING_REASON_RUN_NOT_PUBLISHED
        )
        return _memory(reason, store_run_id=link.store_run_id, detail=str(refusal))
    except StoreCompatibilityError as refusal:
        return _memory(
            SERVING_REASON_INCOMPATIBLE_GENERATION,
            store_run_id=link.store_run_id,
            detail=str(refusal),
        )
    except StoreIntegrityError as refusal:
        return _memory(
            SERVING_REASON_INTEGRITY,
            store_run_id=link.store_run_id,
            detail=str(refusal),
        )
    except CanonicalModelError as refusal:
        return _memory(
            SERVING_REASON_UNEXPRESSIBLE,
            store_run_id=link.store_run_id,
            detail=str(refusal),
        )
    return slices, RunStoreServingOutcome(
        source=SERVING_SOURCE_RUN_STORE,
        reason=SERVING_REASON_SERVED,
        store_run_id=link.store_run_id,
    )


__all__ = [
    "MEMORY_BY_DESIGN_REASONS",
    "SERVING_REASONS",
    "SERVING_REASON_DIVERGENT",
    "SERVING_REASON_INCOMPATIBLE_GENERATION",
    "SERVING_REASON_INTEGRITY",
    "SERVING_REASON_NOT_PUBLISHED",
    "SERVING_REASON_RUN_NOT_PUBLISHED",
    "SERVING_REASON_SERVED",
    "SERVING_REASON_STORE_ABSENT",
    "SERVING_REASON_STORE_DISABLED",
    "SERVING_REASON_UNEXPRESSIBLE",
    "SERVING_SOURCES",
    "SERVING_SOURCE_MEMORY",
    "SERVING_SOURCE_RUN_STORE",
    "RunStoreServingOutcome",
    "ServedRunSlices",
    "ServedUnitLocation",
    "read_run_store_slices",
]
