# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import dataclass, replace
from math import ceil, fsum, ulp
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
    HEALTH_DEPENDENCY_DEFERRED_CYCLE_PENALTY,
    HEALTH_DEPENDENCY_DEPTH_AVG_MULTIPLIER,
    HEALTH_DEPENDENCY_DEPTH_LEVEL_PENALTY,
    HEALTH_DEPENDENCY_DEPTH_P95_MARGIN,
    HEALTH_WEIGHTS,
    ObservedPopulation,
    observed_population,
    population_carries_score,
)
from ..contracts.errors import ContractInvariantError
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
    #: Cycles whose import-time edges still cycle: they can crash the
    #: interpreter at import. Split from the raw total on purpose — there is no
    #: kind-agnostic cycle input any more, so a caller cannot accidentally
    #: charge a deferred cycle at the import rate by passing one number.
    import_dependency_cycles: int
    #: Cycles closed only by deferred, lazy, or typing edges. Real, but they
    #: cannot fail an import. Priced by their own constant.
    deferred_dependency_cycles: int
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


def _weight_sum_slack(count: int) -> float:
    """Return how far a correct weight vector's float total may sit from 1.0.

    Not a tuning knob and not a comfort margin: a bound re-derived from how
    the weights are stored. Each is written as a decimal and kept as the
    nearest double, so it carries at most half an ulp of its own magnitude,
    and ``fsum`` rounds the exact total once more, at most half an ulp of 1.0.
    For ``count`` weights whose true sum is one that bounds the drift at
    ``count + 1`` half-ulps -- around 1e-15, twelve orders below the smallest
    slip a human can type into a weight. Widening it past that stops being a
    representation bound and starts admitting vectors that are simply wrong.
    """

    return (count + 1) * ulp(1.0) / 2


def _convex_weights() -> dict[str, float]:
    """Return ``HEALTH_WEIGHTS`` once the aggregate is allowed to use it.

    ``compute_health`` forms a raw weighted sum -- there is no division by the
    weight total anywhere -- so "a health score is a number in [0, 100]" is a
    property of the weight vector, not of the arithmetic. It holds while the
    vector is a convex combination, and both halves carry load:

    * a total above one inflates every score, and ``_clamp_score`` then folds
      the overflow onto a perfectly ordinary-looking 100;
    * a negative weight escapes the range even at a total of exactly one, and
      it inverts that dimension -- more debt reads as more health.

    Measured on this tree: at ``coupling = -0.10, dead_code = 0.30`` (total
    1.0) a repository whose coupling dimension falls from 100 to 0 sees its
    raw aggregate *rise* from 100.00 to 110.00.

    The check reads the same binding the sum consumes and hands it back, so
    the validated mapping and the weighted one cannot drift apart.
    """

    weights = HEALTH_WEIGHTS
    negative = sorted(name for name, weight in weights.items() if weight < 0.0)
    if negative:
        raise ContractInvariantError(
            "HEALTH_WEIGHTS must never be negative; "
            f"got a negative weight for {', '.join(negative)}."
        )
    total = fsum(weights[name] for name in sorted(weights))
    if abs(total - 1.0) > _weight_sum_slack(len(weights)):
        raise ContractInvariantError(
            f"HEALTH_WEIGHTS must sum to 1.0; got {total!r} "
            f"across {len(weights)} dimensions."
        )
    return weights


def _observed_population(inputs: HealthInputs) -> ObservedPopulation:
    """Read this run's population state off its two counters.

    Consults the owner instead of restating the rule. ``observed_population``
    beside the models is the only implementation, because health, the gates,
    the baseline publisher and every renderer decide on the same fact, and a
    second copy here would be a second semantics for one word.
    """

    return observed_population(
        files_found=inputs.files_found,
        files_analyzed_or_cached=inputs.files_analyzed_or_cached,
    )


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
        - inputs.import_dependency_cycles * HEALTH_DEPENDENCY_CYCLE_PENALTY
        - inputs.deferred_dependency_cycles * HEALTH_DEPENDENCY_DEFERRED_CYCLE_PENALTY
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

    population = _observed_population(inputs)
    if not population_carries_score(population):
        # No observed population, so there is no evidence of health to report.
        # The weighted sum here would be 90/A — six counter-driven dimensions
        # see an empty population and report no debt — which is an assertion
        # of cleanliness about code that was never opened, or about code that
        # does not exist. Both absences withhold the number; which absence it
        # was travels in ``population``. Refusing is not a recalibration: no
        # weight, band, or reference moves, and a run that read even one file
        # takes the ordinary path below unchanged.
        return HealthScore(
            total=0,
            grade=_grade(0),
            dimensions=dimensions,
            population=population,
        )

    weights = _convex_weights()
    total = sum(dimensions[name] * weights[name] for name in sorted(weights))
    score = _clamp_score(total)
    return HealthScore(
        total=score,
        grade=_grade(score),
        dimensions=dimensions,
        population=population,
    )


#: Placeholder inputs for a lane that produced nothing. Every field is zero
#: because nothing was observed, not because zero was observed — which is
#: exactly why ``health_not_computed`` states its population instead of
#: deriving it from these numbers.
_NO_OBSERVATION_INPUTS: HealthInputs = HealthInputs(
    files_found=0,
    files_analyzed_or_cached=0,
    function_clone_groups=0,
    block_clone_groups=0,
    complexity_avg=0.0,
    complexity_max=0,
    high_risk_functions=0,
    elevated_complexity_functions=0,
    complexity_function_population=0,
    coupling_avg=0.0,
    coupling_max=0,
    high_risk_classes=0,
    elevated_coupling_classes=0,
    coupling_class_population=0,
    cohesion_avg=0.0,
    low_cohesion_classes=0,
    import_dependency_cycles=0,
    deferred_dependency_cycles=0,
    dependency_max_depth=0,
    dependency_avg_depth=0.0,
    dependency_p95_depth=0,
    dead_code_items=0,
)


def health_not_computed() -> HealthScore:
    """The score to report when the health lane never executed.

    ``--skip-metrics``, or a metric result that is not a ``HealthScore`` at
    all. The zeros this is built from are placeholders, not observations, so
    the state is *declared* rather than derived from them: deriving would read
    ``files_found == 0`` and call an unrun lane ``complete_empty``, which is
    the conflation this split removes, reintroduced from the other end.

    ``unmeasured`` is the honest word here — it is the state that means "no
    evidence", and a lane that did not run produced none.
    """

    return replace(compute_health(_NO_OBSERVATION_INPUTS), population="unmeasured")


def health_report_fields(health: HealthScore) -> dict[str, object]:
    """Project one score into the fields every report surface reads.

    The population state turns into a refusal here and nowhere else. ``score``
    and ``grade`` are not "0" and "F" for a run that opened no file — 0 is a
    measured value, and the six counter-driven dimensions reporting 100 are
    the same claim broken into parts. They are ``None``: no measurement was
    made, so no number is reported. An honestly empty scope is withheld by the
    same rule and for the symmetric reason: 90/A would be a verdict of
    excellence about code that does not exist.

    ``population`` rides every run, not only the refused ones, and it is what
    keeps the two refusals apart downstream — a surface that inferred the
    refusal from ``score is None`` would know that something is absent but not
    which absence, and could not word it. A consumer that has to infer the
    state from a missing key learns nothing; a consumer that reads the key
    learns the fact. This is also the single owner of that fact for the whole
    report tree: renderers read it from the document and never re-derive it
    from the file counters beside it.
    """

    if not population_carries_score(health.population):
        return {
            "score": None,
            "grade": None,
            "dimensions": None,
            "population": health.population,
        }
    return {
        "score": health.total,
        "grade": health.grade,
        "dimensions": dict(health.dimensions),
        "population": health.population,
    }
