# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from ..findings.structural.detectors import normalize_structural_finding_group
from ..models import (
    ApiParamSpecDict,
    BlockGroupItem,
    BlockUnit,
    ClassMetrics,
    ClassMetricsDict,
    DeadCandidate,
    DeadCandidateDict,
    FunctionGroupItem,
    FunctionRelationshipFacts,
    FunctionRelationshipFactsDict,
    ModuleApiSurface,
    ModuleApiSurfaceDict,
    ModuleDep,
    ModuleDepDict,
    ModuleDocstringCoverage,
    ModuleDocstringCoverageDict,
    ModuleTypingCoverage,
    ModuleTypingCoverageDict,
    PublicSymbolDict,
    RelationshipRecord,
    RelationshipRecordDict,
    RuntimeReachabilityFact,
    RuntimeReachabilityFactDict,
    SecuritySurface,
    SecuritySurfaceDict,
    SegmentGroupItem,
    SegmentUnit,
    SourceStatsDict,
    StructuralFindingGroup,
    StructuralFindingGroupDict,
    StructuralFindingOccurrence,
    StructuralFindingOccurrenceDict,
    Unit,
)

UnitDict = FunctionGroupItem
BlockDict = BlockGroupItem
SegmentDict = SegmentGroupItem


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


def _as_relationship_kind(value: object) -> Literal["call", "reference"] | None:
    if value == "call":
        return "call"
    if value == "reference":
        return "reference"
    return None


def _as_relationship_resolution_status(
    value: object,
) -> Literal["resolved", "unresolved"] | None:
    if value == "resolved":
        return "resolved"
    if value == "unresolved":
        return "unresolved"
    return None


def _as_relationship_origin_lane(
    value: object,
) -> Literal["production", "test"] | None:
    if value == "production":
        return "production"
    if value == "test":
        return "test"
    return None


def _as_security_surface_category(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    if value in {
        "archive_extraction",
        "crypto_transport",
        "database_boundary",
        "deserialization",
        "dynamic_execution",
        "dynamic_loading",
        "filesystem_mutation",
        "identity_token",
        "network_boundary",
        "process_boundary",
    }:
        return value
    return None


def _as_security_surface_location_scope(value: object) -> str | None:
    if isinstance(value, str) and value in {"module", "class", "callable"}:
        return value
    return None


def _as_security_surface_classification_mode(value: object) -> str | None:
    if isinstance(value, str) and value in {
        "exact_builtin",
        "exact_call",
        "exact_import",
    }:
        return value
    return None


def _as_security_surface_evidence_kind(value: object) -> str | None:
    if isinstance(value, str) and value in {"builtin", "call", "import"}:
        return value
    return None


def _as_runtime_reachability_framework(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    if value in {
        "aiogram",
        "aiohttp",
        "flask",
        "celery",
        "click",
        "dependency_injector",
        "django",
        "fastapi",
        "pydantic",
        "sqlalchemy",
        "starlette",
        "typer",
    }:
        return value
    return None


def _as_runtime_reachability_edge_kind(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    if value in {
        "declares_dependency",
        "provides",
        "registers_command",
        "registers_handler",
        "registers_task",
        "runtime_hook",
    }:
        return value
    return None


def _as_runtime_reachability_confidence(value: object) -> str | None:
    if isinstance(value, str) and value in {"high", "medium", "low"}:
        return value
    return None


def _as_runtime_reachability_target_kind(value: object) -> str | None:
    if isinstance(value, str) and value in {"function", "class", "method"}:
        return value
    return None


def _new_optional_metrics_payload() -> tuple[
    list[ClassMetricsDict],
    list[ModuleDepDict],
    list[DeadCandidateDict],
    list[str],
    list[str],
    list[str],
    list[str],
    list[RuntimeReachabilityFactDict],
    list[SecuritySurfaceDict],
    ModuleTypingCoverageDict | None,
    ModuleDocstringCoverageDict | None,
    ModuleApiSurfaceDict | None,
]:
    return [], [], [], [], [], [], [], [], [], None, None, None


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
        cfg_cyclomatic_complexity=unit.cfg_cyclomatic_complexity,
        nesting_depth=unit.nesting_depth,
        risk=unit.risk,
        raw_hash=unit.raw_hash,
        entry_guard_count=unit.entry_guard_count,
        entry_guard_terminal_profile=unit.entry_guard_terminal_profile,
        entry_guard_has_side_effect_before=unit.entry_guard_has_side_effect_before,
        terminal_kind=unit.terminal_kind,
        try_finally_profile=unit.try_finally_profile,
        side_effect_order_profile=unit.side_effect_order_profile,
        statement_sequence=unit.statement_sequence,
        renamed_fingerprint=unit.renamed_fingerprint,
        renamed_statement_sequence=unit.renamed_statement_sequence,
        unreachable_statements=unit.unreachable_statements,
    )


def _relationship_record_dict_from_model(
    record: RelationshipRecord,
    *,
    source_qualname: str,
    filepath: str,
) -> RelationshipRecordDict:
    if record.source_qualname != source_qualname:
        raise ValueError(
            "Relationship record source_qualname must match its facts container"
        )
    return RelationshipRecordDict(
        relation_kind=record.relation_kind,
        resolution_status=record.resolution_status,
        origin_lane=record.origin_lane,
        source_qualname=source_qualname,
        target_qualname=record.target_qualname,
        path=filepath,
        line=record.line,
        expression=record.expression,
        resolution_rule=record.resolution_rule,
    )


def _function_relationship_facts_dict_from_model(
    facts: FunctionRelationshipFacts,
    *,
    filepath: str,
) -> FunctionRelationshipFactsDict:
    return FunctionRelationshipFactsDict(
        source_qualname=facts.source_qualname,
        relationships=[
            _relationship_record_dict_from_model(
                record,
                source_qualname=facts.source_qualname,
                filepath=filepath,
            )
            for record in facts.relationships
        ],
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
        instantiation_candidates=sorted(set(metric.instantiation_candidates)),
        base_names=sorted(set(metric.base_names)),
        has_unresolved_external_base=metric.has_unresolved_external_base,
        decorator_evidenced_methods=sorted(set(metric.decorator_evidenced_methods)),
        self_dispatched_methods=sorted(set(metric.self_dispatched_methods)),
    )


def _module_dep_dict_from_model(dep: ModuleDep) -> ModuleDepDict:
    return ModuleDepDict(
        source=dep.source,
        target=dep.target,
        import_type=dep.import_type,
        line=dep.line,
        resolution=dep.resolution,
        inventory_expansion=dep.inventory_expansion,
        level=dep.level,
        requested_module=dep.requested_module,
        requested_names=list(dep.requested_names),
        candidate_targets=list(dep.candidate_targets),
        mechanism=dep.mechanism,
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
    if candidate.live_root_reason is not None:
        result["live_root_reason"] = candidate.live_root_reason
    return result


def _security_surface_dict_from_model(
    surface: SecuritySurface,
    filepath: str,
) -> SecuritySurfaceDict:
    return SecuritySurfaceDict(
        category=surface.category,
        capability=surface.capability,
        module=surface.module,
        filepath=filepath,
        qualname=surface.qualname,
        start_line=surface.start_line,
        end_line=surface.end_line,
        location_scope=surface.location_scope,
        classification_mode=surface.classification_mode,
        evidence_kind=surface.evidence_kind,
        evidence_symbol=surface.evidence_symbol,
    )


def _runtime_reachability_dict_from_model(
    fact: RuntimeReachabilityFact,
    filepath: str,
) -> RuntimeReachabilityFactDict:
    return RuntimeReachabilityFactDict(
        target_qualname=fact.target_qualname,
        filepath=filepath,
        start_line=fact.start_line,
        end_line=fact.end_line,
        target_kind=fact.target_kind,
        framework=fact.framework,
        edge_kind=fact.edge_kind,
        confidence=fact.confidence,
        evidence=fact.evidence,
        evidence_symbol=fact.evidence_symbol,
        source_qualname=fact.source_qualname,
    )


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
    "ClassMetricsDict",
    "DeadCandidateDict",
    "FunctionRelationshipFactsDict",
    "ModuleApiSurfaceDict",
    "ModuleDepDict",
    "ModuleDocstringCoverageDict",
    "ModuleTypingCoverageDict",
    "PublicSymbolDict",
    "RelationshipRecordDict",
    "RuntimeReachabilityFactDict",
    "SecuritySurfaceDict",
    "SegmentDict",
    "SourceStatsDict",
    "StructuralFindingGroupDict",
    "StructuralFindingOccurrenceDict",
    "UnitDict",
    "_api_surface_dict_from_model",
    "_as_relationship_kind",
    "_as_relationship_origin_lane",
    "_as_relationship_resolution_status",
    "_as_risk_literal",
    "_as_runtime_reachability_confidence",
    "_as_runtime_reachability_edge_kind",
    "_as_runtime_reachability_framework",
    "_as_runtime_reachability_target_kind",
    "_as_security_surface_category",
    "_as_security_surface_classification_mode",
    "_as_security_surface_evidence_kind",
    "_as_security_surface_location_scope",
    "_block_dict_from_model",
    "_class_metrics_dict_from_model",
    "_dead_candidate_dict_from_model",
    "_docstring_coverage_dict_from_model",
    "_function_relationship_facts_dict_from_model",
    "_module_dep_dict_from_model",
    "_new_optional_metrics_payload",
    "_normalize_cached_structural_group",
    "_normalize_cached_structural_groups",
    "_relationship_record_dict_from_model",
    "_runtime_reachability_dict_from_model",
    "_security_surface_dict_from_model",
    "_segment_dict_from_model",
    "_structural_group_dict_from_model",
    "_structural_occurrence_dict_from_model",
    "_typing_coverage_dict_from_model",
    "_unit_dict_from_model",
]
