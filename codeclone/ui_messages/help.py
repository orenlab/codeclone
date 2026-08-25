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
    "Minimum top-level statements in the function body required for\n"
    "clone analysis. Statements nested inside them are not counted.\n"
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
HELP_NEAR_MISS = (
    "Report near-miss clone pairs: functions whose normalized statement\n"
    "sequences differ by exactly one statement.\n"
    "Advisory only; never enters clone gates or the baseline."
)
HELP_RENAMED_STRUCTURE = (
    "Report renamed-structure clone groups: functions identical up to a\n"
    "bijective, consistent renaming of locals and receiver attributes.\n"
    "Advisory only; never enters clone gates or the baseline."
)
HELP_CACHE_PATH = (
    "Path to the cache file.\nIf FILE is omitted, uses <root>/.codeclone/cache.json."
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
HELP_FAIL_ON_UNRESOLVED_DEAD_CODE = (
    "Exit with code 3 if any symbol is an unresolved external override.\n"
    "These are abstentions, not findings: a public method whose class "
    "inherits from a base outside the analysis root, with no evidence "
    "either way. Off by default, and never counted as dead code."
)
HELP_FAIL_ON_TRUNCATED_RUN = (
    "Exit with code 3 if the run could not read every file it found.\n"
    "Files lost to a dead worker, a permission fault or an unreadable\n"
    "encoding leave metrics measured over an incomplete population.\n"
    "Off by default; publishing a baseline from such a run is refused\n"
    "unconditionally either way."
)
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
HELP_SEMANTIC_AUTHORITY = (
    "Collect report-only semantic authority candidates and provenance facts.\n"
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
HELP_FAIL_ON_AUTHORITY_VIOLATION = (
    "Exit with code 3 if a governed semantic contract has an authority violation.\n"
    "Requires a reviewed [[tool.codeclone.authority]] registry entry."
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
HELP_INTERACTIVE = (
    "Open the guided CodeClone product tour.\n"
    "Use together with --help in an interactive terminal."
)
HELP_MASCOT_TAGLINE = (
    "Run `codeclone --help --interactive-help` for a guided product tour."
)
HELP_BASELINE_COMMAND = "Manage the native baseline publication state."
HELP_BASELINE_RECOVER_LOCK = (
    "Explicitly recover a stale baseline publication lock without writing the baseline."
)
HELP_BASELINE_RECOVER_PATH = "Baseline target whose adjacent lock is recovered."
HELP_BASELINE_RECOVER_TOKEN = "Exact lock token observed by the operator."
HELP_BASELINE_RECOVER_FORCE = (
    "Allow recovery of foreign-host or malformed lock evidence."
)
HELP_TOUR_STEP_INTRO_TITLE = "CodeClone product tour"
HELP_TOUR_STEP_INTRO_BODY = (
    "CodeClone is a deterministic Structural Change Controller for AI-assisted\n"
    "Python development. It starts before a diff exists: declare intent, map the\n"
    "structural blast radius, bound the edit, verify the patch, and leave an\n"
    "auditable receipt. Docs: https://orenlab.github.io/codeclone/"
)
HELP_TOUR_STEP_PIPELINE_TITLE = "One analysis, many projections"
HELP_TOUR_STEP_PIPELINE_BODY = (
    "The pipeline scans files, parses Python, normalizes structural facts,\n"
    "builds fingerprints, derives clones and metrics, then emits one canonical\n"
    "report. CLI, HTML, JSON, SARIF, MCP, and IDE clients project the same facts.\n"
    "First run: `codeclone .`; HTML: `codeclone . --html --open-html-report`."
)
HELP_TOUR_STEP_CLONES_TITLE = "Fingerprinting structural clones"
HELP_TOUR_STEP_CLONES_BODY = (
    "Function, block, and segment clones are grouped from normalized AST facts.\n"
    "Fingerprints stay stable across renames. NEW vs KNOWN is baseline-relative,\n"
    "not a patch-local proof by itself.\n"
    "Tune sensitivity with `--min-loc`, `--min-stmt`, and pyproject thresholds."
)
HELP_TOUR_STEP_CACHE_TITLE = "Reusing structural facts"
HELP_TOUR_STEP_CACHE_BODY = (
    "The integrity-checked cache under `.codeclone/cache.json` speeds repeat runs.\n"
    "Cache is optimization only, never analysis truth. Reports record whether\n"
    "cache was used; profile mismatch or invalid cache is ignored safely."
)
HELP_TOUR_STEP_DEPENDENCIES_TITLE = "Following dependency pressure"
HELP_TOUR_STEP_DEPENDENCIES_BODY = (
    "Module graphs surface cycles, coupling hotspots, and likely blast-radius\n"
    "neighbors before a change. Query a focused impact view with\n"
    "`codeclone --blast-radius path/to/file.py` after a normal analysis run."
)
HELP_TOUR_STEP_METRICS_TITLE = "Measuring project health"
HELP_TOUR_STEP_METRICS_BODY = (
    "Metrics cover cyclomatic complexity, class coupling/cohesion, dead code,\n"
    "dependency cycles, typing/docstring adoption, and a composite health score.\n"
    "Gate with `--fail-complexity`, `--fail-dead-code`, `--fail-health`, and more."
)
HELP_TOUR_STEP_REPORTS_TITLE = "Publishing the same evidence"
HELP_TOUR_STEP_REPORTS_BODY = (
    "The canonical report powers HTML triage, JSON, Markdown, SARIF 2.1, and text.\n"
    "Export SARIF for GitHub code scanning. Browse the public sample report from\n"
    "the documentation site. Default HTML path: `.codeclone/report.html`."
)
HELP_TOUR_STEP_BASELINE_TITLE = "Baseline-aware CI gating"
HELP_TOUR_STEP_BASELINE_BODY = (
    "`codeclone . --ci` fails on NEW clone findings vs a trusted baseline.\n"
    "The metrics baseline can track API breaks and typing/docstring regressions.\n"
    "The GitHub Action and `codeclone setup wizard` help align repository hygiene."
)
HELP_TOUR_STEP_CONTROLLER_TITLE = "Governed change control"
HELP_TOUR_STEP_CONTROLLER_BODY = (
    "For AI-assisted work, the controller starts before the diff: declare intent,\n"
    "inspect blast radius, retrieve scoped memory, verify the patch, and leave a\n"
    "receipt. MCP workflow: `start_controlled_change` and `finish_controlled_change`."
)
HELP_TOUR_STEP_MEMORY_TITLE = "Engineering Memory"
HELP_TOUR_STEP_MEMORY_BODY = (
    "Local evidence-linked memory: scoped retrieval, trajectories, Patch Trail,\n"
    "and Experience patterns. Agents propose drafts; humans approve in VS Code.\n"
    "Memory guides, but never grants edit permission."
)
HELP_TOUR_STEP_INTEGRATIONS_TITLE = "IDE and agent clients"
HELP_TOUR_STEP_INTEGRATIONS_BODY = (
    "Native surfaces: VS Code extension, Cursor/Codex/Claude Code plugins,\n"
    "Claude Desktop bundle, and GitHub Action. They all use the same local\n"
    "`codeclone-mcp` server and the same canonical analysis facts.\n"
    'Install MCP support with `pip install "codeclone[mcp]"`.'
)
HELP_TOUR_STEP_SUCCESS_TITLE = "Project health  91 / A"
HELP_TOUR_STEP_SUCCESS_BODY = (
    "A typical clean run ends with health grade, inventory summary, and report path.\n"
    "Explore `--patch-verify` for budget checks and `--session-stats` for workspace\n"
    "coordination when multiple agents share a repo."
)
HELP_TOUR_STEP_REGRESSION_TITLE = "2 new structural regressions"
HELP_TOUR_STEP_REGRESSION_BODY = (
    "When CI or `--ci` sees NEW clones or metric regressions, the run should stop\n"
    "for review. Inspect HTML or JSON, fix the issue, or update the baseline only\n"
    "after deliberate human inspection."
)
HELP_TOUR_STEP_BLOCKED_TITLE = "STOP: do-not-touch boundary"
HELP_TOUR_STEP_BLOCKED_BODY = (
    "The controller blocks edits on baselines, generated reports, and `.codeclone/`\n"
    "state unless explicitly scoped. `do_not_touch` is a hard boundary; expand\n"
    "scope deliberately via a fresh intent. Never bypass it silently."
)
HELP_TOUR_STEP_NEXT_TITLE = "Ready when you are"
HELP_TOUR_STEP_NEXT_BODY = (
    "Run `codeclone .`, open the documentation site, wire MCP where needed, try\n"
    "`codeclone setup wizard`, and use `codeclone --help` for the complete flag\n"
    "reference."
)
