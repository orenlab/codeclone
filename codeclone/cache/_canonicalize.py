# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TypeGuard, TypeVar

from ._validators import (
    _is_block_dict,
    _is_class_metrics_dict,
    _is_dead_candidate_dict,
    _is_file_stat_dict,
    _is_module_api_surface_dict,
    _is_module_dep_dict,
    _is_module_docstring_coverage_dict,
    _is_module_typing_coverage_dict,
    _is_security_surface_dict,
    _is_segment_dict,
    _is_source_stats_dict,
    _is_string_list,
    _is_unit_dict,
)
from .entries import (
    ApiParamSpecDict,
    BlockDict,
    CacheEntry,
    ClassMetricsDict,
    DeadCandidateDict,
    FileStat,
    ModuleApiSurfaceDict,
    ModuleDepDict,
    ModuleDocstringCoverageDict,
    ModuleTypingCoverageDict,
    PublicSymbolDict,
    SecuritySurfaceDict,
    SegmentDict,
    SourceStatsDict,
    StructuralFindingGroupDict,
    UnitDict,
)

_ValidatedItemT = TypeVar("_ValidatedItemT")


def _is_str_item(value: object) -> TypeGuard[str]:
    return isinstance(value, str)


def _as_file_stat_dict(value: object) -> FileStat | None:
    if not _is_file_stat_dict(value):
        return None
    mtime_ns = value.get("mtime_ns")
    size = value.get("size")
    if not isinstance(mtime_ns, int) or not isinstance(size, int):
        return None
    return FileStat(mtime_ns=mtime_ns, size=size)


def _as_source_stats_dict(value: object) -> SourceStatsDict | None:
    if not _is_source_stats_dict(value):
        return None
    return SourceStatsDict(
        lines=value["lines"],
        functions=value["functions"],
        methods=value["methods"],
        classes=value["classes"],
    )


def _as_typed_list(
    value: object,
    *,
    predicate: Callable[[object], TypeGuard[_ValidatedItemT]],
) -> list[_ValidatedItemT] | None:
    if not isinstance(value, list):
        return None
    items: list[_ValidatedItemT] = []
    for item in value:
        if not predicate(item):
            return None
        items.append(item)
    return items


def _as_typed_unit_list(value: object) -> list[UnitDict] | None:
    return _as_typed_list(value, predicate=_is_unit_dict)


def _as_typed_block_list(value: object) -> list[BlockDict] | None:
    return _as_typed_list(value, predicate=_is_block_dict)


def _as_typed_segment_list(value: object) -> list[SegmentDict] | None:
    return _as_typed_list(value, predicate=_is_segment_dict)


def _as_typed_class_metrics_list(value: object) -> list[ClassMetricsDict] | None:
    return _as_typed_list(value, predicate=_is_class_metrics_dict)


def _as_typed_dead_candidates_list(
    value: object,
) -> list[DeadCandidateDict] | None:
    return _as_typed_list(value, predicate=_is_dead_candidate_dict)


def _as_typed_module_deps_list(value: object) -> list[ModuleDepDict] | None:
    return _as_typed_list(value, predicate=_is_module_dep_dict)


def _as_typed_security_surfaces_list(value: object) -> list[SecuritySurfaceDict] | None:
    return _as_typed_list(value, predicate=_is_security_surface_dict)


def _as_typed_string_list(value: object) -> list[str] | None:
    return _as_typed_list(value, predicate=_is_str_item)


def _as_module_typing_coverage_dict(
    value: object,
) -> ModuleTypingCoverageDict | None:
    if not _is_module_typing_coverage_dict(value):
        return None
    return value


def _as_module_docstring_coverage_dict(
    value: object,
) -> ModuleDocstringCoverageDict | None:
    if not _is_module_docstring_coverage_dict(value):
        return None
    return value


def _as_module_api_surface_dict(value: object) -> ModuleApiSurfaceDict | None:
    if not _is_module_api_surface_dict(value):
        return None
    return value


def _normalized_optional_string_list(value: object) -> list[str] | None:
    items = _as_typed_string_list(value)
    if not items:
        return None
    return sorted(set(items))


def _is_canonical_cache_entry(value: object) -> TypeGuard[CacheEntry]:
    return isinstance(value, dict) and _has_cache_entry_container_shape(value)


def _has_cache_entry_container_shape(entry: Mapping[str, object]) -> bool:
    required = {"stat", "units", "blocks", "segments"}
    if not required.issubset(entry.keys()):
        return False
    if not isinstance(entry.get("stat"), dict):
        return False
    if not isinstance(entry.get("units"), list):
        return False
    if not isinstance(entry.get("blocks"), list):
        return False
    if not isinstance(entry.get("segments"), list):
        return False
    source_stats = entry.get("source_stats")
    if source_stats is not None and not _is_source_stats_dict(source_stats):
        return False
    optional_list_keys = (
        "class_metrics",
        "module_deps",
        "dead_candidates",
        "referenced_names",
        "referenced_qualnames",
        "import_names",
        "class_names",
        "security_surfaces",
        "structural_findings",
    )
    if not all(isinstance(entry.get(key, []), list) for key in optional_list_keys):
        return False
    typing_coverage = entry.get("typing_coverage")
    if typing_coverage is not None and not _is_module_typing_coverage_dict(
        typing_coverage
    ):
        return False
    docstring_coverage = entry.get("docstring_coverage")
    if docstring_coverage is not None and not _is_module_docstring_coverage_dict(
        docstring_coverage
    ):
        return False
    api_surface = entry.get("api_surface")
    return api_surface is None or _is_module_api_surface_dict(api_surface)


def _decode_optional_cache_sections(
    entry: Mapping[str, object],
) -> (
    tuple[
        list[ClassMetricsDict],
        list[ModuleDepDict],
        list[DeadCandidateDict],
        list[str],
        list[str],
        list[str],
        list[str],
        list[SecuritySurfaceDict],
        ModuleTypingCoverageDict | None,
        ModuleDocstringCoverageDict | None,
        ModuleApiSurfaceDict | None,
        SourceStatsDict | None,
        list[StructuralFindingGroupDict] | None,
    ]
    | None
):
    class_metrics_raw = _as_typed_class_metrics_list(entry.get("class_metrics", []))
    module_deps_raw = _as_typed_module_deps_list(entry.get("module_deps", []))
    dead_candidates_raw = _as_typed_dead_candidates_list(
        entry.get("dead_candidates", [])
    )
    referenced_names_raw = _as_typed_string_list(entry.get("referenced_names", []))
    referenced_qualnames_raw = _as_typed_string_list(
        entry.get("referenced_qualnames", [])
    )
    import_names_raw = _as_typed_string_list(entry.get("import_names", []))
    class_names_raw = _as_typed_string_list(entry.get("class_names", []))
    security_surfaces_raw = _as_typed_security_surfaces_list(
        entry.get("security_surfaces", [])
    )
    if (
        class_metrics_raw is None
        or module_deps_raw is None
        or dead_candidates_raw is None
        or referenced_names_raw is None
        or referenced_qualnames_raw is None
        or import_names_raw is None
        or class_names_raw is None
        or security_surfaces_raw is None
    ):
        return None
    typing_coverage_raw = _as_module_typing_coverage_dict(entry.get("typing_coverage"))
    docstring_coverage_raw = _as_module_docstring_coverage_dict(
        entry.get("docstring_coverage")
    )
    api_surface_raw = _as_module_api_surface_dict(entry.get("api_surface"))
    source_stats = _as_source_stats_dict(entry.get("source_stats"))
    structural_findings = entry.get("structural_findings")
    typed_structural_findings = (
        structural_findings if isinstance(structural_findings, list) else None
    )
    return (
        class_metrics_raw,
        module_deps_raw,
        dead_candidates_raw,
        referenced_names_raw,
        referenced_qualnames_raw,
        import_names_raw,
        class_names_raw,
        security_surfaces_raw,
        typing_coverage_raw,
        docstring_coverage_raw,
        api_surface_raw,
        source_stats,
        typed_structural_findings,
    )


def _attach_optional_cache_sections(
    entry: CacheEntry,
    *,
    typing_coverage: ModuleTypingCoverageDict | None = None,
    docstring_coverage: ModuleDocstringCoverageDict | None = None,
    api_surface: ModuleApiSurfaceDict | None = None,
    security_surfaces: list[SecuritySurfaceDict] | None = None,
    source_stats: SourceStatsDict | None = None,
    structural_findings: list[StructuralFindingGroupDict] | None = None,
) -> CacheEntry:
    if typing_coverage is not None:
        entry["typing_coverage"] = typing_coverage
    if docstring_coverage is not None:
        entry["docstring_coverage"] = docstring_coverage
    if api_surface is not None:
        entry["api_surface"] = api_surface
    if security_surfaces is not None:
        entry["security_surfaces"] = security_surfaces
    if source_stats is not None:
        entry["source_stats"] = source_stats
    if structural_findings is not None:
        entry["structural_findings"] = structural_findings
    return entry


def _canonicalize_cache_entry(entry: CacheEntry) -> CacheEntry:
    class_metrics_sorted = sorted(
        entry["class_metrics"],
        key=lambda item: (
            item["start_line"],
            item["end_line"],
            item["qualname"],
        ),
    )
    for metric in class_metrics_sorted:
        coupled_classes = metric.get("coupled_classes", [])
        if coupled_classes:
            metric["coupled_classes"] = sorted(set(coupled_classes))

    module_deps_sorted = sorted(
        entry["module_deps"],
        key=lambda item: (
            item["source"],
            item["target"],
            item["import_type"],
            item["line"],
        ),
    )
    dead_candidates_normalized: list[DeadCandidateDict] = []
    for candidate in entry["dead_candidates"]:
        suppressed_rules = candidate.get("suppressed_rules", [])
        normalized_candidate = DeadCandidateDict(
            qualname=candidate["qualname"],
            local_name=candidate["local_name"],
            filepath=candidate["filepath"],
            start_line=candidate["start_line"],
            end_line=candidate["end_line"],
            kind=candidate["kind"],
        )
        if _is_string_list(suppressed_rules):
            normalized_rules = sorted(set(suppressed_rules))
            if normalized_rules:
                normalized_candidate["suppressed_rules"] = normalized_rules
        dead_candidates_normalized.append(normalized_candidate)

    dead_candidates_sorted = sorted(
        dead_candidates_normalized,
        key=lambda item: (
            item["start_line"],
            item["end_line"],
            item["qualname"],
            item["local_name"],
            item["kind"],
            tuple(item.get("suppressed_rules", [])),
        ),
    )

    result: CacheEntry = {
        "stat": entry["stat"],
        "units": entry["units"],
        "blocks": entry["blocks"],
        "segments": entry["segments"],
        "class_metrics": class_metrics_sorted,
        "module_deps": module_deps_sorted,
        "dead_candidates": dead_candidates_sorted,
        "referenced_names": sorted(set(entry["referenced_names"])),
        "referenced_qualnames": sorted(set(entry.get("referenced_qualnames", []))),
        "import_names": sorted(set(entry["import_names"])),
        "class_names": sorted(set(entry["class_names"])),
        "security_surfaces": sorted(
            entry.get("security_surfaces", []),
            key=lambda item: (
                item["start_line"],
                item["end_line"],
                item["qualname"],
                item["category"],
                item["capability"],
                item["evidence_symbol"],
            ),
        ),
    }
    typing_coverage = entry.get("typing_coverage")
    if typing_coverage is not None:
        result["typing_coverage"] = ModuleTypingCoverageDict(
            module=typing_coverage["module"],
            filepath=typing_coverage["filepath"],
            callable_count=typing_coverage["callable_count"],
            params_total=typing_coverage["params_total"],
            params_annotated=typing_coverage["params_annotated"],
            returns_total=typing_coverage["returns_total"],
            returns_annotated=typing_coverage["returns_annotated"],
            any_annotation_count=typing_coverage["any_annotation_count"],
        )
    docstring_coverage = entry.get("docstring_coverage")
    if docstring_coverage is not None:
        result["docstring_coverage"] = ModuleDocstringCoverageDict(
            module=docstring_coverage["module"],
            filepath=docstring_coverage["filepath"],
            public_symbol_total=docstring_coverage["public_symbol_total"],
            public_symbol_documented=docstring_coverage["public_symbol_documented"],
        )
    api_surface = entry.get("api_surface")
    if api_surface is not None:
        symbols = sorted(
            api_surface["symbols"],
            key=lambda item: (
                item["qualname"],
                item["kind"],
                item["start_line"],
                item["end_line"],
            ),
        )
        normalized_symbols = [
            PublicSymbolDict(
                qualname=symbol["qualname"],
                kind=symbol["kind"],
                start_line=symbol["start_line"],
                end_line=symbol["end_line"],
                params=[
                    ApiParamSpecDict(
                        name=param["name"],
                        kind=param["kind"],
                        has_default=param["has_default"],
                        annotation_hash=param["annotation_hash"],
                    )
                    for param in symbol.get("params", [])
                ],
                returns_hash=symbol.get("returns_hash", ""),
                exported_via=symbol.get("exported_via", "name"),
            )
            for symbol in symbols
        ]
        result["api_surface"] = ModuleApiSurfaceDict(
            module=api_surface["module"],
            filepath=api_surface["filepath"],
            all_declared=sorted(set(api_surface.get("all_declared", []))),
            symbols=normalized_symbols,
        )
    structural_findings = entry.get("structural_findings")
    if structural_findings is not None:
        result["structural_findings"] = structural_findings
    source_stats = entry.get("source_stats")
    if source_stats is not None:
        result["source_stats"] = source_stats
    return result


__all__ = [
    "_as_file_stat_dict",
    "_as_module_api_surface_dict",
    "_as_module_docstring_coverage_dict",
    "_as_module_typing_coverage_dict",
    "_as_source_stats_dict",
    "_as_typed_block_list",
    "_as_typed_class_metrics_list",
    "_as_typed_dead_candidates_list",
    "_as_typed_module_deps_list",
    "_as_typed_security_surfaces_list",
    "_as_typed_segment_list",
    "_as_typed_string_list",
    "_as_typed_unit_list",
    "_attach_optional_cache_sections",
    "_canonicalize_cache_entry",
    "_decode_optional_cache_sections",
    "_has_cache_entry_container_shape",
    "_is_canonical_cache_entry",
    "_normalized_optional_string_list",
]
