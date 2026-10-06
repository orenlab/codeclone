# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

import contextlib
import io
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import codeclone.surfaces.cli.changed_scope as cli_changed_scope
import codeclone.surfaces.cli.workflow as cli_workflow
from codeclone.contracts import ExitCode
from codeclone.contracts.comparison_state import COMPARISON_HEALTH, TERM_SCORE_DELTA
from codeclone.core._types import AnalysisResult
from codeclone.models import (
    HealthScore,
    LaneTrust,
    MetricsDiff,
    ProjectMetrics,
    TrustVector,
)
from codeclone.surfaces.cli.patch_verify import (
    patch_gate_config,
    render_patch_verify,
    validate_strictness,
)
from codeclone.surfaces.cli.post_run import DiffContext
from tests import conftest as corpora
from tests._report_fixtures import build_test_report_document
from tests.test_observation_contract import TEST_OBSERVATION_BUNDLE


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
        low_value_segment_groups=0,
        block_group_facts={},
        func_clones_count=function_clones,
        block_clones_count=0,
        segment_clones_count=0,
        files_analyzed_or_cached=1,
        project_metrics=None,
        metrics_payload=None,
        suggestions=(),
        segment_groups_raw_digest="",
        observation_bundle=TEST_OBSERVATION_BUNDLE,
    )


def _diff_context(*, new_clones: int = 0) -> DiffContext:
    return DiffContext(
        new_func={f"func-{index}" for index in range(new_clones)},
        new_block=set(),
        new_clones_count=new_clones,
        clone_novelty_available=True,
        metrics_diff=None,
        coverage_adoption_diff_available=False,
        api_surface_diff_available=False,
    )


def _baseline_state(*, trusted: bool = True) -> object:
    return SimpleNamespace(trusted_for_diff=trusted)


def _report_document(
    *,
    gate_exit_code: int = 0,
    gate_reasons: tuple[str, ...] = (),
) -> dict[str, object]:
    trust = TrustVector(
        root_verified=True,
        lanes=tuple(
            LaneTrust(name=lane, status="trusted", reason="compatible")
            for lane in TEST_OBSERVATION_BUNDLE.contract.enabled_lanes
        ),
    )
    return build_test_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        baseline_trust=trust,
        gate_exit_code=gate_exit_code,
        gate_reasons=gate_reasons,
    )


def test_patch_verify_accepts_clean_patch_quiet() -> None:
    printer = _RecordingPrinter()

    exit_code = render_patch_verify(
        console=printer,
        args=cast(Any, _args()),
        strictness="ci",
        report_document=_report_document(),
        analysis=_analysis(),
        diff_context=_diff_context(),
        baseline_state=cast(Any, _baseline_state()),
        quiet=True,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    assert printer.text == (
        "patch-verify: accepted | health=0 delta=n/a (not compared) "
        "regressions=0 gates=pass"
    )


@pytest.mark.parametrize(
    ("strictness", "expected_code", "expected_text"),
    [
        (
            "ci",
            int(ExitCode.GATING_FAILURE),
            "patch-verify: violated | health=0 delta=n/a (not compared) "
            "regressions=1 gates=FAIL",
        ),
        (
            "relaxed",
            int(ExitCode.SUCCESS),
            "patch-verify: violated | health=0 delta=n/a (not compared) "
            "regressions=1 gates=pass",
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
        report_document=_report_document(
            gate_exit_code=(
                int(ExitCode.SUCCESS)
                if strictness == "relaxed"
                else int(ExitCode.GATING_FAILURE)
            )
        ),
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
        report_document=_report_document(),
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


def test_patch_gate_config_covers_strictness_threshold_profiles() -> None:
    strict = patch_gate_config(
        args=cast(
            Any,
            _args(
                fail_complexity=11,
                fail_coupling=7,
                fail_cohesion=4,
            ),
        ),
        strictness="strict",
    )
    relaxed = patch_gate_config(
        args=cast(Any, _args()),
        strictness="relaxed",
    )

    assert strict.fail_complexity == 10
    assert strict.fail_coupling == 5
    assert strict.fail_cohesion == 3
    assert relaxed.fail_complexity == -1
    assert relaxed.fail_coupling == -1
    assert relaxed.fail_cohesion == -1


def test_patch_verify_rejects_invalid_strictness() -> None:
    printer = _RecordingPrinter()

    exit_code = render_patch_verify(
        console=printer,
        args=cast(Any, _args()),
        strictness="nope",
        report_document=_report_document(),
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
        report_document=_report_document(),
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
        "Strictness",
        "Health",
        "Regressions",
        "Gate preview",
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
        report_document=_report_document(gate_exit_code=int(ExitCode.GATING_FAILURE)),
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


def test_patch_verify_renders_canonical_gate_reasons() -> None:
    printer = _RecordingPrinter()

    exit_code = render_patch_verify(
        console=printer,
        args=cast(Any, _args()),
        strictness="ci",
        report_document=_report_document(
            gate_exit_code=int(ExitCode.GATING_FAILURE),
            gate_reasons=("clone:new",),
        ),
        analysis=_analysis(),
        diff_context=_diff_context(),
        baseline_state=cast(Any, _baseline_state()),
        quiet=False,
    )

    assert exit_code == int(ExitCode.GATING_FAILURE)
    assert "clone:new" in printer.text


def test_patch_verify_missing_canonical_evaluation_fails_closed() -> None:
    printer = _RecordingPrinter()

    exit_code = render_patch_verify(
        console=printer,
        args=cast(Any, _args()),
        strictness="ci",
        report_document={},
        analysis=_analysis(),
        diff_context=_diff_context(),
        baseline_state=cast(Any, _baseline_state()),
        quiet=True,
    )

    assert exit_code == int(ExitCode.GATING_FAILURE)
    assert "gates=FAIL" in printer.text


def test_patch_verify_verbose_relaxed_advisory() -> None:
    printer = _RecordingPrinter()

    exit_code = render_patch_verify(
        console=printer,
        args=cast(Any, _args()),
        strictness="relaxed",
        report_document=_report_document(),
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
        report_document=_report_document(gate_exit_code=int(ExitCode.GATING_FAILURE)),
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
        low_value_segment_groups=0,
        block_group_facts={},
        func_clones_count=function_clones,
        block_clones_count=0,
        segment_clones_count=0,
        files_analyzed_or_cached=1,
        project_metrics=_project_metrics(health=health),
        metrics_payload=None,
        suggestions=(),
        segment_groups_raw_digest="",
        observation_bundle=TEST_OBSERVATION_BUNDLE,
    )


def test_patch_verify_with_project_metrics_quiet() -> None:
    """Covers _health_after, _health_delta, and gate_state_from_project_metrics."""
    printer = _RecordingPrinter()

    exit_code = render_patch_verify(
        console=printer,
        args=cast(Any, _args()),
        strictness="ci",
        report_document=_report_document(),
        analysis=_analysis_with_metrics(health=85),
        diff_context=_diff_context(),
        baseline_state=cast(Any, _baseline_state()),
        quiet=True,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    # The context states no health comparison: the score, never "85->85".
    assert "health=85 delta=n/a (not compared)" in printer.text
    assert "accepted" in printer.text


def test_patch_verify_with_project_metrics_verbose() -> None:
    printer = _RecordingPrinter()

    exit_code = render_patch_verify(
        console=printer,
        args=cast(Any, _args()),
        strictness="ci",
        report_document=_report_document(),
        analysis=_analysis_with_metrics(health=85),
        diff_context=_diff_context(),
        baseline_state=cast(Any, _baseline_state()),
        quiet=False,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    # The context states no health comparison: never "(+0)".
    assert "85 · health delta: not compared" in printer.text


def _diff_context_with_metrics_diff(
    *, new_clones: int = 0, health_delta: int = 0
) -> DiffContext:
    return DiffContext(
        new_func={f"func-{index}" for index in range(new_clones)},
        new_block=set(),
        new_clones_count=new_clones,
        clone_novelty_available=True,
        metrics_diff=MetricsDiff(
            new_high_risk_functions=(),
            new_high_coupling_classes=(),
            new_cycles=(),
            new_dead_code=(),
            health_delta=health_delta,
        ),
        coverage_adoption_diff_available=False,
        api_surface_diff_available=False,
        stated_comparisons={COMPARISON_HEALTH: {TERM_SCORE_DELTA: health_delta}},
    )


def test_patch_verify_health_delta_from_metrics_diff() -> None:
    """Covers _health_delta: the health comparison the run's state states."""
    printer = _RecordingPrinter()

    exit_code = render_patch_verify(
        console=printer,
        args=cast(Any, _args()),
        strictness="ci",
        report_document=_report_document(),
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


def test_run_controller_query_routes_blast_radius(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def _render_blast_radius(**kwargs: object) -> int:
        files_obj = kwargs.get("files", ())
        assert isinstance(files_obj, tuple)
        # Standing in for the renderer means answering for what the renderer
        # needs. It navigates these two addresses, so a stub that accepted any
        # object let the caller hand it a document real code cannot read --
        # which is how a withdrawn shape survived at this call site.
        document = kwargs.get("report_document")
        assert isinstance(document, dict)
        integrity = cast("dict[str, Any]", document["integrity"])
        assert integrity["digests"]["envelope"]["value"]
        inventory = cast("dict[str, Any]", document["inventory"])
        assert isinstance(inventory["file_registry"]["items"], list)
        calls.append(tuple(str(path) for path in files_obj))
        return int(ExitCode.SUCCESS)

    monkeypatch.setattr(
        "codeclone.surfaces.cli.blast_radius.render_blast_radius",
        _render_blast_radius,
    )
    args = Namespace(
        blast_radius=("pkg/a.py",),
        patch_verify=False,
        quiet=True,
    )
    result = cli_workflow._run_controller_query(
        args=cast(Any, args),
        report_document=_report_document(),
        root_path=tmp_path,
        analysis_result=_analysis(),
        diff_context=_diff_context(),
        baseline_state=cast(Any, _baseline_state()),
    )
    assert result == int(ExitCode.SUCCESS)
    assert calls == [("pkg/a.py",)]


def test_run_controller_query_routes_patch_verify(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _render_patch_verify(**_kwargs: object) -> int:
        return int(ExitCode.GATING_FAILURE)

    monkeypatch.setattr(
        "codeclone.surfaces.cli.patch_verify.render_patch_verify",
        _render_patch_verify,
    )
    args = Namespace(
        blast_radius=(),
        patch_verify=True,
        quiet=True,
        strictness="strict",
    )
    result = cli_workflow._run_controller_query(
        args=cast(Any, args),
        report_document=_report_document(),
        root_path=tmp_path,
        analysis_result=_analysis(),
        diff_context=_diff_context(),
        baseline_state=cast(Any, _baseline_state()),
    )
    assert result == int(ExitCode.GATING_FAILURE)


def test_run_controller_query_returns_none_without_controller_mode(
    tmp_path: Path,
) -> None:
    args = Namespace(blast_radius=(), patch_verify=False, quiet=True)
    result = cli_workflow._run_controller_query(
        args=cast(Any, args),
        report_document=None,
        root_path=tmp_path,
        analysis_result=_analysis(),
        diff_context=_diff_context(),
        baseline_state=cast(Any, _baseline_state()),
    )
    assert result is None


# -- the health line: the health comparison the run's state states ---------------
#
# Not compared -> null (ruling 2026-10-03): the human line says the ruling's
# words, never ``(+0)``, and a measured zero stays ``0``.  The state decides;
# the raw metrics diff beside it carries another number that must never reach
# the line.


def _diff_context_stating(health_delta: int | None) -> DiffContext:
    return DiffContext(
        new_func=set(),
        new_block=set(),
        new_clones_count=0,
        clone_novelty_available=True,
        metrics_diff=MetricsDiff(
            new_high_risk_functions=(),
            new_high_coupling_classes=(),
            new_cycles=(),
            new_dead_code=(),
            health_delta=7,
        ),
        coverage_adoption_diff_available=False,
        api_surface_diff_available=False,
        stated_comparisons=(
            {}
            if health_delta is None
            else {COMPARISON_HEALTH: {TERM_SCORE_DELTA: health_delta}}
        ),
    )


def _patch_verify_text(health_delta: int | None, *, quiet: bool) -> str:
    printer = _RecordingPrinter()
    render_patch_verify(
        console=printer,
        args=cast(Any, _args()),
        strictness="ci",
        report_document=_report_document(),
        analysis=_analysis_with_metrics(health=85),
        diff_context=_diff_context_stating(health_delta),
        baseline_state=cast(Any, _baseline_state()),
        quiet=quiet,
    )
    return printer.text


@pytest.mark.parametrize(
    ("health_delta", "line"),
    [
        pytest.param(None, "85 · health delta: not compared", id="not-compared"),
        pytest.param(0, "85 → 85 (0)", id="measured-zero"),
        pytest.param(5, "80 → 85 (+5)", id="rose"),
        pytest.param(-3, "88 → 85 (-3)", id="fell"),
    ],
)
def test_the_rich_health_line_is_the_states_health_comparison(
    health_delta: int | None, line: str
) -> None:
    text = _patch_verify_text(health_delta, quiet=False)
    assert line in text
    assert "(+0)" not in text
    assert "78 → 85" not in text, "the raw metrics diff reached the line"


@pytest.mark.parametrize(
    ("health_delta", "fragment"),
    [
        pytest.param(
            None, "| health=85 delta=n/a (not compared) regressions=", id="not-compared"
        ),
        pytest.param(0, "| health=85->85 regressions=", id="measured-zero"),
        pytest.param(5, "| health=80->85 regressions=", id="rose"),
        pytest.param(-3, "| health=88->85 regressions=", id="fell"),
    ],
)
def test_the_compact_health_line_is_the_states_health_comparison(
    health_delta: int | None, fragment: str
) -> None:
    text = _patch_verify_text(health_delta, quiet=True)
    assert fragment in text
    assert "78->85" not in text, "the raw metrics diff reached the line"


#: The comparison corpus through the real CLI, against the stage-A baseline:
#: the health line each population prints, rich and compact.  ``compared``
#: compares health (+4); with dead code and dependencies skipped two of the
#: lanes health reads were never observed; against a baseline of another
#: scope every lane is untrusted -- both state no health comparison.
CLI_HEALTH_LINES: dict[tuple[str, bool], str] = {
    ("compared", False): "66 → 70 (+4)",
    ("compared", True): "| health=66->70 regressions=",
    ("lanes_skipped", False): "82 · health delta: not compared",
    ("lanes_skipped", True): "| health=82 delta=n/a (not compared) regressions=",
    ("foreign_scope", False): "70 · health delta: not compared",
    ("foreign_scope", True): "| health=70 delta=n/a (not compared) regressions=",
}
_CLI_FLAGS: dict[str, tuple[str, ...]] = {
    "compared": ("--api-surface",),
    "lanes_skipped": ("--api-surface", "--skip-dead-code", "--skip-dependencies"),
    "foreign_scope": ("--api-surface",),
}


@pytest.fixture(scope="module")
def cli_patch_verify_text(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[tuple[str, bool], str]:
    base = tmp_path_factory.mktemp("patch_verify_health").resolve()
    baseline = corpora._comparison_baseline(base)
    texts: dict[tuple[str, bool], str] = {}
    for population, quiet in CLI_HEALTH_LINES:
        root = base / f"{population}{'-quiet' if quiet else ''}"
        corpora.materialize_comparison_corpus(root, stage_b=True)
        if population == "foreign_scope":
            corpora._rewrite_scope_as_foreign(root)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            corpora._run_codeclone_cli_exit(
                [
                    str(root),
                    "--no-progress",
                    "--baseline",
                    str(baseline),
                    "--patch-verify",
                    *(("--quiet",) if quiet else ()),
                    *_CLI_FLAGS[population],
                ],
                {},
            )
        texts[(population, quiet)] = out.getvalue()
    return texts


@pytest.mark.parametrize(("population", "quiet"), list(CLI_HEALTH_LINES))
def test_the_cli_patch_verify_health_line_reads_the_runs_state(
    cli_patch_verify_text: dict[tuple[str, bool], str],
    population: str,
    quiet: bool,
) -> None:
    text = cli_patch_verify_text[(population, quiet)]
    assert CLI_HEALTH_LINES[(population, quiet)] in text, text
