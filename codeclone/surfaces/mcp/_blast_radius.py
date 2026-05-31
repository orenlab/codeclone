# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""MCP blast-radius presentation over the neutral analysis core."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final, Literal

from codeclone.analysis import blast_radius as _core

BlastRadiusDepth = _core.BlastRadiusDepth
BlastRadiusResult = _core.BlastRadiusResult
DEFAULT_DO_NOT_TOUCH_PATTERNS = _core.DEFAULT_DO_NOT_TOUCH_PATTERNS
MAX_CONTEXT_ITEMS = _core.MAX_CONTEXT_ITEMS
compute_blast_radius = _core.compute_blast_radius

# Re-export core helpers for MCP contract tests and backward compatibility.
_append_boundary_entry = _core._append_boundary_entry
_append_review_entry = _core._append_review_entry
_as_int = _core._as_int
_compute_transitive_dependents = _core._compute_transitive_dependents
_guardrails = _core._guardrails
_item_path = _core._item_path
_normalize_relative_path = _core._normalize_relative_path
_path_to_module = _core._path_to_module

BlastRadiusInclude = Literal[
    "imports",
    "clone_cohorts",
    "coverage",
    "risk_signals",
    "do_not_touch",
    "review_context",
    "cycles",
]

VALID_BLAST_RADIUS_DEPTHS: Final[frozenset[str]] = frozenset({"direct", "transitive"})
VALID_BLAST_RADIUS_INCLUDE: Final[frozenset[str]] = frozenset(
    {
        "imports",
        "clone_cohorts",
        "coverage",
        "risk_signals",
        "do_not_touch",
        "review_context",
        "cycles",
    }
)
DEFAULT_BLAST_RADIUS_INCLUDE: Final[tuple[BlastRadiusInclude, ...]] = (
    "imports",
    "clone_cohorts",
    "coverage",
    "risk_signals",
    "do_not_touch",
    "review_context",
    "cycles",
)


def _bounded_entries(
    entries: Sequence[Mapping[str, str]],
    *,
    limit: int = MAX_CONTEXT_ITEMS,
) -> list[dict[str, str]]:
    return [dict(item) for item in entries[:limit]]


def _count_by_field(
    entries: Sequence[Mapping[str, str]],
    *,
    field: str,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        key = str(entry.get(field, "")).strip() or "unknown"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _entry_summary(
    *,
    entries: Sequence[Mapping[str, str]],
    shown: int,
) -> dict[str, object]:
    return {
        "total": len(entries),
        "shown": shown,
        "truncated": shown < len(entries),
        "top_categories": _count_by_field(entries, field="category"),
        "top_reasons": _count_by_field(entries, field="reason"),
    }


def blast_radius_to_payload(
    result: BlastRadiusResult,
    *,
    include: Sequence[str] = DEFAULT_BLAST_RADIUS_INCLUDE,
) -> dict[str, object]:
    include_set = {str(item) for item in include}
    imports_enabled = "imports" in include_set
    risk_enabled = "risk_signals" in include_set or "coverage" in include_set
    structural_risk = dict(result.structural_risk) if risk_enabled else {}
    if "coverage" not in include_set:
        structural_risk.pop("low_coverage_in_blast_zone", None)
    if "risk_signals" not in include_set:
        for key in (
            "high_complexity_in_blast_zone",
            "high_coupling_in_blast_zone",
            "overloaded_modules_in_blast_zone",
        ):
            structural_risk.pop(key, None)
    do_not_touch = result.do_not_touch if "do_not_touch" in include_set else ()
    review_context = result.review_context if "review_context" in include_set else ()
    do_not_touch_payload = _bounded_entries(do_not_touch)
    review_context_payload = _bounded_entries(review_context)
    return {
        "run_id": result.run_id,
        "origin": list(result.origin),
        "depth": result.depth,
        "radius_level": result.radius_level,
        "direct_dependents": (
            list(result.direct_dependents) if imports_enabled else []
        ),
        "transitive_dependents": (
            list(result.transitive_dependents)
            if imports_enabled and result.depth == "transitive"
            else []
        ),
        "clone_cohort_members": (
            list(result.clone_cohort_members) if "clone_cohorts" in include_set else []
        ),
        "in_dependency_cycle": (
            list(result.in_dependency_cycle) if "cycles" in include_set else []
        ),
        "structural_risk": structural_risk,
        "do_not_touch": do_not_touch_payload,
        "do_not_touch_summary": _entry_summary(
            entries=do_not_touch,
            shown=len(do_not_touch_payload),
        ),
        "review_context": review_context_payload,
        "review_context_summary": _entry_summary(
            entries=review_context,
            shown=len(review_context_payload),
        ),
        "guardrails": list(result.guardrails),
    }


__all__ = [
    "DEFAULT_BLAST_RADIUS_INCLUDE",
    "DEFAULT_DO_NOT_TOUCH_PATTERNS",
    "MAX_CONTEXT_ITEMS",
    "VALID_BLAST_RADIUS_DEPTHS",
    "VALID_BLAST_RADIUS_INCLUDE",
    "BlastRadiusDepth",
    "BlastRadiusInclude",
    "BlastRadiusResult",
    "blast_radius_to_payload",
    "compute_blast_radius",
]
