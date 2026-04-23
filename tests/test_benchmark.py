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
    _run_cli_once,
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
        digest="digest",
        files_found=found,
        files_analyzed=analyzed,
        files_cached=cached,
        files_skipped=skipped,
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
