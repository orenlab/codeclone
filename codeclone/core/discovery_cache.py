# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, cast

from ..cache.entries import (
    ApiParamSpecDict,
    CacheEntry,
    ClassMetricsDict,
    DeadCandidateDict,
    ModuleDepDict,
    PublicSymbolDict,
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
from ._types import _as_sorted_str_tuple


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


def _public_symbol_from_cache_dict(value: PublicSymbolDict) -> PublicSymbol | None:
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
            kind=cast("Literal['function', 'class', 'method', 'import']", row["kind"]),
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
