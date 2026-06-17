# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Bounded, deterministic name search across one stored MCP run.

Three lanes are indexed from a single ``MCPRunRecord``:

* ``definition`` — analyzed function/method/class qualnames (``unit_inventory``).
* ``call`` / ``reference`` — resolved relationship targets, including external
  ``module:attr`` targets reached through a tracked import (``relationship_facts``).
* ``import`` — raw imports, including external/stdlib, that the report's
  dependency family filters out to internal-only (``module_imports``).

Matching is an adaptive cascade (``exact`` -> ``token`` -> ``prefix`` ->
``substring``); only the narrowest non-empty tier is returned, so a precise hit
never drowns under loose substring noise. The projection is read-only and never
authorizes edits.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ._implementation_context import _repo_relative
from ._session_shared import MCPRunRecord

_TIER_ORDER: tuple[str, ...] = ("exact", "token", "prefix", "substring")
_LANE_ORDER: dict[str, int] = {
    "definition": 0,
    "call": 1,
    "reference": 2,
    "import": 3,
}
_LANE_RESULT_KEYS: dict[str, str] = {
    "definition": "definitions",
    "call": "calls",
    "reference": "references",
    "import": "imports",
}
_TOKEN_SPLIT = re.compile(r"[.:_]")


@dataclass(frozen=True, slots=True)
class _SearchEntry:
    lane: str
    name: str
    location: str
    line: int
    detail: str | None


def _name_tokens(name_casefold: str) -> frozenset[str]:
    return frozenset(token for token in _TOKEN_SPLIT.split(name_casefold) if token)


def _match_tier(name: str, query_casefold: str) -> str | None:
    """Narrowest tier at which ``name`` matches the (already casefolded) query."""
    name_cf = name.casefold()
    if name_cf == query_casefold:
        return "exact"
    if query_casefold in _name_tokens(name_cf):
        return "token"
    if name_cf.startswith(query_casefold):
        return "prefix"
    if query_casefold in name_cf:
        return "substring"
    return None


def _module_path_index(record: MCPRunRecord) -> dict[str, str]:
    """Map each analyzed module to a repo-relative file path via its units."""
    index: dict[str, str] = {}
    for unit in record.unit_inventory:
        module = unit.qualname.split(":", 1)[0]
        index.setdefault(module, unit.path)
    return index


def _build_search_entries(
    record: MCPRunRecord,
    root: Path,
) -> list[_SearchEntry]:
    entries: list[_SearchEntry] = [
        _SearchEntry(
            lane="definition",
            name=unit.qualname,
            location=unit.path,
            line=unit.start_line,
            detail=None,
        )
        for unit in record.unit_inventory
    ]
    for facts in record.relationship_facts:
        for relation in facts.relationships:
            if relation.target_qualname is None:
                continue
            lane = "call" if relation.relation_kind == "call" else "reference"
            entries.append(
                _SearchEntry(
                    lane=lane,
                    name=relation.target_qualname,
                    location=_repo_relative(relation.path, root),
                    line=relation.line,
                    detail=relation.source_qualname,
                )
            )
    module_paths = _module_path_index(record)
    entries.extend(
        _SearchEntry(
            lane="import",
            name=dep.target,
            location=module_paths.get(dep.source, dep.source),
            line=dep.line,
            detail=dep.import_type,
        )
        for dep in record.module_imports
    )
    return entries


def _entry_row(entry: _SearchEntry, *, tier: str) -> dict[str, object]:
    row: dict[str, object] = {
        "lane": entry.lane,
        "name": entry.name,
        "location": entry.location,
        "line": entry.line,
        "match_tier": tier,
    }
    if entry.detail is not None:
        row["detail"] = entry.detail
    return row


def _bounded_summary(*, total: int, shown: int) -> dict[str, object]:
    return {
        "total": total,
        "shown": shown,
        "truncated": shown < total,
        "omitted": total - shown,
    }


def _search_response(
    *,
    query: str,
    tier: str,
    matches: list[_SearchEntry],
    budget: int,
) -> dict[str, object]:
    ordered = sorted(
        matches,
        key=lambda entry: (
            _LANE_ORDER.get(entry.lane, 99),
            entry.name,
            entry.location,
            entry.line,
        ),
    )
    limit = max(0, budget)
    shown = ordered[:limit]
    grouped: dict[str, list[dict[str, object]]] = {}
    for entry in shown:
        key = _LANE_RESULT_KEYS[entry.lane]
        grouped.setdefault(key, []).append(_entry_row(entry, tier=tier))
    return {
        "status": "ok",
        "query": query,
        "match_tier": tier,
        "results": grouped,
        "results_summary": _bounded_summary(total=len(ordered), shown=len(shown)),
    }


def _no_matches_response(*, query: str) -> dict[str, object]:
    return {
        "status": "no_matches",
        "query": query,
        "results": {},
        "results_summary": _bounded_summary(total=0, shown=0),
        "next_steps": [
            "Broaden the query — names match by exact, then whole-token, prefix, "
            "and substring across definitions, call targets, and imports.",
            "Try a shorter fragment or a module name (for example 'logging' "
            "rather than 'logging.getLogger').",
            "Re-run analyze_repository if the stored run is stale.",
        ],
    }


def search_graph(
    *,
    record: MCPRunRecord,
    root: Path,
    query: str,
    budget: int = 50,
) -> dict[str, object]:
    """Search analyzed names across definitions, calls/references, and imports.

    Returns the narrowest non-empty match tier grouped by lane, or a compact
    ``no_matches`` response with ``next_steps`` when nothing matches.
    """
    normalized = query.strip()
    if not normalized:
        return _no_matches_response(query=query)
    query_casefold = normalized.casefold()
    entries = _build_search_entries(record, root)
    buckets: dict[str, list[_SearchEntry]] = {tier: [] for tier in _TIER_ORDER}
    for entry in entries:
        tier = _match_tier(entry.name, query_casefold)
        if tier is not None:
            buckets[tier].append(entry)
    for tier in _TIER_ORDER:
        if buckets[tier]:
            return _search_response(
                query=normalized,
                tier=tier,
                matches=buckets[tier],
                budget=budget,
            )
    return _no_matches_response(query=normalized)
