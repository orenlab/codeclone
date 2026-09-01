# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The boundary between disposable cache state and canonical run authority.

These are the acceptance pins for moving the analysis cache onto the SQLite
backend.  They are deliberately about the *semantics* of the move rather than
its speed: a faster cache that changes an answer is not a cache.

Three claims, each with its own test:

* a warm run answers exactly what a cold run answers, byte for byte;
* deleting the whole store changes no answer, only the time taken;
* the cache never weakens the run store's durability, and never shares its
  ``synchronous`` setting by accident.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from codeclone.cache.backend import (
    CACHE_SYNCHRONOUS,
    CacheBackend,
    CacheBackendForeign,
    CacheBackendUnreadable,
)
from codeclone.cache.store import Cache
from codeclone.cache.versioning import CacheStatus
from codeclone.core._types import BootstrapResult
from tests._cache_store_fixtures import (
    META_KEY_VERSION,
    open_store,
    read_cache_rows,
    write_cache_meta,
)
from tests._pipeline_fixtures import (
    PipelineRun,
    analysis_boot,
    run_pipeline_once,
)

_MODULES = {
    "alpha.py": (
        "def widen(left, right):\n"
        "    total = left + right\n"
        "    for step in range(total):\n"
        "        total += step\n"
        "    return total\n"
    ),
    "beta.py": (
        "from alpha import widen\n"
        "\n"
        "def narrow(values):\n"
        "    seen = []\n"
        "    for value in values:\n"
        "        seen.append(widen(value, 1))\n"
        "    return seen\n"
    ),
    "gamma.py": (
        "import beta\n"
        "\n"
        "class Holder:\n"
        "    def __init__(self, items):\n"
        "        self.items = list(items)\n"
        "\n"
        "    def widened(self):\n"
        "        return beta.narrow(self.items)\n"
    ),
}


def _corpus(tmp_path: Path) -> tuple[BootstrapResult, Path]:
    for name, source in _MODULES.items():
        (tmp_path / name).write_text(source, "utf-8")
    boot = analysis_boot(tmp_path, min_loc=1, min_stmt=1, skip_metrics=False)
    return boot, tmp_path / "cache.sqlite3"


def _cold_and_saved(tmp_path: Path) -> tuple[BootstrapResult, Path, PipelineRun]:
    """Write the corpus, run it cold, and leave a saved store behind."""

    boot, cache_path = _corpus(tmp_path)
    cache, run = run_pipeline_once(boot, cache_path, root=tmp_path, warm=False)
    cache.save()
    return boot, cache_path, run


def _answer(result: object) -> str:
    """One comparable rendering of an analysis result.

    ``repr`` of the frozen result dataclasses is exact here: every field is a
    frozen dataclass, tuple, or primitive, so equal reprs mean equal answers,
    and a diff points at the field that moved.
    """

    return repr(result)


def test_a_warm_run_answers_exactly_what_a_cold_run_answers(tmp_path: Path) -> None:
    """Equivalence: the cache accelerates the answer, it does not shape it.

    This is the property the whole migration has to preserve. It is checked on
    a non-empty corpus with imports, a class, and a loop, because a cache that
    only round-trips trivial files proves nothing about the wire encoding of
    the facts that actually vary.
    """

    boot, cache_path, cold = _cold_and_saved(tmp_path)

    _warm_cache, warm = run_pipeline_once(
        boot,
        cache_path,
        root=tmp_path,
        warm=True,
        expect_cache_hits=len(_MODULES),
    )

    assert _answer(warm.result) == _answer(cold.result)
    assert warm.processing.files_analyzed == 0
    assert cold.processing.files_analyzed == len(_MODULES)


def test_deleting_the_whole_store_changes_no_answer(tmp_path: Path) -> None:
    """The cache is disposable, and that is a testable claim, not a slogan.

    Deleting the store must cost time and nothing else. If this ever fails,
    some fact reached a report through the cache that the analysis could not
    re-derive -- which would mean the cache had become authority.
    """

    boot, cache_path, first = _cold_and_saved(tmp_path)
    assert cache_path.exists()

    cache_path.unlink()
    for sidecar in (".sqlite3-wal", ".sqlite3-shm"):
        companion = cache_path.with_name(cache_path.stem + sidecar)
        if companion.exists():
            companion.unlink()
    assert not cache_path.exists()

    _second_cache, second = run_pipeline_once(
        boot,
        cache_path,
        root=tmp_path,
        warm=False,
    )

    assert _answer(second.result) == _answer(first.result)
    # Proof the deletion was real rather than a no-op on an already-cold run.
    assert second.processing.files_analyzed == len(_MODULES)


def test_a_corrupt_row_costs_one_entry_and_not_the_store(tmp_path: Path) -> None:
    """Per-row integrity: damage is bounded by the row that carries it.

    Under the JSON monolith one bad byte anywhere condemned every entry,
    because one checksum covered the whole document. Row checksums make a
    damaged entry a single cache miss, which is the difference between a slow
    run and a cold one.
    """

    _boot, cache_path, _cold = _cold_and_saved(tmp_path)
    assert len(read_cache_rows(cache_path)) == len(_MODULES)

    with open_store(cache_path) as conn:
        conn.execute(
            "UPDATE cache_files SET checksum = 'wrong' WHERE wire_path = ?",
            ("alpha.py",),
        )

    warm = Cache(cache_path, root=tmp_path)
    warm.load()
    assert warm.load_status is CacheStatus.OK
    assert warm.get_file_entry("alpha.py") is None
    assert warm.get_file_entry("beta.py") is not None
    assert warm.get_file_entry("gamma.py") is not None


def test_the_cache_does_not_borrow_the_run_stores_durability(tmp_path: Path) -> None:
    """The two stores share infrastructure, not durability semantics.

    The run store commits at ``synchronous=FULL`` because losing a published
    run loses authority. The cache does not, because losing it costs only a
    cold file. This pins the asymmetry in both directions: if a later
    unification set the cache to FULL it would pay for nothing, and if it set
    the run store to NORMAL it would weaken a durability guarantee that is not
    the cache's to spend.
    """

    from codeclone.canonical.store import RunStore

    assert CACHE_SYNCHRONOUS == "NORMAL"

    cache_path = tmp_path / "cache.sqlite3"
    with CacheBackend(cache_path) as backend:
        (cache_mode,) = backend._connection.execute("PRAGMA synchronous").fetchone()

    run_store_path = tmp_path / "runs.sqlite3"
    with RunStore(run_store_path) as run_store:
        (run_mode,) = run_store._connection.execute("PRAGMA synchronous").fetchone()

    # 1 == NORMAL, 2 == FULL in SQLite's own encoding.
    assert cache_mode == 1
    assert run_mode == 2


def test_a_foreign_database_is_refused_before_it_is_written_to(
    tmp_path: Path,
) -> None:
    """Reading must never create. Pinned at the backend, not only at the store.

    ``--cache-path`` accepts any path. Opening read-write to discover the file
    is not ours would add our tables to somebody else's database, which is a
    write performed by a read.
    """

    foreign = tmp_path / "foreign.sqlite3"
    with sqlite3.connect(foreign) as conn:
        conn.execute("CREATE TABLE theirs(id INTEGER PRIMARY KEY)")
    before = foreign.read_bytes()

    with pytest.raises(CacheBackendForeign):
        CacheBackend(foreign, read_only=True)

    assert foreign.read_bytes() == before


def test_an_unopenable_store_is_unreadable_not_foreign(tmp_path: Path) -> None:
    """The two refusals stay distinguishable, each reachable by some input.

    A guard no input can trip is theater, so both branches are exercised: this
    one by a directory where the database belongs, its sibling above by a real
    database with the wrong schema.
    """

    blocked = tmp_path / "cache.sqlite3"
    blocked.mkdir()

    with pytest.raises(CacheBackendUnreadable):
        CacheBackend(blocked, read_only=True)


def test_a_save_writes_only_the_rows_that_moved(tmp_path: Path) -> None:
    """Write amplification is bounded by the change, not by the repository.

    The monolith re-serialised every entry on every save, so editing one file
    rewrote the whole cache. This is the pin that says it no longer does --
    and it is the reason ``TrackedFiles`` exists.
    """

    _boot, cache_path, _cold = _cold_and_saved(tmp_path)

    warm = Cache(cache_path, root=tmp_path)
    warm.load()
    files = warm.data["files"]
    dirty = getattr(files, "dirty", None)
    deleted = getattr(files, "deleted", None)
    assert dirty == set(), "a load must not look like a change"
    assert deleted == set()

    # A save with nothing changed writes no entry rows at all.
    warm._dirty = True
    with CacheBackend(cache_path) as backend:
        generations_before = sorted(
            row[0]
            for row in backend._connection.execute(
                "SELECT generation FROM cache_files"
            ).fetchall()
        )
    warm.save()
    with CacheBackend(cache_path) as backend:
        generations_after = sorted(
            row[0]
            for row in backend._connection.execute(
                "SELECT generation FROM cache_files"
            ).fetchall()
        )
    assert generations_after == generations_before


def test_a_refused_generation_is_replaced_not_partially_inherited(
    tmp_path: Path,
) -> None:
    """Delta writing has one sharp edge, and this is it.

    When a load is refused -- a foreign version mark, a failed envelope
    checksum, another interpreter -- the rows on disk belong to a generation
    this run rejected. Writing only what changed would leave them there for the
    next load to serve, quietly readmitting entries this run refused. The
    monolith replaced the whole document and never had to say so; a row store
    has to say it out loud.

    Note what this is NOT: a single row that fails its own checksum is one
    cache miss, not a refusal, and is pinned separately by
    ``test_a_corrupt_row_costs_one_entry_and_not_the_store``.
    """

    _boot, cache_path, _cold = _cold_and_saved(tmp_path)
    assert set(read_cache_rows(cache_path)) == set(_MODULES)

    write_cache_meta(cache_path, **{META_KEY_VERSION: "0.1"})

    refused = Cache(cache_path, root=tmp_path)
    refused.load()
    assert refused.load_status is CacheStatus.VERSION_MISMATCH
    assert refused.data["files"] == {}

    refused.save()
    # Nothing from the refused generation survived into the new one.
    assert read_cache_rows(cache_path) == {}
