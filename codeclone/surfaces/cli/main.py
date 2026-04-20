# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os
import sys
import time
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, NoReturn, Protocol, cast

from ... import __version__
from ... import ui_messages as ui
from ...baseline import Baseline
from ...cache import Cache, CacheStatus, build_segment_report_projection
from ...config import (
    ConfigValidationError,
    apply_pyproject_config_overrides,
    build_parser,
    collect_explicit_cli_dests,
    load_pyproject_config,
)
from ...contracts import (
    DEFAULT_REPORT_DESIGN_COHESION_THRESHOLD,
    DEFAULT_REPORT_DESIGN_COMPLEXITY_THRESHOLD,
    DEFAULT_REPORT_DESIGN_COUPLING_THRESHOLD,
    ISSUES_URL,
    ExitCode,
)
from ...contracts.errors import CacheError
from ...core import (
    MAX_FILE_SIZE,
    AnalysisResult,
    BootstrapResult,
    DiscoveryResult,
    analyze,
    bootstrap,
    discover,
    gate,
    process,
    process_file,
    report,
)
from ...core._types import FileProcessResult as ProcessingResult
from ...core._types import ProcessingResult as PipelineProcessingResult
from . import report_meta as cli_meta_mod
from . import state as cli_state
from .baseline_state import (
    CloneBaselineState as _CloneBaselineState,
)
from .baseline_state import (
    MetricsBaselineSectionProbe as _MetricsBaselineSectionProbe,
)
from .baseline_state import (
    MetricsBaselineState as _MetricsBaselineState,
)
from .baseline_state import (
    probe_metrics_baseline_section as _probe_metrics_baseline_section_impl,
)
from .baseline_state import (
    resolve_clone_baseline_state as _resolve_clone_baseline_state_impl,
)
from .baseline_state import (
    resolve_metrics_baseline_state as _resolve_metrics_baseline_state_impl,
)
from .changed_scope import (
    ChangedCloneGate,
)
from .changed_scope import (
    _changed_clone_gate_from_report as _changed_clone_gate_from_report_impl,
)
from .changed_scope import (
    _git_diff_changed_paths as _git_diff_changed_paths_impl,
)
from .changed_scope import (
    _normalize_changed_paths as _normalize_changed_paths_impl,
)
from .changed_scope import (
    _validate_changed_scope_args as _validate_changed_scope_args_impl,
)
from .console import (
    PlainConsole,
    _is_debug_enabled,
    _parse_metric_reason_entry,
    _print_verbose_clone_hashes,
    _rich_progress_symbols,
    build_html_report,
)
from .console import (
    _print_gating_failure_block as _print_gating_failure_block_impl,
)
from .console import (
    make_console as _make_rich_console,
)
from .console import (
    make_plain_console as _make_plain_console_impl,
)
from .console import (
    print_banner as _print_banner_impl,
)
from .reports_output import (
    _report_path_origins as _report_path_origins_impl,
)
from .reports_output import (
    _resolve_output_paths as _resolve_output_paths_impl,
)
from .reports_output import (
    _timestamped_report_path as _timestamped_report_path_impl,
)
from .reports_output import (
    _validate_report_ui_flags as _validate_report_ui_flags_impl,
)
from .reports_output import (
    _write_report_outputs as _write_report_outputs_impl,
)
from .runtime import (
    _configure_metrics_mode as _configure_metrics_mode_impl,
)
from .runtime import (
    _metrics_computed as _metrics_computed_impl,
)
from .runtime import (
    _print_failed_files as _print_failed_files_impl,
)
from .runtime import (
    _resolve_cache_path as _resolve_cache_path_impl,
)
from .runtime import (
    _resolve_cache_status as _resolve_cache_status_impl,
)
from .runtime import (
    _validate_numeric_args as _validate_numeric_args_impl,
)
from .summary import (
    ChangedScopeSnapshot,
    _print_changed_scope,
    _print_metrics,
    _print_summary,
    build_metrics_snapshot,
    build_summary_counts,
)
from .types import OutputPaths, ReportPathOrigin

__all__ = [
    "LEGACY_CACHE_PATH",
    "MAX_FILE_SIZE",
    "Baseline",
    "Cache",
    "ChangedCloneGate",
    "ConfigValidationError",
    "ExitCode",
    "ProcessingResult",
    "_changed_clone_gate_from_report",
    "_configure_metrics_mode",
    "_enforce_gating",
    "_git_diff_changed_paths",
    "_main_impl",
    "_make_console",
    "_make_plain_console",
    "_make_rich_console",
    "_metrics_computed",
    "_normalize_changed_paths",
    "_parse_metric_reason_entry",
    "_print_changed_scope",
    "_print_failed_files",
    "_print_gating_failure_block",
    "_print_metrics",
    "_print_summary",
    "_print_verbose_clone_hashes",
    "_probe_metrics_baseline_section",
    "_report_path_origins",
    "_resolve_cache_path",
    "_resolve_cache_status",
    "_resolve_clone_baseline_state",
    "_resolve_metrics_baseline_state",
    "_resolve_output_paths",
    "_run_analysis_stages",
    "_timestamped_report_path",
    "_validate_changed_scope_args",
    "_validate_numeric_args",
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
    "process_file",
    "report",
]


class _PrinterLike(Protocol):
    def print(self, *objects: object, **kwargs: object) -> None: ...

    def status(self, *objects: object, **kwargs: object) -> object: ...


@dataclass(frozen=True, slots=True)
class _ResolvedBaselineInputs:
    baseline_path: Path
    baseline_exists: bool
    metrics_baseline_path: Path
    metrics_baseline_exists: bool
    shared_baseline_payload: dict[str, object] | None


@dataclass(frozen=True, slots=True)
class _DiffContext:
    new_func: set[str]
    new_block: set[str]
    new_clones_count: int
    metrics_diff: object | None
    coverage_adoption_diff_available: bool
    api_surface_diff_available: bool


def _set_console(value: object) -> object:
    cli_state.set_console(value)
    return value


def _console() -> _PrinterLike:
    return cast("_PrinterLike", _set_console(console))


def _make_console(*, no_color: bool) -> object:
    return _make_rich_console(
        no_color=no_color,
        width=ui.CLI_LAYOUT_MAX_WIDTH,
    )


def _make_plain_console() -> PlainConsole:
    return _make_plain_console_impl()


console: object = _make_plain_console()
_set_console(console)
LEGACY_CACHE_PATH = cli_state.LEGACY_CACHE_PATH


def print_banner(*, root: Path | None = None) -> None:
    _set_console(console)
    _print_banner_impl(root=root)


def _report_path_origins(argv: Sequence[str]) -> dict[str, ReportPathOrigin | None]:
    return _report_path_origins_impl(argv)


def _timestamped_report_path(path: Path, *, report_generated_at_utc: str) -> Path:
    return _timestamped_report_path_impl(
        path,
        report_generated_at_utc=report_generated_at_utc,
    )


def _validate_changed_scope_args(*, args: object) -> str | None:
    _set_console(console)
    return _validate_changed_scope_args_impl(args=args)


def _normalize_changed_paths(
    *,
    root_path: Path,
    paths: Sequence[str],
) -> tuple[str, ...]:
    _set_console(console)
    return _normalize_changed_paths_impl(root_path=root_path, paths=paths)


def _git_diff_changed_paths(*, root_path: Path, git_diff_ref: str) -> tuple[str, ...]:
    _set_console(console)
    return _git_diff_changed_paths_impl(root_path=root_path, git_diff_ref=git_diff_ref)


def _changed_clone_gate_from_report(
    report_document: Mapping[str, object],
    *,
    changed_paths: Sequence[str],
) -> ChangedCloneGate:
    return _changed_clone_gate_from_report_impl(
        report_document,
        changed_paths=changed_paths,
    )


def _resolve_output_paths(
    args: object,
    *,
    report_path_origins: Mapping[str, ReportPathOrigin | None],
    report_generated_at_utc: str,
) -> OutputPaths:
    _set_console(console)
    return _resolve_output_paths_impl(
        args,
        report_path_origins=report_path_origins,
        report_generated_at_utc=report_generated_at_utc,
    )


def _validate_report_ui_flags(*, args: object, output_paths: OutputPaths) -> None:
    _set_console(console)
    _validate_report_ui_flags_impl(args=args, output_paths=output_paths)


def _resolve_cache_path(*, root_path: Path, args: object, from_args: bool) -> Path:
    cli_state.LEGACY_CACHE_PATH = LEGACY_CACHE_PATH
    _set_console(console)
    return _resolve_cache_path_impl(
        root_path=root_path,
        args=args,
        from_args=from_args,
    )


def _validate_numeric_args(args: object) -> bool:
    return _validate_numeric_args_impl(args)


def _configure_metrics_mode(*, args: object, metrics_baseline_exists: bool) -> None:
    _set_console(console)
    _configure_metrics_mode_impl(
        args=args,
        metrics_baseline_exists=metrics_baseline_exists,
    )


def _print_failed_files(failed_files: Sequence[str]) -> None:
    _set_console(console)
    _print_failed_files_impl(tuple(failed_files))


def _metrics_computed(args: object) -> tuple[str, ...]:
    return _metrics_computed_impl(args)


def _probe_metrics_baseline_section(path: Path) -> _MetricsBaselineSectionProbe:
    return _probe_metrics_baseline_section_impl(path)


def _resolve_clone_baseline_state(
    *,
    args: object,
    baseline_path: Path,
    baseline_exists: bool,
    analysis: AnalysisResult,
    shared_baseline_payload: dict[str, object] | None = None,
) -> _CloneBaselineState:
    return _resolve_clone_baseline_state_impl(
        args=cast("Any", args),
        baseline_path=baseline_path,
        baseline_exists=baseline_exists,
        func_groups=analysis.func_groups,
        block_groups=analysis.block_groups,
        codeclone_version=__version__,
        console=_console(),
        shared_baseline_payload=shared_baseline_payload,
    )


def _resolve_metrics_baseline_state(
    *,
    args: object,
    metrics_baseline_path: Path,
    metrics_baseline_exists: bool,
    baseline_updated_path: Path | None,
    analysis: AnalysisResult,
    shared_baseline_payload: dict[str, object] | None = None,
) -> _MetricsBaselineState:
    return _resolve_metrics_baseline_state_impl(
        args=cast("Any", args),
        metrics_baseline_path=metrics_baseline_path,
        metrics_baseline_exists=metrics_baseline_exists,
        baseline_updated_path=baseline_updated_path,
        project_metrics=analysis.project_metrics,
        console=_console(),
        shared_baseline_payload=shared_baseline_payload,
    )


def _resolve_cache_status(cache: Cache) -> tuple[CacheStatus, str | None]:
    return _resolve_cache_status_impl(cache)


def _print_gating_failure_block(
    *,
    code: str,
    entries: Sequence[tuple[str, object]],
    args: object,
) -> None:
    _set_console(console)
    _print_gating_failure_block_impl(
        code=code,
        entries=entries,
        args=args,
    )


def _write_report_outputs(
    *,
    args: object,
    output_paths: OutputPaths,
    report_artifacts: object,
    open_html_report: bool = False,
) -> str | None:
    _set_console(console)
    return _write_report_outputs_impl(
        args=args,
        output_paths=output_paths,
        report_artifacts=report_artifacts,
        open_html_report=open_html_report,
    )


def _resolve_runtime_path_arg(
    *,
    root_path: Path,
    raw_path: str,
    from_cli: bool,
) -> Path:
    candidate_path = Path(raw_path).expanduser()
    if from_cli or candidate_path.is_absolute():
        return candidate_path.resolve()
    return (root_path / candidate_path).resolve()


def _exit_contract_error(
    message: str,
    *,
    cause: BaseException | None = None,
) -> NoReturn:
    _console().print(ui.fmt_contract_error(message))
    if cause is None:
        raise SystemExit(ExitCode.CONTRACT_ERROR)
    raise SystemExit(ExitCode.CONTRACT_ERROR) from cause


def _resolve_existing_root_path(args: object) -> Path:
    args_obj = cast("Any", args)
    try:
        root_path = Path(args_obj.root).resolve()
    except OSError as exc:
        _exit_contract_error(ui.ERR_INVALID_ROOT_PATH.format(error=exc), cause=exc)
    if not root_path.exists():
        _exit_contract_error(ui.ERR_ROOT_NOT_FOUND.format(path=root_path))
    return root_path


def _load_pyproject_config_or_exit(root_path: Path) -> dict[str, object]:
    try:
        return load_pyproject_config(root_path)
    except ConfigValidationError as exc:
        _exit_contract_error(str(exc), cause=exc)


def _configure_runtime_flags(args: object) -> None:
    args_obj = cast("Any", args)
    if args_obj.debug:
        os.environ["CODECLONE_DEBUG"] = "1"
    if args_obj.ci:
        args_obj.fail_on_new = True
        args_obj.no_color = True
        args_obj.quiet = True


def _configure_runtime_console(args: object) -> None:
    global console

    args_obj = cast("Any", args)
    console = (
        _make_plain_console()
        if args_obj.quiet
        else _make_console(no_color=args_obj.no_color)
    )
    _set_console(console)


def _validate_numeric_args_or_exit(args: object) -> None:
    if _validate_numeric_args(args):
        return
    _exit_contract_error(
        "Size limits must be non-negative integers (MB), "
        "threshold flags must be >= 0 or -1, and coverage thresholds "
        "must be between 0 and 100."
    )


def _resolve_baseline_inputs(
    *,
    ap: object,
    args: object,
    root_path: Path,
    baseline_path_from_args: bool,
    metrics_path_from_args: bool,
) -> _ResolvedBaselineInputs:
    args_obj = cast("Any", args)
    ap_obj = cast("Any", ap)

    baseline_arg_path = Path(args_obj.baseline).expanduser()
    try:
        baseline_path = _resolve_runtime_path_arg(
            root_path=root_path,
            raw_path=args_obj.baseline,
            from_cli=baseline_path_from_args,
        )
        baseline_exists = baseline_path.exists()
    except OSError as exc:
        _exit_contract_error(
            ui.fmt_invalid_baseline_path(path=baseline_arg_path, error=exc),
            cause=exc,
        )

    shared_baseline_payload: dict[str, object] | None = None
    default_metrics_baseline = ap_obj.get_default("metrics_baseline")
    metrics_path_overridden = metrics_path_from_args or (
        args_obj.metrics_baseline != default_metrics_baseline
    )
    metrics_baseline_raw_path = (
        args_obj.metrics_baseline if metrics_path_overridden else args_obj.baseline
    )
    metrics_baseline_arg_path = Path(metrics_baseline_raw_path).expanduser()
    try:
        metrics_baseline_path = _resolve_runtime_path_arg(
            root_path=root_path,
            raw_path=metrics_baseline_raw_path,
            from_cli=metrics_path_from_args,
        )
        if metrics_baseline_path == baseline_path:
            probe = _probe_metrics_baseline_section(metrics_baseline_path)
            metrics_baseline_exists = probe.has_metrics_section
            shared_baseline_payload = probe.payload
        else:
            metrics_baseline_exists = metrics_baseline_path.exists()
    except OSError as exc:
        _exit_contract_error(
            ui.fmt_invalid_baseline_path(
                path=metrics_baseline_arg_path,
                error=exc,
            ),
            cause=exc,
        )

    return _ResolvedBaselineInputs(
        baseline_path=baseline_path,
        baseline_exists=baseline_exists,
        metrics_baseline_path=metrics_baseline_path,
        metrics_baseline_exists=metrics_baseline_exists,
        shared_baseline_payload=shared_baseline_payload,
    )


def _prepare_metrics_mode_and_ui(
    *,
    args: object,
    root_path: Path,
    baseline_path: Path,
    baseline_exists: bool,
    metrics_baseline_path: Path,
    metrics_baseline_exists: bool,
) -> None:
    args_obj = cast("Any", args)
    if (
        args_obj.update_baseline
        and not args_obj.skip_metrics
        and not args_obj.update_metrics_baseline
    ):
        args_obj.update_metrics_baseline = True
    _configure_metrics_mode(
        args=args_obj,
        metrics_baseline_exists=metrics_baseline_exists,
    )
    if (
        args_obj.update_metrics_baseline
        and metrics_baseline_path == baseline_path
        and not baseline_exists
        and not args_obj.update_baseline
    ):
        args_obj.update_baseline = True
    if args_obj.quiet:
        args_obj.no_progress = True
        return
    print_banner(root=root_path)


def _resolve_report_cache_path(cache_path: Path) -> Path:
    try:
        return cache_path.resolve()
    except OSError:
        return cache_path


def _gating_mode_enabled(args: object) -> bool:
    args_obj = cast("Any", args)
    return bool(
        args_obj.fail_on_new
        or args_obj.fail_threshold >= 0
        or args_obj.fail_complexity >= 0
        or args_obj.fail_coupling >= 0
        or args_obj.fail_cohesion >= 0
        or args_obj.fail_cycles
        or args_obj.fail_dead_code
        or args_obj.fail_health >= 0
        or args_obj.fail_on_new_metrics
        or args_obj.fail_on_typing_regression
        or args_obj.fail_on_docstring_regression
        or args_obj.fail_on_api_break
        or args_obj.min_typing_coverage >= 0
        or args_obj.min_docstring_coverage >= 0
    )


def _build_diff_context(
    *,
    analysis: AnalysisResult,
    baseline_path: Path,
    baseline_state: _CloneBaselineState,
    metrics_baseline_state: _MetricsBaselineState,
) -> _DiffContext:
    baseline_for_diff = (
        baseline_state.baseline
        if baseline_state.trusted_for_diff
        else Baseline(baseline_path)
    )
    raw_new_func, raw_new_block = baseline_for_diff.diff(
        analysis.func_groups,
        analysis.block_groups,
    )
    metrics_diff = None
    if analysis.project_metrics is not None and metrics_baseline_state.trusted_for_diff:
        metrics_diff = metrics_baseline_state.baseline.diff(analysis.project_metrics)
    return _DiffContext(
        new_func=set(raw_new_func),
        new_block=set(raw_new_block),
        new_clones_count=len(raw_new_func) + len(raw_new_block),
        metrics_diff=metrics_diff,
        coverage_adoption_diff_available=bool(
            metrics_baseline_state.trusted_for_diff
            and getattr(
                metrics_baseline_state.baseline,
                "has_coverage_adoption_snapshot",
                False,
            )
        ),
        api_surface_diff_available=bool(
            metrics_baseline_state.trusted_for_diff
            and getattr(metrics_baseline_state.baseline, "api_surface_snapshot", None)
            is not None
        ),
    )


def _print_metrics_if_available(
    *,
    args: object,
    analysis: AnalysisResult,
    metrics_diff: object | None,
    api_surface_diff_available: bool,
) -> None:
    args_obj = cast("Any", args)
    if analysis.project_metrics is None:
        return
    _print_metrics(
        console=_console(),
        quiet=args_obj.quiet,
        metrics=build_metrics_snapshot(
            analysis_result=analysis,
            metrics_diff=metrics_diff,
            api_surface_diff_available=api_surface_diff_available,
        ),
    )


def _resolve_changed_clone_gate(
    *,
    args: object,
    report_document: Mapping[str, object] | None,
    changed_paths: Collection[str],
) -> ChangedCloneGate | None:
    args_obj = cast("Any", args)
    if not args_obj.changed_only or report_document is None:
        return None
    return _changed_clone_gate_from_report(
        report_document,
        changed_paths=tuple(changed_paths),
    )


def _maybe_print_changed_scope_snapshot(
    *,
    args: object,
    changed_clone_gate: ChangedCloneGate | None,
) -> None:
    args_obj = cast("Any", args)
    if changed_clone_gate is None:
        return
    _print_changed_scope(
        console=_console(),
        quiet=args_obj.quiet,
        changed_scope=ChangedScopeSnapshot(
            paths_count=len(changed_clone_gate.changed_paths),
            findings_total=changed_clone_gate.findings_total,
            findings_new=changed_clone_gate.findings_new,
            findings_known=changed_clone_gate.findings_known,
        ),
    )


def _warn_new_clones_without_fail(
    *,
    args: object,
    notice_new_clones_count: int,
) -> None:
    args_obj = cast("Any", args)
    if args_obj.update_baseline or args_obj.fail_on_new or notice_new_clones_count <= 0:
        return
    _console().print(ui.WARN_NEW_CLONES_WITHOUT_FAIL)


def _print_pipeline_done_if_needed(*, args: object, run_started_at: float) -> None:
    args_obj = cast("Any", args)
    if args_obj.quiet:
        return
    elapsed = time.monotonic() - run_started_at
    _console().print()
    _console().print(ui.fmt_pipeline_done(elapsed))


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
    def _require_rich_console(value: object) -> object:
        if isinstance(value, PlainConsole):
            raise RuntimeError("Rich console is required when progress UI is enabled.")
        return value

    args_obj = cast("Any", args)
    printer = _console()
    use_status = not args_obj.quiet and not args_obj.no_progress

    try:
        if use_status:
            with cast("Any", printer).status(ui.STATUS_DISCOVERING, spinner="dots"):
                discovery_result = discover(boot=boot, cache=cache)
        else:
            discovery_result = discover(boot=boot, cache=cache)
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
        ) = _rich_progress_symbols()

        progress_factory = cast("Any", progress_cls)
        with progress_factory(
            cast("Any", spinner_column_cls)(),
            cast("Any", text_column_cls)("[progress.description]{task.description}"),
            cast("Any", bar_column_cls)(),
            cast("Any", text_column_cls)(
                "[progress.percentage]{task.percentage:>3.0f}%"
            ),
            cast("Any", time_elapsed_column_cls)(),
            console=_require_rich_console(console),
        ) as progress_ui:
            progress_ui_any = cast("Any", progress_ui)
            task_id = progress_ui_any.add_task(
                f"Analyzing {total_files} files...",
                total=total_files,
            )
            processing_result = process(
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
        processing_result = process(
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

    _print_failed_files(processing_result.failed_files)
    if not processing_result.failed_files and processing_result.source_read_failures:
        _print_failed_files(processing_result.source_read_failures)

    if use_status:
        with cast("Any", printer).status(ui.STATUS_GROUPING, spinner="dots"):
            analysis_result = analyze(
                boot=boot,
                discovery=discovery_result,
                processing=processing_result,
            )
            _cache_update_segment_projection(cache, analysis_result)
            try:
                cache.save()
            except CacheError as exc:
                printer.print(ui.fmt_cache_save_failed(exc))
    else:
        analysis_result = analyze(
            boot=boot,
            discovery=discovery_result,
            processing=processing_result,
        )
        _cache_update_segment_projection(cache, analysis_result)
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
    args_obj = cast("Any", args)
    printer = _console()

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

    gate_result = gate(
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
        _print_gating_failure_block(
            code="metrics",
            entries=[_parse_metric_reason_entry(reason) for reason in metric_reasons],
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
        _print_gating_failure_block(
            code="new-clones",
            entries=clone_entries,
            args=args_obj,
        )

        if args_obj.verbose:
            _print_verbose_clone_hashes(
                printer,
                label="Function clone hashes",
                clone_hashes=new_func,
            )
            _print_verbose_clone_hashes(
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
        _print_gating_failure_block(
            code="threshold",
            entries=(
                ("clone_groups_total", int(total_raw)),
                ("clone_groups_limit", int(threshold_raw)),
            ),
            args=args_obj,
        )
        sys.exit(ExitCode.GATING_FAILURE)


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

    root_path = _resolve_existing_root_path(args)
    pyproject_config = _load_pyproject_config_or_exit(root_path)
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
    _validate_numeric_args_or_exit(args)
    baseline_inputs = _resolve_baseline_inputs(
        ap=ap,
        args=args,
        root_path=root_path,
        baseline_path_from_args=baseline_path_from_args,
        metrics_path_from_args=metrics_path_from_args,
    )
    (
        baseline_path,
        baseline_exists,
        metrics_baseline_path,
        metrics_baseline_exists,
    ) = (
        baseline_inputs.baseline_path,
        baseline_inputs.baseline_exists,
        baseline_inputs.metrics_baseline_path,
        baseline_inputs.metrics_baseline_exists,
    )
    shared_baseline_payload = baseline_inputs.shared_baseline_payload

    _prepare_metrics_mode_and_ui(
        args=args,
        root_path=root_path,
        baseline_path=baseline_path,
        baseline_exists=baseline_exists,
        metrics_baseline_path=metrics_baseline_path,
        metrics_baseline_exists=metrics_baseline_exists,
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

    gating_mode = _gating_mode_enabled(args)
    source_read_contract_failure = (
        bool(processing_result.source_read_failures)
        and gating_mode
        and not args.update_baseline
    )
    baseline_state = _resolve_clone_baseline_state(
        args=args,
        baseline_path=baseline_path,
        baseline_exists=baseline_exists,
        analysis=analysis_result,
        shared_baseline_payload=(
            shared_baseline_payload if metrics_baseline_path == baseline_path else None
        ),
    )
    metrics_baseline_state = _resolve_metrics_baseline_state(
        args=args,
        metrics_baseline_path=metrics_baseline_path,
        metrics_baseline_exists=metrics_baseline_exists,
        baseline_updated_path=baseline_state.updated_path,
        analysis=analysis_result,
        shared_baseline_payload=(
            shared_baseline_payload if metrics_baseline_path == baseline_path else None
        ),
    )

    report_cache_path = _resolve_report_cache_path(cache_path)

    cache_status, cache_schema_version = _resolve_cache_status(cache)
    report_meta = cli_meta_mod._build_report_meta(
        codeclone_version=__version__,
        scan_root=root_path,
        baseline_path=baseline_path,
        baseline=baseline_state.baseline,
        baseline_loaded=baseline_state.loaded,
        baseline_status=baseline_state.status.value,
        cache_path=report_cache_path,
        cache_used=cache_status == CacheStatus.OK,
        cache_status=cache_status.value,
        cache_schema_version=cache_schema_version,
        files_skipped_source_io=len(processing_result.source_read_failures),
        metrics_baseline_path=metrics_baseline_path,
        metrics_baseline=metrics_baseline_state.baseline,
        metrics_baseline_loaded=metrics_baseline_state.loaded,
        metrics_baseline_status=metrics_baseline_state.status.value,
        health_score=(
            analysis_result.project_metrics.health.total
            if analysis_result.project_metrics
            else None
        ),
        health_grade=(
            analysis_result.project_metrics.health.grade
            if analysis_result.project_metrics
            else None
        ),
        analysis_mode=("clones_only" if args.skip_metrics else "full"),
        metrics_computed=_metrics_computed(args),
        min_loc=args.min_loc,
        min_stmt=args.min_stmt,
        block_min_loc=args.block_min_loc,
        block_min_stmt=args.block_min_stmt,
        segment_min_loc=args.segment_min_loc,
        segment_min_stmt=args.segment_min_stmt,
        design_complexity_threshold=DEFAULT_REPORT_DESIGN_COMPLEXITY_THRESHOLD,
        design_coupling_threshold=DEFAULT_REPORT_DESIGN_COUPLING_THRESHOLD,
        design_cohesion_threshold=DEFAULT_REPORT_DESIGN_COHESION_THRESHOLD,
        analysis_started_at_utc=analysis_started_at_utc,
        report_generated_at_utc=report_generated_at_utc,
    )

    diff_context = _build_diff_context(
        analysis=analysis_result,
        baseline_path=baseline_path,
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
    _print_metrics_if_available(
        args=args,
        analysis=analysis_result,
        metrics_diff=diff_context.metrics_diff,
        api_surface_diff_available=diff_context.api_surface_diff_available,
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
    changed_clone_gate = _resolve_changed_clone_gate(
        args=args,
        report_document=report_artifacts.report_document,
        changed_paths=changed_paths,
    )
    _maybe_print_changed_scope_snapshot(
        args=args,
        changed_clone_gate=changed_clone_gate,
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
    _warn_new_clones_without_fail(
        args=args,
        notice_new_clones_count=notice_new_clones_count,
    )
    _print_pipeline_done_if_needed(args=args, run_started_at=run_started_at)


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
        sys.exit(ExitCode.INTERNAL_ERROR)


if __name__ == "__main__":
    main()
