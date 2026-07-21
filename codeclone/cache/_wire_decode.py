# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from typing import Literal, TypeGuard

from ..models import (
    ApiParamSpecDict,
    BlockGroupItem,
    CacheDependentPayload,
    CacheEntryV3,
    CacheNeutralBlock,
    CacheNeutralPayload,
    CacheNeutralSegment,
    CacheNeutralUnit,
    ClassMetricsDict,
    DeadCandidateDict,
    DependencyResolution,
    DigestObject,
    EventKind,
    FactRef,
    FactRefKind,
    FileStat,
    FunctionContractSummary,
    FunctionGroupItem,
    FunctionRelationshipFactsDict,
    GitBlobIdentity,
    GitObjectFormat,
    ModuleApiSurfaceDict,
    ModuleDepDict,
    ModuleDocstringCoverageDict,
    ModuleTypingCoverageDict,
    PublicSymbolDict,
    RelationshipRecordDict,
    RuntimeReachabilityFactDict,
    SecuritySurfaceDict,
    SegmentGroupItem,
    SemanticEvent,
    SemanticEventResolution,
    SemanticFileFacts,
    SourceStatsDict,
    StructuralFindingGroupDict,
    StructuralFindingOccurrenceDict,
)
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
    BlockDict,
    SegmentDict,
    UnitDict,
    _as_relationship_kind,
    _as_relationship_origin_lane,
    _as_relationship_resolution_status,
    _as_runtime_reachability_confidence,
    _as_runtime_reachability_edge_kind,
    _as_runtime_reachability_framework,
    _as_runtime_reachability_target_kind,
    _as_security_surface_category,
    _as_security_surface_classification_mode,
    _as_security_surface_evidence_kind,
    _as_security_surface_location_scope,
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


def _event_kind(value: object) -> EventKind | None:
    match value:
        case "artifact_write":
            return "artifact_write"
        case "assign":
            return "assign"
        case "compatibility_check":
            return "compatibility_check"
        case "compute_digest":
            return "compute_digest"
        case "construct":
            return "construct"
        case "field_write":
            return "field_write"
        case "publish_event":
            return "publish_event"
        case "resolve_identity":
            return "resolve_identity"
        case "return_value":
            return "return_value"
        case "serialize_field":
            return "serialize_field"
        case "security_observation":
            return "security_observation"
        case _:
            return None


def _is_dependency_resolution(value: object) -> TypeGuard[DependencyResolution]:
    return isinstance(value, str) and value in {
        "analyzed",
        "known_internal_not_analyzed",
        "external",
        "unresolved_relative",
        "ambiguous",
    }


def _is_module_dep_import_type(
    value: object,
) -> TypeGuard[Literal["import", "from_import"]]:
    return isinstance(value, str) and value in {"import", "from_import"}


def _fact_ref_kind(value: object) -> FactRefKind | None:
    match value:
        case "param":
            return "param"
        case "event":
            return "event"
        case "const":
            return "const"
        case "unresolved":
            return "unresolved"
        case _:
            return None


def _event_resolution(value: object) -> SemanticEventResolution | None:
    match value:
        case "resolved":
            return "resolved"
        case "unavailable":
            return "unavailable"
        case _:
            return None


def _decode_fact_ref(value: object) -> FactRef | None:
    row = _as_list(value)
    if row is None or len(row) != 2:
        return None
    kind = _fact_ref_kind(row[0])
    ref = _as_str(row[1])
    if kind is None or ref is None:
        return None
    return FactRef(kind=kind, ref=ref)


def _decode_semantic_event(value: object, *, filepath: str) -> SemanticEvent | None:
    row = _as_list(value)
    if row is None or len(row) != 8:
        return None
    event_id = _as_str(row[0])
    kind = _event_kind(row[1])
    subject = _as_str(row[2])
    inputs_raw = _as_list(row[3])
    output_raw = row[4]
    guards_raw = _as_list(row[5])
    line = _as_int(row[6])
    resolution = _event_resolution(row[7])
    if (
        event_id is None
        or kind is None
        or subject is None
        or inputs_raw is None
        or guards_raw is None
        or line is None
        or line < 1
        or resolution is None
    ):
        return None
    inputs = tuple(_decode_fact_ref(item) for item in inputs_raw)
    if any(item is None for item in inputs):
        return None
    guards = tuple(_as_str(item) for item in guards_raw)
    if any(item is None for item in guards):
        return None
    output = None if output_raw is None else _decode_fact_ref(output_raw)
    if output_raw is not None and output is None:
        return None
    return SemanticEvent(
        event_id=event_id,
        kind=kind,
        subject=subject,
        inputs=tuple(item for item in inputs if item is not None),
        output=output,
        guards=tuple(item for item in guards if item is not None),
        location=(filepath, line),
        resolution=resolution,
    )


def _decode_contract_summary(
    value: object,
    *,
    filepath: str,
) -> FunctionContractSummary | None:
    row = _as_list(value)
    if row is None or len(row) != 5:
        return None
    function = _as_str(row[0])
    events_raw = _as_list(row[1])
    flows_raw = _as_list(row[2])
    returns_raw = _as_list(row[3])
    unresolved_flow = row[4]
    if (
        function is None
        or events_raw is None
        or flows_raw is None
        or returns_raw is None
        or not isinstance(unresolved_flow, bool)
    ):
        return None
    events = tuple(
        _decode_semantic_event(item, filepath=filepath) for item in events_raw
    )
    returns = tuple(_decode_fact_ref(item) for item in returns_raw)
    if any(item is None for item in events) or any(item is None for item in returns):
        return None
    flows: list[tuple[str, str]] = []
    for item in flows_raw:
        flow = _as_list(item)
        if flow is None or len(flow) != 2:
            return None
        source = _as_str(flow[0])
        target = _as_str(flow[1])
        if source is None or target is None:
            return None
        flows.append((source, target))
    return FunctionContractSummary(
        function=function,
        events=tuple(item for item in events if item is not None),
        param_flows=tuple(flows),
        returns=tuple(item for item in returns if item is not None),
        unresolved_flow=unresolved_flow,
    )


def _decode_semantic_facts(
    obj: dict[str, object],
    *,
    filepath: str,
) -> SemanticFileFacts | None:
    events_raw = _as_list(obj.get("se"))
    summaries_raw = _as_list(obj.get("fc"))
    if events_raw is None or summaries_raw is None:
        return None
    events = tuple(
        _decode_semantic_event(item, filepath=filepath) for item in events_raw
    )
    summaries = tuple(
        _decode_contract_summary(item, filepath=filepath) for item in summaries_raw
    )
    if any(item is None for item in events) or any(item is None for item in summaries):
        return None
    return SemanticFileFacts(
        events=tuple(item for item in events if item is not None),
        function_contract_summaries=tuple(
            item for item in summaries if item is not None
        ),
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


def _decode_sha256_value(value: object, *, expected_domain: str) -> str | None:
    row = _as_list(value)
    if row is None or len(row) != 3:
        return None
    domain = _as_str(row[0])
    algorithm = _as_str(row[1])
    digest_value = _as_str(row[2])
    if domain != expected_domain or algorithm != "sha256":
        return None
    return digest_value


def _decode_profile_digest(
    value: object,
    *,
    expected_domain: str,
) -> DigestObject | None:
    digest_value = _decode_sha256_value(value, expected_domain=expected_domain)
    if digest_value is None:
        return None
    normalized_domain: Literal[
        "codeclone.cache.profile.neutral.v1",
        "codeclone.cache.profile.dependent.v1",
    ]
    if expected_domain == "codeclone.cache.profile.neutral.v1":
        normalized_domain = "codeclone.cache.profile.neutral.v1"
    elif expected_domain == "codeclone.cache.profile.dependent.v1":
        normalized_domain = "codeclone.cache.profile.dependent.v1"
    else:
        return None
    try:
        return DigestObject(
            domain=normalized_domain,
            algorithm="sha256",
            value=digest_value,
        )
    except ValueError:
        return None


def _decode_content_binding(
    obj: dict[str, object],
) -> tuple[DigestObject, GitBlobIdentity | None] | None:
    if obj.get("cb") != "1" or "gb" not in obj:
        return None
    value = _decode_sha256_value(
        obj.get("sd"), expected_domain="codeclone.source-content.v1"
    )
    if value is None:
        return None
    try:
        source_digest = DigestObject(
            domain="codeclone.source-content.v1",
            algorithm="sha256",
            value=value,
        )
    except ValueError:
        return None

    raw_blob = obj.get("gb")
    if raw_blob is None:
        return source_digest, None
    blob_row = _as_list(raw_blob)
    if blob_row is None or len(blob_row) != 2:
        return None
    object_format = _as_str(blob_row[0])
    object_id = _as_str(blob_row[1])
    if object_id is None:
        return None
    normalized_object_format: GitObjectFormat
    if object_format == "sha1":
        normalized_object_format = "sha1"
    elif object_format == "sha256":
        normalized_object_format = "sha256"
    else:
        return None
    try:
        blob = GitBlobIdentity(
            object_format=normalized_object_format,
            object_id=object_id,
        )
    except ValueError:
        return None
    return source_digest, blob


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


def _neutral_unit_from_wire(unit: UnitDict) -> CacheNeutralUnit:
    return CacheNeutralUnit(
        local_name=unit["qualname"],
        start_line=unit["start_line"],
        end_line=unit["end_line"],
        loc=unit["loc"],
        stmt_count=unit["stmt_count"],
        fingerprint=unit["fingerprint"],
        loc_bucket=unit["loc_bucket"],
        cyclomatic_complexity=unit.get("cyclomatic_complexity", 1),
        nesting_depth=unit.get("nesting_depth", 0),
        risk=unit.get("risk", "low"),
        raw_hash=unit.get("raw_hash", ""),
        entry_guard_count=unit.get("entry_guard_count", 0),
        entry_guard_terminal_profile=unit.get("entry_guard_terminal_profile", "none"),
        entry_guard_has_side_effect_before=unit.get(
            "entry_guard_has_side_effect_before", False
        ),
        terminal_kind=unit.get("terminal_kind", "fallthrough"),
        try_finally_profile=unit.get("try_finally_profile", "none"),
        side_effect_order_profile=unit.get("side_effect_order_profile", "none"),
    )


def _neutral_block_from_wire(block: BlockDict) -> CacheNeutralBlock:
    return CacheNeutralBlock(
        local_name=block["qualname"],
        start_line=block["start_line"],
        end_line=block["end_line"],
        size=block["size"],
        block_hash=block["block_hash"],
    )


def _neutral_segment_from_wire(segment: SegmentDict) -> CacheNeutralSegment:
    return CacheNeutralSegment(
        local_name=segment["qualname"],
        start_line=segment["start_line"],
        end_line=segment["end_line"],
        size=segment["size"],
        segment_hash=segment["segment_hash"],
        segment_sig=segment["segment_sig"],
    )


def _decode_wire_file_entry(value: object, filepath: str) -> CacheEntryV3 | None:
    obj = _as_str_dict(value)
    if obj is None:
        return None

    stat = _decode_wire_stat(obj)
    content_binding = _decode_content_binding(obj)
    neutral_profile = _decode_profile_digest(
        obj.get("np"), expected_domain="codeclone.cache.profile.neutral.v1"
    )
    dependent_profile = _decode_profile_digest(
        obj.get("dp"), expected_domain="codeclone.cache.profile.dependent.v1"
    )
    neutral_obj = _as_str_dict(obj.get("n"))
    dependent_obj = _as_str_dict(obj.get("d"))
    if (
        stat is None
        or content_binding is None
        or neutral_profile is None
        or dependent_profile is None
        or neutral_obj is None
        or dependent_obj is None
    ):
        return None
    source_content_digest, git_blob_id_at_write = content_binding
    source_stats = _decode_optional_wire_source_stats(obj=neutral_obj)
    semantic_facts = _decode_semantic_facts(neutral_obj, filepath=filepath)
    if source_stats is None or semantic_facts is None:
        return None
    facts_obj = dict(dependent_obj)
    facts_obj.update(neutral_obj)
    file_sections = _decode_wire_file_sections(obj=facts_obj, filepath=filepath)
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
    name_sections = _decode_wire_name_sections(obj=facts_obj)
    if name_sections is None:
        return None
    (
        referenced_names,
        referenced_qualnames,
        import_names,
        class_names,
    ) = name_sections
    typing_coverage = _decode_optional_wire_typing_coverage(
        obj=dependent_obj, filepath=filepath
    )
    docstring_coverage = _decode_optional_wire_docstring_coverage(
        obj=dependent_obj,
        filepath=filepath,
    )
    api_surface = _decode_optional_wire_api_surface(
        obj=dependent_obj, filepath=filepath
    )
    runtime_reachability = _decode_optional_wire_runtime_reachability(
        obj=dependent_obj,
        filepath=filepath,
    )
    security_surfaces = _decode_optional_wire_security_surfaces(
        obj=dependent_obj,
        filepath=filepath,
    )
    function_relationship_facts = _decode_optional_wire_function_relationship_facts(
        obj=dependent_obj,
        filepath=filepath,
    )
    coupled_classes_map = _decode_optional_wire_coupled_classes(
        obj=dependent_obj, key="cc"
    )
    if coupled_classes_map is None:
        return None
    if (
        runtime_reachability is None
        or security_surfaces is None
        or function_relationship_facts is None
    ):
        return None

    for metric in class_metrics:
        names = coupled_classes_map.get(metric["qualname"], [])
        if names:
            metric["coupled_classes"] = names

    has_structural_findings = "sf" in dependent_obj
    structural_findings = _decode_wire_structural_findings_optional(dependent_obj)
    if structural_findings is None:
        return None

    return CacheEntryV3(
        cache_content_binding_version="1",
        source_content_digest=source_content_digest,
        git_blob_id_at_write=git_blob_id_at_write,
        stat=stat,
        module_neutral_profile=neutral_profile,
        module_dependent_profile=dependent_profile,
        module_neutral=CacheNeutralPayload(
            source_stats=source_stats,
            units=tuple(_neutral_unit_from_wire(unit) for unit in units),
            blocks=tuple(_neutral_block_from_wire(block) for block in blocks),
            segments=tuple(_neutral_segment_from_wire(segment) for segment in segments),
            semantic_facts=semantic_facts,
        ),
        module_dependent=CacheDependentPayload(
            class_metrics=tuple(class_metrics),
            module_deps=tuple(module_deps),
            dead_candidates=tuple(dead_candidates),
            referenced_names=tuple(referenced_names),
            referenced_qualnames=tuple(referenced_qualnames),
            import_names=tuple(import_names),
            class_names=tuple(class_names),
            runtime_reachability=tuple(runtime_reachability),
            security_surfaces=tuple(security_surfaces),
            function_relationship_facts=tuple(function_relationship_facts),
            typing_coverage=typing_coverage,
            docstring_coverage=docstring_coverage,
            api_surface=api_surface,
            structural_findings=(
                tuple(
                    _normalize_cached_structural_groups(
                        structural_findings, filepath=filepath
                    )
                )
                if has_structural_findings
                else None
            ),
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


def _decode_optional_wire_security_surfaces(
    *,
    obj: dict[str, object],
    filepath: str,
) -> list[SecuritySurfaceDict] | None:
    rows = _decode_optional_wire_items_for_filepath(
        obj=obj,
        key="sc",
        filepath=filepath,
        decode_item=_decode_wire_security_surface,
    )
    return rows


def _decode_optional_wire_runtime_reachability(
    *,
    obj: dict[str, object],
    filepath: str,
) -> list[RuntimeReachabilityFactDict] | None:
    return _decode_optional_wire_items_for_filepath(
        obj=obj,
        key="rr",
        filepath=filepath,
        decode_item=_decode_wire_runtime_reachability,
    )


def _decode_optional_wire_function_relationship_facts(
    *,
    obj: dict[str, object],
    filepath: str,
) -> list[FunctionRelationshipFactsDict] | None:
    raw_facts = obj.get("fr")
    if raw_facts is None:
        return []
    facts_rows = _as_list(raw_facts)
    if facts_rows is None:
        return None
    decoded: list[FunctionRelationshipFactsDict] = []
    for facts_raw in facts_rows:
        facts_row = _decode_wire_row(facts_raw, valid_lengths={2})
        if facts_row is None:
            return None
        source_qualname = _as_str(facts_row[0])
        relationships_raw = _as_list(facts_row[1])
        if source_qualname is None or relationships_raw is None:
            return None
        relationships: list[RelationshipRecordDict] = []
        for relationship_raw in relationships_raw:
            relationship = _decode_wire_relationship_record(
                relationship_raw,
                source_qualname=source_qualname,
                filepath=filepath,
            )
            if relationship is None:
                return None
            relationships.append(relationship)
        decoded.append(
            FunctionRelationshipFactsDict(
                source_qualname=source_qualname,
                relationships=relationships,
            )
        )
    return decoded


def _decode_wire_relationship_record(
    value: object,
    *,
    source_qualname: str,
    filepath: str,
) -> RelationshipRecordDict | None:
    row = _decode_wire_row(value, valid_lengths={7})
    if row is None:
        return None
    relation_kind = _as_relationship_kind(_as_str(row[0]))
    resolution_status = _as_relationship_resolution_status(_as_str(row[1]))
    origin_lane = _as_relationship_origin_lane(_as_str(row[2]))
    target_qualname = row[3]
    line = _as_int(row[4])
    expression = row[5]
    resolution_rule = row[6]
    if (
        relation_kind is None
        or resolution_status is None
        or origin_lane is None
        or line is None
        or line < 1
        or (target_qualname is not None and not isinstance(target_qualname, str))
        or (expression is not None and not isinstance(expression, str))
        or (resolution_rule is not None and not isinstance(resolution_rule, str))
    ):
        return None
    if resolution_status == "resolved" and not isinstance(target_qualname, str):
        return None
    if resolution_status == "unresolved" and target_qualname is not None:
        return None
    return RelationshipRecordDict(
        relation_kind=relation_kind,
        resolution_status=resolution_status,
        origin_lane=origin_lane,
        source_qualname=source_qualname,
        target_qualname=target_qualname,
        path=filepath,
        line=line,
        expression=expression,
        resolution_rule=resolution_rule,
    )


def _decode_wire_runtime_reachability(
    row_raw: object,
    filepath: str,
) -> RuntimeReachabilityFactDict | None:
    row = _decode_wire_row(row_raw, valid_lengths={10})
    if row is None:
        return None
    target_qualname = _as_str(row[0])
    lines = _decode_wire_int_fields(row, 1, 2)
    target_kind = _as_runtime_reachability_target_kind(_as_str(row[3]))
    framework = _as_runtime_reachability_framework(_as_str(row[4]))
    edge_kind = _as_runtime_reachability_edge_kind(_as_str(row[5]))
    confidence = _as_runtime_reachability_confidence(_as_str(row[6]))
    evidence = _as_str(row[7])
    evidence_symbol = _as_str(row[8])
    source_qualname = _as_str(row[9])
    if (
        target_qualname is None
        or lines is None
        or target_kind is None
        or framework is None
        or edge_kind is None
        or confidence is None
        or evidence is None
        or evidence_symbol is None
        or source_qualname is None
    ):
        return None
    start_line, end_line = lines
    return RuntimeReachabilityFactDict(
        target_qualname=target_qualname,
        filepath=filepath,
        start_line=start_line,
        end_line=end_line,
        target_kind=target_kind,
        framework=framework,
        edge_kind=edge_kind,
        confidence=confidence,
        evidence=evidence,
        evidence_symbol=evidence_symbol,
        source_qualname=source_qualname,
    )


def _decode_wire_security_surface(
    row_raw: object,
    filepath: str,
) -> SecuritySurfaceDict | None:
    row = _decode_wire_row(row_raw, valid_lengths={10})
    if row is None:
        return None
    category = _as_security_surface_category(_as_str(row[0]))
    capability = _as_str(row[1])
    module = _as_str(row[2])
    qualname = _as_str(row[3])
    lines = _decode_wire_int_fields(row, 4, 5)
    location_scope = _as_security_surface_location_scope(_as_str(row[6]))
    classification_mode = _as_security_surface_classification_mode(_as_str(row[7]))
    evidence_kind = _as_security_surface_evidence_kind(_as_str(row[8]))
    evidence_symbol = _as_str(row[9])
    if (
        category is None
        or capability is None
        or module is None
        or qualname is None
        or lines is None
        or location_scope is None
        or classification_mode is None
        or evidence_kind is None
        or evidence_symbol is None
    ):
        return None
    start_line, end_line = lines
    return SecuritySurfaceDict(
        category=category,
        capability=capability,
        module=module,
        filepath=filepath,
        qualname=qualname,
        start_line=start_line,
        end_line=end_line,
        location_scope=location_scope,
        classification_mode=classification_mode,
        evidence_kind=evidence_kind,
        evidence_symbol=evidence_symbol,
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
    if row is None or len(row) not in {4, 10}:
        return None
    source = _as_str(row[0])
    target = _as_str(row[1])
    import_type = row[2]
    line = _as_int(row[3])
    if (
        source is None
        or target is None
        or not _is_module_dep_import_type(import_type)
        or line is None
        or isinstance(line, bool)
    ):
        return None
    base = ModuleDepDict(
        source=source,
        target=target,
        import_type=import_type,
        line=line,
    )
    if len(row) == 4:
        return base

    resolution = row[4]
    inventory_expansion = row[5]
    level = _as_int(row[6])
    requested_module_raw = row[7]
    requested_names_raw = _as_list(row[8])
    candidate_targets_raw = _as_list(row[9])
    requested_names = (
        None
        if requested_names_raw is None
        else [_as_str(item) for item in requested_names_raw]
    )
    candidate_targets = (
        None
        if candidate_targets_raw is None
        else [_as_str(item) for item in candidate_targets_raw]
    )
    if (
        not _is_dependency_resolution(resolution)
        or not isinstance(inventory_expansion, bool)
        or level is None
        or isinstance(level, bool)
        or not (requested_module_raw is None or isinstance(requested_module_raw, str))
        or requested_names is None
        or any(item is None for item in requested_names)
        or candidate_targets is None
        or any(item is None for item in candidate_targets)
    ):
        return None
    return ModuleDepDict(
        **base,
        resolution=resolution,
        inventory_expansion=inventory_expansion,
        level=level,
        requested_module=requested_module_raw,
        requested_names=[item for item in requested_names if item is not None],
        candidate_targets=[item for item in candidate_targets if item is not None],
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
