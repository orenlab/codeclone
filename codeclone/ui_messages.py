from __future__ import annotations

import platform
import shlex
import sys
import traceback
from pathlib import Path

from . import __version__
from .contracts import ISSUES_URL

BANNER_SUBTITLE = "[italic]Architectural duplication and code-health analysis[/italic]"

MARKER_CONTRACT_ERROR = "[error]CONTRACT ERROR:[/error]"
MARKER_INTERNAL_ERROR = "[error]INTERNAL ERROR:[/error]"

REPORT_BLOCK_GROUP_DISPLAY_NAME_ASSERT_PATTERN = "Assert pattern block"

HELP_VERSION = "Print the CodeClone version and exit."
HELP_ROOT = "Project root directory to scan."
HELP_MIN_LOC = "Minimum Lines of Code (LOC) to consider."
HELP_MIN_STMT = "Minimum AST statements to consider."
HELP_PROCESSES = "Number of parallel worker processes."
HELP_CACHE_PATH = "Path to the cache file. Default: <root>/.cache/codeclone/cache.json."
HELP_CACHE_DIR_LEGACY = "Legacy alias for --cache-path."
HELP_MAX_BASELINE_SIZE_MB = "Maximum baseline file size in MB."
HELP_MAX_CACHE_SIZE_MB = "Maximum cache file size in MB."
HELP_BASELINE = "Path to baseline file (omit value to use default path)."
HELP_UPDATE_BASELINE = "Overwrite the baseline file with current results."
HELP_FAIL_ON_NEW = "Exit with error if NEW clones (not in baseline) are detected."
HELP_FAIL_THRESHOLD = (
    "Exit with error if total clone groups (function + block) exceed this number."
)
HELP_FAIL_COMPLEXITY = "Exit with error if any function has CC above this threshold."
HELP_FAIL_COUPLING = "Exit with error if any class has CBO above this threshold."
HELP_FAIL_COHESION = "Exit with error if any class has LCOM4 above this threshold."
HELP_FAIL_CYCLES = "Exit with error if circular module dependencies are detected."
HELP_FAIL_DEAD_CODE = "Exit with error if high-confidence dead code is detected."
HELP_FAIL_HEALTH = "Exit with error if health score is below this threshold."
HELP_FAIL_ON_NEW_METRICS = (
    "Exit with error if new metric violations appear vs metrics baseline."
)
HELP_CI = "CI preset: --fail-on-new --no-color --quiet."
HELP_UPDATE_METRICS_BASELINE = "Overwrite metrics baseline with current metrics."
HELP_METRICS_BASELINE = (
    "Path to metrics baseline file (omit value to use default path)."
)
HELP_SKIP_METRICS = "Skip full metrics analysis (clone-only mode)."
HELP_SKIP_DEAD_CODE = "Skip dead code detection stage."
HELP_SKIP_DEPENDENCIES = "Skip dependency graph analysis stage."
HELP_HTML = (
    "Generate HTML report (optional FILE, default: .cache/codeclone/report.html)."
)
HELP_JSON = (
    "Generate JSON report (optional FILE, default: .cache/codeclone/report.json)."
)
HELP_TEXT = (
    "Generate text report (optional FILE, default: .cache/codeclone/report.txt)."
)
HELP_NO_PROGRESS = "Disable the progress bar (recommended for CI logs)."
HELP_PROGRESS = "Enable progress bar output."
HELP_NO_COLOR = "Disable ANSI colors in output."
HELP_COLOR = "Enable ANSI colors in output."
HELP_QUIET = "Minimize output (still shows warnings and errors)."
HELP_VERBOSE = "Print detailed hash identifiers for new clones."
HELP_DEBUG = "Print debug details (traceback and environment) on internal errors."

SUMMARY_TITLE = "Analysis Summary"
METRICS_TITLE = "Quality Metrics"
REPORTS_TITLE = "Reports"

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
    "Summary  found={found}  analyzed={analyzed}  cache={cache_hits}  skipped={skipped}"
)
SUMMARY_COMPACT_CLONES = (
    "Clones   func={function}  block={block}  seg={segment}"
    "  suppressed={suppressed}  new={new}"
)
SUMMARY_COMPACT_METRICS = (
    "Metrics  CC={cc_avg}/{cc_max}  CBO={cbo_avg}/{cbo_max}"
    "  LCOM4={lcom_avg}/{lcom_max}  cycles={cycles}  dead={dead}"
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


def cli_layout_width(console_width: int | None) -> int:
    return min(console_width or 80, CLI_LAYOUT_MAX_WIDTH)


def version_output(version: str) -> str:
    return f"CodeClone {version}"


def banner_title(version: str, *, root: Path | None = None) -> str:
    line1 = (
        f"[bold white]CodeClone[/bold white] [dim]v{version}[/dim]"
        f"  [dim]·[/dim]  {BANNER_SUBTITLE}"
    )
    if root is None:
        return line1
    return f"{line1}\n[dim]{root}[/dim]"


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
