# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A run's served facts are kept for the life of the process.

The run summary, the patch contract and the blast radius are answered from
facts the store states for a published run -- a pure function of the run's
member rows, which its content address fixes.  The door keeps each run's
facts once read (``api.run_store_serving.ServedFactsCache``), so a question
asked again reads no family; what a kept fact may never do is outlive the
run it states or answer for another run:

* the key is the store FILE (where, which file, which generation) and the
  run id: two runs of one store, or one run id in two store files, are two
  entries;
* a hit still opens the store and proves the run is published THERE -- a run
  unpublished or collected since is refused, never served from the cache;
* the cache is a bounded LRU over runs, its bound held equal to the most
  runs one MCP session may retain.
"""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

import codeclone.api.run_store_serving as door
from codeclone.api.run_store_serving import (
    SERVED_FACTS_CACHE_RUNS,
    RunStoreServingOutcome,
    ServedFactsCache,
    read_run_store_blast_radius_facts,
    read_run_store_patch_run,
    read_run_store_summary,
)
from codeclone.surfaces.mcp._session_shared import MAX_MCP_HISTORY_LIMIT
from tests._patch_contract_serving import shared_cycles
from tests._run_summary_serving import (
    SummaryPopulation,
    fresh_served_facts,
    serving_environment,
    shared_populations,
)
from tests.test_run_summary_declared_families import scanned

__all__ = ["scanned"]

_Door = Callable[..., tuple[object | None, RunStoreServingOutcome]]
_DOORS: dict[str, _Door] = {
    "run_summary": read_run_store_summary,
    "patch_run": read_run_store_patch_run,
    "blast_radius": read_run_store_blast_radius_facts,
}


def _ask(
    population: SummaryPopulation, kind: str, *, store: Path | None = None
) -> tuple[object | None, RunStoreServingOutcome]:
    record = population.record
    with serving_environment(store or population.store_path, serve_from="run_store"):
        return _DOORS[kind](root=record.root, link=record.execution.run_snapshot_link)


@pytest.mark.parametrize("kind", list(_DOORS))
@pytest.mark.parametrize("name", ["trusted", "coverage_ok", "projection_corpus"])
def test_a_question_asked_again_reads_no_family_and_states_the_same_facts(
    tmp_path_factory: pytest.TempPathFactory,
    scanned: list[str],
    kind: str,
    name: str,
) -> None:
    population = shared_populations(tmp_path_factory)[name]
    first, served = _ask(population, kind)
    assert served.reason == "served", served
    assert scanned, "the first question read nothing"
    scanned.clear()
    again, served_again = _ask(population, kind)
    assert scanned == []
    assert again == first
    assert served_again == served


def _store_copy(population: SummaryPopulation, directory: Path) -> Path:
    copy = directory / f"{population.name}.sqlite3"
    shutil.copy(population.store_path, copy)
    return copy


@pytest.mark.parametrize("kind", list(_DOORS))
def test_a_kept_run_no_longer_published_is_refused_not_served(
    tmp_path_factory: pytest.TempPathFactory, tmp_path: Path, kind: str
) -> None:
    population = shared_populations(tmp_path_factory)["trusted"]
    copy = _store_copy(population, tmp_path)
    kept, served = _ask(population, kind, store=copy)
    assert kept is not None and served.reason == "served"
    run_id = population.record.execution.run_snapshot_link.store_run_id  # type: ignore[union-attr]
    with sqlite3.connect(copy) as raw:
        raw.execute("UPDATE runs SET published = 0 WHERE run_id = ?", (run_id,))
    raw.close()
    answer, refused = _ask(population, kind, store=copy)
    assert answer is None
    assert refused.reason == "run_not_published", refused


@pytest.mark.parametrize("kind", list(_DOORS))
def test_a_kept_run_is_not_served_out_of_another_store_file(
    tmp_path_factory: pytest.TempPathFactory, tmp_path: Path, kind: str
) -> None:
    """The same run id in another file -- here a copy whose declared rows
    no longer hash to their addresses -- is another run to the cache."""
    population = shared_populations(tmp_path_factory)["trusted"]
    kept, served = _ask(population, kind)
    assert kept is not None and served.reason == "served"
    copy = _store_copy(population, tmp_path)
    with sqlite3.connect(copy) as raw:
        raw.execute(
            "UPDATE objects SET payload = ? WHERE family_pk = "
            "(SELECT family_pk FROM families WHERE family = 'clone_group')",
            (b'{"tampered": 1}',),
        )
    raw.close()
    answer, refused = _ask(population, kind, store=copy)
    assert answer is None
    assert refused.reason == "integrity", refused


@pytest.mark.parametrize("kind", ["run_summary", "patch_run"])
def test_two_runs_of_one_store_keep_their_own_facts(
    tmp_path_factory: pytest.TempPathFactory, kind: str
) -> None:
    """A patch cycle's before-run and after-run share one store file: each
    is answered with its own facts, whichever was kept first."""
    cycle = shared_cycles(tmp_path_factory)["regressed"]
    assert cycle.before is not None and cycle.after is not None
    answers = []
    for record in (cycle.before, cycle.after, cycle.before):
        with serving_environment(cycle.store_path, serve_from="run_store"):
            facts, served = _DOORS[kind](
                root=record.root, link=record.execution.run_snapshot_link
            )
        assert served.reason == "served", served
        link = record.execution.run_snapshot_link
        assert link is not None
        assert facts == fresh_served_facts(kind, cycle.store_path, link.store_run_id)
        answers.append(facts)
    assert answers[0] != answers[1]
    assert answers[0] == answers[2]


def test_each_kind_of_one_run_is_kept_apart(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """One run asked all three questions twice: each kind answers its own
    facts, kept or not."""
    population = shared_populations(tmp_path_factory)["coverage_ok"]
    link = population.record.execution.run_snapshot_link
    assert link is not None
    for _round in range(2):
        for kind in _DOORS:
            facts, served = _ask(population, kind)
            assert served.reason == "served", served
            assert facts == fresh_served_facts(
                kind, population.store_path, link.store_run_id
            ), kind


def test_the_cache_evicts_the_run_used_least_recently() -> None:
    cache = ServedFactsCache(2)
    first, second, third = ((("store", 0, 0, (1, "r", "c")), run) for run in "abc")
    cache.keep(first, "kind", "A")
    cache.keep(second, "kind", "B")
    assert cache.held(first, "kind") == "A"  # first is now the most recent
    cache.keep(third, "kind", "C")
    assert cache.runs() == (first, third)
    assert cache.held(second, "kind") is None
    assert cache.held(first, "other kind") is None


def test_the_process_keeps_as_many_runs_as_one_session_may_retain() -> None:
    """The bound's rule, not its literal: the facts of every run a session
    can name at once, and no more."""
    assert SERVED_FACTS_CACHE_RUNS == MAX_MCP_HISTORY_LIMIT
    for index in range(SERVED_FACTS_CACHE_RUNS + 1):
        door._SERVED_FACTS.keep((("s", 0, 0, (1, "r", "c")), str(index)), "kind", index)
    runs = door._SERVED_FACTS.runs()
    assert len(runs) == SERVED_FACTS_CACHE_RUNS
    assert runs[0][1] == "1"


@pytest.mark.parametrize("kind", list(_DOORS))
def test_a_store_file_removed_under_the_open_handle_is_unavailable(
    tmp_path_factory: pytest.TempPathFactory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    """The file named by the open handle is gone before its identity is
    read: a fault of the environment, answered ``store_unavailable`` with
    memory -- never a raw ``OSError`` taking the tool down."""
    population = shared_populations(tmp_path_factory)["trusted"]
    copy = _store_copy(population, tmp_path)
    store_class = vars(door)["RunStore"]
    opened = store_class.__init__

    def _opened_then_removed(
        self: object, path: object, *, create: bool = True
    ) -> None:
        opened(self, path, create=create)
        Path(str(path)).unlink()

    monkeypatch.setattr(store_class, "__init__", _opened_then_removed)
    answer, outcome = _ask(population, kind, store=copy)
    assert answer is None
    assert outcome.reason == "store_unavailable", outcome
