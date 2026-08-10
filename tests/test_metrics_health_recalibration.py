# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Owning tests for the coupling risk bands and the coupling health dimension.

Phase 39Y item 3. Two facts are proven here.

**The bands are percentile-grounded.** ``COUPLING_RISK_LOW_MAX`` and
``COUPLING_RISK_MEDIUM_MAX`` are the 90th and 95th percentile of the reference
distribution recorded in :data:`REFERENCE_HISTOGRAM`. The derivation is
executable: the test recomputes both percentiles from the recorded measurement
and asserts the constants equal them, so a future edit cannot move a band
without either a new measurement or a declared change of the percentile rule.

**The dimension is bounded and monotone.** The previous formula
(``100 - avg*7 - max*2 - high*8``) was a function of a single class: one
27-collaborator outlier alone cost 54 of 100 points and 16 high-risk classes
cost 128, so the dimension was pinned at 0 on the reference distribution and
could not move when the code improved. Every term is now bounded by its own
named weight, so no single class and no single term can consume the dimension,
and the score is provably non-increasing under pointwise worsening.

Expected values here are consequences of the constants, never targets: nothing
in this module is derived from a desired self-health.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import pytest

from codeclone.contracts import (
    COMPLEXITY_RISK_LOW_MAX,
    COMPLEXITY_RISK_MEDIUM_MAX,
    COUPLING_RISK_LOW_MAX,
    COUPLING_RISK_MEDIUM_MAX,
    HEALTH_COMPLEXITY_ELEVATED_REFERENCE_PERMILLE,
    HEALTH_COMPLEXITY_ELEVATED_WEIGHT,
    HEALTH_COMPLEXITY_EXTREME_REFERENCE_PERMILLE,
    HEALTH_COMPLEXITY_EXTREME_WEIGHT,
    HEALTH_COMPLEXITY_OUTLIER_WEIGHT,
    HEALTH_COMPLEXITY_TYPICAL_WEIGHT,
    HEALTH_COUPLING_ELEVATED_REFERENCE_PERMILLE,
    HEALTH_COUPLING_ELEVATED_WEIGHT,
    HEALTH_COUPLING_EXTREME_REFERENCE_PERMILLE,
    HEALTH_COUPLING_EXTREME_WEIGHT,
    HEALTH_COUPLING_OUTLIER_SATURATION_MULTIPLE,
    HEALTH_COUPLING_OUTLIER_WEIGHT,
    HEALTH_COUPLING_TAIL_SATURATION_MULTIPLE,
    HEALTH_COUPLING_TYPICAL_WEIGHT,
)
from codeclone.metrics import complexity_calibration as calibration
from codeclone.metrics.health import HealthInputs, compute_health

# Reference distribution: CBO of every class of this repository, measured with
# the resolution-gated edge contract that 39Y item 2 landed.
#
#   ./.venv/bin/codeclone . --cache-path <fresh> --json <report>
#   -> 915 classes, 918 files, avg 1.4426, max 27
#
# Recorded as (cbo, class_count) pairs. This is the evidence the band
# percentiles are read from; replacing it requires a fresh measurement.
REFERENCE_HISTOGRAM: tuple[tuple[int, int], ...] = (
    (0, 458),
    (1, 220),
    (2, 76),
    (3, 57),
    (4, 27),
    (5, 16),
    (6, 13),
    (7, 10),
    (8, 12),
    (9, 4),
    (10, 6),
    (11, 1),
    (12, 2),
    (13, 2),
    (14, 3),
    (15, 1),
    (16, 3),
    (17, 2),
    (22, 1),
    (27, 1),
)

#: The band percentiles. Low is the bulk below the upper decile; medium runs to
#: the upper ventile; high is the 5% tail.
LOW_BAND_PERCENTILE = 90
MEDIUM_BAND_PERCENTILE = 95


def _reference_distribution() -> tuple[int, ...]:
    return tuple(value for value, count in REFERENCE_HISTOGRAM for _ in range(count))


def _percentile(values: Sequence[int], percentile: int) -> int:
    """Return the nearest-rank percentile of a sorted-on-demand sample."""

    ordered = sorted(values)
    rank = math.ceil(percentile / 100 * len(ordered))
    return ordered[max(0, min(len(ordered) - 1, rank - 1))]


def _coupling_inputs(distribution: Sequence[int]) -> HealthInputs:
    """Return health inputs whose only non-neutral dimension is coupling."""

    population = len(distribution)
    return HealthInputs(
        files_found=1,
        files_analyzed_or_cached=1,
        function_clone_groups=0,
        block_clone_groups=0,
        complexity_avg=0.0,
        complexity_max=0,
        high_risk_functions=0,
        elevated_complexity_functions=0,
        complexity_function_population=0,
        coupling_avg=(sum(distribution) / population if population else 0.0),
        coupling_max=max(distribution, default=0),
        coupling_class_population=population,
        elevated_coupling_classes=sum(
            1 for value in distribution if value > COUPLING_RISK_LOW_MAX
        ),
        high_risk_classes=sum(
            1 for value in distribution if value > COUPLING_RISK_MEDIUM_MAX
        ),
        cohesion_avg=1.0,
        low_cohesion_classes=0,
        dependency_cycles=0,
        dependency_max_depth=0,
        dependency_avg_depth=0.0,
        dependency_p95_depth=0,
        dead_code_items=0,
    )


def _dimension(distribution: Sequence[int]) -> int:
    return compute_health(_coupling_inputs(distribution)).dimensions["coupling"]


def test_reference_histogram_matches_its_recorded_summary() -> None:
    """The recorded evidence must still describe the measurement it claims."""

    distribution = _reference_distribution()

    assert len(distribution) == 915
    assert max(distribution) == 27
    assert sum(distribution) / len(distribution) == pytest.approx(1.4426, abs=1e-4)


def test_coupling_bands_are_the_declared_percentiles_of_the_reference() -> None:
    """Both band edges are recomputed from the evidence, not asserted by hand."""

    distribution = _reference_distribution()

    assert _percentile(distribution, LOW_BAND_PERCENTILE) == COUPLING_RISK_LOW_MAX
    assert (
        _percentile(
            distribution,
            MEDIUM_BAND_PERCENTILE,
        )
        == COUPLING_RISK_MEDIUM_MAX
    )


def test_tail_reference_shares_are_implied_by_the_band_percentiles() -> None:
    """The score's reference shares are not a second, independent measurement.

    A band edge at the Nth percentile means exactly ``1000 - 10*N`` per mille of
    the reference sits above it. Bands and score therefore share one derivation;
    a change to either percentile must move both or fail here.
    """

    assert HEALTH_COUPLING_ELEVATED_REFERENCE_PERMILLE == (
        1000 - 10 * LOW_BAND_PERCENTILE
    )
    assert HEALTH_COUPLING_EXTREME_REFERENCE_PERMILLE == (
        1000 - 10 * MEDIUM_BAND_PERCENTILE
    )


def test_coupling_term_weights_are_a_complete_budget() -> None:
    """The four bounded terms spend exactly the dimension, so 0 is reachable."""

    assert (
        HEALTH_COUPLING_TYPICAL_WEIGHT
        + HEALTH_COUPLING_ELEVATED_WEIGHT
        + HEALTH_COUPLING_EXTREME_WEIGHT
        + HEALTH_COUPLING_OUTLIER_WEIGHT
    ) == 100


def test_reference_distribution_does_not_saturate_the_dimension() -> None:
    """The reported defect: the reference distribution scored a pinned 0.

    A repository whose median class has no collaborators at all and whose mean
    is 1.44 must not read as a total loss on coupling. The old formula charged
    54 points for one 27-CBO class and 128 for the 16 classes above the old
    medium band, so the dimension was clamped to 0 and carried no signal.
    """

    score = _dimension(_reference_distribution())

    assert 0 < score < 100, (
        f"reference distribution scores {score}: the dimension is saturated "
        f"and cannot move with real improvement"
    )
    # Consequence of the constants, recorded so silent drift is visible.
    # This is an output of the derivation, never a target it was fitted to.
    assert score == 72


def test_improving_the_worst_class_is_visible_in_the_score() -> None:
    """No dead zone: fixing the single worst class must move the dimension.

    Under the old formula this exact improvement moved the score 0 -> 0, which
    is what made the dimension useless as a signal.
    """

    reference = _reference_distribution()
    improved = [*sorted(reference)[:-1], 22]

    assert _dimension(improved) > _dimension(reference)


def test_improvement_is_visible_at_every_tail_of_the_distribution() -> None:
    """Each declared pressure independently rewards a real improvement."""

    reference = sorted(_reference_distribution())
    baseline = _dimension(reference)

    # Halve the extreme tail by pulling every high-risk class to the band edge.
    tail_fixed = [min(value, COUPLING_RISK_MEDIUM_MAX) for value in reference]
    # Pull every elevated class down to the low band.
    elevated_fixed = [min(value, COUPLING_RISK_LOW_MAX) for value in reference]
    # Reduce the typical class without touching either tail.
    typical_fixed = [max(0, value - 1) for value in reference]

    assert _dimension(tail_fixed) > baseline
    assert _dimension(elevated_fixed) > _dimension(tail_fixed)
    assert _dimension(typical_fixed) > baseline


@pytest.mark.parametrize(
    "base",
    [
        pytest.param(_reference_distribution(), id="reference"),
        pytest.param((0,) * 50, id="pristine"),
        pytest.param(tuple(range(20)), id="ramp"),
        pytest.param((3,) * 100, id="uniform-low"),
        pytest.param((0, 0, 0, 0, 30), id="single-outlier"),
    ],
)
def test_coupling_score_never_improves_when_a_class_gets_worse(
    base: tuple[int, ...],
) -> None:
    """Weak monotonicity, proven by enumeration over pointwise worsening.

    Every term is non-decreasing in a pointwise-larger distribution: the mean
    rises, neither band count can fall, and the maximum cannot fall. The score
    is therefore non-increasing, and rounding preserves that.
    """

    reference_score = _dimension(base)
    step = max(1, len(base) // 7)

    for index in range(0, len(base), step):
        for delta in (1, 3, 9):
            worse = list(base)
            worse[index] += delta
            assert _dimension(worse) <= reference_score, (
                f"raising class {index} by {delta} improved the dimension"
            )


def test_coupling_score_strictly_decreases_across_meaningful_intervals() -> None:
    """Strict monotonicity on a ladder of materially different populations.

    Each rung is a whole population one collaborator-band worse than the last.
    Under the old formula the last two rungs were both 0 — the dimension had
    stopped distinguishing bad from catastrophic.
    """

    ladder = ((0,), (1,), (2,), (4,), (6,), (8,), (12,), (20,))
    scores = [_dimension(value * 100) for value in ladder]

    assert scores == sorted(scores, reverse=True)
    for worse, better in zip(scores[1:], scores[:-1], strict=True):
        assert worse < better, f"ladder stalled at {scores}"


def test_outlier_pressure_is_bounded_and_saturates() -> None:
    """One class cannot spend more than the outlier weight, however extreme.

    The old ``max * 2`` term was unbounded: a single 27-collaborator class cost
    54 points and a 60-collaborator class would have cost 120. The replacement
    saturates at ``MEDIUM_MAX * OUTLIER_SATURATION_MULTIPLE``, so an arbitrarily
    bad single class costs the outlier weight and nothing more.
    """

    saturation = COUPLING_RISK_MEDIUM_MAX * (
        1 + HEALTH_COUPLING_OUTLIER_SATURATION_MULTIPLE
    )
    population = (0,) * 999

    at_band_edge = _dimension((*population, COUPLING_RISK_MEDIUM_MAX))
    at_saturation = _dimension((*population, saturation))
    far_beyond = _dimension((*population, saturation * 10))

    assert at_band_edge - at_saturation <= HEALTH_COUPLING_OUTLIER_WEIGHT
    # Beyond saturation only the mean still moves, and it moves by a hair:
    # the dimension is no longer a function of one class's magnitude.
    assert at_saturation - far_beyond <= 1


def test_tail_pressure_saturates_at_the_declared_multiple() -> None:
    """A tail this many times the reference share spends its whole term."""

    population = 1000
    elevated_at_saturation = (
        HEALTH_COUPLING_ELEVATED_REFERENCE_PERMILLE
        * HEALTH_COUPLING_TAIL_SATURATION_MULTIPLE
        * population
        // 1000
    )
    distribution = [COUPLING_RISK_LOW_MAX + 1] * elevated_at_saturation
    distribution += [0] * (population - elevated_at_saturation)

    saturated = _dimension(distribution)
    worse = _dimension([*distribution[:-1], COUPLING_RISK_LOW_MAX + 1])

    # The elevated term is already fully spent, so widening the tail further
    # cannot charge for it twice.
    assert saturated - worse <= 1


def test_empty_population_scores_full_marks() -> None:
    """A project with no classes has no coupling debt to report."""

    assert _dimension(()) == 100


# ---------------------------------------------------------------------------
# The complexity dimension (39Y Addition 1)
# ---------------------------------------------------------------------------

# Reference distribution: source-decision complexity of every PRODUCTION
# function of this repository (files outside tests/ and benchmarks/), the same
# population the retired Y9-CFG calibration used, re-measured for the
# source-decision metric at Wave D option A:
#
#   n=5438, avg 3.8957, p90/p95/p99 = 8/11/21, max 98
#
# It lives beside the procedure that consumes it, in
# ``codeclone.metrics.complexity_calibration``, so the histogram, the generated
# permilles and their digest have one source of truth. The retired Y9-CFG
# reference was n=5194, avg 2.9692, p90/p95/p99 = 6/8/15, max 34.
COMPLEXITY_REFERENCE_HISTOGRAM = calibration.COMPLEXITY_REFERENCE_DISTRIBUTION


def _complexity_reference() -> tuple[int, ...]:
    return tuple(
        value for value, count in COMPLEXITY_REFERENCE_HISTOGRAM for _ in range(count)
    )


def _complexity_inputs(distribution: Sequence[int]) -> HealthInputs:
    """Return health inputs whose only non-neutral dimension is complexity."""

    population = len(distribution)
    return HealthInputs(
        files_found=1,
        files_analyzed_or_cached=1,
        function_clone_groups=0,
        block_clone_groups=0,
        complexity_avg=(sum(distribution) / population if population else 0.0),
        complexity_max=max(distribution, default=0),
        high_risk_functions=sum(
            1 for value in distribution if value > COMPLEXITY_RISK_MEDIUM_MAX
        ),
        elevated_complexity_functions=sum(
            1 for value in distribution if value > COMPLEXITY_RISK_LOW_MAX
        ),
        complexity_function_population=population,
        coupling_avg=0.0,
        coupling_max=0,
        high_risk_classes=0,
        elevated_coupling_classes=0,
        coupling_class_population=0,
        cohesion_avg=1.0,
        low_cohesion_classes=0,
        dependency_cycles=0,
        dependency_max_depth=0,
        dependency_avg_depth=0.0,
        dependency_p95_depth=0,
        dead_code_items=0,
    )


def _complexity_dimension(distribution: Sequence[int]) -> int:
    return compute_health(_complexity_inputs(distribution)).dimensions["complexity"]


def test_complexity_reference_histogram_matches_its_recorded_summary() -> None:
    distribution = _complexity_reference()

    assert len(distribution) == 5438
    assert round(sum(distribution) / len(distribution), 4) == 3.8957
    assert max(distribution) == 98
    assert _percentile(distribution, 90) == 8
    assert _percentile(distribution, 95) == 11
    assert _percentile(distribution, 99) == 21


def test_complexity_bands_are_unchanged_by_the_recalibration() -> None:
    """The bands were reviewed and kept; only the scoring moved.

    Unlike the coupling bands, these are NOT percentiles of the reference —
    10 sits above its p95 and 20 above its p99. Pinning them here states that
    on purpose, so a later cycle cannot quietly re-derive them from a
    distribution and call it a refinement.
    """

    assert COMPLEXITY_RISK_LOW_MAX == 10
    assert COMPLEXITY_RISK_MEDIUM_MAX == 20


def test_complexity_tail_references_are_the_measured_shares() -> None:
    """The two reference shares are read off the measurement, not chosen."""

    distribution = _complexity_reference()
    elevated = sum(1 for value in distribution if value > COMPLEXITY_RISK_LOW_MAX)
    extreme = sum(1 for value in distribution if value > COMPLEXITY_RISK_MEDIUM_MAX)

    assert elevated == 321
    assert extreme == 56
    # The materialized shares equal the procedure's generated permilles.
    assert calibration.reference_permilles() == (
        HEALTH_COMPLEXITY_ELEVATED_REFERENCE_PERMILLE,
        HEALTH_COMPLEXITY_EXTREME_REFERENCE_PERMILLE,
    )
    assert HEALTH_COMPLEXITY_ELEVATED_REFERENCE_PERMILLE == 59
    assert HEALTH_COMPLEXITY_EXTREME_REFERENCE_PERMILLE == 10


def test_complexity_term_weights_are_a_complete_budget() -> None:
    assert (
        HEALTH_COMPLEXITY_TYPICAL_WEIGHT
        + HEALTH_COMPLEXITY_ELEVATED_WEIGHT
        + HEALTH_COMPLEXITY_EXTREME_WEIGHT
        + HEALTH_COMPLEXITY_OUTLIER_WEIGHT
    ) == 100


def test_complexity_reference_distribution_does_not_saturate_the_dimension() -> None:
    """The defect this replaces, pinned as a permanent fence.

    Bounded terms keep the reference distribution in the sixties-to-seventies
    with room to move in both directions, which is the whole point - a score
    that cannot improve when the code improves is not a measurement. Under the
    source-decision metric the reference outlier (max 98) alone spends the
    whole 10-point outlier term, which is a property of the max/band ratio, not
    of the tail-reference recalibration this cycle performed.
    """

    score = _complexity_dimension(_complexity_reference())

    assert 60 <= score <= 90
    # Every single term is bounded by its own weight, so no one function and no
    # one term can consume the dimension.
    assert _complexity_dimension([1] * calibration.reference_population()) > score
    assert _complexity_dimension([]) == 100


def test_complexity_score_never_improves_when_a_function_gets_worse() -> None:
    """Monotonicity: a pointwise worse distribution can never score higher."""

    distribution = list(_complexity_reference())
    baseline = _complexity_dimension(distribution)
    for index in (0, 900, 4000, len(distribution) - 1):
        for step in (1, 5, 40):
            worse = list(distribution)
            worse[index] += step
            assert _complexity_dimension(worse) <= baseline


def test_improving_the_worst_function_is_visible_in_the_complexity_score() -> None:
    """The dimension must respond to real work on the worst offender."""

    distribution = list(_complexity_reference())
    before = _complexity_dimension(distribution)
    improved = sorted(distribution)
    improved[-1] = COMPLEXITY_RISK_MEDIUM_MAX
    assert _complexity_dimension(improved) > before
