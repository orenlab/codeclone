# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Literal

from ..contracts import (
    COMPLEXITY_RISK_MEDIUM_MAX,
    COUPLING_RISK_MEDIUM_MAX,
    HEALTH_COMPLEXITY_ELEVATED_REFERENCE_PERMILLE,
    HEALTH_COMPLEXITY_ELEVATED_WEIGHT,
    HEALTH_COMPLEXITY_EXTREME_REFERENCE_PERMILLE,
    HEALTH_COMPLEXITY_EXTREME_WEIGHT,
    HEALTH_COMPLEXITY_OUTLIER_SATURATION_MULTIPLE,
    HEALTH_COMPLEXITY_OUTLIER_WEIGHT,
    HEALTH_COMPLEXITY_TAIL_SATURATION_MULTIPLE,
    HEALTH_COMPLEXITY_TYPICAL_WEIGHT,
    HEALTH_COUPLING_ELEVATED_REFERENCE_PERMILLE,
    HEALTH_COUPLING_ELEVATED_WEIGHT,
    HEALTH_COUPLING_EXTREME_REFERENCE_PERMILLE,
    HEALTH_COUPLING_EXTREME_WEIGHT,
    HEALTH_COUPLING_OUTLIER_SATURATION_MULTIPLE,
    HEALTH_COUPLING_OUTLIER_WEIGHT,
    HEALTH_COUPLING_TAIL_SATURATION_MULTIPLE,
    HEALTH_COUPLING_TYPICAL_WEIGHT,
    HEALTH_DEPENDENCY_CYCLE_PENALTY,
    HEALTH_DEPENDENCY_DEPTH_AVG_MULTIPLIER,
    HEALTH_DEPENDENCY_DEPTH_LEVEL_PENALTY,
    HEALTH_DEPENDENCY_DEPTH_P95_MARGIN,
    HEALTH_WEIGHTS,
)
from ..models import HealthScore


@dataclass(frozen=True, slots=True)
class HealthInputs:
    files_found: int
    files_analyzed_or_cached: int
    function_clone_groups: int
    block_clone_groups: int
    complexity_avg: float
    complexity_max: int
    #: Functions above COMPLEXITY_RISK_MEDIUM_MAX — the extreme tail.
    high_risk_functions: int
    #: Functions above COMPLEXITY_RISK_LOW_MAX, extreme ones included: the
    #: tails nest, exactly as they do for coupling below.
    elevated_complexity_functions: int
    #: Denominator of both complexity tail shares. Zero means no functions were
    #: observed, in which case there is no complexity debt to report.
    complexity_function_population: int
    coupling_avg: float
    coupling_max: int
    #: Classes above COUPLING_RISK_MEDIUM_MAX — the extreme tail.
    high_risk_classes: int
    #: Classes above COUPLING_RISK_LOW_MAX, extreme ones included: the tails
    #: nest, so the worst classes press on both the width and the depth of the
    #: tail rather than being partitioned between them.
    elevated_coupling_classes: int
    #: Denominator of both tail shares. Zero means no classes were observed, in
    #: which case there is no coupling debt to report.
    coupling_class_population: int
    cohesion_avg: float
    low_cohesion_classes: int
    dependency_cycles: int
    dependency_max_depth: int
    dependency_avg_depth: float
    dependency_p95_depth: int
    dead_code_items: int


def _clamp_score(value: float) -> int:
    return max(0, min(100, round(value)))


def _grade(score: int) -> Literal["A", "B", "C", "D", "F"]:
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    if score >= 40:
        return "D"
    return "F"


def _safe_div(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _dependency_expected_tail(*, avg_depth: float, p95_depth: int) -> int:
    avg_based = ceil(max(0.0, avg_depth) * HEALTH_DEPENDENCY_DEPTH_AVG_MULTIPLIER)
    p95_based = max(0, p95_depth) + HEALTH_DEPENDENCY_DEPTH_P95_MARGIN
    return max(avg_based, p95_based)


def _dependency_tail_pressure(
    *,
    max_depth: int,
    avg_depth: float,
    p95_depth: int,
) -> int:
    if max_depth <= 0:
        return 0
    return max(
        0,
        max_depth - _dependency_expected_tail(avg_depth=avg_depth, p95_depth=p95_depth),
    )


# Piecewise clone-density curve: mild penalty for low density,
# steep in the structural-debt zone, brutal when it's systemic.
_CLONE_BREAKPOINTS: tuple[tuple[float, float], ...] = (
    (0.05, 90.0),  # ≤5% density — 1-2 accidental groups, almost no penalty
    (0.20, 50.0),  # 5-20% — clear structural debt, steep slope
    (0.50, 0.0),  # >20% — systemic duplication, score floors at 0
)


def _unit(value: float) -> float:
    """Clamp a pressure to [0, 1] so a term can never exceed its weight."""

    return max(0.0, min(1.0, value))


def _tail_pressure(
    *,
    count: int,
    population: int,
    reference_permille: int,
    saturation_multiple: int,
) -> float:
    """Pressure from a tail, measured against the share its reference implies.

    A share is used rather than a count so a dimension does not fall simply
    because a project has more functions or more classes. Shared by both the
    complexity and the coupling dimensions: one derivation, two callers.
    """

    if population <= 0 or count <= 0:
        return 0.0
    observed_permille = count * 1000 / population
    return _unit(observed_permille / (reference_permille * saturation_multiple))


def _outlier_pressure(*, observed_max: int, band_edge: int, multiple: int) -> float:
    """Pressure from the single worst subject, bounded by construction.

    The excess over the high-risk band edge is measured in multiples of that
    edge and saturates, so the dimension stops responding once one subject is
    simply extreme. One subject can never spend more than its own weight.
    """

    excess = observed_max - band_edge
    if excess <= 0:
        return 0.0
    return _unit(excess / (band_edge * multiple))


def _complexity_score(inputs: HealthInputs) -> int:
    """Return the complexity dimension as four bounded, monotone penalties.

    Every term is non-decreasing when any function becomes more complex — the
    mean rises, neither band count can fall, and the maximum cannot fall — so
    the score is non-increasing under pointwise worsening. The bands stay at
    COMPLEXITY_RISK_LOW_MAX / COMPLEXITY_RISK_MEDIUM_MAX; only the scoring
    changed. See the term budget in ``contracts`` and the owning proof in
    ``tests/test_metrics_health_recalibration.py``.
    """

    population = inputs.complexity_function_population
    return _clamp_score(
        100
        # The typical function, spent when the mean reaches the high-risk edge:
        # a project whose *average* function sits there has no typical function
        # left to defend.
        - HEALTH_COMPLEXITY_TYPICAL_WEIGHT
        * _unit(inputs.complexity_avg / COMPLEXITY_RISK_MEDIUM_MAX)
        - HEALTH_COMPLEXITY_ELEVATED_WEIGHT
        * _tail_pressure(
            count=inputs.elevated_complexity_functions,
            population=population,
            reference_permille=HEALTH_COMPLEXITY_ELEVATED_REFERENCE_PERMILLE,
            saturation_multiple=HEALTH_COMPLEXITY_TAIL_SATURATION_MULTIPLE,
        )
        - HEALTH_COMPLEXITY_EXTREME_WEIGHT
        * _tail_pressure(
            count=inputs.high_risk_functions,
            population=population,
            reference_permille=HEALTH_COMPLEXITY_EXTREME_REFERENCE_PERMILLE,
            saturation_multiple=HEALTH_COMPLEXITY_TAIL_SATURATION_MULTIPLE,
        )
        - HEALTH_COMPLEXITY_OUTLIER_WEIGHT
        * _outlier_pressure(
            observed_max=inputs.complexity_max,
            band_edge=COMPLEXITY_RISK_MEDIUM_MAX,
            multiple=HEALTH_COMPLEXITY_OUTLIER_SATURATION_MULTIPLE,
        )
    )


def _coupling_score(inputs: HealthInputs) -> int:
    """Return the coupling dimension as four bounded, monotone penalties.

    Every term is non-decreasing when any class becomes more coupled — the mean
    rises, neither band count can fall, and the maximum cannot fall — so the
    score is non-increasing under pointwise worsening. See the term budget in
    ``contracts`` and the owning proof in
    ``tests/test_metrics_health_recalibration.py``.
    """

    population = inputs.coupling_class_population
    return _clamp_score(
        100
        # The typical class, spent when the mean reaches the high-risk edge.
        - HEALTH_COUPLING_TYPICAL_WEIGHT
        * _unit(inputs.coupling_avg / COUPLING_RISK_MEDIUM_MAX)
        - HEALTH_COUPLING_ELEVATED_WEIGHT
        * _tail_pressure(
            count=inputs.elevated_coupling_classes,
            population=population,
            reference_permille=HEALTH_COUPLING_ELEVATED_REFERENCE_PERMILLE,
            saturation_multiple=HEALTH_COUPLING_TAIL_SATURATION_MULTIPLE,
        )
        - HEALTH_COUPLING_EXTREME_WEIGHT
        * _tail_pressure(
            count=inputs.high_risk_classes,
            population=population,
            reference_permille=HEALTH_COUPLING_EXTREME_REFERENCE_PERMILLE,
            saturation_multiple=HEALTH_COUPLING_TAIL_SATURATION_MULTIPLE,
        )
        - HEALTH_COUPLING_OUTLIER_WEIGHT
        * _outlier_pressure(
            observed_max=inputs.coupling_max,
            band_edge=COUPLING_RISK_MEDIUM_MAX,
            multiple=HEALTH_COUPLING_OUTLIER_SATURATION_MULTIPLE,
        )
    )


def _clone_piecewise_score(density: float) -> int:
    """Return clone dimension score (0-100) for a given clone density."""
    if density <= 0:
        return 100
    prev_d, prev_s = 0.0, 100.0
    for bp_d, bp_s in _CLONE_BREAKPOINTS:
        if density <= bp_d:
            t = (density - prev_d) / (bp_d - prev_d)
            return _clamp_score(prev_s + t * (bp_s - prev_s))
        prev_d, prev_s = bp_d, bp_s
    return 0


def compute_health(inputs: HealthInputs) -> HealthScore:
    total_clone_groups = inputs.function_clone_groups + inputs.block_clone_groups
    clone_density = _safe_div(
        float(total_clone_groups),
        max(1, inputs.files_analyzed_or_cached),
    )

    clones_score = _clone_piecewise_score(clone_density)
    complexity_score = _complexity_score(inputs)
    coupling_score = _coupling_score(inputs)
    cohesion_score = _clamp_score(
        100
        - max(0.0, inputs.cohesion_avg - 1.0) * 20
        - (inputs.low_cohesion_classes * 12)
    )
    dead_code_score = _clamp_score(100 - inputs.dead_code_items * 8)
    dependency_score = _clamp_score(
        100
        - inputs.dependency_cycles * HEALTH_DEPENDENCY_CYCLE_PENALTY
        - _dependency_tail_pressure(
            max_depth=inputs.dependency_max_depth,
            avg_depth=inputs.dependency_avg_depth,
            p95_depth=inputs.dependency_p95_depth,
        )
        * HEALTH_DEPENDENCY_DEPTH_LEVEL_PENALTY
    )
    coverage_score = _clamp_score(
        _safe_div(inputs.files_analyzed_or_cached * 100.0, max(1, inputs.files_found))
    )

    dimensions = {
        "clones": clones_score,
        "complexity": complexity_score,
        "coupling": coupling_score,
        "cohesion": cohesion_score,
        "dead_code": dead_code_score,
        "dependencies": dependency_score,
        "coverage": coverage_score,
    }

    total = sum(
        dimensions[name] * HEALTH_WEIGHTS[name] for name in sorted(HEALTH_WEIGHTS)
    )
    score = _clamp_score(total)
    return HealthScore(total=score, grade=_grade(score), dimensions=dimensions)
