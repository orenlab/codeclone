# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A gate may not answer a question the run never measured.

Every metric gate is a predicate over counted debt, so a run that read no
source file makes all of them silently true: zero cycles, zero dead code, zero
new anything. Two of them — the typing and docstring thresholds — do the
opposite and fail loudly at 0.0 %, which is a verdict about nothing just the
same. This suite pins the single honest outcome for that input, and pins the
reverse skew just as hard: a run that read its whole tree must keep exactly the
verdict it had before.

The truncation half is separate and quieter: a run that read *most* of its
tree can still be gated, but it may not become a baseline — a truncated public
API surface published as the reference turns every unread symbol into a
phantom breaking change on the next run.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from codeclone.contracts import ExitCode
from codeclone.report.gates.evaluator import (
    GateResult,
    GateState,
    MetricGateConfig,
    evaluate_gate_state,
)

_CLEAN_CONFIG = MetricGateConfig(
    fail_complexity=-1,
    fail_coupling=-1,
    fail_cohesion=-1,
    fail_cycles=False,
    fail_dead_code=False,
    fail_health=-1,
    fail_on_new_metrics=False,
)

#: Every switch that turns some gate on, one per row. The point of the table
#: is exhaustiveness: a gate added later without a row here is a gate that can
#: still be answered from an unmeasured population.
_EVERY_GATE: tuple[tuple[str, dict[str, Any]], ...] = (
    ("fail_complexity", {"fail_complexity": 10}),
    ("fail_coupling", {"fail_coupling": 10}),
    ("fail_cohesion", {"fail_cohesion": 10}),
    ("fail_cycles", {"fail_cycles": True}),
    ("fail_dead_code", {"fail_dead_code": True}),
    ("fail_on_unresolved_dead_code", {"fail_on_unresolved_dead_code": True}),
    ("fail_health", {"fail_health": 50}),
    ("fail_on_new_metrics", {"fail_on_new_metrics": True}),
    ("fail_on_typing_regression", {"fail_on_typing_regression": True}),
    ("fail_on_docstring_regression", {"fail_on_docstring_regression": True}),
    ("fail_on_api_break", {"fail_on_api_break": True}),
    ("fail_on_authority_violation", {"fail_on_authority_violation": True}),
    ("fail_on_untested_hotspots", {"fail_on_untested_hotspots": True}),
    ("min_typing_coverage", {"min_typing_coverage": 90}),
    ("min_docstring_coverage", {"min_docstring_coverage": 90}),
    ("fail_on_new", {"fail_on_new": True}),
    ("fail_threshold", {"fail_threshold": 0}),
)

_ALL_LANES = (
    "adoption_counts",
    "api_surface",
    "clones.blocks",
    "clones.functions",
    "coupling_cohesion_observations",
    "dead_code",
    "dependencies",
    "module_identity",
    "risk_observations",
    "semantic_authority",
)

_TRUSTED = dict.fromkeys(_ALL_LANES, "trusted")


def _unmeasured_state(**overrides: Any) -> GateState:
    """The state a run produces when files existed and it opened none."""

    return GateState(health_population="unmeasured", **overrides)


def _empty_scope_state(**overrides: Any) -> GateState:
    """The state a run produces when the scope holds no source file at all."""

    return GateState(health_population="complete_empty", **overrides)


def _measured_clean_state(**overrides: Any) -> GateState:
    """A whole tree read, and nothing wrong with it."""

    fields: dict[str, Any] = {
        "health_population": "complete_nonempty",
        "health_score": 95,
        "typing_param_permille": 1000,
        "docstring_permille": 1000,
    }
    fields.update(overrides)
    return GateState(**fields)


def _evaluate(config: MetricGateConfig, state: GateState) -> GateResult:
    return evaluate_gate_state(
        state=state,
        config=config,
        lane_trust=_TRUSTED,
        enabled_lanes=_ALL_LANES,
    )


# ── the unmeasured population refuses every gate ────────────────────


@pytest.mark.parametrize(
    "overrides",
    [pytest.param(row, id=name) for name, row in _EVERY_GATE],
)
def test_no_gate_is_answered_from_an_unmeasured_population(
    overrides: dict[str, Any],
) -> None:
    """Every switch, one outcome: refusal, not a verdict.

    Thirteen of these gates used to pass in silence because their counters
    were zero by construction. Two — the typing and docstring thresholds —
    used to fail for the wrong reason, quoting 0.0 % coverage of a population
    that was never read. Both shapes are the same defect.
    """

    result = _evaluate(replace(_CLEAN_CONFIG, **overrides), _unmeasured_state())

    assert result.exit_code == int(ExitCode.GATING_FAILURE)
    assert any("unmeasured" in reason for reason in result.reasons)


def test_the_unmeasured_refusal_replaces_the_false_coverage_reason() -> None:
    """Not "passed", not "0.0 % < 90 %" — "we did not measure"."""

    config = replace(_CLEAN_CONFIG, min_typing_coverage=90, min_docstring_coverage=90)

    result = _evaluate(config, _unmeasured_state())

    assert result.exit_code == int(ExitCode.GATING_FAILURE)
    assert not any("coverage below threshold" in reason for reason in result.reasons)


def test_an_unmeasured_run_without_any_gate_stays_silent() -> None:
    """No gate was asked for, so none is answered — and none is invented."""

    result = _evaluate(_CLEAN_CONFIG, _unmeasured_state())

    assert result.exit_code == int(ExitCode.SUCCESS)
    assert result.reasons == ()


def test_lane_unavailability_still_outranks_the_unmeasured_refusal() -> None:
    """A contract error stays a contract error, with its own exit code.

    Ordering matters for CI: a missing lane is a configuration fault (exit 2)
    and must not be downgraded into an ordinary gating failure (exit 3).
    """

    result = evaluate_gate_state(
        state=_unmeasured_state(),
        config=replace(_CLEAN_CONFIG, fail_health=50),
        lane_trust=_TRUSTED,
        enabled_lanes=(),
    )

    assert result.exit_code == int(ExitCode.CONTRACT_ERROR)


# ── an empty scope refuses too, and says so in its own words ────────


@pytest.mark.parametrize(
    "overrides",
    [pytest.param(row, id=name) for name, row in _EVERY_GATE],
)
def test_no_gate_is_answered_over_an_empty_analysis_scope(
    overrides: dict[str, Any],
) -> None:
    """A gate is a predicate about code; here there is no code to predicate.

    Argued from what a gate means, not from what is convenient. The "at most"
    gates (complexity, coupling, cycles, dead code, clones) are vacuously
    satisfied — truthfully, since there really is no debt. The "at least"
    gates are the ones that decide this: ``--fail-health``, ``--min-typing-
    coverage`` and ``--min-docstring-coverage`` ask for a floor on a quantity
    that is *undefined* over an empty set, and today they answer it with a
    fabricated ``0``. One outcome has to cover both families, and the only one
    that invents nothing is a refusal.

    Fail-closed also matches what actually produces an empty scope in a run
    that asked for gates: a mis-pointed root or a mis-configured include list.
    A green CI would hide exactly that. It is additionally the *conservative*
    reading — this input already exits 3 today, by way of the conflation this
    wave removes, so the exit code is preserved and only the reason becomes
    honest.
    """

    result = _evaluate(replace(_CLEAN_CONFIG, **overrides), _empty_scope_state())

    assert result.exit_code == int(ExitCode.GATING_FAILURE)
    assert any("empty analysis scope" in reason for reason in result.reasons)


def test_the_empty_scope_refusal_is_worded_apart_from_the_unmeasured_one() -> None:
    """Two absences, two remediations; an operator must be told which one.

    "No file was read" sends you to look for a dead worker or a permission
    fault. "There is no file in scope" sends you to look at the root and the
    include patterns. A shared string would send everyone to the wrong place.

    ``fail_cycles`` rather than ``fail_health`` on purpose. Written first with
    ``fail_health=50`` this test passed on unfixed code: the default
    ``health_score`` of 0 tripped the health threshold, so exit 3 arrived from
    a sibling mechanism and the refusal under test never ran. The gate chosen
    here cannot fail on a state with zero cycles, so only the refusal can
    produce the exit code below.
    """

    config = replace(_CLEAN_CONFIG, fail_cycles=True)

    empty = _evaluate(config, _empty_scope_state())
    unread = _evaluate(config, _unmeasured_state())

    assert empty.exit_code == unread.exit_code == int(ExitCode.GATING_FAILURE)
    assert empty.reasons != unread.reasons
    assert any("empty analysis scope" in reason for reason in empty.reasons)
    assert any("unmeasured" in reason for reason in unread.reasons)
    assert not any("unmeasured" in reason for reason in empty.reasons)
    assert not any("empty analysis scope" in reason for reason in unread.reasons)


def test_an_empty_scope_without_any_gate_stays_silent() -> None:
    """No gate was asked for, so none is refused — and none is invented."""

    result = _evaluate(_CLEAN_CONFIG, _empty_scope_state())

    assert result.exit_code == int(ExitCode.SUCCESS)
    assert result.reasons == ()


def test_lane_unavailability_still_outranks_the_empty_scope_refusal() -> None:
    """Same ordering law as the unmeasured refusal: exit 2 is not exit 3."""

    result = evaluate_gate_state(
        state=_empty_scope_state(),
        config=replace(_CLEAN_CONFIG, fail_health=50),
        lane_trust=_TRUSTED,
        enabled_lanes=(),
    )

    assert result.exit_code == int(ExitCode.CONTRACT_ERROR)


# ── reverse skew: a measured run keeps the verdict it earned ────────


@pytest.mark.parametrize(
    "overrides",
    [pytest.param(row, id=name) for name, row in _EVERY_GATE],
)
def test_a_measured_clean_run_is_never_refused(overrides: dict[str, Any]) -> None:
    """False silence must not become false alarm.

    Same table, same gates, a population that was fully read and holds no
    debt: every one of them must still pass. A refusal that leaked into this
    row would be the original defect wearing the opposite sign.
    """

    result = _evaluate(replace(_CLEAN_CONFIG, **overrides), _measured_clean_state())

    assert result.exit_code == int(ExitCode.SUCCESS)
    assert result.reasons == ()


def test_a_measured_run_still_fails_for_its_own_reasons() -> None:
    """The refusal does not swallow real findings on a measured run."""

    config = replace(_CLEAN_CONFIG, fail_cycles=True)
    state = _measured_clean_state(import_dependency_cycles=2)

    result = _evaluate(config, state)

    assert result.exit_code == int(ExitCode.GATING_FAILURE)
    assert any("cycles" in reason.lower() for reason in result.reasons)
    assert not any("unmeasured" in reason for reason in result.reasons)


def test_a_partial_run_is_not_treated_as_unmeasured() -> None:
    """Truncation is not absence: a partial run keeps its ordinary verdict."""

    result = _evaluate(
        replace(_CLEAN_CONFIG, fail_health=50),
        _measured_clean_state(health_population="partial", files_skipped=3),
    )

    assert result.exit_code == int(ExitCode.SUCCESS)


# ── the truncation gate, opt-in ─────────────────────────────────────


def test_truncated_run_fails_when_the_truncation_gate_is_asked_for() -> None:
    """Files lost to a dead worker or a permission fault, made loud."""

    config = replace(_CLEAN_CONFIG, fail_on_truncated_run=True)
    state = _measured_clean_state(health_population="partial", files_skipped=29)

    result = _evaluate(config, state)

    assert result.exit_code == int(ExitCode.GATING_FAILURE)
    assert any("29" in reason for reason in result.reasons)


def test_complete_run_passes_the_truncation_gate() -> None:
    """The reverse skew: nothing skipped, nothing to report."""

    config = replace(_CLEAN_CONFIG, fail_on_truncated_run=True)

    result = _evaluate(config, _measured_clean_state(files_skipped=0))

    assert result.exit_code == int(ExitCode.SUCCESS)


def test_truncation_stays_silent_until_it_is_asked_for() -> None:
    """Opt-in: turning this on by default is a policy call, not a fix."""

    state = _measured_clean_state(health_population="partial", files_skipped=29)

    result = _evaluate(_CLEAN_CONFIG, state)

    assert result.exit_code == int(ExitCode.SUCCESS)
