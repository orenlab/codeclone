# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""CLI flag help text for argparse."""

from __future__ import annotations

from pathlib import Path

from ..contracts import (
    DEFAULT_BASELINE_PATH,
    DEFAULT_COVERAGE_MIN,
    DEFAULT_HTML_REPORT_PATH,
    DEFAULT_JSON_REPORT_PATH,
    DEFAULT_MARKDOWN_REPORT_PATH,
    DEFAULT_MAX_BASELINE_SIZE_MB,
    DEFAULT_MAX_CACHE_SIZE_MB,
    DEFAULT_MIN_LOC,
    DEFAULT_MIN_STMT,
    DEFAULT_PROCESSES,
    DEFAULT_SARIF_REPORT_PATH,
    DEFAULT_TEXT_REPORT_PATH,
)

HELP_VERSION = "Print the CodeClone version and exit."
HELP_ROOT = "Project root directory to scan.\nDefaults to the current directory."
HELP_MIN_LOC = (
    "Minimum Lines of Code (LOC) required for clone analysis.\n"
    f"Default: {DEFAULT_MIN_LOC}."
)
HELP_MIN_STMT = (
    "Minimum AST statement count required for clone analysis.\n"
    f"Default: {DEFAULT_MIN_STMT}."
)
HELP_PROCESSES = f"Number of parallel worker processes.\nDefault: {DEFAULT_PROCESSES}."
HELP_CHANGED_ONLY = (
    "Limit clone gating and changed-scope summaries to findings that touch\n"
    "files from a git diff selection."
)
HELP_DIFF_AGAINST = (
    "Resolve changed files from `git diff --name-only <REF>`.\n"
    "Use together with --changed-only."
)
HELP_PATHS_FROM_GIT_DIFF = (
    "Shorthand for --changed-only using `git diff --name-only <REF>`.\n"
    "Useful for PR and CI review flows."
)
HELP_BLAST_RADIUS = (
    "Show structural blast radius for the given files.\n"
    "Runs analysis first, then projects dependents, clone cohorts,\n"
    "risk signals, and do-not-touch boundaries."
)
HELP_PATCH_VERIFY = (
    "Verify the current patch against the trusted baseline budget.\n"
    "Runs analysis, checks baseline-relative regressions and gate status, then exits."
)
HELP_STRICTNESS = (
    "Strictness profile for --patch-verify: ci, strict, or relaxed.\nDefault: ci."
)
HELP_SESSION_STATS = (
    "Show workspace session status: active agents, intents, lease health.\n"
    "Read-only, does not run analysis."
)
HELP_AUDIT = (
    "Show local Controller audit trail from the configured audit database.\n"
    "Read-only, does not run analysis."
)
HELP_AUDIT_JSON = (
    "Output audit payload footprint as JSON.\n"
    "Implies --audit. Useful for cross-repository comparison."
)
HELP_CACHE_PATH = (
    "Path to the cache file.\n"
    "If FILE is omitted, uses <root>/.cache/codeclone/cache.json."
)
HELP_CACHE_DIR_LEGACY = (
    "Legacy alias for --cache-path.\nPrefer --cache-path in new configurations."
)
HELP_MAX_BASELINE_SIZE_MB = (
    f"Maximum allowed baseline size in MB.\nDefault: {DEFAULT_MAX_BASELINE_SIZE_MB}."
)
HELP_MAX_CACHE_SIZE_MB = (
    f"Maximum cache file size in MB.\nDefault: {DEFAULT_MAX_CACHE_SIZE_MB}."
)
HELP_BASELINE = (
    "Path to the clone baseline.\n"
    f"If FILE is omitted, uses {Path(DEFAULT_BASELINE_PATH)}."
)
HELP_UPDATE_BASELINE = (
    "Overwrite the clone baseline with current results.\nDisabled by default."
)
HELP_FAIL_ON_NEW = (
    "Exit with code 3 if NEW clone findings not present in the baseline\nare detected."
)
HELP_FAIL_THRESHOLD = (
    "Exit with code 3 if the total number of function + block clone groups\n"
    "exceeds this value.\n"
    "Disabled unless set."
)
HELP_FAIL_COMPLEXITY = (
    "Exit with code 3 if any function exceeds the cyclomatic complexity\n"
    "threshold.\n"
    "If enabled without a value, uses 20."
)
HELP_FAIL_COUPLING = (
    "Exit with code 3 if any class exceeds the coupling threshold.\n"
    "If enabled without a value, uses 10."
)
HELP_FAIL_COHESION = (
    "Exit with code 3 if any class exceeds the cohesion threshold.\n"
    "If enabled without a value, uses 4."
)
HELP_FAIL_CYCLES = "Exit with code 3 if circular module dependencies are detected."
HELP_FAIL_DEAD_CODE = "Exit with code 3 if high-confidence dead code is detected."
HELP_FAIL_HEALTH = (
    "Exit with code 3 if the overall health score falls below the threshold.\n"
    "If enabled without a value, uses 60."
)
HELP_FAIL_ON_NEW_METRICS = (
    "Exit with code 3 if new metrics violations appear relative to the\n"
    "metrics baseline."
)
HELP_API_SURFACE = (
    "Collect public API surface facts for baseline-aware compatibility review.\n"
    "Disabled by default."
)
HELP_COVERAGE = (
    "Join external Cobertura XML line coverage to function spans.\n"
    "Pass a `coverage xml` report path."
)
HELP_FAIL_ON_TYPING_REGRESSION = (
    "Exit with code 3 if typing adoption coverage regresses relative to the\n"
    "metrics baseline."
)
HELP_FAIL_ON_DOCSTRING_REGRESSION = (
    "Exit with code 3 if public docstring coverage regresses relative to the\n"
    "metrics baseline."
)
HELP_FAIL_ON_API_BREAK = (
    "Exit with code 3 if public API removals or signature breaks are detected\n"
    "relative to the metrics baseline."
)
HELP_FAIL_ON_UNTESTED_HOTSPOTS = (
    "Exit with code 3 if medium/high-risk functions measured by Coverage Join\n"
    "fall below the joined coverage threshold.\nRequires --coverage."
)
HELP_MIN_TYPING_COVERAGE = (
    "Exit with code 3 if parameter typing coverage falls below the threshold.\n"
    "Threshold is a whole percent from 0 to 100."
)
HELP_MIN_DOCSTRING_COVERAGE = (
    "Exit with code 3 if public docstring coverage falls below the threshold.\n"
    "Threshold is a whole percent from 0 to 100."
)
HELP_COVERAGE_MIN = (
    "Coverage threshold for untested hotspot detection.\n"
    "Threshold is a whole percent from 0 to 100.\n"
    f"Default: {DEFAULT_COVERAGE_MIN}."
)
HELP_CI = (
    "Enable CI preset.\n"
    "Equivalent to: --fail-on-new --no-color --quiet.\n"
    "When a trusted metrics baseline is available, CI mode also enables\n"
    "metrics regression gating."
)
HELP_UPDATE_METRICS_BASELINE = (
    "Overwrite the metrics baseline with current metrics.\nDisabled by default."
)
HELP_METRICS_BASELINE = (
    "Path to the metrics baseline.\n"
    f"If FILE is omitted, uses {Path(DEFAULT_BASELINE_PATH)}."
)
HELP_SKIP_METRICS = "Skip full metrics analysis and run in clone-only mode."
HELP_SKIP_DEAD_CODE = "Skip dead code detection."
HELP_SKIP_DEPENDENCIES = "Skip dependency graph analysis."
HELP_HTML = (
    "Generate an HTML report.\n"
    f"If FILE is omitted, writes to {DEFAULT_HTML_REPORT_PATH}."
)
HELP_JSON = (
    "Generate the canonical JSON report.\n"
    f"If FILE is omitted, writes to {DEFAULT_JSON_REPORT_PATH}."
)
HELP_MD = (
    "Generate a Markdown report.\n"
    f"If FILE is omitted, writes to {DEFAULT_MARKDOWN_REPORT_PATH}."
)
HELP_SARIF = (
    "Generate a SARIF 2.1.0 report.\n"
    f"If FILE is omitted, writes to {DEFAULT_SARIF_REPORT_PATH}."
)
HELP_TEXT = (
    "Generate a plain-text report.\n"
    f"If FILE is omitted, writes to {DEFAULT_TEXT_REPORT_PATH}."
)
HELP_OPEN_HTML_REPORT = (
    "Open the generated HTML report in the default browser.\nRequires --html."
)
HELP_TIMESTAMPED_REPORT_PATHS = (
    "Append a UTC timestamp to default report filenames.\n"
    "Applies only to report flags passed without FILE."
)
HELP_NO_PROGRESS = "Disable progress output.\nRecommended for CI logs."
HELP_PROGRESS = "Force-enable progress output."
HELP_NO_COLOR = "Disable ANSI colors."
HELP_COLOR = "Force-enable ANSI colors."
HELP_QUIET = "Reduce output to warnings, errors, and essential summaries."
HELP_VERBOSE = "Include detailed identifiers for NEW clone findings."
HELP_DEBUG = (
    "Print debug details for internal errors, including traceback and\n"
    "environment information."
)
