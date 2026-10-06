# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The session's side of dropping run payloads.

The history limit bounds the payloads the session holds; when a new run is
about to be registered past it, the oldest payloads the drop rule lets go
are dropped first (:meth:`_relieve_payload_pressure`) -- before the new run
is registered, so a run is never dropped by the call that registers it.  A
payload the rule keeps is skipped, and the registry's own history bound
forgets an unpinned run held whole past the limit, as it always did.

The rule is ``api.run_residence.payload_droppable``; this mixin only gathers
its inputs: the execution's store link, the serving switch, the run's pins
and the store lease of each intent pinning it, and -- asked last -- the
store's proof of the run's membership.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ...api.intent_run_lease import RunLeaseState
from ...api.run_residence import payload_droppable
from ...api.run_store_serving import (
    SERVE_FROM_RUN_STORE,
    SERVING_REASON_SERVED,
    prove_published_run,
    serving_source,
)
from ._intent import IntentRecord, IntentStatus
from ._run_residence import resident_identity
from ._session_shared import CodeCloneMCPRunStore, MCPRunRecord

if TYPE_CHECKING:
    from ._session_finding_mixin import _StateLock


class _MCPSessionRunPayloadMixin:
    _runs: CodeCloneMCPRunStore
    _state_lock: _StateLock
    _active_intents: dict[str, IntentRecord]
    _intent_run_leases: dict[str, tuple[Path, RunLeaseState]]

    def _relieve_payload_pressure(self, *, incoming: int) -> tuple[str, ...]:
        """Make room for ``incoming`` new payloads under the history limit,
        oldest payload first, and return the executions whose payload was
        dropped, in that order.

        Each payload, oldest first, while room is still owed:

        * the drop rule lets it go -- dropped, the run held by its identity;
        * it is pinned -- kept and skipped, exempt from the bound as before;
        * it is unpinned -- left to the registry's history bound, which
          forgets an unpinned run held whole past the limit as it always
          did, and counted as the room that forgetting makes.

        So a run the store cannot stand in for is forgotten exactly when it
        was before this rule existed, and no newer payload is dropped in its
        place; with nothing droppable, nothing changes at all.
        """

        owed = self._runs.payload_excess(incoming=incoming)
        dropped: list[str] = []
        for record in self._runs.records():
            if owed <= 0:
                break
            event_id = record.execution.execution_event_id
            if self._payload_droppable(record):
                # ``False`` only when another call dropped it first: gone
                # either way.
                self._runs.drop_payload(resident_identity(record))
                dropped.append(event_id)
                owed -= 1
            elif self._runs.pin_count(event_id) == 0:
                owed -= 1
        return tuple(dropped)

    def _payload_droppable(self, record: MCPRunRecord) -> bool:
        """The drop rule over ``record``'s inputs as the session holds them."""

        event_id = record.execution.execution_event_id
        link = record.execution.run_snapshot_link
        with self._state_lock:
            leases = [
                None if entry is None else entry[1]
                for entry in (
                    self._intent_run_leases.get(intent.intent_id)
                    for intent in self._active_intents.values()
                    if intent.before_execution_id == event_id
                    and intent.status is not IntentStatus.QUEUED
                )
            ]
        return payload_droppable(
            link=link,
            store_serves=serving_source() == SERVE_FROM_RUN_STORE,
            pins=self._runs.pin_count(event_id),
            leases=leases,
            membership_proven=lambda: (
                prove_published_run(root=record.root, link=link).reason
                == SERVING_REASON_SERVED
            ),
        )


__all__ = ["_MCPSessionRunPayloadMixin"]
