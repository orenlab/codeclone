# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ...contracts import DEFAULT_COVERAGE_MIN, ExitCode
from ...metrics.registry import METRIC_FAMILIES
from ...utils.coerce import as_int as _as_int
from ...utils.coerce import as_mapping as _as_mapping
from ...utils.coerce import as_sequence as _as_sequence

if TYPE_CHECKING:
    from ...models import CoverageJoinResult, ProjectMetrics


@dataclass(frozen=True, slots=True)
class MetricGateConfig:
    fail_complexity: int
    fail_coupling: int
    fail_cohesion: int
    fail_cycles: bool
    fail_dead_code: bool
    fail_health: int
    fail_on_new_metrics: bool
    fail_on_typing_regression: bool = False
    fail_on_docstring_regression: bool = False
    fail_on_api_break: bool = False
    fail_on_untested_hotspots: bool = False
    min_typing_coverage: int = -1
    min_docstring_coverage: int = -1
    coverage_min: int = DEFAULT_COVERAGE_MIN
    fail_on_new: bool = False
    fail_threshold: int = -1


@dataclass(frozen=True, slots=True)
class GateResult:
    exit_code: int
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GateState:
    clone_new_count: int = 0
    clone_total: int = 0
    complexity_max: int = 0
    coupling_max: int = 0
    cohesion_max: int = 0
    dependency_cycles: int = 0
    dead_high_confidence: int = 0
    health_score: int = 0
    typing_param_permille: int = 0
    docstring_permille: int = 0
    coverage_join_status: str = ""
    coverage_hotspots: int = 0
    api_breaking_changes: int = 0
    diff_new_high_risk_functions: int = 0
    diff_new_high_coupling_classes: int = 0
    diff_new_cycles: int = 0
    diff_new_dead_code: int = 0
    diff_health_delta: int = 0
    diff_typing_param_permille_delta: int = 0
    diff_typing_return_permille_delta: int = 0
    diff_docstring_permille_delta: int = 0


def summarize_metrics_diff(metrics_diff: object | None) -> dict[str, object] | None:
    if metrics_diff is None:
        return None

    if isinstance(metrics_diff, Mapping):
        payload = metrics_diff
        return {
            "new_high_risk_functions": _as_int(
                payload.get("new_high_risk_functions"),
                0,
            ),
            "new_high_coupling_classes": _as_int(
                payload.get("new_high_coupling_classes"),
                0,
            ),
            "new_cycles": _as_int(payload.get("new_cycles"), 0),
            "new_dead_code": _as_int(payload.get("new_dead_code"), 0),
            "health_delta": _as_int(payload.get("health_delta"), 0),
            "typing_param_permille_delta": _as_int(
                payload.get("typing_param_permille_delta"),
                0,
            ),
            "typing_return_permille_delta": _as_int(
                payload.get("typing_return_permille_delta"),
                0,
            ),
            "docstring_permille_delta": _as_int(
                payload.get("docstring_permille_delta"),
                0,
            ),
            "new_api_symbols": _as_int(payload.get("new_api_symbols"), 0),
            "api_breaking_changes": _as_int(
                payload.get("api_breaking_changes"),
                _as_int(payload.get("new_api_breaking_changes"), 0),
            ),
        }

    new_high_risk_functions = tuple(
        str(item)
        for item in _as_sequence(getattr(metrics_diff, "new_high_risk_functions", ()))
        if str(item).strip()
    )
    new_high_coupling_classes = tuple(
        str(item)
        for item in _as_sequence(getattr(metrics_diff, "new_high_coupling_classes", ()))
        if str(item).strip()
    )
    new_cycles = tuple(
        tuple(str(part) for part in _as_sequence(item) if str(part).strip())
        for item in _as_sequence(getattr(metrics_diff, "new_cycles", ()))
    )
    new_dead_code = tuple(
        str(item)
        for item in _as_sequence(getattr(metrics_diff, "new_dead_code", ()))
        if str(item).strip()
    )
    api_breaking_changes = tuple(
        _as_sequence(getattr(metrics_diff, "new_api_breaking_changes", ()))
    )
    new_api_symbols = tuple(_as_sequence(getattr(metrics_diff, "new_api_symbols", ())))
    return {
        "new_high_risk_functions": len(new_high_risk_functions),
        "new_high_coupling_classes": len(new_high_coupling_classes),
        "new_cycles": len(new_cycles),
        "new_dead_code": len(new_dead_code),
        "health_delta": _as_int(getattr(metrics_diff, "health_delta", 0), 0),
        "typing_param_permille_delta": _as_int(
            getattr(metrics_diff, "typing_param_permille_delta", 0),
            0,
        ),
        "typing_return_permille_delta": _as_int(
            getattr(metrics_diff, "typing_return_permille_delta", 0),
            0,
        ),
        "docstring_permille_delta": _as_int(
            getattr(metrics_diff, "docstring_permille_delta", 0),
            0,
        ),
        "new_api_symbols": len(new_api_symbols),
        "api_breaking_changes": len(api_breaking_changes),
    }


def gate_state_from_project_metrics(
    *,
    project_metrics: ProjectMetrics,
    coverage_join: CoverageJoinResult | None,
    metrics_diff: object | None,
    clone_new_count: int = 0,
    clone_total: int = 0,
) -> GateState:
    diff_summary = summarize_metrics_diff(metrics_diff) or {}
    return GateState(
        clone_new_count=max(clone_new_count, 0),
        clone_total=max(clone_total, 0),
        complexity_max=max(int(project_metrics.complexity_max), 0),
        coupling_max=max(int(project_metrics.coupling_max), 0),
        cohesion_max=max(int(project_metrics.cohesion_max), 0),
        dependency_cycles=len(tuple(project_metrics.dependency_cycles)),
        dead_high_confidence=sum(
            1
            for item in project_metrics.dead_code
            if str(getattr(item, "confidence", "")).strip().lower() == "high"
        ),
        health_score=max(int(project_metrics.health.total), 0),
        typing_param_permille=_permille(
            int(project_metrics.typing_param_annotated),
            int(project_metrics.typing_param_total),
        ),
        docstring_permille=_permille(
            int(project_metrics.docstring_public_documented),
            int(project_metrics.docstring_public_total),
        ),
        coverage_join_status=(
            str(coverage_join.status) if coverage_join is not None else ""
        ),
        coverage_hotspots=(
            int(coverage_join.coverage_hotspots) if coverage_join is not None else 0
        ),
        api_breaking_changes=_as_int(diff_summary.get("api_breaking_changes"), 0),
        diff_new_high_risk_functions=_as_int(
            diff_summary.get("new_high_risk_functions"),
            0,
        ),
        diff_new_high_coupling_classes=_as_int(
            diff_summary.get("new_high_coupling_classes"),
            0,
        ),
        diff_new_cycles=_as_int(diff_summary.get("new_cycles"), 0),
        diff_new_dead_code=_as_int(diff_summary.get("new_dead_code"), 0),
        diff_health_delta=_as_int(diff_summary.get("health_delta"), 0),
        diff_typing_param_permille_delta=_as_int(
            diff_summary.get("typing_param_permille_delta"),
            0,
        ),
        diff_typing_return_permille_delta=_as_int(
            diff_summary.get("typing_return_permille_delta"),
            0,
        ),
        diff_docstring_permille_delta=_as_int(
            diff_summary.get("docstring_permille_delta"),
            0,
        ),
    )


def metric_gate_reasons_for_state(
    *,
    state: GateState,
    config: MetricGateConfig,
) -> tuple[str, ...]:
    gate_keys = sorted(
        {
            gate_key
            for family in METRIC_FAMILIES.values()
            for gate_key in family.gate_keys
        },
        key=lambda gate_key: (_GATE_REASON_ORDER.get(gate_key, 999), gate_key),
    )
    reasons: list[str] = []
    for gate_key in gate_keys:
        builder = _GATE_REASON_BUILDERS.get(gate_key)
        if builder is None:
            continue
        reasons.extend(builder(state=state, config=config))
    return tuple(reasons)


_GATE_REASON_ORDER = {
    "complexity_threshold": 10,
    "coupling_threshold": 20,
    "cohesion_threshold": 30,
    "health_threshold": 40,
    "dependency_cycles": 50,
    "dead_code_high_confidence": 60,
    "new_high_risk_functions": 70,
    "new_high_coupling_classes": 80,
    "new_dependency_cycles": 90,
    "new_dead_code": 100,
    "health_regression": 110,
    "typing_coverage_threshold": 120,
    "docstring_coverage_threshold": 130,
    "typing_regression": 140,
    "docstring_regression": 150,
    "api_breaking_changes": 160,
    "coverage_hotspots": 170,
}


def _reason_if(triggered: bool, message: str) -> tuple[str, ...]:
    return (message,) if triggered else ()


def _complexity_threshold_reason(
    *,
    state: GateState,
    config: MetricGateConfig,
) -> tuple[str, ...]:
    return _reason_if(
        0 <= config.fail_complexity < state.complexity_max,
        "Complexity threshold exceeded: "
        f"max CC={state.complexity_max}, "
        f"threshold={config.fail_complexity}.",
    )


def _coupling_threshold_reason(
    *,
    state: GateState,
    config: MetricGateConfig,
) -> tuple[str, ...]:
    return _reason_if(
        0 <= config.fail_coupling < state.coupling_max,
        "Coupling threshold exceeded: "
        f"max CBO={state.coupling_max}, "
        f"threshold={config.fail_coupling}.",
    )


def _cohesion_threshold_reason(
    *,
    state: GateState,
    config: MetricGateConfig,
) -> tuple[str, ...]:
    return _reason_if(
        0 <= config.fail_cohesion < state.cohesion_max,
        "Cohesion threshold exceeded: "
        f"max LCOM4={state.cohesion_max}, "
        f"threshold={config.fail_cohesion}.",
    )


def _health_threshold_reason(
    *,
    state: GateState,
    config: MetricGateConfig,
) -> tuple[str, ...]:
    return _reason_if(
        config.fail_health >= 0 and state.health_score < config.fail_health,
        "Health score below threshold: "
        f"score={state.health_score}, threshold={config.fail_health}.",
    )


def _dependency_cycles_reason(
    *,
    state: GateState,
    config: MetricGateConfig,
) -> tuple[str, ...]:
    return _reason_if(
        config.fail_cycles and state.dependency_cycles > 0,
        f"Dependency cycles detected: {state.dependency_cycles} cycle(s).",
    )


def _dead_code_high_confidence_reason(
    *,
    state: GateState,
    config: MetricGateConfig,
) -> tuple[str, ...]:
    return _reason_if(
        config.fail_dead_code and state.dead_high_confidence > 0,
        f"Dead code detected (high confidence): {state.dead_high_confidence} item(s).",
    )


def _new_high_risk_functions_reason(
    *,
    state: GateState,
    config: MetricGateConfig,
) -> tuple[str, ...]:
    return _reason_if(
        config.fail_on_new_metrics and state.diff_new_high_risk_functions > 0,
        "New high-risk functions vs metrics baseline: "
        f"{state.diff_new_high_risk_functions}.",
    )


def _new_high_coupling_classes_reason(
    *,
    state: GateState,
    config: MetricGateConfig,
) -> tuple[str, ...]:
    return _reason_if(
        config.fail_on_new_metrics and state.diff_new_high_coupling_classes > 0,
        "New high-coupling classes vs metrics baseline: "
        f"{state.diff_new_high_coupling_classes}.",
    )


def _new_dependency_cycles_reason(
    *,
    state: GateState,
    config: MetricGateConfig,
) -> tuple[str, ...]:
    return _reason_if(
        config.fail_on_new_metrics and state.diff_new_cycles > 0,
        f"New dependency cycles vs metrics baseline: {state.diff_new_cycles}.",
    )


def _new_dead_code_reason(
    *,
    state: GateState,
    config: MetricGateConfig,
) -> tuple[str, ...]:
    return _reason_if(
        config.fail_on_new_metrics and state.diff_new_dead_code > 0,
        f"New dead code items vs metrics baseline: {state.diff_new_dead_code}.",
    )


def _health_regression_reason(
    *,
    state: GateState,
    config: MetricGateConfig,
) -> tuple[str, ...]:
    return _reason_if(
        config.fail_on_new_metrics and state.diff_health_delta < 0,
        f"Health score regressed vs metrics baseline: delta={state.diff_health_delta}.",
    )


def _typing_coverage_threshold_reason(
    *,
    state: GateState,
    config: MetricGateConfig,
) -> tuple[str, ...]:
    typing_percent = state.typing_param_permille / 10.0
    return _reason_if(
        config.min_typing_coverage >= 0
        and typing_percent < float(config.min_typing_coverage),
        "Typing coverage below threshold: "
        f"coverage={typing_percent:.1f}%, threshold={config.min_typing_coverage}%.",
    )


def _docstring_coverage_threshold_reason(
    *,
    state: GateState,
    config: MetricGateConfig,
) -> tuple[str, ...]:
    docstring_percent = state.docstring_permille / 10.0
    return _reason_if(
        config.min_docstring_coverage >= 0
        and docstring_percent < float(config.min_docstring_coverage),
        "Docstring coverage below threshold: "
        f"coverage={docstring_percent:.1f}%, "
        f"threshold={config.min_docstring_coverage}%.",
    )


def _typing_regression_reason(
    *,
    state: GateState,
    config: MetricGateConfig,
) -> tuple[str, ...]:
    return _reason_if(
        config.fail_on_typing_regression
        and (
            state.diff_typing_param_permille_delta < 0
            or state.diff_typing_return_permille_delta < 0
        ),
        "Typing coverage regressed vs metrics baseline: "
        f"params_delta={state.diff_typing_param_permille_delta}, "
        f"returns_delta={state.diff_typing_return_permille_delta}.",
    )


def _docstring_regression_reason(
    *,
    state: GateState,
    config: MetricGateConfig,
) -> tuple[str, ...]:
    return _reason_if(
        config.fail_on_docstring_regression and state.diff_docstring_permille_delta < 0,
        "Docstring coverage regressed vs metrics baseline: "
        f"delta={state.diff_docstring_permille_delta}.",
    )


def _api_breaking_changes_reason(
    *,
    state: GateState,
    config: MetricGateConfig,
) -> tuple[str, ...]:
    return _reason_if(
        config.fail_on_api_break and state.api_breaking_changes > 0,
        "Public API breaking changes vs metrics baseline: "
        f"{state.api_breaking_changes}.",
    )


def _coverage_hotspots_reason(
    *,
    state: GateState,
    config: MetricGateConfig,
) -> tuple[str, ...]:
    return _reason_if(
        config.fail_on_untested_hotspots
        and state.coverage_join_status == "ok"
        and state.coverage_hotspots > 0,
        "Coverage hotspots detected: "
        f"hotspots={state.coverage_hotspots}, "
        f"threshold={config.coverage_min}%.",
    )


_GATE_REASON_BUILDERS: dict[str, Callable[..., tuple[str, ...]]] = {
    "complexity_threshold": _complexity_threshold_reason,
    "coupling_threshold": _coupling_threshold_reason,
    "cohesion_threshold": _cohesion_threshold_reason,
    "health_threshold": _health_threshold_reason,
    "dependency_cycles": _dependency_cycles_reason,
    "dead_code_high_confidence": _dead_code_high_confidence_reason,
    "new_high_risk_functions": _new_high_risk_functions_reason,
    "new_high_coupling_classes": _new_high_coupling_classes_reason,
    "new_dependency_cycles": _new_dependency_cycles_reason,
    "new_dead_code": _new_dead_code_reason,
    "health_regression": _health_regression_reason,
    "typing_coverage_threshold": _typing_coverage_threshold_reason,
    "docstring_coverage_threshold": _docstring_coverage_threshold_reason,
    "typing_regression": _typing_regression_reason,
    "docstring_regression": _docstring_regression_reason,
    "api_breaking_changes": _api_breaking_changes_reason,
    "coverage_hotspots": _coverage_hotspots_reason,
}


def evaluate_gate_state(
    *,
    state: GateState,
    config: MetricGateConfig,
) -> GateResult:
    reasons = [
        f"metric:{reason}"
        for reason in metric_gate_reasons_for_state(state=state, config=config)
    ]

    if config.fail_on_new and state.clone_new_count > 0:
        reasons.append("clone:new")

    if 0 <= config.fail_threshold < state.clone_total:
        reasons.append(f"clone:threshold:{state.clone_total}:{config.fail_threshold}")

    if reasons:
        return GateResult(
            exit_code=int(ExitCode.GATING_FAILURE),
            reasons=tuple(reasons),
        )
    return GateResult(exit_code=int(ExitCode.SUCCESS), reasons=())


# codeclone: ignore[dead-code]
def metric_gate_reasons(
    *,
    report_document: Mapping[str, object],
    config: MetricGateConfig,
    metrics_diff: object | None = None,
) -> tuple[str, ...]:
    state = _gate_state_from_report_document(
        report_document=report_document,
        metrics_diff=metrics_diff,
    )
    return metric_gate_reasons_for_state(state=state, config=config)


def evaluate_gates(
    *,
    report_document: Mapping[str, object],
    config: MetricGateConfig,
    baseline_status: str | None = None,
    metrics_diff: object | None = None,
    clone_new_count: int | None = None,
    clone_total: int | None = None,
) -> GateResult:
    _ = baseline_status
    state = _gate_state_from_report_document(
        report_document=report_document,
        metrics_diff=metrics_diff,
        clone_new_count=clone_new_count,
        clone_total=clone_total,
    )
    return evaluate_gate_state(state=state, config=config)


def _gate_state_from_report_document(
    *,
    report_document: Mapping[str, object],
    metrics_diff: object | None,
    clone_new_count: int | None = None,
    clone_total: int | None = None,
) -> GateState:
    findings = _as_mapping(report_document.get("findings"))
    groups = _as_mapping(findings.get("groups"))
    clone_groups = _as_mapping(groups.get("clones"))
    function_groups = _as_sequence(clone_groups.get("functions"))
    block_groups = _as_sequence(clone_groups.get("blocks"))
    derived_clone_new_count = sum(
        1
        for group in (*function_groups, *block_groups)
        if str(_as_mapping(group).get("novelty", "")).strip() == "new"
    )
    metrics = _as_mapping(report_document.get("metrics"))
    families = _as_mapping(metrics.get("families"))
    complexity_summary = _as_mapping(
        _as_mapping(families.get("complexity")).get("summary")
    )
    coupling_summary = _as_mapping(_as_mapping(families.get("coupling")).get("summary"))
    cohesion_summary = _as_mapping(_as_mapping(families.get("cohesion")).get("summary"))
    dependencies_summary = _as_mapping(
        _as_mapping(families.get("dependencies")).get("summary")
    )
    dead_code_summary = _as_mapping(
        _as_mapping(families.get("dead_code")).get("summary")
    )
    health_summary = _as_mapping(_as_mapping(families.get("health")).get("summary"))
    coverage_adoption_summary = _as_mapping(
        _as_mapping(families.get("coverage_adoption")).get("summary")
    )
    api_surface_summary = _as_mapping(
        _as_mapping(families.get("api_surface")).get("summary")
    )
    coverage_join_summary = _as_mapping(
        _as_mapping(families.get("coverage_join")).get("summary")
    )
    diff_summary = summarize_metrics_diff(metrics_diff) or {}
    prefer_diff_summary = metrics_diff is not None
    return GateState(
        clone_new_count=max(
            clone_new_count if clone_new_count is not None else derived_clone_new_count,
            0,
        ),
        clone_total=max(
            clone_total
            if clone_total is not None
            else len(function_groups) + len(block_groups),
            0,
        ),
        complexity_max=_as_int(complexity_summary.get("max"), 0),
        coupling_max=_as_int(coupling_summary.get("max"), 0),
        cohesion_max=_as_int(cohesion_summary.get("max"), 0),
        dependency_cycles=_as_int(dependencies_summary.get("cycles"), 0),
        dead_high_confidence=_as_int(dead_code_summary.get("high_confidence"), 0),
        health_score=_as_int(health_summary.get("score"), 0),
        typing_param_permille=_as_int(
            coverage_adoption_summary.get("param_permille"), 0
        ),
        docstring_permille=_as_int(
            coverage_adoption_summary.get("docstring_permille"),
            0,
        ),
        coverage_join_status=str(coverage_join_summary.get("status", "")),
        coverage_hotspots=_as_int(
            coverage_join_summary.get("coverage_hotspots"),
            0,
        ),
        api_breaking_changes=(
            _as_int(diff_summary.get("api_breaking_changes"), 0)
            if prefer_diff_summary
            else _as_int(api_surface_summary.get("breaking"), 0)
        ),
        diff_new_high_risk_functions=_as_int(
            diff_summary.get("new_high_risk_functions"),
            0,
        ),
        diff_new_high_coupling_classes=_as_int(
            diff_summary.get("new_high_coupling_classes"),
            0,
        ),
        diff_new_cycles=_as_int(diff_summary.get("new_cycles"), 0),
        diff_new_dead_code=_as_int(diff_summary.get("new_dead_code"), 0),
        diff_health_delta=_as_int(diff_summary.get("health_delta"), 0),
        diff_typing_param_permille_delta=(
            _as_int(diff_summary.get("typing_param_permille_delta"), 0)
            if prefer_diff_summary
            else _as_int(coverage_adoption_summary.get("param_delta"), 0)
        ),
        diff_typing_return_permille_delta=(
            _as_int(diff_summary.get("typing_return_permille_delta"), 0)
            if prefer_diff_summary
            else _as_int(coverage_adoption_summary.get("return_delta"), 0)
        ),
        diff_docstring_permille_delta=(
            _as_int(diff_summary.get("docstring_permille_delta"), 0)
            if prefer_diff_summary
            else _as_int(coverage_adoption_summary.get("docstring_delta"), 0)
        ),
    )


def _permille(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        return 0
    return round(numerator * 1000 / denominator)


__all__ = [
    "GateResult",
    "GateState",
    "MetricGateConfig",
    "evaluate_gate_state",
    "evaluate_gates",
    "gate_state_from_project_metrics",
    "metric_gate_reasons",
    "metric_gate_reasons_for_state",
    "summarize_metrics_diff",
]
