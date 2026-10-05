# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The patch-contract reading declares its families, and reads exactly those.

``read_served_patch_run`` reads ``PATCH_CONTRACT_FAMILIES`` and the
condition of ``PATCH_CONTRACT_READ_WHEN`` with ``read_named_families``:
every family outside the declaration is a typed absence.  The declaration
is held in both directions (consumer migration C6), per branch of its
condition, on every run of the patch-contract battery and the sixteen
served populations of the run summary --

* complete: the bounded reading never refuses and equals the reading of
  the whole run, fact for fact, on runs that meet the condition and runs
  that do not;
* not excessive: every unconditional family, declared away, refuses on some
  run; the authority graph, taken out of its condition, refuses on some run
  that holds a violation row and on none that does not;
* exact: every run scans exactly the families declared for it.

The positive controls close it from the store side: the reading decodes
declared families only, and a corrupted member of an undeclared family is
never read while the whole read refuses it.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from codeclone.canonical import store as store_module
from codeclone.canonical.errors import StoreIntegrityError
from codeclone.canonical.serving import (
    PATCH_CONTRACT_FAMILIES,
    PATCH_CONTRACT_READ_WHEN,
    patch_run_from_model,
    read_served_patch_run,
)
from codeclone.canonical.store import RunStore, UnreadFamilyError, read_named_families
from codeclone.report.gates.evaluator import GateState
from tests._patch_contract_serving import (
    CYCLE_BUILDERS,
    document_gate_state,
    document_lane_trust,
    document_metric_items,
    shared_cycles,
)
from tests._run_summary_serving import SUMMARY_POPULATIONS, shared_populations
from tests.test_run_store_named_family_read import decoded
from tests.test_run_summary_declared_families import (
    _Stored,
    _tampered_copy,
    condition_branches,
    declaration_is_well_formed,
    families_declared_for,
    scanned,
    without,
)

__all__ = ["decoded", "scanned"]


@dataclass(frozen=True, slots=True)
class _GateInputs:
    name: str
    document: dict[str, object]
    stored: dict[str, object]
    document_lanes: tuple[dict[str, str], tuple[str, ...]]
    stored_lanes: tuple[dict[str, str], tuple[str, ...]]
    document_items: dict[str, dict[tuple[str, str], int]]
    stored_items: dict[str, dict[tuple[str, str], int]]


@pytest.fixture(scope="module")
def gate_inputs(tmp_path_factory: pytest.TempPathFactory) -> list[_GateInputs]:
    """Every run's gate inputs twice: as the document reader builds them for
    the record, and as the store's rows state them."""
    executions = []
    cycles = shared_cycles(tmp_path_factory)
    for name in CYCLE_BUILDERS:
        cycle = cycles[name]
        for side, record in (("before", cycle.before), ("after", cycle.after)):
            if record is not None:
                executions.append((f"{name}.{side}", cycle.store_path, record))
    populations = shared_populations(tmp_path_factory)
    for name in SUMMARY_POPULATIONS:
        population = populations[name]
        executions.append((name, population.store_path, population.record))
    inputs: list[_GateInputs] = []
    for name, path, record in executions:
        link = record.execution.run_snapshot_link
        assert link is not None and link.store_run_id
        with RunStore(path, create=False) as store:
            served = read_served_patch_run(store, link.store_run_id)
        inputs.append(
            _GateInputs(
                name=name,
                document=document_gate_state(record),
                stored=dataclasses.asdict(served.gate_state),
                document_lanes=(
                    document_lane_trust(record),
                    tuple(record.served_report.contract.enabled_lanes),
                ),
                stored_lanes=(dict(served.lane_trust), served.enabled_lanes),
                document_items=document_metric_items(record),
                stored_items={
                    family: dict(items) for family, items in served.metric_items.items()
                },
            )
        )
    return inputs


#: The runs whose stored gate input disagrees with the document's, by term:
#: the run summary's declared disagreements (desk 2026-09-27) reaching the
#: gate's record.  On each the memory's metrics diff counts what the store,
#: whose comparison of that lane did not run, states as no delta.
DECLARED_GATE_DISAGREEMENTS: dict[str, frozenset[str]] = {
    "api_breaking_changes": frozenset(
        {
            "api_disabled",
            "partial",
            "api_lane_off.before",
            "api_lane_off.after",
            "truncated_api.before",
            "truncated_api.after",
        }
    ),
    "diff_new_dead_code": frozenset({"older_schema_dead_code_lane"}),
}
#: Terms no run of the population moves off one value: held equal, and named
#: so the population's blind spot is on the record, not assumed away.
CONSTANT_GATE_TERMS: frozenset[str] = frozenset({"files_skipped"})


@pytest.mark.parametrize(
    "term", [field.name for field in dataclasses.fields(GateState)]
)
def test_each_stored_gate_input_is_the_documents_on_every_run(
    gate_inputs: list[_GateInputs], term: str
) -> None:
    """Per term of the gate's record: the stored value is the document's on
    every run but the declared ones, and the population distinguishes it."""
    disagreeing = {
        inputs.name
        for inputs in gate_inputs
        if inputs.document[term] != inputs.stored[term]
    }
    assert disagreeing == DECLARED_GATE_DISAGREEMENTS.get(term, frozenset())
    values = {json.dumps(inputs.document[term]) for inputs in gate_inputs}
    if term in CONSTANT_GATE_TERMS:
        assert len(values) == 1
    else:
        assert len(values) >= 2, (term, values)


def test_the_stored_lanes_are_the_documents_on_every_run(
    gate_inputs: list[_GateInputs],
) -> None:
    """Lane trust and the enabled lanes (one trust row per enabled lane, by
    construction of the document's baseline section) on every run."""
    assert [inputs.stored_lanes for inputs in gate_inputs] == [
        inputs.document_lanes for inputs in gate_inputs
    ]
    statuses = {
        status for inputs in gate_inputs for status in inputs.stored_lanes[0].values()
    }
    assert {"trusted", "unavailable"} <= statuses


@pytest.mark.parametrize("family", ["complexity", "coupling", "cohesion"])
def test_each_stored_metric_index_is_the_documents_on_every_run(
    gate_inputs: list[_GateInputs], family: str
) -> None:
    """``worsened`` per family: the stored per-symbol index -- a measured
    class without a row of the dimension is its measured zero -- is the
    document's on every run.  The population holds a zero coupling to read;
    cohesion has none to hold (a measured class has one component at least,
    so the zero rule is vacuous there by definition)."""
    assert [inputs.stored_items[family] for inputs in gate_inputs] == [
        inputs.document_items[family] for inputs in gate_inputs
    ]
    assert any(inputs.document_items[family] for inputs in gate_inputs)
    zeros = any(0 in inputs.document_items[family].values() for inputs in gate_inputs)
    assert zeros is (family == "coupling")


@pytest.fixture(scope="module")
def stored(tmp_path_factory: pytest.TempPathFactory) -> list[_Stored]:
    """Every run the battery published, and every served population's."""
    runs: list[_Stored] = []
    cycles = shared_cycles(tmp_path_factory)
    for name in CYCLE_BUILDERS:
        cycle = cycles[name]
        for side, record in (("before", cycle.before), ("after", cycle.after)):
            link = None if record is None else record.execution.run_snapshot_link
            if link is not None and link.store_run_id:
                runs.append(
                    _Stored(f"{name}.{side}", cycle.store_path, link.store_run_id)
                )
    populations = shared_populations(tmp_path_factory)
    for name in SUMMARY_POPULATIONS:
        population = populations[name]
        link = population.record.execution.run_snapshot_link
        assert link is not None and link.store_run_id
        runs.append(_Stored(name, population.store_path, link.store_run_id))
    return runs


def test_the_population_is_every_battery_run_and_every_served_one(
    stored: list[_Stored],
) -> None:
    """The accounting: 31 battery runs (one cycle analyses once) and the
    sixteen populations, all published.  One pair shares a store run: the
    contract-B cycle analyses the same bytes twice (measured; the invariant
    cycle's comment edit moves the scope receipt, so it is two)."""
    assert len(stored) == 47
    by_address: dict[tuple[Path, str], list[str]] = {}
    for run in stored:
        by_address.setdefault((run.path, run.run_id), []).append(run.name)
    shared = [names for names in by_address.values() if len(names) > 1]
    assert shared == [["predates.before", "predates.after"]]


def test_the_declaration_names_each_registry_family_once() -> None:
    declaration_is_well_formed(PATCH_CONTRACT_FAMILIES, PATCH_CONTRACT_READ_WHEN)


def test_each_condition_is_met_and_missed_by_the_population(
    stored: list[_Stored],
) -> None:
    for decider, (held, empty) in condition_branches(
        PATCH_CONTRACT_READ_WHEN, stored
    ).items():
        assert held and empty, (decider, held, empty)


def test_the_bounded_reading_is_the_whole_reads_on_every_run(
    stored: list[_Stored],
) -> None:
    for run in stored:
        with RunStore(run.path, create=False) as store:
            whole = patch_run_from_model(store.read_run(run.run_id), run_id=run.run_id)
            bounded = read_served_patch_run(store, run.run_id)
        assert bounded == whole, run.name


@pytest.mark.parametrize(
    "declared", PATCH_CONTRACT_FAMILIES, ids=lambda entry: entry.family
)
def test_no_declared_family_can_be_declared_away(
    stored: list[_Stored], declared: store_module._FamilyEntry
) -> None:
    rest = [entry for entry in PATCH_CONTRACT_FAMILIES if entry is not declared]
    conditions = without(PATCH_CONTRACT_READ_WHEN, declared.family)
    refusers: list[str] = []
    for run in stored:
        with RunStore(run.path, create=False) as store:
            model = read_named_families(store, run.run_id, rest, read_when=conditions)
        try:
            patch_run_from_model(model, run_id=run.run_id)
        except UnreadFamilyError as refusal:
            assert declared.family in str(refusal)
            refusers.append(run.name)
    assert refusers, f"{declared.family} is declared and read by no run"


@pytest.mark.parametrize(
    "conditional",
    [entry for when in PATCH_CONTRACT_READ_WHEN for entry in when.families],
    ids=lambda entry: entry.family,
)
def test_each_conditional_family_is_needed_exactly_when_its_condition_holds(
    stored: list[_Stored], conditional: store_module._FamilyEntry
) -> None:
    (when,) = [
        item for item in PATCH_CONTRACT_READ_WHEN if conditional in item.families
    ]
    held, _empty = condition_branches((when,), stored)[when.decider.family]
    conditions = without(PATCH_CONTRACT_READ_WHEN, conditional.family)
    refusers: list[str] = []
    for run in stored:
        with RunStore(run.path, create=False) as store:
            model = read_named_families(
                store, run.run_id, PATCH_CONTRACT_FAMILIES, read_when=conditions
            )
        try:
            patch_run_from_model(model, run_id=run.run_id)
        except UnreadFamilyError as refusal:
            assert refusal.family == conditional.family
            refusers.append(run.name)
    assert refusers, f"{conditional.family} is read by no run"
    assert set(refusers) <= set(held), sorted(set(refusers) - set(held))


def test_the_reading_scans_exactly_its_declared_families_per_run(
    stored: list[_Stored], scanned: list[str]
) -> None:
    for run in stored:
        with RunStore(run.path, create=False) as store:
            expected = families_declared_for(
                PATCH_CONTRACT_FAMILIES, PATCH_CONTRACT_READ_WHEN, store, run.run_id
            )
            scanned.clear()
            read_served_patch_run(store, run.run_id)
        assert sorted(scanned) == sorted(expected), run.name


def test_the_reading_decodes_only_its_declared_families(
    stored: list[_Stored], decoded: list[str]
) -> None:
    run = next(item for item in stored if item.name == "gate_caused.after")
    with RunStore(run.path, create=False) as store:
        read_served_patch_run(store, run.run_id)
        bounded = list(decoded)
        decoded.clear()
        store.read_run(run.run_id)
        declared = families_declared_for(
            PATCH_CONTRACT_FAMILIES, PATCH_CONTRACT_READ_WHEN, store, run.run_id
        )
    assert bounded and set(bounded) <= declared
    assert len(decoded) > len(bounded)


def test_a_corrupt_member_outside_the_declaration_is_never_read(
    stored: list[_Stored], tmp_path: Path
) -> None:
    run = next(item for item in stored if item.name == "trusted")
    with RunStore(run.path, create=False) as store:
        expected = read_served_patch_run(store, run.run_id)
    undeclared = _tampered_copy(run, tmp_path, "unit_span")
    with RunStore(undeclared, create=False) as store:
        assert read_served_patch_run(store, run.run_id) == expected
        with pytest.raises(StoreIntegrityError, match="content address"):
            store.read_run(run.run_id)
    declared = _tampered_copy(run, tmp_path, "risk_observation")
    with (
        RunStore(declared, create=False) as store,
        pytest.raises(StoreIntegrityError, match="content address"),
    ):
        read_served_patch_run(store, run.run_id)
