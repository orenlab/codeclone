# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The R3 door through which a change intent keeps its before-run in the store.

The run store's collector keeps a target's head and one previous generation,
then whatever a lease or a retention row still roots.  A run a live change
intent was declared against is none of those once two later publications
land, and nothing else protected it: a published before-run could be collected
while the cycle that names it was still open.  A lease of the store's
``session`` kind -- in the store's own words, an MCP session pinned to a run --
is that protection.  The intent takes it when it becomes active, renews it
where it renews its workspace lease, and releases it when it is cleared,
superseded or rebound; a server that dies without releasing leaves a lease the
collector dissolves at its deadline.

**One road to the store.**  A lease is asked for over the serving door's
road (:func:`codeclone.api.run_store_serving._read_published`): the same
rollout gate (the kill switch -- a store the rollout does not name is never
opened), the same two roads to the store run (the record's address, or the
report half completed against the persisted index), the same one open and the
same typed refusal vocabulary.  A lease is that road with a reader that
grants, renews or releases instead of reading, so the store's address is
resolved in one place for every consumer, and the reason words a lease
answers with are the serving door's own.

**The answer is always typed, and it never takes the cycle down.**  Every
refusal is a reason on the returned :class:`RunLeaseState`, and the change
intent proceeds exactly as it would without a store.  Two refusals are the
lease's own: the store refusing the grant itself (``lease_refused`` -- the id
already names another run or kind), and a lock another writer holds past the
busy timeout, which the store's lease writes leave raw (the run-store
contention suite pins that as its positive control) and which is answered
here exactly as the store answers it everywhere else, ``store_unavailable``.

**A lease is a write, so it obeys the surface's write boundary.**  The
door's one caller is the MCP surface, which writes only inside CodeClone's
service directories of the analysed root -- the boundary its publication
obeys (``core.canonical_snapshot.run_store_outside_boundary``, the one
decision for both).  The store the road actually opened is asked, so the
answer names the file the grant would have been written into: outside the
boundary nothing is written, and the state says so (``store_disabled`` --
this surface's writes into that store are off -- with the boundary in
``detail``).

**A lease id names one grant.**  It is built from the server session (the
agent pid and start epoch the workspace registry already identifies a session
by), a sequence the session never resets, and the intent id: two servers on one
root, or one server whose intent ids restarted, can never renew or release
each other's grant.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ..canonical.errors import (
    RunReportLinkError,
    RunStoreError,
    StoreCompatibilityError,
    StoreIntegrityError,
    StoreUnavailableError,
    UnknownRunError,
)
from ..canonical.store import RunStore, acquire_run_lease, release_run_lease
from ..core.canonical_snapshot import run_store_outside_boundary
from ..models import RunSnapshotLink
from .run_store_serving import (
    SERVING_REASON_DIVERGENT,
    SERVING_REASON_SERVED,
    SERVING_REASON_STORE_DISABLED,
    SERVING_REASONS,
    SERVING_SOURCE_MEMORY,
    RunStoreServingOutcome,
    _read_published,
)

#: The store's lease kind for "an MCP session pinned to a run".
RUN_LEASE_KIND: Final = "session"

RUN_LEASE_HELD: Final = "held"
RUN_LEASE_RELEASED: Final = "released"
#: The store refused the grant itself: the id already names another run or
#: kind, or the store's generation moved under the handle.
RUN_LEASE_REFUSED: Final = "lease_refused"

#: Every reason a lease state can carry: its own three, and every reason the
#: serving road gives for not reaching a run (``store_disabled``,
#: ``not_published``, ``store_absent``, ``run_not_published``,
#: ``store_unavailable``, ``incompatible_generation``, ``integrity``,
#: ``unexpressible``) -- spelled by the road, never restated here.
RUN_LEASE_REASONS: Final[tuple[str, ...]] = tuple(
    sorted(
        {
            RUN_LEASE_HELD,
            RUN_LEASE_RELEASED,
            RUN_LEASE_REFUSED,
            *(
                reason
                for reason in SERVING_REASONS
                if reason not in {SERVING_REASON_SERVED, SERVING_REASON_DIVERGENT}
            ),
        }
    )
)

#: ``detail`` of a lease the write boundary withheld: where the store is,
#: and why nothing was written into it.
RUN_LEASE_OUTSIDE_SERVICE_DIRECTORIES: Final = (
    "run store {store_path} is outside CodeClone's service directories of "
    "{root}; a lease is a write, and this surface writes only inside them"
)

#: The refusals the road itself classifies; a reader lets them through.
_ROAD_REFUSALS: Final[tuple[type[RunStoreError], ...]] = (
    UnknownRunError,
    RunReportLinkError,
    StoreCompatibilityError,
    StoreIntegrityError,
    StoreUnavailableError,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class RunLeaseState:
    """Whether a store lease protects an intent's before-run, and why not.

    ``held`` is true for exactly the ``held`` reason, and only a held lease
    carries the store's deadline.  ``link``, ``lease_id`` and ``ttl_seconds``
    are what a renewal re-grants and a release names; ``store_run_id`` is the
    run the lease roots, when the road reached one.
    """

    held: bool
    reason: str
    lease_id: str
    ttl_seconds: int
    link: RunSnapshotLink | None = None
    store_run_id: str = ""
    expires_at: int | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        if self.reason not in RUN_LEASE_REASONS:
            raise ValueError(f"unknown run lease reason: {self.reason!r}")
        if self.held != (self.reason == RUN_LEASE_HELD):
            raise ValueError("a run lease is held for exactly the held reason")
        if (self.expires_at is not None) != self.held:
            raise ValueError("only a held run lease carries a deadline")


def run_lease_id(
    *,
    agent_pid: int,
    agent_start_epoch: int,
    sequence: int,
    intent_id: str,
) -> str:
    """The id of one grant: server session, never-reset sequence, intent."""

    return f"intent:{agent_pid}:{agent_start_epoch}:{sequence}:{intent_id}"


def acquire_intent_run_lease(
    *,
    root: Path,
    link: RunSnapshotLink | None,
    lease_id: str,
    ttl_seconds: int,
) -> RunLeaseState:
    """Grant a ``session`` lease on the run ``link`` names, or say why not."""

    return _grant(
        root=root,
        link=link,
        lease_id=lease_id,
        ttl_seconds=ttl_seconds,
    )


def renew_intent_run_lease(*, root: Path, state: RunLeaseState) -> RunLeaseState:
    """Push a held lease's deadline ``ttl_seconds`` past now; anything not
    held is returned as it is -- a lease that was refused is not retried."""

    if not state.held:
        return state
    return _grant(
        root=root,
        link=state.link,
        lease_id=state.lease_id,
        ttl_seconds=state.ttl_seconds,
    )


def release_intent_run_lease(*, root: Path, state: RunLeaseState) -> RunLeaseState:
    """Release a held lease.  A store that cannot be asked now leaves the
    lease to its deadline, and the answer says why; nothing is raised."""

    if not state.held:
        return state
    answer, outcome = _over_the_road(
        root=root,
        link=state.link,
        write=lambda store, _run_id: _release(store, state.lease_id),
    )
    reason = RUN_LEASE_RELEASED if answer is not None else outcome.reason
    return _not_held(state, reason, outcome.detail)


@dataclass(frozen=True, slots=True)
class _StoreAnswer:
    """What one write through the road came back with: the store's answer,
    its refusal, or the opened store the write boundary withheld."""

    expires_at: int | None = None
    refusal: str = ""
    withheld: str = ""


def _grant(
    *,
    root: Path,
    link: RunSnapshotLink | None,
    lease_id: str,
    ttl_seconds: int,
) -> RunLeaseState:
    answer, outcome = _over_the_road(
        root=root,
        link=link,
        write=lambda store, store_run_id: acquire_run_lease(
            store,
            store_run_id,
            kind=RUN_LEASE_KIND,
            lease_id=lease_id,
            ttl_seconds=ttl_seconds,
        ),
    )
    reached = RunLeaseState(
        held=False,
        reason=RUN_LEASE_REFUSED,
        lease_id=lease_id,
        ttl_seconds=ttl_seconds,
        link=link,
        store_run_id=outcome.store_run_id,
    )
    if answer is None:
        return _not_held(reached, outcome.reason, outcome.detail)
    if answer.refusal:
        return _not_held(reached, RUN_LEASE_REFUSED, answer.refusal)
    return RunLeaseState(
        held=True,
        reason=RUN_LEASE_HELD,
        lease_id=lease_id,
        ttl_seconds=ttl_seconds,
        link=link,
        store_run_id=outcome.store_run_id,
        expires_at=answer.expires_at,
    )


def _over_the_road(
    *,
    root: Path,
    link: RunSnapshotLink | None,
    write: Callable[[RunStore, str], int | None],
) -> tuple[_StoreAnswer | None, RunStoreServingOutcome]:
    """One write to the run the road resolves, or the road's typed reason --
    and no write at all into a store outside the surface's write boundary."""

    def read(store: RunStore, store_run_id: str) -> _StoreAnswer:
        opened = Path(store.file_identity()[0])
        if run_store_outside_boundary(opened, boundary=root) is not None:
            return _StoreAnswer(withheld=str(opened))
        try:
            return _StoreAnswer(expires_at=write(store, store_run_id))
        except sqlite3.OperationalError as fault:
            # The store's lease writes leave a held lock raw; it is the
            # environment, answered as the store answers it on every read.
            raise StoreUnavailableError(
                path=store.file_identity()[0], fault=fault
            ) from fault
        except _ROAD_REFUSALS:
            raise
        except RunStoreError as refused:
            return _StoreAnswer(refusal=str(refused))

    answer, outcome = _read_published(root=root, link=link, read=read)
    return _unless_withheld(answer, outcome, root=root)


def _unless_withheld(
    answer: _StoreAnswer | None, outcome: RunStoreServingOutcome, *, root: Path
) -> tuple[_StoreAnswer | None, RunStoreServingOutcome]:
    """The road's answer as it came -- or, when the write boundary withheld
    the store the road opened, no answer and the typed ``store_disabled``
    that names the store and the boundary."""
    if answer is None or not answer.withheld:
        return answer, outcome
    return None, RunStoreServingOutcome(
        source=SERVING_SOURCE_MEMORY,
        reason=SERVING_REASON_STORE_DISABLED,
        store_run_id=outcome.store_run_id,
        detail=RUN_LEASE_OUTSIDE_SERVICE_DIRECTORIES.format(
            store_path=answer.withheld, root=root
        ),
    )


def _release(store: RunStore, lease_id: str) -> None:
    release_run_lease(store, lease_id)


def _not_held(state: RunLeaseState, reason: str, detail: str = "") -> RunLeaseState:
    return RunLeaseState(
        held=False,
        reason=reason,
        lease_id=state.lease_id,
        ttl_seconds=state.ttl_seconds,
        link=state.link,
        store_run_id=state.store_run_id,
        detail=detail,
    )
