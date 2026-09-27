# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The production owner of run-store GC, pinned on the path that runs it.

The substrate (``collect_garbage``, the §8 roots, the leases, the physical
release) is pinned as a library in ``test_canonical_store_gc``; what those
pins cannot see is whether anything in the product ever calls it.  Every run
below goes through the real CLI waterfall (``run_store_cli``), and the sweep
is counted on the ``RunStoreGcJob`` CLASS OBJECT, which the process holds
exactly one of: a count taken there sees the owner's call through every
binding, so ``sweeps == 1`` is a statement about the edge from the
publication to the substrate, not about a spelling of it.

The receipt is read off the carrier the publication outcome already rides --
every ``RunSnapshotPublication`` the process mints, observed on its class --
and compared with numbers measured from the store itself immediately before
the sweep, so a receipt that invented its counts could not agree with them.

The subject is ring r2 throughout; the CLI is reached through the conftest
fixture, exactly as ``test_run_store_producer_wiring`` does, so no r4 import
turns this module into a new architecture-ratchet entry.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import pytest

import codeclone.core.reporting as reporting_module
from codeclone.canonical import store as store_module
from codeclone.canonical.store import (
    HeadState,
    RunStore,
    RunStoreGcJob,
    acquire_run_lease,
    collect_garbage,
    retain_run,
)
from codeclone.core.canonical_snapshot import (
    RUN_SNAPSHOT_NAMESPACE,
    bridge_run_snapshot,
    persist_run_snapshot_link,
    release_publication_lease,
)
from codeclone.models import (
    CANONICAL_HEAD_TARGET,
    GC_COLLECT_UNREACHABLE,
    GC_HOLD_HEAD,
    GC_HOLD_HISTORY,
    GC_HOLD_LEASE,
    GC_HOLD_RETAINED,
    GC_HOLD_STAGING,
    RUN_SNAPSHOT_PUBLICATION_DISABLED,
    RUN_SNAPSHOT_PUBLICATION_FAILED,
    RUN_SNAPSHOT_PUBLICATION_HEAD_CONFLICT,
    RUN_SNAPSHOT_PUBLICATION_PUBLISHED,
    GcJobReport,
    RunSnapshotLink,
    RunSnapshotPublication,
    RunStoreConfig,
)
from tests.conftest import RunStoreCorpusRunner

_ARGS = (
    "--fail-health",
    "0",
    "--api-surface",
    "--min-loc",
    "3",
    "--min-stmt",
    "2",
)

#: The stated lifetime of an in-flight lease nobody released: one day.
_ONE_DAY = 24 * 60 * 60

#: One generated module whose every unit carries the run's tag, so each run
#: owns objects no other run shares: a sweep that collects a run then has
#: exclusive rows to delete and pages to hand back.  A run whose objects
#: were all shared would collect nothing physical, and a pin reading the
#: file would be green for any implementation.
_UNITS_PER_RUN = 90


def _write_run(root: Path, tag: str) -> None:
    package = root / "pkg"
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text("", "utf-8")
    units = "\n\n".join(
        f"def unit_{tag}_{index}(value: int) -> int:\n"
        f'    """Unit {index} of run {tag}."""\n'
        f"    return value + {index}\n"
        for index in range(_UNITS_PER_RUN)
    )
    (package / "gen.py").write_text(f'"""Run {tag}."""\n\n\n{units}', "utf-8")


# -- instruments -------------------------------------------------------------


@dataclass(frozen=True)
class _StoreState:
    """The store as the file itself states it, read at the sweep boundary."""

    page_count: int
    freelist_count: int
    head_run_id: str
    #: sha256 of the canonical bytes of every published run.
    run_bytes: dict[str, str]
    #: Objects referenced by exactly one run, keyed by that run.
    exclusive_objects: dict[str, int]
    runs: int


def _read_state(store: RunStore) -> _StoreState:
    connection = store._connection
    published = [
        str(row[0])
        for row in connection.execute(
            "SELECT run_id FROM runs WHERE published = 1 ORDER BY run_id"
        )
    ]
    exclusive = dict.fromkeys(published, 0)
    for run_id, count in connection.execute(
        "SELECT r.run_id, COUNT(*) FROM run_members m "
        "JOIN runs r ON r.run_pk = m.run_pk "
        "WHERE m.object_pk IN (SELECT object_pk FROM run_members "
        "GROUP BY object_pk HAVING COUNT(*) = 1) GROUP BY r.run_id"
    ):
        exclusive[str(run_id)] = int(count)
    head = store.head(namespace=RUN_SNAPSHOT_NAMESPACE, target=CANONICAL_HEAD_TARGET)
    return _StoreState(
        page_count=int(connection.execute("PRAGMA page_count").fetchone()[0]),
        freelist_count=int(connection.execute("PRAGMA freelist_count").fetchone()[0]),
        head_run_id="" if head is None else head.run_id,
        run_bytes={
            run_id: hashlib.sha256(store.project_run(run_id)).hexdigest()
            for run_id in published
        },
        exclusive_objects=exclusive,
        runs=int(connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0]),
    )


@dataclass
class _Sweep:
    before: _StoreState
    report: GcJobReport | None = None
    after: _StoreState | None = None


@dataclass
class _Meters:
    """Every sweep dispatched, every publication minted, every store opened."""

    sweeps: list[_Sweep] = field(default_factory=list)
    publications: list[RunSnapshotPublication] = field(default_factory=list)
    store_opens: int = 0

    def last_publication(self) -> RunSnapshotPublication:
        assert self.publications, "no publication was minted"
        return self.publications[-1]


@pytest.fixture
def meters(monkeypatch: pytest.MonkeyPatch) -> _Meters:
    """Install the three meters on the CLASS OBJECTS the product uses.

    A class attribute is looked up on the type, so every binding that
    reaches ``RunStoreGcJob.collect``, ``RunSnapshotPublication`` or
    ``RunStore`` is counted -- a re-import, an alias, a future owner module.
    """
    recorded = _Meters()
    real_collect = RunStoreGcJob.collect
    real_post_init = RunSnapshotPublication.__post_init__
    real_init = RunStore.__init__

    def measured_collect(job: RunStoreGcJob) -> GcJobReport:
        sweep = _Sweep(before=_read_state(job.store))
        recorded.sweeps.append(sweep)
        sweep.report = real_collect(job)
        sweep.after = _read_state(job.store)
        return sweep.report

    def recorded_post_init(publication: RunSnapshotPublication) -> None:
        real_post_init(publication)
        recorded.publications.append(publication)

    def counted_init(store: RunStore, *args: object, **kwargs: object) -> None:
        recorded.store_opens += 1
        real_init(store, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(RunStoreGcJob, "collect", measured_collect)
    monkeypatch.setattr(RunSnapshotPublication, "__post_init__", recorded_post_init)
    monkeypatch.setattr(RunStore, "__init__", counted_init)
    return recorded


@dataclass(frozen=True)
class _Corpus:
    root: Path
    store: Path
    cli: RunStoreCorpusRunner

    def publish(self, tag: str, *, enabled: bool = True) -> None:
        """One real CLI analysis of the tagged tree, rendering a document so
        the identity bridge is stated and persisted on every run."""
        _write_run(self.root, tag)
        self.cli(
            self.root,
            *_ARGS,
            "--json",
            str(self.root / f"report-{tag}.json"),
            store=self.store if enabled else None,
        )

    @contextmanager
    def open(self) -> Iterator[RunStore]:
        with RunStore(self.store, create=False) as store:
            yield store


@pytest.fixture
def corpus(tmp_path: Path, run_store_cli: RunStoreCorpusRunner) -> _Corpus:
    root = tmp_path / "corpus"
    root.mkdir()
    return _Corpus(root=root, store=tmp_path / "runs.sqlite3", cli=run_store_cli)


def _receipt(
    *,
    candidates: int,
    held: dict[str, int],
    collected: int = 0,
    history_pruned: int = 0,
    leases_expired: int = 0,
    objects_collected: int = 0,
) -> GcJobReport:
    """The expected receipt of one sweep, every lane spelled."""
    return GcJobReport.build(
        job="canonical_run_store",
        candidates=candidates,
        held={
            GC_HOLD_HEAD: 0,
            GC_HOLD_HISTORY: 0,
            GC_HOLD_LEASE: 0,
            GC_HOLD_RETAINED: 0,
            GC_HOLD_STAGING: 0,
            **held,
        },
        collected={GC_COLLECT_UNREACHABLE: collected},
        detail={
            "history_rows_pruned": history_pruned,
            "leases_expired": leases_expired,
            "objects_collected": objects_collected,
        },
    )


def _run_ids(store: RunStore) -> set[str]:
    return {str(row[0]) for row in store._connection.execute("SELECT run_id FROM runs")}


def _lease_rows(store: RunStore) -> list[tuple[str, str]]:
    return [
        (str(row[0]), str(row[1]))
        for row in store._connection.execute(
            "SELECT lease_id, kind FROM run_leases ORDER BY lease_id"
        )
    ]


def _linked_edges(store: RunStore, run_id: str) -> int:
    """Identity-bridge edges persisted for one run."""
    row = store._connection.execute(
        "SELECT COUNT(*) FROM run_report_links l JOIN runs r "
        "ON r.run_pk = l.run_pk WHERE r.run_id = ?",
        (run_id,),
    ).fetchone()
    return int(row[0])


# -- reachability: when, and how many times ----------------------------------


def test_every_stored_publication_is_swept_once_and_carries_the_receipt(
    corpus: _Corpus, meters: _Meters
) -> None:
    """The owner calls the substrate on the production path, exactly once,
    AFTER the publication committed, and the answer rides the publication.

    Three facts, each a different mutation home: the count (an owner that
    never dispatches the job, or dispatches it twice), the moment (a sweep
    run before the write sees another head), and the carrier (a receipt
    computed and dropped is a silent GC).
    """
    corpus.publish("a")

    assert len(meters.sweeps) == 1, "one stored publication, one sweep"
    sweep = meters.sweeps[0]
    publication = meters.last_publication()
    assert publication.outcome == RUN_SNAPSHOT_PUBLICATION_PUBLISHED
    assert sweep.before.head_run_id == publication.run_id, (
        "the sweep ran before its own publication had moved the head"
    )
    assert publication.collection is sweep.report, (
        "the receipt the publication carries is not the one the substrate returned"
    )
    assert publication.collection == _receipt(candidates=1, held={GC_HOLD_HEAD: 1})


def test_the_history_window_holds_exactly_one_superseded_generation(
    corpus: _Corpus, meters: _Meters
) -> None:
    """The window is the smallest one whose history root is not the head root.

    With a window of one, the only history row a sweep keeps is the head's
    own, so the retained-history class of W4 §8 would exist in production
    and hold nothing; with two, the generation this publication superseded
    stays readable through exactly one more publication.  Both edges are
    pinned: the superseded run survives the next sweep as ``history``, and
    the run superseded twice is collected.
    """
    for tag in ("a", "b", "c"):
        corpus.publish(tag)
    first, second, third = meters.sweeps
    run_a = first.before.head_run_id

    assert second.report == _receipt(
        candidates=2, held={GC_HOLD_HEAD: 1, GC_HOLD_HISTORY: 1}
    ), "the generation this publication superseded was not held as history"
    exclusive_a = third.before.exclusive_objects[run_a]
    assert exclusive_a > 0, "the population carries no object only the victim owns"
    assert third.report == _receipt(
        candidates=3,
        held={GC_HOLD_HEAD: 1, GC_HOLD_HISTORY: 1},
        collected=1,
        history_pruned=1,
        objects_collected=exclusive_a,
    ), "a run superseded twice must leave, with exactly its own objects"
    with corpus.open() as store:
        assert run_a not in _run_ids(store)


def test_the_owners_sweep_hands_pages_back_and_leaves_rooted_bytes_alone(
    corpus: _Corpus, meters: _Meters
) -> None:
    """Physical reclamation on the production path, read off the file.

    The collected run must leave the FILE (page count down, freelist empty),
    and every run that stayed rooted must project to the very bytes it
    projected before the sweep -- deletion never breaks a neighbour through
    shared immutable objects.
    """
    for tag in ("a", "b", "c"):
        corpus.publish(tag)
    sweep = meters.sweeps[-1]
    assert sweep.after is not None
    victim = meters.sweeps[0].before.head_run_id
    assert sweep.before.freelist_count == 0
    assert sweep.after.page_count < sweep.before.page_count, (
        f"the sweep kept every page: {sweep.after.page_count} of "
        f"{sweep.before.page_count}"
    )
    assert sweep.after.freelist_count == 0, "freed pages were left on the freelist"
    survivors = dict(sweep.before.run_bytes)
    del survivors[victim]
    assert sweep.after.run_bytes == survivors


# -- leases: every root class of W4 §8 holds against the owner ---------------


def _root(store: RunStore, run_id: str, how: str) -> None:
    if how == "retained":
        retain_run(store, run_id)
        return
    acquire_run_lease(
        store, run_id, kind=how, lease_id=f"test-{how}", ttl_seconds=_ONE_DAY
    )


def _stage_unpublished_run(store: RunStore) -> None:
    """A committed unpublished run: the staging root's only shape."""
    cursor = store._connection.cursor()
    cursor.execute("BEGIN IMMEDIATE")
    cursor.execute(
        "INSERT INTO runs (namespace_pk, run_id, analysis_scope_digest, "
        "membership_digest, published) "
        "SELECT namespace_pk, 'staged', 'scope', 'members', 0 "
        "FROM namespaces LIMIT 1"
    )
    cursor.execute("COMMIT")


def test_every_root_class_survives_the_owners_sweep(
    corpus: _Corpus, meters: _Meters
) -> None:
    """Explicit retention, the three lease kinds, staging -- and a control.

    Each rooted run is published and rooted, then pushed out of the history
    window by later publications, so only its own root can still hold it.
    The unrooted ``e`` run is the positive control: the same sweep that holds
    the other four collects it, so "nothing was collected" can never be the
    reason the rooted runs survive.
    """
    roots = {"a": "retained", "b": "session", "c": "export", "d": "active"}
    rooted: dict[str, str] = {}
    for tag in ("a", "b", "c", "d", "e"):
        corpus.publish(tag)
        head = meters.last_publication().run_id
        if tag in roots:
            with corpus.open() as store:
                _root(store, head, roots[tag])
            rooted[tag] = head
    with corpus.open() as store:
        _stage_unpublished_run(store)
    corpus.publish("f")
    corpus.publish("g")

    final = meters.sweeps[-1]
    control = final.before.exclusive_objects[meters.sweeps[4].before.head_run_id]
    assert final.report == _receipt(
        candidates=8,
        held={
            GC_HOLD_HEAD: 1,
            GC_HOLD_HISTORY: 1,
            GC_HOLD_RETAINED: 1,
            GC_HOLD_LEASE: 3,
            GC_HOLD_STAGING: 1,
        },
        collected=1,
        history_pruned=1,
        objects_collected=control,
    )
    with corpus.open() as store:
        present = _run_ids(store)
    assert set(rooted.values()) <= present
    assert "staged" in present


def _stale_head(_self: RunStore, *, namespace: str, target: str) -> HeadState:
    """A concurrent winner between the head read and the CAS."""
    return HeadState(namespace=namespace, target=target, generation=7, run_id="x")


def test_a_run_that_lost_the_head_race_is_held_until_its_bridge_is_written(
    corpus: _Corpus, meters: _Meters, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The in-flight lease: the publisher's own run through its own report.

    A run that lost the CAS is never head and never history, so between its
    commit and its bridge nothing but a lease roots it.  A foreign sweep is
    injected at the worst moment -- after the owner's own sweep, before the
    bridge is stated -- and must hold the run; the bridge must then persist,
    and the lease must be gone once the report is done.  The next ordinary
    publication then collects the run, which proves the lease was the hold.
    """
    foreign: list[GcJobReport] = []

    def sweep_then_bridge(
        *,
        publication: RunSnapshotPublication,
        report_document: Mapping[str, object] | None,
    ) -> RunSnapshotLink:
        with corpus.open() as other:
            foreign.append(collect_garbage(other, retain_history=0))
        return bridge_run_snapshot(
            publication=publication, report_document=report_document
        )

    with monkeypatch.context() as patch:
        patch.setattr(RunStore, "head", _stale_head)
        patch.setattr(reporting_module, "bridge_run_snapshot", sweep_then_bridge)
        corpus.publish("a")
    lost = meters.last_publication()
    assert lost.outcome == RUN_SNAPSHOT_PUBLICATION_HEAD_CONFLICT
    assert lost.collection == _receipt(candidates=1, held={GC_HOLD_LEASE: 1})
    assert foreign == [_receipt(candidates=1, held={GC_HOLD_LEASE: 1})]
    with corpus.open() as store:
        assert _linked_edges(store, lost.run_id) == 1, (
            "the bridge of the lost run was not persisted"
        )
        assert _lease_rows(store) == [], "the in-flight lease outlived its report"

    corpus.publish("b")
    assert meters.sweeps[-1].report == _receipt(
        candidates=2,
        held={GC_HOLD_HEAD: 1},
        collected=1,
        objects_collected=meters.sweeps[-1].before.exclusive_objects[lost.run_id],
    )


def test_the_bridge_is_written_under_the_lease_and_only_then_released(
    corpus: _Corpus, meters: _Meters, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The in-flight window ends in one order: bridge first, release second.

    Two readings of that order, on a run that lost the head race (so the
    lease is the only thing rooting it).  At the bridge write the store is
    read: the publisher's lease must still hold the run.  The release is
    then followed, inside the same call, by a foreign collector: the moment
    the lease goes the lost run is garbage, so that sweep collects it -- and
    it reads, before sweeping, that the edge was already written.  Release
    before the bridge and the collector takes the run first, and the bridge
    is left addressing a row that no longer exists.
    """
    held_at_bridge: list[bool] = []
    linked_at_release: list[int] = []
    foreign: list[GcJobReport] = []

    def lease_held() -> bool:
        lease = meters.last_publication().in_flight_lease
        with corpus.open() as store:
            return lease in {lease_id for lease_id, _kind in _lease_rows(store)}

    def watched_bridge_write(*, store_path: Path, link: RunSnapshotLink) -> bool:
        held_at_bridge.append(lease_held())
        return persist_run_snapshot_link(store_path=store_path, link=link)

    def release_then_collect(
        *, config: RunStoreConfig, publication: RunSnapshotPublication
    ) -> bool:
        released = release_publication_lease(config=config, publication=publication)
        with corpus.open() as other:
            linked_at_release.append(_linked_edges(other, publication.run_id))
            foreign.append(RunStoreGcJob(store=other, retain_history=2).collect())
        return released

    with monkeypatch.context() as patch:
        patch.setattr(RunStore, "head", _stale_head)
        patch.setattr(
            reporting_module, "persist_run_snapshot_link", watched_bridge_write
        )
        patch.setattr(
            reporting_module, "release_publication_lease", release_then_collect
        )
        corpus.publish("a")
    lost = meters.last_publication()
    assert lost.outcome == RUN_SNAPSHOT_PUBLICATION_HEAD_CONFLICT
    assert held_at_bridge == [True], "the bridge was written after the lease went"
    assert linked_at_release == [1], "the lease went before the bridge was written"
    assert [report.collected_count(GC_COLLECT_UNREACHABLE) for report in foreign] == [
        1
    ], "the release did not leave the lost run to the collector"
    with corpus.open() as store:
        assert lost.run_id not in _run_ids(store)
        assert _lease_rows(store) == []


def test_an_unreleased_in_flight_lease_dissolves_one_day_after_its_grant(
    corpus: _Corpus, meters: _Meters, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A publisher that died before its report released nothing: the grant's
    own deadline is the backstop, and it is one day -- held one second
    before, collected at the deadline."""
    moment = 5_000_000
    monkeypatch.setattr(store_module, "_lease_now", lambda: moment)
    with monkeypatch.context() as patch:
        patch.setattr(RunStore, "head", _stale_head)
        patch.setattr(
            reporting_module, "release_publication_lease", lambda **_kwargs: False
        )
        corpus.publish("a")
    orphan = meters.last_publication().run_id
    with corpus.open() as store:
        assert [kind for _lease, kind in _lease_rows(store)] == ["active"]
        monkeypatch.setattr(store_module, "_lease_now", lambda: moment + _ONE_DAY - 1)
        assert collect_garbage(store, retain_history=0).held_count(GC_HOLD_LEASE) == 1
        monkeypatch.setattr(store_module, "_lease_now", lambda: moment + _ONE_DAY)
        swept = collect_garbage(store, retain_history=0)
        assert swept.collected_count(GC_COLLECT_UNREACHABLE) == 1
        assert orphan not in _run_ids(store)


# -- fail-closed: a refused substrate is a typed receipt ---------------------


@dataclass
class _WriteLockHolder:
    """A second connection holding the write lock while the owner works.

    The owner's handle is made to give up at once instead of waiting out the
    shared five-second busy timeout: the refusal is SQLite's own
    ``database is locked``, reached through the real ``BEGIN IMMEDIATE``.
    The lock is dropped when the publishing handle closes, so the rest of the
    report (the bridge, the release) runs against a free store.
    """

    path: Path
    blocker: sqlite3.Connection | None = None

    def engage(self, store: RunStore) -> None:
        store._connection.execute("PRAGMA busy_timeout = 0")
        self.blocker = sqlite3.connect(self.path, isolation_level=None)
        self.blocker.execute("BEGIN IMMEDIATE")

    def disengage(self) -> None:
        if self.blocker is not None:
            self.blocker.execute("ROLLBACK")
            self.blocker.close()
            self.blocker = None


def _lock_after(
    monkeypatch: pytest.MonkeyPatch,
    holder: _WriteLockHolder,
    owner: object,
    name: str,
) -> None:
    """Engage the lock right after ``owner.name`` returns on a store."""
    real: Callable[..., object] = getattr(owner, name)

    def locked(*args: object, **kwargs: object) -> object:
        result = real(*args, **kwargs)
        store = next(arg for arg in args if isinstance(arg, RunStore))
        holder.engage(store)
        return result

    real_close = RunStore.close

    def close_and_release(store: RunStore) -> None:
        holder.disengage()
        real_close(store)

    monkeypatch.setattr(owner, name, locked)
    monkeypatch.setattr(RunStore, "close", close_and_release)


def test_a_refused_substrate_is_a_typed_receipt_and_the_publication_stands(
    corpus: _Corpus, meters: _Meters, monkeypatch: pytest.MonkeyPatch
) -> None:
    """IMMEDIATE not obtained for the sweep that follows a publication.

    The publication is stored and says so, its in-flight lease was granted
    by the publishing transaction itself (there is no separate lease step
    left to refuse -- protocol A), the receipt is a claim-free refusal naming
    the cause, nothing was collected (the run the sweep would have taken is
    still there), the lease is released, and the analysis finishes.
    """
    corpus.publish("a")
    corpus.publish("b")
    run_a = meters.sweeps[0].before.head_run_id
    sweeps_before = len(meters.sweeps)
    with monkeypatch.context() as patch:
        _lock_after(patch, _WriteLockHolder(corpus.store), RunStore, "write_full_run")
        corpus.publish("c")

    refused = meters.last_publication()
    assert refused.outcome == RUN_SNAPSHOT_PUBLICATION_PUBLISHED
    assert refused.collection is not None
    assert refused.collection.refusal is not None
    assert refused.collection.refusal.startswith("sweep not completed")
    assert "database is locked" in refused.collection.refusal
    assert refused.in_flight_lease
    assert [sweep.report for sweep in meters.sweeps[sweeps_before:]] == [None]
    with corpus.open() as store:
        assert {run_a, refused.run_id} <= _run_ids(store)
        assert _lease_rows(store) == []


def test_a_release_the_store_refuses_does_not_fail_the_analysis(
    corpus: _Corpus, meters: _Meters, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ending the in-flight operation is best effort: the lease's deadline is
    the backstop, so a store that vanished before the release may not take
    the analysis down with it."""

    def persist_then_vanish(*, store_path: Path, link: RunSnapshotLink) -> bool:
        persisted = persist_run_snapshot_link(store_path=store_path, link=link)
        corpus.store.unlink()
        return persisted

    monkeypatch.setattr(
        reporting_module, "persist_run_snapshot_link", persist_then_vanish
    )
    corpus.publish("a")
    assert meters.last_publication().in_flight_lease
    report = json.loads((corpus.root / "report-a.json").read_text("utf-8"))
    assert report["meta"]["analysis_mode"] == "full"


# -- the rollout stays the kill switch ---------------------------------------


def test_a_disabled_rollout_never_sweeps_and_never_opens_a_store(
    corpus: _Corpus, meters: _Meters
) -> None:
    corpus.publish("a", enabled=False)
    publication = meters.last_publication()
    assert publication.outcome == RUN_SNAPSHOT_PUBLICATION_DISABLED
    assert publication.collection is None
    assert publication.in_flight_lease == ""
    assert meters.sweeps == []
    assert meters.store_opens == 0
    assert not corpus.store.exists()


def test_an_unstored_publication_is_never_swept(
    corpus: _Corpus, meters: _Meters, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing stored, nothing to collect after: the owner runs only behind
    a stored publication, and the release never opens a store for it."""

    def _refuse(**_kwargs: object) -> object:
        raise RuntimeError("the producer edge came apart")

    monkeypatch.setattr(
        "codeclone.core.canonical_snapshot.canonical_snapshot_from_producers", _refuse
    )
    corpus.publish("a")
    publication = meters.last_publication()
    assert publication.outcome == RUN_SNAPSHOT_PUBLICATION_FAILED
    assert publication.collection is None
    assert meters.sweeps == []
    assert meters.store_opens == 0


def test_the_release_reads_no_store_the_rollout_does_not_name(
    meters: _Meters,
) -> None:
    """Handed a leased publication under a rollout that names no store, the
    release answers ``False`` without constructing one -- the kill switch
    holds for the release as it does for every other store reader."""
    leased = _stored(
        collection=_receipt(candidates=1, held={GC_HOLD_HEAD: 1}),
        in_flight_lease="publication:1:lease",
    )
    released = release_publication_lease(
        config=RunStoreConfig(enabled=False), publication=leased
    )
    assert released is False
    assert meters.store_opens == 0


# -- the receipt's carrier refuses a claim it cannot hold --------------------


def _stored(**overrides: object) -> RunSnapshotPublication:
    fields: dict[str, object] = {
        "outcome": RUN_SNAPSHOT_PUBLICATION_PUBLISHED,
        "admissible": True,
        "target": CANONICAL_HEAD_TARGET,
        "run_id": "r" * 64,
        "generation": 1,
        "analysis_scope_digest": "s" * 64,
    }
    fields.update(overrides)
    return RunSnapshotPublication(**fields)  # type: ignore[arg-type]


def test_a_collection_rides_only_a_stored_publication() -> None:
    receipt = _receipt(candidates=1, held={GC_HOLD_HEAD: 1})
    assert _stored(collection=receipt, in_flight_lease="l").collection is receipt
    with pytest.raises(ValueError, match="never swept"):
        RunSnapshotPublication(
            outcome=RUN_SNAPSHOT_PUBLICATION_DISABLED,
            admissible=False,
            collection=receipt,
        )
    with pytest.raises(ValueError, match="never swept"):
        RunSnapshotPublication(
            outcome=RUN_SNAPSHOT_PUBLICATION_DISABLED,
            admissible=False,
            in_flight_lease="l",
        )
    with pytest.raises(ValueError, match="receipt travels with it"):
        _stored(in_flight_lease="l")
