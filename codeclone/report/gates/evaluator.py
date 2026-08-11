# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from ...contracts import (
    DEFAULT_COVERAGE_MIN,
    GATE_LANE_MATRIX_VERSION,
    HEALTH_INPUT_MANIFEST_VERSION,
    ExitCode,
)
from ...metrics.registry import METRIC_FAMILIES
from ...models import ObservationLaneName, cycle_kind_counts
from ...observability import span
from ...utils.coerce import as_int as _as_int
from ...utils.coerce import as_mapping as _as_mapping
from ...utils.coerce import as_sequence as _as_sequence
from ..messages import gates as gate_msgs

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
    fail_on_authority_violation: bool = False
    fail_on_untested_hotspots: bool = False
    min_typing_coverage: int = -1
    min_docstring_coverage: int = -1
    coverage_min: int = DEFAULT_COVERAGE_MIN
    fail_on_new: bool = False
    fail_threshold: int = -1
    # Defaulted so the three constructors outside the CLI reporting path stay
    # untouched; abstentions are opt-in and never gate by default.
    fail_on_unresolved_dead_code: bool = False


@dataclass(frozen=True, slots=True)
class GateResult:
    exit_code: int
    reasons: tuple[str, ...]
    required_lanes: tuple[ObservationLaneName, ...] = ()
    unavailable_lanes: tuple[ObservationLaneName, ...] = ()


@dataclass(frozen=True, slots=True)
class GateState:
    clone_new_count: int = 0
    clone_total: int = 0
    complexity_max: int = 0
    coupling_max: int = 0
    cohesion_max: int = 0
    #: Every runtime cycle, both kinds. Reported, never gated on: a deferred
    #: cycle is real but cannot crash an import, so failing a build for one
    #: would apply an import-time verdict to a fact that is not import-time.
    dependency_cycles: int = 0
    #: The gating subset — cycles whose import-time edges still cycle. This is
    #: what --fail-cycles reads.
    import_dependency_cycles: int = 0
    dead_high_confidence: int = 0
    unresolved_external_override: int = 0
    health_score: int = 0
    typing_param_permille: int = 0
    docstring_permille: int = 0
    coverage_join_status: str = ""
    coverage_hotspots: int = 0
    api_breaking_changes: int = 0
    authority_violations: int = 0
    diff_new_high_risk_functions: int = 0
    diff_new_high_coupling_classes: int = 0
    #: New cycles of either kind — the visibility count.
    diff_new_cycles: int = 0
    #: Cycles that are import-time now and were not before, including a
    #: deferred cycle that hardened into one. The only cycle novelty that gates.
    diff_new_import_cycles: int = 0
    diff_new_dead_code: int = 0
    diff_health_delta: int = 0
    diff_typing_param_permille_delta: int = 0
    diff_typing_return_permille_delta: int = 0
    diff_docstring_permille_delta: int = 0


HEALTH_INPUT_LANES: tuple[ObservationLaneName, ...] = (
    "clones.blocks",
    "clones.functions",
    "coupling_cohesion_observations",
    "dead_code",
    "dependencies",
    "module_identity",
    "risk_observations",
)

_COMPARISON_GATE_NAMES = frozenset(
    {
        "adoption_regression",
        "api_compatibility",
        "clone_novelty",
        "complexity_delta",
        "coupling_cohesion_delta",
        "dead_code_delta",
        "dependency_delta",
        "health_delta",
    }
)


def active_gate_lane_requirements(
    *,
    config: MetricGateConfig,
    enabled_lanes: Collection[str],
) -> tuple[tuple[str, tuple[ObservationLaneName, ...]], ...]:
    """Return the sole versioned mapping from active gates to evidence lanes."""

    enabled = frozenset(enabled_lanes)
    rows: dict[str, tuple[ObservationLaneName, ...]] = {}
    if config.fail_on_new:
        rows["clone_novelty"] = ("clones.blocks", "clones.functions")
    if config.fail_complexity >= 0:
        rows["complexity_current"] = ("risk_observations",)
    if config.fail_coupling >= 0 or config.fail_cohesion >= 0:
        rows["coupling_cohesion_current"] = ("coupling_cohesion_observations",)
    if config.fail_on_new_metrics:
        rows["complexity_delta"] = ("risk_observations",)
        rows["coupling_cohesion_delta"] = ("coupling_cohesion_observations",)
        rows["dependency_delta"] = ("dependencies",)
        rows["dead_code_delta"] = ("dead_code",)
        rows["health_delta"] = HEALTH_INPUT_LANES
    if config.fail_cycles:
        rows["dependency_cycles_current"] = ("dependencies",)
    # Both dead-code predicates read the same evidence lane, so they share the
    # existing family rather than adding one: a new family key would change the
    # versioned gate-to-lane matrix, which this flag is not chartered to move.
    if config.fail_dead_code or config.fail_on_unresolved_dead_code:
        rows["dead_code_current"] = ("dead_code",)
    if config.fail_health >= 0:
        rows["health_current"] = HEALTH_INPUT_LANES
    if "adoption_counts" in enabled and (
        config.fail_on_typing_regression or config.fail_on_docstring_regression
    ):
        rows["adoption_regression"] = ("adoption_counts",)
    if "adoption_counts" in enabled and (
        config.min_typing_coverage >= 0 or config.min_docstring_coverage >= 0
    ):
        rows["adoption_threshold"] = ("adoption_counts",)
    if "api_surface" in enabled and config.fail_on_api_break:
        rows["api_compatibility"] = ("api_surface",)
    if "adoption_counts" in enabled and config.fail_on_untested_hotspots:
        rows["coverage_hotspots"] = ("adoption_counts",)
    if config.fail_on_authority_violation:
        rows["authority_current"] = ("semantic_authority",)
    return tuple(sorted(rows.items()))


def gate_lane_contract_versions() -> tuple[str, str]:
    return GATE_LANE_MATRIX_VERSION, HEALTH_INPUT_MANIFEST_VERSION


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
            # A payload written before the kind split carries no import count.
            # Falling back to the undifferentiated total keeps such a payload
            # gating exactly as it used to; defaulting to zero would silently
            # open the gate for every legacy caller.
            "new_import_cycles": _as_int(
                payload.get("new_import_cycles"),
                _as_int(payload.get("new_cycles"), 0),
            ),
            "new_deferred_cycles": _as_int(payload.get("new_deferred_cycles"), 0),
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
    new_import_cycles = tuple(
        tuple(str(part) for part in _as_sequence(item) if str(part).strip())
        for item in _as_sequence(getattr(metrics_diff, "new_import_cycles", ()))
    )
    new_deferred_cycles = tuple(
        tuple(str(part) for part in _as_sequence(item) if str(part).strip())
        for item in _as_sequence(getattr(metrics_diff, "new_deferred_cycles", ()))
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
        "new_import_cycles": len(new_import_cycles),
        "new_deferred_cycles": len(new_deferred_cycles),
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
        import_dependency_cycles=cycle_kind_counts(
            cycles=tuple(project_metrics.dependency_cycles),
            details=project_metrics.dependency_cycle_details,
        ).import_cycles,
        dead_high_confidence=sum(
            1
            for item in project_metrics.dead_code
            if str(getattr(item, "confidence", "")).strip().lower() == "high"
        ),
        # The CLI gate path reads project metrics, not the report document, so
        # without this the opt-in --fail-on-unresolved-dead-code flag could
        # never fire outside the MCP surface.
        unresolved_external_override=len(tuple(project_metrics.unresolved_overrides)),
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
        authority_violations=(
            len(project_metrics.semantic_authority.violations)
            if project_metrics.semantic_authority is not None
            else 0
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
        diff_new_import_cycles=_as_int(diff_summary.get("new_import_cycles"), 0),
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
    "unresolved_external_override": 65,
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
        gate_msgs.GATE_REASON_COMPLEXITY_THRESHOLD
        + f"max CC={state.complexity_max}, "
        + f"threshold={config.fail_complexity}.",
    )


def _coupling_threshold_reason(
    *,
    state: GateState,
    config: MetricGateConfig,
) -> tuple[str, ...]:
    return _reason_if(
        0 <= config.fail_coupling < state.coupling_max,
        gate_msgs.GATE_REASON_COUPLING_THRESHOLD
        + f"max CBO={state.coupling_max}, "
        + f"threshold={config.fail_coupling}.",
    )


def _cohesion_threshold_reason(
    *,
    state: GateState,
    config: MetricGateConfig,
) -> tuple[str, ...]:
    return _reason_if(
        0 <= config.fail_cohesion < state.cohesion_max,
        gate_msgs.GATE_REASON_COHESION_THRESHOLD
        + f"max LCOM4={state.cohesion_max}, "
        + f"threshold={config.fail_cohesion}.",
    )


def _health_threshold_reason(
    *,
    state: GateState,
    config: MetricGateConfig,
) -> tuple[str, ...]:
    return _reason_if(
        config.fail_health >= 0 and state.health_score < config.fail_health,
        gate_msgs.GATE_REASON_HEALTH_THRESHOLD
        + f"score={state.health_score}, threshold={config.fail_health}.",
    )


def _dependency_cycles_reason(
    *,
    state: GateState,
    config: MetricGateConfig,
) -> tuple[str, ...]:
    return _reason_if(
        config.fail_cycles and state.import_dependency_cycles > 0,
        f"{gate_msgs.GATE_REASON_CYCLES_DETECTED}{state.import_dependency_cycles}{gate_msgs.GATE_SUFFIX_CYCLES}.",
    )


def _dead_code_high_confidence_reason(
    *,
    state: GateState,
    config: MetricGateConfig,
) -> tuple[str, ...]:
    return _reason_if(
        config.fail_dead_code and state.dead_high_confidence > 0,
        f"{gate_msgs.GATE_REASON_DEAD_CODE_DETECTED}{state.dead_high_confidence}{gate_msgs.GATE_SUFFIX_ITEMS}.",
    )


def _unresolved_external_override_reason(
    *,
    state: GateState,
    config: MetricGateConfig,
) -> tuple[str, ...]:
    return _reason_if(
        config.fail_on_unresolved_dead_code and state.unresolved_external_override > 0,
        f"{gate_msgs.GATE_REASON_UNRESOLVED_DEAD_CODE}"
        f"{state.unresolved_external_override}{gate_msgs.GATE_SUFFIX_ITEMS}.",
    )


def _new_high_risk_functions_reason(
    *,
    state: GateState,
    config: MetricGateConfig,
) -> tuple[str, ...]:
    return _reason_if(
        config.fail_on_new_metrics and state.diff_new_high_risk_functions > 0,
        f"{gate_msgs.GATE_REASON_NEW_HIGH_RISK_FUNCTIONS}{state.diff_new_high_risk_functions}.",
    )


def _new_high_coupling_classes_reason(
    *,
    state: GateState,
    config: MetricGateConfig,
) -> tuple[str, ...]:
    return _reason_if(
        config.fail_on_new_metrics and state.diff_new_high_coupling_classes > 0,
        f"{gate_msgs.GATE_REASON_NEW_HIGH_COUPLING}{state.diff_new_high_coupling_classes}.",
    )


def _new_dependency_cycles_reason(
    *,
    state: GateState,
    config: MetricGateConfig,
) -> tuple[str, ...]:
    return _reason_if(
        config.fail_on_new_metrics and state.diff_new_import_cycles > 0,
        f"{gate_msgs.GATE_REASON_NEW_CYCLES}{state.diff_new_import_cycles}.",
    )


def _new_dead_code_reason(
    *,
    state: GateState,
    config: MetricGateConfig,
) -> tuple[str, ...]:
    return _reason_if(
        config.fail_on_new_metrics and state.diff_new_dead_code > 0,
        f"{gate_msgs.GATE_REASON_NEW_DEAD_CODE}{state.diff_new_dead_code}.",
    )


def _health_regression_reason(
    *,
    state: GateState,
    config: MetricGateConfig,
) -> tuple[str, ...]:
    return _reason_if(
        config.fail_on_new_metrics and state.diff_health_delta < 0,
        f"{gate_msgs.GATE_REASON_HEALTH_REGRESSION}{state.diff_health_delta}.",
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
        gate_msgs.GATE_REASON_TYPING_THRESHOLD
        + f"coverage={typing_percent:.1f}%, threshold={config.min_typing_coverage}%.",
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
        gate_msgs.GATE_REASON_DOCSTRING_THRESHOLD
        + f"coverage={docstring_percent:.1f}%, "
        + f"threshold={config.min_docstring_coverage}%.",
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
        gate_msgs.GATE_REASON_TYPING_REGRESSION
        + f"params_delta={state.diff_typing_param_permille_delta}, "
        + f"returns_delta={state.diff_typing_return_permille_delta}.",
    )


def _docstring_regression_reason(
    *,
    state: GateState,
    config: MetricGateConfig,
) -> tuple[str, ...]:
    return _reason_if(
        config.fail_on_docstring_regression and state.diff_docstring_permille_delta < 0,
        f"{gate_msgs.GATE_REASON_DOCSTRING_REGRESSION}{state.diff_docstring_permille_delta}.",
    )


def _api_breaking_changes_reason(
    *,
    state: GateState,
    config: MetricGateConfig,
) -> tuple[str, ...]:
    return _reason_if(
        config.fail_on_api_break and state.api_breaking_changes > 0,
        f"{gate_msgs.GATE_REASON_API_BREAKING}{state.api_breaking_changes}.",
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
        gate_msgs.GATE_REASON_COVERAGE_HOTSPOTS
        + f"hotspots={state.coverage_hotspots}, "
        + f"threshold={config.coverage_min}%.",
    )


_GATE_REASON_BUILDERS: dict[str, Callable[..., tuple[str, ...]]] = {
    "complexity_threshold": _complexity_threshold_reason,
    "coupling_threshold": _coupling_threshold_reason,
    "cohesion_threshold": _cohesion_threshold_reason,
    "health_threshold": _health_threshold_reason,
    "dependency_cycles": _dependency_cycles_reason,
    "dead_code_high_confidence": _dead_code_high_confidence_reason,
    "unresolved_external_override": _unresolved_external_override_reason,
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


def _evaluate_gate_state_result(
    *,
    state: GateState,
    config: MetricGateConfig,
    lane_trust: Mapping[str, str] | None = None,
    enabled_lanes: Collection[str] = (),
) -> GateResult:
    requirements = active_gate_lane_requirements(
        config=config,
        enabled_lanes=enabled_lanes,
    )
    required_lanes = tuple(
        sorted({lane for _gate, lanes in requirements for lane in lanes})
    )
    enabled = frozenset(enabled_lanes)
    trust = lane_trust or {}
    unavailable_lanes = tuple(
        sorted(
            {
                lane
                for gate_name, lanes in requirements
                for lane in lanes
                if lane not in enabled
                or (
                    gate_name in _COMPARISON_GATE_NAMES and trust.get(lane) != "trusted"
                )
            }
        )
    )
    if unavailable_lanes:
        return GateResult(
            exit_code=int(ExitCode.CONTRACT_ERROR),
            reasons=tuple(f"lane:unavailable:{lane}" for lane in unavailable_lanes),
            required_lanes=required_lanes,
            unavailable_lanes=unavailable_lanes,
        )

    effective_config = replace(
        config,
        fail_on_typing_regression=(
            config.fail_on_typing_regression and "adoption_counts" in enabled
        ),
        fail_on_docstring_regression=(
            config.fail_on_docstring_regression and "adoption_counts" in enabled
        ),
        fail_on_api_break=config.fail_on_api_break and "api_surface" in enabled,
        fail_on_untested_hotspots=(
            config.fail_on_untested_hotspots and "adoption_counts" in enabled
        ),
        min_typing_coverage=(
            config.min_typing_coverage if "adoption_counts" in enabled else -1
        ),
        min_docstring_coverage=(
            config.min_docstring_coverage if "adoption_counts" in enabled else -1
        ),
    )
    reasons = [
        f"metric:{reason}"
        for reason in metric_gate_reasons_for_state(
            state=state,
            config=effective_config,
        )
    ]
    if config.fail_on_authority_violation and state.authority_violations > 0:
        reasons.append(
            "metric:"
            + gate_msgs.GATE_REASON_AUTHORITY_VIOLATIONS
            + f"{state.authority_violations}."
        )

    if config.fail_on_new and state.clone_new_count > 0:
        reasons.append("clone:new")

    if 0 <= config.fail_threshold < state.clone_total:
        reasons.append(f"clone:threshold:{state.clone_total}:{config.fail_threshold}")

    if reasons:
        return GateResult(
            exit_code=int(ExitCode.GATING_FAILURE),
            reasons=tuple(reasons),
            required_lanes=required_lanes,
        )
    return GateResult(
        exit_code=int(ExitCode.SUCCESS),
        reasons=(),
        required_lanes=required_lanes,
    )


def evaluate_gate_state(
    *,
    state: GateState,
    config: MetricGateConfig,
    lane_trust: Mapping[str, str] | None = None,
    enabled_lanes: Collection[str] = (),
) -> GateResult:
    """Evaluate one typed gate request under the sole report observer owner."""

    with span(name="report.evaluate") as evaluation_span:
        result = _evaluate_gate_state_result(
            state=state,
            config=config,
            lane_trust=lane_trust,
            enabled_lanes=enabled_lanes,
        )
        passed = result.exit_code == int(ExitCode.SUCCESS)
        evaluation_span.set_counter("report_gate_pass", int(passed))
        evaluation_span.set_counter("report_gate_fail", int(not passed))
        return result


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
    metrics_diff: object | None = None,
    clone_new_count: int | None = None,
    clone_total: int | None = None,
) -> GateResult:
    state = _gate_state_from_report_document(
        report_document=report_document,
        metrics_diff=metrics_diff,
        clone_new_count=clone_new_count,
        clone_total=clone_total,
    )
    baseline = _as_mapping(report_document.get("baseline"))
    lane_trust_rows = _as_sequence(baseline.get("sorted_lane_trust"))
    lane_trust = {
        str(row.get("name", "")): str(row.get("status", ""))
        for item in lane_trust_rows
        for row in (_as_mapping(item),)
        if str(row.get("name", "")).strip()
    }
    source_facts = _as_mapping(report_document.get("source_facts"))
    observation_contract = _as_mapping(source_facts.get("observation_contract"))
    return evaluate_gate_state(
        state=state,
        config=config,
        lane_trust=lane_trust,
        enabled_lanes=tuple(
            str(item)
            for item in _as_sequence(observation_contract.get("enabled_lanes"))
        ),
    )


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
    semantic_authority_summary = _as_mapping(
        _as_mapping(families.get("semantic_authority")).get("summary")
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
        # A document written before the split has no import count. Reading the
        # total keeps its gate verdict identical rather than quietly passing a
        # build that used to fail.
        import_dependency_cycles=_as_int(
            dependencies_summary.get("import_cycles"),
            _as_int(dependencies_summary.get("cycles"), 0),
        ),
        dead_high_confidence=_as_int(dead_code_summary.get("high_confidence"), 0),
        unresolved_external_override=_as_int(
            dead_code_summary.get("unresolved_external_override"), 0
        ),
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
        authority_violations=_as_int(
            semantic_authority_summary.get("violations"),
            0,
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
        diff_new_import_cycles=_as_int(diff_summary.get("new_import_cycles"), 0),
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
    "HEALTH_INPUT_LANES",
    "GateResult",
    "GateState",
    "MetricGateConfig",
    "active_gate_lane_requirements",
    "evaluate_gate_state",
    "evaluate_gates",
    "gate_lane_contract_versions",
    "gate_state_from_project_metrics",
    "metric_gate_reasons",
    "metric_gate_reasons_for_state",
    "summarize_metrics_diff",
]
