# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The session's store leases on its intents' before-runs.

One lease per intent, taken when the intent becomes active (declare,
promote, recover), re-granted where the intent's workspace lease is renewed,
released when the intent is cleared, superseded or rebound.  A retired
intent -- its before-run gone from memory -- keeps its lease: the store copy
is then the only one left, and it is what the next part of the effort serves
``finish`` from.

The state is the door's typed answer (:class:`RunLeaseState`), kept beside
the root whose store it names, in ``_intent_run_leases[intent_id]`` -- read
it under the session's state lock.
Nothing here decides a cycle: every refusal is a state, never an exception,
and no tool answer carries it.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from ...api.intent_run_lease import (
    RunLeaseState,
    acquire_intent_run_lease,
    release_intent_run_lease,
    renew_intent_run_lease,
    run_lease_id,
)
from ._session_shared import MCPRunRecord
from ._workspace_intent_store import WorkspaceIntentRegistryUnreadableError
from ._workspace_intents import find_workspace_intent, resolved_ttl_seconds

if TYPE_CHECKING:
    from ._session_finding_mixin import _StateLock


class _MCPSessionRunLeaseMixin:
    _state_lock: _StateLock
    _agent_pid: int
    _agent_start_epoch: int
    # intent id -> (the root whose store the lease is in, the door's answer)
    _intent_run_leases: dict[str, tuple[Path, RunLeaseState]]
    # Never reset, not even by clear_session_runs: intent ids restart there,
    # and a lease id must still name one grant.
    _intent_run_lease_sequence: int

    def _take_intent_run_lease(
        self,
        *,
        intent_id: str,
        record: MCPRunRecord,
        ttl_seconds: int | None = None,
    ) -> None:
        """Lease ``record``'s stored run for ``intent_id``, then release the
        lease the intent held before (a rebinding, or an id the session
        handed out again) -- in that order, so a run both name is never
        unrooted in between.  ``ttl_seconds`` defaults to the intent's own
        TTL as its registry row states it."""

        ttl = (
            ttl_seconds
            if ttl_seconds is not None
            else _registry_ttl_seconds(record.root, intent_id)
        )
        with self._state_lock:
            self._intent_run_lease_sequence += 1
            lease_id = run_lease_id(
                agent_pid=self._agent_pid,
                agent_start_epoch=self._agent_start_epoch,
                sequence=self._intent_run_lease_sequence,
                intent_id=intent_id,
            )
        state = acquire_intent_run_lease(
            root=record.root,
            link=record.execution.run_snapshot_link,
            lease_id=lease_id,
            ttl_seconds=ttl,
        )
        with self._state_lock:
            previous = self._intent_run_leases.get(intent_id)
            self._intent_run_leases[intent_id] = (record.root, state)
        if previous is not None:
            release_intent_run_lease(root=previous[0], state=previous[1])

    def _renew_intent_run_lease(self, intent_id: str, *, renewed: bool) -> None:
        """Re-grant the intent's lease when its workspace lease was renewed;
        a renewal the registry refused renews nothing here either."""

        with self._state_lock:
            entry = self._intent_run_leases.get(intent_id)
        if entry is None or not renewed:
            return
        root, state = entry
        fresh = renew_intent_run_lease(root=root, state=state)
        with self._state_lock:
            if self._intent_run_leases.get(intent_id) == entry:
                self._intent_run_leases[intent_id] = (root, fresh)

    def _release_intent_run_leases(self, intent_ids: Sequence[str]) -> None:
        """Release the leases of intents this session no longer holds."""

        with self._state_lock:
            entries = [
                entry
                for intent_id in intent_ids
                if (entry := self._intent_run_leases.pop(intent_id, None)) is not None
            ]
        for root, state in entries:
            release_intent_run_lease(root=root, state=state)


def _registry_ttl_seconds(root: Path, intent_id: str) -> int:
    """The intent's TTL as its registry row states it; the configured default
    when the row cannot be read -- a lease is never refused over its TTL."""

    try:
        row = find_workspace_intent(root=root, intent_id=intent_id)
    except WorkspaceIntentRegistryUnreadableError:
        row = None
    if row is not None:
        return row.ttl_seconds
    return resolved_ttl_seconds(
        None,
        env_value=os.environ.get("CODECLONE_INTENT_TTL_SECONDS"),
    )


__all__ = ["_MCPSessionRunLeaseMixin"]
