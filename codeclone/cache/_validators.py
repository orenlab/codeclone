# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeGuard

from ..models import (
    ApiParamSpecDict,
    ClassMetricsDict,
    DeadCandidateDict,
    DigestObject,
    FileStat,
    FunctionRelationshipFactsDict,
    GitBlobIdentity,
    ModuleApiSurfaceDict,
    ModuleDepDict,
    ModuleDocstringCoverageDict,
    ModuleTypingCoverageDict,
    PublicSymbolDict,
    RelationshipRecordDict,
    RuntimeReachabilityFactDict,
    SecuritySurfaceDict,
    SourceStatsDict,
)
from .entries import (
    BlockDict,
    SegmentDict,
    UnitDict,
    _as_relationship_kind,
    _as_relationship_origin_lane,
    _as_relationship_resolution_status,
)


def _is_file_stat_dict(value: object) -> TypeGuard[FileStat]:
    if not isinstance(value, dict):
        return False
    return isinstance(value.get("mtime_ns"), int) and isinstance(value.get("size"), int)


def _is_source_content_digest(value: object) -> TypeGuard[DigestObject]:
    return (
        isinstance(value, DigestObject)
        and value.domain == "codeclone.source-content.v1"
        and value.algorithm == "sha256"
    )


def _is_git_blob_identity(value: object) -> TypeGuard[GitBlobIdentity]:
    return isinstance(value, GitBlobIdentity)


def _is_source_stats_dict(value: object) -> TypeGuard[SourceStatsDict]:
    if not isinstance(value, dict):
        return False
    lines = value.get("lines")
    functions = value.get("functions")
    methods = value.get("methods")
    classes = value.get("classes")
    return (
        isinstance(lines, int)
        and lines >= 0
        and isinstance(functions, int)
        and functions >= 0
        and isinstance(methods, int)
        and methods >= 0
        and isinstance(classes, int)
        and classes >= 0
    )


def _is_unit_dict(value: object) -> TypeGuard[UnitDict]:
    if not isinstance(value, dict):
        return False
    string_keys = ("qualname", "filepath", "fingerprint", "loc_bucket")
    int_keys = ("start_line", "end_line", "loc", "stmt_count")
    if not _has_typed_fields(value, string_keys=string_keys, int_keys=int_keys):
        return False
    cyclomatic_complexity = value.get("cyclomatic_complexity", 1)
    cfg_cyclomatic_complexity = value.get("cfg_cyclomatic_complexity", 1)
    nesting_depth = value.get("nesting_depth", 0)
    risk = value.get("risk", "low")
    raw_hash = value.get("raw_hash", "")
    return (
        isinstance(cyclomatic_complexity, int)
        and isinstance(cfg_cyclomatic_complexity, int)
        and isinstance(nesting_depth, int)
        and isinstance(risk, str)
        and risk in {"low", "medium", "high"}
        and isinstance(raw_hash, str)
        and isinstance(value.get("entry_guard_count", 0), int)
        and isinstance(value.get("entry_guard_terminal_profile", "none"), str)
        and isinstance(value.get("entry_guard_has_side_effect_before", False), bool)
        and isinstance(value.get("terminal_kind", "fallthrough"), str)
        and isinstance(value.get("try_finally_profile", "none"), str)
        and isinstance(value.get("side_effect_order_profile", "none"), str)
    )


def _is_block_dict(value: object) -> TypeGuard[BlockDict]:
    if not isinstance(value, dict):
        return False
    string_keys = ("block_hash", "filepath", "qualname")
    int_keys = ("start_line", "end_line", "size")
    return _has_typed_fields(value, string_keys=string_keys, int_keys=int_keys)


def _is_segment_dict(value: object) -> TypeGuard[SegmentDict]:
    if not isinstance(value, dict):
        return False
    string_keys = ("segment_hash", "segment_sig", "filepath", "qualname")
    int_keys = ("start_line", "end_line", "size")
    return _has_typed_fields(value, string_keys=string_keys, int_keys=int_keys)


def _is_module_typing_coverage_dict(
    value: object,
) -> TypeGuard[ModuleTypingCoverageDict]:
    if not isinstance(value, dict):
        return False
    string_keys = ("module", "filepath")
    int_keys = (
        "callable_count",
        "params_total",
        "params_annotated",
        "returns_total",
        "returns_annotated",
        "any_annotation_count",
    )
    return _has_typed_fields(value, string_keys=string_keys, int_keys=int_keys)


def _is_module_docstring_coverage_dict(
    value: object,
) -> TypeGuard[ModuleDocstringCoverageDict]:
    if not isinstance(value, dict):
        return False
    string_keys = ("module", "filepath")
    int_keys = ("public_symbol_total", "public_symbol_documented")
    return _has_typed_fields(value, string_keys=string_keys, int_keys=int_keys)


def _is_api_param_spec_dict(value: object) -> TypeGuard[ApiParamSpecDict]:
    if not isinstance(value, dict):
        return False
    return (
        isinstance(value.get("name"), str)
        and isinstance(value.get("kind"), str)
        and isinstance(value.get("has_default"), bool)
        and isinstance(value.get("annotation_hash", ""), str)
    )


def _is_public_symbol_dict(value: object) -> TypeGuard[PublicSymbolDict]:
    if not isinstance(value, dict):
        return False
    if not _has_typed_fields(
        value,
        string_keys=("qualname", "kind", "exported_via"),
        int_keys=("start_line", "end_line"),
    ):
        return False
    params = value.get("params", [])
    return (
        isinstance(value.get("returns_hash", ""), str)
        and isinstance(params, list)
        and all(_is_api_param_spec_dict(item) for item in params)
    )


def _is_module_api_surface_dict(value: object) -> TypeGuard[ModuleApiSurfaceDict]:
    if not isinstance(value, dict):
        return False
    all_declared = value.get("all_declared", [])
    symbols = value.get("symbols", [])
    return (
        isinstance(value.get("module"), str)
        and isinstance(value.get("filepath"), str)
        and _is_string_list(all_declared)
        and isinstance(symbols, list)
        and all(_is_public_symbol_dict(item) for item in symbols)
    )


def _is_class_metrics_dict(value: object) -> TypeGuard[ClassMetricsDict]:
    if not isinstance(value, dict):
        return False
    if not _has_typed_fields(
        value,
        string_keys=(
            "qualname",
            "filepath",
            "risk_coupling",
            "risk_cohesion",
        ),
        int_keys=(
            "start_line",
            "end_line",
            "cbo",
            "lcom4",
            "method_count",
            "instance_var_count",
        ),
    ):
        return False

    coupled_classes = value.get("coupled_classes")
    if coupled_classes is None:
        return True
    return _is_string_list(coupled_classes)


def _is_module_dep_dict(value: object) -> TypeGuard[ModuleDepDict]:
    if not isinstance(value, dict):
        return False
    if not _has_typed_fields(
        value,
        string_keys=("source", "target", "import_type"),
        int_keys=("line",),
    ):
        return False
    if value.get("import_type") not in {"import", "from_import"}:
        return False
    detail_keys = {
        "resolution",
        "mechanism",
        "inventory_expansion",
        "level",
        "requested_module",
        "requested_names",
        "candidate_targets",
    }
    # Payload_schema "6" pair: written together or not at all. A "5" row has
    # neither and stays valid; a row carrying only half the pair is corrupt.
    binding_pair_present = ("binding" in value) or ("is_lazy" in value)
    if binding_pair_present:
        if ("binding" not in value) or ("is_lazy" not in value):
            return False
        if value.get("binding") not in {
            "import_time",
            "deferred_function",
            "deferred_getattr",
            "type_checking",
            "lazy_syntax",
        } or not isinstance(value.get("is_lazy"), bool):
            return False
    present_detail_keys = detail_keys.intersection(value)
    if not present_detail_keys:
        return True
    if present_detail_keys != detail_keys:
        return False
    resolution = value.get("resolution")
    inventory_expansion = value.get("inventory_expansion")
    level = value.get("level")
    requested_module = value.get("requested_module")
    return (
        resolution
        in {
            "analyzed",
            "known_internal_not_analyzed",
            "external",
            "unresolved_relative",
            "unresolved_dynamic",
            "ambiguous",
        }
        and value.get("mechanism") in {"static", "dynamic"}
        and isinstance(inventory_expansion, bool)
        and isinstance(level, int)
        and not isinstance(level, bool)
        and (requested_module is None or isinstance(requested_module, str))
        and _is_string_list(value.get("requested_names"))
        and _is_string_list(value.get("candidate_targets"))
    )


def _is_dead_candidate_dict(value: object) -> TypeGuard[DeadCandidateDict]:
    if not isinstance(value, dict):
        return False
    if not _has_typed_fields(
        value,
        string_keys=("qualname", "local_name", "filepath", "kind"),
        int_keys=("start_line", "end_line"),
    ):
        return False
    # A present-but-wrongly-typed binding fact is a writer the reader does not
    # understand, not a symbol that happens to be unbound: absence is the only
    # honest way to say "this row predates the fact".
    if not isinstance(value.get("star_import_bound", False), bool):
        return False
    suppressed_rules = value.get("suppressed_rules")
    if suppressed_rules is None:
        return True
    return _is_string_list(suppressed_rules)


def _is_security_surface_dict(value: object) -> TypeGuard[SecuritySurfaceDict]:
    if not isinstance(value, dict):
        return False
    return _has_typed_fields(
        value,
        string_keys=(
            "category",
            "capability",
            "module",
            "filepath",
            "qualname",
            "location_scope",
            "classification_mode",
            "evidence_kind",
            "evidence_symbol",
        ),
        int_keys=("start_line", "end_line"),
    )


def _is_runtime_reachability_fact_dict(
    value: object,
) -> TypeGuard[RuntimeReachabilityFactDict]:
    if not isinstance(value, dict):
        return False
    return _has_typed_fields(
        value,
        string_keys=(
            "target_qualname",
            "filepath",
            "target_kind",
            "framework",
            "edge_kind",
            "confidence",
            "evidence",
            "evidence_symbol",
            "source_qualname",
        ),
        int_keys=("start_line", "end_line"),
    )


def _is_relationship_record_dict(
    value: object,
) -> TypeGuard[RelationshipRecordDict]:
    if not isinstance(value, dict):
        return False
    relation_kind = _as_relationship_kind(value.get("relation_kind"))
    resolution_status = _as_relationship_resolution_status(
        value.get("resolution_status")
    )
    origin_lane = _as_relationship_origin_lane(value.get("origin_lane"))
    target_qualname = value.get("target_qualname")
    expression = value.get("expression")
    resolution_rule = value.get("resolution_rule")
    line = value.get("line")
    if (
        relation_kind is None
        or resolution_status is None
        or origin_lane is None
        or not isinstance(value.get("source_qualname"), str)
        or not isinstance(value.get("path"), str)
        or not isinstance(line, int)
        or line < 1
        or (expression is not None and not isinstance(expression, str))
        or (resolution_rule is not None and not isinstance(resolution_rule, str))
    ):
        return False
    if resolution_status == "resolved":
        return isinstance(target_qualname, str)
    return target_qualname is None


def _is_function_relationship_facts_dict(
    value: object,
) -> TypeGuard[FunctionRelationshipFactsDict]:
    if not isinstance(value, dict):
        return False
    source_qualname = value.get("source_qualname")
    relationships = value.get("relationships")
    return (
        isinstance(source_qualname, str)
        and isinstance(relationships, list)
        and all(
            _is_relationship_record_dict(record)
            and record["source_qualname"] == source_qualname
            for record in relationships
        )
    )


def _is_string_list(value: object) -> TypeGuard[list[str]]:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _has_typed_fields(
    value: object,
    *,
    string_keys: Sequence[str],
    int_keys: Sequence[str],
) -> bool:
    if not isinstance(value, dict):
        return False
    return all(isinstance(value.get(key), str) for key in string_keys) and all(
        isinstance(value.get(key), int) for key in int_keys
    )


__all__ = [
    "_has_typed_fields",
    "_is_api_param_spec_dict",
    "_is_block_dict",
    "_is_class_metrics_dict",
    "_is_dead_candidate_dict",
    "_is_file_stat_dict",
    "_is_function_relationship_facts_dict",
    "_is_git_blob_identity",
    "_is_module_api_surface_dict",
    "_is_module_dep_dict",
    "_is_module_docstring_coverage_dict",
    "_is_module_typing_coverage_dict",
    "_is_public_symbol_dict",
    "_is_relationship_record_dict",
    "_is_runtime_reachability_fact_dict",
    "_is_security_surface_dict",
    "_is_segment_dict",
    "_is_source_content_digest",
    "_is_source_stats_dict",
    "_is_string_list",
    "_is_unit_dict",
]
