# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The publication protocol against a collector in another process.

Ruling 2026-09-25 (protocol A): a publisher's run must be rooted from the
very commit that publishes it until the publisher is done with it -- the
bridge stated, the lease released -- and released on every way out.  The
lease guards the run's logical life, the SQLite transaction guards its
bytes, and neither stands in for the other.

Measured on dd7663ed before this module existed: a run that lost the head
race was committed by one transaction and leased by the next, and a
collector in another process that took the write lock between the two
collected it; the bridge then died on ``run_not_published`` and the CLI
exited 5 without writing its report.  The existing owner pins injected their
foreign sweep only AFTER the lease, so they could not see that window.

Every store here lives under ``tmp_path``; the child processes are handed
that path and nothing else, and the parent proves it lies outside every
live CodeClone service directory before it spawns them.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import pytest

import codeclone.core.reporting as reporting_module
from codeclone.canonical import store as store_module
from codeclone.canonical.errors import RunReportLinkError, RunStoreError
from codeclone.canonical.store import HeadState, RunStore
from codeclone.core.canonical_snapshot import RunSnapshotBridgeError
from codeclone.models import (
    GC_COLLECT_UNREACHABLE,
    GC_HOLD_LEASE,
    RUN_SNAPSHOT_PUBLICATION_HEAD_CONFLICT,
    RunSnapshotPublication,
)
from codeclone.utils.sqlite_store import open_sqlite_db
from tests._live_state import discover_live_state_boundary
from tests._publication_race import COMMIT_THEN_LEASE, race, sweep_once
from tests.conftest import RunStoreCorpusRunner
from tests.test_canonical_roundtrip import fixture_model

_ARGS = ("--fail-health", "0", "--min-loc", "3", "--min-stmt", "2")


def _write_tree(root: Path) -> None:
    package = root / "pkg"
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text("", "utf-8")
    units = "\n\n".join(
        f"def unit_{index}(value: int) -> int:\n"
        f'    """Unit {index}."""\n'
        f"    return value + {index}\n"
        for index in range(12)
    )
    (package / "gen.py").write_text(f'"""Gen."""\n\n\n{units}', "utf-8")


def _outside_live_state(path: Path) -> Path:
    """The store path a child process may be handed: never live state."""
    boundary = discover_live_state_boundary()
    assert boundary.state_dir_of(path) is None, path
    assert boundary.live_root_of(path) is None, path
    return path


def _stale_head(_self: RunStore, *, namespace: str, target: str) -> HeadState:
    """A concurrent winner between the head read and the CAS: this
    publisher's run is neither head nor history."""
    return HeadState(namespace=namespace, target=target, generation=7, run_id="x")


# -- a foreign collector between every two commits of the publisher ---------


class _WatchedCursor:
    """A cursor that calls ``after_commit`` once a COMMIT has landed."""

    def __init__(
        self, cursor: sqlite3.Cursor, after_commit: Callable[[], None]
    ) -> None:
        self._cursor = cursor
        self._after_commit = after_commit

    def execute(self, sql: str, *parameters: Any) -> sqlite3.Cursor:
        result = self._cursor.execute(sql, *parameters)
        if sql.strip().upper() == "COMMIT":
            self._after_commit()
        return result

    def __getattr__(self, name: str) -> object:
        return getattr(self._cursor, name)


class _WatchedConnection:
    """The store's connection, with every transaction end observed.

    Keyed on the COMMIT statement itself, not on which step issued it: the
    foreign collector runs after EVERY transaction the publisher commits,
    so no protocol that leaves its run unrooted between any two of its own
    commits survives -- wherever that gap was put.
    """

    def __init__(
        self, connection: sqlite3.Connection, after_commit: Callable[[], None]
    ) -> None:
        self._connection = connection
        self._after_commit = after_commit

    def cursor(self) -> _WatchedCursor:
        return _WatchedCursor(self._connection.cursor(), self._after_commit)

    def commit(self) -> None:
        self._connection.commit()
        self._after_commit()

    def __getattr__(self, name: str) -> object:
        return getattr(self._connection, name)


@dataclass
class _ForeignCollector:
    db: Path
    sweeps: list[dict[str, object]] = field(default_factory=list)

    def sweep(self) -> None:
        self.sweeps.append(sweep_once(self.db))


@pytest.fixture
def publications(monkeypatch: pytest.MonkeyPatch) -> list[RunSnapshotPublication]:
    """Every publication witness the process mints, read on its class."""
    minted: list[RunSnapshotPublication] = []
    real = RunSnapshotPublication.__post_init__

    def recorded(publication: RunSnapshotPublication) -> None:
        real(publication)
        minted.append(publication)

    monkeypatch.setattr(RunSnapshotPublication, "__post_init__", recorded)
    return minted


def test_no_foreign_collector_between_two_publisher_commits_takes_the_run_early(
    tmp_path: Path,
    run_store_cli: RunStoreCorpusRunner,
    monkeypatch: pytest.MonkeyPatch,
    publications: list[RunSnapshotPublication],
) -> None:
    """The run that lost the head race is rooted from its first visible
    moment until its lease is released, against a collector in another
    process that sweeps with no history window after EVERY commit.

    The collector collects the run exactly once, and that sweep is the
    first one to see the bridge written and the lease gone.  The positive
    control is built in: the same collector does collect the run -- after
    the release -- so "it was never collected" cannot be why this passes.
    """
    root = tmp_path / "corpus"
    _write_tree(root)
    db = _outside_live_state(tmp_path / "runs.sqlite3")
    foreign = _ForeignCollector(db)
    real_open = open_sqlite_db

    def watched_open(*args: Any, **kwargs: Any) -> _WatchedConnection:
        return _WatchedConnection(real_open(*args, **kwargs), foreign.sweep)

    monkeypatch.setattr(store_module, "open_sqlite_db", watched_open)
    monkeypatch.setattr(RunStore, "head", _stale_head)
    run_store_cli(root, *_ARGS, "--json", str(root / "report.json"), store=db)

    lost = publications[-1]
    assert lost.outcome == RUN_SNAPSHOT_PUBLICATION_HEAD_CONFLICT
    seen = [
        sweep
        for sweep in foreign.sweeps
        if lost.run_id in cast("list[str]", sweep["runs_before"])
    ]
    collected = [
        sweep
        for sweep in seen
        if cast("dict[str, int]", sweep["collected"])[GC_COLLECT_UNREACHABLE]
    ]
    assert len(collected) == 1, foreign.sweeps
    held = seen[: seen.index(collected[0])]
    assert held, "no foreign sweep ran while the run was in flight"
    assert all(
        cast("dict[str, int]", sweep["held"])[GC_HOLD_LEASE] == 1 for sweep in held
    ), held
    assert (collected[0]["edges_before"], collected[0]["leases_before"]) == (1, 0), (
        "the run was collected before its bridge was written and its lease released"
    )
    assert json.loads((root / "report.json").read_text("utf-8"))["meta"]


# -- the publication's own lease, at the store -------------------------------


def test_a_publication_grants_its_in_flight_lease_in_the_publishing_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The lease row exists exactly when the run does: an ``active`` lease
    with the caller's time to live, in the same commit; a malformed request
    rolls the whole publication back instead of publishing an unrooted run."""
    monkeypatch.setattr(store_module, "_lease_now", lambda: 1_000)
    with RunStore(tmp_path / "runs.sqlite3") as store:
        with pytest.raises(RunStoreError, match="must be positive"):
            store.write_full_run(
                fixture_model(),
                namespace="ns",
                target="t",
                expected_generation=-1,
                in_flight_lease=("pub:1", 0),
            )
        with pytest.raises(RunStoreError, match="non-empty"):
            store.write_full_run(
                fixture_model(),
                namespace="ns",
                target="t",
                expected_generation=-1,
                in_flight_lease=("", 60),
            )
        assert store._connection.execute("SELECT COUNT(*) FROM runs").fetchone() == (0,)
        receipt = store.write_full_run(
            fixture_model(),
            namespace="ns",
            target="t",
            expected_generation=-1,
            in_flight_lease=("pub:1", 60),
        )
        leases = store._connection.execute(
            "SELECT l.lease_id, r.run_id, l.kind, l.expires_at FROM run_leases l "
            "JOIN runs r ON r.run_pk = l.run_pk"
        ).fetchall()
    assert receipt.head_advanced is False
    assert leases == [("pub:1", receipt.run_id, "active", 1_060)]


# -- the lease is released on every way out of the report --------------------


def _raise_bridge(**_kwargs: object) -> object:
    raise RunSnapshotBridgeError("the two halves disagree")


def _raise_link(**_kwargs: object) -> object:
    raise RunReportLinkError("the store refused the edge")


def _raise_seal() -> Callable[..., dict[str, object]]:
    def seal(**_kwargs: object) -> dict[str, object]:
        raise RuntimeError("the document could not be sealed")

    return seal


@pytest.mark.parametrize(
    ("name", "replacement"),
    [
        pytest.param("bridge_run_snapshot", _raise_bridge, id="bridge"),
        pytest.param("persist_run_snapshot_link", _raise_link, id="link"),
        pytest.param("_load_report_document_finalizer", _raise_seal, id="seal"),
    ],
)
def test_the_in_flight_lease_is_released_whatever_ends_the_report(
    tmp_path: Path,
    run_store_cli: RunStoreCorpusRunner,
    monkeypatch: pytest.MonkeyPatch,
    publications: list[RunSnapshotPublication],
    name: str,
    replacement: Callable[..., object],
) -> None:
    """A report that dies after its publication still ends the in-flight
    operation: the lease is gone, and the run is left exactly as rooted as
    the store says -- here, nothing but garbage for the next sweep."""
    root = tmp_path / "corpus"
    _write_tree(root)
    db = tmp_path / "runs.sqlite3"
    monkeypatch.setattr(RunStore, "head", _stale_head)
    monkeypatch.setattr(reporting_module, name, replacement)
    with pytest.raises(AssertionError, match="INTERNAL_ERROR: 5"):
        run_store_cli(root, *_ARGS, "--json", str(root / "report.json"), store=db)

    lost = publications[-1]
    assert lost.in_flight_lease
    with RunStore(db, create=False) as store:
        leases = store._connection.execute("SELECT lease_id FROM run_leases").fetchall()
        runs = {
            str(row[0]) for row in store._connection.execute("SELECT run_id FROM runs")
        }
    assert leases == [], "the lease outlived the report that held it"
    assert lost.run_id in runs


# -- N publishers, M readers, G collectors, in separate processes ------------


@dataclass(frozen=True)
class _Load:
    publishers: int
    iterations: int
    readers: int
    sweepers: int


#: The suite's load: two publishers that win the head and two that always
#: lose it, two readers and two collectors that sweep with no history window
#: as fast as the write lock lets them.  The lab driver runs the same
#: instrument at larger N/M/K (REPORT, part A).
_SUITE_LOAD = _Load(publishers=4, iterations=6, readers=2, sweepers=2)


@pytest.fixture
def race_db(tmp_path: Path) -> Iterator[Path]:
    yield _outside_live_state(tmp_path / "race.sqlite3")


def test_no_leased_run_vanishes_under_concurrent_publishers_readers_and_collectors(
    race_db: Path,
) -> None:
    """The rule's DoD, in separate processes: every publisher's run is
    still there at its bridge, whether it won the head or lost it, while
    other publishers publish and collectors sweep with no history window;
    no process breaks.

    Probe validity, stated as assertions: the population holds runs that
    only a lease roots (``head_conflict`` > 0), the collectors really
    collected (released lost runs), and every child loaded this checkout.
    """
    result = race(
        race_db,
        publishers=_SUITE_LOAD.publishers,
        iterations=_SUITE_LOAD.iterations,
        readers=_SUITE_LOAD.readers,
        sweepers=_SUITE_LOAD.sweepers,
    )
    assert result.crashes() == []
    assert result.total("publishers", "vanished") == 0, result.publishers
    assert result.outcome("head_conflict") > 0
    assert result.outcome("published") > 0
    assert result.total("sweepers", "collected") > 0
    assert result.total("readers", "reads") > 0
    assert result.loaded() == {str(Path(store_module.__file__))}


def test_the_race_instrument_sees_a_run_vanish_when_the_lease_trails_the_commit(
    race_db: Path,
) -> None:
    """The positive control of the proof above, on the same causal path: the
    shape before protocol A -- publish, then lease in a second transaction
    -- with a window between the two.  The same collectors take the lost
    runs in that window, so a zero above is the protocol's, not the
    instrument's."""
    result = race(
        race_db,
        publishers=2,
        iterations=4,
        readers=0,
        sweepers=2,
        protocol=COMMIT_THEN_LEASE,
        window=0.1,
    )
    assert result.crashes() == []
    assert result.total("publishers", "vanished") > 0, result.publishers
