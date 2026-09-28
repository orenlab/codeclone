# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Canonical epoch E3 (2026-09-27): the evaluation families, produced and
read back — the producer-native snapshot against the ingest oracle over the
document the SAME execution rendered, on ten populations that between them
carry every state the families distinguish.

The populations are accounted for before anything is compared (Probe
Validity Law): a comparison of two empty houses, or of two houses that both
say "passed" everywhere, proves nothing about the words they did not carry.
The accounting literals are measurements of the comparison corpus and its
evaluation carrier (``tests/conftest.py``), taken 2026-09-27.
"""

from __future__ import annotations

import copy
from collections import Counter
from collections.abc import Mapping
from typing import Any

import pytest

from codeclone.canonical.comparison_ingest import comparison_facts_from_document
from codeclone.canonical.errors import CanonicalModelError, LegacyIngestError
from codeclone.canonical.evaluation_ingest import evaluation_facts_from_document
from codeclone.canonical.finding_projection import projected_finding_groups
from codeclone.canonical.ingest import _document_identity_index
from codeclone.canonical.model import CanonicalModel, EvaluationFacts
from codeclone.metrics.cohesion import cohesion_risk
from codeclone.metrics.complexity import risk_level
from codeclone.metrics.coupling import coupling_risk
from codeclone.report.document.integrity import _params_digest
from tests.conftest import (
    COMPARISON_POPULATIONS,
    EVALUATION_POPULATIONS,
    ComparisonRun,
    EvaluationRun,
)

_Run = ComparisonRun | EvaluationRun


def _oracle(document: Mapping[str, object]) -> EvaluationFacts:
    return evaluation_facts_from_document(document, _document_identity_index(document))


def _all_runs(
    comparison_runs: dict[str, ComparisonRun],
    evaluation_runs: dict[str, EvaluationRun],
) -> dict[str, _Run]:
    return {**comparison_runs, **evaluation_runs}


_POPULATIONS = sorted({*COMPARISON_POPULATIONS, *EVALUATION_POPULATIONS})


# ---------------------------------------------------------------------------
# Producer-native == oracle, one execution, every population.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("population", _POPULATIONS)
def test_the_evaluation_families_agree_between_producer_and_oracle(
    comparison_runs: dict[str, ComparisonRun],
    evaluation_runs: dict[str, EvaluationRun],
    population: str,
) -> None:
    run = _all_runs(comparison_runs, evaluation_runs)[population]
    stored = run.stored.facts
    assert stored.evaluation == _oracle(run.document)
    assert stored.comparison.health_delta == (
        comparison_facts_from_document(run.document).health_delta
    )


def test_the_populations_carry_every_distinguishing_state(
    comparison_runs: dict[str, ComparisonRun],
    evaluation_runs: dict[str, EvaluationRun],
) -> None:
    """The accounting, before any equality is read as a result: all three
    gate outcomes and the gate-less pass, a health verdict with a delta, with
    a measured zero delta, without one, and withheld altogether."""
    runs = _all_runs(comparison_runs, evaluation_runs)
    outcomes = {
        name: (run.stored.facts.evaluation.gate_outcome or _missing()).exit_code
        for name, run in runs.items()
    }
    assert outcomes == {
        **dict.fromkeys(COMPARISON_POPULATIONS, 0),
        "gates_failed": 3,
        "gates_passed": 0,
        "gate_lane": 2,
        "clones_only": 0,
    }
    assert {name: run.exit_code for name, run in evaluation_runs.items()} == {
        "gates_failed": 3,
        "gates_passed": None,
        "gate_lane": 2,
        "clones_only": None,
    }
    passed = evaluation_runs["gates_passed"].stored.facts.evaluation.gate_outcome
    assert passed is not None and passed.required_lanes, "a pass under gates"
    deltas = {
        name: sorted(row.value for row in run.stored.facts.comparison.health_delta)
        for name, run in runs.items()
    }
    assert deltas == {
        "compared": [4],
        "partial": [4],
        "api_disabled": [4],
        "lanes_skipped": [16],
        "foreign_scope": [],
        "missing": [],
        "gates_failed": [0],
        "gates_passed": [0],
        "gate_lane": [],
        "clones_only": [],
    }
    populations = {
        name: (
            None
            if run.stored.facts.evaluation.health_result is None
            else run.stored.facts.evaluation.health_result.population
        )
        for name, run in runs.items()
    }
    assert populations["clones_only"] is None
    assert populations["partial"] == "partial"
    assert {
        value
        for name, value in populations.items()
        if name not in {"clones_only", "partial"}
    } == {"complete_nonempty"}


def _missing() -> Any:
    raise AssertionError("the run was not evaluated")


def _bands(evaluation: EvaluationFacts, dimension: str) -> set[str]:
    return {
        row.band for row in evaluation.unit_risk_result if row.dimension == dimension
    }


@pytest.mark.parametrize(
    ("dimension", "bands"),
    [
        ("complexity", {"high", "low", "medium"}),
        ("coupling", {"high", "low", "medium"}),
        ("cohesion", {"high", "low"}),
    ],
)
def test_the_bands_carry_every_word_they_distinguish(
    evaluation_runs: dict[str, EvaluationRun], dimension: str, bands: set[str]
) -> None:
    """Every band word on the function dimension and the two class
    dimensions (the carrier's middle words)."""
    evaluation = evaluation_runs["gates_failed"].stored.facts.evaluation
    assert _bands(evaluation, dimension) == bands


def test_the_verdicts_carry_every_word_they_distinguish(
    evaluation_runs: dict[str, EvaluationRun],
) -> None:
    """Both confidences (the carrier's structural finding is the medium
    one), all three severities, and a clone type beside its absence."""
    verdicts = evaluation_runs[
        "gates_failed"
    ].stored.facts.evaluation.finding_evaluation
    assert {row.confidence for row in verdicts} == {"high", "medium"}
    assert {row.severity for row in verdicts} == {"critical", "info", "warning"}
    assert {row.clone_type for row in verdicts} == {None, "Type-2", "Type-4"}


def test_a_selection_is_cut_from_a_larger_population(
    evaluation_runs: dict[str, EvaluationRun],
) -> None:
    """The document's cut shortens the production hotspot selection: the
    runtime population is larger than the hotlist that ranks it; on the
    clones-only run the lists are shorter than the cut and no suggestion is
    stated."""
    run = evaluation_runs["gates_failed"]
    production = [
        row
        for row in run.stored.facts.evaluation.hotlist_selection
        if row.hotlist == "production_hotspot"
    ]
    runtime = [
        group
        for group in _document_groups(run.document)
        if group["source_scope"]["impact_scope"] in {"runtime", "mixed"}
    ]
    assert len(production) == 5 < len(runtime) == 17
    clones_only = evaluation_runs["clones_only"].stored.facts.evaluation
    lengths = Counter(row.hotlist for row in clones_only.hotlist_selection)
    assert lengths == {
        "highest_spread": 4,
        "most_actionable": 3,
        "production_hotspot": 4,
    }


def _document_groups(document: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    groups = document["findings"]["groups"]
    clones = groups["clones"]
    return [
        *(
            group
            for kind in ("functions", "blocks", "segments")
            for group in clones[kind]
        ),
        *(
            group
            for family in ("structural", "dead_code", "design", "authority")
            for group in groups[family]["groups"]
        ),
    ]


@pytest.mark.parametrize(
    ("population", "exit_code", "reasons"),
    [
        (
            "gates_failed",
            3,
            (
                "metric:Complexity threshold exceeded: max CC=25, threshold=20.",
                "metric:Health score below threshold: score=66, threshold=99.",
                "clone:new",
            ),
        ),
        ("gates_passed", 0, ()),
        ("gate_lane", 2, ("lane:unavailable:adoption_counts",)),
    ],
)
def test_each_gate_outcome_is_stored_as_the_evaluator_stated_it(
    evaluation_runs: dict[str, EvaluationRun],
    population: str,
    exit_code: int,
    reasons: tuple[str, ...],
) -> None:
    """m-gate-both-outcomes: a failure, a pass and a lane refusal, each with
    its own reasons, as the document's ``evaluation.outcome`` states them."""
    evaluation = evaluation_runs[population].stored.facts.evaluation
    outcome = evaluation.gate_outcome
    request = evaluation.evaluation_request
    assert outcome is not None and request is not None
    assert (outcome.exit_code, outcome.reasons) == (exit_code, reasons)
    document: Any = evaluation_runs[population].document
    assert (
        outcome.gate_thresholds_digest
        == (document["contracts"]["evaluation"]["gate_thresholds_digest"])
    )
    assert dict(request.terms) == document["evaluation"]["request"]


def test_one_analysis_under_two_requests_is_two_store_runs(
    evaluation_runs: dict[str, EvaluationRun],
) -> None:
    """The D-10 input for the store bump, measured: the SAME analysis and the
    same comparison under two gate requests publish two store runs — the
    request digest, the outcome and the realized contract are members — while
    the analysis and comparison houses are equal row for row."""
    failed = evaluation_runs["gates_failed"]
    passed = evaluation_runs["gates_passed"]
    assert failed.stored.facts.analysis == passed.stored.facts.analysis
    assert failed.stored.facts.comparison == passed.stored.facts.comparison
    assert failed.run_id != passed.run_id
    failed_request = failed.stored.facts.evaluation.evaluation_request
    passed_request = passed.stored.facts.evaluation.evaluation_request
    assert failed_request is not None and passed_request is not None
    assert (
        failed_request.gate_thresholds_digest != passed_request.gate_thresholds_digest
    )


def _nested(pairs: tuple[tuple[str, int | float], ...]) -> dict[str, object]:
    nested: dict[str, Any] = {}
    for dotted, value in pairs:
        head, _dot, tail = dotted.partition(".")
        if tail:
            nested.setdefault(head, {})[tail] = value
        else:
            nested[head] = value
    return nested


@pytest.mark.parametrize("population", ["compared", "gates_failed"])
def test_the_stored_health_parameters_are_the_documents_digest_preimage(
    comparison_runs: dict[str, ComparisonRun],
    evaluation_runs: dict[str, EvaluationRun],
    population: str,
) -> None:
    """The flattening is lossless: re-nested, the stored parameters hash to
    the ``params_digest`` the document sealed them under."""
    run = _all_runs(comparison_runs, evaluation_runs)[population]
    contract = run.stored.facts.evaluation.evaluation_contract
    assert contract is not None and contract.health_params
    document: Any = run.document
    realized = document["integrity"]["semantic"]["realized_contracts"]
    health = realized["evaluation"]["health"]
    assert _nested(contract.health_params) == health["params"]
    assert _params_digest(_nested(contract.health_params)) == health["params_digest"]


def test_every_verdict_names_a_published_finding(
    evaluation_runs: dict[str, EvaluationRun],
) -> None:
    """The verdicts reference their findings, never invent one: the ids are
    exactly the published finding universe the analysis skeletons project."""
    model = evaluation_runs["gates_failed"].stored
    published = {
        str(group["id"])
        for groups in projected_finding_groups(model).values()
        for group in groups
    }
    verdicts = {row.finding_id for row in model.facts.evaluation.finding_evaluation}
    assert verdicts == published
    selected = {row.finding_id for row in model.facts.evaluation.hotlist_selection}
    assert selected <= published


def _numerators(model: CanonicalModel) -> dict[tuple[str, object, int], int]:
    facts = model.facts.analysis
    values: dict[tuple[str, object, int], int] = {}
    for risk in facts.risk_observations:
        if risk.dimension == "cyclomatic_complexity":
            values["complexity", risk.symbol, risk.start_line] = risk.numerator
    starts = {
        (row.dimension, row.symbol): row.start_line
        for row in model.facts.evaluation.unit_risk_result
    }
    for observation in facts.coupling_cohesion_observations:
        dimension = {"cbo": "coupling", "lcom4": "cohesion"}.get(observation.dimension)
        if dimension is not None:
            start = starts[dimension, observation.symbol]
            values[dimension, observation.symbol, start] = observation.numerator
    return values


def test_every_stored_band_is_the_band_owner_of_its_measurement(
    evaluation_runs: dict[str, EvaluationRun],
) -> None:
    """Under this run's parameters the stored word is exactly what the band
    owners say of the unit's own analysis measurement — the verdict stored,
    and the owner that decided it, agree on every unit (a zero coupling is
    no observation row, and reads as zero)."""
    model = evaluation_runs["gates_failed"].stored
    owners = {
        "complexity": risk_level,
        "coupling": coupling_risk,
        "cohesion": cohesion_risk,
    }
    numerators = _numerators(model)
    for row in model.facts.evaluation.unit_risk_result:
        measured = numerators.get((row.dimension, row.symbol, row.start_line), 0)
        assert owners[row.dimension](measured) == row.band, row


# ---------------------------------------------------------------------------
# The oracle alone: the empty house, typed refusals, and a positive control.
# ---------------------------------------------------------------------------


def test_a_document_without_an_evaluation_is_the_empty_house(
    evaluation_runs: dict[str, EvaluationRun],
) -> None:
    document = copy.deepcopy(evaluation_runs["gates_failed"].document)
    del document["evaluation"]
    assert _oracle(document) == EvaluationFacts()


def test_the_oracle_sees_one_changed_verdict(
    evaluation_runs: dict[str, EvaluationRun],
) -> None:
    """The positive control of the equivalence above: one severity flipped in
    the document makes the oracle differ from the store — the comparison can
    see a verdict move."""
    run = evaluation_runs["gates_failed"]
    document: Any = copy.deepcopy(run.document)
    group = document["findings"]["groups"]["design"]["groups"][0]
    group["severity"] = "info" if group["severity"] != "info" else "warning"
    group["priority"] = 0.5 if group["severity"] == "info" else 1.0
    assert _oracle(document) != run.stored.facts.evaluation


def _corrupt(
    document: dict[str, Any], path: tuple[str | int, ...], value: object
) -> None:
    target: Any = document
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


@pytest.mark.parametrize(
    ("path", "value", "error", "match"),
    [
        (("contracts", "evaluation"), [], LegacyIngestError, "is not an object"),
        (
            ("evaluation", "request", "fail_complexity"),
            "20",
            LegacyIngestError,
            "not an int",
        ),
        (("evaluation", "outcome", "exit_code"), "3", LegacyIngestError, "not an int"),
        (("evaluation", "outcome", "reasons"), [1], LegacyIngestError, "non-string"),
        (
            ("contracts", "evaluation", "active_gate_lane_requirements"),
            [[1, []]],
            LegacyIngestError,
            "names no gate",
        ),
        (
            ("metrics", "families", "health", "summary", "dimensions"),
            {"clones": "x"},
            LegacyIngestError,
            "not an int",
        ),
        (
            ("metrics", "families", "complexity", "items"),
            {},
            LegacyIngestError,
            "not an array",
        ),
        (("derived", "hotlists"), [], LegacyIngestError, "is not an object"),
        (
            (
                "integrity",
                "semantic",
                "realized_contracts",
                "evaluation",
                "health",
                "params",
            ),
            {"weights": {"clones": "x"}},
            LegacyIngestError,
            "not a number",
        ),
        (("evaluation", "outcome", "exit_code"), 1, CanonicalModelError, "exit code"),
        (
            ("contracts", "evaluation", "gate_thresholds_digest"),
            7,
            LegacyIngestError,
            r"contracts\.evaluation\.gate_thresholds_digest is not a string",
        ),
        (
            ("findings", "groups", "design", "groups", 0, "id"),
            7,
            LegacyIngestError,
            r"finding group\.id is not a string",
        ),
        (
            ("derived", "hotlists", "most_actionable_ids"),
            {},
            LegacyIngestError,
            "most_actionable_ids is not an array",
        ),
    ],
)
def test_a_malformed_evaluation_member_is_a_typed_refusal(
    evaluation_runs: dict[str, EvaluationRun],
    path: tuple[str | int, ...],
    value: object,
    error: type[Exception],
    match: str,
) -> None:
    document = copy.deepcopy(evaluation_runs["gates_failed"].document)
    _corrupt(document, path, value)
    with pytest.raises(error, match=match):
        _oracle(document)


@pytest.mark.parametrize(
    ("container", "member", "match"),
    [
        (
            ("evaluation", "outcome"),
            "reasons",
            "evaluation.outcome is missing 'reasons'",
        ),
        (("derived",), "hotlists", "derived is missing 'hotlists'"),
    ],
)
def test_a_missing_evaluation_member_is_a_typed_refusal(
    evaluation_runs: dict[str, EvaluationRun],
    container: tuple[str, ...],
    member: str,
    match: str,
) -> None:
    """A member the document builder always writes, absent: the oracle's own
    reader (``evaluation.outcome``) and the reader it shares with the
    producer (``derived``) each refuse it by name — never a ``KeyError``."""
    document: Any = copy.deepcopy(evaluation_runs["gates_failed"].document)
    target = document
    for key in container:
        target = target[key]
    del target[member]
    with pytest.raises(LegacyIngestError, match=match):
        _oracle(document)
