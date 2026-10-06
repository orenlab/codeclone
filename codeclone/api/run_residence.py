# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""What a surface keeps of a run whose payload it let go, and when it may.

A surface that serves runs out of the run store (``api.run_store_serving``)
can let a run's in-memory payload -- its report projection, summary and
per-file tables -- go, and keep only what names the run and its execution
(:class:`ResidentRun`).  Whether it may is ONE rule (:func:`payload_droppable`):
only while the run store can stand in for the payload, and only for as
long as nothing can collect the run from under it.

The request a run was analysed with is the surface's own type, so the
resident run is generic over it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

from ..models import RUN_SNAPSHOT_LINK_LINKED, RunSnapshotLink
from .execution_event import ExecutionEvent
from .intent_run_lease import RunLeaseState

RequestT = TypeVar("RequestT")


@dataclass(frozen=True, slots=True, kw_only=True)
class RunSummaryResidue:
    """The run summary's fields only memory states, kept when a payload goes.

    The run store carries every block of the run summary that is a fact of
    the run; these are the rest -- the producer's version, the report
    schema, the cache state, the interpreter keys of ``baseline``, the
    inventory's ``entity_counts`` refusal and the presentation keys of
    ``security_surfaces``.  Copied out of the payload when it is dropped.
    """

    version: str
    schema: str
    cache: Mapping[str, object]
    baseline_execution: Mapping[str, object]
    entity_counts: Mapping[str, object] | None
    security_presentation: Mapping[str, object]


@dataclass(frozen=True, kw_only=True)
class ResidentRun(Generic[RequestT]):
    """The resident part of a held run: what stays when its payload goes.

    The record's own resident fields -- the identity, the request and the
    comparison settings, the changed paths, the clone counts and the
    execution event with every witness and the store link -- the very
    objects the record held, plus the run summary's memory-only fields,
    copied out of the payload at the drop.  (An intent's expiry needs no
    copy: the run id IS the report's evaluation digest.)  Nothing turns it
    back into a record:
    a run without its payload is answered from the run store, or refused.
    """

    run_id: str
    root: Path
    request: RequestT
    comparison_settings: tuple[object, ...]
    changed_paths: tuple[str, ...]
    func_clones_count: int
    block_clones_count: int
    execution: ExecutionEvent
    summary_residue: RunSummaryResidue


def payload_droppable(
    *,
    link: RunSnapshotLink | None,
    store_serves: bool,
    pins: int,
    leases: Sequence[RunLeaseState | None],
    membership_proven: Callable[[], bool],
) -> bool:
    """Whether a held run's payload may be dropped -- the one drop rule.

    ``link`` is the execution's store link; ``store_serves`` whether the
    serving switch names the run store; ``pins`` how many references pin
    the run and ``leases`` the store lease of each intent of the session
    pinning it (``None`` for an intent that holds none); and
    ``membership_proven`` asks the store, last, whether it holds the run
    published with its membership proven.

    ============================  =====================================
    the run                       the payload
    ============================  =====================================
    not linked (no store run)     kept -- nothing can stand in for it
    switch names memory           kept -- no migrated reading reads it
    a pin no lease accounts for   kept -- the collector may take it
    a lease not held / elsewhere  kept -- the collector may take it
    membership not proven         kept -- the store's copy is unproven
    all of the above hold         may be dropped
    ============================  =====================================
    """
    if link is None or link.state != RUN_SNAPSHOT_LINK_LINKED:
        return False
    if not store_serves:
        return False
    if len(leases) != pins:
        return False
    for lease in leases:
        if lease is None or not lease.held:
            return False
        if lease.store_run_id != link.store_run_id:
            return False
    return membership_proven()


__all__ = [
    "ResidentRun",
    "RunSummaryResidue",
    "payload_droppable",
]
