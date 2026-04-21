# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from argparse import Namespace
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import cast

import orjson

from ..analysis.normalizer import NormalizationConfig
from ..cache.entries import FileStat
from ..cache.projection import SegmentReportProjection
from ..models import (
    BlockUnit,
    ClassMetrics,
    CoverageJoinResult,
    DeadCandidate,
    FileMetrics,
    GroupItem,
    GroupItemLike,
    ModuleApiSurface,
    ModuleDep,
    ModuleDocstringCoverage,
    ModuleTypingCoverage,
    ProjectMetrics,
    SegmentUnit,
    StructuralFindingGroup,
    Suggestion,
    SuppressedCloneGroup,
    Unit,
)
from ..utils.coerce import as_int, as_str

MAX_FILE_SIZE = 10 * 1024 * 1024
DEFAULT_BATCH_SIZE = 100
PARALLEL_MIN_FILES_PER_WORKER = 8
PARALLEL_MIN_FILES_FLOOR = 16
DEFAULT_RUNTIME_PROCESSES = 4


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
    func_groups: Mapping[str, list[GroupItem]]
    block_groups: Mapping[str, list[GroupItem]]
    block_groups_report: Mapping[str, list[GroupItem]]
    segment_groups: Mapping[str, list[GroupItem]]
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
class ReportArtifacts:
    html: str | None = None
    json: str | None = None
    text: str | None = None
    md: str | None = None
    sarif: str | None = None
    report_document: dict[str, object] | None = None


def _as_sorted_str_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(sorted({item for item in value if isinstance(item, str) and item}))


def _group_item_sort_key(item: GroupItemLike) -> tuple[str, int, int, str]:
    return (
        as_str(item.get("filepath")),
        as_int(item.get("start_line")),
        as_int(item.get("end_line")),
        as_str(item.get("qualname")),
    )


def _segment_projection_item_sort_key(
    item: GroupItemLike,
) -> tuple[str, str, int, int]:
    return (
        as_str(item.get("filepath")),
        as_str(item.get("qualname")),
        as_int(item.get("start_line")),
        as_int(item.get("end_line")),
    )


def _segment_groups_digest(segment_groups: Mapping[str, list[GroupItem]]) -> str:
    normalized_rows: list[
        tuple[str, tuple[tuple[str, str, int, int, int, str, str], ...]]
    ] = []
    for group_key in sorted(segment_groups):
        items = sorted(segment_groups[group_key], key=_segment_projection_item_sort_key)
        normalized_items = [
            (
                as_str(item.get("filepath")),
                as_str(item.get("qualname")),
                as_int(item.get("start_line")),
                as_int(item.get("end_line")),
                as_int(item.get("size")),
                as_str(item.get("segment_hash")),
                as_str(item.get("segment_sig")),
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


def _module_names_from_units(units: tuple[GroupItemLike, ...]) -> frozenset[str]:
    modules: set[str] = set()
    for item in units:
        qualname = as_str(item.get("qualname")) if isinstance(item, Mapping) else ""
        module_name = qualname.split(":", 1)[0] if ":" in qualname else qualname
        if module_name:
            modules.add(module_name)
    return frozenset(sorted(modules))


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
        "filepath": segment.filepath,
        "qualname": segment.qualname,
        "start_line": segment.start_line,
        "end_line": segment.end_line,
        "size": segment.size,
        "segment_hash": segment.segment_hash,
        "segment_sig": segment.segment_sig,
    }


def _should_collect_structural_findings(output_paths: OutputPaths) -> bool:
    return bool(
        output_paths.html
        or output_paths.json
        or output_paths.md
        or output_paths.text
        or output_paths.sarif
    )
