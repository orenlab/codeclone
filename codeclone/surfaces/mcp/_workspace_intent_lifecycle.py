# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from enum import Enum

from ._workspace_intent_contract import WorkspaceIntentRecord


class WorkspaceIntentStatus(str, Enum):
    ACTIVE = "active"
    QUEUED = "queued"
    CLEAN = "clean"
    EXPANDED = "expanded"
    VIOLATED = "violated"
    EXPIRED = "expired"
    ORPHANED = "orphaned"


TERMINAL_WORKSPACE_INTENT_STATUSES: frozenset[str] = frozenset(
    {
        WorkspaceIntentStatus.CLEAN.value,
        WorkspaceIntentStatus.EXPIRED.value,
        WorkspaceIntentStatus.ORPHANED.value,
    }
)


def is_terminal_workspace_intent_status(status: str) -> bool:
    return status in TERMINAL_WORKSPACE_INTENT_STATUSES


def gc_status_for_reason(reason: str) -> str:
    if reason == "orphaned":
        return WorkspaceIntentStatus.ORPHANED.value
    return WorkspaceIntentStatus.EXPIRED.value


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def parse_utc(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return False
    except OSError:
        return True
    return True


def is_orphaned(record: WorkspaceIntentRecord) -> bool:
    return not is_pid_alive(record.agent_pid)


def lease_expiry(record: WorkspaceIntentRecord) -> datetime | None:
    renewed_at = parse_utc(record.lease_renewed_at_utc)
    if renewed_at is None:
        return None
    return renewed_at + timedelta(seconds=record.lease_seconds)


def is_lease_expired(record: WorkspaceIntentRecord) -> bool:
    expiry = lease_expiry(record)
    return expiry is None or expiry <= utc_now()


__all__ = [
    "TERMINAL_WORKSPACE_INTENT_STATUSES",
    "WorkspaceIntentStatus",
    "gc_status_for_reason",
    "is_lease_expired",
    "is_orphaned",
    "is_pid_alive",
    "is_terminal_workspace_intent_status",
    "lease_expiry",
    "parse_utc",
    "utc_now",
]
