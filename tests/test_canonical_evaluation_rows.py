# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Canonical epoch E3 (2026-09-27): the evaluation families' laws, their
store rows, and the absence of any evaluation byte on the wire.

Every law is pinned on the mechanism it names, both boundaries where it
classifies: the row refuses what the producer cannot publish and admits what
it does, the model binds the evaluation to ONE request and dates the health
verdict by its contract, the store reads each family back under its own name
with DDL 0 — and the wire of this revision carries none of it (the negative
contract of the 2026-09-26 ruling, applied to the next tier).
"""

from __future__ import annotations

import dataclasses
import io
import json
import sqlite3
import typing
from dataclasses import replace
from pathlib import Path

import pytest

from codeclone.canonical import (
    CanonicalModelError,
    RunStore,
    StoreIntegrityError,
    WireDecodeError,
    decode_canonical_json,
    encode_canonical_json,
    export_run,
)
from codeclone.canonical import evaluation_rows as rows
from codeclone.canonical.comparison_rows import MetricDeltaRow
from codeclone.canonical.evaluation_rows import (
    EvaluationContractRecord,
    EvaluationRequestRecord,
    FindingEvaluationRow,
    GateOutcomeRecord,
    HealthResultRecord,
    HotlistRow,
    UnitRiskRow,
    finding_priority_is_admissible,
)
from codeclone.canonical.identity import FileId, SymbolId
from codeclone.canonical.model import EvaluationFacts
from codeclone.canonical.store import (
    FAMILY_EVALUATION_CONTRACT,
    FAMILY_EVALUATION_REQUEST,
    FAMILY_FINDING_EVALUATION,
    FAMILY_GATE_OUTCOME,
    FAMILY_HEALTH_DELTA,
    FAMILY_HEALTH_RESULT,
    FAMILY_HOTLIST_SELECTION,
    FAMILY_UNIT_RISK_RESULT,
    StoredFamily,
    _collected_model,
)
from codeclone.contracts import (
    BASELINE_SCHEMA_VERSION,
    CANONICAL_MODEL_REVISION,
    CANONICAL_WIRE_REVISION,
    COMPLEXITY_ALGORITHM_REVISION,
    DESIGN_METRICS_ALGORITHM_REVISION,
    GATE_ALGORITHM_REVISION,
    GATE_LANE_MATRIX_VERSION,
    HEALTH_ALGORITHM_REVISION,
    HEALTH_INPUT_MANIFEST_VERSION,
    HEALTH_WEIGHTS,
    METRICS_BASELINE_SCHEMA_VERSION,
    STORAGE_SCHEMA_REVISION,
    ExitCode,
    ObservedPopulation,
)
from codeclone.domain.quality import EFFORT_WEIGHT, SEVERITY_RANK
from codeclone.report.gates.evaluator import (
    HEALTH_INPUT_LANES,
    GateState,
    MetricGateConfig,
    evaluate_gate_state,
)
from codeclone.report.suggestions import CloneType
from tests.test_canonical_roundtrip import (
    FIXTURE_BASELINE_SCOPE_ID,
    FIXTURE_REQUEST_DIGEST,
    FIXTURE_ROOT_DIGEST,
    evaluated_fixture_model,
    evaluation_fixture_facts,
    fixture_model,
)

#: Every evaluation storage family and the health delta, spelled by hand.
_EVALUATION_FAMILIES: tuple[StoredFamily[typing.Any], ...] = (
    FAMILY_EVALUATION_CONTRACT,
    FAMILY_EVALUATION_REQUEST,
    FAMILY_GATE_OUTCOME,
    FAMILY_HEALTH_RESULT,
    FAMILY_UNIT_RISK_RESULT,
    FAMILY_FINDING_EVALUATION,
    FAMILY_HOTLIST_SELECTION,
    FAMILY_HEALTH_DELTA,
)
_FA = FileId("pkg/a.py")


def _publish(store: RunStore, model: object, target: str = "head") -> str:
    return store.write_full_run(
        model,  # type: ignore[arg-type]
        namespace="e3",
        target=target,
        expected_generation=0,
    ).run_id


def _outcome(**overrides: object) -> GateOutcomeRecord:
    fields: dict[str, object] = {
        "gate_thresholds_digest": FIXTURE_REQUEST_DIGEST,
        "exit_code": 3,
        "reasons": ("metric:x",),
        "required_lanes": ("risk_observations",),
        "unavailable_lanes": (),
        **overrides,
    }
    return GateOutcomeRecord(**fields)  # type: ignore[arg-type]


def _health(**overrides: object) -> HealthResultRecord:
    base = evaluation_fixture_facts().health_result
    assert base is not None
    return replace(base, **overrides)  # type: ignore[arg-type]


def _verdict(**overrides: object) -> FindingEvaluationRow:
    fields: dict[str, object] = {
        "finding_id": "design:complexity:pkg.a:A.run",
        "severity": "warning",
        "confidence": "high",
        "priority": 1.0,
        "clone_type": None,
        **overrides,
    }
    return FindingEvaluationRow(**fields)  # type: ignore[arg-type]


def _contract(**overrides: object) -> EvaluationContractRecord:
    base = evaluation_fixture_facts().evaluation_contract
    assert base is not None
    return replace(base, **overrides)  # type: ignore[arg-type]


def _request(**overrides: object) -> EvaluationRequestRecord:
    base = evaluation_fixture_facts().evaluation_request
    assert base is not None
    return replace(base, **overrides)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Mirrored vocabularies: each pinned against its one owner.
# ---------------------------------------------------------------------------


def test_the_request_terms_are_the_gate_config_fields_and_types() -> None:
    fields = {field.name: field.type for field in dataclasses.fields(MetricGateConfig)}
    assert set(rows.GATE_REQUEST_TERMS) == set(fields)
    assert {name: kind.__name__ for name, kind in rows.GATE_REQUEST_TERMS.items()} == (
        fields
    )


def test_the_health_vocabularies_are_their_owners() -> None:
    assert rows.HEALTH_INPUT_LANES == HEALTH_INPUT_LANES
    assert tuple(sorted(HEALTH_WEIGHTS)) == rows.HEALTH_DIMENSIONS
    assert (
        tuple(sorted(typing.get_args(ObservedPopulation))) == rows.OBSERVED_POPULATIONS
    )
    assert typing.get_args(CloneType) == rows.CLONE_TYPES
    assert tuple(sorted(SEVERITY_RANK)) == rows.SEVERITIES


def test_the_gate_outcomes_are_the_exit_codes() -> None:
    assert (
        int(ExitCode.SUCCESS),
        int(ExitCode.CONTRACT_ERROR),
        int(ExitCode.GATING_FAILURE),
    ) == rows.GATE_EXIT_CODES


def test_the_unavailable_reason_is_the_evaluators_spelling() -> None:
    """Measured on the owner: a complexity gate whose lane the run did not
    enable is refused with exactly this reason, and the record admits the
    evaluator's own result."""
    config = MetricGateConfig(
        fail_complexity=20,
        fail_coupling=-1,
        fail_cohesion=-1,
        fail_cycles=False,
        fail_dead_code=False,
        fail_health=-1,
        fail_on_new_metrics=False,
    )
    result = evaluate_gate_state(state=GateState(), config=config, enabled_lanes=())
    assert result.unavailable_lanes == ("risk_observations",)
    assert result.reasons == (
        rows.LANE_UNAVAILABLE_REASON.format(lane="risk_observations"),
    )
    assert _outcome(
        exit_code=result.exit_code,
        reasons=result.reasons,
        required_lanes=result.required_lanes,
        unavailable_lanes=result.unavailable_lanes,
    )


def test_the_hotlists_are_the_documents_selections() -> None:
    from codeclone.report.document.derived import _build_derived_overview

    _overview, hotlists = _build_derived_overview(findings={}, metrics_payload={})
    named = {key.removesuffix("_ids") for key in hotlists}
    assert all(key.endswith("_ids") for key in hotlists)
    assert set(rows.HOTLISTS) == named | {"suggestions"}


# ---------------------------------------------------------------------------
# Row laws, both boundaries.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("build", "match"),
    [
        (lambda: _request(terms=_request().terms[1:]), "not exactly the gate terms"),
        (
            lambda: _request(
                terms=tuple(
                    (name, 1 if name == "fail_cycles" else value)
                    for name, value in _request().terms
                )
            ),
            "'fail_cycles' must be a bool",
        ),
        (
            lambda: _request(
                terms=tuple(
                    (name, True if name == "fail_complexity" else value)
                    for name, value in _request().terms
                )
            ),
            "'fail_complexity' must be a int",
        ),
        (lambda: _request(gate_thresholds_digest=""), "request digest"),
        (lambda: _outcome(exit_code=1), "unknown gate outcome exit code"),
        (lambda: _outcome(exit_code=0), "contradicts its reasons"),
        (lambda: _outcome(reasons=()), "contradicts its reasons"),
        (
            lambda: _outcome(
                exit_code=2,
                reasons=("lane:unavailable:risk_observations",),
            ),
            "contradicts its unavailable lanes",
        ),
        (
            lambda: _outcome(unavailable_lanes=("risk_observations",)),
            "contradicts its unavailable lanes",
        ),
        (
            lambda: _outcome(
                exit_code=2,
                reasons=("metric:x",),
                unavailable_lanes=("risk_observations",),
            ),
            "states other reasons",
        ),
        (
            lambda: _outcome(
                exit_code=2,
                reasons=("lane:unavailable:dead_code",),
                unavailable_lanes=("dead_code",),
            ),
            "no requested gate reads",
        ),
        (
            lambda: _outcome(required_lanes=("risk_observations", "dead_code")),
            "sorted and unique",
        ),
        (lambda: _outcome(required_lanes=("vibes",)), "required lane"),
        (lambda: _health(score=None), "must state score, grade and dimensions"),
        (lambda: _health(grade=None), "must state score, grade and dimensions"),
        (lambda: _health(dimensions=None), "must state score, grade and dimensions"),
        (
            lambda: _health(population="unmeasured"),
            "must withhold score, grade and dimensions",
        ),
        (lambda: _health(score=101), "score must lie in"),
        (lambda: _health(score=-1), "score must lie in"),
        (lambda: _health(grade="E"), "grade"),
        (lambda: _health(dimensions=_health().dimensions[1:]), "not exactly"),  # type: ignore[index]
        (lambda: _health(population="half"), "population"),
        (lambda: _health(health_algorithm_revision=""), "algorithm revision"),
        (lambda: _verdict(priority=0.75), "no effort's priority"),
        (lambda: _verdict(severity="critical", priority=2.0), "no effort's priority"),
        (lambda: _verdict(severity="fatal"), "severity"),
        (lambda: _verdict(confidence="certain"), "confidence"),
        (lambda: _verdict(priority=True), "must be a number"),
        (lambda: _verdict(clone_type="Type-2"), "clone findings only"),
        (
            lambda: _verdict(finding_id="clone:block:k", severity="info", priority=0.5),
            "clone findings only",
        ),
        (
            lambda: _verdict(
                finding_id="clone:function:k", clone_type="Type-9", priority=2.0
            ),
            "clone type",
        ),
        (
            lambda: UnitRiskRow(
                dimension="nesting", symbol=SymbolId(_FA, "f"), start_line=1, band="low"
            ),
            "unit risk dimension",
        ),
        (
            lambda: UnitRiskRow(
                dimension="complexity",
                symbol=SymbolId(_FA, "f"),
                start_line=0,
                band="low",
            ),
            "unit risk site",
        ),
        (
            lambda: UnitRiskRow(
                dimension="complexity",
                symbol=SymbolId(_FA, "f"),
                start_line=1,
                band="extreme",
            ),
            "unit risk band",
        ),
        (lambda: HotlistRow(hotlist="favourites", rank=1, finding_id="x"), "hotlist"),
        (lambda: HotlistRow(hotlist="suggestions", rank=0, finding_id="x"), "rank"),
        (
            lambda: HotlistRow(hotlist="suggestions", rank=1, finding_id=""),
            "finding id",
        ),
        (
            lambda: _contract(health_input_lanes=("risk_observations", "dead_code")),
            "sorted and unique",
        ),
        (
            lambda: _contract(
                active_gate_lane_requirements=(("b", ()), ("a", ())),
            ),
            "gate names",
        ),
        (
            lambda: _contract(health_params=(("b", 1), ("a", 2))),
            "health parameter names",
        ),
        (
            lambda: _contract(health_params=(("a", float("nan")),)),
            "must be finite",
        ),
        (lambda: _contract(health_params=(("a", "1"),)), "must be a number"),
    ],
)
def test_rows_refuse_what_the_producer_cannot_publish(
    build: typing.Callable[[], object], match: str
) -> None:
    with pytest.raises(CanonicalModelError, match=match):
        build()


def test_rows_admit_what_the_producer_publishes() -> None:
    """The other boundary of every refusal above: the three outcomes, a
    withheld verdict for each withholding population, every admitted
    priority, a clone verdict with its type."""
    assert _outcome(exit_code=0, reasons=(), required_lanes=())
    assert _outcome(
        exit_code=2,
        reasons=("lane:unavailable:risk_observations",),
        unavailable_lanes=("risk_observations",),
    )
    for population in ("complete_empty", "unmeasured"):
        assert _health(score=None, grade=None, dimensions=None, population=population)
    assert _health(population="partial")
    for severity in SEVERITY_RANK:
        for weight in EFFORT_WEIGHT.values():
            priority = float(SEVERITY_RANK[severity]) / float(weight)
            assert finding_priority_is_admissible(severity, priority)
            assert _verdict(severity=severity, priority=priority)
    assert _verdict(finding_id="clone:segment:k", clone_type="Type-4", priority=1.0)
    assert _contract(health_params=())


# ---------------------------------------------------------------------------
# Model laws: one request, a dated verdict, contiguous selections.
# ---------------------------------------------------------------------------


def _normalize_with(**overrides: object) -> None:
    model = evaluated_fixture_model()
    evaluation = replace(model.facts.evaluation, **overrides)  # type: ignore[arg-type]
    replace(model, facts=replace(model.facts, evaluation=evaluation)).normalize()


def _normalize_comparison_with(**overrides: object) -> None:
    model = evaluated_fixture_model()
    comparison = replace(model.facts.comparison, **overrides)  # type: ignore[arg-type]
    replace(model, facts=replace(model.facts, comparison=comparison)).normalize()


def test_the_evaluated_fixture_is_admitted_and_distinguishing() -> None:
    evaluation = evaluated_fixture_model().normalize().facts.evaluation
    assert {row.band for row in evaluation.unit_risk_result} == set(rows.RISK_BANDS)
    assert {row.dimension for row in evaluation.unit_risk_result} == set(
        rows.RISK_UNIT_DIMENSIONS
    )
    assert {row.severity for row in evaluation.finding_evaluation} == set(
        rows.SEVERITIES
    )
    assert {row.hotlist for row in evaluation.hotlist_selection} == {
        "most_actionable",
        "suggestions",
    }


def test_the_empty_house_is_the_unevaluated_run() -> None:
    """The decoded-from-wire state: no records, no rows — admitted."""
    assert fixture_model().normalize().facts.evaluation == EvaluationFacts()


@pytest.mark.parametrize("record", ["evaluation_contract", "evaluation_request"])
def test_a_partial_evaluation_witness_is_refused(record: str) -> None:
    with pytest.raises(CanonicalModelError, match="witnessed in part"):
        _normalize_with(**{record: None})


@pytest.mark.parametrize(
    "family",
    ["health_result", "finding_evaluation", "unit_risk_result", "hotlist_selection"],
)
def test_an_evaluation_fact_without_the_witness_is_refused(family: str) -> None:
    kept = getattr(evaluation_fixture_facts(), family)
    model = fixture_model()
    with pytest.raises(CanonicalModelError, match="without the evaluation witness"):
        replace(
            model,
            facts=replace(model.facts, evaluation=EvaluationFacts(**{family: kept})),
        ).normalize()


@pytest.mark.parametrize("record", ["evaluation_contract", "gate_outcome"])
def test_a_second_request_under_one_run_is_refused(record: str) -> None:
    """m-request-digest: the contract and the outcome name the run's one
    request; either naming another is two evaluations under one run."""
    value = getattr(evaluation_fixture_facts(), record)
    with pytest.raises(CanonicalModelError, match="evaluated under one request"):
        _normalize_with(**{record: replace(value, gate_thresholds_digest="f" * 64)})


def test_the_health_verdict_is_dated_by_the_runs_contract() -> None:
    with pytest.raises(CanonicalModelError, match="dated by another contract"):
        _normalize_with(health_result=_health(health_algorithm_revision="9"))
    with pytest.raises(CanonicalModelError, match="dated by another contract"):
        _normalize_with(health_result=_health(health_input_manifest_version="9"))


def test_the_health_parameters_ride_the_contract_exactly_with_a_verdict() -> None:
    with pytest.raises(CanonicalModelError, match="exactly when a health verdict"):
        _normalize_with(evaluation_contract=_contract(health_params=()))
    with pytest.raises(CanonicalModelError, match="exactly when a health verdict"):
        _normalize_with(health_result=None)
    # The other boundary: no verdict, no parameters (the metrics never ran).
    evaluation = evaluation_fixture_facts()
    model = evaluated_fixture_model()
    replace(
        model,
        facts=replace(
            model.facts,
            comparison=replace(model.facts.comparison, health_delta=frozenset()),
            evaluation=replace(
                evaluation,
                health_result=None,
                evaluation_contract=_contract(health_params=()),
            ),
        ),
    ).normalize()


def test_a_selection_ranks_from_one_without_a_gap() -> None:
    fixture = evaluation_fixture_facts()
    gapped = frozenset(
        replace(row, rank=3) if row.rank == 2 else row
        for row in fixture.hotlist_selection
    )
    with pytest.raises(CanonicalModelError, match="most_actionable selection skips"):
        _normalize_with(hotlist_selection=gapped)
    shifted = frozenset(
        replace(row, rank=row.rank + 1) for row in fixture.hotlist_selection
    )
    with pytest.raises(CanonicalModelError, match="selection skips a rank"):
        _normalize_with(hotlist_selection=shifted)


def test_one_finding_twice_in_one_selection_is_refused() -> None:
    fixture = evaluation_fixture_facts()
    doubled = fixture.hotlist_selection | {
        HotlistRow(
            hotlist="most_actionable", rank=3, finding_id="clone:function:aa11|0-19"
        )
    }
    with pytest.raises(CanonicalModelError, match=r"hotlist_selection\.id"):
        _normalize_with(hotlist_selection=doubled)
    with pytest.raises(CanonicalModelError, match=r"hotlist_selection\.rank"):
        _normalize_with(
            hotlist_selection=fixture.hotlist_selection
            | {HotlistRow(hotlist="suggestions", rank=1, finding_id="dead_code:x")}
        )


def test_two_verdicts_on_one_finding_are_refused() -> None:
    fixture = evaluation_fixture_facts()
    with pytest.raises(CanonicalModelError, match=r"finding_evaluation\.id"):
        _normalize_with(
            finding_evaluation=fixture.finding_evaluation
            | {
                _verdict(
                    finding_id="design:dependency:pkg.a -> pkg.h",
                    severity="warning",
                    priority=1.0,
                )
            }
        )


def test_two_bands_of_one_unit_are_refused() -> None:
    fixture = evaluation_fixture_facts()
    with pytest.raises(CanonicalModelError, match=r"unit_risk_result\.key"):
        _normalize_with(
            unit_risk_result=fixture.unit_risk_result
            | {
                UnitRiskRow(
                    dimension="complexity",
                    symbol=SymbolId(_FA, "A.run"),
                    start_line=3,
                    band="low",
                )
            }
        )


def test_a_band_of_a_unit_outside_the_run_is_refused() -> None:
    """The evaluation never widens the identity domains the wire addresses."""
    fixture = evaluation_fixture_facts()
    with pytest.raises(CanonicalModelError, match="a unit of no file of the run"):
        _normalize_with(
            unit_risk_result=fixture.unit_risk_result
            | {
                UnitRiskRow(
                    dimension="complexity",
                    symbol=SymbolId(FileId("elsewhere.py"), "f"),
                    start_line=1,
                    band="low",
                )
            }
        )


def test_a_health_delta_needs_a_stated_score() -> None:
    with pytest.raises(CanonicalModelError, match="annotates no stated health score"):
        _normalize_with(
            health_result=None, evaluation_contract=_contract(health_params=())
        )
    with pytest.raises(CanonicalModelError, match="annotates no stated health score"):
        _normalize_with(
            health_result=_health(
                score=None, grade=None, dimensions=None, population="complete_empty"
            )
        )


def test_a_health_delta_states_exactly_its_term() -> None:
    foreign = frozenset(
        {
            MetricDeltaRow(
                delta="new_api_symbols",
                value=1,
                baseline_scope_id=FIXTURE_BASELINE_SCOPE_ID,
                root_digest=FIXTURE_ROOT_DIGEST,
            )
        }
    )
    with pytest.raises(CanonicalModelError, match="not exactly its term"):
        _normalize_comparison_with(health_delta=foreign)


def test_a_health_delta_against_an_untrusted_health_lane_is_refused() -> None:
    """Both boundaries: an untrusted health input lane refuses the delta; an
    untrusted lane health does not read admits it."""
    comparison = evaluated_fixture_model().facts.comparison
    lanes = comparison.lane_trust
    for lane, refused in (("dead_code", True), ("api_surface", False)):
        untrusted = frozenset(
            replace(row, status="unavailable", reason="payload_schema_outdated")
            if row.lane == lane
            else row
            for row in lanes
        )
        availability = frozenset(
            replace(row, availability="unavailable") if row.lane == lane else row
            for row in comparison.comparison_availability
        )
        overrides = {"lane_trust": untrusted, "comparison_availability": availability}
        if lane == "api_surface":
            overrides["api_surface_delta"] = frozenset()
        if refused:
            with pytest.raises(
                CanonicalModelError, match=r"\['dead_code'\] are untrusted"
            ):
                _normalize_comparison_with(**overrides)
        else:
            _normalize_comparison_with(**overrides)


# ---------------------------------------------------------------------------
# The store: rows in ``objects``, read back by name, DDL 0.
# ---------------------------------------------------------------------------


def test_each_evaluation_family_is_read_back_under_its_own_name(
    tmp_path: Path,
) -> None:
    model = evaluated_fixture_model()
    expected = model.normalize().facts
    with RunStore(tmp_path / "runs.sqlite3") as store:
        run_id = _publish(store, model)
        whole = store.read_run(run_id).facts
        read = {
            entry.family: store.read_family(run_id, entry)
            for entry in _EVALUATION_FAMILIES
        }
    assert whole.evaluation == expected.evaluation
    assert whole.comparison.health_delta == expected.comparison.health_delta
    evaluation = expected.evaluation
    assert read["evaluation_contract"] == (evaluation.evaluation_contract,)
    assert read["evaluation_request"] == (evaluation.evaluation_request,)
    assert read["gate_outcome"] == (evaluation.gate_outcome,)
    assert read["health_result"] == (evaluation.health_result,)
    assert frozenset(read["unit_risk_result"]) == evaluation.unit_risk_result
    assert frozenset(read["finding_evaluation"]) == evaluation.finding_evaluation
    assert frozenset(read["hotlist_selection"]) == evaluation.hotlist_selection
    assert frozenset(read["health_delta"]) == expected.comparison.health_delta


def test_the_evaluation_families_take_no_ddl(tmp_path: Path) -> None:
    assert STORAGE_SCHEMA_REVISION == "1"
    path = tmp_path / "runs.sqlite3"
    with RunStore(path) as store:
        _publish(store, evaluated_fixture_model())
    connection = sqlite3.connect(path)
    try:
        schema = {
            name
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'index')"
            )
        }
        families = {
            family
            for (family,) in connection.execute("SELECT DISTINCT family FROM objects")
        }
    finally:
        connection.close()
    names = {entry.family for entry in _EVALUATION_FAMILIES}
    assert names <= families
    assert not any(any(name in item for name in names) for item in schema)


def test_each_evaluation_family_takes_the_namespace_of_its_contracts() -> None:
    gate = (
        f"gate_algorithm:{GATE_ALGORITHM_REVISION}"
        f":gate_lane_matrix:{GATE_LANE_MATRIX_VERSION}"
    )
    health = (
        f"health_algorithm:{HEALTH_ALGORITHM_REVISION}"
        f":health_input_manifest:{HEALTH_INPUT_MANIFEST_VERSION}"
    )
    metrics_baseline = (
        f"baseline_schema:{BASELINE_SCHEMA_VERSION}"
        f":metrics_baseline_schema:{METRICS_BASELINE_SCHEMA_VERSION}"
    )
    expected = {
        "evaluation_contract": f"{gate}:{health}",
        "evaluation_request": gate,
        "gate_outcome": gate,
        "health_result": health,
        "unit_risk_result": (
            f"{health}:complexity_metrics:{COMPLEXITY_ALGORITHM_REVISION}"
            f":design_metrics:{DESIGN_METRICS_ALGORITHM_REVISION}"
        ),
        "finding_evaluation": f"canonical_model:{CANONICAL_MODEL_REVISION}",
        "hotlist_selection": f"canonical_model:{CANONICAL_MODEL_REVISION}",
        "health_delta": f"{metrics_baseline}:{health}",
    }
    assert {entry.family: entry.namespace for entry in _EVALUATION_FAMILIES} == expected


@pytest.mark.parametrize(
    "record",
    ["evaluation_contract", "evaluation_request", "gate_outcome", "health_result"],
)
def test_two_stored_evaluation_records_of_one_run_are_a_writer_defect(
    record: str,
) -> None:
    value = getattr(evaluation_fixture_facts(), record)
    with pytest.raises(StoreIntegrityError, match=f"more than one {record}"):
        _collected_model({record: [value, value]})


@pytest.mark.parametrize(
    ("family", "field", "value", "match"),
    [
        ("evaluation_request", "terms", [["fail_cycles", "yes"]], "is not an int"),
        ("evaluation_request", "terms", {"a": 1}, "not a list"),
        ("evaluation_contract", "health_params", [["a", "1"]], "not a number"),
        ("evaluation_contract", "health_params", [["a", True]], "not a number"),
        (
            "evaluation_contract",
            "active_gate_lane_requirements",
            [["gate", "dead_code"]],
            "is not an array",
        ),
        (
            "evaluation_contract",
            "active_gate_lane_requirements",
            [["gate", [1]]],
            "carries a non-string",
        ),
        ("health_result", "dimensions", [["clones", 1.5]], "is not an int"),
        ("health_result", "score", "70", "neither an int nor null"),
        ("health_result", "score", True, "neither an int nor null"),
        ("finding_evaluation", "priority", 1, "is not a float"),
        ("gate_outcome", "exit_code", "3", "is not an int"),
    ],
)
def test_a_malformed_stored_evaluation_field_is_refused(
    family: str, field: str, value: object, match: str
) -> None:
    """The decoders are the wall: each malformed stored value is a typed
    refusal at decode, never a coerced row."""
    from codeclone.canonical.store import _collect_row, _model_rows

    stored = {
        name: row
        for name, row in _model_rows(evaluated_fixture_model().normalize())
        if name == family
    }
    row = dict(stored[family])
    row[field] = value
    with pytest.raises(StoreIntegrityError, match=match):
        _collect_row(family, row, f"{family} object", {})


def test_the_evaluation_house_enters_the_store_run_and_not_the_wire(
    tmp_path: Path,
) -> None:
    """The evaluation facts are MEMBERS of the run — its identity names the
    evaluation it made — while the artifact the run exports is the
    analysis-only wire, byte for byte.  Two requests over one analysis are
    two store runs (the input the store bump has to decide)."""
    compared = replace(
        evaluated_fixture_model(),
        facts=replace(
            evaluated_fixture_model().facts,
            evaluation=EvaluationFacts(),
            comparison=replace(
                evaluated_fixture_model().facts.comparison, health_delta=frozenset()
            ),
        ),
    )
    evaluated = evaluated_fixture_model()
    fixture = evaluation_fixture_facts()
    other_request = "e3" + "b" * 62
    reevaluated = replace(
        evaluated,
        facts=replace(
            evaluated.facts,
            evaluation=replace(
                fixture,
                evaluation_contract=_contract(gate_thresholds_digest=other_request),
                evaluation_request=_request(gate_thresholds_digest=other_request),
                gate_outcome=_outcome(
                    gate_thresholds_digest=other_request,
                    reasons=fixture.gate_outcome.reasons
                    if fixture.gate_outcome
                    else (),
                    required_lanes=("clones.functions", "risk_observations"),
                ),
            ),
        ),
    )
    with RunStore(tmp_path / "runs.sqlite3") as store:
        plain = _publish(store, compared, target="plain")
        full = _publish(store, evaluated, target="full")
        other = _publish(store, reevaluated, target="other")
        plain_bytes, full_bytes = io.BytesIO(), io.BytesIO()
        plain_envelope = export_run(store, plain, plain_bytes)
        full_envelope = export_run(store, full, full_bytes)
        assert store.project_run(full) == encode_canonical_json(fixture_model())
    assert len({plain, full, other}) == 3
    assert full_bytes.getvalue() == plain_bytes.getvalue()
    assert full_envelope.artifact_digest == plain_envelope.artifact_digest
    assert full_envelope.wire_revision == CANONICAL_WIRE_REVISION


# ---------------------------------------------------------------------------
# The negative contract: no evaluation byte on the wire of this revision.
# ---------------------------------------------------------------------------


def test_the_wire_carries_no_evaluation_section() -> None:
    """Byte for byte AND semantically: the encoding of an evaluated model is
    the encoding of the same analysis unevaluated, no member of it names an
    evaluation family, and a decode answers the house empty — "not witnessed
    by this artifact", never "evaluated, nothing concluded"."""
    evaluated = evaluated_fixture_model()
    data = encode_canonical_json(evaluated)
    assert data == encode_canonical_json(fixture_model())
    document = json.loads(data)
    assert "evaluation" not in document
    assert not set(document["facts"]) & set(EvaluationFacts.__annotations__)
    for family in (entry.family for entry in _EVALUATION_FAMILIES):
        assert f'"{family}"'.encode() not in data
    decoded = decode_canonical_json(data)
    assert decoded.facts.evaluation == EvaluationFacts()
    assert decoded.facts.comparison.health_delta == frozenset()


def test_a_revision_one_document_carrying_an_evaluation_section_is_refused() -> None:
    document = json.loads(encode_canonical_json(fixture_model()))
    integrity = document.pop("integrity")
    document["evaluation"] = {}
    document["integrity"] = integrity
    with pytest.raises(WireDecodeError) as refusal:
        decode_canonical_json(json.dumps(document, separators=(",", ":")).encode())
    assert refusal.value.code == "W01"
