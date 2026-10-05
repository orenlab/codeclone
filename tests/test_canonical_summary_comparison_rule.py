# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The one owner of "not compared -> null" (ruling 2026-10-03).

``canonical.comparison_projection`` decides, for both answers of
``get_run_summary``, which comparison field states a number: the store's
answer reads the comparisons a stored run made off its rows
(``comparisons_made``), the memory answer off the sealed document it is
built from (``document_comparisons_made``), and both hand the same rule
(``answered_if_compared``) the same vocabulary.  The live state table is
``tests/test_run_summary_not_compared_is_null.py``; the pins here hold the
owner's own decisions, cell by cell, including the one no live population
reaches: a health comparison that ran and measured zero.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from codeclone.canonical.comparison_ingest import (
    _DELTA_FAMILY_LANES as INGEST_DELTA_FAMILY_LANES,
)
from codeclone.canonical.comparison_projection import (
    COMPARISON_ADOPTION,
    COMPARISON_API_SURFACE,
    COMPARISON_CLONES,
    COMPARISON_HEALTH,
    DIFF_DELTA_KEYS,
    SUMMARY_COMPARISON_FIELDS,
    SUMMARY_DIFF_BLOCK,
    SUMMARY_HEALTH_BLOCK,
    answered_if_compared,
    comparisons_made,
    document_comparisons_made,
)
from codeclone.canonical.comparison_rows import (
    AVAILABILITY_COMPARED,
    AVAILABILITY_NOT_COMPARED,
    AVAILABILITY_UNAVAILABLE,
    DELTA_FAMILY_TERMS,
    ComparisonAvailabilityRow,
    MetricDeltaRow,
)
from codeclone.canonical.model import ComparisonFacts
from codeclone.core.comparison_snapshot import (
    _DELTA_FAMILY_LANES as PRODUCER_DELTA_FAMILY_LANES,
)

_ALL = frozenset(
    {COMPARISON_ADOPTION, COMPARISON_API_SURFACE, COMPARISON_CLONES, COMPARISON_HEALTH}
)
_FIELDS = sorted(SUMMARY_COMPARISON_FIELDS)
_SCOPE = "9e6a3f60-1df0-4c1e-9f3a-6f2f4b6a0c11"
_DIGEST = "0" * 64


def test_the_rule_covers_exactly_the_nine_comparison_fields() -> None:
    assert set(SUMMARY_COMPARISON_FIELDS) == {
        (SUMMARY_DIFF_BLOCK, key)
        for key in ("new_clones", "health_delta", *DIFF_DELTA_KEYS)
    } | {(SUMMARY_HEALTH_BLOCK, "delta")}
    assert len(SUMMARY_COMPARISON_FIELDS) == 9


def test_each_field_is_owned_by_the_comparison_both_producers_pair_it_with() -> None:
    """The delta terms are owned by the lane both comparison producers
    write their family from -- re-derived from the producers' own pairing,
    not restated; the clone count by the clone comparison; both health
    fields by the health comparison."""
    for pairing in (PRODUCER_DELTA_FAMILY_LANES, INGEST_DELTA_FAMILY_LANES):
        assert {
            (SUMMARY_DIFF_BLOCK, term): lane
            for family, lane in pairing.items()
            for term in DELTA_FAMILY_TERMS[family]
        }.items() <= SUMMARY_COMPARISON_FIELDS.items()
    assert SUMMARY_COMPARISON_FIELDS[(SUMMARY_DIFF_BLOCK, "new_clones")] == (
        COMPARISON_CLONES
    )
    for field in (
        (SUMMARY_DIFF_BLOCK, "health_delta"),
        (SUMMARY_HEALTH_BLOCK, "delta"),
    ):
        assert SUMMARY_COMPARISON_FIELDS[field] == COMPARISON_HEALTH


@pytest.mark.parametrize("field", _FIELDS)
def test_a_comparison_that_ran_and_measured_zero_answers_zero(
    field: tuple[str, str],
) -> None:
    """The decision reads the fact, not the value: a measured zero is a
    number, under exactly its own comparison."""
    block, key = field
    made = frozenset({SUMMARY_COMPARISON_FIELDS[field]})
    assert answered_if_compared(block, {key: 0}, made) == {key: 0}


@pytest.mark.parametrize("field", _FIELDS)
def test_a_number_whose_comparison_did_not_run_answers_null(
    field: tuple[str, str],
) -> None:
    """Whatever the number, a comparison the run did not make answers
    ``None`` -- every other comparison made does not make it one."""
    block, key = field
    made = _ALL - {SUMMARY_COMPARISON_FIELDS[field]}
    assert answered_if_compared(block, {key: 7}, made) == {key: None}
    assert answered_if_compared(block, {key: 0}, made) == {key: None}


def test_keys_outside_the_rule_stay_as_they_are_and_in_their_order() -> None:
    health = {
        "score": 81,
        "grade": "B",
        "dimensions": {"clones": 100},
        "population": "complete_nonempty",
        "baseline_diff_available": False,
        "delta": 0,
    }
    answered = answered_if_compared(SUMMARY_HEALTH_BLOCK, health, frozenset())
    assert list(answered) == list(health)
    assert answered == {**health, "delta": None}
    skipped = {"available": False, "reason": "metrics_skipped"}
    assert answered_if_compared(SUMMARY_HEALTH_BLOCK, skipped, frozenset()) == skipped
    # The block names the field: ``delta`` of ``diff`` is no comparison field.
    assert answered_if_compared(SUMMARY_DIFF_BLOCK, {"delta": 3}, frozenset()) == {
        "delta": 3
    }


def _availability(lane: str, word: str) -> ComparisonAvailabilityRow:
    return ComparisonAvailabilityRow(
        baseline_scope_id=_SCOPE, root_digest=_DIGEST, lane=lane, availability=word
    )


def test_the_store_reads_the_comparisons_off_its_rows() -> None:
    assert comparisons_made(ComparisonFacts()) == frozenset()
    house = ComparisonFacts(
        comparison_availability=frozenset(
            {
                _availability("adoption_counts", AVAILABILITY_COMPARED),
                _availability("api_surface", AVAILABILITY_NOT_COMPARED),
                _availability("clones.blocks", AVAILABILITY_COMPARED),
                _availability("clones.functions", AVAILABILITY_UNAVAILABLE),
                _availability("dead_code", AVAILABILITY_COMPARED),
            }
        ),
        health_delta=frozenset(
            {
                MetricDeltaRow(
                    baseline_scope_id=_SCOPE,
                    root_digest=_DIGEST,
                    delta="health_delta",
                    value=0,
                )
            }
        ),
    )
    assert comparisons_made(house) == {
        COMPARISON_ADOPTION,
        COMPARISON_CLONES,
        COMPARISON_HEALTH,
    }
    api_only = ComparisonFacts(
        comparison_availability=frozenset(
            {_availability("api_surface", AVAILABILITY_COMPARED)}
        )
    )
    assert comparisons_made(api_only) == {COMPARISON_API_SURFACE}


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


def test_the_memory_reads_the_comparisons_off_its_document() -> None:
    every = {"coverage_adoption": True, "api_surface": True, "health": True}
    assert document_comparisons_made(_document(flags=every), clones_compared=True) == (
        _ALL
    )
    assert document_comparisons_made({}, clones_compared=False) == frozenset()
    assert document_comparisons_made(
        _document(flags={"coverage_adoption": False, "health": True}),
        clones_compared=False,
    ) == {COMPARISON_HEALTH}


def test_a_disabled_lane_is_not_compared_whatever_its_family_says() -> None:
    """Measured 2026-10-05: a run with the API lane not enabled publishes
    ``api_surface.summary.baseline_diff_available: true``; the lane is a
    disabled capability, and no comparison of it ran."""
    document = _document(
        disabled=("api_surface",),
        flags={"coverage_adoption": True, "api_surface": True, "health": True},
    )
    assert document_comparisons_made(document, clones_compared=True) == (
        _ALL - {COMPARISON_API_SURFACE}
    )


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
    assert document_comparisons_made(document, clones_compared=False) == frozenset()
