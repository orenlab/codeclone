# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The run summary's reading of "not compared -> null" (ruling 2026-10-03).

Both answers of ``get_run_summary`` read the run's normalized comparison
state (``contracts.comparison_state``): the store's answer off the stored
run's rows (``stored_comparison_state``), the memory answer off the sealed
document it is built from (``document_comparison_state``), and both hand the
same rule (``answered_if_compared``) the same state.  The live state table
is ``tests/test_run_summary_not_compared_is_null.py``; the pins here hold
the rule and the document reader cell by cell, including the cell no live
population reaches: a health comparison that ran and measured zero.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from codeclone.canonical.comparison_ingest import (
    _DELTA_FAMILY_LANES as INGEST_DELTA_FAMILY_LANES,
)
from codeclone.canonical.comparison_projection import (
    DIFF_DELTA_KEYS,
    SUMMARY_COMPARISON_FIELDS,
    SUMMARY_DIFF_BLOCK,
    SUMMARY_HEALTH_BLOCK,
    answered_if_compared,
)
from codeclone.canonical.comparison_rows import DELTA_FAMILY_TERMS
from codeclone.canonical.comparison_state import (
    ComparisonState,
    compared,
    comparison_state,
    document_comparison_state,
    not_compared,
)
from codeclone.contracts.comparison_state import (
    COMPARISON_ADOPTION,
    COMPARISON_API_SURFACE,
    COMPARISON_CLONES,
    COMPARISON_HEALTH,
    COMPARISON_KEYS,
    COMPARISON_LANES,
    NOT_COMPARED_DISABLED,
    TERM_NEW_GROUPS,
    TERM_SCORE_DELTA,
    ComparisonKey,
)
from codeclone.core.comparison_snapshot import (
    _DELTA_FAMILY_LANES as PRODUCER_DELTA_FAMILY_LANES,
)

_FIELDS = sorted(SUMMARY_COMPARISON_FIELDS)

#: The comparison each delta family of the house states.
_FAMILY_COMPARISONS = {
    "adoption_delta": COMPARISON_ADOPTION,
    "api_surface_delta": COMPARISON_API_SURFACE,
}


def _state(made: frozenset[ComparisonKey]) -> ComparisonState:
    """Every key compared with value 7 when in ``made``, else not run."""
    return comparison_state(
        {
            key: compared(7) if key in made else not_compared("not_compared")
            for key in COMPARISON_KEYS
        }
    )


def test_the_rule_covers_exactly_the_nine_comparison_fields() -> None:
    assert set(SUMMARY_COMPARISON_FIELDS) == {
        (SUMMARY_DIFF_BLOCK, key)
        for key in ("new_clones", "health_delta", *DIFF_DELTA_KEYS)
    } | {(SUMMARY_HEALTH_BLOCK, "delta")}
    assert len(SUMMARY_COMPARISON_FIELDS) == 9


def test_every_field_spells_a_key_of_the_state() -> None:
    assert set(SUMMARY_COMPARISON_FIELDS.values()) <= set(COMPARISON_KEYS)


@pytest.mark.parametrize(
    "pairing",
    [PRODUCER_DELTA_FAMILY_LANES, INGEST_DELTA_FAMILY_LANES],
    ids=["producer", "ingest"],
)
def test_each_field_is_owned_by_the_comparison_both_producers_pair_it_with(
    pairing: Mapping[str, str],
) -> None:
    """The delta terms are owned by the comparison whose lane both
    comparison producers write their family from -- re-derived from the
    producers' own pairing, not restated."""
    owners = {
        term: SUMMARY_COMPARISON_FIELDS[(SUMMARY_DIFF_BLOCK, term)][0]
        for family in pairing
        for term in DELTA_FAMILY_TERMS[family]
    }
    assert {
        term: COMPARISON_LANES[comparison] for term, comparison in owners.items()
    } == {
        term: (lane,)
        for family, lane in pairing.items()
        for term in DELTA_FAMILY_TERMS[family]
    }


def test_the_clone_and_health_fields_are_owned_by_their_comparisons() -> None:
    """The clone count by the clone comparison; both health fields by the
    health comparison."""
    assert SUMMARY_COMPARISON_FIELDS[(SUMMARY_DIFF_BLOCK, "new_clones")] == (
        COMPARISON_CLONES,
        TERM_NEW_GROUPS,
    )
    assert {
        SUMMARY_COMPARISON_FIELDS[(SUMMARY_DIFF_BLOCK, "health_delta")],
        SUMMARY_COMPARISON_FIELDS[(SUMMARY_HEALTH_BLOCK, "delta")],
    } == {(COMPARISON_HEALTH, TERM_SCORE_DELTA)}


@pytest.mark.parametrize("field", _FIELDS)
def test_a_comparison_that_ran_and_measured_zero_answers_zero(
    field: tuple[str, str],
) -> None:
    """The decision reads the state, not the value: a measured zero is a
    number, under exactly its own comparison key."""
    block, key = field
    state = _state(frozenset({SUMMARY_COMPARISON_FIELDS[field]}))
    assert answered_if_compared(block, {key: 0}, state) == {key: 0}


@pytest.mark.parametrize("field", _FIELDS)
def test_a_number_whose_comparison_did_not_run_answers_null(
    field: tuple[str, str],
) -> None:
    """Whatever the number, a comparison the run did not make answers
    ``None`` -- every other key compared does not make it one."""
    block, key = field
    state = _state(frozenset(COMPARISON_KEYS) - {SUMMARY_COMPARISON_FIELDS[field]})
    assert answered_if_compared(block, {key: 7}, state) == {key: None}
    assert answered_if_compared(block, {key: 0}, state) == {key: None}


def test_keys_outside_the_rule_stay_as_they_are_and_in_their_order() -> None:
    health = {
        "score": 81,
        "grade": "B",
        "dimensions": {"clones": 100},
        "population": "complete_nonempty",
        "baseline_diff_available": False,
        "delta": 0,
    }
    nothing = _state(frozenset())
    answered = answered_if_compared(SUMMARY_HEALTH_BLOCK, health, nothing)
    assert list(answered) == list(health)
    assert answered == {**health, "delta": None}
    skipped = {"available": False, "reason": "metrics_skipped"}
    assert answered_if_compared(SUMMARY_HEALTH_BLOCK, skipped, nothing) == skipped
    # The block names the field: ``delta`` of ``diff`` is no comparison field.
    assert answered_if_compared(SUMMARY_DIFF_BLOCK, {"delta": 3}, nothing) == {
        "delta": 3
    }


def _document(
    *,
    disabled: tuple[str, ...] = (),
    flags: Mapping[str, bool],
) -> dict[str, object]:
    return {
        "baseline": {"disabled_capabilities": list(disabled)},
        "metrics": {
            "families": {
                family: {"summary": {"baseline_diff_available": flag}}
                for family, flag in flags.items()
            }
        },
    }


def _made(
    document: Mapping[str, object], new_clone_groups: int | None
) -> frozenset[str]:
    return document_comparison_state(
        document, new_clone_groups=new_clone_groups
    ).comparisons_made()


def test_the_memory_reads_the_comparisons_off_its_document() -> None:
    every = {"coverage_adoption": True, "api_surface": True, "health": True}
    assert _made(_document(flags=every), 0) == {
        COMPARISON_ADOPTION,
        COMPARISON_API_SURFACE,
        COMPARISON_CLONES,
        COMPARISON_HEALTH,
    }
    assert _made({}, None) == frozenset()
    flags = {"coverage_adoption": False, "health": True}
    assert _made(_document(flags=flags), None) == {COMPARISON_HEALTH}


def _disabled_api_document() -> dict[str, object]:
    return _document(
        disabled=("api_surface",),
        flags={"coverage_adoption": True, "api_surface": True, "health": True},
    )


def test_a_disabled_lane_is_not_compared_whatever_its_family_says() -> None:
    """A capability the run did not enable never ran: the one rule of the
    carrier, whatever flag a document of an older producer carries
    (measured 2026-10-05 before the producer was fixed:
    ``api_surface.summary.baseline_diff_available: true`` beside
    ``enabled: false``)."""
    assert _made(_disabled_api_document(), 0) == {
        COMPARISON_ADOPTION,
        COMPARISON_CLONES,
        COMPARISON_HEALTH,
    }


def test_a_disabled_lane_names_its_reason() -> None:
    state = document_comparison_state(_disabled_api_document(), new_clone_groups=0)
    assert state.reason(COMPARISON_API_SURFACE) == NOT_COMPARED_DISABLED


def test_a_flag_that_is_not_true_is_not_a_comparison() -> None:
    """Only the boolean ``true`` the document builder writes states a
    comparison: a missing summary, a missing key or a truthy non-boolean
    does not."""
    document: dict[str, object] = {
        "metrics": {
            "families": {
                "coverage_adoption": {"summary": {"baseline_diff_available": 1}},
                "api_surface": {"summary": {}},
                "health": {},
            }
        }
    }
    assert _made(document, None) == frozenset()
