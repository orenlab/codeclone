# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import functools
import sys
import time
from pathlib import Path
from typing import Protocol, TypeGuard

from ... import __version__
from ... import ui_messages as ui
from ...baseline import Baseline
from ...cache.projection import build_segment_report_projection
from ...cache.store import Cache
from ...config import resolver as config_resolver
from ...config.argparse_builder import build_parser
from ...config.observability import resolve_observability_config
from ...config.pyproject_loader import load_pyproject_config
from ...contracts import (
    ISSUES_URL,
    ExitCode,
    observed_population,
)
from ...contracts.errors import DiagnosedUserError
from ...core._types import AnalysisResult, BootstrapResult, DiscoveryResult
from ...core._types import ProcessingResult as PipelineProcessingResult
from ...core.bootstrap import bootstrap
from ...core.discovery import discover
from ...core.parallelism import process
from ...core.pipeline import analyze
from ...core.reporting import (
    GatingResult,
    build_report_body_for_analysis,
    gate,
    gate_required_lanes,
    gate_with_config,
    report,
    report_document_required,
    resolve_report_baseline_trust,
)
from ...observability import bootstrap as start_observability
from ...observability import operation, span
from ...report.html import build_html_report
from ...utils.run_identity import report_run_identity
from . import baseline_state as cli_baseline_state
from . import changed_scope as cli_changed_scope
from . import console as cli_console
from . import controller_queries as cli_controller_queries
from . import execution as cli_execution
from . import post_run as cli_post_run
from . import report_meta as cli_meta_mod
from . import reports_output as cli_reports_output
from . import runtime as cli_runtime
from . import startup as cli_startup
from . import state as cli_state
from . import summary as cli_summary
from . import tips as cli_tips
from .attrs import bool_attr
from .subcommands import dispatch_subcommand
from .types import CLIArgsLike, StatusConsole, require_status_console

_CLI_SESSION_START_EPOCH = cli_state.CLI_SESSION_START_EPOCH


class _AuditEnabledArgs(Protocol):
    audit_enabled: bool


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
    "_validate_controller_query_flags",
    "_validate_report_ui_flags",
    "_write_report_outputs",
    "analyze",
    "apply_pyproject_config_overrides",
    "bootstrap",
    "build_html_report",
    "collect_explicit_cli_dests",
    "console",
    "discover",
    "gate",
    "main",
    "maybe_print_gitignore_codeclone_cache_tip",
    "maybe_print_vscode_extension_tip",
    "print_banner",
    "process",
    "report",
]

apply_pyproject_config_overrides = config_resolver.apply_pyproject_config_overrides
collect_explicit_cli_dests = config_resolver.collect_explicit_cli_dests

_probe_metrics_baseline_section = cli_baseline_state._probe_metrics_baseline_section
_resolve_clone_baseline_state = cli_baseline_state._resolve_clone_baseline_state
_resolve_metrics_baseline_state = cli_baseline_state._resolve_metrics_baseline_state

_changed_clone_gate_from_report = cli_changed_scope._changed_clone_gate_from_report
_git_diff_changed_paths = cli_changed_scope._git_diff_changed_paths
_validate_changed_scope_args = cli_changed_scope._validate_changed_scope_args

_is_debug_enabled = cli_console._is_debug_enabled
_make_plain_console = cli_console._make_plain_console
_make_rich_console = cli_console.make_console
_parse_metric_reason_entry = cli_console._parse_metric_reason_entry
_print_banner_impl = cli_console.print_banner
_print_gating_failure_block_impl = cli_console._print_gating_failure_block
_print_verbose_clone_hashes = cli_console._print_verbose_clone_hashes
_rich_progress_symbols = cli_console._rich_progress_symbols

print_pipeline_done_if_needed = cli_execution.print_pipeline_done_if_needed
run_analysis_stages = cli_execution.run_analysis_stages

_build_diff_context = cli_post_run.build_diff_context
maybe_print_changed_scope_snapshot = cli_post_run.maybe_print_changed_scope_snapshot
print_metrics_if_available = cli_post_run.print_metrics_if_available
resolve_changed_clone_gate = cli_post_run.resolve_changed_clone_gate
warn_new_clones_without_fail = cli_post_run.warn_new_clones_without_fail
maybe_print_vscode_extension_tip = cli_tips.maybe_print_vscode_extension_tip
maybe_print_dead_code_reachability_migration_note = (
    cli_tips.maybe_print_dead_code_reachability_migration_note
)
maybe_print_cohesion_lcom4_migration_note = (
    cli_tips.maybe_print_cohesion_lcom4_migration_note
)
maybe_print_gitignore_codeclone_cache_tip = (
    cli_tips.maybe_print_gitignore_codeclone_cache_tip
)

_report_path_origins = cli_reports_output._report_path_origins
_resolve_output_paths = cli_reports_output._resolve_output_paths
_validate_report_ui_flags = cli_reports_output._validate_report_ui_flags
_write_report_outputs = cli_reports_output._write_report_outputs

_configure_metrics_mode = cli_runtime._configure_metrics_mode
_print_failed_files = cli_runtime._print_failed_files
_resolve_cache_path_impl = cli_runtime._resolve_cache_path
_resolve_cache_status = cli_runtime._resolve_cache_status
_validate_numeric_args = cli_runtime._validate_numeric_args
gating_mode_enabled = cli_runtime.gating_mode_enabled
prepare_metrics_mode_and_ui = cli_runtime.prepare_metrics_mode_and_ui
resolve_report_cache_path = cli_runtime.resolve_report_cache_path

_configure_runtime_console_impl = cli_startup.configure_runtime_console
_configure_runtime_flags = cli_startup.configure_runtime_flags
_load_pyproject_config_or_exit = cli_startup.load_pyproject_config_or_exit
_resolve_baseline_inputs = cli_startup.resolve_baseline_inputs
_resolve_existing_root_path = cli_startup.resolve_existing_root_path
_validate_numeric_args_or_exit = cli_startup.validate_numeric_args_or_exit

_print_changed_scope = cli_summary._print_changed_scope
_print_metrics = cli_summary._print_metrics
_print_summary = cli_summary._print_summary
build_metrics_snapshot = cli_summary.build_metrics_snapshot
build_summary_counts = cli_summary.build_summary_counts


def _set_console(value: object) -> object:
    cli_state.set_console(value)
    return value


def _console() -> StatusConsole:
    return require_status_console(_set_console(console))


def _make_console(*, no_color: bool) -> object:
    return _make_rich_console(no_color=no_color, width=ui.CLI_LAYOUT_MAX_WIDTH)


console: object = _make_plain_console()
_set_console(console)
LEGACY_CACHE_PATH = cli_state.LEGACY_CACHE_PATH


def _controller_query_mode(args: object) -> bool:
    return cli_controller_queries.controller_query_mode(args)


def _validate_controller_query_flags(
    *,
    args: object,
    report_outputs_requested: bool = False,
    strictness_explicit: bool = False,
) -> None:
    cli_controller_queries.validate_controller_query_flags(
        args=args,
        printer=_console(),
        report_outputs_requested=report_outputs_requested,
        strictness_explicit=strictness_explicit,
    )


def _run_controller_query(
    *,
    args: CLIArgsLike,
    report_document: dict[str, object] | None,
    root_path: Path,
    analysis_result: AnalysisResult,
    diff_context: cli_post_run.DiffContext,
    baseline_state: cli_baseline_state.CloneBaselineState,
) -> int | None:
    return cli_controller_queries.run_post_analysis_controller_query(
        args=args,
        report_document=report_document,
        root_path=root_path,
        analysis_result=analysis_result,
        diff_context=diff_context,
        baseline_state=baseline_state,
        console_factory=_console,
    )


def _controller_query_console(args: CLIArgsLike) -> StatusConsole:
    """Shared console for pre-analysis controller query screens."""
    return require_status_console(
        cli_console.make_query_console(no_color=args.no_color)
    )


def _run_pre_analysis_controller_query(
    *,
    args: CLIArgsLike,
    root_path: Path,
) -> int | None:
    return cli_controller_queries.run_pre_analysis_controller_query(
        args=args,
        root_path=root_path,
        query_console_factory=_controller_query_console,
    )


def print_banner(*, root: Path | None = None) -> None:
    _set_console(console)
    _print_banner_impl(console=_console(), root=root)


def _print_gating_failure_block(
    *,
    code: str,
    entries: tuple[tuple[str, object], ...] | list[tuple[str, object]],
    args: CLIArgsLike,
) -> None:
    _print_gating_failure_block_impl(
        console=_console(),
        code=code,
        entries=entries,
        args=args,
    )


def _configure_runtime_console(args: CLIArgsLike) -> None:
    global console
    console = _configure_runtime_console_impl(
        args=args,
        make_plain_console=_make_plain_console,
        make_console=_make_console,
        set_console=lambda value: cli_state.set_console(value),
    )


def _resolve_cache_path(
    *,
    root_path: Path,
    args: CLIArgsLike,
    from_args: bool,
) -> Path:
    cli_state.LEGACY_CACHE_PATH = LEGACY_CACHE_PATH
    _set_console(console)
    return _resolve_cache_path_impl(
        root_path=root_path,
        args=args,
        from_args=from_args,
    )


def _cache_update_segment_projection(cache: Cache, analysis: AnalysisResult) -> None:
    if not hasattr(cache, "segment_report_projection"):
        return
    new_projection = build_segment_report_projection(
        digest=analysis.segment_groups_raw_digest,
        suppressed=analysis.low_value_segment_groups,
        groups=analysis.segment_groups,
    )
    if new_projection != cache.segment_report_projection:
        cache.segment_report_projection = new_projection
        cache._dirty = True


def _run_analysis_stages(
    *,
    args: CLIArgsLike,
    boot: BootstrapResult,
    cache: Cache,
    collect_block_group_facts: bool = True,
) -> tuple[DiscoveryResult, PipelineProcessingResult, AnalysisResult]:
    _set_console(console)
    return run_analysis_stages(
        args=args,
        boot=boot,
        cache=cache,
        discover_fn=discover,
        process_fn=process,
        analyze_fn=functools.partial(
            analyze,
            collect_block_group_facts=collect_block_group_facts,
        ),
        print_failed_files_fn=_print_failed_files,
        cache_update_segment_projection_fn=_cache_update_segment_projection,
        rich_progress_symbols_fn=_rich_progress_symbols,
    )


def _enforce_gating(
    *,
    args: object,
    analysis: AnalysisResult,
    processing: PipelineProcessingResult,
    source_read_contract_failure: bool,
    baseline_failure_code: ExitCode | None,
    metrics_baseline_failure_code: ExitCode | None,
    new_func: set[str],
    new_block: set[str],
    gate_result: GatingResult,
    html_report_path: str | None,
) -> None:
    _set_console(console)
    cli_execution.enforce_gating(
        args=args,
        analysis=analysis,
        processing=processing,
        source_read_contract_failure=source_read_contract_failure,
        baseline_failure_code=baseline_failure_code,
        metrics_baseline_failure_code=metrics_baseline_failure_code,
        new_func=new_func,
        new_block=new_block,
        gate_result=gate_result,
        html_report_path=html_report_path,
        parse_metric_reason_entry_fn=_parse_metric_reason_entry,
        print_gating_failure_block_fn=_print_gating_failure_block,
        print_verbose_clone_hashes_fn=_print_verbose_clone_hashes,
    )


def _main_impl() -> None:
    run_started_at = time.monotonic()
    analysis_started_at_utc = cli_meta_mod._current_report_timestamp_utc()
    ap = build_parser(__version__)

    raw_argv = tuple(sys.argv[1:])
    report_path_origins = _report_path_origins(raw_argv)
    report_generated_at_utc = cli_meta_mod._current_report_timestamp_utc()
    args = ap.parse_args()
    # Ask argparse which options were supplied, after it accepted them: token
    # matching misses the prefix abbreviations argparse itself expands.
    explicit_cli_dests = collect_explicit_cli_dests(ap, argv=raw_argv)
    strictness_explicit = "strictness" in explicit_cli_dests
    cache_path_from_args = "cache_path" in explicit_cli_dests
    baseline_path_from_args = "baseline" in explicit_cli_dests
    args._full_metrics_explicit = (
        "skip_metrics" in explicit_cli_dests and not bool_attr(args, "skip_metrics")
    )

    root_path = _resolve_existing_root_path(args=args, printer=_console())
    # Freeze the env-resolved observability decision for this CLI process (default
    # OFF) before config/baseline/cache work so the whole cli.analyze operation is
    # measured; span()/operation() are inert when disabled.
    start_observability(resolve_observability_config(), root=root_path)
    with operation(name="cli.analyze", surface="cli"):
        with span(name="config.resolve") as config_span:
            try:
                pyproject_config = _load_pyproject_config_or_exit(
                    root_path=root_path,
                    load_pyproject_config_fn=load_pyproject_config,
                    printer=_console(),
                )
                apply_pyproject_config_overrides(
                    args=args,
                    config_values=pyproject_config,
                    explicit_cli_dests=explicit_cli_dests,
                    root_path=root_path,
                )
            except SystemExit:
                config_span.add_counter("config_validation_failures")
                raise
            source_roots = getattr(args, "source_roots", ())
            configured_root_count = (
                len(source_roots) if isinstance(source_roots, tuple) else 0
            )
            config_span.set_counter("config_configured_roots", configured_root_count)
            config_span.set_counter(
                "config_autodetect_used",
                int(pyproject_config.get("source_roots") is None),
            )
        _validate_controller_query_flags(
            args=args,
            strictness_explicit=strictness_explicit,
        )
        _configure_runtime_flags(args)
        _configure_runtime_console(args)
        pre_analysis_query_exit = _run_pre_analysis_controller_query(
            args=args,
            root_path=root_path,
        )
        if pre_analysis_query_exit is not None:
            sys.exit(pre_analysis_query_exit)
        git_diff_ref = _validate_changed_scope_args(args=args)
        changed_paths = (
            _git_diff_changed_paths(root_path=root_path, git_diff_ref=git_diff_ref)
            if git_diff_ref is not None
            else ()
        )
        _validate_numeric_args_or_exit(
            args=args,
            validate_numeric_args_fn=_validate_numeric_args,
            printer=_console(),
        )
        with span(name="pipeline.baseline"):
            baseline_inputs = _resolve_baseline_inputs(
                args=args,
                root_path=root_path,
                baseline_path_from_args=baseline_path_from_args,
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
        _validate_controller_query_flags(
            args=args,
            report_outputs_requested=bool(
                output_paths.html
                or output_paths.json
                or output_paths.md
                or output_paths.sarif
                or output_paths.text
                or bool_attr(args, "open_html_report")
                or bool_attr(args, "timestamped_report_paths")
            ),
            strictness_explicit=strictness_explicit,
        )
        cache_path = _resolve_cache_path(
            root_path=root_path,
            args=args,
            from_args=cache_path_from_args,
        )

        with span(name="pipeline.cache_load"):
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
            _console().print(ui.fmt_cli_runtime_warning(cache.load_warning))

        with span(name="pipeline.bootstrap"):
            boot = bootstrap(
                args=args,
                root=root_path,
                output_paths=output_paths,
                cache_path=cache_path,
            )
        # One owner for "will a report body exist": the same answer gates the
        # block-group-facts build inside analyze and the body build below, so
        # the facts can never be paid for and thrown away, nor skipped while a
        # body still wants them.
        include_report_document = bool(changed_paths) or _controller_query_mode(args)
        needs_report_body = report_document_required(
            boot,
            include_report_document=include_report_document,
        ) or bool(getattr(args, "changed_only", False))
        discovery_result, processing_result, analysis_result = _run_analysis_stages(
            args=args,
            boot=boot,
            cache=cache,
            collect_block_group_facts=needs_report_body,
        )

        source_read_contract_failure = (
            bool(processing_result.source_read_failures)
            and gating_mode_enabled(args)
            and not args.update_baseline
        )
        baseline_required_lanes = gate_required_lanes(
            args=args,
            enabled_lanes=analysis_result.observation_bundle.contract.enabled_lanes,
        )
        # Read through the one computer, not recounted here and not taken
        # from ``project_metrics.health``: the health lane does not run
        # under ``--skip-metrics``, and both the publisher's empty-scope rule
        # and the gate refusals must hold for those runs too. The rule itself
        # lives in the dependency-free contract ring precisely so this
        # surface can ask without reaching into the model store.
        analysis_population = observed_population(
            files_found=discovery_result.files_found,
            files_analyzed_or_cached=analysis_result.files_analyzed_or_cached,
        )
        baseline_state = _resolve_clone_baseline_state(
            args=args,
            baseline_path=baseline_inputs.baseline_path,
            baseline_exists=baseline_inputs.baseline_exists,
            analysis=analysis_result,
            required_lanes=baseline_required_lanes,
            files_skipped=processing_result.files_skipped,
            analysis_population=analysis_population,
        )
        metrics_baseline_state = _resolve_metrics_baseline_state(
            args=args,
            metrics_baseline_path=baseline_inputs.metrics_baseline_path,
            metrics_baseline_exists=baseline_inputs.metrics_baseline_exists,
            clone_baseline_state=baseline_state,
            required_lanes=baseline_required_lanes,
        )
        baseline_container = baseline_state.baseline.container
        baseline_trust = resolve_report_baseline_trust(
            baseline_container,
            baseline_scope_id=getattr(args, "baseline_scope_id", None),
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
            analysis_started_at_utc=analysis_started_at_utc,
            report_generated_at_utc=report_generated_at_utc,
        )

        diff_context = _build_diff_context(
            analysis=analysis_result,
            baseline_path=baseline_inputs.baseline_path,
            baseline_state=baseline_state,
            metrics_baseline_state=metrics_baseline_state,
            baseline_trust=baseline_trust,
        )
        summary_counts = build_summary_counts(
            discovery_result=discovery_result,
            processing_result=processing_result,
        )
        if not _controller_query_mode(args):
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
                suppressed_clone_groups=len(
                    getattr(analysis_result, "suppressed_clone_groups", ())
                ),
                low_value_segment_groups=(analysis_result.low_value_segment_groups),
                new_clones_count=(
                    diff_context.new_clones_count
                    if diff_context.clone_novelty_available
                    else None
                ),
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

        with span(name="pipeline.report"):
            # Build only when something consumes it. `needs_report_body` is
            # computed once before the analysis stages: `report_document_required`
            # owns the artifact and controller cases; the changed-clone gate is
            # the third consumer and keys off the flag rather than the changed
            # path set, so it has to be asked separately.
            report_body = (
                build_report_body_for_analysis(
                    discovery=discovery_result,
                    processing=processing_result,
                    analysis=analysis_result,
                    report_meta=report_meta,
                    new_func=diff_context.new_func,
                    new_block=diff_context.new_block,
                    metrics_diff=diff_context.metrics_diff,
                    coverage_adoption_diff_available=(
                        diff_context.coverage_adoption_diff_available
                    ),
                    api_surface_diff_available=(
                        diff_context.api_surface_diff_available
                    ),
                    baseline_trust=baseline_trust,
                )
                if needs_report_body
                else None
            )
            changed_clone_gate = resolve_changed_clone_gate(
                args=args,
                report_document=report_body,
                changed_paths=changed_paths,
                changed_clone_gate_from_report_fn=_changed_clone_gate_from_report,
            )
            gate_new_func = (
                set(changed_clone_gate.new_func)
                if changed_clone_gate
                else diff_context.new_func
            )
            gate_new_block = (
                set(changed_clone_gate.new_block)
                if changed_clone_gate
                else diff_context.new_block
            )
            patch_gate_config = None
            if bool(getattr(args, "patch_verify", False)):
                from .patch_verify import patch_gate_config as build_patch_gate_config
                from .patch_verify import validate_strictness

                patch_gate_config = build_patch_gate_config(
                    args=args,
                    strictness=validate_strictness(
                        str(getattr(args, "strictness", "ci") or "ci")
                    ),
                )
            gate_config, gate_result = gate_with_config(
                boot=boot,
                analysis=analysis_result,
                new_func=gate_new_func,
                new_block=gate_new_block,
                metrics_diff=diff_context.metrics_diff,
                clone_threshold_total=(
                    changed_clone_gate.total_clone_groups
                    if changed_clone_gate
                    else None
                ),
                baseline_trust=baseline_trust,
                gate_config=patch_gate_config,
                files_skipped=processing_result.files_skipped,
                # The same fact the baseline resolver consumed above; without
                # it a ``--skip-metrics`` run answers every gate over a
                # population nobody measured (`B8`, `G3`).
                analysis_population=analysis_population,
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
                coverage_adoption_diff_available=(
                    diff_context.coverage_adoption_diff_available
                ),
                api_surface_diff_available=diff_context.api_surface_diff_available,
                include_report_document=include_report_document,
                report_body=report_body,
                baseline_container=baseline_container,
                baseline_trust=baseline_trust,
                baseline_scope_id=getattr(args, "baseline_scope_id", None),
                gate_config=gate_config,
                gate_result=gate_result,
            )
    _emit_cli_analysis_completed_if_enabled(
        args=args,
        root_path=root_path,
        report_document=report_artifacts.report_document,
        new_func_count=(
            len(diff_context.new_func) if diff_context.clone_novelty_available else None
        ),
        new_block_count=(
            len(diff_context.new_block)
            if diff_context.clone_novelty_available
            else None
        ),
    )
    controller_exit_code = _run_controller_query(
        args=args,
        report_document=report_artifacts.report_document,
        root_path=root_path,
        analysis_result=analysis_result,
        diff_context=diff_context,
        baseline_state=baseline_state,
    )
    if controller_exit_code is not None:
        sys.exit(controller_exit_code)
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
        analysis=analysis_result,
        processing=processing_result,
        source_read_contract_failure=source_read_contract_failure,
        baseline_failure_code=baseline_state.failure_code,
        metrics_baseline_failure_code=metrics_baseline_state.failure_code,
        new_func=gate_new_func,
        new_block=gate_new_block,
        gate_result=gate_result,
        html_report_path=html_report_path,
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
    maybe_print_dead_code_reachability_migration_note(
        args=args,
        console=_console(),
        codeclone_version=__version__,
        cache_path=cache_path,
        baseline_generator_version=baseline_state.baseline.generator_version,
        baseline_trusted_for_diff=baseline_state.trusted_for_diff,
    )
    maybe_print_cohesion_lcom4_migration_note(
        args=args,
        console=_console(),
        codeclone_version=__version__,
        cache_path=cache_path,
        baseline_generator_version=baseline_state.baseline.generator_version,
        baseline_trusted_for_diff=baseline_state.trusted_for_diff,
    )
    maybe_print_vscode_extension_tip(
        args=args,
        console=_console(),
        codeclone_version=__version__,
        cache_path=cache_path,
    )
    maybe_print_gitignore_codeclone_cache_tip(
        args=args,
        console=_console(),
        root_path=root_path,
    )
    print_pipeline_done_if_needed(args=args, run_started_at=run_started_at)


def _emit_cli_analysis_completed_if_enabled(
    *,
    args: _AuditEnabledArgs,
    root_path: Path,
    report_document: object,
    #: ``None`` when no clone lane was compared, so the recorded event does not
    #: claim a new-clone count the run never measured.
    new_func_count: int | None,
    new_block_count: int | None,
) -> None:
    if not bool(getattr(args, "audit_enabled", False)):
        return
    if not _is_report_document(report_document):
        return
    # Read outside the guard below on purpose: that guard exists so a failure
    # to *write* the row cannot take the analysis down with it, and catching
    # the identity refusal in it would restore the silent skip this replaced.
    digest = report_run_identity(report_document)
    try:
        from ...audit.analysis_completed import (
            ANALYSIS_SOURCE_CLI,
            emit_analysis_completed_from_report,
        )

        emit_analysis_completed_from_report(
            root_path=root_path,
            report_document=report_document,
            report_digest=digest,
            run_id=digest,
            source=ANALYSIS_SOURCE_CLI,
            new_func_count=new_func_count,
            new_block_count=new_block_count,
            agent_start_epoch=_CLI_SESSION_START_EPOCH,
        )
    except Exception:
        return None


def _is_report_document(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict)


def main() -> None:
    dispatch_subcommand(sys.argv)
    try:
        _main_impl()
    except SystemExit:
        raise
    except DiagnosedUserError as exc:
        # Ahead of the internal envelope and reading the CLASS, not a list of
        # exceptions: the diagnosed families are marked at their own
        # definitions, so a new one is routed correctly the day it is written
        # rather than the day somebody notices it in a bug report.
        _console().print(ui.fmt_diagnosed_user_error(exc))
        raise SystemExit(ExitCode.CONTRACT_ERROR) from exc
    except Exception as exc:
        _console().print(
            ui.fmt_internal_error(
                exc,
                issues_url=ISSUES_URL,
                debug=_is_debug_enabled(),
            )
        )
        raise SystemExit(ExitCode.INTERNAL_ERROR) from exc
