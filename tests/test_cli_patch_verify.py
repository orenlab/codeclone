# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

from argparse import Namespace
from types import SimpleNamespace
from typing import Any, cast

import pytest

import codeclone.surfaces.cli.changed_scope as cli_changed_scope
import codeclone.surfaces.cli.workflow as cli_workflow
from codeclone.contracts import ExitCode
from codeclone.core._types import AnalysisResult
from codeclone.models import HealthScore, MetricsDiff, ProjectMetrics
from codeclone.surfaces.cli.patch_verify import (
    render_patch_verify,
    validate_strictness,
)
from codeclone.surfaces.cli.post_run import DiffContext


class _RecordingPrinter:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def print(self, *objects: object, **kwargs: object) -> None:
        self.lines.append(" ".join(str(item) for item in objects))

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def _args(**overrides: object) -> Namespace:
    values: dict[str, object] = {
        "fail_complexity": -1,
        "fail_coupling": -1,
        "fail_cohesion": -1,
        "fail_cycles": False,
        "fail_dead_code": False,
        "fail_health": -1,
        "fail_on_new_metrics": False,
        "fail_on_typing_regression": False,
        "fail_on_docstring_regression": False,
        "fail_on_api_break": False,
        "fail_on_untested_hotspots": False,
        "min_typing_coverage": -1,
        "min_docstring_coverage": -1,
        "coverage_min": 50,
    }
    values.update(overrides)
    return Namespace(**values)


def _analysis(*, function_clones: int = 0) -> AnalysisResult:
    return AnalysisResult(
        func_groups={},
        block_groups={},
        block_groups_report={},
        segment_groups={},
        suppressed_segment_groups=0,
        block_group_facts={},
        func_clones_count=function_clones,
        block_clones_count=0,
        segment_clones_count=0,
        files_analyzed_or_cached=1,
        project_metrics=None,
        metrics_payload=None,
        suggestions=(),
        segment_groups_raw_digest="",
    )


def _diff_context(*, new_clones: int = 0) -> DiffContext:
    return DiffContext(
        new_func={f"func-{index}" for index in range(new_clones)},
        new_block=set(),
        new_clones_count=new_clones,
        metrics_diff=None,
        coverage_adoption_diff_available=False,
        api_surface_diff_available=False,
    )


def _baseline_state(*, trusted: bool = True) -> object:
    return SimpleNamespace(trusted_for_diff=trusted)


def test_patch_verify_accepts_clean_patch_quiet() -> None:
    printer = _RecordingPrinter()

    exit_code = render_patch_verify(
        console=printer,
        args=cast(Any, _args()),
        strictness="ci",
        analysis=_analysis(),
        diff_context=_diff_context(),
        baseline_state=cast(Any, _baseline_state()),
        quiet=True,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    assert printer.text == (
        "patch-verify: accepted | health=0->0 regressions=0 gates=pass"
    )


@pytest.mark.parametrize(
    ("strictness", "expected_code", "expected_text"),
    [
        (
            "ci",
            int(ExitCode.GATING_FAILURE),
            "patch-verify: violated | health=0->0 regressions=1 gates=FAIL",
        ),
        (
            "relaxed",
            int(ExitCode.SUCCESS),
            "patch-verify: violated | health=0->0 regressions=1 gates=pass",
        ),
    ],
)
def test_patch_verify_reports_clone_regressions_by_strictness(
    strictness: str,
    expected_code: int,
    expected_text: str,
) -> None:
    printer = _RecordingPrinter()

    exit_code = render_patch_verify(
        console=printer,
        args=cast(Any, _args()),
        strictness=strictness,
        analysis=_analysis(function_clones=1),
        diff_context=_diff_context(new_clones=1),
        baseline_state=cast(Any, _baseline_state()),
        quiet=True,
    )

    assert exit_code == expected_code
    assert printer.text == expected_text


def test_patch_verify_requires_trusted_baseline() -> None:
    printer = _RecordingPrinter()

    exit_code = render_patch_verify(
        console=printer,
        args=cast(Any, _args()),
        strictness="ci",
        analysis=_analysis(),
        diff_context=_diff_context(),
        baseline_state=cast(Any, _baseline_state(trusted=False)),
        quiet=True,
    )

    assert exit_code == int(ExitCode.CONTRACT_ERROR)
    assert "Patch verify requires a trusted baseline" in printer.text


def test_patch_verify_validates_strictness_values() -> None:
    assert validate_strictness("ci") == "ci"
    assert validate_strictness("strict") == "strict"
    assert validate_strictness("relaxed") == "relaxed"
    with pytest.raises(ValueError, match="Invalid --strictness value"):
        validate_strictness("nope")


def test_patch_verify_rejects_invalid_strictness() -> None:
    printer = _RecordingPrinter()

    exit_code = render_patch_verify(
        console=printer,
        args=cast(Any, _args()),
        strictness="nope",
        analysis=_analysis(),
        diff_context=_diff_context(),
        baseline_state=cast(Any, _baseline_state()),
        quiet=True,
    )

    assert exit_code == int(ExitCode.CONTRACT_ERROR)
    assert "Invalid --strictness value" in printer.text


def test_patch_verify_verbose_accepted() -> None:
    printer = _RecordingPrinter()

    exit_code = render_patch_verify(
        console=printer,
        args=cast(Any, _args()),
        strictness="ci",
        analysis=_analysis(),
        diff_context=_diff_context(),
        baseline_state=cast(Any, _baseline_state()),
        quiet=False,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    text = printer.text
    assert "accepted" in text.lower()
    expected_sections = (
        "Patch Verify",
        "Strictness:",
        "Health:",
        "Structural delta:",
        "Gate preview:",
        "Contract violations:",
        "Patch contract accepted",
    )
    for section in expected_sections:
        assert section in text, f"Missing section: {section}"


def test_patch_verify_verbose_violated() -> None:
    printer = _RecordingPrinter()

    exit_code = render_patch_verify(
        console=printer,
        args=cast(Any, _args()),
        strictness="ci",
        analysis=_analysis(function_clones=1),
        diff_context=_diff_context(new_clones=1),
        baseline_state=cast(Any, _baseline_state()),
        quiet=False,
    )

    assert exit_code == int(ExitCode.GATING_FAILURE)
    text = printer.text
    assert "violated" in text.lower()
    assert "structural_regressions" in text
    assert "Patch contract violated" in text


def test_patch_verify_verbose_relaxed_advisory() -> None:
    printer = _RecordingPrinter()

    exit_code = render_patch_verify(
        console=printer,
        args=cast(Any, _args()),
        strictness="relaxed",
        analysis=_analysis(function_clones=1),
        diff_context=_diff_context(new_clones=1),
        baseline_state=cast(Any, _baseline_state()),
        quiet=False,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    text = printer.text
    assert "advisory violations" in text
    assert "relaxed mode exits 0" in text


def test_patch_verify_strict_strictness_quiet_enforces_health() -> None:
    """Strict mode with health_floor=70 and no metrics yields gate failure."""
    printer = _RecordingPrinter()

    exit_code = render_patch_verify(
        console=printer,
        args=cast(Any, _args()),
        strictness="strict",
        analysis=_analysis(),
        diff_context=_diff_context(),
        baseline_state=cast(Any, _baseline_state()),
        quiet=True,
    )

    assert exit_code == int(ExitCode.GATING_FAILURE)
    assert "violated" in printer.text


def _project_metrics(*, health: int = 85) -> ProjectMetrics:
    return ProjectMetrics(
        complexity_avg=5.0,
        complexity_max=10,
        high_risk_functions=(),
        coupling_avg=3.0,
        coupling_max=5,
        high_risk_classes=(),
        cohesion_avg=1.0,
        cohesion_max=2,
        low_cohesion_classes=(),
        dependency_modules=3,
        dependency_edges=2,
        dependency_edge_list=(),
        dependency_cycles=(),
        dependency_max_depth=2,
        dependency_longest_chains=(),
        dead_code=(),
        health=HealthScore(total=health, grade="A", dimensions={}),
    )


def _analysis_with_metrics(
    *, health: int = 85, function_clones: int = 0
) -> AnalysisResult:
    return AnalysisResult(
        func_groups={},
        block_groups={},
        block_groups_report={},
        segment_groups={},
        suppressed_segment_groups=0,
        block_group_facts={},
        func_clones_count=function_clones,
        block_clones_count=0,
        segment_clones_count=0,
        files_analyzed_or_cached=1,
        project_metrics=_project_metrics(health=health),
        metrics_payload=None,
        suggestions=(),
        segment_groups_raw_digest="",
    )


def test_patch_verify_with_project_metrics_quiet() -> None:
    """Covers _health_after, _health_delta, and gate_state_from_project_metrics."""
    printer = _RecordingPrinter()

    exit_code = render_patch_verify(
        console=printer,
        args=cast(Any, _args()),
        strictness="ci",
        analysis=_analysis_with_metrics(health=85),
        diff_context=_diff_context(),
        baseline_state=cast(Any, _baseline_state()),
        quiet=True,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    assert "health=85->85" in printer.text
    assert "accepted" in printer.text


def test_patch_verify_with_project_metrics_verbose() -> None:
    printer = _RecordingPrinter()

    exit_code = render_patch_verify(
        console=printer,
        args=cast(Any, _args()),
        strictness="ci",
        analysis=_analysis_with_metrics(health=85),
        diff_context=_diff_context(),
        baseline_state=cast(Any, _baseline_state()),
        quiet=False,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    assert "85 -> 85" in printer.text


def _diff_context_with_metrics_diff(
    *, new_clones: int = 0, health_delta: int = 0
) -> DiffContext:
    return DiffContext(
        new_func={f"func-{index}" for index in range(new_clones)},
        new_block=set(),
        new_clones_count=new_clones,
        metrics_diff=MetricsDiff(
            new_high_risk_functions=(),
            new_high_coupling_classes=(),
            new_cycles=(),
            new_dead_code=(),
            health_delta=health_delta,
        ),
        coverage_adoption_diff_available=False,
        api_surface_diff_available=False,
    )


def test_patch_verify_health_delta_from_metrics_diff() -> None:
    """Covers _health_delta with a real MetricsDiff object."""
    printer = _RecordingPrinter()

    exit_code = render_patch_verify(
        console=printer,
        args=cast(Any, _args()),
        strictness="ci",
        analysis=_analysis_with_metrics(health=85),
        diff_context=_diff_context_with_metrics_diff(health_delta=5),
        baseline_state=cast(Any, _baseline_state()),
        quiet=True,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    assert "health=80->85" in printer.text


def test_patch_verify_allows_diff_against_without_changed_only() -> None:
    cli_workflow.console = cli_workflow._make_plain_console()
    args = Namespace(
        changed_only=False,
        diff_against="HEAD~1",
        paths_from_git_diff=None,
        patch_verify=True,
        blast_radius=None,
    )

    assert cli_changed_scope._validate_changed_scope_args(args=args) == "HEAD~1"


def test_controller_query_flags_reject_mutually_exclusive_modes() -> None:
    cli_workflow.console = cli_workflow._make_plain_console()
    args = Namespace(
        blast_radius=("pkg/a.py",),
        patch_verify=True,
        strictness="ci",
        update_baseline=False,
        update_metrics_baseline=False,
    )

    with pytest.raises(SystemExit) as exc:
        cli_workflow._validate_controller_query_flags(args=args)

    assert exc.value.code == int(ExitCode.CONTRACT_ERROR)
