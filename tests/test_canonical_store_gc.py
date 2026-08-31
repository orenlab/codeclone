# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Run-store GC (ruling 2026-08-24 §8): roots, leases, sweep, snapshot.

Every root has a test that its removal would redden (the mutation law: a
guard no input reaches is theater), the sharing invariant is proven on a
pair of runs the publish receipt itself witnesses as sharing storage, and
the crash probe proves the sweep is one atom — not a transactional
intention.
"""

from __future__ import annotations

import io
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest

from codeclone.api.gc import run_gc
from codeclone.canonical import (
    CanonicalModel,
    PublishReceipt,
    RunStore,
    UnknownRunError,
    export_run,
)
from codeclone.canonical import store as store_module
from codeclone.canonical.errors import RunStoreError
from codeclone.canonical.store import (
    RunStoreGcJob,
    acquire_run_lease,
    collect_garbage,
    release_retained_run,
    release_run_lease,
    retain_run,
)
from codeclone.models import (
    GC_COLLECT_UNREACHABLE,
    GC_HOLD_HEAD,
    GC_HOLD_HISTORY,
    GC_HOLD_LEASE,
    GC_HOLD_RETAINED,
    GC_HOLD_STAGING,
    GcJobReport,
)
from tests.test_canonical_roundtrip import fixture_model

_NS = "lineage-gc"
_TARGET = "worktree-gc"


def _store(tmp_path: Path, name: str = "runs.sqlite") -> RunStore:
    return RunStore(tmp_path / name)


def _publish(
    store: RunStore, model: CanonicalModel, *, expected_generation: int = 0
) -> PublishReceipt:
    return store.write_full_run(
        model,
        namespace=_NS,
        target=_TARGET,
        expected_generation=expected_generation,
    )


def _wider_model(*labels: str) -> CanonicalModel:
    """A state sharing every fixture object and adding one per label."""
    model = fixture_model()
    coupled = set(model.coupled_sets)
    for label in labels:
        coupled.add(frozenset({label}))
    return replace(model, coupled_sets=frozenset(coupled))


def _report(
    *,
    candidates: int,
    held: dict[str, int],
    collected: int,
    history_pruned: int = 0,
    leases_expired: int = 0,
    objects_collected: int = 0,
) -> GcJobReport:
    """The expected receipt of one sweep, spelled in full every time."""
    base = {
        GC_HOLD_HEAD: 0,
        GC_HOLD_HISTORY: 0,
        GC_HOLD_LEASE: 0,
        GC_HOLD_RETAINED: 0,
        GC_HOLD_STAGING: 0,
    }
    base.update(held)
    return GcJobReport.build(
        job="canonical_run_store",
        candidates=candidates,
        held=base,
        collected={GC_COLLECT_UNREACHABLE: collected},
        detail={
            "history_rows_pruned": history_pruned,
            "leases_expired": leases_expired,
            "objects_collected": objects_collected,
        },
    )


# -- the invariant: deletion never breaks a neighbour -----------------------


def test_deleting_a_run_never_breaks_a_neighbour_through_shared_objects(
    tmp_path: Path,
) -> None:
    """§8's load-bearing line, proven on a REALLY shared pair.

    The witness comes first: the survivor's publish receipt must show that
    every one of its objects was already the neighbour's (maximal content
    sharing), or this test would be comparing two independent runs and
    prove nothing.  Then the neighbour is swept, and the survivor must
    stay readable and byte-identical — while the swept run's one exclusive
    object is actually gone, so the sweep collected garbage and only
    garbage.
    """
    wide = _wider_model("OnlyInFirst")
    narrow = fixture_model()
    with _store(tmp_path) as store:
        first = _publish(store, wide)
        second = _publish(store, narrow, expected_generation=1)
        # The instrument is on: the surviving run shares EVERY object with
        # the run about to be deleted, and stored nothing of its own.
        assert second.shared_objects == second.object_count
        assert second.new_objects == 0
        assert first.object_count == second.object_count + 1
        survivor_bytes = store.project_run(second.run_id)

        report = collect_garbage(store, retain_history=1)

        assert report == _report(
            candidates=2,
            held={GC_HOLD_HEAD: 1},
            collected=1,
            history_pruned=1,
            objects_collected=1,
        )
        assert store.project_run(second.run_id) == survivor_bytes
        sink = io.BytesIO()
        export_run(store, second.run_id, sink)
        assert sink.getvalue() == survivor_bytes
        with pytest.raises(UnknownRunError):
            store.read_run(first.run_id)


# -- each root, separately (mutation homes) ---------------------------------


def test_head_root_alone_holds_the_current_head_run(tmp_path: Path) -> None:
    """retain_history=0 empties the history root entirely, so the current
    head survives through the heads table and nothing else."""
    with _store(tmp_path) as store:
        first = _publish(store, fixture_model())
        second = _publish(store, _wider_model("OnlyInSecond"), expected_generation=1)
        head_bytes = store.project_run(second.run_id)

        report = collect_garbage(store, retain_history=0)

        assert report == _report(
            candidates=2, held={GC_HOLD_HEAD: 1}, collected=1, history_pruned=2
        )
        assert store.project_run(second.run_id) == head_bytes
        with pytest.raises(UnknownRunError):
            store.read_run(first.run_id)
        assert store.head(namespace=_NS, target=_TARGET) is not None


def test_history_root_holds_exactly_the_retained_window(tmp_path: Path) -> None:
    """Three generations, a window of two: the superseded-but-retained run
    survives through head_history, the one beyond the window is collected."""
    with _store(tmp_path) as store:
        first = _publish(store, fixture_model())
        second = _publish(store, _wider_model("Mid"), expected_generation=1)
        third = _publish(store, _wider_model("Mid", "New"), expected_generation=2)
        middle_bytes = store.project_run(second.run_id)

        report = collect_garbage(store, retain_history=2)

        assert report == _report(
            candidates=3,
            held={GC_HOLD_HEAD: 1, GC_HOLD_HISTORY: 1},
            collected=1,
            history_pruned=1,
        )
        assert store.project_run(second.run_id) == middle_bytes
        assert store.read_run(third.run_id)
        with pytest.raises(UnknownRunError):
            store.read_run(first.run_id)


def test_retained_run_root_is_set_and_cleared_only_by_the_operator(
    tmp_path: Path,
) -> None:
    """Explicit retention survives any sweep until explicitly released —
    the one root whose owner is a decision, not a process."""
    with _store(tmp_path) as store:
        first = _publish(store, fixture_model())
        _publish(store, _wider_model("OnlyInSecond"), expected_generation=1)
        assert retain_run(store, first.run_id) is True
        assert retain_run(store, first.run_id) is False

        held = collect_garbage(store, retain_history=0)
        assert held == _report(
            candidates=2,
            held={GC_HOLD_HEAD: 1, GC_HOLD_RETAINED: 1},
            collected=0,
            history_pruned=2,
        )
        assert store.read_run(first.run_id)

        assert release_retained_run(store, first.run_id) is True
        assert release_retained_run(store, first.run_id) is False
        swept = collect_garbage(store, retain_history=0)
        assert swept.collected_count(GC_COLLECT_UNREACHABLE) == 1
        with pytest.raises(UnknownRunError):
            store.read_run(first.run_id)


def test_lease_root_holds_until_the_deadline_then_dissolves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A live lease roots the run; the sweep's clock passing the deadline
    dissolves the grant and collects the run — the crash-of-the-owner
    story, told without the owner ever calling release."""
    moment = 1_000_000
    monkeypatch.setattr(store_module, "_lease_now", lambda: moment)
    with _store(tmp_path) as store:
        first = _publish(store, fixture_model())
        _publish(store, _wider_model("OnlyInSecond"), expected_generation=1)
        expires_at = acquire_run_lease(
            store, first.run_id, kind="session", lease_id="session-a", ttl_seconds=300
        )
        assert expires_at == moment + 300

        held = collect_garbage(store, retain_history=0)
        assert held == _report(
            candidates=2,
            held={GC_HOLD_HEAD: 1, GC_HOLD_LEASE: 1},
            collected=0,
            history_pruned=2,
        )
        assert store.read_run(first.run_id)

        monkeypatch.setattr(store_module, "_lease_now", lambda: moment + 301)
        swept = collect_garbage(store, retain_history=0)
        assert swept == _report(
            candidates=2,
            held={GC_HOLD_HEAD: 1},
            collected=1,
            leases_expired=1,
        )
        with pytest.raises(UnknownRunError):
            store.read_run(first.run_id)


def test_a_lease_expires_exactly_at_its_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The boundary of the shared deadline law, pinned at the store level:
    expired AT the deadline, not one tick later."""
    moment = 2_000_000
    monkeypatch.setattr(store_module, "_lease_now", lambda: moment)
    with _store(tmp_path) as store:
        first = _publish(store, fixture_model())
        _publish(store, _wider_model("OnlyInSecond"), expected_generation=1)
        acquire_run_lease(
            store, first.run_id, kind="active", lease_id="op-1", ttl_seconds=50
        )
        monkeypatch.setattr(store_module, "_lease_now", lambda: moment + 50)
        report = collect_garbage(store, retain_history=0)
        assert report.collected_count(GC_COLLECT_UNREACHABLE) == 1
        assert dict(report.detail)["leases_expired"] == 1
        with pytest.raises(UnknownRunError):
            store.read_run(first.run_id)


def test_lease_renewal_moves_the_deadline_of_the_same_grant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    moment = 3_000_000
    monkeypatch.setattr(store_module, "_lease_now", lambda: moment)
    with _store(tmp_path) as store:
        first = _publish(store, fixture_model())
        assert (
            acquire_run_lease(
                store, first.run_id, kind="export", lease_id="exp-1", ttl_seconds=10
            )
            == moment + 10
        )
        monkeypatch.setattr(store_module, "_lease_now", lambda: moment + 5)
        assert (
            acquire_run_lease(
                store, first.run_id, kind="export", lease_id="exp-1", ttl_seconds=10
            )
            == moment + 15
        )
        assert release_run_lease(store, "exp-1") is True
        assert release_run_lease(store, "exp-1") is False


def test_lease_grants_are_typed_refusals_not_guesses(tmp_path: Path) -> None:
    """The grant API refuses everything that would make a lease a lie: an
    unknown run, an unknown kind, a non-positive TTL (an eternal lease has
    no representation), an empty id, and a rebind of an existing id."""
    with _store(tmp_path) as store:
        first = _publish(store, fixture_model())
        with pytest.raises(UnknownRunError):
            acquire_run_lease(
                store, "no-such-run", kind="session", lease_id="s", ttl_seconds=10
            )
        with pytest.raises(RunStoreError, match="unknown lease kind"):
            acquire_run_lease(
                store, first.run_id, kind="forever", lease_id="s", ttl_seconds=10
            )
        with pytest.raises(RunStoreError, match="eternal lease"):
            acquire_run_lease(
                store, first.run_id, kind="session", lease_id="s", ttl_seconds=0
            )
        with pytest.raises(RunStoreError, match="must be an integer"):
            acquire_run_lease(
                store, first.run_id, kind="session", lease_id="s", ttl_seconds=True
            )
        with pytest.raises(RunStoreError, match="non-empty"):
            acquire_run_lease(
                store, first.run_id, kind="session", lease_id="", ttl_seconds=10
            )
        acquire_run_lease(
            store, first.run_id, kind="session", lease_id="s", ttl_seconds=10
        )
        with pytest.raises(RunStoreError, match="different run or kind"):
            acquire_run_lease(
                store, first.run_id, kind="export", lease_id="s", ttl_seconds=10
            )


def test_retention_requires_a_published_run(tmp_path: Path) -> None:
    with _store(tmp_path) as store:
        _publish(store, fixture_model())
        with pytest.raises(UnknownRunError):
            retain_run(store, "no-such-run")
        with pytest.raises(UnknownRunError):
            release_retained_run(store, "no-such-run")
        with pytest.raises(RunStoreError, match="non-negative"):
            collect_garbage(store, retain_history=-1)
        with pytest.raises(RunStoreError, match="non-negative"):
            collect_garbage(store, retain_history=True)


def test_a_committed_unpublished_run_is_staging_protected_and_reported(
    tmp_path: Path,
) -> None:
    """The staging root: today a publish's unpublished rows live only
    inside its own transaction, so a COMMITTED unpublished run can only
    come from the future multi-transaction staging path — the sweep
    protects it and says so, never guesses it into garbage."""
    with _store(tmp_path) as store:
        _publish(store, fixture_model())
        cursor = store._connection.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "INSERT INTO runs (namespace_pk, run_id, analysis_scope_digest, "
            "membership_digest, published) "
            "SELECT namespace_pk, 'staged-by-future-path', 'scope', 'members', 0 "
            "FROM namespaces LIMIT 1"
        )
        cursor.execute("COMMIT")

        report = collect_garbage(store, retain_history=1)

        assert report == _report(
            candidates=2, held={GC_HOLD_HEAD: 1, GC_HOLD_STAGING: 1}, collected=0
        )
        row = store._connection.execute(
            "SELECT COUNT(*) FROM runs WHERE published = 0"
        ).fetchone()
        assert row is not None and int(row[0]) == 1


# -- crash in the middle -----------------------------------------------------


@contextmanager
def _crash_before_commit(store: RunStore) -> Iterator[sqlite3.Cursor]:
    """Dies inside the fenced transaction: after the sweep's last delete,
    before COMMIT — the crash lands at the transaction owner."""
    with _real_fenced_transaction(store) as cursor:
        yield cursor
        raise RuntimeError("injected crash before the sweep's commit")


_real_fenced_transaction = store_module._fenced_transaction


def test_a_crash_mid_sweep_leaves_no_partially_collected_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Atomicity proven by probe, not intention: the injected crash lands
    after every delete was staged and before COMMIT — the worst moment —
    and the store must come back whole: victim still readable
    byte-identically, history and head untouched, and a later sweep on a
    healthy handle collects exactly what the crashed one was about to."""
    path = tmp_path / "runs.sqlite"
    with RunStore(path) as store:
        first = _publish(store, fixture_model())
        second = _publish(store, _wider_model("OnlyInSecond"), expected_generation=1)
        victim_bytes = store.project_run(first.run_id)
        head_bytes = store.project_run(second.run_id)

        monkeypatch.setattr(store_module, "_fenced_transaction", _crash_before_commit)
        with pytest.raises(RuntimeError, match="injected crash"):
            collect_garbage(store, retain_history=0)

        assert store.project_run(first.run_id) == victim_bytes
        assert store.project_run(second.run_id) == head_bytes
        history = store._connection.execute(
            "SELECT COUNT(*) FROM head_history"
        ).fetchone()
        assert history is not None and int(history[0]) == 2

    monkeypatch.setattr(store_module, "_fenced_transaction", _real_fenced_transaction)
    with _store(tmp_path) as healthy:
        report = collect_garbage(healthy, retain_history=0)
        assert report == _report(
            candidates=2,
            held={GC_HOLD_HEAD: 1},
            collected=1,
            history_pruned=2,
            objects_collected=0,
        )
        assert healthy.project_run(second.run_id) == head_bytes


# -- what a sweep never touches, held by mechanism ---------------------------


def test_foreign_keys_refuse_deleting_a_rooted_run_even_for_a_buggy_sweep(
    tmp_path: Path,
) -> None:
    """The hold is a constraint, not a convention: even a sweep whose root
    computation went wrong cannot delete a run the heads table roots, nor
    an object a surviving membership references — SQLite refuses the row."""
    with _store(tmp_path) as store:
        _publish(store, fixture_model())
        with pytest.raises(sqlite3.IntegrityError):
            store._connection.execute("DELETE FROM runs")
        with pytest.raises(sqlite3.IntegrityError):
            store._connection.execute("DELETE FROM objects")


def test_the_sweep_leaves_meta_witness_namespaces_and_heads_alone(
    tmp_path: Path,
) -> None:
    with _store(tmp_path) as store:
        _publish(store, fixture_model())
        _publish(store, _wider_model("OnlyInSecond"), expected_generation=1)
        before = {
            table: sorted(store._connection.execute(f"SELECT * FROM {table}"))
            for table in ("store_meta", "witness", "namespaces", "heads")
        }
        collect_garbage(store, retain_history=0)
        after = {
            table: sorted(store._connection.execute(f"SELECT * FROM {table}"))
            for table in ("store_meta", "witness", "namespaces", "heads")
        }
        assert after == before


# -- receipts: a measured zero is not silence --------------------------------


def test_a_sweep_that_collects_nothing_still_answers_in_full(
    tmp_path: Path,
) -> None:
    with _store(tmp_path) as store:
        _publish(store, fixture_model())
        report = collect_garbage(store, retain_history=1)
        assert report == _report(candidates=1, held={GC_HOLD_HEAD: 1}, collected=0)


def test_an_empty_store_sweeps_to_an_answered_zero(tmp_path: Path) -> None:
    with _store(tmp_path) as store:
        report = collect_garbage(store, retain_history=1)
        assert report == _report(candidates=0, held={}, collected=0)


# -- the job under the unified protocol --------------------------------------


def test_the_run_store_job_answers_the_protocol_by_name(tmp_path: Path) -> None:
    with _store(tmp_path) as store:
        first = _publish(store, fixture_model())
        _publish(store, _wider_model("OnlyInSecond"), expected_generation=1)
        job = RunStoreGcJob(store=store, retain_history=0)
        assert job.name == "canonical_run_store"

        receipt = run_gc([job])

        assert len(receipt.reports) == 1
        assert receipt.reports[0] == _report(
            candidates=2,
            held={GC_HOLD_HEAD: 1},
            collected=1,
            history_pruned=2,
        )
        with pytest.raises(UnknownRunError):
            store.read_run(first.run_id)


def test_a_moved_store_generation_is_a_typed_refusal_not_a_defect(
    tmp_path: Path,
) -> None:
    """The one anticipated concurrent outcome: another handle migrated the
    store under this one.  The job answers with a visible refusal report —
    claim-free by protocol law — instead of an exception, and the store
    remains exactly as it was."""
    path = tmp_path / "runs.sqlite"
    with _store(tmp_path) as stale, RunStore(path) as mover:
        first = _publish(stale, fixture_model())
        mover.bump_store_epoch()

        report = RunStoreGcJob(store=stale, retain_history=0).collect()

        assert report.job == "canonical_run_store"
        assert report.refusal is not None
        assert "store generation moved" in report.refusal
        assert report.candidates == 0
        assert report.held == ()
        assert report.collected == ()
        assert mover.read_run(first.run_id)


# -- §11.1: the export sees one snapshot ------------------------------------


class _SweepingSeamStore(RunStore):
    """Fires a concurrent collector's commit between resolution and stream."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.collector: RunStore | None = None

    def _pin_export(self, run_id: str) -> None:
        if self.collector is not None:
            collect_garbage(self.collector, retain_history=0)


def test_export_streams_one_snapshot_under_a_concurrent_sweep(
    tmp_path: Path,
) -> None:
    """A collector committing mid-export must not change the export's
    universe (brief §11.1): the stream is served from one read snapshot
    from the first byte to the last, byte-identical to the pre-sweep
    projection — never a torn refusal, never mixed generations.  Measured
    red before the export transaction existed: the concurrent commit
    turned the export into a membership-digest integrity refusal."""
    path = tmp_path / "runs.sqlite"
    seam_store = _SweepingSeamStore(path)
    with seam_store as store:
        superseded = _publish(store, fixture_model())
        _publish(store, _wider_model("OnlyInSecond"), expected_generation=1)
        expected = store.project_run(superseded.run_id)
        with _store(tmp_path) as collector:
            seam_store.collector = collector
            sink = io.BytesIO()
            envelope = export_run(store, superseded.run_id, sink)
            seam_store.collector = None
        assert sink.getvalue() == expected
        assert envelope.run_id == superseded.run_id
        # After the export released its snapshot, the sweep's world is
        # real: the superseded run is gone.
        with pytest.raises(UnknownRunError):
            store.read_run(superseded.run_id)
