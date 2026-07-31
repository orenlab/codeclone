# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The near-miss tier's exact bounded confirmation, at the predicate level.

``tests/test_clone_tiers_near_miss.py`` drives the tier end to end from the
``clone_tiers`` fixture and its ``ground_truth.json``. This module pins the
confirmation step underneath it, because the deletion index is deliberately
only a superset filter: ``[X, Y]`` and ``[Y, X]`` share the variants ``[X]``
and ``[Y]`` yet sit at distance two. Everything that keeps an over-collected
candidate from being reported lives in ``_confirm``, so its rejections are
pinned here directly rather than inferred from a pair that happens not to
appear in a fixture's output.
"""

from __future__ import annotations

import pytest

from codeclone.findings.clones.near_miss import _confirm, _elements
from codeclone.models import GroupItemLike


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (("a", "b", "c"), ("a",)),
        (("a",), ("a", "b", "c")),
    ],
)
def test_confirm_refuses_pairs_beyond_the_declared_edit_bound(
    left: tuple[str, ...],
    right: tuple[str, ...],
) -> None:
    """A two-statement length gap is outside the tier, not a weak match.

    The bound is an integer contract constant, so exceeding it is a refusal
    rather than a lower score.
    """

    assert _confirm(left, right) is None


def test_confirm_refuses_identical_sequences_to_the_exact_tier() -> None:
    """Distance zero is the exact tier's business; near-miss declines it."""

    assert _confirm(("a", "b"), ("a", "b")) is None


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (("x", "y"), ("y", "x")),
        (("a", "b", "c"), ("a", "c", "b")),
    ],
)
def test_confirm_refuses_candidates_the_deletion_index_over_collects(
    left: tuple[str, ...],
    right: tuple[str, ...],
) -> None:
    """Two transposed statements share deletion variants but sit at distance two.

    This is precisely the case the module's docstring names as the reason
    confirmation exists at all, so the tail comparison must reject it.
    """

    assert _confirm(left, right) is None


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        (("a", "b"), ("a", "x", "b"), ("insert", -1, 1, 1)),
        (("a", "x", "b"), ("a", "b"), ("delete", 1, -1, 1)),
        (("a", "x"), ("a", "y"), ("replace", 1, 1, 1)),
    ],
)
def test_confirm_names_the_edit_kind_and_the_index_on_each_side(
    left: tuple[str, ...],
    right: tuple[str, ...],
    expected: tuple[str, int, int, int],
) -> None:
    """The result is honest about direction: ``-1`` where a side has no edit."""

    assert _confirm(left, right) == expected


@pytest.mark.parametrize(
    "raw",
    ["not-a-sequence", 7, None],
)
def test_elements_reads_no_statements_from_a_non_sequence(raw: object) -> None:
    """A unit whose statement sequence is not a sequence contributes nothing.

    Returning ``()`` keeps the unit out of every cohort, which is the correct
    outcome: the tier reports pairs, and a unit with no readable sequence
    cannot be half of one.
    """

    unit: GroupItemLike = {"statement_sequence": raw}
    assert _elements(unit) == ()


@pytest.mark.parametrize(
    "item",
    [("token", 1), ("token", 1, 2, 3), "not-a-triple"],
)
def test_elements_rejects_the_whole_unit_when_one_element_is_malformed(
    item: object,
) -> None:
    """An element is ``(token, start, end)`` exactly, or the unit is dropped."""

    unit: GroupItemLike = {"statement_sequence": [("ok", 1, 2), item]}
    assert _elements(unit) == ()


def test_elements_normalizes_a_well_formed_sequence_to_triples() -> None:
    """Pins the accepted shape the rejections above are drawn against."""

    unit: GroupItemLike = {"statement_sequence": [["call", "1", "2"]]}
    assert _elements(unit) == (("call", 1, 2),)


def test_elements_treats_an_absent_sequence_as_empty() -> None:
    """A unit that recorded no sequence is simply not a near-miss candidate."""

    assert _elements({}) == ()
