# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from ...cache.store import resolve_cache_status
from ...report.meta import build_report_meta as _build_report_meta
from ...report.meta import current_report_timestamp_utc as _current_report_timestamp_utc
from . import _session_helpers as _helpers
from ._session_baseline import (
    resolve_clone_baseline_state,
    resolve_metrics_baseline_state,
)
from ._session_shared import (
    _REPORT_DUMMY_PATH,
    DEFAULT_BLOCK_MIN_LOC,
    DEFAULT_BLOCK_MIN_STMT,
    DEFAULT_MCP_HISTORY_LIMIT,
    DEFAULT_MIN_LOC,
    DEFAULT_MIN_STMT,
    DEFAULT_REPORT_DESIGN_COHESION_THRESHOLD,
    DEFAULT_REPORT_DESIGN_COMPLEXITY_THRESHOLD,
    DEFAULT_REPORT_DESIGN_COUPLING_THRESHOLD,
    DEFAULT_SEGMENT_MIN_LOC,
    DEFAULT_SEGMENT_MIN_STMT,
    MAX_MCP_HISTORY_LIMIT,
    AnalysisMode,
    Baseline,
    CachePolicy,
    CacheStatus,
    CodeCloneMCPRunStore,
    DetailLevel,
    MCPAnalysisRequest,
    MCPFindingNotFoundError,
    MCPGateRequest,
    MCPGitDiffError,
    MCPRunNotFoundError,
    MCPRunRecord,
    MCPServiceContractError,
    MCPServiceError,
    OrderedDict,
    OutputPaths,
    RLock,
    __version__,
    _as_int,
    _BufferConsole,
    _validated_history_limit,
    analyze,
    bootstrap,
    discover,
    process,
    report,
)
from ._session_state_mixin import _MCPSessionStateMixin

__all__ = [
    "DEFAULT_MCP_HISTORY_LIMIT",
    "MAX_MCP_HISTORY_LIMIT",
    "AnalysisMode",
    "CachePolicy",
    "DetailLevel",
    "MCPAnalysisRequest",
    "MCPFindingNotFoundError",
    "MCPGateRequest",
    "MCPGitDiffError",
    "MCPRunNotFoundError",
    "MCPRunRecord",
    "MCPServiceContractError",
    "MCPServiceError",
    "MCPSession",
    "_validated_history_limit",
]


class MCPSession(_MCPSessionStateMixin):
    def __init__(self, *, history_limit: int = DEFAULT_MCP_HISTORY_LIMIT) -> None:
        self._runs = CodeCloneMCPRunStore(history_limit=history_limit)
        self._state_lock = RLock()
        self._review_state: dict[str, OrderedDict[str, str | None]] = {}
        self._last_gate_results: dict[str, dict[str, object]] = {}
        self._spread_max_cache: dict[str, int] = {}

    def analyze_repository(self, request: MCPAnalysisRequest) -> dict[str, object]:
        self._validate_analysis_request(request)
        root_path = _helpers._resolve_root(request.root)
        analysis_started_at_utc = _current_report_timestamp_utc()
        changed_paths = self._resolve_request_changed_paths(
            root_path=root_path,
            changed_paths=request.changed_paths,
            git_diff_ref=request.git_diff_ref,
        )
        args = self._build_args(root_path=root_path, request=request)
        (
            baseline_path,
            baseline_exists,
            metrics_baseline_path,
            metrics_baseline_exists,
            shared_baseline_payload,
        ) = self._resolve_baseline_inputs(root_path=root_path, args=args)
        cache_path = _helpers._resolve_cache_path(root_path=root_path, args=args)
        cache = _helpers._build_cache(
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

        clone_baseline_state = resolve_clone_baseline_state(
            baseline_path=baseline_path,
            baseline_exists=baseline_exists,
            max_baseline_size_mb=_as_int(args.max_baseline_size_mb, 0),
            shared_baseline_payload=(
                shared_baseline_payload
                if metrics_baseline_path == baseline_path
                else None
            ),
        )
        metrics_baseline_state = resolve_metrics_baseline_state(
            metrics_baseline_path=metrics_baseline_path,
            metrics_baseline_exists=metrics_baseline_exists,
            max_baseline_size_mb=_as_int(args.max_baseline_size_mb, 0),
            skip_metrics=bool(args.skip_metrics),
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
            metrics_computed=_helpers._metrics_computed(request.analysis_mode),
            min_loc=_as_int(args.min_loc, DEFAULT_MIN_LOC),
            min_stmt=_as_int(args.min_stmt, DEFAULT_MIN_STMT),
            block_min_loc=_as_int(args.block_min_loc, DEFAULT_BLOCK_MIN_LOC),
            block_min_stmt=_as_int(args.block_min_stmt, DEFAULT_BLOCK_MIN_STMT),
            segment_min_loc=_as_int(args.segment_min_loc, DEFAULT_SEGMENT_MIN_LOC),
            segment_min_stmt=_as_int(args.segment_min_stmt, DEFAULT_SEGMENT_MIN_STMT),
            design_complexity_threshold=_as_int(
                getattr(
                    args,
                    "design_complexity_threshold",
                    DEFAULT_REPORT_DESIGN_COMPLEXITY_THRESHOLD,
                ),
                DEFAULT_REPORT_DESIGN_COMPLEXITY_THRESHOLD,
            ),
            design_coupling_threshold=_as_int(
                getattr(
                    args,
                    "design_coupling_threshold",
                    DEFAULT_REPORT_DESIGN_COUPLING_THRESHOLD,
                ),
                DEFAULT_REPORT_DESIGN_COUPLING_THRESHOLD,
            ),
            design_cohesion_threshold=_as_int(
                getattr(
                    args,
                    "design_cohesion_threshold",
                    DEFAULT_REPORT_DESIGN_COHESION_THRESHOLD,
                ),
                DEFAULT_REPORT_DESIGN_COHESION_THRESHOLD,
            ),
            analysis_started_at_utc=analysis_started_at_utc,
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
        report_document = _helpers._load_report_document(report_json)
        run_id = _helpers._report_digest(report_document)

        warning_items = set(console.messages)
        baseline_warning = getattr(clone_baseline_state, "warning_message", None)
        if isinstance(baseline_warning, str) and baseline_warning:
            warning_items.add(baseline_warning)
        metrics_warning = getattr(metrics_baseline_state, "warning_message", None)
        if isinstance(metrics_warning, str) and metrics_warning:
            warning_items.add(metrics_warning)
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

        base_summary = self._build_run_summary_payload(
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
        provisional_record = MCPRunRecord(
            run_id=run_id,
            root=root_path,
            request=request,
            comparison_settings=_helpers._comparison_settings(
                args=args,
                request=request,
            ),
            report_document=report_document,
            summary=base_summary,
            changed_paths=changed_paths,
            changed_projection=None,
            warnings=warnings,
            failures=failures,
            func_clones_count=analysis_result.func_clones_count,
            block_clones_count=analysis_result.block_clones_count,
            project_metrics=analysis_result.project_metrics,
            coverage_join=analysis_result.coverage_join,
            suggestions=analysis_result.suggestions,
            new_func=frozenset(new_func),
            new_block=frozenset(new_block),
            metrics_diff=metrics_diff,
        )
        changed_projection = self._build_changed_projection(provisional_record)
        summary = self._augment_summary_with_changed(
            summary=base_summary,
            changed_paths=changed_paths,
            changed_projection=changed_projection,
        )
        record = MCPRunRecord(
            run_id=run_id,
            root=root_path,
            request=request,
            comparison_settings=_helpers._comparison_settings(
                args=args,
                request=request,
            ),
            report_document=report_document,
            summary=summary,
            changed_paths=changed_paths,
            changed_projection=changed_projection,
            warnings=warnings,
            failures=failures,
            func_clones_count=analysis_result.func_clones_count,
            block_clones_count=analysis_result.block_clones_count,
            project_metrics=analysis_result.project_metrics,
            coverage_join=analysis_result.coverage_join,
            suggestions=analysis_result.suggestions,
            new_func=frozenset(new_func),
            new_block=frozenset(new_block),
            metrics_diff=metrics_diff,
        )
        self._runs.register(record)
        self._prune_session_state()
        return self._summary_payload(record.summary, record=record)

    def analyze_changed_paths(self, request: MCPAnalysisRequest) -> dict[str, object]:
        if not request.changed_paths and request.git_diff_ref is None:
            raise MCPServiceContractError(
                "analyze_changed_paths requires changed_paths or git_diff_ref."
            )
        analysis_summary = self.analyze_repository(request)
        record = self._runs.get(str(analysis_summary.get("run_id", "")) or None)
        return self._changed_analysis_payload(record)
