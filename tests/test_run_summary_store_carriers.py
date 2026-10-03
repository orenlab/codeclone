# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Each store-carried field of the run summary is READ from its store row.

Consumer migration C1, the carriers.  The served answer of an agree-gated
edge is the memory's bytes by construction, so equality alone cannot tell a
field the edge reads from the store from a field it quietly keeps from
memory -- both agree.  What tells them apart is a store that says something
else: here one stored row (or record) is replaced on its way out of the
store, the execution's memory untouched, and the field that row carries
must move -- the answer turns ``divergent`` and names it.  A carrier branch
that read memory instead would leave the answer ``served``.

One perturbation per carrier (``STORE_ROW_PERTURBATIONS`` in
``tests/_run_summary_serving.py``), each its own named case, so every
carrier branch of ``store_summary_payload`` and of
``canonical.serving.run_summary_from_model`` has a pin that dies with it.
"""

from __future__ import annotations

import pytest

from codeclone.api.run_store_serving import SERVE_FROM_RUN_STORE
from codeclone.utils.coerce import as_mapping
from tests._run_summary_serving import (
    STORE_ROW_PERTURBATIONS,
    SummaryPopulations,
    shared_populations,
    store_row_replaced,
)


@pytest.fixture(scope="module")
def populations(tmp_path_factory: pytest.TempPathFactory) -> SummaryPopulations:
    return shared_populations(tmp_path_factory)


def _diverging(detail: object) -> set[str]:
    text = str(detail)
    assert text.startswith("diverging: "), text
    return set(text.removeprefix("diverging: ").split(", "))


@pytest.mark.parametrize("carrier", list(STORE_ROW_PERTURBATIONS))
def test_a_replaced_store_row_moves_the_field_it_carries(
    populations: SummaryPopulations, carrier: str
) -> None:
    name, perturb, fields = STORE_ROW_PERTURBATIONS[carrier]
    population = populations[name]
    untouched = as_mapping(
        population.answer(serve_from=SERVE_FROM_RUN_STORE)["serving"]
    )
    assert untouched["reason"] == "served", untouched
    with store_row_replaced(perturb):
        answer = population.answer(serve_from=SERVE_FROM_RUN_STORE)
    serving = as_mapping(answer.pop("serving"))
    assert serving["source"] == "memory"
    assert serving["reason"] == "divergent"
    assert set(fields) <= _diverging(serving["detail"]), serving["detail"]
    assert answer == population.memory_answer()
