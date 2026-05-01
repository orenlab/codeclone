# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""GitHub Action helpers for running CodeClone and rendering PR feedback.

This module is intentionally small and dependency-free. It builds the CodeClone
CLI invocation from action inputs, executes the analyzer, writes GitHub Actions
outputs, and renders a compact Markdown review comment from the canonical JSON
report.

Public functions and dataclasses are used by the action entrypoint and should
remain stable.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

COMMENT_MARKER = "<!-- codeclone-report -->"
DEFAULT_CODECLONE_PACKAGE_VERSION = "2.0.0"


@dataclass(frozen=True, slots=True)
class ActionInputs:
    """Normalized GitHub Action inputs used to build a CodeClone invocation."""

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
    """Result of a CodeClone CLI execution inside the action runtime."""

    exit_code: int
    json_path: str
    json_exists: bool
    sarif_path: str
    sarif_exists: bool


@dataclass(frozen=True, slots=True)
class InstallTarget:
    """Resolved package requirement used by the action installer."""

    requirement: str
    source: Literal["repo", "pypi-version", "pypi-default"]


@dataclass(frozen=True, slots=True)
class _PrCommentContext:
    """Typed internal view over canonical report fields used by PR rendering."""

    clone_summary: dict[str, object]
    families: dict[str, object]
    complexity: dict[str, object]
    coupling: dict[str, object]
    cohesion: dict[str, object]
    dependencies: dict[str, object]
    dead_code: dict[str, object]
    overloaded_modules: dict[str, object]
    coverage_join: dict[str, object]
    security_surfaces: dict[str, object]
    api_surface: dict[str, object]
    health_score: int
    health_grade: str
    baseline_status: str
    cache_label: str
    codeclone_version: str


def parse_bool(value: str) -> bool:
    """Parse GitHub Action boolean input values.

    GitHub Action inputs arrive as strings. CodeClone action booleans are true
    only when the normalized value is exactly ``"true"``.
    """

    return value.strip().lower() == "true"


def parse_optional_int(value: str) -> int | None:
    """Parse optional integer action input values.

    Empty strings and ``-1`` are treated as unset values because GitHub Action
    inputs do not have native nullable integer types.
    """

    normalized = value.strip()
    if normalized in {"", "-1"}:
        return None
    return int(normalized)


def build_codeclone_args(inputs: ActionInputs) -> list[str]:
    """Build CodeClone CLI arguments from normalized action inputs.

    The returned list intentionally excludes the executable name. Extra
    arguments are parsed with :mod:`shlex` so quoted values behave like shell
    arguments without invoking a shell.
    """

    args: list[str] = [inputs.path, "--json", inputs.json_path]

    for value, flag in _valued_codeclone_options(inputs):
        if value is not None:
            args.extend([flag, str(value)])

    for enabled, flag in _boolean_codeclone_flags(inputs):
        if enabled:
            args.append(flag)

    extra_args = inputs.extra_args.strip()
    if extra_args:
        args.extend(shlex.split(extra_args))

    return args


def ensure_parent_dir(path_text: str) -> None:
    """Create the parent directory for an output path when needed."""

    Path(path_text).parent.mkdir(parents=True, exist_ok=True)


def write_outputs(path: str, values: dict[str, str]) -> None:
    """Append GitHub Action output values to ``GITHUB_OUTPUT``."""

    with open(path, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


# codeclone: ignore[dead-code]
def resolve_install_target(
    *,
    action_path: str,
    workspace: str,
    package_version: str,
) -> InstallTarget:
    """Resolve whether the action should install CodeClone from repo or PyPI.

    When the action itself is executed from the same checkout as the workspace,
    installing from the repository keeps local action smoke tests honest.
    Otherwise the action installs either the explicitly requested PyPI version
    or the stable default package version.
    """

    action_root = Path(action_path).resolve().parents[2]
    workspace_root = Path(workspace).resolve()

    if action_root == workspace_root:
        return InstallTarget(requirement=str(action_root), source="repo")

    normalized_version = package_version.strip()
    if normalized_version:
        return InstallTarget(
            requirement=f"codeclone=={normalized_version}",
            source="pypi-version",
        )

    return InstallTarget(
        requirement=f"codeclone=={DEFAULT_CODECLONE_PACKAGE_VERSION}",
        source="pypi-default",
    )


def run_codeclone(inputs: ActionInputs) -> RunResult:
    """Run CodeClone and return output artifact status.

    The action treats analyzer timeouts as internal execution errors and maps
    them to CodeClone's internal-error exit code ``5``.
    """

    ensure_parent_dir(inputs.json_path)
    if inputs.sarif:
        ensure_parent_dir(inputs.sarif_path)

    argv = ["codeclone", *build_codeclone_args(inputs)]

    try:
        completed = subprocess.run(argv, check=False, timeout=600, shell=False)
    except subprocess.TimeoutExpired:
        print("::error::CodeClone analysis timed out after 10 minutes")
        return _run_result_from_paths(exit_code=5, inputs=inputs)

    return _run_result_from_paths(exit_code=completed.returncode, inputs=inputs)


def render_pr_comment(report: dict[str, object], *, exit_code: int) -> str:
    """Render a compact Markdown PR review comment from a canonical report."""

    ctx = _build_pr_comment_context(report)
    rows = _build_pr_comment_rows(ctx)
    focus = _review_focus(
        exit_code=exit_code,
        clone_summary=ctx.clone_summary,
        dependencies=ctx.dependencies,
        coverage_join=ctx.coverage_join,
        security_surfaces=ctx.security_surfaces,
        overloaded_modules=ctx.overloaded_modules,
    )

    status_icon, status_label = _status_label(exit_code)

    lines = [
        COMMENT_MARKER,
        "## CodeClone Review",
        "",
        (
            f"**{status_icon} {status_label}** · "
            f"Health **{ctx.health_score}/100 ({ctx.health_grade})** · "
            f"Baseline `{ctx.baseline_status}` · "
            f"Cache `{ctx.cache_label}` · "
            f"CodeClone `{ctx.codeclone_version}`"
        ),
        "",
        "### Review snapshot",
        "| Area | Signal | Review note |",
        "|------|--------|-------------|",
        *[
            f"| {_table_cell(area)} | {_table_cell(signal)} | {_table_cell(note)} |"
            for area, signal, note in rows
        ],
        "",
        "### Review focus",
        *[f"- {item}" for item in focus],
        "",
        "<sub>Security Surfaces are report-only capability inventory, "
        "not vulnerability claims. Generated by "
        '<a href="https://github.com/orenlab/codeclone">CodeClone</a></sub>',
    ]
    return "\n".join(lines)


def write_step_summary(path: str, body: str) -> None:
    """Append Markdown content to ``GITHUB_STEP_SUMMARY``."""

    with open(path, "a", encoding="utf-8") as handle:
        handle.write(body)
        handle.write("\n")


def load_report(path: str) -> dict[str, object]:
    """Load a CodeClone JSON report and return an empty mapping on bad shape."""

    with open(path, encoding="utf-8") as handle:
        loaded = json.load(handle)
    return loaded if isinstance(loaded, dict) else {}


def build_inputs_from_env(env: dict[str, str]) -> ActionInputs:
    """Build normalized action inputs from the GitHub Actions environment."""

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


def _valued_codeclone_options(
    inputs: ActionInputs,
) -> tuple[tuple[object | None, str], ...]:
    """Return valued CLI options in deterministic output order."""

    return (
        (inputs.sarif_path if inputs.sarif else None, "--sarif"),
        (inputs.fail_threshold, "--fail-threshold"),
        (inputs.fail_complexity, "--fail-complexity"),
        (inputs.fail_coupling, "--fail-coupling"),
        (inputs.fail_cohesion, "--fail-cohesion"),
        (inputs.fail_health, "--fail-health"),
        (inputs.baseline_path.strip() or None, "--baseline"),
        (inputs.metrics_baseline_path.strip() or None, "--metrics-baseline"),
    )


def _boolean_codeclone_flags(inputs: ActionInputs) -> tuple[tuple[bool, str], ...]:
    """Return boolean CLI flags in deterministic output order."""

    return (
        (inputs.no_progress, "--no-progress"),
        (inputs.fail_on_new, "--fail-on-new"),
        (inputs.fail_on_new_metrics, "--fail-on-new-metrics"),
        (inputs.fail_cycles, "--fail-cycles"),
        (inputs.fail_dead_code, "--fail-dead-code"),
    )


def _run_result_from_paths(*, exit_code: int, inputs: ActionInputs) -> RunResult:
    """Build a run result from expected output paths."""

    json_path = Path(inputs.json_path)
    sarif_path = Path(inputs.sarif_path)

    return RunResult(
        exit_code=exit_code,
        json_path=inputs.json_path,
        json_exists=json_path.exists(),
        sarif_path=inputs.sarif_path,
        sarif_exists=inputs.sarif and sarif_path.exists(),
    )


def _mapping(value: object) -> dict[str, object]:
    """Return ``value`` when it is a JSON object, otherwise an empty mapping."""

    return value if isinstance(value, dict) else {}


def _int(value: object, default: int = 0) -> int:
    """Return an integer JSON value or a default."""

    return value if isinstance(value, int) else default


def _str(value: object, default: str = "") -> str:
    """Return a string JSON value or a default."""

    return value if isinstance(value, str) else default


def _float(value: object, default: float = 0.0) -> float:
    """Return a numeric JSON value as float or a default."""

    if isinstance(value, int | float):
        return float(value)
    return default


def _one_decimal(value: object) -> str:
    """Format a numeric JSON value with one decimal place."""

    return f"{_float(value):.1f}"


def _percent_from_permille(value: object) -> str:
    """Format a permille JSON value as a percentage string."""

    return f"{_float(value) / 10.0:.1f}%"


def _table_cell(value: object) -> str:
    """Escape Markdown table cell separators and newlines."""

    text = str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _status_label(exit_code: int) -> tuple[str, str]:
    """Map CodeClone exit codes to PR comment status labels."""

    if exit_code == 0:
        return ":white_check_mark:", "Passed"
    if exit_code == 3:
        return ":x:", "Failed (gating)"
    if exit_code == 2:
        return ":warning:", "Contract error"
    return ":warning:", "Error"


def _build_pr_comment_context(report: dict[str, object]) -> _PrCommentContext:
    """Extract the report fields needed for PR comment rendering."""

    meta = _mapping(report.get("meta"))
    findings = _mapping(report.get("findings"))
    findings_summary = _mapping(findings.get("summary"))
    metrics = _mapping(report.get("metrics"))
    metrics_summary = _mapping(metrics.get("summary"))

    health = _mapping(metrics_summary.get("health"))
    baseline = _mapping(meta.get("baseline"))
    cache = _mapping(meta.get("cache"))

    return _PrCommentContext(
        clone_summary=_mapping(findings_summary.get("clones")),
        families=_mapping(findings_summary.get("families")),
        complexity=_mapping(metrics_summary.get("complexity")),
        coupling=_mapping(metrics_summary.get("coupling")),
        cohesion=_mapping(metrics_summary.get("cohesion")),
        dependencies=_mapping(metrics_summary.get("dependencies")),
        dead_code=_mapping(metrics_summary.get("dead_code")),
        overloaded_modules=_mapping(metrics_summary.get("overloaded_modules")),
        coverage_join=_mapping(metrics_summary.get("coverage_join")),
        security_surfaces=_mapping(metrics_summary.get("security_surfaces")),
        api_surface=_mapping(metrics_summary.get("api_surface")),
        health_score=_int(health.get("score"), default=-1),
        health_grade=_str(health.get("grade"), default="?"),
        baseline_status=_str(baseline.get("status"), default="unknown"),
        cache_label="hit" if bool(cache.get("used")) else "miss",
        codeclone_version=_str(meta.get("codeclone_version"), default="?"),
    )


def _build_pr_comment_rows(ctx: _PrCommentContext) -> list[tuple[str, str, str]]:
    """Build the fixed PR comment review snapshot rows."""

    coverage_signal, coverage_note = _format_coverage_join_row(ctx.coverage_join)
    security_signal, security_note = _format_security_surfaces_row(
        ctx.security_surfaces
    )
    api_signal, api_note = _format_api_surface_row(ctx.api_surface)

    return [
        (
            "Clones",
            _clone_signal_line(
                clone_summary=ctx.clone_summary,
                families=ctx.families,
            ),
            (
                "review new groups before merge"
                if _int(ctx.clone_summary.get("new"))
                else "no new clone debt reported"
            ),
        ),
        (
            "Quality",
            _format_quality_signal(
                complexity=ctx.complexity,
                coupling=ctx.coupling,
                cohesion=ctx.cohesion,
                overloaded_modules=ctx.overloaded_modules,
            ),
            "structural metric snapshot",
        ),
        (
            "Dependencies",
            _format_dependencies_signal(ctx.dependencies),
            (
                "acyclic"
                if _int(ctx.dependencies.get("cycles")) == 0
                else "cycle review needed"
            ),
        ),
        ("Coverage Join", coverage_signal, coverage_note),
        ("Security Surfaces", security_signal, security_note),
        ("API Surface", api_signal, api_note),
        (
            "Dead code",
            _format_dead_code_signal(ctx.dead_code),
            (
                "clean"
                if _int(ctx.dead_code.get("high_confidence")) == 0
                else "review candidates"
            ),
        ),
    ]


def _format_quality_signal(
    *,
    complexity: dict[str, object],
    coupling: dict[str, object],
    cohesion: dict[str, object],
    overloaded_modules: dict[str, object],
) -> str:
    """Format the quality row signal."""

    return (
        f"CC max {_int(complexity.get('max'))}, "
        f"CBO max {_int(coupling.get('max'))}, "
        f"LCOM4 max {_int(cohesion.get('max'))}, "
        f"overloaded {_int(overloaded_modules.get('candidates'))}"
    )


def _format_dependencies_signal(dependencies: dict[str, object]) -> str:
    """Format the dependency profile row signal."""

    return (
        f"avg {_one_decimal(dependencies.get('avg_depth'))}, "
        f"p95 {_int(dependencies.get('p95_depth'))}, "
        f"max {_int(dependencies.get('max_depth'))}, "
        f"cycles {_int(dependencies.get('cycles'))}"
    )


def _format_coverage_join_row(coverage_join: dict[str, object]) -> tuple[str, str]:
    """Format the Coverage Join review row."""

    if not coverage_join:
        return "not joined", "no coverage.xml facts in this report"

    coverage_status = _str(coverage_join.get("status"), default="")
    signal = (
        f"{_percent_from_permille(coverage_join.get('overall_permille'))} overall, "
        f"{_int(coverage_join.get('coverage_hotspots'))} hotspots, "
        f"{_int(coverage_join.get('scope_gap_hotspots'))} scope gaps"
    )
    note = (
        "joined with coverage.xml"
        if coverage_status == "ok"
        else f"not joined: {_str(coverage_join.get('invalid_reason'), 'unknown')}"
    )
    return signal, note


def _format_security_surfaces_row(
    security_surfaces: dict[str, object],
) -> tuple[str, str]:
    """Format the Security Surfaces review row."""

    security_items = _int(security_surfaces.get("items"))
    signal = (
        f"{security_items} surfaces, "
        f"{_int(security_surfaces.get('category_count'))} categories, "
        f"{_int(security_surfaces.get('production'))} production"
    )
    note = (
        "report-only boundary inventory"
        if security_items
        else "no security surfaces reported"
    )
    return signal, note


def _format_api_surface_row(api_surface: dict[str, object]) -> tuple[str, str]:
    """Format the API Surface review row."""

    api_enabled = bool(api_surface.get("enabled"))
    signal = (
        f"{_int(api_surface.get('public_symbols'))} symbols, "
        f"{_int(api_surface.get('modules'))} modules"
        if api_enabled
        else "disabled"
    )
    note = (
        f"{_int(api_surface.get('breaking'))} breaking, "
        f"{_int(api_surface.get('added'))} added"
        if api_enabled
        else "not part of this run"
    )
    return signal, note


def _format_dead_code_signal(dead_code: dict[str, object]) -> str:
    """Format the dead-code row signal."""

    return (
        f"{_int(dead_code.get('high_confidence'))} high-confidence, "
        f"{_int(dead_code.get('suppressed'))} suppressed"
    )


def _review_focus(
    *,
    exit_code: int,
    clone_summary: dict[str, object],
    dependencies: dict[str, object],
    coverage_join: dict[str, object],
    security_surfaces: dict[str, object],
    overloaded_modules: dict[str, object],
) -> list[str]:
    """Build focused follow-up suggestions for the PR comment."""

    items: list[str] = []

    if exit_code == 3:
        items.append("CI gates failed; start with rows marked as gating-sensitive.")
    elif exit_code == 2:
        items.append(
            "Contract error; check baseline/config trust before reviewing metrics."
        )

    new_clones = _int(clone_summary.get("new"))
    if new_clones:
        items.append(f"Review {new_clones} new clone group(s) before merge.")

    cycles = _int(dependencies.get("cycles"))
    if cycles:
        items.append(
            f"Inspect {cycles} dependency cycle(s); cycles are hard structural risk."
        )

    coverage_hotspots = _int(coverage_join.get("coverage_hotspots"))
    scope_gaps = _int(coverage_join.get("scope_gap_hotspots"))
    if coverage_hotspots or scope_gaps:
        items.append(
            f"Use Coverage Join for {coverage_hotspots} coverage hotspot(s) "
            f"and {scope_gaps} scope gap(s)."
        )

    production_surfaces = _int(security_surfaces.get("production"))
    if production_surfaces:
        items.append(
            f"Treat {production_surfaces} production security surface(s) as "
            "review-first boundary code when touched."
        )

    overloaded = _int(overloaded_modules.get("candidates"))
    if overloaded:
        items.append(
            f"Review {overloaded} overloaded module candidate(s) "
            "when they intersect this PR."
        )

    if not items:
        items.append("No focused review pressure reported by the canonical summary.")

    return items


def _clone_signal_line(
    *,
    clone_summary: dict[str, object],
    families: dict[str, object],
) -> str:
    """Format the clone summary row signal."""

    return (
        f"{_int(families.get('clones'))} total, "
        f"{_int(clone_summary.get('new'))} new, "
        f"{_int(clone_summary.get('known'))} known"
    )
