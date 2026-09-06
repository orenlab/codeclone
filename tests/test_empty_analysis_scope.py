# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""An honestly empty scope is a measurement; an unread one is the absence of it.

``_observed_population`` used to fold both into ``unmeasured`` on the single
predicate ``files_analyzed_or_cached <= 0``. A root with forty files and a dead
worker, and a root with no Python at all, produced the same word — so no layer
downstream could tell "we did not look" apart from "we looked, and there is
nothing there". The first is a broken run; the second is a fact about the
repository.

Four states replace it, and every one of them is pinned here in both
directions: mutating any state into its neighbour must red a *different* test,
never leave the suite green.

The four states live in ``codeclone.contracts`` — the dependency-free ring —
because health, the gates, the baseline publisher and the CLI all decide on
them, and the CLI may not import the model store at all.

The file is deliberately confined to ring r2 (contracts, models, metrics,
baseline, report.gates). The r4 surfaces that render the same fact — CLI
summary line, HTML, markdown, MCP — are pinned in
``tests/test_report_honest_population.py``, which already owns that ring;
importing them here would make every model import above an
architecture-boundary violation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from codeclone.baseline.publish import BaselinePublicationError, publish_baseline
from codeclone.contracts import (
    ObservedPopulation,
    observed_population,
    population_carries_score,
)
from codeclone.metrics.health import (
    HealthInputs,
    compute_health,
    health_not_computed,
    health_report_fields,
)
from codeclone.metrics.registry import project_metrics_defaults
from codeclone.models import HealthScore, ObservationBundle
from codeclone.observations.projection import build_observation_bundle
from tests._ast_metrics_helpers import module_registry_context
from tests._pipeline_fixtures import analysis_boot, run_pipeline_once

_SCOPE_ID = UUID("019f7fa1-8866-7242-b0bf-0ff282cafbcb")
_FUNCTION_ID = f"{'a' * 64}|0-19"
_BLOCK_ID = "|".join(("b" * 64,) * 4)

#: Every state the two counters can name, with the input that produces it.
#: Exhaustive on purpose: a fifth state added without a row here is a state no
#: layer below has been shown to handle.
_STATE_BY_COUNTERS: tuple[tuple[int, int, ObservedPopulation], ...] = (
    (0, 0, "complete_empty"),
    (40, 0, "unmeasured"),
    (1, 0, "unmeasured"),
    (40, 1, "partial"),
    (40, 39, "partial"),
    (40, 40, "complete_nonempty"),
    (1, 1, "complete_nonempty"),
    (0, 5, "complete_nonempty"),
)


def _health_inputs(*, found: int, analyzed: int, **debt: Any) -> HealthInputs:
    base: dict[str, Any] = {
        "files_found": found,
        "files_analyzed_or_cached": analyzed,
        "function_clone_groups": 0,
        "block_clone_groups": 0,
        "complexity_avg": 0.0,
        "complexity_max": 0,
        "high_risk_functions": 0,
        "elevated_complexity_functions": 0,
        "complexity_function_population": 0,
        "coupling_avg": 0.0,
        "coupling_max": 0,
        "high_risk_classes": 0,
        "elevated_coupling_classes": 0,
        "coupling_class_population": 0,
        "cohesion_avg": 0.0,
        "low_cohesion_classes": 0,
        "import_dependency_cycles": 0,
        "deferred_dependency_cycles": 0,
        "dependency_max_depth": 0,
        "dependency_avg_depth": 0.0,
        "dependency_p95_depth": 0,
        "dead_code_items": 0,
    }
    base.update(debt)
    return HealthInputs(**base)


def _bundle() -> ObservationBundle:
    registry = module_registry_context(
        filepath="pkg/mod.py",
        module_name="pkg.mod",
    )[1]
    return build_observation_bundle(
        scan_root=Path("."),
        module_registry=registry,
        function_clone_keys=(_FUNCTION_ID,),
        block_clone_keys=(_BLOCK_ID,),
    )


# ── the owner: one computer, four states ────────────────────────────


@pytest.mark.parametrize(
    ("found", "analyzed", "expected"),
    [
        pytest.param(found, analyzed, expected, id=f"{found}-{analyzed}-{expected}")
        for found, analyzed, expected in _STATE_BY_COUNTERS
    ],
)
def test_every_counter_pair_names_exactly_one_state(
    found: int,
    analyzed: int,
    expected: ObservedPopulation,
) -> None:
    """The decision table, walked from both sides of every boundary.

    A guard no input can reach is theatre, so each of the four states is
    produced here by a concrete pair of counters, and each boundary is crossed
    in both directions.
    """

    assert (
        observed_population(files_found=found, files_analyzed_or_cached=analyzed)
        == expected
    )


def test_an_empty_scope_is_not_an_unread_one() -> None:
    """The defect, stated as one assertion: these two must not be one word.

    ``(0, 0)`` is a complete measurement of an area with no Python in it.
    ``(40, 0)`` is forty files found and none read. Folding them together is
    what let a health grade be issued about code nobody opened, and what let an
    honestly empty repository be called broken.

    Distinctness is asserted over the set rather than with ``empty != unread``:
    written that way, mypy narrows both sides to their literal return types,
    proves the comparison can never be true, and rejects the line — a static
    proof of the same property, but one that leaves nothing to execute.
    """

    empty = observed_population(files_found=0, files_analyzed_or_cached=0)
    unread = observed_population(files_found=40, files_analyzed_or_cached=0)

    assert empty == "complete_empty"
    assert unread == "unmeasured"
    assert len({empty, unread}) == 2


@pytest.mark.parametrize(
    ("population", "carries"),
    [
        ("complete_nonempty", True),
        ("partial", True),
        ("complete_empty", False),
        ("unmeasured", False),
    ],
)
def test_only_a_non_empty_observed_population_carries_a_score(
    population: ObservedPopulation,
    carries: bool,
) -> None:
    """One owner for the derived question every surface asks.

    "Is there a number to show?" is answered once, here. A surface that
    re-derives it from ``score is None`` is reading the consequence instead of
    the fact, and cannot tell the two refusals apart when it has to word them.
    """

    assert population_carries_score(population) is carries


# ── health: an empty area has no health, and says which absence it is ──


def test_compute_health_names_an_empty_scope_rather_than_an_unread_one() -> None:
    score = compute_health(_health_inputs(found=0, analyzed=0))

    assert score.population == "complete_empty"


def test_compute_health_still_names_an_unread_population_unmeasured() -> None:
    """The reverse skew: the new state must not swallow the old one."""

    score = compute_health(_health_inputs(found=40, analyzed=0))

    assert score.population == "unmeasured"


def test_health_refuses_a_verdict_on_an_empty_scope() -> None:
    """90/100 (A) for a directory with no code is the lie in the other sign.

    Six of the seven dimensions count observed debt, so an empty area scores
    like an immaculate one. There is no code, so there is no health: the
    number is withheld, and the reason travels beside it.
    """

    fields = health_report_fields(compute_health(_health_inputs(found=0, analyzed=0)))

    assert fields["score"] is None
    assert fields["grade"] is None
    assert fields["dimensions"] is None
    assert fields["population"] == "complete_empty"


def test_health_keeps_the_two_refusals_apart() -> None:
    """Both withhold the number; they must not withhold the reason too."""

    empty = health_report_fields(compute_health(_health_inputs(found=0, analyzed=0)))
    unread = health_report_fields(compute_health(_health_inputs(found=40, analyzed=0)))

    assert empty["score"] is None and unread["score"] is None
    assert empty["population"] != unread["population"]
    assert empty["population"] == "complete_empty"
    assert unread["population"] == "unmeasured"


@pytest.mark.parametrize(
    ("found", "analyzed", "expected"),
    [(40, 40, "complete_nonempty"), (40, 20, "partial")],
)
def test_health_keeps_its_verdict_wherever_a_population_was_observed(
    found: int,
    analyzed: int,
    expected: str,
) -> None:
    """The reverse skew again: the refusal must not leak onto measured runs."""

    fields = health_report_fields(
        compute_health(_health_inputs(found=found, analyzed=analyzed))
    )

    assert fields["score"] is not None
    assert fields["grade"] is not None
    assert fields["dimensions"] is not None
    assert fields["population"] == expected


def test_a_health_lane_that_never_ran_is_unmeasured_not_empty() -> None:
    """``--skip-metrics`` zeros are placeholders, not observations.

    Deriving the state from them would call an unrun lane ``complete_empty``:
    the exact conflation this split removes, reintroduced from the other end.
    The state is therefore declared here rather than computed.
    """

    not_computed = health_not_computed()
    default = project_metrics_defaults()["health"]

    assert not_computed.population == "unmeasured"
    assert isinstance(default, HealthScore)
    assert default.population == "unmeasured"


# ── baseline publication: two rules, two names, two messages ────────


def test_publication_refuses_an_empty_analysis_scope(tmp_path: Path) -> None:
    """A run that found nothing is not a reference for anything.

    Named on its own, and reachable on its own: nothing was skipped here, so
    the truncation rule cannot be what fired.
    """

    target = tmp_path / "baseline.json"

    with pytest.raises(BaselinePublicationError) as excinfo:
        publish_baseline(
            target=target,
            bundle=_bundle(),
            scope_id=_SCOPE_ID,
            max_size_bytes=5_000_000,
            files_skipped=0,
            analysis_population="complete_empty",
        )

    assert excinfo.value.reason == "empty_analysis_scope"
    assert not target.exists()


def test_the_truncation_rule_keeps_its_own_name_and_message(tmp_path: Path) -> None:
    """The controller's rejected shortcut, pinned so it cannot come back.

    Replacing ``files_skipped > 0`` with "population is not complete" was
    refused: it swaps one symptom for another and merges "truncated" with
    "empty". The two rules stay separate, and each keeps its own wording.
    """

    target = tmp_path / "baseline.json"

    with pytest.raises(BaselinePublicationError) as excinfo:
        publish_baseline(
            target=target,
            bundle=_bundle(),
            scope_id=_SCOPE_ID,
            max_size_bytes=5_000_000,
            files_skipped=29,
            analysis_population="partial",
        )

    assert excinfo.value.reason == "truncated_run"
    assert "29" in str(excinfo.value)


def test_the_two_publication_refusals_do_not_borrow_each_other_s_words(
    tmp_path: Path,
) -> None:
    """An operator must be able to tell which rule stopped the publication."""

    empty_detail = ""
    truncated_detail = ""
    with pytest.raises(BaselinePublicationError) as empty_exc:
        publish_baseline(
            target=tmp_path / "empty.json",
            bundle=_bundle(),
            scope_id=_SCOPE_ID,
            max_size_bytes=5_000_000,
            analysis_population="complete_empty",
        )
    empty_detail = str(empty_exc.value)
    with pytest.raises(BaselinePublicationError) as truncated_exc:
        publish_baseline(
            target=tmp_path / "truncated.json",
            bundle=_bundle(),
            scope_id=_SCOPE_ID,
            max_size_bytes=5_000_000,
            files_skipped=3,
            analysis_population="partial",
        )
    truncated_detail = str(truncated_exc.value)

    assert empty_detail != truncated_detail
    assert "did not read" not in empty_detail
    assert "no source file" not in truncated_detail


@pytest.mark.parametrize("population", ["complete_nonempty", "partial", "unmeasured"])
def test_publication_proceeds_for_every_state_that_is_not_an_empty_scope(
    tmp_path: Path,
    population: ObservedPopulation,
) -> None:
    """The reverse skew: the new rule must fire on one state and no other.

    ``unmeasured`` is included deliberately. It is already refused by the
    truncation rule whenever it can occur in production — a run that found
    files and read none has skipped them all — so the empty-scope rule must
    not claim it as a second owner.
    """

    target = tmp_path / f"{population}.json"

    receipt = publish_baseline(
        target=target,
        bundle=_bundle(),
        scope_id=_SCOPE_ID,
        max_size_bytes=5_000_000,
        files_skipped=0,
        analysis_population=population,
    )

    assert receipt.outcome == "published"
    assert target.exists()


def test_publication_default_is_the_measured_state(tmp_path: Path) -> None:
    """Callers that predate the parameter keep publishing exactly as before."""

    target = tmp_path / "baseline.json"

    receipt = publish_baseline(
        target=target,
        bundle=_bundle(),
        scope_id=_SCOPE_ID,
        max_size_bytes=5_000_000,
    )

    assert receipt.outcome == "published"


# ── end to end: the input that started this ─────────────────────────


def _analyse(
    root: Path, cache_dir: Path
) -> tuple[dict[str, object], ObservedPopulation]:
    """Run the real pipeline once; return its health block and the same state.

    The state is re-read through the owner from the counters the run reports,
    which is exactly what the CLI does before publishing a baseline. Returning
    both lets each test assert that the projection every surface reads and the
    value the publisher is handed cannot disagree.
    """

    boot = analysis_boot(root, min_loc=1, min_stmt=1, skip_metrics=False)
    _cache, run = run_pipeline_once(
        boot,
        cache_dir / "cache.json",
        root=root,
        warm=False,
    )
    payload = run.result.metrics_payload
    assert payload is not None, "metrics payload missing; the run skipped metrics"
    health = payload["health"]
    assert isinstance(health, dict)
    return health, observed_population(
        files_found=run.discovery.files_found,
        files_analyzed_or_cached=run.result.files_analyzed_or_cached,
    )


def test_an_empty_root_reports_an_empty_scope_not_an_unread_one(
    tmp_path: Path,
) -> None:
    """The reproduction: a directory with no Python, analysed end to end."""

    root = tmp_path / "empty"
    root.mkdir()

    health, population = _analyse(root, tmp_path)

    assert health["population"] == "complete_empty"
    assert health["score"] is None
    assert health["grade"] is None
    assert population == "complete_empty"


def test_a_root_with_python_reports_a_non_empty_scope(tmp_path: Path) -> None:
    """The reverse skew end to end: one file is not an empty scope."""

    root = tmp_path / "read"
    root.mkdir()
    (root / "mod.py").write_text("def f() -> int:\n    return 1\n", "utf-8")

    health, population = _analyse(root, tmp_path)

    assert health["population"] == "complete_nonempty"
    assert isinstance(health["score"], int)
    assert population == "complete_nonempty"
