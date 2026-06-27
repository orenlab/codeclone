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

from ._context_governance import (
    BLAST_ARTIFACT_PROJECTION_KIND,
    context_governance_digest,
)

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
BLAST_ARTIFACT_DETAIL_CONTRACT_VERSION: Final = "1"


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


def blast_radius_artifact_payload(
    blast_payload: Mapping[str, object],
    *,
    source_tool: str,
) -> dict[str, object]:
    """Return the immutable audit payload for exact blast drill-down."""

    full_projection = dict(blast_payload)
    projection_digest = context_governance_digest(
        BLAST_ARTIFACT_PROJECTION_KIND,
        full_projection,
    )
    digest_value = projection_digest["value"]
    return {
        "artifact_schema_version": "1",
        "blast_artifact_id": f"blast-{digest_value}",
        "run_id": str(full_projection.get("run_id", "")),
        "projection_digest": projection_digest,
        "detail_contract_version": BLAST_ARTIFACT_DETAIL_CONTRACT_VERSION,
        "source_tool": source_tool,
        "source": "audit_event",
        "durable": True,
        "retention_bounded": True,
        "blast_radius": full_projection,
    }


def blast_radius_summary_payload(
    blast_payload: Mapping[str, object],
    *,
    artifact: Mapping[str, object],
) -> dict[str, object]:
    """Return the safety-complete summary projection for start responses."""

    direct = _object_sequence(blast_payload.get("direct_dependents"))
    transitive = _object_sequence(blast_payload.get("transitive_dependents"))
    cohorts = _object_sequence(blast_payload.get("clone_cohort_members"))
    cycles = _object_sequence(blast_payload.get("in_dependency_cycle"))
    review = _object_sequence(blast_payload.get("review_context"))
    return {
        "run_id": blast_payload.get("run_id"),
        "origin": list(_object_sequence(blast_payload.get("origin"))),
        "depth": blast_payload.get("depth"),
        "radius_level": blast_payload.get("radius_level"),
        "direct_dependents": [],
        "direct_dependents_summary": _list_summary(direct),
        "transitive_dependents": [],
        "transitive_dependents_summary": _list_summary(transitive),
        "clone_cohort_members": [],
        "clone_cohort_summary": _list_summary(cohorts),
        "in_dependency_cycle": [],
        "cycle_summary": _list_summary(cycles),
        "structural_risk": {},
        "structural_risk_summary": _structural_risk_summary(blast_payload),
        "do_not_touch": list(_object_sequence(blast_payload.get("do_not_touch"))),
        "do_not_touch_summary": blast_payload.get("do_not_touch_summary", {}),
        "review_context": [],
        "review_context_summary": blast_payload.get(
            "review_context_summary",
            _list_summary(review),
        ),
        "guardrails": list(_object_sequence(blast_payload.get("guardrails"))),
        "blast_artifact": blast_artifact_reference(artifact),
        "omitted_evidence": _build_omitted_evidence(
            artifact=artifact,
            lanes={
                "direct_dependents": direct,
                "transitive_dependents": transitive,
                "clone_cohort_members": cohorts,
                "review_context": review,
                "in_dependency_cycle": cycles,
                "structural_risk": _flatten_structural_risk(blast_payload),
            },
        ),
    }


def blast_artifact_reference(artifact: Mapping[str, object]) -> dict[str, object]:
    """Return the stable read-only route metadata for a blast artifact."""

    return {
        "blast_artifact_id": artifact.get("blast_artifact_id"),
        "run_id": artifact.get("run_id"),
        "projection_digest": artifact.get("projection_digest"),
        "detail_contract_version": artifact.get("detail_contract_version"),
        "retrieval_tool": "get_blast_artifact",
        "route": "get_blast_artifact(root=..., run_id=..., blast_artifact_id=...)",
        "retention_bounded": bool(artifact.get("retention_bounded")),
        "source": artifact.get("source"),
    }


def _object_sequence(value: object) -> tuple[object, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(value)
    return ()


def _list_summary(items: Sequence[object]) -> dict[str, object]:
    return {
        "total": len(items),
        "shown": 0,
        "truncated": bool(items),
    }


def _build_omitted_evidence(
    *,
    lanes: Mapping[str, Sequence[object]],
    artifact: Mapping[str, object],
) -> dict[str, object]:
    omitted: dict[str, object] = {}
    for lane, items in sorted(lanes.items(), key=lambda item: str(item[0])):
        summary = _omitted_lane_summary(items, artifact)
        if summary is not None:
            omitted[lane] = summary
    return omitted


def _omitted_lane_summary(
    items: Sequence[object],
    artifact: Mapping[str, object],
) -> dict[str, object] | None:
    summary = _list_summary(items)
    if not summary["truncated"]:
        return None
    summary["retrieval"] = _compact_artifact_retrieval(artifact)
    return summary


def _compact_artifact_retrieval(artifact: Mapping[str, object]) -> dict[str, object]:
    return {
        "blast_artifact_id": artifact.get("blast_artifact_id"),
        "run_id": artifact.get("run_id"),
        "retrieval_tool": "get_blast_artifact",
        "route": "get_blast_artifact(root=..., run_id=..., blast_artifact_id=...)",
    }


def _structural_risk_summary(
    blast_payload: Mapping[str, object],
) -> dict[str, object]:
    risk = blast_payload.get("structural_risk")
    if not isinstance(risk, Mapping):
        return {}
    return {
        str(key): _list_summary(_object_sequence(value))
        for key, value in sorted(risk.items(), key=lambda item: str(item[0]))
    }


def _flatten_structural_risk(
    blast_payload: Mapping[str, object],
) -> tuple[object, ...]:
    risk = blast_payload.get("structural_risk")
    if not isinstance(risk, Mapping):
        return ()
    flattened: list[object] = []
    for value in risk.values():
        flattened.extend(_object_sequence(value))
    return tuple(flattened)


__all__ = [
    "BLAST_ARTIFACT_DETAIL_CONTRACT_VERSION",
    "DEFAULT_BLAST_RADIUS_INCLUDE",
    "DEFAULT_DO_NOT_TOUCH_PATTERNS",
    "MAX_CONTEXT_ITEMS",
    "VALID_BLAST_RADIUS_DEPTHS",
    "VALID_BLAST_RADIUS_INCLUDE",
    "BlastRadiusDepth",
    "BlastRadiusInclude",
    "BlastRadiusResult",
    "blast_artifact_reference",
    "blast_radius_artifact_payload",
    "blast_radius_summary_payload",
    "blast_radius_to_payload",
    "compute_blast_radius",
]
