# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol, cast

from . import __version__, _coerce
from . import ui_messages as ui
from ._cli_args import build_parser
from ._cli_baselines import (
    CloneBaselineState as _CloneBaselineStateImpl,
)
from ._cli_baselines import (
    MetricsBaselineSectionProbe as _MetricsBaselineSectionProbeImpl,
)
from ._cli_baselines import (
    MetricsBaselineState as _MetricsBaselineStateImpl,
)
from ._cli_baselines import (
    probe_metrics_baseline_section as _probe_metrics_baseline_section_impl,
)
from ._cli_baselines import (
    resolve_clone_baseline_state as _resolve_clone_baseline_state_impl,
)
from ._cli_baselines import (
    resolve_metrics_baseline_state as _resolve_metrics_baseline_state_impl,
)
from ._cli_config import (
    ConfigValidationError,
    apply_pyproject_config_overrides,
    collect_explicit_cli_dests,
    load_pyproject_config,
)
from ._cli_gating import (
    parse_metric_reason_entry as _parse_metric_reason_entry_impl,
)
from ._cli_gating import (
    print_gating_failure_block as _print_gating_failure_block_impl,
)
from ._cli_paths import _validate_output_path
from ._cli_reports import (
    write_report_outputs as _write_report_outputs_impl,
)
from ._cli_rich import (
    PlainConsole as _PlainConsole,
)
from ._cli_rich import (
    make_console as _make_rich_console,
)
from ._cli_rich import (
    make_plain_console as _make_plain_console_impl,
)
from ._cli_rich import (
    print_banner as _print_banner_impl,
)
from ._cli_rich import (
    rich_progress_symbols as _rich_progress_symbols_impl,
)
from ._cli_runtime import (
    configure_metrics_mode as _configure_metrics_mode_impl,
)
from ._cli_runtime import (
    metrics_computed as _metrics_computed_impl,
)
from ._cli_runtime import (
    print_failed_files as _print_failed_files_impl,
)
from ._cli_runtime import (
    resolve_cache_path as _resolve_cache_path_impl,
)
from ._cli_runtime import (
    resolve_cache_status as _resolve_cache_status_impl,
)
from ._cli_runtime import (
    validate_numeric_args as _validate_numeric_args_impl,
)
from ._cli_summary import (
    ChangedScopeSnapshot,
    MetricsSnapshot,
    _print_changed_scope,
    _print_metrics,
    _print_summary,
)
from ._git_diff import validate_git_diff_ref
from .baseline import Baseline
from .cache import Cache, CacheStatus, build_segment_report_projection
from .contracts import (
    DEFAULT_REPORT_DESIGN_COHESION_THRESHOLD,
    DEFAULT_REPORT_DESIGN_COMPLEXITY_THRESHOLD,
    DEFAULT_REPORT_DESIGN_COUPLING_THRESHOLD,
    ISSUES_URL,
    ExitCode,
)
from .errors import CacheError

if TYPE_CHECKING:
    from argparse import Namespace
    from collections.abc import Callable, Mapping, Sequence
    from types import ModuleType

    from rich.console import Console as RichConsole
    from rich.progress import BarColumn as RichBarColumn
    from rich.progress import Progress as RichProgress
    from rich.progress import SpinnerColumn as RichSpinnerColumn
    from rich.progress import TextColumn as RichTextColumn
    from rich.progress import TimeElapsedColumn as RichTimeElapsedColumn

    from ._cli_baselines import _BaselineArgs as _BaselineArgsLike
    from ._cli_gating import _GatingArgs as _GatingArgsLike
    from ._cli_reports import _QuietArgs as _QuietArgsLike
    from ._cli_runtime import _RuntimeArgs as _RuntimeArgsLike
    from .models import MetricsDiff
    from .normalize import NormalizationConfig
    from .pipeline import (
        AnalysisResult,
        BootstrapResult,
        DiscoveryResult,
        GatingResult,
        ReportArtifacts,
    )
    from .pipeline import (
        OutputPaths as PipelineOutputPaths,
    )
    from .pipeline import (
        ProcessingResult as PipelineProcessingResult,
    )

MAX_FILE_SIZE = 10 * 1024 * 1024
__all__ = [
    "MAX_FILE_SIZE",
    "ExitCode",
    "ProcessingResult",
    "analyze",
    "bootstrap",
    "discover",
    "gate",
    "main",
    "process",
    "process_file",
    "report",
]

# Lazy singleton for pipeline module — deferred import to keep CLI startup fast.
# Tests monkeypatch this via _pipeline_module() to inject mocks.
_PIPELINE_MODULE: ModuleType | None = None


def _pipeline_module() -> ModuleType:
    global _PIPELINE_MODULE
    if _PIPELINE_MODULE is None:
        from . import pipeline as _pipeline

        _PIPELINE_MODULE = _pipeline
    return _PIPELINE_MODULE


@dataclass(frozen=True, slots=True)
class OutputPaths:
    html: Path | None = None
    json: Path | None = None
    text: Path | None = None
    md: Path | None = None
    sarif: Path | None = None


@dataclass(frozen=True, slots=True)
class ProcessingResult:
    filepath: str
    success: bool
    error: str | None = None
    units: list[object] | None = None
    blocks: list[object] | None = None
    segments: list[object] | None = None
    lines: int = 0
    functions: int = 0
    methods: int = 0
    classes: int = 0
    stat: Mapping[str, int] | None = None
    error_kind: str | None = None
    file_metrics: object | None = None
    structural_findings: list[object] | None = None


@dataclass(frozen=True, slots=True)
class ChangedCloneGate:
    changed_paths: tuple[str, ...]
    new_func: frozenset[str]
    new_block: frozenset[str]
    total_clone_groups: int
    findings_total: int
    findings_new: int
    findings_known: int


_as_mapping = _coerce.as_mapping
_as_int = _coerce.as_int
_as_sequence = _coerce.as_sequence


def _validate_changed_scope_args(*, args: Namespace) -> str | None:
    if args.diff_against and args.paths_from_git_diff:
        console.print(
            ui.fmt_contract_error(
                "Use --diff-against or --paths-from-git-diff, not both."
            )
        )
        sys.exit(ExitCode.CONTRACT_ERROR)
    if args.paths_from_git_diff:
        args.changed_only = True
        return str(args.paths_from_git_diff)
    if args.diff_against and not args.changed_only:
        console.print(ui.fmt_contract_error("--diff-against requires --changed-only."))
        sys.exit(ExitCode.CONTRACT_ERROR)
    if args.changed_only and not args.diff_against:
        console.print(
            ui.fmt_contract_error(
                "--changed-only requires --diff-against or --paths-from-git-diff."
            )
        )
        sys.exit(ExitCode.CONTRACT_ERROR)
    return str(args.diff_against) if args.diff_against else None


def _normalize_changed_paths(
    *,
    root_path: Path,
    paths: Sequence[str],
) -> tuple[str, ...]:
    normalized: set[str] = set()
    for raw_path in paths:
        candidate = raw_path.strip()
        if not candidate:
            continue
        candidate_path = Path(candidate)
        try:
            absolute_path = (
                candidate_path.resolve()
                if candidate_path.is_absolute()
                else (root_path / candidate_path).resolve()
            )
        except OSError as exc:
            console.print(
                ui.fmt_contract_error(
                    f"Unable to resolve changed path '{candidate}': {exc}"
                )
            )
            sys.exit(ExitCode.CONTRACT_ERROR)
        try:
            relative_path = absolute_path.relative_to(root_path)
        except ValueError:
            console.print(
                ui.fmt_contract_error(
                    f"Changed path '{candidate}' is outside the scan root."
                )
            )
            sys.exit(ExitCode.CONTRACT_ERROR)
        cleaned = str(relative_path).replace("\\", "/").strip("/")
        if cleaned:
            normalized.add(cleaned)
    return tuple(sorted(normalized))


def _git_diff_changed_paths(*, root_path: Path, git_diff_ref: str) -> tuple[str, ...]:
    try:
        validated_ref = validate_git_diff_ref(git_diff_ref)
    except ValueError as exc:
        console.print(ui.fmt_contract_error(str(exc)))
        sys.exit(ExitCode.CONTRACT_ERROR)
    try:
        completed = subprocess.run(
            ["git", "diff", "--name-only", validated_ref, "--"],
            cwd=str(root_path),
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (
        FileNotFoundError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as exc:
        console.print(
            ui.fmt_contract_error(
                "Unable to resolve changed files from git diff ref "
                f"'{validated_ref}': {exc}"
            )
        )
        sys.exit(ExitCode.CONTRACT_ERROR)
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    return _normalize_changed_paths(root_path=root_path, paths=lines)


def _path_matches(relative_path: str, changed_paths: Sequence[str]) -> bool:
    return any(
        relative_path == candidate or relative_path.startswith(candidate + "/")
        for candidate in changed_paths
    )


def _flatten_report_findings(
    report_document: Mapping[str, object],
) -> list[dict[str, object]]:
    findings = _as_mapping(report_document.get("findings"))
    groups = _as_mapping(findings.get("groups"))
    clone_groups = _as_mapping(groups.get("clones"))
    return [
        *[
            dict(_as_mapping(item))
            for item in _as_sequence(clone_groups.get("functions"))
        ],
        *[dict(_as_mapping(item)) for item in _as_sequence(clone_groups.get("blocks"))],
        *[
            dict(_as_mapping(item))
            for item in _as_sequence(clone_groups.get("segments"))
        ],
        *[
            dict(_as_mapping(item))
            for item in _as_sequence(
                _as_mapping(groups.get("structural")).get("groups")
            )
        ],
        *[
            dict(_as_mapping(item))
            for item in _as_sequence(_as_mapping(groups.get("dead_code")).get("groups"))
        ],
        *[
            dict(_as_mapping(item))
            for item in _as_sequence(_as_mapping(groups.get("design")).get("groups"))
        ],
    ]


def _finding_touches_changed_paths(
    finding: Mapping[str, object],
    *,
    changed_paths: Sequence[str],
) -> bool:
    for item in _as_sequence(finding.get("items")):
        relative_path = str(_as_mapping(item).get("relative_path", "")).strip()
        if relative_path and _path_matches(relative_path, changed_paths):
            return True
    return False


def _changed_clone_gate_from_report(
    report_document: Mapping[str, object],
    *,
    changed_paths: Sequence[str],
) -> ChangedCloneGate:
    findings = [
        finding
        for finding in _flatten_report_findings(report_document)
        if _finding_touches_changed_paths(finding, changed_paths=changed_paths)
    ]
    clone_findings = [
        finding
        for finding in findings
        if str(finding.get("family", "")).strip() == "clone"
        and str(finding.get("category", "")).strip() in {"function", "block"}
    ]
    new_func = frozenset(
        str(finding.get("id", ""))
        for finding in clone_findings
        if str(finding.get("category", "")).strip() == "function"
        and str(finding.get("novelty", "")).strip() == "new"
    )
    new_block = frozenset(
        str(finding.get("id", ""))
        for finding in clone_findings
        if str(finding.get("category", "")).strip() == "block"
        and str(finding.get("novelty", "")).strip() == "new"
    )
    findings_new = sum(
        1 for finding in findings if str(finding.get("novelty", "")).strip() == "new"
    )
    findings_known = sum(
        1 for finding in findings if str(finding.get("novelty", "")).strip() == "known"
    )
    return ChangedCloneGate(
        changed_paths=tuple(changed_paths),
        new_func=new_func,
        new_block=new_block,
        total_clone_groups=len(clone_findings),
        findings_total=len(findings),
        findings_new=findings_new,
        findings_known=findings_known,
    )


def process_file(
    filepath: str,
    root: str,
    cfg: NormalizationConfig,
    min_loc: int,
    min_stmt: int,
    collect_structural_findings: bool = True,
) -> ProcessingResult:
    pipeline_mod = _pipeline_module()
    result = pipeline_mod.process_file(
        filepath,
        root,
        cfg,
        min_loc,
        min_stmt,
        collect_structural_findings,
    )
    return cast("ProcessingResult", result)


def bootstrap(
    *,
    args: Namespace,
    root: Path,
    output_paths: PipelineOutputPaths | OutputPaths,
    cache_path: Path,
) -> BootstrapResult:
    return cast(
        "BootstrapResult",
        _pipeline_module().bootstrap(
            args=args,
            root=root,
            output_paths=output_paths,
            cache_path=cache_path,
        ),
    )


def discover(*, boot: BootstrapResult, cache: Cache) -> DiscoveryResult:
    return cast("DiscoveryResult", _pipeline_module().discover(boot=boot, cache=cache))


def process(
    *,
    boot: BootstrapResult,
    discovery: DiscoveryResult,
    cache: Cache,
    on_advance: Callable[[], None] | None = None,
    on_worker_error: Callable[[str], None] | None = None,
    on_parallel_fallback: Callable[[Exception], None] | None = None,
) -> PipelineProcessingResult:
    return cast(
        "PipelineProcessingResult",
        _pipeline_module().process(
            boot=boot,
            discovery=discovery,
            cache=cache,
            on_advance=on_advance,
            on_worker_error=on_worker_error,
            on_parallel_fallback=on_parallel_fallback,
        ),
    )


def analyze(
    *,
    boot: BootstrapResult,
    discovery: DiscoveryResult,
    processing: PipelineProcessingResult,
) -> AnalysisResult:
    return cast(
        "AnalysisResult",
        _pipeline_module().analyze(
            boot=boot,
            discovery=discovery,
            processing=processing,
        ),
    )


def report(
    *,
    boot: BootstrapResult,
    discovery: DiscoveryResult,
    processing: PipelineProcessingResult,
    analysis: AnalysisResult,
    report_meta: Mapping[str, object],
    new_func: set[str],
    new_block: set[str],
    html_builder: Callable[..., str] | None = None,
    metrics_diff: MetricsDiff | None = None,
    coverage_adoption_diff_available: bool = False,
    api_surface_diff_available: bool = False,
    include_report_document: bool = False,
) -> ReportArtifacts:
    return cast(
        "ReportArtifacts",
        _pipeline_module().report(
            boot=boot,
            discovery=discovery,
            processing=processing,
            analysis=analysis,
            report_meta=report_meta,
            new_func=new_func,
            new_block=new_block,
            html_builder=html_builder,
            metrics_diff=metrics_diff,
            coverage_adoption_diff_available=coverage_adoption_diff_available,
            api_surface_diff_available=api_surface_diff_available,
            include_report_document=include_report_document,
        ),
    )


def gate(
    *,
    boot: BootstrapResult,
    analysis: AnalysisResult,
    new_func: set[str],
    new_block: set[str],
    metrics_diff: MetricsDiff | None,
) -> GatingResult:
    return cast(
        "GatingResult",
        _pipeline_module().gate(
            boot=boot,
            analysis=analysis,
            new_func=new_func,
            new_block=new_block,
            metrics_diff=metrics_diff,
        ),
    )


class _PrinterLike(Protocol):
    def print(self, *objects: object, **kwargs: object) -> None: ...


LEGACY_CACHE_PATH = Path("~/.cache/codeclone/cache.json").expanduser()
ReportPathOrigin = Literal["default", "explicit"]


def _rich_progress_symbols() -> tuple[
    type[RichProgress],
    type[RichSpinnerColumn],
    type[RichTextColumn],
    type[RichBarColumn],
    type[RichTimeElapsedColumn],
]:
    return _rich_progress_symbols_impl()


def _make_console(*, no_color: bool) -> RichConsole:
    return _make_rich_console(
        no_color=no_color,
        width=ui.CLI_LAYOUT_MAX_WIDTH,
    )


def _print_verbose_clone_hashes(
    console: _PrinterLike,
    *,
    label: str,
    clone_hashes: set[str],
) -> None:
    if not clone_hashes:
        return
    console.print(f"\n    {label}:")
    for clone_hash in sorted(clone_hashes):
        console.print(f"      - {clone_hash}")


def _make_plain_console() -> _PlainConsole:
    return _make_plain_console_impl()


console: RichConsole | _PlainConsole = _make_plain_console()


def _parse_metric_reason_entry(reason: str) -> tuple[str, str]:
    return _parse_metric_reason_entry_impl(reason)


def _print_gating_failure_block(
    *,
    code: str,
    entries: Sequence[tuple[str, object]],
    args: Namespace,
) -> None:
    _print_gating_failure_block_impl(
        console=cast("_PrinterLike", console),
        code=code,
        entries=list(entries),
        args=cast("_GatingArgsLike", cast(object, args)),
    )


def build_html_report(*args: object, **kwargs: object) -> str:
    # Lazy import avoids pulling HTML renderer in non-HTML CLI runs.
    from .html_report import build_html_report as _build_html_report

    html_builder: Callable[..., str] = _build_html_report
    return html_builder(*args, **kwargs)


_CloneBaselineState = _CloneBaselineStateImpl
_MetricsBaselineState = _MetricsBaselineStateImpl
_MetricsBaselineSectionProbe = _MetricsBaselineSectionProbeImpl


def print_banner(*, root: Path | None = None) -> None:
    _print_banner_impl(
        console=cast("_PrinterLike", console),
        banner_title=ui.banner_title(__version__),
        project_name=(root.name if root is not None else None),
        root_display=(str(root) if root is not None else None),
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


def _report_path_origins(argv: Sequence[str]) -> dict[str, ReportPathOrigin | None]:
    origins: dict[str, ReportPathOrigin | None] = {
        "html": None,
        "json": None,
        "md": None,
        "sarif": None,
        "text": None,
    }
    flag_to_field = {
        "--html": "html",
        "--json": "json",
        "--md": "md",
        "--sarif": "sarif",
        "--text": "text",
    }
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--":
            break
        if "=" in token:
            flag, _value = token.split("=", maxsplit=1)
            field_name = flag_to_field.get(flag)
            if field_name is not None:
                origins[field_name] = "explicit"
            index += 1
            continue
        field_name = flag_to_field.get(token)
        if field_name is None:
            index += 1
            continue
        next_token = argv[index + 1] if index + 1 < len(argv) else None
        if next_token is None or next_token.startswith("-"):
            origins[field_name] = "default"
            index += 1
            continue
        origins[field_name] = "explicit"
        index += 2
    return origins


def _report_path_timestamp_slug(report_generated_at_utc: str) -> str:
    return report_generated_at_utc.replace("-", "").replace(":", "")


def _timestamped_report_path(path: Path, *, report_generated_at_utc: str) -> Path:
    suffix = path.suffix
    stem = path.name[: -len(suffix)] if suffix else path.name
    return path.with_name(
        f"{stem}-{_report_path_timestamp_slug(report_generated_at_utc)}{suffix}"
    )


def _resolve_output_paths(
    args: Namespace,
    *,
    report_path_origins: Mapping[str, ReportPathOrigin | None],
    report_generated_at_utc: str,
) -> OutputPaths:
    printer = cast("_PrinterLike", console)
    resolved: dict[str, Path | None] = {
        "html": None,
        "json": None,
        "md": None,
        "sarif": None,
        "text": None,
    }
    output_specs = (
        ("html", "html_out", ".html", "HTML"),
        ("json", "json_out", ".json", "JSON"),
        ("md", "md_out", ".md", "Markdown"),
        ("sarif", "sarif_out", ".sarif", "SARIF"),
        ("text", "text_out", ".txt", "text"),
    )

    for field_name, arg_name, expected_suffix, label in output_specs:
        raw_value = getattr(args, arg_name, None)
        if not raw_value:
            continue
        path = _validate_output_path(
            raw_value,
            expected_suffix=expected_suffix,
            label=label,
            console=printer,
            invalid_message=ui.fmt_invalid_output_extension,
            invalid_path_message=ui.fmt_invalid_output_path,
        )
        if (
            args.timestamped_report_paths
            and report_path_origins.get(field_name) == "default"
        ):
            path = _timestamped_report_path(
                path,
                report_generated_at_utc=report_generated_at_utc,
            )
        resolved[field_name] = path

    return OutputPaths(
        html=resolved["html"],
        json=resolved["json"],
        text=resolved["text"],
        md=resolved["md"],
        sarif=resolved["sarif"],
    )


def _validate_report_ui_flags(*, args: Namespace, output_paths: OutputPaths) -> None:
    if args.open_html_report and output_paths.html is None:
        console.print(ui.fmt_contract_error(ui.ERR_OPEN_HTML_REPORT_REQUIRES_HTML))
        sys.exit(ExitCode.CONTRACT_ERROR)

    if args.timestamped_report_paths and not any(
        (
            output_paths.html,
            output_paths.json,
            output_paths.md,
            output_paths.sarif,
            output_paths.text,
        )
    ):
        console.print(
            ui.fmt_contract_error(ui.ERR_TIMESTAMPED_REPORT_PATHS_REQUIRES_REPORT)
        )
        sys.exit(ExitCode.CONTRACT_ERROR)


def _resolve_cache_path(*, root_path: Path, args: Namespace, from_args: bool) -> Path:
    return _resolve_cache_path_impl(
        root_path=root_path,
        args=cast("_RuntimeArgsLike", cast(object, args)),
        from_args=from_args,
        legacy_cache_path=LEGACY_CACHE_PATH,
        console=cast("_PrinterLike", console),
    )


def _validate_numeric_args(args: Namespace) -> bool:
    return _validate_numeric_args_impl(cast("_RuntimeArgsLike", cast(object, args)))


def _configure_metrics_mode(*, args: Namespace, metrics_baseline_exists: bool) -> None:
    _configure_metrics_mode_impl(
        args=cast("_RuntimeArgsLike", cast(object, args)),
        metrics_baseline_exists=metrics_baseline_exists,
        console=cast("_PrinterLike", console),
    )


def _print_failed_files(failed_files: Sequence[str]) -> None:
    _print_failed_files_impl(
        failed_files=tuple(failed_files),
        console=cast("_PrinterLike", console),
    )


def _metrics_computed(args: Namespace) -> tuple[str, ...]:
    return _metrics_computed_impl(cast("_RuntimeArgsLike", cast(object, args)))


def _probe_metrics_baseline_section(path: Path) -> _MetricsBaselineSectionProbe:
    return _probe_metrics_baseline_section_impl(path)


def _resolve_clone_baseline_state(
    *,
    args: Namespace,
    baseline_path: Path,
    baseline_exists: bool,
    analysis: AnalysisResult,
    shared_baseline_payload: dict[str, object] | None = None,
) -> _CloneBaselineState:
    return _resolve_clone_baseline_state_impl(
        args=cast("_BaselineArgsLike", cast(object, args)),
        baseline_path=baseline_path,
        baseline_exists=baseline_exists,
        func_groups=analysis.func_groups,
        block_groups=analysis.block_groups,
        codeclone_version=__version__,
        console=cast("_PrinterLike", console),
        shared_baseline_payload=shared_baseline_payload,
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
    return _resolve_metrics_baseline_state_impl(
        args=cast("_BaselineArgsLike", cast(object, args)),
        metrics_baseline_path=metrics_baseline_path,
        metrics_baseline_exists=metrics_baseline_exists,
        baseline_updated_path=baseline_updated_path,
        project_metrics=analysis.project_metrics,
        console=cast("_PrinterLike", console),
        shared_baseline_payload=shared_baseline_payload,
    )


def _resolve_cache_status(cache: Cache) -> tuple[CacheStatus, str | None]:
    return _resolve_cache_status_impl(cache)


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
    args: Namespace,
    boot: BootstrapResult,
    cache: Cache,
) -> tuple[DiscoveryResult, PipelineProcessingResult, AnalysisResult]:
    def _require_rich_console(
        value: RichConsole | _PlainConsole,
    ) -> RichConsole:
        if isinstance(value, _PlainConsole):
            raise RuntimeError("Rich console is required when progress UI is enabled.")
        return value

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
        (
            progress_cls,
            spinner_column_cls,
            text_column_cls,
            bar_column_cls,
            time_elapsed_column_cls,
        ) = _rich_progress_symbols()

        with progress_cls(
            spinner_column_cls(),
            text_column_cls("[progress.description]{task.description}"),
            bar_column_cls(),
            text_column_cls("[progress.percentage]{task.percentage:>3.0f}%"),
            time_elapsed_column_cls(),
            console=_require_rich_console(console),
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
    # Keep unreadable-source diagnostics visible in normal mode even if
    # failed_files was filtered/empty due upstream transport differences.
    if not processing_result.failed_files and processing_result.source_read_failures:
        _print_failed_files(processing_result.source_read_failures)

    if use_status:
        with console.status(ui.STATUS_GROUPING, spinner="dots"):
            analysis_result = analyze(
                boot=boot,
                discovery=discovery_result,
                processing=processing_result,
            )
            _cache_update_segment_projection(cache, analysis_result)
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
        _cache_update_segment_projection(cache, analysis_result)
        try:
            cache.save()
        except CacheError as exc:
            console.print(ui.fmt_cache_save_failed(exc))

    coverage_join = getattr(analysis_result, "coverage_join", None)
    if (
        coverage_join is not None
        and coverage_join.status != "ok"
        and coverage_join.invalid_reason
    ):
        console.print(ui.fmt_coverage_join_ignored(coverage_join.invalid_reason))

    return discovery_result, processing_result, analysis_result


def _write_report_outputs(
    *,
    args: Namespace,
    output_paths: OutputPaths,
    report_artifacts: ReportArtifacts,
    open_html_report: bool = False,
) -> str | None:
    return _write_report_outputs_impl(
        args=cast("_QuietArgsLike", cast(object, args)),
        output_paths=output_paths,
        report_artifacts=report_artifacts,
        console=cast("_PrinterLike", console),
        open_html_report=open_html_report,
    )


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
    clone_threshold_total: int | None = None,
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

    if bool(getattr(args, "fail_on_untested_hotspots", False)):
        if analysis.coverage_join is None:
            console.print(
                ui.fmt_contract_error(
                    "--fail-on-untested-hotspots requires --coverage."
                )
            )
            sys.exit(ExitCode.CONTRACT_ERROR)
        if analysis.coverage_join.status != "ok":
            detail = analysis.coverage_join.invalid_reason or "invalid coverage input"
            console.print(
                ui.fmt_contract_error(
                    "Coverage gating requires a valid Cobertura XML input.\n"
                    f"Reason: {detail}"
                )
            )
            sys.exit(ExitCode.CONTRACT_ERROR)

    gate_result = gate(
        boot=boot,
        analysis=analysis,
        new_func=new_func,
        new_block=new_block,
        metrics_diff=metrics_diff,
    )
    if clone_threshold_total is not None:
        reasons = [
            reason
            for reason in gate_result.reasons
            if not reason.startswith("clone:threshold:")
        ]
        if 0 <= args.fail_threshold < clone_threshold_total:
            reasons.append(
                f"clone:threshold:{clone_threshold_total}:{args.fail_threshold}"
            )
        gate_result = cast(
            "GatingResult",
            _pipeline_module().GatingResult(
                exit_code=(
                    int(ExitCode.GATING_FAILURE) if reasons else int(ExitCode.SUCCESS)
                ),
                reasons=tuple(reasons),
            ),
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
            args=args,
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
            args=args,
        )

        if args.verbose:
            _print_verbose_clone_hashes(
                cast("_PrinterLike", console),
                label="Function clone hashes",
                clone_hashes=new_func,
            )
            _print_verbose_clone_hashes(
                cast("_PrinterLike", console),
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
        total = int(total_raw)
        threshold = int(threshold_raw)
        _print_gating_failure_block(
            code="threshold",
            entries=(
                ("clone_groups_total", total),
                ("clone_groups_limit", threshold),
            ),
            args=args,
        )
        sys.exit(ExitCode.GATING_FAILURE)


def _main_impl() -> None:
    global console

    run_started_at = time.monotonic()
    from ._cli_meta import _build_report_meta, _current_report_timestamp_utc

    analysis_started_at_utc = _current_report_timestamp_utc()
    ap = build_parser(__version__)

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
        tuple[str, ...],
        str,
        str,
    ]:
        global console
        raw_argv = tuple(sys.argv[1:])
        explicit_cli_dests = collect_explicit_cli_dests(ap, argv=raw_argv)
        report_path_origins = _report_path_origins(raw_argv)
        report_generated_at_utc = _current_report_timestamp_utc()
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
        git_diff_ref = _validate_changed_scope_args(args=args)
        changed_paths = (
            _git_diff_changed_paths(root_path=root_path, git_diff_ref=git_diff_ref)
            if git_diff_ref is not None
            else ()
        )
        if args.debug:
            os.environ["CODECLONE_DEBUG"] = "1"

        if args.ci:
            args.fail_on_new = True
            args.no_color = True
            args.quiet = True

        console = (
            _make_plain_console()
            if args.quiet
            else _make_console(no_color=args.no_color)
        )

        if not _validate_numeric_args(args):
            console.print(
                ui.fmt_contract_error(
                    "Size limits must be non-negative integers (MB), "
                    "threshold flags must be >= 0 or -1, and coverage thresholds "
                    "must be between 0 and 100."
                )
            )
            sys.exit(ExitCode.CONTRACT_ERROR)

        baseline_arg_path = Path(args.baseline).expanduser()
        try:
            baseline_path = _resolve_runtime_path_arg(
                root_path=root_path,
                raw_path=args.baseline,
                from_cli=baseline_path_from_args,
            )
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
            metrics_baseline_path = _resolve_runtime_path_arg(
                root_path=root_path,
                raw_path=(
                    args.metrics_baseline if metrics_path_overridden else args.baseline
                ),
                from_cli=metrics_path_from_args,
            )
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
            changed_paths,
            analysis_started_at_utc,
            report_generated_at_utc,
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
        changed_paths,
        analysis_started_at_utc,
        report_generated_at_utc,
    ) = _prepare_run_inputs()

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
        or args.fail_on_typing_regression
        or args.fail_on_docstring_regression
        or args.fail_on_api_break
        or args.min_typing_coverage >= 0
        or args.min_docstring_coverage >= 0
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
    coverage_adoption_diff_available = bool(
        metrics_baseline_state.trusted_for_diff
        and getattr(
            metrics_baseline_state.baseline,
            "has_coverage_adoption_snapshot",
            False,
        )
    )
    api_surface_diff_available = bool(
        metrics_baseline_state.trusted_for_diff
        and getattr(metrics_baseline_state.baseline, "api_surface_snapshot", None)
        is not None
    )

    _print_summary(
        console=cast("_PrinterLike", console),
        quiet=args.quiet,
        files_found=discovery_result.files_found,
        files_analyzed=processing_result.files_analyzed,
        cache_hits=discovery_result.cache_hits,
        files_skipped=processing_result.files_skipped,
        analyzed_lines=(
            processing_result.analyzed_lines
            + int(getattr(discovery_result, "cached_lines", 0))
        ),
        analyzed_functions=(
            processing_result.analyzed_functions
            + int(getattr(discovery_result, "cached_functions", 0))
        ),
        analyzed_methods=(
            processing_result.analyzed_methods
            + int(getattr(discovery_result, "cached_methods", 0))
        ),
        analyzed_classes=(
            processing_result.analyzed_classes
            + int(getattr(discovery_result, "cached_classes", 0))
        ),
        func_clones_count=analysis_result.func_clones_count,
        block_clones_count=analysis_result.block_clones_count,
        segment_clones_count=analysis_result.segment_clones_count,
        suppressed_golden_fixture_groups=len(
            getattr(analysis_result, "suppressed_clone_groups", ())
        ),
        suppressed_segment_groups=analysis_result.suppressed_segment_groups,
        new_clones_count=new_clones_count,
    )

    if analysis_result.project_metrics is not None:
        pm = analysis_result.project_metrics
        metrics_payload_map = _as_mapping(analysis_result.metrics_payload)
        overloaded_modules_summary = _as_mapping(
            _as_mapping(metrics_payload_map.get("overloaded_modules")).get("summary")
        )
        adoption_summary = _as_mapping(
            _as_mapping(metrics_payload_map.get("coverage_adoption")).get("summary")
        )
        api_surface_summary = _as_mapping(
            _as_mapping(metrics_payload_map.get("api_surface")).get("summary")
        )
        coverage_join_summary = _as_mapping(
            _as_mapping(metrics_payload_map.get("coverage_join")).get("summary")
        )
        overloaded_modules_summary_map = _as_mapping(overloaded_modules_summary)
        coverage_join_source = str(coverage_join_summary.get("source", "")).strip()
        _print_metrics(
            console=cast("_PrinterLike", console),
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
                suppressed_dead_code_count=analysis_result.suppressed_dead_code_items,
                overloaded_modules_candidates=_as_int(
                    overloaded_modules_summary_map.get("candidates")
                ),
                overloaded_modules_total=_as_int(
                    overloaded_modules_summary_map.get("total")
                ),
                overloaded_modules_population_status=str(
                    overloaded_modules_summary_map.get("population_status", "")
                ),
                overloaded_modules_top_score=_coerce.as_float(
                    overloaded_modules_summary_map.get("top_score")
                ),
                adoption_param_permille=(
                    _as_int(adoption_summary.get("param_permille"))
                    if adoption_summary
                    else None
                ),
                adoption_return_permille=(
                    _as_int(adoption_summary.get("return_permille"))
                    if adoption_summary
                    else None
                ),
                adoption_docstring_permille=(
                    _as_int(adoption_summary.get("docstring_permille"))
                    if adoption_summary
                    else None
                ),
                adoption_any_annotation_count=_as_int(
                    adoption_summary.get("typing_any_count")
                ),
                api_surface_enabled=bool(api_surface_summary.get("enabled")),
                api_surface_modules=_as_int(api_surface_summary.get("modules")),
                api_surface_public_symbols=_as_int(
                    api_surface_summary.get("public_symbols")
                ),
                api_surface_added=(
                    len(metrics_diff.new_api_symbols)
                    if metrics_diff is not None and api_surface_diff_available
                    else 0
                ),
                api_surface_breaking=(
                    len(metrics_diff.new_api_breaking_changes)
                    if metrics_diff is not None and api_surface_diff_available
                    else 0
                ),
                coverage_join_status=str(
                    coverage_join_summary.get("status", "")
                ).strip(),
                coverage_join_overall_permille=_as_int(
                    coverage_join_summary.get("overall_permille")
                ),
                coverage_join_coverage_hotspots=_as_int(
                    coverage_join_summary.get("coverage_hotspots")
                ),
                coverage_join_scope_gap_hotspots=_as_int(
                    coverage_join_summary.get("scope_gap_hotspots")
                ),
                coverage_join_threshold_percent=_as_int(
                    coverage_join_summary.get("hotspot_threshold_percent")
                ),
                coverage_join_source_label=(
                    Path(coverage_join_source).name if coverage_join_source else ""
                ),
            ),
        )

    report_artifacts = report(
        boot=boot,
        discovery=discovery_result,
        processing=processing_result,
        analysis=analysis_result,
        report_meta=report_meta,
        new_func=new_func,
        new_block=new_block,
        html_builder=build_html_report,
        metrics_diff=metrics_diff,
        coverage_adoption_diff_available=coverage_adoption_diff_available,
        api_surface_diff_available=api_surface_diff_available,
        include_report_document=bool(changed_paths),
    )
    changed_clone_gate = (
        _changed_clone_gate_from_report(
            report_artifacts.report_document or {},
            changed_paths=changed_paths,
        )
        if args.changed_only and report_artifacts.report_document is not None
        else None
    )
    if changed_clone_gate is not None:
        _print_changed_scope(
            console=cast("_PrinterLike", console),
            quiet=args.quiet,
            changed_scope=ChangedScopeSnapshot(
                paths_count=len(changed_clone_gate.changed_paths),
                findings_total=changed_clone_gate.findings_total,
                findings_new=changed_clone_gate.findings_new,
                findings_known=changed_clone_gate.findings_known,
            ),
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
        new_func=set(changed_clone_gate.new_func) if changed_clone_gate else new_func,
        new_block=(
            set(changed_clone_gate.new_block) if changed_clone_gate else new_block
        ),
        metrics_diff=metrics_diff,
        html_report_path=html_report_path,
        clone_threshold_total=(
            changed_clone_gate.total_clone_groups if changed_clone_gate else None
        ),
    )

    notice_new_clones_count = (
        len(changed_clone_gate.new_func) + len(changed_clone_gate.new_block)
        if changed_clone_gate is not None
        else new_clones_count
    )
    if (
        not args.update_baseline
        and not args.fail_on_new
        and notice_new_clones_count > 0
    ):
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
