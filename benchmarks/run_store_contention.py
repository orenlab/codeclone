#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Run-store contention under load: N publishers, M readers, G collectors.

A benchmark, not a gate (ruling 2026-09-25, protocol B4).  Every role is its
own process on ONE store the harness creates under ``--root``, which must be
new or empty: the benchmark never opens a store it did not create.

* a **publisher** runs the publication protocol, iteration after iteration:
  publish under its in-flight lease, sweep, write the bridge edge on a second
  open, release the lease on a third;
* a **reader** opens the store, resolves the head and reads one family, until
  the publishers are done;
* a **collector** sweeps with the publication's retention, until then too.

Each process measures itself and prints one JSON line; the harness folds
them.  The write lock is measured where it is taken: on the publisher's own
connection, ``BEGIN IMMEDIATE`` returned .. ``COMMIT`` returned is the hold,
the ``BEGIN IMMEDIATE`` call itself is the wait.  A ``StoreUnavailableError``
is a refusal (a lock not obtained within the busy timeout); any other
exception is a crash, and the harness exits 1 when there is one.

Usage::

    uv run python benchmarks/run_store_contention.py --root <new dir> \\
        --publishers 4 --readers 4 --sweepers 1 --iterations 20 \\
        --files 2000 --repeats 3 --json <out.json>
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final, cast

from codeclone.canonical.errors import StoreUnavailableError, UnknownRunError
from codeclone.canonical.identity import FileId
from codeclone.canonical.model import CanonicalModel
from codeclone.canonical.store import (
    FAMILY_FILE,
    PublishReceipt,
    RunStore,
    RunStoreGcJob,
    collect_garbage,
    link_run_report,
    release_run_lease,
)
from codeclone.models import GC_COLLECT_UNREACHABLE

_NAMESPACE: Final = "codeclone.analysis"
_TARGET: Final = "canonical"
_RETAIN_HISTORY: Final = 2
_LEASE_SECONDS: Final = 24 * 60 * 60


def _model(files: int, tag: str) -> CanonicalModel:
    """``2 * files + 1`` objects; two tags over one file set share all but one."""
    paths = frozenset(FileId(f"pkg/m{index}.py") for index in range(files))
    return CanonicalModel(
        files=paths,
        analyzed_files=paths,
        coupled_sets=frozenset({frozenset({tag})}),
    )


class _LockClock:
    """The publisher's connection, timing every write lock it takes."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection
        self.holds: list[float] = []
        self.waits: list[float] = []
        self._since: float | None = None

    def cursor(self) -> _TimedCursor:
        return _TimedCursor(self, self._connection.cursor())

    def execute(self, sql: str, *args: Any) -> Any:
        return self.cursor().execute(sql, *args)

    def timed(self, cursor: Any, sql: str, *args: Any) -> Any:
        verb = sql.strip().upper()
        started = time.perf_counter()
        result = cursor.execute(sql, *args)
        finished = time.perf_counter()
        if verb == "BEGIN IMMEDIATE":
            self.waits.append(finished - started)
            self._since = finished
        elif verb in {"COMMIT", "ROLLBACK"} and self._since is not None:
            self.holds.append(finished - self._since)
            self._since = None
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)


class _TimedCursor:
    def __init__(self, clock: _LockClock, cursor: Any) -> None:
        self._clock = clock
        self._cursor = cursor

    def execute(self, sql: str, *args: Any) -> Any:
        return self._clock.timed(self._cursor, sql, *args)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cursor, name)


class _Tally:
    """One process's measurements: latencies by operation, outcomes by kind."""

    def __init__(self) -> None:
        self.seconds: dict[str, list[float]] = {}
        self.refusals: dict[str, int] = {}
        self.crashes: list[str] = []
        self.counts: dict[str, int] = {}

    def time(self, operation: str, started: float) -> None:
        self.seconds.setdefault(operation, []).append(time.perf_counter() - started)

    def count(self, name: str, amount: int = 1) -> None:
        self.counts[name] = self.counts.get(name, 0) + amount

    def attempt(self, operation: str, action: Callable[[], object]) -> object:
        started = time.perf_counter()
        try:
            result = action()
        except StoreUnavailableError:
            self.refusals[operation] = self.refusals.get(operation, 0) + 1
            return None
        except Exception as failure:
            self.crashes.append(f"{operation}: {type(failure).__name__}: {failure}")
            return None
        self.time(operation, started)
        return result

    def payload(self) -> dict[str, object]:
        return {
            "seconds": self.seconds,
            "refusals": self.refusals,
            "crashes": self.crashes,
            "counts": self.counts,
        }


def _publish_once(
    store_path: Path, model: CanonicalModel, lease_id: str
) -> tuple[PublishReceipt, _LockClock]:
    with RunStore(store_path, create=True) as store:
        clock = _LockClock(store._connection)
        # Measured on the connection that takes the lock, and only here.
        setattr(store, "_connection", clock)  # noqa: B010
        head = store.head(namespace=_NAMESPACE, target=_TARGET)
        receipt = store.write_full_run(
            model,
            namespace=_NAMESPACE,
            target=_TARGET,
            expected_generation=0 if head is None else head.generation,
            in_flight_lease=(lease_id, _LEASE_SECONDS),
        )
        RunStoreGcJob(store=store, retain_history=_RETAIN_HISTORY).collect()
    return receipt, clock


def _publisher(arguments: Mapping[str, Any], tally: _Tally) -> None:
    store_path = Path(str(arguments["store"]))
    for iteration in range(int(arguments["iterations"])):
        label = f"publisher-{arguments['index']}-{iteration}"
        lease_id = f"bench:{label}"
        model = _model(int(arguments["files"]), label)

        def publish(model: CanonicalModel = model, lease_id: str = lease_id) -> object:
            return _publish_once(store_path, model, lease_id)

        published = tally.attempt("publish", publish)
        if published is None:
            continue
        receipt, clock = cast("tuple[PublishReceipt, _LockClock]", published)
        tally.seconds.setdefault("publish_lock_hold", []).extend(clock.holds)
        tally.seconds.setdefault("publish_lock_wait", []).extend(clock.waits)
        tally.count("head_advanced" if receipt.head_advanced else "head_conflict")

        def link(receipt: PublishReceipt = receipt, label: str = label) -> None:
            with RunStore(store_path, create=False) as store:
                link_run_report(
                    store,
                    run_id=receipt.run_id,
                    report_run_identity=label.encode().hex().ljust(64, "0")[:64],
                    expected_scope_digest=receipt.analysis_scope_digest,
                )

        def release(lease_id: str = lease_id) -> None:
            with RunStore(store_path, create=False) as store:
                release_run_lease(store, lease_id)

        tally.attempt("link", link)
        tally.attempt("release", release)


def _until_stopped(stop: Path) -> bool:
    return not stop.exists()


def _reader(arguments: Mapping[str, Any], tally: _Tally) -> None:
    store_path = Path(str(arguments["store"]))
    stop = Path(str(arguments["stop"]))

    def read() -> None:
        started = time.perf_counter()
        with RunStore(store_path, create=False) as store:
            tally.time("reader_open", started)
            head = store.head(namespace=_NAMESPACE, target=_TARGET)
            if head is None:
                return
            try:
                store.read_family(head.run_id, FAMILY_FILE)
            except UnknownRunError:
                # A reader holds no lease: its head may have moved and been
                # collected before the family read.
                tally.count("unleased_miss")

    while _until_stopped(stop):
        tally.attempt("read", read)


def _sweeper(arguments: Mapping[str, Any], tally: _Tally) -> None:
    store_path = Path(str(arguments["store"]))
    stop = Path(str(arguments["stop"]))

    def sweep() -> None:
        with RunStore(store_path, create=False) as store:
            report = collect_garbage(store, retain_history=_RETAIN_HISTORY)
        tally.count("collected_runs", report.collected_count(GC_COLLECT_UNREACHABLE))

    while _until_stopped(stop):
        tally.attempt("sweep", sweep)


_ROLES: Final[dict[str, Callable[[Mapping[str, Any], _Tally], None]]] = {
    "publisher": _publisher,
    "reader": _reader,
    "sweeper": _sweeper,
}


def _child(role: str, raw: str) -> int:
    import codeclone.canonical.store as store_module

    tally = _Tally()
    _ROLES[role](json.loads(raw), tally)
    print(
        json.dumps(
            {"role": role, "loaded": store_module.__file__, **tally.payload()},
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


def _spawn(role: str, arguments: Mapping[str, Any]) -> subprocess.Popen[str]:
    return subprocess.Popen(
        (sys.executable, "-B", __file__, "--role", role, json.dumps(arguments)),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )


def _collect(process: subprocess.Popen[str]) -> dict[str, Any]:
    stdout, stderr = process.communicate(timeout=3600)
    if process.returncode != 0:
        return {"crashes": [f"exit {process.returncode}: {stderr.strip()[-500:]}"]}
    parsed: dict[str, Any] = json.loads(stdout.strip().splitlines()[-1])
    return parsed


def _distribution(values: Sequence[float]) -> dict[str, float | int]:
    if not values:
        return {"n": 0}
    ordered = sorted(values)
    return {
        "n": len(ordered),
        "p50_s": round(statistics.median(ordered), 4),
        "p95_s": round(ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))], 4),
        "max_s": round(ordered[-1], 4),
    }


def _fold(lines: Sequence[Mapping[str, Any]]) -> dict[str, object]:
    seconds: dict[str, list[float]] = {}
    refusals: dict[str, int] = {}
    counts: dict[str, int] = {}
    crashes: list[str] = []
    for line in lines:
        for key, values in line.get("seconds", {}).items():
            seconds.setdefault(key, []).extend(values)
        for key, value in line.get("refusals", {}).items():
            refusals[key] = refusals.get(key, 0) + int(value)
        for key, value in line.get("counts", {}).items():
            counts[key] = counts.get(key, 0) + int(value)
        crashes.extend(line.get("crashes", []))
    attempts = {
        key: len(values) + refusals.get(key, 0) for key, values in seconds.items()
    }
    return {
        "latency": {
            key: _distribution(values) for key, values in sorted(seconds.items())
        },
        "refusals": refusals,
        "refusal_share": {
            key: round(value / attempts[key], 4) if attempts.get(key) else 1.0
            for key, value in refusals.items()
        },
        "counts": counts,
        "crashes": crashes,
        "loaded": sorted({str(line.get("loaded")) for line in lines}),
    }


def _repeat(
    root: Path, arguments: argparse.Namespace, repeat: int
) -> dict[str, object]:
    store_path = root / f"repeat-{repeat}" / "runs.sqlite3"
    store_path.parent.mkdir(parents=True)
    RunStore(store_path, create=True).close()
    stop = store_path.with_name("stop")
    shared = {"store": str(store_path), "stop": str(stop)}
    background = [_spawn("reader", shared) for _ in range(arguments.readers)] + [
        _spawn("sweeper", shared) for _ in range(arguments.sweepers)
    ]
    started = time.perf_counter()
    publishers = [
        _spawn(
            "publisher",
            {
                **shared,
                "index": index,
                "iterations": arguments.iterations,
                "files": arguments.files,
            },
        )
        for index in range(arguments.publishers)
    ]
    publisher_lines = [_collect(process) for process in publishers]
    wall = time.perf_counter() - started
    stop.touch()
    background_lines = [_collect(process) for process in background]
    return {
        "repeat": repeat,
        "wall_s": round(wall, 3),
        "all": _fold([*publisher_lines, *background_lines]),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--role", choices=sorted(_ROLES))
    parser.add_argument("arguments", nargs="?")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--publishers", type=int, default=4)
    parser.add_argument("--readers", type=int, default=4)
    parser.add_argument("--sweepers", type=int, default=1)
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--files", type=int, default=2000)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--json", type=Path)
    arguments = parser.parse_args(argv)
    if arguments.role:
        return _child(arguments.role, str(arguments.arguments))
    root: Path | None = arguments.root
    if root is None or (root.exists() and any(root.iterdir())):
        parser.error("--root must name a new or empty directory")
    root.mkdir(parents=True, exist_ok=True)
    repeats = [_repeat(root, arguments, repeat) for repeat in range(arguments.repeats)]
    result = {
        "load": {
            key: getattr(arguments, key)
            for key in ("publishers", "readers", "sweepers", "iterations", "files")
        },
        "repeats": repeats,
    }
    text = json.dumps(result, indent=1, sort_keys=True)
    if arguments.json is not None:
        arguments.json.write_text(text, "utf-8")
    print(text)
    crashed = any(
        cast("dict[str, list[str]]", repeat["all"])["crashes"] for repeat in repeats
    )
    return 1 if crashed else 0


if __name__ == "__main__":
    raise SystemExit(main())
