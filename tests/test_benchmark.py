# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess

import pytest

from benchmarks.run_benchmark import (
    BENCHMARK_CLI_MODULE,
    BENCHMARK_NEUTRAL_ARGS,
    RunMeasurement,
    Scenario,
    _comparison_metrics,
    _run_cli_once,
    _scenario_profile,
    _timing_regressions,
    _validate_inventory_sample,
)


def _measurement(
    *,
    found: int,
    analyzed: int,
    cached: int,
    skipped: int = 0,
) -> RunMeasurement:
    return RunMeasurement(
        elapsed_seconds=0.1,
        child_user_seconds=0.08,
        child_system_seconds=0.01,
        exit_code=0,
        digest="digest",
        files_found=found,
        files_analyzed=analyzed,
        files_cached=cached,
        files_skipped=skipped,
        artifact_bytes={"json": 128},
        cache_bytes=256,
    )


def _benchmark_payload(
    *,
    cold_full: float,
    warm_full: float,
    warm_clones_only: float,
) -> dict[str, object]:
    def _scenario(name: str, median: float) -> dict[str, object]:
        return {
            "name": name,
            "stats_seconds": {"median": median},
        }

    return {
        "scenarios": [
            _scenario("cold_full", cold_full),
            _scenario("warm_full", warm_full),
            _scenario("warm_clones_only", warm_clones_only),
        ]
    }


def test_benchmark_inventory_validation_accepts_valid_cold_and_warm_samples() -> None:
    _validate_inventory_sample(
        scenario=Scenario(name="cold_full", mode="cold", extra_args=()),
        measurement=_measurement(found=10, analyzed=10, cached=0),
    )
    _validate_inventory_sample(
        scenario=Scenario(name="warm_full", mode="warm", extra_args=()),
        measurement=_measurement(found=10, analyzed=0, cached=10),
    )


def test_benchmark_neutral_args_disable_repo_quality_gates() -> None:
    assert "--no-fail-on-new" in BENCHMARK_NEUTRAL_ARGS
    assert "--no-fail-on-new-metrics" in BENCHMARK_NEUTRAL_ARGS
    assert "--no-fail-cycles" in BENCHMARK_NEUTRAL_ARGS
    assert "--no-fail-dead-code" in BENCHMARK_NEUTRAL_ARGS
    assert "--no-api-surface" in BENCHMARK_NEUTRAL_ARGS
    assert "--no-update-metrics-baseline" in BENCHMARK_NEUTRAL_ARGS
    assert "--fail-health" in BENCHMARK_NEUTRAL_ARGS
    assert "--min-typing-coverage" in BENCHMARK_NEUTRAL_ARGS
    assert "--min-docstring-coverage" in BENCHMARK_NEUTRAL_ARGS
    assert "--skip-metrics" not in BENCHMARK_NEUTRAL_ARGS


def test_benchmark_runner_invokes_canonical_main_entrypoint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(
        cmd: list[str],
        *,
        check: bool,
        capture_output: bool,
        text: bool,
        env: dict[str, str],
    ) -> CompletedProcess[str]:
        captured["cmd"] = cmd
        captured["check"] = check
        captured["capture_output"] = capture_output
        captured["text"] = text
        captured["env"] = env
        return CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("benchmarks.run_benchmark.subprocess.run", fake_run)
    monkeypatch.setattr(
        "benchmarks.run_benchmark._read_report",
        lambda _report_path: (
            "digest",
            {"found": 10, "analyzed": 10, "cached": 0, "skipped": 0},
        ),
    )

    _run_cli_once(
        target=tmp_path,
        python_executable="python3",
        cache_path=tmp_path / "cache.json",
        report_path=tmp_path / "report.json",
        extra_args=("--skip-metrics",),
    )

    assert captured["cmd"] == [
        "python3",
        "-m",
        BENCHMARK_CLI_MODULE,
        str(tmp_path),
        *BENCHMARK_NEUTRAL_ARGS,
        "--json",
        str(tmp_path / "report.json"),
        "--cache-path",
        str(tmp_path / "cache.json"),
        "--no-progress",
        "--quiet",
        "--skip-metrics",
    ]


def test_benchmark_runner_can_emit_additional_report_formats(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(
        cmd: list[str],
        *,
        check: bool,
        capture_output: bool,
        text: bool,
        env: dict[str, str],
    ) -> CompletedProcess[str]:
        captured["cmd"] = cmd
        captured["check"] = check
        captured["capture_output"] = capture_output
        captured["text"] = text
        captured["env"] = env
        return CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("benchmarks.run_benchmark.subprocess.run", fake_run)
    monkeypatch.setattr(
        "benchmarks.run_benchmark._read_report",
        lambda _report_path: (
            "digest",
            {"found": 10, "analyzed": 10, "cached": 0, "skipped": 0},
        ),
    )

    report_path = tmp_path / "report.json"
    _run_cli_once(
        target=tmp_path,
        python_executable="python3",
        cache_path=tmp_path / "cache.json",
        report_path=report_path,
        extra_args=(),
        report_formats=("html", "md", "sarif", "text"),
    )

    assert captured["cmd"] == [
        "python3",
        "-m",
        BENCHMARK_CLI_MODULE,
        str(tmp_path),
        *BENCHMARK_NEUTRAL_ARGS,
        "--json",
        str(report_path),
        "--html",
        str(tmp_path / "report.html"),
        "--md",
        str(tmp_path / "report.md"),
        "--sarif",
        str(tmp_path / "report.sarif"),
        "--text",
        str(tmp_path / "report.txt"),
        "--cache-path",
        str(tmp_path / "cache.json"),
        "--no-progress",
        "--quiet",
    ]


def test_benchmark_extended_profile_adds_capped_report_scenarios() -> None:
    scenarios = {scenario.name: scenario for scenario in _scenario_profile("extended")}

    assert set(scenarios) == {
        "cold_full",
        "warm_full",
        "warm_clones_only",
        "cold_html",
        "warm_html",
        "cold_all_reports",
        "warm_all_reports",
    }
    assert scenarios["cold_html"].report_formats == ("html",)
    assert scenarios["cold_html"].run_cap == 3
    assert scenarios["warm_all_reports"].report_formats == (
        "html",
        "md",
        "sarif",
        "text",
    )
    assert scenarios["warm_all_reports"].run_cap == 5


def test_benchmark_diagnostic_profile_allows_ci_gate_exit_codes() -> None:
    scenarios = {
        scenario.name: scenario for scenario in _scenario_profile("diagnostic")
    }

    diagnostic = scenarios["ci_cold_diagnostic"]
    assert diagnostic.extra_args == ("--ci",)
    assert diagnostic.expected_exit_codes == (0, 2, 3)


def test_benchmark_comparison_metrics_include_report_overheads() -> None:
    scenarios: list[dict[str, object]] = [
        {"name": "cold_full", "stats_seconds": {"median": 2.0}},
        {"name": "warm_full", "stats_seconds": {"median": 1.0}},
        {"name": "warm_clones_only", "stats_seconds": {"median": 0.5}},
        {"name": "cold_html", "stats_seconds": {"median": 2.4}},
        {"name": "warm_html", "stats_seconds": {"median": 1.2}},
        {"name": "cold_all_reports", "stats_seconds": {"median": 3.0}},
        {"name": "warm_all_reports", "stats_seconds": {"median": 1.5}},
    ]

    assert _comparison_metrics(scenarios) == {
        "cold_all_reports_overhead_vs_cold_full": 1.5,
        "cold_html_overhead_vs_cold_full": 1.2,
        "warm_all_reports_overhead_vs_warm_full": 1.5,
        "warm_clones_only_speedup_vs_warm_full": 2.0,
        "warm_full_speedup_vs_cold_full": 2.0,
        "warm_html_overhead_vs_warm_full": 1.2,
    }


@pytest.mark.parametrize(
    ("scenario", "measurement", "message"),
    (
        (
            Scenario(name="cold_full", mode="cold", extra_args=()),
            _measurement(found=10, analyzed=0, cached=0, skipped=10),
            "skipped 10 files",
        ),
        (
            Scenario(name="cold_full", mode="cold", extra_args=()),
            _measurement(found=10, analyzed=9, cached=1),
            "unexpectedly used cache",
        ),
        (
            Scenario(name="warm_full", mode="warm", extra_args=()),
            _measurement(found=10, analyzed=10, cached=0),
            "did not use cache",
        ),
        (
            Scenario(name="warm_full", mode="warm", extra_args=()),
            _measurement(found=10, analyzed=1, cached=9),
            "analyzed files unexpectedly",
        ),
    ),
)
def test_benchmark_inventory_validation_rejects_invalid_samples(
    scenario: Scenario,
    measurement: RunMeasurement,
    message: str,
) -> None:
    with pytest.raises(RuntimeError, match=message):
        _validate_inventory_sample(
            scenario=scenario,
            measurement=measurement,
        )


def test_benchmark_timing_regressions_accept_within_tolerance() -> None:
    baseline = _benchmark_payload(
        cold_full=1.0,
        warm_full=0.30,
        warm_clones_only=0.25,
    )
    current = _benchmark_payload(
        cold_full=1.04,
        warm_full=0.31,
        warm_clones_only=0.24,
    )

    assert (
        _timing_regressions(
            current_payload=current,
            baseline_payload=baseline,
            max_regression_pct=5.0,
        )
        == []
    )


def test_benchmark_timing_regressions_report_excess_slowdown() -> None:
    baseline = _benchmark_payload(
        cold_full=1.0,
        warm_full=0.30,
        warm_clones_only=0.25,
    )
    current = _benchmark_payload(
        cold_full=1.07,
        warm_full=0.32,
        warm_clones_only=0.27,
    )

    regressions = _timing_regressions(
        current_payload=current,
        baseline_payload=baseline,
        max_regression_pct=5.0,
    )

    assert regressions == [
        "cold_full: median 1.0700s exceeds baseline 1.0000s by 7.00% (allowed 5.00%)",
        (
            "warm_clones_only: median 0.2700s exceeds baseline 0.2500s "
            "by 8.00% (allowed 5.00%)"
        ),
        "warm_full: median 0.3200s exceeds baseline 0.3000s by 6.67% (allowed 5.00%)",
    ]
