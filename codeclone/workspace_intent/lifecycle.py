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
    """The union vocabulary this column used to carry, kept for READING.

    Two axes were spelled into one field.  ``CLEAN``/``EXPANDED``/``VIOLATED``
    are what verification SAID; the rest are what the row IS.  Rows written by
    earlier builds still carry the first three, so the names stay -- but only
    :class:`WorkspaceIntentLifecycle` may be written from here on, and the
    read path normalises the verdicts away (:func:`lifecycle_for_status`).
    """

    ACTIVE = "active"
    QUEUED = "queued"
    CLEAN = "clean"
    EXPANDED = "expanded"
    VIOLATED = "violated"
    EXPIRED = "expired"
    ORPHANED = "orphaned"
    NEEDS_RECOVERY = "needs_recovery"


class WorkspaceIntentLifecycle(str, Enum):
    """What the registry row IS -- never what verification said about it.

    ``find_workspace_intent`` filters on this axis, so a value here decides
    whether an agent can still reach its own intent.  Measured 2026-09-04: a
    ``finish`` whose scope check passed and whose verification failed wrote
    the scope verdict ``clean`` -- terminal on this axis -- and the refusal
    that told the agent to recover deleted the row it named.  Separating the
    two vocabularies makes that sentence unrepresentable rather than merely
    unlikely.

    ``CLOSED`` keeps the persisted token ``clean``.  The value is what an
    older build reads back, and only the terminal reading is safe to leave
    unchanged: a new token there would make a finished row look live to every
    build that has not been upgraded.  ``NEEDS_RECOVERY`` is a new token, and
    new in the safe direction -- an older build reads it as non-terminal,
    which is exactly what it means.
    """

    ACTIVE = "active"
    QUEUED = "queued"
    NEEDS_RECOVERY = "needs_recovery"
    CLOSED = "clean"
    EXPIRED = "expired"
    ORPHANED = "orphaned"


class PidLiveness(str, Enum):
    ALIVE = "alive"
    DEAD = "dead"
    UNKNOWN = "unknown"


WORKSPACE_INTENT_LIFECYCLE_VALUES: frozenset[str] = frozenset(
    member.value for member in WorkspaceIntentLifecycle
)


TERMINAL_WORKSPACE_INTENT_STATUSES: frozenset[str] = frozenset(
    {
        WorkspaceIntentLifecycle.CLOSED.value,
        WorkspaceIntentLifecycle.EXPIRED.value,
        WorkspaceIntentLifecycle.ORPHANED.value,
    }
)


# The whole decision table, in one place and total over both vocabularies.
# A verification verdict is not a fate: a scope check that passed has not
# closed anything (only ``clear`` closes a row), and one that failed has not
# ended anything either -- it has asked for recovery, which is editing, and
# so leaves the row live and findable.
_LIFECYCLE_BY_STATUS: dict[str, WorkspaceIntentLifecycle] = {
    WorkspaceIntentStatus.ACTIVE.value: WorkspaceIntentLifecycle.ACTIVE,
    WorkspaceIntentStatus.QUEUED.value: WorkspaceIntentLifecycle.QUEUED,
    WorkspaceIntentStatus.EXPANDED.value: WorkspaceIntentLifecycle.ACTIVE,
    WorkspaceIntentStatus.VIOLATED.value: WorkspaceIntentLifecycle.NEEDS_RECOVERY,
    WorkspaceIntentStatus.NEEDS_RECOVERY.value: (
        WorkspaceIntentLifecycle.NEEDS_RECOVERY
    ),
    WorkspaceIntentStatus.CLEAN.value: WorkspaceIntentLifecycle.CLOSED,
    WorkspaceIntentStatus.EXPIRED.value: WorkspaceIntentLifecycle.EXPIRED,
    WorkspaceIntentStatus.ORPHANED.value: WorkspaceIntentLifecycle.ORPHANED,
    # The in-memory verification vocabulary reaches here through the intent
    # session, which holds an ``IntentStatus`` the registry has no column for.
    "unverified": WorkspaceIntentLifecycle.NEEDS_RECOVERY,
}


def lifecycle_for_status(status: str) -> WorkspaceIntentLifecycle:
    """Map any status word -- verdict or fate -- onto the lifecycle axis.

    ``clean`` maps to ``CLOSED`` because that token has one persisted meaning
    and it is terminal.  Callers holding a *scope verdict* must therefore not
    hand it here; :func:`lifecycle_for_verification_outcome` is the door for
    those, and it refuses to read a verdict as a fate.
    """

    try:
        return _LIFECYCLE_BY_STATUS[status]
    except KeyError:
        raise ValueError(f"unknown workspace intent status: {status!r}") from None


# Verdicts, and what each means for the row that carries it.  ``clean`` is
# the entry the incident turned on: a passed scope check says nothing about
# whether the work is finished, so it must not be read as the closing token
# that happens to share its spelling.
_LIFECYCLE_BY_VERIFICATION_OUTCOME: dict[str, WorkspaceIntentLifecycle] = {
    "active": WorkspaceIntentLifecycle.ACTIVE,
    "queued": WorkspaceIntentLifecycle.QUEUED,
    "clean": WorkspaceIntentLifecycle.ACTIVE,
    "expanded": WorkspaceIntentLifecycle.ACTIVE,
    "violated": WorkspaceIntentLifecycle.NEEDS_RECOVERY,
    "unverified": WorkspaceIntentLifecycle.NEEDS_RECOVERY,
    "expired": WorkspaceIntentLifecycle.EXPIRED,
}


def lifecycle_for_verification_outcome(outcome: str) -> WorkspaceIntentLifecycle:
    """The fate implied by a verification or scope verdict.

    Total over the in-memory verification vocabulary; anything else raises,
    because a status this table has not considered is a new axis smuggled
    into an old field and must fail loudly rather than pick a default.
    """

    try:
        return _LIFECYCLE_BY_VERIFICATION_OUTCOME[outcome]
    except KeyError:
        raise ValueError(f"unknown verification outcome: {outcome!r}") from None


def is_workspace_intent_lifecycle(status: str) -> bool:
    return status in WORKSPACE_INTENT_LIFECYCLE_VALUES


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
# unrelated process once the old one is reaped. The tolerance below is one
# proven bound plus one declared margin. Keep the two apart: only the first is
# a measurement, and only the first may be re-derived from the machine.
#
# Three floors sit between a genuine agent's real start ``S`` and the number
# this module compares:
#
#     epoch = floor(E)        E sampled inside the running agent, S <= E <= B
#     etime = floor(t - S)    whole seconds, read at some t >= B
#     start = floor(B) - etime
#
# Bounding each floor by its own argument gives
#
#     start - epoch  <  B - (B - S - 1) - (S - 1)  =  2
#
# so a genuine agent's drift is at most ONE second. The individual truncations
# do NOT compose additively -- they share a time base, and adding them
# double-counts. Sampling ``B`` before the probe is what keeps it there: every
# later scheduling delay inflates ``etime`` and drags ``start`` earlier, which
# is the safe direction. ``test_measurement_drift_bound_is_re_derived_by_
# simulation`` rebuilds this bound by exhaustive search rather than trusting
# the algebra above.
_MEASUREMENT_DRIFT_BOUND_SECONDS = 1

# Not a measurement: a declared cushion, and the honest name for it. It buys
# one second against a small forward wall-clock adjustment landing between the
# agent's stamp and this probe, and costs nothing in detection power because a
# pid takes minutes to be reissued. A large NTP *step* is not covered by any
# constant of this size, and pretending otherwise would be the fabrication this
# module exists to refuse.
_CLOCK_ADJUSTMENT_MARGIN_SECONDS = 1

# Strictly greater: a start exactly on the tolerance is still inside the
# declared envelope, and this module converts ALIVE to DEAD only on positive
# evidence. The boundary's strictness is pinned by its own two tests.
START_EPOCH_SLACK_SECONDS = (
    _MEASUREMENT_DRIFT_BOUND_SECONDS + _CLOCK_ADJUSTMENT_MARGIN_SECONDS
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
    "liveness_probe_is_declared",
    "parse_utc",
    "pid_liveness",
    "probe_process_start_epoch",
    "utc_now",
]
