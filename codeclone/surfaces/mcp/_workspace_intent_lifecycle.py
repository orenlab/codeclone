# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Compatibility exports for surface-neutral workspace intent lifecycle rules."""

from __future__ import annotations

from ...workspace_intent.contract import WorkspaceIntentRecord
from ...workspace_intent.lifecycle import (
    TERMINAL_WORKSPACE_INTENT_STATUSES,
    WORKSPACE_INTENT_LIFECYCLE_VALUES,
    PidLiveness,
    WorkspaceIntentLifecycle,
    WorkspaceIntentStatus,
    agent_identity_liveness,
    gc_status_for_reason,
    is_lease_expired,
    is_pid_alive,
    is_terminal_workspace_intent_status,
    is_workspace_intent_lifecycle,
    lease_expiry,
    lifecycle_for_status,
    lifecycle_for_verification_outcome,
    parse_utc,
    pid_liveness,
    utc_now,
)


def is_orphaned(record: WorkspaceIntentRecord) -> bool:
    """Preserve the legacy monkeypatch seam around pid_liveness."""

    base = pid_liveness(record.agent_pid)
    return agent_identity_liveness(record, base=base) == PidLiveness.DEAD


__all__ = [
    "TERMINAL_WORKSPACE_INTENT_STATUSES",
    "WORKSPACE_INTENT_LIFECYCLE_VALUES",
    "PidLiveness",
    "WorkspaceIntentLifecycle",
    "WorkspaceIntentStatus",
    "agent_identity_liveness",
    "gc_status_for_reason",
    "is_lease_expired",
    "is_orphaned",
    "is_pid_alive",
    "is_terminal_workspace_intent_status",
    "is_workspace_intent_lifecycle",
    "lease_expiry",
    "lifecycle_for_status",
    "lifecycle_for_verification_outcome",
    "parse_utc",
    "pid_liveness",
    "utc_now",
]
