# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
import re
import sys
import textwrap
from pathlib import Path
from subprocess import CompletedProcess
from typing import cast

import pytest

from benchmarks.run_benchmark import (
    BENCHMARK_CLI_MODULE,
    BENCHMARK_NEUTRAL_ARGS,
    RunMeasurement,
    Scenario,
    _comparison_metrics,
    _load_benchmark_payload,
    _read_report,
    _require_json_object,
    _run_cli_once,
    _scenario_profile,
    _scenario_result,
    _timing_regressions,
    _validate_inventory_sample,
)

from ._report_fixtures import build_test_report_document


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


def _digest_tiers(document: dict[str, object]) -> dict[str, object]:
    """The five named digest tiers of a report the product's builder produced.

    The shape is the report contract, not a guess, so this narrows in one step
    instead of repeating an isinstance ladder the suite already carries
    elsewhere. A document that does not match fails on the next subscript.
    """

    integrity = cast(dict[str, object], document["integrity"])
    return cast(dict[str, object], integrity["digests"])


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
    assert "--no-update-baseline" in BENCHMARK_NEUTRAL_ARGS
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


def test_load_benchmark_payload_accepts_json_object(tmp_path: Path) -> None:
    path = tmp_path / "bench.json"
    path.write_text('{"scenarios": []}', encoding="utf-8")

    assert _load_benchmark_payload(path) == {"scenarios": []}


def test_load_benchmark_payload_rejects_non_object(tmp_path: Path) -> None:
    path = tmp_path / "bench.json"
    path.write_text("[1, 2]", encoding="utf-8")

    with pytest.raises(RuntimeError, match="not an object"):
        _load_benchmark_payload(path)


def test_require_json_object_preserves_mapping_identity() -> None:
    payload: dict[str, object] = {"median": 1.5}

    assert _require_json_object(payload, message="expected object") is payload


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


def test_benchmark_neutral_args_are_a_valid_cli_contract() -> None:
    """Every neutral argument must still exist in the CLI it drives.

    The benchmark harness speaks to CodeClone through argparse, so a flag that
    is renamed or removed turns every scenario into exit code 2 before any work
    happens -- which is exactly how this drifted: the harness kept passing
    ``--no-update-metrics-baseline`` long after the option was gone, and only
    CI noticed. Asserting the flags one by one could not catch that, because
    such an assertion only proves the harness is self-consistent.

    This parses the real argument list with the real parser, so the harness can
    never again disagree with the contract it calls.

    Parsing proves the flags exist; it cannot prove they still mean "measure, do
    not gate" once this repository's own configuration is resolved on top. That
    second half lives in tests/test_cli_unit.py, next to the contract it reads.
    """

    from codeclone.config.argparse_builder import build_parser

    parser = build_parser("test")
    parser.parse_args([".", *BENCHMARK_NEUTRAL_ARGS])


def test_benchmark_report_reader_reads_a_document_the_product_builds(
    tmp_path: Path,
) -> None:
    """The reader is pinned against a real report, with nothing stubbed out.

    Every other test in this module replaces ``_read_report`` with a stub, so
    the reader was free to drift away from the report it consumes -- and it did.
    The v3 digest hierarchy replaced the single ``integrity.digest`` with five
    named tiers under ``integrity.digests``, and the harness kept asking for the
    old key. Nothing went red, because the benchmark was already dying earlier
    on a stale CLI flag; the moment that flag was fixed the harness reached its
    first report and raised "digest block missing".

    The flag guard above proves the harness agrees with the CLI it calls. This
    proves it agrees with the document that CLI produces, by building one with
    the product's own builder.
    """

    document = build_test_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        inventory={
            "files": {
                "total_found": 7,
                "analyzed": 5,
                "cached": 2,
                "skipped": 1,
            }
        },
    )
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(document), encoding="utf-8")

    digest, files = _read_report(report_path)

    evaluation = _digest_tiers(document)["evaluation"]
    assert isinstance(evaluation, dict)
    assert digest == evaluation["value"]
    assert files == {"found": 7, "analyzed": 5, "cached": 2, "skipped": 1}


def test_benchmark_report_reader_names_the_tier_it_cannot_find(
    tmp_path: Path,
) -> None:
    """A missing tier must say which key path is absent, not just "digest".

    The original message named a key that had not existed for weeks, which cost
    a reader the time to discover the block was there under a different name.
    """

    document = build_test_report_document(
        func_groups={}, block_groups={}, segment_groups={}
    )
    del _digest_tiers(document)["evaluation"]

    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(RuntimeError, match=re.escape("integrity.digests.evaluation")):
        _read_report(report_path)


def _write_tiny_target(root: Path) -> Path:
    """A minimal but real analysis target: two typed, documented modules."""

    target = root / "target"
    target.mkdir()
    (target / "alpha.py").write_text(
        textwrap.dedent(
            '''
            def add(a: int, b: int) -> int:
                """Add two integers."""
                return a + b
            '''
        ),
        encoding="utf-8",
    )
    (target / "beta.py").write_text(
        textwrap.dedent(
            '''
            def mul(a: int, b: int) -> int:
                """Multiply two integers."""
                return a * b
            '''
        ),
        encoding="utf-8",
    )
    return target


def test_benchmark_scenario_leaves_no_per_iteration_reports_after_success(
    tmp_path: Path,
) -> None:
    """A completed scenario must not keep any per-iteration report artifacts.

    The harness writes ``seed-report.json``, ``warmup-report-{idx}.json``, and
    ``run-report-{idx}.json`` -- plus one sibling per extra report format --
    for every iteration and never deleted any of them. The smoke profile
    multiplies that by runs x warmups x scenarios inside a small container, so
    the reports accumulated until the disk was gone: CI died mid-scenario at
    ``cold_full/run-report-9.json`` with "No space left on device". Once an
    iteration's measurement is extracted the files carry no further signal --
    determinism compares digest strings and inventory validation reads
    measurement fields -- so a successful scenario must leave its directory
    clean of them, bounding disk use by construction. Nothing is stubbed:
    the real CLI runs against a real target.
    """

    target = _write_tiny_target(tmp_path)
    workspace = tmp_path / "workspace"
    scenario = Scenario(name="warm_tiny", mode="warm", report_formats=("html",))

    result = _scenario_result(
        scenario=scenario,
        target=target,
        python_executable=sys.executable,
        workspace=workspace,
        warmups=1,
        runs=2,
    )

    assert result["deterministic"] is True
    scenario_dir = workspace / scenario.name
    leftover_reports = sorted(
        path.name
        for path in scenario_dir.iterdir()
        if path.name.startswith(("seed-report", "warmup-report", "run-report"))
    )
    assert leftover_reports == []
    # Only report artifacts are bounded; the warm cache is the scenario's
    # working state and stays.
    assert (scenario_dir / "shared-cache.json").exists()


def _write_report_artifacts(
    tmp_path: Path,
    document: dict[str, object],
) -> tuple[Path, Path]:
    """Materialize one iteration's report and its html sibling on disk."""

    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(document), encoding="utf-8")
    html_path = tmp_path / "report.html"
    html_path.write_text("<html></html>", encoding="utf-8")
    return report_path, html_path


def _run_stubbed_iteration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    report_path: Path,
) -> RunMeasurement:
    """Drive one ``_run_cli_once`` iteration over a pre-written report."""

    monkeypatch.setattr(
        "benchmarks.run_benchmark.subprocess.run",
        lambda cmd, *, check, capture_output, text, env: CompletedProcess(
            cmd, 0, stdout="", stderr=""
        ),
    )
    return _run_cli_once(
        target=tmp_path,
        python_executable="python3",
        cache_path=tmp_path / "cache.json",
        report_path=report_path,
        extra_args=(),
        report_formats=("html",),
    )


def test_benchmark_runner_deletes_report_artifacts_after_measurement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """One successful iteration deletes its report and format siblings.

    Deletion must happen only after the measurement is extracted: the
    returned ``artifact_bytes`` still carries the sizes of the files that
    are gone from disk.
    """

    document = build_test_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        inventory={
            "files": {
                "total_found": 2,
                "analyzed": 2,
                "cached": 0,
                "skipped": 0,
            }
        },
    )
    report_path, html_path = _write_report_artifacts(tmp_path, document)
    json_size = report_path.stat().st_size
    html_size = html_path.stat().st_size

    measurement = _run_stubbed_iteration(monkeypatch, tmp_path, report_path)

    assert measurement.artifact_bytes == {"html": html_size, "json": json_size}
    assert not report_path.exists()
    assert not html_path.exists()


def test_benchmark_runner_preserves_report_artifacts_on_contract_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A failed iteration leaves its report artifacts on disk for forensics.

    When the report violates its contract the exception is the measurement,
    and the file that produced it is the evidence; cleanup applies only to
    iterations whose measurement was extracted successfully.
    """

    document = build_test_report_document(
        func_groups={}, block_groups={}, segment_groups={}
    )
    del _digest_tiers(document)["evaluation"]
    report_path, html_path = _write_report_artifacts(tmp_path, document)

    with pytest.raises(RuntimeError, match=re.escape("integrity.digests.evaluation")):
        _run_stubbed_iteration(monkeypatch, tmp_path, report_path)

    assert report_path.exists()
    assert html_path.exists()
