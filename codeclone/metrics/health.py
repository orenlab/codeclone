"""Project health scoring."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..contracts import HEALTH_WEIGHTS
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


def compute_health(inputs: HealthInputs) -> HealthScore:
    total_clone_groups = inputs.function_clone_groups + inputs.block_clone_groups
    clone_density = _safe_div(
        float(total_clone_groups),
        max(1, inputs.files_analyzed_or_cached),
    )

    clones_score = _clamp_score(100 - clone_density * 30)
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
        - inputs.dependency_cycles * 25
        - max(0, inputs.dependency_max_depth - 6) * 4
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
