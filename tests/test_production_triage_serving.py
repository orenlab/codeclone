# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The production triage's serving edge: the store's answer, or memory and
why.

Consumer migration C2.  ``get_production_triage`` builds its answer through
``_run_store_serving.served_production_triage``: the store's blocks and
cards are placed into the answer the surface built from the record, and
that answer is served only when it is the memory's byte for byte; every
other outcome is memory with a typed reason in ``serving`` -- the serving
switch on memory (its default until the cutover), the rollout off, a store
that is absent, of another generation, corrupt or unable to express the
run, a publication that failed, a store that disagrees.  Measured before
the edge (audit of 2026-10-06): the triage answer was the same bytes under
every value of the switch and carried no ``serving`` block -- the switch was
inert for this tool, and the pins below turn that around.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

import codeclone.api.run_store_serving as door_mod
import codeclone.surfaces.mcp._session_state_mixin as state_mixin_mod
import codeclone.utils.sqlite_store as sqlite_store
from codeclone.api.run_store_serving import (
    ENV_SERVE_FROM,
    SERVE_FROM_DEFAULT,
    SERVE_FROM_MEMORY,
    SERVE_FROM_RUN_STORE,
    RunStoreServingOutcome,
)
from codeclone.utils.coerce import as_mapping
from tests._run_summary_serving import (
    STORE_ROW_PERTURBATIONS,
    SummaryPopulation,
    serving_environment,
    store_row_replaced,
)
from tests._triage_serving import (
    TriagePopulations,
    memory_triage,
    shared_triage_populations,
    triage_answer,
    without_serving,
)

_GENERATION_1 = Path(__file__).parent / "fixtures" / "run_store_generation_1"


@pytest.fixture(scope="module")
def populations(tmp_path_factory: pytest.TempPathFactory) -> TriagePopulations:
    return shared_triage_populations(tmp_path_factory)


@pytest.fixture
def trusted(populations: TriagePopulations) -> SummaryPopulation:
    """A published run with a trusted baseline: every block populated."""
    return populations["trusted"]


@pytest.fixture
def read_count(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every run the door's triage reader reads, in order."""
    reads: list[str] = []
    original = vars(door_mod)["read_served_triage"]

    def _counting(store: object, run_id: str) -> object:
        reads.append(run_id)
        return original(store, run_id)

    monkeypatch.setattr(door_mod, "read_served_triage", _counting)
    return reads


def _wire(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _store_run_id(population: SummaryPopulation) -> str:
    link = population.record.execution.run_snapshot_link
    assert link is not None and link.store_run_id
    return link.store_run_id


def _door(
    population: SummaryPopulation,
    store_path: Path,
    edit: Callable[[Any], Any] = lambda link: link,
) -> tuple[object | None, RunStoreServingOutcome]:
    """The triage door over the population's bridge witness, edited."""
    record = population.record
    with serving_environment(store_path, serve_from=SERVE_FROM_RUN_STORE):
        return door_mod.read_run_store_triage(
            root=record.root, link=edit(record.execution.run_snapshot_link)
        )


# -- the switch -------------------------------------------------------------


def test_a_published_run_is_served_from_the_store_and_says_so(
    trusted: SummaryPopulation, read_count: list[str]
) -> None:
    """The store's answer is the memory's answer byte for byte, and the
    ``serving`` block -- the one key this edge adds, last -- names the
    store run the answer was read from."""
    answer = triage_answer(trusted, serve_from=SERVE_FROM_RUN_STORE)
    assert answer["serving"] == {
        "source": "run_store",
        "reason": "served",
        "store_run_id": _store_run_id(trusted),
    }
    assert list(answer)[-1] == "serving"
    assert _wire(without_serving(answer)) == _wire(memory_triage(trusted))
    assert read_count == [_store_run_id(trusted)]


@pytest.mark.parametrize(
    ("serve_from", "detail"),
    [
        (None, f"{ENV_SERVE_FROM}=memory"),
        (SERVE_FROM_MEMORY, f"{ENV_SERVE_FROM}=memory"),
        ("store", f"{ENV_SERVE_FROM}=memory"),
    ],
    ids=["unset", "memory", "misspelled"],
)
def test_every_other_switch_value_answers_memory_and_never_reads_the_store(
    trusted: SummaryPopulation,
    read_count: list[str],
    serve_from: str | None,
    detail: str,
) -> None:
    """Unset, ``memory`` and a word the switch does not know all name
    memory: the store is not read and the answer names the switch."""
    answer = triage_answer(trusted, serve_from=serve_from)
    assert answer["serving"] == {
        "source": "memory",
        "reason": "store_disabled",
        "store_run_id": _store_run_id(trusted),
        "detail": detail,
    }
    assert read_count == []
    assert _wire(without_serving(answer)) == _wire(memory_triage(trusted))


def test_the_default_source_is_memory_until_the_cutover() -> None:
    assert SERVE_FROM_DEFAULT == SERVE_FROM_MEMORY


def test_the_switch_is_no_longer_inert_for_the_triage(
    trusted: SummaryPopulation,
) -> None:
    """The positive control the audit measured the other way round
    (2d370f30: the same bytes under ``run_store`` and unset, no
    ``serving``): the two switch values now give two answers, and only in
    the block that says where the answer came from."""
    on_store = triage_answer(trusted, serve_from=SERVE_FROM_RUN_STORE)
    unset = triage_answer(trusted, serve_from=None)
    assert _wire(on_store) != _wire(unset)
    assert as_mapping(on_store["serving"])["source"] == "run_store"
    assert as_mapping(unset["serving"])["source"] == "memory"
    assert _wire(without_serving(on_store)) == _wire(without_serving(unset))


def test_a_rollout_that_names_no_store_answers_memory_by_design(
    trusted: SummaryPopulation,
    read_count: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The publication flag stays the kill switch: an execution that
    published is answered from memory, unread, once the rollout is off."""
    monkeypatch.delenv("CODECLONE_RUN_STORE_ENABLED", raising=False)
    monkeypatch.setenv(ENV_SERVE_FROM, SERVE_FROM_RUN_STORE)
    answer = trusted.service.get_production_triage(
        run_id=trusted.record.run_id, root=str(trusted.root)
    )
    assert answer["serving"] == {
        "source": "memory",
        "reason": "store_disabled",
        "store_run_id": _store_run_id(trusted),
    }
    assert read_count == []


# -- the door's reasons -----------------------------------------------------


def _failed(link: Any) -> Any:
    return replace(
        link,
        state="unpublished",
        outcome="failed",
        store_run_id="",
        report_run_identity="f" * 64,
        failure="OSError",
    )


def test_a_record_that_states_no_bridge_is_memory_by_design(
    trusted: SummaryPopulation,
) -> None:
    stored, outcome = _door(trusted, trusted.store_path, lambda _link: None)
    assert stored is None
    assert (outcome.source, outcome.reason) == ("memory", "not_published")


def test_a_failed_publication_is_a_typed_fallback(
    trusted: SummaryPopulation,
) -> None:
    stored, outcome = _door(trusted, trusted.store_path, _failed)
    assert stored is None
    assert (outcome.source, outcome.reason) == ("memory", "run_not_published")
    assert "ffffffffffff" in outcome.detail


def test_a_store_of_another_generation_is_refused_typed(
    trusted: SummaryPopulation, tmp_path: Path
) -> None:
    """The REAL generation-1 artifact is refused at open."""
    provenance = json.loads((_GENERATION_1 / "provenance.json").read_text("utf-8"))
    store = tmp_path / "generation-1.sqlite3"
    shutil.copy(_GENERATION_1 / "runs.sqlite3", store)
    stored, outcome = _door(
        trusted,
        store,
        lambda link: replace(link, store_run_id=str(provenance["run_id"])),
    )
    assert stored is None
    assert (outcome.source, outcome.reason) == ("memory", "incompatible_generation")
    assert "canonical_model stored '1' declared '3'" in outcome.detail


def test_an_absent_store_is_a_fallback_and_is_never_created(
    trusted: SummaryPopulation, tmp_path: Path
) -> None:
    absent = tmp_path / "nowhere" / "runs.sqlite3"
    stored, outcome = _door(trusted, absent)
    assert stored is None
    assert (outcome.source, outcome.reason) == ("memory", "store_absent")
    assert not absent.parent.exists()


def test_a_corrupt_member_the_triage_reads_is_an_integrity_refusal(
    trusted: SummaryPopulation, tmp_path: Path
) -> None:
    """On a copy of the published store, one ``finding_evaluation`` member
    no longer hashes to its address: the triage reads that family, so the
    door refuses ``integrity``."""
    copy = tmp_path / "trusted.sqlite3"
    shutil.copy(trusted.store_path, copy)
    with sqlite3.connect(copy) as raw:
        raw.execute(
            "UPDATE objects SET payload = ? WHERE object_pk = "
            "(SELECT MIN(o.object_pk) FROM objects o JOIN families f "
            "ON f.family_pk = o.family_pk WHERE f.family = 'finding_evaluation')",
            (b'{"tampered": true}',),
        )
    raw.close()
    stored, outcome = _door(trusted, copy)
    assert stored is None
    assert (outcome.source, outcome.reason) == ("memory", "integrity")


def test_a_store_another_process_holds_is_unavailable_and_then_served(
    trusted: SummaryPopulation, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A held exclusive lock on a copy of the published store: the triage
    is answered from memory as ``store_unavailable``; the lock lifted, the
    same door serves the run (the positive control)."""
    copy = tmp_path / "trusted.sqlite3"
    shutil.copy(trusted.store_path, copy)
    monkeypatch.setattr(sqlite_store, "_SQLITE_BUSY_TIMEOUT_MS", 200)
    holder = sqlite3.connect(copy, isolation_level=None)
    holder.execute("PRAGMA locking_mode=EXCLUSIVE")
    holder.execute("BEGIN EXCLUSIVE")
    holder.execute("SELECT COUNT(*) FROM runs").fetchone()
    try:
        stored, outcome = _door(trusted, copy)
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    assert stored is None
    assert (outcome.source, outcome.reason) == ("memory", "store_unavailable")
    assert "database is locked" in outcome.detail
    _stored, served = _door(trusted, copy)
    assert served.reason == "served", served


def test_a_suggestion_whose_finding_the_store_lacks_is_unexpressible(
    trusted: SummaryPopulation,
) -> None:
    """One stored dead-code group taken away while its suggestion stays
    ranked: the store cannot state that suggestion's source kind or
    effort, so it refuses the run typed -- never a suggestion silently
    dropped from the breakdown."""
    _name, perturb, _fields = STORE_ROW_PERTURBATIONS["dead_symbol_group"]
    with store_row_replaced(perturb):
        stored, outcome = _door(trusted, trusted.store_path)
        answer = triage_answer(trusted, serve_from=SERVE_FROM_RUN_STORE)
    assert stored is None
    assert (outcome.source, outcome.reason) == ("memory", "unexpressible")
    assert "dead_code:" in outcome.detail, outcome.detail
    serving = as_mapping(answer.pop("serving"))
    assert (serving["source"], serving["reason"]) == ("memory", "unexpressible")
    assert _wire(answer) == _wire(memory_triage(trusted))


# -- the decision -----------------------------------------------------------


@pytest.fixture
def disagreeing_total(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The door's reader, answering every fact as stored but the suggestion
    total one more."""
    original = vars(door_mod)["read_served_triage"]

    def _read(store: object, run_id: str) -> object:
        stored = original(store, run_id)
        suggestions = dict(stored.suggestions)
        suggestions["total"] = int(str(suggestions["total"])) + 1
        return replace(stored, suggestions=suggestions)

    monkeypatch.setattr(door_mod, "read_served_triage", _read)
    yield


@pytest.mark.usefixtures("disagreeing_total")
def test_a_disagreeing_store_is_answered_from_memory_and_named(
    trusted: SummaryPopulation,
) -> None:
    """The store never wins an argument with the producer's own answer:
    the values stay memory's, the reason says divergent, the detail names
    the field."""
    answer = triage_answer(trusted, serve_from=SERVE_FROM_RUN_STORE)
    assert answer["serving"] == {
        "source": "memory",
        "reason": "divergent",
        "store_run_id": _store_run_id(trusted),
        "detail": "diverging: suggestions.total",
    }
    assert _wire(without_serving(answer)) == _wire(memory_triage(trusted))


def test_get_production_triage_answers_what_the_edge_decides(
    trusted: SummaryPopulation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reverse pin at the call site: the tool's values are the edge's
    payload, not a second reading of the record beside it."""
    outcome = RunStoreServingOutcome(source="memory", reason="not_published")
    monkeypatch.setattr(
        state_mixin_mod,
        "served_production_triage",
        lambda _record, _memory, **_limits: ({"sentinel": True}, outcome),
    )
    answer = trusted.service.get_production_triage(
        run_id=trusted.record.run_id, root=str(trusted.root)
    )
    assert answer == {
        "sentinel": True,
        "serving": {"source": "memory", "reason": "not_published"},
    }


@pytest.mark.parametrize(
    ("asked", "returned"),
    [(0, 1), (-3, 1), (1, 1), (99, 10)],
    ids=["zero", "negative", "one", "past_the_ceiling"],
)
def test_a_limit_is_clamped_once_for_both_answers(
    populations: TriagePopulations, asked: int, returned: int
) -> None:
    """The surface's limit is one to ten, applied before either answer is
    built: the store's projection, which would answer a limit of zero with
    nothing, never sees an unclamped limit."""
    population = populations["triage_kinds"]
    answer = triage_answer(
        population,
        serve_from=SERVE_FROM_RUN_STORE,
        max_hotspots=asked,
        max_suggestions=asked,
    )
    assert as_mapping(answer["serving"])["reason"] == "served", answer["serving"]
    hotspots = as_mapping(answer["top_hotspots"])
    suggestions = as_mapping(answer["top_suggestions"])
    assert hotspots["returned"] == min(returned, int(str(hotspots["available"])))
    assert suggestions["returned"] == min(returned, int(str(suggestions["available"])))


# -- the kept facts ---------------------------------------------------------


def test_a_triage_asked_again_reads_no_family_and_states_the_same_facts(
    trusted: SummaryPopulation, read_count: list[str]
) -> None:
    first, served = _door(trusted, trusted.store_path)
    again, served_again = _door(trusted, trusted.store_path)
    assert served.reason == served_again.reason == "served"
    assert read_count == [_store_run_id(trusted)]
    assert again is first


def test_the_triage_facts_are_kept_apart_from_the_summary_facts(
    trusted: SummaryPopulation,
) -> None:
    """One run asked the summary and the triage: each kind is read and kept
    under its own name, and neither answers for the other."""
    record = trusted.record
    with serving_environment(trusted.store_path, serve_from=SERVE_FROM_RUN_STORE):
        summary, _summary_served = door_mod.read_run_store_summary(
            root=record.root, link=record.execution.run_snapshot_link
        )
    triage, _triage_served = _door(trusted, trusted.store_path)
    assert type(summary).__name__ == "ServedRunSummary"
    assert type(triage).__name__ == "ServedTriage"
    kinds = {
        kind
        for run in door_mod._SERVED_FACTS.runs()
        for kind in ("run_summary", "triage")
        if door_mod._SERVED_FACTS.held(run, kind) is not None
    }
    assert kinds == {"run_summary", "triage"}
