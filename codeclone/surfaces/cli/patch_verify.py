# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Sequence

from ... import ui_messages as ui
from ...contracts import ExitCode
from ...core._types import AnalysisResult
from ...report.gates.evaluator import (
    GateResult,
    GateState,
    MetricGateConfig,
    evaluate_gate_state,
    gate_state_from_project_metrics,
)
from ...utils.coerce import as_int as _as_int
from ..mcp._patch_contract import (
    VALID_STRICTNESS_PROFILES,
    StrictnessProfile,
    budgets_for_strictness,
)
from .baseline_state import CloneBaselineState
from .post_run import DiffContext
from .types import CLIArgsLike, PrinterLike

_STATUS_STYLES = {
    "accepted": "bold green",
    "violated": "bold red",
    "unverified": "yellow",
}


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


def _health_delta(metrics_diff: object | None) -> int:
    if metrics_diff is None:
        return 0
    return _as_int(getattr(metrics_diff, "health_delta", 0), 0)


def _metric_gate_config(
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


def _gate_state(
    *,
    analysis: AnalysisResult,
    diff_context: DiffContext,
) -> GateState:
    clone_total = analysis.func_clones_count + analysis.block_clones_count
    if analysis.project_metrics is None:
        return GateState(
            clone_new_count=diff_context.new_clones_count,
            clone_total=clone_total,
        )
    return gate_state_from_project_metrics(
        project_metrics=analysis.project_metrics,
        coverage_join=analysis.coverage_join,
        metrics_diff=diff_context.metrics_diff,
        clone_new_count=diff_context.new_clones_count,
        clone_total=clone_total,
    )


def _evaluate_patch_gates(
    *,
    args: CLIArgsLike,
    strictness: StrictnessProfile,
    analysis: AnalysisResult,
    diff_context: DiffContext,
) -> GateResult:
    return evaluate_gate_state(
        state=_gate_state(analysis=analysis, diff_context=diff_context),
        config=_metric_gate_config(args=args, strictness=strictness),
    )


def _status_text(status: str) -> str:
    style = _STATUS_STYLES.get(status)
    return f"[{style}]{status}[/{style}]" if style else status


def _gate_status(gate_result: GateResult) -> str:
    return "FAIL" if gate_result.exit_code != 0 else "pass"


def _contract_violations(
    *,
    diff_context: DiffContext,
    gate_result: GateResult,
) -> tuple[str, ...]:
    violations: list[str] = []
    if diff_context.new_clones_count > 0:
        violations.append("structural_regressions")
    if gate_result.exit_code != 0:
        violations.append("gate_failures")
    return tuple(violations)


def _render_reasons(
    *,
    console: PrinterLike,
    title: str,
    values: Sequence[str],
) -> None:
    console.print(f"  [bold]{title}:[/bold]")
    if not values:
        console.print("    [dim]none[/dim]")
        return
    for value in values:
        console.print(f"    - {value}")


def render_patch_verify(
    *,
    console: PrinterLike,
    args: CLIArgsLike,
    strictness: str,
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
        console.print(
            ui.fmt_contract_error(
                "Patch verify requires a trusted baseline. "
                "Run codeclone . --update-baseline first."
            )
        )
        return int(ExitCode.CONTRACT_ERROR)

    gate_result = _evaluate_patch_gates(
        args=args,
        strictness=validated_strictness,
        analysis=analysis,
        diff_context=diff_context,
    )
    violations = _contract_violations(
        diff_context=diff_context,
        gate_result=gate_result,
    )
    status = "violated" if violations else "accepted"
    exit_code = (
        int(ExitCode.GATING_FAILURE)
        if violations and validated_strictness != "relaxed"
        else int(ExitCode.SUCCESS)
    )
    health_after = _health_after(analysis)
    health_before = health_after - _health_delta(diff_context.metrics_diff)
    gate_status = _gate_status(gate_result)

    if quiet:
        console.print(
            ui.fmt_patch_verify_compact(
                status=status,
                health_before=health_before,
                health_after=health_after,
                regressions=diff_context.new_clones_count,
                gate_status=gate_status,
            )
        )
        return exit_code

    from rich.rule import Rule

    console.print()
    console.print(Rule(ui.PATCH_VERIFY_TITLE))
    console.print()
    console.print(
        f"  [bold]{ui.PATCH_VERIFY_LABEL_STRICTNESS}[/bold] {validated_strictness}"
    )
    console.print(
        f"  [bold]{ui.PATCH_VERIFY_LABEL_STATUS}[/bold] {_status_text(status)}"
    )
    console.print()
    console.print(
        f"  [bold]{ui.PATCH_VERIFY_LABEL_HEALTH}[/bold] "
        f"{health_before} -> {health_after} "
        f"(delta: {health_after - health_before})"
    )
    console.print()
    console.print(f"  [bold]{ui.PATCH_VERIFY_LABEL_STRUCTURAL_DELTA}[/bold]")
    console.print(
        f"    {ui.PATCH_VERIFY_LABEL_REGRESSIONS} {diff_context.new_clones_count}"
    )
    console.print(f"    {ui.PATCH_VERIFY_LABEL_IMPROVEMENTS} 0")
    verdict = (
        ui.PATCH_VERIFY_VERDICT_REGRESSED
        if diff_context.new_clones_count > 0
        else ui.PATCH_VERIFY_VERDICT_STABLE
    )
    console.print(f"    {ui.PATCH_VERIFY_LABEL_VERDICT} {verdict}")
    console.print()
    console.print(
        f"  [bold]{ui.PATCH_VERIFY_LABEL_GATE_PREVIEW}[/bold] {gate_status} "
        f"{ui.PATCH_VERIFY_GATE_EXIT.format(exit_code=gate_result.exit_code)}"
    )
    if gate_result.reasons:
        for reason in gate_result.reasons:
            console.print(f"    - {reason}")
    console.print()
    _render_reasons(
        console=console,
        title=ui.PATCH_VERIFY_CONTRACT_VIOLATIONS,
        values=violations,
    )
    console.print()
    if status == "accepted":
        console.print(f"  [bold green]{ui.PATCH_VERIFY_ACCEPTED}[/bold green]")
    elif validated_strictness == "relaxed":
        console.print(f"  [yellow]{ui.PATCH_VERIFY_RELAXED_ADVISORY}[/yellow]")
    else:
        console.print(f"  [bold red]{ui.PATCH_VERIFY_VIOLATED}[/bold red]")
    return exit_code


__all__ = [
    "VALID_STRICTNESS_PROFILES",
    "render_patch_verify",
    "validate_strictness",
]
