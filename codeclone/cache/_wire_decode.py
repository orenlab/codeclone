# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from ..models import BlockGroupItem, FunctionGroupItem, SegmentGroupItem
from ._canonicalize import _attach_optional_cache_sections
from ._wire_helpers import (
    _decode_optional_wire_coupled_classes,
    _decode_optional_wire_items,
    _decode_optional_wire_items_for_filepath,
    _decode_optional_wire_names,
    _decode_optional_wire_row,
    _decode_wire_class_metric_fields,
    _decode_wire_int_fields,
    _decode_wire_named_sized_span,
    _decode_wire_named_span,
    _decode_wire_qualname_span,
    _decode_wire_qualname_span_size,
    _decode_wire_row,
    _decode_wire_str_fields,
    _decode_wire_unit_core_fields,
    _decode_wire_unit_flow_profiles,
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
    SegmentDict,
    SourceStatsDict,
    StructuralFindingGroupDict,
    StructuralFindingOccurrenceDict,
    UnitDict,
    _normalize_cached_structural_groups,
)
from .integrity import (
    as_int_or_none as _as_int,
)
from .integrity import (
    as_object_list as _as_list,
)
from .integrity import (
    as_str_dict as _as_str_dict,
)
from .integrity import (
    as_str_or_none as _as_str,
)


def _decode_wire_stat(obj: dict[str, object]) -> FileStat | None:
    stat_list = _as_list(obj.get("st"))
    if stat_list is None or len(stat_list) != 2:
        return None
    mtime_ns = _as_int(stat_list[0])
    size = _as_int(stat_list[1])
    if mtime_ns is None or size is None:
        return None
    return FileStat(mtime_ns=mtime_ns, size=size)


def _decode_optional_wire_source_stats(
    *,
    obj: dict[str, object],
) -> SourceStatsDict | None:
    row = _decode_optional_wire_row(obj=obj, key="ss", expected_len=4)
    if row is None:
        return None
    counts = _decode_wire_int_fields(row, 0, 1, 2, 3)
    if counts is None:
        return None
    lines, functions, methods, classes = counts
    if any(value < 0 for value in counts):
        return None
    return SourceStatsDict(
        lines=lines,
        functions=functions,
        methods=methods,
        classes=classes,
    )


def _decode_wire_file_entry(value: object, filepath: str) -> CacheEntry | None:
    obj = _as_str_dict(value)
    if obj is None:
        return None

    stat = _decode_wire_stat(obj)
    if stat is None:
        return None
    source_stats = _decode_optional_wire_source_stats(obj=obj)
    file_sections = _decode_wire_file_sections(obj=obj, filepath=filepath)
    if file_sections is None:
        return None
    (
        units,
        blocks,
        segments,
        class_metrics,
        module_deps,
        dead_candidates,
    ) = file_sections
    name_sections = _decode_wire_name_sections(obj=obj)
    if name_sections is None:
        return None
    (
        referenced_names,
        referenced_qualnames,
        import_names,
        class_names,
    ) = name_sections
    typing_coverage = _decode_optional_wire_typing_coverage(obj=obj, filepath=filepath)
    docstring_coverage = _decode_optional_wire_docstring_coverage(
        obj=obj,
        filepath=filepath,
    )
    api_surface = _decode_optional_wire_api_surface(obj=obj, filepath=filepath)
    coupled_classes_map = _decode_optional_wire_coupled_classes(obj=obj, key="cc")
    if coupled_classes_map is None:
        return None

    for metric in class_metrics:
        names = coupled_classes_map.get(metric["qualname"], [])
        if names:
            metric["coupled_classes"] = names

    has_structural_findings = "sf" in obj
    structural_findings = _decode_wire_structural_findings_optional(obj)
    if structural_findings is None:
        return None

    return _attach_optional_cache_sections(
        CacheEntry(
            stat=stat,
            units=units,
            blocks=blocks,
            segments=segments,
            class_metrics=class_metrics,
            module_deps=module_deps,
            dead_candidates=dead_candidates,
            referenced_names=referenced_names,
            referenced_qualnames=referenced_qualnames,
            import_names=import_names,
            class_names=class_names,
        ),
        typing_coverage=typing_coverage,
        docstring_coverage=docstring_coverage,
        api_surface=api_surface,
        source_stats=source_stats,
        structural_findings=(
            _normalize_cached_structural_groups(structural_findings, filepath=filepath)
            if has_structural_findings
            else None
        ),
    )


def _decode_wire_file_sections(
    *,
    obj: dict[str, object],
    filepath: str,
) -> (
    tuple[
        list[UnitDict],
        list[BlockDict],
        list[SegmentDict],
        list[ClassMetricsDict],
        list[ModuleDepDict],
        list[DeadCandidateDict],
    ]
    | None
):
    units = _decode_optional_wire_items_for_filepath(
        obj=obj,
        key="u",
        filepath=filepath,
        decode_item=_decode_wire_unit,
    )
    blocks = _decode_optional_wire_items_for_filepath(
        obj=obj,
        key="b",
        filepath=filepath,
        decode_item=_decode_wire_block,
    )
    segments = _decode_optional_wire_items_for_filepath(
        obj=obj,
        key="s",
        filepath=filepath,
        decode_item=_decode_wire_segment,
    )
    class_metrics = _decode_optional_wire_items_for_filepath(
        obj=obj,
        key="cm",
        filepath=filepath,
        decode_item=_decode_wire_class_metric,
    )
    module_deps = _decode_optional_wire_items(
        obj=obj,
        key="md",
        decode_item=_decode_wire_module_dep,
    )
    dead_candidates = _decode_optional_wire_items_for_filepath(
        obj=obj,
        key="dc",
        filepath=filepath,
        decode_item=_decode_wire_dead_candidate,
    )
    if (
        units is None
        or blocks is None
        or segments is None
        or class_metrics is None
        or module_deps is None
        or dead_candidates is None
    ):
        return None
    return (
        units,
        blocks,
        segments,
        class_metrics,
        module_deps,
        dead_candidates,
    )


def _decode_wire_name_sections(
    *,
    obj: dict[str, object],
) -> tuple[list[str], list[str], list[str], list[str]] | None:
    referenced_names = _decode_optional_wire_names(obj=obj, key="rn")
    referenced_qualnames = _decode_optional_wire_names(obj=obj, key="rq")
    import_names = _decode_optional_wire_names(obj=obj, key="in")
    class_names = _decode_optional_wire_names(obj=obj, key="cn")
    if (
        referenced_names is None
        or referenced_qualnames is None
        or import_names is None
        or class_names is None
    ):
        return None
    return (
        referenced_names,
        referenced_qualnames,
        import_names,
        class_names,
    )


def _decode_optional_wire_typing_coverage(
    *,
    obj: dict[str, object],
    filepath: str,
) -> ModuleTypingCoverageDict | None:
    module_and_ints = _decode_optional_wire_module_ints(
        obj=obj,
        key="tc",
        expected_len=7,
        int_indexes=(1, 2, 3, 4, 5, 6),
    )
    if module_and_ints is None:
        return None
    module, ints = module_and_ints
    (
        callable_count,
        params_total,
        params_annotated,
        returns_total,
        returns_annotated,
        any_annotation_count,
    ) = ints
    return ModuleTypingCoverageDict(
        module=module,
        filepath=filepath,
        callable_count=callable_count,
        params_total=params_total,
        params_annotated=params_annotated,
        returns_total=returns_total,
        returns_annotated=returns_annotated,
        any_annotation_count=any_annotation_count,
    )


def _decode_optional_wire_docstring_coverage(
    *,
    obj: dict[str, object],
    filepath: str,
) -> ModuleDocstringCoverageDict | None:
    module_and_counts = _decode_optional_wire_module_ints(
        obj=obj,
        key="dg",
        expected_len=3,
        int_indexes=(1, 2),
    )
    if module_and_counts is None:
        return None
    module, counts = module_and_counts
    public_symbol_total, public_symbol_documented = counts
    return ModuleDocstringCoverageDict(
        module=module,
        filepath=filepath,
        public_symbol_total=public_symbol_total,
        public_symbol_documented=public_symbol_documented,
    )


def _decode_optional_wire_api_surface(
    *,
    obj: dict[str, object],
    filepath: str,
) -> ModuleApiSurfaceDict | None:
    row = _decode_optional_wire_row(obj=obj, key="as", expected_len=3)
    if row is None:
        return None
    module = _as_str(row[0])
    all_declared = _decode_optional_wire_names(obj={"ad": row[1]}, key="ad")
    symbols_raw = _as_list(row[2])
    if module is None or all_declared is None or symbols_raw is None:
        return None
    symbols: list[PublicSymbolDict] = []
    for symbol_raw in symbols_raw:
        decoded_symbol = _decode_wire_api_surface_symbol(symbol_raw)
        if decoded_symbol is None:
            return None
        symbols.append(decoded_symbol)
    return ModuleApiSurfaceDict(
        module=module,
        filepath=filepath,
        all_declared=sorted(set(all_declared)),
        symbols=symbols,
    )


def _decode_optional_wire_module_ints(
    *,
    obj: dict[str, object],
    key: str,
    expected_len: int,
    int_indexes: tuple[int, ...],
) -> tuple[str, tuple[int, ...]] | None:
    row = _decode_optional_wire_row(obj=obj, key=key, expected_len=expected_len)
    if row is None:
        return None
    module = _as_str(row[0])
    ints = _decode_wire_int_fields(row, *int_indexes)
    if module is None or ints is None:
        return None
    return module, ints


def _decode_wire_api_surface_symbol(
    value: object,
) -> PublicSymbolDict | None:
    symbol_row = _decode_wire_row(value, valid_lengths={7})
    if symbol_row is None:
        return None
    str_fields = _decode_wire_str_fields(symbol_row, 0, 1, 4, 5)
    int_fields = _decode_wire_int_fields(symbol_row, 2, 3)
    params_raw = _as_list(symbol_row[6])
    if str_fields is None or int_fields is None or params_raw is None:
        return None
    qualname, kind, exported_via, returns_hash = str_fields
    start_line, end_line = int_fields
    params: list[ApiParamSpecDict] = []
    for param_raw in params_raw:
        decoded_param = _decode_wire_api_param_spec(param_raw)
        if decoded_param is None:
            return None
        params.append(decoded_param)
    return PublicSymbolDict(
        qualname=qualname,
        kind=kind,
        start_line=start_line,
        end_line=end_line,
        params=params,
        returns_hash=returns_hash,
        exported_via=exported_via,
    )


def _decode_wire_api_param_spec(
    value: object,
) -> ApiParamSpecDict | None:
    param_row = _decode_wire_row(value, valid_lengths={4})
    if param_row is None:
        return None
    str_fields = _decode_wire_str_fields(param_row, 0, 1, 3)
    int_fields = _decode_wire_int_fields(param_row, 2)
    if str_fields is None or int_fields is None:
        return None
    name, param_kind, annotation_hash = str_fields
    (has_default_raw,) = int_fields
    return ApiParamSpecDict(
        name=name,
        kind=param_kind,
        has_default=bool(has_default_raw),
        annotation_hash=annotation_hash,
    )


def _decode_wire_structural_findings_optional(
    obj: dict[str, object],
) -> list[StructuralFindingGroupDict] | None:
    raw = obj.get("sf")
    if raw is None:
        return []
    groups_raw = _as_list(raw)
    if groups_raw is None:
        return None
    groups: list[StructuralFindingGroupDict] = []
    for group_raw in groups_raw:
        group = _decode_wire_structural_group(group_raw)
        if group is None:
            return None
        groups.append(group)
    return groups


def _decode_wire_structural_group(value: object) -> StructuralFindingGroupDict | None:
    group_row = _decode_wire_row(value, valid_lengths={4})
    if group_row is None:
        return None
    str_fields = _decode_wire_str_fields(group_row, 0, 1)
    items_raw = _as_list(group_row[3])
    signature = _decode_wire_structural_signature(group_row[2])
    if str_fields is None or items_raw is None or signature is None:
        return None
    finding_kind, finding_key = str_fields
    items: list[StructuralFindingOccurrenceDict] = []
    for item_raw in items_raw:
        item = _decode_wire_structural_occurrence(item_raw)
        if item is None:
            return None
        items.append(item)
    return StructuralFindingGroupDict(
        finding_kind=finding_kind,
        finding_key=finding_key,
        signature=signature,
        items=items,
    )


def _decode_wire_structural_signature(value: object) -> dict[str, str] | None:
    sig_raw = _as_list(value)
    if sig_raw is None:
        return None
    signature: dict[str, str] = {}
    for pair in sig_raw:
        pair_list = _as_list(pair)
        if pair_list is None or len(pair_list) != 2:
            return None
        key = _as_str(pair_list[0])
        val = _as_str(pair_list[1])
        if key is None or val is None:
            return None
        signature[key] = val
    return signature


def _decode_wire_structural_occurrence(
    value: object,
) -> StructuralFindingOccurrenceDict | None:
    item_list = _as_list(value)
    if item_list is None or len(item_list) != 3:
        return None
    qualname = _as_str(item_list[0])
    start = _as_int(item_list[1])
    end = _as_int(item_list[2])
    if qualname is None or start is None or end is None:
        return None
    return StructuralFindingOccurrenceDict(
        qualname=qualname,
        start=start,
        end=end,
    )


def _decode_wire_unit(value: object, filepath: str) -> UnitDict | None:
    decoded = _decode_wire_named_span(value, valid_lengths={11, 17})
    if decoded is None:
        return None
    row, qualname, start_line, end_line = decoded
    core_fields = _decode_wire_unit_core_fields(row)
    flow_profiles = _decode_wire_unit_flow_profiles(row)
    if core_fields is None or flow_profiles is None:
        return None
    (
        loc,
        stmt_count,
        fingerprint,
        loc_bucket,
        cyclomatic_complexity,
        nesting_depth,
        risk,
        raw_hash,
    ) = core_fields
    (
        entry_guard_count,
        entry_guard_terminal_profile,
        entry_guard_has_side_effect_before,
        terminal_kind,
        try_finally_profile,
        side_effect_order_profile,
    ) = flow_profiles
    return FunctionGroupItem(
        qualname=qualname,
        filepath=filepath,
        start_line=start_line,
        end_line=end_line,
        loc=loc,
        stmt_count=stmt_count,
        fingerprint=fingerprint,
        loc_bucket=loc_bucket,
        cyclomatic_complexity=cyclomatic_complexity,
        nesting_depth=nesting_depth,
        risk=risk,
        raw_hash=raw_hash,
        entry_guard_count=entry_guard_count,
        entry_guard_terminal_profile=entry_guard_terminal_profile,
        entry_guard_has_side_effect_before=entry_guard_has_side_effect_before,
        terminal_kind=terminal_kind,
        try_finally_profile=try_finally_profile,
        side_effect_order_profile=side_effect_order_profile,
    )


def _decode_wire_block(value: object, filepath: str) -> BlockDict | None:
    decoded = _decode_wire_named_sized_span(value, valid_lengths={5})
    if decoded is None:
        return None
    row, qualname, start_line, end_line, size = decoded
    block_hash = _as_str(row[4])
    if block_hash is None:
        return None

    return BlockGroupItem(
        block_hash=block_hash,
        filepath=filepath,
        qualname=qualname,
        start_line=start_line,
        end_line=end_line,
        size=size,
    )


def _decode_wire_segment(value: object, filepath: str) -> SegmentDict | None:
    decoded = _decode_wire_named_sized_span(value, valid_lengths={6})
    if decoded is None:
        return None
    row, qualname, start_line, end_line, size = decoded
    segment_hash = _as_str(row[4])
    segment_sig = _as_str(row[5])
    if segment_hash is None or segment_sig is None:
        return None

    return SegmentGroupItem(
        segment_hash=segment_hash,
        segment_sig=segment_sig,
        filepath=filepath,
        qualname=qualname,
        start_line=start_line,
        end_line=end_line,
        size=size,
    )


def _decode_wire_class_metric(
    value: object,
    filepath: str,
) -> ClassMetricsDict | None:
    decoded = _decode_wire_named_span(value, valid_lengths={9})
    if decoded is None:
        return None
    row, qualname, start_line, end_line = decoded
    metric_fields = _decode_wire_class_metric_fields(row)
    if metric_fields is None:
        return None
    cbo, lcom4, method_count, instance_var_count, risk_coupling, risk_cohesion = (
        metric_fields
    )
    return ClassMetricsDict(
        qualname=qualname,
        filepath=filepath,
        start_line=start_line,
        end_line=end_line,
        cbo=cbo,
        lcom4=lcom4,
        method_count=method_count,
        instance_var_count=instance_var_count,
        risk_coupling=risk_coupling,
        risk_cohesion=risk_cohesion,
    )


def _decode_wire_module_dep(value: object) -> ModuleDepDict | None:
    row = _as_list(value)
    if row is None or len(row) != 4:
        return None
    source = _as_str(row[0])
    target = _as_str(row[1])
    import_type = _as_str(row[2])
    line = _as_int(row[3])
    if source is None or target is None or import_type is None or line is None:
        return None
    return ModuleDepDict(
        source=source,
        target=target,
        import_type=import_type,
        line=line,
    )


def _decode_wire_dead_candidate(
    value: object,
    filepath: str,
) -> DeadCandidateDict | None:
    row = _decode_wire_row(value, valid_lengths={5, 6})
    if row is None:
        return None
    str_fields = _decode_wire_str_fields(row, 0, 1, 4)
    int_fields = _decode_wire_int_fields(row, 2, 3)
    suppressed_rules: list[str] | None = []
    if len(row) == 6:
        raw_rules = _as_list(row[5])
        if raw_rules is None or not all(isinstance(rule, str) for rule in raw_rules):
            return None
        suppressed_rules = sorted({str(rule) for rule in raw_rules if str(rule)})
    if str_fields is None or int_fields is None:
        return None
    qualname, local_name, kind = str_fields
    start_line, end_line = int_fields
    decoded = DeadCandidateDict(
        qualname=qualname,
        local_name=local_name,
        filepath=filepath,
        start_line=start_line,
        end_line=end_line,
        kind=kind,
    )
    if suppressed_rules:
        decoded["suppressed_rules"] = suppressed_rules
    return decoded


__all__ = [
    "_decode_optional_wire_api_surface",
    "_decode_optional_wire_coupled_classes",
    "_decode_optional_wire_docstring_coverage",
    "_decode_optional_wire_items",
    "_decode_optional_wire_items_for_filepath",
    "_decode_optional_wire_module_ints",
    "_decode_optional_wire_names",
    "_decode_optional_wire_row",
    "_decode_optional_wire_source_stats",
    "_decode_optional_wire_typing_coverage",
    "_decode_wire_api_param_spec",
    "_decode_wire_api_surface_symbol",
    "_decode_wire_block",
    "_decode_wire_class_metric",
    "_decode_wire_class_metric_fields",
    "_decode_wire_dead_candidate",
    "_decode_wire_file_entry",
    "_decode_wire_file_sections",
    "_decode_wire_int_fields",
    "_decode_wire_module_dep",
    "_decode_wire_name_sections",
    "_decode_wire_named_sized_span",
    "_decode_wire_named_span",
    "_decode_wire_qualname_span",
    "_decode_wire_qualname_span_size",
    "_decode_wire_row",
    "_decode_wire_segment",
    "_decode_wire_stat",
    "_decode_wire_str_fields",
    "_decode_wire_structural_findings_optional",
    "_decode_wire_structural_group",
    "_decode_wire_structural_occurrence",
    "_decode_wire_structural_signature",
    "_decode_wire_unit",
    "_decode_wire_unit_core_fields",
    "_decode_wire_unit_flow_profiles",
]
