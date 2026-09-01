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
    RECENCY_GRANULARITY_SECONDS,
    CacheBackend,
    CacheBackendForeign,
    CacheBackendUnreadable,
)
from codeclone.cache.store import Cache
from codeclone.cache.versioning import CacheStatus
from codeclone.core._types import BootstrapResult
from tests._cache_store_fixtures import (
    META_KEY_VERSION,
    break_identity_checksum,
    read_cache_rows,
    read_identity_columns,
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


def _reloaded(tmp_path: Path, cache_path: Path) -> Cache:
    """A fresh Cache over an existing store, loaded and nothing more."""

    warm = Cache(cache_path, root=tmp_path)
    warm.load()
    return warm


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

    break_identity_checksum(cache_path, "alpha.py")

    warm = Cache(cache_path, root=tmp_path)
    warm.load()
    assert warm.load_status is CacheStatus.OK
    assert warm.get_file_entry("alpha.py") is None
    assert warm.get_file_entry("beta.py") is not None
    assert warm.get_file_entry("gamma.py") is not None


def _synchronous_of(connection: object) -> int:
    """SQLite's own encoding: 1 == NORMAL, 2 == FULL."""

    (mode,) = connection.execute("PRAGMA synchronous").fetchone()  # type: ignore[attr-defined]
    return int(mode)


def test_the_cache_commits_at_normal_not_full(tmp_path: Path) -> None:
    """Half of the durability asymmetry: the cache does not overpay.

    Losing a cache costs a cold file, so an fsync per commit buys nothing. Kept
    separate from its sibling below because the two errors are opposites and a
    single test would let one mutation stand in for both.
    """

    assert CACHE_SYNCHRONOUS == "NORMAL"
    with CacheBackend(tmp_path / "cache.sqlite3") as backend:
        assert _synchronous_of(backend._connection) == 1


def test_the_run_store_keeps_full_durability(tmp_path: Path) -> None:
    """The other half: the run store's guarantee is not the cache's to spend.

    Losing a published run loses authority, so it commits at FULL. If a later
    unification of the two stores reached for one setting, this is what refuses.
    """

    from codeclone.canonical.store import RunStore

    with RunStore(tmp_path / "runs.sqlite3") as run_store:
        assert _synchronous_of(run_store._connection) == 2


def _epochs(cache_path: Path) -> dict[str, object]:
    return {
        path: row["last_used_epoch"]
        for path, row in read_identity_columns(cache_path).items()
    }


def test_a_second_run_inside_the_window_rewrites_no_recency_marks(
    tmp_path: Path,
) -> None:
    """Recency is coarse, and the coarseness is the point.

    Measured on this repository: marking every read entry on every run cost
    33 MB of extra write volume per warm run -- a table page and an index page
    per row, to re-record a fact that had not changed. A run inside the window
    must leave the marks exactly as they were.
    """

    _boot, cache_path, _cold = _cold_and_saved(tmp_path)
    before = _epochs(cache_path)
    assert before

    with CacheBackend(cache_path) as backend:
        backend.touch(sorted(before), now_epoch=_max_epoch(before) + 1)

    assert _epochs(cache_path) == before


def test_the_lane_reader_is_one_connection_not_one_per_entry(
    tmp_path: Path,
) -> None:
    """Materialising N entries opens one connection, not N.

    Measured before this held: a warm run over 1133 files opened 1133
    read-only connections and paid 33 MB of filesystem output for it -- the
    N+1 shape the observer's db_cost section exists to name, built by hand.

    The handle identity is the assertion because a count of opens is not
    observable from outside; the same object serving every lane is.
    """

    _boot, cache_path, _cold = _cold_and_saved(tmp_path)

    warm = _reloaded(tmp_path, cache_path)
    assert warm._reader is None, "a load must not open the lane reader"

    handles: list[CacheBackend | None] = []
    for name in sorted(_MODULES):
        assert warm.get_file_entry(str(tmp_path / name)) is not None
        handles.append(warm._reader)

    assert len(handles) == len(_MODULES)
    assert all(handle is handles[0] for handle in handles)
    assert handles[0] is not None

    # And it is released rather than left open for the process lifetime.
    warm.release_loaded_entries()
    assert warm._reader is None


def test_the_recency_window_is_derived_from_the_ttl_it_serves() -> None:
    """Pin the rule the number comes from, not the number.

    ``test_a_run_past_the_window_does_refresh_the_marks`` reads the constant to
    build its own deadline, so it stays green for *any* value of it -- the
    relative-invariant hole. Measured: setting the window to 2^40 seconds left
    that test green while marks could never move again.

    The rule is stated where the constant lives: coarse enough that a TTL
    measured in days cannot tell the difference, and strictly positive, because
    a zero window is the per-run write amplification that made it necessary. So
    the window must be inside a day, and above nothing.
    """

    one_day = 24 * 60 * 60
    assert 0 < RECENCY_GRANULARITY_SECONDS <= one_day


def test_a_run_past_the_window_does_refresh_the_marks(tmp_path: Path) -> None:
    """The other side: coarse is not the same as never.

    Its own test rather than a second assertion above, so a mutation that
    stopped marks moving altogether cannot be reported as covered by the
    mutation that stopped them moving too eagerly.
    """

    _boot, cache_path, _cold = _cold_and_saved(tmp_path)
    before = _epochs(cache_path)
    later = _max_epoch(before) + RECENCY_GRANULARITY_SECONDS + 1

    with CacheBackend(cache_path) as backend:
        backend.touch(sorted(before), now_epoch=later)

    after = _epochs(cache_path)
    assert after != before
    assert set(after.values()) == {later}


def _max_epoch(epochs: dict[str, object]) -> int:
    return max(int(str(value)) for value in epochs.values())


def test_the_cache_schema_is_not_in_the_run_stores_identity_salt() -> None:
    """Adding a cache index must not change what a run means.

    The run store salts its content addresses with ``STORAGE_SCHEMA_REVISION``.
    If the cache's own storage revision were ever folded into that salt, adding
    an index here would change analysis identities without changing a single
    fact -- a defect a parallel wave is removing at the source by splitting
    ``CANONICAL_OBJECT_IDENTITY_VERSION`` out of it.

    This pins the property from the cache's side, which holds independently of
    that wave: no module of the cache package reaches the salt, or the run
    store that owns it. Checked over the package's own module list rather than
    a text search of the tree, so a new cache module cannot slip past it.
    """

    import codeclone.cache

    package = Path(codeclone.cache.__file__).parent
    forbidden = ("STORAGE_SCHEMA_REVISION", "canonical.store", "_DOMAIN_OBJECT")
    offenders = {
        module.name: sorted(
            name for name in forbidden if name in module.read_text("utf-8")
        )
        for module in sorted(package.glob("*.py"))
    }
    assert {name: hits for name, hits in offenders.items() if hits} == {}
    assert offenders, "the probe needs modules to inspect"


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

    warm = _reloaded(tmp_path, cache_path)
    files = warm.data["files"]
    dirty = getattr(files, "dirty", None)
    deleted = getattr(files, "deleted", None)
    assert dirty == set(), "a load must not look like a change"
    assert deleted == set()

    # A save with nothing changed writes no entry rows at all.
    warm._dirty = True

    def generations() -> dict[str, object]:
        return {
            path: row["generation"]
            for path, row in read_identity_columns(cache_path).items()
        }

    before = generations()
    warm.save()
    after = generations()
    assert after == before


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
