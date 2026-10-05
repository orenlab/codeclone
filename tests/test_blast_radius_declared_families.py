# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The blast radius reads its declared families, all of them, and only them.

Consumer migration C7.  ``read_served_blast_radius_facts`` reads
``BLAST_RADIUS_FAMILIES`` through ``read_named_families``: every family
outside the declaration is a typed absence, so the declaration is proven in
both directions on the populations of ``tests/_blast_radius_serving.py``
(the measurement that produced it, 2026-10-03, ran the same way):

* complete: the bounded facts never refuse, and equal the facts of the whole
  read on every population;
* not excessive: every declared family, declared away, refuses on some
  population -- a family the projection never touches could not be found
  this way, so it could not stay declared.

Beside the declaration, the store's facts are held to the document's facts
FIELD BY FIELD and ORDER BY ORDER on every population: the carrier the
computation reads is the same value whichever source filled it.
"""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, fields
from pathlib import Path

import pytest

from codeclone.analysis.blast_radius import blast_radius_facts
from codeclone.canonical import store as store_module
from codeclone.canonical.blast_radius_facts import BlastRadiusFacts
from codeclone.canonical.blast_radius_projection import blast_radius_facts_from_model
from codeclone.canonical.errors import StoreIntegrityError
from codeclone.canonical.serving import (
    BLAST_RADIUS_FAMILIES,
    read_served_blast_radius_facts,
)
from codeclone.canonical.store import (
    RunStore,
    UnreadFamilyError,
    read_named_families,
)
from tests._blast_radius_serving import (
    BLAST_POPULATIONS,
    BlastPopulations,
    BlastRequest,
    blast_answer,
    forget_answers,
    shared_blast_populations,
)
from tests._run_summary_serving import store_row_replaced
from tests.test_run_store_named_family_read import decoded

__all__ = ["decoded"]


@dataclass(frozen=True, slots=True)
class _Stored:
    name: str
    path: Path
    run_id: str
    memory: BlastRadiusFacts


@pytest.fixture(scope="module")
def populations(tmp_path_factory: pytest.TempPathFactory) -> BlastPopulations:
    return shared_blast_populations(tmp_path_factory)


@pytest.fixture(scope="module")
def stored(populations: BlastPopulations) -> list[_Stored]:
    """Every population's store, its run, and the facts its document states."""
    runs: list[_Stored] = []
    for name in BLAST_POPULATIONS:
        population = populations[name]
        record = population.record
        link = record.execution.run_snapshot_link
        assert link is not None and link.store_run_id
        runs.append(
            _Stored(
                name,
                population.store_path,
                link.store_run_id,
                blast_radius_facts(record.served_report),
            )
        )
    return runs


def _bounded(run: _Stored) -> BlastRadiusFacts:
    with RunStore(run.path, create=False) as store:
        return read_served_blast_radius_facts(store, run.run_id)


def test_the_declaration_names_each_registry_family_once() -> None:
    names = [entry.family for entry in BLAST_RADIUS_FAMILIES]
    registry = {entry.family for entry in store_module._FAMILIES}
    assert len(names) == len(set(names))
    assert set(names) <= registry
    assert names == sorted(names)


def test_the_bounded_facts_are_the_whole_reads_on_every_population(
    stored: list[_Stored],
) -> None:
    for run in stored:
        with RunStore(run.path, create=False) as store:
            whole = blast_radius_facts_from_model(store.read_run(run.run_id))
            bounded = read_served_blast_radius_facts(store, run.run_id)
        assert bounded == whole, run.name


@pytest.mark.parametrize("field", [field.name for field in fields(BlastRadiusFacts)])
def test_each_stored_fact_is_the_documents_in_value_and_order(
    stored: list[_Stored], field: str
) -> None:
    """One field of the carrier: the store's tuple is the document's tuple,
    element for element, on every population -- and some population holds a
    non-empty one, so the comparison saw something."""
    reached = []
    for run in stored:
        value = getattr(_bounded(run), field)
        assert value == getattr(run.memory, field), (run.name, field)
        if value:
            reached.append(run.name)
    assert reached, f"{field} is empty on every population"


@pytest.mark.parametrize(
    "declared", BLAST_RADIUS_FAMILIES, ids=lambda entry: entry.family
)
def test_no_declared_family_can_be_declared_away(
    stored: list[_Stored], declared: store_module._FamilyEntry
) -> None:
    rest = [entry for entry in BLAST_RADIUS_FAMILIES if entry is not declared]
    refusers: list[str] = []
    for run in stored:
        with RunStore(run.path, create=False) as store:
            model = read_named_families(store, run.run_id, rest)
        try:
            blast_radius_facts_from_model(model)
        except UnreadFamilyError as refusal:
            assert refusal.family == declared.family
            refusers.append(run.name)
    assert refusers, f"{declared.family} is declared and read by no population"


def test_the_reading_decodes_only_its_declared_families(
    stored: list[_Stored], decoded: list[str]
) -> None:
    run = next(item for item in stored if item.name == "fanout")
    statements: list[str] = []
    with RunStore(run.path, create=False) as store:
        store._connection.set_trace_callback(statements.append)
        try:
            read_served_blast_radius_facts(store, run.run_id)
        finally:
            store._connection.set_trace_callback(None)
        bounded = list(decoded)
        decoded.clear()
        store.read_run(run.run_id)
    declared = {entry.family for entry in BLAST_RADIUS_FAMILIES}
    assert bounded and set(bounded) <= declared
    assert len(decoded) > len(bounded)
    assert not any("FROM run_members m" in sql for sql in statements), statements
    assert sum("CROSS JOIN run_members m" in sql for sql in statements) == len(declared)


def _dropped(family: str) -> Callable[[dict[str, list[object]]], None]:
    def perturb(collected: dict[str, list[object]]) -> None:
        rows = collected.get(family)
        if rows is not None:
            del rows[0]

    return perturb


@pytest.mark.parametrize(
    "family",
    ["unit_span", "relationship_observation", "candidate", "dead_code_observation"],
)
def test_a_replaced_row_of_an_undeclared_family_leaves_the_answer(
    populations: BlastPopulations, family: str
) -> None:
    """The positive control from the store side: the row really is replaced
    for the whole read, and the served answer neither moves nor stops being
    served."""
    population = populations["fanout"]
    link = population.record.execution.run_snapshot_link
    assert link is not None
    assert family not in {entry.family for entry in BLAST_RADIUS_FAMILIES}
    entry = next(item for item in store_module._FAMILIES if item.family == family)
    request = BlastRequest(("pkg/core.py",), "transitive")
    forget_answers(population)
    before = blast_answer(population, request, serve_from="run_store")
    with RunStore(population.store_path, create=False) as store:
        untouched = len(store.read_family(link.store_run_id, entry))  # type: ignore[arg-type]
    forget_answers(population)
    with store_row_replaced(_dropped(family)):
        after = blast_answer(population, request, serve_from="run_store")
        with RunStore(population.store_path, create=False) as store:
            whole = store.read_run(link.store_run_id)
    forget_answers(population)
    assert untouched >= 1
    replaced = len(getattr(whole.facts.analysis, _ATTRIBUTE[family]))
    assert replaced == untouched - 1, "the replacement did not reach the whole read"
    assert before == after
    assert after["serving"] == {
        "source": "run_store",
        "reason": "served",
        "store_run_id": link.store_run_id,
    }


#: The model attribute each undeclared control family is assembled into.
_ATTRIBUTE: dict[str, str] = {
    "unit_span": "unit_spans",
    "relationship_observation": "relationship_observations",
    "candidate": "candidates",
    "dead_code_observation": "dead_code_observations",
}


_CORRUPT_FIRST_MEMBER = (
    "UPDATE objects SET payload = ? WHERE object_pk = "
    "(SELECT MIN(o.object_pk) FROM objects o "
    "JOIN families f ON f.family_pk = o.family_pk WHERE f.family = ?)"
)


def _corrupted(run: _Stored, directory: Path, family: str) -> Path:
    """A copy of the run's store whose first ``family`` member no longer
    matches its content address."""
    copy = Path(shutil.copy(run.path, directory / f"{family}.sqlite3"))
    connection = sqlite3.connect(copy)
    try:
        with connection:
            connection.execute(_CORRUPT_FIRST_MEMBER, (b'{"tampered": 1}', family))
    finally:
        connection.close()
    return copy


def test_a_corrupt_member_outside_the_declaration_is_never_read(
    stored: list[_Stored], tmp_path: Path
) -> None:
    run = next(item for item in stored if item.name == "fanout")
    expected = _bounded(run)
    undeclared = _corrupted(run, tmp_path, "unit_span")
    with RunStore(undeclared, create=False) as store:
        assert read_served_blast_radius_facts(store, run.run_id) == expected
        with pytest.raises(StoreIntegrityError, match="content address"):
            store.read_run(run.run_id)
    declared = _corrupted(run, tmp_path, "dependency_relation")
    with (
        RunStore(declared, create=False) as store,
        pytest.raises(StoreIntegrityError, match="content address"),
    ):
        read_served_blast_radius_facts(store, run.run_id)
