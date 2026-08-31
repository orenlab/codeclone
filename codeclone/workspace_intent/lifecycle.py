# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
from enum import Enum

from ..models import deadline_passed
from .contract import WorkspaceIntentRecord


class WorkspaceIntentStatus(str, Enum):
    ACTIVE = "active"
    QUEUED = "queued"
    CLEAN = "clean"
    EXPANDED = "expanded"
    VIOLATED = "violated"
    EXPIRED = "expired"
    ORPHANED = "orphaned"


class PidLiveness(str, Enum):
    ALIVE = "alive"
    DEAD = "dead"
    UNKNOWN = "unknown"


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


def pid_liveness(pid: int) -> PidLiveness:
    if pid <= 0:
        return PidLiveness.DEAD
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return PidLiveness.DEAD
    except PermissionError:
        return PidLiveness.UNKNOWN
    except OSError:
        return PidLiveness.ALIVE
    return PidLiveness.ALIVE


def is_pid_alive(pid: int) -> bool:
    return pid_liveness(pid) == PidLiveness.ALIVE


_DEFAULT_IS_PID_ALIVE = is_pid_alive


def liveness_probe_is_declared() -> bool:
    """True when this seam's boolean probe has been replaced.

    A replaced probe means somebody is declaring pid fates rather than reading
    them. The kernel must not then be consulted about a pid the declarer never
    reserved -- that would reintroduce, one layer down, exactly the machine
    dependence the identity check exists to remove.
    """

    return globals()["is_pid_alive"] is not _DEFAULT_IS_PID_ALIVE


# A pid is a slot, not an identity: the kernel hands the same number to an
# unrelated process once the old one is reaped. The two terms below are the
# whole derivation of how far a *genuine* agent's measured start may drift
# past the epoch it recorded for itself. Both are one second, and each is one
# second for a stated reason -- do not fold them into a literal.
#
#   1. ``agent_start_epoch`` is ``int(time.time())`` sampled *inside* the
#      already-running agent, so it floors a real reading: the true start is
#      at most one second later than the recorded integer.
#   2. ``ps -o etime=`` reports whole seconds of elapsed time. Sampling the
#      wall clock *before* the probe makes every later scheduling delay push
#      the derived start earlier (safe), leaving truncation as the only
#      overshoot, and that is under one second.
_RECORDED_EPOCH_TRUNCATION_SECONDS = 1
_ELAPSED_RESOLUTION_SECONDS = 1
START_EPOCH_SLACK_SECONDS = (
    _RECORDED_EPOCH_TRUNCATION_SECONDS + _ELAPSED_RESOLUTION_SECONDS
)

_PROCESS_START_PROBE_TIMEOUT_SECONDS = 5.0


def _parse_elapsed_seconds(raw: str) -> int | None:
    """Read the POSIX ``ps -o etime`` field: ``[[dd-]hh:]mm:ss``."""

    text = raw.strip()
    if not text:
        return None
    days = 0
    if "-" in text:
        day_text, _, text = text.partition("-")
        try:
            days = int(day_text)
        except ValueError:
            return None
    parts = text.split(":")
    if len(parts) not in (2, 3):
        return None
    try:
        values = [int(part) for part in parts]
    except ValueError:
        return None
    while len(values) < 3:
        values.insert(0, 0)
    hours, minutes, seconds = values
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def probe_process_start_epoch(pid: int) -> int | None:
    """Wall-clock second at or after which the process now holding ``pid``
    started, or None when this platform will not say.

    Deliberately never guesses: an unreadable start time is reported as
    absence, and callers must translate that into UNKNOWN rather than death.
    """

    if pid <= 0:
        return None
    ps_path = shutil.which("ps")
    if ps_path is None:
        return None
    # Sample before the probe: any delay inside ``ps`` only inflates the
    # elapsed reading, which drags the derived start *earlier*. Overshoot --
    # the only direction that can libel a live agent -- stays under a second.
    before = time.time()
    try:
        completed = subprocess.run(
            [ps_path, "-o", "etime=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=_PROCESS_START_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    elapsed = _parse_elapsed_seconds(completed.stdout)
    if elapsed is None:
        return None
    return int(before) - elapsed


def agent_identity_liveness(
    record: WorkspaceIntentRecord,
    *,
    base: PidLiveness | None = None,
    base_is_declared: bool = False,
) -> PidLiveness:
    """Liveness of the *recorded agent*, not of its pid slot.

    Existence of the number proves nothing: a process that started after the
    agent stamped ``agent_start_epoch`` cannot be that agent, so the record is
    dead however lively the pid looks. The check only ever converts ALIVE into
    something weaker, and only on positive evidence -- when the start time
    cannot be read at all the answer is UNKNOWN, never DEAD.

    ``base_is_declared`` marks a verdict that came from a replaced probe on a
    seam this module cannot see. Such a verdict is final: the caller declared
    this pid's fate and the kernel is not asked to overrule it.
    """

    liveness = pid_liveness(record.agent_pid) if base is None else base
    if liveness is not PidLiveness.ALIVE:
        return liveness
    if base_is_declared or liveness_probe_is_declared():
        return liveness
    started_at = probe_process_start_epoch(record.agent_pid)
    if started_at is None:
        return PidLiveness.UNKNOWN
    if started_at > record.agent_start_epoch + START_EPOCH_SLACK_SECONDS:
        return PidLiveness.DEAD
    return PidLiveness.ALIVE


def is_orphaned(record: WorkspaceIntentRecord) -> bool:
    return agent_identity_liveness(record) == PidLiveness.DEAD


def lease_expiry(record: WorkspaceIntentRecord) -> datetime | None:
    renewed_at = parse_utc(record.lease_renewed_at_utc)
    if renewed_at is None:
        return None
    return renewed_at + timedelta(seconds=record.lease_seconds)


def is_lease_expired(record: WorkspaceIntentRecord) -> bool:
    """Decided by the one hold-deadline law of the unified GC point: a
    lease whose renewal timestamp cannot be read has a passed deadline —
    collectable, never immortal."""
    return deadline_passed(lease_expiry(record), utc_now())


__all__ = [
    "START_EPOCH_SLACK_SECONDS",
    "TERMINAL_WORKSPACE_INTENT_STATUSES",
    "PidLiveness",
    "WorkspaceIntentStatus",
    "agent_identity_liveness",
    "gc_status_for_reason",
    "is_lease_expired",
    "is_orphaned",
    "is_pid_alive",
    "is_terminal_workspace_intent_status",
    "lease_expiry",
    "liveness_probe_is_declared",
    "parse_utc",
    "pid_liveness",
    "probe_process_start_epoch",
    "utc_now",
]
