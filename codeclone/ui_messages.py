# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import platform
import shlex
import sys
import traceback
from pathlib import Path

from . import __version__
from .contracts import ISSUES_URL

BANNER_SUBTITLE = "Structural code analysis"

MARKER_CONTRACT_ERROR = "[error]CONTRACT ERROR:[/error]"
MARKER_INTERNAL_ERROR = "[error]INTERNAL ERROR:[/error]"

REPORT_BLOCK_GROUP_DISPLAY_NAME_ASSERT_PATTERN = "Assert pattern block"

HELP_VERSION = "Print the CodeClone version and exit."
HELP_ROOT = "Project root directory to scan.\nDefaults to the current directory."
HELP_MIN_LOC = "Minimum Lines of Code (LOC) required for clone analysis.\nDefault: 15."
HELP_MIN_STMT = "Minimum AST statement count required for clone analysis.\nDefault: 6."
HELP_PROCESSES = "Number of parallel worker processes.\nDefault: 4."
HELP_CACHE_PATH = (
    "Path to the cache file.\n"
    "If FILE is omitted, uses <root>/.cache/codeclone/cache.json."
)
HELP_CACHE_DIR_LEGACY = (
    "Legacy alias for --cache-path.\nPrefer --cache-path in new configurations."
)
HELP_MAX_BASELINE_SIZE_MB = "Maximum allowed baseline size in MB.\nDefault: 5."
HELP_MAX_CACHE_SIZE_MB = "Maximum cache file size in MB.\nDefault: 50."
HELP_BASELINE = (
    "Path to the clone baseline.\n"
    f"If FILE is omitted, uses {Path('codeclone.baseline.json')}."
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
    f"If FILE is omitted, uses {Path('codeclone.baseline.json')}."
)
HELP_SKIP_METRICS = "Skip full metrics analysis and run in clone-only mode."
HELP_SKIP_DEAD_CODE = "Skip dead code detection."
HELP_SKIP_DEPENDENCIES = "Skip dependency graph analysis."
HELP_HTML = (
    "Generate an HTML report.\n"
    "If FILE is omitted, writes to .cache/codeclone/report.html."
)
HELP_JSON = (
    "Generate the canonical JSON report.\n"
    "If FILE is omitted, writes to .cache/codeclone/report.json."
)
HELP_MD = (
    "Generate a Markdown report.\n"
    "If FILE is omitted, writes to .cache/codeclone/report.md."
)
HELP_SARIF = (
    "Generate a SARIF 2.1.0 report.\n"
    "If FILE is omitted, writes to .cache/codeclone/report.sarif."
)
HELP_TEXT = (
    "Generate a plain-text report.\n"
    "If FILE is omitted, writes to .cache/codeclone/report.txt."
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
    "  health={health}({grade})"
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
ERR_BASELINE_GATING_REQUIRES_TRUSTED = (
    f"[error]CI requires a trusted baseline.[/error]\n{ACTION_UPDATE_BASELINE}"
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


def fmt_legacy_cache_warning(*, legacy_path: Path, new_path: Path) -> str:
    return WARN_LEGACY_CACHE.format(legacy_path=legacy_path, new_path=new_path)


def fmt_invalid_baseline(error: object) -> str:
    return ERR_INVALID_BASELINE.format(error=error)


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
    new: int,
) -> str:
    return SUMMARY_COMPACT_CLONES.format(
        function=function,
        block=block,
        segment=segment,
        suppressed=suppressed,
        new=new,
    )


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
    )


_HEALTH_GRADE_STYLE: dict[str, str] = {
    "A": "bold green",
    "B": "green",
    "C": "yellow",
    "D": "bold red",
    "F": "bold red",
}

_L = 12  # label column width (after 2-space indent)


def _v(n: int, style: str = "") -> str:
    """Format value: dim if zero, styled otherwise."""
    if n == 0:
        return f"[dim]{n}[/dim]"
    if style:
        return f"[{style}]{n}[/{style}]"
    return str(n)


def _vn(n: int, style: str = "") -> str:
    """Format value with comma separator: dim if zero, styled otherwise."""
    if n == 0:
        return f"[dim]{n:,}[/dim]"
    if style:
        return f"[{style}]{n:,}[/{style}]"
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
    parts = [f"{_vn(lines, 'bold cyan')} lines"]
    if functions:
        parts.append(f"{_v(functions, 'bold cyan')} functions")
    if methods:
        parts.append(f"{_v(methods, 'bold cyan')} methods")
    if classes:
        parts.append(f"{_v(classes, 'bold cyan')} classes")
    val = " \u00b7 ".join(parts)
    return f"  {'Parsed':<{_L}}{val}"


def fmt_summary_clones(
    *, func: int, block: int, segment: int, suppressed: int, new: int
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
        f"{_v(new, 'bold red')} new",
    ]
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
    if count == 0:
        return f"  {'Cycles':<{_L}}[green]\u2714 clean[/green]"
    return f"  {'Cycles':<{_L}}[bold red]{count} detected[/bold red]"


def fmt_metrics_dead_code(count: int) -> str:
    if count == 0:
        return f"  {'Dead code':<{_L}}[green]\u2714 clean[/green]"
    return f"  {'Dead code':<{_L}}[bold red]{count} found[/bold red]"


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
