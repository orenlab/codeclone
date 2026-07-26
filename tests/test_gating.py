# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

from argparse import Namespace
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
)
from codeclone.report.gates.evaluator import (
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
    assert gate_lane_contract_versions() == ("1", "1")


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
