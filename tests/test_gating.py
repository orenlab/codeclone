# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

from argparse import Namespace
from dataclasses import replace
from pathlib import Path
from typing import Literal, cast

import pytest

from codeclone.analysis.normalizer import NormalizationConfig
from codeclone.contracts import HealthPopulation
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
    UnreachableStatementFinding,
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
    gate_state_from_project_metrics,
)
from codeclone.report.messages import gates as gate_msgs
from codeclone.surfaces.cli.summary import build_metrics_snapshot
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.surfaces.mcp.session import (
    MCPAnalysisRequest,
    MCPGateRequest,
    MCPRunRecord,
)
from codeclone.ui_messages import fmt_metrics_dead_code
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


def _analysis_result(project_metrics: ProjectMetrics) -> AnalysisResult:
    """One analysis result, so the gate and the summary read the same run.

    Carries the dead-code counts in the shape the metrics payload publishes
    them, because that published summary is what both the CLI line and the
    gate now read. ``codeclone.core.metrics_payload`` owns producing it and is
    pinned where it is produced; here the contract shape is what matters.
    """

    published_dead_code = {
        "summary": {
            "total": len(project_metrics.dead_code),
            "high_confidence": sum(
                1
                for item in project_metrics.dead_code
                if str(item.confidence).strip().lower() == "high"
            ),
            "unreachable_statements": len(project_metrics.unreachable_statements),
            "unresolved_external_override": len(project_metrics.unresolved_overrides),
        }
    }
    return AnalysisResult(
        func_groups={},
        block_groups={},
        block_groups_report={},
        segment_groups={},
        low_value_segment_groups=0,
        block_group_facts={},
        func_clones_count=0,
        block_clones_count=0,
        segment_clones_count=0,
        files_analyzed_or_cached=1,
        project_metrics=project_metrics,
        metrics_payload={"dead_code": published_dead_code},
        suggestions=(),
        segment_groups_raw_digest="",
        observation_bundle=TEST_OBSERVATION_BUNDLE,
    )


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
    analysis = _analysis_result(project_metrics)
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


def test_unreachable_statements_trip_the_plain_dead_code_gate() -> None:
    """``--fail-dead-code`` must read every proven dead-code lane, not one.

    The statement-level lane is proven-dead, high-confidence, and rides the
    ``dead_code`` family in findings. It reached the gate's own evidence and
    was simply not consulted, so ten published findings exited 0.
    """
    config = _dead_code_gate_config(
        fail_dead_code=True,
        fail_on_unresolved_dead_code=False,
    )

    statements_only = evaluate_gate_state(
        state=GateState(dead_high_confidence=0, dead_unreachable_statements=3),
        config=config,
        enabled_lanes=("dead_code",),
    )
    both_lanes = evaluate_gate_state(
        state=GateState(dead_high_confidence=1, dead_unreachable_statements=2),
        config=config,
        enabled_lanes=("dead_code",),
    )
    neither = evaluate_gate_state(
        state=GateState(dead_high_confidence=0, dead_unreachable_statements=0),
        config=config,
        enabled_lanes=("dead_code",),
    )

    _assert_gate(
        statements_only,
        exit_code=3,
        reasons=("metric:Dead code detected (high confidence): 3 item(s).",),
    )
    # One predicate, one reason, one count: both proven lanes are the same
    # question ("is there dead code?"), unlike the abstention lane above.
    _assert_gate(
        both_lanes,
        exit_code=3,
        reasons=("metric:Dead code detected (high confidence): 3 item(s).",),
    )
    _assert_gate(neither, exit_code=0, reasons=())
    assert statements_only.required_lanes == ("dead_code",)


def test_unreachable_statements_never_gate_while_the_flag_is_off() -> None:
    """The mirror: consulting the lane must not make it gate by default."""
    disarmed = evaluate_gate_state(
        state=GateState(dead_high_confidence=0, dead_unreachable_statements=9),
        config=_dead_code_gate_config(
            fail_dead_code=False,
            fail_on_unresolved_dead_code=False,
        ),
        enabled_lanes=("dead_code",),
    )
    _assert_gate(disarmed, exit_code=0, reasons=())


def test_cli_gate_state_carries_the_unreachable_statement_lane() -> None:
    """The CLI builds its state from project metrics, not from the document.

    Two constructors feed one predicate. Fixing only the document one leaves
    ``codeclone . --fail-dead-code`` — the surface the operator actually runs —
    exactly as silent as before.
    """
    metrics = replace(
        _project_metrics(),
        dead_code=(),
        unreachable_statements=(
            UnreachableStatementFinding(
                qualname="pkg.mod:looping",
                filepath="pkg/mod.py",
                reason="after_terminator",
                start_line=10,
                end_line=11,
                statement_count=2,
            ),
        ),
    )

    state = gate_state_from_project_metrics(
        project_metrics=metrics,
        coverage_join=None,
        metrics_diff=None,
    )

    assert state.dead_high_confidence == 0
    assert state.dead_unreachable_statements == 1


def test_report_document_gate_reads_the_statement_lane_it_already_carries() -> None:
    """Regression barrier for a gate that consulted one lane out of two.

    The document carries both lanes and handed both to the findings builder,
    which published ten findings while the dead-code gate read only the
    counter built from ``items`` and exited 0. The gate now reads the same
    published ``unreachable_statements`` count that text, markdown and HTML
    read, so this fails the moment it goes back to one lane — or starts
    measuring the list beside the field for itself.
    """
    document = {
        "metrics": {
            "families": {
                "dead_code": {
                    "summary": {
                        "total": 0,
                        "high_confidence": 0,
                        "unreachable_statements": 4,
                    },
                    "items": [],
                    "unreachable_statements": [
                        {
                            "qualname": f"pkg.mod:looping{index}",
                            "relative_path": "pkg/mod.py",
                            "start_line": 10 + index,
                            "end_line": 11 + index,
                            "reason": "after_terminator",
                            "statement_count": 2,
                        }
                        for index in range(4)
                    ],
                }
            }
        },
        "source_facts": {"observation_contract": {"enabled_lanes": ["dead_code"]}},
    }

    result = evaluate_gates(
        report_document=document,
        config=_dead_code_gate_config(
            fail_dead_code=True,
            fail_on_unresolved_dead_code=False,
        ),
    )

    _assert_gate(
        result,
        exit_code=3,
        reasons=("metric:Dead code detected (high confidence): 4 item(s).",),
    )


def _dead_items(
    count: int,
    *,
    confidence: Literal["high", "medium"] = "high",
) -> tuple[DeadItem, ...]:
    return tuple(
        DeadItem(
            qualname=f"pkg.mod:unused{index}",
            filepath="pkg/mod.py",
            start_line=index + 1,
            end_line=index + 2,
            kind="function",
            confidence=confidence,
        )
        for index in range(count)
    )


def _unreachable(count: int) -> tuple[UnreachableStatementFinding, ...]:
    return tuple(
        UnreachableStatementFinding(
            qualname=f"pkg.mod:looping{index}",
            filepath="pkg/mod.py",
            reason="after_terminator",
            start_line=10 + index,
            end_line=11 + index,
            statement_count=2,
        )
        for index in range(count)
    )


def _gate_cited_dead_code_count(result: GateResult) -> int:
    """The number the operator reads in the gate reason, parsed back out."""

    prefix = "metric:Dead code detected (high confidence): "
    cited = [reason for reason in result.reasons if reason.startswith(prefix)]
    assert len(cited) == 1, f"expected exactly one dead-code reason, got {cited}"
    return int(cited[0].removeprefix(prefix).split(" ", 1)[0])


@pytest.mark.parametrize(
    ("classic", "unreachable", "expected"),
    [
        pytest.param(0, 3, 3, id="statement_lane_only"),
        pytest.param(2, 3, 5, id="both_lanes"),
        pytest.param(2, 0, 2, id="classic_lane_only"),
    ],
)
def test_cli_dead_code_summary_shows_the_number_the_gate_cites(
    tmp_path: Path,
    classic: int,
    unreachable: int,
    expected: int,
) -> None:
    """One run, one number: the summary line and the gate reason must agree.

    The gate learned to count the statement lane while the summary line still
    counted only unreferenced symbols, so a scan could print "Dead code
    ✔ clean" directly above "dead_code_items 10". Pinning each surface against
    its own literal would let them drift apart again; this pins them against
    each other, on one analysis result, in both directions -- a summary that
    forgets either lane stops matching the reason.

    Every classic item here is high confidence, which is the case the gate
    speaks about; the medium-confidence boundary is pinned separately below.
    """

    metrics = replace(
        _project_metrics(),
        dead_code=_dead_items(classic),
        unreachable_statements=_unreachable(unreachable),
    )
    snapshot = build_metrics_snapshot(
        analysis_result=_analysis_result(metrics),
        metrics_diff=None,
        api_surface_diff_available=False,
    )
    gate = _cli_gate_result(
        tmp_path=tmp_path,
        project_metrics=metrics,
        args=_gating_args(fail_dead_code=True),
    )

    assert snapshot.dead_code_count == expected
    assert gate.exit_code == 3
    assert _gate_cited_dead_code_count(gate) == snapshot.dead_code_count
    assert "clean" not in fmt_metrics_dead_code(snapshot.dead_code_count)


def test_cli_dead_code_summary_never_understates_the_gate(tmp_path: Path) -> None:
    """The one place the two numbers may differ, and the direction they may differ in.

    A medium-confidence unreferenced symbol is shown as a candidate but does
    not trip ``--fail-dead-code``, so the summary is deliberately the wider
    number. That is safe -- the operator sees more than the gate acts on --
    and it is the reason the invariant above is stated for high-confidence
    items rather than as blanket equality. What must never happen is the
    reverse: the summary reading lower than the gate.
    """

    metrics = replace(
        _project_metrics(),
        dead_code=_dead_items(1, confidence="medium"),
        unreachable_statements=(),
    )
    snapshot = build_metrics_snapshot(
        analysis_result=_analysis_result(metrics),
        metrics_diff=None,
        api_surface_diff_available=False,
    )
    gate = _cli_gate_result(
        tmp_path=tmp_path,
        project_metrics=metrics,
        args=_gating_args(fail_dead_code=True),
    )
    state = gate_state_from_project_metrics(
        project_metrics=metrics,
        coverage_join=None,
        metrics_diff=None,
    )

    assert snapshot.dead_code_count == 1
    assert gate.exit_code == 0, "a medium-confidence candidate must not gate"
    assert snapshot.dead_code_count >= (
        state.dead_high_confidence + state.dead_unreachable_statements
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
        low_value_segment_groups=0,
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


def test_gate_state_carries_the_population_the_score_was_measured_over() -> None:
    """The fact existed on the score and stopped one layer short of the gate.

    ``HealthScore.population`` names whether the run read anything at all.
    Until it reached ``GateState`` the gate could only see ``health.total``,
    so an unmeasured run looked to it exactly like a measured clean one.
    """

    unmeasured = replace(
        _project_metrics(),
        health=HealthScore(
            total=0,
            grade="F",
            dimensions={"coverage": 0},
            population="unmeasured",
        ),
    )

    state = gate_state_from_project_metrics(
        project_metrics=unmeasured,
        coverage_join=None,
        metrics_diff=None,
    )

    assert state.health_population == "unmeasured"


def test_gate_state_reports_a_measured_population_as_measured() -> None:
    """The reverse skew: an ordinary run must not look unmeasured."""

    state = gate_state_from_project_metrics(
        project_metrics=_project_metrics(),
        coverage_join=None,
        metrics_diff=None,
    )

    assert state.health_population == "complete_nonempty"


def test_gate_state_carries_the_skipped_file_count() -> None:
    """``files_skipped`` is carried to the pixel and asked by nobody.

    It reaches the summary line and the HTML meta table, and no gate or budget
    ever reads it. This is the seam where it enters a decision.
    """

    state = gate_state_from_project_metrics(
        project_metrics=_project_metrics(),
        coverage_join=None,
        metrics_diff=None,
        files_skipped=29,
    )

    assert state.files_skipped == 29


def _cli_gate_without_metrics(
    *,
    tmp_path: Path,
    population: str,
    args: Namespace,
) -> GateResult:
    """The ``--skip-metrics`` shape: no project metrics, no metrics payload.

    ``analysis_population`` is the run's own population fact from its sole
    owner (``observed_population``); with no ``project_metrics`` to carry it,
    this parameter is the only road it has into the gate state.
    """

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
        low_value_segment_groups=0,
        block_group_facts={},
        func_clones_count=0,
        block_clones_count=0,
        segment_clones_count=0,
        files_analyzed_or_cached=0,
        project_metrics=None,
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
        analysis_population=cast("HealthPopulation", population),
    )


def test_cli_gate_without_metrics_refuses_an_unmeasured_population(
    tmp_path: Path,
) -> None:
    """The clone gate must not pass a comparison whose current term is absent.

    With ``--skip-metrics`` there is no ``project_metrics`` to carry the
    population, so the hand-built gate state defaulted to
    ``complete_nonempty`` and ``--fail-on-new`` passed an unmeasured run on
    sets that were empty by construction — while the identical run with
    metrics enabled was refused. One run, one population, two verdicts
    (`G3`); the trusted-lane vector above is what proves lane trust alone
    cannot close this road: it guards the baseline term, not the current one.
    """

    result = _cli_gate_without_metrics(
        tmp_path=tmp_path,
        population="unmeasured",
        args=_gating_args(fail_on_new=True),
    )

    _assert_gate(
        result,
        exit_code=3,
        reasons=(f"metric:{gate_msgs.GATE_REASON_UNMEASURED_POPULATION}",),
    )


def test_cli_gate_without_metrics_refuses_an_emptied_scope(
    tmp_path: Path,
) -> None:
    """The sibling refusal keeps its own wording on the metrics-off road."""

    result = _cli_gate_without_metrics(
        tmp_path=tmp_path,
        population="complete_empty",
        args=_gating_args(fail_on_new=True),
    )

    _assert_gate(
        result,
        exit_code=3,
        reasons=(f"metric:{gate_msgs.GATE_REASON_EMPTY_ANALYSIS_SCOPE}",),
    )


def test_cli_gate_without_metrics_keeps_a_measured_run_clean(
    tmp_path: Path,
) -> None:
    """The opposite boundary: a fully observed metrics-off run still passes."""

    result = _cli_gate_without_metrics(
        tmp_path=tmp_path,
        population="complete_nonempty",
        args=_gating_args(fail_on_new=True),
    )

    _assert_gate(result, exit_code=0, reasons=())


def test_report_document_gate_reads_the_population_it_already_carries() -> None:
    """The document publishes the population; its gate reader must consult it.

    ``evaluate_gates`` rebuilt its state from the family summaries and left
    ``health_population`` at the constructor default, so a stored unmeasured
    document answered every gate the way a measured clean one would — the
    exact divergence from the project-metrics road that `G3` forbids.
    """

    def _document(population: str) -> dict[str, object]:
        return {
            "metrics": {
                "families": {
                    "health": {
                        "summary": {
                            "score": None if population == "unmeasured" else 82,
                            "population": population,
                        }
                    }
                }
            },
            "source_facts": {
                "observation_contract": {"enabled_lanes": ["dependencies"]}
            },
        }

    config = MetricGateConfig(
        fail_complexity=-1,
        fail_coupling=-1,
        fail_cohesion=-1,
        fail_cycles=True,
        fail_dead_code=False,
        fail_health=-1,
        fail_on_new_metrics=False,
    )

    refused = evaluate_gates(
        report_document=_document("unmeasured"),
        config=config,
    )
    _assert_gate(
        refused,
        exit_code=3,
        reasons=(f"metric:{gate_msgs.GATE_REASON_UNMEASURED_POPULATION}",),
    )

    measured = evaluate_gates(
        report_document=_document("complete_nonempty"),
        config=config,
    )
    _assert_gate(measured, exit_code=0, reasons=())
