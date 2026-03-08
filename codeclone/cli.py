# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
import os
import sys
import time
from argparse import Namespace
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from rich.console import Console
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
from ._cli_config import (
    ConfigValidationError,
    apply_pyproject_config_overrides,
    collect_explicit_cli_dests,
    load_pyproject_config,
)
from ._cli_meta import _build_report_meta
from ._cli_paths import _validate_output_path
from ._cli_summary import MetricsSnapshot, _print_metrics, _print_summary
from .baseline import (
    BASELINE_UNTRUSTED_STATUSES,
    Baseline,
    BaselineStatus,
    coerce_baseline_status,
    current_python_tag,
)
from .cache import Cache, CacheStatus
from .contracts import (
    BASELINE_FINGERPRINT_VERSION,
    BASELINE_SCHEMA_VERSION,
    ISSUES_URL,
    ExitCode,
)
from .errors import BaselineValidationError, CacheError
from .metrics_baseline import (
    METRICS_BASELINE_UNTRUSTED_STATUSES,
    MetricsBaseline,
    MetricsBaselineStatus,
    coerce_metrics_baseline_status,
)
from .models import MetricsDiff
from .pipeline import (
    MAX_FILE_SIZE,
    AnalysisResult,
    BootstrapResult,
    DiscoveryResult,
    FileProcessResult,
    OutputPaths,
    ReportArtifacts,
    analyze,
    bootstrap,
    discover,
    gate,
    process,
    process_file,
    report,
)
from .pipeline import (
    ProcessingResult as PipelineProcessingResult,
)

# Backward-compatible public symbol
ProcessingResult = FileProcessResult
__all__ = ["MAX_FILE_SIZE", "ProcessingResult", "main", "process_file"]

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
    return Console(theme=custom_theme, no_color=no_color, width=ui.CLI_LAYOUT_MAX_WIDTH)


console = _make_console(no_color=False)


def build_html_report(*args: object, **kwargs: object) -> str:
    # Lazy import avoids pulling HTML renderer in non-HTML CLI runs.
    from .html_report import build_html_report as _build_html_report

    html_builder = _build_html_report
    return cast(Callable[..., str], html_builder)(*args, **kwargs)


@dataclass(frozen=True, slots=True)
class _CloneBaselineState:
    baseline: Baseline
    loaded: bool
    status: BaselineStatus
    failure_code: ExitCode | None
    trusted_for_diff: bool
    updated_path: Path | None


@dataclass(frozen=True, slots=True)
class _MetricsBaselineState:
    baseline: MetricsBaseline
    loaded: bool
    status: MetricsBaselineStatus
    failure_code: ExitCode | None
    trusted_for_diff: bool


@dataclass(slots=True)
class _MetricsBaselineRuntime:
    baseline: MetricsBaseline
    loaded: bool = False
    status: MetricsBaselineStatus = MetricsBaselineStatus.MISSING
    failure_code: ExitCode | None = None
    trusted_for_diff: bool = False


@dataclass(frozen=True, slots=True)
class _MetricsBaselineSectionProbe:
    has_metrics_section: bool
    payload: dict[str, object] | None


def print_banner(*, root: Path | None = None) -> None:
    console.print(ui.banner_title(__version__))
    console.print()
    project_name = root.name if root is not None else ""
    console.print(
        Rule(
            title=f"Analyze: {project_name}" if project_name else "Analyze",
            style="dim",
            characters="\u2500",
        )
    )
    if root is not None:
        console.print(f"  [dim]Root:[/dim] [dim]{root}[/dim]")


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


def _resolve_output_paths(args: Namespace) -> OutputPaths:
    html_out_path: Path | None = None
    json_out_path: Path | None = None
    text_out_path: Path | None = None

    if getattr(args, "html_out", None):
        html_out_path = _validate_output_path(
            args.html_out,
            expected_suffix=".html",
            label="HTML",
            console=console,
            invalid_message=ui.fmt_invalid_output_extension,
            invalid_path_message=ui.fmt_invalid_output_path,
        )

    if getattr(args, "json_out", None):
        json_out_path = _validate_output_path(
            args.json_out,
            expected_suffix=".json",
            label="JSON",
            console=console,
            invalid_message=ui.fmt_invalid_output_extension,
            invalid_path_message=ui.fmt_invalid_output_path,
        )

    if getattr(args, "text_out", None):
        text_out_path = _validate_output_path(
            args.text_out,
            expected_suffix=".txt",
            label="text",
            console=console,
            invalid_message=ui.fmt_invalid_output_extension,
            invalid_path_message=ui.fmt_invalid_output_path,
        )

    return OutputPaths(html=html_out_path, json=json_out_path, text=text_out_path)


def _resolve_cache_path(*, root_path: Path, args: Namespace, from_args: bool) -> Path:
    if from_args and getattr(args, "cache_path", None):
        return Path(args.cache_path).expanduser()

    cache_path = root_path / ".cache" / "codeclone" / "cache.json"
    if LEGACY_CACHE_PATH.exists():
        try:
            legacy_resolved = LEGACY_CACHE_PATH.resolve()
        except OSError:
            legacy_resolved = LEGACY_CACHE_PATH
        if legacy_resolved != cache_path:
            console.print(
                ui.fmt_legacy_cache_warning(
                    legacy_path=legacy_resolved,
                    new_path=cache_path,
                )
            )
    return cache_path


def _validate_numeric_args(args: Namespace) -> bool:
    return bool(
        not (
            args.max_baseline_size_mb < 0
            or args.max_cache_size_mb < 0
            or args.fail_threshold < -1
            or args.fail_complexity < -1
            or args.fail_coupling < -1
            or args.fail_cohesion < -1
            or args.fail_health < -1
        )
    )


def _metrics_flags_requested(args: Namespace) -> bool:
    return bool(
        args.fail_complexity >= 0
        or args.fail_coupling >= 0
        or args.fail_cohesion >= 0
        or args.fail_cycles
        or args.fail_dead_code
        or args.fail_health >= 0
        or args.fail_on_new_metrics
        or args.update_metrics_baseline
    )


def _configure_metrics_mode(*, args: Namespace, metrics_baseline_exists: bool) -> None:
    metrics_flags_requested = _metrics_flags_requested(args)

    if args.skip_metrics and metrics_flags_requested:
        console.print(
            ui.fmt_contract_error(
                "--skip-metrics cannot be used together with metrics gating/update "
                "flags."
            )
        )
        sys.exit(ExitCode.CONTRACT_ERROR)

    if (
        not args.skip_metrics
        and not metrics_flags_requested
        and not metrics_baseline_exists
    ):
        args.skip_metrics = True

    if args.skip_metrics:
        args.skip_dead_code = True
        args.skip_dependencies = True
        return

    if args.fail_dead_code:
        args.skip_dead_code = False
    if args.fail_cycles:
        args.skip_dependencies = False


def _print_failed_files(failed_files: Sequence[str]) -> None:
    if not failed_files:
        return
    console.print(ui.fmt_failed_files_header(len(failed_files)))
    for failure in failed_files[:10]:
        console.print(f"  • {failure}")
    if len(failed_files) > 10:
        console.print(f"  ... and {len(failed_files) - 10} more")


def _metrics_computed(args: Namespace) -> tuple[str, ...]:
    if args.skip_metrics:
        return ()

    computed = ["complexity", "coupling", "cohesion", "health"]
    if not args.skip_dependencies:
        computed.append("dependencies")
    if not args.skip_dead_code:
        computed.append("dead_code")
    return tuple(computed)


def _probe_metrics_baseline_section(path: Path) -> _MetricsBaselineSectionProbe:
    if not path.exists():
        return _MetricsBaselineSectionProbe(
            has_metrics_section=False,
            payload=None,
        )
    try:
        raw_payload = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return _MetricsBaselineSectionProbe(
            has_metrics_section=True,
            payload=None,
        )
    if not isinstance(raw_payload, dict):
        return _MetricsBaselineSectionProbe(
            has_metrics_section=True,
            payload=None,
        )
    payload = dict(raw_payload)
    return _MetricsBaselineSectionProbe(
        has_metrics_section=("metrics" in payload),
        payload=payload,
    )


def _resolve_clone_baseline_state(
    *,
    args: Namespace,
    baseline_path: Path,
    baseline_exists: bool,
    analysis: AnalysisResult,
    shared_baseline_payload: dict[str, object] | None = None,
) -> _CloneBaselineState:
    baseline = Baseline(baseline_path)
    baseline_loaded = False
    baseline_status = BaselineStatus.MISSING
    baseline_failure_code: ExitCode | None = None
    baseline_trusted_for_diff = False
    baseline_updated_path: Path | None = None

    if baseline_exists:
        try:
            if shared_baseline_payload is None:
                baseline.load(max_size_bytes=args.max_baseline_size_mb * 1024 * 1024)
            else:
                baseline.load(
                    max_size_bytes=args.max_baseline_size_mb * 1024 * 1024,
                    preloaded_payload=shared_baseline_payload,
                )
        except BaselineValidationError as exc:
            baseline_status = coerce_baseline_status(exc.status)
            if not args.update_baseline:
                console.print(ui.fmt_invalid_baseline(exc))
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
                except BaselineValidationError as exc:
                    baseline_status = coerce_baseline_status(exc.status)
                    console.print(ui.fmt_invalid_baseline(exc))
                    if args.fail_on_new:
                        baseline_failure_code = ExitCode.CONTRACT_ERROR
                    else:
                        console.print(ui.WARN_BASELINE_IGNORED)
                else:
                    baseline_loaded = True
                    baseline_status = BaselineStatus.OK
                    baseline_trusted_for_diff = True
    elif not args.update_baseline:
        console.print(ui.fmt_path(ui.WARN_BASELINE_MISSING, baseline_path))

    if baseline_status in BASELINE_UNTRUSTED_STATUSES:
        baseline_loaded = False
        baseline_trusted_for_diff = False
        if args.fail_on_new and not args.update_baseline:
            baseline_failure_code = ExitCode.CONTRACT_ERROR

    if args.update_baseline:
        new_baseline = Baseline.from_groups(
            analysis.func_groups,
            analysis.block_groups,
            path=baseline_path,
            python_tag=current_python_tag(),
            fingerprint_version=BASELINE_FINGERPRINT_VERSION,
            schema_version=BASELINE_SCHEMA_VERSION,
            generator_version=__version__,
        )
        try:
            new_baseline.save()
        except OSError as exc:
            console.print(
                ui.fmt_contract_error(
                    ui.fmt_baseline_write_failed(path=baseline_path, error=exc)
                )
            )
            sys.exit(ExitCode.CONTRACT_ERROR)
        console.print(ui.fmt_path(ui.SUCCESS_BASELINE_UPDATED, baseline_path))
        baseline = new_baseline
        baseline_loaded = True
        baseline_status = BaselineStatus.OK
        baseline_trusted_for_diff = True
        baseline_updated_path = baseline_path

    return _CloneBaselineState(
        baseline=baseline,
        loaded=baseline_loaded,
        status=baseline_status,
        failure_code=baseline_failure_code,
        trusted_for_diff=baseline_trusted_for_diff,
        updated_path=baseline_updated_path,
    )


def _resolve_metrics_baseline_state(
    *,
    args: Namespace,
    metrics_baseline_path: Path,
    metrics_baseline_exists: bool,
    baseline_updated_path: Path | None,
    analysis: AnalysisResult,
    shared_baseline_payload: dict[str, object] | None = None,
) -> _MetricsBaselineState:
    state = _MetricsBaselineRuntime(baseline=MetricsBaseline(metrics_baseline_path))

    if _metrics_mode_short_circuit(args=args):
        return _MetricsBaselineState(
            baseline=state.baseline,
            loaded=state.loaded,
            status=state.status,
            failure_code=state.failure_code,
            trusted_for_diff=state.trusted_for_diff,
        )

    _load_metrics_baseline_for_diff(
        args=args,
        metrics_baseline_exists=metrics_baseline_exists,
        state=state,
        shared_baseline_payload=shared_baseline_payload,
    )
    _apply_metrics_baseline_untrusted_policy(args=args, state=state)
    _update_metrics_baseline_if_requested(
        args=args,
        metrics_baseline_path=metrics_baseline_path,
        baseline_updated_path=baseline_updated_path,
        analysis=analysis,
        state=state,
    )
    if args.ci and state.loaded:
        args.fail_on_new_metrics = True

    return _MetricsBaselineState(
        baseline=state.baseline,
        loaded=state.loaded,
        status=state.status,
        failure_code=state.failure_code,
        trusted_for_diff=state.trusted_for_diff,
    )


def _metrics_mode_short_circuit(*, args: Namespace) -> bool:
    if not args.skip_metrics:
        return False
    if args.update_metrics_baseline or args.fail_on_new_metrics:
        console.print(
            ui.fmt_contract_error(
                "Metrics baseline operations require metrics analysis. "
                "Remove --skip-metrics."
            )
        )
        sys.exit(ExitCode.CONTRACT_ERROR)
    return True


def _load_metrics_baseline_for_diff(
    *,
    args: Namespace,
    metrics_baseline_exists: bool,
    state: _MetricsBaselineRuntime,
    shared_baseline_payload: dict[str, object] | None = None,
) -> None:
    if not metrics_baseline_exists:
        if args.fail_on_new_metrics and not args.update_metrics_baseline:
            state.failure_code = ExitCode.CONTRACT_ERROR
            console.print(
                ui.fmt_contract_error(
                    "Metrics baseline file is required for --fail-on-new-metrics. "
                    "Run codeclone . --update-metrics-baseline first."
                )
            )
        return

    try:
        if shared_baseline_payload is None:
            state.baseline.load(max_size_bytes=args.max_baseline_size_mb * 1024 * 1024)
        else:
            state.baseline.load(
                max_size_bytes=args.max_baseline_size_mb * 1024 * 1024,
                preloaded_payload=shared_baseline_payload,
            )
    except BaselineValidationError as exc:
        state.status = coerce_metrics_baseline_status(exc.status)
        if not args.update_metrics_baseline:
            console.print(ui.fmt_invalid_baseline(exc))
            if args.fail_on_new_metrics:
                state.failure_code = ExitCode.CONTRACT_ERROR
        return

    if args.update_metrics_baseline:
        return

    try:
        state.baseline.verify_compatibility(runtime_python_tag=current_python_tag())
    except BaselineValidationError as exc:
        state.status = coerce_metrics_baseline_status(exc.status)
        console.print(ui.fmt_invalid_baseline(exc))
        if args.fail_on_new_metrics:
            state.failure_code = ExitCode.CONTRACT_ERROR
    else:
        state.loaded = True
        state.status = MetricsBaselineStatus.OK
        state.trusted_for_diff = True


def _apply_metrics_baseline_untrusted_policy(
    *,
    args: Namespace,
    state: _MetricsBaselineRuntime,
) -> None:
    if state.status not in METRICS_BASELINE_UNTRUSTED_STATUSES:
        return
    state.loaded = False
    state.trusted_for_diff = False
    if args.fail_on_new_metrics and not args.update_metrics_baseline:
        state.failure_code = ExitCode.CONTRACT_ERROR


def _update_metrics_baseline_if_requested(
    *,
    args: Namespace,
    metrics_baseline_path: Path,
    baseline_updated_path: Path | None,
    analysis: AnalysisResult,
    state: _MetricsBaselineRuntime,
) -> None:
    if not args.update_metrics_baseline:
        return
    if analysis.project_metrics is None:
        console.print(
            ui.fmt_contract_error(
                "Cannot update metrics baseline: metrics were not computed."
            )
        )
        sys.exit(ExitCode.CONTRACT_ERROR)

    new_metrics_baseline = MetricsBaseline.from_project_metrics(
        project_metrics=analysis.project_metrics,
        path=metrics_baseline_path,
    )
    try:
        new_metrics_baseline.save()
    except OSError as exc:
        console.print(
            ui.fmt_contract_error(
                ui.fmt_baseline_write_failed(
                    path=metrics_baseline_path,
                    error=exc,
                )
            )
        )
        sys.exit(ExitCode.CONTRACT_ERROR)

    if baseline_updated_path != metrics_baseline_path:
        console.print(ui.fmt_path(ui.SUCCESS_BASELINE_UPDATED, metrics_baseline_path))

    state.baseline = new_metrics_baseline
    state.loaded = True
    state.status = MetricsBaselineStatus.OK
    state.trusted_for_diff = True


def _resolve_cache_status(cache: Cache) -> tuple[CacheStatus, str | None]:
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
    return cache_status, cache_schema_version


def _run_analysis_stages(
    *,
    args: Namespace,
    boot: BootstrapResult,
    cache: Cache,
) -> tuple[DiscoveryResult, PipelineProcessingResult, AnalysisResult]:
    use_status = not args.quiet and not args.no_progress
    try:
        if use_status:
            with console.status(ui.STATUS_DISCOVERING, spinner="dots"):
                discovery_result = discover(boot=boot, cache=cache)
        else:
            discovery_result = discover(boot=boot, cache=cache)
    except OSError as exc:
        console.print(ui.fmt_contract_error(ui.ERR_SCAN_FAILED.format(error=exc)))
        sys.exit(ExitCode.CONTRACT_ERROR)

    for warning in discovery_result.skipped_warnings:
        console.print(f"[warning]{warning}[/warning]")

    total_files = len(discovery_result.files_to_process)
    if total_files > 0 and not args.quiet and args.no_progress:
        console.print(ui.fmt_processing_changed(total_files))

    if total_files > 0 and not args.no_progress:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=console,
        ) as progress_ui:
            task_id = progress_ui.add_task(
                f"Analyzing {total_files} files...",
                total=total_files,
            )
            processing_result = process(
                boot=boot,
                discovery=discovery_result,
                cache=cache,
                on_advance=lambda: progress_ui.advance(task_id),
                on_worker_error=lambda reason: console.print(
                    ui.fmt_worker_failed(reason)
                ),
                on_parallel_fallback=lambda exc: console.print(
                    ui.fmt_parallel_fallback(exc)
                ),
            )
    else:
        processing_result = process(
            boot=boot,
            discovery=discovery_result,
            cache=cache,
            on_worker_error=(
                (lambda reason: console.print(ui.fmt_batch_item_failed(reason)))
                if args.no_progress
                else (lambda reason: console.print(ui.fmt_worker_failed(reason)))
            ),
            on_parallel_fallback=lambda exc: console.print(
                ui.fmt_parallel_fallback(exc)
            ),
        )

    _print_failed_files(processing_result.failed_files)

    if use_status:
        with console.status(ui.STATUS_GROUPING, spinner="dots"):
            analysis_result = analyze(
                boot=boot,
                discovery=discovery_result,
                processing=processing_result,
            )
            try:
                cache.save()
            except CacheError as exc:
                console.print(ui.fmt_cache_save_failed(exc))
    else:
        analysis_result = analyze(
            boot=boot,
            discovery=discovery_result,
            processing=processing_result,
        )
        try:
            cache.save()
        except CacheError as exc:
            console.print(ui.fmt_cache_save_failed(exc))

    return discovery_result, processing_result, analysis_result


def _write_report_outputs(
    *,
    args: Namespace,
    output_paths: OutputPaths,
    report_artifacts: ReportArtifacts,
) -> str | None:
    html_report_path: str | None = None
    saved_reports: list[tuple[str, Path]] = []

    def _write_report_output(*, out: Path, content: str, label: str) -> None:
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(content, "utf-8")
        except OSError as exc:
            console.print(
                ui.fmt_contract_error(
                    ui.fmt_report_write_failed(label=label, path=out, error=exc)
                )
            )
            sys.exit(ExitCode.CONTRACT_ERROR)

    if output_paths.html and report_artifacts.html is not None:
        out = output_paths.html
        _write_report_output(out=out, content=report_artifacts.html, label="HTML")
        html_report_path = str(out)
        saved_reports.append(("HTML", out))

    if output_paths.json and report_artifacts.json is not None:
        out = output_paths.json
        _write_report_output(out=out, content=report_artifacts.json, label="JSON")
        saved_reports.append(("JSON", out))

    if output_paths.text and report_artifacts.text is not None:
        out = output_paths.text
        _write_report_output(out=out, content=report_artifacts.text, label="text")
        saved_reports.append(("Text", out))

    if saved_reports and not args.quiet:
        cwd = Path.cwd()
        console.print()
        for label, path in saved_reports:
            try:
                display = path.relative_to(cwd)
            except ValueError:
                display = path
            console.print(f"  [bold]{label} report saved:[/bold] [dim]{display}[/dim]")

    return html_report_path


def _enforce_gating(
    *,
    args: Namespace,
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
) -> None:
    if source_read_contract_failure:
        console.print(
            ui.fmt_contract_error(
                ui.fmt_unreadable_source_in_gating(
                    count=len(processing.source_read_failures)
                )
            )
        )
        for failure in processing.source_read_failures[:10]:
            console.print(f"  • {failure}")
        if len(processing.source_read_failures) > 10:
            console.print(f"  ... and {len(processing.source_read_failures) - 10} more")
        sys.exit(ExitCode.CONTRACT_ERROR)

    if baseline_failure_code is not None:
        console.print(ui.fmt_contract_error(ui.ERR_BASELINE_GATING_REQUIRES_TRUSTED))
        sys.exit(baseline_failure_code)

    if metrics_baseline_failure_code is not None:
        console.print(
            ui.fmt_contract_error(
                "Metrics baseline is untrusted or missing for requested metrics gating."
            )
        )
        sys.exit(metrics_baseline_failure_code)

    gate_result = gate(
        boot=boot,
        analysis=analysis,
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
        console.print(
            "\n[bold red]\u2717 GATING FAILURE:[/bold red] "
            "Metrics quality gate triggered."
        )
        for reason in metric_reasons:
            console.print(f"    - {reason}")
        sys.exit(ExitCode.GATING_FAILURE)

    if "clone:new" in gate_result.reasons:
        default_report = Path(".cache/codeclone/report.html")
        resolved_html_report_path = html_report_path
        if resolved_html_report_path is None and default_report.exists():
            resolved_html_report_path = str(default_report)

        console.print(
            "\n[bold red]\u2717 GATING FAILURE:[/bold red] New code clones detected."
        )
        console.print(f"    Function clone groups: {len(new_func)}")
        console.print(f"    Block clone groups: {len(new_block)}")
        if resolved_html_report_path:
            console.print(f"\n    See report: {resolved_html_report_path}")
        console.print("\n    To accept as technical debt:")
        console.print("      codeclone . --update-baseline")

        if args.verbose:
            if new_func:
                console.print("\n    Function clone hashes:")
                for clone_hash in sorted(new_func):
                    console.print(f"      - {clone_hash}")
            if new_block:
                console.print("\n    Block clone hashes:")
                for clone_hash in sorted(new_block):
                    console.print(f"      - {clone_hash}")

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
        total = int(total_raw)
        threshold = int(threshold_raw)
        console.print(
            "\n[bold red]\u2717 GATING FAILURE:[/bold red] "
            f"Total clones ({total}) exceed threshold ({threshold})."
        )
        sys.exit(ExitCode.GATING_FAILURE)


def _main_impl() -> None:
    global console

    run_started_at = time.monotonic()

    ap = build_parser(__version__)

    def _prepare_run_inputs() -> tuple[
        Namespace,
        Path,
        Path,
        bool,
        Path,
        bool,
        OutputPaths,
        Path,
        dict[str, object] | None,
    ]:
        global console
        raw_argv = tuple(sys.argv[1:])
        explicit_cli_dests = collect_explicit_cli_dests(ap, argv=raw_argv)
        cache_path_from_args = any(
            arg in {"--cache-dir", "--cache-path"}
            or arg.startswith(("--cache-dir=", "--cache-path="))
            for arg in sys.argv
        )
        metrics_path_from_args = any(
            arg == "--metrics-baseline" or arg.startswith("--metrics-baseline=")
            for arg in sys.argv
        )
        args = ap.parse_args()

        try:
            root_path = Path(args.root).resolve()
            if not root_path.exists():
                console.print(
                    ui.fmt_contract_error(ui.ERR_ROOT_NOT_FOUND.format(path=root_path))
                )
                sys.exit(ExitCode.CONTRACT_ERROR)
        except OSError as exc:
            console.print(
                ui.fmt_contract_error(ui.ERR_INVALID_ROOT_PATH.format(error=exc))
            )
            sys.exit(ExitCode.CONTRACT_ERROR)

        try:
            pyproject_config = load_pyproject_config(root_path)
        except ConfigValidationError as exc:
            console.print(ui.fmt_contract_error(str(exc)))
            sys.exit(ExitCode.CONTRACT_ERROR)
        apply_pyproject_config_overrides(
            args=args,
            config_values=pyproject_config,
            explicit_cli_dests=explicit_cli_dests,
        )
        if args.debug:
            os.environ["CODECLONE_DEBUG"] = "1"

        if args.ci:
            args.fail_on_new = True
            args.no_color = True
            args.quiet = True

        console = _make_console(no_color=args.no_color)

        if not _validate_numeric_args(args):
            console.print(
                ui.fmt_contract_error(
                    "Size limits must be non-negative integers (MB), "
                    "threshold flags must be >= 0 or -1."
                )
            )
            sys.exit(ExitCode.CONTRACT_ERROR)

        baseline_arg_path = Path(args.baseline).expanduser()
        try:
            baseline_path = baseline_arg_path.resolve()
            baseline_exists = baseline_path.exists()
        except OSError as exc:
            console.print(
                ui.fmt_contract_error(
                    ui.fmt_invalid_baseline_path(path=baseline_arg_path, error=exc)
                )
            )
            sys.exit(ExitCode.CONTRACT_ERROR)

        shared_baseline_payload: dict[str, object] | None = None
        default_metrics_baseline = ap.get_default("metrics_baseline")
        metrics_path_overridden = metrics_path_from_args or (
            args.metrics_baseline != default_metrics_baseline
        )
        metrics_baseline_arg_path = Path(
            args.metrics_baseline if metrics_path_overridden else args.baseline
        ).expanduser()
        try:
            metrics_baseline_path = metrics_baseline_arg_path.resolve()
            if metrics_baseline_path == baseline_path:
                probe = _probe_metrics_baseline_section(metrics_baseline_path)
                metrics_baseline_exists = probe.has_metrics_section
                shared_baseline_payload = probe.payload
            else:
                metrics_baseline_exists = metrics_baseline_path.exists()
        except OSError as exc:
            console.print(
                ui.fmt_contract_error(
                    ui.fmt_invalid_baseline_path(
                        path=metrics_baseline_arg_path,
                        error=exc,
                    )
                )
            )
            sys.exit(ExitCode.CONTRACT_ERROR)

        if (
            args.update_baseline
            and not args.skip_metrics
            and not args.update_metrics_baseline
        ):
            args.update_metrics_baseline = True
        _configure_metrics_mode(
            args=args,
            metrics_baseline_exists=metrics_baseline_exists,
        )
        if (
            args.update_metrics_baseline
            and metrics_baseline_path == baseline_path
            and not baseline_exists
            and not args.update_baseline
        ):
            # Unified baseline needs clone payload before metrics can be embedded.
            args.update_baseline = True

        if args.quiet:
            args.no_progress = True

        if not args.quiet:
            print_banner(root=root_path)

        output_paths = _resolve_output_paths(args)
        cache_path = _resolve_cache_path(
            root_path=root_path,
            args=args,
            from_args=cache_path_from_args,
        )
        return (
            args,
            root_path,
            baseline_path,
            baseline_exists,
            metrics_baseline_path,
            metrics_baseline_exists,
            output_paths,
            cache_path,
            shared_baseline_payload,
        )

    (
        args,
        root_path,
        baseline_path,
        baseline_exists,
        metrics_baseline_path,
        metrics_baseline_exists,
        output_paths,
        cache_path,
        shared_baseline_payload,
    ) = _prepare_run_inputs()

    cache = Cache(
        cache_path,
        root=root_path,
        max_size_bytes=args.max_cache_size_mb * 1024 * 1024,
        min_loc=args.min_loc,
        min_stmt=args.min_stmt,
    )
    cache.load()
    if cache.load_warning:
        console.print(f"[warning]{cache.load_warning}[/warning]")

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

    gating_mode = (
        args.fail_on_new
        or args.fail_threshold >= 0
        or args.fail_complexity >= 0
        or args.fail_coupling >= 0
        or args.fail_cohesion >= 0
        or args.fail_cycles
        or args.fail_dead_code
        or args.fail_health >= 0
        or args.fail_on_new_metrics
    )
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

    try:
        report_cache_path = cache_path.resolve()
    except OSError:
        report_cache_path = cache_path

    cache_status, cache_schema_version = _resolve_cache_status(cache)

    report_meta = _build_report_meta(
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
    )

    baseline_for_diff = (
        baseline_state.baseline
        if baseline_state.trusted_for_diff
        else Baseline(baseline_path)
    )
    new_func, new_block = baseline_for_diff.diff(
        analysis_result.func_groups,
        analysis_result.block_groups,
    )
    new_clones_count = len(new_func) + len(new_block)

    metrics_diff: MetricsDiff | None = None
    if (
        analysis_result.project_metrics is not None
        and metrics_baseline_state.trusted_for_diff
    ):
        metrics_diff = metrics_baseline_state.baseline.diff(
            analysis_result.project_metrics
        )

    _print_summary(
        console=console,
        quiet=args.quiet,
        files_found=discovery_result.files_found,
        files_analyzed=processing_result.files_analyzed,
        cache_hits=discovery_result.cache_hits,
        files_skipped=processing_result.files_skipped,
        analyzed_lines=processing_result.analyzed_lines,
        analyzed_functions=processing_result.analyzed_functions,
        analyzed_methods=processing_result.analyzed_methods,
        analyzed_classes=processing_result.analyzed_classes,
        func_clones_count=analysis_result.func_clones_count,
        block_clones_count=analysis_result.block_clones_count,
        segment_clones_count=analysis_result.segment_clones_count,
        suppressed_segment_groups=analysis_result.suppressed_segment_groups,
        new_clones_count=new_clones_count,
    )

    if analysis_result.project_metrics is not None:
        pm = analysis_result.project_metrics
        _print_metrics(
            console=console,
            quiet=args.quiet,
            metrics=MetricsSnapshot(
                complexity_avg=pm.complexity_avg,
                complexity_max=pm.complexity_max,
                high_risk_count=len(pm.high_risk_functions),
                coupling_avg=pm.coupling_avg,
                coupling_max=pm.coupling_max,
                cohesion_avg=pm.cohesion_avg,
                cohesion_max=pm.cohesion_max,
                cycles_count=len(pm.dependency_cycles),
                dead_code_count=len(pm.dead_code),
                health_total=pm.health.total,
                health_grade=pm.health.grade,
            ),
        )

    report_artifacts = report(
        boot=boot,
        analysis=analysis_result,
        report_meta=report_meta,
        new_func=new_func,
        new_block=new_block,
        html_builder=build_html_report,
    )
    html_report_path = _write_report_outputs(
        args=args,
        output_paths=output_paths,
        report_artifacts=report_artifacts,
    )

    _enforce_gating(
        args=args,
        boot=boot,
        analysis=analysis_result,
        processing=processing_result,
        source_read_contract_failure=source_read_contract_failure,
        baseline_failure_code=baseline_state.failure_code,
        metrics_baseline_failure_code=metrics_baseline_state.failure_code,
        new_func=new_func,
        new_block=new_block,
        metrics_diff=metrics_diff,
        html_report_path=html_report_path,
    )

    if not args.update_baseline and not args.fail_on_new and new_clones_count > 0:
        console.print(ui.WARN_NEW_CLONES_WITHOUT_FAIL)

    if not args.quiet:
        elapsed = time.monotonic() - run_started_at
        console.print()
        console.print(ui.fmt_pipeline_done(elapsed))


def main() -> None:
    try:
        _main_impl()
    except SystemExit:
        raise
    except Exception as exc:
        console.print(
            ui.fmt_internal_error(
                exc,
                issues_url=ISSUES_URL,
                debug=_is_debug_enabled(),
            )
        )
        sys.exit(ExitCode.INTERNAL_ERROR)


if __name__ == "__main__":
    main()
