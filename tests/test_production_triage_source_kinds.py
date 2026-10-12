# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The triage's source-kind breakdown, as the store's one owner answers it.

``canonical.summary_projection.finding_counts`` states the triage's
``findings.by_source_kind`` over the projected finding groups.  Measured
2026-10-12 on the triage populations, before the owner was corrected: it
answered a group whose sites span production and tests (dominant kind
``mixed``) as ``other`` -- the report layer's normalization, which has no
``mixed`` word -- and spelled the five kinds in another order than the
surface's, so 13 of the 20 run-summary populations disagreed with the
surface's answer and every population disagreed on the wire.  The pin
compares serialized bytes: a breakdown that is the surface's as a set of
pairs and not as the answer it serves is not the surface's breakdown.
"""

from __future__ import annotations

import json

import pytest

from codeclone.canonical.store import RunStore
from codeclone.canonical.summary_projection import finding_counts
from codeclone.utils.coerce import as_mapping
from tests._triage_serving import (
    TRIAGE_POPULATIONS,
    TriagePopulations,
    shared_triage_populations,
    triage_answer,
)


@pytest.fixture(scope="module")
def populations(tmp_path_factory: pytest.TempPathFactory) -> TriagePopulations:
    return shared_triage_populations(tmp_path_factory)


def _wire(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


@pytest.mark.parametrize("name", list(TRIAGE_POPULATIONS))
def test_the_stored_breakdown_is_the_surfaces_on_the_wire(
    populations: TriagePopulations, name: str
) -> None:
    population = populations[name]
    link = population.record.execution.run_snapshot_link
    assert link is not None and link.store_run_id
    with RunStore(population.store_path, create=False) as store:
        counts = finding_counts(store.read_run(link.store_run_id))
    memory = as_mapping(triage_answer(population, serve_from=None)["findings"])
    assert _wire(counts["by_source_kind"]) == _wire(memory["by_source_kind"])
    assert counts["total"] == memory["total"]


def test_the_breakdown_population_holds_a_mixed_finding(
    populations: TriagePopulations,
) -> None:
    """The accounting: a ``mixed`` group is what tells the two
    normalizations apart, so some population must hold one."""
    mixed = [
        name
        for name in TRIAGE_POPULATIONS
        if as_mapping(
            as_mapping(triage_answer(populations[name], serve_from=None)["findings"])[
                "by_source_kind"
            ]
        )["mixed"]
    ]
    assert mixed
