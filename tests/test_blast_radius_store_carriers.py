# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Each store-carried fact of the blast radius is READ from its store row.

Consumer migration C7, the carriers.  The served answer of an agree-gated
edge is the memory's bytes by construction, so equality alone cannot tell a
field the edge computes from the store from one it quietly keeps from memory
-- both agree.  What tells them apart is a store that says something else:
one stored row is replaced on its way out of the store, the execution's
memory untouched, and the field that row carries must move -- the answer
turns ``divergent`` and names it, and the values stay memory's.  A carrier
branch that read memory instead would leave the answer ``served``.

One perturbation per carrier (``STORE_ROW_CARRIERS`` in
``tests/_blast_radius_serving.py``), each its own named case, so every
carrier branch of ``canonical.blast_radius_projection`` has a pin that dies
with it.  The dependency row case is the brief's own: a replaced import edge
must change the dependents list.
"""

from __future__ import annotations

import pytest

import codeclone.surfaces.mcp._run_store_serving as serving_mod
from codeclone.api.run_store_serving import SERVE_FROM_RUN_STORE
from codeclone.surfaces.mcp._blast_radius import BlastRadiusResult
from codeclone.utils.coerce import as_mapping
from tests._blast_radius_serving import (
    STORE_ROW_CARRIERS,
    BlastPopulations,
    blast_answer,
    carrier_answer,
    forget_answers,
    shared_blast_populations,
)


@pytest.fixture(scope="module")
def populations(tmp_path_factory: pytest.TempPathFactory) -> BlastPopulations:
    return shared_blast_populations(tmp_path_factory)


def _diverging(detail: object) -> set[str]:
    text = str(detail)
    assert text.startswith("diverging: "), text
    return set(text.removeprefix("diverging: ").split(", "))


@pytest.mark.parametrize("carrier", list(STORE_ROW_CARRIERS))
def test_a_replaced_store_row_moves_the_field_it_carries(
    populations: BlastPopulations, carrier: str
) -> None:
    case = STORE_ROW_CARRIERS[carrier]
    population = populations[case.population]
    forget_answers(population)
    untouched = blast_answer(population, case.request, serve_from=SERVE_FROM_RUN_STORE)
    assert as_mapping(untouched.pop("serving"))["reason"] == "served"
    answer = carrier_answer(population, case)
    serving = as_mapping(answer.pop("serving"))
    assert serving["source"] == "memory"
    assert serving["reason"] == "divergent"
    assert set(case.fields) <= _diverging(serving["detail"]), serving["detail"]
    assert answer == untouched


def test_the_dependency_row_moves_exactly_the_dependents(
    populations: BlastPopulations, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The edge ``pkg.user_0 -> pkg.core`` stored as ``pkg.top -> pkg.core``:
    the store's own radius names ``pkg/top.py`` where memory names
    ``pkg/user_0.py``, and the edge serves memory's list."""
    compared: list[tuple[object, object]] = []
    real = serving_mod._blast_radius_agrees

    def _recording(stored: BlastRadiusResult, memory: BlastRadiusResult) -> bool:
        compared.append((stored.direct_dependents, memory.direct_dependents))
        return real(stored, memory)

    monkeypatch.setattr(serving_mod, "_blast_radius_agrees", _recording)
    case = STORE_ROW_CARRIERS["dependency_relation"]
    answer = carrier_answer(populations[case.population], case)
    ((stored, memory),) = compared
    assert isinstance(stored, tuple) and isinstance(memory, tuple)
    assert set(stored) ^ set(memory) == {"pkg/top.py", "pkg/user_0.py"}
    assert "pkg/top.py" in stored and "pkg/user_0.py" in memory
    assert answer["direct_dependents"] == list(memory)
