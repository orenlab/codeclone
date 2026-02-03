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

from .baseline import Baseline
from .cache import Cache, CacheEntry, FileStat, file_stat_signature
from .errors import CacheError
from .extractor import extract_units_from_source
from .html_report import build_html_report
from .normalize import NormalizationConfig
from .report import build_block_groups, build_groups, to_json_report, to_text
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
console = Console(theme=custom_theme, width=200)

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

        units, blocks = extract_units_from_source(
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
            "[bold white]CodeClone[/bold white] [dim]v1.2.1[/dim]\n"
            "[italic]Architectural duplication detector[/italic]",
            border_style="blue",
            padding=(0, 2),
        )
    )


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="codeclone",
        description="AST and CFG-based code clone detector for Python.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
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
        "--cache-dir",
        default="~/.cache/codeclone/cache.json",
        help="Path to the cache file to speed up subsequent runs.",
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
        help="Exit with error if total clone groups exceed this number.",
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

    args = ap.parse_args()

    print_banner()

    try:
        root_path = Path(args.root).resolve()
        if not root_path.exists():
            console.print(f"[error]Root path does not exist: {root_path}[/error]")
            sys.exit(1)
    except Exception as e:
        console.print(f"[error]Invalid root path: {e}[/error]")
        sys.exit(1)

    console.print(f"[info]Scanning root:[/info] {root_path}")

    # Initialize Cache
    cfg = NormalizationConfig()
    cache_path = Path(args.cache_dir).expanduser()
    cache = Cache(cache_path)
    cache.load()
    if cache.load_warning:
        console.print(f"[warning]{cache.load_warning}[/warning]")

    all_units: list[dict[str, Any]] = []
    all_blocks: list[dict[str, Any]] = []
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
    with console.status("[bold green]Discovering Python files...", spinner="dots"):
        try:
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
                )
                changed_files_count += 1
                if result.units:
                    all_units.extend([asdict(u) for u in result.units])
                if result.blocks:
                    all_blocks.extend([asdict(b) for b in result.blocks])
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
                console.print(f"[info]Processing {total_files} changed files...[/info]")
                for fp in files_to_process:
                    result = _safe_process_file(fp)
                    if result is not None:
                        handle_result(result)

        try:
            with ProcessPoolExecutor(max_workers=args.processes) as executor:
                if args.no_progress:
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
    with console.status("[bold green]Grouping clones...", spinner="dots"):
        func_groups = build_groups(all_units)
        block_groups = build_block_groups(all_blocks)
        try:
            cache.save()
        except CacheError as e:
            console.print(f"[warning]Failed to save cache: {e}[/warning]")

    # Reporting
    func_clones_count = len(func_groups)
    block_clones_count = len(block_groups)

    # Baseline Logic
    baseline_path = Path(args.baseline).expanduser().resolve()

    # If user didn't specify path and default logic applies, baseline_path
    # is now ./codeclone_baseline.json

    baseline = Baseline(baseline_path)
    baseline_exists = baseline_path.exists()

    if baseline_exists:
        baseline.load()
        if not args.update_baseline and baseline.python_version:
            current_version = f"{sys.version_info.major}.{sys.version_info.minor}"
            if baseline.python_version != current_version:
                console.print(
                    "[warning]Baseline Python version mismatch.[/warning]\n"
                    f"Baseline was generated with Python {baseline.python_version}.\n"
                    f"Current interpreter: Python {current_version}."
                )
                if args.fail_on_new:
                    console.print(
                        "[error]Baseline checks require the same Python version to "
                        "ensure deterministic results. Please regenerate the baseline "
                        "using the current interpreter.[/error]"
                    )
                    sys.exit(2)
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
        )
        new_baseline.save()
        console.print(f"[success]✔ Baseline updated:[/success] {baseline_path}")
        # When updating, we don't fail on new, we just saved the new state.
        # But we might still want to print the summary.

    # Diff
    new_func, new_block = baseline.diff(func_groups, block_groups)
    new_clones_count = len(new_func) + len(new_block)

    # Summary Table
    table = Table(title="Analysis Summary", border_style="blue")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="bold white")

    table.add_row("Files Processed", str(changed_files_count))
    table.add_row("Total Function Clones", str(func_clones_count))
    table.add_row("Total Block Clones", str(block_clones_count))

    if baseline_exists:
        style = "error" if new_clones_count > 0 else "success"
        table.add_row(
            "New Clones (vs Baseline)", f"[{style}]{new_clones_count}[/{style}]"
        )

    console.print(table)

    # Outputs
    if args.html_out:
        out = Path(args.html_out).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            build_html_report(
                func_groups=func_groups,
                block_groups=block_groups,
                title="CodeClone Report",
                context_lines=3,
                max_snippet_lines=220,
            ),
            "utf-8",
        )
        console.print(f"[info]HTML report saved:[/info] {out}")

    if args.json_out:
        out = Path(args.json_out).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            to_json_report(func_groups, block_groups),
            "utf-8",
        )
        console.print(f"[info]JSON report saved:[/info] {out}")

    if args.text_out:
        out = Path(args.text_out).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            "FUNCTION CLONES\n"
            + to_text(func_groups)
            + "\nBLOCK CLONES\n"
            + to_text(block_groups),
            "utf-8",
        )
        console.print(f"[info]Text report saved:[/info] {out}")

    # Exit Codes
    if args.fail_on_new and (new_func or new_block):
        console.print("\n[error]❌ FAILED: New code clones detected![/error]")
        if new_func:
            console.print(f"  New Functions: {', '.join(sorted(new_func))}")
        if new_block:
            console.print(f"  New Blocks: {', '.join(sorted(new_block))}")
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
