from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.theme import Theme

from . import __version__
from .baseline import BASELINE_SCHEMA_VERSION, Baseline
from .cache import Cache, CacheEntry, FileStat, file_stat_signature
from .errors import CacheError
from .extractor import extract_units_from_source
from .html_report import build_html_report
from .normalize import NormalizationConfig
from .report import (
    build_block_groups,
    build_groups,
    build_segment_groups,
    prepare_segment_report_groups,
    to_json_report,
    to_text_report,
)
from .scanner import iter_py_files, module_name_from_path

# Custom theme for Rich
custom_theme = Theme(
    {
        "info": "cyan",
        "warning": "yellow",
        "error": "bold red",
        "success": "bold green",
        "dim": "dim",
    }
)


class _HelpFormatter(argparse.ArgumentDefaultsHelpFormatter):
    def _get_help_string(self, action: argparse.Action) -> str:
        if action.dest == "cache_path":
            return action.help or ""
        return cast(str, super()._get_help_string(action))


LEGACY_CACHE_PATH = Path("~/.cache/codeclone/cache.json").expanduser()


def _make_console(*, no_color: bool) -> Console:
    return Console(theme=custom_theme, width=200, no_color=no_color)


console = _make_console(no_color=False)

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
BATCH_SIZE = 100


@dataclass(slots=True)
class ProcessingResult:
    """Result of processing a single file."""

    filepath: str
    success: bool
    error: str | None = None
    units: list[Any] | None = None
    blocks: list[Any] | None = None
    segments: list[Any] | None = None
    stat: FileStat | None = None


def expand_path(p: str) -> Path:
    return Path(p).expanduser().resolve()


def process_file(
    filepath: str,
    root: str,
    cfg: NormalizationConfig,
    min_loc: int,
    min_stmt: int,
) -> ProcessingResult:
    """
    Process a single Python file with comprehensive error handling.

    Args:
        filepath: Absolute path to the file
        root: Root directory of the scan
        cfg: Normalization configuration
        min_loc: Minimum lines of code to consider a function
        min_stmt: Minimum statements to consider a function

    Returns:
        ProcessingResult object indicating success/failure and containing
        extracted units/blocks if successful.
    """

    try:
        # Check file size
        try:
            st_size = os.path.getsize(filepath)
            if st_size > MAX_FILE_SIZE:
                return ProcessingResult(
                    filepath=filepath,
                    success=False,
                    error=f"File too large: {st_size} bytes (max {MAX_FILE_SIZE})",
                )
        except OSError as e:
            return ProcessingResult(
                filepath=filepath, success=False, error=f"Cannot stat file: {e}"
            )

        try:
            source = Path(filepath).read_text("utf-8")
        except UnicodeDecodeError as e:
            return ProcessingResult(
                filepath=filepath, success=False, error=f"Encoding error: {e}"
            )

        stat = file_stat_signature(filepath)
        module_name = module_name_from_path(root, filepath)

        units, blocks, segments = extract_units_from_source(
            source=source,
            filepath=filepath,
            module_name=module_name,
            cfg=cfg,
            min_loc=min_loc,
            min_stmt=min_stmt,
        )

        return ProcessingResult(
            filepath=filepath,
            success=True,
            units=units,
            blocks=blocks,
            segments=segments,
            stat=stat,
        )

    except Exception as e:
        return ProcessingResult(
            filepath=filepath,
            success=False,
            error=f"Unexpected error: {type(e).__name__}: {e}",
        )


def print_banner() -> None:
    console.print(
        Panel.fit(
            f"[bold white]CodeClone[/bold white] [dim]v{__version__}[/dim]\n"
            "[italic]Architectural duplication detector[/italic]",
            border_style="blue",
            padding=(0, 2),
        )
    )


def _validate_output_path(path: str, *, expected_suffix: str, label: str) -> Path:
    out = Path(path).expanduser()
    if out.suffix.lower() != expected_suffix:
        console.print(
            f"[error]Invalid {label} output extension: {out} "
            f"(expected {expected_suffix}).[/error]"
        )
        sys.exit(2)
    return out.resolve()


def _current_python_version() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def _build_report_meta(
    *,
    baseline_path: Path,
    baseline: Baseline,
    baseline_loaded: bool,
    baseline_status: str,
    cache_path: Path,
    cache_used: bool,
) -> dict[str, Any]:
    return {
        "codeclone_version": __version__,
        "python_version": _current_python_version(),
        "baseline_path": str(baseline_path),
        "baseline_version": baseline.baseline_version,
        "baseline_schema_version": baseline.schema_version,
        "baseline_python_version": baseline.python_version,
        "baseline_loaded": baseline_loaded,
        "baseline_status": baseline_status,
        "cache_path": str(cache_path),
        "cache_used": cache_used,
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="codeclone",
        description="AST and CFG-based code clone detector for Python.",
        formatter_class=_HelpFormatter,
    )
    ap.add_argument(
        "--version",
        action="version",
        version=f"CodeClone {__version__}",
        help="Print the CodeClone version and exit.",
    )

    # Core Arguments
    core_group = ap.add_argument_group("Target")
    core_group.add_argument(
        "root",
        nargs="?",
        default=".",
        help="Project root directory to scan.",
    )

    # Tuning
    tune_group = ap.add_argument_group("Analysis Tuning")
    tune_group.add_argument(
        "--min-loc",
        type=int,
        default=15,
        help="Minimum Lines of Code (LOC) to consider.",
    )
    tune_group.add_argument(
        "--min-stmt",
        type=int,
        default=6,
        help="Minimum AST statements to consider.",
    )
    tune_group.add_argument(
        "--processes",
        type=int,
        default=4,
        help="Number of parallel worker processes.",
    )
    tune_group.add_argument(
        "--cache-path",
        dest="cache_path",
        metavar="FILE",
        default=None,
        help="Path to the cache file. Default: <root>/.cache/codeclone/cache.json.",
    )
    tune_group.add_argument(
        "--cache-dir",
        dest="cache_path",
        metavar="FILE",
        default=None,
        help="Legacy alias for --cache-path.",
    )

    # Baseline & CI
    ci_group = ap.add_argument_group("Baseline & CI/CD")
    ci_group.add_argument(
        "--baseline",
        default="codeclone.baseline.json",
        help="Path to the baseline file (stored in repo).",
    )
    ci_group.add_argument(
        "--update-baseline",
        action="store_true",
        help="Overwrite the baseline file with current results.",
    )
    ci_group.add_argument(
        "--fail-on-new",
        action="store_true",
        help="Exit with error if NEW clones (not in baseline) are detected.",
    )
    ci_group.add_argument(
        "--fail-threshold",
        type=int,
        default=-1,
        metavar="MAX_CLONES",
        help=(
            "Exit with error if total clone groups (function + block) "
            "exceed this number."
        ),
    )
    ci_group.add_argument(
        "--ci",
        action="store_true",
        help="CI preset: --fail-on-new --no-color --quiet.",
    )

    # Output
    out_group = ap.add_argument_group("Reporting")
    out_group.add_argument(
        "--html",
        dest="html_out",
        metavar="FILE",
        help="Generate an HTML report to FILE.",
    )
    out_group.add_argument(
        "--json",
        dest="json_out",
        metavar="FILE",
        help="Generate a JSON report to FILE.",
    )
    out_group.add_argument(
        "--text",
        dest="text_out",
        metavar="FILE",
        help="Generate a text report to FILE.",
    )
    out_group.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable the progress bar (recommended for CI logs).",
    )
    out_group.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI colors in output.",
    )
    out_group.add_argument(
        "--quiet",
        action="store_true",
        help="Minimize output (still shows warnings and errors).",
    )
    out_group.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed hash identifiers for new clones.",
    )

    cache_path_from_args = any(
        arg in {"--cache-dir", "--cache-path"}
        or arg.startswith(("--cache-dir=", "--cache-path="))
        for arg in sys.argv
    )
    args = ap.parse_args()

    if args.ci:
        args.fail_on_new = True
        args.no_color = True
        args.quiet = True

    if args.quiet:
        args.no_progress = True

    global console
    console = _make_console(no_color=args.no_color)

    if not args.quiet:
        print_banner()

    try:
        root_path = Path(args.root).resolve()
        if not root_path.exists():
            console.print(f"[error]Root path does not exist: {root_path}[/error]")
            sys.exit(1)
    except Exception as e:
        console.print(f"[error]Invalid root path: {e}[/error]")
        sys.exit(1)

    if not args.quiet:
        console.print(f"[info]Scanning root:[/info] {root_path}")

    html_out_path: Path | None = None
    json_out_path: Path | None = None
    text_out_path: Path | None = None
    if args.html_out:
        html_out_path = _validate_output_path(
            args.html_out, expected_suffix=".html", label="HTML"
        )
    if args.json_out:
        json_out_path = _validate_output_path(
            args.json_out, expected_suffix=".json", label="JSON"
        )
    if args.text_out:
        text_out_path = _validate_output_path(
            args.text_out, expected_suffix=".txt", label="text"
        )

    # Initialize Cache
    cfg = NormalizationConfig()
    if cache_path_from_args and args.cache_path:
        cache_path = Path(args.cache_path).expanduser()
    else:
        cache_path = root_path / ".cache" / "codeclone" / "cache.json"
        if LEGACY_CACHE_PATH.exists():
            try:
                legacy_resolved = LEGACY_CACHE_PATH.resolve()
            except OSError:
                legacy_resolved = LEGACY_CACHE_PATH
            if legacy_resolved != cache_path:
                console.print(
                    "[warning]Legacy cache file found at: "
                    f"{legacy_resolved}.[/warning]\n"
                    "[warning]Cache is now stored per-project at: "
                    f"{cache_path}.[/warning]\n"
                    "[warning]Please delete the legacy cache file and add "
                    ".cache/ to .gitignore.[/warning]"
                )
    cache = Cache(cache_path)
    cache.load()
    if cache.load_warning:
        console.print(f"[warning]{cache.load_warning}[/warning]")

    all_units: list[dict[str, Any]] = []
    all_blocks: list[dict[str, Any]] = []
    all_segments: list[dict[str, Any]] = []
    changed_files_count = 0
    files_to_process: list[str] = []

    def _get_cached_entry(
        fp: str,
    ) -> tuple[FileStat | None, CacheEntry | None, str | None]:
        try:
            stat = file_stat_signature(fp)
        except OSError as e:
            return None, None, f"[warning]Skipping file {fp}: {e}[/warning]"
        cached = cache.get_file_entry(fp)
        return stat, cached, None

    def _safe_process_file(fp: str) -> ProcessingResult | None:
        try:
            return process_file(
                fp,
                str(root_path),
                cfg,
                args.min_loc,
                args.min_stmt,
            )
        except Exception as e:
            console.print(f"[warning]Worker failed: {e}[/warning]")
            return None

    def _safe_future_result(future: Any) -> tuple[ProcessingResult | None, str | None]:
        try:
            return future.result(), None
        except Exception as e:
            return None, str(e)

    # Discovery phase
    try:
        if args.quiet:
            for fp in iter_py_files(str(root_path)):
                stat, cached, warn = _get_cached_entry(fp)
                if warn:
                    console.print(warn)
                    continue
                if cached and cached.get("stat") == stat:
                    all_units.extend(
                        cast(
                            list[dict[str, Any]],
                            cast(object, cached.get("units", [])),
                        )
                    )
                    all_blocks.extend(
                        cast(
                            list[dict[str, Any]],
                            cast(object, cached.get("blocks", [])),
                        )
                    )
                    all_segments.extend(
                        cast(
                            list[dict[str, Any]],
                            cast(object, cached.get("segments", [])),
                        )
                    )
                else:
                    files_to_process.append(fp)
        else:
            with console.status(
                "[bold green]Discovering Python files...", spinner="dots"
            ):
                for fp in iter_py_files(str(root_path)):
                    stat, cached, warn = _get_cached_entry(fp)
                    if warn:
                        console.print(warn)
                        continue
                    if cached and cached.get("stat") == stat:
                        all_units.extend(
                            cast(
                                list[dict[str, Any]],
                                cast(object, cached.get("units", [])),
                            )
                        )
                        all_blocks.extend(
                            cast(
                                list[dict[str, Any]],
                                cast(object, cached.get("blocks", [])),
                            )
                        )
                        all_segments.extend(
                            cast(
                                list[dict[str, Any]],
                                cast(object, cached.get("segments", [])),
                            )
                        )
                    else:
                        files_to_process.append(fp)
    except Exception as e:
        console.print(f"[error]Scan failed: {e}[/error]")
        sys.exit(1)

    total_files = len(files_to_process)
    failed_files = []

    # Processing phase
    if total_files > 0:

        def handle_result(result: ProcessingResult) -> None:
            nonlocal changed_files_count
            if result.success and result.stat:
                cache.put_file_entry(
                    result.filepath,
                    result.stat,
                    result.units or [],
                    result.blocks or [],
                    result.segments or [],
                )
                changed_files_count += 1
                if result.units:
                    all_units.extend([asdict(u) for u in result.units])
                if result.blocks:
                    all_blocks.extend([asdict(b) for b in result.blocks])
                if result.segments:
                    all_segments.extend([asdict(s) for s in result.segments])
            else:
                failed_files.append(f"{result.filepath}: {result.error}")

        def process_sequential(with_progress: bool) -> None:
            if with_progress:
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                    TimeElapsedColumn(),
                    console=console,
                ) as progress:
                    task = progress.add_task(
                        f"Analyzing {total_files} files...", total=total_files
                    )
                    for fp in files_to_process:
                        result = _safe_process_file(fp)
                        if result is not None:
                            handle_result(result)
                        progress.advance(task)
            else:
                if not args.quiet:
                    console.print(
                        f"[info]Processing {total_files} changed files...[/info]"
                    )
                for fp in files_to_process:
                    result = _safe_process_file(fp)
                    if result is not None:
                        handle_result(result)

        try:
            with ProcessPoolExecutor(max_workers=args.processes) as executor:
                if args.no_progress:
                    if not args.quiet:
                        console.print(
                            f"[info]Processing {total_files} changed files...[/info]"
                        )

                    # Process in batches to manage memory
                    for i in range(0, total_files, BATCH_SIZE):
                        batch = files_to_process[i : i + BATCH_SIZE]
                        futures = [
                            executor.submit(
                                process_file,
                                fp,
                                str(root_path),
                                cfg,
                                args.min_loc,
                                args.min_stmt,
                            )
                            for fp in batch
                        ]

                        for future in as_completed(futures):
                            result, err = _safe_future_result(future)
                            if result is not None:
                                handle_result(result)
                            elif err is not None:
                                console.print(
                                    "[warning]Failed to process batch item: "
                                    f"{err}[/warning]"
                                )

                else:
                    with Progress(
                        SpinnerColumn(),
                        TextColumn("[progress.description]{task.description}"),
                        BarColumn(),
                        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                        TimeElapsedColumn(),
                        console=console,
                    ) as progress:
                        task = progress.add_task(
                            f"Analyzing {total_files} files...", total=total_files
                        )

                        # Process in batches
                        for i in range(0, total_files, BATCH_SIZE):
                            batch = files_to_process[i : i + BATCH_SIZE]
                            futures = [
                                executor.submit(
                                    process_file,
                                    fp,
                                    str(root_path),
                                    cfg,
                                    args.min_loc,
                                    args.min_stmt,
                                )
                                for fp in batch
                            ]

                            for future in as_completed(futures):
                                result, err = _safe_future_result(future)
                                if result is not None:
                                    handle_result(result)
                                elif err is not None:
                                    # Should rarely happen due to try/except
                                    # in process_file.
                                    console.print(
                                        f"[warning]Worker failed: {err}[/warning]"
                                    )
                                progress.advance(task)
        except (OSError, RuntimeError, PermissionError) as e:
            console.print(
                "[warning]Parallel processing unavailable, "
                f"falling back to sequential: {e}[/warning]"
            )
            process_sequential(with_progress=not args.no_progress)

    if failed_files:
        console.print(
            f"\n[warning]⚠ {len(failed_files)} files failed to process:[/warning]"
        )
        for failure in failed_files[:10]:
            console.print(f"  • {failure}")
        if len(failed_files) > 10:
            console.print(f"  ... and {len(failed_files) - 10} more")

    # Analysis phase
    suppressed_segment_groups = 0
    if args.quiet:
        func_groups = build_groups(all_units)
        block_groups = build_block_groups(all_blocks)
        segment_groups = build_segment_groups(all_segments)
        segment_groups, suppressed_segment_groups = prepare_segment_report_groups(
            segment_groups
        )
        try:
            cache.save()
        except CacheError as e:
            console.print(f"[warning]Failed to save cache: {e}[/warning]")
    else:
        with console.status("[bold green]Grouping clones...", spinner="dots"):
            func_groups = build_groups(all_units)
            block_groups = build_block_groups(all_blocks)
            segment_groups = build_segment_groups(all_segments)
            segment_groups, suppressed_segment_groups = prepare_segment_report_groups(
                segment_groups
            )
            try:
                cache.save()
            except CacheError as e:
                console.print(f"[warning]Failed to save cache: {e}[/warning]")

    # Reporting
    func_clones_count = len(func_groups)
    block_clones_count = len(block_groups)
    segment_clones_count = len(segment_groups)

    # Baseline Logic
    baseline_path = Path(args.baseline).expanduser().resolve()

    # If user didn't specify path, the default is ./codeclone.baseline.json.

    baseline = Baseline(baseline_path)
    baseline_exists = baseline_path.exists()
    baseline_loaded = False
    baseline_status = "missing"
    baseline_failure_code: int | None = None

    if baseline_exists:
        try:
            baseline.load()
        except ValueError as e:
            baseline_status = "invalid"
            if not args.update_baseline:
                console.print(
                    "[error]Invalid baseline file.[/error]\n"
                    f"{e}\n"
                    "Please regenerate the baseline with --update-baseline."
                )
                baseline_failure_code = 2
        else:
            baseline_loaded = True
            baseline_status = "ok"
            if not args.update_baseline:
                if baseline.baseline_version != __version__:
                    baseline_status = "mismatch"
                    if baseline.baseline_version is None:
                        console.print(
                            "[error]Baseline version mismatch.[/error]\n"
                            "Baseline version missing (legacy baseline format).\n"
                            f"Current version: {__version__}.\n"
                            "Please regenerate the baseline with --update-baseline."
                        )
                    else:
                        console.print(
                            "[error]Baseline version mismatch.[/error]\n"
                            "Baseline was generated with CodeClone "
                            f"{baseline.baseline_version}.\n"
                            f"Current version: {__version__}.\n"
                            "Please regenerate the baseline with --update-baseline."
                        )
                    baseline_failure_code = 2
                if (
                    baseline.schema_version is not None
                    and baseline.schema_version != BASELINE_SCHEMA_VERSION
                ):
                    baseline_status = "mismatch"
                    console.print(
                        "[error]Baseline schema version mismatch.[/error]\n"
                        f"Baseline schema: {baseline.schema_version}. "
                        f"Current schema: {BASELINE_SCHEMA_VERSION}.\n"
                        "Please regenerate the baseline with --update-baseline."
                    )
                    baseline_failure_code = 2
            if not args.update_baseline and baseline.python_version:
                current_version = _current_python_version()
                if baseline.python_version != current_version:
                    baseline_status = "mismatch"
                    console.print(
                        "[warning]Baseline Python version mismatch.[/warning]\n"
                        "Baseline was generated with Python "
                        f"{baseline.python_version}.\n"
                        f"Current interpreter: Python {current_version}."
                    )
                    if args.fail_on_new:
                        console.print(
                            "[error]Baseline checks require the same Python version to "
                            "ensure deterministic results. Please regenerate the "
                            "baseline "
                            "using the current interpreter.[/error]"
                        )
                        baseline_failure_code = 2
    else:
        if not args.update_baseline:
            console.print(
                "[warning]Baseline file not found at: [bold]"
                f"{baseline_path}"
                "[/bold][/warning]\n"
                "[dim]Comparing against an empty baseline. "
                "Use --update-baseline to create it.[/dim]"
            )

    if args.update_baseline:
        new_baseline = Baseline.from_groups(
            func_groups,
            block_groups,
            path=baseline_path,
            python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
            baseline_version=__version__,
            schema_version=BASELINE_SCHEMA_VERSION,
        )
        new_baseline.save()
        console.print(f"[success]✔ Baseline updated:[/success] {baseline_path}")
        # When updating, we don't fail on new, we just saved the new state.
        # But we might still want to print the summary.

    report_meta = _build_report_meta(
        baseline_path=baseline_path,
        baseline=baseline,
        baseline_loaded=baseline_loaded,
        baseline_status=baseline_status,
        cache_path=cache_path.resolve(),
        cache_used=cache.load_warning is None,
    )

    # Diff
    new_func, new_block = baseline.diff(func_groups, block_groups)
    new_clones_count = len(new_func) + len(new_block)

    # Summary Table
    if not args.quiet:
        table = Table(title="Analysis Summary", border_style="blue")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="bold white")

        table.add_row("Files Processed", str(changed_files_count))
        table.add_row("Total Function Clones", str(func_clones_count))
        table.add_row("Total Block Clones", str(block_clones_count))
        table.add_row("Total Segment Clones", str(segment_clones_count))
        if suppressed_segment_groups > 0:
            table.add_row("Suppressed Segment Groups", str(suppressed_segment_groups))

        if baseline_exists:
            style = "error" if new_clones_count > 0 else "success"
            table.add_row(
                "New Clones (vs Baseline)", f"[{style}]{new_clones_count}[/{style}]"
            )

        console.print(table)

    # Outputs
    html_report_path: str | None = None
    if html_out_path:
        out = html_out_path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            build_html_report(
                func_groups=func_groups,
                block_groups=block_groups,
                segment_groups=segment_groups,
                report_meta=report_meta,
                title="CodeClone Report",
                context_lines=3,
                max_snippet_lines=220,
            ),
            "utf-8",
        )
        html_report_path = str(out)
        if not args.quiet:
            console.print(f"[info]HTML report saved:[/info] {out}")

    if json_out_path:
        out = json_out_path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            to_json_report(func_groups, block_groups, segment_groups, report_meta),
            "utf-8",
        )
        if not args.quiet:
            console.print(f"[info]JSON report saved:[/info] {out}")

    if text_out_path:
        out = text_out_path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            to_text_report(
                meta=report_meta,
                func_groups=func_groups,
                block_groups=block_groups,
                segment_groups=segment_groups,
            ),
            "utf-8",
        )
        if not args.quiet:
            console.print(f"[info]Text report saved:[/info] {out}")

    if baseline_failure_code is not None:
        sys.exit(baseline_failure_code)

    # Exit Codes
    if args.fail_on_new and (new_func or new_block):
        default_report = Path(".cache/codeclone/report.html")
        if html_report_path is None and default_report.exists():
            html_report_path = str(default_report)

        console.print("\n[error]FAILED: New code clones detected.[/error]")
        console.print("\nSummary:")
        console.print(f"- New function clone groups: {len(new_func)}")
        console.print(f"- New block clone groups: {len(new_block)}")
        if html_report_path:
            console.print("\nSee detailed report:")
            console.print(f"  {html_report_path}")
        console.print("\nTo accept these clones as technical debt, run:")
        console.print("  codeclone . --update-baseline")

        if args.verbose:
            if new_func:
                console.print("\nDetails (function clone hashes):")
                for h in sorted(new_func):
                    console.print(f"- {h}")
            if new_block:
                console.print("\nDetails (block clone hashes):")
                for h in sorted(new_block):
                    console.print(f"- {h}")
        sys.exit(3)

    if 0 <= args.fail_threshold < (func_clones_count + block_clones_count):
        total = func_clones_count + block_clones_count
        console.print(
            f"\n[error]❌ FAILED: Total clones ({total}) "
            f"exceed threshold ({args.fail_threshold})![/error]"
        )
        sys.exit(2)

    if not args.update_baseline and not args.fail_on_new and new_clones_count > 0:
        console.print(
            "\n[warning]New clones detected but --fail-on-new not set.[/warning]\n"
            "Run with --update-baseline to accept them as technical debt."
        )


if __name__ == "__main__":
    main()
