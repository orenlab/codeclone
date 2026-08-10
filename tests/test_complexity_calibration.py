# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Procedure pin for the complexity-health reference permilles (Wave D option A).

The materialized permilles in ``codeclone.contracts`` are a GENERATED
calibration artifact. These tests are the rule-pin the maintainer's ruling
requires: they red if a materialized permille stops equalling the procedure's
output on the pinned reference distribution, or if the pinned distribution is
silently edited (digest). A test that only checked "health computes" or
"permilles exist" would survive a permille being quietly changed — these do
not.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from codeclone.contracts import (
    COMPLEXITY_ALGORITHM_REVISION,
    COMPLEXITY_RISK_LOW_MAX,
    COMPLEXITY_RISK_MEDIUM_MAX,
    HEALTH_COMPLEXITY_ELEVATED_REFERENCE_PERMILLE,
    HEALTH_COMPLEXITY_EXTREME_REFERENCE_PERMILLE,
)
from codeclone.metrics import complexity_calibration as calibration

# Pinned digest of the reference distribution captured at the Wave D landing.
# A silent edit to the histogram, the population or the revision moves this.
_PINNED_REFERENCE_DIGEST = (
    "8bfe01022c675a17bf66b54ab815571f3beae0e2f50163da64858a16b810f929"
)


def test_materialized_permilles_equal_the_procedure_output() -> None:
    """THE rule-pin: the scorer's constants ARE the procedure's output.

    Hand-editing ``HEALTH_COMPLEXITY_ELEVATED_REFERENCE_PERMILLE`` or
    ``HEALTH_COMPLEXITY_EXTREME_REFERENCE_PERMILLE`` to any wrong value reds
    this test, because the right-hand side is recomputed from the pinned
    reference distribution, not copied from the constant.
    """

    elevated, extreme = calibration.reference_permilles()
    assert elevated == HEALTH_COMPLEXITY_ELEVATED_REFERENCE_PERMILLE
    assert extreme == HEALTH_COMPLEXITY_EXTREME_REFERENCE_PERMILLE


def test_reference_distribution_digest_is_pinned() -> None:
    """A silent edit to the pinned reference distribution reds here."""

    assert calibration.reference_digest() == _PINNED_REFERENCE_DIGEST


def test_procedure_recomputes_permilles_from_the_population() -> None:
    """The permilles are derived, not asserted: recompute them independently.

    This mirrors the measurement contract with an inline round-half-up so the
    procedure cannot silently change its rounding rule without a second
    computation disagreeing.
    """

    population = calibration.reference_population()
    assert population == sum(
        count for _cc, count in calibration.COMPLEXITY_REFERENCE_DISTRIBUTION
    )
    assert population == calibration.REFERENCE_POPULATION

    def permille(count: int) -> int:
        return int(
            (Decimal(count * 1000) / Decimal(population)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )

    elevated = calibration.count_above(COMPLEXITY_RISK_LOW_MAX)
    extreme = calibration.count_above(COMPLEXITY_RISK_MEDIUM_MAX)
    assert calibration.reference_permilles() == (permille(elevated), permille(extreme))


def test_reference_distribution_is_source_decision_revision() -> None:
    """The calibration is bound to the source-decision metric revision."""

    assert COMPLEXITY_ALGORITHM_REVISION == "3"
    # Max reflects the source-decision metric (98), not the retired Y9-CFG (34).
    assert calibration.reference_maximum() == 98


def test_debt_snapshot_reports_the_measured_tail() -> None:
    """The debt receipt aggregates are the measured tail counts (gh #61)."""

    snapshot = calibration.debt_distribution_snapshot()
    assert snapshot == {
        "population": 5438,
        "above_10": 321,
        "above_20": 56,
        "above_30": 10,
        "maximum": 98,
    }


def test_permilles_are_not_the_retired_cfg_values() -> None:
    """Guard against a merge accidentally restoring the Y9-CFG calibration."""

    assert HEALTH_COMPLEXITY_ELEVATED_REFERENCE_PERMILLE == 59
    assert HEALTH_COMPLEXITY_EXTREME_REFERENCE_PERMILLE == 10
    assert (
        HEALTH_COMPLEXITY_ELEVATED_REFERENCE_PERMILLE,
        HEALTH_COMPLEXITY_EXTREME_REFERENCE_PERMILLE,
    ) != (28, 1)
