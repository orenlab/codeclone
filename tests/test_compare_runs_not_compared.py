# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""``compare_runs`` states no number for a comparison that did not run
(ruling 2026-10-03, "not compared -> null").

Measured 2026-10-06 on the pair population: two clones-only runs asked for
their ``structural`` or ``metrics`` findings answered ``comparable: true``,
``verdict: stable``, ``unchanged: 0`` -- a zero over families the mode never
analysed.  Such a focus is now not compared: ``comparable: false`` with the
reason ``focus_not_analyzed``, the existing incomparable shape (``null``
counts, empty lists, the ``incomparable`` verdict, an "omitted" summary).
A focus the mode did analyse, and every focus of a full pair, still compare;
an empty scope is a measured one and still compares.
"""

from __future__ import annotations

import pytest

from codeclone.surfaces.mcp._patch_contract_runs import focus_is_analyzed
from codeclone.utils.coerce import as_sequence
from tests._compare_runs_serving import COMPARE_FOCUSES, ComparePair, shared_pairs

#: (analysis mode, focus) -> whether the focus compares anything.
_FOCUS_TABLE: dict[tuple[str, str], bool] = {
    ("full", "all"): True,
    ("full", "clones"): True,
    ("full", "structural"): True,
    ("full", "metrics"): True,
    ("clones_only", "all"): True,
    ("clones_only", "clones"): True,
    ("clones_only", "structural"): False,
    ("clones_only", "metrics"): False,
}


@pytest.mark.parametrize(("mode", "focus"), list(_FOCUS_TABLE))
def test_a_focus_compares_only_the_families_its_mode_analysed(
    mode: str, focus: str
) -> None:
    assert focus_is_analyzed(focus, analysis_mode=mode) is _FOCUS_TABLE[(mode, focus)]


@pytest.fixture(scope="module")
def pairs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, ComparePair]:
    return shared_pairs(tmp_path_factory)


@pytest.mark.parametrize("focus", ["structural", "metrics"])
def test_a_focus_the_mode_did_not_analyse_states_no_number(
    pairs: dict[str, ComparePair], focus: str
) -> None:
    answer = pairs["clones_only"].ask(focus, serve_from="run_store")
    assert {key: answer[key] for key in answer if key != "serving"} == {
        "before": answer["before"],
        "after": answer["after"],
        "comparable": False,
        "health_delta": None,
        "verdict": "incomparable",
        "regressions": [],
        "improvements": [],
        "unchanged": None,
        "summary": (
            "Finding and run health deltas omitted "
            "(the analysis mode did not analyse this focus)"
        ),
        "reason": "focus_not_analyzed",
    }


@pytest.mark.parametrize("focus", ["all", "clones"])
def test_a_focus_the_mode_analysed_still_compares(
    pairs: dict[str, ComparePair], focus: str
) -> None:
    """The positive control on the same pair: its clone comparison runs and
    finds the clone pair the second run added."""
    answer = pairs["clones_only"].ask(focus, serve_from="run_store")
    assert answer["comparable"] is True and answer["verdict"] == "regressed"
    assert len(as_sequence(answer["regressions"])) == 1
    assert answer["unchanged"] == 4


@pytest.mark.parametrize("focus", COMPARE_FOCUSES)
def test_every_focus_of_a_full_pair_and_of_an_empty_scope_compares(
    pairs: dict[str, ComparePair], focus: str
) -> None:
    """A full pair compares under every focus; a scope with no source file
    is a measured one, so its ``unchanged: 0`` is a measured zero."""
    assert (
        pairs["regressed.forward"].ask(focus, serve_from="run_store")["comparable"]
        is True
    )
    empty = pairs["complete_empty"].ask(focus, serve_from="run_store")
    assert empty["comparable"] is True and empty["unchanged"] == 0
