# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""CLI runtime status, warning, error, and gate messages.

Warning-class constants hold the sentence only; ``fmt_cli_runtime_warning``
puts it on the grid under the advisory glyph. Error-class constants keep the
``[error]`` headline plus a ``[dim]`` next step; ``fmt_contract_error`` puts
them under the error banner. Neither family carries its own indentation.
"""

from __future__ import annotations

from .styling import GLYPH_OK, GLYPH_WARN

WARN_SUMMARY_ACCOUNTING_MISMATCH = (
    "Summary accounting mismatch: "
    "files_found != files_analyzed + cache_hits + files_skipped"
)

STATUS_DISCOVERING = "[success]Discovering Python files...[/success]"
STATUS_GROUPING = "[success]Grouping clones...[/success]"

INFO_PROCESSING_CHANGED = "  [info]Processing {count} changed files...[/info]"

WARN_WORKER_FAILED = "[warning]Worker failed: {error}[/warning]"
WARN_BATCH_ITEM_FAILED = "[warning]Failed to process batch item: {error}[/warning]"
WARN_PARALLEL_FALLBACK = (
    "[warning]Parallel processing unavailable, "
    "falling back to sequential: {error}[/warning]"
)
WARN_FAILED_FILES_HEADER = (
    f"\n  [warning]{GLYPH_WARN} {{count}} files failed to process[/warning]"
)
WARN_UNSUPPORTED_CONSTRUCT_SUMMARY = (
    f"  [warning]{GLYPH_WARN} {{count}} files not analyzed: "
    "unsupported syntax ({constructs})[/warning]"
)
WARN_CACHE_SAVE_FAILED = "[warning]Failed to save cache: {error}[/warning]"
WARN_HTML_REPORT_OPEN_FAILED = (
    "[warning]Failed to open HTML report in browser: {path} ({error}).[/warning]"
)
WARN_COVERAGE_JOIN_IGNORED = "[warning]Coverage join ignored: {error}[/warning]"

ERR_INVALID_OUTPUT_EXT = (
    "[error]Invalid {label} output extension: {path} "
    "(expected {expected_suffix}).[/error]\n"
    "[dim]Pass a {expected_suffix} path to {flag}, or pass {flag} without "
    "FILE to use the default report path.[/dim]"
)
ERR_INVALID_OUTPUT_PATH = (
    "[error]Invalid {label} output path: {path} ({error}).[/error]\n"
    "[dim]Pass a writable path to {flag}, or pass {flag} without FILE to "
    "use the default report path.[/dim]"
)
ERR_ROOT_NOT_FOUND = (
    "[error]Root path does not exist: {path}[/error]\n"
    "[dim]Pass an existing project directory, or omit the root argument "
    "to scan the current directory: codeclone .[/dim]"
)
ERR_INVALID_ROOT_PATH = (
    "[error]Invalid root path: {error}[/error]\n"
    "[dim]Pass an existing project directory, or omit the root argument "
    "to scan the current directory: codeclone .[/dim]"
)
ERR_SCAN_FAILED = (
    "[error]Scan failed: {error}[/error]\n"
    "[dim]Re-run with --debug to include a traceback.[/dim]"
)
ERR_INVALID_BASELINE_PATH = (
    "[error]Invalid baseline path: {path} ({error}).[/error]\n"
    "[dim]Pass an existing baseline file via --baseline, or create one "
    "with --update-baseline.[/dim]"
)
ERR_BASELINE_WRITE_FAILED = (
    "[error]Failed to write baseline file: {path} ({error}).[/error]\n"
    "[dim]Check that the path is writable, then re-run with "
    "--update-baseline.[/dim]"
)
# Printed with ``markup=False`` (see ``_print_scope_id_required``), so the
# bracket must stay bare: a Rich escape would be shown, not consumed, and the
# operator would read "\[tool.codeclone]".
ERR_BASELINE_SCOPE_ID_REQUIRED = (
    "baseline_scope_id is required for baseline update and gating; set a "
    "stable canonical UUID under [tool.codeclone]."
)
# The refusal above says what is wrong. These say what to paste and where,
# because "run codeclone setup" is not an answer for the projects that never
# run it. Which one applies is decided by the shape of the file on disk --
# offering a table header to a project that already has one hands it broken
# TOML, and a wrong instruction is worse than none.
HINT_SCOPE_ID_CREATE_FILE = "No pyproject.toml yet. Create {path} with:"
HINT_SCOPE_ID_ADD_SECTION = "Add this section to {path}:"
HINT_SCOPE_ID_ADD_KEY = "Add this line to [tool.codeclone] in {path}:"
HINT_SCOPE_ID_TABLE_HEADER = "[tool.codeclone]"
HINT_SCOPE_ID_KEY_LINE = 'baseline_scope_id = "{scope_id}"'
HINT_SCOPE_ID_FOOTER = (
    "That UUID was generated for this run. Commit it and never change it: it "
    "is what keeps this project's baseline from being read as another's."
)
ERR_INVALID_BASELINE_SCOPE_ID = (
    "Invalid baseline_scope_id for {path}: {error}.\n"
    "[dim]Set a stable canonical UUID under \\[tool.codeclone].[/dim]"
)
ERR_REPORT_WRITE_FAILED = (
    "[error]Failed to write {label} report: {path} ({error}).[/error]\n"
    "[dim]Check that the path is writable, then re-run with {flag}.[/dim]"
)
ERR_OPEN_HTML_REPORT_REQUIRES_HTML = (
    "[error]--open-html-report requires --html.[/error]"
)
ERR_TIMESTAMPED_REPORT_PATHS_REQUIRES_REPORT = (
    "[error]--timestamped-report-paths requires at least one report output "
    "flag.[/error]"
)
ERR_UNREADABLE_SOURCE_IN_GATING = (
    "One or more source files could not be read in CI/gating mode.\n"
    "Unreadable source files: {count}.\n"
    "[dim]Fix the file permissions or exclude the paths, then re-run "
    "codeclone with the same gates.[/dim]"
)

WARN_LEGACY_CACHE = (
    "Legacy cache file found at: {legacy_path}.\n"
    "Cache is now stored per-project at: {new_path}.\n"
    "Please delete the legacy cache file and add `.codeclone/` to .gitignore."
)
WARN_LEGACY_REPO_WORKSPACE = (
    "Legacy CodeClone workspace (.cache/codeclone/) found at: {legacy_dir}.\n"
    "Artifacts now live under: {new_dir}.\n"
    "Remove the legacy directory after you no longer need its contents."
)

# The commands every remedy names. Spelled once; every message that hands
# one over reads it from here.
ACTION_UPDATE_BASELINE = "codeclone . --update-baseline"
ACTION_CI = "codeclone . --ci"
ACTION_HTML = "codeclone . --html"
ACTION_FAIL_ON_NEW = "codeclone . --fail-on-new"
ACTION_API_SURFACE_BASELINE = "codeclone . --api-surface --update-baseline"

# The reasons a run could not compare against the baseline, worded for the
# ``New`` summary row. One vocabulary for the row, the outcome block, and the
# baseline warnings, so the three cannot describe one absence three ways.
NOVELTY_REASON_NO_BASELINE = "no baseline yet"
NOVELTY_REASON_BASELINE_IGNORED = "baseline ignored"
NOVELTY_REASON_LANES_OPAQUE = "clone lanes opaque"

# Invalid baseline, two registers. The gating register states the fact and
# leaves the remedy to the refusal that follows it; the advisory register
# is the whole story because nothing follows it.
WARN_BASELINE_INVALID = "Invalid baseline file\n{error}"
WARN_BASELINE_IGNORED = (
    "Baseline ignored: invalid file\n"
    "{error}\n"
    "Nothing can be called new this run.\n"
    "Regenerate it: " + ACTION_UPDATE_BASELINE
)
NOTE_BASELINE_FOREIGN_INTERPRETER = (
    "Baseline was taken on {baseline_tag}; this run is {runtime_tag}.\n"
    "Observations are interpreter-independent, so it is used as it is."
)
WARN_BASELINE_LANES_OPAQUE = (
    "Baseline lanes opaque for this run: {lanes}.\n"
    "No active gate reads them, so the run continues; their novelty is "
    "reported as unavailable, not as zero.\n"
    "Regenerate it: " + ACTION_UPDATE_BASELINE
)
ERR_BASELINE_CI_REQUIRES_TRUSTED = (
    "[error]CI requires a trusted baseline.[/error]\n"
    f"[dim]Create it: {ACTION_UPDATE_BASELINE}[/dim]"
)
ERR_BASELINE_GATING_REQUIRES_TRUSTED = (
    "[error]Baseline-aware gates require a trusted baseline.[/error]\n"
    f"[dim]Create it: {ACTION_UPDATE_BASELINE}[/dim]"
)
ERR_BASELINE_LANES_UNAVAILABLE = (
    "[error]Required baseline lanes are unavailable: {lanes}.[/error]\n"
    f"[dim]Regenerate it: {ACTION_UPDATE_BASELINE}[/dim]"
)
ERR_GATE_EVIDENCE_UNAVAILABLE = (
    "[error]Required gate evidence is unavailable.[/error]\n"
    f"[dim]Regenerate the baseline: {ACTION_UPDATE_BASELINE}[/dim]"
)
SUCCESS_BASELINE_UPDATED = f"  [success]{GLYPH_OK} Baseline written: {{path}}[/success]"
SUCCESS_BASELINE_LOCK_RECOVERED = (
    f"{GLYPH_OK} Baseline publication lock recovered: {{path}}"
)
ERR_BASELINE_LOCK_RECOVERY_FAILED = (
    "[error]Baseline publication lock recovery failed for {path}: "
    "{reason}.[/error]\n"
    "[dim]Verify the lock owner is gone, then retry with --force if the "
    "lock evidence is abandoned.[/dim]"
)

ERR_MEMORY_DB_NOT_FOUND = (
    "Engineering memory database not found: {error}\n"
    "[dim]Run: codeclone memory init --root <root>[/dim]"
)
ERR_MEMORY_ROOT_NOT_FOUND = (
    "Repository root does not exist: {path}\n"
    "[dim]Pass an existing directory via --root.[/dim]"
)

# ── run outcome: the last block of an analysis run ───────────────────
# Each sentence answers the question the reader has at that moment: did I
# pass, and what do I type now. The first-run register also says what the
# product is, because that is the moment the reader asks.
OUTCOME_EMPTY_SCOPE = "Nothing analyzed: no Python files under this root"
OUTCOME_EMPTY_SCOPE_NEXT = (
    "Pass a project directory that contains Python files: codeclone <root>"
)
OUTCOME_BASELINE_WRITTEN = "Baseline ready: {path}"
OUTCOME_BASELINE_WRITTEN_NEXT = "Later runs report only what changed against it."
OUTCOME_GATE_IN_CI = "Gate every change in CI:"
OUTCOME_CREATE_BASELINE = "Create the baseline:"
OUTCOME_NOT_COMPARED = "Not compared: {reason}"
OUTCOME_FIRST_RUN_WHY = (
    "CodeClone reports what changed in your code's structure against an "
    "accepted baseline; today's findings become known debt once you create one."
)
OUTCOME_FIRST_RUN_THEN = "Then gate changes in CI:"
OUTCOME_IGNORED_NEXT = "Regenerate it:"
OUTCOME_CLEAN = "Nothing new since the baseline"
OUTCOME_GATE_PASSED = "Gate passed: nothing new since the baseline"
OUTCOME_NEW_CLONES = "{count} since the baseline"
OUTCOME_NEW_CLONES_BLOCK = "Block it in CI:"
OUTCOME_NEW_CLONES_ACCEPT = "Accept as known debt:"
OUTCOME_LOCATIONS = "Locations:"
OUTCOME_API_NOT_COMPARED = "Public API not compared:"
OUTCOME_NEW_CLONES_QUIET = (
    "{count} since the baseline (--fail-on-new blocks it, --update-baseline accepts it)"
)

# Tips and notes are label rows on the grid: the label sits in the label
# field, the text in the value column, and the continuation under the text.
_TIP_LABEL = "  [dim]Tip[/dim]           "
_NOTE_LABEL = "  [dim]Note[/dim]          "
_HANG = " " * 16
TIP_VSCODE_EXTENSION = (
    f"\n{_TIP_LABEL}VS Code detected. "
    "CodeClone has a native extension for triage-first review and hotspot "
    "navigation.\n"
    f"{_HANG}[dim]{{url}}[/dim]"
)
NOTE_DEAD_CODE_REACHABILITY_2_0_1_MIGRATION = (
    f"\n{_NOTE_LABEL}Dead-code reachability was refined in 2.0.1 for "
    "common Python frameworks.\n"
    f"{_HANG}[dim]Fewer dead-code findings after upgrading from 2.0.0 are "
    "expected: this usually means reduced false positives, not weaker "
    "detection.[/dim]"
)
NOTE_DEAD_CODE_REACHABILITY_2_0_2_MIGRATION = (
    f"\n{_NOTE_LABEL}Dead-code reachability was refined again in 2.0.2.\n"
    f"{_HANG}[dim]Fewer dead-code findings after upgrading from 2.0.1 are "
    "expected: framework hooks, public exports, and guarded dynamic dispatch "
    "now produce fewer false positives, not weaker detection.[/dim]"
)
NOTE_COHESION_LCOM4_2_1_MIGRATION = (
    f"\n{_NOTE_LABEL}Class cohesion (LCOM4) applicability was refined in "
    "2.1.0.\n"
    f"{_HANG}[dim]Cohesion counts and low-cohesion class totals may change after "
    "upgrading from 2.0.2: Protocol interfaces and Pydantic validation hooks "
    "are excluded from the LCOM4 graph. This reflects tighter applicability "
    "rules, not weaker detection.[/dim]"
)
TIP_GITIGNORE_CODECLONE_CACHE = (
    f"\n{_TIP_LABEL}{{message}}\n{_HANG}[dim]Suggested entry: `{{entry}}`[/dim]"
)
NOTE_DEAD_CODE_REACHABILITY_MIGRATION = NOTE_DEAD_CODE_REACHABILITY_2_0_1_MIGRATION
