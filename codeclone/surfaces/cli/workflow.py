# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Protocol, cast

from ... import __version__
from ... import ui_messages as ui
from ...baseline import Baseline
from ...cache.projection import build_segment_report_projection
from ...cache.store import Cache
from ...config.argparse_builder import build_parser
from ...config.pyproject_loader import load_pyproject_config
from ...config.resolver import (
    apply_pyproject_config_overrides,
    collect_explicit_cli_dests,
)
from ...contracts import (
    ISSUES_URL,
    ExitCode,
)
from ...core._types import AnalysisResult, BootstrapResult, DiscoveryResult
from ...core._types import ProcessingResult as PipelineProcessingResult
from ...core.bootstrap import bootstrap
from ...core.discovery import discover
from ...core.parallelism import process
from ...core.pipeline import analyze
from ...core.reporting import gate, report
from ...report.html import build_html_report
from . import report_meta as cli_meta_mod
from . import state as cli_state
from .baseline_state import (
    _probe_metrics_baseline_section,
    _resolve_clone_baseline_state,
    _resolve_metrics_baseline_state,
)
from .changed_scope import (
    _changed_clone_gate_from_report,
    _git_diff_changed_paths,
    _validate_changed_scope_args,
)
from .console import (
    _is_debug_enabled,
    _make_plain_console,
    _parse_metric_reason_entry,
    _print_gating_failure_block,
    _print_verbose_clone_hashes,
    _rich_progress_symbols,
)
from .console import make_console as _make_rich_console
from .console import print_banner as _print_banner_impl
from .execution import (
    enforce_gating,
    print_pipeline_done_if_needed,
    run_analysis_stages,
)
from .post_run import build_diff_context as _build_diff_context
from .post_run import (
    maybe_print_changed_scope_snapshot,
    print_metrics_if_available,
    resolve_changed_clone_gate,
    warn_new_clones_without_fail,
)
from .reports_output import (
    _report_path_origins,
    _resolve_output_paths,
    _validate_report_ui_flags,
    _write_report_outputs,
)
from .runtime import (
    _configure_metrics_mode,
    _metrics_computed,
    _print_failed_files,
    _resolve_cache_status,
    _validate_numeric_args,
    gating_mode_enabled,
    prepare_metrics_mode_and_ui,
    resolve_report_cache_path,
)
from .runtime import _resolve_cache_path as _resolve_cache_path_impl
from .startup import configure_runtime_console as _configure_runtime_console_impl
from .startup import configure_runtime_flags as _configure_runtime_flags
from .startup import load_pyproject_config_or_exit as _load_pyproject_config_or_exit
from .startup import resolve_baseline_inputs as _resolve_baseline_inputs
from .startup import resolve_existing_root_path as _resolve_existing_root_path
from .startup import validate_numeric_args_or_exit as _validate_numeric_args_or_exit
from .summary import (
    _print_changed_scope,
    _print_metrics,
    _print_summary,
    build_metrics_snapshot,
    build_summary_counts,
)

__all__ = [
    "LEGACY_CACHE_PATH",
    "Baseline",
    "Cache",
    "ExitCode",
    "_changed_clone_gate_from_report",
    "_configure_metrics_mode",
    "_enforce_gating",
    "_git_diff_changed_paths",
    "_main_impl",
    "_make_console",
    "_make_plain_console",
    "_make_rich_console",
    "_print_changed_scope",
    "_print_failed_files",
    "_print_gating_failure_block",
    "_print_summary",
    "_probe_metrics_baseline_section",
    "_resolve_cache_path",
    "_resolve_clone_baseline_state",
    "_resolve_metrics_baseline_state",
    "_rich_progress_symbols",
    "_run_analysis_stages",
    "_validate_report_ui_flags",
    "_write_report_outputs",
    "analyze",
    "bootstrap",
    "build_html_report",
    "console",
    "discover",
    "gate",
    "main",
    "print_banner",
    "process",
    "report",
]


class _PrinterLike(Protocol):
    def print(self, *objects: object, **kwargs: object) -> None: ...


def _set_console(value: object) -> object:
    cli_state.set_console(value)
    return value


def _console() -> _PrinterLike:
    return cast("_PrinterLike", _set_console(console))


def _make_console(*, no_color: bool) -> object:
    return _make_rich_console(no_color=no_color, width=ui.CLI_LAYOUT_MAX_WIDTH)


console: object = _make_plain_console()
_set_console(console)
LEGACY_CACHE_PATH = cli_state.LEGACY_CACHE_PATH


def print_banner(*, root: Path | None = None) -> None:
    _set_console(console)
    _print_banner_impl(root=root)


def _configure_runtime_console(args: object) -> None:
    global console
    console = _configure_runtime_console_impl(
        args=args,
        make_plain_console=_make_plain_console,
        make_console=_make_console,
        set_console=_set_console,
    )


def _resolve_cache_path(*, root_path: Path, args: object, from_args: bool) -> Path:
    cli_state.LEGACY_CACHE_PATH = LEGACY_CACHE_PATH
    _set_console(console)
    return _resolve_cache_path_impl(
        root_path=cast("Any", root_path),
        args=args,
        from_args=from_args,
    )


def _cache_update_segment_projection(cache: Cache, analysis: AnalysisResult) -> None:
    if not hasattr(cache, "segment_report_projection"):
        return
    new_projection = build_segment_report_projection(
        digest=analysis.segment_groups_raw_digest,
        suppressed=analysis.suppressed_segment_groups,
        groups=analysis.segment_groups,
    )
    if new_projection != cache.segment_report_projection:
        cache.segment_report_projection = new_projection
        cache._dirty = True


def _run_analysis_stages(
    *,
    args: object,
    boot: BootstrapResult,
    cache: Cache,
) -> tuple[DiscoveryResult, PipelineProcessingResult, AnalysisResult]:
    _set_console(console)
    return run_analysis_stages(
        args=args,
        boot=boot,
        cache=cache,
        discover_fn=discover,
        process_fn=process,
        analyze_fn=analyze,
        print_failed_files_fn=_print_failed_files,
        cache_update_segment_projection_fn=_cache_update_segment_projection,
        rich_progress_symbols_fn=_rich_progress_symbols,
    )


def _enforce_gating(
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
    clone_threshold_total: int | None = None,
) -> None:
    _set_console(console)
    enforce_gating(
        args=args,
        boot=boot,
        analysis=analysis,
        processing=processing,
        source_read_contract_failure=source_read_contract_failure,
        baseline_failure_code=baseline_failure_code,
        metrics_baseline_failure_code=metrics_baseline_failure_code,
        new_func=new_func,
        new_block=new_block,
        metrics_diff=metrics_diff,
        html_report_path=html_report_path,
        gate_fn=gate,
        parse_metric_reason_entry_fn=_parse_metric_reason_entry,
        print_gating_failure_block_fn=_print_gating_failure_block,
        print_verbose_clone_hashes_fn=_print_verbose_clone_hashes,
        clone_threshold_total=clone_threshold_total,
    )


def _main_impl() -> None:
    run_started_at = time.monotonic()
    analysis_started_at_utc = cli_meta_mod._current_report_timestamp_utc()
    ap = build_parser(__version__)

    raw_argv = tuple(sys.argv[1:])
    explicit_cli_dests = collect_explicit_cli_dests(ap, argv=raw_argv)
    report_path_origins = _report_path_origins(raw_argv)
    report_generated_at_utc = cli_meta_mod._current_report_timestamp_utc()
    cache_path_from_args = any(
        arg in {"--cache-dir", "--cache-path"}
        or arg.startswith(("--cache-dir=", "--cache-path="))
        for arg in sys.argv
    )
    baseline_path_from_args = any(
        arg == "--baseline" or arg.startswith("--baseline=") for arg in sys.argv
    )
    metrics_path_from_args = any(
        arg == "--metrics-baseline" or arg.startswith("--metrics-baseline=")
        for arg in sys.argv
    )
    args = ap.parse_args()

    root_path = _resolve_existing_root_path(args=args, printer=_console())
    pyproject_config = _load_pyproject_config_or_exit(
        root_path=root_path,
        load_pyproject_config_fn=load_pyproject_config,
        printer=_console(),
    )
    apply_pyproject_config_overrides(
        args=args,
        config_values=pyproject_config,
        explicit_cli_dests=explicit_cli_dests,
    )
    git_diff_ref = _validate_changed_scope_args(args=args)
    changed_paths = (
        _git_diff_changed_paths(root_path=root_path, git_diff_ref=git_diff_ref)
        if git_diff_ref is not None
        else ()
    )
    _configure_runtime_flags(args)
    _configure_runtime_console(args)
    _validate_numeric_args_or_exit(
        args=args,
        validate_numeric_args_fn=_validate_numeric_args,
        printer=_console(),
    )
    baseline_inputs = _resolve_baseline_inputs(
        ap=ap,
        args=args,
        root_path=root_path,
        baseline_path_from_args=baseline_path_from_args,
        metrics_path_from_args=metrics_path_from_args,
        probe_metrics_baseline_section_fn=_probe_metrics_baseline_section,
        printer=_console(),
    )
    prepare_metrics_mode_and_ui(
        args=args,
        root_path=root_path,
        baseline_path=baseline_inputs.baseline_path,
        baseline_exists=baseline_inputs.baseline_exists,
        metrics_baseline_path=baseline_inputs.metrics_baseline_path,
        metrics_baseline_exists=baseline_inputs.metrics_baseline_exists,
        configure_metrics_mode=_configure_metrics_mode,
        print_banner=print_banner,
    )

    output_paths = _resolve_output_paths(
        args,
        report_path_origins=report_path_origins,
        report_generated_at_utc=report_generated_at_utc,
    )
    _validate_report_ui_flags(args=args, output_paths=output_paths)
    cache_path = _resolve_cache_path(
        root_path=root_path,
        args=args,
        from_args=cache_path_from_args,
    )

    cache = Cache(
        cache_path,
        root=root_path,
        max_size_bytes=args.max_cache_size_mb * 1024 * 1024,
        min_loc=args.min_loc,
        min_stmt=args.min_stmt,
        block_min_loc=args.block_min_loc,
        block_min_stmt=args.block_min_stmt,
        segment_min_loc=args.segment_min_loc,
        segment_min_stmt=args.segment_min_stmt,
        collect_api_surface=bool(args.api_surface),
    )
    cache.load()
    if cache.load_warning:
        _console().print(f"[warning]{cache.load_warning}[/warning]")

    boot = bootstrap(
        args=args,
        root=root_path,
        output_paths=output_paths,
        cache_path=cache_path,
    )
    discovery_result, processing_result, analysis_result = _run_analysis_stages(
        args=args,
        boot=boot,
        cache=cache,
    )

    source_read_contract_failure = (
        bool(processing_result.source_read_failures)
        and gating_mode_enabled(args)
        and not args.update_baseline
    )
    shared_baseline_payload = (
        baseline_inputs.shared_baseline_payload
        if baseline_inputs.metrics_baseline_path == baseline_inputs.baseline_path
        else None
    )
    baseline_state = _resolve_clone_baseline_state(
        args=args,
        baseline_path=baseline_inputs.baseline_path,
        baseline_exists=baseline_inputs.baseline_exists,
        analysis=analysis_result,
        shared_baseline_payload=shared_baseline_payload,
    )
    metrics_baseline_state = _resolve_metrics_baseline_state(
        args=args,
        metrics_baseline_path=baseline_inputs.metrics_baseline_path,
        metrics_baseline_exists=baseline_inputs.metrics_baseline_exists,
        baseline_updated_path=baseline_state.updated_path,
        analysis=analysis_result,
        shared_baseline_payload=shared_baseline_payload,
    )

    cache_status, cache_schema_version = _resolve_cache_status(cache)
    report_meta = cli_meta_mod.build_cli_report_meta(
        codeclone_version=__version__,
        scan_root=root_path,
        baseline_path=baseline_inputs.baseline_path,
        baseline_state=baseline_state,
        cache_path=resolve_report_cache_path(cache_path),
        cache_status=cache_status,
        cache_schema_version=cache_schema_version,
        processing_result=processing_result,
        metrics_baseline_path=baseline_inputs.metrics_baseline_path,
        metrics_baseline_state=metrics_baseline_state,
        analysis_result=analysis_result,
        args=args,
        metrics_computed=_metrics_computed(args),
        analysis_started_at_utc=analysis_started_at_utc,
        report_generated_at_utc=report_generated_at_utc,
    )

    diff_context = _build_diff_context(
        analysis=analysis_result,
        baseline_path=baseline_inputs.baseline_path,
        baseline_state=baseline_state,
        metrics_baseline_state=metrics_baseline_state,
    )
    summary_counts = build_summary_counts(
        discovery_result=discovery_result,
        processing_result=processing_result,
    )
    _print_summary(
        console=_console(),
        quiet=args.quiet,
        files_found=discovery_result.files_found,
        files_analyzed=processing_result.files_analyzed,
        cache_hits=discovery_result.cache_hits,
        files_skipped=processing_result.files_skipped,
        analyzed_lines=summary_counts["analyzed_lines"],
        analyzed_functions=summary_counts["analyzed_functions"],
        analyzed_methods=summary_counts["analyzed_methods"],
        analyzed_classes=summary_counts["analyzed_classes"],
        func_clones_count=analysis_result.func_clones_count,
        block_clones_count=analysis_result.block_clones_count,
        segment_clones_count=analysis_result.segment_clones_count,
        suppressed_golden_fixture_groups=len(
            getattr(analysis_result, "suppressed_clone_groups", ())
        ),
        suppressed_segment_groups=analysis_result.suppressed_segment_groups,
        new_clones_count=diff_context.new_clones_count,
    )
    print_metrics_if_available(
        args=args,
        analysis=analysis_result,
        metrics_diff=diff_context.metrics_diff,
        api_surface_diff_available=diff_context.api_surface_diff_available,
        console=_console(),
        build_metrics_snapshot_fn=build_metrics_snapshot,
        print_metrics_fn=_print_metrics,
    )

    report_artifacts = report(
        boot=boot,
        discovery=discovery_result,
        processing=processing_result,
        analysis=analysis_result,
        report_meta=report_meta,
        new_func=diff_context.new_func,
        new_block=diff_context.new_block,
        html_builder=build_html_report,
        metrics_diff=diff_context.metrics_diff,
        coverage_adoption_diff_available=diff_context.coverage_adoption_diff_available,
        api_surface_diff_available=diff_context.api_surface_diff_available,
        include_report_document=bool(changed_paths),
    )
    changed_clone_gate = resolve_changed_clone_gate(
        args=args,
        report_document=report_artifacts.report_document,
        changed_paths=changed_paths,
        changed_clone_gate_from_report_fn=_changed_clone_gate_from_report,
    )
    maybe_print_changed_scope_snapshot(
        args=args,
        changed_clone_gate=changed_clone_gate,
        console=_console(),
        print_changed_scope_fn=_print_changed_scope,
    )
    html_report_path = _write_report_outputs(
        args=args,
        output_paths=output_paths,
        report_artifacts=report_artifacts,
        open_html_report=args.open_html_report,
    )

    _enforce_gating(
        args=args,
        boot=boot,
        analysis=analysis_result,
        processing=processing_result,
        source_read_contract_failure=source_read_contract_failure,
        baseline_failure_code=baseline_state.failure_code,
        metrics_baseline_failure_code=metrics_baseline_state.failure_code,
        new_func=(
            set(changed_clone_gate.new_func)
            if changed_clone_gate
            else diff_context.new_func
        ),
        new_block=(
            set(changed_clone_gate.new_block)
            if changed_clone_gate
            else diff_context.new_block
        ),
        metrics_diff=diff_context.metrics_diff,
        html_report_path=html_report_path,
        clone_threshold_total=(
            changed_clone_gate.total_clone_groups if changed_clone_gate else None
        ),
    )

    notice_new_clones_count = (
        len(changed_clone_gate.new_func) + len(changed_clone_gate.new_block)
        if changed_clone_gate is not None
        else diff_context.new_clones_count
    )
    warn_new_clones_without_fail(
        args=args,
        notice_new_clones_count=notice_new_clones_count,
        console=_console(),
    )
    print_pipeline_done_if_needed(args=args, run_started_at=run_started_at)


def main() -> None:
    try:
        _main_impl()
    except SystemExit:
        raise
    except Exception as exc:
        _console().print(
            ui.fmt_internal_error(
                exc,
                issues_url=ISSUES_URL,
                debug=_is_debug_enabled(),
            )
        )
        raise SystemExit(ExitCode.INTERNAL_ERROR) from exc
