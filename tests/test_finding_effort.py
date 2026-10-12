# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The effort a finding was priced under, read back from its price -- one
owner, and the two producers it reads back held to one rule.

Consumer migration C2.  The store carries the verdict on every finding --
severity and priority -- and never the suggestion beside it, so the
triage's effort is the price read backwards: ``priority = severity rank /
effort weight`` (the admissibility law of
``canonical.evaluation_rows.FindingEvaluationRow``), and the three effort
weights are distinct, so the reading is unique.  It is the suggestion's
effort only while the document's group builders and the suggestion
producer name the same effort for the same finding; those are two
producers (``report.document._findings_groups`` / ``_design_groups`` and
``report.suggestions``), so their agreement is pinned here on every
suggestion of every triage population, per producer branch.
"""

from __future__ import annotations

import math

import pytest

from codeclone.canonical import evaluation_rows
from codeclone.canonical.errors import CanonicalModelError
from codeclone.domain.quality import EFFORT_WEIGHT, SEVERITY_RANK
from tests._triage_serving import (
    TRIAGE_POPULATIONS,
    SuggestionPricing,
    shared_triage_populations,
    suggestion_pricings,
)


@pytest.fixture(scope="module")
def pricings(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[SuggestionPricing, ...]:
    populations = shared_triage_populations(tmp_path_factory)
    return tuple(
        pricing
        for name in TRIAGE_POPULATIONS
        for pricing in suggestion_pricings(populations[name])
    )


@pytest.mark.parametrize("severity", sorted(SEVERITY_RANK))
@pytest.mark.parametrize("effort", sorted(EFFORT_WEIGHT))
def test_the_effort_is_the_one_the_priority_was_priced_under(
    severity: str, effort: str
) -> None:
    """The rule, not a table: every (severity, effort) price reads back to
    its effort, through the same arithmetic the document prices with."""
    priority = float(SEVERITY_RANK[severity]) / float(EFFORT_WEIGHT[effort])
    assert evaluation_rows.finding_priority_is_admissible(severity, priority)
    assert evaluation_rows.finding_effort(severity, priority) == effort


@pytest.mark.parametrize(
    ("severity", "priority"),
    [("warning", 1.5), ("critical", 2.0), ("info", 3.0), ("warning", math.nan)],
)
def test_a_priority_no_effort_prices_is_refused(severity: str, priority: float) -> None:
    assert not evaluation_rows.finding_priority_is_admissible(severity, priority)
    with pytest.raises(CanonicalModelError, match="no effort's priority"):
        evaluation_rows.finding_effort(severity, priority)


def test_both_producers_price_every_suggested_finding_under_one_effort(
    pricings: tuple[SuggestionPricing, ...],
) -> None:
    """The suggestion's effort, the document's published one and the price
    read backwards are one effort, for every suggestion of every population."""
    disagreeing = [
        pricing
        for pricing in pricings
        if not (
            evaluation_rows.finding_effort(pricing.severity, pricing.priority)
            == pricing.suggested_effort
            == pricing.published_effort
        )
    ]
    assert pricings
    assert disagreeing == []


def test_the_populations_reach_every_branch_of_the_suggestion_producer(
    pricings: tuple[SuggestionPricing, ...],
) -> None:
    """The accounting behind the pin above: each producer branch that names
    an effort is reached by some suggestion -- a branch nobody reaches could
    name any effort and the pin would stay green."""
    reached = {(pricing.category, pricing.suggested_effort) for pricing in pricings}
    assert reached >= {
        ("clone", "easy"),
        ("clone", "moderate"),
        ("structural", "moderate"),
        ("complexity", "moderate"),
        ("coupling", "moderate"),
        ("cohesion", "moderate"),
        ("dead_code", "easy"),
        ("dependency", "hard"),
    }, sorted(reached)
    assert {pricing.severity for pricing in pricings} == set(SEVERITY_RANK)
