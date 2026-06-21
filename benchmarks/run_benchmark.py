#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean, median, pstdev
from typing import Literal, cast

from codeclone import __version__ as codeclone_version
from codeclone.baseline import current_python_tag

BENCHMARK_SCHEMA_VERSION = "1.1"
BENCHMARK_CLI_MODULE = "codeclone.main"
BenchmarkProfile = Literal["smoke", "extended", "diagnostic"]
ReportFormat = Literal["html", "md", "sarif", "text"]
REPORT_FORMAT_SPECS: Mapping[ReportFormat, tuple[str, str]] = {
    "html": ("--html", ".html"),
    "md": ("--md", ".md"),
    "sarif": ("--sarif", ".sarif"),
    "text": ("--text", ".txt"),
}
BENCHMARK_NEUTRAL_ARGS: tuple[str, ...] = (
    "--no-fail-on-new",
    "--no-fail-on-new-metrics",
    "--no-fail-cycles",
    "--no-fail-dead-code",
    "--no-fail-on-typing-regression",
    "--no-fail-on-docstring-regression",
    "--no-fail-on-api-break",
    "--no-fail-on-untested-hotspots",
    "--fail-threshold",
    "-1",
    "--fail-complexity",
    "-1",
    "--fail-coupling",
    "-1",
    "--fail-cohesion",
    "-1",
    "--fail-health",
    "-1",
    "--min-typing-coverage",
    "-1",
    "--min-docstring-coverage",
    "-1",
    "--no-api-surface",
    "--no-update-metrics-baseline",
)


@dataclass(frozen=True)
class Scenario:
    name: str
    mode: Literal["cold", "warm"]
    extra_args: tuple[str, ...] = ()
    report_formats: tuple[ReportFormat, ...] = ()
    run_cap: int | None = None
    warmup_cap: int | None = None
    expected_exit_codes: tuple[int, ...] = (0,)


@dataclass(frozen=True)
class RunMeasurement:
    elapsed_seconds: float
    child_user_seconds: float
    child_system_seconds: float
    exit_code: int
    digest: str
    files_found: int
    files_analyzed: int
    files_cached: int
    files_skipped: int
    artifact_bytes: dict[str, int]
    cache_bytes: int


@dataclass(frozen=True)
class StartupProbe:
    name: str
    args: tuple[str, ...]


@dataclass(frozen=True)
class ProbeMeasurement:
    elapsed_seconds: float
    child_user_seconds: float
    child_system_seconds: float
    exit_code: int


def _percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (len(sorted_values) - 1) * q
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = rank - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def _stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {
            "min": 0.0,
            "max": 0.0,
            "mean": 0.0,
            "median": 0.0,
            "p95": 0.0,
            "stdev": 0.0,
        }
    ordered = sorted(values)
    return {
        "min": ordered[0],
        "max": ordered[-1],
        "mean": fmean(ordered),
        "median": median(ordered),
        "p95": _percentile(ordered, 0.95),
        "stdev": pstdev(ordered) if len(ordered) > 1 else 0.0,
    }


def _as_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _resource_usage_seconds() -> tuple[float, float]:
    try:
        import resource
    except ImportError:
        return (0.0, 0.0)
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return (float(usage.ru_utime), float(usage.ru_stime))


def _resource_delta(
    before: tuple[float, float],
    after: tuple[float, float],
) -> tuple[float, float]:
    return (
        max(0.0, after[0] - before[0]),
        max(0.0, after[1] - before[1]),
    )


def _normalized_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = "0"
    env["LC_ALL"] = "C.UTF-8"
    env["LANG"] = "C.UTF-8"
    env["TZ"] = "UTC"
    return env


def _artifact_paths(
    *,
    report_path: Path,
    report_formats: tuple[ReportFormat, ...],
) -> dict[str, Path]:
    paths: dict[str, Path] = {"json": report_path}
    for report_format in report_formats:
        _flag, suffix = REPORT_FORMAT_SPECS[report_format]
        paths[report_format] = report_path.with_suffix(suffix)
    return paths


def _artifact_size_map(paths: Mapping[str, Path]) -> dict[str, int]:
    return {
        name: path.stat().st_size
        for name, path in sorted(paths.items())
        if path.exists()
    }


def _file_size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


def _read_report(report_path: Path) -> tuple[str, dict[str, int]]:
    payload_obj: object = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(payload_obj, dict):
        raise RuntimeError(f"report payload is not an object: {report_path}")
    payload = payload_obj

    integrity_obj = payload.get("integrity")
    if not isinstance(integrity_obj, dict):
        raise RuntimeError(f"integrity block missing in {report_path}")
    digest_obj = integrity_obj.get("digest")
    if not isinstance(digest_obj, dict):
        raise RuntimeError(f"digest block missing in {report_path}")
    digest_value = str(digest_obj.get("value", "")).strip()
    if not digest_value:
        raise RuntimeError(f"digest value missing in {report_path}")

    inventory_obj = payload.get("inventory")
    if not isinstance(inventory_obj, dict):
        raise RuntimeError(f"inventory block missing in {report_path}")
    files_obj = inventory_obj.get("files")
    if not isinstance(files_obj, dict):
        raise RuntimeError(f"inventory.files block missing in {report_path}")

    def _as_int(value: object) -> int:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return 0
        return 0

    return digest_value, {
        "found": _as_int(files_obj.get("total_found")),
        "analyzed": _as_int(files_obj.get("analyzed")),
        "cached": _as_int(files_obj.get("cached")),
        "skipped": _as_int(files_obj.get("skipped")),
    }


def _run_cli_once(
    *,
    target: Path,
    python_executable: str,
    cache_path: Path,
    report_path: Path,
    extra_args: tuple[str, ...],
    report_formats: tuple[ReportFormat, ...] = (),
    expected_exit_codes: tuple[int, ...] = (0,),
) -> RunMeasurement:
    env = _normalized_env()
    artifact_paths = _artifact_paths(
        report_path=report_path,
        report_formats=report_formats,
    )
    report_args: list[str] = ["--json", str(report_path)]
    for report_format in report_formats:
        flag, _suffix = REPORT_FORMAT_SPECS[report_format]
        report_args.extend([flag, str(artifact_paths[report_format])])
    cmd = [
        python_executable,
        "-m",
        BENCHMARK_CLI_MODULE,
        str(target),
        *BENCHMARK_NEUTRAL_ARGS,
        *report_args,
        "--cache-path",
        str(cache_path),
        "--no-progress",
        "--quiet",
        *extra_args,
    ]

    usage_before = _resource_usage_seconds()
    start = time.perf_counter()
    completed = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    elapsed_seconds = time.perf_counter() - start
    child_user_seconds, child_system_seconds = _resource_delta(
        usage_before,
        _resource_usage_seconds(),
    )
    if completed.returncode not in expected_exit_codes:
        stderr_tail = "\n".join(completed.stderr.splitlines()[-20:])
        stdout_tail = "\n".join(completed.stdout.splitlines()[-20:])
        raise RuntimeError(
            "benchmark command failed with exit "
            f"{completed.returncode}\nSTDOUT:\n{stdout_tail}\nSTDERR:\n{stderr_tail}"
        )

    digest, files = _read_report(report_path)
    return RunMeasurement(
        elapsed_seconds=elapsed_seconds,
        child_user_seconds=child_user_seconds,
        child_system_seconds=child_system_seconds,
        exit_code=completed.returncode,
        digest=digest,
        files_found=files["found"],
        files_analyzed=files["analyzed"],
        files_cached=files["cached"],
        files_skipped=files["skipped"],
        artifact_bytes=_artifact_size_map(artifact_paths),
        cache_bytes=_file_size(cache_path),
    )


def _validate_inventory_sample(
    *,
    scenario: Scenario,
    measurement: RunMeasurement,
) -> None:
    if measurement.files_found <= 0:
        raise RuntimeError(
            f"scenario {scenario.name} produced an empty inventory sample; "
            "benchmark target is invalid"
        )
    if measurement.files_skipped > 0:
        raise RuntimeError(
            f"scenario {scenario.name} skipped {measurement.files_skipped} files; "
            "benchmark run is invalid"
        )
    if scenario.mode == "cold":
        if measurement.files_cached != 0:
            raise RuntimeError(
                f"cold scenario {scenario.name} unexpectedly used cache: "
                f"cached={measurement.files_cached}"
            )
        if measurement.files_analyzed <= 0:
            raise RuntimeError(
                f"cold scenario {scenario.name} analyzed no files: "
                f"found={measurement.files_found} analyzed={measurement.files_analyzed}"
            )
        return
    if measurement.files_cached <= 0:
        raise RuntimeError(
            f"warm scenario {scenario.name} did not use cache: "
            f"cached={measurement.files_cached}"
        )
    if measurement.files_analyzed != 0:
        raise RuntimeError(
            f"warm scenario {scenario.name} analyzed files unexpectedly: "
            f"analyzed={measurement.files_analyzed}"
        )


def _print_bulleted_lines(header: str, lines: Sequence[str]) -> None:
    if not lines:
        return
    print(header)
    for line in lines:
        print(f"- {line}")


def _effective_count(requested: int, cap: int | None) -> int:
    return min(requested, cap) if cap is not None else requested


def _exit_code_counts(measurements: Sequence[RunMeasurement]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for measurement in measurements:
        key = str(measurement.exit_code)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: int(item[0])))


def _artifact_total_kib(artifact_bytes: Mapping[str, int]) -> float:
    return sum(artifact_bytes.values()) / 1024.0


def _scenario_result(
    *,
    scenario: Scenario,
    target: Path,
    python_executable: str,
    workspace: Path,
    warmups: int,
    runs: int,
) -> dict[str, object]:
    scenario_dir = workspace / scenario.name
    if scenario_dir.exists():
        shutil.rmtree(scenario_dir)
    scenario_dir.mkdir(parents=True, exist_ok=True)

    effective_runs = _effective_count(runs, scenario.run_cap)
    effective_warmups = _effective_count(warmups, scenario.warmup_cap)
    warm_cache_path = scenario_dir / "shared-cache.json"
    cold_cache_path = scenario_dir / "cold-cache.json"

    if scenario.mode == "warm":
        _run_cli_once(
            target=target,
            python_executable=python_executable,
            cache_path=warm_cache_path,
            report_path=scenario_dir / "seed-report.json",
            extra_args=scenario.extra_args,
            report_formats=scenario.report_formats,
            expected_exit_codes=scenario.expected_exit_codes,
        )

    for idx in range(effective_warmups):
        if scenario.mode == "warm":
            cache_path = warm_cache_path
        else:
            cache_path = cold_cache_path
            cache_path.unlink(missing_ok=True)
        _run_cli_once(
            target=target,
            python_executable=python_executable,
            cache_path=cache_path,
            report_path=scenario_dir / f"warmup-report-{idx}.json",
            extra_args=scenario.extra_args,
            report_formats=scenario.report_formats,
            expected_exit_codes=scenario.expected_exit_codes,
        )

    measurements: list[RunMeasurement] = []
    for idx in range(effective_runs):
        if scenario.mode == "warm":
            cache_path = warm_cache_path
        else:
            cache_path = cold_cache_path
            cache_path.unlink(missing_ok=True)
        measurement = _run_cli_once(
            target=target,
            python_executable=python_executable,
            cache_path=cache_path,
            report_path=scenario_dir / f"run-report-{idx}.json",
            extra_args=scenario.extra_args,
            report_formats=scenario.report_formats,
            expected_exit_codes=scenario.expected_exit_codes,
        )
        _validate_inventory_sample(scenario=scenario, measurement=measurement)
        measurements.append(measurement)

    digests = sorted({m.digest for m in measurements})
    deterministic = len(digests) == 1
    if not deterministic:
        raise RuntimeError(
            "non-deterministic report digest detected "
            f"in scenario {scenario.name}: {digests}"
        )

    timings = [m.elapsed_seconds for m in measurements]
    child_user = [m.child_user_seconds for m in measurements]
    child_system = [m.child_system_seconds for m in measurements]
    child_cpu = [m.child_user_seconds + m.child_system_seconds for m in measurements]
    sample = measurements[0]
    return {
        "name": scenario.name,
        "mode": scenario.mode,
        "extra_args": list(scenario.extra_args),
        "report_formats": list(scenario.report_formats),
        "warmups": effective_warmups,
        "runs": effective_runs,
        "requested_warmups": warmups,
        "requested_runs": runs,
        "run_cap": scenario.run_cap,
        "warmup_cap": scenario.warmup_cap,
        "expected_exit_codes": list(scenario.expected_exit_codes),
        "exit_code_counts": _exit_code_counts(measurements),
        "deterministic": deterministic,
        "digest": digests[0],
        "timings_seconds": timings,
        "stats_seconds": _stats(timings),
        "child_user_stats_seconds": _stats(child_user),
        "child_system_stats_seconds": _stats(child_system),
        "child_cpu_stats_seconds": _stats(child_cpu),
        "inventory_sample": {
            "found": sample.files_found,
            "analyzed": sample.files_analyzed,
            "cached": sample.files_cached,
            "skipped": sample.files_skipped,
        },
        "artifact_bytes_sample": sample.artifact_bytes,
        "artifact_total_kib_sample": _artifact_total_kib(sample.artifact_bytes),
        "cache_bytes_sample": sample.cache_bytes,
    }


def _run_probe_once(
    *,
    python_executable: str,
    probe: StartupProbe,
) -> ProbeMeasurement:
    cmd = [python_executable, *probe.args]
    usage_before = _resource_usage_seconds()
    start = time.perf_counter()
    completed = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        env=_normalized_env(),
    )
    elapsed_seconds = time.perf_counter() - start
    child_user_seconds, child_system_seconds = _resource_delta(
        usage_before,
        _resource_usage_seconds(),
    )
    if completed.returncode != 0:
        stderr_tail = "\n".join(completed.stderr.splitlines()[-20:])
        stdout_tail = "\n".join(completed.stdout.splitlines()[-20:])
        raise RuntimeError(
            f"startup probe {probe.name} failed with exit {completed.returncode}"
            f"\nSTDOUT:\n{stdout_tail}\nSTDERR:\n{stderr_tail}"
        )
    return ProbeMeasurement(
        elapsed_seconds=elapsed_seconds,
        child_user_seconds=child_user_seconds,
        child_system_seconds=child_system_seconds,
        exit_code=completed.returncode,
    )


def _startup_probes() -> tuple[StartupProbe, ...]:
    return (
        StartupProbe(name="python_empty", args=("-c", "pass")),
        StartupProbe(name="import_codeclone", args=("-c", "import codeclone")),
        StartupProbe(
            name="import_codeclone_main",
            args=("-c", "import codeclone.main"),
        ),
        StartupProbe(
            name="cli_version",
            args=("-m", BENCHMARK_CLI_MODULE, "--version"),
        ),
    )


def _probe_result(
    *,
    probe: StartupProbe,
    python_executable: str,
    runs: int,
) -> dict[str, object]:
    measurements = [
        _run_probe_once(python_executable=python_executable, probe=probe)
        for _idx in range(runs)
    ]
    timings = [m.elapsed_seconds for m in measurements]
    child_user = [m.child_user_seconds for m in measurements]
    child_system = [m.child_system_seconds for m in measurements]
    child_cpu = [m.child_user_seconds + m.child_system_seconds for m in measurements]
    return {
        "name": probe.name,
        "args": list(probe.args),
        "runs": runs,
        "timings_seconds": timings,
        "stats_seconds": _stats(timings),
        "first_seconds": timings[0] if timings else 0.0,
        "subsequent_stats_seconds": _stats(timings[1:]) if len(timings) > 1 else None,
        "child_user_stats_seconds": _stats(child_user),
        "child_system_stats_seconds": _stats(child_system),
        "child_cpu_stats_seconds": _stats(child_cpu),
        "exit_code_counts": {
            str(code): sum(1 for item in measurements if item.exit_code == code)
            for code in sorted({item.exit_code for item in measurements})
        },
    }


def _scenario_profile(profile: BenchmarkProfile) -> tuple[Scenario, ...]:
    core = (
        Scenario(name="cold_full", mode="cold"),
        Scenario(name="warm_full", mode="warm"),
        Scenario(name="warm_clones_only", mode="warm", extra_args=("--skip-metrics",)),
    )
    report_scenarios = (
        Scenario(
            name="cold_html",
            mode="cold",
            report_formats=("html",),
            run_cap=3,
            warmup_cap=1,
        ),
        Scenario(
            name="warm_html",
            mode="warm",
            report_formats=("html",),
            run_cap=5,
            warmup_cap=1,
        ),
        Scenario(
            name="cold_all_reports",
            mode="cold",
            report_formats=("html", "md", "sarif", "text"),
            run_cap=3,
            warmup_cap=1,
        ),
        Scenario(
            name="warm_all_reports",
            mode="warm",
            report_formats=("html", "md", "sarif", "text"),
            run_cap=5,
            warmup_cap=1,
        ),
    )
    diagnostic_scenarios = (
        Scenario(
            name="ci_cold_diagnostic",
            mode="cold",
            extra_args=("--ci",),
            report_formats=("html",),
            run_cap=3,
            warmup_cap=0,
            expected_exit_codes=(0, 2, 3),
        ),
    )
    if profile == "smoke":
        return core
    if profile == "extended":
        return core + report_scenarios
    return core + report_scenarios + diagnostic_scenarios


def _cgroup_value(path: Path) -> str | None:
    try:
        content = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return content or None


def _environment() -> dict[str, object]:
    affinity_count: int | None = None
    if hasattr(os, "sched_getaffinity"):
        try:
            affinity_count = len(os.sched_getaffinity(0))
        except OSError:
            affinity_count = None

    cgroup_cpu_max = _cgroup_value(Path("/sys/fs/cgroup/cpu.max"))
    cgroup_memory_max = _cgroup_value(Path("/sys/fs/cgroup/memory.max"))
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "python_tag": current_python_tag(),
        "cpu_count": os.cpu_count(),
        "cpu_affinity_count": affinity_count,
        "container_detected": Path("/.dockerenv").exists(),
        "cgroup_cpu_max": cgroup_cpu_max,
        "cgroup_memory_max": cgroup_memory_max,
        "timestamp_utc": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
    }


def _comparison_metrics(scenarios: list[dict[str, object]]) -> dict[str, float]:
    by_name = {
        str(item["name"]): item
        for item in scenarios
        if isinstance(item, dict) and "name" in item
    }

    def _median_for(name: str) -> float | None:
        scenario = by_name.get(name)
        if not isinstance(scenario, dict):
            return None
        stats = scenario.get("stats_seconds")
        if not isinstance(stats, dict):
            return None
        value = stats.get("median")
        if isinstance(value, (int, float)):
            return float(value)
        return None

    cold_full = _median_for("cold_full")
    warm_full = _median_for("warm_full")
    warm_clones = _median_for("warm_clones_only")
    cold_html = _median_for("cold_html")
    warm_html = _median_for("warm_html")
    cold_all_reports = _median_for("cold_all_reports")
    warm_all_reports = _median_for("warm_all_reports")

    comparisons: dict[str, float] = {}
    if cold_full and warm_full:
        comparisons["warm_full_speedup_vs_cold_full"] = cold_full / warm_full
    if warm_full and warm_clones:
        comparisons["warm_clones_only_speedup_vs_warm_full"] = warm_full / warm_clones
    if cold_full and cold_html:
        comparisons["cold_html_overhead_vs_cold_full"] = cold_html / cold_full
    if warm_full and warm_html:
        comparisons["warm_html_overhead_vs_warm_full"] = warm_html / warm_full
    if cold_full and cold_all_reports:
        comparisons["cold_all_reports_overhead_vs_cold_full"] = (
            cold_all_reports / cold_full
        )
    if warm_full and warm_all_reports:
        comparisons["warm_all_reports_overhead_vs_warm_full"] = (
            warm_all_reports / warm_full
        )
    return comparisons


def _load_benchmark_payload(path: Path) -> dict[str, object]:
    payload_obj: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload_obj, dict):
        raise RuntimeError(f"benchmark payload is not an object: {path}")
    return payload_obj


def _scenario_medians(payload: Mapping[str, object]) -> dict[str, float]:
    scenarios_obj = payload.get("scenarios")
    if not isinstance(scenarios_obj, list):
        raise RuntimeError("benchmark payload is missing a scenarios list")

    medians: dict[str, float] = {}
    for item in scenarios_obj:
        if not isinstance(item, dict):
            raise RuntimeError("benchmark scenario entry is not an object")
        name = item.get("name")
        stats = item.get("stats_seconds")
        if not isinstance(name, str) or not isinstance(stats, dict):
            raise RuntimeError("benchmark scenario entry is missing name/stats_seconds")
        median = stats.get("median")
        if not isinstance(median, (int, float)):
            raise RuntimeError(f"benchmark scenario {name} is missing median timing")
        medians[name] = float(median)
    return medians


def _timing_regressions(
    *,
    current_payload: Mapping[str, object],
    baseline_payload: Mapping[str, object],
    max_regression_pct: float,
) -> list[str]:
    current_medians = _scenario_medians(current_payload)
    baseline_medians = _scenario_medians(baseline_payload)

    missing = sorted(set(baseline_medians) - set(current_medians))
    if missing:
        raise RuntimeError(
            "benchmark payload is missing baseline scenario(s): " + ", ".join(missing)
        )

    regressions: list[str] = []
    for name, baseline_median in sorted(baseline_medians.items()):
        if baseline_median <= 0:
            raise RuntimeError(
                f"baseline scenario {name} has non-positive median: {baseline_median}"
            )
        current_median = current_medians[name]
        allowed_median = baseline_median * (1.0 + (max_regression_pct / 100.0))
        if current_median <= allowed_median:
            continue
        regression_pct = ((current_median - baseline_median) / baseline_median) * 100.0
        regressions.append(
            f"{name}: median {current_median:.4f}s exceeds baseline "
            f"{baseline_median:.4f}s by {regression_pct:.2f}% "
            f"(allowed {max_regression_pct:.2f}%)"
        )
    return regressions


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Deterministic Docker-oriented benchmark for CodeClone CLI "
            "(cold/warm cache, report, and startup scenarios)."
        )
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=Path(os.environ.get("CODECLONE_BENCH_ROOT", "/opt/codeclone")),
        help="Analysis target directory inside container",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            os.environ.get(
                "CODECLONE_BENCH_OUTPUT",
                "/bench-out/codeclone-benchmark.json",
            )
        ),
        help="Output JSON path",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=int(os.environ.get("CODECLONE_BENCH_RUNS", "12")),
        help="Measured runs per scenario",
    )
    parser.add_argument(
        "--warmups",
        type=int,
        default=int(os.environ.get("CODECLONE_BENCH_WARMUPS", "3")),
        help="Warmup runs per scenario",
    )
    parser.add_argument(
        "--scenario-profile",
        choices=("smoke", "extended", "diagnostic"),
        default=os.environ.get("CODECLONE_BENCH_PROFILE", "smoke"),
        help=(
            "Scenario set: smoke keeps the historical core set; extended adds "
            "report-format scenarios with per-scenario caps; diagnostic also "
            "adds a CI-gate timing scenario that may exit non-zero."
        ),
    )
    parser.add_argument(
        "--startup-runs",
        type=int,
        default=int(os.environ.get("CODECLONE_BENCH_STARTUP_RUNS", "3")),
        help="Measured runs per startup/import probe",
    )
    parser.add_argument(
        "--no-startup-probes",
        action="store_true",
        help="Skip Python/import startup probes.",
    )
    parser.add_argument(
        "--tmp-dir",
        type=Path,
        default=Path("/tmp/codeclone-benchmark"),
        help="Temporary working directory",
    )
    parser.add_argument(
        "--python-executable",
        default=sys.executable,
        help="Python executable used to invoke codeclone CLI",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help="Existing benchmark JSON used for per-scenario median regression checks.",
    )
    parser.add_argument(
        "--max-regression-pct",
        type=float,
        default=5.0,
        help="Allowed per-scenario median slowdown versus --baseline.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.runs <= 0:
        raise SystemExit("--runs must be > 0")
    if args.warmups < 0:
        raise SystemExit("--warmups must be >= 0")
    if args.startup_runs <= 0:
        raise SystemExit("--startup-runs must be > 0")
    if args.max_regression_pct < 0:
        raise SystemExit("--max-regression-pct must be >= 0")
    target = args.target.resolve()
    if not target.exists():
        raise SystemExit(f"target does not exist: {target}")
    if not target.is_dir():
        raise SystemExit(f"target is not a directory: {target}")

    workspace = args.tmp_dir.resolve()
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True, exist_ok=True)

    scenario_profile = str(args.scenario_profile)
    if scenario_profile not in {"smoke", "extended", "diagnostic"}:
        raise SystemExit(f"unknown scenario profile: {scenario_profile}")
    scenarios = _scenario_profile(cast(BenchmarkProfile, scenario_profile))
    scenario_results = [
        _scenario_result(
            scenario=scenario,
            target=target,
            python_executable=args.python_executable,
            workspace=workspace,
            warmups=args.warmups,
            runs=args.runs,
        )
        for scenario in scenarios
    ]
    startup_probe_results = (
        [
            _probe_result(
                probe=probe,
                python_executable=args.python_executable,
                runs=args.startup_runs,
            )
            for probe in _startup_probes()
        ]
        if not args.no_startup_probes
        else []
    )

    comparisons = _comparison_metrics(scenario_results)

    payload = {
        "benchmark_schema_version": BENCHMARK_SCHEMA_VERSION,
        "tool": {
            "name": "codeclone",
            "version": codeclone_version,
            "python_tag": current_python_tag(),
        },
        "config": {
            "target": str(target),
            "runs": args.runs,
            "warmups": args.warmups,
            "scenario_profile": scenario_profile,
            "startup_runs": args.startup_runs,
            "startup_probes": not args.no_startup_probes,
            "python_executable": args.python_executable,
        },
        "environment": _environment(),
        "startup_probes": startup_probe_results,
        "scenarios": scenario_results,
        "comparisons": comparisons,
        "generated_at_utc": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
    }

    regressions: list[str] = []
    baseline_path = args.baseline.resolve() if args.baseline is not None else None
    if baseline_path is not None:
        baseline_payload = _load_benchmark_payload(baseline_path)
        regressions = _timing_regressions(
            current_payload=payload,
            baseline_payload=baseline_payload,
            max_regression_pct=args.max_regression_pct,
        )
        payload["baseline_comparison"] = {
            "baseline_path": str(baseline_path),
            "max_regression_pct": args.max_regression_pct,
            "status": "regression" if regressions else "ok",
            "regressions": regressions,
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp_output = args.output.with_suffix(args.output.suffix + ".tmp")
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    tmp_output.write_text(rendered, encoding="utf-8")
    tmp_output.replace(args.output)

    print("CodeClone Docker benchmark")
    print(f"target={target}")
    print(
        f"profile={scenario_profile} runs={args.runs} "
        f"warmups={args.warmups} startup_runs={args.startup_runs}"
    )
    if startup_probe_results:
        print("startup probes:")
        for probe in startup_probe_results:
            name = str(probe["name"])
            stats = probe["stats_seconds"]
            cpu_stats = probe["child_cpu_stats_seconds"]
            assert isinstance(stats, dict)
            assert isinstance(cpu_stats, dict)
            print(
                f"- {name:22s} median={_as_float(stats['median']):.4f}s "
                f"first={_as_float(probe['first_seconds']):.4f}s "
                f"cpu={_as_float(cpu_stats['median']):.4f}s"
            )
    for scenario in scenario_results:
        name = str(scenario["name"])
        stats = scenario["stats_seconds"]
        cpu_stats = scenario["child_cpu_stats_seconds"]
        inventory = scenario["inventory_sample"]
        exit_counts = scenario["exit_code_counts"]
        assert isinstance(stats, dict)
        assert isinstance(cpu_stats, dict)
        assert isinstance(inventory, dict)
        assert isinstance(exit_counts, dict)
        median_s = float(stats["median"])
        p95_s = float(stats["p95"])
        stdev_s = float(stats["stdev"])
        cpu_median_s = float(cpu_stats["median"])
        print(
            f"- {name:20s} median={median_s:.4f}s "
            f"p95={p95_s:.4f}s stdev={stdev_s:.4f}s "
            f"cpu={cpu_median_s:.4f}s "
            f"files={inventory.get('analyzed', 0)}/{inventory.get('cached', 0)} "
            f"artifacts={_as_float(scenario['artifact_total_kib_sample']):.1f}KiB "
            f"exit={exit_counts} "
            f"digest={scenario['digest']}"
        )
    _print_bulleted_lines(
        "ratios:",
        [f"{name}={value:.3f}x" for name, value in sorted(comparisons.items())],
    )
    if baseline_path is not None:
        print(f"baseline={baseline_path}")
        print(f"max_regression_pct={args.max_regression_pct:.2f}")
        if regressions:
            _print_bulleted_lines("regressions:", regressions)
        else:
            print("baseline_status=ok")
    print(f"output={args.output}")
    return 1 if regressions else 0


if __name__ == "__main__":
    raise SystemExit(main())
