# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Protocol, cast

from ... import ui_messages as ui
from ...cache.store import Cache
from ...contracts import ExitCode
from ...contracts.errors import CacheError
from ...core._types import AnalysisResult, BootstrapResult, DiscoveryResult
from ...core._types import ProcessingResult as PipelineProcessingResult
from . import state as cli_state
from .console import PlainConsole


class _PrinterLike(Protocol):
    def print(self, *objects: object, **kwargs: object) -> None: ...


def run_analysis_stages(
    *,
    args: object,
    boot: BootstrapResult,
    cache: Cache,
    discover_fn: Any,
    process_fn: Any,
    analyze_fn: Any,
    print_failed_files_fn: Any,
    cache_update_segment_projection_fn: Any,
    rich_progress_symbols_fn: Any,
) -> tuple[DiscoveryResult, PipelineProcessingResult, AnalysisResult]:
    def _require_rich_console(value: object) -> object:
        if isinstance(value, PlainConsole):
            raise RuntimeError("Rich console is required when progress UI is enabled.")
        return value

    args_obj = cast("Any", args)
    printer = cast("_PrinterLike", cli_state.get_console())
    use_status = not args_obj.quiet and not args_obj.no_progress

    try:
        if use_status:
            with cast("Any", printer).status(ui.STATUS_DISCOVERING, spinner="dots"):
                discovery_result = discover_fn(boot=boot, cache=cache)
        else:
            discovery_result = discover_fn(boot=boot, cache=cache)
    except OSError as exc:
        printer.print(ui.fmt_contract_error(ui.ERR_SCAN_FAILED.format(error=exc)))
        sys.exit(ExitCode.CONTRACT_ERROR)

    for warning in discovery_result.skipped_warnings:
        printer.print(f"[warning]{warning}[/warning]")

    total_files = len(discovery_result.files_to_process)
    if total_files > 0 and not args_obj.quiet and args_obj.no_progress:
        printer.print(ui.fmt_processing_changed(total_files))

    if total_files > 0 and not args_obj.no_progress:
        (
            progress_cls,
            spinner_column_cls,
            text_column_cls,
            bar_column_cls,
            time_elapsed_column_cls,
        ) = rich_progress_symbols_fn()

        progress_factory = cast("Any", progress_cls)
        with progress_factory(
            cast("Any", spinner_column_cls)(),
            cast("Any", text_column_cls)("[progress.description]{task.description}"),
            cast("Any", bar_column_cls)(),
            cast("Any", text_column_cls)(
                "[progress.percentage]{task.percentage:>3.0f}%"
            ),
            cast("Any", time_elapsed_column_cls)(),
            console=_require_rich_console(cli_state.get_console()),
        ) as progress_ui:
            progress_ui_any = cast("Any", progress_ui)
            task_id = progress_ui_any.add_task(
                f"Analyzing {total_files} files...",
                total=total_files,
            )
            processing_result = process_fn(
                boot=boot,
                discovery=discovery_result,
                cache=cache,
                on_advance=lambda: progress_ui_any.advance(task_id),
                on_worker_error=lambda reason: printer.print(
                    ui.fmt_worker_failed(reason)
                ),
                on_parallel_fallback=lambda exc: printer.print(
                    ui.fmt_parallel_fallback(exc)
                ),
            )
    else:
        processing_result = process_fn(
            boot=boot,
            discovery=discovery_result,
            cache=cache,
            on_worker_error=(
                (lambda reason: printer.print(ui.fmt_batch_item_failed(reason)))
                if args_obj.no_progress
                else (lambda reason: printer.print(ui.fmt_worker_failed(reason)))
            ),
            on_parallel_fallback=lambda exc: printer.print(
                ui.fmt_parallel_fallback(exc)
            ),
        )

    print_failed_files_fn(tuple(processing_result.failed_files))
    if not processing_result.failed_files and processing_result.source_read_failures:
        print_failed_files_fn(tuple(processing_result.source_read_failures))

    if use_status:
        with cast("Any", printer).status(ui.STATUS_GROUPING, spinner="dots"):
            analysis_result = analyze_fn(
                boot=boot,
                discovery=discovery_result,
                processing=processing_result,
            )
            cache_update_segment_projection_fn(cache, analysis_result)
            try:
                cache.save()
            except CacheError as exc:
                printer.print(ui.fmt_cache_save_failed(exc))
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
            printer.print(ui.fmt_cache_save_failed(exc))

    coverage_join = getattr(analysis_result, "coverage_join", None)
    if (
        coverage_join is not None
        and coverage_join.status != "ok"
        and coverage_join.invalid_reason
    ):
        printer.print(ui.fmt_coverage_join_ignored(coverage_join.invalid_reason))

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
    metrics_diff: object | None,
    html_report_path: str | None,
    gate_fn: Any,
    parse_metric_reason_entry_fn: Any,
    print_gating_failure_block_fn: Any,
    print_verbose_clone_hashes_fn: Any,
    clone_threshold_total: int | None = None,
) -> None:
    args_obj = cast("Any", args)
    printer = cast("_PrinterLike", cli_state.get_console())

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

    if bool(getattr(args_obj, "fail_on_untested_hotspots", False)):
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
        metrics_diff=cast("Any", metrics_diff),
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
            args=args_obj,
        )
        sys.exit(ExitCode.GATING_FAILURE)

    if "clone:new" in gate_result.reasons:
        default_report = Path(".cache/codeclone/report.html")
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
            args=args_obj,
        )

        if args_obj.verbose:
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
            args=args_obj,
        )
        sys.exit(ExitCode.GATING_FAILURE)


def print_pipeline_done_if_needed(*, args: object, run_started_at: float) -> None:
    args_obj = cast("Any", args)
    if args_obj.quiet:
        return
    elapsed = time.monotonic() - run_started_at
    printer = cast("_PrinterLike", cli_state.get_console())
    printer.print()
    printer.print(ui.fmt_pipeline_done(elapsed))
