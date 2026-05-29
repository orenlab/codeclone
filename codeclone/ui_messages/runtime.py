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

STATUS_DISCOVERING = "[bold green]Discovering Python files..."
STATUS_GROUPING = "[bold green]Grouping clones..."

INFO_PROCESSING_CHANGED = "[info]Processing {count} changed files...[/info]"

WARN_WORKER_FAILED = "[warning]Worker failed: {error}[/warning]"
WARN_BATCH_ITEM_FAILED = "[warning]Failed to process batch item: {error}[/warning]"
WARN_PARALLEL_FALLBACK = (
    "[warning]Parallel processing unavailable, "
    "falling back to sequential: {error}[/warning]"
)
WARN_FAILED_FILES_HEADER = "\n[warning]{count} files failed to process:[/warning]"
WARN_CACHE_SAVE_FAILED = "[warning]Failed to save cache: {error}[/warning]"
WARN_HTML_REPORT_OPEN_FAILED = (
    "[warning]Failed to open HTML report in browser: {path} ({error}).[/warning]"
)
WARN_COVERAGE_JOIN_IGNORED = "[warning]Coverage join ignored: {error}[/warning]"

ERR_INVALID_OUTPUT_EXT = (
    "[error]Invalid {label} output extension: {path} "
    "(expected {expected_suffix}).[/error]"
)
ERR_INVALID_OUTPUT_PATH = (
    "[error]Invalid {label} output path: {path} ({error}).[/error]"
)
ERR_ROOT_NOT_FOUND = "[error]Root path does not exist: {path}[/error]"
ERR_INVALID_ROOT_PATH = "[error]Invalid root path: {error}[/error]"
ERR_SCAN_FAILED = "[error]Scan failed: {error}[/error]"
ERR_INVALID_BASELINE_PATH = "[error]Invalid baseline path: {path} ({error}).[/error]"
ERR_BASELINE_WRITE_FAILED = (
    "[error]Failed to write baseline file: {path} ({error}).[/error]"
)
ERR_REPORT_WRITE_FAILED = (
    "[error]Failed to write {label} report: {path} ({error}).[/error]"
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
    "Unreadable source files: {count}."
)

WARN_LEGACY_CACHE = (
    "[warning]Legacy cache file found at: {legacy_path}.[/warning]\n"
    "[warning]Cache is now stored per-project at: {new_path}.[/warning]\n"
    "[warning]Please delete the legacy cache file and add "
    ".cache/ to .gitignore.[/warning]"
)

ERR_INVALID_BASELINE = (
    "[error]Invalid baseline file.[/error]\n"
    "{error}\n"
    "Please regenerate the baseline with --update-baseline."
)
ACTION_UPDATE_BASELINE = "Run: codeclone . --update-baseline"
WARN_BASELINE_MISSING = (
    "[warning]Baseline file not found at: [bold]{path}[/bold][/warning]\n"
    "[dim]Comparing against an empty baseline. "
    "Use --update-baseline to create it.[/dim]\n"
    f"[dim]{ACTION_UPDATE_BASELINE}[/dim]"
)
WARN_BASELINE_IGNORED = (
    "[warning]Baseline is not trusted for this run and will be ignored.[/warning]\n"
    "[dim]Comparison will proceed against an empty baseline.[/dim]\n"
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
NOTE_DEAD_CODE_REACHABILITY_MIGRATION = NOTE_DEAD_CODE_REACHABILITY_2_0_1_MIGRATION
