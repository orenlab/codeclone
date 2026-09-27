# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Canonical epoch E3 (2026-09-27): the evaluation tier's families.

Every row here states what THIS run concluded under the evaluation it was
given — the policy it was evaluated under, the verdicts that policy produced —
and nothing a later session concluded about it.  The report document already
publishes all of it: the realized evaluation contract and the gate request and
outcome (``evaluation`` / ``contracts.evaluation``), the health verdict
(``metrics.families.health``), the band of every measured unit (the ``risk``
word of ``metrics.families.{complexity,coupling,cohesion}.items``), the verdict
on every published finding (``severity`` / ``confidence`` / ``priority`` /
``clone_type``, which the analysis skeletons of ``finding_projection``
deliberately do not carry) and the document's own selections
(``derived.hotlists`` and the order of ``derived.suggestions``).

The families bind to the five closed productions of the ratified grammar
(``codeclone.canonical.grammar.SEMANTIC_KIND_TIERS``) and to nothing new:

* the realized contract is ``evaluation_contract``, the request (the
  thresholds as uttered) ``evaluation_request``, the gate result
  ``gate_outcome`` — one record each per evaluated run, joined by the
  request digest the document already names (``gate_thresholds_digest``);
* the health verdict is ``health_result``, and so is the band of one unit:
  a band is decided by the health parameters (``EVALUATION_HEALTH_PARAM_OWNERS``
  registers the band edges beside the health weights);
* the verdict on a finding and the document's selections are ``verdict``.

What is NOT a row, named so it cannot rot: a gate outcome under any request
other than the run's own (``evaluate_gates`` realizes a (run, request) pair in
a session, and the session tier is not created, ruling 2026-09-18); every
run-against-run verdict (``compare_runs``, the patch contract, the PR summary,
the blast radius level) — none of them is a fact of ONE run; the MCP surface's
``priority_score`` / ``priority_factors`` (weights the surface owns, derived
from stored inputs); the text of a suggestion (remediation, not evaluation).
The health DELTA is not here either: it is a comparison fact about an
evaluation quantity (``grammar.field_morphology``) and lives in the comparison
house as a delta annotation of ``health_result``.

Field names carry no comparison marker by construction (the registry gate
refuses one): ``baseline_diff_available`` is the presence of that delta
annotation, never a field here.

Nothing in this module reaches the wire: until the wire-revision bump the
evaluation house is internal model and store state (ruling 2026-09-26).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final, cast

from codeclone.canonical.comparison_rows import OBSERVATION_LANES
from codeclone.canonical.errors import CanonicalModelError
from codeclone.canonical.identity import SymbolId
from codeclone.contracts import (
    ExitCode,
    ObservedPopulation,
    population_carries_score,
)
from codeclone.domain.quality import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    EFFORT_WEIGHT,
    HEALTH_GRADES,
    RISK_HIGH,
    RISK_LOW,
    RISK_MEDIUM,
    SEVERITY_RANK,
)
from codeclone.findings.ids import clone_group_id

#: The gate request terms and the type each is uttered in — the fields of
#: ``report.gates.evaluator.MetricGateConfig``, mirrored and pinned against
#: the dataclass by test.  ``bool`` is never an ``int`` here.
GATE_REQUEST_TERMS: Final[dict[str, type]] = {
    "coverage_min": int,
    "fail_cohesion": int,
    "fail_complexity": int,
    "fail_coupling": int,
    "fail_cycles": bool,
    "fail_dead_code": bool,
    "fail_health": int,
    "fail_on_api_break": bool,
    "fail_on_authority_violation": bool,
    "fail_on_docstring_regression": bool,
    "fail_on_new": bool,
    "fail_on_new_metrics": bool,
    "fail_on_truncated_run": bool,
    "fail_on_typing_regression": bool,
    "fail_on_unresolved_dead_code": bool,
    "fail_on_untested_hotspots": bool,
    "fail_threshold": int,
    "min_docstring_coverage": int,
    "min_typing_coverage": int,
}

#: The three outcomes a gate evaluation has (``contracts.ExitCode``): it
#: passed, a gate failed, or a lane a requested gate reads was unavailable.
GATE_PASSED: Final = int(ExitCode.SUCCESS)
GATE_LANE_UNAVAILABLE: Final = int(ExitCode.CONTRACT_ERROR)
GATE_FAILED: Final = int(ExitCode.GATING_FAILURE)
GATE_EXIT_CODES: Final = (GATE_PASSED, GATE_LANE_UNAVAILABLE, GATE_FAILED)
#: The one reason spelling of an unavailable lane
#: (``report.gates.evaluator``), pinned against the evaluator by test.
LANE_UNAVAILABLE_REASON: Final = "lane:unavailable:{lane}"

#: The seven lanes health is computed from (``report.gates.evaluator.
#: HEALTH_INPUT_LANES``), mirrored and pinned by test.
HEALTH_INPUT_LANES: Final = (
    "clones.blocks",
    "clones.functions",
    "coupling_cohesion_observations",
    "dead_code",
    "dependencies",
    "module_identity",
    "risk_observations",
)
#: The health dimensions a scored verdict states (``metrics.health``),
#: pinned against the producer by test.
HEALTH_DIMENSIONS: Final = (
    "clones",
    "cohesion",
    "complexity",
    "coupling",
    "coverage",
    "dead_code",
    "dependencies",
)
#: ``contracts.ObservedPopulation``, pinned against the literal by test.
OBSERVED_POPULATIONS: Final = (
    "complete_empty",
    "complete_nonempty",
    "partial",
    "unmeasured",
)
HEALTH_SCORE_MAX: Final = 100

#: The measured units a band is decided for, named by the document's metric
#: family, and the three bands (``domain.quality``).
RISK_UNIT_DIMENSIONS: Final = ("cohesion", "complexity", "coupling")
RISK_BANDS: Final = (RISK_HIGH, RISK_LOW, RISK_MEDIUM)

SEVERITIES: Final = tuple(sorted(SEVERITY_RANK))
CONFIDENCES: Final = (CONFIDENCE_HIGH, CONFIDENCE_LOW, CONFIDENCE_MEDIUM)
#: ``report.suggestions.CloneType``, pinned against the literal by test.
CLONE_TYPES: Final = ("Type-1", "Type-2", "Type-3", "Type-4")
#: Every published clone finding id starts with one of these (the three
#: clone kinds, spelled through the one id owner).
CLONE_FINDING_PREFIXES: Final = tuple(
    clone_group_id(kind, "") for kind in ("block", "function", "segment")
)

#: The document's selections: its four hotlists (``derived.hotlists``,
#: ``<name>_ids``) and the order of its suggestions (``derived.suggestions``).
HOTLISTS: Final = (
    "highest_spread",
    "most_actionable",
    "production_hotspot",
    "suggestions",
    "test_fixture_hotspot",
)


def _require_member(value: object, vocabulary: tuple[str, ...], what: str) -> None:
    if not isinstance(value, str) or value not in vocabulary:
        raise CanonicalModelError(f"unknown {what}: {value!r}")


def _require_text(value: object, what: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise CanonicalModelError(f"{what} must be a non-empty string: {value!r}")


def _require_int(
    value: object, what: str, *, floor: int, ceiling: int | None = None
) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CanonicalModelError(f"{what} must be an int: {value!r}")
    if value < floor or (ceiling is not None and value > ceiling):
        raise CanonicalModelError(f"{what} must lie in [{floor}, {ceiling}]: {value}")


def _require_sorted_unique(values: tuple[str, ...], what: str) -> None:
    if values != tuple(sorted(set(values))):
        raise CanonicalModelError(f"{what} must be sorted and unique: {values!r}")


def _require_lanes(lanes: tuple[str, ...], what: str) -> None:
    for lane in lanes:
        _require_member(lane, OBSERVATION_LANES, what)
    _require_sorted_unique(lanes, what)


def _require_number(value: object, what: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CanonicalModelError(f"{what} must be a number: {value!r}")
    if not math.isfinite(value):
        raise CanonicalModelError(f"{what} must be finite: {value!r}")


@dataclass(frozen=True, slots=True, kw_only=True)
class EvaluationRequestRecord:
    """The request this run was evaluated under, ONE per evaluated run.

    ``terms`` is the request as uttered — every gate term of the closed
    vocabulary, by name — and ``gate_thresholds_digest`` its identity as the
    document names it (``contracts.evaluation.gate_thresholds_digest``,
    ``sha256`` of the canonical request by its one owner
    ``report.document.integrity.build_evaluation_contract``).
    """

    gate_thresholds_digest: str
    terms: tuple[tuple[str, int | bool], ...]

    def __post_init__(self) -> None:
        _require_text(self.gate_thresholds_digest, "request digest")
        names = tuple(name for name, _value in self.terms)
        if names != tuple(sorted(GATE_REQUEST_TERMS)):
            raise CanonicalModelError(
                f"the request states {list(names)!r}, not exactly the gate terms"
            )
        for name, value in self.terms:
            if type(value) is not GATE_REQUEST_TERMS[name]:
                raise CanonicalModelError(
                    f"request term {name!r} must be a "
                    f"{GATE_REQUEST_TERMS[name].__name__}: {value!r}"
                )


@dataclass(frozen=True, slots=True, kw_only=True)
class EvaluationContractRecord:
    """The realized evaluation contract of this run, ONE per evaluated run.

    The document's ``contracts.evaluation`` whole (the revisions and matrix
    versions health and the gates were computed under, the health input
    lanes this run enabled, the lanes each requested gate reads) and the
    health parameters the verdict used (``integrity.semantic.
    realized_contracts.evaluation.health.params``, flattened to dotted names
    — the reference permilles, the weights and the band edges as values).
    ``health_params`` is empty exactly when no health verdict was computed;
    its digest is not stored — it is ``sha256`` of the canonical parameter
    mapping by its one owner (``report.document.integrity``).
    """

    gate_thresholds_digest: str
    health_algorithm_revision: str
    gate_algorithm_revision: str
    gate_lane_matrix_version: str
    health_input_manifest_version: str
    health_input_lanes: tuple[str, ...]
    active_gate_lane_requirements: tuple[tuple[str, tuple[str, ...]], ...]
    health_params: tuple[tuple[str, int | float], ...]

    def __post_init__(self) -> None:
        what = "evaluation contract"
        for name in (
            "gate_thresholds_digest",
            "health_algorithm_revision",
            "gate_algorithm_revision",
            "gate_lane_matrix_version",
            "health_input_manifest_version",
        ):
            _require_text(getattr(self, name), f"{what} {name}")
        _require_lanes(self.health_input_lanes, f"{what} health input lane")
        gates = tuple(gate for gate, _lanes in self.active_gate_lane_requirements)
        _require_sorted_unique(gates, f"{what} gate names")
        for gate, lanes in self.active_gate_lane_requirements:
            _require_text(gate, f"{what} gate name")
            _require_lanes(lanes, f"{what} lane of gate {gate!r}")
        names = tuple(name for name, _value in self.health_params)
        _require_sorted_unique(names, f"{what} health parameter names")
        for name, value in self.health_params:
            _require_text(name, f"{what} health parameter name")
            _require_number(value, f"{what} health parameter {name!r}")


@dataclass(frozen=True, slots=True, kw_only=True)
class GateOutcomeRecord:
    """The gate result of this run under its own request, ONE per evaluated
    run, keyed by the request digest.

    The three outcomes are the evaluator's: passed (no reason), a gate failed
    (its reasons, in the evaluator's order), a requested gate's lane was
    unavailable (one ``lane:unavailable:<lane>`` reason per lane, nothing
    else).  ``would_fail`` is not stored: it is ``exit_code != 0``.
    """

    gate_thresholds_digest: str
    exit_code: int
    reasons: tuple[str, ...]
    required_lanes: tuple[str, ...]
    unavailable_lanes: tuple[str, ...]

    def __post_init__(self) -> None:
        what = "gate outcome"
        _require_text(self.gate_thresholds_digest, f"{what} request digest")
        if self.exit_code not in GATE_EXIT_CODES:
            raise CanonicalModelError(f"unknown {what} exit code: {self.exit_code!r}")
        for reason in self.reasons:
            _require_text(reason, f"{what} reason")
        _require_lanes(self.required_lanes, f"{what} required lane")
        _require_lanes(self.unavailable_lanes, f"{what} unavailable lane")
        if not set(self.unavailable_lanes) <= set(self.required_lanes):
            raise CanonicalModelError(
                f"{what} names unavailable lanes no requested gate reads"
            )
        if (self.exit_code == GATE_PASSED) == bool(self.reasons):
            raise CanonicalModelError(
                f"{what} {self.exit_code} contradicts its reasons {self.reasons!r}"
            )
        if (self.exit_code == GATE_LANE_UNAVAILABLE) != bool(self.unavailable_lanes):
            raise CanonicalModelError(
                f"{what} {self.exit_code} contradicts its unavailable lanes"
            )
        if self.unavailable_lanes and self.reasons != tuple(
            LANE_UNAVAILABLE_REASON.format(lane=lane) for lane in self.unavailable_lanes
        ):
            raise CanonicalModelError(
                f"{what} for unavailable lanes states other reasons {self.reasons!r}"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class HealthResultRecord:
    """The health verdict of this run, ONE per run whose metrics ran.

    Dated by its own contract: the health algorithm revision and input
    manifest it was computed under ride the row (the model proves them equal
    to the evaluation contract's).  A population that carries no score
    (``contracts.population_carries_score``) withholds all three of score,
    grade and dimensions — the refusal is the population, never a zero.
    """

    score: int | None
    grade: str | None
    dimensions: tuple[tuple[str, int], ...] | None
    population: str
    health_algorithm_revision: str
    health_input_manifest_version: str

    def __post_init__(self) -> None:
        what = "health result"
        _require_member(self.population, OBSERVED_POPULATIONS, f"{what} population")
        _require_text(self.health_algorithm_revision, f"{what} algorithm revision")
        _require_text(self.health_input_manifest_version, f"{what} input manifest")
        scored = population_carries_score(cast("ObservedPopulation", self.population))
        stated = (
            self.score is not None,
            self.grade is not None,
            self.dimensions is not None,
        )
        if stated != (scored, scored, scored):
            raise CanonicalModelError(
                f"{what} of a {self.population!r} population must "
                f"{'state' if scored else 'withhold'} score, grade and dimensions"
            )
        if self.score is None or self.dimensions is None:
            return
        _require_int(self.score, f"{what} score", floor=0, ceiling=HEALTH_SCORE_MAX)
        _require_member(self.grade, HEALTH_GRADES, f"{what} grade")
        if tuple(name for name, _value in self.dimensions) != HEALTH_DIMENSIONS:
            raise CanonicalModelError(
                f"{what} dimensions are not exactly {list(HEALTH_DIMENSIONS)!r}"
            )
        for name, value in self.dimensions:
            _require_int(value, f"{what} {name}", floor=0, ceiling=HEALTH_SCORE_MAX)


@dataclass(frozen=True, slots=True, kw_only=True)
class UnitRiskRow:
    """The band of one measured unit, keyed by ``(dimension, symbol,
    start_line)`` — the declaration-site key of the analysis risk facts.

    The band is the word the run decided under its health parameters; it is
    stored, not re-derived, so a unit keeps the verdict it was given even
    after the parameters move.
    """

    dimension: str
    symbol: SymbolId
    start_line: int
    band: str

    def __post_init__(self) -> None:
        _require_member(self.dimension, RISK_UNIT_DIMENSIONS, "unit risk dimension")
        _require_int(self.start_line, "unit risk site", floor=1)
        _require_member(self.band, RISK_BANDS, "unit risk band")


def finding_priority_is_admissible(severity: str, priority: float) -> bool:
    """Whether ``priority`` is the document's priority of a finding of this
    severity under SOME effort — ``severity rank / effort weight``, the one
    formula of ``report.document._common._priority`` and
    ``report.suggestions._priority``."""
    return any(
        priority == float(SEVERITY_RANK[severity]) / float(weight)
        for weight in EFFORT_WEIGHT.values()
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class FindingEvaluationRow:
    """The verdict on one published finding, keyed by its published id.

    ``severity`` / ``confidence`` / ``priority`` / ``clone_type`` are the
    four group keys the analysis skeleton leaves to evaluation
    (``finding_projection.UNPROJECTED_GROUP_KEYS``).  A clone finding carries
    its clone type and no other finding does.
    """

    finding_id: str
    severity: str
    confidence: str
    priority: float
    clone_type: str | None

    def __post_init__(self) -> None:
        what = f"verdict on {self.finding_id!r}"
        _require_text(self.finding_id, "evaluated finding id")
        _require_member(self.severity, SEVERITIES, f"{what} severity")
        _require_member(self.confidence, CONFIDENCES, f"{what} confidence")
        _require_number(self.priority, f"{what} priority")
        if not finding_priority_is_admissible(self.severity, self.priority):
            raise CanonicalModelError(
                f"{what}: priority {self.priority!r} is no effort's priority "
                f"of a {self.severity!r} finding"
            )
        is_clone = self.finding_id.startswith(CLONE_FINDING_PREFIXES)
        if is_clone != (self.clone_type is not None):
            raise CanonicalModelError(
                f"{what}: a clone type belongs to clone findings only "
                f"({self.clone_type!r})"
            )
        if self.clone_type is not None:
            _require_member(self.clone_type, CLONE_TYPES, f"{what} clone type")


@dataclass(frozen=True, slots=True, kw_only=True)
class HotlistRow:
    """One finding at one rank of one of the document's selections, keyed by
    ``(hotlist, rank)``; ranks count from one."""

    hotlist: str
    rank: int
    finding_id: str

    def __post_init__(self) -> None:
        _require_member(self.hotlist, HOTLISTS, "hotlist")
        _require_int(self.rank, f"{self.hotlist} rank", floor=1)
        _require_text(self.finding_id, f"{self.hotlist} finding id")


__all__ = [
    "CLONE_FINDING_PREFIXES",
    "CLONE_TYPES",
    "CONFIDENCES",
    "GATE_EXIT_CODES",
    "GATE_FAILED",
    "GATE_LANE_UNAVAILABLE",
    "GATE_PASSED",
    "GATE_REQUEST_TERMS",
    "HEALTH_DIMENSIONS",
    "HEALTH_INPUT_LANES",
    "HEALTH_SCORE_MAX",
    "HOTLISTS",
    "LANE_UNAVAILABLE_REASON",
    "OBSERVED_POPULATIONS",
    "RISK_BANDS",
    "RISK_UNIT_DIMENSIONS",
    "SEVERITIES",
    "EvaluationContractRecord",
    "EvaluationRequestRecord",
    "FindingEvaluationRow",
    "GateOutcomeRecord",
    "HealthResultRecord",
    "HotlistRow",
    "UnitRiskRow",
    "finding_priority_is_admissible",
]
