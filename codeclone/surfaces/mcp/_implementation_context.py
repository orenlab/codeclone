# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Deterministic implementation-context projection over one MCP run."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import orjson

from ...models import RelationshipRecord
from ...paths import classify_source_kind
from ...utils.coerce import as_mapping as _as_mapping
from ...utils.coerce import as_sequence as _as_sequence
from ._blast_radius import _path_to_module
from ._session_shared import MCPRunRecord, MCPUnitLocation
from ._workspace_drift import WorkspaceDrift, compute_drift
from .messages.params import Facet

CONTEXT_CONTRACT_VERSION: Final = "1"
CALL_RESOLUTION_VERSION: Final = "1"
MAX_CONTEXT_TOTAL_ITEMS: Final = 200
DEFAULT_IMPLEMENTATION_FACETS: Final[tuple[Facet, ...]] = (
    "module_role",
    "imports",
    "importers",
    "callees",
    "public_surface",
    "blast_radius",
    "tests",
    "docs",
    "memory",
)
DEFAULT_IMPACT_FACETS: Final[tuple[Facet, ...]] = (
    "blast_radius",
    "importers",
    "callers",
    "public_surface",
    "baseline_sensitive_findings",
    "tests",
    "review_context",
    "memory",
)
DEFAULT_CONTRACT_FACETS: Final[tuple[Facet, ...]] = (
    "definition_sites",
    "version_constants",
    "contract_tests",
    "public_surface",
    "callers",
    "persistence_path_callers",
    "serialization_path_callers",
    "deserialization_path_callers",
    "store_api_consumers",
    "memory_conflicts",
    "docs",
    "memory",
)
MEMORY_BACKED_FACETS: Final[frozenset[Facet]] = frozenset(
    {
        "docs",
        "memory",
        "trajectories",
        "experiences",
        "tests",
        "contract_tests",
        "memory_conflicts",
    }
)
IMPLEMENTED_CONTEXT_FACETS: Final[frozenset[Facet]] = frozenset(
    {
        *DEFAULT_IMPLEMENTATION_FACETS,
        *DEFAULT_IMPACT_FACETS,
        *DEFAULT_CONTRACT_FACETS,
        "references",
        "test_callers",
        "scope",
        "trajectories",
        "experiences",
    }
)
_CONTRACT_PATH_FACET_ROLES: Final[Mapping[Facet, str]] = {
    "persistence_path_callers": "persistence",
    "serialization_path_callers": "serialization",
    "deserialization_path_callers": "deserialization",
    "store_api_consumers": "store",
}


@dataclass(slots=True)
class _EntryBudget:
    limit: int
    remaining: int
    emitted: int = 0

    def take(
        self,
        items: Sequence[Mapping[str, object]],
    ) -> tuple[list[dict[str, object]], dict[str, object]]:
        total = len(items)
        shown = min(total, self.remaining)
        projected = [dict(item) for item in items[:shown]]
        self.remaining -= shown
        self.emitted += shown
        return projected, {
            "total": total,
            "shown": shown,
            "truncated": shown < total,
            "omitted": total - shown,
        }

    def take_values(
        self,
        items: Sequence[str],
    ) -> tuple[list[str], dict[str, object]]:
        total = len(items)
        shown = min(total, self.remaining)
        projected = list(items[:shown])
        self.remaining -= shown
        self.emitted += shown
        return projected, {
            "total": total,
            "shown": shown,
            "truncated": shown < total,
            "omitted": total - shown,
        }

    @property
    def used(self) -> int:
        return self.emitted

    def reserve(self, count: int) -> None:
        self.remaining = max(0, self.remaining - max(0, count))


# (facet, output_key, reverse_index, keyed_on_source, relation_kind, status, lane)
_CALL_CONTEXT_LANES: Final[
    tuple[tuple[Facet, str, bool, bool, str | None, str, str | None], ...]
] = (
    ("callers", "callers", True, True, "call", "resolved", "production"),
    ("test_callers", "test_callers", True, True, None, "resolved", "test"),
    ("callees", "callees", False, False, "call", "resolved", None),
    ("callees", "unresolved", False, False, "call", "unresolved", None),
    ("references", "references", False, False, "reference", "resolved", None),
)


def _relationship_indexes(
    record: MCPRunRecord,
) -> tuple[dict[str, list[RelationshipRecord]], dict[str, list[RelationshipRecord]]]:
    """Forward (by source) and reverse (by resolved target) relationship indexes."""
    by_source: dict[str, list[RelationshipRecord]] = {}
    by_target: dict[str, list[RelationshipRecord]] = {}
    for facts in record.relationship_facts:
        for relation in facts.relationships:
            by_source.setdefault(relation.source_qualname, []).append(relation)
            if relation.target_qualname is not None:
                by_target.setdefault(relation.target_qualname, []).append(relation)
    return by_source, by_target


def _repo_relative(path: str, root: Path) -> str:
    """Render a relationship-fact path repo-relative so call_context rows and the
    artifact digest stay machine-independent (relationship facts carry the
    absolute analysis filepath; the rest of the tool is repo-relative)."""
    candidate = Path(path)
    if not candidate.is_absolute():
        return path
    try:
        return candidate.relative_to(root).as_posix()
    except ValueError:
        return path


def _relationship_row(
    relation: RelationshipRecord,
    *,
    keyed_on_source: bool,
    root: Path,
) -> dict[str, object]:
    row: dict[str, object] = {
        "relation_kind": relation.relation_kind,
        "resolution_status": relation.resolution_status,
        "origin_lane": relation.origin_lane,
        "evidence": f"{relation.resolution_status}_{relation.relation_kind}",
        "path": _repo_relative(relation.path, root),
        "line": relation.line,
    }
    if keyed_on_source:
        row["source_qualname"] = relation.source_qualname
    else:
        row["target_qualname"] = relation.target_qualname
    if relation.resolution_status == "unresolved":
        row["expression"] = relation.expression
        row["resolution_rule"] = relation.resolution_rule
    return row


def _collect_relationship_rows(
    index: Mapping[str, Sequence[RelationshipRecord]],
    subject_qualnames: frozenset[str],
    *,
    keyed_on_source: bool,
    relation_kind: str | None,
    resolution_status: str,
    origin_lane: str | None,
    root: Path,
) -> list[dict[str, object]]:
    rows: dict[tuple[str, str, int], dict[str, object]] = {}
    for qualname in subject_qualnames:
        for relation in index.get(qualname, ()):
            mismatched = (
                (relation_kind is not None and relation.relation_kind != relation_kind)
                or relation.resolution_status != resolution_status
                or (origin_lane is not None and relation.origin_lane != origin_lane)
            )
            if mismatched:
                continue
            counterpart = (
                relation.source_qualname
                if keyed_on_source
                else relation.target_qualname or relation.expression or ""
            )
            rows.setdefault(
                (counterpart, relation.path, relation.line),
                _relationship_row(relation, keyed_on_source=keyed_on_source, root=root),
            )
    return [rows[key] for key in sorted(rows)]


def _project_call_context(
    *,
    record: MCPRunRecord,
    subject_qualnames: frozenset[str],
    include_set: frozenset[Facet],
    budget: _EntryBudget,
) -> dict[str, object]:
    """Project bounded callers/callees/references/test_callers from run-record facts.

    Reverse-index callers are production-lane resolved calls; test-origin callers
    are a separate lane that never feeds production liveness (D11). Unresolved
    calls are emitted as observations (target=null) alongside callees.
    """
    by_source, by_target = _relationship_indexes(record)
    call_context: dict[str, object] = {}
    for (
        facet,
        key,
        reverse_index,
        keyed_on_source,
        relation_kind,
        status,
        lane,
    ) in _CALL_CONTEXT_LANES:
        if facet not in include_set:
            continue
        _attach_bounded(
            call_context,
            key=key,
            items=_collect_relationship_rows(
                by_target if reverse_index else by_source,
                subject_qualnames,
                keyed_on_source=keyed_on_source,
                relation_kind=relation_kind,
                resolution_status=status,
                origin_lane=lane,
                root=record.root,
            ),
            budget=budget,
        )
    return call_context


def _subject_qualnames(
    record: MCPRunRecord,
    *,
    paths: Sequence[str],
    resolved_symbols: Sequence[Mapping[str, object]],
    resolved_from: str,
) -> frozenset[str]:
    qualnames: set[str] = {
        str(item["qualname"]) for item in resolved_symbols if item.get("qualname")
    }
    # An explicit-symbol subject is the named symbols themselves; the symbol's
    # file is recorded for file-level structural facts but must NOT pull every
    # file-mate's call edges into a function-level call_context.
    if resolved_from == "explicit_symbols":
        return frozenset(qualnames)
    path_set = frozenset(paths)
    for row in _unit_location_index(record):
        if str(row["path"]) in path_set:
            qualnames.add(str(row["qualname"]))
    return frozenset(qualnames)


def _call_graph_status(record: MCPRunRecord) -> tuple[str, list[str]]:
    failed = sorted({failure.split(": ", 1)[0] for failure in record.failures})
    return ("partial" if failed else "complete"), failed


def _relationship_digest_records(record: MCPRunRecord) -> list[dict[str, object]]:
    """Canonical relationship rows for the artifact digest (expression excluded)."""
    rows: list[dict[str, object]] = [
        {
            "relation_kind": relation.relation_kind,
            "resolution_status": relation.resolution_status,
            "origin_lane": relation.origin_lane,
            "source_qualname": relation.source_qualname,
            "target_qualname": relation.target_qualname,
            "path": _repo_relative(relation.path, record.root),
            "line": relation.line,
            "resolution_rule": relation.resolution_rule,
        }
        for facts in record.relationship_facts
        for relation in facts.relationships
    ]
    rows.sort(
        key=lambda row: (
            str(row["source_qualname"]),
            str(row["relation_kind"]),
            str(row["origin_lane"]),
            str(row["target_qualname"] or ""),
            str(row["path"]),
            _as_int(row["line"]),
        )
    )
    return rows


def _context_uncertainties(call_graph_status: str) -> list[str]:
    notes = [
        "resolved call/reference edges are best-effort (cross-module imports, "
        "same-module functions/methods, self/cls); dynamic dispatch and deep "
        "aliasing stay unresolved observations — verify dispatch against source"
    ]
    if call_graph_status != "complete":
        notes.append(
            "call_graph_status is not complete: some files failed analysis and "
            "their relationship edges are missing"
        )
    return notes


def _contract_path_role(records: Sequence[Mapping[str, object]]) -> str | None:
    """D18 anchor: a deterministic contract role for the subject, or None.

    Priority is a typed contract registry, then a known protocol/interface
    symbol, then an Engineering Memory module_role/contract_note — never a name
    or directory heuristic. Phase 30 wires only the memory anchor: a module_role
    record whose role_kind is a contract role (not the inventory_module default).
    """
    for row in records:
        if row.get("type") != "module_role":
            continue
        role_kind = str(_as_mapping(row.get("payload")).get("role_kind", "")).strip()
        if role_kind and role_kind != "inventory_module":
            return role_kind
    return None


def _project_contracts(
    *,
    record: MCPRunRecord,
    subject_paths: Sequence[str],
    subject_qualnames: frozenset[str],
    memory_result: Mapping[str, object] | None,
    include_set: frozenset[Facet],
    budget: _EntryBudget,
) -> dict[str, object]:
    """Project the contract truth-map: where the shape is defined, its pinned
    contract tests and version constants, memory conflicts, and D18-gated
    persistence/serialization path callers. Path-specific caller facets are
    emitted only with a typed or memory-backed anchor; otherwise they are marked
    not_available rather than name/dir-guessed (D13/D18)."""
    contracts: dict[str, object] = {}
    surface = _public_surface_rows(
        record, paths=frozenset(subject_paths), detail_level="normal"
    )
    records = _mapping_rows((memory_result or {}).get("records"))
    facet_items: dict[Facet, list[dict[str, object]]] = {
        "definition_sites": [
            row for row in surface if row["symbol_kind"] in {"class", "constant"}
        ],
        "version_constants": [
            row for row in surface if row["symbol_kind"] == "constant"
        ],
        "contract_tests": [row for row in records if row.get("type") == "test_anchor"],
        "memory_conflicts": [row for row in records if row.get("contradiction_note")],
    }
    for facet, items in facet_items.items():
        if facet in include_set:
            _attach_bounded(contracts, key=facet, items=items, budget=budget)
    role = _contract_path_role(records)
    _, by_target = _relationship_indexes(record)
    for facet, facet_role in _CONTRACT_PATH_FACET_ROLES.items():
        if facet not in include_set:
            continue
        if role == facet_role:
            _attach_bounded(
                contracts,
                key=facet,
                items=_collect_relationship_rows(
                    by_target,
                    subject_qualnames,
                    keyed_on_source=True,
                    relation_kind="call",
                    resolution_status="resolved",
                    origin_lane="production",
                    root=record.root,
                ),
                budget=budget,
            )
        else:
            contracts[facet] = {
                "status": "not_available",
                "reason": "no_typed_or_memory_anchor",
                "tier": "resolvable",
            }
    return contracts


def build_implementation_context(
    *,
    record: MCPRunRecord,
    paths: Sequence[str],
    symbols: Sequence[str],
    subject_resolved_from: str,
    subject_source_summary: Mapping[str, object],
    resolved_symbols: Sequence[Mapping[str, object]],
    unresolved_symbols: Sequence[str],
    mode: str,
    include: Sequence[Facet],
    depth: int,
    detail_level: str,
    budget: int,
    blast_radius: Mapping[str, object],
    memory_result: Mapping[str, object] | None,
    change_control: Mapping[str, object] | None,
) -> dict[str, object]:
    """Build the path-owned implementation-context response."""
    normalized_paths = tuple(sorted(set(paths)))
    normalized_symbols = tuple(sorted(set(symbols)))
    normalized_resolved_symbols = tuple(
        sorted(
            (dict(item) for item in resolved_symbols),
            key=lambda item: (
                str(item.get("qualname", "")),
                str(item.get("path", "")),
                _as_int(item.get("start_line")),
            ),
        )
    )
    normalized_unresolved_symbols = tuple(sorted(set(unresolved_symbols)))
    include_set = frozenset(include)
    (
        entry_budget,
        projected_change_control,
        safety_summary,
        safety_overflow,
    ) = _initialize_context_budget(
        requested_budget=budget,
        change_control=change_control,
    )
    subject = _project_subject(
        paths=normalized_paths,
        symbols=normalized_symbols,
        resolved_symbols=normalized_resolved_symbols,
        unresolved_symbols=normalized_unresolved_symbols,
        resolved_from=subject_resolved_from,
        source_summary=subject_source_summary,
        budget=entry_budget,
    )
    if projected_change_control is not None:
        _project_change_control_scope(
            projected_change_control,
            change_control=change_control or {},
            budget=entry_budget,
        )
    drift = compute_drift(record)
    freshness = _project_freshness(
        drift=drift,
        budget=entry_budget,
    )
    dependency_rows = _dependency_rows(record)
    context_artifact_digest = _context_artifact_digest(
        record=record,
        dependency_rows=dependency_rows,
    )
    request_projection = _context_request_projection(
        subject_resolved_from=subject_resolved_from,
        paths=normalized_paths,
        symbols=normalized_symbols,
        mode=mode,
        include=include,
        depth=depth,
        detail_level=detail_level,
        budget=budget,
        change_control=change_control,
        freshness_status=drift.status,
    )
    if (
        not safety_overflow
        and normalized_symbols
        and not normalized_resolved_symbols
        and not normalized_paths
    ):
        return _subject_not_found_payload(
            record=record,
            mode=mode,
            subject=subject,
            freshness=freshness,
            context_artifact_digest=context_artifact_digest,
            projected_change_control=projected_change_control,
            request=request_projection,
        )
    module_paths = _module_path_index(record)
    selected_modules = frozenset(_path_to_module(path) for path in normalized_paths)
    structural_context: dict[str, object] = {}

    if "module_role" in include_set:
        module_roles = tuple(
            {
                "path": path,
                "module": _path_to_module(path),
                "source_kind": classify_source_kind(path),
                "evidence": "structural",
            }
            for path in normalized_paths
        )
        _attach_bounded(
            structural_context,
            key="module_role",
            items=module_roles,
            budget=entry_budget,
        )

    imports = _imports_for_modules(
        dependency_rows=dependency_rows,
        selected_modules=selected_modules,
        module_paths=module_paths,
    )
    importers = _importers_for_modules(
        dependency_rows=dependency_rows,
        selected_modules=selected_modules,
        module_paths=module_paths,
    )
    if {"imports", "importers", "tests"}.intersection(include_set):
        _attach_bounded(
            structural_context,
            key="related_modules",
            items=_collapsed_related_modules(
                imports=imports if "imports" in include_set else (),
                importers=(
                    importers
                    if {"importers", "tests"}.intersection(include_set)
                    else ()
                ),
                include_production_importers="importers" in include_set,
                include_test_importers="tests" in include_set,
            ),
            budget=entry_budget,
        )

    if "public_surface" in include_set:
        _attach_bounded(
            structural_context,
            key="public_surface",
            items=_public_surface_rows(
                record,
                paths=frozenset(normalized_paths),
                detail_level=detail_level,
            ),
            budget=entry_budget,
        )

    if "blast_radius" in include_set:
        structural_context["blast_radius"] = _bounded_blast_radius(
            blast_radius,
            budget=entry_budget,
            depth=2 if mode == "impact" else depth,
        )

    if "baseline_sensitive_findings" in include_set:
        _attach_bounded(
            structural_context,
            key="baseline_sensitive_findings",
            items=_baseline_sensitive_findings(
                record,
                relevant_paths=_blast_zone_paths(
                    paths=normalized_paths,
                    blast_radius=blast_radius,
                ),
            ),
            budget=entry_budget,
        )

    if "review_context" in include_set and change_control is None:
        _attach_bounded(
            structural_context,
            key="review_context",
            items=_mapping_rows(blast_radius.get("review_context")),
            budget=entry_budget,
        )

    call_graph_status, failed_files = _call_graph_status(record)
    subject_qualnames = _subject_qualnames(
        record,
        paths=normalized_paths,
        resolved_symbols=normalized_resolved_symbols,
        resolved_from=subject_resolved_from,
    )
    call_context = _project_call_context(
        record=record,
        subject_qualnames=subject_qualnames,
        include_set=include_set,
        budget=entry_budget,
    )
    contracts = _project_contracts(
        record=record,
        subject_paths=normalized_paths,
        subject_qualnames=subject_qualnames,
        memory_result=memory_result,
        include_set=include_set,
        budget=entry_budget,
    )

    analysis: dict[str, object] = {
        "run_id": record.run_id,
        "report_digest": record.run_id,
        "context_artifact_digest": context_artifact_digest,
        "context_contract_version": CONTEXT_CONTRACT_VERSION,
        "call_resolution_version": CALL_RESOLUTION_VERSION,
        "freshness": freshness,
        "cache_mode": _cache_mode(record),
        "call_graph_status": call_graph_status,
        "failed_files": failed_files,
    }
    unavailable_facets = sorted(include_set - IMPLEMENTED_CONTEXT_FACETS)
    payload: dict[str, object] = {
        "status": (
            "safety_context_overflow"
            if safety_overflow
            else "subject_not_found"
            if normalized_symbols
            and not normalized_resolved_symbols
            and not normalized_paths
            else "ok"
        ),
        "mode": mode,
        "subject": subject,
        "analysis": analysis,
        "structural_context": structural_context,
        "budget_summary": {
            "requested": budget,
            "effective": entry_budget.limit,
            "emitted": entry_budget.used,
            "remaining": entry_budget.remaining,
            "hard_cap": MAX_CONTEXT_TOTAL_ITEMS,
            "safety": safety_summary,
        },
        "dataflow": {
            "writers": {"status": "not_available", "tier": "dataflow"},
            "readers": {"status": "not_available", "tier": "dataflow"},
        },
        "uncertainties": _context_uncertainties(call_graph_status),
        "next_queries": [
            "Re-run after analyze_repository when analysis.freshness.status is drifted."
        ],
    }
    if memory_result is not None:
        payload["implementation_evidence"] = _implementation_evidence(
            memory_result,
            include=include_set,
            budget=entry_budget,
        )
    if call_context:
        payload["call_context"] = call_context
    if contracts:
        payload["contracts"] = contracts
    if projected_change_control is not None:
        payload["change_control"] = projected_change_control
    if unavailable_facets:
        payload["unavailable_facets"] = unavailable_facets
    budget_summary = _as_mapping(payload["budget_summary"])
    if isinstance(budget_summary, dict):
        budget_summary["emitted"] = entry_budget.used
        budget_summary["remaining"] = entry_budget.remaining
    _attach_projection_digest(
        payload,
        analysis,
        context_artifact_digest=context_artifact_digest,
        request=request_projection,
    )
    return payload


def _context_request_projection(
    *,
    subject_resolved_from: str,
    paths: Sequence[str],
    symbols: Sequence[str],
    mode: str,
    include: Sequence[Facet],
    depth: int,
    detail_level: str,
    budget: int,
    change_control: Mapping[str, object] | None,
    freshness_status: str,
) -> dict[str, object]:
    """Deterministic request fingerprint bound into the projection digest."""
    return {
        "subject": {
            "resolved_from": subject_resolved_from,
            "paths": list(paths),
            "symbols": list(symbols),
        },
        "mode": mode,
        "include": sorted(include),
        "depth": depth,
        "detail_level": detail_level,
        "budget": budget,
        "intent_id": (
            str(change_control.get("intent_id")) if change_control is not None else None
        ),
        "freshness_status": freshness_status,
    }


def _attach_projection_digest(
    payload: Mapping[str, object],
    analysis: dict[str, object],
    *,
    context_artifact_digest: str,
    request: Mapping[str, object],
) -> None:
    """Bind the request and bounded response into analysis.context_projection_digest."""
    analysis["context_projection_digest"] = _digest(
        _projection_digest_payload(
            payload,
            context_artifact_digest=context_artifact_digest,
            request=request,
        )
    )


def _subject_not_found_payload(
    *,
    record: MCPRunRecord,
    mode: str,
    subject: Mapping[str, object],
    freshness: Mapping[str, object],
    context_artifact_digest: str,
    projected_change_control: Mapping[str, object] | None,
    request: Mapping[str, object],
) -> dict[str, object]:
    """Compact response when an explicit symbol query resolves nothing.

    Emitting the full empty facet scaffolding (structural_context, budget,
    dataflow, uncertainties, call_context) on a miss burns LLM context for zero
    signal. Return only the status, the unresolved subject, a slim provenance
    block, the projection digest for determinism, and actionable next steps.
    """
    analysis: dict[str, object] = {
        "run_id": record.run_id,
        "report_digest": record.run_id,
        "context_artifact_digest": context_artifact_digest,
        "context_contract_version": CONTEXT_CONTRACT_VERSION,
        "call_resolution_version": CALL_RESOLUTION_VERSION,
        "freshness": freshness,
    }
    payload: dict[str, object] = {
        "status": "subject_not_found",
        "mode": mode,
        "subject": subject,
        "analysis": analysis,
        "next_steps": [
            "Pass an exact qualname as module:symbol with a colon separator "
            "(for example pkg.mod:func); dot notation does not resolve.",
            "Only analyzed definitions resolve — functions, methods, classes, "
            "and public API rows. External or stdlib names are not indexed.",
            "Inspect subject.unresolved_symbols for the exact tokens that "
            "failed to resolve.",
            "Run analyze_repository again if analysis.freshness.status is drifted.",
        ],
    }
    if projected_change_control is not None:
        payload["change_control"] = projected_change_control
    _attach_projection_digest(
        payload,
        analysis,
        context_artifact_digest=context_artifact_digest,
        request=request,
    )
    return payload


def build_unit_location_inventory(
    *,
    root: Path,
    units: Sequence[Mapping[str, object]],
) -> tuple[MCPUnitLocation, ...]:
    """Project analyzed units into a deterministic, repository-relative index."""
    locations: set[MCPUnitLocation] = set()
    for unit in units:
        qualname = str(unit.get("qualname", "")).strip()
        path = _repo_relative_location(root, unit.get("filepath"))
        start_line = _as_int(unit.get("start_line"))
        end_line = _as_int(unit.get("end_line"))
        if not qualname or path is None or start_line <= 0:
            continue
        locations.add(
            MCPUnitLocation(
                qualname=qualname,
                path=path,
                start_line=start_line,
                end_line=max(start_line, end_line),
            )
        )
    return tuple(
        sorted(
            locations,
            key=lambda item: (
                item.qualname,
                item.path,
                item.start_line,
                item.end_line,
            ),
        )
    )


def resolve_context_symbols(
    record: MCPRunRecord,
    symbols: Sequence[str],
) -> tuple[tuple[dict[str, object], ...], tuple[str, ...]]:
    """Resolve exact qualnames against the off-report Unit/API location index."""
    requested = tuple(sorted({symbol.strip() for symbol in symbols if symbol.strip()}))
    by_qualname: dict[str, list[dict[str, object]]] = {}
    for row in _unit_location_index(record):
        by_qualname.setdefault(str(row["qualname"]), []).append(row)
    resolved = tuple(
        {
            "qualname": symbol,
            "path": str(row["path"]),
            "start_line": _as_int(row["start_line"]),
            "end_line": _as_int(row.get("end_line")),
            "tier": "structural",
            "source": str(row["source"]),
        }
        for symbol in requested
        for row in by_qualname.get(symbol, ())
    )
    unresolved = tuple(symbol for symbol in requested if symbol not in by_qualname)
    return resolved, unresolved


def _initialize_context_budget(
    *,
    requested_budget: int,
    change_control: Mapping[str, object] | None,
) -> tuple[_EntryBudget, dict[str, object] | None, dict[str, object], bool]:
    if change_control is None:
        budget = _EntryBudget(limit=requested_budget, remaining=requested_budget)
        return (
            budget,
            None,
            _summary_from_counts(total=0, shown=0),
            False,
        )
    do_not_touch = _sorted_safety_rows(change_control.get("do_not_touch"))
    review_context = _sorted_safety_rows(change_control.get("review_context"))
    do_not_total = _summary_total(
        change_control.get("do_not_touch_summary"),
        fallback=len(do_not_touch),
    )
    review_total = _summary_total(
        change_control.get("review_context_summary"),
        fallback=len(review_context),
    )
    safety_total = do_not_total + review_total
    effective_limit = min(
        MAX_CONTEXT_TOTAL_ITEMS,
        max(requested_budget, safety_total),
    )
    budget = _EntryBudget(limit=effective_limit, remaining=effective_limit)
    projected = {
        key: value
        for key, value in change_control.items()
        if key
        not in {
            "allowed_files",
            "allowed_related",
            "do_not_touch",
            "do_not_touch_summary",
            "guards",
            "review_context",
            "review_context_summary",
        }
    }
    shown_do_not, _ = budget.take(do_not_touch)
    shown_review, _ = budget.take(review_context)
    shown_total = len(shown_do_not) + len(shown_review)
    budget.reserve(max(0, safety_total - shown_total))
    projected["do_not_touch"] = shown_do_not
    projected["do_not_touch_summary"] = _summary_from_counts(
        total=do_not_total,
        shown=len(shown_do_not),
    )
    projected["review_context"] = shown_review
    projected["review_context_summary"] = _summary_from_counts(
        total=review_total,
        shown=len(shown_review),
    )
    safety_summary = _summary_from_counts(
        total=safety_total,
        shown=shown_total,
    )
    safety_overflow = (
        safety_total > MAX_CONTEXT_TOTAL_ITEMS or safety_total > shown_total
    )
    return budget, projected, safety_summary, safety_overflow


def _project_subject(
    *,
    paths: Sequence[str],
    symbols: Sequence[str],
    resolved_symbols: Sequence[Mapping[str, object]],
    unresolved_symbols: Sequence[str],
    resolved_from: str,
    source_summary: Mapping[str, object],
    budget: _EntryBudget,
) -> dict[str, object]:
    shown_paths, paths_summary = budget.take_values(paths)
    shown_symbols, symbols_summary = budget.take_values(symbols)
    shown_resolved, resolved_summary = budget.take(resolved_symbols)
    shown_unresolved, unresolved_summary = budget.take_values(unresolved_symbols)
    return {
        "resolved_from": resolved_from,
        "paths": shown_paths,
        "paths_summary": paths_summary,
        "symbols": shown_symbols,
        "symbols_summary": symbols_summary,
        "resolved_symbols": shown_resolved,
        "resolved_symbols_summary": resolved_summary,
        "unresolved_symbols": shown_unresolved,
        "unresolved_symbols_summary": unresolved_summary,
        "source_summary": dict(source_summary),
    }


def _project_change_control_scope(
    projected: dict[str, object],
    *,
    change_control: Mapping[str, object],
    budget: _EntryBudget,
) -> None:
    for key in ("allowed_files", "allowed_related", "guards"):
        values = tuple(
            sorted(
                {
                    str(item)
                    for item in _as_sequence(change_control.get(key))
                    if str(item).strip()
                }
            )
        )
        shown, summary = budget.take_values(values)
        projected[key] = shown
        projected[f"{key}_summary"] = summary


def _project_freshness(
    *,
    drift: WorkspaceDrift,
    budget: _EntryBudget,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": drift.status,
        "topology_drift": drift.topology_drift,
        "strength": drift.strength,
    }
    for key, values in (
        ("drifted_files", drift.drifted_files),
        ("added_files", drift.added_files),
        ("deleted_files", drift.deleted_files),
    ):
        shown, summary = budget.take_values(values)
        payload[key] = shown
        payload[f"{key}_summary"] = summary
    return payload


def _collapsed_related_modules(
    *,
    imports: Sequence[Mapping[str, object]],
    importers: Sequence[Mapping[str, object]],
    include_production_importers: bool,
    include_test_importers: bool,
) -> tuple[dict[str, object], ...]:
    rows: dict[tuple[str, str], dict[str, object]] = {}
    for item in imports:
        _append_related_relation(
            rows,
            path=str(item.get("target_path") or ""),
            module=str(item.get("target_module") or ""),
            source_kind=classify_source_kind(str(item.get("target_path") or "")),
            relation={
                "kind": "imports",
                "evidence": "structural",
                "import_type": str(item.get("import_type") or ""),
                "line": _as_int(item.get("line")),
            },
        )
    for item in importers:
        source_kind = str(item.get("source_kind") or "")
        is_test = source_kind in {"tests", "fixtures"}
        if (is_test and not include_test_importers) or (
            not is_test and not include_production_importers
        ):
            continue
        _append_related_relation(
            rows,
            path=str(item.get("source_path") or ""),
            module=str(item.get("source_module") or ""),
            source_kind=source_kind,
            relation={
                "kind": "tested_by" if is_test else "imported_by",
                "evidence": "structural",
                "import_type": str(item.get("import_type") or ""),
                "line": _as_int(item.get("line")),
            },
        )
    return tuple(
        sorted(
            rows.values(),
            key=lambda row: (
                _as_int(row.get("relevance_rank")),
                str(row.get("path", "")),
                str(row.get("module", "")),
            ),
        )
    )


def _append_related_relation(
    rows: dict[tuple[str, str], dict[str, object]],
    *,
    path: str,
    module: str,
    source_kind: str,
    relation: Mapping[str, object],
) -> None:
    key = (path, module)
    row = rows.setdefault(
        key,
        {
            "path": path or None,
            "module": module,
            "source_kind": source_kind,
            "relations": [],
            "relevance_rank": 3,
        },
    )
    relations = row["relations"]
    if not isinstance(relations, list):
        return
    normalized_relation = dict(relation)
    if normalized_relation not in relations:
        relations.append(normalized_relation)
        relations.sort(
            key=lambda item: (
                str(item.get("kind", "")),
                str(item.get("import_type", "")),
                _as_int(item.get("line")),
            )
        )
    relation_rank = {
        "tested_by": 0,
        "imported_by": 1,
        "imports": 2,
    }.get(str(relation.get("kind", "")), 3)
    row["relevance_rank"] = min(
        _as_int(row.get("relevance_rank")),
        relation_rank,
    )


def _sorted_safety_rows(value: object) -> tuple[dict[str, object], ...]:
    return tuple(
        sorted(
            _mapping_rows(value),
            key=lambda row: (
                str(row.get("path", "")),
                str(row.get("category", "")),
                str(row.get("reason", "")),
                str(row.get("severity", "")),
            ),
        )
    )


def _summary_total(value: object, *, fallback: int) -> int:
    return max(fallback, _as_int(_as_mapping(value).get("total")))


def _summary_from_counts(*, total: int, shown: int) -> dict[str, object]:
    return {
        "total": total,
        "shown": shown,
        "truncated": shown < total,
        "omitted": max(0, total - shown),
    }


def _implementation_evidence(
    memory_result: Mapping[str, object],
    *,
    include: frozenset[Facet],
    budget: _EntryBudget,
) -> dict[str, object]:
    records = _mapping_rows(memory_result.get("records"))
    test_records = tuple(row for row in records if row.get("type") == "test_anchor")
    doc_records = tuple(row for row in records if row.get("type") == "document_link")
    general_records = tuple(
        row
        for row in records
        if row.get("type") not in {"document_link", "test_anchor"}
    )
    payload: dict[str, object] = {
        "scope_resolved_from": memory_result.get("scope_resolved_from"),
        "retrieval_policy": dict(_as_mapping(memory_result.get("retrieval_policy"))),
    }
    if "memory" in include:
        _attach_bounded(payload, key="memory", items=general_records, budget=budget)
    if {"memory", "trajectories"}.intersection(include):
        _attach_bounded(
            payload,
            key="trajectories",
            items=_mapping_rows(memory_result.get("trajectories")),
            budget=budget,
        )
    if {"memory", "experiences"}.intersection(include):
        _attach_bounded(
            payload,
            key="experiences",
            items=_mapping_rows(memory_result.get("experiences")),
            budget=budget,
        )
    if "tests" in include:
        _attach_bounded(payload, key="test_anchors", items=test_records, budget=budget)
    if "docs" in include:
        _attach_bounded(payload, key="doc_anchors", items=doc_records, budget=budget)
    return payload


def _baseline_sensitive_findings(
    record: MCPRunRecord,
    *,
    relevant_paths: frozenset[str],
) -> tuple[dict[str, object], ...]:
    findings = _as_mapping(record.report_document.get("findings"))
    groups = _as_mapping(findings.get("groups"))
    rows: list[dict[str, object]] = []
    for family, family_payload in sorted(groups.items()):
        for category, category_payload in sorted(_as_mapping(family_payload).items()):
            for raw_group in _as_sequence(category_payload):
                group = _as_mapping(raw_group)
                paths = _finding_paths(group)
                novelty = str(group.get("novelty", "")).strip()
                if not relevant_paths.intersection(paths) or novelty not in {
                    "known",
                    "new",
                }:
                    continue
                rows.append(
                    {
                        "id": str(group.get("id", "")).strip(),
                        "family": str(family),
                        "category": str(category),
                        "kind": str(group.get("kind", "")).strip(),
                        "severity": str(group.get("severity", "")).strip(),
                        "novelty": novelty,
                        "paths": list(paths),
                        "evidence": "structural",
                    }
                )
    return tuple(
        sorted(
            rows,
            key=lambda row: (
                0 if row["novelty"] == "new" else 1,
                str(row["severity"]),
                str(row["family"]),
                str(row["category"]),
                str(row["id"]),
            ),
        )
    )


def _finding_paths(group: Mapping[str, object]) -> tuple[str, ...]:
    paths = {
        str(
            item.get("relative_path") or item.get("path") or item.get("file") or ""
        ).strip()
        for item in _mapping_rows(group.get("items"))
    }
    return tuple(sorted(path for path in paths if path))


def _blast_zone_paths(
    *,
    paths: Sequence[str],
    blast_radius: Mapping[str, object],
) -> frozenset[str]:
    return frozenset(
        {
            *paths,
            *(
                str(item)
                for key in (
                    "direct_dependents",
                    "transitive_dependents",
                    "clone_cohort_members",
                    "in_dependency_cycle",
                )
                for item in _as_sequence(blast_radius.get(key))
                if str(item).strip()
            ),
        }
    )


def _mapping_rows(value: object) -> tuple[dict[str, object], ...]:
    return tuple(dict(_as_mapping(item)) for item in _as_sequence(value))


def _dependency_rows(record: MCPRunRecord) -> tuple[dict[str, object], ...]:
    families = _report_families(record)
    dependencies = _as_mapping(families.get("dependencies"))
    rows: list[dict[str, object]] = [
        {
            "source": str(item.get("source", "")).strip(),
            "target": str(item.get("target", "")).strip(),
            "import_type": str(item.get("import_type", "")).strip(),
            "line": _as_int(item.get("line")),
        }
        for raw in _as_sequence(dependencies.get("items"))
        for item in (_as_mapping(raw),)
    ]
    return tuple(
        sorted(
            (row for row in rows if row["source"] and row["target"]),
            key=lambda row: (
                str(row["source"]),
                str(row["target"]),
                str(row["import_type"]),
                _as_int(row["line"]),
            ),
        )
    )


def _imports_for_modules(
    *,
    dependency_rows: Sequence[Mapping[str, object]],
    selected_modules: frozenset[str],
    module_paths: Mapping[str, str],
) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = [
        {
            "source_module": str(row["source"]),
            "target_module": str(row["target"]),
            "target_path": module_paths.get(str(row["target"])),
            "import_type": str(row["import_type"]),
            "line": _as_int(row["line"]),
            "evidence": "structural",
        }
        for row in dependency_rows
        if str(row["source"]) in selected_modules
    ]
    return tuple(
        sorted(
            rows,
            key=lambda row: (
                str(row["source_module"]),
                str(row["target_module"]),
                str(row["import_type"]),
                _as_int(row["line"]),
            ),
        )
    )


def _importers_for_modules(
    *,
    dependency_rows: Sequence[Mapping[str, object]],
    selected_modules: frozenset[str],
    module_paths: Mapping[str, str],
) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = [
        {
            "source_module": str(row["source"]),
            "source_path": module_paths.get(str(row["source"])),
            "source_kind": classify_source_kind(
                module_paths.get(str(row["source"]), "")
            ),
            "target_module": str(row["target"]),
            "import_type": str(row["import_type"]),
            "line": _as_int(row["line"]),
            "evidence": "structural",
        }
        for row in dependency_rows
        if str(row["target"]) in selected_modules
    ]
    return tuple(
        sorted(
            rows,
            key=lambda row: (
                str(row["source_module"]),
                str(row["target_module"]),
                str(row["import_type"]),
                _as_int(row["line"]),
            ),
        )
    )


def _public_surface_rows(
    record: MCPRunRecord,
    *,
    paths: frozenset[str],
    detail_level: str,
) -> tuple[dict[str, object], ...]:
    families = _report_families(record)
    api_surface = _as_mapping(families.get("api_surface"))
    rows: list[dict[str, object]] = []
    for raw in _as_sequence(api_surface.get("items")):
        item = _as_mapping(raw)
        path = _report_item_path(record, item)
        if path not in paths:
            continue
        row: dict[str, object] = {
            "qualname": str(item.get("qualname", "")).strip(),
            "path": path,
            "start_line": _as_int(item.get("start_line")),
            "end_line": _as_int(item.get("end_line")),
            "symbol_kind": str(item.get("symbol_kind", "")).strip(),
            "evidence": "structural",
        }
        if detail_level != "compact":
            row["params"] = [
                dict(_as_mapping(param)) for param in _as_sequence(item.get("params"))
            ]
            row["returns_annotated"] = bool(item.get("returns_annotated"))
            row["exported_via"] = item.get("exported_via")
        if detail_level == "full":
            row["record_kind"] = str(item.get("record_kind", "symbol"))
            row["module"] = str(item.get("module", "")).strip()
        rows.append(row)
    return tuple(
        sorted(
            rows,
            key=lambda row: (
                str(row["path"]),
                _as_int(row["start_line"]),
                str(row["qualname"]),
            ),
        )
    )


def _bounded_blast_radius(
    payload: Mapping[str, object],
    *,
    budget: _EntryBudget,
    depth: int,
) -> dict[str, object]:
    result: dict[str, object] = {
        "radius_level": str(payload.get("radius_level", "low")),
        "depth": "transitive" if depth > 1 else "direct",
    }
    for source_key, output_key in (
        ("direct_dependents", "direct"),
        ("transitive_dependents", "transitive"),
        ("clone_cohort_members", "clone_cohorts"),
        ("in_dependency_cycle", "dependency_cycles"),
    ):
        items = tuple(
            {"path": str(item), "evidence": "structural"}
            for item in _as_sequence(payload.get(source_key))
            if str(item).strip()
        )
        _attach_bounded(result, key=output_key, items=items, budget=budget)
    return result


def _attach_bounded(
    payload: dict[str, object],
    *,
    key: str,
    items: Sequence[Mapping[str, object]],
    budget: _EntryBudget,
) -> None:
    projected, summary = budget.take(items)
    payload[key] = projected
    payload[f"{key}_summary"] = summary


def _module_path_index(record: MCPRunRecord) -> dict[str, str]:
    if record.manifest is None:
        return {}
    return {
        module: path
        for path in sorted(record.manifest)
        if (module := _path_to_module(path))
    }


def _context_artifact_digest(
    *,
    record: MCPRunRecord,
    dependency_rows: Sequence[Mapping[str, object]],
) -> str:
    del dependency_rows
    manifest = record.manifest or {}
    call_graph_status, failed_files = _call_graph_status(record)
    return _digest(
        {
            "canonicalization": {
                "version": "1",
                "algorithm": "sha256",
                "scope": "context_artifact",
                "wire": "bare_hex",
            },
            "report_digest": record.run_id,
            "context_contract_version": CONTEXT_CONTRACT_VERSION,
            "call_resolution_version": CALL_RESOLUTION_VERSION,
            "call_graph_status": call_graph_status,
            "failed_files": failed_files,
            "manifest": [
                {
                    "path": path,
                    "mtime_ns": int(manifest[path]["mtime_ns"]),
                    "size": int(manifest[path]["size"]),
                }
                for path in sorted(manifest)
            ],
            "unit_location_index": [
                {
                    "qualname": str(row["qualname"]),
                    "path": str(row["path"]),
                    "start_line": _as_int(row["start_line"]),
                }
                for row in _unit_location_index(record)
            ],
            "relationship_records": _relationship_digest_records(record),
        }
    )


def _projection_digest_payload(
    payload: Mapping[str, object],
    *,
    context_artifact_digest: str,
    request: Mapping[str, object],
) -> dict[str, object]:
    return {
        "canonicalization": {
            "version": "1",
            "algorithm": "sha256",
            "scope": "context_projection",
            "wire": "bare_hex",
        },
        "context_artifact_digest": context_artifact_digest,
        "request": dict(request),
        "projection": {
            key: value
            for key, value in payload.items()
            if key not in {"message", "next_queries", "uncertainties"}
        },
    }


def _cache_mode(record: MCPRunRecord) -> str:
    cache = _as_mapping(record.summary.get("cache"))
    freshness = str(cache.get("freshness", "")).strip()
    return {
        "fresh": "fresh_compute",
        "mixed": "partial_reuse",
        "reused": "full_reuse",
    }.get(freshness, "fresh_compute")


def _report_families(record: MCPRunRecord) -> Mapping[str, object]:
    metrics = _as_mapping(record.report_document.get("metrics"))
    return _as_mapping(metrics.get("families"))


def _unit_location_index(
    record: MCPRunRecord,
) -> tuple[dict[str, object], ...]:
    rows: dict[tuple[str, str, int], dict[str, object]] = {}
    for location in record.unit_inventory:
        key = (location.qualname, location.path, location.start_line)
        rows[key] = {
            "qualname": location.qualname,
            "path": location.path,
            "start_line": location.start_line,
            "end_line": location.end_line,
            "source": "unit_inventory",
        }
    api_surface = _as_mapping(_report_families(record).get("api_surface"))
    for raw in _as_sequence(api_surface.get("items")):
        item = _as_mapping(raw)
        qualname = str(item.get("qualname", "")).strip()
        path = _report_item_path(record, item)
        start_line = _as_int(item.get("start_line"))
        if not qualname or not path or start_line <= 0:
            continue
        key = (qualname, path, start_line)
        rows[key] = {
            "qualname": qualname,
            "path": path,
            "start_line": start_line,
            "end_line": max(start_line, _as_int(item.get("end_line"))),
            "source": "api_surface",
        }
    return tuple(
        rows[key]
        for key in sorted(
            rows,
            key=lambda item: (item[0], item[1], item[2]),
        )
    )


def _report_item_path(
    record: MCPRunRecord,
    item: Mapping[str, object],
) -> str:
    raw = item.get("relative_path") or item.get("filepath")
    path = _repo_relative_location(record.root, raw)
    return path or ""


def _repo_relative_location(root: Path, raw: object) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None
    root_path = root.resolve()
    candidate = Path(text)
    if not candidate.is_absolute():
        candidate = root_path / candidate
    try:
        return candidate.resolve().relative_to(root_path).as_posix()
    except (OSError, ValueError):
        return None


def _digest(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(
        orjson.dumps(payload, option=orjson.OPT_SORT_KEYS),
    ).hexdigest()


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


__all__ = [
    "CALL_RESOLUTION_VERSION",
    "CONTEXT_CONTRACT_VERSION",
    "DEFAULT_IMPACT_FACETS",
    "DEFAULT_IMPLEMENTATION_FACETS",
    "IMPLEMENTED_CONTEXT_FACETS",
    "build_implementation_context",
    "build_unit_location_inventory",
    "resolve_context_symbols",
]
