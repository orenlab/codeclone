# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The cache's collector, and the fact that it is not a private one.

Two things are under test here. First, that the cache collects what it should
collect and holds what it must hold -- corrupt rows, orphans, expiry, the size
bound, and the rows of the current generation it may never take. Second, and
just as load-bearing, that it does all of this *through the shared protocol*:
one dispatcher, one report shape, one closed vocabulary. A cache that swept
itself on the side would be a second collector nobody could see from the first.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from codeclone.api.gc import run_gc
from codeclone.cache.gc import GC_JOB_NAME, CacheStoreGcJob, collect_cache_garbage
from codeclone.cache.store import Cache
from codeclone.models import (
    GC_COLLECT_CORRUPT,
    GC_COLLECT_EXPIRED,
    GC_COLLECT_ORPHANED,
    GC_COLLECT_REASONS,
    GC_HOLD_REASONS,
    GC_HOLD_RETAINED,
)
from tests._cache_store_fixtures import (
    break_identity_checksum,
    read_identity_columns,
    set_identity_column,
)
from tests._pipeline_fixtures import analysis_boot, run_pipeline_once

_MODULES = {
    "alpha.py": "def alpha(left, right):\n    total = left + right\n    return total\n",
    "beta.py": "def beta(values):\n    return [v + 1 for v in values]\n",
    "gamma.py": "def gamma(text):\n    return text.strip().lower()\n",
}


def _cold_store(tmp_path: Path) -> Path:
    for name, source in _MODULES.items():
        (tmp_path / name).write_text(source, "utf-8")
    boot = analysis_boot(tmp_path, min_loc=1, min_stmt=1, skip_metrics=True)
    cache_path = tmp_path / "cache.sqlite3"
    cache, _run = run_pipeline_once(boot, cache_path, root=tmp_path, warm=False)
    cache.save()
    return cache_path


def _sweep(cache_path: Path, **policy: object) -> object:
    return collect_cache_garbage(
        path=cache_path,
        version=Cache._CACHE_VERSION,
        generation=1 << 62,
        now_epoch=int(time.time()),
        **policy,  # type: ignore[arg-type]
    )


def test_the_report_balances_and_speaks_the_closed_vocabulary(
    tmp_path: Path,
) -> None:
    """The protocol's honesty envelope, checked on this job's own answer.

    ``candidates == held + collected`` is what stops a job from quietly losing
    an entry it cannot attribute, and the vocabularies are the protocol's, not
    the cache's.
    """

    cache_path = _cold_store(tmp_path)
    report = _sweep(cache_path)

    held = sum(count for _reason, count in report.held)  # type: ignore[attr-defined]
    collected = sum(count for _reason, count in report.collected)  # type: ignore[attr-defined]
    assert report.candidates == len(_MODULES)  # type: ignore[attr-defined]
    assert report.candidates == held + collected  # type: ignore[attr-defined]
    assert {r for r, _c in report.held} <= GC_HOLD_REASONS  # type: ignore[attr-defined]
    assert {r for r, _c in report.collected} <= GC_COLLECT_REASONS  # type: ignore[attr-defined]
    # A quiet run still answers, with measured zeros.
    assert dict(report.collected)[GC_COLLECT_CORRUPT] == 0  # type: ignore[attr-defined]
    assert dict(report.held)[GC_HOLD_RETAINED] == len(_MODULES)  # type: ignore[attr-defined]


def test_a_corrupt_identity_row_is_collected(tmp_path: Path) -> None:
    cache_path = _cold_store(tmp_path)
    break_identity_checksum(cache_path, "alpha.py")

    report = _sweep(cache_path)

    assert dict(report.collected)[GC_COLLECT_CORRUPT] == 1  # type: ignore[attr-defined]
    assert set(read_identity_columns(cache_path)) == {"beta.py", "gamma.py"}


def test_an_orphan_is_collected_only_when_the_live_set_is_known(
    tmp_path: Path,
) -> None:
    """A job asked without a live set does not guess which files still exist.

    Both directions in one place on purpose: the same store answers "nothing
    orphaned" and "one orphaned" depending only on whether the caller could
    say what is live.
    """

    cache_path = _cold_store(tmp_path)

    blind = _sweep(cache_path)
    assert dict(blind.collected)[GC_COLLECT_ORPHANED] == 0  # type: ignore[attr-defined]
    assert len(read_identity_columns(cache_path)) == len(_MODULES)

    informed = _sweep(cache_path, live_wire_paths=frozenset({"alpha.py", "beta.py"}))
    assert dict(informed.collected)[GC_COLLECT_ORPHANED] == 1  # type: ignore[attr-defined]
    assert set(read_identity_columns(cache_path)) == {"alpha.py", "beta.py"}


def test_ttl_collects_only_what_the_deadline_has_passed(tmp_path: Path) -> None:
    """Both sides of the deadline, so a sweep that took everything would fail.

    The covering index ``ix_entry_used`` exists for exactly this query; its
    absence is caught by its own mutation.
    """

    cache_path = _cold_store(tmp_path)
    set_identity_column(cache_path, "alpha.py", "last_used_epoch", 0)

    report = collect_cache_garbage(
        path=cache_path,
        version=Cache._CACHE_VERSION,
        generation=1 << 62,
        now_epoch=int(time.time()),
        ttl_seconds=3600,
    )

    assert dict(report.collected)[GC_COLLECT_EXPIRED] == 1
    assert dict(report.detail)["expired_by_ttl"] == 1
    assert dict(report.detail)["evicted_for_budget"] == 0
    assert set(read_identity_columns(cache_path)) == {"beta.py", "gamma.py"}


def test_the_size_bound_evicts_and_says_it_was_the_budget(tmp_path: Path) -> None:
    cache_path = _cold_store(tmp_path)

    report = _sweep(cache_path, max_bytes=1)

    assert dict(report.detail)["evicted_for_budget"] > 0  # type: ignore[attr-defined]
    assert dict(report.detail)["expired_by_ttl"] == 0  # type: ignore[attr-defined]


def test_the_sweep_never_takes_the_current_generation(tmp_path: Path) -> None:
    """The one rule that is not a policy knob.

    Rows the running save produced are what make the *next* run warm; a
    collector that took them would rebuild the defect this whole migration
    exists to remove. Asked with a budget of one byte and the live generation,
    the sweep must decline to collect anything at all.
    """

    cache_path = _cold_store(tmp_path)
    generation = min(
        int(str(row["generation"]))
        for row in read_identity_columns(cache_path).values()
    )

    report = collect_cache_garbage(
        path=cache_path,
        version=Cache._CACHE_VERSION,
        generation=generation,
        now_epoch=int(time.time()),
        max_bytes=1,
    )

    assert sum(count for _r, count in report.collected) == 0
    assert len(read_identity_columns(cache_path)) == len(_MODULES)


def test_an_unusable_store_is_a_refusal_not_a_crash(tmp_path: Path) -> None:
    """A refusing job makes no claims, which the protocol enforces for us."""

    blocked = tmp_path / "cache.sqlite3"
    blocked.mkdir()

    report = _sweep(blocked)

    assert report.refusal is not None  # type: ignore[attr-defined]
    assert report.candidates == 0  # type: ignore[attr-defined]
    assert report.collected == ()  # type: ignore[attr-defined]


def test_the_cache_collects_through_the_shared_dispatcher(tmp_path: Path) -> None:
    """The cache is a job, not a mechanism of its own.

    This is the half that matters architecturally: the same ``run_gc`` that
    sweeps the run store sweeps the cache, the receipt carries the cache's
    report beside any other, and the orchestrator never learns that one of its
    jobs is a cache.
    """

    cache_path = _cold_store(tmp_path)
    break_identity_checksum(cache_path, "alpha.py")

    receipt = run_gc(
        [
            CacheStoreGcJob(
                path=cache_path,
                version=Cache._CACHE_VERSION,
                now_epoch=int(time.time()),
            )
        ]
    )

    assert [report.job for report in receipt.reports] == [GC_JOB_NAME]
    assert dict(receipt.reports[0].collected)[GC_COLLECT_CORRUPT] == 1


@pytest.mark.parametrize(
    "index_name",
    ["ux_entry_path", "ix_entry_gen", "ix_entry_used"],
)
def test_every_declared_index_is_used_by_a_query_that_runs(
    tmp_path: Path,
    index_name: str,
) -> None:
    """An index whose absence changes no plan is not an index this store keeps.

    Each of the three is named by the plan of the query it exists for, on the
    real schema. Dropping one is a mutation, and the mutation is what proves
    this test is not decoration.
    """

    from tests._cache_store_fixtures import open_store

    cache_path = _cold_store(tmp_path)
    plans_by_index = {
        "ux_entry_path": (
            "SELECT file_id FROM cache_entry WHERE wire_path = ?",
            ("alpha.py",),
        ),
        "ix_entry_gen": (
            "SELECT file_id FROM cache_entry WHERE generation < ? "
            "ORDER BY generation ASC",
            (1 << 62,),
        ),
        "ix_entry_used": (
            "SELECT file_id FROM cache_entry WHERE last_used_epoch < ?",
            (0,),
        ),
    }
    query, params = plans_by_index[index_name]
    with open_store(cache_path) as conn:
        plan = " ".join(
            str(row[-1]) for row in conn.execute("EXPLAIN QUERY PLAN " + query, params)
        )
    assert index_name in plan, plan
