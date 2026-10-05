# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The producer of a run's normalized comparison state.

One function, :func:`run_comparison_state`, decides once per run which
comparison against the baseline ran and what it measured, from the run's
own comparison facts: the per-lane trust vector, the lanes the run enabled,
the population it observed, the health verdict it withheld or published,
the baseline terms the comparison context found, and the metrics diff.
The report document and the run store are written from its answer
(``core.reporting``), and every reader reads that answer back
(``contracts.comparison_state``) instead of deciding again.

The decision for each comparison, in the words its old owners used:

* a set-difference family (complexity, coupling, dependencies, dead code)
  ran when every lane it reads is trusted and the current universe was
  observed — on an unobserved universe the current term is empty by
  construction, and "0 new" would state a comparison whose current half
  never existed;
* health ran when its seven input lanes are trusted and the run published
  a verdict;
* adoption ran when the comparison context found a baseline term and the
  health verdict was not withheld (its permilles are ratios over the same
  population);
* the API comparison ran when the comparison context found a baseline term
  over an observed universe AND the run collected the surface it compares:
  a run that did not enable the ``api_surface`` lane compared the baseline
  against nothing, and the "removed" changes it counted are not facts
  (measured 2026-10-05: ``{enabled: false, baseline_diff_available: true,
  breaking: 29}``);
* the clone comparison ran for a lane that is trusted and whose difference
  set exists.

A capability the run did not enable never ran, whatever else holds.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import TYPE_CHECKING

from ..canonical.comparison_state import (
    ComparisonResult,
    ComparisonState,
    comparison_results,
    comparison_state,
)
from ..contracts import population_universe_observed
from ..contracts.comparison_state import (
    COMPARISON_ADOPTION,
    COMPARISON_API_SURFACE,
    COMPARISON_CLONES,
    COMPARISON_COMPLEXITY,
    COMPARISON_COUPLING,
    COMPARISON_DEAD_CODE,
    COMPARISON_DEPENDENCIES,
    COMPARISON_HEALTH,
    COMPARISON_LANES,
    TERM_ADDED_SYMBOLS,
    TERM_BREAKING_CHANGES,
    TERM_DOCSTRING_DELTA,
    TERM_NEW_CYCLES,
    TERM_NEW_DEFERRED_CYCLES,
    TERM_NEW_GROUPS,
    TERM_NEW_HIGH_RISK,
    TERM_NEW_IMPORT_CYCLES,
    TERM_NEW_ITEMS,
    TERM_SCORE_DELTA,
    TERM_SIGNATURE_CHANGES,
    TERM_TYPING_PARAM_DELTA,
    TERM_TYPING_RETURN_DELTA,
    ComparisonKey,
)
from ..report.document._common import health_verdict_withheld
from ..utils.coerce import as_mapping

if TYPE_CHECKING:
    from ..models import MetricsDiff, TrustVector
    from ._types import AnalysisResult

_SET_DIFF_COMPARISONS = (
    COMPARISON_COMPLEXITY,
    COMPARISON_COUPLING,
    COMPARISON_DEPENDENCIES,
    COMPARISON_DEAD_CODE,
)


def _trusted_lanes(trust: TrustVector | None) -> frozenset[str]:
    if trust is None or not trust.root_verified:
        return frozenset()
    return frozenset(item.name for item in trust.lanes if item.status == "trusted")


def _values(diff: MetricsDiff | None) -> dict[str, dict[str, int]]:
    """Every delta the metrics diff measured, by comparison and term."""
    if diff is None:
        return {}
    return {
        COMPARISON_HEALTH: {TERM_SCORE_DELTA: diff.health_delta},
        COMPARISON_ADOPTION: {
            TERM_TYPING_PARAM_DELTA: int(diff.typing_param_permille_delta),
            TERM_TYPING_RETURN_DELTA: int(diff.typing_return_permille_delta),
            TERM_DOCSTRING_DELTA: int(diff.docstring_permille_delta),
        },
        COMPARISON_API_SURFACE: {
            TERM_BREAKING_CHANGES: len(diff.new_api_breaking_changes),
            TERM_SIGNATURE_CHANGES: len(diff.new_api_signature_changes),
            TERM_ADDED_SYMBOLS: len(diff.new_api_symbols),
        },
        COMPARISON_COMPLEXITY: {TERM_NEW_HIGH_RISK: len(diff.new_high_risk_functions)},
        COMPARISON_COUPLING: {TERM_NEW_HIGH_RISK: len(diff.new_high_coupling_classes)},
        COMPARISON_DEPENDENCIES: {
            TERM_NEW_CYCLES: len(diff.new_cycles),
            TERM_NEW_IMPORT_CYCLES: len(diff.new_import_cycles),
            TERM_NEW_DEFERRED_CYCLES: len(diff.new_deferred_cycles),
        },
        COMPARISON_DEAD_CODE: {TERM_NEW_ITEMS: len(diff.new_dead_code)},
    }


def _clone_results(
    *,
    trusted: frozenset[str],
    enabled: frozenset[str],
    new_func: Collection[str] | None,
    new_block: Collection[str] | None,
) -> dict[ComparisonKey, ComparisonResult]:
    """Read the way the store reads it: a difference set under an untrusted
    lane is not a comparison (``core.comparison_snapshot._compared``)."""
    lanes = COMPARISON_LANES[COMPARISON_CLONES]
    sets = {"clones.blocks": new_block, "clones.functions": new_func}
    compared_sets = [
        sets[lane] for lane in lanes if lane in trusted and sets[lane] is not None
    ]
    return comparison_results(
        COMPARISON_CLONES,
        {TERM_NEW_GROUPS: sum(len(tuple(keys or ())) for keys in compared_sets)},
        ran=bool(compared_sets),
        enabled=not enabled.isdisjoint(lanes),
        lanes_trusted=not trusted.isdisjoint(lanes),
    )


def run_comparison_state(
    *,
    analysis: AnalysisResult,
    metrics_diff: MetricsDiff | None,
    new_func: Collection[str] | None,
    new_block: Collection[str] | None,
    coverage_adoption_diff_available: bool,
    api_surface_diff_available: bool,
    baseline_trust: TrustVector | None,
) -> ComparisonState:
    """The run's comparison deltas, each ``compared(value)`` or
    ``not_compared(reason)``, decided once (module docstring)."""
    trusted = _trusted_lanes(baseline_trust)
    enabled = frozenset(analysis.observation_bundle.contract.enabled_lanes)
    values = _values(metrics_diff)
    metrics_payload = analysis.metrics_payload
    health_withheld = metrics_payload is None or health_verdict_withheld(
        as_mapping(metrics_payload.get("health"))
    )
    universe_observed = analysis.project_metrics is not None and (
        population_universe_observed(analysis.project_metrics.health.population)
    )
    diffed = metrics_diff is not None and metrics_payload is not None
    ran = {
        COMPARISON_HEALTH: diffed
        and trusted.issuperset(COMPARISON_LANES[COMPARISON_HEALTH])
        and not health_withheld,
        COMPARISON_ADOPTION: diffed
        and coverage_adoption_diff_available
        and not health_withheld,
        COMPARISON_API_SURFACE: diffed and api_surface_diff_available,
        **{
            comparison: diffed
            and universe_observed
            and trusted.issuperset(COMPARISON_LANES[comparison])
            for comparison in _SET_DIFF_COMPARISONS
        },
    }
    results = _clone_results(
        trusted=trusted, enabled=enabled, new_func=new_func, new_block=new_block
    )
    for comparison, made in ran.items():
        lanes = COMPARISON_LANES[comparison]
        results.update(
            comparison_results(
                comparison,
                values.get(comparison, {}),
                ran=made,
                enabled=enabled.issuperset(lanes),
                lanes_trusted=trusted.issuperset(lanes),
            )
        )
    return comparison_state(results)


__all__ = ["run_comparison_state"]
