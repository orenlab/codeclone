# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, TypedDict

from ..findings.structural.detectors import normalize_structural_finding_group
from ..models import (
    BlockGroupItem,
    BlockUnit,
    ClassMetrics,
    DeadCandidate,
    FunctionGroupItem,
    ModuleApiSurface,
    ModuleDep,
    ModuleDocstringCoverage,
    ModuleTypingCoverage,
    SegmentGroupItem,
    SegmentUnit,
    StructuralFindingGroup,
    StructuralFindingOccurrence,
    Unit,
)


class FileStat(TypedDict):
    mtime_ns: int
    size: int


class SourceStatsDict(TypedDict):
    lines: int
    functions: int
    methods: int
    classes: int


UnitDict = FunctionGroupItem
BlockDict = BlockGroupItem
SegmentDict = SegmentGroupItem


class ClassMetricsDictBase(TypedDict):
    qualname: str
    filepath: str
    start_line: int
    end_line: int
    cbo: int
    lcom4: int
    method_count: int
    instance_var_count: int
    risk_coupling: str
    risk_cohesion: str


class ClassMetricsDict(ClassMetricsDictBase, total=False):
    coupled_classes: list[str]


class ModuleDepDict(TypedDict):
    source: str
    target: str
    import_type: str
    line: int


class DeadCandidateDictBase(TypedDict):
    qualname: str
    local_name: str
    filepath: str
    start_line: int
    end_line: int
    kind: str


class DeadCandidateDict(DeadCandidateDictBase, total=False):
    suppressed_rules: list[str]


class ModuleTypingCoverageDict(TypedDict):
    module: str
    filepath: str
    callable_count: int
    params_total: int
    params_annotated: int
    returns_total: int
    returns_annotated: int
    any_annotation_count: int


class ModuleDocstringCoverageDict(TypedDict):
    module: str
    filepath: str
    public_symbol_total: int
    public_symbol_documented: int


class ApiParamSpecDict(TypedDict):
    name: str
    kind: str
    has_default: bool
    annotation_hash: str


class PublicSymbolDict(TypedDict):
    qualname: str
    kind: str
    start_line: int
    end_line: int
    params: list[ApiParamSpecDict]
    returns_hash: str
    exported_via: str


class ModuleApiSurfaceDict(TypedDict):
    module: str
    filepath: str
    all_declared: list[str]
    symbols: list[PublicSymbolDict]


class StructuralFindingOccurrenceDict(TypedDict):
    qualname: str
    start: int
    end: int


class StructuralFindingGroupDict(TypedDict):
    finding_kind: str
    finding_key: str
    signature: dict[str, str]
    items: list[StructuralFindingOccurrenceDict]


class _FileEntryBase(TypedDict):
    stat: FileStat
    units: list[UnitDict]
    blocks: list[BlockDict]
    segments: list[SegmentDict]


class _FileEntryV25(_FileEntryBase, total=False):
    source_stats: SourceStatsDict
    class_metrics: list[ClassMetricsDict]
    module_deps: list[ModuleDepDict]
    dead_candidates: list[DeadCandidateDict]
    referenced_names: list[str]
    referenced_qualnames: list[str]
    import_names: list[str]
    class_names: list[str]
    typing_coverage: ModuleTypingCoverageDict
    docstring_coverage: ModuleDocstringCoverageDict
    api_surface: ModuleApiSurfaceDict
    structural_findings: list[StructuralFindingGroupDict]


CacheEntryBase = _FileEntryBase
CacheEntry = _FileEntryV25


def _normalize_cached_structural_group(
    group: StructuralFindingGroupDict,
    *,
    filepath: str,
) -> StructuralFindingGroupDict | None:
    signature = dict(group["signature"])
    finding_kind = group["finding_kind"]
    finding_key = group["finding_key"]
    normalized = normalize_structural_finding_group(
        StructuralFindingGroup(
            finding_kind=finding_kind,
            finding_key=finding_key,
            signature=signature,
            items=tuple(
                StructuralFindingOccurrence(
                    finding_kind=finding_kind,
                    finding_key=finding_key,
                    file_path=filepath,
                    qualname=item["qualname"],
                    start=item["start"],
                    end=item["end"],
                    signature=signature,
                )
                for item in group["items"]
            ),
        )
    )
    if normalized is None:
        return None
    return StructuralFindingGroupDict(
        finding_kind=normalized.finding_kind,
        finding_key=normalized.finding_key,
        signature=dict(normalized.signature),
        items=[
            StructuralFindingOccurrenceDict(
                qualname=item.qualname,
                start=item.start,
                end=item.end,
            )
            for item in normalized.items
        ],
    )


def _normalize_cached_structural_groups(
    groups: Sequence[StructuralFindingGroupDict],
    *,
    filepath: str,
) -> list[StructuralFindingGroupDict]:
    normalized = [
        candidate
        for candidate in (
            _normalize_cached_structural_group(group, filepath=filepath)
            for group in groups
        )
        if candidate is not None
    ]
    normalized.sort(key=lambda group: (-len(group["items"]), group["finding_key"]))
    return normalized


def _as_risk_literal(value: object) -> Literal["low", "medium", "high"] | None:
    match value:
        case "low":
            return "low"
        case "medium":
            return "medium"
        case "high":
            return "high"
        case _:
            return None


def _new_optional_metrics_payload() -> tuple[
    list[ClassMetricsDict],
    list[ModuleDepDict],
    list[DeadCandidateDict],
    list[str],
    list[str],
    list[str],
    list[str],
    ModuleTypingCoverageDict | None,
    ModuleDocstringCoverageDict | None,
    ModuleApiSurfaceDict | None,
]:
    return [], [], [], [], [], [], [], None, None, None


def _unit_dict_from_model(unit: Unit, filepath: str) -> UnitDict:
    return FunctionGroupItem(
        qualname=unit.qualname,
        filepath=filepath,
        start_line=unit.start_line,
        end_line=unit.end_line,
        loc=unit.loc,
        stmt_count=unit.stmt_count,
        fingerprint=unit.fingerprint,
        loc_bucket=unit.loc_bucket,
        cyclomatic_complexity=unit.cyclomatic_complexity,
        nesting_depth=unit.nesting_depth,
        risk=unit.risk,
        raw_hash=unit.raw_hash,
        entry_guard_count=unit.entry_guard_count,
        entry_guard_terminal_profile=unit.entry_guard_terminal_profile,
        entry_guard_has_side_effect_before=unit.entry_guard_has_side_effect_before,
        terminal_kind=unit.terminal_kind,
        try_finally_profile=unit.try_finally_profile,
        side_effect_order_profile=unit.side_effect_order_profile,
    )


def _block_dict_from_model(block: BlockUnit, filepath: str) -> BlockDict:
    return BlockGroupItem(
        block_hash=block.block_hash,
        filepath=filepath,
        qualname=block.qualname,
        start_line=block.start_line,
        end_line=block.end_line,
        size=block.size,
    )


def _segment_dict_from_model(segment: SegmentUnit, filepath: str) -> SegmentDict:
    return SegmentGroupItem(
        segment_hash=segment.segment_hash,
        segment_sig=segment.segment_sig,
        filepath=filepath,
        qualname=segment.qualname,
        start_line=segment.start_line,
        end_line=segment.end_line,
        size=segment.size,
    )


def _typing_coverage_dict_from_model(
    coverage: ModuleTypingCoverage | None,
    *,
    filepath: str,
) -> ModuleTypingCoverageDict | None:
    if coverage is None:
        return None
    return ModuleTypingCoverageDict(
        module=coverage.module,
        filepath=filepath,
        callable_count=coverage.callable_count,
        params_total=coverage.params_total,
        params_annotated=coverage.params_annotated,
        returns_total=coverage.returns_total,
        returns_annotated=coverage.returns_annotated,
        any_annotation_count=coverage.any_annotation_count,
    )


def _docstring_coverage_dict_from_model(
    coverage: ModuleDocstringCoverage | None,
    *,
    filepath: str,
) -> ModuleDocstringCoverageDict | None:
    if coverage is None:
        return None
    return ModuleDocstringCoverageDict(
        module=coverage.module,
        filepath=filepath,
        public_symbol_total=coverage.public_symbol_total,
        public_symbol_documented=coverage.public_symbol_documented,
    )


def _api_surface_dict_from_model(
    surface: ModuleApiSurface | None,
    *,
    filepath: str,
) -> ModuleApiSurfaceDict | None:
    if surface is None:
        return None
    return ModuleApiSurfaceDict(
        module=surface.module,
        filepath=filepath,
        all_declared=list(surface.all_declared or ()),
        symbols=[
            PublicSymbolDict(
                qualname=symbol.qualname,
                kind=symbol.kind,
                start_line=symbol.start_line,
                end_line=symbol.end_line,
                params=[
                    ApiParamSpecDict(
                        name=param.name,
                        kind=param.kind,
                        has_default=param.has_default,
                        annotation_hash=param.annotation_hash,
                    )
                    for param in symbol.params
                ],
                returns_hash=symbol.returns_hash,
                exported_via=symbol.exported_via,
            )
            for symbol in surface.symbols
        ],
    )


def _class_metrics_dict_from_model(
    metric: ClassMetrics,
    filepath: str,
) -> ClassMetricsDict:
    return ClassMetricsDict(
        qualname=metric.qualname,
        filepath=filepath,
        start_line=metric.start_line,
        end_line=metric.end_line,
        cbo=metric.cbo,
        lcom4=metric.lcom4,
        method_count=metric.method_count,
        instance_var_count=metric.instance_var_count,
        risk_coupling=metric.risk_coupling,
        risk_cohesion=metric.risk_cohesion,
        coupled_classes=sorted(set(metric.coupled_classes)),
    )


def _module_dep_dict_from_model(dep: ModuleDep) -> ModuleDepDict:
    return ModuleDepDict(
        source=dep.source,
        target=dep.target,
        import_type=dep.import_type,
        line=dep.line,
    )


def _dead_candidate_dict_from_model(
    candidate: DeadCandidate,
    filepath: str,
) -> DeadCandidateDict:
    result = DeadCandidateDict(
        qualname=candidate.qualname,
        local_name=candidate.local_name,
        filepath=filepath,
        start_line=candidate.start_line,
        end_line=candidate.end_line,
        kind=candidate.kind,
    )
    if candidate.suppressed_rules:
        result["suppressed_rules"] = sorted(set(candidate.suppressed_rules))
    return result


def _structural_occurrence_dict_from_model(
    occurrence: StructuralFindingOccurrence,
) -> StructuralFindingOccurrenceDict:
    return StructuralFindingOccurrenceDict(
        qualname=occurrence.qualname,
        start=occurrence.start,
        end=occurrence.end,
    )


def _structural_group_dict_from_model(
    group: StructuralFindingGroup,
) -> StructuralFindingGroupDict:
    return StructuralFindingGroupDict(
        finding_kind=group.finding_kind,
        finding_key=group.finding_key,
        signature=dict(group.signature),
        items=[
            _structural_occurrence_dict_from_model(occurrence)
            for occurrence in group.items
        ],
    )


__all__ = [
    "ApiParamSpecDict",
    "BlockDict",
    "CacheEntry",
    "CacheEntryBase",
    "ClassMetricsDict",
    "DeadCandidateDict",
    "FileStat",
    "ModuleApiSurfaceDict",
    "ModuleDepDict",
    "ModuleDocstringCoverageDict",
    "ModuleTypingCoverageDict",
    "PublicSymbolDict",
    "SegmentDict",
    "SourceStatsDict",
    "StructuralFindingGroupDict",
    "StructuralFindingOccurrenceDict",
    "UnitDict",
    "_api_surface_dict_from_model",
    "_as_risk_literal",
    "_block_dict_from_model",
    "_class_metrics_dict_from_model",
    "_dead_candidate_dict_from_model",
    "_docstring_coverage_dict_from_model",
    "_module_dep_dict_from_model",
    "_new_optional_metrics_payload",
    "_normalize_cached_structural_group",
    "_normalize_cached_structural_groups",
    "_segment_dict_from_model",
    "_structural_group_dict_from_model",
    "_structural_occurrence_dict_from_model",
    "_typing_coverage_dict_from_model",
    "_unit_dict_from_model",
]
