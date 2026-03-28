# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import argparse
import sys
from typing import NoReturn

from . import ui_messages as ui
from .contracts import (
    DEFAULT_COHESION_THRESHOLD,
    DEFAULT_COMPLEXITY_THRESHOLD,
    DEFAULT_COUPLING_THRESHOLD,
    DEFAULT_HEALTH_THRESHOLD,
    ExitCode,
    cli_help_epilog,
)

DEFAULT_ROOT = "."
DEFAULT_MIN_LOC = 10
DEFAULT_MIN_STMT = 6
DEFAULT_BLOCK_MIN_LOC = 20
DEFAULT_BLOCK_MIN_STMT = 8
DEFAULT_SEGMENT_MIN_LOC = 20
DEFAULT_SEGMENT_MIN_STMT = 10
DEFAULT_PROCESSES = 4
DEFAULT_MAX_CACHE_SIZE_MB = 50
DEFAULT_MAX_BASELINE_SIZE_MB = 5

DEFAULT_BASELINE_PATH = "codeclone.baseline.json"
DEFAULT_HTML_REPORT_PATH = ".cache/codeclone/report.html"
DEFAULT_JSON_REPORT_PATH = ".cache/codeclone/report.json"
DEFAULT_MARKDOWN_REPORT_PATH = ".cache/codeclone/report.md"
DEFAULT_SARIF_REPORT_PATH = ".cache/codeclone/report.sarif"
DEFAULT_TEXT_REPORT_PATH = ".cache/codeclone/report.txt"


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(
            int(ExitCode.CONTRACT_ERROR),
            f"CONTRACT ERROR: {message}\n",
        )


class _HelpFormatter(argparse.RawTextHelpFormatter):
    """Product-oriented help formatter extension point."""


def _add_optional_path_argument(
    group: argparse._ArgumentGroup,
    *,
    flag: str,
    dest: str,
    help_text: str,
    default: str | None = None,
    const: str | None = None,
    metavar: str = "FILE",
) -> None:
    group.add_argument(
        flag,
        dest=dest,
        nargs="?",
        metavar=metavar,
        default=default,
        const=const,
        help=help_text,
    )


def _add_bool_optional_argument(
    group: argparse._ArgumentGroup,
    *,
    flag: str,
    help_text: str,
    default: bool = False,
) -> None:
    group.add_argument(
        flag,
        action=argparse.BooleanOptionalAction,
        default=default,
        help=help_text,
    )


def build_parser(version: str) -> _ArgumentParser:
    ap = _ArgumentParser(
        prog="codeclone",
        description="Structural code quality analysis for Python.",
        add_help=False,
        formatter_class=_HelpFormatter,
        epilog=cli_help_epilog(),
    )

    target_group = ap.add_argument_group("Target")
    target_group.add_argument(
        "root",
        nargs="?",
        default=DEFAULT_ROOT,
        help=ui.HELP_ROOT,
    )

    analysis_group = ap.add_argument_group("Analysis")
    analysis_group.add_argument(
        "--min-loc",
        type=int,
        default=DEFAULT_MIN_LOC,
        help=ui.HELP_MIN_LOC,
    )
    analysis_group.add_argument(
        "--min-stmt",
        type=int,
        default=DEFAULT_MIN_STMT,
        help=ui.HELP_MIN_STMT,
    )
    # Block/segment thresholds are advanced tuning: configurable via
    # pyproject.toml only (no CLI flags).  Defaults live on the namespace
    # so apply_pyproject_config_overrides can override them.
    ap.set_defaults(
        block_min_loc=DEFAULT_BLOCK_MIN_LOC,
        block_min_stmt=DEFAULT_BLOCK_MIN_STMT,
        segment_min_loc=DEFAULT_SEGMENT_MIN_LOC,
        segment_min_stmt=DEFAULT_SEGMENT_MIN_STMT,
    )
    analysis_group.add_argument(
        "--processes",
        type=int,
        default=DEFAULT_PROCESSES,
        help=ui.HELP_PROCESSES,
    )
    _add_bool_optional_argument(
        analysis_group,
        flag="--changed-only",
        help_text=ui.HELP_CHANGED_ONLY,
    )
    analysis_group.add_argument(
        "--diff-against",
        default=None,
        metavar="GIT_REF",
        help=ui.HELP_DIFF_AGAINST,
    )
    analysis_group.add_argument(
        "--paths-from-git-diff",
        default=None,
        metavar="GIT_REF",
        help=ui.HELP_PATHS_FROM_GIT_DIFF,
    )
    _add_optional_path_argument(
        analysis_group,
        flag="--cache-path",
        dest="cache_path",
        default=None,
        const=None,
        help_text=ui.HELP_CACHE_PATH,
    )
    _add_optional_path_argument(
        analysis_group,
        flag="--cache-dir",
        dest="cache_path",
        default=None,
        const=None,
        help_text=ui.HELP_CACHE_DIR_LEGACY,
    )
    analysis_group.add_argument(
        "--max-cache-size-mb",
        type=int,
        default=DEFAULT_MAX_CACHE_SIZE_MB,
        metavar="MB",
        help=ui.HELP_MAX_CACHE_SIZE_MB,
    )

    baselines_ci_group = ap.add_argument_group("Baselines and CI")
    _add_optional_path_argument(
        baselines_ci_group,
        flag="--baseline",
        dest="baseline",
        default=DEFAULT_BASELINE_PATH,
        const=DEFAULT_BASELINE_PATH,
        help_text=ui.HELP_BASELINE,
    )
    baselines_ci_group.add_argument(
        "--max-baseline-size-mb",
        type=int,
        default=DEFAULT_MAX_BASELINE_SIZE_MB,
        metavar="MB",
        help=ui.HELP_MAX_BASELINE_SIZE_MB,
    )
    _add_bool_optional_argument(
        baselines_ci_group,
        flag="--update-baseline",
        help_text=ui.HELP_UPDATE_BASELINE,
    )
    _add_optional_path_argument(
        baselines_ci_group,
        flag="--metrics-baseline",
        dest="metrics_baseline",
        default=DEFAULT_BASELINE_PATH,
        const=DEFAULT_BASELINE_PATH,
        help_text=ui.HELP_METRICS_BASELINE,
    )
    _add_bool_optional_argument(
        baselines_ci_group,
        flag="--update-metrics-baseline",
        help_text=ui.HELP_UPDATE_METRICS_BASELINE,
    )
    _add_bool_optional_argument(
        baselines_ci_group,
        flag="--ci",
        help_text=ui.HELP_CI,
    )

    quality_group = ap.add_argument_group("Quality gates")
    _add_bool_optional_argument(
        quality_group,
        flag="--fail-on-new",
        help_text=ui.HELP_FAIL_ON_NEW,
    )
    _add_bool_optional_argument(
        quality_group,
        flag="--fail-on-new-metrics",
        help_text=ui.HELP_FAIL_ON_NEW_METRICS,
    )
    quality_group.add_argument(
        "--fail-threshold",
        type=int,
        default=-1,
        metavar="MAX_CLONES",
        help=ui.HELP_FAIL_THRESHOLD,
    )
    quality_group.add_argument(
        "--fail-complexity",
        type=int,
        nargs="?",
        const=DEFAULT_COMPLEXITY_THRESHOLD,
        default=-1,
        metavar="CC_MAX",
        help=ui.HELP_FAIL_COMPLEXITY,
    )
    quality_group.add_argument(
        "--fail-coupling",
        type=int,
        nargs="?",
        const=DEFAULT_COUPLING_THRESHOLD,
        default=-1,
        metavar="CBO_MAX",
        help=ui.HELP_FAIL_COUPLING,
    )
    quality_group.add_argument(
        "--fail-cohesion",
        type=int,
        nargs="?",
        const=DEFAULT_COHESION_THRESHOLD,
        default=-1,
        metavar="LCOM4_MAX",
        help=ui.HELP_FAIL_COHESION,
    )
    _add_bool_optional_argument(
        quality_group,
        flag="--fail-cycles",
        help_text=ui.HELP_FAIL_CYCLES,
    )
    _add_bool_optional_argument(
        quality_group,
        flag="--fail-dead-code",
        help_text=ui.HELP_FAIL_DEAD_CODE,
    )
    quality_group.add_argument(
        "--fail-health",
        type=int,
        nargs="?",
        const=DEFAULT_HEALTH_THRESHOLD,
        default=-1,
        metavar="SCORE_MIN",
        help=ui.HELP_FAIL_HEALTH,
    )

    stages_group = ap.add_argument_group("Analysis stages")
    _add_bool_optional_argument(
        stages_group,
        flag="--skip-metrics",
        help_text=ui.HELP_SKIP_METRICS,
    )
    _add_bool_optional_argument(
        stages_group,
        flag="--skip-dead-code",
        help_text=ui.HELP_SKIP_DEAD_CODE,
    )
    _add_bool_optional_argument(
        stages_group,
        flag="--skip-dependencies",
        help_text=ui.HELP_SKIP_DEPENDENCIES,
    )

    reporting_group = ap.add_argument_group("Reporting")
    _add_optional_path_argument(
        reporting_group,
        flag="--html",
        dest="html_out",
        const=DEFAULT_HTML_REPORT_PATH,
        help_text=ui.HELP_HTML,
    )
    _add_optional_path_argument(
        reporting_group,
        flag="--json",
        dest="json_out",
        const=DEFAULT_JSON_REPORT_PATH,
        help_text=ui.HELP_JSON,
    )
    _add_optional_path_argument(
        reporting_group,
        flag="--md",
        dest="md_out",
        const=DEFAULT_MARKDOWN_REPORT_PATH,
        help_text=ui.HELP_MD,
    )
    _add_optional_path_argument(
        reporting_group,
        flag="--sarif",
        dest="sarif_out",
        const=DEFAULT_SARIF_REPORT_PATH,
        help_text=ui.HELP_SARIF,
    )
    _add_optional_path_argument(
        reporting_group,
        flag="--text",
        dest="text_out",
        const=DEFAULT_TEXT_REPORT_PATH,
        help_text=ui.HELP_TEXT,
    )
    _add_bool_optional_argument(
        reporting_group,
        flag="--timestamped-report-paths",
        help_text=ui.HELP_TIMESTAMPED_REPORT_PATHS,
    )

    ui_group = ap.add_argument_group("Output and UI")
    _add_bool_optional_argument(
        ui_group,
        flag="--open-html-report",
        help_text=ui.HELP_OPEN_HTML_REPORT,
    )
    ui_group.add_argument(
        "--no-progress",
        dest="no_progress",
        action="store_true",
        help=ui.HELP_NO_PROGRESS,
    )
    ui_group.add_argument(
        "--progress",
        dest="no_progress",
        action="store_false",
        help=ui.HELP_PROGRESS,
    )
    ui_group.add_argument(
        "--no-color",
        dest="no_color",
        action="store_true",
        help=ui.HELP_NO_COLOR,
    )
    ui_group.add_argument(
        "--color",
        dest="no_color",
        action="store_false",
        help=ui.HELP_COLOR,
    )
    ui_group.set_defaults(no_progress=False, no_color=False)
    _add_bool_optional_argument(
        ui_group,
        flag="--quiet",
        help_text=ui.HELP_QUIET,
    )
    _add_bool_optional_argument(
        ui_group,
        flag="--verbose",
        help_text=ui.HELP_VERBOSE,
    )
    _add_bool_optional_argument(
        ui_group,
        flag="--debug",
        help_text=ui.HELP_DEBUG,
    )

    general_group = ap.add_argument_group("General")
    general_group.add_argument(
        "-h",
        "--help",
        action="help",
        help="Show this help message and exit.",
    )
    general_group.add_argument(
        "--version",
        action="version",
        version=ui.version_output(version),
        help=ui.HELP_VERSION,
    )

    return ap
