# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The storage row form of the comparison and evaluation houses.

One owner for how a comparison or an evaluation fact is spelled as a row:
the run store stores these rows and reads them back, and the canonical wire
(wire revision 2) carries exactly the same rows in its ``comparison`` and
``evaluation`` members.  Before this module the form lived inside the store,
and the wire could not emit the two houses without a second spelling of it.

:data:`TIER_FAMILIES` is the one list of the two houses' families -- the
name the registry, the house and the wire give each one, the storage family
its rows are filed under, whether it is one record or a set of rows, and its
decoder -- so the wire's family order and columns are mechanical.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import asdict, dataclass
from typing import Final, Literal, TypeVar

from codeclone.canonical.comparison_rows import (
    BaselineWitnessRecord,
    ComparisonAvailabilityRow,
    DisabledCapabilityRow,
    FindingNoveltyRow,
    LaneTrustRow,
    MetricDeltaRow,
    MetricsBaselineWitnessRecord,
)
from codeclone.canonical.errors import CanonicalModelError, StoreIntegrityError
from codeclone.canonical.evaluation_rows import (
    EvaluationContractRecord,
    EvaluationRequestRecord,
    FindingEvaluationRow,
    GateOutcomeRecord,
    HealthResultRecord,
    HotlistRow,
    UnitRiskRow,
)
from codeclone.canonical.identity import canonical_key
from codeclone.canonical.model import (
    ComparisonFacts,
    EvaluationFacts,
    novelty_families,
)
from codeclone.canonical.registry import (
    COMPARISON_RECORD_FAMILIES,
    EVALUATION_RECORD_FAMILIES,
    comparison_stored_fields,
    evaluation_stored_fields,
)
from codeclone.canonical.stored_fields import (
    decode_stored_pairs,
    decode_str_list,
    require_bool,
    require_field,
    require_float,
    require_int,
    require_line,
    require_optional_int,
    require_optional_str,
    require_str,
    require_str_list,
    row_symbol,
    storage_form,
    symbol_value,
)

TierHouse = Literal["comparison", "evaluation"]
_RowT = TypeVar("_RowT")


def comparison_storage_rows(
    comparison: ComparisonFacts,
) -> Iterator[tuple[str, dict[str, object]]]:
    """Storage rows of the comparison house (canonical epoch E2).

    Every row is stored whole — its baseline identity included — because the
    comparison it states is against THAT container: two runs compared against
    two baselines never share a novelty object.  Row order is the same
    insurance as everywhere in this walk; the content address owns
    determinism.
    """
    yield from _comparison_result_rows(comparison)
    for trust in sorted(comparison.lane_trust, key=lambda row: row.lane):
        yield "lane_trust", dict(sorted(asdict(trust).items()))
    for available in sorted(
        comparison.comparison_availability, key=lambda row: row.lane
    ):
        yield "comparison_availability", dict(sorted(asdict(available).items()))
    for disabled in sorted(comparison.disabled_capabilities, key=lambda row: row.lane):
        yield "disabled_capability", dict(sorted(asdict(disabled).items()))
    for family, rows in novelty_families(comparison):
        for novelty in sorted(rows, key=lambda row: row.finding_id):
            yield family, dict(sorted(asdict(novelty).items()))


def _comparison_result_rows(
    comparison: ComparisonFacts,
) -> Iterator[tuple[str, dict[str, object]]]:
    """The two witness records and the two delta families' named rows."""
    for family, record in (
        ("baseline_witness", comparison.baseline_witness),
        ("metrics_baseline_witness", comparison.metrics_baseline_witness),
    ):
        if record is not None:
            # One record per run, present iff the model carries it.
            yield family, dict(sorted(asdict(record).items()))
    for family, deltas in (
        ("adoption_delta", comparison.adoption_delta),
        ("api_surface_delta", comparison.api_surface_delta),
        ("health_delta", comparison.health_delta),
    ):
        for delta in sorted(deltas, key=lambda row: row.delta):
            yield family, dict(sorted(asdict(delta).items()))


def evaluation_storage_rows(
    evaluation: EvaluationFacts,
) -> Iterator[tuple[str, dict[str, object]]]:
    """Storage rows of the evaluation house (canonical epoch E3).

    Every record and row is stored whole: a verdict is what the run concluded
    under ITS request, and the request digest the records carry keeps two
    policies' verdicts apart.  Row order is the same insurance as everywhere
    in this walk; the content address owns determinism.
    """
    for family, record in (
        ("evaluation_contract", evaluation.evaluation_contract),
        ("evaluation_request", evaluation.evaluation_request),
        ("gate_outcome", evaluation.gate_outcome),
        ("health_result", evaluation.health_result),
    ):
        if record is not None:
            yield family, storage_form(asdict(record))
    for verdict in sorted(
        evaluation.finding_evaluation, key=lambda row: row.finding_id
    ):
        yield "finding_evaluation", storage_form(asdict(verdict))
    for unit in sorted(
        evaluation.unit_risk_result,
        key=lambda row: (row.dimension, canonical_key(row.symbol), row.start_line),
    ):
        yield (
            "unit_risk_result",
            {
                "band": unit.band,
                "dimension": unit.dimension,
                "start_line": unit.start_line,
                "symbol": symbol_value(unit.symbol),
            },
        )
    for selected in sorted(
        evaluation.hotlist_selection, key=lambda row: (row.hotlist, row.rank)
    ):
        yield "hotlist_selection", storage_form(asdict(selected))


def _stored_identity(
    row: Mapping[str, object], where: str
) -> tuple[str | None, str | None]:
    return (
        require_optional_str(row, "baseline_scope_id", where),
        require_optional_str(row, "root_digest", where),
    )


def decode_baseline_witness_row(
    row: Mapping[str, object], where: str
) -> BaselineWitnessRecord:
    scope_id, root_digest = _stored_identity(row, where)
    return BaselineWitnessRecord(
        baseline_scope_id=scope_id,
        root_digest=root_digest,
        state=require_str(row, "state", where),
        loaded=require_bool(row, "loaded", where),
        status=require_str(row, "status", where),
        fingerprint_version=require_optional_str(row, "fingerprint_version", where),
        schema_version=require_optional_str(row, "schema_version", where),
        python_tag=require_optional_str(row, "python_tag", where),
        payload_sha256=require_optional_str(row, "payload_sha256", where),
    )


def decode_metrics_baseline_witness_row(
    row: Mapping[str, object], where: str
) -> MetricsBaselineWitnessRecord:
    scope_id, root_digest = _stored_identity(row, where)
    return MetricsBaselineWitnessRecord(
        baseline_scope_id=scope_id,
        root_digest=root_digest,
        loaded=require_bool(row, "loaded", where),
        status=require_str(row, "status", where),
        schema_version=require_optional_str(row, "schema_version", where),
        payload_sha256=require_optional_str(row, "payload_sha256", where),
    )


def decode_lane_trust_row(row: Mapping[str, object], where: str) -> LaneTrustRow:
    scope_id, root_digest = _stored_identity(row, where)
    return LaneTrustRow(
        baseline_scope_id=scope_id,
        root_digest=root_digest,
        lane=require_str(row, "lane", where),
        status=require_str(row, "status", where),
        reason=require_str(row, "reason", where),
    )


def decode_comparison_availability_row(
    row: Mapping[str, object], where: str
) -> ComparisonAvailabilityRow:
    scope_id, root_digest = _stored_identity(row, where)
    return ComparisonAvailabilityRow(
        baseline_scope_id=scope_id,
        root_digest=root_digest,
        lane=require_str(row, "lane", where),
        availability=require_str(row, "availability", where),
    )


def decode_disabled_capability_row(
    row: Mapping[str, object], where: str
) -> DisabledCapabilityRow:
    scope_id, root_digest = _stored_identity(row, where)
    return DisabledCapabilityRow(
        baseline_scope_id=scope_id,
        root_digest=root_digest,
        lane=require_str(row, "lane", where),
    )


def decode_finding_novelty_row(
    row: Mapping[str, object], where: str
) -> FindingNoveltyRow:
    scope_id, root_digest = _stored_identity(row, where)
    return FindingNoveltyRow(
        baseline_scope_id=scope_id,
        root_digest=root_digest,
        finding_id=require_str(row, "finding_id", where),
        novelty=require_str(row, "novelty", where),
        novelty_reason=require_optional_str(row, "novelty_reason", where),
    )


def decode_metric_delta_row(row: Mapping[str, object], where: str) -> MetricDeltaRow:
    scope_id, root_digest = _stored_identity(row, where)
    return MetricDeltaRow(
        baseline_scope_id=scope_id,
        root_digest=root_digest,
        delta=require_str(row, "delta", where),
        value=require_int(row, "value", where),
    )


def _decode_request_terms(value: object, where: str) -> tuple[tuple[str, int], ...]:
    """Request terms: every value an int or a boolean (``bool`` is an ``int``
    here; the record's own law holds each term to its declared type)."""
    terms: list[tuple[str, int]] = []
    for name, term in decode_stored_pairs(value, where):
        if not isinstance(term, int):
            raise StoreIntegrityError(f"{where}: stored term {name!r} is not an int")
        terms.append((name, term))
    return tuple(terms)


def _decode_numeric_pairs(
    value: object, where: str
) -> tuple[tuple[str, int | float], ...]:
    pairs: list[tuple[str, int | float]] = []
    for name, number in decode_stored_pairs(value, where):
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            raise StoreIntegrityError(
                f"{where}: stored value of {name!r} is not a number"
            )
        pairs.append((name, number))
    return tuple(pairs)


def _decode_gate_requirements(
    value: object, where: str
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return tuple(
        (gate, tuple(decode_str_list(lanes, f"lanes of {gate}", where)))
        for gate, lanes in decode_stored_pairs(value, where)
    )


def decode_evaluation_request_row(
    row: Mapping[str, object], where: str
) -> EvaluationRequestRecord:
    return EvaluationRequestRecord(
        gate_thresholds_digest=require_str(row, "gate_thresholds_digest", where),
        terms=_decode_request_terms(require_field(row, "terms", where), where),
    )


def decode_evaluation_contract_row(
    row: Mapping[str, object], where: str
) -> EvaluationContractRecord:
    return EvaluationContractRecord(
        gate_thresholds_digest=require_str(row, "gate_thresholds_digest", where),
        health_algorithm_revision=require_str(row, "health_algorithm_revision", where),
        gate_algorithm_revision=require_str(row, "gate_algorithm_revision", where),
        gate_lane_matrix_version=require_str(row, "gate_lane_matrix_version", where),
        health_input_manifest_version=require_str(
            row, "health_input_manifest_version", where
        ),
        health_input_lanes=tuple(require_str_list(row, "health_input_lanes", where)),
        active_gate_lane_requirements=_decode_gate_requirements(
            require_field(row, "active_gate_lane_requirements", where), where
        ),
        health_params=_decode_numeric_pairs(
            require_field(row, "health_params", where), where
        ),
    )


def decode_gate_outcome_row(row: Mapping[str, object], where: str) -> GateOutcomeRecord:
    return GateOutcomeRecord(
        gate_thresholds_digest=require_str(row, "gate_thresholds_digest", where),
        exit_code=require_int(row, "exit_code", where),
        reasons=tuple(require_str_list(row, "reasons", where)),
        required_lanes=tuple(require_str_list(row, "required_lanes", where)),
        unavailable_lanes=tuple(require_str_list(row, "unavailable_lanes", where)),
    )


def _decode_health_dimensions(
    value: object, where: str
) -> tuple[tuple[str, int], ...] | None:
    if value is None:
        return None
    dimensions: list[tuple[str, int]] = []
    for name, score in _decode_numeric_pairs(value, where):
        if not isinstance(score, int):
            raise StoreIntegrityError(
                f"{where}: stored dimension {name!r} is not an int"
            )
        dimensions.append((name, score))
    return tuple(dimensions)


def decode_health_result_row(
    row: Mapping[str, object], where: str
) -> HealthResultRecord:
    return HealthResultRecord(
        score=require_optional_int(row, "score", where),
        grade=require_optional_str(row, "grade", where),
        dimensions=_decode_health_dimensions(
            require_field(row, "dimensions", where), where
        ),
        population=require_str(row, "population", where),
        health_algorithm_revision=require_str(row, "health_algorithm_revision", where),
        health_input_manifest_version=require_str(
            row, "health_input_manifest_version", where
        ),
    )


def decode_unit_risk_row(row: Mapping[str, object], where: str) -> UnitRiskRow:
    return UnitRiskRow(
        dimension=require_str(row, "dimension", where),
        symbol=row_symbol(row, "symbol", where),
        start_line=require_line(row, "start_line", where),
        band=require_str(row, "band", where),
    )


def decode_finding_evaluation_row(
    row: Mapping[str, object], where: str
) -> FindingEvaluationRow:
    return FindingEvaluationRow(
        finding_id=require_str(row, "finding_id", where),
        severity=require_str(row, "severity", where),
        confidence=require_str(row, "confidence", where),
        priority=require_float(row, "priority", where),
        clone_type=require_optional_str(row, "clone_type", where),
    )


def decode_hotlist_row(row: Mapping[str, object], where: str) -> HotlistRow:
    return HotlistRow(
        hotlist=require_str(row, "hotlist", where),
        rank=require_int(row, "rank", where),
        finding_id=require_str(row, "finding_id", where),
    )


@dataclass(frozen=True, slots=True)
class TierFamily:
    """One family of the comparison or evaluation house.

    ``name`` is the family's one public name -- its registry declaration,
    its field on the house and its member on the wire; ``stored`` is the
    storage family its rows are filed under in the run store.
    """

    house: TierHouse
    name: str
    stored: str
    decode: Callable[[Mapping[str, object], str], object]

    @property
    def record(self) -> bool:
        """One record per run (``None`` is its absence), never a row set."""
        return self.name in COMPARISON_RECORD_FAMILIES | EVALUATION_RECORD_FAMILIES

    @property
    def columns(self) -> tuple[str, ...]:
        """The stored fields of the family, in the wire's (sorted) order."""
        if self.house == "comparison":
            return comparison_stored_fields(self.name)
        return evaluation_stored_fields(self.name)


def _family(
    house: TierHouse,
    name: str,
    decode: Callable[[Mapping[str, object], str], object],
    stored: str | None = None,
) -> TierFamily:
    return TierFamily(house=house, name=name, stored=stored or name, decode=decode)


#: Every family of the two houses, each house in sorted name order -- the
#: order of the wire's members.
TIER_FAMILIES: Final[tuple[TierFamily, ...]] = (
    _family("comparison", "adoption_delta", decode_metric_delta_row),
    _family("comparison", "api_surface_delta", decode_metric_delta_row),
    _family("comparison", "baseline_witness", decode_baseline_witness_row),
    _family("comparison", "clone_novelty", decode_finding_novelty_row),
    _family(
        "comparison", "comparison_availability", decode_comparison_availability_row
    ),
    _family("comparison", "complexity_novelty", decode_finding_novelty_row),
    _family("comparison", "coupling_novelty", decode_finding_novelty_row),
    _family("comparison", "dead_symbol_novelty", decode_finding_novelty_row),
    _family("comparison", "dependency_cycle_novelty", decode_finding_novelty_row),
    _family(
        "comparison",
        "disabled_capabilities",
        decode_disabled_capability_row,
        stored="disabled_capability",
    ),
    _family("comparison", "health_delta", decode_metric_delta_row),
    _family("comparison", "lane_trust", decode_lane_trust_row),
    _family(
        "comparison", "metrics_baseline_witness", decode_metrics_baseline_witness_row
    ),
    _family("evaluation", "evaluation_contract", decode_evaluation_contract_row),
    _family("evaluation", "evaluation_request", decode_evaluation_request_row),
    _family("evaluation", "finding_evaluation", decode_finding_evaluation_row),
    _family("evaluation", "gate_outcome", decode_gate_outcome_row),
    _family("evaluation", "health_result", decode_health_result_row),
    _family("evaluation", "hotlist_selection", decode_hotlist_row),
    _family("evaluation", "unit_risk_result", decode_unit_risk_row),
)


def tier_families(house: TierHouse) -> tuple[TierFamily, ...]:
    """The families of one house, in the wire's order."""
    return tuple(family for family in TIER_FAMILIES if family.house == house)


def tier_rows(
    house: TierHouse, facts: ComparisonFacts | EvaluationFacts
) -> dict[str, list[dict[str, object]]]:
    """One house's storage rows grouped by family name, each family's rows
    in the order the storage writer yields them -- the wire's row order."""
    if isinstance(facts, ComparisonFacts):
        written = comparison_storage_rows(facts)
    else:
        written = evaluation_storage_rows(facts)
    by_stored = {family.stored: family.name for family in tier_families(house)}
    grouped: dict[str, list[dict[str, object]]] = {}
    for stored, row in written:
        grouped.setdefault(by_stored[stored], []).append(row)
    return grouped


def comparison_house(decoded: Mapping[str, list[object]]) -> ComparisonFacts:
    """The comparison house from its decoded rows, keyed by family name."""
    return ComparisonFacts(
        baseline_witness=_record(decoded, "baseline_witness", BaselineWitnessRecord),
        metrics_baseline_witness=_record(
            decoded, "metrics_baseline_witness", MetricsBaselineWitnessRecord
        ),
        lane_trust=_rows(decoded, "lane_trust", LaneTrustRow),
        comparison_availability=_rows(
            decoded, "comparison_availability", ComparisonAvailabilityRow
        ),
        disabled_capabilities=_rows(
            decoded, "disabled_capabilities", DisabledCapabilityRow
        ),
        clone_novelty=_rows(decoded, "clone_novelty", FindingNoveltyRow),
        complexity_novelty=_rows(decoded, "complexity_novelty", FindingNoveltyRow),
        coupling_novelty=_rows(decoded, "coupling_novelty", FindingNoveltyRow),
        dependency_cycle_novelty=_rows(
            decoded, "dependency_cycle_novelty", FindingNoveltyRow
        ),
        dead_symbol_novelty=_rows(decoded, "dead_symbol_novelty", FindingNoveltyRow),
        adoption_delta=_rows(decoded, "adoption_delta", MetricDeltaRow),
        api_surface_delta=_rows(decoded, "api_surface_delta", MetricDeltaRow),
        health_delta=_rows(decoded, "health_delta", MetricDeltaRow),
    )


def evaluation_house(decoded: Mapping[str, list[object]]) -> EvaluationFacts:
    """The evaluation house from its decoded rows, keyed by family name."""
    return EvaluationFacts(
        evaluation_contract=_record(
            decoded, "evaluation_contract", EvaluationContractRecord
        ),
        evaluation_request=_record(
            decoded, "evaluation_request", EvaluationRequestRecord
        ),
        gate_outcome=_record(decoded, "gate_outcome", GateOutcomeRecord),
        health_result=_record(decoded, "health_result", HealthResultRecord),
        finding_evaluation=_rows(decoded, "finding_evaluation", FindingEvaluationRow),
        unit_risk_result=_rows(decoded, "unit_risk_result", UnitRiskRow),
        hotlist_selection=_rows(decoded, "hotlist_selection", HotlistRow),
    )


def _typed(
    decoded: Mapping[str, list[object]], name: str, row_type: type[_RowT]
) -> list[_RowT]:
    typed: list[_RowT] = []
    for row in decoded.get(name, []):
        if not isinstance(row, row_type):
            raise CanonicalModelError(
                f"family {name!r} carries a {type(row).__name__}, "
                f"not a {row_type.__name__}"
            )
        typed.append(row)
    return typed


def _rows(
    decoded: Mapping[str, list[object]], name: str, row_type: type[_RowT]
) -> frozenset[_RowT]:
    return frozenset(_typed(decoded, name, row_type))


def _record(
    decoded: Mapping[str, list[object]], name: str, row_type: type[_RowT]
) -> _RowT | None:
    rows = _typed(decoded, name, row_type)
    if len(rows) > 1:
        raise CanonicalModelError(
            f"{name} carries more than one record; the family is one record per run"
        )
    return rows[0] if rows else None
