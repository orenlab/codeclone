# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

from argparse import Namespace
from dataclasses import replace
from pathlib import Path

from codeclone.analysis.normalizer import NormalizationConfig
from codeclone.core._types import AnalysisResult, BootstrapResult, OutputPaths
from codeclone.core.reporting import gate as cli_gate
from codeclone.models import (
    DeadItem,
    HealthScore,
    LaneTrust,
    MetricsDiff,
    ModuleDep,
    ProjectMetrics,
    TrustVector,
    UnresolvedOverrideItem,
)
from codeclone.report.gates.evaluator import (
    GateResult,
    GateState,
    MetricGateConfig,
    active_gate_lane_requirements,
    evaluate_gate_state,
    evaluate_gates,
    gate_lane_contract_versions,
)
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.surfaces.mcp.session import (
    MCPAnalysisRequest,
    MCPGateRequest,
    MCPRunRecord,
)
from tests.test_observation_contract import TEST_OBSERVATION_BUNDLE


def _project_metrics() -> ProjectMetrics:
    return ProjectMetrics(
        complexity_avg=10.0,
        complexity_max=30,
        high_risk_functions=("pkg.mod:hot",),
        coupling_avg=5.0,
        coupling_max=12,
        high_risk_classes=("pkg.mod:Service",),
        cohesion_avg=2.5,
        cohesion_max=4,
        low_cohesion_classes=("pkg.mod:Service",),
        dependency_modules=2,
        dependency_edges=1,
        dependency_edge_list=(
            ModuleDep(source="pkg.mod", target="pkg.dep", import_type="import", line=1),
        ),
        dependency_cycles=(),
        dependency_max_depth=1,
        dependency_longest_chains=(),
        dead_code=(
            DeadItem(
                qualname="pkg.mod:unused",
                filepath="pkg/mod.py",
                start_line=1,
                end_line=2,
                kind="function",
                confidence="high",
            ),
        ),
        health=HealthScore(total=90, grade="A", dimensions={"health": 90}),
    )


def _abstaining_project_metrics() -> ProjectMetrics:
    """Project metrics whose only dead-code signal is a rule-3 abstention."""
    return replace(
        _project_metrics(),
        dead_code=(),
        unresolved_overrides=(
            UnresolvedOverrideItem(
                qualname="pkg.mod:Handler.handle",
                filepath="pkg/mod.py",
                start_line=10,
                end_line=12,
                kind="method",
                class_qualname="pkg.mod:Handler",
                base_names=("external_lib.Base",),
            ),
        ),
    )


def _gating_args(**overrides: object) -> Namespace:
    defaults: dict[str, object] = {
        "fail_complexity": -1,
        "fail_coupling": -1,
        "fail_cohesion": -1,
        "fail_cycles": False,
        "fail_dead_code": False,
        "fail_on_unresolved_dead_code": False,
        "fail_health": -1,
        "fail_on_new_metrics": False,
        "fail_on_typing_regression": False,
        "fail_on_docstring_regression": False,
        "fail_on_api_break": False,
        "fail_on_authority_violation": False,
        "fail_on_untested_hotspots": False,
        "min_typing_coverage": -1,
        "min_docstring_coverage": -1,
        "coverage_min": 50,
        "fail_on_new": False,
        "fail_threshold": -1,
    }
    defaults.update(overrides)
    return Namespace(**defaults)


def _assert_gate(
    result: GateResult,
    *,
    exit_code: int,
    reasons: tuple[str, ...],
) -> None:
    """Assert exit code and reasons together so neither can drift alone."""
    assert (result.exit_code, result.reasons) == (exit_code, reasons)


def _cli_gate_result(
    *,
    tmp_path: Path,
    project_metrics: ProjectMetrics,
    args: Namespace,
) -> GateResult:
    boot = BootstrapResult(
        root=tmp_path,
        config=NormalizationConfig(),
        args=args,
        output_paths=OutputPaths(),
        cache_path=tmp_path / "cache.json",
    )
    analysis = AnalysisResult(
        func_groups={},
        block_groups={},
        block_groups_report={},
        segment_groups={},
        suppressed_segment_groups=0,
        block_group_facts={},
        func_clones_count=0,
        block_clones_count=0,
        segment_clones_count=0,
        files_analyzed_or_cached=1,
        project_metrics=project_metrics,
        metrics_payload=None,
        suggestions=(),
        segment_groups_raw_digest="",
        observation_bundle=TEST_OBSERVATION_BUNDLE,
    )
    return cli_gate(
        boot=boot,
        analysis=analysis,
        new_func=set(),
        new_block=set(),
        metrics_diff=None,
        baseline_trust=TrustVector(
            root_verified=True,
            lanes=tuple(
                LaneTrust(name=lane, status="trusted", reason="compatible")
                for lane in TEST_OBSERVATION_BUNDLE.contract.enabled_lanes
            ),
        ),
    )


def test_cli_path_gates_on_unresolved_overrides_in_both_directions(
    tmp_path: Path,
) -> None:
    """39Y cycle 2b: the opt-in flag must work end-to-end through the CLI.

    The evaluator-seam pins above proved the predicate; this proves the CLI
    gate path actually carries the abstention count into GateState. Before
    this cycle ``gate_state_from_project_metrics`` never populated
    ``unresolved_external_override``, so the flag was inert in the real CLI
    no matter what the operator asked for.
    """
    project_metrics = _abstaining_project_metrics()

    off = _cli_gate_result(
        tmp_path=tmp_path,
        project_metrics=project_metrics,
        args=_gating_args(fail_dead_code=True),
    )
    on = _cli_gate_result(
        tmp_path=tmp_path,
        project_metrics=project_metrics,
        args=_gating_args(fail_on_unresolved_dead_code=True),
    )

    _assert_gate(off, exit_code=0, reasons=())
    _assert_gate(
        on,
        exit_code=3,
        reasons=(
            "metric:Unresolved dead-code overrides "
            "(--fail-on-unresolved-dead-code): 1 item(s).",
        ),
    )


def test_gate_lane_matrix_is_explicit_and_required_unavailable_exits_two() -> None:
    config = MetricGateConfig(
        fail_complexity=-1,
        fail_coupling=-1,
        fail_cohesion=-1,
        fail_cycles=False,
        fail_dead_code=False,
        fail_health=-1,
        fail_on_new_metrics=False,
        fail_on_new=True,
    )

    assert active_gate_lane_requirements(
        config=config,
        enabled_lanes=("clones.blocks", "clones.functions"),
    ) == (("clone_novelty", ("clones.blocks", "clones.functions")),)
    result = evaluate_gate_state(
        state=GateState(clone_new_count=0),
        config=config,
        lane_trust={"clones.blocks": "trusted"},
        enabled_lanes=("clones.blocks", "clones.functions"),
    )

    assert result.exit_code == 2
    assert result.required_lanes == ("clones.blocks", "clones.functions")
    assert result.unavailable_lanes == ("clones.functions",)


def test_disabled_optional_api_and_coverage_gates_are_informational() -> None:
    config = MetricGateConfig(
        fail_complexity=-1,
        fail_coupling=-1,
        fail_cohesion=-1,
        fail_cycles=False,
        fail_dead_code=False,
        fail_health=-1,
        fail_on_new_metrics=False,
        fail_on_api_break=True,
        fail_on_untested_hotspots=True,
    )

    result = evaluate_gate_state(
        state=GateState(
            api_breaking_changes=2,
            coverage_join_status="ok",
            coverage_hotspots=3,
        ),
        config=config,
        lane_trust={},
        enabled_lanes=("clones.blocks", "clones.functions"),
    )

    assert result.exit_code == 0
    assert result.reasons == ()
    assert result.required_lanes == ()


def test_current_state_gate_requires_enabled_lane_not_baseline_trust() -> None:
    config = MetricGateConfig(
        fail_complexity=-1,
        fail_coupling=-1,
        fail_cohesion=-1,
        fail_cycles=False,
        fail_dead_code=True,
        fail_health=-1,
        fail_on_new_metrics=False,
    )

    result = evaluate_gate_state(
        state=GateState(dead_high_confidence=0),
        config=config,
        lane_trust={"dead_code": "unavailable"},
        enabled_lanes=("dead_code",),
    )

    assert active_gate_lane_requirements(
        config=config,
        enabled_lanes=("dead_code",),
    ) == (("dead_code_current", ("dead_code",)),)
    assert result.exit_code == 0
    assert result.required_lanes == ("dead_code",)
    assert result.unavailable_lanes == ()


def test_authority_gate_distinguishes_unavailable_lane_from_violations() -> None:
    config = MetricGateConfig(
        fail_complexity=-1,
        fail_coupling=-1,
        fail_cohesion=-1,
        fail_cycles=False,
        fail_dead_code=False,
        fail_health=-1,
        fail_on_new_metrics=False,
        fail_on_authority_violation=True,
    )

    unavailable = evaluate_gate_state(
        state=GateState(authority_violations=1),
        config=config,
        enabled_lanes=(),
    )
    violated = evaluate_gate_state(
        state=GateState(authority_violations=1),
        config=config,
        lane_trust={"semantic_authority": "unavailable"},
        enabled_lanes=("semantic_authority",),
    )

    assert unavailable.exit_code == 2
    assert unavailable.unavailable_lanes == ("semantic_authority",)
    assert violated.exit_code == 3
    assert violated.unavailable_lanes == ()
    assert violated.reasons == ("metric:Semantic authority violations detected: 1.",)


def test_gate_lane_matrix_covers_every_active_gate_family() -> None:
    enabled_lanes = TEST_OBSERVATION_BUNDLE.contract.enabled_lanes
    config = MetricGateConfig(
        fail_complexity=10,
        fail_coupling=8,
        fail_cohesion=4,
        fail_cycles=True,
        fail_dead_code=True,
        fail_health=70,
        fail_on_new_metrics=True,
        fail_on_typing_regression=True,
        fail_on_docstring_regression=True,
        fail_on_api_break=True,
        fail_on_authority_violation=True,
        fail_on_untested_hotspots=True,
        min_typing_coverage=900,
        min_docstring_coverage=800,
        fail_on_new=True,
    )

    requirements = active_gate_lane_requirements(
        config=config,
        enabled_lanes=enabled_lanes,
    )

    assert {name for name, _lanes in requirements} == {
        "adoption_regression",
        "adoption_threshold",
        "api_compatibility",
        "authority_current",
        "clone_novelty",
        "complexity_current",
        "complexity_delta",
        "coupling_cohesion_current",
        "coupling_cohesion_delta",
        "coverage_hotspots",
        "dead_code_current",
        "dead_code_delta",
        "dependency_cycles_current",
        "dependency_delta",
        "health_current",
        "health_delta",
    }
    assert gate_lane_contract_versions() == ("2", "2")


def _dead_code_gate_config(
    *,
    fail_dead_code: bool,
    fail_on_unresolved_dead_code: bool,
) -> MetricGateConfig:
    """Arm the two dead-code predicates and nothing else."""
    return MetricGateConfig(
        fail_complexity=-1,
        fail_coupling=-1,
        fail_cohesion=-1,
        fail_cycles=False,
        fail_dead_code=fail_dead_code,
        fail_health=-1,
        fail_on_new_metrics=False,
        fail_on_unresolved_dead_code=fail_on_unresolved_dead_code,
    )


def test_unresolved_override_abstentions_never_gate_while_flag_is_off() -> None:
    """39Y brief section 6, OFF direction: abstention is not a gate input.

    The maintainer ruling makes ``unresolved_external_override`` neither dead
    nor live: excluded from default dead-code gates, never a gate regression.
    Opting out is the default, so abstentions must neither raise the exit code
    on their own nor inflate the count of the plain dead-code predicate.
    """
    config = _dead_code_gate_config(
        fail_dead_code=True,
        fail_on_unresolved_dead_code=False,
    )
    assert config.fail_on_unresolved_dead_code is False

    abstentions_only = evaluate_gate_state(
        state=GateState(dead_high_confidence=0, unresolved_external_override=3),
        config=config,
        enabled_lanes=("dead_code",),
    )
    alongside_dead_code = evaluate_gate_state(
        state=GateState(dead_high_confidence=1, unresolved_external_override=3),
        config=config,
        enabled_lanes=("dead_code",),
    )

    _assert_gate(abstentions_only, exit_code=0, reasons=())
    # Distinct counts prove the two predicates never share a counter: the
    # reported item count is the dead one alone, not dead + abstained.
    _assert_gate(
        alongside_dead_code,
        exit_code=3,
        reasons=("metric:Dead code detected (high confidence): 1 item(s).",),
    )


def test_unresolved_override_gate_fails_with_its_own_reason_and_count() -> None:
    """39Y brief section 6, ON direction: opt-in gates on the exact count.

    The reason names the flag inline because this failure and a plain
    dead-code failure need different remediation (produce evidence vs delete
    the symbol), so an operator must never have to guess which tripped.
    """
    config = _dead_code_gate_config(
        fail_dead_code=False,
        fail_on_unresolved_dead_code=True,
    )

    abstentions = evaluate_gate_state(
        state=GateState(dead_high_confidence=0, unresolved_external_override=3),
        config=config,
        enabled_lanes=("dead_code",),
    )
    none_abstained = evaluate_gate_state(
        state=GateState(dead_high_confidence=0, unresolved_external_override=0),
        config=config,
        enabled_lanes=("dead_code",),
    )
    both_predicates = evaluate_gate_state(
        state=GateState(dead_high_confidence=1, unresolved_external_override=3),
        config=_dead_code_gate_config(
            fail_dead_code=True,
            fail_on_unresolved_dead_code=True,
        ),
        enabled_lanes=("dead_code",),
    )

    assert abstentions.exit_code == 3
    assert abstentions.reasons == (
        "metric:Unresolved dead-code overrides "
        "(--fail-on-unresolved-dead-code): 3 item(s).",
    )
    # The opt-in predicate reads the abstention lane, so it must declare the
    # same evidence lane rather than gating on absent evidence.
    assert abstentions.required_lanes == ("dead_code",)
    assert abstentions.unavailable_lanes == ()
    # Arming the flag is not itself a failure: zero abstentions still passes.
    assert none_abstained.exit_code == 0
    assert none_abstained.reasons == ()
    # Both armed: two separately-worded reasons, each carrying its own count.
    assert both_predicates.reasons == (
        "metric:Dead code detected (high confidence): 1 item(s).",
        "metric:Unresolved dead-code overrides "
        "(--fail-on-unresolved-dead-code): 3 item(s).",
    )


def test_unresolved_override_flag_shares_the_dead_code_gate_family() -> None:
    """The opt-in predicate must not move the versioned gate-to-lane matrix.

    Both dead-code predicates read the same evidence lane, so the flag joins
    the existing ``dead_code_current`` family. A new family key would change
    the matrix this file pins above, which this flag is not chartered to move.
    """
    flag_only = active_gate_lane_requirements(
        config=_dead_code_gate_config(
            fail_dead_code=False,
            fail_on_unresolved_dead_code=True,
        ),
        enabled_lanes=("dead_code",),
    )
    both = active_gate_lane_requirements(
        config=_dead_code_gate_config(
            fail_dead_code=True,
            fail_on_unresolved_dead_code=True,
        ),
        enabled_lanes=("dead_code",),
    )

    assert flag_only == (("dead_code_current", ("dead_code",)),)
    assert both == flag_only
    assert gate_lane_contract_versions() == ("2", "2")


def _report_document() -> dict[str, object]:
    enabled_lanes = TEST_OBSERVATION_BUNDLE.contract.enabled_lanes
    return {
        "meta": {"baseline": {"status": "ok"}},
        "baseline": {
            "sorted_lane_trust": [
                {"name": lane, "status": "trusted", "reason": "compatible"}
                for lane in enabled_lanes
            ]
        },
        "source_facts": {
            "observation_contract": {"enabled_lanes": list(enabled_lanes)}
        },
        "findings": {
            "groups": {
                "clones": {
                    "functions": [{"id": "clone:function:new", "novelty": "new"}],
                    "blocks": [],
                    "segments": [],
                }
            }
        },
        "metrics": {
            "families": {
                "complexity": {"summary": {"max": 30}},
                "coupling": {"summary": {"max": 12}},
                "cohesion": {"summary": {"max": 4}},
                "dependencies": {"summary": {"cycles": 0}},
                "dead_code": {"summary": {"high_confidence": 1}},
                "health": {"summary": {"score": 90}},
                "coverage_adoption": {
                    "summary": {
                        "param_permille": 1000,
                        "docstring_permille": 1000,
                        "param_delta": 0,
                        "return_delta": 0,
                        "docstring_delta": 0,
                    }
                },
                "api_surface": {"summary": {"breaking": 0}},
                "coverage_join": {"summary": {"status": "", "coverage_hotspots": 0}},
            }
        },
    }


def test_cli_and_mcp_gate_results_match_for_same_inputs(tmp_path: Path) -> None:
    report_document = _report_document()
    project_metrics = _project_metrics()
    metrics_diff = MetricsDiff(
        new_high_risk_functions=(),
        new_high_coupling_classes=(),
        new_cycles=(),
        new_dead_code=("pkg.mod:unused",),
        health_delta=-1,
    )
    config = MetricGateConfig(
        fail_complexity=20,
        fail_coupling=-1,
        fail_cohesion=-1,
        fail_cycles=False,
        fail_dead_code=True,
        fail_health=-1,
        fail_on_new_metrics=True,
        fail_on_new=True,
        fail_threshold=0,
    )

    args = Namespace(
        fail_complexity=config.fail_complexity,
        fail_coupling=config.fail_coupling,
        fail_cohesion=config.fail_cohesion,
        fail_cycles=config.fail_cycles,
        fail_dead_code=config.fail_dead_code,
        fail_health=config.fail_health,
        fail_on_new_metrics=config.fail_on_new_metrics,
        fail_on_typing_regression=config.fail_on_typing_regression,
        fail_on_docstring_regression=config.fail_on_docstring_regression,
        fail_on_api_break=config.fail_on_api_break,
        fail_on_untested_hotspots=config.fail_on_untested_hotspots,
        min_typing_coverage=config.min_typing_coverage,
        min_docstring_coverage=config.min_docstring_coverage,
        coverage_min=config.coverage_min,
        fail_on_new=config.fail_on_new,
        fail_threshold=config.fail_threshold,
    )
    boot = BootstrapResult(
        root=tmp_path,
        config=NormalizationConfig(),
        args=args,
        output_paths=OutputPaths(),
        cache_path=tmp_path / "cache.json",
    )
    analysis = AnalysisResult(
        func_groups={},
        block_groups={},
        block_groups_report={},
        segment_groups={},
        suppressed_segment_groups=0,
        block_group_facts={},
        func_clones_count=1,
        block_clones_count=0,
        segment_clones_count=0,
        files_analyzed_or_cached=1,
        project_metrics=project_metrics,
        metrics_payload=None,
        suggestions=(),
        segment_groups_raw_digest="",
        observation_bundle=TEST_OBSERVATION_BUNDLE,
    )
    baseline_trust = TrustVector(
        root_verified=True,
        lanes=tuple(
            LaneTrust(name=lane, status="trusted", reason="compatible")
            for lane in TEST_OBSERVATION_BUNDLE.contract.enabled_lanes
        ),
    )

    cli_result = cli_gate(
        boot=boot,
        analysis=analysis,
        new_func={"clone:function:new"},
        new_block=set(),
        metrics_diff=metrics_diff,
        baseline_trust=baseline_trust,
    )

    service = CodeCloneMCPService(history_limit=2)
    request = MCPAnalysisRequest(root=str(tmp_path), respect_pyproject=False)
    record = MCPRunRecord(
        run_id="gate-parity",
        root=tmp_path,
        request=request,
        comparison_settings=(),
        report_document=report_document,
        summary={},
        changed_paths=(),
        changed_projection=None,
        warnings=(),
        failures=(),
        func_clones_count=1,
        block_clones_count=0,
        project_metrics=project_metrics,
        coverage_join=None,
        suggestions=(),
        new_func=frozenset({"clone:function:new"}),
        new_block=frozenset(),
        metrics_diff=metrics_diff,
    )
    mcp_result = service._evaluate_gate_snapshot(
        record=record,
        request=MCPGateRequest(
            fail_complexity=20,
            fail_dead_code=True,
            fail_on_new_metrics=True,
            fail_on_new=True,
            fail_threshold=0,
        ),
    )

    evaluator_result = evaluate_gates(
        report_document=report_document,
        config=config,
        metrics_diff=metrics_diff,
        clone_new_count=1,
        clone_total=1,
    )

    expected_reasons = (
        "metric:Complexity threshold exceeded: max CC=30, threshold=20.",
        "metric:Dead code detected (high confidence): 1 item(s).",
        "metric:New dead code items vs metrics baseline: 1.",
        "metric:Health score regressed vs metrics baseline: delta=-1.",
        "clone:new",
        "clone:threshold:1:0",
    )

    assert cli_result == mcp_result == evaluator_result
    assert cli_result.reasons == expected_reasons
