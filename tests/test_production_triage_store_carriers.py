# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Each store-carried field of the production triage is READ from its rows
(consumer migration C2, the carriers).

The served answer of an agree-gated edge is the memory's bytes by
construction, so equality alone cannot tell a field the edge reads from the
store from one it quietly keeps from memory.  What tells them apart is a
store that says something else: rows of one run are replaced on their way
out of the store (``tests/_run_summary_serving.store_row_replaced``), the
execution's memory untouched, within the laws of the model -- gapless
ranks, a priority some effort prices -- and the fields those rows carry must
move in the store's answer, which the tool then refuses to serve
(``divergent``, the block named).  Rows that name a finding the store no
longer expresses are refused typed (``unexpressible``), and rows the triage
shows nothing of move nothing.
"""

from __future__ import annotations

import pytest

from codeclone.api.run_store_serving import SERVE_FROM_RUN_STORE
from codeclone.canonical.store import RunStore
from codeclone.utils.coerce import as_mapping
from tests._run_summary_serving import store_row_replaced
from tests._triage_serving import (
    TRIAGE_REFUSING_PERTURBATIONS,
    TRIAGE_ROW_PERTURBATIONS,
    TRIAGE_UNMOVED_PERTURBATIONS,
    TriagePopulations,
    answer_at,
    memory_triage,
    shared_triage_populations,
    triage_answer,
    triage_pair,
    without_serving,
)

#: The limit every carrier is asked under: every card and suggestion shown.
_SHOWN = 10


@pytest.fixture(scope="module")
def populations(tmp_path_factory: pytest.TempPathFactory) -> TriagePopulations:
    return shared_triage_populations(tmp_path_factory)


def _named(path: str) -> str:
    """The name a divergence gives the block a path lies in: the top-level
    key and the key under it, without a list position."""
    return ".".join(part.partition("[")[0] for part in path.split(".")[:2])


def _diverging(detail: object) -> set[str]:
    text = str(detail)
    assert text.startswith("diverging: "), text
    return set(text.removeprefix("diverging: ").split(", "))


@pytest.mark.parametrize("carrier", list(TRIAGE_ROW_PERTURBATIONS))
def test_a_replaced_store_row_moves_the_field_it_carries(
    populations: TriagePopulations, carrier: str
) -> None:
    name, perturb, paths = TRIAGE_ROW_PERTURBATIONS[carrier]
    population = populations[name]
    memory, untouched = triage_pair(population, limit=_SHOWN)
    assert [answer_at(untouched, path) for path in paths] == [
        answer_at(memory, path) for path in paths
    ], "the store's answer disagrees before any row is replaced"
    with store_row_replaced(perturb):
        _memory, moved = triage_pair(population, limit=_SHOWN)
        answer = triage_answer(
            population,
            serve_from=SERVE_FROM_RUN_STORE,
            max_hotspots=_SHOWN,
            max_suggestions=_SHOWN,
        )
    still = [
        path for path in paths if answer_at(moved, path) == answer_at(memory, path)
    ]
    assert still == [], f"{carrier}: the store's answer kept memory's value"
    serving = as_mapping(answer.pop("serving"))
    assert (serving["source"], serving["reason"]) == ("memory", "divergent")
    assert {_named(path) for path in paths} <= _diverging(serving["detail"])
    assert answer == memory_triage(
        population, max_hotspots=_SHOWN, max_suggestions=_SHOWN
    )


@pytest.mark.parametrize("carrier", list(TRIAGE_REFUSING_PERTURBATIONS))
def test_a_selected_finding_the_store_no_longer_states_is_refused(
    populations: TriagePopulations, carrier: str
) -> None:
    name, perturb, fragment = TRIAGE_REFUSING_PERTURBATIONS[carrier]
    population = populations[name]
    with store_row_replaced(perturb):
        answer = triage_answer(population, serve_from=SERVE_FROM_RUN_STORE)
    serving = as_mapping(answer.pop("serving"))
    assert (serving["source"], serving["reason"]) == ("memory", "unexpressible")
    assert fragment in str(serving["detail"]), serving["detail"]
    assert answer == memory_triage(population)


@pytest.mark.parametrize("perturbation", list(TRIAGE_UNMOVED_PERTURBATIONS))
def test_a_row_the_triage_shows_nothing_of_moves_nothing(
    populations: TriagePopulations, perturbation: str
) -> None:
    """The positive control of the carriers from the other side: the row is
    really replaced -- the whole read's run is not the run it was -- and the
    served answer neither moves nor stops being served."""
    name, perturb = TRIAGE_UNMOVED_PERTURBATIONS[perturbation]
    population = populations[name]
    link = population.record.execution.run_snapshot_link
    assert link is not None
    before = triage_answer(population, serve_from=SERVE_FROM_RUN_STORE)
    with RunStore(population.store_path, create=False) as store:
        untouched = store.read_run(link.store_run_id)
    with store_row_replaced(perturb):
        after = triage_answer(population, serve_from=SERVE_FROM_RUN_STORE)
        with RunStore(population.store_path, create=False) as store:
            replaced = store.read_run(link.store_run_id)
    assert replaced != untouched, "the replacement did not reach the store's read"
    assert after == before
    assert as_mapping(after["serving"])["reason"] == "served"
    assert without_serving(after) == memory_triage(population)
