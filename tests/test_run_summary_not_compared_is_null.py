# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Not compared -> null: the nine comparison fields of ``get_run_summary``.

The maintainer's ruling (2026-10-03): ``0`` means a measured comparison
result equal to zero; if no comparison happened, ``0`` is a false
statement.  The eight terms of ``diff`` and ``health.delta`` therefore state
a number ONLY when their comparison ran, and ``null`` otherwise -- and the
rule holds identically for the answer built from memory and the answer
built from the run store.

The state table below is the specification, one cell per (population,
field): the number the comparison measured, ``None`` where the comparison
did not run, or ``ABSENT`` where the block states no verdict at all (a
clones-only run's ``health``).  Every cell is its own test, and every test
holds three answers to the cell: the memory road of the tool, the store's
own projection of the run, and the tool's store-backed answer.

The populations are the live MCP executions of
``tests/_run_summary_serving.py``; the accounting test proves before
anything is counted that the table distinguishes (Probe Validity Law):
every field takes both a number and ``null``, and the comparisons that ran
and measured zero are present for every field but the health score's (no
live population compares a health score equal to its baseline's; the owner
pin ``tests/test_canonical_summary_comparison_rule.py`` holds that cell).
"""

from __future__ import annotations

import json
from collections.abc import Mapping

import pytest

from codeclone.api.run_store_serving import SERVE_FROM_MEMORY, SERVE_FROM_RUN_STORE
from tests._run_summary_serving import (
    RUN_SUMMARY_POPULATIONS,
    SummaryPopulations,
    shared_populations,
    stored_blocks,
)

#: A field the answer does not carry: the block states no verdict.
ABSENT = "<absent>"

#: The nine comparison fields, as (block, key), in the answer's order.
FIELDS: tuple[tuple[str, str], ...] = (
    ("diff", "new_clones"),
    ("diff", "health_delta"),
    ("diff", "typing_param_permille_delta"),
    ("diff", "typing_return_permille_delta"),
    ("diff", "docstring_permille_delta"),
    ("diff", "api_breaking_changes"),
    ("diff", "api_signature_changes"),
    ("diff", "new_api_symbols"),
    ("health", "delta"),
)

_Cell = int | str | None
_NONE9: tuple[_Cell, ...] = (None,) * 9
#: Stage B against the stage-A baseline, every comparison run.
_TRUSTED: tuple[_Cell, ...] = (2, 2, -97, -43, 16, 2, 1, 38, 2)
#: The same run with the API comparison not made (lane untrusted, lane not
#: enabled, or a partial population whose universe was not observed).
_NO_API: tuple[_Cell, ...] = (2, 2, -97, -43, 16, None, None, None, 2)
#: A clones-only run: only the clone comparison runs, and ``health`` states
#: no verdict.
_CLONES_ONLY: tuple[_Cell, ...] = (2, *(None,) * 7, ABSENT)

#: The state table: population -> the nine cells, in ``FIELDS`` order.
#: Columns of the ruling's table: no baseline (``no_baseline`` and the other
#: bare trees); a trusted baseline (``trusted``, ``trusted_unchanged``); a
#: carrier lane untrusted or recorded under an older schema
#: (``older_schema_*``, ``foreign_scope``); a capability the run did not
#: enable (``api_disabled``); a truncated run (``partial``); clones-only;
#: a withheld health verdict under a trusted baseline (``trusted_unmeasured``,
#: ``trusted_complete_empty``).
STATE_TABLE: dict[str, tuple[_Cell, ...]] = {
    "no_baseline": _NONE9,
    "projection_corpus": _NONE9,
    "trusted": _TRUSTED,
    "foreign_scope": _NONE9,
    # The dead-code lane feeds health: the health comparison is withheld,
    # every other comparison runs.
    "older_schema_dead_code_lane": (2, None, -97, -43, 16, 2, 1, 38, None),
    "older_schema_api_lane": _NO_API,
    "api_disabled": _NO_API,
    "partial": _NO_API,
    "gated": (3, -1, -88, -37, 14, 2, 1, 47, -1),
    "clones_only": _CLONES_ONLY,
    "complete_empty": _NONE9,
    "unmeasured": _NONE9,
    "coverage_ok": _TRUSTED,
    "coverage_invalid": _TRUSTED,
    "warm_rerun": _NONE9,
    "clones_only_warm": _CLONES_ONLY,
    # Every comparison runs and every result but the health score's is a
    # measured zero.
    "trusted_unchanged": (0, 9, 0, 0, 0, 0, 0, 0, 9),
    # Nothing was read: the clone comparison runs (and finds nothing new),
    # the adoption and API comparisons are not made, health is withheld.
    "trusted_unmeasured": (0, *(None,) * 7, None),
    # Nothing to read: health is withheld and adoption not compared, while
    # the API comparison runs over an observed empty universe and measures
    # every baseline symbol removed.
    "trusted_complete_empty": (0, None, None, None, None, 29, 0, 0, None),
}


@pytest.fixture(scope="module")
def populations(tmp_path_factory: pytest.TempPathFactory) -> SummaryPopulations:
    return shared_populations(tmp_path_factory)


def _cell(answer: Mapping[str, object], block: str, key: str) -> _Cell:
    container = answer.get(block)
    assert isinstance(container, Mapping), (block, answer)
    if key not in container:
        return ABSENT
    value = container[key]
    assert value is None or (isinstance(value, int) and not isinstance(value, bool))
    return value


def _cases() -> list[tuple[str, str, str]]:
    return [(name, block, key) for name in STATE_TABLE for block, key in FIELDS]


def test_the_table_covers_every_population_and_field() -> None:
    assert list(STATE_TABLE) == list(RUN_SUMMARY_POPULATIONS)
    assert all(len(cells) == len(FIELDS) for cells in STATE_TABLE.values())


@pytest.mark.parametrize(("name", "block", "key"), _cases())
def test_a_comparison_field_states_a_number_only_when_it_was_compared(
    populations: SummaryPopulations, name: str, block: str, key: str
) -> None:
    """One cell of the table: the memory road, the store's projection and
    the store-backed answer all state exactly the cell."""
    expected = STATE_TABLE[name][FIELDS.index((block, key))]
    population = populations[name]
    memory = population.answer(serve_from=SERVE_FROM_MEMORY)
    stored = stored_blocks(population)
    store_block = {"diff": stored.diff, "health": stored.health}[block]
    served = population.answer(serve_from=SERVE_FROM_RUN_STORE)
    assert _cell(memory, block, key) == expected, "memory"
    assert _cell({block: store_block}, block, key) == expected, "store"
    assert _cell(served, block, key) == expected, "served"


@pytest.mark.parametrize("name", list(STATE_TABLE))
def test_the_store_backed_answer_is_served_on_every_population(
    populations: SummaryPopulations, name: str
) -> None:
    """Memory and the store agree on every cell, so nothing diverges: the
    store's answer is the one served."""
    served = populations[name].answer(serve_from=SERVE_FROM_RUN_STORE)
    serving = served["serving"]
    assert isinstance(serving, Mapping)
    assert (serving["source"], serving["reason"]) == ("run_store", "served"), (
        json.dumps(serving)
    )


def test_the_table_distinguishes_every_field() -> None:
    """The accounting (Probe Validity Law): every field is ``null`` in some
    cell and a number in another; a measured zero is present for every
    field whose comparison a live population makes with a zero result --
    all but the health score's two fields."""
    zero_measured: set[tuple[str, str]] = set()
    for index, field in enumerate(FIELDS):
        column = [cells[index] for cells in STATE_TABLE.values()]
        assert None in column, field
        assert any(isinstance(cell, int) for cell in column), field
        if 0 in column:
            zero_measured.add(field)
    health_fields = {("diff", "health_delta"), ("health", "delta")}
    assert zero_measured == set(FIELDS) - health_fields
