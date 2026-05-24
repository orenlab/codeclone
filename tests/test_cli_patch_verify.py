from __future__ import annotations

from argparse import Namespace
from types import SimpleNamespace
from typing import Any, cast

import pytest

import codeclone.surfaces.cli.changed_scope as cli_changed_scope
import codeclone.surfaces.cli.workflow as cli_workflow
from codeclone.contracts import ExitCode
from codeclone.core._types import AnalysisResult
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
