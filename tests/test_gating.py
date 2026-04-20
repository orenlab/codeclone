from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from codeclone.analysis.normalizer import NormalizationConfig
from codeclone.core._types import AnalysisResult, BootstrapResult, OutputPaths
from codeclone.core.reporting import gate as cli_gate
from codeclone.models import (
    DeadItem,
    HealthScore,
    MetricsDiff,
    ModuleDep,
    ProjectMetrics,
)
from codeclone.report.gates import MetricGateConfig, evaluate_gates
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.surfaces.mcp.session import (
    MCPAnalysisRequest,
    MCPGateRequest,
    MCPRunRecord,
)


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


def _report_document() -> dict[str, object]:
    return {
        "meta": {"baseline": {"status": "ok"}},
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
    )

    cli_result = cli_gate(
        boot=boot,
        analysis=analysis,
        new_func={"clone:function:new"},
        new_block=set(),
        metrics_diff=metrics_diff,
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
        baseline_status="ok",
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
