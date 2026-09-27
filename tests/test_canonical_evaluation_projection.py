# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Shadow equivalence of the evaluation tier (canonical epoch E3, cycle 3).

Every evaluation-tier field serving census 3 names for this wave, as the MCP
surface answered it, against ``codeclone.canonical.evaluation_projection`` over
the run THAT SAME execution published: the surface is the oracle, the store
rows the shadow.  Seven served populations, each a real MCP execution
(``tests/conftest.py``): the baseline-less serving corpus, the four comparison
populations of E2 (trusted, foreign scope, API lane disabled, partial), and
the two evaluation populations of E3 — a repository whose own gates fail
(analysed twice, then compared) and a clones-only run.

The accounting comes first (Probe Validity Law): the populations are shown to
carry both gate outcomes, a verdict with and without its delta, a verdict
withheld for skipped metrics, a selection its limit cuts and a zone with and
without a high band.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import NamedTuple

import pytest

from codeclone.canonical.evaluation_projection import (
    GATE_CONFIG_KEYS,
    authority_health,
    diff_health_delta,
    finding_severities,
    gate_answer,
    health_payload,
    health_score,
    high_band_paths,
    production_hotspots,
    suggestion_total,
)
from codeclone.canonical.evaluation_rows import GATE_REQUEST_TERMS
from codeclone.canonical.model import CanonicalModel, EvaluationFacts
from codeclone.canonical.store import RunStore
from codeclone.utils.coerce import as_mapping, as_sequence
from tests._served_run import (
    ServedComparisonRun,
    ServedEvaluationRun,
    ServedRunStoreProjection,
)
from tests.conftest import SERVED_COMPARISON_POPULATIONS, SERVED_EVALUATION_GATES
from tests.test_canonical_roundtrip import (
    evaluated_fixture_model,
    evaluation_fixture_facts,
)

_Answers = Mapping[str, Mapping[str, object]]


class _Served(NamedTuple):
    name: str
    model: CanonicalModel
    answers: _Answers


def _read(store_path: Path, run_id: str) -> CanonicalModel:
    with RunStore(store_path) as store:
        return store.read_run(run_id)


def _served(request: pytest.FixtureRequest, name: str) -> _Served:
    if name == "missing":
        projection: ServedRunStoreProjection = request.getfixturevalue(
            "served_run_store_projection"
        )
        return _Served(
            name,
            _read(projection.store_path, projection.store_run_id),
            {
                "run_summary": projection.run_summary,
                "production_triage": projection.production_triage,
            },
        )
    if name in SERVED_COMPARISON_POPULATIONS:
        runs: dict[str, ServedComparisonRun] = request.getfixturevalue(
            "served_comparison_runs"
        )
        run = runs[name]
        return _Served(name, _read(run.store_path, run.store_run_id), run.answers)
    evaluated: dict[str, ServedEvaluationRun] = request.getfixturevalue(
        "served_evaluation_runs"
    )
    served = evaluated[name]
    return _Served(
        name, _read(served.store_path, served.store_run_ids[0]), served.answers
    )


_ALL = ("missing", *SERVED_COMPARISON_POPULATIONS, "gated", "clones_only")
#: The populations asked ``evaluate_gates`` under their own request.
_GATED = (*SERVED_COMPARISON_POPULATIONS, "gated")


def _canonical(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _answer(served: _Served, label: str) -> Mapping[str, object]:
    return as_mapping(served.answers[label])


# -- The accounting ---------------------------------------------------------------


def test_the_served_populations_carry_every_distinguishing_state(
    request: pytest.FixtureRequest,
) -> None:
    """Both gate outcomes under the runs' own requests, a verdict with a
    delta and without one, a verdict withheld for skipped metrics, and the
    population word ``partial``."""
    served = {name: _served(request, name) for name in _ALL}
    exits = {
        name: as_mapping(served[name].answers["evaluate_gates"])["exit_code"]
        for name in _GATED
    }
    assert exits == {**dict.fromkeys(SERVED_COMPARISON_POPULATIONS, 0), "gated": 3}
    availability = {
        name: _answer(item, "run_summary")["health"] for name, item in served.items()
    }
    assert availability["clones_only"] == {
        "available": False,
        "reason": "metrics_skipped",
    }
    delta_stated = {
        name: as_mapping(health).get("baseline_diff_available")
        for name, health in availability.items()
    }
    assert delta_stated == {
        "missing": False,
        "trusted": True,
        "foreign_scope": False,
        "api_disabled": True,
        "partial": True,
        "gated": True,
        "clones_only": None,
    }
    assert as_mapping(availability["partial"])["population"] == "partial"


# -- C1.15 / C2.05 / C5.04 / C8v.07: the health block -------------------------------


@pytest.mark.parametrize("name", _ALL)
@pytest.mark.parametrize("label", ["run_summary", "production_triage"])
def test_the_health_block_matches_the_mcp_surface(
    request: pytest.FixtureRequest, name: str, label: str
) -> None:
    served = _served(request, name)
    assert _canonical(_answer(served, label)["health"]) == _canonical(
        health_payload(served.model)
    )


@pytest.mark.parametrize("name", list(SERVED_COMPARISON_POPULATIONS))
def test_the_pr_summary_health_matches_the_mcp_surface(
    request: pytest.FixtureRequest, name: str
) -> None:
    served = _served(request, name)
    assert _canonical(_answer(served, "pr_summary")["health"]) == _canonical(
        health_payload(served.model)
    )


@pytest.mark.parametrize("name", [*SERVED_COMPARISON_POPULATIONS, "gated"])
def test_the_authority_check_health_matches_the_mcp_surface(
    request: pytest.FixtureRequest, name: str
) -> None:
    served = _served(request, name)
    assert _canonical(_answer(served, "check_authority")["health"]) == _canonical(
        authority_health(served.model)
    )


@pytest.mark.parametrize("name", _ALL)
def test_the_diff_health_delta_matches_the_mcp_surface(
    request: pytest.FixtureRequest, name: str
) -> None:
    """``diff.health_delta`` (census row C1.22, which E2 named for this
    tier): the stored delta, ``None`` when the comparison did not run."""
    served = _served(request, name)
    diff = as_mapping(_answer(served, "run_summary")["diff"])
    assert diff["health_delta"] == diff_health_delta(served.model)


# -- C6b.09 / C3.02 / C6v.02: the per-run health score ------------------------------


@pytest.mark.parametrize("name", _GATED)
def test_the_patch_budget_health_matches_the_mcp_surface(
    request: pytest.FixtureRequest, name: str
) -> None:
    served = _served(request, name)
    state = as_mapping(_answer(served, "patch_budget")["current_state"])
    assert state["health_score"] == health_score(served.model)


def test_the_run_comparison_reads_each_runs_stored_health(
    served_evaluation_runs: dict[str, ServedEvaluationRun],
) -> None:
    """``compare_runs`` of two runs of one session: its ``before`` and
    ``after`` health are the two stored verdicts, and they differ (the
    distinguishing case: a projection that read one run twice would pass on
    equal scores)."""
    gated = served_evaluation_runs["gated"]
    before, after = (_read(gated.store_path, run_id) for run_id in gated.store_run_ids)
    comparison = as_mapping(gated.answers["compare_runs"])
    stated = (
        as_mapping(comparison["before"])["health"],
        as_mapping(comparison["after"])["health"],
    )
    assert stated == (health_score(before), health_score(after))
    assert stated[0] != stated[1]


# -- C4.02-C4.05: the gate answer under the run's own request -----------------------


@pytest.mark.parametrize("name", _GATED)
def test_the_gate_answer_matches_the_mcp_surface(
    request: pytest.FixtureRequest, name: str
) -> None:
    """``would_fail`` / ``exit_code`` / ``reasons`` and the configuration echo,
    byte for byte, when ``evaluate_gates`` is asked the run's own request."""
    served = _served(request, name)
    answer = dict(_answer(served, "evaluate_gates"))
    del answer["run_id"]
    assert _canonical(answer) == _canonical(gate_answer(served.model.facts.evaluation))


def test_the_gate_echo_is_a_subset_of_the_stored_request() -> None:
    """The surface echoes sixteen of the nineteen stored request terms."""
    assert set(GATE_CONFIG_KEYS) < set(GATE_REQUEST_TERMS)
    assert len(GATE_CONFIG_KEYS) == len(set(GATE_CONFIG_KEYS)) == 16


def test_the_gated_request_is_the_repositorys_own(
    served_evaluation_runs: dict[str, ServedEvaluationRun],
) -> None:
    """The ``gated`` run's stored request carries the two gates its
    repository declares — the request the surface was asked is the run's."""
    gated = served_evaluation_runs["gated"]
    model = _read(gated.store_path, gated.store_run_ids[0])
    request = model.facts.evaluation.evaluation_request
    assert request is not None
    terms = dict(request.terms)
    assert {name: terms[name] for name in SERVED_EVALUATION_GATES} == (
        SERVED_EVALUATION_GATES
    )


# -- C2.12 / C2.13 / C2.14: the triage selections -----------------------------------


@pytest.mark.parametrize("name", _ALL)
def test_the_triage_hotspot_selection_matches_the_mcp_surface(
    request: pytest.FixtureRequest, name: str
) -> None:
    """``available`` / ``returned`` and the ranked canonical ids of the cards,
    under the limit the surface was asked with (its default)."""
    served = _served(request, name)
    hotspots = as_mapping(_answer(served, "production_triage")["top_hotspots"])
    items = [as_mapping(item) for item in as_sequence(hotspots["items"])]
    projected = production_hotspots(served.model.facts.evaluation, len(items))
    assert (hotspots["available"], hotspots["returned"]) == (
        projected["available"],
        projected["returned"],
    )
    assert [str(item["canonical_id"]) for item in items] == projected["canonical_ids"]
    severities = finding_severities(served.model.facts.evaluation)
    assert [item["severity"] for item in items] == [
        severities[str(item["canonical_id"])] for item in items
    ]


@pytest.mark.parametrize("name", _ALL)
def test_the_triage_suggestion_total_matches_the_mcp_surface(
    request: pytest.FixtureRequest, name: str
) -> None:
    served = _served(request, name)
    suggestions = as_mapping(_answer(served, "production_triage")["suggestions"])
    assert suggestions["total"] == suggestion_total(served.model.facts.evaluation)


def test_the_hotspot_limit_cuts_the_stored_selection(
    served_evaluation_runs: dict[str, ServedEvaluationRun],
) -> None:
    """The distinguishing case of ``returned``: the surface's limit cuts the
    selection the run stored, so available and returned differ."""
    gated = served_evaluation_runs["gated"]
    hotspots = as_mapping(
        as_mapping(gated.answers["production_triage"])["top_hotspots"]
    )
    returned, available = hotspots["returned"], hotspots["available"]
    assert isinstance(returned, int) and isinstance(available, int)
    assert returned < available


# -- C7.09 / C7.10: the high bands inside a blast zone --------------------------------


def _zone(answer: Mapping[str, object]) -> set[str]:
    return {
        str(path)
        for key in ("origin", "direct_dependents", "transitive_dependents")
        for path in as_sequence(answer.get(key))
    } | {
        str(as_mapping(member).get("path", member))
        if isinstance(member, Mapping)
        else str(member)
        for member in as_sequence(answer.get("clone_cohort_members"))
    }


@pytest.mark.parametrize("name", list(SERVED_COMPARISON_POPULATIONS))
@pytest.mark.parametrize("label", ["blast_known", "blast_new"])
@pytest.mark.parametrize(
    ("dimension", "key"),
    [
        ("complexity", "high_complexity_in_blast_zone"),
        ("coupling", "high_coupling_in_blast_zone"),
    ],
)
def test_the_blast_zone_high_bands_match_the_mcp_surface(
    request: pytest.FixtureRequest, name: str, label: str, dimension: str, key: str
) -> None:
    served = _served(request, name)
    answer = _answer(served, label)
    stated = [
        str(path) for path in as_sequence(as_mapping(answer["structural_risk"])[key])
    ]
    assert stated == high_band_paths(
        served.model.facts.evaluation, dimension, _zone(answer)
    )


@pytest.mark.parametrize(
    ("dimension", "key", "stated"),
    [
        ("complexity", "high_complexity_in_blast_zone", ["pkg/complex_old.py"]),
        ("coupling", "high_coupling_in_blast_zone", ["pkg/hub.py"]),
    ],
)
def test_a_zone_with_high_bands_matches_the_mcp_surface(
    served_evaluation_runs: dict[str, ServedEvaluationRun],
    dimension: str,
    key: str,
    stated: list[str],
) -> None:
    """The distinguishing case of the lists above, whose zones hold no high
    band: a zone that holds one on each dimension, stated by literal."""
    gated = served_evaluation_runs["gated"]
    model = _read(gated.store_path, gated.store_run_ids[0])
    answer = as_mapping(gated.answers["blast_high"])
    risk = as_mapping(answer["structural_risk"])
    assert [str(path) for path in as_sequence(risk[key])] == stated
    assert high_band_paths(model.facts.evaluation, dimension, _zone(answer)) == stated


# -- The projection alone: the outcomes no served population reaches ------------------


@pytest.mark.parametrize(
    ("exit_code", "reasons", "unavailable", "would_fail"),
    [
        (0, (), (), False),
        (2, ("lane:unavailable:risk_observations",), ("risk_observations",), True),
        (3, ("metric:x",), (), True),
    ],
)
def test_the_gate_answer_states_every_outcome(
    exit_code: int,
    reasons: tuple[str, ...],
    unavailable: tuple[str, ...],
    would_fail: bool,
) -> None:
    """m-gate-both-outcomes on the projection: a pass under gates, a lane
    refusal (which the served runs never reach) and a failure; the request
    echo in the surface's key order."""
    fixture = evaluation_fixture_facts()
    assert fixture.gate_outcome is not None
    evaluation = replace(
        fixture,
        gate_outcome=replace(
            fixture.gate_outcome,
            exit_code=exit_code,
            reasons=reasons,
            required_lanes=("risk_observations",),
            unavailable_lanes=unavailable,
        ),
    )
    answer = gate_answer(evaluation)
    assert (answer["would_fail"], answer["exit_code"], answer["reasons"]) == (
        would_fail,
        exit_code,
        list(reasons),
    )
    assert list(as_mapping(answer["config"])) == list(GATE_CONFIG_KEYS)
    assert gate_answer(EvaluationFacts()) == {}


def test_a_run_without_a_verdict_outside_clones_only_is_unavailable() -> None:
    """The surface's second absence: no verdict, and the metrics were not
    skipped — ``unavailable``, never ``metrics_skipped``."""
    model = evaluated_fixture_model()
    bare = replace(
        model,
        facts=replace(
            model.facts,
            evaluation=replace(model.facts.evaluation, health_result=None),
        ),
    )
    assert health_payload(bare) == {"available": False, "reason": "unavailable"}
    assert health_score(bare) is None
    assert authority_health(bare) == {"score": None, "grade": None, "dimensions": {}}


@pytest.mark.parametrize("name", list(SERVED_COMPARISON_POPULATIONS))
def test_the_pr_summary_card_severities_are_the_stored_verdicts(
    request: pytest.FixtureRequest, name: str
) -> None:
    """C5.07's evaluation half: every new finding the PR summary lists for
    the changed paths carries the stored verdict's severity."""
    served = _served(request, name)
    items = [
        as_mapping(item)
        for item in as_sequence(
            _answer(served, "pr_summary_changed")["new_findings_in_changed_files"]
        )
    ]
    severities = finding_severities(served.model.facts.evaluation)
    assert [item["severity"] for item in items] == [
        severities[str(item["canonical_id"])] for item in items
    ]
    # The instrument reaches a card on the trusted population.
    assert name != "trusted" or items
