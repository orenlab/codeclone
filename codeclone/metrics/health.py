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
    high_risk_functions: int
    coupling_avg: float
    coupling_max: int
    high_risk_classes: int
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
    complexity_score = _clamp_score(
        100
        - (inputs.complexity_avg * 2.5)
        - (inputs.complexity_max * 1.2)
        - (inputs.high_risk_functions * 8)
    )
    coupling_score = _clamp_score(
        100
        - (inputs.coupling_avg * 7)
        - (inputs.coupling_max * 2)
        - (inputs.high_risk_classes * 8)
    )
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
