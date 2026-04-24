# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import platform
import re
import shlex
import sys
import textwrap
import traceback
from pathlib import Path

from .. import __version__
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
    ISSUES_URL,
)
from ..domain.quality import (
    HEALTH_GRADE_A,
    HEALTH_GRADE_B,
    HEALTH_GRADE_C,
    HEALTH_GRADE_D,
    HEALTH_GRADE_F,
)

BANNER_SUBTITLE = "Structural code analysis"

MARKER_CONTRACT_ERROR = "[error]CONTRACT ERROR:[/error]"
MARKER_INTERNAL_ERROR = "[error]INTERNAL ERROR:[/error]"

REPORT_BLOCK_GROUP_DISPLAY_NAME_ASSERT_PATTERN = "Assert pattern block"

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

SUMMARY_TITLE = "Summary"
METRICS_TITLE = "Metrics"
CHANGED_SCOPE_TITLE = "Changed Scope"

CLI_LAYOUT_MAX_WIDTH = 80

SUMMARY_LABEL_FILES_FOUND = "Files found"
SUMMARY_LABEL_FILES_ANALYZED = "  analyzed"
SUMMARY_LABEL_CACHE_HITS = "  from cache"
SUMMARY_LABEL_FILES_SKIPPED = "  skipped"
SUMMARY_LABEL_LINES_ANALYZED = "Lines (this run)"
SUMMARY_LABEL_FUNCTIONS_ANALYZED = "Functions (this run)"
SUMMARY_LABEL_METHODS_ANALYZED = "Methods (this run)"
SUMMARY_LABEL_CLASSES_ANALYZED = "Classes (this run)"
SUMMARY_LABEL_FUNCTION = "Function clones"
SUMMARY_LABEL_BLOCK = "Block clones"
SUMMARY_LABEL_SEGMENT = "Segment clones"
SUMMARY_LABEL_SUPPRESSED = "  suppressed"
SUMMARY_LABEL_NEW_BASELINE = "New vs baseline"

SUMMARY_COMPACT = (
    "Summary  found={found}  analyzed={analyzed}"
    "  cached={cache_hits}  skipped={skipped}"
)
SUMMARY_COMPACT_CLONES = (
    "Clones   func={function}  block={block}  seg={segment}"
    "  suppressed={suppressed}  new={new}"
)
SUMMARY_COMPACT_METRICS = (
    "Metrics  cc={cc_avg}/{cc_max}  cbo={cbo_avg}/{cbo_max}"
    "  lcom4={lcom_avg}/{lcom_max}  cycles={cycles}  dead_code={dead}"
    "  health={health}({grade})  overloaded_modules={overloaded_modules}"
)
SUMMARY_COMPACT_DEPENDENCIES = (
    "Dependencies  avg={avg_depth}  p95={p95_depth}  max={max_depth}"
)
SUMMARY_COMPACT_CHANGED_SCOPE = (
    "Changed  paths={paths}  findings={findings}  new={new}  known={known}"
)

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

_RICH_MARKUP_TAG_RE = re.compile(r"\[/?[a-zA-Z][a-zA-Z0-9_ .#:-]*]")


def version_output(version: str) -> str:
    return f"CodeClone {version}"


def banner_title(version: str) -> str:
    return (
        f"  [bold white]CodeClone[/bold white] [dim]v{version}[/dim]"
        f"  [dim]\u00b7[/dim]  [dim]{BANNER_SUBTITLE}[/dim]"
    )


def fmt_invalid_output_extension(
    *, label: str, path: Path, expected_suffix: str
) -> str:
    return ERR_INVALID_OUTPUT_EXT.format(
        label=label, path=path, expected_suffix=expected_suffix
    )


def fmt_invalid_output_path(*, label: str, path: Path, error: object) -> str:
    return ERR_INVALID_OUTPUT_PATH.format(label=label, path=path, error=error)


def fmt_invalid_baseline_path(*, path: Path, error: object) -> str:
    return ERR_INVALID_BASELINE_PATH.format(path=path, error=error)


def fmt_baseline_write_failed(*, path: Path, error: object) -> str:
    return ERR_BASELINE_WRITE_FAILED.format(path=path, error=error)


def fmt_report_write_failed(*, label: str, path: Path, error: object) -> str:
    return ERR_REPORT_WRITE_FAILED.format(label=label, path=path, error=error)


def fmt_html_report_open_failed(*, path: Path, error: object) -> str:
    return WARN_HTML_REPORT_OPEN_FAILED.format(path=path, error=error)


def fmt_coverage_join_ignored(error: object) -> str:
    return WARN_COVERAGE_JOIN_IGNORED.format(error=error)


def fmt_unreadable_source_in_gating(*, count: int) -> str:
    return ERR_UNREADABLE_SOURCE_IN_GATING.format(count=count)


def fmt_processing_changed(count: int) -> str:
    return INFO_PROCESSING_CHANGED.format(count=count)


def fmt_worker_failed(error: object) -> str:
    return WARN_WORKER_FAILED.format(error=error)


def fmt_batch_item_failed(error: object) -> str:
    return WARN_BATCH_ITEM_FAILED.format(error=error)


def fmt_parallel_fallback(error: object) -> str:
    return WARN_PARALLEL_FALLBACK.format(error=error)


def fmt_failed_files_header(count: int) -> str:
    return WARN_FAILED_FILES_HEADER.format(count=count)


def fmt_cache_save_failed(error: object) -> str:
    return WARN_CACHE_SAVE_FAILED.format(error=error)


def fmt_vscode_extension_tip(*, url: str) -> str:
    return TIP_VSCODE_EXTENSION.format(url=url)


def fmt_legacy_cache_warning(*, legacy_path: Path, new_path: Path) -> str:
    return WARN_LEGACY_CACHE.format(legacy_path=legacy_path, new_path=new_path)


def fmt_invalid_baseline(error: object) -> str:
    return ERR_INVALID_BASELINE.format(error=error)


def fmt_baseline_gating_requires_trusted(*, ci: bool) -> str:
    return (
        ERR_BASELINE_CI_REQUIRES_TRUSTED if ci else ERR_BASELINE_GATING_REQUIRES_TRUSTED
    )


def fmt_cli_runtime_warning(message: object) -> str:
    source = _RICH_MARKUP_TAG_RE.sub("", str(message)).strip()
    paragraphs = [
        line.strip() for raw_line in source.splitlines() if (line := raw_line.strip())
    ]
    rendered: list[str] = []
    for index, paragraph in enumerate(paragraphs):
        label = "Warning"
        body = paragraph.rstrip()
        lowered = body.lower()
        if lowered.startswith("cache "):
            label = "Cache"
            body = body[6:]
        elif lowered.startswith("baseline "):
            label = "Baseline"
            body = body[9:]
        elif lowered.startswith("legacy cache "):
            label = "Cache"

        segments = [segment.strip() for segment in body.split("; ") if segment.strip()]
        head = segments[0].rstrip(".)") if segments else body.rstrip(".)")
        details: list[str] = []
        if " (" in head:
            head, extra = head.split(" (", 1)
            details.append(extra.rstrip(".)"))
        if not details and ": " in head:
            head, extra = head.split(": ", 1)
            details.append(extra.rstrip(".)"))
        details.extend(segment.rstrip(".)") for segment in segments[1:])

        rendered.append(f"  [warning]{label}[/warning] {head}")
        for detail in details:
            rendered.extend(
                [
                    f"    [dim]{wrapped}[/dim]"
                    for wrapped in textwrap.wrap(
                        detail,
                        width=max(40, CLI_LAYOUT_MAX_WIDTH - 8),
                        break_long_words=False,
                        break_on_hyphens=False,
                    )
                ]
            )
        if index != len(paragraphs) - 1:
            rendered.append("")
    return "\n".join(rendered)


def fmt_path(template: str, path: Path) -> str:
    return template.format(path=path)


def fmt_summary_compact(
    *, found: int, analyzed: int, cache_hits: int, skipped: int
) -> str:
    return SUMMARY_COMPACT.format(
        found=found, analyzed=analyzed, cache_hits=cache_hits, skipped=skipped
    )


def fmt_summary_compact_clones(
    *,
    function: int,
    block: int,
    segment: int,
    suppressed: int,
    fixture_excluded: int,
    new: int,
) -> str:
    parts = [
        f"Clones   func={function}",
        f"block={block}",
        f"seg={segment}",
        f"suppressed={suppressed}",
    ]
    if fixture_excluded > 0:
        parts.append(f"fixtures={fixture_excluded}")
    parts.append(f"new={new}")
    return "  ".join(parts)


def fmt_summary_compact_metrics(
    *,
    cc_avg: float,
    cc_max: int,
    cbo_avg: float,
    cbo_max: int,
    lcom_avg: float,
    lcom_max: int,
    cycles: int,
    dead: int,
    health: int,
    grade: str,
    overloaded_modules: int,
) -> str:
    return SUMMARY_COMPACT_METRICS.format(
        cc_avg=f"{cc_avg:.1f}",
        cc_max=cc_max,
        cbo_avg=f"{cbo_avg:.1f}",
        cbo_max=cbo_max,
        lcom_avg=f"{lcom_avg:.1f}",
        lcom_max=lcom_max,
        cycles=cycles,
        dead=dead,
        health=health,
        grade=grade,
        overloaded_modules=overloaded_modules,
    )


def fmt_summary_compact_dependencies(
    *,
    avg_depth: float,
    p95_depth: int,
    max_depth: int,
) -> str:
    return SUMMARY_COMPACT_DEPENDENCIES.format(
        avg_depth=f"{avg_depth:.1f}",
        p95_depth=p95_depth,
        max_depth=max_depth,
    )


def fmt_summary_compact_adoption(
    *,
    param_permille: int,
    return_permille: int,
    docstring_permille: int,
    any_annotation_count: int,
) -> str:
    return (
        "Adoption"
        f"  params={_format_permille_pct(param_permille)}"
        f"  returns={_format_permille_pct(return_permille)}"
        f"  docstrings={_format_permille_pct(docstring_permille)}"
        f"  any={any_annotation_count}"
    )


def fmt_summary_compact_api_surface(
    *,
    public_symbols: int,
    modules: int,
    added: int,
    breaking: int,
) -> str:
    return (
        "Public API"
        f"  symbols={public_symbols}"
        f"  modules={modules}"
        f"  breaking={breaking}"
        f"  added={added}"
    )


def fmt_summary_compact_coverage_join(
    *,
    status: str,
    overall_permille: int,
    coverage_hotspots: int,
    scope_gap_hotspots: int,
    threshold_percent: int,
    source_label: str,
) -> str:
    parts = [f"Coverage  status={status or 'unknown'}"]
    if status == "ok":
        parts.extend(
            [
                f"overall={_format_permille_pct(overall_permille)}",
                f"coverage_hotspots={coverage_hotspots}",
                f"threshold={threshold_percent}",
            ]
        )
        if scope_gap_hotspots > 0:
            parts.append(f"scope_gaps={scope_gap_hotspots}")
    if source_label:
        parts.append(f"source={source_label}")
    return "  ".join(parts)


_HEALTH_GRADE_STYLE: dict[str, str] = {
    HEALTH_GRADE_A: "bold green",
    HEALTH_GRADE_B: "green",
    HEALTH_GRADE_C: "yellow",
    HEALTH_GRADE_D: "bold red",
    HEALTH_GRADE_F: "bold red",
}

_L = 13  # label column width (after 2-space indent)


def _v(n: int, style: str = "") -> str:
    """Format value: dim if zero, styled otherwise."""
    match (n == 0, bool(style)):
        case (True, _):
            return f"[dim]{n}[/dim]"
        case (False, True):
            return f"[{style}]{n}[/{style}]"
        case _:
            return str(n)


def _vn(n: int, style: str = "") -> str:
    """Format value with comma separator: dim if zero, styled otherwise."""
    match (n == 0, bool(style)):
        case (True, _):
            return f"[dim]{n:,}[/dim]"
        case (False, True):
            return f"[{style}]{n:,}[/{style}]"
        case _:
            return f"{n:,}"


def fmt_summary_files(*, found: int, analyzed: int, cached: int, skipped: int) -> str:
    parts = [
        f"{_v(found, 'bold')} found",
        f"{_v(analyzed, 'bold cyan')} analyzed",
        f"{_v(cached)} cached",
        f"{_v(skipped)} skipped",
    ]
    val = " \u00b7 ".join(parts)
    return f"  {'Files':<{_L}}{val}"


def fmt_summary_parsed(
    *, lines: int, functions: int, methods: int, classes: int
) -> str | None:
    if lines == 0 and functions == 0 and methods == 0 and classes == 0:
        return None
    callable_count = functions + methods
    parts = [f"{_vn(lines, 'bold cyan')} lines"]
    if callable_count:
        parts.append(f"{_v(callable_count, 'bold cyan')} callables")
    if classes:
        parts.append(f"{_v(classes, 'bold cyan')} classes")
    val = " \u00b7 ".join(parts)
    return f"  {'Parsed':<{_L}}{val}"


def fmt_summary_clones(
    *,
    func: int,
    block: int,
    segment: int,
    suppressed: int,
    fixture_excluded: int,
    new: int,
) -> str:
    clone_parts = [
        f"{_v(func, 'bold yellow')} func",
        f"{_v(block, 'bold yellow')} block",
    ]
    if segment:
        clone_parts.append(f"{_v(segment, 'bold yellow')} seg")
    main = " \u00b7 ".join(clone_parts)
    quals = [
        f"{_v(suppressed, 'yellow')} suppressed",
    ]
    if fixture_excluded > 0:
        quals.append(f"{_v(fixture_excluded, 'yellow')} fixtures")
    quals.append(f"{_v(new, 'bold red')} new")
    return f"  {'Clones':<{_L}}{main} ({', '.join(quals)})"


def fmt_metrics_health(total: int, grade: str) -> str:
    s = _HEALTH_GRADE_STYLE.get(grade, "bold")
    return f"  {'Health':<{_L}}[{s}]{total}/100 ({grade})[/{s}]"


def fmt_metrics_cc(avg: float, max_val: int, high_risk: int) -> str:
    hr = (
        f"[bold red]{high_risk} high-risk[/bold red]"
        if high_risk
        else "[dim]0 high-risk[/dim]"
    )
    return f"  {'CC':<{_L}}avg {avg:.1f} \u00b7 max {max_val} \u00b7 {hr}"


def fmt_metrics_coupling(avg: float, max_val: int) -> str:
    return f"  {'Coupling':<{_L}}avg {avg:.1f} \u00b7 max {max_val}"


def fmt_metrics_cohesion(avg: float, max_val: int) -> str:
    return f"  {'Cohesion':<{_L}}avg {avg:.1f} \u00b7 max {max_val}"


def fmt_metrics_cycles(count: int) -> str:
    match count:
        case 0:
            return f"  {'Cycles':<{_L}}[green]\u2714 clean[/green]"
        case _:
            return f"  {'Cycles':<{_L}}[bold red]{count} detected[/bold red]"


def fmt_metrics_dependencies(
    *, avg_depth: float, p95_depth: int, max_depth: int
) -> str:
    return (
        f"  {'Dependencies':<{_L}}"
        f"avg {avg_depth:.1f} · p95 {p95_depth} · max {max_depth}"
    )


def fmt_metrics_dead_code(count: int, *, suppressed: int = 0) -> str:
    suppressed_suffix = (
        f" [dim]({suppressed} suppressed)[/dim]" if suppressed > 0 else ""
    )
    match count:
        case 0:
            return (
                f"  {'Dead code':<{_L}}[green]\u2714 clean[/green]{suppressed_suffix}"
            )
        case _:
            return (
                f"  {'Dead code':<{_L}}[bold red]{count} found[/bold red]"
                f"{suppressed_suffix}"
            )


def _format_permille_pct(value: int) -> str:
    return f"{value / 10.0:.1f}%"


def fmt_metrics_adoption(
    *,
    param_permille: int,
    return_permille: int,
    docstring_permille: int,
    any_annotation_count: int,
) -> str:
    parts = [
        f"params {_format_permille_pct(param_permille)}",
        f"returns {_format_permille_pct(return_permille)}",
        f"docstrings {_format_permille_pct(docstring_permille)}",
        f"Any {_v(any_annotation_count)}",
    ]
    return f"  {'Adoption':<{_L}}{' · '.join(parts)}"


def fmt_metrics_api_surface(
    *,
    public_symbols: int,
    modules: int,
    added: int,
    breaking: int,
) -> str:
    parts = [
        f"{_v(public_symbols, 'bold cyan')} symbols",
        f"{_v(modules, 'bold cyan')} modules",
    ]
    if breaking > 0 or added > 0:
        parts.append(
            " / ".join(
                [
                    f"{_v(breaking, 'bold red')} breaking",
                    f"{_v(added, 'bold cyan')} added",
                ]
            )
        )
    return f"  {'Public API':<{_L}}{' · '.join(parts)}"


def fmt_metrics_coverage_join(
    *,
    status: str,
    overall_permille: int,
    coverage_hotspots: int,
    scope_gap_hotspots: int,
    threshold_percent: int,
    source_label: str,
) -> str:
    if status != "ok":
        parts = ["join unavailable"]
        if source_label:
            parts.append(source_label)
        return f"  {'Coverage':<{_L}}[yellow]{' · '.join(parts)}[/yellow]"
    parts = [
        f"{_format_permille_pct(overall_permille)} overall",
        f"{_v(coverage_hotspots, 'bold red')} hotspots < {threshold_percent}%",
    ]
    if scope_gap_hotspots > 0:
        parts.append(f"{_v(scope_gap_hotspots, 'bold yellow')} scope gaps")
    if source_label:
        parts.append(source_label)
    return f"  {'Coverage':<{_L}}{' · '.join(parts)}"


def fmt_metrics_overloaded_modules(
    *,
    candidates: int,
    total: int,
    population_status: str,
    top_score: float,
) -> str:
    parts = [f"{_v(candidates, 'bold magenta')} candidates"]
    if top_score > 0:
        parts.append(f"max score {top_score:.2f}")
    parts.append(f"{_vn(total)} ranked")
    summary = " \u00b7 ".join(parts)
    note = "report-only"
    if population_status and population_status != "ok":
        note = f"{note}; {population_status.replace('_', ' ')} population"
    return f"  {'Overloaded':<{_L}}{summary} [dim]({note})[/dim]"


def fmt_changed_scope_paths(*, count: int) -> str:
    return f"  {'Paths':<{_L}}{_v(count, 'bold cyan')} from git diff"


def fmt_changed_scope_findings(*, total: int, new: int, known: int) -> str:
    parts = [
        f"{_v(total, 'bold')} total",
        f"{_v(new, 'bold cyan')} new",
        f"{_v(known)} known",
    ]
    separator = " \u00b7 "
    return f"  {'Findings':<{_L}}{separator.join(parts)}"


def fmt_changed_scope_compact(
    *,
    paths: int,
    findings: int,
    new: int,
    known: int,
) -> str:
    return SUMMARY_COMPACT_CHANGED_SCOPE.format(
        paths=paths,
        findings=findings,
        new=new,
        known=known,
    )


def fmt_pipeline_done(elapsed: float) -> str:
    return f"  [dim]Pipeline done in {elapsed:.2f}s[/dim]"


def fmt_contract_error(message: str) -> str:
    return f"{MARKER_CONTRACT_ERROR}\n{message}"


def fmt_internal_error(
    error: BaseException,
    *,
    issues_url: str = ISSUES_URL,
    debug: bool = False,
) -> str:
    bug_report_url = issues_url.rstrip("/") + "/new?template=bug_report.yml"
    error_name = type(error).__name__
    error_text = str(error).strip() or "<no message>"
    lines = [
        MARKER_INTERNAL_ERROR,
        "Unexpected exception.",
        f"Reason: {error_name}: {error_text}",
        "",
        "Next steps:",
        "- Re-run with --debug to include a traceback.",
        f"- If this is reproducible, open an issue: {bug_report_url}.",
        (
            "- Attach: command line, CodeClone version, Python version, "
            "and the report file if generated."
        ),
    ]
    if not debug:
        return "\n".join(lines)

    traceback_lines = traceback.format_exception(
        type(error), error, error.__traceback__
    )
    command_line = shlex.join(sys.argv)
    lines.extend(
        [
            "",
            "DEBUG DETAILS",
            f"Platform: {platform.platform()}",
            f"Python: {sys.version.split()[0]}",
            f"CodeClone: {__version__}",
            f"Command: {command_line}",
            f"CWD: {Path.cwd()}",
            "Traceback:",
            "".join(traceback_lines).rstrip(),
        ]
    )
    return "\n".join(lines)
