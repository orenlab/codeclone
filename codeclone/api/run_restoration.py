# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The R3 door through which a surface finds a run again in a process that
did not publish it -- or learns, typed, why it cannot.

The MCP surface (ring ``r4``) may not import the run store (``r2``); this
door carries its two operations across:

* **finalization** -- after an analysis, the surface hands over the
  publication the report left pending and the execution overlay it built,
  and the store joins the snapshot, the record, the bridge edge and the end
  of the publisher's lease in one fenced transaction
  (:func:`finalize_execution_record`);
* **restoration** -- a surface that misses a run in memory asks the store's
  execution registry for it, by the report it names under a root
  (:func:`restore_run`).

**The answer is always typed** (:class:`RunRestoration`), with the closed
vocabulary below: the serving door's own words wherever one already means
the same (``store_disabled``, ``run_not_published``, ``store_unavailable``,
``incompatible_generation``, ``integrity``), and two words of this door's
own -- ``run_not_found`` (the registry holds no record: no proof that the
run ever existed) and ``run_expired`` (the registry holds the record and the
store no longer holds the run: the record IS the proof).  Each reason says
whether the same call may succeed later (``retryable``).  The store path is
the rollout's own, resolved here like every other door resolves it, and the
serving switch is honoured: a store the switch does not name is never read.

**Reading is reading.**  The store is opened ``create=False``, decided under
a deferred snapshot, never migrated, never locked for a write.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ..canonical.errors import (
    ExecutionRecordError,
    StoreCompatibilityError,
    StoreIntegrityError,
    StoreUnavailableError,
    UnknownRunError,
)
from ..canonical.executions import (
    EXECUTION_AVAILABLE,
    EXECUTION_EXPIRED,
    RegisteredExecution,
)
from ..canonical.store import RunStore, registered_report_execution
from ..core.canonical_snapshot import PUBLICATION_RETENTION, finalize_run_publication
from ..models import (
    RUN_SNAPSHOT_LINK_LINKED,
    RUN_SNAPSHOT_LINK_UNRECORDED,
    FileStat,
    RunSnapshotLink,
)
from .run_store_serving import (
    SERVING_REASON_INCOMPATIBLE_GENERATION,
    SERVING_REASON_INTEGRITY,
    SERVING_REASON_RUN_NOT_PUBLISHED,
    SERVING_REASON_SERVED,
    SERVING_REASON_STORE_DISABLED,
    SERVING_REASON_STORE_UNAVAILABLE,
    restoration_store,
)

#: The registry holds no record of the run: nothing proves it ever existed.
RESTORATION_RUN_NOT_FOUND: Final = "run_not_found"
#: The registry holds the record and the store no longer holds the run.
RESTORATION_RUN_EXPIRED: Final = "run_expired"

#: Every reason a restoration answers with, and whether a later call of the
#: same request may succeed.  ``served`` is the one success.
RESTORATION_RETRYABLE: Final[dict[str, bool]] = {
    SERVING_REASON_SERVED: False,
    RESTORATION_RUN_NOT_FOUND: False,
    RESTORATION_RUN_EXPIRED: False,
    SERVING_REASON_RUN_NOT_PUBLISHED: False,
    SERVING_REASON_STORE_DISABLED: False,
    SERVING_REASON_INCOMPATIBLE_GENERATION: False,
    SERVING_REASON_INTEGRITY: False,
    SERVING_REASON_STORE_UNAVAILABLE: True,
}
RESTORATION_REASONS: Final[tuple[str, ...]] = tuple(sorted(RESTORATION_RETRYABLE))


@dataclass(frozen=True, slots=True, kw_only=True)
class RunRestoration:
    """The registry's answer to one restoration, typed.

    ``served``: ``overlay`` holds the producer's execution overlay under
    ``record_contract`` and ``store_run_id`` names the run the store holds
    for it.  Any other reason: why not, ``detail`` in the store's words,
    and -- for ``run_expired`` -- the record that proves the run existed
    (``execution_event_id``, ``store_run_id``, ``finalized_at``).
    """

    reason: str
    detail: str = ""
    next_step: str = ""
    execution_event_id: str = ""
    store_run_id: str = ""
    finalized_at: int | None = None
    record_contract: str = ""
    overlay: bytes = b""

    def __post_init__(self) -> None:
        if self.reason not in RESTORATION_RETRYABLE:
            raise ValueError(f"unknown restoration reason: {self.reason!r}")
        if bool(self.overlay) != (self.reason == SERVING_REASON_SERVED):
            raise ValueError("an overlay rides a served restoration and nothing else")


def _refused(reason: str, *, detail: str = "", next_step: str = "") -> RunRestoration:
    return RunRestoration(reason=reason, detail=detail, next_step=next_step)


def _answer(registered: RegisteredExecution | None, *, asked: str) -> RunRestoration:
    """One registry answer as a restoration."""
    if registered is None:
        return _refused(
            RESTORATION_RUN_NOT_FOUND,
            detail=f"the run store holds no execution record of {asked}",
        )
    record = registered.record
    if registered.availability == EXECUTION_AVAILABLE:
        return RunRestoration(
            reason=SERVING_REASON_SERVED,
            execution_event_id=record.execution_event_id,
            store_run_id=record.store_run_id,
            finalized_at=registered.finalized_at,
            record_contract=record.record_contract,
            overlay=record.overlay,
        )
    reason = (
        RESTORATION_RUN_EXPIRED
        if registered.availability == EXECUTION_EXPIRED
        else SERVING_REASON_RUN_NOT_PUBLISHED
    )
    return RunRestoration(
        reason=reason,
        detail=(
            f"execution {record.execution_event_id} published store run "
            f"{record.store_run_id[:12]}, which the store no longer holds "
            "published"
        ),
        execution_event_id=record.execution_event_id,
        store_run_id=record.store_run_id,
        finalized_at=registered.finalized_at,
    )


def _registry_answer(
    *, root: Path, asked: str, read: Callable[[RunStore], RegisteredExecution | None]
) -> RunRestoration:
    """The gates, one store open, one registry read, or a typed reason.

    The gates are the serving door's own (``restoration_store``): the store
    the rollout names for this root, read only while the serving switch names
    the store -- one read-side resolution of one flag, never a second.
    """
    path = restoration_store(root=root)
    if not isinstance(path, Path):
        return _refused(path.reason, detail=path.detail)
    try:
        with RunStore(path, create=False) as store:
            registered = read(store)
    except UnknownRunError as absent:
        # The non-creating open's one refusal: there is no store at this
        # path, so no record of any run -- which proves nothing about one
        # having existed.
        return _refused(RESTORATION_RUN_NOT_FOUND, detail=str(absent))
    except StoreCompatibilityError as refusal:
        return _refused(
            SERVING_REASON_INCOMPATIBLE_GENERATION,
            detail=str(refusal),
            next_step=refusal.next_step,
        )
    except StoreIntegrityError as refusal:
        return _refused(SERVING_REASON_INTEGRITY, detail=str(refusal))
    except StoreUnavailableError as refusal:
        return _refused(SERVING_REASON_STORE_UNAVAILABLE, detail=str(refusal))
    return _answer(registered, asked=asked)


def restore_run(*, root: Path, run_id: str) -> RunRestoration:
    """The newest execution of the report ``run_id`` names under ``root``.

    ``run_id`` is the report identity or a unique lowercase-hex prefix of
    it; a prefix naming two reports under the root is refused by the
    store (:class:`~codeclone.canonical.errors.ExecutionRecordError`) and
    propagates -- the request was ambiguous, the store was not.
    """
    spelled = str(root.resolve())
    return _registry_answer(
        root=root,
        asked=f"run {run_id} under {spelled}",
        read=lambda store: registered_report_execution(
            store, root=spelled, run_id=run_id
        ),
    )


def finalize_execution_record(
    *,
    store_path: Path,
    link: RunSnapshotLink,
    publisher_lease: str,
    execution_event_id: str,
    root: Path,
    record_contract: str,
    overlay: bytes,
) -> RunSnapshotLink:
    """Finalize the publication a report left for its caller: the snapshot,
    the record, the bridge edge and the end of the publisher's lease, one
    atom (``core.canonical_snapshot.finalize_run_publication``)."""
    return finalize_run_publication(
        store_path=store_path,
        link=link,
        publisher_lease=publisher_lease,
        execution_event_id=execution_event_id,
        root=root,
        record_contract=record_contract,
        overlay=overlay,
    )


__all__ = [
    "PUBLICATION_RETENTION",
    "RESTORATION_REASONS",
    "RESTORATION_RETRYABLE",
    "RESTORATION_RUN_EXPIRED",
    "RESTORATION_RUN_NOT_FOUND",
    "RUN_SNAPSHOT_LINK_LINKED",
    "RUN_SNAPSHOT_LINK_UNRECORDED",
    "ExecutionRecordError",
    "FileStat",
    "RunRestoration",
    "RunSnapshotLink",
    "finalize_execution_record",
    "restore_run",
]
