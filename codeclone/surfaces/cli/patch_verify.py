# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from ... import ui_messages as ui
from ...budget.patch_contract import (
    VALID_STRICTNESS_PROFILES,
    StrictnessProfile,
    budgets_for_strictness,
)
from ...contracts import ExitCode
from ...contracts.comparison_state import COMPARISON_HEALTH, TERM_SCORE_DELTA
from ...core._types import AnalysisResult
from ...report.gates.evaluator import (
    _POPULATION_REFUSALS,
    GateResult,
    MetricGateConfig,
)
from ...report.messages.comparison import comparison_text, comparison_text_compact
from ...ui_messages.formatters import _patch_verify_compact_health
from ...ui_messages.styling import _L
from ...utils.coerce import as_int as _as_int
from ...utils.coerce import as_mapping as _as_mapping
from ...utils.coerce import as_sequence as _as_sequence
from .baseline_state import CloneBaselineState
from .post_run import DiffContext
from .types import CLIArgsLike, PrinterLike


def validate_strictness(value: str) -> StrictnessProfile:
    if value not in VALID_STRICTNESS_PROFILES:
        expected = ", ".join(sorted(VALID_STRICTNESS_PROFILES))
        raise ValueError(f"Invalid --strictness value: {value!r}. Expected {expected}.")
    if value == "strict":
        return "strict"
    if value == "relaxed":
        return "relaxed"
    return "ci"


def _threshold_or_none(value: object) -> int | None:
    threshold = _as_int(value, -1)
    return threshold if threshold >= 0 else None


def _health_after(analysis: AnalysisResult) -> int:
    metrics = analysis.project_metrics
    if metrics is None:
        return 0
    return max(int(metrics.health.total), 0)


def _health_delta(diff_context: DiffContext) -> int | None:
    """The health comparison the run states (its normalized comparison
    state, ``DiffContext.stated_comparisons``): the delta when it ran,
    ``None`` when it did not -- never a zero the run did not measure."""
    stated = diff_context.stated_comparisons.get(COMPARISON_HEALTH)
    return None if stated is None else stated[TERM_SCORE_DELTA]


def patch_gate_config(
    *,
    args: CLIArgsLike,
    strictness: StrictnessProfile,
) -> MetricGateConfig:
    if strictness == "ci":
        return MetricGateConfig(
            fail_complexity=int(args.fail_complexity),
            fail_coupling=int(args.fail_coupling),
            fail_cohesion=int(args.fail_cohesion),
            fail_cycles=bool(args.fail_cycles),
            fail_dead_code=bool(args.fail_dead_code),
            fail_health=int(args.fail_health),
            fail_on_new_metrics=bool(args.fail_on_new_metrics),
            fail_on_typing_regression=bool(args.fail_on_typing_regression),
            fail_on_docstring_regression=bool(args.fail_on_docstring_regression),
            fail_on_api_break=bool(args.fail_on_api_break),
            fail_on_untested_hotspots=bool(args.fail_on_untested_hotspots),
            min_typing_coverage=int(args.min_typing_coverage),
            min_docstring_coverage=int(args.min_docstring_coverage),
            coverage_min=int(args.coverage_min),
            fail_on_new=True,
            fail_threshold=-1,
        )

    budgets = budgets_for_strictness(
        strictness=strictness,
        coverage_min=int(args.coverage_min),
        complexity_threshold=_threshold_or_none(args.fail_complexity),
        coupling_threshold=_threshold_or_none(args.fail_coupling),
        cohesion_threshold=_threshold_or_none(args.fail_cohesion),
    )
    return MetricGateConfig(
        fail_complexity=budgets.complexity_delta,
        fail_coupling=budgets.coupling_delta,
        fail_cohesion=budgets.cohesion_delta,
        fail_cycles=budgets.dependency_cycle,
        fail_dead_code=budgets.dead_code_regression,
        fail_health=budgets.health_floor,
        fail_on_new_metrics=(
            budgets.typing_regression
            or budgets.docstring_regression
            or budgets.api_break
        ),
        fail_on_typing_regression=budgets.typing_regression,
        fail_on_docstring_regression=budgets.docstring_regression,
        fail_on_api_break=budgets.api_break,
        fail_on_untested_hotspots=budgets.coverage_hotspot,
        min_typing_coverage=int(args.min_typing_coverage),
        min_docstring_coverage=int(args.min_docstring_coverage),
        coverage_min=budgets.coverage_min,
        fail_on_new=budgets.clone_regression == 0,
        fail_threshold=-1,
    )


def _gate_result_from_report_document(
    report_document: Mapping[str, object],
) -> GateResult:
    evaluation = _as_mapping(report_document.get("evaluation"))
    outcome = _as_mapping(evaluation.get("outcome"))
    if not outcome:
        return GateResult(
            exit_code=int(ExitCode.CONTRACT_ERROR),
            reasons=("report:evaluation:missing",),
        )
    return GateResult(
        exit_code=_as_int(outcome.get("exit_code"), int(ExitCode.CONTRACT_ERROR)),
        reasons=tuple(str(item) for item in _as_sequence(outcome.get("reasons"))),
    )


#: The gate's closed exit contract.  A pass and a failure on a fact are a
#: verdict; the contract-error code is a required check that did not run (a
#: lane it could not read, a comparison the run did not make, a missing
#: evaluation); the internal-error code is the gate's own crash.  Any other
#: exit is a protocol error of the evaluation -- never a check that did not
#: run, never a verdict (ruling 2026-10-20 (17)).
_GATE_PASSED: Final = int(ExitCode.SUCCESS)
_GATE_UNAVAILABLE: Final = int(ExitCode.CONTRACT_ERROR)
_GATE_FAILED: Final = int(ExitCode.GATING_FAILURE)
_GATE_CRASHED: Final = int(ExitCode.INTERNAL_ERROR)
_GATE_ANSWERS: Final = (_GATE_PASSED, _GATE_UNAVAILABLE, _GATE_FAILED)
#: The gate's population refusals, worded as the gate states them (its one
#: table, ``_POPULATION_REFUSALS``): the gate's failure code over a
#: population nobody measured is an answer it declined to give, never a
#: fact it found.
_POPULATION_REFUSAL_REASONS: Final = frozenset(
    f"metric:{reason}" for reason in _POPULATION_REFUSALS.values()
)


def _refused_over_the_population(gate_result: GateResult) -> bool:
    return (
        gate_result.exit_code == _GATE_FAILED
        and bool(gate_result.reasons)
        and all(reason in _POPULATION_REFUSAL_REASONS for reason in gate_result.reasons)
    )


#: The gate label: one word per gate outcome (maintainer ruling 2026-10-23).
#: It names what the gate said, never the patch verdict, and it never changes
#: an exit code.  ``REFUSED`` is a baseline the run would not compare against
#: -- another project's, one that failed its integrity check, or one written
#: under an incompatible contract; ``UNAVAILABLE`` is a measurement the run
#: did not have -- no baseline, a comparison it did not make, a population
#: nobody measured, a missing evaluation.
GATE_LABEL_PASS: Final = "PASS"
GATE_LABEL_VIOLATED: Final = "VIOLATED"
GATE_LABEL_REFUSED: Final = "REFUSED"
GATE_LABEL_UNAVAILABLE: Final = "UNAVAILABLE"
GATE_LABEL_ERROR: Final = "ERROR"
_LANE_UNAVAILABLE_PREFIX: Final = "lane:unavailable:"
#: The lane-trust word for a trusted lane, and for a lane with no container
#: behind it (``canonical.comparison_rows.LANE_TRUST_COMPATIBLE`` and
#: ``LANE_TRUST_BASELINE_MISSING``, which a surface may not import).  Every
#: other lane-trust reason the document states is a refusal of that lane.
_LANE_TRUSTED: Final = "compatible"
_LANE_NO_CONTAINER: Final = "baseline_missing"
#: The baseline file statuses that are not a refusal: no file at all, or a
#: status the document does not state.  Any other status is a file the run
#: found and refused (integrity, schema, scope id, ...): it records every
#: lane as having no container, so the file status is what tells the two
#: apart.
_BASELINE_NOT_REFUSED: Final = frozenset({"missing", "ok", ""})


def _refused_by_the_baseline(
    gate_result: GateResult, report_document: Mapping[str, object]
) -> bool:
    """The gate named unavailable lanes, and the document states each of
    those lanes refused -- read off the run's own lane trust and baseline
    status, never re-derived.  A refused lane beside one the run simply did
    not compare is not a refusal of the whole gate."""
    lanes = [
        reason.removeprefix(_LANE_UNAVAILABLE_PREFIX)
        for reason in gate_result.reasons
        if reason.startswith(_LANE_UNAVAILABLE_PREFIX)
    ]
    if not lanes:
        return False
    baseline = _as_mapping(report_document.get("baseline"))
    trust = {
        str(row.get("name", "")): str(row.get("reason", ""))
        for row in (
            _as_mapping(item)
            for item in _as_sequence(baseline.get("sorted_lane_trust"))
        )
    }
    meta_baseline = _as_mapping(
        _as_mapping(report_document.get("meta")).get("baseline")
    )
    file_refused = str(meta_baseline.get("status") or "") not in _BASELINE_NOT_REFUSED

    def refused(lane: str) -> bool:
        reason = trust.get(lane)
        if reason == _LANE_NO_CONTAINER:
            return file_refused
        return reason is not None and reason != _LANE_TRUSTED

    return all(refused(lane) for lane in lanes)


def gate_label(gate_result: GateResult, report_document: Mapping[str, object]) -> str:
    """The word for the gate's outcome, by its closed exit contract."""
    code = gate_result.exit_code
    if code == _GATE_PASSED:
        return GATE_LABEL_PASS
    if code == _GATE_FAILED:
        if _refused_over_the_population(gate_result):
            return GATE_LABEL_UNAVAILABLE
        return GATE_LABEL_VIOLATED
    if code == _GATE_UNAVAILABLE:
        if _refused_by_the_baseline(gate_result, report_document):
            return GATE_LABEL_REFUSED
        return GATE_LABEL_UNAVAILABLE
    return GATE_LABEL_ERROR


def contract_violations(
    *, diff_context: DiffContext, gate_result: GateResult
) -> tuple[str, ...]:
    """What the run PROVED against the patch: new clone groups on the clone
    lanes it compared, or a gate that failed on a fact.  A lane that was not
    compared proves nothing either way and is never counted here, and
    neither is the gate's refusal to answer over an unmeasured population
    (:func:`policy_failures`)."""
    violations: list[str] = []
    if diff_context.clone_novelty_available and diff_context.new_clones_count > 0:
        violations.append("structural_regressions")
    if gate_result.exit_code == _GATE_FAILED and not _refused_over_the_population(
        gate_result
    ):
        violations.append("gate_failures")
    return tuple(violations)


def policy_failures(gate_result: GateResult) -> tuple[str, ...]:
    """The measurements the policy required and the run did not make: the
    gate's population refusals (``unmeasured``, ``complete_empty``), as it
    stated them.  Never a proven violation, never a regression -- the
    verification is incomplete (ruling 2026-10-20 (17))."""
    return gate_result.reasons if _refused_over_the_population(gate_result) else ()


def _clone_lanes_not_compared(report_document: Mapping[str, object]) -> list[str]:
    """``lane:reason`` of every clone lane the document states it did not
    trust -- read off the run's own lane trust, never re-derived."""
    baseline = _as_mapping(report_document.get("baseline"))
    rows = (_as_mapping(row) for row in _as_sequence(baseline.get("sorted_lane_trust")))
    return [
        f"{row.get('name')}:{row.get('reason')}"
        for row in rows
        if str(row.get("name", "")).startswith("clones.")
        and row.get("status") != "trusted"
    ]


def not_verified(
    *,
    diff_context: DiffContext,
    gate_result: GateResult,
    baseline_state: CloneBaselineState,
    report_document: Mapping[str, object],
) -> tuple[str, ...]:
    """Each check the verification needed and could not complete, named: a
    baseline this run cannot trust, every clone lane it did not compare --
    one opaque lane beside a compared one too, under every profile (ruling
    2026-10-20 (17)) -- and a gate that could not answer (a lane it could
    not read, a comparison the run did not make, a missing evaluation).  The
    gate's crash and an exit outside its contract are not here:
    :func:`internal_errors`."""
    reasons: list[str] = []
    if not baseline_state.trusted_for_diff:
        reasons.append(f"baseline:{baseline_state.status.value}")
    lanes = _clone_lanes_not_compared(report_document)
    if lanes:
        reasons.extend(lanes)
    elif not diff_context.clone_novelty_available:
        reasons.append("clones:not_compared")
    if gate_result.exit_code == _GATE_UNAVAILABLE:
        reasons.extend(gate_result.reasons or [f"gate:exit:{gate_result.exit_code}"])
    return tuple(dict.fromkeys(reasons))


def internal_errors(gate_result: GateResult) -> tuple[str, ...]:
    """The gate's internal error with its cause, first-hand: the exit and
    the gate's own reasons -- its crash (5), or an exit outside its closed
    contract, a protocol error named with the code the document carried.
    Neither is an analytical abstention, so neither is folded into what a
    lane could not compare (rulings 2026-10-20 (13), (17)): the
    verification is incomplete and exits with the internal-error code."""
    code = gate_result.exit_code
    if code in _GATE_ANSWERS:
        return ()
    head = (
        f"gate:exit:{code}"
        if code == _GATE_CRASHED
        else f"gate:protocol_error:exit:{code}"
    )
    return (head, *gate_result.reasons)


def patch_status(
    *,
    violations: tuple[str, ...],
    unverified: tuple[str, ...],
    internal: tuple[str, ...],
    policy: tuple[str, ...],
) -> str:
    """One status per row:

    ===============================================  ==================
    the run                                          status
    ===============================================  ==================
    proved a violation                               ``violated``
    proved none; the gate crashed or broke protocol  ``internal_error``
    proved none; a check or a measurement missing    ``unverified``
    proved none; every check ran                     ``accepted``
    ===============================================  ==================

    A proven violation outranks what could not be checked -- the
    uncertainty of one fact never hides the failure of another -- and what
    could not be checked is never accepted.  Whether the verification was
    complete is the second fact, stated beside the status, never inside it.
    """
    if violations:
        return "violated"
    if internal:
        return "internal_error"
    return "unverified" if unverified or policy else "accepted"


def patch_exit_code(
    *,
    violations: tuple[str, ...],
    unverified: tuple[str, ...],
    internal: tuple[str, ...],
    policy: tuple[str, ...],
    strictness: StrictnessProfile,
) -> int:
    """One code per row, under every profile:

    ===============================================  ============================
    the run                                          exit
    ===============================================  ============================
    the gate crashed or broke its exit contract      5 (internal error)
    a required check or measurement did not happen   2 (verification unavailable)
    proved a violation; every check ran              3 (``relaxed``: 0, advisory)
    proved none; every check ran                     0
    ===============================================  ============================

    A check that did not run exits with the contract-error code the gate
    itself returns for an unavailable lane before it evaluates any failure
    (``report.gates.evaluator._unavailable``) -- beside a proven violation
    too, whose verdict still reads ``violated`` -- and never 0: ``relaxed``
    makes a violation advisory, never a missing check.  A crash keeps its
    own code; it is never an abstention and never an acceptance.
    """
    if internal:
        return int(ExitCode.INTERNAL_ERROR)
    if unverified or policy:
        return int(ExitCode.CONTRACT_ERROR)
    if violations and strictness != "relaxed":
        return int(ExitCode.GATING_FAILURE)
    return int(ExitCode.SUCCESS)


def patch_complete(
    *,
    unverified: tuple[str, ...],
    internal: tuple[str, ...],
    policy: tuple[str, ...],
) -> bool:
    """Whether the verification ran to the end: no required check left
    undone, no required measurement missing, no internal error.  The second
    fact of every verdict, stated beside the status, never inside it."""
    return not unverified and not internal and not policy


def _regressions(diff_context: DiffContext) -> int | None:
    """The new clone groups the run compared, or ``None`` when no clone
    lane was compared -- never a zero nobody measured."""
    if not diff_context.clone_novelty_available:
        return None
    return diff_context.new_clones_count


def _compact_line(
    *,
    status: str,
    health_after: int,
    health_delta: int | None,
    regressions: int | None,
    gate_status: str,
) -> str:
    return ui.SUMMARY_COMPACT_PATCH_VERIFY.format(
        status=status,
        health=_patch_verify_compact_health(
            health_after=health_after, health_delta=health_delta
        ),
        regressions=comparison_text_compact(regressions),
        gate_status=gate_status,
    )


def _verdict_line(*, status: str, complete: bool, exit_code: int) -> str:
    if status == "accepted":
        return ui.styled(
            f"{ui.GLYPH_OK} {ui.PATCH_VERIFY_ACCEPTED}", ui.STYLE_VERDICT_PASS_STRONG
        )
    if status == "unverified":
        return ui.styled(
            f"{ui.GLYPH_WARN} {ui.PATCH_VERIFY_UNVERIFIED}", ui.STYLE_VERDICT_WARN
        )
    if status == "internal_error":
        return ui.styled(
            f"{ui.GLYPH_FAIL} {ui.PATCH_VERIFY_INTERNAL_ERROR}", ui.STYLE_VERDICT_FAIL
        )
    if not complete:
        return ui.styled(
            f"{ui.GLYPH_FAIL} {ui.PATCH_VERIFY_VIOLATED_INCOMPLETE}",
            ui.STYLE_VERDICT_FAIL,
        )
    if exit_code != int(ExitCode.SUCCESS):
        return ui.styled(
            f"{ui.GLYPH_FAIL} {ui.PATCH_VERIFY_VIOLATED}", ui.STYLE_VERDICT_FAIL
        )
    return ui.styled(
        f"{ui.GLYPH_WARN} {ui.PATCH_VERIFY_RELAXED_ADVISORY}", ui.STYLE_VERDICT_WARN
    )


#: The verdict word of each status, as the labelled verdict line states it.
_VERDICT_WORDS: Final[Mapping[str, str]] = {
    "accepted": ui.PATCH_VERIFY_VERDICT_ACCEPTED,
    "violated": ui.PATCH_VERIFY_VERDICT_VIOLATED,
    "unverified": ui.PATCH_VERIFY_VERDICT_UNVERIFIED,
    "internal_error": ui.PATCH_VERIFY_VERDICT_INTERNAL_ERROR,
}

#: Why the process exits with its code, beside the code itself.
_EXIT_WHY: Final[Mapping[int, str]] = {
    int(ExitCode.INTERNAL_ERROR): ui.PATCH_VERIFY_EXIT_INTERNAL_ERROR,
    int(ExitCode.CONTRACT_ERROR): ui.PATCH_VERIFY_EXIT_UNAVAILABLE,
    int(ExitCode.GATING_FAILURE): ui.PATCH_VERIFY_EXIT_VIOLATION,
}


def _exit_text(*, exit_code: int, violations: tuple[str, ...]) -> str:
    why = _EXIT_WHY.get(exit_code)
    if why is None and violations:
        why = ui.PATCH_VERIFY_EXIT_ADVISORY
    return f"{exit_code}" if why is None else f"{exit_code} ({why})"


def _listed(values: tuple[str, ...]) -> str:
    return f"[{', '.join(values)}]"


def verdict_lines(
    *,
    status: str,
    violations: tuple[str, ...],
    unverified: tuple[str, ...],
    internal: tuple[str, ...],
    policy: tuple[str, ...],
    exit_code: int,
) -> tuple[str, ...]:
    """Both facts, labelled, in every profile and both output modes: the
    verdict, whether the verification was complete, the exit and why, what
    was proven and what was not verified -- the measurements the policy
    required and the run did not make, and the internal error with its
    cause, when there are any.  Never a bare ``VIOLATED`` that reads as a
    verification that ran to the end."""
    complete = patch_complete(unverified=unverified, internal=internal, policy=policy)
    lines = [
        f"{ui.PATCH_VERIFY_LABEL_STATUS}: {_VERDICT_WORDS[status]}",
        f"{ui.PATCH_VERIFY_LABEL_COMPLETENESS}: "
        + (ui.PATCH_VERIFY_COMPLETE if complete else ui.PATCH_VERIFY_INCOMPLETE),
        f"{ui.PATCH_VERIFY_LABEL_EXIT}: "
        + _exit_text(exit_code=exit_code, violations=violations),
        f"{ui.PATCH_VERIFY_CONTRACT_VIOLATIONS}: {_listed(violations)}",
        f"{ui.PATCH_VERIFY_NOT_VERIFIED}: {_listed(unverified)}",
    ]
    if policy:
        lines.append(f"{ui.PATCH_VERIFY_LABEL_POLICY_FAILURES}: {_listed(policy)}")
    if internal:
        lines.append(f"{ui.PATCH_VERIFY_LABEL_INTERNAL_ERROR}: {_listed(internal)}")
    return tuple(lines)


def _print_verdict_lines(console: PrinterLike, lines: tuple[str, ...]) -> None:
    # One line per label, whatever the terminal width: the bracketed lists
    # are data -- never console markup (``markup=False``), never wrapped onto
    # a second line a reader of the labelled line would miss (``soft_wrap``).
    for line in lines:
        console.print(f"  {line}", markup=False, soft_wrap=True)


def render_patch_verify(
    *,
    console: PrinterLike,
    args: CLIArgsLike,
    strictness: str,
    report_document: Mapping[str, object],
    analysis: AnalysisResult,
    diff_context: DiffContext,
    baseline_state: CloneBaselineState,
    quiet: bool,
) -> int:
    try:
        validated_strictness = validate_strictness(strictness)
    except ValueError as exc:
        console.print(ui.fmt_contract_error(str(exc)))
        return int(ExitCode.CONTRACT_ERROR)

    if not baseline_state.trusted_for_diff:
        console.print(ui.fmt_contract_error(ui.PATCH_VERIFY_BASELINE_UNTRUSTED))

    gate_result = _gate_result_from_report_document(report_document)
    violations = contract_violations(diff_context=diff_context, gate_result=gate_result)
    unverified = not_verified(
        diff_context=diff_context,
        gate_result=gate_result,
        baseline_state=baseline_state,
        report_document=report_document,
    )
    internal = internal_errors(gate_result)
    policy = policy_failures(gate_result)
    status = patch_status(
        violations=violations, unverified=unverified, internal=internal, policy=policy
    )
    exit_code = patch_exit_code(
        violations=violations,
        unverified=unverified,
        internal=internal,
        policy=policy,
        strictness=validated_strictness,
    )
    lines = verdict_lines(
        status=status,
        violations=violations,
        unverified=unverified,
        internal=internal,
        policy=policy,
        exit_code=exit_code,
    )
    health_after = _health_after(analysis)
    health_delta = _health_delta(diff_context)
    regressions = _regressions(diff_context)
    gate_status = gate_label(gate_result, report_document)

    if quiet:
        console.print(
            _compact_line(
                status=status,
                health_after=health_after,
                health_delta=health_delta,
                regressions=regressions,
                gate_status=gate_status,
            )
        )
        _print_verdict_lines(console, lines)
        return exit_code

    from rich.rule import Rule

    console.print()
    console.print(
        Rule(title=ui.PATCH_VERIFY_TITLE, style=ui.STYLE_META, characters=ui.GLYPH_RULE)
    )
    console.print(f"  {ui.PATCH_VERIFY_LABEL_STRICTNESS:<{_L}}{validated_strictness}")
    health_text = ui.fmt_patch_verify_health(
        health_after=health_after, health_delta=health_delta
    )
    console.print(f"  {ui.PATCH_VERIFY_LABEL_HEALTH:<{_L}}{health_text}")
    regressions_text = (
        comparison_text(None)
        if regressions is None
        else ui.n_of(regressions, "new clone group")
    )
    console.print(f"  {ui.PATCH_VERIFY_LABEL_REGRESSIONS:<{_L}}{regressions_text}")
    console.print(
        f"  {ui.PATCH_VERIFY_LABEL_GATE_PREVIEW:<{_L}}{gate_status} "
        f"{ui.PATCH_VERIFY_GATE_EXIT.format(exit_code=gate_result.exit_code)}"
    )
    for reason in gate_result.reasons:
        console.print(f"    - {reason}")
    _print_verdict_lines(console, lines)
    console.print()
    verdict_line = _verdict_line(
        status=status,
        complete=patch_complete(
            unverified=unverified, internal=internal, policy=policy
        ),
        exit_code=exit_code,
    )
    console.print(f"  {verdict_line}")
    return exit_code


__all__ = [
    "GATE_LABEL_ERROR",
    "GATE_LABEL_PASS",
    "GATE_LABEL_REFUSED",
    "GATE_LABEL_UNAVAILABLE",
    "GATE_LABEL_VIOLATED",
    "VALID_STRICTNESS_PROFILES",
    "contract_violations",
    "gate_label",
    "internal_errors",
    "not_verified",
    "patch_complete",
    "patch_exit_code",
    "patch_status",
    "policy_failures",
    "render_patch_verify",
    "validate_strictness",
    "verdict_lines",
]
