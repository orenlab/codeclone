# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Processes for the publication-protocol race proofs, one role each.

Run as ``python -m tests._publication_race <role> <json-arguments>``; every
role prints exactly one JSON line on stdout and exits 0 unless the process
itself broke.  The roles act on a store under a temporary root that the
parent names, never on a live one, and every role reports which
``codeclone.canonical.store`` it actually loaded, read in the child.

* ``sweep``      -- one collection with no history window: the most
  aggressive collector the store admits, reporting what it saw first.
* ``publisher``  -- publish, sweep, state the bridge, release: the
  publication protocol, iteration after iteration.
* ``sweeper``    -- collect with no history window until told to stop.
* ``reader``     -- open, read the head, read one family, until told to stop.

``race`` in the parent runs N publishers, M readers and G sweepers at once
and aggregates their lines; it is shared by the suite and by the lab driver
so both measure with the same instrument.

What a publisher counts as ``vanished`` is the one failure the protocol
exists to rule out: its own run, published by it and not yet released, gone
(``run_not_published``) at the bridge.  Anything else unexpected is a
``crash``.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from codeclone.canonical.model import CanonicalModel
    from codeclone.canonical.store import PublishReceipt
    from codeclone.models import GcJobReport

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Protocols a publisher can run.  ``production`` is the product's own
#: publication step; ``commit_then_lease`` re-enacts the shape the product had
#: before the lease moved into the publishing transaction -- publish, wait
#: ``window`` seconds, then lease -- and exists only as the positive control
#: that the instrument can see a run vanish when such a window exists.
PRODUCTION = "production"
COMMIT_THEN_LEASE = "commit_then_lease"

_NAMESPACE = "codeclone.analysis"
_TARGET = "canonical"
_ONE_DAY = 24 * 60 * 60


def _loaded() -> str:
    import codeclone.canonical.store as store_module

    return str(store_module.__file__)


def _model(label: str) -> CanonicalModel:
    """A small canonical model that is its own run: the roundtrip fixture
    plus one coupled set named by ``label``."""
    from tests.test_canonical_roundtrip import fixture_model

    model = fixture_model()
    return replace(
        model, coupled_sets=frozenset({*model.coupled_sets, frozenset({label})})
    )


# -- roles -------------------------------------------------------------------


def _sweep(arguments: Mapping[str, object]) -> dict[str, object]:
    from codeclone.canonical.store import RunStore, collect_garbage

    with RunStore(str(arguments["db"]), create=False) as store:
        connection = store._connection
        runs = [
            str(row[0])
            for row in connection.execute(
                "SELECT run_id FROM runs WHERE published = 1 ORDER BY run_id"
            )
        ]
        edges = int(
            connection.execute("SELECT COUNT(*) FROM run_report_links").fetchone()[0]
        )
        leases = int(
            connection.execute("SELECT COUNT(*) FROM run_leases").fetchone()[0]
        )
        report = collect_garbage(store, retain_history=0)
    return {
        "runs_before": runs,
        "edges_before": edges,
        "leases_before": leases,
        "held": dict(report.held),
        "collected": dict(report.collected),
    }


@contextmanager
def _stale_heads(stale: bool) -> Iterator[None]:
    """A publisher that always loses the head race: its head read answers a
    generation no store ever holds, so the CAS never moves for it and its
    run is rooted by nothing but its own lease."""
    from codeclone.canonical.store import HeadState, RunStore

    if not stale:
        yield
        return
    real = RunStore.head

    def stale_head(_self: RunStore, *, namespace: str, target: str) -> HeadState:
        return HeadState(namespace=namespace, target=target, generation=-1, run_id="x")

    setattr(RunStore, "head", stale_head)  # noqa: B010
    try:
        yield
    finally:
        setattr(RunStore, "head", real)  # noqa: B010


def _publish_production(
    db: Path, model: CanonicalModel
) -> tuple[PublishReceipt, str, GcJobReport]:
    from codeclone.canonical.store import RunStore
    from codeclone.core.canonical_snapshot import _publish_and_collect

    with RunStore(db, create=True) as store:
        return _publish_and_collect(store, model, namespace=_NAMESPACE, target=_TARGET)


def _publish_commit_then_lease(
    db: Path, model: CanonicalModel, *, window: float, lease_id: str
) -> tuple[PublishReceipt, str, GcJobReport]:
    from codeclone.canonical.store import (
        RunStore,
        RunStoreGcJob,
        acquire_run_lease,
    )

    with RunStore(db) as store:
        head = store.head(namespace=_NAMESPACE, target=_TARGET)
        receipt = store.write_full_run(
            model,
            namespace=_NAMESPACE,
            target=_TARGET,
            expected_generation=0 if head is None else head.generation,
        )
        time.sleep(window)
        acquire_run_lease(
            store,
            receipt.run_id,
            kind="active",
            lease_id=lease_id,
            ttl_seconds=_ONE_DAY,
        )
        collection = RunStoreGcJob(store=store, retain_history=2).collect()
    return receipt, lease_id, collection


def _bridge_and_release(
    db: Path,
    receipt: PublishReceipt,
    lease_id: str,
    collection: GcJobReport,
    label: str,
) -> None:
    from codeclone.core.canonical_snapshot import (
        persist_run_snapshot_link,
        release_publication_lease,
    )
    from codeclone.models import (
        RUN_SNAPSHOT_LINK_LINKED,
        RUN_SNAPSHOT_PUBLICATION_HEAD_CONFLICT,
        RUN_SNAPSHOT_PUBLICATION_PUBLISHED,
        RunSnapshotLink,
        RunSnapshotPublication,
        RunStoreConfig,
    )

    run_id = receipt.run_id
    scope = receipt.analysis_scope_digest
    outcome = (
        RUN_SNAPSHOT_PUBLICATION_PUBLISHED
        if receipt.head_advanced
        else RUN_SNAPSHOT_PUBLICATION_HEAD_CONFLICT
    )
    publication = RunSnapshotPublication(
        outcome=outcome,
        admissible=True,
        target=_TARGET,
        run_id=run_id,
        generation=receipt.generation,
        analysis_scope_digest=scope,
        collection=collection,
        in_flight_lease=lease_id,
    )
    try:
        persist_run_snapshot_link(
            store_path=db,
            link=RunSnapshotLink(
                state=RUN_SNAPSHOT_LINK_LINKED,
                outcome=outcome,
                store_run_id=run_id,
                analysis_scope_digest=scope,
                report_run_identity=hashlib.sha256(label.encode()).hexdigest(),
            ),
        )
    finally:
        release_publication_lease(
            config=RunStoreConfig(enabled=True, path=db), publication=publication
        )


def _publisher(arguments: Mapping[str, object]) -> dict[str, object]:
    from codeclone.canonical.errors import UNKNOWN_RUN_NOT_PUBLISHED, UnknownRunError

    db = Path(str(arguments["db"]))
    index = int(cast("int", arguments["index"]))
    protocol = str(arguments["protocol"])
    window = float(cast("float", arguments["window"]))
    outcomes = {"published": 0, "head_conflict": 0}
    vanished: list[str] = []
    crashes: list[str] = []
    started = time.perf_counter()
    with _stale_heads(bool(arguments["stale"])):
        for iteration in range(int(cast("int", arguments["iterations"]))):
            label = f"publisher-{index}-{iteration}"
            model = _model(label)
            try:
                if protocol == PRODUCTION:
                    receipt, lease_id, collection = _publish_production(db, model)
                else:
                    receipt, lease_id, collection = _publish_commit_then_lease(
                        db, model, window=window, lease_id=f"legacy:{label}"
                    )
                advanced = receipt.head_advanced
                outcomes["published" if advanced else "head_conflict"] += 1
                _bridge_and_release(db, receipt, lease_id, collection, label)
            except UnknownRunError as refusal:
                if refusal.reason != UNKNOWN_RUN_NOT_PUBLISHED:
                    crashes.append(f"{type(refusal).__name__}: {refusal}")
                else:
                    vanished.append(label)
            except Exception as failure:
                crashes.append(f"{type(failure).__name__}: {failure}")
    return {
        "outcomes": outcomes,
        "vanished": vanished,
        "crashes": crashes,
        "elapsed_s": round(time.perf_counter() - started, 3),
    }


def _until_stopped(arguments: Mapping[str, object]) -> Iterator[int]:
    stop = Path(str(arguments["stop"]))
    count = 0
    while not stop.exists():
        yield count
        count += 1


def _sweeper(arguments: Mapping[str, object]) -> dict[str, object]:
    from codeclone.canonical.store import RunStore, collect_garbage
    from codeclone.models import GC_COLLECT_UNREACHABLE, GC_HOLD_LEASE

    sweeps = collected = held_by_lease = 0
    crashes: list[str] = []
    longest = 0.0
    for _ in _until_stopped(arguments):
        started = time.perf_counter()
        try:
            with RunStore(str(arguments["db"]), create=False) as store:
                report = collect_garbage(store, retain_history=0)
        except Exception as failure:
            crashes.append(f"{type(failure).__name__}: {failure}")
            continue
        longest = max(longest, time.perf_counter() - started)
        sweeps += 1
        collected += report.collected_count(GC_COLLECT_UNREACHABLE)
        held_by_lease += report.held_count(GC_HOLD_LEASE)
    return {
        "sweeps": sweeps,
        "collected": collected,
        "held_by_lease": held_by_lease,
        "crashes": crashes,
        "longest_sweep_s": round(longest, 4),
    }


def _reader(arguments: Mapping[str, object]) -> dict[str, object]:
    from codeclone.canonical.errors import UnknownRunError
    from codeclone.canonical.store import FAMILY_FILE, RunStore

    reads = misses = 0
    crashes: list[str] = []
    longest_open = 0.0
    for _ in _until_stopped(arguments):
        started = time.perf_counter()
        try:
            with RunStore(str(arguments["db"]), create=False) as store:
                longest_open = max(longest_open, time.perf_counter() - started)
                head = store.head(namespace=_NAMESPACE, target=_TARGET)
                if head is None:
                    continue
                try:
                    store.read_family(head.run_id, FAMILY_FILE)
                except UnknownRunError:
                    # A reader holds no lease: the head it read may have moved
                    # and its run been collected before the family read.
                    misses += 1
                    continue
                reads += 1
        except Exception as failure:
            crashes.append(f"{type(failure).__name__}: {failure}")
    return {
        "reads": reads,
        "unleased_misses": misses,
        "crashes": crashes,
        "longest_open_s": round(longest_open, 4),
    }


_ROLES = {
    "sweep": _sweep,
    "publisher": _publisher,
    "sweeper": _sweeper,
    "reader": _reader,
}


def main(argv: list[str]) -> int:
    role, raw = argv[0], argv[1]
    result = _ROLES[role](json.loads(raw))
    result["role"] = role
    result["loaded"] = _loaded()
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0


# -- the parent side ---------------------------------------------------------


def _spawn(role: str, arguments: Mapping[str, object]) -> subprocess.Popen[str]:
    return subprocess.Popen(
        (
            sys.executable,
            "-B",
            "-m",
            "tests._publication_race",
            role,
            json.dumps(arguments),
        ),
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )


def _collect(process: subprocess.Popen[str], timeout: float) -> dict[str, object]:
    stdout, stderr = process.communicate(timeout=timeout)
    if process.returncode != 0:
        raise AssertionError(
            f"race process exited {process.returncode}: {stderr.strip()[-2000:]}"
        )
    return cast("dict[str, object]", json.loads(stdout.strip().splitlines()[-1]))


def sweep_once(db: Path) -> dict[str, object]:
    """One foreign collection in its own process, synchronously."""
    return _collect(_spawn("sweep", {"db": str(db)}), timeout=120)


@dataclass
class RaceResult:
    """Every line the race's processes printed, by role, plus the wall time."""

    publishers: list[dict[str, object]] = field(default_factory=list)
    sweepers: list[dict[str, object]] = field(default_factory=list)
    readers: list[dict[str, object]] = field(default_factory=list)
    wall_s: float = 0.0

    def total(self, role: str, key: str) -> int:
        lines = getattr(self, role)
        return sum(
            len(value) if isinstance(value, list) else int(value)
            for value in (line[key] for line in lines)
        )

    def outcome(self, name: str) -> int:
        return sum(
            int(cast("Mapping[str, int]", line["outcomes"])[name])
            for line in self.publishers
        )

    def crashes(self) -> list[str]:
        return [
            str(crash)
            for lines in (self.publishers, self.sweepers, self.readers)
            for line in lines
            for crash in cast("list[str]", line["crashes"])
        ]

    def loaded(self) -> set[str]:
        return {
            str(line["loaded"])
            for lines in (self.publishers, self.sweepers, self.readers)
            for line in lines
        }


def race(
    db: Path,
    *,
    publishers: int,
    iterations: int,
    readers: int,
    sweepers: int,
    protocol: str = PRODUCTION,
    window: float = 0.0,
    timeout: float = 600.0,
) -> RaceResult:
    """N publishers, M readers and G sweepers on one store, all at once.

    Odd-numbered publishers always lose the head race, so the population
    holds runs that nothing but a lease roots.  Readers and sweepers run
    until every publisher has finished, then stop on a flag file.
    """
    from codeclone.canonical.store import RunStore

    RunStore(db).close()
    stop = db.with_name(db.name + ".stop")
    stop.unlink(missing_ok=True)
    started = time.perf_counter()
    background = [
        ("sweepers", _spawn("sweeper", {"db": str(db), "stop": str(stop)}))
        for _ in range(sweepers)
    ] + [
        ("readers", _spawn("reader", {"db": str(db), "stop": str(stop)}))
        for _ in range(readers)
    ]
    publishing = [
        _spawn(
            "publisher",
            {
                "db": str(db),
                "index": index,
                "iterations": iterations,
                "protocol": protocol,
                "window": window,
                "stale": index % 2 == 1,
            },
        )
        for index in range(publishers)
    ]
    result = RaceResult()
    try:
        result.publishers = [_collect(process, timeout) for process in publishing]
    finally:
        stop.touch()
        for role, process in background:
            getattr(result, role).append(_collect(process, timeout))
    result.wall_s = round(time.perf_counter() - started, 3)
    return result


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
