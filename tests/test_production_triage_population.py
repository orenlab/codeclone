# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The triage populations distinguish what the triage's store reading must
get right -- the accounting before any equivalence pin counts.

Consumer migration C2 (Probe Validity Law: a pin that compares the store's
triage with the memory's proves nothing on a population where a wrong
reading answers the same).  Over every triage population
(``tests/_triage_serving.py``), the memory answer -- the switch unset, every
card and suggestion shown -- must reach:

* every source kind among the findings, and every source kind a suggestion
  can carry among the suggestions: a reading that answered ``production``
  for all of them would otherwise agree;
* every effort among the suggestions, and cards both with and without one:
  an effort read without the suggestion's membership, or a constant one,
  would otherwise agree;
* all three novelty words and all three severities among the cards;
* a limit that cuts the hotspots and one that cuts the suggestions;
* a short id shown disambiguated whose twin is neither a production hotspot
  nor a production suggestion: a short-id map over the shown or selected
  findings instead of the whole universe would otherwise agree.

``other`` is the one source kind no suggestion can carry, measured and held
here: a suggestion's kind combines the kinds of its sites' paths (or of its
cycle's member paths), and a non-empty path is never ``other``
(``paths.classify_source_kind``).
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from tests._triage_serving import (
    TriageAccount,
    TriagePopulations,
    accounts,
    shared_triage_populations,
)

_SOURCE_KINDS = frozenset({"production", "tests", "fixtures", "mixed", "other"})


@pytest.fixture(scope="module")
def account(tmp_path_factory: pytest.TempPathFactory) -> Mapping[str, TriageAccount]:
    populations: TriagePopulations = shared_triage_populations(tmp_path_factory)
    return accounts(populations)


def _reached(account: Mapping[str, TriageAccount], field: str) -> dict[str, list[str]]:
    """Each value of one account field, with the populations that reach it."""
    reached: dict[str, list[str]] = {}
    for name, entry in account.items():
        for value in getattr(entry, field):
            reached.setdefault(value, []).append(name)
    return reached


def test_every_source_kind_is_reached_among_the_findings(
    account: Mapping[str, TriageAccount],
) -> None:
    reached = _reached(account, "finding_kinds")
    assert set(reached) == _SOURCE_KINDS, reached


def test_every_reachable_source_kind_is_reached_among_the_suggestions(
    account: Mapping[str, TriageAccount],
) -> None:
    reached = _reached(account, "suggestion_kinds")
    assert set(reached) == _SOURCE_KINDS - {"other"}, reached


def test_every_effort_is_reached_and_cards_go_without_one(
    account: Mapping[str, TriageAccount],
) -> None:
    items = _reached(account, "item_efforts")
    cards = _reached(account, "card_efforts")
    assert set(items) == {"easy", "moderate", "hard"}, items
    assert {"", "easy", "moderate"} <= set(cards), cards


def test_every_novelty_and_severity_is_reached_among_the_cards(
    account: Mapping[str, TriageAccount],
) -> None:
    novelty = _reached(account, "card_novelty")
    severities = _reached(account, "card_severities")
    assert set(novelty) == {"new", "known", "unavailable"}, novelty
    assert set(severities) == {"critical", "warning", "info"}, severities


def test_the_default_limits_cut_both_lists_somewhere(
    account: Mapping[str, TriageAccount],
) -> None:
    hotspots = [name for name, entry in account.items() if entry.hotspots_cut]
    suggestions = [name for name, entry in account.items() if entry.suggestions_cut]
    assert hotspots, "no population ranks more hotspots than the default shows"
    assert suggestions, "no population ranks more suggestions than the default shows"


def test_a_disambiguated_short_id_is_shown_beside_an_unselected_twin(
    account: Mapping[str, TriageAccount],
) -> None:
    shown = {
        name: entry.discriminating_collisions
        for name, entry in account.items()
        if entry.discriminating_collisions
    }
    assert shown, "no shown short id tells the universe's map from a narrower one"
