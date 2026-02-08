"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

import argparse
from typing import cast

from . import ui_messages as ui


class _HelpFormatter(argparse.ArgumentDefaultsHelpFormatter):
    def _get_help_string(self, action: argparse.Action) -> str:
        if action.dest == "cache_path":
            return action.help or ""
        return cast(str, super()._get_help_string(action))


def build_parser(version: str) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="codeclone",
        description="AST and CFG-based code clone detector for Python.",
        formatter_class=_HelpFormatter,
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
        metavar="FILE",
        default=None,
        help=ui.HELP_CACHE_PATH,
    )
    tune_group.add_argument(
        "--cache-dir",
        dest="cache_path",
        metavar="FILE",
        default=None,
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
        default="codeclone.baseline.json",
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
        action="store_true",
        help=ui.HELP_UPDATE_BASELINE,
    )
    ci_group.add_argument(
        "--fail-on-new",
        action="store_true",
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
        action="store_true",
        help=ui.HELP_CI,
    )

    out_group = ap.add_argument_group("Reporting")
    out_group.add_argument(
        "--html",
        dest="html_out",
        metavar="FILE",
        help=ui.HELP_HTML,
    )
    out_group.add_argument(
        "--json",
        dest="json_out",
        metavar="FILE",
        help=ui.HELP_JSON,
    )
    out_group.add_argument(
        "--text",
        dest="text_out",
        metavar="FILE",
        help=ui.HELP_TEXT,
    )
    out_group.add_argument(
        "--no-progress",
        action="store_true",
        help=ui.HELP_NO_PROGRESS,
    )
    out_group.add_argument(
        "--no-color",
        action="store_true",
        help=ui.HELP_NO_COLOR,
    )
    out_group.add_argument(
        "--quiet",
        action="store_true",
        help=ui.HELP_QUIET,
    )
    out_group.add_argument(
        "--verbose",
        action="store_true",
        help=ui.HELP_VERBOSE,
    )
    return ap
