# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The production triage's reading declares its families, and reads exactly
those (consumer migration C2).

The triage is read with ``read_named_families`` over ``TRIAGE_FAMILIES`` --
the run summary's families, whose arrangement it reads for the blocks the
two share, and the two evaluation families its verdicts and selections are
rows of -- under the run summary's conditions.  Proven in both directions
on the triage populations (``tests/_triage_serving.py``), per branch of each
condition, the way the run summary's declaration is
(``tests/test_run_summary_declared_families.py``, whose instruments are
reused here):

* complete: the bounded triage never refuses, and it equals the triage of
  the whole read on every population;
* not excessive: every family declared on every run, declared away, refuses
  on some population, naming exactly it; every family a condition reads,
  taken out of its condition, refuses on some population that meets the
  condition and on none that does not;
* exact: on every population the reading scans exactly the families
  declared for it, and decodes nothing outside them.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from codeclone.canonical import store as store_module
from codeclone.canonical.serving import (
    RUN_SUMMARY_FAMILIES,
    RUN_SUMMARY_READ_WHEN,
    TRIAGE_FAMILIES,
    TRIAGE_READ_WHEN,
    read_served_triage,
    triage_from_model,
)
from codeclone.canonical.store import (
    FAMILY_FINDING_EVALUATION,
    FAMILY_HOTLIST_SELECTION,
    RunStore,
    UnreadFamilyError,
    read_named_families,
)
from tests._triage_serving import (
    TRIAGE_POPULATIONS,
    TriagePopulations,
    shared_triage_populations,
)
from tests.test_run_store_named_family_read import decoded
from tests.test_run_summary_declared_families import (
    _Stored,
    condition_branches,
    declaration_is_well_formed,
    families_declared_for,
    reads_only_its_declared_families,
    scanned,
    without,
)

__all__ = ["decoded", "scanned"]


@pytest.fixture(scope="module")
def populations(tmp_path_factory: pytest.TempPathFactory) -> TriagePopulations:
    return shared_triage_populations(tmp_path_factory)


@pytest.fixture(scope="module")
def stored(populations: TriagePopulations) -> list[_Stored]:
    """Every triage population's store and the run its execution published."""
    runs: list[_Stored] = []
    for name in TRIAGE_POPULATIONS:
        population = populations[name]
        link = population.record.execution.run_snapshot_link
        assert link is not None and link.store_run_id
        runs.append(_Stored(name, population.store_path, link.store_run_id))
    return runs


def test_the_declaration_names_each_registry_family_once() -> None:
    declaration_is_well_formed(TRIAGE_FAMILIES, TRIAGE_READ_WHEN)


def test_the_triage_reads_the_summarys_families_and_its_two_evaluation_rows() -> None:
    """The declaration's composition, as the module states it: the run
    summary's families and conditions, and the two evaluation families."""
    assert {entry.family for entry in TRIAGE_FAMILIES} == {
        *(entry.family for entry in RUN_SUMMARY_FAMILIES),
        FAMILY_FINDING_EVALUATION.family,
        FAMILY_HOTLIST_SELECTION.family,
    }
    assert TRIAGE_READ_WHEN == RUN_SUMMARY_READ_WHEN


def test_each_condition_is_met_and_missed_by_the_population(
    stored: list[_Stored],
) -> None:
    for decider, (held, empty) in condition_branches(TRIAGE_READ_WHEN, stored).items():
        assert held and empty, (decider, held, empty)


def test_the_bounded_triage_is_the_whole_reads_on_every_population(
    stored: list[_Stored],
) -> None:
    for run in stored:
        with RunStore(run.path, create=False) as store:
            whole = triage_from_model(store.read_run(run.run_id), run_id=run.run_id)
            bounded = read_served_triage(store, run.run_id)
        assert bounded == whole, run.name


def _refusers(
    stored: list[_Stored],
    family: str,
    read: Callable[[RunStore, str], object],
) -> list[str]:
    refusers: list[str] = []
    for run in stored:
        with RunStore(run.path, create=False) as store:
            model = read(store, run.run_id)
        try:
            triage_from_model(model, run_id=run.run_id)  # type: ignore[arg-type]
        except UnreadFamilyError as refusal:
            assert refusal.family == family
            refusers.append(run.name)
    return refusers


@pytest.mark.parametrize("declared", TRIAGE_FAMILIES, ids=lambda entry: entry.family)
def test_no_declared_family_can_be_declared_away(
    stored: list[_Stored], declared: store_module._FamilyEntry
) -> None:
    rest = [entry for entry in TRIAGE_FAMILIES if entry is not declared]
    conditions = without(TRIAGE_READ_WHEN, declared.family)
    refusers = _refusers(
        stored,
        declared.family,
        lambda store, run_id: read_named_families(
            store, run_id, rest, read_when=conditions
        ),
    )
    assert refusers, f"{declared.family} is declared and read by no population"


@pytest.mark.parametrize(
    "conditional",
    [entry for when in TRIAGE_READ_WHEN for entry in when.families],
    ids=lambda entry: entry.family,
)
def test_each_conditional_family_is_needed_exactly_when_its_condition_holds(
    stored: list[_Stored], conditional: store_module._FamilyEntry
) -> None:
    (when,) = [item for item in TRIAGE_READ_WHEN if conditional in item.families]
    held, _empty = condition_branches((when,), stored)[when.decider.family]
    conditions = without(TRIAGE_READ_WHEN, conditional.family)
    refusers = _refusers(
        stored,
        conditional.family,
        lambda store, run_id: read_named_families(
            store, run_id, TRIAGE_FAMILIES, read_when=conditions
        ),
    )
    assert refusers, f"{conditional.family} is read by no population"
    assert set(refusers) <= set(held), sorted(set(refusers) - set(held))


def test_the_triage_reading_scans_exactly_its_declared_families_per_run(
    stored: list[_Stored], scanned: list[str]
) -> None:
    for run in stored:
        with RunStore(run.path, create=False) as store:
            expected = families_declared_for(
                TRIAGE_FAMILIES, TRIAGE_READ_WHEN, store, run.run_id
            )
            scanned.clear()
            read_served_triage(store, run.run_id)
        assert sorted(scanned) == sorted(expected), run.name


def test_the_triage_reading_decodes_only_its_declared_families(
    stored: list[_Stored], decoded: list[str]
) -> None:
    run = next(item for item in stored if item.name == "trusted")
    reads_only_its_declared_families(
        run, read_served_triage, (TRIAGE_FAMILIES, TRIAGE_READ_WHEN), decoded
    )
