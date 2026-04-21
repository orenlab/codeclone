# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from ..cache.entries import (
    CacheEntry,
    ClassMetricsDict,
    DeadCandidateDict,
    ModuleDepDict,
    StructuralFindingGroupDict,
)
from ..models import (
    ApiParamSpec,
    ClassMetrics,
    DeadCandidate,
    ModuleApiSurface,
    ModuleDep,
    ModuleDocstringCoverage,
    ModuleTypingCoverage,
    PublicSymbol,
    StructuralFindingGroup,
    StructuralFindingOccurrence,
)
from ..paths import is_test_filepath
from ..utils.coerce import as_mapping
from ._types import _as_sorted_str_tuple

_ApiParamKind = Literal["pos_only", "pos_or_kw", "vararg", "kw_only", "kwarg"]
_PublicSymbolKind = Literal["function", "class", "method", "constant"]
_ExportedViaKind = Literal["all", "name"]
_RiskLevel = Literal["low", "medium", "high"]
_ImportType = Literal["import", "from_import"]
_DeadCandidateKind = Literal["function", "class", "method", "import"]


def _api_param_kind(value: object) -> _ApiParamKind | None:
    match value:
        case "pos_only":
            return "pos_only"
        case "pos_or_kw":
            return "pos_or_kw"
        case "vararg":
            return "vararg"
        case "kw_only":
            return "kw_only"
        case "kwarg":
            return "kwarg"
        case _:
            return None


def _public_symbol_kind(value: object) -> _PublicSymbolKind | None:
    match value:
        case "function":
            return "function"
        case "class":
            return "class"
        case "method":
            return "method"
        case "constant":
            return "constant"
        case _:
            return None


def _exported_via_kind(value: object) -> _ExportedViaKind | None:
    match value:
        case "all":
            return "all"
        case "name":
            return "name"
        case _:
            return None


def _risk_level(value: object) -> _RiskLevel | None:
    match value:
        case "low":
            return "low"
        case "medium":
            return "medium"
        case "high":
            return "high"
        case _:
            return None


def _import_type(value: object) -> _ImportType | None:
    match value:
        case "import":
            return "import"
        case "from_import":
            return "from_import"
        case _:
            return None


def _dead_candidate_kind(value: object) -> _DeadCandidateKind | None:
    match value:
        case "function":
            return "function"
        case "class":
            return "class"
        case "method":
            return "method"
        case "import":
            return "import"
        case _:
            return None


def decode_cached_structural_finding_group(
    group_dict: StructuralFindingGroupDict,
    filepath: str,
) -> StructuralFindingGroup:
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


def usable_cached_source_stats(
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
    if not isinstance(value, Mapping):
        return None
    row = as_mapping(value)
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


def _api_param_fields(
    row: Mapping[str, object],
) -> tuple[str, _ApiParamKind, bool, str] | None:
    name = row.get("name")
    validated_kind = _api_param_kind(row.get("kind"))
    has_default = row.get("has_default")
    annotation_hash = row.get("annotation_hash", "")
    if (
        not isinstance(name, str)
        or validated_kind is None
        or not isinstance(has_default, bool)
        or not isinstance(annotation_hash, str)
    ):
        return None
    return name, validated_kind, has_default, annotation_hash


def _typing_coverage_from_cache_dict(value: object) -> ModuleTypingCoverage | None:
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
    return ModuleTypingCoverage(
        module=module,
        filepath=filepath,
        callable_count=int_fields[0],
        params_total=int_fields[1],
        params_annotated=int_fields[2],
        returns_total=int_fields[3],
        returns_annotated=int_fields[4],
        any_annotation_count=int_fields[5],
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
    return ModuleDocstringCoverage(
        module=module,
        filepath=filepath,
        public_symbol_total=totals[0],
        public_symbol_documented=totals[1],
    )


def _api_param_spec_from_cache_dict(value: object) -> ApiParamSpec | None:
    row = as_mapping(value)
    if not row:
        return None
    fields = _api_param_fields(row)
    if fields is None:
        return None
    name, validated_kind, has_default, annotation_hash = fields
    return ApiParamSpec(
        name=name,
        kind=validated_kind,
        has_default=has_default,
        annotation_hash=annotation_hash,
    )


def _public_symbol_from_cache_dict(value: object) -> PublicSymbol | None:
    row = as_mapping(value)
    if not row:
        return None
    qualname = row.get("qualname")
    start_line = row.get("start_line")
    end_line = row.get("end_line")
    returns_hash = row.get("returns_hash", "")
    params_raw = row.get("params", [])
    validated_kind = _public_symbol_kind(row.get("kind"))
    validated_exported_via = _exported_via_kind(row.get("exported_via", "name"))
    if (
        not isinstance(qualname, str)
        or validated_kind is None
        or not isinstance(start_line, int)
        or not isinstance(end_line, int)
        or validated_exported_via is None
        or not isinstance(returns_hash, str)
        or not isinstance(params_raw, list)
    ):
        return None
    params: list[ApiParamSpec] = []
    for param in params_raw:
        if not isinstance(param, dict):
            return None
        parsed = _api_param_spec_from_cache_dict(param)
        if parsed is None:
            return None
        params.append(parsed)
    return PublicSymbol(
        qualname=qualname,
        kind=validated_kind,
        start_line=start_line,
        end_line=end_line,
        params=tuple(params),
        returns_hash=returns_hash,
        exported_via=validated_exported_via,
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
        parsed = _public_symbol_from_cache_dict(item)
        if parsed is None:
            return None
        symbols.append(parsed)
    return ModuleApiSurface(
        module=module,
        filepath=filepath,
        all_declared=tuple(sorted(set(all_declared_raw))) or None,
        symbols=tuple(sorted(symbols, key=lambda item: item.qualname)),
    )


def _class_metric_from_cache_row(metric_row: ClassMetricsDict) -> ClassMetrics | None:
    risk_coupling = _risk_level(metric_row["risk_coupling"])
    risk_cohesion = _risk_level(metric_row["risk_cohesion"])
    if (
        not metric_row.get("qualname")
        or not metric_row.get("filepath")
        or risk_coupling is None
        or risk_cohesion is None
    ):
        return None
    return ClassMetrics(
        qualname=metric_row["qualname"],
        filepath=metric_row["filepath"],
        start_line=metric_row["start_line"],
        end_line=metric_row["end_line"],
        cbo=metric_row["cbo"],
        lcom4=metric_row["lcom4"],
        method_count=metric_row["method_count"],
        instance_var_count=metric_row["instance_var_count"],
        risk_coupling=risk_coupling,
        risk_cohesion=risk_cohesion,
        coupled_classes=_as_sorted_str_tuple(metric_row.get("coupled_classes", [])),
    )


def _module_dep_from_cache_row(dep_row: ModuleDepDict) -> ModuleDep | None:
    import_type = _import_type(dep_row["import_type"])
    if not dep_row.get("source") or not dep_row.get("target") or import_type is None:
        return None
    return ModuleDep(
        source=dep_row["source"],
        target=dep_row["target"],
        import_type=import_type,
        line=dep_row["line"],
    )


def _dead_candidate_from_cache_row(dead_row: DeadCandidateDict) -> DeadCandidate | None:
    kind = _dead_candidate_kind(dead_row["kind"])
    if (
        not dead_row.get("qualname")
        or not dead_row.get("local_name")
        or not dead_row.get("filepath")
        or kind is None
    ):
        return None
    return DeadCandidate(
        qualname=dead_row["qualname"],
        local_name=dead_row["local_name"],
        filepath=dead_row["filepath"],
        start_line=dead_row["start_line"],
        end_line=dead_row["end_line"],
        kind=kind,
        suppressed_rules=_as_sorted_str_tuple(dead_row.get("suppressed_rules", [])),
    )


def load_cached_metrics_extended(
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
    class_metrics_items: list[ClassMetrics] = []
    for metric_row in class_metrics_rows:
        parsed_metric = _class_metric_from_cache_row(metric_row)
        if parsed_metric is not None:
            class_metrics_items.append(parsed_metric)
    class_metrics = tuple(class_metrics_items)
    module_dep_rows: list[ModuleDepDict] = entry.get("module_deps", [])
    module_dep_items: list[ModuleDep] = []
    for dep_row in module_dep_rows:
        parsed_dep = _module_dep_from_cache_row(dep_row)
        if parsed_dep is not None:
            module_dep_items.append(parsed_dep)
    module_deps = tuple(module_dep_items)
    dead_rows: list[DeadCandidateDict] = entry.get("dead_candidates", [])
    dead_candidate_items: list[DeadCandidate] = []
    for dead_row in dead_rows:
        parsed_dead = _dead_candidate_from_cache_row(dead_row)
        if parsed_dead is not None:
            dead_candidate_items.append(parsed_dead)
    dead_candidates = tuple(dead_candidate_items)
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
    return (
        class_metrics,
        module_deps,
        dead_candidates,
        referenced_names,
        referenced_qualnames,
        _typing_coverage_from_cache_dict(entry.get("typing_coverage")),
        _docstring_coverage_from_cache_dict(entry.get("docstring_coverage")),
        _api_surface_from_cache_dict(entry.get("api_surface")),
    )
