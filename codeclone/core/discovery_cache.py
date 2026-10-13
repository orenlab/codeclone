# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Final, Literal, TypeVar, get_args

from ..metrics._risk import RiskLevel
from ..models import (
    LIVE_ROOT_REASONS,
    ApiParameterKind,
    ApiParamSpec,
    ApiSymbolKind,
    ApiVisibility,
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
    NestedDefinition,
    NestedDefinitionDict,
    NestedDefinitionKind,
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
from ..utils.closed_vocabulary import narrow_to_vocabulary
from ..utils.coerce import as_mapping
from ._types import _as_sorted_str_tuple

_RowT = TypeVar("_RowT")
_FactT = TypeVar("_FactT")

#: Every vocabulary rehydration narrows, each taken from the alias that
#: declares it. A ``match`` ladder per vocabulary stood here until 2026-10-13,
#: and the framework ladder was one member short of the model: every warm run
#: threw the pydantic reachability fact away. Held by
#: ``tests/test_cache_vocabulary_closure.py``.
_API_PARAMETER_KINDS: Final[tuple[ApiParameterKind, ...]] = get_args(ApiParameterKind)
_API_SYMBOL_KINDS: Final[tuple[ApiSymbolKind, ...]] = get_args(ApiSymbolKind)
_API_VISIBILITIES: Final[tuple[ApiVisibility, ...]] = get_args(ApiVisibility)
_RISK_LEVELS: Final[tuple[RiskLevel, ...]] = get_args(RiskLevel)
_DEAD_CODE_CANDIDATE_KINDS: Final[tuple[DeadCodeCandidateKind, ...]] = get_args(
    DeadCodeCandidateKind
)
_NESTED_DEFINITION_KINDS: Final[tuple[NestedDefinitionKind, ...]] = get_args(
    NestedDefinitionKind
)
_SECURITY_SURFACE_CATEGORIES: Final[tuple[SecuritySurfaceCategory, ...]] = get_args(
    SecuritySurfaceCategory
)
_SECURITY_SURFACE_LOCATION_SCOPES: Final[tuple[SecuritySurfaceLocationScope, ...]] = (
    get_args(SecuritySurfaceLocationScope)
)
_SECURITY_SURFACE_CLASSIFICATION_MODES: Final[
    tuple[SecuritySurfaceClassificationMode, ...]
] = get_args(SecuritySurfaceClassificationMode)
_SECURITY_SURFACE_EVIDENCE_KINDS: Final[tuple[SecuritySurfaceEvidenceKind, ...]] = (
    get_args(SecuritySurfaceEvidenceKind)
)
_RUNTIME_REACHABILITY_FRAMEWORKS: Final[tuple[RuntimeReachabilityFramework, ...]] = (
    get_args(RuntimeReachabilityFramework)
)
_RUNTIME_REACHABILITY_EDGE_KINDS: Final[tuple[RuntimeReachabilityEdgeKind, ...]] = (
    get_args(RuntimeReachabilityEdgeKind)
)
_RUNTIME_REACHABILITY_CONFIDENCES: Final[tuple[RuntimeReachabilityConfidence, ...]] = (
    get_args(RuntimeReachabilityConfidence)
)
_RUNTIME_REACHABILITY_TARGET_KINDS: Final[tuple[RuntimeReachabilityTargetKind, ...]] = (
    get_args(RuntimeReachabilityTargetKind)
)


#: Each family rehydration rebuilds row by row, named in a refusal.
CachedFactFamily = Literal[
    "api_surface",
    "class_metrics",
    "dead_candidates",
    "docstring_coverage",
    "function_relationship_facts",
    "module_deps",
    "nested_definitions",
    "runtime_reachability",
    "security_surfaces",
    "typing_coverage",
]


class CachedRowRefused(Exception):
    """A cached row this reader cannot rebuild into the fact it stands for.

    Every family used to end ``if parsed is not None: append``, so a row the
    reader could not rebuild was skipped and its file was still served off the
    cache -- a published run in which the fact had never existed (measured
    2026-10-13: the pydantic reachability fact on fastapi). A row is rebuilt
    whole or the file's dependent lane is refused, typed and counted as
    ``malformed_payload``, and the file is walked again (ruling 2026-10-13,
    invariant 2). ``family`` names where the refusal happened.
    """

    def __init__(self, family: CachedFactFamily) -> None:
        super().__init__(f"a cached {family} row cannot be rebuilt")
        self.family: CachedFactFamily = family


def _rebuild_all(
    rows: Iterable[_RowT],
    rebuild: Callable[[_RowT], _FactT | None],
    family: CachedFactFamily,
) -> tuple[_FactT, ...]:
    """Every row rebuilt, in order, or a refusal of the whole family."""

    facts: list[_FactT] = []
    for row in rows:
        fact = rebuild(row)
        if fact is None:
            raise CachedRowRefused(family)
        facts.append(fact)
    return tuple(facts)


def _rebuild_optional(
    row: _RowT | None,
    rebuild: Callable[[_RowT], _FactT | None],
    family: CachedFactFamily,
) -> _FactT | None:
    """An absent section stays absent; a present one is rebuilt or refused."""

    if row is None:
        return None
    fact = rebuild(row)
    if fact is None:
        raise CachedRowRefused(family)
    return fact


def _api_param_kind(value: object) -> ApiParameterKind | None:
    return narrow_to_vocabulary(value, _API_PARAMETER_KINDS)


def _public_symbol_kind(value: object) -> ApiSymbolKind | None:
    return narrow_to_vocabulary(value, _API_SYMBOL_KINDS)


def _exported_via_kind(value: object) -> ApiVisibility | None:
    return narrow_to_vocabulary(value, _API_VISIBILITIES)


def _risk_level(value: object) -> RiskLevel | None:
    return narrow_to_vocabulary(value, _RISK_LEVELS)


def _dead_candidate_kind(value: object) -> DeadCodeCandidateKind | None:
    """Narrow one cached ``kind`` string back onto the declared vocabulary.

    The ``import`` member is admitted although the encoder cannot write it: it
    writes ``candidate.kind``, and no producer can construct that kind
    (measured 2026-08-30, pinned by ``tests/test_pipeline_process.py``). It is
    admitted while the vocabulary declares it, and it goes with it.
    """
    return narrow_to_vocabulary(value, _DEAD_CODE_CANDIDATE_KINDS)


def _nested_definition_kind(value: object) -> NestedDefinitionKind | None:
    """Narrow one cached nested ``kind`` onto the population's vocabulary.

    Definitions only, no ``import``: a row carrying anything else is a writer
    this reader does not understand, and it refuses the row.
    """
    return narrow_to_vocabulary(value, _NESTED_DEFINITION_KINDS)


def _cached_liveness_tags(
    reason: object, witness: object
) -> tuple[LiveRootReason | None, str | None] | None:
    """A row's live-root reason and escape witness, or ``None`` if unreadable.

    ``None`` and ``""`` are each field's legal "nothing here" (a row written
    before the fact, and the nested row's always-written empty value); any
    other value must be a member or a witness string, and a value that is
    neither refuses the row rather than reading as "no reason". Read as no
    reason, an unknown liveness reason turned a live root into a candidate.
    """

    decoded_reason = None if reason in (None, "") else _live_root_reason(reason)
    if reason not in (None, "") and decoded_reason is None:
        return None
    if witness is not None and not isinstance(witness, str):
        return None
    return decoded_reason, witness or None


def _nested_definition_tags(
    row: NestedDefinitionDict,
) -> tuple[NestedDefinitionKind, LiveRootReason | None, str | None] | None:
    kind = _nested_definition_kind(row.get("kind"))
    tags = _cached_liveness_tags(row.get("live_root_reason"), row.get("escape_witness"))
    if kind is None or tags is None:
        return None
    return kind, *tags


def _nested_definition_from_cache_row(
    row: NestedDefinitionDict,
) -> NestedDefinition | None:
    tags = _nested_definition_tags(row)
    if (
        tags is None
        or not row.get("qualname")
        or not row.get("local_name")
        or not row.get("filepath")
        or not row.get("lexical_parent")
        or not row.get("lexical_path")
    ):
        return None
    kind, live_root_reason, escape_witness = tags
    try:
        return NestedDefinition(
            qualname=row["qualname"],
            local_name=row["local_name"],
            kind=kind,
            lexical_parent=row["lexical_parent"],
            lexical_path=row["lexical_path"],
            filepath=row["filepath"],
            start_line=row["start_line"],
            end_line=row["end_line"],
            suppressed_rules=_as_sorted_str_tuple(row.get("suppressed_rules", [])),
            live_root_reason=live_root_reason,
            owner_base_names=_as_sorted_str_tuple(row.get("owner_base_names", [])),
            owner_has_unresolved_external_base=(
                row.get("owner_has_unresolved_external_base", False) is True
            ),
            decorator_evidenced=row.get("decorator_evidenced", False) is True,
            self_dispatched=row.get("self_dispatched", False) is True,
            escape_witness=escape_witness,
        )
    except ValueError:
        # The row's own construction law refused it (a path without a
        # function boundary, a qualname that does not spell its path): a
        # writer this reader does not understand, dropped rather than read.
        return None


def _security_surface_category(value: object) -> SecuritySurfaceCategory | None:
    return narrow_to_vocabulary(value, _SECURITY_SURFACE_CATEGORIES)


def _security_surface_location_scope(
    value: object,
) -> SecuritySurfaceLocationScope | None:
    return narrow_to_vocabulary(value, _SECURITY_SURFACE_LOCATION_SCOPES)


def _security_surface_classification_mode(
    value: object,
) -> SecuritySurfaceClassificationMode | None:
    return narrow_to_vocabulary(value, _SECURITY_SURFACE_CLASSIFICATION_MODES)


def _security_surface_evidence_kind(
    value: object,
) -> SecuritySurfaceEvidenceKind | None:
    return narrow_to_vocabulary(value, _SECURITY_SURFACE_EVIDENCE_KINDS)


def _runtime_reachability_framework(
    value: object,
) -> RuntimeReachabilityFramework | None:
    return narrow_to_vocabulary(value, _RUNTIME_REACHABILITY_FRAMEWORKS)


def _runtime_reachability_edge_kind(
    value: object,
) -> RuntimeReachabilityEdgeKind | None:
    return narrow_to_vocabulary(value, _RUNTIME_REACHABILITY_EDGE_KINDS)


def _runtime_reachability_confidence(
    value: object,
) -> RuntimeReachabilityConfidence | None:
    return narrow_to_vocabulary(value, _RUNTIME_REACHABILITY_CONFIDENCES)


def _runtime_reachability_target_kind(
    value: object,
) -> RuntimeReachabilityTargetKind | None:
    return narrow_to_vocabulary(value, _RUNTIME_REACHABILITY_TARGET_KINDS)


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
) -> tuple[str, ApiParameterKind, bool, str] | None:
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


def _dead_candidate_tags(
    dead_row: DeadCandidateDict,
) -> tuple[DeadCodeCandidateKind, LiveRootReason | None, str | None] | None:
    kind = _dead_candidate_kind(dead_row["kind"])
    tags = _cached_liveness_tags(
        dead_row.get("live_root_reason"), dead_row.get("escape_witness")
    )
    if kind is None or tags is None:
        return None
    return kind, *tags


def _dead_candidate_from_cache_row(dead_row: DeadCandidateDict) -> DeadCandidate | None:
    tags = _dead_candidate_tags(dead_row)
    if (
        not dead_row.get("qualname")
        or not dead_row.get("local_name")
        or not dead_row.get("filepath")
        or tags is None
    ):
        return None
    kind, live_root_reason, escape_witness = tags
    return DeadCandidate(
        qualname=dead_row["qualname"],
        local_name=dead_row["local_name"],
        filepath=dead_row["filepath"],
        start_line=dead_row["start_line"],
        end_line=dead_row["end_line"],
        kind=kind,
        suppressed_rules=_as_sorted_str_tuple(dead_row.get("suppressed_rules", [])),
        live_root_reason=live_root_reason,
        star_import_bound=dead_row.get("star_import_bound", False) is True,
        escape_witness=escape_witness,
    )


def _live_root_reason(value: object) -> LiveRootReason | None:
    """Narrow the cached reason back onto its closed set.

    Narrowing against the vocabulary is what makes this a narrower rather
    than a sixth authority over it. The arm-per-value ladder this replaced was
    type-checked in one direction only: inventing a member the vocabulary does
    not carry is a type error, but FAILING to mention one is not. A value
    outside the set answers ``None`` here; the row decoders refuse such a row
    (``_cached_liveness_tags``) rather than read it as "no reason".
    """

    return narrow_to_vocabulary(value, LIVE_ROOT_REASONS)


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


#: The metrics facts of one cached row, in the order every caller unpacks.
CachedMetrics = tuple[
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
]


def load_cached_metrics_extended(
    entry: CacheEntryV3,
    *,
    filepath: str,
    module_registry: ModuleRegistryHandle | None = None,
) -> CachedMetrics:
    """Rebuild every metrics fact of one cached row, or refuse the row.

    Raises :class:`CachedRowRefused` naming the first family with a row this
    reader cannot rebuild; nothing is returned short of the whole row.
    """

    dependent = entry.module_dependent
    test_file = is_test_filepath(filepath, module_registry=module_registry)
    return (
        _rebuild_all(
            dependent.class_metrics, _class_metric_from_cache_row, "class_metrics"
        ),
        _rebuild_all(dependent.module_deps, _module_dep_from_cache_row, "module_deps"),
        _rebuild_all(
            dependent.dead_candidates, _dead_candidate_from_cache_row, "dead_candidates"
        ),
        frozenset() if test_file else frozenset(dependent.referenced_names),
        frozenset() if test_file else frozenset(dependent.referenced_qualnames),
        _rebuild_optional(
            dependent.typing_coverage,
            _typing_coverage_from_cache_dict,
            "typing_coverage",
        ),
        _rebuild_optional(
            dependent.docstring_coverage,
            _docstring_coverage_from_cache_dict,
            "docstring_coverage",
        ),
        _rebuild_optional(
            dependent.api_surface, _api_surface_from_cache_dict, "api_surface"
        ),
        _rebuild_all(
            dependent.runtime_reachability,
            _runtime_reachability_from_cache_row,
            "runtime_reachability",
        ),
        _rebuild_all(
            dependent.security_surfaces,
            _security_surface_from_cache_row,
            "security_surfaces",
        ),
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


def load_cached_nested_definitions(
    entry: CacheEntryV3,
) -> tuple[NestedDefinition, ...]:
    """The function-local population of one cached row (liveness policy v5).

    Its own loader for the reason ``load_cached_declared_exports`` has one:
    the metrics tuple is unpacked by position, and a population is not a
    metric. Rehydrated for test files too, exactly as the module-level
    candidates are; the test-lane rule is applied by the evaluator, which
    reads the file's lane and never the row's.
    """

    return _rebuild_all(
        entry.module_dependent.nested_definitions,
        _nested_definition_from_cache_row,
        "nested_definitions",
    )
