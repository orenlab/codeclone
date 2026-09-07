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
    DEFAULT_CACHE_PATH,
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
HELP_ROOT = "Project root directory to scan. Defaults to the current\ndirectory."
HELP_MIN_LOC = (
    "Minimum Lines of Code (LOC) required for clone analysis.\n"
    f"Default: {DEFAULT_MIN_LOC}."
)
HELP_MIN_STMT = (
    "Minimum top-level statements in the function body\n"
    "required for clone analysis. Statements nested inside\n"
    f"them are not counted. Default: {DEFAULT_MIN_STMT}."
)
HELP_PROCESSES = f"Number of parallel worker processes. Default: {DEFAULT_PROCESSES}."
HELP_CHANGED_ONLY = (
    "Limit clone gating and changed-scope summaries to\n"
    "findings that touch files from a git diff selection."
)
HELP_DIFF_AGAINST = (
    "Resolve changed files from `git diff --name-only <REF>`.\n"
    "Use together with --changed-only."
)
HELP_PATHS_FROM_GIT_DIFF = (
    "Shorthand for --changed-only using `git diff --name-only\n"
    "<REF>`. Useful for PR and CI review flows."
)
HELP_BLAST_RADIUS = (
    "Show structural blast radius for the given files. Runs\n"
    "analysis first, then projects dependents, clone cohorts,\n"
    "risk signals, and do-not-touch boundaries."
)
HELP_PATCH_VERIFY = (
    "Verify the current patch against the trusted baseline\n"
    "budget. Runs analysis, checks baseline-relative\n"
    "regressions and gate status, then exits."
)
HELP_STRICTNESS = (
    "Strictness profile for --patch-verify: ci, strict, or\nrelaxed. Default: ci."
)
HELP_SESSION_STATS = (
    "Show workspace session status: active agents, intents,\n"
    "lease health. Read-only, does not run analysis."
)
HELP_AUDIT = (
    "Show local Controller audit trail from the configured\n"
    "audit database. Read-only, does not run analysis."
)
HELP_AUDIT_JSON = (
    "Output audit payload footprint as JSON. Implies --audit.\n"
    "Useful for cross-repository comparison."
)
HELP_NEAR_MISS = (
    "Report near-miss clone pairs: functions whose normalized\n"
    "statement sequences differ by exactly one statement.\n"
    "Advisory only; never enters clone gates or the baseline."
)
HELP_RENAMED_STRUCTURE = (
    "Report renamed-structure clone groups: functions\n"
    "identical up to a bijective, consistent renaming of\n"
    "locals and receiver attributes. Advisory only; never\n"
    "enters clone gates or the baseline."
)
HELP_CACHE_PATH = (
    f"Path to the cache file. If FILE is omitted, uses\n<root>/{DEFAULT_CACHE_PATH}."
)
# "Prefer --cache-path in new configurations" used to follow, which is what
# "Legacy alias for --cache-path" already says.
HELP_CACHE_DIR_LEGACY = "Legacy alias for --cache-path."
HELP_MAX_BASELINE_SIZE_MB = (
    f"Maximum allowed baseline size in MB. Default: {DEFAULT_MAX_BASELINE_SIZE_MB}."
)
HELP_MAX_CACHE_SIZE_MB = (
    f"Maximum cache file size in MB. Default: {DEFAULT_MAX_CACHE_SIZE_MB}."
)
HELP_BASELINE = (
    "Path to the clone baseline. If FILE is omitted, uses\n"
    f"{Path(DEFAULT_BASELINE_PATH)}."
)
HELP_UPDATE_BASELINE = (
    "Overwrite the clone baseline with current results.\nDisabled by default."
)
HELP_FAIL_ON_NEW = (
    "Exit with code 3 if NEW clone findings not present in\nthe baseline are detected."
)
HELP_FAIL_THRESHOLD = (
    "Exit with code 3 if the total number of function + block\n"
    "clone groups exceeds this value. Disabled unless set."
)
HELP_FAIL_COMPLEXITY = (
    "Exit with code 3 if any function exceeds the cyclomatic\n"
    "complexity threshold. If enabled without a value, uses\n"
    "20."
)
HELP_FAIL_COUPLING = (
    "Exit with code 3 if any class exceeds the coupling\n"
    "threshold. If enabled without a value, uses 10."
)
HELP_FAIL_COHESION = (
    "Exit with code 3 if any class exceeds the cohesion\n"
    "threshold. If enabled without a value, uses 4."
)
HELP_FAIL_CYCLES = "Exit with code 3 if circular module dependencies are\ndetected."
HELP_FAIL_DEAD_CODE = "Exit with code 3 if high-confidence dead code is\ndetected."
HELP_FAIL_ON_UNRESOLVED_DEAD_CODE = (
    "Exit with code 3 if any symbol is an unresolved external\n"
    "override. These are abstentions, not findings: a public\n"
    "method whose class inherits from a base outside the\n"
    "analysis root, with no evidence either way. Off by\n"
    "default, and never counted as dead code."
)
HELP_FAIL_ON_TRUNCATED_RUN = (
    "Exit with code 3 if the run could not read every file it\n"
    "found. Files lost to a dead worker, a permission fault\n"
    "or an unreadable encoding leave metrics measured over an\n"
    "incomplete population. Off by default; publishing a\n"
    "baseline from such a run is refused unconditionally\n"
    "either way."
)
HELP_FAIL_HEALTH = (
    "Exit with code 3 if the overall health score falls below\n"
    "the threshold. If enabled without a value, uses 60."
)
HELP_FAIL_ON_NEW_METRICS = (
    "Exit with code 3 if new metrics violations appear\n"
    "relative to the metrics baseline."
)
HELP_API_SURFACE = (
    "Collect public API surface facts for baseline-aware\n"
    "compatibility review. Disabled by default."
)
HELP_SEMANTIC_AUTHORITY = (
    "Collect report-only semantic authority candidates and\n"
    "provenance facts. Disabled by default."
)
HELP_COVERAGE = (
    "Join external Cobertura XML line coverage to function\n"
    "spans. Pass a `coverage xml` report path."
)
HELP_FAIL_ON_TYPING_REGRESSION = (
    "Exit with code 3 if typing adoption coverage regresses\n"
    "relative to the metrics baseline."
)
HELP_FAIL_ON_DOCSTRING_REGRESSION = (
    "Exit with code 3 if public docstring coverage regresses\n"
    "relative to the metrics baseline."
)
HELP_FAIL_ON_API_BREAK = (
    "Exit with code 3 if public API removals or signature\n"
    "breaks are detected relative to the metrics baseline."
)
HELP_FAIL_ON_AUTHORITY_VIOLATION = (
    "Exit with code 3 if a governed semantic contract has an\n"
    "authority violation. Requires a reviewed\n"
    "[[tool.codeclone.authority]] registry entry."
)
HELP_FAIL_ON_UNTESTED_HOTSPOTS = (
    "Exit with code 3 if medium/high-risk functions measured\n"
    "by Coverage Join fall below the joined coverage\n"
    "threshold. Requires --coverage."
)
HELP_MIN_TYPING_COVERAGE = (
    "Exit with code 3 if parameter typing coverage falls\n"
    "below the threshold. Threshold is a whole percent from 0\n"
    "to 100."
)
HELP_MIN_DOCSTRING_COVERAGE = (
    "Exit with code 3 if public docstring coverage falls\n"
    "below the threshold. Threshold is a whole percent from 0\n"
    "to 100."
)
HELP_COVERAGE_MIN = (
    "Coverage threshold for untested hotspot detection.\n"
    f"Threshold is a whole percent from 0 to 100. Default: {DEFAULT_COVERAGE_MIN}."
)
HELP_CI = (
    "Enable CI preset. Equivalent to: --fail-on-new\n"
    "--no-color --quiet. When a trusted metrics baseline is\n"
    "available, CI mode also enables metrics regression\n"
    "gating."
)
HELP_SKIP_METRICS = "Skip full metrics analysis and run in clone-only mode."
HELP_SKIP_DEAD_CODE = "Skip dead code detection."
HELP_DEAD_CODE_WORLD = (
    "World contract for dead-code verdicts. open (default): a\n"
    "symbol consumers outside the repository could reach is\n"
    "never asserted dead on internal evidence alone; it is\n"
    "reported as unresolved. closed: every consumer is inside\n"
    "the repository."
)
HELP_SKIP_DEPENDENCIES = "Skip dependency graph analysis."
HELP_HTML = (
    "Generate an HTML report. If FILE is omitted, writes to\n"
    f"{DEFAULT_HTML_REPORT_PATH}."
)
HELP_JSON = (
    "Generate the canonical JSON report. If FILE is omitted,\n"
    f"writes to {DEFAULT_JSON_REPORT_PATH}."
)
HELP_MD = (
    "Generate a Markdown report. If FILE is omitted, writes\n"
    f"to {DEFAULT_MARKDOWN_REPORT_PATH}."
)
HELP_SARIF = (
    "Generate a SARIF 2.1.0 report. If FILE is omitted,\n"
    f"writes to {DEFAULT_SARIF_REPORT_PATH}."
)
HELP_TEXT = (
    "Generate a plain-text report. If FILE is omitted, writes\n"
    f"to {DEFAULT_TEXT_REPORT_PATH}."
)
HELP_OPEN_HTML_REPORT = (
    "Open the generated HTML report in the default browser.\nRequires --html."
)
HELP_TIMESTAMPED_REPORT_PATHS = (
    "Append a UTC timestamp to default report filenames.\n"
    "Applies only to report flags passed without FILE."
)
HELP_NO_PROGRESS = "Disable progress output. Recommended for CI logs."
HELP_PROGRESS = "Force-enable progress output."
HELP_NO_COLOR = "Disable ANSI colors."
HELP_COLOR = "Force-enable ANSI colors."
HELP_QUIET = "Reduce output to warnings, errors, and essential\nsummaries."
HELP_VERBOSE = "Include detailed identifiers for NEW clone findings."
HELP_DEBUG = (
    "Print debug details for internal errors, including\n"
    "traceback and environment information."
)
HELP_INTERACTIVE = (
    "Open the guided CodeClone product tour. Use together\n"
    "with --help in an interactive terminal."
)
HELP_MASCOT_TAGLINE = (
    "Run `codeclone --help --interactive-help` for a guided product tour."
)
HELP_TOUR_INTERRUPTED = "Tour ended. `codeclone --help` lists every flag."
HELP_BASELINE_COMMAND = "Manage the native baseline publication state."
HELP_BASELINE_RECOVER_LOCK = (
    "Explicitly recover a stale baseline publication lock\n"
    "without writing the baseline."
)
HELP_BASELINE_RECOVER_PATH = "Baseline target whose adjacent lock is recovered."
HELP_BASELINE_RECOVER_TOKEN = "Exact lock token observed by the operator."
HELP_BASELINE_RECOVER_FORCE = (
    "Allow recovery of foreign-host or malformed lock\nevidence."
)
HELP_TOUR_STEP_INTRO_TITLE = "CodeClone product tour"
HELP_TOUR_STEP_INTRO_BODY = (
    "CodeClone is a deterministic Structural Change Controller for "
    "AI-assisted Python development. It starts before a diff exists: declare "
    "intent, map the structural blast radius, bound the edit, verify the "
    "patch, and leave an auditable receipt. Docs: "
    "https://orenlab.github.io/codeclone/"
)
HELP_TOUR_STEP_PIPELINE_TITLE = "One analysis, many projections"
HELP_TOUR_STEP_PIPELINE_BODY = (
    "The pipeline scans files, parses Python, normalizes structural facts, "
    "builds fingerprints, derives clones and metrics, then emits one "
    "canonical report. CLI, HTML, JSON, SARIF, MCP, and IDE clients project "
    "the same facts. First run: `codeclone .`; HTML: `codeclone . --html "
    "--open-html-report`."
)
HELP_TOUR_STEP_CLONES_TITLE = "Fingerprinting structural clones"
HELP_TOUR_STEP_CLONES_BODY = (
    "Function, block, and segment clones are grouped from normalized AST "
    "facts. Fingerprints stay stable across renames. NEW vs KNOWN is "
    "baseline-relative, not a patch-local proof by itself. Tune sensitivity "
    "with `--min-loc`, `--min-stmt`, and pyproject thresholds."
)
HELP_TOUR_STEP_CACHE_TITLE = "Reusing structural facts"
HELP_TOUR_STEP_CACHE_BODY = (
    f"The integrity-checked cache under `{DEFAULT_CACHE_PATH}` speeds "
    "repeat runs. Cache is optimization only, never analysis truth. Reports "
    "record whether cache was used; profile mismatch or invalid cache is "
    "ignored safely."
)
HELP_TOUR_STEP_DEPENDENCIES_TITLE = "Following dependency pressure"
HELP_TOUR_STEP_DEPENDENCIES_BODY = (
    "Module graphs surface cycles, coupling hotspots, and likely blast-radius "
    "neighbors before a change. Query a focused impact view with `codeclone "
    "--blast-radius path/to/file.py` after a normal analysis run."
)
HELP_TOUR_STEP_METRICS_TITLE = "Measuring project health"
HELP_TOUR_STEP_METRICS_BODY = (
    "Metrics cover cyclomatic complexity, class coupling/cohesion, dead code, "
    "dependency cycles, typing/docstring adoption, and a composite health "
    "score. Gate with `--fail-complexity`, `--fail-dead-code`, "
    "`--fail-health`, and more."
)
HELP_TOUR_STEP_REPORTS_TITLE = "Publishing the same evidence"
HELP_TOUR_STEP_REPORTS_BODY = (
    "The canonical report powers HTML triage, JSON, Markdown, SARIF 2.1, and "
    "text. Export SARIF for GitHub code scanning. Browse the public sample "
    "report from the documentation site. Default HTML path: "
    f"`{DEFAULT_HTML_REPORT_PATH}`."
)
HELP_TOUR_STEP_BASELINE_TITLE = "Baseline-aware CI gating"
HELP_TOUR_STEP_BASELINE_BODY = (
    "`codeclone . --ci` fails on NEW clone findings vs a trusted baseline. "
    "The metrics baseline can track API breaks and typing/docstring "
    "regressions. The GitHub Action and `codeclone setup wizard` help align "
    "repository hygiene."
)
HELP_TOUR_STEP_CONTROLLER_TITLE = "Governed change control"
HELP_TOUR_STEP_CONTROLLER_BODY = (
    "For AI-assisted work, the controller starts before the diff: declare "
    "intent, inspect blast radius, retrieve scoped memory, verify the patch, "
    "and leave a receipt. MCP workflow: `start_controlled_change` and "
    "`finish_controlled_change`."
)
HELP_TOUR_STEP_MEMORY_TITLE = "Engineering Memory"
HELP_TOUR_STEP_MEMORY_BODY = (
    "Local evidence-linked memory: scoped retrieval, trajectories, Patch "
    "Trail, and Experience patterns. Agents propose drafts; humans approve in "
    "VS Code. Memory guides, but never grants edit permission."
)
HELP_TOUR_STEP_INTEGRATIONS_TITLE = "IDE and agent clients"
HELP_TOUR_STEP_INTEGRATIONS_BODY = (
    "Native surfaces: VS Code extension, Cursor/Codex/Claude Code plugins, "
    "Claude Desktop bundle, and GitHub Action. They all use the same local "
    "`codeclone-mcp` server and the same canonical analysis facts. Install "
    'MCP support with `pip install "codeclone[mcp]"`.'
)
# Two spaces: the run banner spaces score from grade the same way.
HELP_TOUR_STEP_SUCCESS_TITLE = "Project health  91 / A"
HELP_TOUR_STEP_SUCCESS_BODY = (
    "A typical clean run ends with health grade, inventory summary, and "
    "report path. Explore `--patch-verify` for budget checks and "
    "`--session-stats` for workspace coordination when multiple agents share "
    "a repo."
)
HELP_TOUR_STEP_REGRESSION_TITLE = "2 new structural regressions"
HELP_TOUR_STEP_REGRESSION_BODY = (
    "When CI or `--ci` sees NEW clones or metric regressions, the run should "
    "stop for review. Inspect HTML or JSON, fix the issue, or update the "
    "baseline only after deliberate human inspection."
)
HELP_TOUR_STEP_BLOCKED_TITLE = "STOP: do-not-touch boundary"
HELP_TOUR_STEP_BLOCKED_BODY = (
    "The controller blocks edits on baselines, generated reports, and "
    "`.codeclone/` state unless explicitly scoped. `do_not_touch` is a hard "
    "boundary; expand scope deliberately via a fresh intent. Never bypass it "
    "silently."
)
HELP_TOUR_STEP_NEXT_TITLE = "Ready when you are"
HELP_TOUR_STEP_NEXT_BODY = (
    "Run `codeclone .`, open the documentation site, wire MCP where needed, "
    "try `codeclone setup wizard`, and use `codeclone --help` for the "
    "complete flag reference."
)
