# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The evaluation half of the ingest oracle (canonical epoch E3, 2026-09-27).

The report document already publishes this run's evaluation: the gate request
and outcome (``evaluation``), the realized evaluation contract
(``contracts.evaluation``) and its health parameters
(``integrity.semantic.realized_contracts.evaluation.health``), the health
verdict (``metrics.families.health.summary``, present as a verdict exactly
when the document's own population says the health producer completed), the
band of every measured unit (the ``risk`` word of the three design metric
families' items), the verdict on every finding and the document's selections.
This module reads each family from the container the document builder writes
it to — the oracle side of the shadow; the producer-native snapshot
(``core.evaluation_snapshot``) is the other side.

A document that carries no ``evaluation`` section was never evaluated, and
the answer is the EMPTY house — "not witnessed by this artifact".  A section
that is present is read whole; a malformed member is a typed refusal.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from codeclone.canonical.errors import LegacyIngestError
from codeclone.canonical.evaluation_rows import (
    RISK_UNIT_DIMENSIONS,
    EvaluationContractRecord,
    EvaluationRequestRecord,
    GateOutcomeRecord,
    HealthResultRecord,
    UnitRiskRow,
    document_selections,
    finding_verdicts,
    flatten_health_params,
)
from codeclone.canonical.model import EvaluationFacts
from codeclone.canonical.semantic_grammar import IdentityIndex, parse_symbol

#: The producer state under which the document states a health verdict.
_HEALTH_COMPLETE = "complete"


def _mapping(value: object, where: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise LegacyIngestError(f"{where} is not an object")
    return cast("Mapping[str, object]", value)


def _sequence(value: object, where: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise LegacyIngestError(f"{where} is not an array")
    return value


def _field(container: Mapping[str, object], key: str, where: str) -> object:
    if key not in container:
        raise LegacyIngestError(f"{where} is missing {key!r}")
    return container[key]


def _member(
    container: Mapping[str, object], key: str, where: str
) -> Mapping[str, object]:
    return _mapping(_field(container, key, where), f"{where}.{key}")


def _text(container: Mapping[str, object], key: str, where: str) -> str:
    value = _field(container, key, where)
    if not isinstance(value, str):
        raise LegacyIngestError(f"{where}.{key} is not a string")
    return value


def _texts(container: Mapping[str, object], key: str, where: str) -> tuple[str, ...]:
    return _strings(_field(container, key, where), f"{where}.{key}")


def _strings(value: object, where: str) -> tuple[str, ...]:
    values = _sequence(value, where)
    if not all(isinstance(item, str) for item in values):
        raise LegacyIngestError(f"{where} carries a non-string")
    return tuple(str(item) for item in values)


def _number(container: Mapping[str, object], key: str, where: str) -> int:
    value = _field(container, key, where)
    if isinstance(value, bool) or not isinstance(value, int):
        raise LegacyIngestError(f"{where}.{key} is not an int")
    return value


def _contract(
    contract: Mapping[str, object], health_params: tuple[tuple[str, int | float], ...]
) -> EvaluationContractRecord:
    where = "contracts.evaluation"
    return EvaluationContractRecord(
        gate_thresholds_digest=_text(contract, "gate_thresholds_digest", where),
        health_algorithm_revision=_text(contract, "health_algorithm_revision", where),
        gate_algorithm_revision=_text(contract, "gate_algorithm_revision", where),
        gate_lane_matrix_version=_text(contract, "gate_lane_matrix_version", where),
        health_input_manifest_version=_text(
            contract, "health_input_manifest_version", where
        ),
        health_input_lanes=_texts(contract, "health_input_lanes", where),
        active_gate_lane_requirements=_requirements(
            _field(contract, "active_gate_lane_requirements", where), where
        ),
        health_params=health_params,
    )


def _requirements(value: object, where: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    requirements: list[tuple[str, tuple[str, ...]]] = []
    for pair in _sequence(value, f"{where}.active_gate_lane_requirements"):
        gate, lanes = _sequence(pair, f"{where} requirement")
        if not isinstance(gate, str):
            raise LegacyIngestError(f"{where} requirement names no gate")
        requirements.append((gate, _strings(lanes, f"{where}.{gate}")))
    return tuple(requirements)


def _request(request: Mapping[str, object], digest: str) -> EvaluationRequestRecord:
    terms: list[tuple[str, int | bool]] = []
    for name, value in sorted(request.items()):
        if not isinstance(value, int):
            raise LegacyIngestError(f"evaluation.request.{name} is not an int")
        terms.append((name, value))
    return EvaluationRequestRecord(gate_thresholds_digest=digest, terms=tuple(terms))


def _outcome(outcome: Mapping[str, object], digest: str) -> GateOutcomeRecord:
    where = "evaluation.outcome"
    return GateOutcomeRecord(
        gate_thresholds_digest=digest,
        exit_code=_number(outcome, "exit_code", where),
        reasons=_texts(outcome, "reasons", where),
        required_lanes=_texts(outcome, "required_lanes", where),
        unavailable_lanes=_texts(outcome, "unavailable_lanes", where),
    )


def _semantic(document: Mapping[str, object]) -> Mapping[str, object]:
    """The document's semantic identity block (``integrity.semantic``): where
    it states which producers completed and which contracts they realized."""
    return _member(_member(document, "integrity", "document"), "semantic", "integrity")


def _realized_health_params(
    semantic: Mapping[str, object],
) -> tuple[tuple[str, int | float], ...]:
    """The realized health parameters, flattened — empty when the document
    realized no health contract (the health producer did not complete)."""
    realized = _member(
        _member(semantic, "realized_contracts", "semantic"),
        "evaluation",
        "realized_contracts",
    )
    if "health" not in realized:
        return ()
    health = _member(realized, "health", "realized_contracts.evaluation")
    return flatten_health_params(_member(health, "params", "realized health"))


def _health_completed(semantic: Mapping[str, object]) -> bool:
    population = _member(semantic, "population", "semantic")
    producers = _member(population, "producers", "semantic.population")
    return producers.get("health") == _HEALTH_COMPLETE


def _health(
    families: Mapping[str, object], contract: EvaluationContractRecord
) -> HealthResultRecord:
    where = "metrics.families.health.summary"
    summary = _member(_member(families, "health", "metrics.families"), "summary", where)
    dimensions = _field(summary, "dimensions", where)
    score = _field(summary, "score", where)
    grade = _field(summary, "grade", where)
    return HealthResultRecord(
        score=None if score is None else _number(summary, "score", where),
        grade=None if grade is None else _text(summary, "grade", where),
        dimensions=(
            None
            if dimensions is None
            else tuple(
                sorted(
                    (name, _number(_mapping(dimensions, where), name, where))
                    for name in _mapping(dimensions, where)
                )
            )
        ),
        population=_text(summary, "population", where),
        health_algorithm_revision=contract.health_algorithm_revision,
        health_input_manifest_version=contract.health_input_manifest_version,
    )


def _unit_bands(
    families: Mapping[str, object], index: IdentityIndex
) -> frozenset[UnitRiskRow]:
    """Every measured unit's band, read off the document's items and named
    through the one symbol-key owner (``semantic_grammar.parse_symbol``)."""
    bands: set[UnitRiskRow] = set()
    for dimension in RISK_UNIT_DIMENSIONS:
        where = f"metrics.families.{dimension}"
        items = _field(_member(families, dimension, "metrics.families"), "items", where)
        for item in _sequence(items, where):
            unit = _mapping(item, f"{where} item")
            bands.add(
                UnitRiskRow(
                    dimension=dimension,
                    symbol=parse_symbol(index, _text(unit, "qualname", where), where),
                    start_line=_number(unit, "start_line", where),
                    band=_text(unit, "risk", where),
                )
            )
    return frozenset(bands)


def evaluation_facts_from_document(
    document: Mapping[str, object], index: IdentityIndex
) -> EvaluationFacts:
    """The evaluation house the report document publishes — or the empty
    house for a document that was never evaluated."""
    if "evaluation" not in document:
        return EvaluationFacts()
    evaluation = _mapping(document["evaluation"], "evaluation")
    contracts = _member(document, "contracts", "document")
    contract_section = _member(contracts, "evaluation", "contracts")
    digest = _text(contract_section, "gate_thresholds_digest", "contracts.evaluation")
    semantic = _semantic(document)
    contract = _contract(contract_section, _realized_health_params(semantic))
    families = _member(_member(document, "metrics", "document"), "families", "metrics")
    return EvaluationFacts(
        evaluation_contract=contract,
        evaluation_request=_request(
            _member(evaluation, "request", "evaluation"), digest
        ),
        gate_outcome=_outcome(_member(evaluation, "outcome", "evaluation"), digest),
        health_result=(
            _health(families, contract) if _health_completed(semantic) else None
        ),
        finding_evaluation=finding_verdicts(_member(document, "findings", "document")),
        unit_risk_result=_unit_bands(families, index),
        hotlist_selection=document_selections(_member(document, "derived", "document")),
    )


__all__ = ["evaluation_facts_from_document"]
