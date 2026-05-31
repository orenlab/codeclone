# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ... import __version__
from ...cache.store import Cache
from ...config.argparse_builder import build_parser
from ...config.pyproject_loader import load_pyproject_config
from ...config.resolver import apply_pyproject_config_overrides
from ...contracts import DEFAULT_JSON_REPORT_PATH
from ...core.bootstrap import bootstrap
from ...core.discovery import discover
from ...core.parallelism import process
from ...core.pipeline import analyze
from ...core.reporting import report
from ...memory.report_trust import assess_cached_report_trust
from ...report.html import build_html_report
from ...utils.json_io import read_json_object
from . import baseline_state as cli_baseline_state
from . import execution as cli_execution
from . import post_run as cli_post_run
from . import report_meta as cli_meta_mod
from . import reports_output as cli_reports_output
from . import runtime as cli_runtime
from . import startup as cli_startup
from . import state as cli_state
from .console import PlainConsole
from .types import require_status_console

ReportSource = Literal["explicit_report", "trusted_cache", "fresh_analysis"]


@dataclass(frozen=True, slots=True)
class LoadedMemoryReport:
    document: dict[str, object]
    source: ReportSource
    rejected_cache_reason: str | None = None


def _rich_progress_symbols() -> tuple[type, type, type, type, type]:
    from rich.progress import (
        BarColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
    )

    return Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn


def load_report_for_memory_init(
    *,
    root_path: Path,
    from_report: Path | None,
) -> LoadedMemoryReport:
    if from_report is not None:
        return LoadedMemoryReport(
            document=read_json_object(from_report.resolve()),
            source="explicit_report",
        )

    default_path = root_path / DEFAULT_JSON_REPORT_PATH
    if default_path.is_file():
        report_document = read_json_object(default_path)
        trust = assess_cached_report_trust(
            root_path=root_path,
            report_path=default_path,
            report_document=report_document,
        )
        if trust.trusted:
            return LoadedMemoryReport(
                document=report_document,
                source="trusted_cache",
            )
        return LoadedMemoryReport(
            document=run_memory_analysis_report(root_path=root_path),
            source="fresh_analysis",
            rejected_cache_reason=trust.reason,
        )

    return LoadedMemoryReport(
        document=run_memory_analysis_report(root_path=root_path),
        source="fresh_analysis",
    )


def run_memory_analysis_report(*, root_path: Path) -> dict[str, object]:
    ap = build_parser(__version__)
    args = ap.parse_args([str(root_path), "--quiet", "--no-progress"])
    pyproject_config = load_pyproject_config(root_path)
    apply_pyproject_config_overrides(
        args=args,
        config_values=pyproject_config,
        explicit_cli_dests=set(),
    )
    cli_state.set_console(PlainConsole())
    printer = require_status_console(cli_state.get_console())
    started = cli_meta_mod._current_report_timestamp_utc()
    baseline_inputs = cli_startup.resolve_baseline_inputs(
        ap=ap,
        args=args,
        root_path=root_path,
        baseline_path_from_args=False,
        metrics_path_from_args=False,
        probe_metrics_baseline_section_fn=(
            cli_baseline_state._probe_metrics_baseline_section
        ),
        printer=printer,
    )
    cache_path = cli_runtime._resolve_cache_path(
        args=args,
        root_path=root_path,
        from_args=False,
    )
    output_paths = cli_reports_output._resolve_output_paths(
        args,
        report_path_origins=cli_reports_output._report_path_origins([]),
        report_generated_at_utc=started,
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
        collect_api_surface=True,
    )
    cache.load()
    boot = bootstrap(
        args=args,
        root=root_path,
        output_paths=output_paths,
        cache_path=cache_path,
    )
    discovery_result, processing_result, analysis_result = (
        cli_execution.run_analysis_stages(
            args=args,
            boot=boot,
            cache=cache,
            discover_fn=discover,
            process_fn=process,
            analyze_fn=analyze,
            print_failed_files_fn=lambda _paths: None,
            cache_update_segment_projection_fn=lambda _cache, _analysis: None,
            rich_progress_symbols_fn=_rich_progress_symbols,
        )
    )
    shared_baseline_payload = (
        baseline_inputs.shared_baseline_payload
        if baseline_inputs.metrics_baseline_path == baseline_inputs.baseline_path
        else None
    )
    baseline_state = cli_baseline_state._resolve_clone_baseline_state(
        args=args,
        baseline_path=baseline_inputs.baseline_path,
        baseline_exists=baseline_inputs.baseline_exists,
        analysis=analysis_result,
        shared_baseline_payload=shared_baseline_payload,
    )
    metrics_baseline_state = cli_baseline_state._resolve_metrics_baseline_state(
        args=args,
        metrics_baseline_path=baseline_inputs.metrics_baseline_path,
        metrics_baseline_exists=baseline_inputs.metrics_baseline_exists,
        clone_baseline_state=baseline_state,
        baseline_updated_path=baseline_state.updated_path,
        analysis=analysis_result,
        shared_baseline_payload=shared_baseline_payload,
    )
    cache_status, cache_schema_version = cli_runtime._resolve_cache_status(cache)
    report_meta = cli_meta_mod.build_cli_report_meta(
        codeclone_version=__version__,
        scan_root=root_path,
        baseline_path=baseline_inputs.baseline_path,
        baseline_state=baseline_state,
        cache_path=cli_runtime.resolve_report_cache_path(cache_path),
        cache_status=cache_status,
        cache_schema_version=cache_schema_version,
        processing_result=processing_result,
        metrics_baseline_path=baseline_inputs.metrics_baseline_path,
        metrics_baseline_state=metrics_baseline_state,
        analysis_result=analysis_result,
        args=args,
        metrics_computed=cli_runtime._metrics_computed(args),
        analysis_started_at_utc=started,
        report_generated_at_utc=started,
    )
    diff_context = cli_post_run.build_diff_context(
        analysis=analysis_result,
        baseline_path=baseline_inputs.baseline_path,
        baseline_state=baseline_state,
        metrics_baseline_state=metrics_baseline_state,
    )
    artifacts = report(
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
        include_report_document=True,
    )
    if artifacts.report_document is None:
        msg = "Memory init analysis did not produce a canonical report document."
        raise RuntimeError(msg)
    return artifacts.report_document


__all__ = [
    "LoadedMemoryReport",
    "ReportSource",
    "load_report_for_memory_init",
    "run_memory_analysis_report",
]
