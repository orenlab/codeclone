# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Surface-neutral workspace intent ownership classification."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from enum import Enum

import codeclone.workspace_intent.lifecycle as lifecycle

from .contract import WorkspaceIntentRecord
from .lifecycle import PidLiveness, is_terminal_workspace_intent_status


class IntentOwnership(str, Enum):
    OWN_ACTIVE = "own_active"
    OWN_STALE = "own_stale"
    FOREIGN_ACTIVE = "foreign_active"
    FOREIGN_STALE = "foreign_stale"
    RECOVERABLE = "recoverable"
    EXPIRED = "expired"


def classify_intent_ownership(
    record: WorkspaceIntentRecord,
    *,
    own_pid: int,
    own_start_epoch: int,
    now: datetime,
    pid_liveness: Callable[[int], PidLiveness] | None = None,
    record_liveness: Callable[[WorkspaceIntentRecord], PidLiveness] | None = None,
) -> IntentOwnership:
    """Classify one record without coupling the contract to an agent surface."""

    expires = lifecycle.parse_utc(record.expires_at_utc)
    if expires is None or expires <= now:
        return IntentOwnership.EXPIRED

    is_own = record.agent_pid == own_pid and record.agent_start_epoch == own_start_epoch
    lease_expiry = lifecycle.lease_expiry(record)
    lease_valid = lease_expiry is not None and lease_expiry > now
    if is_own:
        return IntentOwnership.OWN_ACTIVE if lease_valid else IntentOwnership.OWN_STALE
    # A live pid is not a live agent. Recovery must be decided on the recorded
    # agent's identity, or foreign work queues behind a recycled pid forever.
    if record_liveness is not None:
        liveness = record_liveness(record)
    else:
        base_liveness = (pid_liveness or lifecycle.pid_liveness)(record.agent_pid)
        liveness = lifecycle.agent_identity_liveness(record, base=base_liveness)
    if liveness == PidLiveness.DEAD:
        return IntentOwnership.RECOVERABLE
    return (
        IntentOwnership.FOREIGN_ACTIVE if lease_valid else IntentOwnership.FOREIGN_STALE
    )


def is_recovery_candidate(
    record: WorkspaceIntentRecord,
    ownership: IntentOwnership,
) -> bool:
    """Whether ``recover`` can actually reopen this row: both axes must agree.

    :class:`IntentOwnership` answers one question -- *whose agent, and is that
    agent still there* -- and ``RECOVERABLE`` is its way of saying the
    declaring agent is gone.  It is silent about the other axis.  A row whose
    lifecycle status is terminal is filtered out by ``find_workspace_intent``,
    so ``recover`` cannot reach it at all: advertising such a row produces a
    reclaim instruction whose only possible outcome is ``not_found``.

    Measured 2026-09-04, and reproduced on both registry backends: a finish
    that reported ``intent_cleared: true`` left ``list_workspace`` publishing
    the closed intent under ``recovery_available`` with the hint "Use
    action='recover' with matching run_id to reclaim", while ``recover``
    answered ``not_found`` for that same id.  The SQLite registry retains a
    closed row for its retention window by design, so the row being *there* is
    correct; calling it reclaimable is not.

    The join lives here rather than at each call site because it was already
    being written by hand at two of them -- the edit gate and the MCP
    workspace-hygiene reader both skip terminal rows before classifying -- and
    was simply missing from the other two.  One fact, one owner.
    """

    return ownership is IntentOwnership.RECOVERABLE and not (
        is_terminal_workspace_intent_status(record.status)
    )


__all__ = [
    "IntentOwnership",
    "classify_intent_ownership",
    "is_recovery_candidate",
]
