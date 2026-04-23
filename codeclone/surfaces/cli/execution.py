# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from rich.console import Console as RichConsole
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from ... import ui_messages as ui
from ...cache.store import Cache
from ...contracts import DEFAULT_HTML_REPORT_PATH, ExitCode
from ...contracts.errors import CacheError
from ...core._types import AnalysisResult, BootstrapResult, DiscoveryResult
from ...core._types import ProcessingResult as PipelineProcessingResult
from ...core.reporting import GatingResult
from ...models import MetricsDiff
from . import state as cli_state
from .attrs import bool_attr
from .console import PlainConsole
from .types import require_status_console


def run_analysis_stages(
    *,
    args: object,
    boot: BootstrapResult,
    cache: Cache,
    discover_fn: Callable[..., DiscoveryResult],
    process_fn: Callable[..., PipelineProcessingResult],
    analyze_fn: Callable[..., AnalysisResult],
    print_failed_files_fn: Callable[[tuple[str, ...]], None],
    cache_update_segment_projection_fn: Callable[[Cache, AnalysisResult], None],
    rich_progress_symbols_fn: Callable[
        [],
        tuple[
            type[Progress],
            type[SpinnerColumn],
            type[TextColumn],
            type[BarColumn],
            type[TimeElapsedColumn],
        ],
    ],
) -> tuple[DiscoveryResult, PipelineProcessingResult, AnalysisResult]:
    def _require_rich_console(value: object) -> RichConsole:
        if isinstance(value, PlainConsole):
            raise RuntimeError("Rich console is required when progress UI is enabled.")
        if not isinstance(value, RichConsole):
            raise RuntimeError("Rich console is required when progress UI is enabled.")
        return value

    printer = require_status_console(cli_state.get_console())
    use_status = not bool_attr(args, "quiet") and not bool_attr(args, "no_progress")

    try:
        if use_status:
            with printer.status(ui.STATUS_DISCOVERING, spinner="dots"):
                discovery_result = discover_fn(boot=boot, cache=cache)
        else:
            discovery_result = discover_fn(boot=boot, cache=cache)
    except OSError as exc:
        printer.print(ui.fmt_contract_error(ui.ERR_SCAN_FAILED.format(error=exc)))
        sys.exit(ExitCode.CONTRACT_ERROR)

    for warning in discovery_result.skipped_warnings:
        printer.print(ui.fmt_cli_runtime_warning(warning))

    total_files = len(discovery_result.files_to_process)
    if (
        total_files > 0
        and not bool_attr(args, "quiet")
        and bool_attr(args, "no_progress")
    ):
        printer.print(ui.fmt_processing_changed(total_files))

    if total_files > 0 and not bool_attr(args, "no_progress"):
        (
            progress_cls,
            spinner_column_cls,
            text_column_cls,
            bar_column_cls,
            time_elapsed_column_cls,
        ) = rich_progress_symbols_fn()

        with progress_cls(
            spinner_column_cls(),
            text_column_cls("[progress.description]{task.description}"),
            bar_column_cls(),
            text_column_cls("[progress.percentage]{task.percentage:>3.0f}%"),
            time_elapsed_column_cls(),
            console=_require_rich_console(cli_state.get_console()),
        ) as progress_ui:
            task_id = progress_ui.add_task(
                f"Analyzing {total_files} files...",
                total=total_files,
            )
            processing_result = process_fn(
                boot=boot,
                discovery=discovery_result,
                cache=cache,
                on_advance=lambda: progress_ui.advance(task_id),
                on_worker_error=lambda reason: printer.print(
                    ui.fmt_cli_runtime_warning(ui.fmt_worker_failed(reason))
                ),
                on_parallel_fallback=lambda exc: printer.print(
                    ui.fmt_cli_runtime_warning(ui.fmt_parallel_fallback(exc))
                ),
            )
    else:
        processing_result = process_fn(
            boot=boot,
            discovery=discovery_result,
            cache=cache,
            on_worker_error=(
                (
                    lambda reason: printer.print(
                        ui.fmt_cli_runtime_warning(ui.fmt_batch_item_failed(reason))
                    )
                )
                if bool_attr(args, "no_progress")
                else (
                    lambda reason: printer.print(
                        ui.fmt_cli_runtime_warning(ui.fmt_worker_failed(reason))
                    )
                )
            ),
            on_parallel_fallback=lambda exc: printer.print(
                ui.fmt_cli_runtime_warning(ui.fmt_parallel_fallback(exc))
            ),
        )

    print_failed_files_fn(tuple(processing_result.failed_files))
    if not processing_result.failed_files and processing_result.source_read_failures:
        print_failed_files_fn(tuple(processing_result.source_read_failures))

    if use_status:
        with printer.status(ui.STATUS_GROUPING, spinner="dots"):
            analysis_result = analyze_fn(
                boot=boot,
                discovery=discovery_result,
                processing=processing_result,
            )
            cache_update_segment_projection_fn(cache, analysis_result)
            try:
                cache.save()
            except CacheError as exc:
                printer.print(ui.fmt_cli_runtime_warning(ui.fmt_cache_save_failed(exc)))
    else:
        analysis_result = analyze_fn(
            boot=boot,
            discovery=discovery_result,
            processing=processing_result,
        )
        cache_update_segment_projection_fn(cache, analysis_result)
        try:
            cache.save()
        except CacheError as exc:
            printer.print(ui.fmt_cli_runtime_warning(ui.fmt_cache_save_failed(exc)))

    coverage_join = getattr(analysis_result, "coverage_join", None)
    if (
        coverage_join is not None
        and coverage_join.status != "ok"
        and coverage_join.invalid_reason
    ):
        printer.print(
            ui.fmt_cli_runtime_warning(
                ui.fmt_coverage_join_ignored(coverage_join.invalid_reason)
            )
        )

    return discovery_result, processing_result, analysis_result


def enforce_gating(
    *,
    args: object,
    boot: BootstrapResult,
    analysis: AnalysisResult,
    processing: PipelineProcessingResult,
    source_read_contract_failure: bool,
    baseline_failure_code: ExitCode | None,
    metrics_baseline_failure_code: ExitCode | None,
    new_func: set[str],
    new_block: set[str],
    metrics_diff: MetricsDiff | None,
    html_report_path: str | None,
    gate_fn: Callable[..., GatingResult],
    parse_metric_reason_entry_fn: Callable[[str], tuple[str, str]],
    print_gating_failure_block_fn: Callable[..., None],
    print_verbose_clone_hashes_fn: Callable[..., None],
    clone_threshold_total: int | None = None,
) -> None:
    printer = require_status_console(cli_state.get_console())

    if source_read_contract_failure:
        printer.print(
            ui.fmt_contract_error(
                ui.fmt_unreadable_source_in_gating(
                    count=len(processing.source_read_failures)
                )
            )
        )
        for failure in processing.source_read_failures[:10]:
            printer.print(f"  • {failure}")
        if len(processing.source_read_failures) > 10:
            printer.print(f"  ... and {len(processing.source_read_failures) - 10} more")
        sys.exit(ExitCode.CONTRACT_ERROR)

    if baseline_failure_code is not None:
        printer.print(ui.fmt_contract_error(ui.ERR_BASELINE_GATING_REQUIRES_TRUSTED))
        sys.exit(baseline_failure_code)

    if metrics_baseline_failure_code is not None:
        printer.print(
            ui.fmt_contract_error(
                "Metrics baseline is untrusted or missing for requested metrics gating."
            )
        )
        sys.exit(metrics_baseline_failure_code)

    if bool_attr(args, "fail_on_untested_hotspots"):
        if analysis.coverage_join is None:
            printer.print(
                ui.fmt_contract_error(
                    "--fail-on-untested-hotspots requires --coverage."
                )
            )
            sys.exit(ExitCode.CONTRACT_ERROR)
        if analysis.coverage_join.status != "ok":
            detail = analysis.coverage_join.invalid_reason or "invalid coverage input"
            printer.print(
                ui.fmt_contract_error(
                    "Coverage gating requires a valid Cobertura XML input.\n"
                    f"Reason: {detail}"
                )
            )
            sys.exit(ExitCode.CONTRACT_ERROR)

    gating_analysis = analysis
    if clone_threshold_total is not None:
        preserved_block_count = min(
            max(analysis.block_clones_count, 0),
            max(clone_threshold_total, 0),
        )
        gating_analysis = replace(
            analysis,
            func_clones_count=max(clone_threshold_total - preserved_block_count, 0),
            block_clones_count=preserved_block_count,
        )

    gate_result = gate_fn(
        boot=boot,
        analysis=gating_analysis,
        new_func=new_func,
        new_block=new_block,
        metrics_diff=metrics_diff,
    )

    metric_reasons = [
        reason[len("metric:") :]
        for reason in gate_result.reasons
        if reason.startswith("metric:")
    ]
    if metric_reasons:
        print_gating_failure_block_fn(
            code="metrics",
            entries=[parse_metric_reason_entry_fn(reason) for reason in metric_reasons],
            args=args,
        )
        sys.exit(ExitCode.GATING_FAILURE)

    if "clone:new" in gate_result.reasons:
        default_report = Path(DEFAULT_HTML_REPORT_PATH)
        resolved_html_report_path = html_report_path
        if resolved_html_report_path is None and default_report.exists():
            resolved_html_report_path = str(default_report)

        clone_entries: list[tuple[str, object]] = [
            ("new_function_clone_groups", len(new_func)),
            ("new_block_clone_groups", len(new_block)),
        ]
        if resolved_html_report_path:
            clone_entries.append(("report", resolved_html_report_path))
        clone_entries.append(("accept", "codeclone . --update-baseline"))
        print_gating_failure_block_fn(
            code="new-clones",
            entries=clone_entries,
            args=args,
        )

        if bool_attr(args, "verbose"):
            print_verbose_clone_hashes_fn(
                printer,
                label="Function clone hashes",
                clone_hashes=new_func,
            )
            print_verbose_clone_hashes_fn(
                printer,
                label="Block clone hashes",
                clone_hashes=new_block,
            )

        sys.exit(ExitCode.GATING_FAILURE)

    threshold_reason = next(
        (
            reason
            for reason in gate_result.reasons
            if reason.startswith("clone:threshold:")
        ),
        None,
    )
    if threshold_reason is not None:
        _, _, total_raw, threshold_raw = threshold_reason.split(":", maxsplit=3)
        print_gating_failure_block_fn(
            code="threshold",
            entries=(
                ("clone_groups_total", int(total_raw)),
                ("clone_groups_limit", int(threshold_raw)),
            ),
            args=args,
        )
        sys.exit(ExitCode.GATING_FAILURE)


def print_pipeline_done_if_needed(*, args: object, run_started_at: float) -> None:
    if bool_attr(args, "quiet"):
        return
    elapsed = time.monotonic() - run_started_at
    printer = require_status_console(cli_state.get_console())
    printer.print()
    printer.print(ui.fmt_pipeline_done(elapsed))
