"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.table import Table
from rich.theme import Theme

from .baseline import Baseline
from .cache import Cache, file_stat_signature
from .extractor import extract_units_from_source
from .html_report import build_html_report
from .normalize import NormalizationConfig
from .report import build_groups, build_block_groups, to_json, to_text
from .scanner import iter_py_files, module_name_from_path

# Custom theme for Rich
custom_theme = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "bold red",
    "success": "bold green",
    "dim": "dim",
})
console = Console(theme=custom_theme, width=200)


def expand_path(p: str) -> Path:
    return Path(p).expanduser().resolve()


def process_file(
        filepath: str,
        root: str,
        cfg: NormalizationConfig,
        min_loc: int,
        min_stmt: int,
) -> tuple[str, dict, list, list] | None:
    try:
        source = Path(filepath).read_text("utf-8")
    except UnicodeDecodeError:
        return None

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

    return filepath, stat, units, blocks


def print_banner():
    console.print(
        Panel.fit(
            "[bold white]CodeClone[/bold white] [dim]v1.1.1[/dim]\n"
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

    root_path = Path(args.root).resolve()
    if not root_path.exists():
        console.print(f"[error]Root path does not exist: {root_path}[/error]")
        sys.exit(1)

    console.print(f"[info]Scanning root:[/info] {root_path}")

    # Initialize Cache
    cfg = NormalizationConfig()
    cache_path = Path(args.cache_dir).expanduser()
    cache = Cache(cache_path)
    cache.load()

    all_units: list[dict] = []
    all_blocks: list[dict] = []
    changed_files_count = 0
    files_to_process: list[str] = []

    # Discovery phase
    with console.status("[bold green]Discovering Python files...", spinner="dots"):
        for fp in iter_py_files(str(root_path)):
            stat = file_stat_signature(fp)
            cached = cache.get_file_entry(fp)
            if cached and cached.get("stat") == stat:
                all_units.extend(cached.get("units", []))
                all_blocks.extend(cached.get("blocks", []))
            else:
                files_to_process.append(fp)

    total_files = len(files_to_process)
    cached_files = len(all_units)  # rough estimate, units != files, but logic holds

    # Processing phase
    if total_files > 0:
        if args.no_progress:
            console.print(f"[info]Processing {total_files} changed files...[/info]")
            with ProcessPoolExecutor(max_workers=args.processes) as executor:
                futures = [
                    executor.submit(
                        process_file, fp, str(root_path), cfg, args.min_loc, args.min_stmt
                    )
                    for fp in files_to_process
                ]
                for future in as_completed(futures):
                    try:
                        result = future.result()
                    except Exception as e:
                        console.print(f"[warning]Failed to process file: {e}[/warning]")
                        continue

                    if result:
                        fp, stat, units, blocks = result
                        cache.put_file_entry(fp, stat, units, blocks)
                        changed_files_count += 1
                        all_units.extend([u.__dict__ for u in units])
                        all_blocks.extend([b.__dict__ for b in blocks])
        else:
            with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                    TimeElapsedColumn(),
                    console=console,
            ) as progress:
                task = progress.add_task(f"Analyzing {total_files} files...", total=total_files)
                with ProcessPoolExecutor(max_workers=args.processes) as executor:
                    futures = [
                        executor.submit(
                            process_file,
                            fp,
                            str(root_path),
                            cfg,
                            args.min_loc,
                            args.min_stmt,
                        )
                        for fp in files_to_process
                    ]
                    for future in as_completed(futures):
                        try:
                            result = future.result()
                        except Exception as e:
                            # Log error but keep progress bar moving?
                            # console.print might break progress bar layout, better to rely on rich logging or just skip
                            # console.print(f"[warning]Failed to process file: {e}[/warning]")
                            continue
                        finally:
                            progress.advance(task)

                        if result:
                            fp, stat, units, blocks = result
                            cache.put_file_entry(fp, stat, units, blocks)
                            changed_files_count += 1
                            all_units.extend([u.__dict__ for u in units])
                            all_blocks.extend([b.__dict__ for b in blocks])

    # Analysis phase
    with console.status("[bold green]Grouping clones...", spinner="dots"):
        func_groups = build_groups(all_units)
        block_groups = build_block_groups(all_blocks)
        cache.save()

    # Reporting
    func_clones_count = len(func_groups)
    block_clones_count = len(block_groups)

    # Baseline Logic
    baseline_path = Path(args.baseline).expanduser().resolve()

    # If user didn't specify path, and default logic applies, baseline_path is now ./codeclone_baseline.json

    baseline = Baseline(baseline_path)
    baseline_exists = baseline_path.exists()

    if baseline_exists:
        baseline.load()
    else:
        if not args.update_baseline:
            console.print(
                f"[warning]Baseline file not found at: [bold]{baseline_path}[/bold][/warning]\n"
                "[dim]Comparing against an empty baseline. "
                "Use --update-baseline to create it.[/dim]"
            )

    if args.update_baseline:
        new_baseline = Baseline.from_groups(func_groups, block_groups, path=baseline_path)
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
        table.add_row("New Clones (vs Baseline)", f"[{style}]{new_clones_count}[/{style}]")

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
            to_json({"functions": func_groups, "blocks": block_groups}),
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
        console.print(
            f"\n[error]❌ FAILED: Total clones ({func_clones_count + block_clones_count}) "
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
