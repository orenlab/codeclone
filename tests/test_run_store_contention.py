# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Run-store contention: who takes the write lock, for how long, and why.

Ruling 2026-09-25 (protocol B), measured on dd7663ed before this module:

* every open took ``BEGIN IMMEDIATE`` for its witness, the reader's
  included, so a reader waited out the five-second busy timeout behind any
  writer and then failed (storage audit RS-02; 5.43 s and
  ``StoreUnavailableError`` on the self-repository store);
* a publication looked every object up by one ``SELECT`` inside its write
  lock, one statement per object (RS-13; 324 745 on the self-repository).

A reader now decides its open under a deferred read snapshot -- under WAL it
never waits for a writer -- and only a creator takes the write lock.  A
publication looks its objects up before the lock, and inside it trusts that
lookup only when no other connection committed in between.

Every store lives under ``tmp_path``; the lock holders are separate
processes handed that path and nothing else.
"""

from __future__ import annotations

import hashlib
import sqlite3
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

import codeclone.utils.sqlite_store as sqlite_store
from codeclone.canonical import store as store_module
from codeclone.canonical.errors import StoreIntegrityError, StoreUnavailableError
from codeclone.canonical.identity import FileId
from codeclone.canonical.model import CanonicalModel
from codeclone.canonical.store import (
    FAMILY_FILE,
    PublishReceipt,
    RunStore,
    acquire_run_lease,
)
from codeclone.core.canonical_snapshot import persist_run_snapshot_link
from codeclone.models import (
    RUN_SNAPSHOT_LINK_LINKED,
    RUN_SNAPSHOT_PUBLICATION_PUBLISHED,
    RunSnapshotLink,
)
from tests._live_state import discover_live_state_boundary

_REPO_ROOT = Path(__file__).resolve().parents[1]
_NS = "contention"
_TARGET = "worktree"


def _model(files: int, tag: str) -> CanonicalModel:
    """A run of ``2 * files + 1`` objects: every file twice (found and
    analysed) and one coupled set named by ``tag``, so two tags over the
    same files share all but one object."""
    paths = frozenset(FileId(f"pkg/m{index}.py") for index in range(files))
    return CanonicalModel(
        files=paths,
        analyzed_files=paths,
        coupled_sets=frozenset({frozenset({tag})}),
    )


def _publish(store: RunStore, model: CanonicalModel) -> PublishReceipt:
    head = store.head(namespace=_NS, target=_TARGET)
    return store.write_full_run(
        model,
        namespace=_NS,
        target=_TARGET,
        expected_generation=0 if head is None else head.generation,
    )


def _outside_live_state(path: Path) -> Path:
    boundary = discover_live_state_boundary()
    assert boundary.state_dir_of(path) is None, path
    assert boundary.live_root_of(path) is None, path
    return path


_HOLDER = """
import sqlite3, sys
connection = sqlite3.connect(sys.argv[1], isolation_level=None, timeout=0)
connection.execute("BEGIN IMMEDIATE")
print("HELD", flush=True)
sys.stdin.read()
connection.execute("ROLLBACK")
"""


@contextmanager
def _write_lock_held_by_another_process(db: Path) -> Iterator[None]:
    """Another process holds ``BEGIN IMMEDIATE`` on ``db`` for the block."""
    holder = subprocess.Popen(
        (sys.executable, "-c", _HOLDER, str(_outside_live_state(db))),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert holder.stdout is not None and holder.stdin is not None
    try:
        assert holder.stdout.readline().strip() == "HELD"
        yield
    finally:
        holder.stdin.close()
        holder.wait(timeout=30)
    assert holder.returncode == 0


def _file_state(db: Path) -> tuple[str, int]:
    """The main file's bytes and the WAL's length: what a write would move."""
    wal = Path(f"{db}-wal")
    return (
        hashlib.sha256(db.read_bytes()).hexdigest(),
        wal.stat().st_size if wal.exists() else -1,
    )


# -- B1: a reader never waits for a writer ------------------------------------


@pytest.mark.parametrize("create", [False, True], ids=["reader", "existing-store"])
def test_an_open_of_an_existing_store_proceeds_while_another_process_writes(
    tmp_path: Path, create: bool
) -> None:
    """Opening, resolving the head and reading a family of an existing store
    take no write lock: they proceed while another process holds one, and
    write nothing.  The positive control is on the same handle and the same
    held lock: a mutation through it is refused at once."""
    db = tmp_path / "runs.sqlite3"
    with RunStore(db) as store:
        receipt = _publish(store, _model(20, "a"))
    with _write_lock_held_by_another_process(db):
        before = _file_state(db)
        started = time.perf_counter()
        with RunStore(db, create=create) as reader:
            head = reader.head(namespace=_NS, target=_TARGET)
            rows = reader.read_family(receipt.run_id, FAMILY_FILE)
            elapsed = time.perf_counter() - started
            reader._connection.execute("PRAGMA busy_timeout = 0")
            with pytest.raises(sqlite3.OperationalError, match="database is locked"):
                acquire_run_lease(
                    reader,
                    receipt.run_id,
                    kind="session",
                    lease_id="control",
                    ttl_seconds=60,
                )
        after = _file_state(db)
    assert head is not None and head.run_id == receipt.run_id
    assert len(rows) == 20
    assert elapsed < 1.0, f"the open waited {elapsed:.2f}s for the writer"
    assert after == before, "an open of an existing store wrote to it"


_CREATOR = """
import sqlite3, sys, time
from codeclone.canonical.store import _create_schema, _write_witness
connection = sqlite3.connect(sys.argv[1], isolation_level=None, timeout=0)
cursor = connection.cursor()
cursor.execute("BEGIN IMMEDIATE")
_create_schema(cursor)
_write_witness(cursor)
print("HELD", flush=True)
time.sleep(0.5)
cursor.execute("COMMIT")
"""


def test_a_creator_waits_for_a_concurrent_creator_and_opens_its_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other direction: creating a store still takes the write lock.

    Two creators race on one empty WAL file.  The other process has written
    the schema and the witness and holds its transaction open when this
    process decides its open; the decision waits for that commit and opens
    the store the other one created.  Decided under a read snapshot
    instead, it would see the empty file, try to create the schema itself
    from a snapshot that is stale by then, and be refused.
    """
    db = _outside_live_state(tmp_path / "runs.sqlite3")
    with sqlite3.connect(db) as seed:
        seed.execute("PRAGMA journal_mode=WAL").fetchone()
    real_initialize = RunStore._initialize
    creators: list[subprocess.Popen[str]] = []

    def race_then_initialize(store: RunStore, *, create: bool, fresh: bool) -> None:
        creator = subprocess.Popen(
            (sys.executable, "-c", _CREATOR, str(db)),
            cwd=_REPO_ROOT,
            stdout=subprocess.PIPE,
            text=True,
        )
        creators.append(creator)
        assert creator.stdout is not None
        assert creator.stdout.readline().strip() == "HELD"
        real_initialize(store, create=create, fresh=fresh)

    monkeypatch.setattr(RunStore, "_initialize", race_then_initialize)
    started = time.perf_counter()
    with RunStore(db) as store:
        waited = time.perf_counter() - started
        tables = {
            str(row[0])
            for row in store._connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert [creator.wait(timeout=30) for creator in creators] == [0]
    assert {"runs", "objects", "witness", "store_meta"} <= tables
    assert waited >= 0.3, f"the creator did not wait for the other ({waited:.2f}s)"


# -- B2: a publication prepares its lookups before the write lock -----------


class _LockCounter:
    """The store's connection, counting ``execute`` calls inside each write
    lock (``BEGIN IMMEDIATE`` .. ``COMMIT``/``ROLLBACK``) and optionally
    acting just before a lock is requested."""

    def __init__(
        self, connection: sqlite3.Connection, before_lock: Callable[[], None]
    ) -> None:
        self._connection = connection
        self._before_lock = before_lock
        self.inside: list[int] = []
        self._open: int | None = None

    def execute_counted(self, cursor: sqlite3.Cursor, sql: str, *args: Any) -> Any:
        verb = sql.strip().upper()
        if verb == "BEGIN IMMEDIATE":
            self._before_lock()
        result = cursor.execute(sql, *args)
        if verb == "BEGIN IMMEDIATE":
            self._open = 0
        elif verb in {"COMMIT", "ROLLBACK"} and self._open is not None:
            self.inside.append(self._open)
            self._open = None
        elif self._open is not None:
            self._open += 1
        return result

    def cursor(self) -> _CountedCursor:
        return _CountedCursor(self, self._connection.cursor())

    def __getattr__(self, name: str) -> object:
        return getattr(self._connection, name)


class _CountedCursor:
    def __init__(self, counter: _LockCounter, cursor: sqlite3.Cursor) -> None:
        self._counter = counter
        self._cursor = cursor

    def execute(self, sql: str, *args: Any) -> Any:
        return self._counter.execute_counted(self._cursor, sql, *args)

    def __getattr__(self, name: str) -> object:
        return getattr(self._cursor, name)


def _statements_inside_the_publish_lock(tmp_path: Path, files: int) -> int:
    with RunStore(tmp_path / f"runs-{files}.sqlite3") as store:
        _publish(store, _model(files, "a"))
        counter = _LockCounter(store._connection, lambda: None)
        store._connection = counter  # type: ignore[assignment]
        receipt = _publish(store, _model(files, "b"))
    assert receipt.new_objects == 1
    assert len(counter.inside) == 1
    return counter.inside[0]


def test_the_publish_lock_holds_no_per_object_lookup(tmp_path: Path) -> None:
    """Republishing over objects the store already holds: the statements
    inside the write lock do not grow with the number of objects, because
    the objects were looked up before the lock was taken.  Measured on
    dd7663ed: one ``SELECT`` per object inside the lock (1201 and 3601
    statements for these two runs)."""
    small = _statements_inside_the_publish_lock(tmp_path, 600)
    large = _statements_inside_the_publish_lock(tmp_path, 1800)
    assert small == large, (small, large)


def _collect_run_behind_the_publisher(db: Path, run_id: str) -> None:
    """Another connection removes ``run_id`` and every object nothing else
    references -- what a collector does to a run nothing roots."""
    with sqlite3.connect(db, isolation_level=None) as foreign:
        foreign.execute("PRAGMA foreign_keys = ON")
        foreign.execute("BEGIN IMMEDIATE")
        (run_pk,) = foreign.execute(
            "SELECT run_pk FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        for table in ("heads", "head_history", "run_members", "runs"):
            foreign.execute(f"DELETE FROM {table} WHERE run_pk = ?", (run_pk,))
        foreign.execute(
            "DELETE FROM objects WHERE object_pk NOT IN "
            "(SELECT object_pk FROM run_members)"
        )
        foreign.execute("COMMIT")


def test_a_lookup_invalidated_before_the_lock_is_redone_inside_it(
    tmp_path: Path,
) -> None:
    """The prepared lookup is trusted only when nothing committed since.

    Between the lookup and the lock, another connection collects the run
    whose objects the lookup found.  The publication must notice, look the
    objects up again under the lock and insert them, and the published run
    must read back as the model it was given."""
    db = _outside_live_state(tmp_path / "runs.sqlite3")
    with RunStore(db) as store:
        first = _publish(store, _model(600, "a"))
        fired: list[bool] = []

        def collect_first() -> None:
            if not fired:
                fired.append(True)
                _collect_run_behind_the_publisher(db, first.run_id)

        store._connection = _LockCounter(store._connection, collect_first)  # type: ignore[assignment]
        second = _publish(store, _model(600, "b"))
        assert fired == [True]
        assert second.new_objects == second.object_count
        assert store.read_run(second.run_id) == _model(600, "b").normalize()


# -- B3: the link write waits a bounded time, then refuses typed -------------


def test_the_link_write_waits_a_bounded_time_then_refuses_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The second write of a publication -- its bridge edge -- meets a held
    write lock: it waits the store's busy timeout and then refuses with the
    store's own ``StoreUnavailableError``, never a raw ``sqlite3`` error and
    never an unbounded wait."""
    monkeypatch.setattr(sqlite_store, "_SQLITE_BUSY_TIMEOUT_MS", 300)
    db = tmp_path / "runs.sqlite3"
    with RunStore(db) as store:
        receipt = _publish(store, _model(5, "a"))
    link = RunSnapshotLink(
        state=RUN_SNAPSHOT_LINK_LINKED,
        outcome=RUN_SNAPSHOT_PUBLICATION_PUBLISHED,
        store_run_id=receipt.run_id,
        analysis_scope_digest=receipt.analysis_scope_digest,
        report_run_identity="r" * 64,
    )
    with _write_lock_held_by_another_process(db):
        started = time.perf_counter()
        with pytest.raises(StoreUnavailableError, match="database is locked"):
            persist_run_snapshot_link(store_path=db, link=link)
        waited = time.perf_counter() - started
    assert 0.3 <= waited < 3.0, waited


def test_the_lookup_chunk_fits_the_bound_parameters_sqlite_admits(
    tmp_path: Path,
) -> None:
    """The chunk constant is bounded by SQLite's own limit, not chosen: one
    lookup statement binds the namespace and a whole chunk, and a chunk past
    the limit fails the publication of every run larger than it.  Proven on
    the store's own connection by binding exactly that many parameters."""
    bound = store_module._OBJECT_LOOKUP_CHUNK + 1
    with RunStore(tmp_path / "runs.sqlite3") as store:
        row = store._connection.execute(
            f"SELECT COUNT(*) WHERE 0 NOT IN ({','.join('?' * bound)})",
            tuple(range(1, bound + 1)),
        ).fetchone()
    assert store_module._OBJECT_LOOKUP_CHUNK >= 1
    assert row == (1,)


def test_the_in_lock_verification_refuses_a_member_whose_family_moved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The verification under the lock proves the family as well as the
    bytes: the content address is hashed over both, so a staged member whose
    family changed after staging no longer has that address."""
    with RunStore(tmp_path / "runs.sqlite3") as store:
        first = _publish(store, _model(5, "a"))

        def move_one_family() -> None:
            store._connection.execute(
                "INSERT OR IGNORE INTO families (family) VALUES ('coupled_set')"
            )
            store._connection.execute(
                "UPDATE objects SET family_pk = "
                "(SELECT family_pk FROM families WHERE family = 'coupled_set') "
                "WHERE object_pk = (SELECT MIN(object_pk) FROM objects WHERE "
                "family_pk = (SELECT family_pk FROM families WHERE family = 'file'))"
            )

        monkeypatch.setattr(store, "_before_publish", move_one_family)
        with pytest.raises(StoreIntegrityError, match="publish refused"):
            _publish(store, _model(5, "b"))
        monkeypatch.undo()
        head = store.head(namespace=_NS, target=_TARGET)
    assert head is not None and head.run_id == first.run_id


def test_a_lookup_that_fails_before_the_lock_leaves_the_handle_usable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A read that dies inside the prepared lookup ends its snapshot: the
    publication fails with the fault, and the same handle publishes next,
    which it could not from inside a snapshot left open."""
    real = store_module._lookup_objects
    with RunStore(tmp_path / "runs.sqlite3") as store:

        def fail(*_args: object) -> dict[str, int]:
            raise sqlite3.OperationalError("injected read fault")

        monkeypatch.setattr(store_module, "_lookup_objects", fail)
        with pytest.raises(sqlite3.OperationalError, match="injected read fault"):
            _publish(store, _model(5, "a"))
        monkeypatch.setattr(store_module, "_lookup_objects", real)
        assert not store._connection.in_transaction
        assert _publish(store, _model(5, "a")).head_advanced
