# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Shared workspace intent staleness predicates (leaf module)."""

from __future__ import annotations

from ._workspace_intent_contract import WorkspaceIntentRecord
from ._workspace_intent_lifecycle import (
    PidLiveness,
    WorkspaceIntentStatus,
    utc_now,
)
from ._workspace_intent_lifecycle import (
    is_lease_expired as _is_lease_expired,
)
from ._workspace_intent_lifecycle import (
    parse_utc as _parse_utc,
)


def stale_reason(record: WorkspaceIntentRecord) -> str | None:
    from . import _workspace_intent_pid as pid_mod

    if record.status == WorkspaceIntentStatus.EXPIRED.value:
        return "expired"
    if record.status == WorkspaceIntentStatus.ORPHANED.value:
        return "orphaned"
    expires = _parse_utc(record.expires_at_utc)
    if expires is None or expires <= utc_now():
        return "expired"
    if pid_mod.agent_pid_liveness(record.agent_pid) == PidLiveness.DEAD:
        return "orphaned"
    if _is_lease_expired(record):
        return "lease_expired"
    return None


def ttl_expired(record: WorkspaceIntentRecord) -> bool:
    expires = _parse_utc(record.expires_at_utc)
    return expires is None or expires <= utc_now()


def gc_removal_reason(
    record: WorkspaceIntentRecord,
    *,
    for_lazy_close: bool = False,
) -> str | None:
    reason = stale_reason(record)
    if reason == "lease_expired" and not ttl_expired(record):
        return None
    if for_lazy_close and reason == "orphaned":
        return None
    return reason


def is_stale(record: WorkspaceIntentRecord) -> bool:
    return stale_reason(record) is not None


__all__ = ["gc_removal_reason", "is_stale", "stale_reason", "ttl_expired"]
