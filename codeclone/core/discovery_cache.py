# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from ..models import (
    LIVE_ROOT_REASONS,
    ApiParamSpec,
    CacheEntryV3,
    ClassMetrics,
    ClassMetricsDict,
    DeadCandidate,
    DeadCandidateDict,
    DeadCodeCandidateKind,
    DependencyResolution,
    LiveRootReason,
    ModuleApiSurface,
    ModuleDep,
    ModuleDepDict,
    ModuleDocstringCoverage,
    ModuleRegistryHandle,
    ModuleTypingCoverage,
    PublicSymbol,
    RuntimeReachabilityConfidence,
    RuntimeReachabilityEdgeKind,
    RuntimeReachabilityFact,
    RuntimeReachabilityFactDict,
    RuntimeReachabilityFramework,
    RuntimeReachabilityTargetKind,
    SecuritySurface,
    SecuritySurfaceCategory,
    SecuritySurfaceClassificationMode,
    SecuritySurfaceDict,
    SecuritySurfaceEvidenceKind,
    SecuritySurfaceLocationScope,
    StructuralFindingGroup,
    StructuralFindingGroupDict,
    StructuralFindingOccurrence,
)
from ..paths import is_test_filepath
from ..utils.coerce import as_mapping
from ._types import _as_sorted_str_tuple

_ApiParamKind = Literal["pos_only", "pos_or_kw", "vararg", "kw_only", "kwarg"]
_PublicSymbolKind = Literal["function", "class", "method", "constant"]
_ExportedViaKind = Literal["all", "name"]
_RiskLevel = Literal["low", "medium", "high"]


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


def _dead_candidate_kind(value: object) -> DeadCodeCandidateKind | None:
    """Narrow one cached ``kind`` string back onto the declared vocabulary.

    The return type is the model's alias rather than a local restatement of
    the four values, so an arm the vocabulary does not carry is a type error
    here instead of a silent second authority over a closed vocabulary.

    The ``import`` arm accepts a value the encoder cannot write: it writes
    ``candidate.kind``, and no producer can construct that kind (measured
    2026-08-30, pinned by ``tests/test_pipeline_process.py``). It stays while
    the vocabulary declares it, and it goes with it.
    """
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


def _security_surface_category(value: object) -> SecuritySurfaceCategory | None:
    match value:
        case "archive_extraction":
            return "archive_extraction"
        case "crypto_transport":
            return "crypto_transport"
        case "database_boundary":
            return "database_boundary"
        case "deserialization":
            return "deserialization"
        case "dynamic_execution":
            return "dynamic_execution"
        case "dynamic_loading":
            return "dynamic_loading"
        case "filesystem_mutation":
            return "filesystem_mutation"
        case "identity_token":
            return "identity_token"
        case "network_boundary":
            return "network_boundary"
        case "process_boundary":
            return "process_boundary"
        case _:
            return None


def _security_surface_location_scope(
    value: object,
) -> SecuritySurfaceLocationScope | None:
    match value:
        case "module":
            return "module"
        case "class":
            return "class"
        case "callable":
            return "callable"
        case _:
            return None


def _security_surface_classification_mode(
    value: object,
) -> SecuritySurfaceClassificationMode | None:
    match value:
        case "exact_builtin":
            return "exact_builtin"
        case "exact_call":
            return "exact_call"
        case "exact_import":
            return "exact_import"
        case _:
            return None


def _security_surface_evidence_kind(
    value: object,
) -> SecuritySurfaceEvidenceKind | None:
    match value:
        case "builtin":
            return "builtin"
        case "call":
            return "call"
        case "import":
            return "import"
        case _:
            return None


def _runtime_reachability_framework(
    value: object,
) -> RuntimeReachabilityFramework | None:
    match value:
        case "aiogram":
            return "aiogram"
        case "aiohttp":
            return "aiohttp"
        case "celery":
            return "celery"
        case "click":
            return "click"
        case "dependency_injector":
            return "dependency_injector"
        case "django":
            return "django"
        case "fastapi":
            return "fastapi"
        case "flask":
            return "flask"
        case "sqlalchemy":
            return "sqlalchemy"
        case "starlette":
            return "starlette"
        case "typer":
            return "typer"
        case _:
            return None


def _runtime_reachability_edge_kind(
    value: object,
) -> RuntimeReachabilityEdgeKind | None:
    match value:
        case "declares_dependency":
            return "declares_dependency"
        case "provides":
            return "provides"
        case "registers_command":
            return "registers_command"
        case "registers_handler":
            return "registers_handler"
        case "registers_task":
            return "registers_task"
        case "runtime_hook":
            return "runtime_hook"
        case _:
            return None


def _runtime_reachability_confidence(
    value: object,
) -> RuntimeReachabilityConfidence | None:
    match value:
        case "high":
            return "high"
        case "medium":
            return "medium"
        case "low":
            return "low"
        case _:
            return None


def _runtime_reachability_target_kind(
    value: object,
) -> RuntimeReachabilityTargetKind | None:
    match value:
        case "function":
            return "function"
        case "class":
            return "class"
        case "method":
            return "method"
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


def _cache_entry_has_metrics(entry: CacheEntryV3) -> bool:
    return entry.module_dependent is not None


def _cache_entry_has_structural_findings(entry: CacheEntryV3) -> bool:
    return entry.module_dependent.structural_findings is not None


def _cache_entry_source_stats(entry: CacheEntryV3) -> tuple[int, int, int, int]:
    stats = entry.module_neutral.source_stats
    return stats["lines"], stats["functions"], stats["methods"], stats["classes"]


#: Why a row both lanes accepted is still not servable to *this* run.  The
#: lanes answer "is this row still true"; this answers "does it carry the
#: sections this run asked for", which is a different question and was the one
#: nothing recorded: a run that needs structural findings refuses every row
#: written by a run that did not collect them, and did so with no counter at
#: all (measured 2026-09-02 -- an MCP analysis reused none of the rows a CLI
#: run had just written, every lane agreeing).
#:
#: The metrics guard below is deliberately NOT a member: measured 2026-09-02,
#: ``CacheEntryV3.module_dependent`` is not optional and no producer writes
#: ``None`` into it, so that branch cannot be reached by any input and a
#: counter for it could never leave zero.  The guard stays -- it is not this
#: change's to remove -- but naming it in telemetry would be theatre.
CachedSourceStatsRefusal = Literal["structural_findings_absent"]


def cached_source_stats_refusal(
    entry: CacheEntryV3,
    *,
    collect_structural_findings: bool,
) -> CachedSourceStatsRefusal | None:
    """Name the section this row is missing, or ``None`` when it carries them."""

    if collect_structural_findings and not _cache_entry_has_structural_findings(entry):
        return "structural_findings_absent"
    return None


def usable_cached_source_stats(
    entry: CacheEntryV3,
    *,
    skip_metrics: bool,
    collect_structural_findings: bool,
) -> tuple[int, int, int, int] | None:
    """The row's source stats, or ``None`` when a required section is absent.

    The structural half delegates rather than restating the rule: the reason a
    row is refused and the fact that it is refused are the same rule, and two
    copies of one rule are two rules that will disagree.
    """

    if not skip_metrics and not _cache_entry_has_metrics(entry):
        return None
    if (
        cached_source_stats_refusal(
            entry,
            collect_structural_findings=collect_structural_findings,
        )
        is not None
    ):
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
    if not isinstance(all_declared_raw, list) or not isinstance(symbols_raw, list):
        return None
    all_declared: list[str] = []
    for item in all_declared_raw:
        if not isinstance(item, str):
            return None
        all_declared.append(item)
    symbols: list[PublicSymbol] = []
    for item in symbols_raw:
        parsed = _public_symbol_from_cache_dict(item)
        if parsed is None:
            return None
        symbols.append(parsed)
    return ModuleApiSurface(
        module=module,
        filepath=filepath,
        all_declared=tuple(sorted(set(all_declared))) or None,
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
        instantiation_candidates=_as_sorted_str_tuple(
            metric_row.get("instantiation_candidates", [])
        ),
        base_names=_as_sorted_str_tuple(metric_row.get("base_names", [])),
        has_unresolved_external_base=bool(
            metric_row.get("has_unresolved_external_base", False)
        ),
        decorator_evidenced_methods=_as_sorted_str_tuple(
            metric_row.get("decorator_evidenced_methods", [])
        ),
        self_dispatched_methods=_as_sorted_str_tuple(
            metric_row.get("self_dispatched_methods", [])
        ),
    )


def _module_dep_target_is_valid(
    *,
    resolution: DependencyResolution,
    target: str,
) -> bool:
    # Unresolved rows legitimately carry no target: a relative import that
    # escapes the package, and a dynamic load whose argument stayed opaque.
    return resolution in {"unresolved_relative", "unresolved_dynamic"} or bool(target)


def _module_dep_from_cache_row(dep_row: ModuleDepDict) -> ModuleDep | None:
    try:
        resolution = dep_row["resolution"]
        inventory_expansion = dep_row["inventory_expansion"]
        level = dep_row["level"]
        requested_module = dep_row["requested_module"]
        requested_names = dep_row["requested_names"]
        candidate_targets = dep_row["candidate_targets"]
        mechanism = dep_row["mechanism"]
    except KeyError:
        return None
    import_type = dep_row["import_type"]
    target = dep_row["target"]
    if not dep_row.get("source") or not _module_dep_target_is_valid(
        resolution=resolution,
        target=target,
    ):
        return None
    return ModuleDep(
        source=dep_row["source"],
        target=target,
        import_type=import_type,
        line=dep_row["line"],
        resolution=resolution,
        inventory_expansion=inventory_expansion,
        level=level,
        requested_module=requested_module,
        requested_names=tuple(requested_names),
        candidate_targets=tuple(candidate_targets),
        mechanism=mechanism,
        # "5"-era rows carry neither key; the model defaults mean eager,
        # which is exactly what those rows asserted when they were written.
        binding=dep_row.get("binding", "import_time"),
        is_lazy=dep_row.get("is_lazy", False),
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
        live_root_reason=_live_root_reason(dead_row.get("live_root_reason")),
        star_import_bound=dead_row.get("star_import_bound", False) is True,
    )


def _live_root_reason(value: object) -> LiveRootReason | None:
    """Narrow the cached reason back onto its closed set.

    Iterating the vocabulary is what makes this a narrower rather than a sixth
    authority over it. The arm-per-value ladder this replaces was type-checked
    in one direction only: inventing a member the vocabulary does not carry is
    a type error, but FAILING to mention one is not, so a vocabulary that grew
    would have been silently narrowed here -- every unlisted reason decoding as
    "no reason at all" -- with nothing red to say so. ``reason`` is already a
    :data:`~codeclone.contracts.LiveRootReason`, so the return needs no cast.
    """

    for reason in LIVE_ROOT_REASONS:
        if value == reason:
            return reason
    return None


def _security_surface_from_cache_row(
    surface_row: SecuritySurfaceDict,
) -> SecuritySurface | None:
    category = _security_surface_category(surface_row.get("category"))
    location_scope = _security_surface_location_scope(surface_row.get("location_scope"))
    classification_mode = _security_surface_classification_mode(
        surface_row.get("classification_mode")
    )
    evidence_kind = _security_surface_evidence_kind(surface_row.get("evidence_kind"))
    if (
        category is None
        or location_scope is None
        or classification_mode is None
        or evidence_kind is None
    ):
        return None
    return SecuritySurface(
        category=category,
        capability=surface_row["capability"],
        module=surface_row["module"],
        filepath=surface_row["filepath"],
        qualname=surface_row["qualname"],
        start_line=surface_row["start_line"],
        end_line=surface_row["end_line"],
        location_scope=location_scope,
        classification_mode=classification_mode,
        evidence_kind=evidence_kind,
        evidence_symbol=surface_row["evidence_symbol"],
    )


def _runtime_reachability_from_cache_row(
    fact_row: RuntimeReachabilityFactDict,
) -> RuntimeReachabilityFact | None:
    target_kind = _runtime_reachability_target_kind(fact_row.get("target_kind"))
    framework = _runtime_reachability_framework(fact_row.get("framework"))
    edge_kind = _runtime_reachability_edge_kind(fact_row.get("edge_kind"))
    confidence = _runtime_reachability_confidence(fact_row.get("confidence"))
    if (
        target_kind is None
        or framework is None
        or edge_kind is None
        or confidence is None
    ):
        return None
    return RuntimeReachabilityFact(
        target_qualname=fact_row["target_qualname"],
        filepath=fact_row["filepath"],
        start_line=fact_row["start_line"],
        end_line=fact_row["end_line"],
        target_kind=target_kind,
        framework=framework,
        edge_kind=edge_kind,
        confidence=confidence,
        evidence=fact_row["evidence"],
        evidence_symbol=fact_row["evidence_symbol"],
        source_qualname=fact_row["source_qualname"],
    )


def load_cached_metrics_extended(
    entry: CacheEntryV3,
    *,
    filepath: str,
    module_registry: ModuleRegistryHandle | None = None,
) -> tuple[
    tuple[ClassMetrics, ...],
    tuple[ModuleDep, ...],
    tuple[DeadCandidate, ...],
    frozenset[str],
    frozenset[str],
    ModuleTypingCoverage | None,
    ModuleDocstringCoverage | None,
    ModuleApiSurface | None,
    tuple[RuntimeReachabilityFact, ...],
    tuple[SecuritySurface, ...],
]:
    dependent = entry.module_dependent
    class_metrics_rows = dependent.class_metrics
    class_metrics_items: list[ClassMetrics] = []
    for metric_row in class_metrics_rows:
        parsed_metric = _class_metric_from_cache_row(metric_row)
        if parsed_metric is not None:
            class_metrics_items.append(parsed_metric)
    class_metrics = tuple(class_metrics_items)
    module_dep_rows = dependent.module_deps
    module_dep_items: list[ModuleDep] = []
    for dep_row in module_dep_rows:
        parsed_dep = _module_dep_from_cache_row(dep_row)
        if parsed_dep is not None:
            module_dep_items.append(parsed_dep)
    module_deps = tuple(module_dep_items)
    dead_rows = dependent.dead_candidates
    dead_candidate_items: list[DeadCandidate] = []
    for dead_row in dead_rows:
        parsed_dead = _dead_candidate_from_cache_row(dead_row)
        if parsed_dead is not None:
            dead_candidate_items.append(parsed_dead)
    dead_candidates = tuple(dead_candidate_items)
    referenced_names = (
        frozenset()
        if is_test_filepath(filepath, module_registry=module_registry)
        else frozenset(dependent.referenced_names)
    )
    referenced_qualnames = (
        frozenset()
        if is_test_filepath(filepath, module_registry=module_registry)
        else frozenset(dependent.referenced_qualnames)
    )
    security_surface_rows = dependent.security_surfaces
    security_surface_items: list[SecuritySurface] = []
    for surface_row in security_surface_rows:
        parsed_surface = _security_surface_from_cache_row(surface_row)
        if parsed_surface is not None:
            security_surface_items.append(parsed_surface)
    reachability_rows = dependent.runtime_reachability
    reachability_items: list[RuntimeReachabilityFact] = []
    for fact_row in reachability_rows:
        parsed_fact = _runtime_reachability_from_cache_row(fact_row)
        if parsed_fact is not None:
            reachability_items.append(parsed_fact)
    return (
        class_metrics,
        module_deps,
        dead_candidates,
        referenced_names,
        referenced_qualnames,
        _typing_coverage_from_cache_dict(dependent.typing_coverage),
        _docstring_coverage_from_cache_dict(dependent.docstring_coverage),
        _api_surface_from_cache_dict(dependent.api_surface),
        tuple(reachability_items),
        tuple(security_surface_items),
    )


def load_cached_declared_exports(entry: CacheEntryV3) -> frozenset[str]:
    """The declaration fact of one cached row (liveness policy v4).

    Its own loader rather than an eleventh member of the metrics tuple
    above: that tuple is unpacked by position in several places, and a
    declaration is not a metric. Rehydrated for test files too - exposure
    reads every module's ``__all__``; the reference lanes are what the
    test-file rule empties.
    """

    return frozenset(entry.module_dependent.declared_exports)
