from __future__ import annotations

import platform
import shlex
import sys
import traceback
from pathlib import Path

from . import __version__
from .contracts import ISSUES_URL

BANNER_SUBTITLE = "[italic]Architectural duplication detector[/italic]"

MARKER_CONTRACT_ERROR = "[error]CONTRACT ERROR:[/error]"
MARKER_GATING_FAILURE = "[error]GATING FAILURE:[/error]"
MARKER_INTERNAL_ERROR = "[error]INTERNAL ERROR:[/error]"

REPORT_BLOCK_GROUP_DISPLAY_NAME_ASSERT_PATTERN = "Assert pattern block"
REPORT_BLOCK_GROUP_COMPARE_NOTE_N_WAY = (
    "N-way group: each block matches {peer_count} peers in this group."
)

HELP_VERSION = "Print the CodeClone version and exit."
HELP_ROOT = "Project root directory to scan."
HELP_MIN_LOC = "Minimum Lines of Code (LOC) to consider."
HELP_MIN_STMT = "Minimum AST statements to consider."
HELP_PROCESSES = "Number of parallel worker processes."
HELP_CACHE_PATH = "Path to the cache file. Default: <root>/.cache/codeclone/cache.json."
HELP_CACHE_DIR_LEGACY = "Legacy alias for --cache-path."
HELP_MAX_BASELINE_SIZE_MB = "Maximum baseline file size in MB."
HELP_MAX_CACHE_SIZE_MB = "Maximum cache file size in MB."
HELP_BASELINE = "Path to the baseline file (stored in repo)."
HELP_UPDATE_BASELINE = "Overwrite the baseline file with current results."
HELP_FAIL_ON_NEW = "Exit with error if NEW clones (not in baseline) are detected."
HELP_FAIL_THRESHOLD = (
    "Exit with error if total clone groups (function + block) exceed this number."
)
HELP_CI = "CI preset: --fail-on-new --no-color --quiet."
HELP_HTML = "Generate an HTML report to FILE."
HELP_JSON = "Generate a JSON report to FILE."
HELP_TEXT = "Generate a text report to FILE."
HELP_NO_PROGRESS = "Disable the progress bar (recommended for CI logs)."
HELP_NO_COLOR = "Disable ANSI colors in output."
HELP_QUIET = "Minimize output (still shows warnings and errors)."
HELP_VERBOSE = "Print detailed hash identifiers for new clones."
HELP_DEBUG = "Print debug details (traceback and environment) on internal errors."

SUMMARY_TITLE = "Analysis Summary"
CLI_LAYOUT_WIDTH = 40
SUMMARY_LABEL_FILES_FOUND = "Files found"
SUMMARY_LABEL_FILES_ANALYZED = "Files analyzed"
SUMMARY_LABEL_CACHE_HITS = "Cache hits"
SUMMARY_LABEL_FILES_SKIPPED = "Files skipped"
SUMMARY_LABEL_FUNCTION = "Function clone groups"
SUMMARY_LABEL_BLOCK = "Block clone groups"
SUMMARY_LABEL_SEGMENT = "Segment clone groups"
SUMMARY_LABEL_SUPPRESSED = "Suppressed segment groups"
SUMMARY_LABEL_NEW_BASELINE = "New vs baseline"
SUMMARY_COMPACT_INPUT = (
    "Input: found={found} analyzed={analyzed} cache_hits={cache_hits} skipped={skipped}"
)
SUMMARY_COMPACT_CLONES = (
    "Clone groups: function={function} block={block} "
    "segment={segment} suppressed={suppressed} new_vs_baseline={new}"
)
WARN_SUMMARY_ACCOUNTING_MISMATCH = (
    "Summary accounting mismatch: "
    "files_found != files_analyzed + cache_hits + files_skipped"
)

STATUS_DISCOVERING = "[bold green]Discovering Python files..."
STATUS_GROUPING = "[bold green]Grouping clones..."

INFO_SCANNING_ROOT = "[info]Scanning root:[/info] {root}"
INFO_PROCESSING_CHANGED = "[info]Processing {count} changed files...[/info]"
INFO_HTML_REPORT_SAVED = "[info]HTML report saved:[/info] {path}"
INFO_JSON_REPORT_SAVED = "[info]JSON report saved:[/info] {path}"
INFO_TEXT_REPORT_SAVED = "[info]Text report saved:[/info] {path}"

WARN_SKIPPING_FILE = "[warning]Skipping file {path}: {error}[/warning]"
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

ERR_FAIL_THRESHOLD = "Total clones ({total}) exceed threshold ({threshold})."
WARN_NEW_CLONES_WITHOUT_FAIL = (
    "\n[warning]New clones detected but --fail-on-new not set.[/warning]\n"
    "Run with --update-baseline to accept them as technical debt."
)


def version_output(version: str) -> str:
    return f"CodeClone {version}"


def banner_title(version: str) -> str:
    return (
        f"[bold white]CodeClone[/bold white] [dim]v{version}[/dim]\n{BANNER_SUBTITLE}"
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


def fmt_scanning_root(root: Path) -> str:
    return INFO_SCANNING_ROOT.format(root=root)


def fmt_processing_changed(count: int) -> str:
    return INFO_PROCESSING_CHANGED.format(count=count)


def fmt_skipping_file(path: str, error: object) -> str:
    return WARN_SKIPPING_FILE.format(path=path, error=error)


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


def fmt_summary_compact_input(
    *, found: int, analyzed: int, cache_hits: int, skipped: int
) -> str:
    return SUMMARY_COMPACT_INPUT.format(
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


def fmt_fail_threshold(*, total: int, threshold: int) -> str:
    return ERR_FAIL_THRESHOLD.format(total=total, threshold=threshold)


def fmt_contract_error(message: str) -> str:
    return f"{MARKER_CONTRACT_ERROR}\n{message}"


def fmt_gating_failure(message: str) -> str:
    return f"{MARKER_GATING_FAILURE}\n{message}"


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


def fmt_report_block_group_compare_note_n_way(*, peer_count: int) -> str:
    return REPORT_BLOCK_GROUP_COMPARE_NOTE_N_WAY.format(peer_count=peer_count)
