# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
import subprocess
from argparse import Namespace
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Final, Literal, cast

from . import __version__, _coerce
from ._cli_args import (
    DEFAULT_BASELINE_PATH,
    DEFAULT_BLOCK_MIN_LOC,
    DEFAULT_BLOCK_MIN_STMT,
    DEFAULT_MAX_BASELINE_SIZE_MB,
    DEFAULT_MAX_CACHE_SIZE_MB,
    DEFAULT_MIN_LOC,
    DEFAULT_MIN_STMT,
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
from .cache import Cache, CacheStatus
from .contracts import (
    DEFAULT_COHESION_THRESHOLD,
    DEFAULT_COMPLEXITY_THRESHOLD,
    DEFAULT_COUPLING_THRESHOLD,
    REPORT_SCHEMA_VERSION,
    ExitCode,
)
from .domain.findings import (
    CATEGORY_CLONE,
    CATEGORY_COHESION,
    CATEGORY_COMPLEXITY,
    CATEGORY_COUPLING,
    CATEGORY_DEAD_CODE,
    CATEGORY_DEPENDENCY,
    CATEGORY_STRUCTURAL,
    CLONE_KIND_SEGMENT,
    FAMILY_CLONE,
    FAMILY_CLONES,
    FAMILY_DEAD_CODE,
    FAMILY_DESIGN,
    FAMILY_STRUCTURAL,
)
from .domain.quality import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    EFFORT_EASY,
    EFFORT_HARD,
    EFFORT_MODERATE,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_WARNING,
)
from .models import MetricsDiff, ProjectMetrics, Suggestion
from .pipeline import (
    GatingResult,
    MetricGateConfig,
    OutputPaths,
    analyze,
    bootstrap,
    discover,
    metric_gate_reasons,
    process,
    report,
)
from .report.json_contract import (
    _source_scope_from_filepaths,
    clone_group_id,
    dead_code_group_id,
    design_group_id,
    structural_group_id,
)
from .report.overview import serialize_finding_group_card

AnalysisMode = Literal["full", "clones_only"]
CachePolicy = Literal["reuse", "refresh", "off"]
HotlistKind = Literal[
    "most_actionable",
    "highest_spread",
    "highest_priority",
    "production_hotspots",
    "test_fixture_hotspots",
]
FindingFamilyFilter = Literal["all", "clone", "structural", "dead_code", "design"]
FindingNoveltyFilter = Literal["all", "new", "known"]
FindingSort = Literal["default", "priority", "severity", "spread"]
DetailLevel = Literal["summary", "normal", "full"]
ComparisonFocus = Literal["all", "clones", "structural", "metrics"]
PRSummaryFormat = Literal["markdown", "json"]
ReportSection = Literal[
    "all",
    "meta",
    "inventory",
    "findings",
    "metrics",
    "derived",
    "changed",
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
_RESOURCE_SECTION_MAP: Final[dict[str, ReportSection]] = {
    "report.json": "all",
    "summary": "meta",
    "health": "metrics",
    "changed": "changed",
    "overview": "derived",
}
_SEVERITY_WEIGHT: Final[dict[str, float]] = {
    SEVERITY_CRITICAL: 1.0,
    SEVERITY_WARNING: 0.6,
    SEVERITY_INFO: 0.2,
}
_EFFORT_WEIGHT: Final[dict[str, float]] = {
    EFFORT_EASY: 1.0,
    EFFORT_MODERATE: 0.6,
    EFFORT_HARD: 0.3,
}
_NOVELTY_WEIGHT: Final[dict[str, float]] = {"new": 1.0, "known": 0.5}
_RUNTIME_WEIGHT: Final[dict[str, float]] = {
    "production": 1.0,
    "mixed": 0.8,
    "tests": 0.4,
    "fixtures": 0.2,
    "other": 0.5,
}
_CONFIDENCE_WEIGHT: Final[dict[str, float]] = {
    CONFIDENCE_HIGH: 1.0,
    CONFIDENCE_MEDIUM: 0.7,
    CONFIDENCE_LOW: 0.3,
}
# Canonical report groups use FAMILY_CLONES ("clones"), while individual finding
# payloads use FAMILY_CLONE ("clone").
_VALID_ANALYSIS_MODES = frozenset({"full", "clones_only"})
_VALID_CACHE_POLICIES = frozenset({"reuse", "refresh", "off"})
_VALID_FINDING_FAMILIES = frozenset(
    {"all", "clone", "structural", "dead_code", "design"}
)
_VALID_FINDING_NOVELTY = frozenset({"all", "new", "known"})
_VALID_FINDING_SORT = frozenset({"default", "priority", "severity", "spread"})
_VALID_DETAIL_LEVELS = frozenset({"summary", "normal", "full"})
_VALID_COMPARISON_FOCUS = frozenset({"all", "clones", "structural", "metrics"})
_VALID_PR_SUMMARY_FORMATS = frozenset({"markdown", "json"})
DEFAULT_MCP_HISTORY_LIMIT = 4
MAX_MCP_HISTORY_LIMIT = 10
_VALID_REPORT_SECTIONS = frozenset(
    {
        "all",
        "meta",
        "inventory",
        "findings",
        "metrics",
        "derived",
        "changed",
        "integrity",
    }
)
_VALID_HOTLIST_KINDS = frozenset(
    {
        "most_actionable",
        "highest_spread",
        "highest_priority",
        "production_hotspots",
        "test_fixture_hotspots",
    }
)
_VALID_SEVERITIES = frozenset({SEVERITY_CRITICAL, SEVERITY_WARNING, SEVERITY_INFO})
_as_int = _coerce.as_int
_as_float = _coerce.as_float
_as_str = _coerce.as_str


def _design_singleton_group_payload(
    *,
    category: str,
    kind: str,
    severity: str,
    qualname: str,
    filepath: str,
    start_line: int,
    end_line: int,
    item_data: Mapping[str, object],
    facts: Mapping[str, object],
    scan_root: str,
) -> dict[str, object]:
    relative_path = filepath
    return {
        "id": design_group_id(category, qualname),
        "family": FAMILY_DESIGN,
        "category": category,
        "kind": kind,
        "severity": severity,
        "confidence": CONFIDENCE_HIGH,
        "priority": 2.0 if severity == SEVERITY_WARNING else 3.0,
        "count": 1,
        "source_scope": _source_scope_from_filepaths(
            (relative_path,),
            scan_root=scan_root,
        ),
        "spread": {"files": 1, "functions": 1},
        "items": [
            {
                "relative_path": relative_path,
                "qualname": qualname,
                "start_line": start_line,
                "end_line": end_line,
                **item_data,
            }
        ],
        "facts": dict(facts),
    }


def _complexity_group_for_threshold_payload(
    item_map: Mapping[str, object],
    *,
    threshold: int,
    scan_root: str,
) -> dict[str, object] | None:
    cc = _as_int(item_map.get("cyclomatic_complexity", 1), 1)
    if cc <= threshold:
        return None
    severity = SEVERITY_CRITICAL if cc > max(40, threshold * 2) else SEVERITY_WARNING
    return _design_singleton_group_payload(
        category=CATEGORY_COMPLEXITY,
        kind="function_hotspot",
        severity=severity,
        qualname=str(item_map.get("qualname", "")),
        filepath=str(item_map.get("relative_path", "")),
        start_line=_as_int(item_map.get("start_line", 0), 0),
        end_line=_as_int(item_map.get("end_line", 0), 0),
        scan_root=scan_root,
        item_data={
            "cyclomatic_complexity": cc,
            "nesting_depth": _as_int(item_map.get("nesting_depth", 0), 0),
            "risk": str(item_map.get("risk", "")),
        },
        facts={
            "cyclomatic_complexity": cc,
            "nesting_depth": _as_int(item_map.get("nesting_depth", 0), 0),
        },
    )


def _coupling_group_for_threshold_payload(
    item_map: Mapping[str, object],
    *,
    threshold: int,
    scan_root: str,
) -> dict[str, object] | None:
    cbo = _as_int(item_map.get("cbo", 0), 0)
    if cbo <= threshold:
        return None
    coupled_classes = list(_coerce.as_sequence(item_map.get("coupled_classes")))
    return _design_singleton_group_payload(
        category=CATEGORY_COUPLING,
        kind="class_hotspot",
        severity=SEVERITY_WARNING,
        qualname=str(item_map.get("qualname", "")),
        filepath=str(item_map.get("relative_path", "")),
        start_line=_as_int(item_map.get("start_line", 0), 0),
        end_line=_as_int(item_map.get("end_line", 0), 0),
        scan_root=scan_root,
        item_data={
            "cbo": cbo,
            "risk": str(item_map.get("risk", "")),
            "coupled_classes": coupled_classes,
        },
        facts={
            "cbo": cbo,
            "coupled_classes": coupled_classes,
        },
    )


def _cohesion_group_for_threshold_payload(
    item_map: Mapping[str, object],
    *,
    threshold: int,
    scan_root: str,
) -> dict[str, object] | None:
    lcom4 = _as_int(item_map.get("lcom4", 0), 0)
    if lcom4 <= threshold:
        return None
    return _design_singleton_group_payload(
        category=CATEGORY_COHESION,
        kind="class_hotspot",
        severity=SEVERITY_WARNING,
        qualname=str(item_map.get("qualname", "")),
        filepath=str(item_map.get("relative_path", "")),
        start_line=_as_int(item_map.get("start_line", 0), 0),
        end_line=_as_int(item_map.get("end_line", 0), 0),
        scan_root=scan_root,
        item_data={
            "lcom4": lcom4,
            "risk": str(item_map.get("risk", "")),
            "method_count": _as_int(item_map.get("method_count", 0), 0),
            "instance_var_count": _as_int(item_map.get("instance_var_count", 0), 0),
        },
        facts={
            "lcom4": lcom4,
            "method_count": _as_int(item_map.get("method_count", 0), 0),
            "instance_var_count": _as_int(item_map.get("instance_var_count", 0), 0),
        },
    )


def _suggestion_finding_id_payload(suggestion: object) -> str:
    if not hasattr(suggestion, "finding_family"):
        return ""
    family = str(getattr(suggestion, "finding_family", "")).strip()
    if family == FAMILY_CLONES:
        kind = str(getattr(suggestion, "finding_kind", "")).strip()
        subject_key = str(getattr(suggestion, "subject_key", "")).strip()
        return clone_group_id(kind or CLONE_KIND_SEGMENT, subject_key)
    if family == FAMILY_STRUCTURAL:
        return structural_group_id(
            str(getattr(suggestion, "finding_kind", "")).strip() or CATEGORY_STRUCTURAL,
            str(getattr(suggestion, "subject_key", "")).strip(),
        )
    category = str(getattr(suggestion, "category", "")).strip()
    subject_key = str(getattr(suggestion, "subject_key", "")).strip()
    if category == CATEGORY_DEAD_CODE:
        return dead_code_group_id(subject_key)
    return design_group_id(
        category,
        subject_key or str(getattr(suggestion, "title", "")),
    )


def _git_diff_lines_payload(
    *,
    root_path: Path,
    git_diff_ref: str,
) -> tuple[str, ...]:
    if git_diff_ref.startswith("-"):
        raise MCPGitDiffError(
            f"Invalid git diff ref '{git_diff_ref}': must not start with '-'."
        )
    try:
        completed = subprocess.run(
            ["git", "diff", "--name-only", git_diff_ref, "--"],
            cwd=root_path,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise MCPGitDiffError(
            f"Unable to resolve changed paths from git diff ref '{git_diff_ref}'."
        ) from exc
    return tuple(
        sorted({line.strip() for line in completed.stdout.splitlines() if line.strip()})
    )


def _load_report_document_payload(report_json: str) -> dict[str, object]:
    try:
        payload = json.loads(report_json)
    except json.JSONDecodeError as exc:
        raise MCPServiceError(
            f"Generated canonical report is not valid JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise MCPServiceError("Generated canonical report must be a JSON object.")
    return dict(payload)


def _validated_history_limit(history_limit: int) -> int:
    if not 1 <= history_limit <= MAX_MCP_HISTORY_LIMIT:
        raise ValueError(
            f"history_limit must be between 1 and {MAX_MCP_HISTORY_LIMIT}."
        )
    return history_limit


class MCPServiceError(RuntimeError):
    """Base class for CodeClone MCP service errors."""


class MCPServiceContractError(MCPServiceError):
    """Raised when an MCP request violates the CodeClone service contract."""


class MCPRunNotFoundError(MCPServiceError):
    """Raised when a requested MCP run is not available in the in-memory registry."""


class MCPFindingNotFoundError(MCPServiceError):
    """Raised when a requested finding id is not present in the selected run."""


class MCPGitDiffError(MCPServiceError):
    """Raised when changed paths cannot be resolved from a git ref."""


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
    changed_paths: tuple[str, ...] = ()
    git_diff_ref: str | None = None
    processes: int | None = None
    min_loc: int | None = None
    min_stmt: int | None = None
    block_min_loc: int | None = None
    block_min_stmt: int | None = None
    segment_min_loc: int | None = None
    segment_min_stmt: int | None = None
    complexity_threshold: int | None = None
    coupling_threshold: int | None = None
    cohesion_threshold: int | None = None
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
    summary: dict[str, object]
    changed_paths: tuple[str, ...]
    changed_projection: dict[str, object] | None
    warnings: tuple[str, ...]
    failures: tuple[str, ...]
    func_clones_count: int
    block_clones_count: int
    project_metrics: ProjectMetrics | None
    suggestions: tuple[Suggestion, ...]
    new_func: frozenset[str]
    new_block: frozenset[str]
    metrics_diff: MetricsDiff | None


class CodeCloneMCPRunStore:
    def __init__(self, *, history_limit: int = DEFAULT_MCP_HISTORY_LIMIT) -> None:
        self._history_limit = _validated_history_limit(history_limit)
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

    def records(self) -> tuple[MCPRunRecord, ...]:
        with self._lock:
            return tuple(self._records.values())

    def clear(self) -> tuple[str, ...]:
        with self._lock:
            removed_run_ids = tuple(self._records.keys())
            self._records.clear()
            self._latest_run_id = None
            return removed_run_ids


class CodeCloneMCPService:
    def __init__(self, *, history_limit: int = DEFAULT_MCP_HISTORY_LIMIT) -> None:
        self._runs = CodeCloneMCPRunStore(history_limit=history_limit)
        self._state_lock = RLock()
        self._review_state: dict[str, OrderedDict[str, str | None]] = {}
        self._last_gate_results: dict[str, dict[str, object]] = {}
        self._spread_max_cache: dict[str, int] = {}

    def analyze_repository(self, request: MCPAnalysisRequest) -> dict[str, object]:
        self._validate_analysis_request(request)
        root_path = self._resolve_root(request.root)
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
            report_document=report_document,
            summary=base_summary,
            changed_paths=changed_paths,
            changed_projection=None,
            warnings=warnings,
            failures=failures,
            func_clones_count=analysis_result.func_clones_count,
            block_clones_count=analysis_result.block_clones_count,
            project_metrics=analysis_result.project_metrics,
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
            report_document=report_document,
            summary=summary,
            changed_paths=changed_paths,
            changed_projection=changed_projection,
            warnings=warnings,
            failures=failures,
            func_clones_count=analysis_result.func_clones_count,
            block_clones_count=analysis_result.block_clones_count,
            project_metrics=analysis_result.project_metrics,
            suggestions=analysis_result.suggestions,
            new_func=frozenset(new_func),
            new_block=frozenset(new_block),
            metrics_diff=metrics_diff,
        )
        self._runs.register(record)
        self._prune_session_state()
        return summary

    def analyze_changed_paths(self, request: MCPAnalysisRequest) -> dict[str, object]:
        if not request.changed_paths and request.git_diff_ref is None:
            raise MCPServiceContractError(
                "analyze_changed_paths requires changed_paths or git_diff_ref."
            )
        return self.analyze_repository(request)

    def get_run_summary(self, run_id: str | None = None) -> dict[str, object]:
        return dict(self._runs.get(run_id).summary)

    def compare_runs(
        self,
        *,
        run_id_before: str,
        run_id_after: str | None = None,
        focus: ComparisonFocus = "all",
    ) -> dict[str, object]:
        validated_focus = cast(
            "ComparisonFocus",
            self._validate_choice("focus", focus, _VALID_COMPARISON_FOCUS),
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
        health_before = self._summary_health_score(before.summary)
        health_after = self._summary_health_score(after.summary)
        health_delta = health_after - health_before
        verdict = self._comparison_verdict(
            regressions=len(regressions),
            improvements=len(improvements),
            health_delta=health_delta,
        )
        return {
            "before": {
                "run_id": before.run_id,
                "health": health_before,
            },
            "after": {
                "run_id": after.run_id,
                "health": health_after,
            },
            "health_delta": health_delta,
            "verdict": verdict,
            "regressions": [
                self._finding_summary_card(after, after_findings[finding_id])
                for finding_id in regressions
            ],
            "improvements": [
                self._finding_summary_card(before, before_findings[finding_id])
                for finding_id in improvements
            ],
            "unchanged_count": len(common),
            "summary": self._comparison_summary_text(
                regressions=len(regressions),
                improvements=len(improvements),
                health_delta=health_delta,
            ),
        }

    def evaluate_gates(self, request: MCPGateRequest) -> dict[str, object]:
        record = self._runs.get(request.run_id)
        gate_result = self._evaluate_gate_snapshot(record=record, request=request)
        result = {
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
        with self._state_lock:
            self._last_gate_results[record.run_id] = dict(result)
        return result

    def _evaluate_gate_snapshot(
        self,
        *,
        record: MCPRunRecord,
        request: MCPGateRequest,
    ) -> GatingResult:
        reasons: list[str] = []
        if record.project_metrics is not None:
            metric_reasons = metric_gate_reasons(
                project_metrics=record.project_metrics,
                metrics_diff=record.metrics_diff,
                config=MetricGateConfig(
                    fail_complexity=request.fail_complexity,
                    fail_coupling=request.fail_coupling,
                    fail_cohesion=request.fail_cohesion,
                    fail_cycles=request.fail_cycles,
                    fail_dead_code=request.fail_dead_code,
                    fail_health=request.fail_health,
                    fail_on_new_metrics=request.fail_on_new_metrics,
                ),
            )
            reasons.extend(f"metric:{reason}" for reason in metric_reasons)

        if request.fail_on_new and (record.new_func or record.new_block):
            reasons.append("clone:new")

        total_clone_groups = record.func_clones_count + record.block_clones_count
        if 0 <= request.fail_threshold < total_clone_groups:
            reasons.append(
                f"clone:threshold:{total_clone_groups}:{request.fail_threshold}"
            )

        if reasons:
            return GatingResult(
                exit_code=int(ExitCode.GATING_FAILURE),
                reasons=tuple(reasons),
            )
        return GatingResult(exit_code=int(ExitCode.SUCCESS), reasons=())

    def get_report_section(
        self,
        *,
        run_id: str | None = None,
        section: ReportSection = "all",
    ) -> dict[str, object]:
        validated_section = cast(
            "ReportSection",
            self._validate_choice("section", section, _VALID_REPORT_SECTIONS),
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
        payload = report_document.get(validated_section)
        if not isinstance(payload, Mapping):
            raise MCPServiceContractError(
                f"Report section '{validated_section}' is not available in this run."
            )
        return dict(payload)

    def list_findings(
        self,
        *,
        run_id: str | None = None,
        family: FindingFamilyFilter = "all",
        category: str | None = None,
        severity: str | None = None,
        source_kind: str | None = None,
        novelty: FindingNoveltyFilter = "all",
        sort_by: FindingSort = "default",
        detail_level: DetailLevel = "normal",
        changed_paths: Sequence[str] = (),
        git_diff_ref: str | None = None,
        exclude_reviewed: bool = False,
        offset: int = 0,
        limit: int = 50,
        max_results: int | None = None,
    ) -> dict[str, object]:
        validated_family = cast(
            "FindingFamilyFilter",
            self._validate_choice("family", family, _VALID_FINDING_FAMILIES),
        )
        validated_novelty = cast(
            "FindingNoveltyFilter",
            self._validate_choice("novelty", novelty, _VALID_FINDING_NOVELTY),
        )
        validated_sort = cast(
            "FindingSort",
            self._validate_choice("sort_by", sort_by, _VALID_FINDING_SORT),
        )
        validated_detail = cast(
            "DetailLevel",
            self._validate_choice("detail_level", detail_level, _VALID_DETAIL_LEVELS),
        )
        validated_severity = self._validate_optional_choice(
            "severity",
            severity,
            _VALID_SEVERITIES,
        )
        record = self._runs.get(run_id)
        paths_filter = self._resolve_query_changed_paths(
            record=record,
            changed_paths=changed_paths,
            git_diff_ref=git_diff_ref,
        )
        normalized_limit = max(
            1,
            min(max_results if max_results is not None else limit, 200),
        )
        filtered = self._query_findings(
            record=record,
            family=validated_family,
            category=category,
            severity=validated_severity,
            source_kind=source_kind,
            novelty=validated_novelty,
            sort_by=validated_sort,
            detail_level=validated_detail,
            changed_paths=paths_filter,
            exclude_reviewed=exclude_reviewed,
        )
        total = len(filtered)
        normalized_offset = max(0, offset)
        items = filtered[normalized_offset : normalized_offset + normalized_limit]
        next_offset = normalized_offset + len(items)
        return {
            "run_id": record.run_id,
            "detail_level": validated_detail,
            "sort_by": validated_sort,
            "changed_paths": list(paths_filter),
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
        for finding in self._base_findings(record):
            if str(finding.get("id")) == finding_id:
                return self._decorate_finding(
                    record,
                    finding,
                    detail_level="full",
                )
        raise MCPFindingNotFoundError(
            f"Finding id '{finding_id}' was not found in run '{record.run_id}'."
        )

    def get_remediation(
        self,
        *,
        finding_id: str,
        run_id: str | None = None,
        detail_level: DetailLevel = "full",
    ) -> dict[str, object]:
        validated_detail = cast(
            "DetailLevel",
            self._validate_choice("detail_level", detail_level, _VALID_DETAIL_LEVELS),
        )
        record = self._runs.get(run_id)
        finding = self.get_finding(finding_id=finding_id, run_id=record.run_id)
        remediation = self._as_mapping(finding.get("remediation"))
        if not remediation:
            raise MCPFindingNotFoundError(
                f"Finding id '{finding_id}' does not expose remediation guidance."
            )
        return {
            "run_id": record.run_id,
            "finding_id": finding_id,
            "detail_level": validated_detail,
            "remediation": self._project_remediation(
                remediation,
                detail_level=validated_detail,
            ),
        }

    def list_hotspots(
        self,
        *,
        kind: HotlistKind,
        run_id: str | None = None,
        detail_level: DetailLevel = "normal",
        changed_paths: Sequence[str] = (),
        git_diff_ref: str | None = None,
        exclude_reviewed: bool = False,
        limit: int = 10,
        max_results: int | None = None,
    ) -> dict[str, object]:
        validated_kind = cast(
            "HotlistKind",
            self._validate_choice("kind", kind, _VALID_HOTLIST_KINDS),
        )
        validated_detail = cast(
            "DetailLevel",
            self._validate_choice("detail_level", detail_level, _VALID_DETAIL_LEVELS),
        )
        record = self._runs.get(run_id)
        paths_filter = self._resolve_query_changed_paths(
            record=record,
            changed_paths=changed_paths,
            git_diff_ref=git_diff_ref,
        )
        rows = self._hotspot_rows(
            record=record,
            kind=validated_kind,
            detail_level=validated_detail,
            changed_paths=paths_filter,
            exclude_reviewed=exclude_reviewed,
        )
        normalized_limit = max(
            1,
            min(max_results if max_results is not None else limit, 50),
        )
        return {
            "run_id": record.run_id,
            "kind": validated_kind,
            "detail_level": validated_detail,
            "changed_paths": list(paths_filter),
            "returned": min(len(rows), normalized_limit),
            "total": len(rows),
            "items": [dict(self._as_mapping(item)) for item in rows[:normalized_limit]],
        }

    def generate_pr_summary(
        self,
        *,
        run_id: str | None = None,
        changed_paths: Sequence[str] = (),
        git_diff_ref: str | None = None,
        format: PRSummaryFormat = "markdown",
    ) -> dict[str, object]:
        output_format = cast(
            "PRSummaryFormat",
            self._validate_choice("format", format, _VALID_PR_SUMMARY_FORMATS),
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
            resolved = cast("list[dict[str, object]]", compare_payload["improvements"])
        with self._state_lock:
            gate_result = dict(
                self._last_gate_results.get(
                    record.run_id,
                    {"would_fail": False, "reasons": []},
                )
            )
        verdict = self._changed_verdict(
            changed_projection={
                "total": len(changed_items),
                "new": sum(
                    1 for item in changed_items if str(item.get("novelty", "")) == "new"
                ),
            },
            health_delta=self._summary_health_delta(record.summary),
        )
        payload = {
            "run_id": record.run_id,
            "changed_paths": list(paths_filter),
            "health": self._as_mapping(record.summary.get("health")),
            "health_delta": self._summary_health_delta(record.summary),
            "verdict": verdict,
            "new_findings_in_changed_files": changed_items,
            "resolved": resolved,
            "blocking_gates": list(cast(Sequence[str], gate_result.get("reasons", []))),
        }
        if output_format == "json":
            return payload
        return {
            "run_id": record.run_id,
            "format": output_format,
            "content": self._render_pr_summary_markdown(payload),
        }

    def mark_finding_reviewed(
        self,
        *,
        finding_id: str,
        run_id: str | None = None,
        note: str | None = None,
    ) -> dict[str, object]:
        record = self._runs.get(run_id)
        self.get_finding(finding_id=finding_id, run_id=record.run_id)
        with self._state_lock:
            review_map = self._review_state.setdefault(record.run_id, OrderedDict())
            review_map[finding_id] = (
                note.strip() if isinstance(note, str) and note.strip() else None
            )
            review_map.move_to_end(finding_id)
        return {
            "run_id": record.run_id,
            "finding_id": finding_id,
            "reviewed": True,
            "note": review_map[finding_id],
            "reviewed_count": len(review_map),
        }

    def list_reviewed_findings(
        self,
        *,
        run_id: str | None = None,
    ) -> dict[str, object]:
        record = self._runs.get(run_id)
        with self._state_lock:
            review_items = tuple(
                self._review_state.get(record.run_id, OrderedDict()).items()
            )
        items = []
        for finding_id, note in review_items:
            try:
                finding = self.get_finding(finding_id=finding_id, run_id=record.run_id)
            except MCPFindingNotFoundError:
                continue
            items.append(
                {
                    "finding_id": finding_id,
                    "note": note,
                    "finding": self._project_finding_detail(
                        finding,
                        detail_level="summary",
                    ),
                }
            )
        return {
            "run_id": record.run_id,
            "reviewed_count": len(items),
            "items": items,
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
            "cleared_run_ids": list(removed_run_ids),
            "cleared_review_entries": cleared_review_entries,
            "cleared_gate_results": cleared_gate_results,
            "cleared_spread_cache_entries": cleared_spread_cache_entries,
        }

    def check_complexity(
        self,
        *,
        run_id: str | None = None,
        root: str = ".",
        path: str | None = None,
        min_complexity: int | None = None,
        max_results: int = 10,
        detail_level: DetailLevel = "normal",
    ) -> dict[str, object]:
        validated_detail = cast(
            "DetailLevel",
            self._validate_choice("detail_level", detail_level, _VALID_DETAIL_LEVELS),
        )
        record = self._resolve_granular_record(
            run_id=run_id,
            root=root,
            analysis_mode="full",
        )
        findings = self._query_findings(
            record=record,
            family="design",
            category=CATEGORY_COMPLEXITY,
            detail_level=validated_detail,
            changed_paths=self._path_filter_tuple(path),
            sort_by="priority",
        )
        if min_complexity is not None:
            findings = [
                finding
                for finding in findings
                if _as_int(
                    self._as_mapping(finding.get("facts")).get(
                        "cyclomatic_complexity",
                        0,
                    )
                )
                >= min_complexity
            ]
        return self._granular_payload(
            record=record,
            check="complexity",
            items=findings,
            detail_level=validated_detail,
            max_results=max_results,
            path=path,
        )

    def check_clones(
        self,
        *,
        run_id: str | None = None,
        root: str = ".",
        path: str | None = None,
        clone_type: str | None = None,
        source_kind: str | None = None,
        max_results: int = 10,
        detail_level: DetailLevel = "normal",
    ) -> dict[str, object]:
        validated_detail = cast(
            "DetailLevel",
            self._validate_choice("detail_level", detail_level, _VALID_DETAIL_LEVELS),
        )
        record = self._resolve_granular_record(
            run_id=run_id,
            root=root,
            analysis_mode="clones_only",
        )
        findings = self._query_findings(
            record=record,
            family="clone",
            source_kind=source_kind,
            detail_level=validated_detail,
            changed_paths=self._path_filter_tuple(path),
            sort_by="priority",
        )
        if clone_type is not None:
            findings = [
                finding
                for finding in findings
                if str(finding.get("clone_type", "")).strip() == clone_type
            ]
        return self._granular_payload(
            record=record,
            check="clones",
            items=findings,
            detail_level=validated_detail,
            max_results=max_results,
            path=path,
        )

    def check_coupling(
        self,
        *,
        run_id: str | None = None,
        root: str = ".",
        path: str | None = None,
        max_results: int = 10,
        detail_level: DetailLevel = "normal",
    ) -> dict[str, object]:
        validated_detail = cast(
            "DetailLevel",
            self._validate_choice("detail_level", detail_level, _VALID_DETAIL_LEVELS),
        )
        record = self._resolve_granular_record(
            run_id=run_id,
            root=root,
            analysis_mode="full",
        )
        findings = self._query_findings(
            record=record,
            family="design",
            category=CATEGORY_COUPLING,
            detail_level=validated_detail,
            changed_paths=self._path_filter_tuple(path),
            sort_by="priority",
        )
        return self._granular_payload(
            record=record,
            check="coupling",
            items=findings,
            detail_level=validated_detail,
            max_results=max_results,
            path=path,
        )

    def check_cohesion(
        self,
        *,
        run_id: str | None = None,
        root: str = ".",
        path: str | None = None,
        max_results: int = 10,
        detail_level: DetailLevel = "normal",
    ) -> dict[str, object]:
        validated_detail = cast(
            "DetailLevel",
            self._validate_choice("detail_level", detail_level, _VALID_DETAIL_LEVELS),
        )
        record = self._resolve_granular_record(
            run_id=run_id,
            root=root,
            analysis_mode="full",
        )
        findings = self._query_findings(
            record=record,
            family="design",
            category=CATEGORY_COHESION,
            detail_level=validated_detail,
            changed_paths=self._path_filter_tuple(path),
            sort_by="priority",
        )
        return self._granular_payload(
            record=record,
            check="cohesion",
            items=findings,
            detail_level=validated_detail,
            max_results=max_results,
            path=path,
        )

    def check_dead_code(
        self,
        *,
        run_id: str | None = None,
        root: str = ".",
        path: str | None = None,
        min_severity: str | None = None,
        max_results: int = 10,
        detail_level: DetailLevel = "normal",
    ) -> dict[str, object]:
        validated_detail = cast(
            "DetailLevel",
            self._validate_choice("detail_level", detail_level, _VALID_DETAIL_LEVELS),
        )
        validated_min_severity = self._validate_optional_choice(
            "min_severity",
            min_severity,
            _VALID_SEVERITIES,
        )
        record = self._resolve_granular_record(
            run_id=run_id,
            root=root,
            analysis_mode="full",
        )
        findings = self._query_findings(
            record=record,
            family="dead_code",
            detail_level=validated_detail,
            changed_paths=self._path_filter_tuple(path),
            sort_by="priority",
        )
        if validated_min_severity is not None:
            findings = [
                finding
                for finding in findings
                if self._severity_rank(str(finding.get("severity", "")))
                >= self._severity_rank(validated_min_severity)
            ]
        return self._granular_payload(
            record=record,
            check="dead_code",
            items=findings,
            detail_level=validated_detail,
            max_results=max_results,
            path=path,
        )

    def read_resource(self, uri: str) -> str:
        if uri == "codeclone://schema":
            return json.dumps(
                self._schema_resource_payload(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
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
        if suffix == "health":
            return json.dumps(
                self._as_mapping(record.summary.get("health")),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        if suffix == "gates":
            with self._state_lock:
                gate_result = self._last_gate_results.get(record.run_id)
            if gate_result is None:
                raise MCPServiceContractError(
                    "No gate evaluation result is available in this MCP session."
                )
            return json.dumps(
                gate_result,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        if suffix == "changed":
            if record.changed_projection is None:
                raise MCPServiceContractError(
                    "Changed-findings projection is not available in this run."
                )
            return json.dumps(
                record.changed_projection,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        if suffix == "schema":
            return json.dumps(
                self._schema_resource_payload(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        if suffix == "report.json":
            return json.dumps(
                record.report_document,
                ensure_ascii=False,
                indent=2,
            )
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

    def _resolve_request_changed_paths(
        self,
        *,
        root_path: Path,
        changed_paths: Sequence[str],
        git_diff_ref: str | None,
    ) -> tuple[str, ...]:
        if changed_paths and git_diff_ref is not None:
            raise MCPServiceContractError(
                "Provide changed_paths or git_diff_ref, not both."
            )
        if git_diff_ref is not None:
            return self._git_diff_paths(root_path=root_path, git_diff_ref=git_diff_ref)
        if not changed_paths:
            return ()
        return self._normalize_changed_paths(root_path=root_path, paths=changed_paths)

    def _resolve_query_changed_paths(
        self,
        *,
        record: MCPRunRecord,
        changed_paths: Sequence[str],
        git_diff_ref: str | None,
        prefer_record_paths: bool = False,
    ) -> tuple[str, ...]:
        if changed_paths or git_diff_ref is not None:
            return self._resolve_request_changed_paths(
                root_path=record.root,
                changed_paths=changed_paths,
                git_diff_ref=git_diff_ref,
            )
        if prefer_record_paths:
            return record.changed_paths
        return ()

    def _normalize_changed_paths(
        self,
        *,
        root_path: Path,
        paths: Sequence[str],
    ) -> tuple[str, ...]:
        normalized: set[str] = set()
        for raw_path in paths:
            candidate = Path(str(raw_path)).expanduser()
            if candidate.is_absolute():
                try:
                    relative = candidate.resolve().relative_to(root_path)
                except (OSError, ValueError) as exc:
                    raise MCPServiceContractError(
                        f"Changed path '{raw_path}' is outside root '{root_path}'."
                    ) from exc
                normalized.add(relative.as_posix())
                continue
            cleaned = self._normalize_relative_path(candidate.as_posix())
            if cleaned:
                normalized.add(cleaned)
        return tuple(sorted(normalized))

    def _git_diff_paths(
        self,
        *,
        root_path: Path,
        git_diff_ref: str,
    ) -> tuple[str, ...]:
        lines = _git_diff_lines_payload(
            root_path=root_path,
            git_diff_ref=git_diff_ref,
        )
        return self._normalize_changed_paths(root_path=root_path, paths=lines)

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

    def _summary_health_score(self, summary: Mapping[str, object]) -> int:
        health = self._as_mapping(summary.get("health"))
        score = health.get("score", 0)
        return _as_int(score, 0)

    def _summary_health_delta(self, summary: Mapping[str, object]) -> int:
        metrics_diff = self._as_mapping(summary.get("metrics_diff"))
        value = metrics_diff.get("health_delta", 0)
        return _as_int(value, 0)

    def _severity_rank(self, severity: str) -> int:
        return {
            SEVERITY_CRITICAL: 3,
            SEVERITY_WARNING: 2,
            SEVERITY_INFO: 1,
        }.get(severity, 0)

    def _path_filter_tuple(self, path: str | None) -> tuple[str, ...]:
        if not path:
            return ()
        cleaned = self._normalize_relative_path(Path(path).as_posix())
        return (cleaned,) if cleaned else ()

    def _normalize_relative_path(self, path: str) -> str:
        cleaned = path.strip()
        if cleaned == ".":
            return ""
        if cleaned.startswith("./"):
            cleaned = cleaned[2:]
        return cleaned.rstrip("/")

    def _previous_run_for_root(self, record: MCPRunRecord) -> MCPRunRecord | None:
        previous: MCPRunRecord | None = None
        for item in self._runs.records():
            if item.run_id == record.run_id:
                return previous
            if item.root == record.root:
                previous = item
        return None

    def _record_supports_analysis_mode(
        self,
        record: MCPRunRecord,
        *,
        analysis_mode: AnalysisMode,
    ) -> bool:
        record_mode = record.request.analysis_mode
        if analysis_mode == "clones_only":
            return record_mode in {"clones_only", "full"}
        return record_mode == "full"

    def _latest_compatible_record(
        self,
        *,
        analysis_mode: AnalysisMode,
        root_path: Path | None = None,
    ) -> MCPRunRecord | None:
        for item in reversed(self._runs.records()):
            if root_path is not None and item.root != root_path:
                continue
            if self._record_supports_analysis_mode(
                item,
                analysis_mode=analysis_mode,
            ):
                return item
        return None

    def _resolve_granular_record(
        self,
        *,
        run_id: str | None,
        root: str,
        analysis_mode: AnalysisMode,
    ) -> MCPRunRecord:
        if run_id is not None:
            record = self._runs.get(run_id)
            if self._record_supports_analysis_mode(record, analysis_mode=analysis_mode):
                return record
            raise MCPServiceContractError(
                "Selected MCP run is not compatible with this check. "
                f"Call analyze_repository(root='{record.root}', "
                "analysis_mode='full') first."
            )
        root_path: Path | None = None
        if root != DEFAULT_ROOT:
            root_path = self._resolve_root(root)
        latest_record = self._latest_compatible_record(
            analysis_mode=analysis_mode,
            root_path=root_path,
        )
        if latest_record is not None:
            return latest_record
        if root_path is not None:
            raise MCPRunNotFoundError(
                f"No compatible MCP analysis run is available for root: {root_path}. "
                f"Call analyze_repository(root='{root_path}') or "
                f"analyze_changed_paths(root='{root_path}', changed_paths=[...]) first."
            )
        raise MCPRunNotFoundError(
            "No compatible MCP analysis run is available. "
            "Call analyze_repository(root='/path/to/repo') or "
            "analyze_changed_paths(root='/path/to/repo', changed_paths=[...]) first."
        )

    def _base_findings(self, record: MCPRunRecord) -> list[dict[str, object]]:
        report_document = record.report_document
        findings = self._as_mapping(report_document.get("findings"))
        groups = self._as_mapping(findings.get("groups"))
        clone_groups = self._as_mapping(groups.get(FAMILY_CLONES))
        design_groups = self._design_groups_for_record(record, groups=groups)
        return [
            *self._dict_list(clone_groups.get("functions")),
            *self._dict_list(clone_groups.get("blocks")),
            *self._dict_list(clone_groups.get("segments")),
            *self._dict_list(
                self._as_mapping(groups.get(FAMILY_STRUCTURAL)).get("groups")
            ),
            *self._dict_list(
                self._as_mapping(groups.get(FAMILY_DEAD_CODE)).get("groups")
            ),
            *design_groups,
        ]

    def _design_groups_for_record(
        self,
        record: MCPRunRecord,
        *,
        groups: Mapping[str, object],
    ) -> list[dict[str, object]]:
        canonical_design_groups = self._dict_list(
            self._as_mapping(groups.get(FAMILY_DESIGN)).get("groups")
        )
        if (
            record.request.complexity_threshold is None
            and record.request.coupling_threshold is None
            and record.request.cohesion_threshold is None
        ):
            return canonical_design_groups

        metrics = self._as_mapping(record.report_document.get("metrics"))
        families = self._as_mapping(metrics.get("families"))
        complexity_threshold = (
            record.request.complexity_threshold
            if record.request.complexity_threshold is not None
            else DEFAULT_COMPLEXITY_THRESHOLD
        )
        coupling_threshold = (
            record.request.coupling_threshold
            if record.request.coupling_threshold is not None
            else DEFAULT_COUPLING_THRESHOLD
        )
        cohesion_threshold = (
            record.request.cohesion_threshold
            if record.request.cohesion_threshold is not None
            else DEFAULT_COHESION_THRESHOLD
        )
        groups_out: list[dict[str, object]] = []
        for item in self._as_sequence(
            self._as_mapping(families.get(CATEGORY_COMPLEXITY)).get("items")
        ):
            group = self._complexity_group_for_threshold(
                self._as_mapping(item),
                threshold=complexity_threshold,
                scan_root=str(record.root),
            )
            if group is not None:
                groups_out.append(group)
        for item in self._as_sequence(
            self._as_mapping(families.get(CATEGORY_COUPLING)).get("items")
        ):
            group = self._coupling_group_for_threshold(
                self._as_mapping(item),
                threshold=coupling_threshold,
                scan_root=str(record.root),
            )
            if group is not None:
                groups_out.append(group)
        for item in self._as_sequence(
            self._as_mapping(families.get(CATEGORY_COHESION)).get("items")
        ):
            group = self._cohesion_group_for_threshold(
                self._as_mapping(item),
                threshold=cohesion_threshold,
                scan_root=str(record.root),
            )
            if group is not None:
                groups_out.append(group)
        groups_out.extend(
            group
            for group in canonical_design_groups
            if str(group.get("category", "")) == CATEGORY_DEPENDENCY
        )
        groups_out.sort(
            key=lambda group: (
                -_as_float(group.get("priority", 0.0), 0.0),
                str(group.get("id", "")),
            )
        )
        return groups_out

    def _design_singleton_group(
        self,
        *,
        category: str,
        kind: str,
        severity: str,
        qualname: str,
        filepath: str,
        start_line: int,
        end_line: int,
        item_data: Mapping[str, object],
        facts: Mapping[str, object],
        scan_root: str,
    ) -> dict[str, object]:
        return _design_singleton_group_payload(
            category=category,
            kind=kind,
            severity=severity,
            qualname=qualname,
            filepath=filepath,
            start_line=start_line,
            end_line=end_line,
            item_data=item_data,
            facts=facts,
            scan_root=scan_root,
        )

    def _complexity_group_for_threshold(
        self,
        item_map: Mapping[str, object],
        *,
        threshold: int,
        scan_root: str,
    ) -> dict[str, object] | None:
        return _complexity_group_for_threshold_payload(
            item_map,
            threshold=threshold,
            scan_root=scan_root,
        )

    def _coupling_group_for_threshold(
        self,
        item_map: Mapping[str, object],
        *,
        threshold: int,
        scan_root: str,
    ) -> dict[str, object] | None:
        return _coupling_group_for_threshold_payload(
            item_map,
            threshold=threshold,
            scan_root=scan_root,
        )

    def _cohesion_group_for_threshold(
        self,
        item_map: Mapping[str, object],
        *,
        threshold: int,
        scan_root: str,
    ) -> dict[str, object] | None:
        return _cohesion_group_for_threshold_payload(
            item_map,
            threshold=threshold,
            scan_root=scan_root,
        )

    def _query_findings(
        self,
        *,
        record: MCPRunRecord,
        family: FindingFamilyFilter = "all",
        category: str | None = None,
        severity: str | None = None,
        source_kind: str | None = None,
        novelty: FindingNoveltyFilter = "all",
        sort_by: FindingSort = "default",
        detail_level: DetailLevel = "normal",
        changed_paths: Sequence[str] = (),
        exclude_reviewed: bool = False,
    ) -> list[dict[str, object]]:
        findings = self._base_findings(record)
        max_spread_value = max(
            (self._spread_value(finding) for finding in findings),
            default=0,
        )
        with self._state_lock:
            self._spread_max_cache[record.run_id] = max_spread_value
        filtered = [
            finding
            for finding in findings
            if self._matches_finding_filters(
                finding=finding,
                family=family,
                category=category,
                severity=severity,
                source_kind=source_kind,
                novelty=novelty,
            )
            and (
                not changed_paths
                or self._finding_touches_paths(
                    finding=finding,
                    changed_paths=changed_paths,
                )
            )
            and (not exclude_reviewed or not self._finding_is_reviewed(record, finding))
        ]
        remediation_map = {
            str(finding.get("id", "")): self._remediation_for_finding(record, finding)
            for finding in filtered
        }
        priority_map = {
            str(finding.get("id", "")): self._priority_score(
                record,
                finding,
                remediation=remediation_map[str(finding.get("id", ""))],
                max_spread_value=max_spread_value,
            )
            for finding in filtered
        }
        ordered = self._sort_findings(
            record=record,
            findings=filtered,
            sort_by=sort_by,
            priority_map=priority_map,
        )
        return [
            self._decorate_finding(
                record,
                finding,
                detail_level=detail_level,
                remediation=remediation_map[str(finding.get("id", ""))],
                priority_payload=priority_map[str(finding.get("id", ""))],
                max_spread_value=max_spread_value,
            )
            for finding in ordered
        ]

    def _sort_findings(
        self,
        *,
        record: MCPRunRecord,
        findings: Sequence[Mapping[str, object]],
        sort_by: FindingSort,
        priority_map: Mapping[str, Mapping[str, object]] | None = None,
    ) -> list[dict[str, object]]:
        finding_rows = [dict(finding) for finding in findings]
        if sort_by == "default":
            return finding_rows
        if sort_by == "severity":
            finding_rows.sort(
                key=lambda finding: (
                    -self._severity_rank(str(finding.get("severity", ""))),
                    str(finding.get("id", "")),
                )
            )
        elif sort_by == "spread":
            finding_rows.sort(
                key=lambda finding: (
                    -self._spread_value(finding),
                    -_as_float(finding.get("priority", 0.0), 0.0),
                    str(finding.get("id", "")),
                )
            )
        else:
            finding_rows.sort(
                key=lambda finding: (
                    -_as_float(
                        self._as_mapping(
                            (priority_map or {}).get(str(finding.get("id", "")))
                        ).get("score", 0.0),
                        0.0,
                    )
                    if priority_map is not None
                    else -_as_float(
                        self._priority_score(record, finding)["score"],
                        0.0,
                    ),
                    -self._severity_rank(str(finding.get("severity", ""))),
                    str(finding.get("id", "")),
                )
            )
        return finding_rows

    def _decorate_finding(
        self,
        record: MCPRunRecord,
        finding: Mapping[str, object],
        *,
        detail_level: DetailLevel,
        remediation: Mapping[str, object] | None = None,
        priority_payload: Mapping[str, object] | None = None,
        max_spread_value: int | None = None,
    ) -> dict[str, object]:
        resolved_remediation = (
            remediation
            if remediation is not None
            else self._remediation_for_finding(record, finding)
        )
        resolved_priority_payload = (
            dict(priority_payload)
            if priority_payload is not None
            else self._priority_score(
                record,
                finding,
                remediation=resolved_remediation,
                max_spread_value=max_spread_value,
            )
        )
        payload = dict(finding)
        payload["priority_score"] = resolved_priority_payload["score"]
        payload["priority_factors"] = resolved_priority_payload["factors"]
        payload["locations"] = self._locations_for_finding(record, finding)
        payload["html_anchor"] = f"finding-{finding.get('id', '')}"
        if resolved_remediation is not None:
            payload["remediation"] = resolved_remediation
        return self._project_finding_detail(payload, detail_level=detail_level)

    def _project_finding_detail(
        self,
        finding: Mapping[str, object],
        *,
        detail_level: DetailLevel,
    ) -> dict[str, object]:
        if detail_level == "full":
            return dict(finding)
        if detail_level == "summary":
            return self._finding_summary_card_payload(finding)
        payload = dict(finding)
        if "remediation" in payload:
            payload["remediation"] = self._project_remediation(
                self._as_mapping(payload["remediation"]),
                detail_level="summary",
            )
        return payload

    def _finding_summary_card(
        self,
        record: MCPRunRecord,
        finding: Mapping[str, object],
    ) -> dict[str, object]:
        return self._finding_summary_card_payload(
            self._decorate_finding(record, finding, detail_level="normal")
        )

    def _finding_summary_card_payload(
        self,
        finding: Mapping[str, object],
    ) -> dict[str, object]:
        card = serialize_finding_group_card(finding)
        return {
            "id": str(finding.get("id", "")),
            **card,
            "novelty": str(finding.get("novelty", "")),
            "priority_score": _as_float(finding.get("priority_score", 0.0), 0.0),
            "priority_factors": dict(self._as_mapping(finding.get("priority_factors"))),
            "locations": [
                dict(self._as_mapping(item))
                for item in self._as_sequence(finding.get("locations"))[:3]
            ],
        }

    def _matches_finding_filters(
        self,
        *,
        finding: Mapping[str, object],
        family: FindingFamilyFilter,
        category: str | None = None,
        severity: str | None,
        source_kind: str | None,
        novelty: FindingNoveltyFilter,
    ) -> bool:
        finding_family = str(finding.get("family", "")).strip()
        if family != "all" and finding_family != family:
            return False
        if (
            category is not None
            and str(finding.get("category", "")).strip() != category
        ):
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

    def _finding_touches_paths(
        self,
        *,
        finding: Mapping[str, object],
        changed_paths: Sequence[str],
    ) -> bool:
        normalized_paths = tuple(changed_paths)
        for item in self._as_sequence(finding.get("items")):
            relative_path = str(self._as_mapping(item).get("relative_path", "")).strip()
            if relative_path and self._path_matches(relative_path, normalized_paths):
                return True
        return False

    def _path_matches(self, relative_path: str, changed_paths: Sequence[str]) -> bool:
        for candidate in changed_paths:
            if relative_path == candidate or relative_path.startswith(candidate + "/"):
                return True
        return False

    def _finding_is_reviewed(
        self,
        record: MCPRunRecord,
        finding: Mapping[str, object],
    ) -> bool:
        with self._state_lock:
            review_map = self._review_state.get(record.run_id, OrderedDict())
            return str(finding.get("id", "")) in review_map

    def _priority_score(
        self,
        record: MCPRunRecord,
        finding: Mapping[str, object],
        *,
        remediation: Mapping[str, object] | None = None,
        max_spread_value: int | None = None,
    ) -> dict[str, object]:
        spread_weight = self._spread_weight(
            record,
            finding,
            max_spread_value=max_spread_value,
        )
        factors = {
            "severity_weight": _SEVERITY_WEIGHT.get(
                str(finding.get("severity", "")),
                0.2,
            ),
            "effort_weight": _EFFORT_WEIGHT.get(
                (
                    str(remediation.get("effort", EFFORT_MODERATE))
                    if remediation is not None
                    else EFFORT_MODERATE
                ),
                0.6,
            ),
            "novelty_weight": _NOVELTY_WEIGHT.get(
                str(finding.get("novelty", "")),
                0.7,
            ),
            "runtime_weight": _RUNTIME_WEIGHT.get(
                str(
                    self._as_mapping(finding.get("source_scope")).get(
                        "dominant_kind",
                        "other",
                    )
                ),
                0.5,
            ),
            "spread_weight": spread_weight,
            "confidence_weight": _CONFIDENCE_WEIGHT.get(
                str(finding.get("confidence", CONFIDENCE_MEDIUM)),
                0.7,
            ),
        }
        product = 1.0
        for value in factors.values():
            product *= max(_as_float(value, 0.01), 0.01)
        score = product ** (1.0 / max(len(factors), 1))
        return {
            "score": round(score, 4),
            "factors": {
                key: round(_as_float(value, 0.0), 4) for key, value in factors.items()
            },
        }

    def _spread_weight(
        self,
        record: MCPRunRecord,
        finding: Mapping[str, object],
        *,
        max_spread_value: int | None = None,
    ) -> float:
        spread_value = self._spread_value(finding)
        if max_spread_value is None:
            with self._state_lock:
                max_spread_value = self._spread_max_cache.get(record.run_id)
            if max_spread_value is None:
                max_spread_value = max(
                    (self._spread_value(item) for item in self._base_findings(record)),
                    default=0,
                )
                with self._state_lock:
                    self._spread_max_cache[record.run_id] = max_spread_value
        max_value = max_spread_value
        if max_value <= 0:
            return 0.3
        return max(0.2, min(1.0, spread_value / max_value))

    def _spread_value(self, finding: Mapping[str, object]) -> int:
        spread = self._as_mapping(finding.get("spread"))
        files = _as_int(spread.get("files", 0), 0)
        functions = _as_int(spread.get("functions", 0), 0)
        count = _as_int(finding.get("count", 0), 0)
        return max(files, functions, count, 1)

    def _locations_for_finding(
        self,
        record: MCPRunRecord,
        finding: Mapping[str, object],
    ) -> list[dict[str, object]]:
        locations: list[dict[str, object]] = []
        for item in self._as_sequence(finding.get("items")):
            item_map = self._as_mapping(item)
            relative_path = str(item_map.get("relative_path", "")).strip()
            if not relative_path:
                continue
            absolute_path = (record.root / relative_path).resolve()
            line = _as_int(item_map.get("start_line", 0) or 0, 0)
            symbol = str(item_map.get("qualname", item_map.get("module", ""))).strip()
            uri = absolute_path.as_uri()
            if line > 0:
                uri = f"{uri}#L{line}"
            locations.append(
                {
                    "file": relative_path,
                    "line": line,
                    "symbol": symbol,
                    "uri": uri,
                }
            )
        deduped: list[dict[str, object]] = []
        seen: set[tuple[str, int, str]] = set()
        for location in locations:
            key = (
                str(location.get("file", "")),
                _as_int(location.get("line", 0), 0),
                str(location.get("symbol", "")),
            )
            if key not in seen:
                seen.add(key)
                deduped.append(location)
        return deduped

    def _suggestion_finding_id(self, suggestion: object) -> str:
        return _suggestion_finding_id_payload(suggestion)

    def _remediation_for_finding(
        self,
        record: MCPRunRecord,
        finding: Mapping[str, object],
    ) -> dict[str, object] | None:
        suggestion = self._suggestion_for_finding(record, str(finding.get("id", "")))
        if suggestion is None:
            return None
        source_kind = str(getattr(suggestion, "source_kind", "other"))
        spread_files = _as_int(getattr(suggestion, "spread_files", 0), 0)
        spread_functions = _as_int(getattr(suggestion, "spread_functions", 0), 0)
        title = str(getattr(suggestion, "title", "")).strip()
        severity = str(finding.get("severity", "")).strip()
        novelty = str(finding.get("novelty", "known")).strip()
        count = _as_int(
            getattr(suggestion, "fact_count", 0) or finding.get("count", 0) or 0,
            0,
        )
        safe_refactor_shape = self._safe_refactor_shape(suggestion)
        effort = str(getattr(suggestion, "effort", EFFORT_MODERATE))
        confidence = str(getattr(suggestion, "confidence", CONFIDENCE_MEDIUM))
        risk_level = self._risk_level_for_effort(effort)
        return {
            "effort": effort,
            "priority": _as_float(getattr(suggestion, "priority", 0.0), 0.0),
            "confidence": confidence,
            "safe_refactor_shape": safe_refactor_shape,
            "steps": list(getattr(suggestion, "steps", ())),
            "risk_level": risk_level,
            "why_now": self._why_now_text(
                title=title,
                severity=severity,
                novelty=novelty,
                count=count,
                source_kind=source_kind,
                spread_files=spread_files,
                spread_functions=spread_functions,
                effort=effort,
            ),
            "blast_radius": {
                "files": spread_files,
                "functions": spread_functions,
                "is_production": source_kind == "production",
            },
        }

    def _suggestion_for_finding(
        self,
        record: MCPRunRecord,
        finding_id: str,
    ) -> object | None:
        for suggestion in record.suggestions:
            if self._suggestion_finding_id(suggestion) == finding_id:
                return suggestion
        return None

    def _safe_refactor_shape(self, suggestion: object) -> str:
        category = str(getattr(suggestion, "category", "")).strip()
        clone_type = str(getattr(suggestion, "clone_type", "")).strip()
        title = str(getattr(suggestion, "title", "")).strip()
        if category == CATEGORY_CLONE and clone_type == "Type-1":
            return "Keep one canonical implementation and route callers through it."
        if category == CATEGORY_CLONE and clone_type == "Type-2":
            return "Extract shared implementation with explicit parameters."
        if category == CATEGORY_CLONE and "Block" in title:
            return "Extract the repeated statement sequence into a helper."
        if category == CATEGORY_STRUCTURAL:
            return "Extract the repeated branch family into a named helper."
        if category == CATEGORY_COMPLEXITY:
            return "Split the function into smaller named steps."
        if category == CATEGORY_COUPLING:
            return "Isolate responsibilities and invert unnecessary dependencies."
        if category == CATEGORY_COHESION:
            return "Split the class by responsibility boundary."
        if category == CATEGORY_DEAD_CODE:
            return "Delete the unused symbol or document intentional reachability."
        if category == CATEGORY_DEPENDENCY:
            return "Break the cycle by moving shared abstractions to a lower layer."
        return "Extract the repeated logic into a shared, named abstraction."

    def _risk_level_for_effort(self, effort: str) -> str:
        return {
            EFFORT_EASY: "low",
            EFFORT_MODERATE: "medium",
            EFFORT_HARD: "high",
        }.get(effort, "medium")

    def _why_now_text(
        self,
        *,
        title: str,
        severity: str,
        novelty: str,
        count: int,
        source_kind: str,
        spread_files: int,
        spread_functions: int,
        effort: str,
    ) -> str:
        novelty_text = "new regression" if novelty == "new" else "known debt"
        context = (
            "production code"
            if source_kind == "production"
            else source_kind or "mixed scope"
        )
        spread_text = f"{spread_files} files / {spread_functions} functions"
        count_text = f"{count} instances" if count > 0 else "localized issue"
        return (
            f"{severity.upper()} {title} in {context} — {count_text}, "
            f"{spread_text}, {effort} fix, {novelty_text}."
        )

    def _project_remediation(
        self,
        remediation: Mapping[str, object],
        *,
        detail_level: DetailLevel,
    ) -> dict[str, object]:
        if detail_level == "full":
            return dict(remediation)
        projected = {
            "effort": remediation.get("effort"),
            "priority": remediation.get("priority"),
            "confidence": remediation.get("confidence"),
            "safe_refactor_shape": remediation.get("safe_refactor_shape"),
            "risk_level": remediation.get("risk_level"),
            "why_now": remediation.get("why_now"),
        }
        if detail_level == "summary":
            return projected
        projected["blast_radius"] = dict(
            self._as_mapping(remediation.get("blast_radius"))
        )
        projected["steps"] = list(self._as_sequence(remediation.get("steps")))
        return projected

    def _hotspot_rows(
        self,
        *,
        record: MCPRunRecord,
        kind: HotlistKind,
        detail_level: DetailLevel,
        changed_paths: Sequence[str],
        exclude_reviewed: bool,
    ) -> list[dict[str, object]]:
        findings = self._base_findings(record)
        finding_index = {str(finding.get("id", "")): finding for finding in findings}
        max_spread_value = max(
            (self._spread_value(finding) for finding in findings),
            default=0,
        )
        with self._state_lock:
            self._spread_max_cache[record.run_id] = max_spread_value
        remediation_map = {
            str(finding.get("id", "")): self._remediation_for_finding(record, finding)
            for finding in findings
        }
        priority_map = {
            str(finding.get("id", "")): self._priority_score(
                record,
                finding,
                remediation=remediation_map[str(finding.get("id", ""))],
                max_spread_value=max_spread_value,
            )
            for finding in findings
        }
        derived = self._as_mapping(record.report_document.get("derived"))
        hotlists = self._as_mapping(derived.get("hotlists"))
        if kind == "highest_priority":
            ordered_ids = [
                str(finding.get("id", ""))
                for finding in self._sort_findings(
                    record=record,
                    findings=findings,
                    sort_by="priority",
                    priority_map=priority_map,
                )
            ]
        else:
            hotlist_key = f"{kind}_ids"
            ordered_ids = [
                str(item)
                for item in self._as_sequence(hotlists.get(hotlist_key))
                if str(item)
            ]
        rows: list[dict[str, object]] = []
        for finding_id in ordered_ids:
            finding = finding_index.get(finding_id)
            if finding is None:
                continue
            if changed_paths and not self._finding_touches_paths(
                finding=finding,
                changed_paths=changed_paths,
            ):
                continue
            if exclude_reviewed and self._finding_is_reviewed(record, finding):
                continue
            finding_id_key = str(finding.get("id", ""))
            decorated = self._decorate_finding(
                record,
                finding,
                detail_level=detail_level,
                remediation=remediation_map[finding_id_key],
                priority_payload=priority_map[finding_id_key],
                max_spread_value=max_spread_value,
            )
            if detail_level == "summary":
                rows.append(self._finding_summary_card_payload(decorated))
            elif detail_level == "full":
                rows.append(decorated)
            else:
                rows.append(
                    {
                        **serialize_finding_group_card(decorated),
                        "id": finding_id,
                        "novelty": decorated.get("novelty"),
                        "priority_score": decorated.get("priority_score"),
                        "priority_factors": decorated.get("priority_factors"),
                        "locations": decorated.get("locations"),
                    }
                )
        return rows

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
        health_delta = self._summary_health_delta(record.summary)
        return {
            "run_id": record.run_id,
            "changed_paths": list(record.changed_paths),
            "total": len(items),
            "new": new_count,
            "known": known_count,
            "items": items,
            "health": dict(self._as_mapping(record.summary.get("health"))),
            "health_delta": health_delta,
            "verdict": self._changed_verdict(
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
                    dict(self._as_mapping(item))
                    for item in self._as_sequence(changed_projection.get("items"))[:10]
                ],
            }
            payload["health_delta"] = _as_int(
                changed_projection.get("health_delta", 0),
                0,
            )
            payload["verdict"] = str(changed_projection.get("verdict", "stable"))
        return payload

    def _changed_verdict(
        self,
        *,
        changed_projection: Mapping[str, object],
        health_delta: int,
    ) -> str:
        if _as_int(changed_projection.get("new", 0), 0) > 0 or health_delta < 0:
            return "regressed"
        if _as_int(changed_projection.get("total", 0), 0) == 0 and health_delta > 0:
            return "improved"
        return "stable"

    def _comparison_index(
        self,
        record: MCPRunRecord,
        *,
        focus: ComparisonFocus,
    ) -> dict[str, dict[str, object]]:
        findings = self._base_findings(record)
        if focus == "clones":
            findings = [f for f in findings if str(f.get("family", "")) == FAMILY_CLONE]
        elif focus == "structural":
            findings = [
                f for f in findings if str(f.get("family", "")) == FAMILY_STRUCTURAL
            ]
        elif focus == "metrics":
            findings = [
                f
                for f in findings
                if str(f.get("family", "")) in {FAMILY_DESIGN, FAMILY_DEAD_CODE}
            ]
        return {str(finding.get("id", "")): dict(finding) for finding in findings}

    def _comparison_verdict(
        self,
        *,
        regressions: int,
        improvements: int,
        health_delta: int,
    ) -> str:
        if regressions > 0 or health_delta < 0:
            return "regressed"
        if improvements > 0 or health_delta > 0:
            return "improved"
        return "stable"

    def _comparison_summary_text(
        self,
        *,
        regressions: int,
        improvements: int,
        health_delta: int,
    ) -> str:
        return (
            f"{improvements} findings resolved, {regressions} new regressions, "
            f"health delta {health_delta:+d}"
        )

    def _render_pr_summary_markdown(self, payload: Mapping[str, object]) -> str:
        health = self._as_mapping(payload.get("health"))
        score = health.get("score", "n/a")
        grade = health.get("grade", "n/a")
        delta = _as_int(payload.get("health_delta", 0), 0)
        changed_items = [
            self._as_mapping(item)
            for item in self._as_sequence(payload.get("new_findings_in_changed_files"))
        ]
        resolved = [
            self._as_mapping(item)
            for item in self._as_sequence(payload.get("resolved"))
        ]
        blocking_gates = [
            str(item)
            for item in self._as_sequence(payload.get("blocking_gates"))
            if str(item)
        ]
        lines = [
            "## CodeClone Summary",
            "",
            (
                f"Health: {score}/100 ({grade}) | Delta: {delta:+d} | "
                f"Verdict: {payload.get('verdict', 'stable')}"
            ),
            "",
            f"### New findings in changed files ({len(changed_items)})",
        ]
        if not changed_items:
            lines.append("- None")
        else:
            lines.extend(
                [
                    (
                        f"- **{str(item.get('severity', 'info')).upper()}** "
                        f"{item.get('title', 'Finding')} in "
                        f"`{item.get('location', '(unknown)')}`"
                    )
                    for item in changed_items[:10]
                ]
            )
        lines.extend(["", f"### Resolved ({len(resolved)})"])
        if not resolved:
            lines.append("- None")
        else:
            lines.extend(
                [
                    (
                        f"- {item.get('title', 'Finding')} in "
                        f"`{item.get('location', '(unknown)')}`"
                    )
                    for item in resolved[:10]
                ]
            )
        lines.extend(["", "### Blocking gates"])
        if not blocking_gates:
            lines.append("- none")
        else:
            lines.extend([f"- `{reason}`" for reason in blocking_gates])
        return "\n".join(lines)

    def _granular_payload(
        self,
        *,
        record: MCPRunRecord,
        check: str,
        items: Sequence[Mapping[str, object]],
        detail_level: DetailLevel,
        max_results: int,
        path: str | None,
    ) -> dict[str, object]:
        bounded_items = [dict(item) for item in items[: max(1, max_results)]]
        return {
            "run_id": record.run_id,
            "check": check,
            "detail_level": detail_level,
            "path": path,
            "returned": len(bounded_items),
            "total": len(items),
            "health": dict(self._as_mapping(record.summary.get("health"))),
            "items": bounded_items,
        }

    def _schema_resource_payload(self) -> dict[str, object]:
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "CodeCloneCanonicalReport",
            "type": "object",
            "required": [
                "report_schema_version",
                "meta",
                "inventory",
                "findings",
                "derived",
                "integrity",
            ],
            "properties": {
                "report_schema_version": {
                    "type": "string",
                    "const": REPORT_SCHEMA_VERSION,
                },
                "meta": {"type": "object"},
                "inventory": {"type": "object"},
                "findings": {"type": "object"},
                "metrics": {"type": "object"},
                "derived": {"type": "object"},
                "integrity": {"type": "object"},
            },
        }

    def _validate_analysis_request(self, request: MCPAnalysisRequest) -> None:
        self._validate_choice(
            "analysis_mode",
            request.analysis_mode,
            _VALID_ANALYSIS_MODES,
        )
        self._validate_choice(
            "cache_policy",
            request.cache_policy,
            _VALID_CACHE_POLICIES,
        )
        if request.cache_policy == "refresh":
            raise MCPServiceContractError(
                "cache_policy='refresh' is not supported by the read-only "
                "CodeClone MCP server. Use 'reuse' or 'off'."
            )

    def _validate_choice(
        self,
        name: str,
        value: str,
        allowed: Sequence[str] | frozenset[str],
    ) -> str:
        if value not in allowed:
            allowed_list = ", ".join(sorted(allowed))
            raise MCPServiceContractError(
                f"Invalid value for {name}: {value!r}. Expected one of: {allowed_list}."
            )
        return value

    def _validate_optional_choice(
        self,
        name: str,
        value: str | None,
        allowed: Sequence[str] | frozenset[str],
    ) -> str | None:
        if value is None:
            return None
        return self._validate_choice(name, value, allowed)

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
            max_size_bytes=_as_int(args.max_cache_size_mb, 0) * 1024 * 1024,
            min_loc=_as_int(args.min_loc, DEFAULT_MIN_LOC),
            min_stmt=_as_int(args.min_stmt, DEFAULT_MIN_STMT),
            block_min_loc=_as_int(args.block_min_loc, DEFAULT_BLOCK_MIN_LOC),
            block_min_stmt=_as_int(args.block_min_stmt, DEFAULT_BLOCK_MIN_STMT),
            segment_min_loc=_as_int(args.segment_min_loc, DEFAULT_SEGMENT_MIN_LOC),
            segment_min_stmt=_as_int(
                args.segment_min_stmt,
                DEFAULT_SEGMENT_MIN_STMT,
            ),
        )
        if policy != "off":
            cache.load()
        return cache

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
        return _load_report_document_payload(report_json)

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
            "health_delta": _as_int(health_delta, 0),
        }

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
