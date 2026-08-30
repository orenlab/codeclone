# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""CLI runtime status, warning, error, and gate messages."""

from __future__ import annotations

WARN_SUMMARY_ACCOUNTING_MISMATCH = (
    "Summary accounting mismatch: "
    "files_found != files_analyzed + cache_hits + files_skipped"
)

STATUS_DISCOVERING = "[success]Discovering Python files...[/success]"
STATUS_GROUPING = "[success]Grouping clones...[/success]"

INFO_PROCESSING_CHANGED = "[info]Processing {count} changed files...[/info]"

WARN_WORKER_FAILED = "[warning]Worker failed: {error}[/warning]"
WARN_BATCH_ITEM_FAILED = "[warning]Failed to process batch item: {error}[/warning]"
WARN_PARALLEL_FALLBACK = (
    "[warning]Parallel processing unavailable, "
    "falling back to sequential: {error}[/warning]"
)
WARN_FAILED_FILES_HEADER = "\n[warning]{count} files failed to process:[/warning]"
WARN_UNSUPPORTED_CONSTRUCT_SUMMARY = (
    "[warning]{count} files not analyzed: unsupported syntax ({constructs})[/warning]"
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
    "[warning]Legacy cache file found at: {legacy_path}.[/warning]\n"
    "[warning]Cache is now stored per-project at: {new_path}.[/warning]\n"
    "[warning]Please delete the legacy cache file and add "
    "`.codeclone/` to .gitignore.[/warning]"
)
WARN_LEGACY_REPO_WORKSPACE = (
    "[warning]Legacy CodeClone workspace (.cache/codeclone/) found at: "
    "{legacy_dir}.[/warning]\n"
    "[warning]Artifacts now live under: {new_dir}.[/warning]\n"
    "[warning]Remove the legacy directory after you no longer need its "
    "contents.[/warning]"
)

ERR_INVALID_BASELINE = (
    "[error]Invalid baseline file.[/error]\n"
    "{error}\n"
    "Please regenerate the baseline with --update-baseline."
)
ACTION_UPDATE_BASELINE = "Run: codeclone . --update-baseline"
WARN_BASELINE_MISSING = (
    "[warning]Baseline file not found at: [bold]{path}[/bold][/warning]\n"
    "[dim]Baseline-relative novelty is unavailable. "
    "Use --update-baseline to create it.[/dim]\n"
    f"[dim]{ACTION_UPDATE_BASELINE}[/dim]"
)
WARN_BASELINE_IGNORED = (
    "[warning]Baseline is not trusted for this run and will be ignored.[/warning]\n"
    "[dim]Baseline-relative novelty is unavailable for this run.[/dim]\n"
    f"[dim]{ACTION_UPDATE_BASELINE}[/dim]"
)
NOTE_BASELINE_FOREIGN_INTERPRETER = (
    "[dim]Baseline was taken on [bold]{baseline_tag}[/bold]; "
    "this run is [bold]{runtime_tag}[/bold].[/dim]\n"
    "[dim]Observations are interpreter-independent, so the baseline is used "
    "and its novelty is comparable. This note is about where the reference "
    "came from, not about whether it is trusted.[/dim]"
)
WARN_BASELINE_LANES_OPAQUE = (
    "[warning]Baseline lanes are opaque for this run: [bold]{lanes}[/bold][/warning]\n"
    "[dim]No active gate reads them, so the run continues. "
    "Their baseline-relative novelty is reported as unavailable, "
    "not as zero.[/dim]\n"
    f"[dim]{ACTION_UPDATE_BASELINE}[/dim]"
)
ERR_BASELINE_CI_REQUIRES_TRUSTED = (
    f"[error]CI requires a trusted baseline.[/error]\n{ACTION_UPDATE_BASELINE}"
)
ERR_BASELINE_GATING_REQUIRES_TRUSTED = (
    "[error]Baseline-aware gates require a trusted baseline.[/error]\n"
    f"{ACTION_UPDATE_BASELINE}"
)
SUCCESS_BASELINE_UPDATED = "✔ Baseline updated: {path}"
SUCCESS_BASELINE_LOCK_RECOVERED = "✔ Baseline publication lock recovered: {path}"
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

FAIL_NEW_TITLE = "[error]FAILED: New code clones detected.[/error]"
FAIL_NEW_SUMMARY_TITLE = "Summary:"
FAIL_NEW_FUNCTION = "- New function clone groups: {count}"
FAIL_NEW_BLOCK = "- New block clone groups: {count}"
FAIL_NEW_REPORT_TITLE = "See detailed report:"
FAIL_NEW_ACCEPT_TITLE = "To accept these clones as technical debt, run:"
FAIL_NEW_ACCEPT_COMMAND = "  codeclone . --update-baseline"
FAIL_NEW_DETAIL_FUNCTION = "Details (function clone hashes):"
FAIL_NEW_DETAIL_BLOCK = "Details (block clone hashes):"
FAIL_METRICS_TITLE = "[error]FAILED: Metrics quality gate triggered.[/error]"

WARN_NEW_CLONES_WITHOUT_FAIL = (
    "\n[warning]New clones detected but --fail-on-new not set.[/warning]\n"
    "Run with --update-baseline to accept them as technical debt."
)
TIP_VSCODE_EXTENSION = (
    "\n[dim]Tip:[/dim] VS Code detected. "
    "CodeClone has a native extension for triage-first review and hotspot "
    "navigation.\n"
    "[dim]{url}[/dim]"
)
NOTE_DEAD_CODE_REACHABILITY_2_0_1_MIGRATION = (
    "\n[dim]Note:[/dim] Dead-code reachability was refined in 2.0.1 for "
    "common Python frameworks.\n"
    "[dim]Fewer dead-code findings after upgrading from 2.0.0 are expected: "
    "this usually means reduced false positives, not weaker detection.[/dim]"
)
NOTE_DEAD_CODE_REACHABILITY_2_0_2_MIGRATION = (
    "\n[dim]Note:[/dim] Dead-code reachability was refined again in 2.0.2.\n"
    "[dim]Fewer dead-code findings after upgrading from 2.0.1 are expected: "
    "framework hooks, public exports, and guarded dynamic dispatch now produce "
    "fewer false positives, not weaker detection.[/dim]"
)
NOTE_COHESION_LCOM4_2_1_MIGRATION = (
    "\n[dim]Note:[/dim] Class cohesion (LCOM4) applicability was refined in "
    "2.1.0.\n"
    "[dim]Cohesion counts and low-cohesion class totals may change after "
    "upgrading from 2.0.2: Protocol interfaces and Pydantic validation hooks "
    "are excluded from the LCOM4 graph. This reflects tighter applicability "
    "rules, not weaker detection.[/dim]"
)
TIP_GITIGNORE_CODECLONE_CACHE = (
    "\n[dim]Tip:[/dim] {message}\n[dim]Suggested entry: `{entry}`[/dim]"
)
NOTE_DEAD_CODE_REACHABILITY_MIGRATION = NOTE_DEAD_CODE_REACHABILITY_2_0_1_MIGRATION
