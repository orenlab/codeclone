from __future__ import annotations

import os
import sys
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import Future, ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.rule import Rule
from rich.theme import Theme

from . import __version__
from . import ui_messages as ui
from ._cli_args import build_parser
from ._cli_meta import _build_report_meta
from ._cli_paths import _validate_output_path
from ._cli_summary import _print_summary
from ._report_types import GroupItem
from .baseline import (
    BASELINE_UNTRUSTED_STATUSES,
    Baseline,
    BaselineStatus,
    coerce_baseline_status,
    current_python_tag,
)
from .cache import Cache, CacheEntry, CacheStatus, FileStat, file_stat_signature
from .contracts import (
    BASELINE_FINGERPRINT_VERSION,
    BASELINE_SCHEMA_VERSION,
    ISSUES_URL,
    ExitCode,
)
from .errors import BaselineValidationError, CacheError
from .extractor import extract_units_from_source
from .html_report import build_html_report
from .normalize import NormalizationConfig
from .report import (
    build_block_group_facts,
    build_block_groups,
    build_groups,
    build_segment_groups,
    prepare_block_report_groups,
    prepare_segment_report_groups,
    to_json_report,
    to_text_report,
)
from .scanner import iter_py_files, module_name_from_path

if TYPE_CHECKING:
    from .blocks import BlockUnit, SegmentUnit
    from .extractor import Unit

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


LEGACY_CACHE_PATH = Path("~/.cache/codeclone/cache.json").expanduser()


def _make_console(*, no_color: bool) -> Console:
    return Console(theme=custom_theme, width=100, no_color=no_color)


console = _make_console(no_color=False)

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
BATCH_SIZE = 100


@dataclass(slots=True)
class ProcessingResult:
    """Result of processing a single file."""

    filepath: str
    success: bool
    error: str | None = None
    units: list[Unit] | None = None
    blocks: list[BlockUnit] | None = None
    segments: list[SegmentUnit] | None = None
    stat: FileStat | None = None
    error_kind: str | None = None


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
                    error_kind="file_too_large",
                )
        except OSError as e:
            return ProcessingResult(
                filepath=filepath,
                success=False,
                error=f"Cannot stat file: {e}",
                error_kind="stat_error",
            )

        try:
            source = Path(filepath).read_text("utf-8")
        except UnicodeDecodeError as e:
            return ProcessingResult(
                filepath=filepath,
                success=False,
                error=f"Encoding error: {e}",
                error_kind="source_read_error",
            )
        except OSError as e:
            return ProcessingResult(
                filepath=filepath,
                success=False,
                error=f"Cannot read file: {e}",
                error_kind="source_read_error",
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
            error_kind="unexpected_error",
        )


def print_banner() -> None:
    console.print(
        Panel(
            ui.banner_title(__version__),
            border_style="blue",
            padding=(0, 2),
            width=ui.CLI_LAYOUT_WIDTH,
            expand=False,
        )
    )


def _is_debug_enabled(
    *,
    argv: Sequence[str] | None = None,
    environ: Mapping[str, str] | None = None,
) -> bool:
    args = list(sys.argv[1:] if argv is None else argv)
    debug_from_flag = any(arg == "--debug" for arg in args)
    env = os.environ if environ is None else environ
    debug_from_env = env.get("CODECLONE_DEBUG") == "1"
    return debug_from_flag or debug_from_env


def _main_impl() -> None:
    ap = build_parser(__version__)

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

    if args.max_baseline_size_mb < 0 or args.max_cache_size_mb < 0:
        console.print(
            ui.fmt_contract_error("Size limits must be non-negative integers (MB).")
        )
        sys.exit(ExitCode.CONTRACT_ERROR)

    t0 = time.monotonic()

    if not args.quiet:
        print_banner()

    try:
        root_path = Path(args.root).resolve()
        if not root_path.exists():
            console.print(
                ui.fmt_contract_error(ui.ERR_ROOT_NOT_FOUND.format(path=root_path))
            )
            sys.exit(ExitCode.CONTRACT_ERROR)
    except OSError as e:
        console.print(ui.fmt_contract_error(ui.ERR_INVALID_ROOT_PATH.format(error=e)))
        sys.exit(ExitCode.CONTRACT_ERROR)

    if not args.quiet:
        console.print(ui.fmt_scanning_root(root_path))

    html_out_path: Path | None = None
    json_out_path: Path | None = None
    text_out_path: Path | None = None
    if args.html_out:
        html_out_path = _validate_output_path(
            args.html_out,
            expected_suffix=".html",
            label="HTML",
            console=console,
            invalid_message=ui.fmt_invalid_output_extension,
            invalid_path_message=ui.fmt_invalid_output_path,
        )
    if args.json_out:
        json_out_path = _validate_output_path(
            args.json_out,
            expected_suffix=".json",
            label="JSON",
            console=console,
            invalid_message=ui.fmt_invalid_output_extension,
            invalid_path_message=ui.fmt_invalid_output_path,
        )
    if args.text_out:
        text_out_path = _validate_output_path(
            args.text_out,
            expected_suffix=".txt",
            label="text",
            console=console,
            invalid_message=ui.fmt_invalid_output_extension,
            invalid_path_message=ui.fmt_invalid_output_path,
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
                    ui.fmt_legacy_cache_warning(
                        legacy_path=legacy_resolved, new_path=cache_path
                    )
                )
    cache = Cache(
        cache_path,
        root=root_path,
        max_size_bytes=args.max_cache_size_mb * 1024 * 1024,
    )
    cache.load()
    if cache.load_warning:
        console.print(f"[warning]{cache.load_warning}[/warning]")

    all_units: list[GroupItem] = []
    all_blocks: list[GroupItem] = []
    all_segments: list[GroupItem] = []
    files_found = 0
    files_analyzed = 0
    cache_hits = 0
    files_skipped = 0
    files_to_process: list[str] = []

    def _get_cached_entry(
        fp: str,
    ) -> tuple[FileStat | None, CacheEntry | None, str | None]:
        try:
            stat = file_stat_signature(fp)
        except OSError as e:
            return None, None, ui.fmt_skipping_file(fp, e)
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
            console.print(ui.fmt_worker_failed(e))
            return None

    def _safe_future_result(
        future: Future[ProcessingResult],
    ) -> tuple[ProcessingResult | None, str | None]:
        try:
            return future.result(), None
        except Exception as e:
            return None, str(e)

    # Discovery phase
    try:
        if args.quiet:
            for fp in iter_py_files(str(root_path)):
                files_found += 1
                stat, cached, warn = _get_cached_entry(fp)
                if warn:
                    console.print(warn)
                    files_skipped += 1
                    continue
                if cached and cached.get("stat") == stat:
                    cache_hits += 1
                    all_units.extend(
                        cast(
                            list[GroupItem],
                            cast(object, cached.get("units", [])),
                        )
                    )
                    all_blocks.extend(
                        cast(
                            list[GroupItem],
                            cast(object, cached.get("blocks", [])),
                        )
                    )
                    all_segments.extend(
                        cast(
                            list[GroupItem],
                            cast(object, cached.get("segments", [])),
                        )
                    )
                else:
                    files_to_process.append(fp)
        else:
            with console.status(ui.STATUS_DISCOVERING, spinner="dots"):
                for fp in iter_py_files(str(root_path)):
                    files_found += 1
                    stat, cached, warn = _get_cached_entry(fp)
                    if warn:
                        console.print(warn)
                        files_skipped += 1
                        continue
                    if cached and cached.get("stat") == stat:
                        cache_hits += 1
                        all_units.extend(
                            cast(
                                list[GroupItem],
                                cast(object, cached.get("units", [])),
                            )
                        )
                        all_blocks.extend(
                            cast(
                                list[GroupItem],
                                cast(object, cached.get("blocks", [])),
                            )
                        )
                        all_segments.extend(
                            cast(
                                list[GroupItem],
                                cast(object, cached.get("segments", [])),
                            )
                        )
                    else:
                        files_to_process.append(fp)
    except OSError as e:
        console.print(ui.fmt_contract_error(ui.ERR_SCAN_FAILED.format(error=e)))
        sys.exit(ExitCode.CONTRACT_ERROR)

    total_files = len(files_to_process)
    failed_files = []
    source_read_failures: list[str] = []

    # Processing phase
    if total_files > 0:

        def handle_result(result: ProcessingResult) -> None:
            nonlocal files_analyzed, files_skipped
            if result.success and result.stat:
                cache.put_file_entry(
                    result.filepath,
                    result.stat,
                    result.units or [],
                    result.blocks or [],
                    result.segments or [],
                )
                files_analyzed += 1
                if result.units:
                    all_units.extend([asdict(u) for u in result.units])
                if result.blocks:
                    all_blocks.extend([asdict(b) for b in result.blocks])
                if result.segments:
                    all_segments.extend([asdict(s) for s in result.segments])
            else:
                files_skipped += 1
                failure = f"{result.filepath}: {result.error}"
                failed_files.append(failure)
                if result.error_kind == "source_read_error":
                    source_read_failures.append(failure)

        def process_sequential(with_progress: bool) -> None:
            nonlocal files_skipped
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
                        else:
                            files_skipped += 1
                            failed_files.append(f"{fp}: worker failed")
                        progress.advance(task)
            else:
                if not args.quiet:
                    console.print(ui.fmt_processing_changed(total_files))
                for fp in files_to_process:
                    result = _safe_process_file(fp)
                    if result is not None:
                        handle_result(result)
                    else:
                        files_skipped += 1
                        failed_files.append(f"{fp}: worker failed")

        try:
            with ProcessPoolExecutor(max_workers=args.processes) as executor:
                if args.no_progress:
                    if not args.quiet:
                        console.print(ui.fmt_processing_changed(total_files))

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
                        future_to_fp = {
                            id(fut): fp for fut, fp in zip(futures, batch, strict=True)
                        }

                        for future in as_completed(futures):
                            fp = future_to_fp[id(future)]
                            result, err = _safe_future_result(future)
                            if result is not None:
                                handle_result(result)
                            elif err is not None:
                                files_skipped += 1
                                reason = err
                                failed_files.append(f"{fp}: {reason}")
                                console.print(ui.fmt_batch_item_failed(reason))
                            else:
                                files_skipped += 1

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
                            future_to_fp = {
                                id(fut): fp
                                for fut, fp in zip(futures, batch, strict=True)
                            }

                            for future in as_completed(futures):
                                fp = future_to_fp[id(future)]
                                result, err = _safe_future_result(future)
                                if result is not None:
                                    handle_result(result)
                                elif err is not None:
                                    files_skipped += 1
                                    reason = err
                                    failed_files.append(f"{fp}: {reason}")
                                    # Should rarely happen due to try/except
                                    # in process_file.
                                    console.print(ui.fmt_worker_failed(reason))
                                else:
                                    files_skipped += 1
                                progress.advance(task)
        except (OSError, RuntimeError, PermissionError) as e:
            console.print(ui.fmt_parallel_fallback(e))
            process_sequential(with_progress=not args.no_progress)

    if failed_files:
        console.print(ui.fmt_failed_files_header(len(failed_files)))
        for failure in failed_files[:10]:
            console.print(f"  • {failure}")
        if len(failed_files) > 10:
            console.print(f"  ... and {len(failed_files) - 10} more")

    gating_mode = args.fail_on_new or args.fail_threshold >= 0
    source_read_contract_failure = (
        bool(source_read_failures) and gating_mode and not args.update_baseline
    )

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
            console.print(ui.fmt_cache_save_failed(e))
    else:
        with console.status(ui.STATUS_GROUPING, spinner="dots"):
            func_groups = build_groups(all_units)
            block_groups = build_block_groups(all_blocks)
            segment_groups = build_segment_groups(all_segments)
            segment_groups, suppressed_segment_groups = prepare_segment_report_groups(
                segment_groups
            )
            try:
                cache.save()
            except CacheError as e:
                console.print(ui.fmt_cache_save_failed(e))

    # Reporting
    block_groups_report = prepare_block_report_groups(block_groups)
    block_group_facts = build_block_group_facts(block_groups_report)
    func_clones_count = len(func_groups)
    block_clones_count = len(block_groups)
    segment_clones_count = len(segment_groups)

    # Baseline Logic
    baseline_arg_path = Path(args.baseline).expanduser()
    try:
        baseline_path = baseline_arg_path.resolve()
        baseline_exists = baseline_path.exists()
    except OSError as e:
        console.print(
            ui.fmt_contract_error(
                ui.fmt_invalid_baseline_path(path=baseline_arg_path, error=e)
            )
        )
        sys.exit(ExitCode.CONTRACT_ERROR)

    # If user didn't specify path, the default is ./codeclone.baseline.json.

    baseline = Baseline(baseline_path)
    baseline_loaded = False
    baseline_status = BaselineStatus.MISSING
    baseline_failure_code: ExitCode | None = None
    baseline_trusted_for_diff = False

    if baseline_exists:
        try:
            baseline.load(max_size_bytes=args.max_baseline_size_mb * 1024 * 1024)
        except BaselineValidationError as e:
            baseline_status = coerce_baseline_status(e.status)
            if not args.update_baseline:
                console.print(ui.fmt_invalid_baseline(e))
                if args.fail_on_new:
                    baseline_failure_code = ExitCode.CONTRACT_ERROR
                else:
                    console.print(ui.WARN_BASELINE_IGNORED)
        else:
            if not args.update_baseline:
                try:
                    baseline.verify_compatibility(
                        current_python_tag=current_python_tag()
                    )
                except BaselineValidationError as e:
                    baseline_status = coerce_baseline_status(e.status)
                    console.print(ui.fmt_invalid_baseline(e))
                    if args.fail_on_new:
                        baseline_failure_code = ExitCode.CONTRACT_ERROR
                    else:
                        console.print(ui.WARN_BASELINE_IGNORED)
                else:
                    baseline_loaded = True
                    baseline_status = BaselineStatus.OK
                    baseline_trusted_for_diff = True
    else:
        if not args.update_baseline:
            console.print(ui.fmt_path(ui.WARN_BASELINE_MISSING, baseline_path))

    if baseline_status in BASELINE_UNTRUSTED_STATUSES:
        baseline_loaded = False
        baseline_trusted_for_diff = False
        if args.fail_on_new and not args.update_baseline:
            baseline_failure_code = ExitCode.CONTRACT_ERROR

    if args.update_baseline:
        new_baseline = Baseline.from_groups(
            func_groups,
            block_groups,
            path=baseline_path,
            python_tag=current_python_tag(),
            fingerprint_version=BASELINE_FINGERPRINT_VERSION,
            schema_version=BASELINE_SCHEMA_VERSION,
            generator_version=__version__,
        )
        try:
            new_baseline.save()
        except OSError as e:
            console.print(
                ui.fmt_contract_error(
                    ui.fmt_baseline_write_failed(path=baseline_path, error=e)
                )
            )
            sys.exit(ExitCode.CONTRACT_ERROR)
        console.print(ui.fmt_path(ui.SUCCESS_BASELINE_UPDATED, baseline_path))
        baseline = new_baseline
        baseline_loaded = True
        baseline_status = BaselineStatus.OK
        baseline_trusted_for_diff = True
        # When updating, we don't fail on new, we just saved the new state.
        # But we might still want to print the summary.

    try:
        report_cache_path = cache_path.resolve()
    except OSError:
        report_cache_path = cache_path

    raw_cache_status = getattr(cache, "load_status", None)
    if isinstance(raw_cache_status, CacheStatus):
        cache_status = raw_cache_status
    elif isinstance(raw_cache_status, str):
        try:
            cache_status = CacheStatus(raw_cache_status)
        except ValueError:
            cache_status = (
                CacheStatus.OK
                if cache.load_warning is None
                else CacheStatus.INVALID_TYPE
            )
    else:
        cache_status = (
            CacheStatus.OK if cache.load_warning is None else CacheStatus.INVALID_TYPE
        )

    raw_cache_schema_version = getattr(cache, "cache_schema_version", None)
    cache_schema_version = (
        raw_cache_schema_version if isinstance(raw_cache_schema_version, str) else None
    )

    report_meta = _build_report_meta(
        codeclone_version=__version__,
        baseline_path=baseline_path,
        baseline=baseline,
        baseline_loaded=baseline_loaded,
        baseline_status=baseline_status.value,
        cache_path=report_cache_path,
        cache_used=cache_status == CacheStatus.OK,
        cache_status=cache_status.value,
        cache_schema_version=cache_schema_version,
        files_skipped_source_io=len(source_read_failures),
    )

    # Diff
    baseline_for_diff = (
        baseline if baseline_trusted_for_diff else Baseline(baseline_path)
    )
    new_func, new_block = baseline_for_diff.diff(func_groups, block_groups)
    new_clones_count = len(new_func) + len(new_block)

    if not args.quiet:
        console.print(Rule(style="dim"))

    _print_summary(
        console=console,
        quiet=args.quiet,
        files_found=files_found,
        files_analyzed=files_analyzed,
        cache_hits=cache_hits,
        files_skipped=files_skipped,
        func_clones_count=func_clones_count,
        block_clones_count=block_clones_count,
        segment_clones_count=segment_clones_count,
        suppressed_segment_groups=suppressed_segment_groups,
        new_clones_count=new_clones_count,
    )

    # Outputs
    html_report_path: str | None = None
    output_notice_printed = False

    def _print_output_notice(message: str) -> None:
        nonlocal output_notice_printed
        if args.quiet:
            return
        if not output_notice_printed:
            console.print("")
            output_notice_printed = True
        console.print(message)

    def _write_report_output(*, out: Path, content: str, label: str) -> None:
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(content, "utf-8")
        except OSError as e:
            console.print(
                ui.fmt_contract_error(
                    ui.fmt_report_write_failed(label=label, path=out, error=e)
                )
            )
            sys.exit(ExitCode.CONTRACT_ERROR)

    if html_out_path:
        out = html_out_path
        _write_report_output(
            out=out,
            content=build_html_report(
                func_groups=func_groups,
                block_groups=block_groups_report,
                segment_groups=segment_groups,
                block_group_facts=block_group_facts,
                new_function_group_keys=new_func,
                new_block_group_keys=new_block,
                report_meta=report_meta,
                title="CodeClone Report",
                context_lines=3,
                max_snippet_lines=220,
            ),
            label="HTML",
        )
        html_report_path = str(out)
        _print_output_notice(ui.fmt_path(ui.INFO_HTML_REPORT_SAVED, out))

    if json_out_path:
        out = json_out_path
        _write_report_output(
            out=out,
            content=to_json_report(
                func_groups,
                block_groups_report,
                segment_groups,
                report_meta,
                block_group_facts,
                new_function_group_keys=new_func,
                new_block_group_keys=new_block,
                new_segment_group_keys=set(segment_groups.keys()),
            ),
            label="JSON",
        )
        _print_output_notice(ui.fmt_path(ui.INFO_JSON_REPORT_SAVED, out))

    if text_out_path:
        out = text_out_path
        _write_report_output(
            out=out,
            content=to_text_report(
                meta=report_meta,
                func_groups=func_groups,
                block_groups=block_groups_report,
                segment_groups=segment_groups,
                new_function_group_keys=new_func,
                new_block_group_keys=new_block,
                new_segment_group_keys=set(segment_groups.keys()),
            ),
            label="text",
        )
        _print_output_notice(ui.fmt_path(ui.INFO_TEXT_REPORT_SAVED, out))

    if source_read_contract_failure:
        console.print(
            ui.fmt_contract_error(
                ui.fmt_unreadable_source_in_gating(count=len(source_read_failures))
            )
        )
        for failure in source_read_failures[:10]:
            console.print(f"  • {failure}")
        if len(source_read_failures) > 10:
            console.print(f"  ... and {len(source_read_failures) - 10} more")
        sys.exit(ExitCode.CONTRACT_ERROR)

    if baseline_failure_code is not None:
        console.print(ui.fmt_contract_error(ui.ERR_BASELINE_GATING_REQUIRES_TRUSTED))
        sys.exit(baseline_failure_code)

    # Exit Codes
    if args.fail_on_new and (new_func or new_block):
        default_report = Path(".cache/codeclone/report.html")
        if html_report_path is None and default_report.exists():
            html_report_path = str(default_report)

        console.print(ui.fmt_gating_failure("New code clones detected."))
        console.print(f"\n{ui.FAIL_NEW_TITLE}")
        console.print(f"\n{ui.FAIL_NEW_SUMMARY_TITLE}")
        console.print(ui.FAIL_NEW_FUNCTION.format(count=len(new_func)))
        console.print(ui.FAIL_NEW_BLOCK.format(count=len(new_block)))
        if html_report_path:
            console.print(f"\n{ui.FAIL_NEW_REPORT_TITLE}")
            console.print(f"  {html_report_path}")
        console.print(f"\n{ui.FAIL_NEW_ACCEPT_TITLE}")
        console.print(ui.FAIL_NEW_ACCEPT_COMMAND)

        if args.verbose:
            if new_func:
                console.print(f"\n{ui.FAIL_NEW_DETAIL_FUNCTION}")
                for h in sorted(new_func):
                    console.print(f"- {h}")
            if new_block:
                console.print(f"\n{ui.FAIL_NEW_DETAIL_BLOCK}")
                for h in sorted(new_block):
                    console.print(f"- {h}")
        sys.exit(ExitCode.GATING_FAILURE)

    if 0 <= args.fail_threshold < (func_clones_count + block_clones_count):
        total = func_clones_count + block_clones_count
        console.print(
            ui.fmt_gating_failure(
                ui.fmt_fail_threshold(total=total, threshold=args.fail_threshold)
            )
        )
        sys.exit(ExitCode.GATING_FAILURE)

    if not args.update_baseline and not args.fail_on_new and new_clones_count > 0:
        console.print(ui.WARN_NEW_CLONES_WITHOUT_FAIL)

    if not args.quiet:
        elapsed = time.monotonic() - t0
        console.print(f"\n[dim]Done in {elapsed:.1f}s[/dim]")


def main() -> None:
    try:
        _main_impl()
    except SystemExit:
        raise
    except Exception as e:
        console.print(
            ui.fmt_internal_error(
                e,
                issues_url=ISSUES_URL,
                debug=_is_debug_enabled(),
            )
        )
        sys.exit(ExitCode.INTERNAL_ERROR)


if __name__ == "__main__":
    main()
