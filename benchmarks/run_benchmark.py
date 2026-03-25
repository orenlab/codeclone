#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean, median, pstdev
from typing import Literal

from codeclone import __version__ as codeclone_version
from codeclone.baseline import current_python_tag

BENCHMARK_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class Scenario:
    name: str
    mode: Literal["cold", "warm"]
    extra_args: tuple[str, ...]


@dataclass(frozen=True)
class RunMeasurement:
    elapsed_seconds: float
    digest: str
    files_found: int
    files_analyzed: int
    files_cached: int
    files_skipped: int


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
) -> RunMeasurement:
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = "0"
    env["LC_ALL"] = "C.UTF-8"
    env["LANG"] = "C.UTF-8"
    env["TZ"] = "UTC"

    cmd = [
        python_executable,
        "-m",
        "codeclone.cli",
        str(target),
        "--json",
        str(report_path),
        "--cache-path",
        str(cache_path),
        "--no-progress",
        "--quiet",
        *extra_args,
    ]

    start = time.perf_counter()
    completed = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    elapsed_seconds = time.perf_counter() - start
    if completed.returncode != 0:
        stderr_tail = "\n".join(completed.stderr.splitlines()[-20:])
        stdout_tail = "\n".join(completed.stdout.splitlines()[-20:])
        raise RuntimeError(
            "benchmark command failed with exit "
            f"{completed.returncode}\nSTDOUT:\n{stdout_tail}\nSTDERR:\n{stderr_tail}"
        )

    digest, files = _read_report(report_path)
    return RunMeasurement(
        elapsed_seconds=elapsed_seconds,
        digest=digest,
        files_found=files["found"],
        files_analyzed=files["analyzed"],
        files_cached=files["cached"],
        files_skipped=files["skipped"],
    )


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

    warm_cache_path = scenario_dir / "shared-cache.json"
    cold_cache_path = scenario_dir / "cold-cache.json"

    if scenario.mode == "warm":
        _run_cli_once(
            target=target,
            python_executable=python_executable,
            cache_path=warm_cache_path,
            report_path=scenario_dir / "seed-report.json",
            extra_args=scenario.extra_args,
        )

    for idx in range(warmups):
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
        )

    measurements: list[RunMeasurement] = []
    for idx in range(runs):
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
        )
        measurements.append(measurement)

    digests = sorted({m.digest for m in measurements})
    deterministic = len(digests) == 1
    if not deterministic:
        raise RuntimeError(
            "non-deterministic report digest detected "
            f"in scenario {scenario.name}: {digests}"
        )

    timings = [m.elapsed_seconds for m in measurements]
    sample = measurements[0]
    return {
        "name": scenario.name,
        "mode": scenario.mode,
        "extra_args": list(scenario.extra_args),
        "warmups": warmups,
        "runs": runs,
        "deterministic": deterministic,
        "digest": digests[0],
        "timings_seconds": timings,
        "stats_seconds": _stats(timings),
        "inventory_sample": {
            "found": sample.files_found,
            "analyzed": sample.files_analyzed,
            "cached": sample.files_cached,
            "skipped": sample.files_skipped,
        },
    }


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

    comparisons: dict[str, float] = {}
    if cold_full and warm_full:
        comparisons["warm_full_speedup_vs_cold_full"] = cold_full / warm_full
    if warm_full and warm_clones:
        comparisons["warm_clones_only_speedup_vs_warm_full"] = warm_full / warm_clones
    return comparisons


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Deterministic Docker-oriented benchmark for CodeClone CLI "
            "(cold/warm cache scenarios)."
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
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.runs <= 0:
        raise SystemExit("--runs must be > 0")
    if args.warmups < 0:
        raise SystemExit("--warmups must be >= 0")
    target = args.target.resolve()
    if not target.exists():
        raise SystemExit(f"target does not exist: {target}")
    if not target.is_dir():
        raise SystemExit(f"target is not a directory: {target}")

    workspace = args.tmp_dir.resolve()
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True, exist_ok=True)

    scenarios = [
        Scenario(name="cold_full", mode="cold", extra_args=()),
        Scenario(name="warm_full", mode="warm", extra_args=()),
        Scenario(name="warm_clones_only", mode="warm", extra_args=("--skip-metrics",)),
    ]
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
            "python_executable": args.python_executable,
        },
        "environment": _environment(),
        "scenarios": scenario_results,
        "comparisons": comparisons,
        "generated_at_utc": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp_output = args.output.with_suffix(args.output.suffix + ".tmp")
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    tmp_output.write_text(rendered, encoding="utf-8")
    tmp_output.replace(args.output)

    print("CodeClone Docker benchmark")
    print(f"target={target}")
    print(f"runs={args.runs} warmups={args.warmups}")
    for scenario in scenario_results:
        name = str(scenario["name"])
        stats = scenario["stats_seconds"]
        assert isinstance(stats, dict)
        median_s = float(stats["median"])
        p95_s = float(stats["p95"])
        stdev_s = float(stats["stdev"])
        print(
            f"- {name:16s} median={median_s:.4f}s "
            f"p95={p95_s:.4f}s stdev={stdev_s:.4f}s "
            f"digest={scenario['digest']}"
        )
    if comparisons:
        print("ratios:")
        for name, value in sorted(comparisons.items()):
            print(f"- {name}={value:.3f}x")
    print(f"output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
