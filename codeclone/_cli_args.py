# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import argparse
import sys
from typing import NoReturn, cast

from . import ui_messages as ui
from .contracts import (
    DEFAULT_COHESION_THRESHOLD,
    DEFAULT_COMPLEXITY_THRESHOLD,
    DEFAULT_COUPLING_THRESHOLD,
    DEFAULT_HEALTH_THRESHOLD,
    ExitCode,
    cli_help_epilog,
)

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


class _HelpFormatter(
    argparse.RawTextHelpFormatter, argparse.ArgumentDefaultsHelpFormatter
):
    def _get_help_string(self, action: argparse.Action) -> str:
        if action.dest == "cache_path":
            return action.help or ""
        return cast(str, super()._get_help_string(action))


def build_parser(version: str) -> argparse.ArgumentParser:
    ap = _ArgumentParser(
        prog="codeclone",
        description="Structural code quality analysis for Python.",
        formatter_class=_HelpFormatter,
        epilog=cli_help_epilog(),
    )
    ap.add_argument(
        "--version",
        action="version",
        version=ui.version_output(version),
        help=ui.HELP_VERSION,
    )

    core_group = ap.add_argument_group("Target")
    core_group.add_argument(
        "root",
        nargs="?",
        default=".",
        help=ui.HELP_ROOT,
    )

    tune_group = ap.add_argument_group("Analysis Tuning")
    tune_group.add_argument(
        "--min-loc",
        type=int,
        default=15,
        help=ui.HELP_MIN_LOC,
    )
    tune_group.add_argument(
        "--min-stmt",
        type=int,
        default=6,
        help=ui.HELP_MIN_STMT,
    )
    tune_group.add_argument(
        "--processes",
        type=int,
        default=4,
        help=ui.HELP_PROCESSES,
    )
    tune_group.add_argument(
        "--cache-path",
        dest="cache_path",
        nargs="?",
        metavar="FILE",
        default=None,
        const=None,
        help=ui.HELP_CACHE_PATH,
    )
    tune_group.add_argument(
        "--cache-dir",
        dest="cache_path",
        nargs="?",
        metavar="FILE",
        default=None,
        const=None,
        help=ui.HELP_CACHE_DIR_LEGACY,
    )
    tune_group.add_argument(
        "--max-cache-size-mb",
        type=int,
        default=50,
        metavar="MB",
        help=ui.HELP_MAX_CACHE_SIZE_MB,
    )

    ci_group = ap.add_argument_group("Baseline & CI/CD")
    ci_group.add_argument(
        "--baseline",
        nargs="?",
        default=DEFAULT_BASELINE_PATH,
        const=DEFAULT_BASELINE_PATH,
        help=ui.HELP_BASELINE,
    )
    ci_group.add_argument(
        "--max-baseline-size-mb",
        type=int,
        default=5,
        metavar="MB",
        help=ui.HELP_MAX_BASELINE_SIZE_MB,
    )
    ci_group.add_argument(
        "--update-baseline",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=ui.HELP_UPDATE_BASELINE,
    )
    ci_group.add_argument(
        "--fail-on-new",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=ui.HELP_FAIL_ON_NEW,
    )
    ci_group.add_argument(
        "--fail-threshold",
        type=int,
        default=-1,
        metavar="MAX_CLONES",
        help=ui.HELP_FAIL_THRESHOLD,
    )
    ci_group.add_argument(
        "--ci",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=ui.HELP_CI,
    )
    ci_group.add_argument(
        "--fail-complexity",
        type=int,
        default=-1,
        metavar="CC_MAX",
        help=(
            f"{ui.HELP_FAIL_COMPLEXITY} "
            f"Default when set without value intent: {DEFAULT_COMPLEXITY_THRESHOLD}."
        ),
    )
    ci_group.add_argument(
        "--fail-coupling",
        type=int,
        default=-1,
        metavar="CBO_MAX",
        help=(
            f"{ui.HELP_FAIL_COUPLING} "
            f"Default when set without value intent: {DEFAULT_COUPLING_THRESHOLD}."
        ),
    )
    ci_group.add_argument(
        "--fail-cohesion",
        type=int,
        default=-1,
        metavar="LCOM4_MAX",
        help=(
            f"{ui.HELP_FAIL_COHESION} "
            f"Default when set without value intent: {DEFAULT_COHESION_THRESHOLD}."
        ),
    )
    ci_group.add_argument(
        "--fail-cycles",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=ui.HELP_FAIL_CYCLES,
    )
    ci_group.add_argument(
        "--fail-dead-code",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=ui.HELP_FAIL_DEAD_CODE,
    )
    ci_group.add_argument(
        "--fail-health",
        type=int,
        default=-1,
        metavar="SCORE_MIN",
        help=(
            f"{ui.HELP_FAIL_HEALTH} "
            f"Default when set without value intent: {DEFAULT_HEALTH_THRESHOLD}."
        ),
    )
    ci_group.add_argument(
        "--fail-on-new-metrics",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=ui.HELP_FAIL_ON_NEW_METRICS,
    )
    ci_group.add_argument(
        "--update-metrics-baseline",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=ui.HELP_UPDATE_METRICS_BASELINE,
    )
    ci_group.add_argument(
        "--metrics-baseline",
        nargs="?",
        default=DEFAULT_BASELINE_PATH,
        const=DEFAULT_BASELINE_PATH,
        help=ui.HELP_METRICS_BASELINE,
    )
    ci_group.add_argument(
        "--skip-metrics",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=ui.HELP_SKIP_METRICS,
    )
    ci_group.add_argument(
        "--skip-dead-code",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=ui.HELP_SKIP_DEAD_CODE,
    )
    ci_group.add_argument(
        "--skip-dependencies",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=ui.HELP_SKIP_DEPENDENCIES,
    )

    out_group = ap.add_argument_group("Reporting")
    out_group.add_argument(
        "--html",
        dest="html_out",
        nargs="?",
        metavar="FILE",
        const=DEFAULT_HTML_REPORT_PATH,
        help=ui.HELP_HTML,
    )
    out_group.add_argument(
        "--json",
        dest="json_out",
        nargs="?",
        metavar="FILE",
        const=DEFAULT_JSON_REPORT_PATH,
        help=ui.HELP_JSON,
    )
    out_group.add_argument(
        "--md",
        dest="md_out",
        nargs="?",
        metavar="FILE",
        const=DEFAULT_MARKDOWN_REPORT_PATH,
        help=ui.HELP_MD,
    )
    out_group.add_argument(
        "--sarif",
        dest="sarif_out",
        nargs="?",
        metavar="FILE",
        const=DEFAULT_SARIF_REPORT_PATH,
        help=ui.HELP_SARIF,
    )
    out_group.add_argument(
        "--text",
        dest="text_out",
        nargs="?",
        metavar="FILE",
        const=DEFAULT_TEXT_REPORT_PATH,
        help=ui.HELP_TEXT,
    )
    out_group.add_argument(
        "--no-progress",
        dest="no_progress",
        action="store_true",
        help=ui.HELP_NO_PROGRESS,
    )
    out_group.add_argument(
        "--progress",
        dest="no_progress",
        action="store_false",
        help=ui.HELP_PROGRESS,
    )
    out_group.add_argument(
        "--no-color",
        dest="no_color",
        action="store_true",
        help=ui.HELP_NO_COLOR,
    )
    out_group.add_argument(
        "--color",
        dest="no_color",
        action="store_false",
        help=ui.HELP_COLOR,
    )
    out_group.set_defaults(no_progress=False, no_color=False)
    out_group.add_argument(
        "--quiet",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=ui.HELP_QUIET,
    )
    out_group.add_argument(
        "--verbose",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=ui.HELP_VERBOSE,
    )
    out_group.add_argument(
        "--debug",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=ui.HELP_DEBUG,
    )
    return ap
