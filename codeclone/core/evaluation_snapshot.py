# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The producer-native evaluation facts (canonical epoch E3, 2026-09-27).

``core.reporting.report`` is the one scope in which the run's evaluation is
alive at once — the gate request and its result, the realized contract, the
health verdict, and the report body the document is sealed from.  It hands
them here as :class:`EvaluationInputs`, spelled by the SAME owners the report
document is built from: the gate request and result are the objects
``finalize_report_document`` receives, the contract is
``build_evaluation_contract`` over them, the health verdict is the one
projection every report surface reads (``metrics.health.health_report_fields``),
the parameters are ``realized_health_params``, and the finding verdicts and
selections are read off the report body through the one reading the ingest
oracle shares (``canonical.evaluation_rows``).  The bands of the measured
units come from the producer's own metric rows (``core.canonical_snapshot``).

The ingest oracle (``canonical.evaluation_ingest``) reads the same facts back
out of the serialized document; the equivalence pins hold the two apart.
Nothing here reaches the wire: the evaluation house is model and store state
until its own wire-revision bump.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict
from typing import TYPE_CHECKING, NamedTuple

from ..canonical.evaluation_rows import (
    EvaluationContractRecord,
    EvaluationRequestRecord,
    GateOutcomeRecord,
    HealthResultRecord,
    UnitRiskRow,
    document_selections,
    finding_verdicts,
    flatten_health_params,
)
from ..canonical.model import EvaluationFacts
from ..utils.coerce import as_int, as_mapping

if TYPE_CHECKING:
    from ..models import EvaluationContract
    from ..report.gates.evaluator import GateResult, MetricGateConfig


class EvaluationInputs(NamedTuple):
    """What this run's evaluation produced, as the document's own owners
    spell it.

    ``config`` / ``result`` are the gate request and outcome the document is
    finalized with, ``contract`` the realized contract over them, ``health``
    the health projection (``None`` when the metrics never ran) and
    ``health_params`` the realized health parameters beside it; ``body`` is
    the report body (``build_report_body``) whose ``findings`` and
    ``derived`` sections the document carries.  A named tuple rather than a
    dataclass: runtime model shapes belong to the model store, and this is a
    producer-side carrier that lives for one publication.
    """

    config: MetricGateConfig
    result: GateResult
    contract: EvaluationContract
    health: Mapping[str, object] | None
    health_params: Mapping[str, object] | None
    body: Mapping[str, object]


#: The publisher evaluates the inputs inside its own containment, so an
#: evaluation that cannot be spelled never takes the analysis down.
EvaluationInputsFactory = Callable[[], EvaluationInputs]


def _contract(inputs: EvaluationInputs) -> EvaluationContractRecord:
    contract = inputs.contract
    return EvaluationContractRecord(
        gate_thresholds_digest=contract.gate_thresholds_digest,
        health_algorithm_revision=contract.health_algorithm_revision,
        gate_algorithm_revision=contract.gate_algorithm_revision,
        gate_lane_matrix_version=contract.gate_lane_matrix_version,
        health_input_manifest_version=contract.health_input_manifest_version,
        health_input_lanes=tuple(contract.health_input_lanes),
        active_gate_lane_requirements=tuple(
            (gate, tuple(lanes))
            for gate, lanes in contract.active_gate_lane_requirements
        ),
        health_params=(
            ()
            if inputs.health_params is None
            else flatten_health_params(inputs.health_params)
        ),
    )


def _health(
    health: Mapping[str, object], contract: EvaluationContractRecord
) -> HealthResultRecord:
    """The health verdict as ``health_report_fields`` projects it: the score,
    grade and dimensions a population carries, or all three withheld."""
    dimensions = health.get("dimensions")
    score = health.get("score")
    grade = health.get("grade")
    return HealthResultRecord(
        score=score if isinstance(score, int) else None,
        grade=grade if isinstance(grade, str) else None,
        dimensions=(
            None
            if dimensions is None
            else tuple(
                sorted(
                    (str(name), as_int(value))
                    for name, value in as_mapping(dimensions).items()
                )
            )
        ),
        population=str(health.get("population", "")),
        health_algorithm_revision=contract.health_algorithm_revision,
        health_input_manifest_version=contract.health_input_manifest_version,
    )


def evaluation_facts_from_producers(
    inputs: EvaluationInputs, bands: frozenset[UnitRiskRow]
) -> EvaluationFacts:
    """The evaluation house of one run, straight off its evaluation inputs and
    the bands its metric producers decided."""
    contract = _contract(inputs)
    digest = contract.gate_thresholds_digest
    result = inputs.result
    return EvaluationFacts(
        evaluation_contract=contract,
        evaluation_request=EvaluationRequestRecord(
            gate_thresholds_digest=digest,
            # Every term of the request as uttered; the record refuses a term
            # that is missing or of the wrong type.
            terms=tuple(
                (name, value)
                for name, value in sorted(asdict(inputs.config).items())
                if isinstance(value, int)
            ),
        ),
        gate_outcome=GateOutcomeRecord(
            gate_thresholds_digest=digest,
            exit_code=result.exit_code,
            reasons=tuple(result.reasons),
            required_lanes=tuple(result.required_lanes),
            unavailable_lanes=tuple(result.unavailable_lanes),
        ),
        health_result=(
            None if inputs.health is None else _health(inputs.health, contract)
        ),
        finding_evaluation=finding_verdicts(as_mapping(inputs.body.get("findings"))),
        unit_risk_result=bands,
        hotlist_selection=document_selections(as_mapping(inputs.body.get("derived"))),
    )


def evaluation_house(
    evaluation: EvaluationInputsFactory | None, bands: frozenset[UnitRiskRow]
) -> EvaluationFacts:
    """The evaluation house the publisher stores: the run's evaluation when it
    was handed one — evaluated here, inside the publication's containment —
    and the unwitnessed empty house when it was not."""
    if evaluation is None:
        return EvaluationFacts()
    return evaluation_facts_from_producers(evaluation(), bands)


__all__ = [
    "EvaluationInputs",
    "EvaluationInputsFactory",
    "evaluation_facts_from_producers",
    "evaluation_house",
]
