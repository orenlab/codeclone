# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from ...baseline.metrics_baseline import probe_metrics_baseline_section
from . import _session_helpers as _helpers
from ._session_baseline import (
    CloneBaselineState,
    MetricsBaselineState,
)
from ._session_finding_mixin import _MCPSessionFindingMixin, _StateLock
from ._session_runtime import validate_numeric_args
from ._session_shared import (
    _FOCUS_PRODUCTION,
    _FOCUS_REPOSITORY,
    _HEALTH_SCOPE_REPOSITORY,
    _HELP_TOPIC_SPECS,
    _MCP_CONFIG_KEYS,
    _METRICS_DETAIL_FAMILY_ALIASES,
    _VALID_COMPARISON_FOCUS,
    _VALID_HELP_DETAILS,
    _VALID_HELP_TOPICS,
    _VALID_METRICS_DETAIL_FAMILIES,
    _VALID_PR_SUMMARY_FORMATS,
    _VALID_REPORT_SECTIONS,
    DEFAULT_BASELINE_PATH,
    DEFAULT_BLOCK_MIN_LOC,
    DEFAULT_BLOCK_MIN_STMT,
    DEFAULT_COVERAGE_MIN,
    DEFAULT_MAX_BASELINE_SIZE_MB,
    DEFAULT_MAX_CACHE_SIZE_MB,
    DEFAULT_MIN_LOC,
    DEFAULT_MIN_STMT,
    DEFAULT_REPORT_DESIGN_COHESION_THRESHOLD,
    DEFAULT_REPORT_DESIGN_COMPLEXITY_THRESHOLD,
    DEFAULT_REPORT_DESIGN_COUPLING_THRESHOLD,
    DEFAULT_SEGMENT_MIN_LOC,
    DEFAULT_SEGMENT_MIN_STMT,
    FAMILY_CLONE,
    REPORT_SCHEMA_VERSION,
    SOURCE_KIND_PRODUCTION,
    CacheStatus,
    CodeCloneMCPRunStore,
    ComparisonFocus,
    ConfigValidationError,
    GatingResult,
    HelpDetail,
    HelpTopic,
    Mapping,
    MCPAnalysisRequest,
    MCPGateRequest,
    MCPRunRecord,
    MCPServiceContractError,
    MetricGateConfig,
    MetricsDetailFamily,
    MetricsDiff,
    Namespace,
    OrderedDict,
    Path,
    PRSummaryFormat,
    ReportSection,
    Sequence,
    __version__,
    _as_int,
    _evaluate_report_gates,
    _json_text_payload,
    load_pyproject_config,
    paginate,
)


class _MCPSessionChangedProjectionMixin(_MCPSessionFindingMixin):
    _runs: CodeCloneMCPRunStore
    _state_lock: _StateLock
    _review_state: dict[str, OrderedDict[str, str | None]]
    _last_gate_results: dict[str, dict[str, object]]
    _spread_max_cache: dict[str, int]

    def _build_changed_projection(
        self,
        record: MCPRunRecord,
    ) -> dict[str, object] | None:
        if not record.changed_paths:
            return None
        items = self._query_findings(
            record=record,
            detail_level="summary",
            changed_paths=record.changed_paths,
        )
        new_count = sum(1 for item in items if str(item.get("novelty", "")) == "new")
        known_count = sum(
            1 for item in items if str(item.get("novelty", "")) == "known"
        )
        new_by_source_kind = _helpers._source_kind_breakdown(
            item.get("source_kind")
            for item in items
            if str(item.get("novelty", "")) == "new"
        )
        health_delta = _helpers._summary_health_delta(record.summary)
        return {
            "run_id": _helpers._short_run_id(record.run_id),
            "changed_paths": list(record.changed_paths),
            "total": len(items),
            "new": new_count,
            "known": known_count,
            "new_by_source_kind": new_by_source_kind,
            "items": items,
            "health": dict(_helpers._summary_health_payload(record.summary)),
            "health_delta": health_delta,
            "verdict": _helpers._changed_verdict(
                changed_projection={"new": new_count, "total": len(items)},
                health_delta=health_delta,
            ),
        }

    def _augment_summary_with_changed(
        self,
        *,
        summary: Mapping[str, object],
        changed_paths: Sequence[str],
        changed_projection: Mapping[str, object] | None,
    ) -> dict[str, object]:
        payload = dict(summary)
        if changed_paths:
            payload["changed_paths"] = list(changed_paths)
        if changed_projection is not None:
            payload["changed_findings"] = {
                "total": _as_int(changed_projection.get("total", 0), 0),
                "new": _as_int(changed_projection.get("new", 0), 0),
                "known": _as_int(changed_projection.get("known", 0), 0),
                "items": [
                    dict(_helpers._as_mapping(item))
                    for item in _helpers._as_sequence(changed_projection.get("items"))[
                        :10
                    ]
                ],
            }
            payload["health_delta"] = (
                _as_int(changed_projection.get("health_delta", 0), 0)
                if changed_projection.get("health_delta") is not None
                else None
            )
            payload["verdict"] = str(changed_projection.get("verdict", "stable"))
        return payload


class _MCPSessionAnalysisArgsMixin(_MCPSessionChangedProjectionMixin):
    _runs: CodeCloneMCPRunStore
    _state_lock: _StateLock
    _review_state: dict[str, OrderedDict[str, str | None]]
    _last_gate_results: dict[str, dict[str, object]]
    _spread_max_cache: dict[str, int]

    def _comparison_index(
        self,
        record: MCPRunRecord,
        *,
        focus: str,
    ) -> dict[str, dict[str, object]]:
        findings = self._base_findings(record)
        if focus == "clones":
            findings = [f for f in findings if str(f.get("family", "")) == "clone"]
        elif focus == "structural":
            findings = [f for f in findings if str(f.get("family", "")) == "structural"]
        elif focus == "metrics":
            findings = [
                f
                for f in findings
                if str(f.get("family", "")) in {"design", "dead_code"}
            ]
        return {str(finding.get("id", "")): dict(finding) for finding in findings}

    def _build_args(self, *, root_path: Path, request: MCPAnalysisRequest) -> Namespace:
        args = Namespace(
            root=str(root_path),
            min_loc=DEFAULT_MIN_LOC,
            min_stmt=DEFAULT_MIN_STMT,
            block_min_loc=DEFAULT_BLOCK_MIN_LOC,
            block_min_stmt=DEFAULT_BLOCK_MIN_STMT,
            segment_min_loc=DEFAULT_SEGMENT_MIN_LOC,
            segment_min_stmt=DEFAULT_SEGMENT_MIN_STMT,
            processes=None,
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
            fail_on_typing_regression=False,
            fail_on_docstring_regression=False,
            fail_on_api_break=False,
            min_typing_coverage=-1,
            min_docstring_coverage=-1,
            api_surface=False,
            coverage_xml=None,
            fail_on_untested_hotspots=False,
            coverage_min=DEFAULT_COVERAGE_MIN,
            design_complexity_threshold=DEFAULT_REPORT_DESIGN_COMPLEXITY_THRESHOLD,
            design_coupling_threshold=DEFAULT_REPORT_DESIGN_COUPLING_THRESHOLD,
            design_cohesion_threshold=DEFAULT_REPORT_DESIGN_COHESION_THRESHOLD,
            update_metrics_baseline=False,
            metrics_baseline=DEFAULT_BASELINE_PATH,
            skip_metrics=False,
            skip_dead_code=False,
            skip_dependencies=False,
            golden_fixture_paths=(),
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
                "must be >= -1. Coverage thresholds must be between 0 and 100."
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
            "api_surface": request.api_surface,
            "coverage_min": request.coverage_min,
            "max_baseline_size_mb": request.max_baseline_size_mb,
            "max_cache_size_mb": request.max_cache_size_mb,
            "design_complexity_threshold": request.complexity_threshold,
            "design_coupling_threshold": request.coupling_threshold,
            "design_cohesion_threshold": request.cohesion_threshold,
        }
        for key, value in override_map.items():
            if value is not None:
                setattr(args, key, value)

        if request.baseline_path is not None:
            args.baseline = str(
                _helpers._resolve_optional_path(request.baseline_path, root_path)
            )
        if request.metrics_baseline_path is not None:
            args.metrics_baseline = str(
                _helpers._resolve_optional_path(
                    request.metrics_baseline_path,
                    root_path,
                )
            )
        if request.cache_path is not None:
            args.cache_path = str(
                _helpers._resolve_optional_path(request.cache_path, root_path)
            )
        if request.coverage_xml is not None:
            args.coverage_xml = str(
                _helpers._resolve_optional_path(request.coverage_xml, root_path)
            )

    def _resolve_baseline_inputs(
        self,
        *,
        root_path: Path,
        args: Namespace,
    ) -> tuple[Path, bool, Path, bool, dict[str, object] | None]:
        baseline_path = _helpers._resolve_optional_path(str(args.baseline), root_path)
        baseline_exists = baseline_path.exists()

        metrics_baseline_arg_path = _helpers._resolve_optional_path(
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


class _MCPSessionRunSummaryBuilderMixin(_MCPSessionAnalysisArgsMixin):
    _runs: CodeCloneMCPRunStore
    _state_lock: _StateLock
    _review_state: dict[str, OrderedDict[str, str | None]]
    _last_gate_results: dict[str, dict[str, object]]
    _spread_max_cache: dict[str, int]

    def _changed_analysis_payload(
        self,
        record: MCPRunRecord,
    ) -> dict[str, object]:
        changed_projection = _helpers._as_mapping(record.changed_projection)
        health = _helpers._summary_health_payload(record.summary)
        health_payload = (
            {
                "score": health.get("score"),
                "grade": health.get("grade"),
            }
            if health.get("available") is not False
            else dict(health)
        )
        return {
            "run_id": _helpers._short_run_id(record.run_id),
            "focus": "changed_paths",
            "health_scope": "repository",
            "baseline": dict(
                _helpers._summary_trusted_state_payload(
                    record.summary,
                    key="baseline",
                )
            ),
            "changed_files": len(record.changed_paths),
            "health": health_payload,
            "analysis_profile": _helpers._summary_analysis_profile_payload(
                record.summary
            ),
            "health_delta": (
                _as_int(changed_projection.get("health_delta", 0), 0)
                if changed_projection.get("health_delta") is not None
                else None
            ),
            "verdict": str(changed_projection.get("verdict", "stable")),
            "new_findings": _as_int(changed_projection.get("new", 0), 0),
            "new_by_source_kind": dict(
                _helpers._as_mapping(changed_projection.get("new_by_source_kind"))
            ),
            "resolved_findings": 0,
            "changed_findings": [],
            "coverage_join": _helpers._summary_coverage_join_payload(record),
        }

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
        meta = _helpers._as_mapping(report_document.get("meta"))
        meta_baseline = _helpers._as_mapping(meta.get("baseline"))
        meta_metrics_baseline = _helpers._as_mapping(meta.get("metrics_baseline"))
        meta_cache = _helpers._as_mapping(meta.get("cache"))
        inventory = _helpers._as_mapping(report_document.get("inventory"))
        findings = _helpers._as_mapping(report_document.get("findings"))
        metrics = _helpers._as_mapping(report_document.get("metrics"))
        metrics_summary = _helpers._as_mapping(metrics.get("summary"))
        summary = _helpers._as_mapping(findings.get("summary"))
        analysis_profile = _helpers._summary_analysis_profile_payload(meta)
        payload = {
            "run_id": run_id,
            "root": str(root_path),
            "analysis_mode": request.analysis_mode,
            "codeclone_version": meta.get("codeclone_version", __version__),
            "python_tag": str(meta.get("python_tag", "")),
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
                "python_tag": meta_baseline.get("python_tag"),
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
            "health": dict(_helpers._as_mapping(metrics_summary.get("health"))),
            "baseline_diff": {
                "new_function_clone_groups": len(new_func),
                "new_block_clone_groups": len(new_block),
                "new_clone_groups_total": len(new_func) + len(new_block),
            },
            "metrics_diff": _helpers._metrics_diff_payload(metrics_diff),
            "warnings": list(warnings),
            "failures": list(failures),
        }
        if analysis_profile:
            payload["analysis_profile"] = analysis_profile
        payload["cache"] = _helpers._summary_cache_payload(payload)
        payload["health"] = _helpers._summary_health_payload(payload)
        return payload


class _MCPSessionSummaryMixin(_MCPSessionRunSummaryBuilderMixin):
    _runs: CodeCloneMCPRunStore
    _state_lock: _StateLock
    _review_state: dict[str, OrderedDict[str, str | None]]
    _last_gate_results: dict[str, dict[str, object]]
    _spread_max_cache: dict[str, int]

    def _summary_payload(
        self,
        summary: Mapping[str, object],
        *,
        record: MCPRunRecord | None = None,
    ) -> dict[str, object]:
        inventory = _helpers._as_mapping(summary.get("inventory"))
        if (
            not summary.get("run_id")
            and not record
            and "inventory" in summary
            and not summary.get("baseline")
        ):
            return {
                "focus": _FOCUS_REPOSITORY,
                "health_scope": _HEALTH_SCOPE_REPOSITORY,
                "inventory": _helpers._summary_inventory_payload(inventory),
                "health": _helpers._summary_health_payload(summary),
            }
        resolved_run_id = (
            record.run_id if record is not None else str(summary.get("run_id", ""))
        )
        payload: dict[str, object] = {
            "run_id": (
                _helpers._short_run_id(resolved_run_id) if resolved_run_id else ""
            ),
            "focus": _FOCUS_REPOSITORY,
            "health_scope": _HEALTH_SCOPE_REPOSITORY,
            "version": str(summary.get("codeclone_version", __version__)),
            "schema": str(summary.get("report_schema_version", "")),
            "mode": str(summary.get("analysis_mode", "")),
            "baseline": self._summary_baseline_payload(summary),
            "metrics_baseline": self._summary_metrics_baseline_payload(summary),
            "cache": _helpers._summary_cache_payload(summary),
            "inventory": _helpers._summary_inventory_payload(inventory),
            "health": _helpers._summary_health_payload(summary),
            "findings": self._summary_findings_payload(summary, record=record),
            "diff": _helpers._summary_diff_payload(summary),
            "warnings": list(_helpers._as_sequence(summary.get("warnings"))),
            "failures": list(_helpers._as_sequence(summary.get("failures"))),
        }
        analysis_profile = _helpers._summary_analysis_profile_payload(summary)
        if analysis_profile:
            payload["analysis_profile"] = analysis_profile
        if record is not None:
            coverage_join = _helpers._summary_coverage_join_payload(record)
            if coverage_join:
                payload["coverage_join"] = coverage_join
        return payload

    def _summary_baseline_payload(
        self,
        summary: Mapping[str, object],
    ) -> dict[str, object]:
        return _helpers._summary_trusted_state_payload(summary, key="baseline")

    def _summary_metrics_baseline_payload(
        self,
        summary: Mapping[str, object],
    ) -> dict[str, object]:
        return _helpers._summary_trusted_state_payload(summary, key="metrics_baseline")

    def _summary_findings_payload(
        self,
        summary: Mapping[str, object],
        *,
        record: MCPRunRecord | None,
    ) -> dict[str, object]:
        findings_summary = _helpers._as_mapping(summary.get("findings_summary"))
        if record is None:
            return {
                "total": _as_int(findings_summary.get("total", 0), 0),
                "new": 0,
                "known": 0,
                "by_family": {},
                "production": 0,
                "new_by_source_kind": _helpers._source_kind_breakdown(()),
            }
        findings = self._base_findings(record)
        by_family: dict[str, int] = {
            "clones": 0,
            "structural": 0,
            "dead_code": 0,
            "design": 0,
        }
        new_count = 0
        known_count = 0
        production_count = 0
        new_by_source_kind = _helpers._source_kind_breakdown(
            _helpers._finding_source_kind(finding)
            for finding in findings
            if str(finding.get("novelty", "")).strip() == "new"
        )
        for finding in findings:
            family = str(finding.get("family", "")).strip()
            family_key = "clones" if family == FAMILY_CLONE else family
            if family_key in by_family:
                by_family[family_key] += 1
            if str(finding.get("novelty", "")).strip() == "new":
                new_count += 1
            else:
                known_count += 1
            if _helpers._finding_source_kind(finding) == SOURCE_KIND_PRODUCTION:
                production_count += 1
        return {
            "total": len(findings),
            "new": new_count,
            "known": known_count,
            "by_family": {key: value for key, value in by_family.items() if value > 0},
            "production": production_count,
            "new_by_source_kind": new_by_source_kind,
        }

    def _metrics_detail_payload(
        self,
        *,
        metrics: Mapping[str, object],
        family: MetricsDetailFamily | None,
        path: str | None,
        offset: int,
        limit: int,
    ) -> dict[str, object]:
        summary = dict(_helpers._as_mapping(metrics.get("summary")))
        families = _helpers._as_mapping(metrics.get("families"))
        normalized_path = _helpers._normalize_relative_path(path or "")
        if family is None and not normalized_path:
            return {
                "summary": summary,
                "_hint": "Use family and/or path parameters to access per-item detail.",
            }
        family_names = (family,) if family is not None else tuple(sorted(families))
        items: list[dict[str, object]] = []
        for family_name in family_names:
            family_payload = _helpers._as_mapping(families.get(family_name))
            for item in _helpers._as_sequence(family_payload.get("items")):
                item_map = _helpers._as_mapping(item)
                if normalized_path and not _helpers._metric_item_matches_path(
                    item_map,
                    normalized_path,
                ):
                    continue
                compact_item = _helpers._compact_metrics_item(item_map)
                if family is None:
                    compact_item = {"family": family_name, **compact_item}
                items.append(compact_item)
        if family is None:
            items.sort(
                key=lambda item: (
                    str(item.get("family", "")),
                    str(item.get("path", "")),
                    str(item.get("qualname", "")),
                    _as_int(item.get("start_line", 0), 0),
                )
            )
        page = paginate(items, offset=offset, limit=limit, max_limit=200)
        return {
            "family": family,
            "path": normalized_path or None,
            "offset": page.offset,
            "limit": page.limit,
            "returned": len(page.items),
            "total": page.total,
            "has_more": page.next_offset is not None,
            "items": page.items,
        }

    def _derived_section_payload(self, record: MCPRunRecord) -> dict[str, object]:
        derived = _helpers._as_mapping(record.report_document.get("derived"))
        if not derived:
            raise MCPServiceContractError(
                "Report section 'derived' is not available in this run."
            )
        suggestions = self._triage_suggestion_rows(record)
        canonical_to_short, _ = self._finding_id_maps(record)
        hotlists = _helpers._as_mapping(derived.get("hotlists"))
        projected_hotlists: dict[str, list[str]] = {}
        for hotlist_key, hotlist_ids in hotlists.items():
            projected_hotlists[hotlist_key] = [
                canonical_to_short.get(
                    str(finding_id),
                    _helpers._base_short_finding_id(str(finding_id)),
                )
                for finding_id in _helpers._as_sequence(hotlist_ids)
                if str(finding_id)
            ]
        return {
            "suggestions": suggestions,
            "hotlists": projected_hotlists,
        }


class _MCPSessionReportMixin(_MCPSessionSummaryMixin):
    _runs: CodeCloneMCPRunStore
    _state_lock: _StateLock
    _review_state: dict[str, OrderedDict[str, str | None]]
    _last_gate_results: dict[str, dict[str, object]]
    _spread_max_cache: dict[str, int]

    def get_run_summary(self, run_id: str | None = None) -> dict[str, object]:
        record = self._runs.get(run_id)
        return self._summary_payload(record.summary, record=record)

    def compare_runs(
        self,
        *,
        run_id_before: str,
        run_id_after: str | None = None,
        focus: ComparisonFocus = "all",
    ) -> dict[str, object]:
        validated_focus = _helpers._validate_choice(
            "focus",
            focus,
            _VALID_COMPARISON_FOCUS,
        )
        before = self._runs.get(run_id_before)
        after = self._runs.get(run_id_after)
        before_findings = self._comparison_index(before, focus=validated_focus)
        after_findings = self._comparison_index(after, focus=validated_focus)
        before_ids = set(before_findings)
        after_ids = set(after_findings)
        regressions = sorted(after_ids - before_ids)
        improvements = sorted(before_ids - after_ids)
        common = before_ids & after_ids
        health_before = _helpers._summary_health_score(before.summary)
        health_after = _helpers._summary_health_score(after.summary)
        comparability = _helpers._comparison_scope(before=before, after=after)
        comparable = bool(comparability["comparable"])
        health_delta = (
            health_after - health_before
            if comparable and health_before is not None and health_after is not None
            else None
        )
        verdict = (
            _helpers._comparison_verdict(
                regressions=len(regressions),
                improvements=len(improvements),
                health_delta=health_delta,
            )
            if comparable
            else "incomparable"
        )
        regressions_payload = (
            [
                self._comparison_finding_card(
                    after,
                    after_findings[finding_id],
                )
                for finding_id in regressions
            ]
            if comparable
            else []
        )
        improvements_payload = (
            [
                self._comparison_finding_card(
                    before,
                    before_findings[finding_id],
                )
                for finding_id in improvements
            ]
            if comparable
            else []
        )
        payload: dict[str, object] = {
            "before": {
                "run_id": _helpers._short_run_id(before.run_id),
                "health": health_before,
            },
            "after": {
                "run_id": _helpers._short_run_id(after.run_id),
                "health": health_after,
            },
            "comparable": comparable,
            "health_delta": health_delta,
            "verdict": verdict,
            "regressions": regressions_payload,
            "improvements": improvements_payload,
            "unchanged": len(common) if comparable else None,
            "summary": _helpers._comparison_summary_text(
                comparable=comparable,
                comparability_reason=str(comparability["reason"]),
                regressions=len(regressions),
                improvements=len(improvements),
                health_delta=health_delta,
            ),
        }
        if not comparable:
            payload["reason"] = comparability["reason"]
        return payload


class _MCPSessionStateMixin(_MCPSessionReportMixin):
    _runs: CodeCloneMCPRunStore
    _state_lock: _StateLock
    _review_state: dict[str, OrderedDict[str, str | None]]
    _last_gate_results: dict[str, dict[str, object]]
    _spread_max_cache: dict[str, int]

    def evaluate_gates(self, request: MCPGateRequest) -> dict[str, object]:
        record = self._runs.get(request.run_id)
        gate_result = self._evaluate_gate_snapshot(record=record, request=request)
        result = {
            "run_id": _helpers._short_run_id(record.run_id),
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
                "fail_on_typing_regression": request.fail_on_typing_regression,
                "fail_on_docstring_regression": request.fail_on_docstring_regression,
                "fail_on_api_break": request.fail_on_api_break,
                "fail_on_untested_hotspots": request.fail_on_untested_hotspots,
                "min_typing_coverage": request.min_typing_coverage,
                "min_docstring_coverage": request.min_docstring_coverage,
                "coverage_min": request.coverage_min,
            },
        }
        with self._state_lock:
            self._last_gate_results[record.run_id] = dict(result)
        return result

    def _evaluate_gate_snapshot(
        self,
        *,
        record: MCPRunRecord,
        request: MCPGateRequest,
    ) -> GatingResult:
        if request.fail_on_untested_hotspots:
            if record.coverage_join is None:
                raise MCPServiceContractError(
                    "Coverage gating requires a run created with coverage_xml."
                )
            if record.coverage_join.status != "ok":
                detail = record.coverage_join.invalid_reason or "invalid coverage input"
                raise MCPServiceContractError(
                    "Coverage gating requires a valid Cobertura XML input. "
                    f"Reason: {detail}"
                )
        return _evaluate_report_gates(
            report_document=record.report_document,
            config=MetricGateConfig(
                fail_complexity=request.fail_complexity,
                fail_coupling=request.fail_coupling,
                fail_cohesion=request.fail_cohesion,
                fail_cycles=request.fail_cycles,
                fail_dead_code=request.fail_dead_code,
                fail_health=request.fail_health,
                fail_on_new_metrics=request.fail_on_new_metrics,
                fail_on_typing_regression=request.fail_on_typing_regression,
                fail_on_docstring_regression=request.fail_on_docstring_regression,
                fail_on_api_break=request.fail_on_api_break,
                fail_on_untested_hotspots=request.fail_on_untested_hotspots,
                min_typing_coverage=request.min_typing_coverage,
                min_docstring_coverage=request.min_docstring_coverage,
                coverage_min=request.coverage_min,
                fail_on_new=request.fail_on_new,
                fail_threshold=request.fail_threshold,
            ),
            baseline_status=str(
                _helpers._as_mapping(
                    _helpers._as_mapping(record.report_document.get("meta")).get(
                        "baseline"
                    )
                ).get("status", "")
            ),
            metrics_diff=record.metrics_diff,
            clone_new_count=len(record.new_func) + len(record.new_block),
            clone_total=record.func_clones_count + record.block_clones_count,
        )

    def get_report_section(
        self,
        *,
        run_id: str | None = None,
        section: ReportSection = "all",
        family: MetricsDetailFamily | None = None,
        path: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, object]:
        validated_section = _helpers._validate_choice(
            "section",
            section,
            _VALID_REPORT_SECTIONS,
        )
        record = self._runs.get(run_id)
        report_document = record.report_document
        if validated_section == "all":
            return dict(report_document)
        if validated_section == "changed":
            if record.changed_projection is None:
                raise MCPServiceContractError(
                    "Report section 'changed' is not available in this run."
                )
            return dict(record.changed_projection)
        if validated_section == "metrics":
            metrics = _helpers._as_mapping(report_document.get("metrics"))
            return {"summary": dict(_helpers._as_mapping(metrics.get("summary")))}
        if validated_section == "metrics_detail":
            metrics = _helpers._as_mapping(report_document.get("metrics"))
            if not metrics:
                raise MCPServiceContractError(
                    "Report section 'metrics_detail' is not available in this run."
                )
            validated_family_input = _helpers._validate_optional_choice(
                "family",
                family,
                _VALID_METRICS_DETAIL_FAMILIES,
            )
            normalized_family = (
                _METRICS_DETAIL_FAMILY_ALIASES.get(
                    str(validated_family_input),
                    str(validated_family_input),
                )
                if validated_family_input is not None
                else None
            )
            validated_family = _helpers._metrics_detail_family(normalized_family)
            return self._metrics_detail_payload(
                metrics=metrics,
                family=validated_family,
                path=path,
                offset=offset,
                limit=limit,
            )
        if validated_section == "derived":
            return self._derived_section_payload(record)
        payload = report_document.get(validated_section)
        if not isinstance(payload, Mapping):
            raise MCPServiceContractError(
                f"Report section '{validated_section}' is not available in this run."
            )
        return dict(payload)

    def get_production_triage(
        self,
        *,
        run_id: str | None = None,
        max_hotspots: int = 3,
        max_suggestions: int = 3,
    ) -> dict[str, object]:
        record = self._runs.get(run_id)
        summary = self._summary_payload(record.summary, record=record)
        findings = self._base_findings(record)
        findings_breakdown = _helpers._source_kind_breakdown(
            _helpers._finding_source_kind(finding) for finding in findings
        )
        suggestion_rows = self._triage_suggestion_rows(record)
        suggestion_breakdown = _helpers._source_kind_breakdown(
            row.get("source_kind") for row in suggestion_rows
        )
        hotspot_limit = max(1, min(max_hotspots, 10))
        suggestion_limit = max(1, min(max_suggestions, 10))
        production_hotspots = self._hotspot_rows(
            record=record,
            kind="production_hotspots",
            detail_level="summary",
            changed_paths=(),
            exclude_reviewed=False,
        )
        production_suggestions = [
            dict(row)
            for row in suggestion_rows
            if str(row.get("source_kind", "")) == SOURCE_KIND_PRODUCTION
        ]
        payload: dict[str, object] = {
            "run_id": _helpers._short_run_id(record.run_id),
            "focus": _FOCUS_PRODUCTION,
            "health_scope": _HEALTH_SCOPE_REPOSITORY,
            "baseline": dict(_helpers._as_mapping(summary.get("baseline"))),
            "health": dict(_helpers._summary_health_payload(summary)),
            "cache": dict(_helpers._as_mapping(summary.get("cache"))),
            "findings": {
                "total": len(findings),
                "by_source_kind": findings_breakdown,
                "new_by_source_kind": dict(
                    _helpers._as_mapping(
                        _helpers._as_mapping(summary.get("findings")).get(
                            "new_by_source_kind"
                        )
                    )
                ),
                "outside_focus": len(findings)
                - findings_breakdown[SOURCE_KIND_PRODUCTION],
            },
            "top_hotspots": {
                "kind": "production_hotspots",
                "available": len(production_hotspots),
                "returned": min(len(production_hotspots), hotspot_limit),
                "items": [
                    dict(_helpers._as_mapping(item))
                    for item in production_hotspots[:hotspot_limit]
                ],
            },
            "suggestions": {
                "total": len(suggestion_rows),
                "by_source_kind": suggestion_breakdown,
                "outside_focus": len(suggestion_rows)
                - suggestion_breakdown[SOURCE_KIND_PRODUCTION],
            },
            "top_suggestions": {
                "available": len(production_suggestions),
                "returned": min(len(production_suggestions), suggestion_limit),
                "items": production_suggestions[:suggestion_limit],
            },
        }
        analysis_profile = _helpers._summary_analysis_profile_payload(summary)
        if analysis_profile:
            payload["analysis_profile"] = analysis_profile
        coverage_join = _helpers._summary_coverage_join_payload(record)
        if coverage_join:
            payload["coverage_join"] = coverage_join
        return payload

    def get_help(
        self,
        *,
        topic: HelpTopic,
        detail: HelpDetail = "compact",
    ) -> dict[str, object]:
        validated_topic = _helpers._validate_choice("topic", topic, _VALID_HELP_TOPICS)
        validated_detail = _helpers._validate_choice(
            "detail",
            detail,
            _VALID_HELP_DETAILS,
        )
        spec = _HELP_TOPIC_SPECS[validated_topic]
        payload: dict[str, object] = {
            "topic": validated_topic,
            "detail": validated_detail,
            "summary": spec.summary,
            "key_points": list(spec.key_points),
            "recommended_tools": list(spec.recommended_tools),
            "doc_links": [
                {"title": title, "url": url} for title, url in spec.doc_links
            ],
        }
        if validated_detail == "normal":
            if spec.warnings:
                payload["warnings"] = list(spec.warnings)
            if spec.anti_patterns:
                payload["anti_patterns"] = list(spec.anti_patterns)
        return payload

    def generate_pr_summary(
        self,
        *,
        run_id: str | None = None,
        changed_paths: tuple[str, ...] = (),
        git_diff_ref: str | None = None,
        format: PRSummaryFormat = "markdown",
    ) -> dict[str, object]:
        output_format = _helpers._validate_choice(
            "format",
            format,
            _VALID_PR_SUMMARY_FORMATS,
        )
        record = self._runs.get(run_id)
        paths_filter = self._resolve_query_changed_paths(
            record=record,
            changed_paths=changed_paths,
            git_diff_ref=git_diff_ref,
            prefer_record_paths=True,
        )
        changed_items = self._query_findings(
            record=record,
            detail_level="summary",
            changed_paths=paths_filter,
        )
        previous = self._previous_run_for_root(record)
        resolved: list[dict[str, object]] = []
        if previous is not None:
            compare_payload = self.compare_runs(
                run_id_before=previous.run_id,
                run_id_after=record.run_id,
                focus="all",
            )
            resolved = _helpers._dict_rows(compare_payload.get("improvements"))
        with self._state_lock:
            gate_result = dict(
                self._last_gate_results.get(
                    record.run_id,
                    {"would_fail": False, "reasons": []},
                )
            )
        verdict = _helpers._changed_verdict(
            changed_projection={
                "total": len(changed_items),
                "new": sum(
                    1 for item in changed_items if str(item.get("novelty", "")) == "new"
                ),
            },
            health_delta=_helpers._summary_health_delta(record.summary),
        )
        payload: dict[str, object] = {
            "run_id": _helpers._short_run_id(record.run_id),
            "changed_files": len(paths_filter),
            "health": _helpers._summary_health_payload(record.summary),
            "health_delta": _helpers._summary_health_delta(record.summary),
            "verdict": verdict,
            "new_findings_in_changed_files": changed_items,
            "resolved": resolved,
            "blocking_gates": _helpers._string_rows(gate_result.get("reasons")),
        }
        if output_format == "json":
            return payload
        return {
            "run_id": _helpers._short_run_id(record.run_id),
            "format": output_format,
            "content": _helpers._render_pr_summary_markdown(payload),
        }

    def clear_session_runs(self) -> dict[str, object]:
        removed_run_ids = self._runs.clear()
        with self._state_lock:
            cleared_review_entries = sum(
                len(entries) for entries in self._review_state.values()
            )
            cleared_gate_results = len(self._last_gate_results)
            cleared_spread_cache_entries = len(self._spread_max_cache)
            self._review_state.clear()
            self._last_gate_results.clear()
            self._spread_max_cache.clear()
        return {
            "cleared_runs": len(removed_run_ids),
            "cleared_run_ids": [
                _helpers._short_run_id(run_id) for run_id in removed_run_ids
            ],
            "cleared_review_entries": cleared_review_entries,
            "cleared_gate_results": cleared_gate_results,
            "cleared_spread_cache_entries": cleared_spread_cache_entries,
        }

    def read_resource(self, uri: str) -> str:
        if uri == "codeclone://schema":
            return _json_text_payload(_helpers._schema_resource_payload())
        if uri == "codeclone://latest/triage":
            latest = self._runs.get()
            return _json_text_payload(self.get_production_triage(run_id=latest.run_id))
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
            return _json_text_payload(
                self._summary_payload(record.summary, record=record)
            )
        if suffix == "triage":
            raise MCPServiceContractError(
                "Production triage is exposed only as codeclone://latest/triage."
            )
        if suffix == "health":
            return _json_text_payload(_helpers._summary_health_payload(record.summary))
        if suffix == "gates":
            with self._state_lock:
                gate_result = self._last_gate_results.get(record.run_id)
            if gate_result is None:
                raise MCPServiceContractError(
                    "No gate evaluation result is available in this MCP session."
                )
            return _json_text_payload(gate_result)
        if suffix == "changed":
            if record.changed_projection is None:
                raise MCPServiceContractError(
                    "Changed-findings projection is not available in this run."
                )
            return _json_text_payload(record.changed_projection)
        if suffix == "schema":
            return _json_text_payload(_helpers._schema_resource_payload())
        if suffix == "report.json":
            return _json_text_payload(record.report_document, sort_keys=False)
        if suffix == "overview":
            return _json_text_payload(
                self.list_hotspots(kind="highest_spread", run_id=record.run_id)
            )
        finding_prefix = "findings/"
        if suffix.startswith(finding_prefix):
            finding_id = suffix[len(finding_prefix) :]
            return _json_text_payload(
                self._service_get_finding(
                    run_id=record.run_id,
                    finding_id=finding_id,
                )
            )
        raise MCPServiceContractError(
            f"Unsupported CodeClone resource suffix '{suffix}'."
        )

    def _prune_session_state(self) -> None:
        active_run_ids = {record.run_id for record in self._runs.records()}
        with self._state_lock:
            for state_map in (
                self._review_state,
                self._last_gate_results,
                self._spread_max_cache,
            ):
                stale_run_ids = [
                    run_id for run_id in state_map if run_id not in active_run_ids
                ]
                for run_id in stale_run_ids:
                    state_map.pop(run_id, None)
