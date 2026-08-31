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
from .lifecycle import PidLiveness


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


__all__ = ["IntentOwnership", "classify_intent_ownership"]
