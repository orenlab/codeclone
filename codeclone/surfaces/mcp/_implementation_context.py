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
from typing import Final

import orjson

from ...paths import classify_source_kind
from ._blast_radius import _path_to_module
from ._session_shared import MCPRunRecord
from ._workspace_drift import compute_drift
from .messages.params import Facet

CONTEXT_CONTRACT_VERSION: Final = "1"
CALL_RESOLUTION_VERSION: Final = "1"
DEFAULT_IMPLEMENTATION_FACETS: Final[tuple[Facet, ...]] = (
    "module_role",
    "imports",
    "importers",
    "public_surface",
    "blast_radius",
    "tests",
)
IMPLEMENTED_STEP2_FACETS: Final[frozenset[Facet]] = frozenset(
    DEFAULT_IMPLEMENTATION_FACETS
)


@dataclass(slots=True)
class _EntryBudget:
    remaining: int

    def take(
        self,
        items: Sequence[Mapping[str, object]],
    ) -> tuple[list[dict[str, object]], dict[str, object]]:
        total = len(items)
        shown = min(total, self.remaining)
        projected = [dict(item) for item in items[:shown]]
        self.remaining -= shown
        return projected, {
            "total": total,
            "shown": shown,
            "truncated": shown < total,
        }


def build_implementation_context(
    *,
    record: MCPRunRecord,
    paths: Sequence[str],
    include: Sequence[Facet],
    depth: int,
    detail_level: str,
    budget: int,
    blast_radius: Mapping[str, object],
) -> dict[str, object]:
    """Build the Step-2 path-only implementation context response."""
    normalized_paths = tuple(sorted(set(paths)))
    include_set = frozenset(include)
    entry_budget = _EntryBudget(remaining=budget)
    dependency_rows = _dependency_rows(record)
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
    if "imports" in include_set:
        _attach_bounded(
            structural_context,
            key="direct_imports",
            items=imports,
            budget=entry_budget,
        )

    importers = _importers_for_modules(
        dependency_rows=dependency_rows,
        selected_modules=selected_modules,
        module_paths=module_paths,
    )
    if "importers" in include_set:
        _attach_bounded(
            structural_context,
            key="importers",
            items=importers,
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
            depth=depth,
        )

    if "tests" in include_set:
        test_importers = tuple(
            item
            for item in importers
            if str(item.get("source_kind", "")) in {"tests", "fixtures"}
        )
        _attach_bounded(
            structural_context,
            key="tests",
            items=test_importers,
            budget=entry_budget,
        )

    drift = compute_drift(record)
    analysis = {
        "run_id": record.run_id,
        "report_digest": record.run_id,
        "context_artifact_digest": _context_artifact_digest(
            record=record,
            dependency_rows=dependency_rows,
        ),
        "context_contract_version": CONTEXT_CONTRACT_VERSION,
        "call_resolution_version": CALL_RESOLUTION_VERSION,
        "freshness": {
            "status": drift.status,
            "drifted_files": list(drift.drifted_files),
            "added_files": list(drift.added_files),
            "deleted_files": list(drift.deleted_files),
            "topology_drift": drift.topology_drift,
            "strength": drift.strength,
        },
        "cache_mode": _cache_mode(record),
        "call_graph_status": "unavailable",
        "failed_files": [],
    }
    unavailable_facets = sorted(include_set - IMPLEMENTED_STEP2_FACETS)
    payload: dict[str, object] = {
        "status": "ok",
        "mode": "implementation",
        "subject": {
            "resolved_from": "explicit_paths",
            "paths": list(normalized_paths),
            "symbols": [],
            "resolved_symbols": [],
        },
        "analysis": analysis,
        "structural_context": structural_context,
        "dataflow": {
            "writers": {"status": "not_available", "tier": "dataflow"},
            "readers": {"status": "not_available", "tier": "dataflow"},
        },
        "uncertainties": [
            (
                "call/reference relationships are not available in Step 2; "
                "use structural imports and blast radius until v2 data ships"
            )
        ],
        "next_queries": [
            "Re-run after analyze_repository when analysis.freshness.status is drifted."
        ],
    }
    if unavailable_facets:
        payload["unavailable_facets"] = unavailable_facets
    request_projection: dict[str, object] = {
        "subject": payload["subject"],
        "mode": "implementation",
        "include": sorted(include),
        "depth": depth,
        "detail_level": detail_level,
        "budget": budget,
        "intent_id": None,
        "freshness_status": drift.status,
    }
    analysis["context_projection_digest"] = _digest(
        _projection_digest_payload(
            payload,
            context_artifact_digest=str(analysis["context_artifact_digest"]),
            request=request_projection,
        )
    )
    return payload


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
        path = str(item.get("relative_path", "")).strip()
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
            "call_graph_status": "unavailable",
            "failed_files": [],
            "manifest": [
                {
                    "path": path,
                    "mtime_ns": int(manifest[path]["mtime_ns"]),
                    "size": int(manifest[path]["size"]),
                }
                for path in sorted(manifest)
            ],
            "unit_location_index": [],
            "relationship_records": [],
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


def _digest(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(
        orjson.dumps(payload, option=orjson.OPT_SORT_KEYS),
    ).hexdigest()


def _as_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _as_sequence(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()


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
    "DEFAULT_IMPLEMENTATION_FACETS",
    "IMPLEMENTED_STEP2_FACETS",
    "build_implementation_context",
]
