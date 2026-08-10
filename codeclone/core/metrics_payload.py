# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ..analysis.suppressions import (
    DEAD_CODE_RULE_ID,
    INLINE_CODECLONE_SUPPRESSION_SOURCE,
)
from ..domain.findings import CATEGORY_COHESION, CATEGORY_COMPLEXITY, CATEGORY_COUPLING
from ..domain.quality import CONFIDENCE_HIGH, RISK_LOW
from ..metrics.overloaded_modules import build_overloaded_modules_payload
from ..models import (
    ClassMetrics,
    CoverageJoinResult,
    DeadItem,
    DepGraph,
    GroupItemLike,
    MetricsDiff,
    ModuleDep,
    ModuleRegistryHandle,
    ProjectMetrics,
    ResolvedSourceIdentity,
    RuntimeReachabilityFact,
    SecuritySurface,
    SemanticAuthorityResult,
    UnreachableStatementFinding,
    UnresolvedOverrideItem,
)
from ..utils.coerce import as_int, as_mapping, as_sequence, as_str
from .api_surface_payload import (
    _api_surface_rows,
    _api_surface_summary,
    _breaking_api_surface_rows,
)
from .coverage_payload import (
    _coverage_adoption_rows,
    _coverage_join_rows,
    _coverage_join_summary,
    _permille,
)
from .security_surfaces_payload import build_security_surfaces_payload


def _semantic_authority_payload(
    result: SemanticAuthorityResult,
) -> dict[str, object]:
    status_counts = {
        status: sum(sink.authority_status == status for sink in result.sinks)
        for status in (
            "authoritative",
            "adapter",
            "shadow",
            "mixed",
            "unavailable",
        )
    }
    sink_items: list[dict[str, object]] = [
        {
            "item_kind": "sink",
            "sink_identity": sink.sink_identity,
            "authority_status": sink.authority_status,
            "producer_root_ids": list(sink.producer_root_ids),
            "effect_signature": sink.effect_signature,
            "resolution_state": sink.resolution_state,
            "algorithm_revision": result.algorithm_revision,
        }
        for sink in result.sinks
    ]
    candidate_items: list[dict[str, object]] = [
        {
            "item_kind": "candidate",
            "candidate_id": candidate.candidate_id,
            "level": candidate.level,
            "score": candidate.score,
            "producers": list(candidate.producers),
            "shared_fact": candidate.shared_fact,
            "independence": candidate.independence,
            "semantic_divergence": candidate.semantic_divergence,
            "sink_statuses": list(candidate.sink_statuses),
            "algorithm_revision": result.algorithm_revision,
        }
        for candidate in result.candidates
    ]
    governed_sink_items: list[dict[str, object]] = [
        {
            "item_kind": "governed_sink",
            "contract_id": sink.contract_id,
            "sink_identity": sink.sink_identity,
            "authority_status": sink.authority_status,
            "producer_root_ids": list(sink.producer_root_ids),
            "effect_signature": sink.effect_signature,
            "resolution_state": sink.resolution_state,
            "unresolved_reasons": list(sink.unresolved_reasons),
            "algorithm_revision": result.algorithm_revision,
        }
        for sink in result.governed_sinks
    ]
    violation_items: list[dict[str, object]] = [
        {
            "item_kind": "violation",
            "violation_id": violation.violation_id,
            "contract_id": violation.contract_id,
            "kind": violation.kind,
            "sink_identity": violation.sink_identity,
            "canonical_owner": violation.canonical_owner,
            "authority_status": violation.authority_status,
            "producer_root_ids": list(violation.producer_root_ids),
            "effect_signature": violation.effect_signature,
            "resolution_state": violation.resolution_state,
            "producers": list(violation.producers),
            "suppressed": violation.suppressed,
            "locations": [
                {
                    "relative_path": location.relative_path,
                    "start_line": location.start_line,
                    "end_line": location.end_line,
                    "qualname": location.qualname,
                }
                for location in violation.locations
            ],
            "algorithm_revision": result.algorithm_revision,
        }
        for violation in result.violations
    ]
    registry_entries = (
        []
        if result.registry is None
        else [
            {
                "contract_id": entry.contract_id,
                "canonical_owner": entry.canonical_owner,
                "allowed_adapters": list(entry.allowed_adapters),
                "forbidden_raw_inputs": list(entry.forbidden_raw_inputs),
                "required_provenance": list(entry.required_provenance),
            }
            for entry in result.registry.entries
        ]
    )
    active_violations = sum(not item.suppressed for item in result.violations)
    return {
        "summary": {
            "enabled": True,
            "report_only": not registry_entries,
            "enforcement_enabled": bool(registry_entries),
            "algorithm_revision": result.algorithm_revision,
            "registry_version": (
                "" if result.registry is None else result.registry.version
            ),
            "registry_contracts": len(registry_entries),
            "contracts": len(result.contract_ir.contracts),
            "sinks": len(result.sinks),
            "candidates": len(result.candidates),
            "governed_sinks": len(result.governed_sinks),
            "violations": len(result.violations),
            "active_violations": active_violations,
            "suppressed_violations": len(result.violations) - active_violations,
            "scc_count": len(result.contract_ir.sccs),
            "fixpoint_iterations": result.contract_ir.fixpoint_iterations,
            "sinks_by_status": status_counts,
        },
        "items": sorted(
            [
                *sink_items,
                *candidate_items,
                *governed_sink_items,
                *violation_items,
            ],
            key=lambda item: (
                str(item["item_kind"]),
                str(item.get("sink_identity", "")),
                str(item.get("candidate_id", "")),
            ),
        ),
        "registry": registry_entries,
        "contract_ir": [
            {
                "function": contract.function,
                "wire": contract.wire,
                "effect_signature": contract.effect_signature,
                "producer_root_ids": list(contract.provenance_roots),
            }
            for contract in result.contract_ir.contracts
        ],
    }


def _dependency_source_identity(
    source: str,
    registry: ModuleRegistryHandle,
) -> ResolvedSourceIdentity:
    entry = registry.entries_by_module.get(source)
    if entry is None:
        entry = registry.entries_by_path.get(source)
    if entry is None:
        raise ValueError(f"dependency source is absent from module registry: {source}")
    return entry.identity


def _source_identity_payload(identity: ResolvedSourceIdentity) -> dict[str, object]:
    module = identity.python_module
    return {
        "file": {"path": identity.file.path},
        "python_module": (
            {
                "module": module.module,
                "package": module.package,
                "is_package": module.is_package,
                "mount_path": module.mount_path,
                "origin": module.origin,
                "node_kind": module.node_kind,
            }
            if module is not None
            else None
        ),
    }


def _dependency_observation_rows(
    deps: Sequence[ModuleDep],
    registry: ModuleRegistryHandle,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = [
        {
            "source": _source_identity_payload(
                _dependency_source_identity(dep.source, registry)
            ),
            "syntax_kind": dep.import_type,
            "level": dep.level,
            "requested_module": dep.requested_module,
            "requested_names": list(dep.requested_names),
            "resolution": dep.resolution,
            "candidate_targets": list(dep.candidate_targets),
            "resolved_target": dep.target or None,
            # G4's observation projection plus the classified binding time.
            "binding": dep.binding,
            "is_lazy": dep.is_lazy,
        }
        for dep in deps
    ]
    return sorted(rows, key=_dependency_observation_sort_key)


def _dependency_observation_sort_key(
    row: Mapping[str, object],
) -> tuple[str, ...]:
    return (
        as_str(as_mapping(as_mapping(row["source"]).get("file")).get("path")),
        as_str(row["syntax_kind"]),
        f"{as_int(row['level']):020d}",
        as_str(row["requested_module"]),
        "\0".join(as_str(name) for name in as_sequence(row["requested_names"])),
        as_str(row["resolution"]),
        "\0".join(as_str(name) for name in as_sequence(row["candidate_targets"])),
        as_str(row["resolved_target"]),
    )


def _enrich_metrics_report_payload(
    *,
    metrics_payload: Mapping[str, object],
    metrics_diff: MetricsDiff | None,
    coverage_adoption_diff_available: bool,
    api_surface_diff_available: bool,
) -> dict[str, object]:
    enriched = {
        key: (dict(value) if isinstance(value, Mapping) else value)
        for key, value in metrics_payload.items()
    }
    coverage_adoption = dict(as_mapping(enriched.get("coverage_adoption")))
    coverage_summary = dict(as_mapping(coverage_adoption.get("summary")))
    if coverage_summary:
        coverage_summary["baseline_diff_available"] = coverage_adoption_diff_available
        coverage_summary["param_delta"] = (
            int(metrics_diff.typing_param_permille_delta)
            if metrics_diff is not None and coverage_adoption_diff_available
            else 0
        )
        coverage_summary["return_delta"] = (
            int(metrics_diff.typing_return_permille_delta)
            if metrics_diff is not None and coverage_adoption_diff_available
            else 0
        )
        coverage_summary["docstring_delta"] = (
            int(metrics_diff.docstring_permille_delta)
            if metrics_diff is not None and coverage_adoption_diff_available
            else 0
        )
        coverage_adoption["summary"] = coverage_summary
        enriched["coverage_adoption"] = coverage_adoption

    api_surface = dict(as_mapping(enriched.get("api_surface")))
    api_summary = dict(as_mapping(api_surface.get("summary")))
    api_items = list(as_sequence(api_surface.get("items")))
    if api_summary:
        api_summary["baseline_diff_available"] = api_surface_diff_available
        api_summary["added"] = (
            len(metrics_diff.new_api_symbols)
            if metrics_diff is not None and api_surface_diff_available
            else 0
        )
        api_summary["breaking"] = (
            len(metrics_diff.new_api_breaking_changes)
            if metrics_diff is not None and api_surface_diff_available
            else 0
        )
        api_surface["summary"] = api_summary
    if (
        metrics_diff is not None
        and api_surface_diff_available
        and metrics_diff.new_api_breaking_changes
    ):
        api_items.extend(
            _breaking_api_surface_rows(metrics_diff.new_api_breaking_changes)
        )
    api_surface["items"] = api_items
    if api_surface:
        enriched["api_surface"] = api_surface
    return enriched


def build_metrics_report_payload(
    *,
    scan_root: str = "",
    project_metrics: ProjectMetrics,
    dep_graph: DepGraph | None = None,
    coverage_join: CoverageJoinResult | None = None,
    units: Sequence[GroupItemLike],
    class_metrics: Sequence[ClassMetrics],
    module_deps: Sequence[ModuleDep] = (),
    module_registry: ModuleRegistryHandle,
    runtime_reachability: Sequence[RuntimeReachabilityFact] = (),
    security_surfaces: Sequence[SecuritySurface] = (),
    source_stats_by_file: Sequence[tuple[str, int, int, int, int]] = (),
    suppressed_dead_code: Sequence[DeadItem] = (),
) -> dict[str, object]:
    sorted_units = sorted(
        units,
        key=lambda item: (
            as_int(item.get("cyclomatic_complexity"), 0),
            as_int(item.get("nesting_depth"), 0),
            as_str(item.get("qualname")),
        ),
        reverse=True,
    )
    complexity_rows = [
        {
            "qualname": as_str(item.get("qualname")),
            "filepath": as_str(item.get("filepath")),
            "start_line": as_int(item.get("start_line"), 0),
            "end_line": as_int(item.get("end_line"), 0),
            "cyclomatic_complexity": as_int(item.get("cyclomatic_complexity"), 1),
            "nesting_depth": as_int(item.get("nesting_depth"), 0),
            "risk": as_str(item.get("risk"), RISK_LOW),
        }
        for item in sorted_units
    ]
    classes_sorted = sorted(
        class_metrics,
        key=lambda item: (item.cbo, item.lcom4, item.qualname),
        reverse=True,
    )
    coupling_rows = [
        {
            "qualname": metric.qualname,
            "filepath": metric.filepath,
            "start_line": metric.start_line,
            "end_line": metric.end_line,
            "cbo": metric.cbo,
            "risk": metric.risk_coupling,
            "coupled_classes": list(metric.coupled_classes),
        }
        for metric in classes_sorted
    ]
    cohesion_rows = [
        {
            "qualname": metric.qualname,
            "filepath": metric.filepath,
            "start_line": metric.start_line,
            "end_line": metric.end_line,
            "lcom4": metric.lcom4,
            "risk": metric.risk_cohesion,
            "method_count": metric.method_count,
            "instance_var_count": metric.instance_var_count,
        }
        for metric in classes_sorted
    ]
    active_dead_items = tuple(project_metrics.dead_code)
    suppressed_dead_items = tuple(suppressed_dead_code)
    coverage_adoption_rows = _coverage_adoption_rows(project_metrics)
    api_surface_summary = _api_surface_summary(project_metrics.api_surface)
    api_surface_items = _api_surface_rows(project_metrics.api_surface)
    coverage_join_summary = _coverage_join_summary(coverage_join)
    coverage_join_items = _coverage_join_rows(coverage_join)
    runtime_reachability_items = _runtime_reachability_rows(runtime_reachability)
    runtime_reachability_summary = _runtime_reachability_summary(
        runtime_reachability_items
    )

    def _serialize_dead_item(
        item: DeadItem,
        *,
        suppressed: bool = False,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "qualname": item.qualname,
            "filepath": item.filepath,
            "start_line": item.start_line,
            "end_line": item.end_line,
            "kind": item.kind,
            "confidence": item.confidence,
            "reason": item.reason,
            "test_reference_sources": list(item.test_reference_sources),
        }
        if suppressed:
            payload["suppressed_by"] = [
                {
                    "rule": DEAD_CODE_RULE_ID,
                    "source": INLINE_CODECLONE_SUPPRESSION_SOURCE,
                }
            ]
        return payload

    def _serialize_unresolved_override(
        item: UnresolvedOverrideItem,
    ) -> dict[str, object]:
        return {
            "qualname": item.qualname,
            "filepath": item.filepath,
            "start_line": item.start_line,
            "end_line": item.end_line,
            "kind": item.kind,
            "class_qualname": item.class_qualname,
            "base_names": list(item.base_names),
            "reason": item.reason,
        }

    def _serialize_unreachable_statement(
        item: UnreachableStatementFinding,
    ) -> dict[str, object]:
        return {
            "qualname": item.qualname,
            "filepath": item.filepath,
            "start_line": item.start_line,
            "end_line": item.end_line,
            "reason": item.reason,
            "statement_count": item.statement_count,
            # Fixed, never computed: the finding is a graph proof over the
            # function's own control flow, so there is no weaker case to grade.
            "confidence": CONFIDENCE_HIGH,
        }

    unresolved_override_items = tuple(project_metrics.unresolved_overrides)
    unreachable_statement_items = tuple(project_metrics.unreachable_statements)

    payload = {
        CATEGORY_COMPLEXITY: {
            "functions": complexity_rows,
            "summary": {
                "total": len(complexity_rows),
                "average": round(project_metrics.complexity_avg, 2),
                "max": project_metrics.complexity_max,
                "high_risk": len(project_metrics.high_risk_functions),
            },
        },
        CATEGORY_COUPLING: {
            "classes": coupling_rows,
            "summary": {
                "total": len(coupling_rows),
                "average": round(project_metrics.coupling_avg, 2),
                "max": project_metrics.coupling_max,
                "high_risk": len(project_metrics.high_risk_classes),
            },
        },
        CATEGORY_COHESION: {
            "classes": cohesion_rows,
            "summary": {
                "total": len(cohesion_rows),
                "average": round(project_metrics.cohesion_avg, 2),
                "max": project_metrics.cohesion_max,
                "low_cohesion": len(project_metrics.low_cohesion_classes),
            },
        },
        "dependencies": {
            "observations": _dependency_observation_rows(
                module_deps,
                module_registry,
            ),
            "modules": project_metrics.dependency_modules,
            "edges": project_metrics.dependency_edges,
            "max_depth": project_metrics.dependency_max_depth,
            "avg_depth": (
                round(dep_graph.avg_depth, 2) if dep_graph is not None else 0.0
            ),
            "p95_depth": dep_graph.p95_depth if dep_graph is not None else 0,
            "cycles": [list(cycle) for cycle in project_metrics.dependency_cycles],
            # Aligned with "cycles": the binding-law classification and the
            # registry-resolved member paths (null = honestly unresolved).
            "cycle_details": [
                {
                    "modules": list(detail.modules),
                    "kind": detail.kind,
                    "member_paths": list(detail.member_paths),
                }
                for detail in project_metrics.dependency_cycle_details
            ],
            "longest_chains": [
                list(chain) for chain in project_metrics.dependency_longest_chains
            ],
            "edge_list": [
                {
                    "source": edge.source,
                    "target": edge.target,
                    "import_type": edge.import_type,
                    "line": edge.line,
                    "binding": edge.binding,
                    "is_lazy": edge.is_lazy,
                }
                for edge in project_metrics.dependency_edge_list
            ],
        },
        "dead_code": {
            "items": [_serialize_dead_item(item) for item in active_dead_items],
            "suppressed_items": [
                _serialize_dead_item(item, suppressed=True)
                for item in suppressed_dead_items
            ],
            "unresolved_overrides": [
                _serialize_unresolved_override(item)
                for item in unresolved_override_items
            ],
            # Same family, deliberately its own list: a dead symbol and an
            # unreachable statement inside a live symbol are different defects
            # and are never added together (39Y Y9). No matching "summary"
            # counter — this list is the authority and a count beside it would
            # only be len() restated, unlike the abstention tally, which counts
            # rows that appear in no list at all.
            "unreachable_statements": [
                _serialize_unreachable_statement(item)
                for item in unreachable_statement_items
            ],
            "live_root_reasons": [
                {"qualname": qualname, "reason": reason}
                for qualname, reason in project_metrics.live_root_reasons
            ],
            "summary": {
                "total": len(active_dead_items),
                "critical": sum(
                    1
                    for item in active_dead_items
                    if item.confidence == CONFIDENCE_HIGH
                ),
                "high_confidence": sum(
                    1
                    for item in active_dead_items
                    if item.confidence == CONFIDENCE_HIGH
                ),
                "suppressed": len(suppressed_dead_items),
                # Counted separately from every dead-code number above: an
                # abstention is neither dead nor live, so folding it into
                # "total" would be the claim the tri-state exists to refuse.
                "unresolved_external_override": len(unresolved_override_items),
                "live_roots": len(project_metrics.live_root_reasons),
            },
            "runtime_reachability": {
                "summary": runtime_reachability_summary,
                "items": runtime_reachability_items,
            },
        },
        "health": {
            "score": project_metrics.health.total,
            "grade": project_metrics.health.grade,
            "dimensions": dict(project_metrics.health.dimensions),
        },
        "coverage_adoption": {
            "summary": {
                "modules": len(coverage_adoption_rows),
                "params_total": project_metrics.typing_param_total,
                "params_annotated": project_metrics.typing_param_annotated,
                "param_permille": _permille(
                    project_metrics.typing_param_annotated,
                    project_metrics.typing_param_total,
                ),
                "returns_total": project_metrics.typing_return_total,
                "returns_annotated": project_metrics.typing_return_annotated,
                "return_permille": _permille(
                    project_metrics.typing_return_annotated,
                    project_metrics.typing_return_total,
                ),
                "public_symbol_total": project_metrics.docstring_public_total,
                "public_symbol_documented": project_metrics.docstring_public_documented,
                "docstring_permille": _permille(
                    project_metrics.docstring_public_documented,
                    project_metrics.docstring_public_total,
                ),
                "typing_any_count": project_metrics.typing_any_count,
            },
            "items": coverage_adoption_rows,
        },
        "api_surface": {
            "summary": dict(api_surface_summary),
            "items": api_surface_items,
        },
        "overloaded_modules": build_overloaded_modules_payload(
            scan_root=scan_root,
            registry=module_registry,
            source_stats_by_file=source_stats_by_file,
            units=units,
            class_metrics=class_metrics,
            module_deps=module_deps,
        ),
        "security_surfaces": build_security_surfaces_payload(
            scan_root=scan_root,
            surfaces=security_surfaces,
        ),
    }
    if project_metrics.semantic_authority is not None:
        payload["semantic_authority"] = _semantic_authority_payload(
            project_metrics.semantic_authority
        )
    if coverage_join is not None:
        payload["coverage_join"] = {
            "summary": dict(coverage_join_summary),
            "items": coverage_join_items,
        }
    return payload


def _runtime_reachability_rows(
    runtime_reachability: Sequence[RuntimeReachabilityFact],
) -> list[dict[str, object]]:
    return [
        {
            "target_qualname": fact.target_qualname,
            "filepath": fact.filepath,
            "start_line": fact.start_line,
            "end_line": fact.end_line,
            "target_kind": fact.target_kind,
            "framework": fact.framework,
            "edge_kind": fact.edge_kind,
            "confidence": fact.confidence,
            "evidence": fact.evidence,
            "evidence_symbol": fact.evidence_symbol,
            "source_qualname": fact.source_qualname,
        }
        for fact in sorted(
            runtime_reachability,
            key=lambda item: (
                item.filepath,
                item.start_line,
                item.end_line,
                item.target_qualname,
                item.framework,
                item.edge_kind,
                item.evidence_symbol,
            ),
        )
    ]


def _runtime_reachability_summary(
    rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    by_framework: dict[str, int] = {}
    by_edge_kind: dict[str, int] = {}
    by_confidence: dict[str, int] = {}
    for row in rows:
        framework = as_str(row.get("framework"))
        edge_kind = as_str(row.get("edge_kind"))
        confidence = as_str(row.get("confidence"))
        by_framework[framework] = by_framework.get(framework, 0) + 1
        by_edge_kind[edge_kind] = by_edge_kind.get(edge_kind, 0) + 1
        by_confidence[confidence] = by_confidence.get(confidence, 0) + 1
    return {
        "total": len(rows),
        "by_framework": dict(sorted(by_framework.items())),
        "by_edge_kind": dict(sorted(by_edge_kind.items())),
        "by_confidence": dict(sorted(by_confidence.items())),
    }
