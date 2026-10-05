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
defect should.  What is NOT a defect, and was measured escaping as one
(storage audit RS-04, 2026-09-24): a store another process holds the write
lock on, a read-only medium, a file at the store path that SQLite cannot
read as a database, a member stored under the wrong storage class.  The
store classifies those itself now (``StoreUnavailableError``,
``StoreIntegrityError``) and this door answers them like every other
refusal — the transient ones as ``store_unavailable``, the byte faults as
``integrity`` — because a shadow read that holds the memory answer has no
business taking the tool down over a lock.

**The rollout flag stays the kill switch.**  The store path is resolved
here, from the same resolver the publish path used
(:func:`~codeclone.core.canonical_snapshot.resolve_run_store_config`), so a
flag turned off after an execution published makes the surface serve from
memory with ``store_disabled`` — nobody reads a store the rollout does not
name.

**Two roads name the store run, and the answer says which.**  The record
of the execution that published carries the store address in RAM (the
publication lane).  Every other process holds only the report half of the
relation — the evaluated identity and the scope receipt its own document
re-derives — and the door completes it against the store's persisted index
(``run_report_links``, the identity bridge), holding the edge it finds to
that receipt.  A served answer that came over the bridge says so in
``detail``; a wrong, ambiguous or missing edge fails closed with a reason
this vocabulary already has, and nothing is ever looked up "by a similar
scope".

**One road, five readings.**  What is read at the end of the road is the
only thing that differs between the door's operations: the three served
slices (``search_graph``, ``get_implementation_context``), the authority
candidate rows (``check_authority(section="candidates")``), the run
summary's store-carried blocks (``get_run_summary``, consumer migration
C1), the facts one run lends the patch contract (``check_patch_contract``
and the verification ``finish_controlled_change`` runs, consumer migration
C6) and the facts a blast radius is computed from (``get_blast_radius`` and
the radius ``start_controlled_change`` declares against, consumer migration
C7).  The gates, the two roads, the one store open and the refusal
vocabulary are written once, in :func:`_read_published`, and every
operation is that function with a different reader -- so a consumer that
moves onto the store cannot bring a second resolution with its own idea of
what ``served`` means.

**The serving switch** (:data:`ENV_SERVE_FROM`) is the per-consumer return
road of the consumer-migration program, and it is temporary: a consumer
that moved onto the store goes back to memory under ``memory`` without the
store being read, and says so (``store_disabled``, the switch named in
``detail``).  It is honoured by the migrated consumers only -- the run
summary, patch verification and the blast radius today -- and is removed
with the last consumer's cutover, no later than 2026-11-30.  The
publication flag above stays the kill switch of every reading.

**The run summary's comparison fields** state a number only for a
comparison the run made (ruling 2026-10-03, "not compared -> null").  The
decision has one owner, ``canonical.comparison_projection``, read by the
store's reading here and by the surface's memory answer alike; this door
hands the surface the memory half -- the state read back off the sealed
document (:func:`document_comparison_state`) and the same rule
(:func:`answered_if_compared`) -- so the two answers cannot apply two copies
of the rule.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeVar

from ..canonical.blast_radius_facts import BlastRadiusFacts
from ..canonical.comparison_projection import (
    SUMMARY_DIFF_BLOCK,
    SUMMARY_HEALTH_BLOCK,
    answered_if_compared,
)
from ..canonical.comparison_state import document_comparison_state
from ..canonical.errors import (
    UNKNOWN_RUN_STORE_ABSENT,
    CanonicalModelError,
    RunReportLinkError,
    StoreCompatibilityError,
    StoreIntegrityError,
    StoreUnavailableError,
    UnknownRunError,
)
from ..canonical.serving import (
    ServedAuthorityCandidates,
    ServedPatchRun,
    ServedRunSlices,
    ServedRunSummary,
    ServedUnitLocation,
    read_served_authority_candidates,
    read_served_blast_radius_facts,
    read_served_patch_run,
    read_served_run_slices,
    read_served_run_summary,
)
from ..canonical.store import RunStore
from ..core.canonical_snapshot import resolve_run_store_config, verified_linked_run
from ..models import RunSnapshotLink

_ReadT = TypeVar("_ReadT")

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
#: The store is there and is this generation, and SQLite could not serve it
#: NOW: a held lock, a read-only medium, an I/O fault.  A fallback the
#: surface counts — never memory by design — and the one reason that says
#: "try again" rather than "regenerate" or "delete".
SERVING_REASON_STORE_UNAVAILABLE: Final = "store_unavailable"
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
    SERVING_REASON_STORE_UNAVAILABLE,
    SERVING_REASON_UNEXPRESSIBLE,
)

#: ``serving.detail`` on a store-backed answer whose run the record did NOT
#: name: the report half of the relation (identity and scope receipt) was
#: completed against the store's persisted index.  A publication-lane answer
#: carries no detail, so the two roads to ``served`` stay distinguishable in
#: the payload without a second reason word.
SERVING_DETAIL_IDENTITY_BRIDGE: Final = "identity_bridge"

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

    ``link`` is the execution's bridge witness, and it names the store run
    on one of two roads:

    * the PUBLICATION lane -- this execution published, the link carries
      the store address, and the store is read at it;
    * the IDENTITY BRIDGE -- the link carries only the report half (the
      evaluated identity and the scope receipt its document re-derives:
      the shape every process but the publisher holds), and the store's
      persisted index is asked which published run answers that identity.
      The edge must carry the receipt the link holds, or it is refused
      (``integrity``, as is a second edge for one identity); no edge is
      ``run_not_published``, and no run is ever chosen by a similar scope.

    A ``None`` link is a record that stated no bridge at all, and a report
    half under a rollout that names no store is memory by design: nobody
    reads a store the rollout does not name.  The store is opened with
    ``create=False`` -- a read must never bring a store into existence to
    answer that it holds nothing -- and ONCE per call: the edge and the rows
    it addresses are read on one handle, so a run swept between two opens
    cannot turn a verified edge into a wrong answer.
    """

    def read(store: RunStore, store_run_id: str) -> ServedRunSlices:
        return read_served_run_slices(store, store_run_id, root=root)

    return _read_published(root=root, link=link, read=read)


def read_run_store_authority_candidates(
    *, root: Path, link: RunSnapshotLink | None
) -> tuple[ServedAuthorityCandidates | None, RunStoreServingOutcome]:
    """The store's candidate rows for one execution, or a typed reason for none.

    The same gates, the same two roads and the same one store open as
    :func:`read_run_store_slices` -- only the reading differs.  A run that
    did not MEASURE its authority candidates (the semantic lane did not run
    to completion) is refused ``unexpressible``: its candidate family is
    empty in the store, and an empty family the run never measured is not
    an answer of "no candidates".
    """
    return _read_published(root=root, link=link, read=read_served_authority_candidates)


#: The serving switch of the migrated consumers (module docstring): one
#: name, spelled once, read from the environment on every call like the
#: publication flag.
ENV_SERVE_FROM: Final = "CODECLONE_SERVE_FROM"
SERVE_FROM_MEMORY: Final = "memory"
SERVE_FROM_RUN_STORE: Final = "run_store"
SERVE_FROM_SOURCES: Final[tuple[str, ...]] = (SERVE_FROM_MEMORY, SERVE_FROM_RUN_STORE)
#: Where a migrated consumer reads when the switch names neither source:
#: memory until the consumer's cutover.
SERVE_FROM_DEFAULT: Final = SERVE_FROM_MEMORY


def serving_source(environ: Mapping[str, str] | None = None) -> str:
    """The source the serving switch names, or the default for any other
    value (an unset or misspelled switch never reads a store it was not
    asked to)."""
    env = os.environ if environ is None else environ
    value = env.get(ENV_SERVE_FROM, "").strip().lower()
    return value if value in SERVE_FROM_SOURCES else SERVE_FROM_DEFAULT


def read_run_store_summary(
    *, root: Path, link: RunSnapshotLink | None
) -> tuple[ServedRunSummary | None, RunStoreServingOutcome]:
    """The store-carried blocks of one execution's run summary, or a typed
    reason for none.

    The same gates, the same two roads and the same one store open as
    :func:`read_run_store_slices`, behind the serving switch: a record that
    stated a bridge is answered from memory without a store read while the
    switch names memory, and the answer names the switch.
    """
    source = serving_source()
    if link is not None and source == SERVE_FROM_MEMORY:
        return _memory(
            SERVING_REASON_STORE_DISABLED,
            store_run_id=link.store_run_id,
            detail=f"{ENV_SERVE_FROM}={source}",
        )
    return _read_published(root=root, link=link, read=read_served_run_summary)


#: The store's own typed refusals and the reason each one is answered with,
#: in the order a refusal is matched -- the ONE table the door branches on,
#: so a new refusal class lands here as a row and never as a new clause.
#:
#: ``StoreCompatibilityError`` is also the incomplete-schema refusal
#: (``StoreSchemaIncompleteError`` narrows it): a store of this generation
#: that lacks a table or an index this build declares cannot be opened as it
#: stands, the same question a foreign witness answers, and nothing in it is
#: corrupt -- so ``incompatible_generation``, never ``integrity``; the detail
#: carries the refusal's own words, the one command that completes the store
#: included, and the door runs it for nobody.  ``StoreIntegrityError`` is a
#: stored row that fails its digest, a file SQLite cannot read as a database
#: or a member under the wrong storage class: all statements about the BYTES
#: at the store path, all one word.  ``StoreUnavailableError`` is the bytes
#: and the generation both fine and SQLite unable to serve them at this
#: moment (another process's write lock, a read-only medium, an I/O fault):
#: neither ``integrity`` nor ``incompatible_generation`` would be true, and
#: the memory answer the surface holds is the right one to give right now.
#: ``CanonicalModelError`` is a stored row the projection cannot express.
_REFUSAL_REASONS: Final[tuple[tuple[type[Exception], str], ...]] = (
    (StoreCompatibilityError, SERVING_REASON_INCOMPATIBLE_GENERATION),
    (StoreIntegrityError, SERVING_REASON_INTEGRITY),
    (StoreUnavailableError, SERVING_REASON_STORE_UNAVAILABLE),
    (CanonicalModelError, SERVING_REASON_UNEXPRESSIBLE),
)
_STORE_REFUSALS: Final[tuple[type[Exception], ...]] = tuple(
    refusal for refusal, _reason in _REFUSAL_REASONS
)


def _refusal_reason(refusal: Exception) -> str:
    """The reason word of one typed store refusal, off the one table."""
    return next(
        reason for kind, reason in _REFUSAL_REASONS if isinstance(refusal, kind)
    )


def _read_published(
    *,
    root: Path,
    link: RunSnapshotLink | None,
    read: Callable[[RunStore, str], _ReadT],
) -> tuple[_ReadT | None, RunStoreServingOutcome]:
    """The gates, then one store answer through ``read``, or a typed reason."""
    if link is None:
        return _memory(SERVING_REASON_NOT_PUBLISHED)
    config = resolve_run_store_config(root=root)
    if not config.enabled or config.path is None:
        if link.store_run_id:
            return _memory(
                SERVING_REASON_STORE_DISABLED, store_run_id=link.store_run_id
            )
        return _memory(SERVING_REASON_NOT_PUBLISHED, detail=link.outcome)
    if not link.store_run_id and not link.report_run_identity:
        # Unevaluated and unstored: no half to complete, nothing to read.
        return _memory(SERVING_REASON_NOT_PUBLISHED, detail=link.outcome)
    return _store_answer(config.path, link=link, read=read)


def _store_answer(
    path: Path,
    *,
    link: RunSnapshotLink,
    read: Callable[[RunStore, str], _ReadT],
) -> tuple[_ReadT | None, RunStoreServingOutcome]:
    """One store open, one answer: at the record's address, or over the bridge."""
    store_run_id = link.store_run_id
    detail = ""
    try:
        with RunStore(path, create=False) as store:
            if not store_run_id:
                edge = verified_linked_run(
                    store,
                    report_run_identity=link.report_run_identity,
                    analysis_scope_digest=link.analysis_scope_digest,
                )
                if edge is None:
                    return _memory(
                        SERVING_REASON_RUN_NOT_PUBLISHED,
                        detail=(
                            "no published run of this store answers report "
                            f"{link.report_run_identity[:12]}"
                        ),
                    )
                store_run_id = edge.run_id
                detail = SERVING_DETAIL_IDENTITY_BRIDGE
            answer = read(store, store_run_id)
    except UnknownRunError as refusal:
        reason = (
            SERVING_REASON_STORE_ABSENT
            if refusal.reason == UNKNOWN_RUN_STORE_ABSENT
            else SERVING_REASON_RUN_NOT_PUBLISHED
        )
        return _memory(reason, store_run_id=store_run_id, detail=str(refusal))
    except RunReportLinkError as refusal:
        # The persisted index cannot be trusted for this identity: two edges,
        # or an edge whose run carries another scope receipt.  An index row
        # that fails its own evidence is the class a stored row that fails
        # its digest belongs to, and it gets the same word.
        return _memory(SERVING_REASON_INTEGRITY, detail=str(refusal))
    except _STORE_REFUSALS as refusal:
        return _memory(
            _refusal_reason(refusal), store_run_id=store_run_id, detail=str(refusal)
        )
    return answer, RunStoreServingOutcome(
        source=SERVING_SOURCE_RUN_STORE,
        reason=SERVING_REASON_SERVED,
        store_run_id=store_run_id,
        detail=detail,
    )


def read_run_store_blast_radius_facts(
    *, root: Path, link: RunSnapshotLink | None
) -> tuple[BlastRadiusFacts | None, RunStoreServingOutcome]:
    """The facts one execution's blast radius is computed from, out of the
    store, or a typed reason for none (consumer migration C7).

    The same gates, the same two roads and the same one store open as
    :func:`read_run_store_slices`, behind the same serving switch as
    :func:`read_run_store_summary`: a record that stated a bridge is
    answered from memory without a store read while the switch names
    memory, and the answer names the switch.
    """
    source = serving_source()
    if link is not None and source == SERVE_FROM_MEMORY:
        return _memory(
            SERVING_REASON_STORE_DISABLED,
            store_run_id=link.store_run_id,
            detail=f"{ENV_SERVE_FROM}={source}",
        )
    return _read_published(root=root, link=link, read=read_served_blast_radius_facts)


__all__ = [
    "ENV_SERVE_FROM",
    "MEMORY_BY_DESIGN_REASONS",
    "SERVE_FROM_DEFAULT",
    "SERVE_FROM_MEMORY",
    "SERVE_FROM_RUN_STORE",
    "SERVE_FROM_SOURCES",
    "SERVING_DETAIL_IDENTITY_BRIDGE",
    "SERVING_REASONS",
    "SERVING_REASON_DIVERGENT",
    "SERVING_REASON_INCOMPATIBLE_GENERATION",
    "SERVING_REASON_INTEGRITY",
    "SERVING_REASON_NOT_PUBLISHED",
    "SERVING_REASON_RUN_NOT_PUBLISHED",
    "SERVING_REASON_SERVED",
    "SERVING_REASON_STORE_ABSENT",
    "SERVING_REASON_STORE_DISABLED",
    "SERVING_REASON_STORE_UNAVAILABLE",
    "SERVING_REASON_UNEXPRESSIBLE",
    "SERVING_SOURCES",
    "SERVING_SOURCE_MEMORY",
    "SERVING_SOURCE_RUN_STORE",
    "SUMMARY_DIFF_BLOCK",
    "SUMMARY_HEALTH_BLOCK",
    "BlastRadiusFacts",
    "RunStoreServingOutcome",
    "ServedAuthorityCandidates",
    "ServedRunSlices",
    "ServedRunSummary",
    "ServedUnitLocation",
    "answered_if_compared",
    "document_comparison_state",
    "read_run_store_authority_candidates",
    "read_run_store_blast_radius_facts",
    "read_run_store_slices",
    "read_run_store_summary",
    "serving_source",
]


def read_run_store_patch_run(
    *, root: Path, link: RunSnapshotLink | None
) -> tuple[ServedPatchRun | None, RunStoreServingOutcome]:
    """The facts one run lends ``check_patch_contract``, or a typed reason
    for none (consumer migration C6).

    The same gates, the same two roads, the same one store open and the same
    serving switch as :func:`read_run_store_summary`: a record that stated a
    bridge is answered from memory without a store read while the switch
    names memory.  The verifier reads two runs; each is its own call through
    this door, so each carries its own outcome.
    """
    source = serving_source()
    if link is not None and source == SERVE_FROM_MEMORY:
        return _memory(
            SERVING_REASON_STORE_DISABLED,
            store_run_id=link.store_run_id,
            detail=f"{ENV_SERVE_FROM}={source}",
        )
    return _read_published(root=root, link=link, read=read_served_patch_run)


__all__ += [
    "ServedPatchRun",
    "read_run_store_patch_run",
]
