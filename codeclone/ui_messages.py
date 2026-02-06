from __future__ import annotations

from pathlib import Path

BANNER_SUBTITLE = "[italic]Architectural duplication detector[/italic]"

HELP_VERSION = "Print the CodeClone version and exit."
HELP_ROOT = "Project root directory to scan."
HELP_MIN_LOC = "Minimum Lines of Code (LOC) to consider."
HELP_MIN_STMT = "Minimum AST statements to consider."
HELP_PROCESSES = "Number of parallel worker processes."
HELP_CACHE_PATH = "Path to the cache file. Default: <root>/.cache/codeclone/cache.json."
HELP_CACHE_DIR_LEGACY = "Legacy alias for --cache-path."
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

SUMMARY_TITLE = "Analysis Summary"
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
ERR_ROOT_NOT_FOUND = "[error]Root path does not exist: {path}[/error]"
ERR_INVALID_ROOT_PATH = "[error]Invalid root path: {error}[/error]"
ERR_SCAN_FAILED = "[error]Scan failed: {error}[/error]"

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
ERR_BASELINE_VERSION_MISMATCH = "[error]Baseline version mismatch.[/error]"
ERR_BASELINE_SCHEMA_MISMATCH = "[error]Baseline schema version mismatch.[/error]"
WARN_BASELINE_PYTHON_MISMATCH = "[warning]Baseline Python version mismatch.[/warning]"
ERR_BASELINE_SAME_PYTHON_REQUIRED = (
    "[error]Baseline checks require the same Python version to "
    "ensure deterministic results. Please regenerate the "
    "baseline using the current interpreter.[/error]"
)
WARN_BASELINE_MISSING = (
    "[warning]Baseline file not found at: [bold]{path}[/bold][/warning]\n"
    "[dim]Comparing against an empty baseline. "
    "Use --update-baseline to create it.[/dim]"
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

ERR_FAIL_THRESHOLD = (
    "\n[error]❌ FAILED: Total clones ({total}) exceed threshold ({threshold})![/error]"
)
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


def fmt_baseline_version_missing(current_version: str) -> str:
    return (
        f"{ERR_BASELINE_VERSION_MISMATCH}\n"
        "Baseline version missing (legacy baseline format).\n"
        f"Current version: {current_version}.\n"
        "Please regenerate the baseline with --update-baseline."
    )


def fmt_baseline_version_mismatch(
    *, baseline_version: str, current_version: str
) -> str:
    return (
        f"{ERR_BASELINE_VERSION_MISMATCH}\n"
        "Baseline was generated with CodeClone "
        f"{baseline_version}.\n"
        f"Current version: {current_version}.\n"
        "Please regenerate the baseline with --update-baseline."
    )


def fmt_baseline_schema_mismatch(*, baseline_schema: int, current_schema: int) -> str:
    return (
        f"{ERR_BASELINE_SCHEMA_MISMATCH}\n"
        f"Baseline schema: {baseline_schema}. "
        f"Current schema: {current_schema}.\n"
        "Please regenerate the baseline with --update-baseline."
    )


def fmt_baseline_python_mismatch(*, baseline_python: str, current_python: str) -> str:
    return (
        f"{WARN_BASELINE_PYTHON_MISMATCH}\n"
        "Baseline was generated with Python "
        f"{baseline_python}.\n"
        f"Current interpreter: Python {current_python}."
    )


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
