# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The registry's retention window, cell by cell of its decision table.

A sweep holds a run for the first reason that applies, in the receipt's
fixed order -- head, history (the retention window: the newest registered
runs, none past its age bound), retained, lease, staging -- and collects
every run none applies to.  Every cell below is one store state and the one
answer it must give; the age is set on the store's own clock, never waited.

=====================================  ==================================
the run                                the sweep
=====================================  ==================================
head of any target (any age, any       held: head
registration)
registered, among the newest           held: history
``max_runs`` registered, newest
record younger than ``max_age``
registered, older than ``max_age``     collected (unless a root below)
registered, ranked past ``max_runs``   collected (unless a root below)
retained by the operator               held: retained
under a live lease (intent,            held: lease
publisher, export)
under an expired lease                 collected (the lease dissolves)
staging (``published = 0``)            held: staging
linked by the bridge, no record        collected
published, neither linked nor          collected
recorded
=====================================  ==================================

And for the records themselves: the newest record of a report whose run
survives is kept whatever its rank; past the ``max_execution_records`` newest, every
other record leaves -- the bound of the expiry witness.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from codeclone.canonical.executions import (
    EXECUTION_AVAILABLE,
    EXECUTION_EXPIRED,
    RetentionWindow,
)
from codeclone.canonical.store import (
    RunStore,
    RunStoreRetentionJob,
    acquire_run_lease,
    collect_garbage,
    link_run_report,
    registered_report_execution,
    retain_run,
)
from codeclone.models import (
    GC_HOLD_HEAD,
    GC_HOLD_HISTORY,
    GC_HOLD_LEASE,
    GC_HOLD_RETAINED,
    GC_HOLD_STAGING,
    GcJobReport,
)
from tests._run_store_execution_fixtures import (
    ROOT,
    Clock,
    publish,
    register,
    report_of,
)

_DAY = 24 * 60 * 60
_WINDOW = RetentionWindow(
    max_runs=4, max_age_seconds=7 * _DAY, max_execution_records=32
)
_START = 1_800_000_000


def _run_ids(path: Path) -> set[str]:
    with closing(sqlite3.connect(path)) as raw:
        return {str(row[0]) for row in raw.execute("SELECT run_id FROM runs")}


def _held(report: GcJobReport) -> dict[str, int]:
    return {reason: count for reason, count in report.held if count}


def _sweep(store: RunStore, window: RetentionWindow | None = _WINDOW) -> GcJobReport:
    return collect_garbage(store, retain_history=0, window=window)


# -- the window: rank and age ------------------------------------------------


def test_the_window_holds_exactly_the_newest_max_runs_registered_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Six registered runs, one apart in time: the newest four stay -- the
    newest as head, three as history -- and the two oldest leave.  A window
    of five or of three gives a different survivor set."""
    clock = Clock(monkeypatch, _START)
    path = tmp_path / "runs.sqlite3"
    with RunStore(path) as store:
        runs = []
        for label in ("a", "b", "c", "d", "e", "f"):
            runs.append(register(store, label).receipt.run_id)
            clock.advance(60)
        report = _sweep(store)
    assert _run_ids(path) == set(runs[2:])
    assert _held(report) == {GC_HOLD_HEAD: 1, GC_HOLD_HISTORY: 3}
    assert report.collected == (("unreachable", 2),)


@pytest.mark.parametrize(
    ("age", "held"),
    [(7 * _DAY - 1, True), (7 * _DAY, False), (30 * _DAY, False)],
)
def test_no_registered_run_outlives_the_age_bound_whatever_its_rank(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, age: int, held: bool
) -> None:
    """Held until the deadline, collected AT it (the one deadline law)."""
    clock = Clock(monkeypatch, _START)
    path = tmp_path / "runs.sqlite3"
    with RunStore(path) as store:
        old = register(store, "a").receipt.run_id
        clock.advance(age)
        register(store, "b")
        _sweep(store)
    assert (old in _run_ids(path)) is held


def test_a_run_registered_again_takes_the_rank_and_the_age_of_its_newest_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Clock(monkeypatch, _START)
    path = tmp_path / "runs.sqlite3"
    with RunStore(path) as store:
        first = register(store, "a", execution="exec-a-1").receipt.run_id
        for label in ("b", "c", "d"):
            clock.advance(60)
            register(store, label)
        clock.advance(8 * _DAY)
        register(store, "a", execution="exec-a-2")
        _sweep(store)
    # "a" is the newest again; "b".."d" are past the age bound.
    assert _run_ids(path) == {first}


def test_a_head_is_held_whatever_its_age_and_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The head of a target is its compare-and-swap line, never collected:
    a profile target whose last run is a month old keeps it."""
    clock = Clock(monkeypatch, _START)
    path = tmp_path / "runs.sqlite3"
    with RunStore(path) as store:
        profile = register(store, "p", target="clones-only").receipt.run_id
        clock.advance(30 * _DAY)
        latest = register(store, "a").receipt.run_id
        report = _sweep(store)
    assert _run_ids(path) == {profile, latest}
    assert _held(report) == {GC_HOLD_HEAD: 2}


def test_the_window_counts_every_target_of_the_store_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Clock(monkeypatch, _START)
    path = tmp_path / "runs.sqlite3"
    with RunStore(path) as store:
        runs = []
        for index, label in enumerate("abcdef"):
            target = "clones-only" if index % 2 else "canonical"
            runs.append(register(store, label, target=target).receipt.run_id)
            clock.advance(60)
        report = _sweep(store)
    assert _run_ids(path) == set(runs[2:])
    assert _held(report) == {GC_HOLD_HEAD: 2, GC_HOLD_HISTORY: 2}


# -- the other roots, beside the window -------------------------------------------


def test_a_live_lease_holds_a_run_past_the_window_and_an_expired_one_does_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Clock(monkeypatch, _START)
    path = tmp_path / "runs.sqlite3"
    with RunStore(path) as store:
        leased = register(store, "a").receipt.run_id
        acquire_run_lease(
            store, leased, kind="session", lease_id="intent:test", ttl_seconds=30 * _DAY
        )
        clock.advance(7 * _DAY + 1)
        for label in "bcde":
            register(store, label)
        held = _sweep(store)
        assert leased in _run_ids(path)
        clock.advance(30 * _DAY)
        _sweep(store)
    assert _held(held)[GC_HOLD_LEASE] == 1
    assert leased not in _run_ids(path)


def test_an_operators_retention_holds_a_run_past_every_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Clock(monkeypatch, _START)
    path = tmp_path / "runs.sqlite3"
    with RunStore(path) as store:
        kept = register(store, "a").receipt.run_id
        retain_run(store, kept)
        clock.advance(30 * _DAY)
        for label in "bcde":
            register(store, label)
        report = _sweep(store)
    assert kept in _run_ids(path)
    assert _held(report)[GC_HOLD_RETAINED] == 1


def test_a_staging_row_is_held_and_never_ranked(tmp_path: Path) -> None:
    path = tmp_path / "runs.sqlite3"
    with RunStore(path) as store:
        staged = register(store, "a").receipt.run_id
        register(store, "b")
    with closing(sqlite3.connect(path)) as raw:
        raw.execute("UPDATE runs SET published = 0 WHERE run_id = ?", (staged,))
        raw.commit()
    with RunStore(path, create=False) as store:
        report = _sweep(store)
    assert staged in _run_ids(path)
    assert _held(report)[GC_HOLD_STAGING] == 1


def test_a_run_linked_without_a_record_and_one_never_linked_are_collected(
    tmp_path: Path,
) -> None:
    """A surface that writes the bridge and no record (the CLI), and a run
    nobody linked (a gate-only run), are promised to nobody: the window,
    which counts registrations, does not hold them."""
    path = tmp_path / "runs.sqlite3"
    with RunStore(path) as store:
        linked = publish(store, "a")
        link_run_report(
            store,
            run_id=linked.run_id,
            report_run_identity=report_of("a"),
            expected_scope_digest=linked.analysis_scope_digest,
        )
        unlinked = publish(store, "b")
        head = register(store, "c").receipt.run_id
        report = _sweep(store)
    assert _run_ids(path) == {head}
    assert report.collected == (("unreachable", 2),)
    assert {linked.run_id, unlinked.run_id}.isdisjoint(_run_ids(path))


def test_without_a_window_a_registration_holds_nothing_and_no_record_leaves(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runs.sqlite3"
    with RunStore(path) as store:
        old = register(store, "a").receipt.run_id
        register(store, "b")
        report = _sweep(store, window=None)
    assert old not in _run_ids(path)
    assert dict(report.detail)["execution_records_collected"] == 0
    with closing(sqlite3.connect(path)) as raw:
        assert raw.execute("SELECT count(*) FROM run_executions").fetchone()[0] == 2


# -- the records: findable, then witnesses, then gone ----------------------------


def test_a_collected_runs_record_witnesses_its_expiry_until_the_record_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Clock(monkeypatch, _START)
    window = RetentionWindow(
        max_runs=1, max_age_seconds=7 * _DAY, max_execution_records=3
    )
    path = tmp_path / "runs.sqlite3"
    with RunStore(path) as store:
        register(store, "a")
        clock.advance(60)
        register(store, "b")
        _sweep(store, window)
        witness = registered_report_execution(store, root=ROOT, run_id=report_of("a"))
        for label in "cd":
            clock.advance(60)
            register(store, label)
        report = _sweep(store, window)
        gone = registered_report_execution(store, root=ROOT, run_id=report_of("a"))
        newest = registered_report_execution(store, root=ROOT, run_id=report_of("d"))
    assert witness is not None and witness.availability == EXECUTION_EXPIRED
    assert gone is None
    assert newest is not None and newest.availability == EXECUTION_AVAILABLE
    assert dict(report.detail)["execution_records_collected"] == 1


def test_a_held_runs_newest_record_is_kept_past_the_record_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Many executions of one run push an older run's only record past the
    bound; while that run is held its record stays, or it could not be
    found by its report although the store still holds it."""
    clock = Clock(monkeypatch, _START)
    window = RetentionWindow(
        max_runs=2, max_age_seconds=7 * _DAY, max_execution_records=2
    )
    path = tmp_path / "runs.sqlite3"
    with RunStore(path) as store:
        register(store, "a")
        for index in range(4):
            clock.advance(60)
            register(store, "b", execution=f"exec-b-{index}")
        _sweep(store, window)
        older = registered_report_execution(store, root=ROOT, run_id=report_of("a"))
        with closing(sqlite3.connect(path)) as raw:
            left = sorted(
                str(row[0])
                for row in raw.execute("SELECT execution_event_id FROM run_executions")
            )
    assert older is not None and older.availability == EXECUTION_AVAILABLE
    assert left == ["exec-a", "exec-b-2", "exec-b-3"]


# -- the job the GC orchestrator runs ---------------------------------------------


def test_the_retention_job_sweeps_under_its_window_and_names_the_store_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Clock(monkeypatch, _START)
    path = tmp_path / "runs.sqlite3"
    with RunStore(path) as store:
        runs = []
        for label in "abcdef":
            runs.append(register(store, label).receipt.run_id)
            clock.advance(60)
        job = RunStoreRetentionJob(store=store, window=_WINDOW)
        report = job.collect()
    assert job.name == "canonical_run_store"
    assert _run_ids(path) == set(runs[2:])
    assert _held(report) == {GC_HOLD_HEAD: 1, GC_HOLD_HISTORY: 3}


def test_the_retention_job_answers_a_moved_generation_with_a_typed_refusal(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runs.sqlite3"
    with RunStore(path) as store, RunStore(path) as other:
        register(store, "a")
        other.bump_store_epoch()
        report = RunStoreRetentionJob(store=store, window=_WINDOW).collect()
    assert report.refusal is not None
    assert "store generation moved" in report.refusal
    assert report.candidates == 0
