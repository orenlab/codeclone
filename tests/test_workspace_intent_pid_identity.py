# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A pid is a slot, not an identity.

Every test here races the real operating system on purpose. The only pid it
ever treats as alive is ``os.getpid()`` -- the one process whose liveness the
test itself guarantees -- so no assertion is a function of what else happens
to be running on the machine.
"""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import sys
import time
from dataclasses import replace

import pytest

from codeclone.workspace_intent import lifecycle
from codeclone.workspace_intent.contract import WorkspaceIntentRecord
from codeclone.workspace_intent.lifecycle import (
    START_EPOCH_SLACK_SECONDS,
    PidLiveness,
    agent_identity_liveness,
    probe_process_start_epoch,
    utc_now,
)
from codeclone.workspace_intent.ownership import (
    IntentOwnership,
    classify_intent_ownership,
)
from tests.test_workspace_intents import _record

# 1970. No process on this machine started then, so a record claiming this
# epoch for a live pid is describing an agent the kernel has already reaped.
_GHOST_EPOCH = 100


def _ghost_record() -> WorkspaceIntentRecord:
    """A record whose pid is unquestionably alive and unquestionably not it."""

    return replace(
        _record(intent_id="intent-ghost-001", status="active"),
        agent_pid=os.getpid(),
        agent_start_epoch=_GHOST_EPOCH,
    )


def _living_record() -> WorkspaceIntentRecord:
    """A record this very process could honestly have written for itself."""

    return replace(
        _record(intent_id="intent-living-001", status="active"),
        agent_pid=os.getpid(),
        agent_start_epoch=int(time.time()),
    )


def test_recycled_pid_does_not_keep_the_recorded_agent_alive() -> None:
    """Direction (a): existence of the number is not survival of the agent."""

    record = _ghost_record()

    # Reachability of the guarded branch, proven by the input rather than
    # asserted: this real pid's real start time is past the recorded epoch.
    started_at = probe_process_start_epoch(record.agent_pid)
    assert started_at is not None
    assert started_at > record.agent_start_epoch + START_EPOCH_SLACK_SECONDS

    assert agent_identity_liveness(record) is PidLiveness.DEAD
    assert lifecycle.is_orphaned(record) is True


def test_live_agent_is_never_read_as_dead() -> None:
    """Direction (b): the opposite error, which is the worse one.

    Declaring a living agent dead releases its intent and lets a second agent
    edit the same tree. This pins the identity check against doing that to the
    running process, whose ``agent_start_epoch`` is sampled the way a real
    agent samples it.
    """

    record = _living_record()

    assert agent_identity_liveness(record) is PidLiveness.ALIVE
    assert lifecycle.is_orphaned(record) is False


def test_unreadable_start_time_is_unknown_and_never_dead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail-closed survives: no answer is not the same as a dead answer."""

    monkeypatch.setattr(lifecycle, "probe_process_start_epoch", lambda _pid: None)
    record = _ghost_record()

    assert agent_identity_liveness(record) is PidLiveness.UNKNOWN
    assert lifecycle.is_orphaned(record) is False


def test_absent_pid_stays_dead_without_consulting_the_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pid that does not exist needs no start time to be dead."""

    def _explode(_pid: int) -> int | None:  # pragma: no cover - must not run
        raise AssertionError("start time probed for an already-dead pid")

    monkeypatch.setattr(lifecycle, "probe_process_start_epoch", _explode)
    record = _ghost_record()

    assert agent_identity_liveness(record, base=PidLiveness.DEAD) is PidLiveness.DEAD
    assert (
        agent_identity_liveness(record, base=PidLiveness.UNKNOWN) is PidLiveness.UNKNOWN
    )


def test_ghost_intent_is_recoverable_rather_than_blocking() -> None:
    """The consumer that decides whether foreign work queues behind a ghost.

    ``own_pid=0`` keeps ownership foreign without asserting anything about
    another machine's processes: the own-check is plain tuple equality and
    never probes liveness.
    """

    ownership = classify_intent_ownership(
        _ghost_record(),
        own_pid=0,
        own_start_epoch=0,
        now=utc_now(),
    )

    assert ownership is IntentOwnership.RECOVERABLE


def test_live_foreign_intent_still_blocks() -> None:
    """The same consumer, opposite boundary: a real agent keeps its hold."""

    ownership = classify_intent_ownership(
        _living_record(),
        own_pid=0,
        own_start_epoch=0,
        now=utc_now(),
    )

    assert ownership is IntentOwnership.FOREIGN_ACTIVE


def _simulated_drift(
    start_fraction: float, stamp_offset: float, age: float, probe_delay: float
) -> int | None:
    """One genuine agent, measured: ``start - epoch`` under the three floors.

    ``S`` is the real process start, ``E = S + stamp_offset`` the reading the
    agent floors into its record, ``B = S + age`` the wall clock sampled before
    the probe, and ``t = B + probe_delay`` when ``ps`` actually reads.
    """

    real_start = 1000.0 + start_fraction
    stamped_at = real_start + stamp_offset
    sampled_before = real_start + age
    if stamped_at > sampled_before:
        return None
    elapsed = math.floor(sampled_before + probe_delay - real_start)
    derived_start = math.floor(sampled_before) - elapsed
    return derived_start - math.floor(stamped_at)


def test_measurement_drift_bound_is_re_derived_by_simulation() -> None:
    """Pin the derivation, not the number -- and not a wrong derivation.

    An earlier version of this constant was built by adding the two one-second
    truncations. That double-counts: they share a time base. Search the space
    instead and take the worst case, so the bound is measured rather than
    argued.
    """

    grid = [index / 32 for index in range(32)]
    spans = [index / 16 for index in range(16 * 3)]
    ages = [index / 16 for index in range(16 * 6)]

    observed = {
        drift
        for start_fraction in grid
        for stamp_offset in spans
        for age in ages
        for probe_delay in spans
        if (drift := _simulated_drift(start_fraction, stamp_offset, age, probe_delay))
        is not None
    }

    assert max(observed) == lifecycle._MEASUREMENT_DRIFT_BOUND_SECONDS
    # The worst case is reached, so the bound is tight rather than merely safe.
    assert lifecycle._MEASUREMENT_DRIFT_BOUND_SECONDS in observed


def test_the_clock_margin_is_a_cushion_not_a_new_regime() -> None:
    """Bound the one term that is policy rather than measurement.

    ``_CLOCK_ADJUSTMENT_MARGIN_SECONDS`` cannot be re-derived from the machine
    -- it is a declared cushion. What can be held is its rank: a cushion may
    not outgrow the measured bound it cushions, or a fudge quietly becomes the
    dominant term and the tolerance stops being derived at all. It also may not
    vanish, or the declared protection is gone while its name remains.
    """

    margin = lifecycle._CLOCK_ADJUSTMENT_MARGIN_SECONDS
    bound = lifecycle._MEASUREMENT_DRIFT_BOUND_SECONDS

    assert margin > 0
    assert margin <= bound
    assert bound + margin == START_EPOCH_SLACK_SECONDS


def test_probe_never_overshoots_a_known_child_start_by_a_whole_second() -> None:
    """The live half of the model: real ``ps`` output, real child process.

    The simulation above assumes ``etime`` truncates and that sampling the wall
    clock first keeps the overshoot under a second. This measures that against
    a child whose start instant the test holds to the millisecond.
    """

    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        spawned_at = time.time()
        overshoots = []
        for _ in range(4):
            derived = probe_process_start_epoch(child.pid)
            assert derived is not None
            overshoots.append(derived - spawned_at)
            time.sleep(0.7)
    finally:
        child.kill()
        child.wait()

    assert max(overshoots) < 1.0


def test_an_agent_exactly_on_the_tolerance_reads_alive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The inclusive edge of the boundary.

    A start sitting exactly on ``agent_start_epoch + SLACK`` is still inside
    the declared envelope. Reading it DEAD would release a live agent's intent
    and let a second agent edit the same tree -- the error this module is built
    to refuse. The probe is stubbed because the subject here is the comparison,
    not the reading; the reading has its own live tests above.
    """

    record = _living_record()
    on_the_edge = record.agent_start_epoch + START_EPOCH_SLACK_SECONDS
    monkeypatch.setattr(
        lifecycle, "probe_process_start_epoch", lambda _pid: on_the_edge
    )

    assert agent_identity_liveness(record) is PidLiveness.ALIVE
    assert lifecycle.is_orphaned(record) is False


def test_an_agent_one_second_past_the_tolerance_reads_dead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exclusive neighbour, one second further out.

    A recycled pid's process starts at an arbitrary second, so both this input
    and the one above are reachable; only the comparison separates them.
    """

    record = _living_record()
    past_the_edge = record.agent_start_epoch + START_EPOCH_SLACK_SECONDS + 1
    monkeypatch.setattr(
        lifecycle, "probe_process_start_epoch", lambda _pid: past_the_edge
    )

    assert agent_identity_liveness(record) is PidLiveness.DEAD
    assert lifecycle.is_orphaned(record) is True


def test_probe_reports_absence_for_a_reaped_pid() -> None:
    """The one pid whose death this test owns: a child it reaped itself."""

    child = subprocess.Popen([sys.executable, "-c", "raise SystemExit(0)"])
    child.wait()

    assert probe_process_start_epoch(child.pid) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("00:00", 0),
        ("00:07", 7),
        ("01:30", 90),
        ("02:03:04", 7384),
        ("1-00:00:00", 86400),
        ("3-04:05:06", 273906),
        ("   00:42  \n", 42),
    ],
)
def test_elapsed_field_parses_every_posix_shape(raw: str, expected: int) -> None:
    assert lifecycle._parse_elapsed_seconds(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "not-a-time", "12", "1:2:3:4", "x-00:00", "00:xx", "-1:00"],
)
def test_elapsed_field_refuses_to_guess(raw: str) -> None:
    assert lifecycle._parse_elapsed_seconds(raw) is None


def test_nonpositive_pid_is_never_probed() -> None:
    assert probe_process_start_epoch(0) is None
    assert probe_process_start_epoch(-1) is None


def test_probe_declines_when_the_platform_has_no_ps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No tool to ask means no answer -- and no answer is not a death."""

    monkeypatch.setattr(shutil, "which", lambda _name: None)
    record = _ghost_record()

    assert probe_process_start_epoch(record.agent_pid) is None
    assert agent_identity_liveness(record) is PidLiveness.UNKNOWN


def test_probe_declines_when_the_subprocess_cannot_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A probe that raises must not be read as evidence of anything."""

    def _raise(*_args: object, **_kwargs: object) -> object:
        raise OSError("no fork available")

    monkeypatch.setattr(subprocess, "run", _raise)
    record = _ghost_record()

    assert probe_process_start_epoch(record.agent_pid) is None
    assert agent_identity_liveness(record) is PidLiveness.UNKNOWN


def test_probe_declines_on_output_it_cannot_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A zero exit code carrying unreadable output is still no answer."""

    class _Unreadable:
        returncode = 0
        stdout = "who knows"

    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: _Unreadable())
    record = _ghost_record()

    assert probe_process_start_epoch(record.agent_pid) is None
    assert agent_identity_liveness(record) is PidLiveness.UNKNOWN


def test_declared_liveness_is_not_second_guessed_by_the_kernel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller that declares a pid's fate owns the answer.

    Both halves of the guard are exercised on an input that would otherwise
    flip: a real live pid carrying a 1970 epoch. Without the guard the identity
    check would ask the kernel about pids the declarer never reserved, which is
    the hollow premise reappearing one layer down.
    """

    record = _ghost_record()

    # Half one: a seam this module cannot see reports through the flag.
    assert (
        agent_identity_liveness(record, base=PidLiveness.ALIVE, base_is_declared=True)
        is PidLiveness.ALIVE
    )

    # Half two: this module's own boolean seam, detected rather than passed.
    monkeypatch.setattr(lifecycle, "is_pid_alive", lambda _pid: True)
    assert lifecycle.liveness_probe_is_declared() is True
    assert agent_identity_liveness(record) is PidLiveness.ALIVE
