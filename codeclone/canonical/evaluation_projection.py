# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The evaluation-tier fields of the MCP answers, rebuilt from canonical
rows — one owner.

Canonical epoch E3 (2026-09-27).  The evaluation house (``EvaluationFacts``)
carries the realized contract, the request, the gate outcome, the health
verdict, the band of every measured unit, the verdict on every finding and
the document's selections as run-store rows; the comparison house carries the
health delta.  This module answers, from those rows alone, the fields serving
census 3 assigns to the evaluation tier — in the surface's own key order, so a
shadow pin can hold each against the surface's answer byte for byte.  The
surface is the oracle and the store the shadow: nothing here is read by a
surface (the read edge and the cutover are later waves).

**What is projected**: the ``health`` block of the run summary, the triage and
the PR summary, and the authority check's slim copy of it; the health score
the run comparison and the patch-contract budget read per run; the gate
answer ``evaluate_gates`` gives under the run's OWN request, with its
configuration echo; the production-hotspot selection and the suggestion count
of the triage; the severity of a finding card; the high-band paths a blast
radius reports inside its zone.

**What is NOT projected**, named so it cannot rot: an answer under any request
other than the run's own (a (run, request) pair the session realizes — the
patch-contract budget's gate preview is one, under the strictness profile);
the triage's ``returned`` counts are the caller's limit applied to the stored
count, and ``outside_focus`` is arithmetic over counts the surface already
has; every run-against-run verdict; the suggestion text and source kind
(remediation, not evaluation); the MCP ``priority_score`` / ``priority_factors``
(weights the surface owns, derived from stored inputs).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

from codeclone.canonical.evaluation_rows import GATE_PASSED, HotlistRow
from codeclone.canonical.model import CanonicalModel, EvaluationFacts

#: The analysis mode of a run whose metrics never ran (``core.canonical_
#: snapshot.CLONES_ONLY_MODE``, the run population's own word).
CLONES_ONLY_MODE: Final = "clones_only"

#: The sixteen request terms ``evaluate_gates`` echoes, in its key order; the
#: three terms of the stored request it does not echo are
#: ``fail_on_authority_violation``, ``fail_on_truncated_run`` and
#: ``fail_on_unresolved_dead_code``.
GATE_CONFIG_KEYS: Final[tuple[str, ...]] = (
    "fail_on_new",
    "fail_threshold",
    "fail_complexity",
    "fail_coupling",
    "fail_cohesion",
    "fail_cycles",
    "fail_dead_code",
    "fail_health",
    "fail_on_new_metrics",
    "fail_on_typing_regression",
    "fail_on_docstring_regression",
    "fail_on_api_break",
    "fail_on_untested_hotspots",
    "min_typing_coverage",
    "min_docstring_coverage",
    "coverage_min",
)

#: The selection the triage's ``top_hotspots`` ranks.
PRODUCTION_HOTSPOT: Final = "production_hotspot"
_SUGGESTIONS: Final = "suggestions"
_HIGH: Final = "high"


def _clones_only(model: CanonicalModel) -> bool:
    population = model.facts.analysis.analysis_population
    return population is not None and population.analysis_mode == CLONES_ONLY_MODE


def health_payload(model: CanonicalModel) -> dict[str, object]:
    """``health`` of ``get_run_summary`` / ``get_production_triage`` /
    ``generate_pr_summary``: the verdict with its dimensions, and the health
    delta when the comparison stated one (``0`` beside
    ``baseline_diff_available: false`` otherwise, as the document writes it).
    A run without a verdict answers the surface's two absences: the metrics
    were skipped, or no verdict exists."""
    health = model.facts.evaluation.health_result
    if health is None:
        reason = "metrics_skipped" if _clones_only(model) else "unavailable"
        return {"available": False, "reason": reason}
    deltas = model.facts.comparison.health_delta
    return {
        "score": health.score,
        "grade": health.grade,
        "dimensions": None if health.dimensions is None else dict(health.dimensions),
        "population": health.population,
        "baseline_diff_available": bool(deltas),
        "delta": sum(row.value for row in deltas),
    }


def diff_health_delta(model: CanonicalModel) -> int | None:
    """``diff.health_delta`` of ``get_run_summary``: the stored delta, and
    ``None`` when the health comparison did not run.  Measured on the served
    populations; the surface reads the raw metric comparison, so a run whose
    metrics baseline loaded while a health lane stayed untrusted would answer
    a number here where the store states no delta — no served population
    reaches that case (report, 2026-09-27)."""
    return next((row.value for row in model.facts.comparison.health_delta), None)


def health_score(model: CanonicalModel) -> int | None:
    """The one number ``compare_runs`` and the patch-contract budget read:
    ``None`` for a run with no verdict or a withheld one, never ``0``."""
    health = model.facts.evaluation.health_result
    return None if health is None else health.score


def authority_health(model: CanonicalModel) -> dict[str, object]:
    """The slim ``health`` of ``check_authority``: score, grade and every
    dimension (the authority check names no dimension of its own)."""
    health = model.facts.evaluation.health_result
    if health is None:
        return {"score": None, "grade": None, "dimensions": {}}
    return {
        "score": health.score,
        "grade": health.grade,
        "dimensions": {} if health.dimensions is None else dict(health.dimensions),
    }


def gate_answer(evaluation: EvaluationFacts) -> dict[str, object]:
    """``evaluate_gates`` under the run's OWN request: the outcome the run
    stored and the request it echoes (``{}`` for an unevaluated run)."""
    outcome = evaluation.gate_outcome
    request = evaluation.evaluation_request
    if outcome is None or request is None:
        return {}
    terms = dict(request.terms)
    return {
        "would_fail": outcome.exit_code != GATE_PASSED,
        "exit_code": outcome.exit_code,
        "reasons": list(outcome.reasons),
        "config": {key: terms[key] for key in GATE_CONFIG_KEYS},
    }


def _ranked(rows: Iterable[HotlistRow], hotlist: str) -> list[str]:
    return [
        row.finding_id
        for row in sorted(rows, key=lambda row: row.rank)
        if row.hotlist == hotlist
    ]


def selection(evaluation: EvaluationFacts, hotlist: str) -> list[str]:
    """One of the document's selections, in its rank order."""
    return _ranked(evaluation.hotlist_selection, hotlist)


def production_hotspots(evaluation: EvaluationFacts, limit: int) -> dict[str, object]:
    """``top_hotspots`` of the triage without the cards: how many production
    hotspots the run ranked, how many a caller's limit returns, and which."""
    ranked = selection(evaluation, PRODUCTION_HOTSPOT)
    returned = ranked[: max(limit, 0)]
    return {
        "available": len(ranked),
        "returned": len(returned),
        "canonical_ids": returned,
    }


def suggestion_total(evaluation: EvaluationFacts) -> int:
    """``suggestions.total`` of the triage."""
    return len(selection(evaluation, _SUGGESTIONS))


def finding_severities(evaluation: EvaluationFacts) -> dict[str, str]:
    """The severity of every published finding, by its canonical id."""
    return {row.finding_id: row.severity for row in evaluation.finding_evaluation}


def high_band_files(evaluation: EvaluationFacts, dimension: str) -> tuple[str, ...]:
    """Every file holding a unit the run banded high on ``dimension``, sorted:
    the run-wide set a blast zone is cut from."""
    return tuple(
        sorted(
            {
                row.symbol.file.path
                for row in evaluation.unit_risk_result
                if row.dimension == dimension and row.band == _HIGH
            }
        )
    )


def high_band_paths(
    evaluation: EvaluationFacts, dimension: str, zone: Iterable[str]
) -> list[str]:
    """``structural_risk.high_<dimension>_in_blast_zone``: the files of the
    zone that hold a unit the run banded high on that dimension."""
    paths = set(zone)
    return [path for path in high_band_files(evaluation, dimension) if path in paths]


__all__ = [
    "CLONES_ONLY_MODE",
    "GATE_CONFIG_KEYS",
    "PRODUCTION_HOTSPOT",
    "authority_health",
    "diff_health_delta",
    "finding_severities",
    "gate_answer",
    "health_payload",
    "health_score",
    "high_band_files",
    "high_band_paths",
    "production_hotspots",
    "selection",
    "suggestion_total",
]
