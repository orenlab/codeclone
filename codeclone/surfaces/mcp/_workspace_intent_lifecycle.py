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
    PidLiveness,
    WorkspaceIntentStatus,
    gc_status_for_reason,
    is_lease_expired,
    is_pid_alive,
    is_terminal_workspace_intent_status,
    lease_expiry,
    parse_utc,
    pid_liveness,
    utc_now,
)


def is_orphaned(record: WorkspaceIntentRecord) -> bool:
    """Preserve the legacy monkeypatch seam around pid_liveness."""

    return pid_liveness(record.agent_pid) == PidLiveness.DEAD


__all__ = [
    "TERMINAL_WORKSPACE_INTENT_STATUSES",
    "PidLiveness",
    "WorkspaceIntentStatus",
    "gc_status_for_reason",
    "is_lease_expired",
    "is_orphaned",
    "is_pid_alive",
    "is_terminal_workspace_intent_status",
    "lease_expiry",
    "parse_utc",
    "pid_liveness",
    "utc_now",
]
