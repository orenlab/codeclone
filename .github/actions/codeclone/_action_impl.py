# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

COMMENT_MARKER = "<!-- codeclone-report -->"


@dataclass(frozen=True, slots=True)
class ActionInputs:
    path: str
    json_path: str
    sarif: bool
    sarif_path: str
    fail_on_new: bool
    fail_on_new_metrics: bool
    fail_threshold: int | None
    fail_complexity: int | None
    fail_coupling: int | None
    fail_cohesion: int | None
    fail_cycles: bool
    fail_dead_code: bool
    fail_health: int | None
    baseline_path: str
    metrics_baseline_path: str
    extra_args: str
    no_progress: bool


@dataclass(frozen=True, slots=True)
class RunResult:
    exit_code: int
    json_path: str
    json_exists: bool
    sarif_path: str
    sarif_exists: bool


def parse_bool(value: str) -> bool:
    return value.strip().lower() == "true"


def parse_optional_int(value: str) -> int | None:
    normalized = value.strip()
    if normalized in {"", "-1"}:
        return None
    return int(normalized)


def build_codeclone_args(inputs: ActionInputs) -> list[str]:
    args = [inputs.path, "--json", inputs.json_path]
    if inputs.sarif:
        args.extend(["--sarif", inputs.sarif_path])
    if inputs.no_progress:
        args.append("--no-progress")
    if inputs.fail_on_new:
        args.append("--fail-on-new")
    if inputs.fail_on_new_metrics:
        args.append("--fail-on-new-metrics")
    if inputs.fail_threshold is not None:
        args.extend(["--fail-threshold", str(inputs.fail_threshold)])
    if inputs.fail_complexity is not None:
        args.extend(["--fail-complexity", str(inputs.fail_complexity)])
    if inputs.fail_coupling is not None:
        args.extend(["--fail-coupling", str(inputs.fail_coupling)])
    if inputs.fail_cohesion is not None:
        args.extend(["--fail-cohesion", str(inputs.fail_cohesion)])
    if inputs.fail_cycles:
        args.append("--fail-cycles")
    if inputs.fail_dead_code:
        args.append("--fail-dead-code")
    if inputs.fail_health is not None:
        args.extend(["--fail-health", str(inputs.fail_health)])
    if inputs.baseline_path.strip():
        args.extend(["--baseline", inputs.baseline_path])
    if inputs.metrics_baseline_path.strip():
        args.extend(["--metrics-baseline", inputs.metrics_baseline_path])
    if inputs.extra_args.strip():
        args.extend(shlex.split(inputs.extra_args))
    return args


def ensure_parent_dir(path_text: str) -> None:
    Path(path_text).parent.mkdir(parents=True, exist_ok=True)


def write_outputs(path: str, values: dict[str, str]) -> None:
    with open(path, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def run_codeclone(inputs: ActionInputs) -> RunResult:
    ensure_parent_dir(inputs.json_path)
    if inputs.sarif:
        ensure_parent_dir(inputs.sarif_path)
    argv = ["codeclone", *build_codeclone_args(inputs)]
    try:
        completed = subprocess.run(argv, check=False, timeout=600)
    except subprocess.TimeoutExpired:
        print("::error::CodeClone analysis timed out after 10 minutes")
        return RunResult(
            exit_code=5,
            json_path=inputs.json_path,
            json_exists=Path(inputs.json_path).exists(),
            sarif_path=inputs.sarif_path,
            sarif_exists=inputs.sarif and Path(inputs.sarif_path).exists(),
        )
    return RunResult(
        exit_code=completed.returncode,
        json_path=inputs.json_path,
        json_exists=Path(inputs.json_path).exists(),
        sarif_path=inputs.sarif_path,
        sarif_exists=inputs.sarif and Path(inputs.sarif_path).exists(),
    )


def _mapping(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _int(value: object, default: int = 0) -> int:
    return value if isinstance(value, int) else default


def _str(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def render_pr_comment(report: dict[str, object], *, exit_code: int) -> str:
    meta = _mapping(report.get("meta"))
    findings = _mapping(report.get("findings"))
    findings_summary = _mapping(findings.get("summary"))
    clone_summary = _mapping(findings_summary.get("clones"))
    families = _mapping(findings_summary.get("families"))
    metrics = _mapping(report.get("metrics"))
    metrics_summary = _mapping(metrics.get("summary"))
    health = _mapping(metrics_summary.get("health"))
    baseline = _mapping(meta.get("baseline"))
    cache = _mapping(meta.get("cache"))

    health_score = _int(health.get("score"), default=-1)
    health_grade = _str(health.get("grade"), default="?")
    baseline_status = _str(baseline.get("status"), default="unknown")
    cache_used = bool(cache.get("used"))
    codeclone_version = _str(meta.get("codeclone_version"), default="?")

    status_icon = "white_check_mark"
    status_label = "Passed"
    if exit_code == 3:
        status_icon = "x"
        status_label = "Failed (gating)"
    elif exit_code != 0:
        status_icon = "warning"
        status_label = "Error"

    lines = [
        COMMENT_MARKER,
        "## :microscope: CodeClone Report",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Health | **{health_score}/100 ({health_grade})** |",
        f"| Status | :{status_icon}: {status_label} |",
        f"| Baseline | `{baseline_status}` |",
        f"| Cache | `{'used' if cache_used else 'not used'}` |",
        f"| Version | `{codeclone_version}` |",
        "",
        "### Findings",
        "```text",
        _clone_summary_line(clone_summary=clone_summary, families=families),
        f"Structural: {_int(families.get('structural'))}",
        f"Dead code: {_int(families.get('dead_code'))}",
        f"Design: {_int(families.get('design'))}",
        "```",
        "",
        "<sub>:robot: Generated by "
        '<a href="https://github.com/orenlab/codeclone">CodeClone</a></sub>',
    ]
    return "\n".join(lines)


def write_step_summary(path: str, body: str) -> None:
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(body)
        handle.write("\n")


def load_report(path: str) -> dict[str, object]:
    with open(path, encoding="utf-8") as handle:
        loaded = json.load(handle)
    return loaded if isinstance(loaded, dict) else {}


def build_inputs_from_env(env: dict[str, str]) -> ActionInputs:
    return ActionInputs(
        path=env["INPUT_PATH"],
        json_path=env["INPUT_JSON_PATH"],
        sarif=parse_bool(env["INPUT_SARIF"]),
        sarif_path=env["INPUT_SARIF_PATH"],
        fail_on_new=parse_bool(env["INPUT_FAIL_ON_NEW"]),
        fail_on_new_metrics=parse_bool(env["INPUT_FAIL_ON_NEW_METRICS"]),
        fail_threshold=parse_optional_int(env["INPUT_FAIL_THRESHOLD"]),
        fail_complexity=parse_optional_int(env["INPUT_FAIL_COMPLEXITY"]),
        fail_coupling=parse_optional_int(env["INPUT_FAIL_COUPLING"]),
        fail_cohesion=parse_optional_int(env["INPUT_FAIL_COHESION"]),
        fail_cycles=parse_bool(env["INPUT_FAIL_CYCLES"]),
        fail_dead_code=parse_bool(env["INPUT_FAIL_DEAD_CODE"]),
        fail_health=parse_optional_int(env["INPUT_FAIL_HEALTH"]),
        baseline_path=env["INPUT_BASELINE_PATH"],
        metrics_baseline_path=env["INPUT_METRICS_BASELINE_PATH"],
        extra_args=env["INPUT_EXTRA_ARGS"],
        no_progress=parse_bool(env["INPUT_NO_PROGRESS"]),
    )


def _clone_summary_line(
    *,
    clone_summary: dict[str, object],
    families: dict[str, object],
) -> str:
    return (
        f"Clones: {_int(families.get('clones'))} "
        f"({_int(clone_summary.get('new'))} new, "
        f"{_int(clone_summary.get('known'))} known)"
    )
