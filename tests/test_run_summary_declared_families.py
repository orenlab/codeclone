# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Every serving reading declares its families, and reads exactly those.

The run summary is read with ``read_named_families`` over
``RUN_SUMMARY_FAMILIES`` and the conditions of ``RUN_SUMMARY_READ_WHEN``:
every family outside the declaration is a typed absence, so the declaration
is proven in both directions on the nineteen served populations
(``tests/_run_summary_serving.py``), per branch of each condition --

* complete: the bounded summary never refuses, and it equals the summary of
  the whole read, block for block, on every population -- the populations
  reach both branches of every condition;
* not excessive: every family declared on every run, declared away, refuses
  on some population; every family a condition reads, taken out of its
  condition, refuses on some population that meets the condition and on
  none that does not -- a family the projections never touch could not be
  found this way, so it could not stay declared;
* exact: on every population the reading scans exactly the families
  declared for it -- the unconditional ones, and the conditional ones whose
  decider holds a row of that run.

The two family-read readings (served slices, authority candidates) declare
theirs too, held equal to the families they actually ask the store for.
The positive controls close the loop from the store side: a replaced row of
a declared family moves the answer (``tests/test_run_summary_store_carriers``),
a replaced or even corrupted row of an undeclared family does not, because
the bounded read never reads it -- while the whole read meets it.
"""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from codeclone.canonical import store as store_module
from codeclone.canonical.errors import StoreIntegrityError
from codeclone.canonical.serving import (
    RUN_SUMMARY_FAMILIES,
    RUN_SUMMARY_READ_WHEN,
    SERVED_AUTHORITY_CANDIDATE_FAMILIES,
    SERVED_SLICE_FAMILIES,
    read_served_authority_candidates,
    read_served_run_slices,
    read_served_run_summary,
    run_summary_from_model,
)
from codeclone.canonical.store import (
    ReadWhen,
    RunStore,
    UnreadFamilyError,
    read_named_families,
)
from tests._run_summary_serving import (
    RUN_SUMMARY_POPULATIONS,
    UNREAD_ROW_PERTURBATIONS,
    SummaryPopulations,
    shared_populations,
    store_row_replaced,
)
from tests.test_run_store_bounded_family_read import _MODEL_ACCESSORS
from tests.test_run_store_named_family_read import decoded

__all__ = ["decoded"]


@dataclass(frozen=True, slots=True)
class _Stored:
    name: str
    path: Path
    run_id: str


@pytest.fixture(scope="module")
def populations(tmp_path_factory: pytest.TempPathFactory) -> SummaryPopulations:
    return shared_populations(tmp_path_factory)


@pytest.fixture(scope="module")
def stored(populations: SummaryPopulations) -> list[_Stored]:
    """Every population's store and the run its execution published."""
    runs: list[_Stored] = []
    for name in RUN_SUMMARY_POPULATIONS:
        population = populations[name]
        link = population.record.execution.run_snapshot_link
        assert link is not None and link.store_run_id
        runs.append(_Stored(name, population.store_path, link.store_run_id))
    return runs


def declaration_is_well_formed(
    always: tuple[store_module._FamilyEntry, ...], conditions: tuple[ReadWhen, ...]
) -> None:
    """Each registry family named once across the whole declaration, the
    unconditional ones sorted, every decider among them."""
    names = [entry.family for entry in always]
    conditional = [entry.family for when in conditions for entry in when.families]
    registry = {entry.family for entry in store_module._FAMILIES}
    assert len([*names, *conditional]) == len({*names, *conditional})
    assert {*names, *conditional} <= registry
    assert names == sorted(names)
    assert {when.decider.family for when in conditions} <= set(names)


def families_declared_for(
    always: tuple[store_module._FamilyEntry, ...],
    conditions: tuple[ReadWhen, ...],
    store: RunStore,
    run_id: str,
) -> frozenset[str]:
    """What the declaration says a reading of this run reads: the
    unconditional families, and each condition's families when the run's
    own decider family holds a row."""
    declared = {entry.family for entry in always}
    for when in conditions:
        if store.read_family(run_id, when.decider):  # type: ignore[arg-type]
            declared.update(entry.family for entry in when.families)
    return frozenset(declared)


def condition_branches(
    conditions: tuple[ReadWhen, ...], runs: list[_Stored]
) -> dict[str, tuple[list[str], list[str]]]:
    """Per condition (by its decider): the runs that meet it, and the runs
    that do not."""
    branches: dict[str, tuple[list[str], list[str]]] = {}
    for when in conditions:
        held: list[str] = []
        empty: list[str] = []
        for run in runs:
            with RunStore(run.path, create=False) as store:
                holds = bool(store.read_family(run.run_id, when.decider))  # type: ignore[arg-type]
            (held if holds else empty).append(run.name)
        branches[when.decider.family] = (held, empty)
    return branches


def without(conditions: tuple[ReadWhen, ...], family: str) -> tuple[ReadWhen, ...]:
    """The conditions with ``family`` taken out -- as a decider (its
    condition goes with it) and as a family a condition reads."""
    return tuple(
        ReadWhen(
            decider=when.decider,
            families=tuple(entry for entry in when.families if entry.family != family),
        )
        for when in conditions
        if when.decider.family != family
    )


def test_the_declaration_names_each_registry_family_once() -> None:
    declaration_is_well_formed(RUN_SUMMARY_FAMILIES, RUN_SUMMARY_READ_WHEN)


def test_each_condition_is_met_and_missed_by_the_population(
    stored: list[_Stored],
) -> None:
    """The accounting before the rule: both branches of every condition are
    reached by a named population, or the rule below proves nothing."""
    for decider, (held, empty) in condition_branches(
        RUN_SUMMARY_READ_WHEN, stored
    ).items():
        assert held and empty, (decider, held, empty)


def test_the_bounded_summary_is_the_whole_reads_on_every_population(
    stored: list[_Stored],
) -> None:
    """Complete, and equivalent: the declared families answer every block
    exactly as the whole run does -- no refusal on any population."""
    for run in stored:
        with RunStore(run.path, create=False) as store:
            whole = run_summary_from_model(
                store.read_run(run.run_id), run_id=run.run_id
            )
            bounded = read_served_run_summary(store, run.run_id)
        assert bounded == whole, run.name


@pytest.mark.parametrize(
    "declared", RUN_SUMMARY_FAMILIES, ids=lambda entry: entry.family
)
def test_no_declared_family_can_be_declared_away(
    stored: list[_Stored], declared: store_module._FamilyEntry
) -> None:
    """Not excessive: without this one family -- and without a condition it
    decides -- the summary refuses on some population, naming exactly it."""
    rest = [entry for entry in RUN_SUMMARY_FAMILIES if entry is not declared]
    conditions = without(RUN_SUMMARY_READ_WHEN, declared.family)
    refusers: list[str] = []
    for run in stored:
        with RunStore(run.path, create=False) as store:
            model = read_named_families(store, run.run_id, rest, read_when=conditions)
        try:
            run_summary_from_model(model, run_id=run.run_id)
        except UnreadFamilyError as refusal:
            assert refusal.family == declared.family
            refusers.append(run.name)
    assert refusers, f"{declared.family} is declared and read by no population"


@pytest.mark.parametrize(
    "conditional",
    [entry for when in RUN_SUMMARY_READ_WHEN for entry in when.families],
    ids=lambda entry: entry.family,
)
def test_each_conditional_family_is_needed_exactly_when_its_condition_holds(
    stored: list[_Stored], conditional: store_module._FamilyEntry
) -> None:
    """Per branch: taken out of its condition, the family refuses on some
    population that meets the condition, and on none that does not."""
    (when,) = [item for item in RUN_SUMMARY_READ_WHEN if conditional in item.families]
    held, _empty = condition_branches((when,), stored)[when.decider.family]
    conditions = without(RUN_SUMMARY_READ_WHEN, conditional.family)
    refusers: list[str] = []
    for run in stored:
        with RunStore(run.path, create=False) as store:
            model = read_named_families(
                store, run.run_id, RUN_SUMMARY_FAMILIES, read_when=conditions
            )
        try:
            run_summary_from_model(model, run_id=run.run_id)
        except UnreadFamilyError as refusal:
            assert refusal.family == conditional.family
            refusers.append(run.name)
    assert refusers, f"{conditional.family} is read by no population"
    assert set(refusers) <= set(held), sorted(set(refusers) - set(held))


@pytest.fixture
def scanned(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Every family the store scans for a run, empty or not."""
    seen: list[str] = []
    original = store_module._scan_run_family

    def _scanning(*args: object) -> None:
        seen.append(str(args[3]))
        original(*args)  # type: ignore[arg-type]

    monkeypatch.setattr(store_module, "_scan_run_family", _scanning)
    yield seen


def test_the_summary_reading_scans_exactly_its_declared_families_per_run(
    stored: list[_Stored], scanned: list[str]
) -> None:
    """Exact, per run: every family scanned is declared for that run, and
    every family declared for it is scanned once."""
    for run in stored:
        with RunStore(run.path, create=False) as store:
            expected = families_declared_for(
                RUN_SUMMARY_FAMILIES, RUN_SUMMARY_READ_WHEN, store, run.run_id
            )
            scanned.clear()
            read_served_run_summary(store, run.run_id)
        assert sorted(scanned) == sorted(expected), run.name


def test_the_summary_reading_decodes_only_its_declared_families(
    stored: list[_Stored], decoded: list[str]
) -> None:
    """The edge is bounded, not a whole read wearing a declaration: it
    decodes members of declared families only, through the family scan, and
    the whole read measured beside it decodes more."""
    run = next(item for item in stored if item.name == "trusted")
    reads_only_its_declared_families(
        run,
        read_served_run_summary,
        (RUN_SUMMARY_FAMILIES, RUN_SUMMARY_READ_WHEN),
        decoded,
    )


def reads_only_its_declared_families(
    run: _Stored,
    reading: Callable[[RunStore, str], object],
    declaration: tuple[tuple[store_module._FamilyEntry, ...], tuple[ReadWhen, ...]],
    decoded: list[str],
) -> None:
    """One reading of one run, against the whole read beside it: it decodes
    declared families only, one family scan per family declared for the
    run, never a whole-run scan, and the whole read decodes more."""
    statements: list[str] = []
    with RunStore(run.path, create=False) as store:
        declared = families_declared_for(*declaration, store, run.run_id)
        decoded.clear()
        store._connection.set_trace_callback(statements.append)
        try:
            reading(store, run.run_id)
        finally:
            store._connection.set_trace_callback(None)
        bounded = list(decoded)
        decoded.clear()
        store.read_run(run.run_id)
    assert bounded and set(bounded) <= declared
    assert len(decoded) > len(bounded)
    assert not any("FROM run_members m" in sql for sql in statements), statements
    assert sum("CROSS JOIN run_members m" in sql for sql in statements) == len(declared)


@pytest.mark.parametrize("family", list(UNREAD_ROW_PERTURBATIONS))
def test_a_replaced_row_of_an_undeclared_family_leaves_the_answer(
    populations: SummaryPopulations, family: str
) -> None:
    """The positive control of the declaration from the store side: the row
    is really replaced -- the whole read's family moves -- and the served
    answer neither moves nor stops being served."""
    name, perturb = UNREAD_ROW_PERTURBATIONS[family]
    population = populations[name]
    link = population.record.execution.run_snapshot_link
    assert link is not None
    entry = next(item for item in store_module._FAMILIES if item.family == family)
    assert family not in {item.family for item in RUN_SUMMARY_FAMILIES}
    before = population.answer(serve_from="run_store")
    with RunStore(population.store_path, create=False) as store:
        untouched = len(store.read_family(link.store_run_id, entry))  # type: ignore[arg-type]
    with store_row_replaced(perturb):
        after = population.answer(serve_from="run_store")
        with RunStore(population.store_path, create=False) as store:
            whole = store.read_run(link.store_run_id)
    assert untouched >= 1
    replaced = len(_MODEL_ACCESSORS[family](whole))
    assert replaced == untouched - 1, "the replacement did not reach the whole read"
    assert before == after
    assert after["serving"] == {
        "source": "run_store",
        "reason": "served",
        "store_run_id": link.store_run_id,
    }


def _tampered_copy(run: _Stored, tmp_path: Path, family: str) -> Path:
    copy = tmp_path / f"{run.name}-{family}.sqlite3"
    shutil.copy(run.path, copy)
    with sqlite3.connect(copy) as raw:
        raw.execute(
            "UPDATE objects SET payload = ? WHERE object_pk = "
            "(SELECT MIN(o.object_pk) FROM objects o "
            "JOIN families f ON f.family_pk = o.family_pk WHERE f.family = ?)",
            (b'{"tampered": true}', family),
        )
    raw.close()
    return copy


def test_a_corrupt_member_outside_the_declaration_is_never_read(
    stored: list[_Stored], tmp_path: Path
) -> None:
    """On a copy of a published store: a corrupted member of an undeclared
    family is invisible to the summary reading -- which still answers the
    whole read's summary -- while the whole read refuses the run; the same
    corruption in a declared family is refused by the summary reading."""
    run = next(item for item in stored if item.name == "trusted")
    with RunStore(run.path, create=False) as store:
        expected = read_served_run_summary(store, run.run_id)
    undeclared = _tampered_copy(run, tmp_path, "unit_span")
    with RunStore(undeclared, create=False) as store:
        assert read_served_run_summary(store, run.run_id) == expected
        with pytest.raises(StoreIntegrityError, match="content address"):
            store.read_run(run.run_id)
    declared = _tampered_copy(run, tmp_path, "dead_symbol_group")
    with (
        RunStore(declared, create=False) as store,
        pytest.raises(StoreIntegrityError, match="content address"),
    ):
        read_served_run_summary(store, run.run_id)


@pytest.fixture
def asked(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Every family a reading asks ``RunStore.read_family`` for."""
    seen: list[str] = []
    original = RunStore.read_family

    def _asking(self: RunStore, run_id: str, family: object) -> object:
        seen.append(family.family)  # type: ignore[attr-defined]
        return original(self, run_id, family)  # type: ignore[arg-type]

    monkeypatch.setattr(RunStore, "read_family", _asking)
    yield seen


def test_the_family_readings_ask_for_exactly_their_declarations(
    stored: list[_Stored], asked: list[str]
) -> None:
    """The slices and the authority candidates read family by family; each
    declaration is what the reading asks the store for, no more, no less."""
    run = next(item for item in stored if item.name == "projection_corpus")
    with RunStore(run.path, create=False) as store:
        read_served_run_slices(store, run.run_id, root=run.path.parent)
        slices = sorted(set(asked))
        asked.clear()
        read_served_authority_candidates(store, run.run_id)
        candidates = sorted(set(asked))
    assert slices == sorted(entry.family for entry in SERVED_SLICE_FAMILIES)
    assert candidates == sorted(
        entry.family for entry in SERVED_AUTHORITY_CANDIDATE_FAMILIES
    )
