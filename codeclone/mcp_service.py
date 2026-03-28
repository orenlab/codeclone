# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
from argparse import Namespace
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Literal, cast

from . import __version__
from ._cli_args import (
    DEFAULT_BASELINE_PATH,
    DEFAULT_BLOCK_MIN_LOC,
    DEFAULT_BLOCK_MIN_STMT,
    DEFAULT_MAX_BASELINE_SIZE_MB,
    DEFAULT_MAX_CACHE_SIZE_MB,
    DEFAULT_MIN_LOC,
    DEFAULT_MIN_STMT,
    DEFAULT_PROCESSES,
    DEFAULT_ROOT,
    DEFAULT_SEGMENT_MIN_LOC,
    DEFAULT_SEGMENT_MIN_STMT,
)
from ._cli_baselines import (
    CloneBaselineState,
    MetricsBaselineState,
    probe_metrics_baseline_section,
    resolve_clone_baseline_state,
    resolve_metrics_baseline_state,
)
from ._cli_config import ConfigValidationError, load_pyproject_config
from ._cli_meta import _build_report_meta, _current_report_timestamp_utc
from ._cli_runtime import (
    resolve_cache_path,
    resolve_cache_status,
    validate_numeric_args,
)
from .baseline import Baseline
from .cache import Cache, CacheStatus, build_segment_report_projection
from .contracts import REPORT_SCHEMA_VERSION
from .errors import CacheError
from .models import MetricsDiff
from .normalize import NormalizationConfig
from .pipeline import (
    AnalysisResult,
    BootstrapResult,
    OutputPaths,
    analyze,
    bootstrap,
    discover,
    gate,
    process,
    report,
)
from .report.overview import materialize_report_overview

AnalysisMode = Literal["full", "clones_only"]
CachePolicy = Literal["reuse", "refresh", "off"]
HotlistKind = Literal[
    "most_actionable",
    "highest_spread",
    "production_hotspots",
    "test_fixture_hotspots",
]
FindingFamilyFilter = Literal["all", "clone", "structural", "dead_code", "design"]
FindingNoveltyFilter = Literal["all", "new", "known"]
ReportSection = Literal[
    "all",
    "meta",
    "inventory",
    "findings",
    "metrics",
    "derived",
    "integrity",
]

_LEGACY_CACHE_PATH = Path("~/.cache/codeclone/cache.json").expanduser()
_REPORT_DUMMY_PATH = Path(".cache/codeclone/report.json")
_MCP_CONFIG_KEYS = frozenset(
    {
        "min_loc",
        "min_stmt",
        "block_min_loc",
        "block_min_stmt",
        "segment_min_loc",
        "segment_min_stmt",
        "processes",
        "cache_path",
        "max_cache_size_mb",
        "baseline",
        "max_baseline_size_mb",
        "metrics_baseline",
    }
)
_RESOURCE_SECTION_MAP: dict[str, ReportSection] = {
    "report.json": "all",
    "summary": "meta",
    "overview": "derived",
}


class MCPServiceError(RuntimeError):
    """Base class for CodeClone MCP service errors."""


class MCPServiceContractError(MCPServiceError):
    """Raised when an MCP request violates the CodeClone service contract."""


class MCPRunNotFoundError(MCPServiceError):
    """Raised when a requested MCP run is not available in the in-memory registry."""


class MCPFindingNotFoundError(MCPServiceError):
    """Raised when a requested finding id is not present in the selected run."""


class _BufferConsole:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def print(self, *objects: object, **_kwargs: object) -> None:
        text = " ".join(str(obj) for obj in objects).strip()
        if text:
            self.messages.append(text)


@dataclass(frozen=True, slots=True)
class MCPAnalysisRequest:
    root: str = DEFAULT_ROOT
    analysis_mode: AnalysisMode = "full"
    respect_pyproject: bool = True
    processes: int | None = None
    min_loc: int | None = None
    min_stmt: int | None = None
    block_min_loc: int | None = None
    block_min_stmt: int | None = None
    segment_min_loc: int | None = None
    segment_min_stmt: int | None = None
    baseline_path: str | None = None
    metrics_baseline_path: str | None = None
    max_baseline_size_mb: int | None = None
    cache_policy: CachePolicy = "reuse"
    cache_path: str | None = None
    max_cache_size_mb: int | None = None


@dataclass(frozen=True, slots=True)
class MCPGateRequest:
    run_id: str | None = None
    fail_on_new: bool = False
    fail_threshold: int = -1
    fail_complexity: int = -1
    fail_coupling: int = -1
    fail_cohesion: int = -1
    fail_cycles: bool = False
    fail_dead_code: bool = False
    fail_health: int = -1
    fail_on_new_metrics: bool = False


@dataclass(frozen=True, slots=True)
class MCPRunRecord:
    run_id: str
    root: Path
    request: MCPAnalysisRequest
    report_document: dict[str, object]
    report_json: str
    summary: dict[str, object]
    warnings: tuple[str, ...]
    failures: tuple[str, ...]
    analysis: AnalysisResult
    new_func: frozenset[str]
    new_block: frozenset[str]
    metrics_diff: MetricsDiff | None


class CodeCloneMCPRunStore:
    def __init__(self, *, history_limit: int = 16) -> None:
        self._history_limit = max(1, history_limit)
        self._lock = RLock()
        self._records: OrderedDict[str, MCPRunRecord] = OrderedDict()
        self._latest_run_id: str | None = None

    def register(self, record: MCPRunRecord) -> MCPRunRecord:
        with self._lock:
            self._records.pop(record.run_id, None)
            self._records[record.run_id] = record
            self._records.move_to_end(record.run_id)
            self._latest_run_id = record.run_id
            while len(self._records) > self._history_limit:
                self._records.popitem(last=False)
        return record

    def get(self, run_id: str | None = None) -> MCPRunRecord:
        with self._lock:
            resolved_run_id = run_id or self._latest_run_id
            if resolved_run_id is None or resolved_run_id not in self._records:
                raise MCPRunNotFoundError("No matching MCP analysis run is available.")
            return self._records[resolved_run_id]


class CodeCloneMCPService:
    def __init__(self, *, history_limit: int = 16) -> None:
        self._runs = CodeCloneMCPRunStore(history_limit=history_limit)

    def analyze_repository(self, request: MCPAnalysisRequest) -> dict[str, object]:
        root_path = self._resolve_root(request.root)
        args = self._build_args(root_path=root_path, request=request)
        (
            baseline_path,
            baseline_exists,
            metrics_baseline_path,
            metrics_baseline_exists,
            shared_baseline_payload,
        ) = self._resolve_baseline_inputs(root_path=root_path, args=args)
        cache_path = self._resolve_cache_path(root_path=root_path, args=args)
        cache = self._build_cache(
            root_path=root_path,
            args=args,
            cache_path=cache_path,
            policy=request.cache_policy,
        )
        console = _BufferConsole()

        boot = bootstrap(
            args=args,
            root=root_path,
            output_paths=OutputPaths(json=_REPORT_DUMMY_PATH),
            cache_path=cache_path,
        )
        discovery_result = discover(boot=boot, cache=cache)
        processing_result = process(boot=boot, discovery=discovery_result, cache=cache)
        analysis_result = analyze(
            boot=boot,
            discovery=discovery_result,
            processing=processing_result,
        )

        if request.cache_policy == "refresh":
            self._refresh_cache_projection(cache=cache, analysis=analysis_result)
            try:
                cache.save()
            except CacheError as exc:
                console.print(f"Cache save failed: {exc}")

        clone_baseline_state = resolve_clone_baseline_state(
            args=args,
            baseline_path=baseline_path,
            baseline_exists=baseline_exists,
            func_groups=analysis_result.func_groups,
            block_groups=analysis_result.block_groups,
            codeclone_version=__version__,
            console=console,
            shared_baseline_payload=(
                shared_baseline_payload
                if metrics_baseline_path == baseline_path
                else None
            ),
        )
        metrics_baseline_state = resolve_metrics_baseline_state(
            args=args,
            metrics_baseline_path=metrics_baseline_path,
            metrics_baseline_exists=metrics_baseline_exists,
            baseline_updated_path=clone_baseline_state.updated_path,
            project_metrics=analysis_result.project_metrics,
            console=console,
            shared_baseline_payload=(
                shared_baseline_payload
                if metrics_baseline_path == baseline_path
                else None
            ),
        )

        cache_status, cache_schema_version = resolve_cache_status(cache)
        report_meta = _build_report_meta(
            codeclone_version=__version__,
            scan_root=root_path,
            baseline_path=baseline_path,
            baseline=clone_baseline_state.baseline,
            baseline_loaded=clone_baseline_state.loaded,
            baseline_status=clone_baseline_state.status.value,
            cache_path=cache_path,
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
                if analysis_result.project_metrics is not None
                else None
            ),
            health_grade=(
                analysis_result.project_metrics.health.grade
                if analysis_result.project_metrics is not None
                else None
            ),
            analysis_mode=request.analysis_mode,
            metrics_computed=self._metrics_computed(request.analysis_mode),
            report_generated_at_utc=_current_report_timestamp_utc(),
        )

        baseline_for_diff = (
            clone_baseline_state.baseline
            if clone_baseline_state.trusted_for_diff
            else Baseline(baseline_path)
        )
        new_func, new_block = baseline_for_diff.diff(
            analysis_result.func_groups,
            analysis_result.block_groups,
        )
        metrics_diff = None
        if (
            analysis_result.project_metrics is not None
            and metrics_baseline_state.trusted_for_diff
        ):
            metrics_diff = metrics_baseline_state.baseline.diff(
                analysis_result.project_metrics
            )

        report_artifacts = report(
            boot=boot,
            discovery=discovery_result,
            processing=processing_result,
            analysis=analysis_result,
            report_meta=report_meta,
            new_func=new_func,
            new_block=new_block,
            metrics_diff=metrics_diff,
        )
        report_json = report_artifacts.json
        if report_json is None:
            raise MCPServiceError("CodeClone MCP expected a canonical JSON report.")
        report_document = self._load_report_document(report_json)
        run_id = self._report_digest(report_document)

        warning_items = set(console.messages)
        if cache.load_warning:
            warning_items.add(cache.load_warning)
        warning_items.update(discovery_result.skipped_warnings)
        warnings = tuple(sorted(warning_items))
        failures = tuple(
            sorted(
                {
                    *processing_result.failed_files,
                    *processing_result.source_read_failures,
                }
            )
        )

        summary = self._build_run_summary_payload(
            run_id=run_id,
            root_path=root_path,
            request=request,
            report_document=report_document,
            baseline_state=clone_baseline_state,
            metrics_baseline_state=metrics_baseline_state,
            cache_status=cache_status,
            new_func=new_func,
            new_block=new_block,
            metrics_diff=metrics_diff,
            warnings=warnings,
            failures=failures,
        )
        record = MCPRunRecord(
            run_id=run_id,
            root=root_path,
            request=request,
            report_document=report_document,
            report_json=report_json,
            summary=summary,
            warnings=warnings,
            failures=failures,
            analysis=analysis_result,
            new_func=frozenset(new_func),
            new_block=frozenset(new_block),
            metrics_diff=metrics_diff,
        )
        self._runs.register(record)
        return summary

    def get_run_summary(self, run_id: str | None = None) -> dict[str, object]:
        return dict(self._runs.get(run_id).summary)

    def evaluate_gates(self, request: MCPGateRequest) -> dict[str, object]:
        record = self._runs.get(request.run_id)
        gate_args = Namespace(
            fail_on_new=request.fail_on_new,
            fail_threshold=request.fail_threshold,
            fail_complexity=request.fail_complexity,
            fail_coupling=request.fail_coupling,
            fail_cohesion=request.fail_cohesion,
            fail_cycles=request.fail_cycles,
            fail_dead_code=request.fail_dead_code,
            fail_health=request.fail_health,
            fail_on_new_metrics=request.fail_on_new_metrics,
        )
        boot = BootstrapResult(
            root=record.root,
            config=NormalizationConfig(),
            args=gate_args,
            output_paths=OutputPaths(),
            cache_path=_REPORT_DUMMY_PATH,
        )
        gate_result = gate(
            boot=boot,
            analysis=record.analysis,
            new_func=record.new_func,
            new_block=record.new_block,
            metrics_diff=record.metrics_diff,
        )
        return {
            "run_id": record.run_id,
            "would_fail": gate_result.exit_code != 0,
            "exit_code": gate_result.exit_code,
            "reasons": list(gate_result.reasons),
            "config": {
                "fail_on_new": request.fail_on_new,
                "fail_threshold": request.fail_threshold,
                "fail_complexity": request.fail_complexity,
                "fail_coupling": request.fail_coupling,
                "fail_cohesion": request.fail_cohesion,
                "fail_cycles": request.fail_cycles,
                "fail_dead_code": request.fail_dead_code,
                "fail_health": request.fail_health,
                "fail_on_new_metrics": request.fail_on_new_metrics,
            },
        }

    def get_report_section(
        self,
        *,
        run_id: str | None = None,
        section: ReportSection = "all",
    ) -> dict[str, object]:
        report_document = self._runs.get(run_id).report_document
        if section == "all":
            return dict(report_document)
        payload = report_document.get(section)
        if not isinstance(payload, Mapping):
            raise MCPServiceContractError(
                f"Report section '{section}' is not available in this run."
            )
        return dict(payload)

    def list_findings(
        self,
        *,
        run_id: str | None = None,
        family: FindingFamilyFilter = "all",
        severity: str | None = None,
        source_kind: str | None = None,
        novelty: FindingNoveltyFilter = "all",
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, object]:
        record = self._runs.get(run_id)
        findings = self._flatten_findings(record.report_document)
        filtered = [
            finding
            for finding in findings
            if self._matches_finding_filters(
                finding=finding,
                family=family,
                severity=severity,
                source_kind=source_kind,
                novelty=novelty,
            )
        ]
        total = len(filtered)
        normalized_offset = max(0, offset)
        normalized_limit = max(1, min(limit, 200))
        items = filtered[normalized_offset : normalized_offset + normalized_limit]
        next_offset = normalized_offset + len(items)
        return {
            "run_id": record.run_id,
            "offset": normalized_offset,
            "limit": normalized_limit,
            "returned": len(items),
            "total": total,
            "next_offset": next_offset if next_offset < total else None,
            "items": items,
        }

    def get_finding(
        self,
        *,
        finding_id: str,
        run_id: str | None = None,
    ) -> dict[str, object]:
        record = self._runs.get(run_id)
        for finding in self._flatten_findings(record.report_document):
            if str(finding.get("id")) == finding_id:
                return finding
        raise MCPFindingNotFoundError(
            f"Finding id '{finding_id}' was not found in run '{record.run_id}'."
        )

    def list_hotspots(
        self,
        *,
        kind: HotlistKind,
        run_id: str | None = None,
        limit: int = 10,
    ) -> dict[str, object]:
        record = self._runs.get(run_id)
        derived = self._as_mapping(record.report_document.get("derived"))
        materialized = materialize_report_overview(
            overview=self._as_mapping(derived.get("overview")),
            hotlists=self._as_mapping(derived.get("hotlists")),
            findings=self._as_mapping(record.report_document.get("findings")),
        )
        rows = self._as_sequence(materialized.get(kind))
        normalized_limit = max(1, min(limit, 50))
        return {
            "run_id": record.run_id,
            "kind": kind,
            "returned": min(len(rows), normalized_limit),
            "total": len(rows),
            "items": [dict(self._as_mapping(item)) for item in rows[:normalized_limit]],
        }

    def read_resource(self, uri: str) -> str:
        latest_prefix = "codeclone://latest/"
        run_prefix = "codeclone://runs/"
        if uri.startswith(latest_prefix):
            latest = self._runs.get()
            suffix = uri[len(latest_prefix) :]
            return self._render_resource(latest, suffix)
        if not uri.startswith(run_prefix):
            raise MCPServiceContractError(f"Unsupported CodeClone resource URI: {uri}")
        remainder = uri[len(run_prefix) :]
        run_id, sep, suffix = remainder.partition("/")
        if not sep:
            raise MCPServiceContractError(f"Unsupported CodeClone resource URI: {uri}")
        record = self._runs.get(run_id)
        return self._render_resource(record, suffix)

    def _render_resource(self, record: MCPRunRecord, suffix: str) -> str:
        if suffix == "summary":
            return json.dumps(
                record.summary,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        if suffix == "report.json":
            return record.report_json
        if suffix == "overview":
            return json.dumps(
                self.list_hotspots(kind="highest_spread", run_id=record.run_id),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        finding_prefix = "findings/"
        if suffix.startswith(finding_prefix):
            finding_id = suffix[len(finding_prefix) :]
            return json.dumps(
                self.get_finding(run_id=record.run_id, finding_id=finding_id),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        raise MCPServiceContractError(
            f"Unsupported CodeClone resource suffix '{suffix}'."
        )

    def _resolve_root(self, root: str) -> Path:
        try:
            root_path = Path(root).expanduser().resolve()
        except OSError as exc:
            raise MCPServiceContractError(f"Invalid root path '{root}': {exc}") from exc
        if not root_path.exists():
            raise MCPServiceContractError(f"Root path does not exist: {root_path}")
        if not root_path.is_dir():
            raise MCPServiceContractError(f"Root path is not a directory: {root_path}")
        return root_path

    def _build_args(self, *, root_path: Path, request: MCPAnalysisRequest) -> Namespace:
        args = Namespace(
            root=str(root_path),
            min_loc=DEFAULT_MIN_LOC,
            min_stmt=DEFAULT_MIN_STMT,
            block_min_loc=DEFAULT_BLOCK_MIN_LOC,
            block_min_stmt=DEFAULT_BLOCK_MIN_STMT,
            segment_min_loc=DEFAULT_SEGMENT_MIN_LOC,
            segment_min_stmt=DEFAULT_SEGMENT_MIN_STMT,
            processes=DEFAULT_PROCESSES,
            cache_path=None,
            max_cache_size_mb=DEFAULT_MAX_CACHE_SIZE_MB,
            baseline=DEFAULT_BASELINE_PATH,
            max_baseline_size_mb=DEFAULT_MAX_BASELINE_SIZE_MB,
            update_baseline=False,
            fail_on_new=False,
            fail_threshold=-1,
            ci=False,
            fail_complexity=-1,
            fail_coupling=-1,
            fail_cohesion=-1,
            fail_cycles=False,
            fail_dead_code=False,
            fail_health=-1,
            fail_on_new_metrics=False,
            update_metrics_baseline=False,
            metrics_baseline=DEFAULT_BASELINE_PATH,
            skip_metrics=False,
            skip_dead_code=False,
            skip_dependencies=False,
            html_out=None,
            json_out=None,
            md_out=None,
            sarif_out=None,
            text_out=None,
            no_progress=True,
            no_color=True,
            quiet=True,
            verbose=False,
            debug=False,
            open_html_report=False,
            timestamped_report_paths=False,
        )
        if request.respect_pyproject:
            try:
                config_values = load_pyproject_config(root_path)
            except ConfigValidationError as exc:
                raise MCPServiceContractError(str(exc)) from exc
            for key in sorted(_MCP_CONFIG_KEYS.intersection(config_values)):
                setattr(args, key, config_values[key])

        self._apply_request_overrides(args=args, root_path=root_path, request=request)

        if request.analysis_mode == "clones_only":
            args.skip_metrics = True
            args.skip_dead_code = True
            args.skip_dependencies = True
        else:
            args.skip_metrics = False
            args.skip_dead_code = False
            args.skip_dependencies = False

        if not validate_numeric_args(args):
            raise MCPServiceContractError(
                "Numeric analysis settings must be non-negative and thresholds "
                "must be >= -1."
            )

        return args

    def _apply_request_overrides(
        self,
        *,
        args: Namespace,
        root_path: Path,
        request: MCPAnalysisRequest,
    ) -> None:
        override_map: dict[str, object | None] = {
            "processes": request.processes,
            "min_loc": request.min_loc,
            "min_stmt": request.min_stmt,
            "block_min_loc": request.block_min_loc,
            "block_min_stmt": request.block_min_stmt,
            "segment_min_loc": request.segment_min_loc,
            "segment_min_stmt": request.segment_min_stmt,
            "max_baseline_size_mb": request.max_baseline_size_mb,
            "max_cache_size_mb": request.max_cache_size_mb,
        }
        for key, value in override_map.items():
            if value is not None:
                setattr(args, key, value)

        if request.baseline_path is not None:
            args.baseline = str(
                self._resolve_optional_path(request.baseline_path, root_path)
            )
        if request.metrics_baseline_path is not None:
            args.metrics_baseline = str(
                self._resolve_optional_path(request.metrics_baseline_path, root_path)
            )
        if request.cache_path is not None:
            args.cache_path = str(
                self._resolve_optional_path(request.cache_path, root_path)
            )

    def _resolve_optional_path(self, value: str, root_path: Path) -> Path:
        candidate = Path(value).expanduser()
        resolved = candidate if candidate.is_absolute() else root_path / candidate
        try:
            return resolved.resolve()
        except OSError as exc:
            raise MCPServiceContractError(
                f"Invalid path '{value}' relative to '{root_path}': {exc}"
            ) from exc

    def _resolve_baseline_inputs(
        self,
        *,
        root_path: Path,
        args: Namespace,
    ) -> tuple[Path, bool, Path, bool, dict[str, object] | None]:
        baseline_path = self._resolve_optional_path(str(args.baseline), root_path)
        baseline_exists = baseline_path.exists()

        metrics_baseline_arg_path = self._resolve_optional_path(
            str(args.metrics_baseline),
            root_path,
        )
        shared_baseline_payload: dict[str, object] | None = None
        if metrics_baseline_arg_path == baseline_path:
            probe = probe_metrics_baseline_section(metrics_baseline_arg_path)
            metrics_baseline_exists = probe.has_metrics_section
            shared_baseline_payload = probe.payload
        else:
            metrics_baseline_exists = metrics_baseline_arg_path.exists()

        return (
            baseline_path,
            baseline_exists,
            metrics_baseline_arg_path,
            metrics_baseline_exists,
            shared_baseline_payload,
        )

    def _resolve_cache_path(self, *, root_path: Path, args: Namespace) -> Path:
        return resolve_cache_path(
            root_path=root_path,
            args=args,
            from_args=bool(args.cache_path),
            legacy_cache_path=_LEGACY_CACHE_PATH,
            console=_BufferConsole(),
        )

    def _build_cache(
        self,
        *,
        root_path: Path,
        args: Namespace,
        cache_path: Path,
        policy: CachePolicy,
    ) -> Cache:
        cache = Cache(
            cache_path,
            root=root_path,
            max_size_bytes=int(args.max_cache_size_mb) * 1024 * 1024,
            min_loc=int(args.min_loc),
            min_stmt=int(args.min_stmt),
            block_min_loc=int(args.block_min_loc),
            block_min_stmt=int(args.block_min_stmt),
            segment_min_loc=int(args.segment_min_loc),
            segment_min_stmt=int(args.segment_min_stmt),
        )
        if policy != "off":
            cache.load()
        return cache

    def _refresh_cache_projection(
        self,
        *,
        cache: Cache,
        analysis: AnalysisResult,
    ) -> None:
        if not hasattr(cache, "segment_report_projection"):
            return
        new_projection = build_segment_report_projection(
            suppressed=analysis.suppressed_segment_groups,
            digest=analysis.segment_groups_raw_digest,
            groups=analysis.segment_groups,
        )
        if new_projection != cache.segment_report_projection:
            cache.segment_report_projection = new_projection

    def _metrics_computed(self, analysis_mode: AnalysisMode) -> tuple[str, ...]:
        return (
            ()
            if analysis_mode == "clones_only"
            else (
                "complexity",
                "coupling",
                "cohesion",
                "health",
                "dependencies",
                "dead_code",
            )
        )

    def _load_report_document(self, report_json: str) -> dict[str, object]:
        try:
            payload = json.loads(report_json)
        except json.JSONDecodeError as exc:
            raise MCPServiceError(
                f"Generated canonical report is not valid JSON: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise MCPServiceError("Generated canonical report must be a JSON object.")
        return dict(payload)

    def _report_digest(self, report_document: Mapping[str, object]) -> str:
        integrity = self._as_mapping(report_document.get("integrity"))
        digest = self._as_mapping(integrity.get("digest"))
        value = digest.get("value")
        if not isinstance(value, str) or not value:
            raise MCPServiceError("Canonical report digest is missing.")
        return value

    def _build_run_summary_payload(
        self,
        *,
        run_id: str,
        root_path: Path,
        request: MCPAnalysisRequest,
        report_document: Mapping[str, object],
        baseline_state: CloneBaselineState,
        metrics_baseline_state: MetricsBaselineState,
        cache_status: CacheStatus,
        new_func: Sequence[str] | set[str],
        new_block: Sequence[str] | set[str],
        metrics_diff: MetricsDiff | None,
        warnings: Sequence[str],
        failures: Sequence[str],
    ) -> dict[str, object]:
        meta = self._as_mapping(report_document.get("meta"))
        meta_baseline = self._as_mapping(meta.get("baseline"))
        meta_metrics_baseline = self._as_mapping(meta.get("metrics_baseline"))
        meta_cache = self._as_mapping(meta.get("cache"))
        inventory = self._as_mapping(report_document.get("inventory"))
        findings = self._as_mapping(report_document.get("findings"))
        metrics = self._as_mapping(report_document.get("metrics"))
        metrics_summary = self._as_mapping(metrics.get("summary"))
        summary = self._as_mapping(findings.get("summary"))
        return {
            "run_id": run_id,
            "root": str(root_path),
            "analysis_mode": request.analysis_mode,
            "codeclone_version": meta.get("codeclone_version", __version__),
            "report_schema_version": report_document.get(
                "report_schema_version",
                REPORT_SCHEMA_VERSION,
            ),
            "baseline": {
                "path": meta_baseline.get(
                    "path",
                    str(root_path / DEFAULT_BASELINE_PATH),
                ),
                "loaded": bool(meta_baseline.get("loaded", baseline_state.loaded)),
                "status": str(meta_baseline.get("status", baseline_state.status.value)),
                "trusted_for_diff": baseline_state.trusted_for_diff,
            },
            "metrics_baseline": {
                "path": meta_metrics_baseline.get(
                    "path",
                    str(root_path / DEFAULT_BASELINE_PATH),
                ),
                "loaded": bool(
                    meta_metrics_baseline.get(
                        "loaded",
                        metrics_baseline_state.loaded,
                    )
                ),
                "status": str(
                    meta_metrics_baseline.get(
                        "status",
                        metrics_baseline_state.status.value,
                    )
                ),
                "trusted_for_diff": metrics_baseline_state.trusted_for_diff,
            },
            "cache": {
                "path": meta_cache.get("path"),
                "status": str(meta_cache.get("status", cache_status.value)),
                "used": bool(meta_cache.get("used", False)),
                "schema_version": meta_cache.get("schema_version"),
            },
            "inventory": dict(inventory),
            "findings_summary": dict(summary),
            "health": dict(self._as_mapping(metrics_summary.get("health"))),
            "baseline_diff": {
                "new_function_clone_groups": len(new_func),
                "new_block_clone_groups": len(new_block),
                "new_clone_groups_total": len(new_func) + len(new_block),
            },
            "metrics_diff": self._metrics_diff_payload(metrics_diff),
            "warnings": list(warnings),
            "failures": list(failures),
        }

    def _metrics_diff_payload(
        self,
        metrics_diff: MetricsDiff | None,
    ) -> dict[str, object] | None:
        if metrics_diff is None:
            return None
        new_high_risk_functions = tuple(
            cast(Sequence[str], getattr(metrics_diff, "new_high_risk_functions", ()))
        )
        new_high_coupling_classes = tuple(
            cast(Sequence[str], getattr(metrics_diff, "new_high_coupling_classes", ()))
        )
        new_cycles = tuple(
            cast(Sequence[object], getattr(metrics_diff, "new_cycles", ()))
        )
        new_dead_code = tuple(
            cast(Sequence[str], getattr(metrics_diff, "new_dead_code", ()))
        )
        health_delta = getattr(metrics_diff, "health_delta", 0)
        return {
            "new_high_risk_functions": len(new_high_risk_functions),
            "new_high_coupling_classes": len(new_high_coupling_classes),
            "new_cycles": len(new_cycles),
            "new_dead_code": len(new_dead_code),
            "health_delta": int(health_delta),
        }

    def _flatten_findings(
        self,
        report_document: Mapping[str, object],
    ) -> list[dict[str, object]]:
        findings = self._as_mapping(report_document.get("findings"))
        groups = self._as_mapping(findings.get("groups"))
        clone_groups = self._as_mapping(groups.get("clones"))
        return [
            *self._dict_list(clone_groups.get("functions")),
            *self._dict_list(clone_groups.get("blocks")),
            *self._dict_list(clone_groups.get("segments")),
            *self._dict_list(self._as_mapping(groups.get("structural")).get("groups")),
            *self._dict_list(self._as_mapping(groups.get("dead_code")).get("groups")),
            *self._dict_list(self._as_mapping(groups.get("design")).get("groups")),
        ]

    def _matches_finding_filters(
        self,
        *,
        finding: Mapping[str, object],
        family: FindingFamilyFilter,
        severity: str | None,
        source_kind: str | None,
        novelty: FindingNoveltyFilter,
    ) -> bool:
        finding_family = str(finding.get("family", "")).strip()
        if family != "all" and finding_family != family:
            return False
        if (
            severity is not None
            and str(finding.get("severity", "")).strip() != severity
        ):
            return False
        dominant_kind = str(
            self._as_mapping(finding.get("source_scope")).get("dominant_kind", "")
        ).strip()
        if source_kind is not None and dominant_kind != source_kind:
            return False
        return novelty == "all" or str(finding.get("novelty", "")).strip() == novelty

    def _dict_list(self, value: object) -> list[dict[str, object]]:
        return [dict(self._as_mapping(item)) for item in self._as_sequence(value)]

    @staticmethod
    def _as_mapping(value: object) -> Mapping[str, object]:
        return value if isinstance(value, Mapping) else {}

    @staticmethod
    def _as_sequence(value: object) -> Sequence[object]:
        if isinstance(value, Sequence) and not isinstance(
            value,
            (str, bytes, bytearray),
        ):
            return value
        return ()
