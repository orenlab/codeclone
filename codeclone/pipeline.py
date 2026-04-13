# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import inspect
import os
from collections.abc import Mapping
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

import orjson

from ._coerce import as_int, as_str
from .cache import (
    ApiParamSpecDict,
    Cache,
    CacheEntry,
    ClassMetricsDict,
    DeadCandidateDict,
    FileStat,
    ModuleDepDict,
    PublicSymbolDict,
    SegmentReportProjection,
    SourceStatsDict,
    StructuralFindingGroupDict,
    file_stat_signature,
)
from .contracts import ExitCode
from .domain.findings import CATEGORY_COHESION, CATEGORY_COMPLEXITY, CATEGORY_COUPLING
from .domain.quality import CONFIDENCE_HIGH, RISK_HIGH, RISK_LOW
from .extractor import extract_units_and_stats_from_source
from .golden_fixtures import (
    build_suppressed_clone_groups,
    split_clone_groups_for_golden_fixtures,
)
from .grouping import build_block_groups, build_groups, build_segment_groups
from .metrics import (
    CoverageJoinParseError,
    HealthInputs,
    build_coverage_join,
    build_dep_graph,
    build_overloaded_modules_payload,
    compute_health,
    find_suppressed_unused,
    find_unused,
)
from .models import (
    ApiBreakingChange,
    ApiParamSpec,
    ApiSurfaceSnapshot,
    BlockUnit,
    ClassMetrics,
    CoverageJoinResult,
    DeadCandidate,
    DeadItem,
    DepGraph,
    FileMetrics,
    GroupItem,
    GroupItemLike,
    GroupMap,
    MetricsDiff,
    ModuleApiSurface,
    ModuleDep,
    ModuleDocstringCoverage,
    ModuleTypingCoverage,
    ProjectMetrics,
    PublicSymbol,
    SegmentUnit,
    StructuralFindingGroup,
    StructuralFindingOccurrence,
    Suggestion,
    SuppressedCloneGroup,
    Unit,
)
from .normalize import NormalizationConfig
from .paths import is_test_filepath
from .report.blocks import prepare_block_report_groups
from .report.explain import build_block_group_facts
from .report.json_contract import build_report_document
from .report.segments import prepare_segment_report_groups
from .report.serialize import render_json_report_document, render_text_report_document
from .report.suggestions import generate_suggestions
from .scanner import iter_py_files, module_name_from_path
from .structural_findings import build_clone_cohort_structural_findings
from .suppressions import DEAD_CODE_RULE_ID, INLINE_CODECLONE_SUPPRESSION_SOURCE

if TYPE_CHECKING:
    from argparse import Namespace
    from collections.abc import Callable, Collection, Mapping, Sequence

MAX_FILE_SIZE = 10 * 1024 * 1024
DEFAULT_BATCH_SIZE = 100
PARALLEL_MIN_FILES_PER_WORKER = 8
PARALLEL_MIN_FILES_FLOOR = 16
DEFAULT_RUNTIME_PROCESSES = 4

_as_int = as_int
_as_str = as_str


@dataclass(frozen=True, slots=True)
class OutputPaths:
    html: Path | None = None
    json: Path | None = None
    text: Path | None = None
    md: Path | None = None
    sarif: Path | None = None


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    root: Path
    config: NormalizationConfig
    args: Namespace
    output_paths: OutputPaths
    cache_path: Path


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    files_found: int
    cache_hits: int
    files_skipped: int
    all_file_paths: tuple[str, ...]
    cached_units: tuple[GroupItem, ...]
    cached_blocks: tuple[GroupItem, ...]
    cached_segments: tuple[GroupItem, ...]
    cached_class_metrics: tuple[ClassMetrics, ...]
    cached_module_deps: tuple[ModuleDep, ...]
    cached_dead_candidates: tuple[DeadCandidate, ...]
    cached_referenced_names: frozenset[str]
    files_to_process: tuple[str, ...]
    skipped_warnings: tuple[str, ...]
    cached_referenced_qualnames: frozenset[str] = frozenset()
    cached_typing_modules: tuple[ModuleTypingCoverage, ...] = ()
    cached_docstring_modules: tuple[ModuleDocstringCoverage, ...] = ()
    cached_api_modules: tuple[ModuleApiSurface, ...] = ()
    cached_structural_findings: tuple[StructuralFindingGroup, ...] = ()
    cached_segment_report_projection: SegmentReportProjection | None = None
    cached_lines: int = 0
    cached_functions: int = 0
    cached_methods: int = 0
    cached_classes: int = 0
    cached_source_stats_by_file: tuple[tuple[str, int, int, int, int], ...] = ()


@dataclass(frozen=True, slots=True)
class FileProcessResult:
    filepath: str
    success: bool
    error: str | None = None
    units: list[Unit] | None = None
    blocks: list[BlockUnit] | None = None
    segments: list[SegmentUnit] | None = None
    lines: int = 0
    functions: int = 0
    methods: int = 0
    classes: int = 0
    stat: FileStat | None = None
    error_kind: str | None = None
    file_metrics: FileMetrics | None = None
    structural_findings: list[StructuralFindingGroup] | None = None


@dataclass(frozen=True, slots=True)
class ProcessingResult:
    units: tuple[GroupItem, ...]
    blocks: tuple[GroupItem, ...]
    segments: tuple[GroupItem, ...]
    class_metrics: tuple[ClassMetrics, ...]
    module_deps: tuple[ModuleDep, ...]
    dead_candidates: tuple[DeadCandidate, ...]
    referenced_names: frozenset[str]
    files_analyzed: int
    files_skipped: int
    analyzed_lines: int
    analyzed_functions: int
    analyzed_methods: int
    analyzed_classes: int
    failed_files: tuple[str, ...]
    source_read_failures: tuple[str, ...]
    referenced_qualnames: frozenset[str] = frozenset()
    typing_modules: tuple[ModuleTypingCoverage, ...] = ()
    docstring_modules: tuple[ModuleDocstringCoverage, ...] = ()
    api_modules: tuple[ModuleApiSurface, ...] = ()
    structural_findings: tuple[StructuralFindingGroup, ...] = ()
    source_stats_by_file: tuple[tuple[str, int, int, int, int], ...] = ()


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    func_groups: GroupMap
    block_groups: GroupMap
    block_groups_report: GroupMap
    segment_groups: GroupMap
    suppressed_segment_groups: int
    block_group_facts: dict[str, dict[str, str]]
    func_clones_count: int
    block_clones_count: int
    segment_clones_count: int
    files_analyzed_or_cached: int
    project_metrics: ProjectMetrics | None
    metrics_payload: dict[str, object] | None
    suggestions: tuple[Suggestion, ...]
    segment_groups_raw_digest: str
    suppressed_clone_groups: tuple[SuppressedCloneGroup, ...] = ()
    coverage_join: CoverageJoinResult | None = None
    suppressed_dead_code_items: int = 0
    structural_findings: tuple[StructuralFindingGroup, ...] = ()


@dataclass(frozen=True, slots=True)
class GatingResult:
    exit_code: int
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReportArtifacts:
    html: str | None = None
    json: str | None = None
    text: str | None = None
    md: str | None = None
    sarif: str | None = None
    report_document: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class MetricGateConfig:
    fail_complexity: int
    fail_coupling: int
    fail_cohesion: int
    fail_cycles: bool
    fail_dead_code: bool
    fail_health: int
    fail_on_new_metrics: bool
    fail_on_typing_regression: bool = False
    fail_on_docstring_regression: bool = False
    fail_on_api_break: bool = False
    fail_on_untested_hotspots: bool = False
    min_typing_coverage: int = -1
    min_docstring_coverage: int = -1
    coverage_min: int = 50


def _as_sorted_str_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(sorted({item for item in value if isinstance(item, str) and item}))


def _group_item_sort_key(item: GroupItemLike) -> tuple[str, int, int, str]:
    return (
        _as_str(item.get("filepath")),
        _as_int(item.get("start_line")),
        _as_int(item.get("end_line")),
        _as_str(item.get("qualname")),
    )


def _segment_projection_item_sort_key(item: GroupItemLike) -> tuple[str, str, int, int]:
    return (
        _as_str(item.get("filepath")),
        _as_str(item.get("qualname")),
        _as_int(item.get("start_line")),
        _as_int(item.get("end_line")),
    )


def _segment_groups_digest(segment_groups: GroupMap) -> str:
    normalized_rows: list[
        tuple[str, tuple[tuple[str, str, int, int, int, str, str], ...]]
    ] = []
    for group_key in sorted(segment_groups):
        items = sorted(segment_groups[group_key], key=_segment_projection_item_sort_key)
        normalized_items: list[tuple[str, str, int, int, int, str, str]] = [
            (
                _as_str(item.get("filepath")),
                _as_str(item.get("qualname")),
                _as_int(item.get("start_line")),
                _as_int(item.get("end_line")),
                _as_int(item.get("size")),
                _as_str(item.get("segment_hash")),
                _as_str(item.get("segment_sig")),
            )
            for item in items
        ]
        normalized_rows.append((group_key, tuple(normalized_items)))
    payload = orjson.dumps(tuple(normalized_rows), option=orjson.OPT_SORT_KEYS)
    return sha256(payload).hexdigest()


def _coerce_segment_report_projection(
    value: object,
) -> SegmentReportProjection | None:
    if not isinstance(value, dict):
        return None
    digest = value.get("digest")
    suppressed = value.get("suppressed")
    groups = value.get("groups")
    if (
        not isinstance(digest, str)
        or not isinstance(suppressed, int)
        or not isinstance(groups, dict)
    ):
        return None
    if not all(
        isinstance(group_key, str) and isinstance(items, list)
        for group_key, items in groups.items()
    ):
        return None
    return cast("SegmentReportProjection", value)


def _module_dep_sort_key(dep: ModuleDep) -> tuple[str, str, str, int]:
    return dep.source, dep.target, dep.import_type, dep.line


def _class_metric_sort_key(metric: ClassMetrics) -> tuple[str, int, int, str]:
    return metric.filepath, metric.start_line, metric.end_line, metric.qualname


def _dead_candidate_sort_key(item: DeadCandidate) -> tuple[str, int, int, str]:
    return item.filepath, item.start_line, item.end_line, item.qualname


def _unit_to_group_item(unit: Unit) -> GroupItem:
    return {
        "qualname": unit.qualname,
        "filepath": unit.filepath,
        "start_line": unit.start_line,
        "end_line": unit.end_line,
        "loc": unit.loc,
        "stmt_count": unit.stmt_count,
        "fingerprint": unit.fingerprint,
        "loc_bucket": unit.loc_bucket,
        "cyclomatic_complexity": unit.cyclomatic_complexity,
        "nesting_depth": unit.nesting_depth,
        "risk": unit.risk,
        "raw_hash": unit.raw_hash,
        "entry_guard_count": unit.entry_guard_count,
        "entry_guard_terminal_profile": unit.entry_guard_terminal_profile,
        "entry_guard_has_side_effect_before": unit.entry_guard_has_side_effect_before,
        "terminal_kind": unit.terminal_kind,
        "try_finally_profile": unit.try_finally_profile,
        "side_effect_order_profile": unit.side_effect_order_profile,
    }


def _block_to_group_item(block: BlockUnit) -> GroupItem:
    return {
        "block_hash": block.block_hash,
        "filepath": block.filepath,
        "qualname": block.qualname,
        "start_line": block.start_line,
        "end_line": block.end_line,
        "size": block.size,
    }


def _segment_to_group_item(segment: SegmentUnit) -> GroupItem:
    return {
        "segment_hash": segment.segment_hash,
        "segment_sig": segment.segment_sig,
        "filepath": segment.filepath,
        "qualname": segment.qualname,
        "start_line": segment.start_line,
        "end_line": segment.end_line,
        "size": segment.size,
    }


def _parallel_min_files(processes: int) -> int:
    return max(PARALLEL_MIN_FILES_FLOOR, processes * PARALLEL_MIN_FILES_PER_WORKER)


def _resolve_process_count(processes: object) -> int:
    if processes is None:
        return DEFAULT_RUNTIME_PROCESSES
    return max(1, _as_int(processes, DEFAULT_RUNTIME_PROCESSES))


def _should_collect_structural_findings(output_paths: OutputPaths) -> bool:
    return any(
        path is not None
        for path in (
            output_paths.html,
            output_paths.json,
            output_paths.md,
            output_paths.sarif,
            output_paths.text,
        )
    )


def _should_use_parallel(files_count: int, processes: int) -> bool:
    if processes <= 1:
        return False
    return files_count >= _parallel_min_files(processes)


def _new_discovery_buffers() -> tuple[
    list[GroupItem],
    list[GroupItem],
    list[GroupItem],
    list[ClassMetrics],
    list[ModuleDep],
    list[DeadCandidate],
    set[str],
    set[str],
    list[ModuleTypingCoverage],
    list[ModuleDocstringCoverage],
    list[ModuleApiSurface],
    list[str],
    list[str],
]:
    return [], [], [], [], [], [], set(), set(), [], [], [], [], []


def _decode_cached_structural_finding_group(
    group_dict: StructuralFindingGroupDict,
    filepath: str,
) -> StructuralFindingGroup:
    """Convert a StructuralFindingGroupDict (from cache) to a StructuralFindingGroup."""
    finding_kind = group_dict["finding_kind"]
    finding_key = group_dict["finding_key"]
    signature = group_dict["signature"]
    items = tuple(
        StructuralFindingOccurrence(
            finding_kind=finding_kind,
            finding_key=finding_key,
            file_path=filepath,
            qualname=item["qualname"],
            start=item["start"],
            end=item["end"],
            signature=signature,
        )
        for item in group_dict["items"]
    )
    return StructuralFindingGroup(
        finding_kind=finding_kind,
        finding_key=finding_key,
        signature=signature,
        items=items,
    )


def bootstrap(
    *,
    args: Namespace,
    root: Path,
    output_paths: OutputPaths,
    cache_path: Path,
) -> BootstrapResult:
    return BootstrapResult(
        root=root,
        config=NormalizationConfig(),
        args=args,
        output_paths=output_paths,
        cache_path=cache_path,
    )


def _resolve_optional_runtime_path(value: object, *, root: Path) -> Path | None:
    text = str(value).strip() if value is not None else ""
    if not text:
        return None
    candidate = Path(text).expanduser()
    resolved = candidate if candidate.is_absolute() else root / candidate
    try:
        return resolved.resolve()
    except OSError:
        return resolved.absolute()


def _cache_entry_has_metrics(entry: CacheEntry) -> bool:
    metric_keys = (
        "class_metrics",
        "module_deps",
        "dead_candidates",
        "referenced_names",
        "referenced_qualnames",
        "import_names",
        "class_names",
    )
    return all(key in entry and isinstance(entry.get(key), list) for key in metric_keys)


def _cache_entry_has_structural_findings(entry: CacheEntry) -> bool:
    return "structural_findings" in entry


def _cache_entry_source_stats(entry: CacheEntry) -> tuple[int, int, int, int] | None:
    stats_obj = entry.get("source_stats")
    if not isinstance(stats_obj, dict):
        return None
    lines = stats_obj.get("lines")
    functions = stats_obj.get("functions")
    methods = stats_obj.get("methods")
    classes = stats_obj.get("classes")
    if not (
        isinstance(lines, int)
        and isinstance(functions, int)
        and isinstance(methods, int)
        and isinstance(classes, int)
        and lines >= 0
        and functions >= 0
        and methods >= 0
        and classes >= 0
    ):
        return None
    return lines, functions, methods, classes


def _usable_cached_source_stats(
    entry: CacheEntry,
    *,
    skip_metrics: bool,
    collect_structural_findings: bool,
) -> tuple[int, int, int, int] | None:
    if not skip_metrics and not _cache_entry_has_metrics(entry):
        return None
    if collect_structural_findings and not _cache_entry_has_structural_findings(entry):
        return None
    return _cache_entry_source_stats(entry)


def _cache_dict_module_fields(
    value: object,
) -> tuple[Mapping[str, object], str, str] | None:
    if not isinstance(value, dict):
        return None
    row = cast("Mapping[str, object]", value)
    module = row.get("module")
    filepath = row.get("filepath")
    if not isinstance(module, str) or not isinstance(filepath, str):
        return None
    return row, module, filepath


def _cache_dict_int_fields(
    row: Mapping[str, object],
    *keys: str,
) -> tuple[int, ...] | None:
    values: list[int] = []
    for key in keys:
        value = row.get(key)
        if not isinstance(value, int):
            return None
        values.append(value)
    return tuple(values)


def _typing_coverage_from_cache_dict(
    value: object,
) -> ModuleTypingCoverage | None:
    row_info = _cache_dict_module_fields(value)
    if row_info is None:
        return None
    row, module, filepath = row_info
    int_fields = _cache_dict_int_fields(
        row,
        "callable_count",
        "params_total",
        "params_annotated",
        "returns_total",
        "returns_annotated",
        "any_annotation_count",
    )
    if int_fields is None:
        return None
    (
        callable_count,
        params_total,
        params_annotated,
        returns_total,
        returns_annotated,
        any_annotation_count,
    ) = int_fields
    return ModuleTypingCoverage(
        module=module,
        filepath=filepath,
        callable_count=callable_count,
        params_total=params_total,
        params_annotated=params_annotated,
        returns_total=returns_total,
        returns_annotated=returns_annotated,
        any_annotation_count=any_annotation_count,
    )


def _docstring_coverage_from_cache_dict(
    value: object,
) -> ModuleDocstringCoverage | None:
    row_info = _cache_dict_module_fields(value)
    if row_info is None:
        return None
    row, module, filepath = row_info
    totals = _cache_dict_int_fields(
        row,
        "public_symbol_total",
        "public_symbol_documented",
    )
    if totals is None:
        return None
    public_symbol_total, public_symbol_documented = totals
    return ModuleDocstringCoverage(
        module=module,
        filepath=filepath,
        public_symbol_total=public_symbol_total,
        public_symbol_documented=public_symbol_documented,
    )


def _api_param_spec_from_cache_dict(value: ApiParamSpecDict) -> ApiParamSpec | None:
    name = value.get("name")
    kind = value.get("kind")
    has_default = value.get("has_default")
    annotation_hash = value.get("annotation_hash", "")
    if (
        not isinstance(name, str)
        or not isinstance(kind, str)
        or not isinstance(has_default, bool)
        or not isinstance(annotation_hash, str)
    ):
        return None
    return ApiParamSpec(
        name=name,
        kind=cast(
            "Literal['pos_only', 'pos_or_kw', 'vararg', 'kw_only', 'kwarg']",
            kind,
        ),
        has_default=has_default,
        annotation_hash=annotation_hash,
    )


def _public_symbol_from_cache_dict(
    value: PublicSymbolDict,
) -> PublicSymbol | None:
    qualname = value.get("qualname")
    kind = value.get("kind")
    start_line = value.get("start_line")
    end_line = value.get("end_line")
    exported_via = value.get("exported_via", "name")
    returns_hash = value.get("returns_hash", "")
    params_raw = value.get("params", [])
    if (
        not isinstance(qualname, str)
        or not isinstance(kind, str)
        or not isinstance(start_line, int)
        or not isinstance(end_line, int)
        or not isinstance(exported_via, str)
        or not isinstance(returns_hash, str)
        or not isinstance(params_raw, list)
    ):
        return None
    params = []
    for param in params_raw:
        if not isinstance(param, dict):
            return None
        parsed = _api_param_spec_from_cache_dict(param)
        if parsed is None:
            return None
        params.append(parsed)
    return PublicSymbol(
        qualname=qualname,
        kind=cast("Literal['function', 'class', 'method', 'constant']", kind),
        start_line=start_line,
        end_line=end_line,
        params=tuple(params),
        returns_hash=returns_hash,
        exported_via=cast("Literal['all', 'name']", exported_via),
    )


def _api_surface_from_cache_dict(value: object) -> ModuleApiSurface | None:
    row_info = _cache_dict_module_fields(value)
    if row_info is None:
        return None
    row, module, filepath = row_info
    all_declared_raw = row.get("all_declared", [])
    symbols_raw = row.get("symbols", [])
    if (
        not isinstance(all_declared_raw, list)
        or not isinstance(symbols_raw, list)
        or not all(isinstance(item, str) for item in all_declared_raw)
    ):
        return None
    symbols: list[PublicSymbol] = []
    for item in symbols_raw:
        if not isinstance(item, dict):
            return None
        parsed = _public_symbol_from_cache_dict(cast("PublicSymbolDict", item))
        if parsed is None:
            return None
        symbols.append(parsed)
    return ModuleApiSurface(
        module=module,
        filepath=filepath,
        all_declared=tuple(sorted(set(all_declared_raw))) or None,
        symbols=tuple(sorted(symbols, key=lambda item: item.qualname)),
    )


def _load_cached_metrics_extended(
    entry: CacheEntry,
    *,
    filepath: str,
) -> tuple[
    tuple[ClassMetrics, ...],
    tuple[ModuleDep, ...],
    tuple[DeadCandidate, ...],
    frozenset[str],
    frozenset[str],
    ModuleTypingCoverage | None,
    ModuleDocstringCoverage | None,
    ModuleApiSurface | None,
]:
    class_metrics_rows: list[ClassMetricsDict] = entry.get("class_metrics", [])
    class_metrics = tuple(
        ClassMetrics(
            qualname=row["qualname"],
            filepath=row["filepath"],
            start_line=row["start_line"],
            end_line=row["end_line"],
            cbo=row["cbo"],
            lcom4=row["lcom4"],
            method_count=row["method_count"],
            instance_var_count=row["instance_var_count"],
            risk_coupling=cast(
                "Literal['low', 'medium', 'high']",
                row["risk_coupling"],
            ),
            risk_cohesion=cast(
                "Literal['low', 'medium', 'high']",
                row["risk_cohesion"],
            ),
            coupled_classes=_as_sorted_str_tuple(row.get("coupled_classes", [])),
        )
        for row in class_metrics_rows
        if row.get("qualname") and row.get("filepath")
    )

    module_dep_rows: list[ModuleDepDict] = entry.get("module_deps", [])
    module_deps = tuple(
        ModuleDep(
            source=row["source"],
            target=row["target"],
            import_type=cast("Literal['import', 'from_import']", row["import_type"]),
            line=row["line"],
        )
        for row in module_dep_rows
        if row.get("source") and row.get("target")
    )

    dead_rows: list[DeadCandidateDict] = entry.get("dead_candidates", [])
    dead_candidates = tuple(
        DeadCandidate(
            qualname=row["qualname"],
            local_name=row["local_name"],
            filepath=row["filepath"],
            start_line=row["start_line"],
            end_line=row["end_line"],
            kind=cast(
                "Literal['function', 'class', 'method', 'import']",
                row["kind"],
            ),
            suppressed_rules=tuple(sorted(set(row.get("suppressed_rules", [])))),
        )
        for row in dead_rows
        if row.get("qualname") and row.get("local_name") and row.get("filepath")
    )

    referenced_names = (
        frozenset()
        if is_test_filepath(filepath)
        else frozenset(entry.get("referenced_names", []))
    )
    referenced_qualnames = (
        frozenset()
        if is_test_filepath(filepath)
        else frozenset(entry.get("referenced_qualnames", []))
    )
    typing_coverage = _typing_coverage_from_cache_dict(entry.get("typing_coverage"))
    docstring_coverage = _docstring_coverage_from_cache_dict(
        entry.get("docstring_coverage")
    )
    api_surface = _api_surface_from_cache_dict(entry.get("api_surface"))
    return (
        class_metrics,
        module_deps,
        dead_candidates,
        referenced_names,
        referenced_qualnames,
        typing_coverage,
        docstring_coverage,
        api_surface,
    )


def discover(*, boot: BootstrapResult, cache: Cache) -> DiscoveryResult:
    files_found = 0
    cache_hits = 0
    files_skipped = 0
    collect_structural_findings = _should_collect_structural_findings(boot.output_paths)
    cached_segment_projection = _coerce_segment_report_projection(
        getattr(cache, "segment_report_projection", None)
    )

    (
        cached_units,
        cached_blocks,
        cached_segments,
        cached_class_metrics,
        cached_module_deps,
        cached_dead_candidates,
        cached_referenced_names,
        cached_referenced_qualnames,
        cached_typing_modules,
        cached_docstring_modules,
        cached_api_modules,
        files_to_process,
        skipped_warnings,
    ) = _new_discovery_buffers()
    cached_sf: list[StructuralFindingGroup] = []
    cached_source_stats_by_file: list[tuple[str, int, int, int, int]] = []
    cached_lines = 0
    cached_functions = 0
    cached_methods = 0
    cached_classes = 0
    all_file_paths: list[str] = []

    for filepath in iter_py_files(str(boot.root)):
        files_found += 1
        all_file_paths.append(filepath)
        try:
            stat = file_stat_signature(filepath)
        except OSError as exc:
            files_skipped += 1
            skipped_warnings.append(f"{filepath}: {exc}")
            continue

        cached = cache.get_file_entry(filepath)
        if cached and cached.get("stat") == stat:
            cached_source_stats = _usable_cached_source_stats(
                cached,
                skip_metrics=boot.args.skip_metrics,
                collect_structural_findings=collect_structural_findings,
            )
            if cached_source_stats is None:
                files_to_process.append(filepath)
                continue

            cache_hits += 1
            lines, functions, methods, classes = cached_source_stats
            cached_lines += lines
            cached_functions += functions
            cached_methods += methods
            cached_classes += classes
            cached_source_stats_by_file.append(
                (filepath, lines, functions, methods, classes)
            )
            cached_units.extend(cast("list[GroupItem]", cast(object, cached["units"])))
            cached_blocks.extend(
                cast("list[GroupItem]", cast(object, cached["blocks"]))
            )
            cached_segments.extend(
                cast("list[GroupItem]", cast(object, cached["segments"]))
            )

            if not boot.args.skip_metrics:
                (
                    class_metrics,
                    module_deps,
                    dead_candidates,
                    referenced_names,
                    referenced_qualnames,
                    typing_coverage,
                    docstring_coverage,
                    api_surface,
                ) = _load_cached_metrics_extended(cached, filepath=filepath)
                cached_class_metrics.extend(class_metrics)
                cached_module_deps.extend(module_deps)
                cached_dead_candidates.extend(dead_candidates)
                cached_referenced_names.update(referenced_names)
                cached_referenced_qualnames.update(referenced_qualnames)
                if typing_coverage is not None:
                    cached_typing_modules.append(typing_coverage)
                if docstring_coverage is not None:
                    cached_docstring_modules.append(docstring_coverage)
                if api_surface is not None:
                    cached_api_modules.append(api_surface)
            if collect_structural_findings:
                cached_sf.extend(
                    _decode_cached_structural_finding_group(group_dict, filepath)
                    for group_dict in cached.get("structural_findings") or []
                )
            continue

        files_to_process.append(filepath)

    return DiscoveryResult(
        files_found=files_found,
        cache_hits=cache_hits,
        files_skipped=files_skipped,
        all_file_paths=tuple(all_file_paths),
        cached_units=tuple(sorted(cached_units, key=_group_item_sort_key)),
        cached_blocks=tuple(sorted(cached_blocks, key=_group_item_sort_key)),
        cached_segments=tuple(sorted(cached_segments, key=_group_item_sort_key)),
        cached_class_metrics=tuple(
            sorted(cached_class_metrics, key=_class_metric_sort_key)
        ),
        cached_module_deps=tuple(sorted(cached_module_deps, key=_module_dep_sort_key)),
        cached_dead_candidates=tuple(
            sorted(cached_dead_candidates, key=_dead_candidate_sort_key)
        ),
        cached_referenced_names=frozenset(cached_referenced_names),
        cached_referenced_qualnames=frozenset(cached_referenced_qualnames),
        cached_typing_modules=tuple(
            sorted(cached_typing_modules, key=lambda item: (item.filepath, item.module))
        ),
        cached_docstring_modules=tuple(
            sorted(
                cached_docstring_modules,
                key=lambda item: (item.filepath, item.module),
            )
        ),
        cached_api_modules=tuple(
            sorted(cached_api_modules, key=lambda item: (item.filepath, item.module))
        ),
        files_to_process=tuple(files_to_process),
        skipped_warnings=tuple(sorted(skipped_warnings)),
        cached_structural_findings=tuple(cached_sf),
        cached_segment_report_projection=cached_segment_projection,
        cached_lines=cached_lines,
        cached_functions=cached_functions,
        cached_methods=cached_methods,
        cached_classes=cached_classes,
        cached_source_stats_by_file=tuple(
            sorted(cached_source_stats_by_file, key=lambda row: row[0])
        ),
    )


def process_file(
    filepath: str,
    root: str,
    cfg: NormalizationConfig,
    min_loc: int,
    min_stmt: int,
    collect_structural_findings: bool = True,
    collect_typing_coverage: bool = True,
    collect_docstring_coverage: bool = True,
    collect_api_surface: bool = False,
    api_include_private_modules: bool = False,
    block_min_loc: int = 20,
    block_min_stmt: int = 8,
    segment_min_loc: int = 20,
    segment_min_stmt: int = 10,
) -> FileProcessResult:
    try:
        try:
            stat_result = os.stat(filepath)
            if stat_result.st_size > MAX_FILE_SIZE:
                return FileProcessResult(
                    filepath=filepath,
                    success=False,
                    error=(
                        f"File too large: {stat_result.st_size} bytes "
                        f"(max {MAX_FILE_SIZE})"
                    ),
                    error_kind="file_too_large",
                )
        except OSError as exc:
            return FileProcessResult(
                filepath=filepath,
                success=False,
                error=f"Cannot stat file: {exc}",
                error_kind="stat_error",
            )

        stat: FileStat = {
            "mtime_ns": stat_result.st_mtime_ns,
            "size": stat_result.st_size,
        }

        try:
            source = Path(filepath).read_text("utf-8")
        except UnicodeDecodeError as exc:
            return FileProcessResult(
                filepath=filepath,
                success=False,
                error=f"Encoding error: {exc}",
                error_kind="source_read_error",
            )
        except OSError as exc:
            return FileProcessResult(
                filepath=filepath,
                success=False,
                error=f"Cannot read file: {exc}",
                error_kind="source_read_error",
            )

        module_name = module_name_from_path(root, filepath)
        units, blocks, segments, source_stats, file_metrics, sf = (
            extract_units_and_stats_from_source(
                source=source,
                filepath=filepath,
                module_name=module_name,
                cfg=cfg,
                min_loc=min_loc,
                min_stmt=min_stmt,
                block_min_loc=block_min_loc,
                block_min_stmt=block_min_stmt,
                segment_min_loc=segment_min_loc,
                segment_min_stmt=segment_min_stmt,
                collect_structural_findings=collect_structural_findings,
                collect_typing_coverage=collect_typing_coverage,
                collect_docstring_coverage=collect_docstring_coverage,
                collect_api_surface=collect_api_surface,
                api_include_private_modules=api_include_private_modules,
            )
        )

        return FileProcessResult(
            filepath=filepath,
            success=True,
            units=units,
            blocks=blocks,
            segments=segments,
            lines=source_stats.lines,
            functions=source_stats.functions,
            methods=source_stats.methods,
            classes=source_stats.classes,
            stat=stat,
            file_metrics=file_metrics,
            structural_findings=sf,
        )
    except Exception as exc:  # pragma: no cover - defensive shell around workers
        return FileProcessResult(
            filepath=filepath,
            success=False,
            error=f"Unexpected error: {type(exc).__name__}: {exc}",
            error_kind="unexpected_error",
        )


def _invoke_process_file(
    filepath: str,
    root: str,
    cfg: NormalizationConfig,
    min_loc: int,
    min_stmt: int,
    *,
    collect_structural_findings: bool,
    collect_typing_coverage: bool,
    collect_docstring_coverage: bool,
    collect_api_surface: bool,
    api_include_private_modules: bool,
    block_min_loc: int,
    block_min_stmt: int,
    segment_min_loc: int,
    segment_min_stmt: int,
) -> FileProcessResult:
    optional_kwargs: dict[str, object] = {
        "collect_structural_findings": collect_structural_findings,
        "collect_typing_coverage": collect_typing_coverage,
        "collect_docstring_coverage": collect_docstring_coverage,
        "collect_api_surface": collect_api_surface,
        "api_include_private_modules": api_include_private_modules,
        "block_min_loc": block_min_loc,
        "block_min_stmt": block_min_stmt,
        "segment_min_loc": segment_min_loc,
        "segment_min_stmt": segment_min_stmt,
    }
    try:
        signature = inspect.signature(process_file)
    except (TypeError, ValueError):
        supported_kwargs = optional_kwargs
    else:
        parameters = tuple(signature.parameters.values())
        if any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters
        ):
            supported_kwargs = optional_kwargs
        else:
            supported_names = {parameter.name for parameter in parameters}
            supported_kwargs = {
                key: value
                for key, value in optional_kwargs.items()
                if key in supported_names
            }
    process_callable = cast("Callable[..., FileProcessResult]", process_file)
    return process_callable(
        filepath,
        root,
        cfg,
        min_loc,
        min_stmt,
        **supported_kwargs,
    )


def process(
    *,
    boot: BootstrapResult,
    discovery: DiscoveryResult,
    cache: Cache,
    on_advance: Callable[[], None] | None = None,
    on_worker_error: Callable[[str], None] | None = None,
    on_parallel_fallback: Callable[[Exception], None] | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> ProcessingResult:
    files_to_process = discovery.files_to_process
    if not files_to_process:
        return ProcessingResult(
            units=discovery.cached_units,
            blocks=discovery.cached_blocks,
            segments=discovery.cached_segments,
            class_metrics=discovery.cached_class_metrics,
            module_deps=discovery.cached_module_deps,
            dead_candidates=discovery.cached_dead_candidates,
            referenced_names=discovery.cached_referenced_names,
            referenced_qualnames=discovery.cached_referenced_qualnames,
            typing_modules=discovery.cached_typing_modules,
            docstring_modules=discovery.cached_docstring_modules,
            api_modules=discovery.cached_api_modules,
            files_analyzed=0,
            files_skipped=discovery.files_skipped,
            analyzed_lines=0,
            analyzed_functions=0,
            analyzed_methods=0,
            analyzed_classes=0,
            failed_files=(),
            source_read_failures=(),
            structural_findings=discovery.cached_structural_findings,
            source_stats_by_file=discovery.cached_source_stats_by_file,
        )

    all_units: list[GroupItem] = list(discovery.cached_units)
    all_blocks: list[GroupItem] = list(discovery.cached_blocks)
    all_segments: list[GroupItem] = list(discovery.cached_segments)

    all_class_metrics: list[ClassMetrics] = list(discovery.cached_class_metrics)
    all_module_deps: list[ModuleDep] = list(discovery.cached_module_deps)
    all_dead_candidates: list[DeadCandidate] = list(discovery.cached_dead_candidates)
    all_referenced_names: set[str] = set(discovery.cached_referenced_names)
    all_referenced_qualnames: set[str] = set(discovery.cached_referenced_qualnames)
    all_typing_modules: list[ModuleTypingCoverage] = list(
        discovery.cached_typing_modules
    )
    all_docstring_modules: list[ModuleDocstringCoverage] = list(
        discovery.cached_docstring_modules
    )
    all_api_modules: list[ModuleApiSurface] = list(discovery.cached_api_modules)
    collect_structural_findings = _should_collect_structural_findings(boot.output_paths)
    collect_typing_coverage = not boot.args.skip_metrics and bool(
        getattr(boot.args, "typing_coverage", True)
    )
    collect_docstring_coverage = not boot.args.skip_metrics and bool(
        getattr(boot.args, "docstring_coverage", True)
    )
    collect_api_surface = not boot.args.skip_metrics and bool(
        getattr(boot.args, "api_surface", False)
    )
    api_include_private_modules = bool(
        getattr(boot.args, "api_include_private_modules", False)
    )

    files_analyzed = 0
    files_skipped = discovery.files_skipped
    analyzed_lines = 0
    analyzed_functions = 0
    analyzed_methods = 0
    analyzed_classes = 0

    all_structural_findings: list[StructuralFindingGroup] = list(
        discovery.cached_structural_findings
    )
    source_stats_by_file: dict[str, tuple[int, int, int, int]] = {
        filepath: (lines, functions, methods, classes)
        for filepath, lines, functions, methods, classes in (
            discovery.cached_source_stats_by_file
        )
    }
    failed_files: list[str] = []
    source_read_failures: list[str] = []
    root_str = str(boot.root)
    # Keep process-count fallback in the core runtime so non-CLI callers such as
    # the MCP service do not need to guess or mirror parallelism policy.
    processes = _resolve_process_count(boot.args.processes)
    min_loc = int(boot.args.min_loc)
    min_stmt = int(boot.args.min_stmt)
    block_min_loc = int(boot.args.block_min_loc)
    block_min_stmt = int(boot.args.block_min_stmt)
    segment_min_loc = int(boot.args.segment_min_loc)
    segment_min_stmt = int(boot.args.segment_min_stmt)
    collect_structural_findings = _should_collect_structural_findings(boot.output_paths)

    def _accept_result(result: FileProcessResult) -> None:
        nonlocal files_analyzed
        nonlocal files_skipped
        nonlocal analyzed_lines
        nonlocal analyzed_functions
        nonlocal analyzed_methods
        nonlocal analyzed_classes

        if result.success and result.stat is not None:
            source_stats_payload = SourceStatsDict(
                lines=result.lines,
                functions=result.functions,
                methods=result.methods,
                classes=result.classes,
            )
            structural_payload = (
                result.structural_findings if collect_structural_findings else None
            )
            try:
                cache.put_file_entry(
                    result.filepath,
                    result.stat,
                    result.units or [],
                    result.blocks or [],
                    result.segments or [],
                    source_stats=source_stats_payload,
                    file_metrics=result.file_metrics,
                    structural_findings=structural_payload,
                )
            except TypeError as exc:
                if "source_stats" not in str(exc):
                    raise
                cache.put_file_entry(
                    result.filepath,
                    result.stat,
                    result.units or [],
                    result.blocks or [],
                    result.segments or [],
                    file_metrics=result.file_metrics,
                    structural_findings=structural_payload,
                )
            files_analyzed += 1
            analyzed_lines += result.lines
            analyzed_functions += result.functions
            analyzed_methods += result.methods
            analyzed_classes += result.classes
            source_stats_by_file[result.filepath] = (
                result.lines,
                result.functions,
                result.methods,
                result.classes,
            )

            if result.units:
                all_units.extend(_unit_to_group_item(unit) for unit in result.units)
            if result.blocks:
                all_blocks.extend(
                    _block_to_group_item(block) for block in result.blocks
                )
            if result.segments:
                all_segments.extend(
                    _segment_to_group_item(segment) for segment in result.segments
                )
            if result.structural_findings:
                all_structural_findings.extend(result.structural_findings)

            if not boot.args.skip_metrics and result.file_metrics is not None:
                all_class_metrics.extend(result.file_metrics.class_metrics)
                all_module_deps.extend(result.file_metrics.module_deps)
                all_dead_candidates.extend(result.file_metrics.dead_candidates)
                all_referenced_names.update(result.file_metrics.referenced_names)
                all_referenced_qualnames.update(
                    result.file_metrics.referenced_qualnames
                )
                if result.file_metrics.typing_coverage is not None:
                    all_typing_modules.append(result.file_metrics.typing_coverage)
                if result.file_metrics.docstring_coverage is not None:
                    all_docstring_modules.append(result.file_metrics.docstring_coverage)
                if result.file_metrics.api_surface is not None:
                    all_api_modules.append(result.file_metrics.api_surface)
            return

        files_skipped += 1
        failure = f"{result.filepath}: {result.error}"
        failed_files.append(failure)
        if result.error_kind == "source_read_error":
            source_read_failures.append(failure)

    def _run_sequential(files: Sequence[str]) -> None:
        for filepath in files:
            _accept_result(
                _invoke_process_file(
                    filepath,
                    root_str,
                    boot.config,
                    min_loc,
                    min_stmt,
                    collect_structural_findings=collect_structural_findings,
                    collect_typing_coverage=collect_typing_coverage,
                    collect_docstring_coverage=collect_docstring_coverage,
                    collect_api_surface=collect_api_surface,
                    api_include_private_modules=api_include_private_modules,
                    block_min_loc=block_min_loc,
                    block_min_stmt=block_min_stmt,
                    segment_min_loc=segment_min_loc,
                    segment_min_stmt=segment_min_stmt,
                )
            )
            if on_advance is not None:
                on_advance()

    if _should_use_parallel(len(files_to_process), processes):
        try:
            with ProcessPoolExecutor(max_workers=processes) as executor:
                for idx in range(0, len(files_to_process), batch_size):
                    batch = files_to_process[idx : idx + batch_size]
                    futures = [
                        executor.submit(
                            _invoke_process_file,
                            filepath,
                            root_str,
                            boot.config,
                            min_loc,
                            min_stmt,
                            collect_structural_findings=collect_structural_findings,
                            collect_typing_coverage=collect_typing_coverage,
                            collect_docstring_coverage=collect_docstring_coverage,
                            collect_api_surface=collect_api_surface,
                            api_include_private_modules=api_include_private_modules,
                            block_min_loc=block_min_loc,
                            block_min_stmt=block_min_stmt,
                            segment_min_loc=segment_min_loc,
                            segment_min_stmt=segment_min_stmt,
                        )
                        for filepath in batch
                    ]
                    future_to_path = {
                        id(future): filepath
                        for future, filepath in zip(futures, batch, strict=True)
                    }
                    for future in as_completed(futures):
                        filepath = future_to_path[id(future)]
                        try:
                            _accept_result(future.result())
                        except Exception as exc:  # pragma: no cover - worker crash
                            files_skipped += 1
                            failed_files.append(f"{filepath}: {exc}")
                            if on_worker_error is not None:
                                on_worker_error(str(exc))
                        if on_advance is not None:
                            on_advance()
        except (OSError, RuntimeError, PermissionError) as exc:
            if on_parallel_fallback is not None:
                on_parallel_fallback(exc)
            _run_sequential(files_to_process)
    else:
        _run_sequential(files_to_process)

    return ProcessingResult(
        units=tuple(sorted(all_units, key=_group_item_sort_key)),
        blocks=tuple(sorted(all_blocks, key=_group_item_sort_key)),
        segments=tuple(sorted(all_segments, key=_group_item_sort_key)),
        class_metrics=tuple(sorted(all_class_metrics, key=_class_metric_sort_key)),
        module_deps=tuple(sorted(all_module_deps, key=_module_dep_sort_key)),
        dead_candidates=tuple(
            sorted(all_dead_candidates, key=_dead_candidate_sort_key)
        ),
        referenced_names=frozenset(all_referenced_names),
        referenced_qualnames=frozenset(all_referenced_qualnames),
        typing_modules=tuple(
            sorted(all_typing_modules, key=lambda item: (item.filepath, item.module))
        ),
        docstring_modules=tuple(
            sorted(all_docstring_modules, key=lambda item: (item.filepath, item.module))
        ),
        api_modules=tuple(
            sorted(all_api_modules, key=lambda item: (item.filepath, item.module))
        ),
        files_analyzed=files_analyzed,
        files_skipped=files_skipped,
        analyzed_lines=analyzed_lines,
        analyzed_functions=analyzed_functions,
        analyzed_methods=analyzed_methods,
        analyzed_classes=analyzed_classes,
        failed_files=tuple(sorted(failed_files)),
        source_read_failures=tuple(sorted(source_read_failures)),
        structural_findings=tuple(all_structural_findings),
        source_stats_by_file=tuple(
            (filepath, *stats)
            for filepath, stats in sorted(source_stats_by_file.items())
        ),
    )


def _module_names_from_units(units: Sequence[GroupItemLike]) -> frozenset[str]:
    modules: set[str] = set()
    for unit in units:
        qualname = _as_str(unit.get("qualname"))
        module_name = qualname.split(":", 1)[0] if ":" in qualname else qualname
        if module_name:
            modules.add(module_name)
    return frozenset(sorted(modules))


def compute_project_metrics(
    *,
    units: Sequence[GroupItemLike],
    class_metrics: Sequence[ClassMetrics],
    module_deps: Sequence[ModuleDep],
    dead_candidates: Sequence[DeadCandidate],
    referenced_names: frozenset[str],
    referenced_qualnames: frozenset[str],
    typing_modules: Sequence[ModuleTypingCoverage] = (),
    docstring_modules: Sequence[ModuleDocstringCoverage] = (),
    api_modules: Sequence[ModuleApiSurface] = (),
    files_found: int,
    files_analyzed_or_cached: int,
    function_clone_groups: int,
    block_clone_groups: int,
    skip_dependencies: bool,
    skip_dead_code: bool,
) -> tuple[ProjectMetrics, DepGraph, tuple[DeadItem, ...]]:
    unit_rows = sorted(units, key=_group_item_sort_key)
    complexities = tuple(
        max(1, _as_int(row.get("cyclomatic_complexity"), 1)) for row in unit_rows
    )
    complexity_max = max(complexities) if complexities else 0
    complexity_avg = (
        float(sum(complexities)) / float(len(complexities)) if complexities else 0.0
    )
    high_risk_functions = tuple(
        sorted(
            {
                _as_str(row.get("qualname"))
                for row in unit_rows
                if _as_str(row.get("risk")) == RISK_HIGH
            }
        )
    )

    classes_sorted = tuple(sorted(class_metrics, key=_class_metric_sort_key))
    coupling_values = tuple(metric.cbo for metric in classes_sorted)
    coupling_max = max(coupling_values) if coupling_values else 0
    coupling_avg = (
        float(sum(coupling_values)) / float(len(coupling_values))
        if coupling_values
        else 0.0
    )
    high_risk_classes = tuple(
        sorted(
            {
                metric.qualname
                for metric in classes_sorted
                if metric.risk_coupling == RISK_HIGH
            }
        )
    )

    cohesion_values = tuple(metric.lcom4 for metric in classes_sorted)
    cohesion_max = max(cohesion_values) if cohesion_values else 0
    cohesion_avg = (
        float(sum(cohesion_values)) / float(len(cohesion_values))
        if cohesion_values
        else 0.0
    )
    low_cohesion_classes = tuple(
        sorted(
            {
                metric.qualname
                for metric in classes_sorted
                if metric.risk_cohesion == RISK_HIGH
            }
        )
    )

    dep_graph = DepGraph(
        modules=frozenset(),
        edges=(),
        cycles=(),
        max_depth=0,
        longest_chains=(),
    )
    if not skip_dependencies:
        dep_graph = build_dep_graph(
            modules=_module_names_from_units(unit_rows),
            deps=module_deps,
        )

    dead_items: tuple[DeadItem, ...] = ()
    if not skip_dead_code:
        dead_items = find_unused(
            definitions=tuple(dead_candidates),
            referenced_names=referenced_names,
            referenced_qualnames=referenced_qualnames,
        )

    typing_rows = tuple(
        sorted(typing_modules, key=lambda item: (item.filepath, item.module))
    )
    docstring_rows = tuple(
        sorted(docstring_modules, key=lambda item: (item.filepath, item.module))
    )
    api_rows = tuple(sorted(api_modules, key=lambda item: (item.filepath, item.module)))
    typing_param_total = sum(item.params_total for item in typing_rows)
    typing_param_annotated = sum(item.params_annotated for item in typing_rows)
    typing_return_total = sum(item.returns_total for item in typing_rows)
    typing_return_annotated = sum(item.returns_annotated for item in typing_rows)
    typing_any_count = sum(item.any_annotation_count for item in typing_rows)
    docstring_public_total = sum(item.public_symbol_total for item in docstring_rows)
    docstring_public_documented = sum(
        item.public_symbol_documented for item in docstring_rows
    )

    health = compute_health(
        HealthInputs(
            files_found=files_found,
            files_analyzed_or_cached=files_analyzed_or_cached,
            function_clone_groups=function_clone_groups,
            block_clone_groups=block_clone_groups,
            complexity_avg=complexity_avg,
            complexity_max=complexity_max,
            high_risk_functions=len(high_risk_functions),
            coupling_avg=coupling_avg,
            coupling_max=coupling_max,
            high_risk_classes=len(high_risk_classes),
            cohesion_avg=cohesion_avg,
            low_cohesion_classes=len(low_cohesion_classes),
            dependency_cycles=len(dep_graph.cycles),
            dependency_max_depth=dep_graph.max_depth,
            dead_code_items=len(dead_items),
        )
    )

    project_metrics = ProjectMetrics(
        complexity_avg=complexity_avg,
        complexity_max=complexity_max,
        high_risk_functions=high_risk_functions,
        coupling_avg=coupling_avg,
        coupling_max=coupling_max,
        high_risk_classes=high_risk_classes,
        cohesion_avg=cohesion_avg,
        cohesion_max=cohesion_max,
        low_cohesion_classes=low_cohesion_classes,
        dependency_modules=len(dep_graph.modules),
        dependency_edges=len(dep_graph.edges),
        dependency_edge_list=dep_graph.edges,
        dependency_cycles=dep_graph.cycles,
        dependency_max_depth=dep_graph.max_depth,
        dependency_longest_chains=dep_graph.longest_chains,
        dead_code=dead_items,
        health=health,
        typing_param_total=typing_param_total,
        typing_param_annotated=typing_param_annotated,
        typing_return_total=typing_return_total,
        typing_return_annotated=typing_return_annotated,
        typing_any_count=typing_any_count,
        docstring_public_total=docstring_public_total,
        docstring_public_documented=docstring_public_documented,
        typing_modules=typing_rows,
        docstring_modules=docstring_rows,
        api_surface=ApiSurfaceSnapshot(modules=api_rows) if api_rows else None,
    )
    return project_metrics, dep_graph, dead_items


def compute_suggestions(
    *,
    project_metrics: ProjectMetrics,
    units: Sequence[GroupItemLike],
    class_metrics: Sequence[ClassMetrics],
    func_groups: Mapping[str, Sequence[GroupItemLike]],
    block_groups: Mapping[str, Sequence[GroupItemLike]],
    segment_groups: Mapping[str, Sequence[GroupItemLike]],
    block_group_facts: Mapping[str, Mapping[str, str]] | None = None,
    structural_findings: Sequence[StructuralFindingGroup] | None = None,
    scan_root: str = "",
) -> tuple[Suggestion, ...]:
    return generate_suggestions(
        project_metrics=project_metrics,
        units=units,
        class_metrics=class_metrics,
        func_groups=func_groups,
        block_groups=block_groups,
        segment_groups=segment_groups,
        block_group_facts=block_group_facts,
        structural_findings=structural_findings,
        scan_root=scan_root,
    )


def _permille(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        return 0
    return round((1000.0 * float(numerator)) / float(denominator))


def _coverage_join_summary(
    coverage_join: CoverageJoinResult | None,
) -> dict[str, object]:
    if coverage_join is None:
        return {}
    return {
        "status": coverage_join.status,
        "source": coverage_join.coverage_xml,
        "files": coverage_join.files,
        "units": len(coverage_join.units),
        "measured_units": coverage_join.measured_units,
        "overall_executable_lines": coverage_join.overall_executable_lines,
        "overall_covered_lines": coverage_join.overall_covered_lines,
        "overall_permille": _permille(
            coverage_join.overall_covered_lines,
            coverage_join.overall_executable_lines,
        ),
        "missing_from_report_units": sum(
            1
            for fact in coverage_join.units
            if fact.coverage_status == "missing_from_report"
        ),
        "coverage_hotspots": coverage_join.coverage_hotspots,
        "scope_gap_hotspots": coverage_join.scope_gap_hotspots,
        "hotspot_threshold_percent": coverage_join.hotspot_threshold_percent,
        "invalid_reason": coverage_join.invalid_reason,
    }


def _coverage_join_rows(
    coverage_join: CoverageJoinResult | None,
) -> list[dict[str, object]]:
    if coverage_join is None or coverage_join.status != "ok":
        return []
    return sorted(
        (
            {
                "qualname": fact.qualname,
                "filepath": fact.filepath,
                "start_line": fact.start_line,
                "end_line": fact.end_line,
                "cyclomatic_complexity": fact.cyclomatic_complexity,
                "risk": fact.risk,
                "executable_lines": fact.executable_lines,
                "covered_lines": fact.covered_lines,
                "coverage_permille": fact.coverage_permille,
                "coverage_status": fact.coverage_status,
                "coverage_hotspot": (
                    fact.risk in {"medium", "high"}
                    and fact.coverage_status == "measured"
                    and (fact.coverage_permille / 10.0)
                    < float(coverage_join.hotspot_threshold_percent)
                ),
                "scope_gap_hotspot": (
                    fact.risk in {"medium", "high"}
                    and fact.coverage_status == "missing_from_report"
                ),
                "coverage_review_item": (
                    (
                        fact.risk in {"medium", "high"}
                        and fact.coverage_status == "measured"
                        and (fact.coverage_permille / 10.0)
                        < float(coverage_join.hotspot_threshold_percent)
                    )
                    or (
                        fact.risk in {"medium", "high"}
                        and fact.coverage_status == "missing_from_report"
                    )
                ),
            }
            for fact in coverage_join.units
        ),
        key=lambda item: (
            0 if bool(item.get("coverage_hotspot")) else 1,
            0 if bool(item.get("scope_gap_hotspot")) else 1,
            {"high": 0, "medium": 1, "low": 2}.get(_as_str(item.get("risk")), 3),
            _as_int(item.get("coverage_permille"), 0),
            -_as_int(item.get("cyclomatic_complexity"), 0),
            _as_str(item.get("filepath")),
            _as_int(item.get("start_line")),
            _as_str(item.get("qualname")),
        ),
    )


def _coverage_adoption_rows(
    project_metrics: ProjectMetrics,
) -> list[dict[str, object]]:
    docstring_by_module = {
        (item.filepath, item.module): item for item in project_metrics.docstring_modules
    }
    rows: list[dict[str, object]] = []
    seen_keys: set[tuple[str, str]] = set()
    for typing_item in project_metrics.typing_modules:
        key = (typing_item.filepath, typing_item.module)
        seen_keys.add(key)
        docstring_item = docstring_by_module.get(key)
        doc_total = docstring_item.public_symbol_total if docstring_item else 0
        doc_documented = (
            docstring_item.public_symbol_documented if docstring_item else 0
        )
        rows.append(
            {
                "module": typing_item.module,
                "filepath": typing_item.filepath,
                "callable_count": typing_item.callable_count,
                "params_total": typing_item.params_total,
                "params_annotated": typing_item.params_annotated,
                "param_permille": _permille(
                    typing_item.params_annotated,
                    typing_item.params_total,
                ),
                "returns_total": typing_item.returns_total,
                "returns_annotated": typing_item.returns_annotated,
                "return_permille": _permille(
                    typing_item.returns_annotated,
                    typing_item.returns_total,
                ),
                "any_annotation_count": typing_item.any_annotation_count,
                "public_symbol_total": doc_total,
                "public_symbol_documented": doc_documented,
                "docstring_permille": _permille(doc_documented, doc_total),
            }
        )
    for docstring_item in project_metrics.docstring_modules:
        key = (docstring_item.filepath, docstring_item.module)
        if key in seen_keys:
            continue
        rows.append(
            {
                "module": docstring_item.module,
                "filepath": docstring_item.filepath,
                "callable_count": 0,
                "params_total": 0,
                "params_annotated": 0,
                "param_permille": 0,
                "returns_total": 0,
                "returns_annotated": 0,
                "return_permille": 0,
                "any_annotation_count": 0,
                "public_symbol_total": docstring_item.public_symbol_total,
                "public_symbol_documented": docstring_item.public_symbol_documented,
                "docstring_permille": _permille(
                    docstring_item.public_symbol_documented,
                    docstring_item.public_symbol_total,
                ),
            }
        )
    return sorted(
        rows,
        key=lambda item: (
            _as_int(item.get("param_permille")),
            _as_int(item.get("docstring_permille")),
            _as_int(item.get("return_permille")),
            _as_str(item.get("module")),
        ),
    )


def _api_surface_summary(
    api_surface: ApiSurfaceSnapshot | None,
) -> dict[str, object]:
    modules = api_surface.modules if api_surface is not None else ()
    return {
        "enabled": api_surface is not None,
        "modules": len(modules),
        "public_symbols": sum(len(module.symbols) for module in modules),
        "added": 0,
        "breaking": 0,
        "strict_types": False,
    }


def _api_surface_rows(
    api_surface: ApiSurfaceSnapshot | None,
) -> list[dict[str, object]]:
    if api_surface is None:
        return []
    rows: list[dict[str, object]] = []
    for module in api_surface.modules:
        rows.extend(
            {
                "record_kind": "symbol",
                "module": module.module,
                "filepath": module.filepath,
                "qualname": symbol.qualname,
                "start_line": symbol.start_line,
                "end_line": symbol.end_line,
                "symbol_kind": symbol.kind,
                "exported_via": symbol.exported_via,
                "params_total": len(symbol.params),
                "params": [
                    {
                        "name": param.name,
                        "kind": param.kind,
                        "has_default": param.has_default,
                        "annotated": bool(param.annotation_hash),
                    }
                    for param in symbol.params
                ],
                "returns_annotated": bool(symbol.returns_hash),
            }
            for symbol in module.symbols
        )
    return sorted(
        rows,
        key=lambda item: (
            _as_str(item.get("filepath")),
            _as_int(item.get("start_line")),
            _as_int(item.get("end_line")),
            _as_str(item.get("qualname")),
            _as_str(item.get("record_kind")),
        ),
    )


def _breaking_api_surface_rows(
    changes: Sequence[object],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for change in changes:
        if not isinstance(change, ApiBreakingChange):
            continue
        module_name, _, _local_name = change.qualname.partition(":")
        rows.append(
            {
                "record_kind": "breaking_change",
                "module": module_name,
                "filepath": change.filepath,
                "qualname": change.qualname,
                "start_line": change.start_line,
                "end_line": change.end_line,
                "symbol_kind": change.symbol_kind,
                "change_kind": change.change_kind,
                "detail": change.detail,
            }
        )
    return sorted(
        rows,
        key=lambda item: (
            _as_str(item.get("filepath")),
            _as_int(item.get("start_line")),
            _as_int(item.get("end_line")),
            _as_str(item.get("qualname")),
            _as_str(item.get("change_kind")),
        ),
    )


def _enrich_metrics_report_payload(
    *,
    metrics_payload: Mapping[str, object],
    metrics_diff: MetricsDiff | None,
    coverage_adoption_diff_available: bool,
    api_surface_diff_available: bool,
) -> dict[str, object]:
    enriched = {
        key: (dict(value) if isinstance(value, Mapping) else value)
        for key, value in metrics_payload.items()
    }
    coverage_adoption = dict(
        cast("Mapping[str, object]", enriched.get("coverage_adoption", {}))
    )
    coverage_summary = dict(
        cast("Mapping[str, object]", coverage_adoption.get("summary", {}))
    )
    if coverage_summary:
        coverage_summary["baseline_diff_available"] = coverage_adoption_diff_available
        coverage_summary["param_delta"] = (
            int(metrics_diff.typing_param_permille_delta)
            if metrics_diff is not None and coverage_adoption_diff_available
            else 0
        )
        coverage_summary["return_delta"] = (
            int(metrics_diff.typing_return_permille_delta)
            if metrics_diff is not None and coverage_adoption_diff_available
            else 0
        )
        coverage_summary["docstring_delta"] = (
            int(metrics_diff.docstring_permille_delta)
            if metrics_diff is not None and coverage_adoption_diff_available
            else 0
        )
        coverage_adoption["summary"] = coverage_summary
        enriched["coverage_adoption"] = coverage_adoption

    api_surface = dict(cast("Mapping[str, object]", enriched.get("api_surface", {})))
    api_summary = dict(cast("Mapping[str, object]", api_surface.get("summary", {})))
    api_items = list(cast("Sequence[object]", api_surface.get("items", ())))
    if api_summary:
        api_summary["baseline_diff_available"] = api_surface_diff_available
        api_summary["added"] = (
            len(metrics_diff.new_api_symbols)
            if metrics_diff is not None and api_surface_diff_available
            else 0
        )
        api_summary["breaking"] = (
            len(metrics_diff.new_api_breaking_changes)
            if metrics_diff is not None and api_surface_diff_available
            else 0
        )
        api_surface["summary"] = api_summary
    if (
        metrics_diff is not None
        and api_surface_diff_available
        and metrics_diff.new_api_breaking_changes
    ):
        api_items.extend(
            _breaking_api_surface_rows(metrics_diff.new_api_breaking_changes)
        )
    api_surface["items"] = api_items
    if api_surface:
        enriched["api_surface"] = api_surface
    return enriched


def build_metrics_report_payload(
    *,
    scan_root: str = "",
    project_metrics: ProjectMetrics,
    coverage_join: CoverageJoinResult | None = None,
    units: Sequence[GroupItemLike],
    class_metrics: Sequence[ClassMetrics],
    module_deps: Sequence[ModuleDep] = (),
    source_stats_by_file: Sequence[tuple[str, int, int, int, int]] = (),
    suppressed_dead_code: Sequence[DeadItem] = (),
) -> dict[str, object]:
    sorted_units = sorted(
        units,
        key=lambda item: (
            _as_int(item.get("cyclomatic_complexity")),
            _as_int(item.get("nesting_depth")),
            _as_str(item.get("qualname")),
        ),
        reverse=True,
    )
    complexity_rows = [
        {
            "qualname": _as_str(item.get("qualname")),
            "filepath": _as_str(item.get("filepath")),
            "start_line": _as_int(item.get("start_line")),
            "end_line": _as_int(item.get("end_line")),
            "cyclomatic_complexity": _as_int(item.get("cyclomatic_complexity"), 1),
            "nesting_depth": _as_int(item.get("nesting_depth")),
            "risk": _as_str(item.get("risk"), RISK_LOW),
        }
        for item in sorted_units
    ]
    classes_sorted = sorted(
        class_metrics,
        key=lambda item: (item.cbo, item.lcom4, item.qualname),
        reverse=True,
    )
    coupling_rows = [
        {
            "qualname": metric.qualname,
            "filepath": metric.filepath,
            "start_line": metric.start_line,
            "end_line": metric.end_line,
            "cbo": metric.cbo,
            "risk": metric.risk_coupling,
            "coupled_classes": list(metric.coupled_classes),
        }
        for metric in classes_sorted
    ]
    cohesion_rows = [
        {
            "qualname": metric.qualname,
            "filepath": metric.filepath,
            "start_line": metric.start_line,
            "end_line": metric.end_line,
            "lcom4": metric.lcom4,
            "risk": metric.risk_cohesion,
            "method_count": metric.method_count,
            "instance_var_count": metric.instance_var_count,
        }
        for metric in classes_sorted
    ]
    active_dead_items = tuple(project_metrics.dead_code)
    suppressed_dead_items = tuple(suppressed_dead_code)
    coverage_adoption_rows = _coverage_adoption_rows(project_metrics)
    api_surface_summary = _api_surface_summary(project_metrics.api_surface)
    api_surface_items = _api_surface_rows(project_metrics.api_surface)
    coverage_join_summary = _coverage_join_summary(coverage_join)
    coverage_join_items = _coverage_join_rows(coverage_join)

    def _serialize_dead_item(
        item: DeadItem,
        *,
        suppressed: bool = False,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "qualname": item.qualname,
            "filepath": item.filepath,
            "start_line": item.start_line,
            "end_line": item.end_line,
            "kind": item.kind,
            "confidence": item.confidence,
        }
        if suppressed:
            payload["suppressed_by"] = [
                {
                    "rule": DEAD_CODE_RULE_ID,
                    "source": INLINE_CODECLONE_SUPPRESSION_SOURCE,
                }
            ]
        return payload

    payload = {
        CATEGORY_COMPLEXITY: {
            "functions": complexity_rows,
            "summary": {
                "total": len(complexity_rows),
                "average": round(project_metrics.complexity_avg, 2),
                "max": project_metrics.complexity_max,
                "high_risk": len(project_metrics.high_risk_functions),
            },
        },
        CATEGORY_COUPLING: {
            "classes": coupling_rows,
            "summary": {
                "total": len(coupling_rows),
                "average": round(project_metrics.coupling_avg, 2),
                "max": project_metrics.coupling_max,
                "high_risk": len(project_metrics.high_risk_classes),
            },
        },
        CATEGORY_COHESION: {
            "classes": cohesion_rows,
            "summary": {
                "total": len(cohesion_rows),
                "average": round(project_metrics.cohesion_avg, 2),
                "max": project_metrics.cohesion_max,
                "low_cohesion": len(project_metrics.low_cohesion_classes),
            },
        },
        "dependencies": {
            "modules": project_metrics.dependency_modules,
            "edges": project_metrics.dependency_edges,
            "max_depth": project_metrics.dependency_max_depth,
            "cycles": [list(cycle) for cycle in project_metrics.dependency_cycles],
            "longest_chains": [
                list(chain) for chain in project_metrics.dependency_longest_chains
            ],
            "edge_list": [
                {
                    "source": edge.source,
                    "target": edge.target,
                    "import_type": edge.import_type,
                    "line": edge.line,
                }
                for edge in project_metrics.dependency_edge_list
            ],
        },
        "dead_code": {
            "items": [_serialize_dead_item(item) for item in active_dead_items],
            "suppressed_items": [
                _serialize_dead_item(item, suppressed=True)
                for item in suppressed_dead_items
            ],
            "summary": {
                "total": len(active_dead_items),
                "critical": sum(
                    1
                    for item in active_dead_items
                    if item.confidence == CONFIDENCE_HIGH
                ),
                "high_confidence": sum(
                    1
                    for item in active_dead_items
                    if item.confidence == CONFIDENCE_HIGH
                ),
                "suppressed": len(suppressed_dead_items),
            },
        },
        "health": {
            "score": project_metrics.health.total,
            "grade": project_metrics.health.grade,
            "dimensions": dict(project_metrics.health.dimensions),
        },
        "coverage_adoption": {
            "summary": {
                "modules": len(coverage_adoption_rows),
                "params_total": project_metrics.typing_param_total,
                "params_annotated": project_metrics.typing_param_annotated,
                "param_permille": _permille(
                    project_metrics.typing_param_annotated,
                    project_metrics.typing_param_total,
                ),
                "returns_total": project_metrics.typing_return_total,
                "returns_annotated": project_metrics.typing_return_annotated,
                "return_permille": _permille(
                    project_metrics.typing_return_annotated,
                    project_metrics.typing_return_total,
                ),
                "public_symbol_total": project_metrics.docstring_public_total,
                "public_symbol_documented": project_metrics.docstring_public_documented,
                "docstring_permille": _permille(
                    project_metrics.docstring_public_documented,
                    project_metrics.docstring_public_total,
                ),
                "typing_any_count": project_metrics.typing_any_count,
            },
            "items": coverage_adoption_rows,
        },
        "api_surface": {
            "summary": dict(api_surface_summary),
            "items": api_surface_items,
        },
        "overloaded_modules": build_overloaded_modules_payload(
            scan_root=scan_root,
            source_stats_by_file=source_stats_by_file,
            units=units,
            class_metrics=class_metrics,
            module_deps=module_deps,
        ),
    }
    if coverage_join is not None:
        payload["coverage_join"] = {
            "summary": dict(coverage_join_summary),
            "items": coverage_join_items,
        }
    return payload


def analyze(
    *,
    boot: BootstrapResult,
    discovery: DiscoveryResult,
    processing: ProcessingResult,
) -> AnalysisResult:
    golden_fixture_paths = tuple(
        str(pattern).strip()
        for pattern in getattr(boot.args, "golden_fixture_paths", ())
        if str(pattern).strip()
    )

    func_split = split_clone_groups_for_golden_fixtures(
        groups=build_groups(processing.units),
        kind="function",
        golden_fixture_paths=golden_fixture_paths,
        scan_root=str(boot.root),
    )
    block_split = split_clone_groups_for_golden_fixtures(
        groups=build_block_groups(processing.blocks),
        kind="block",
        golden_fixture_paths=golden_fixture_paths,
        scan_root=str(boot.root),
    )
    segment_split = split_clone_groups_for_golden_fixtures(
        groups=build_segment_groups(processing.segments),
        kind="segment",
        golden_fixture_paths=golden_fixture_paths,
        scan_root=str(boot.root),
    )

    func_groups = func_split.active_groups
    block_groups = block_split.active_groups
    segment_groups_raw = segment_split.active_groups
    segment_groups_raw_digest = _segment_groups_digest(segment_groups_raw)
    cached_projection = discovery.cached_segment_report_projection
    if (
        cached_projection is not None
        and cached_projection.get("digest") == segment_groups_raw_digest
    ):
        projection_groups = cached_projection.get("groups", {})
        segment_groups = {
            group_key: [
                {
                    "segment_hash": str(item["segment_hash"]),
                    "segment_sig": str(item["segment_sig"]),
                    "filepath": str(item["filepath"]),
                    "qualname": str(item["qualname"]),
                    "start_line": int(item["start_line"]),
                    "end_line": int(item["end_line"]),
                    "size": int(item["size"]),
                }
                for item in projection_groups[group_key]
            ]
            for group_key in sorted(projection_groups)
        }
        suppressed_segment_groups = int(cached_projection.get("suppressed", 0))
    else:
        segment_groups, suppressed_segment_groups = prepare_segment_report_groups(
            segment_groups_raw
        )

    block_groups_report = prepare_block_report_groups(block_groups)
    suppressed_block_groups_report = prepare_block_report_groups(
        block_split.suppressed_groups
    )
    if segment_split.suppressed_groups:
        suppressed_segment_groups_report, _ = prepare_segment_report_groups(
            segment_split.suppressed_groups
        )
    else:
        suppressed_segment_groups_report = {}
    suppressed_clone_groups = (
        *build_suppressed_clone_groups(
            kind="function",
            groups=func_split.suppressed_groups,
            matched_patterns=func_split.matched_patterns,
        ),
        *build_suppressed_clone_groups(
            kind="block",
            groups=suppressed_block_groups_report,
            matched_patterns=block_split.matched_patterns,
        ),
        *build_suppressed_clone_groups(
            kind="segment",
            groups=suppressed_segment_groups_report,
            matched_patterns=segment_split.matched_patterns,
        ),
    )
    block_group_facts = build_block_group_facts(
        {
            **block_groups_report,
            **suppressed_block_groups_report,
        }
    )

    func_clones_count = len(func_groups)
    block_clones_count = len(block_groups)
    segment_clones_count = len(segment_groups)
    files_analyzed_or_cached = processing.files_analyzed + discovery.cache_hits

    project_metrics: ProjectMetrics | None = None
    metrics_payload: dict[str, object] | None = None
    suggestions: tuple[Suggestion, ...] = ()
    suppressed_dead_items: tuple[DeadItem, ...] = ()
    coverage_join: CoverageJoinResult | None = None
    cohort_structural_findings: tuple[StructuralFindingGroup, ...] = ()
    if _should_collect_structural_findings(boot.output_paths):
        cohort_structural_findings = build_clone_cohort_structural_findings(
            func_groups=func_groups,
        )
    combined_structural_findings = (
        *processing.structural_findings,
        *cohort_structural_findings,
    )

    if not boot.args.skip_metrics:
        project_metrics, _, _ = compute_project_metrics(
            units=processing.units,
            class_metrics=processing.class_metrics,
            module_deps=processing.module_deps,
            dead_candidates=processing.dead_candidates,
            referenced_names=processing.referenced_names,
            referenced_qualnames=processing.referenced_qualnames,
            typing_modules=processing.typing_modules,
            docstring_modules=processing.docstring_modules,
            api_modules=processing.api_modules,
            files_found=discovery.files_found,
            files_analyzed_or_cached=files_analyzed_or_cached,
            function_clone_groups=func_clones_count,
            block_clone_groups=block_clones_count,
            skip_dependencies=boot.args.skip_dependencies,
            skip_dead_code=boot.args.skip_dead_code,
        )
        if not boot.args.skip_dead_code:
            suppressed_dead_items = find_suppressed_unused(
                definitions=tuple(processing.dead_candidates),
                referenced_names=processing.referenced_names,
                referenced_qualnames=processing.referenced_qualnames,
            )
        suggestions = compute_suggestions(
            project_metrics=project_metrics,
            units=processing.units,
            class_metrics=processing.class_metrics,
            func_groups=func_groups,
            block_groups=block_groups_report,
            segment_groups=segment_groups,
            block_group_facts=block_group_facts,
            structural_findings=combined_structural_findings,
            scan_root=str(boot.root),
        )
        coverage_xml_path = _resolve_optional_runtime_path(
            getattr(boot.args, "coverage_xml", None),
            root=boot.root,
        )
        if coverage_xml_path is not None:
            try:
                coverage_join = build_coverage_join(
                    coverage_xml=coverage_xml_path,
                    root_path=boot.root,
                    units=processing.units,
                    hotspot_threshold_percent=int(
                        getattr(boot.args, "coverage_min", 50)
                    ),
                )
            except CoverageJoinParseError as exc:
                coverage_join = CoverageJoinResult(
                    coverage_xml=str(coverage_xml_path),
                    status="invalid",
                    hotspot_threshold_percent=int(
                        getattr(boot.args, "coverage_min", 50)
                    ),
                    invalid_reason=str(exc),
                )
        metrics_payload = build_metrics_report_payload(
            scan_root=str(boot.root),
            project_metrics=project_metrics,
            coverage_join=coverage_join,
            units=processing.units,
            class_metrics=processing.class_metrics,
            module_deps=processing.module_deps,
            source_stats_by_file=processing.source_stats_by_file,
            suppressed_dead_code=suppressed_dead_items,
        )

    return AnalysisResult(
        func_groups=func_groups,
        block_groups=block_groups,
        block_groups_report=block_groups_report,
        segment_groups=segment_groups,
        suppressed_clone_groups=tuple(suppressed_clone_groups),
        suppressed_segment_groups=suppressed_segment_groups,
        block_group_facts=block_group_facts,
        func_clones_count=func_clones_count,
        block_clones_count=block_clones_count,
        segment_clones_count=segment_clones_count,
        files_analyzed_or_cached=files_analyzed_or_cached,
        project_metrics=project_metrics,
        metrics_payload=metrics_payload,
        suggestions=suggestions,
        segment_groups_raw_digest=segment_groups_raw_digest,
        coverage_join=coverage_join,
        suppressed_dead_code_items=len(suppressed_dead_items),
        structural_findings=combined_structural_findings,
    )


def _load_markdown_report_renderer() -> Callable[..., str]:
    from .report.markdown import to_markdown_report

    return to_markdown_report


def _load_sarif_report_renderer() -> Callable[..., str]:
    from .report.sarif import to_sarif_report

    return to_sarif_report


def report(
    *,
    boot: BootstrapResult,
    discovery: DiscoveryResult,
    processing: ProcessingResult,
    analysis: AnalysisResult,
    report_meta: Mapping[str, object],
    new_func: Collection[str],
    new_block: Collection[str],
    html_builder: Callable[..., str] | None = None,
    metrics_diff: object | None = None,
    coverage_adoption_diff_available: bool = False,
    api_surface_diff_available: bool = False,
    include_report_document: bool = False,
) -> ReportArtifacts:
    contents: dict[str, str | None] = {
        "html": None,
        "json": None,
        "md": None,
        "sarif": None,
        "text": None,
    }

    sf = analysis.structural_findings if analysis.structural_findings else None
    report_inventory = {
        "files": {
            "total_found": discovery.files_found,
            "analyzed": processing.files_analyzed,
            "cached": discovery.cache_hits,
            "skipped": processing.files_skipped,
            "source_io_skipped": len(processing.source_read_failures),
        },
        "code": {
            "parsed_lines": processing.analyzed_lines + discovery.cached_lines,
            "functions": processing.analyzed_functions + discovery.cached_functions,
            "methods": processing.analyzed_methods + discovery.cached_methods,
            "classes": processing.analyzed_classes + discovery.cached_classes,
        },
        "file_list": list(discovery.all_file_paths),
    }
    report_document: dict[str, object] | None = None
    needs_report_document = (
        include_report_document
        or boot.output_paths.html is not None
        or any(
            path is not None
            for path in (
                boot.output_paths.json,
                boot.output_paths.md,
                boot.output_paths.sarif,
                boot.output_paths.text,
            )
        )
    )

    if needs_report_document:
        metrics_for_report = (
            _enrich_metrics_report_payload(
                metrics_payload=analysis.metrics_payload,
                metrics_diff=cast("MetricsDiff | None", metrics_diff),
                coverage_adoption_diff_available=coverage_adoption_diff_available,
                api_surface_diff_available=api_surface_diff_available,
            )
            if analysis.metrics_payload is not None
            else None
        )
        report_document = build_report_document(
            func_groups=analysis.func_groups,
            block_groups=analysis.block_groups_report,
            segment_groups=analysis.segment_groups,
            suppressed_clone_groups=analysis.suppressed_clone_groups,
            meta=report_meta,
            inventory=report_inventory,
            block_facts=analysis.block_group_facts,
            new_function_group_keys=new_func,
            new_block_group_keys=new_block,
            new_segment_group_keys=set(analysis.segment_groups.keys()),
            metrics=metrics_for_report,
            suggestions=analysis.suggestions,
            structural_findings=sf,
        )

    if boot.output_paths.html and html_builder is not None:
        metrics_for_html = (
            _enrich_metrics_report_payload(
                metrics_payload=analysis.metrics_payload,
                metrics_diff=cast("MetricsDiff | None", metrics_diff),
                coverage_adoption_diff_available=coverage_adoption_diff_available,
                api_surface_diff_available=api_surface_diff_available,
            )
            if analysis.metrics_payload is not None
            else None
        )
        contents["html"] = html_builder(
            func_groups=analysis.func_groups,
            block_groups=analysis.block_groups_report,
            segment_groups=analysis.segment_groups,
            block_group_facts=analysis.block_group_facts,
            new_function_group_keys=new_func,
            new_block_group_keys=new_block,
            report_meta=report_meta,
            metrics=metrics_for_html,
            suggestions=analysis.suggestions,
            structural_findings=sf,
            report_document=report_document,
            metrics_diff=metrics_diff,
            title="CodeClone Report",
            context_lines=3,
            max_snippet_lines=220,
        )

    if any(
        path is not None
        for path in (
            boot.output_paths.json,
            boot.output_paths.md,
            boot.output_paths.sarif,
            boot.output_paths.text,
        )
    ):
        assert report_document is not None

    if boot.output_paths.json and report_document is not None:
        contents["json"] = render_json_report_document(report_document)

    def _render_projection_artifact(
        renderer: Callable[..., str],
    ) -> str:
        assert report_document is not None
        return renderer(
            report_document=report_document,
            meta=report_meta,
            inventory=report_inventory,
            func_groups=analysis.func_groups,
            block_groups=analysis.block_groups_report,
            segment_groups=analysis.segment_groups,
            block_facts=analysis.block_group_facts,
            new_function_group_keys=new_func,
            new_block_group_keys=new_block,
            new_segment_group_keys=set(analysis.segment_groups.keys()),
            metrics=analysis.metrics_payload,
            suggestions=analysis.suggestions,
            structural_findings=sf,
        )

    for key, output_path, loader in (
        ("md", boot.output_paths.md, _load_markdown_report_renderer),
        ("sarif", boot.output_paths.sarif, _load_sarif_report_renderer),
    ):
        if output_path and report_document is not None:
            contents[key] = _render_projection_artifact(loader())

    if boot.output_paths.text and report_document is not None:
        contents["text"] = render_text_report_document(report_document)

    return ReportArtifacts(
        html=contents["html"],
        json=contents["json"],
        md=contents["md"],
        sarif=contents["sarif"],
        text=contents["text"],
        report_document=report_document,
    )


def metric_gate_reasons(
    *,
    project_metrics: ProjectMetrics,
    coverage_join: CoverageJoinResult | None,
    metrics_diff: MetricsDiff | None,
    config: MetricGateConfig,
) -> tuple[str, ...]:
    reasons: list[str] = []
    _append_threshold_metric_reasons(
        reasons=reasons,
        project_metrics=project_metrics,
        config=config,
    )
    _append_new_metric_diff_reasons(
        reasons=reasons,
        metrics_diff=metrics_diff,
        config=config,
    )
    _append_adoption_metric_reasons(
        reasons=reasons,
        metrics_diff=metrics_diff,
        project_metrics=project_metrics,
        config=config,
    )
    _append_coverage_join_reasons(
        reasons=reasons,
        coverage_join=coverage_join,
        config=config,
    )
    return tuple(reasons)


def _append_threshold_metric_reasons(
    *,
    reasons: list[str],
    project_metrics: ProjectMetrics,
    config: MetricGateConfig,
) -> None:
    threshold_rows = (
        (
            config.fail_complexity >= 0
            and project_metrics.complexity_max > config.fail_complexity,
            "Complexity threshold exceeded: "
            f"max CC={project_metrics.complexity_max}, "
            f"threshold={config.fail_complexity}.",
        ),
        (
            config.fail_coupling >= 0
            and project_metrics.coupling_max > config.fail_coupling,
            "Coupling threshold exceeded: "
            f"max CBO={project_metrics.coupling_max}, "
            f"threshold={config.fail_coupling}.",
        ),
        (
            config.fail_cohesion >= 0
            and project_metrics.cohesion_max > config.fail_cohesion,
            "Cohesion threshold exceeded: "
            f"max LCOM4={project_metrics.cohesion_max}, "
            f"threshold={config.fail_cohesion}.",
        ),
        (
            config.fail_health >= 0
            and project_metrics.health.total < config.fail_health,
            "Health score below threshold: "
            f"score={project_metrics.health.total}, threshold={config.fail_health}.",
        ),
    )
    reasons.extend(message for triggered, message in threshold_rows if triggered)
    if config.fail_cycles and project_metrics.dependency_cycles:
        reasons.append(
            "Dependency cycles detected: "
            f"{len(project_metrics.dependency_cycles)} cycle(s)."
        )
    high_conf_dead = _high_confidence_dead_code_count(project_metrics.dead_code)
    if config.fail_dead_code and high_conf_dead > 0:
        reasons.append(
            f"Dead code detected (high confidence): {high_conf_dead} item(s)."
        )


def _append_new_metric_diff_reasons(
    *,
    reasons: list[str],
    metrics_diff: MetricsDiff | None,
    config: MetricGateConfig,
) -> None:
    if not config.fail_on_new_metrics or metrics_diff is None:
        return
    if metrics_diff.new_high_risk_functions:
        reasons.append(
            "New high-risk functions vs metrics baseline: "
            f"{len(metrics_diff.new_high_risk_functions)}."
        )
    if metrics_diff.new_high_coupling_classes:
        reasons.append(
            "New high-coupling classes vs metrics baseline: "
            f"{len(metrics_diff.new_high_coupling_classes)}."
        )
    if metrics_diff.new_cycles:
        reasons.append(
            "New dependency cycles vs metrics baseline: "
            f"{len(metrics_diff.new_cycles)}."
        )
    if metrics_diff.new_dead_code:
        reasons.append(
            "New dead code items vs metrics baseline: "
            f"{len(metrics_diff.new_dead_code)}."
        )
    if metrics_diff.health_delta < 0:
        reasons.append(
            "Health score regressed vs metrics baseline: "
            f"delta={metrics_diff.health_delta}."
        )


def _append_metric_gate_reason(
    *,
    reasons: list[str],
    enabled: bool,
    triggered: bool,
    message: str,
) -> None:
    if enabled and triggered:
        reasons.append(message)


def _append_adoption_metric_reasons(
    *,
    reasons: list[str],
    metrics_diff: MetricsDiff | None,
    project_metrics: ProjectMetrics,
    config: MetricGateConfig,
) -> None:
    typing_percent = (
        _permille(
            project_metrics.typing_param_annotated,
            project_metrics.typing_param_total,
        )
        / 10.0
    )
    docstring_percent = (
        _permille(
            project_metrics.docstring_public_documented,
            project_metrics.docstring_public_total,
        )
        / 10.0
    )
    if config.min_typing_coverage >= 0 and typing_percent < float(
        config.min_typing_coverage
    ):
        reasons.append(
            "Typing coverage below threshold: "
            f"coverage={typing_percent:.1f}%, threshold={config.min_typing_coverage}%."
        )
    if config.min_docstring_coverage >= 0 and docstring_percent < float(
        config.min_docstring_coverage
    ):
        reasons.append(
            "Docstring coverage below threshold: "
            "coverage="
            f"{docstring_percent:.1f}%, "
            f"threshold={config.min_docstring_coverage}%."
        )
    if metrics_diff is None:
        return
    if config.fail_on_typing_regression:
        typing_delta = int(getattr(metrics_diff, "typing_param_permille_delta", 0))
        return_delta = int(getattr(metrics_diff, "typing_return_permille_delta", 0))
        if typing_delta < 0 or return_delta < 0:
            reasons.append(
                "Typing coverage regressed vs metrics baseline: "
                f"params_delta={typing_delta}, returns_delta={return_delta}."
            )
    docstring_delta = int(getattr(metrics_diff, "docstring_permille_delta", 0))
    _append_metric_gate_reason(
        reasons=reasons,
        enabled=config.fail_on_docstring_regression,
        triggered=docstring_delta < 0,
        message=(
            "Docstring coverage regressed vs metrics baseline: "
            f"delta={docstring_delta}."
        ),
    )
    api_breaking = tuple(
        cast(
            "Sequence[object]",
            getattr(metrics_diff, "new_api_breaking_changes", ()),
        )
    )
    _append_metric_gate_reason(
        reasons=reasons,
        enabled=config.fail_on_api_break,
        triggered=bool(api_breaking),
        message=(
            f"Public API breaking changes vs metrics baseline: {len(api_breaking)}."
        ),
    )


def _append_coverage_join_reasons(
    *,
    reasons: list[str],
    coverage_join: CoverageJoinResult | None,
    config: MetricGateConfig,
) -> None:
    if not config.fail_on_untested_hotspots or coverage_join is None:
        return
    if coverage_join.status != "ok":
        return
    if coverage_join.coverage_hotspots > 0:
        reasons.append(
            "Coverage hotspots detected: "
            f"hotspots={coverage_join.coverage_hotspots}, "
            f"threshold={config.coverage_min}%."
        )


def _high_confidence_dead_code_count(items: Sequence[DeadItem]) -> int:
    return sum(1 for item in items if item.confidence == "high")


def gate(
    *,
    boot: BootstrapResult,
    analysis: AnalysisResult,
    new_func: Collection[str],
    new_block: Collection[str],
    metrics_diff: MetricsDiff | None,
) -> GatingResult:
    reasons: list[str] = []

    if analysis.project_metrics is not None:
        metric_reasons = metric_gate_reasons(
            project_metrics=analysis.project_metrics,
            coverage_join=analysis.coverage_join,
            metrics_diff=metrics_diff,
            config=MetricGateConfig(
                fail_complexity=boot.args.fail_complexity,
                fail_coupling=boot.args.fail_coupling,
                fail_cohesion=boot.args.fail_cohesion,
                fail_cycles=boot.args.fail_cycles,
                fail_dead_code=boot.args.fail_dead_code,
                fail_health=boot.args.fail_health,
                fail_on_new_metrics=boot.args.fail_on_new_metrics,
                fail_on_typing_regression=bool(
                    getattr(boot.args, "fail_on_typing_regression", False)
                ),
                fail_on_docstring_regression=bool(
                    getattr(boot.args, "fail_on_docstring_regression", False)
                ),
                fail_on_api_break=bool(getattr(boot.args, "fail_on_api_break", False)),
                fail_on_untested_hotspots=bool(
                    getattr(boot.args, "fail_on_untested_hotspots", False)
                ),
                min_typing_coverage=int(getattr(boot.args, "min_typing_coverage", -1)),
                min_docstring_coverage=int(
                    getattr(boot.args, "min_docstring_coverage", -1)
                ),
                coverage_min=int(getattr(boot.args, "coverage_min", 50)),
            ),
        )
        reasons.extend(f"metric:{reason}" for reason in metric_reasons)

    if boot.args.fail_on_new and (new_func or new_block):
        reasons.append("clone:new")

    total_clone_groups = analysis.func_clones_count + analysis.block_clones_count
    if 0 <= boot.args.fail_threshold < total_clone_groups:
        reasons.append(
            f"clone:threshold:{total_clone_groups}:{boot.args.fail_threshold}"
        )

    if reasons:
        return GatingResult(
            exit_code=int(ExitCode.GATING_FAILURE),
            reasons=tuple(reasons),
        )

    return GatingResult(exit_code=int(ExitCode.SUCCESS), reasons=())
