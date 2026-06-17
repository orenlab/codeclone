# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import re
import sqlite3
from collections.abc import Mapping, Sequence

import orjson

from ..models import MemoryProject
from ..paths import normalize_memory_scope_path
from .models import Trajectory
from .patch_trail import patch_trail_from_mapping
from .profiles import TrajectoryExportProfile, trajectory_eligible_for_export
from .retrieval import compact_step_text, serialize_patch_trail_summary

_REDACT_HOME = re.compile(r"(?i)(/Users/[^/\s]+|/home/[^/\s]+)")

MAX_MEMORY_PRECEDENTS = 8
MAX_TRAJECTORY_PRECEDENTS = 5
MAX_CITATIONS = 32
MAX_OVERLAP_PATHS = 12
MAX_STATEMENT_PREVIEW = 220

_PROJECTION_VERSION_PREFIX = "trajectory-v"


def projection_version_rank(version: str) -> int:
    """Rank trajectory projection versions by numeric suffix so newer
    projections supersede older ones; unknown formats rank 0."""
    if version.startswith(_PROJECTION_VERSION_PREFIX):
        suffix = version[len(_PROJECTION_VERSION_PREFIX) :]
        if suffix.isdigit():
            return int(suffix)
    return 0


def select_canonical_trajectories(
    trajectories: Sequence[Trajectory],
) -> list[Trajectory]:
    best: dict[str, Trajectory] = {}
    for trajectory in trajectories:
        current = best.get(trajectory.workflow_id)
        if current is None or _prefer_trajectory_projection(trajectory, current):
            best[trajectory.workflow_id] = trajectory
    return sorted(best.values(), key=lambda item: (item.finished_at_utc, item.id))


def build_export_context(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    trajectory: Trajectory,
    scope_paths: Sequence[str],
    patch_trail_payload: Mapping[str, object] | None,
    canonical_by_workflow: Mapping[str, Trajectory],
) -> dict[str, object]:
    effective_scope = _effective_scope_paths(
        trajectory,
        scope_paths=scope_paths,
        patch_trail_payload=patch_trail_payload,
    )
    memory_precedents = _memory_precedents(
        conn,
        project_id=project_id,
        trajectory=trajectory,
        scope_paths=effective_scope,
    )
    trajectory_precedents = _trajectory_precedents(
        trajectory=trajectory,
        scope_paths=effective_scope,
        canonical_by_workflow=canonical_by_workflow,
    )
    citations = extract_trajectory_citations(trajectory)
    context: dict[str, object] = {
        "memory_precedents": memory_precedents,
        "trajectory_precedents": trajectory_precedents,
    }
    payload: dict[str, object] = {
        "context": context,
        "citations": citations,
    }
    summary = serialize_patch_trail_summary(patch_trail_payload)
    if summary is not None:
        payload["patch_trail_summary"] = summary
    return payload


def build_export_record(
    *,
    trajectory: Trajectory,
    profile: TrajectoryExportProfile,
    project: MemoryProject,
    include_payloads: bool,
    enrichment: Mapping[str, object],
    scope_paths: Sequence[str],
) -> dict[str, object]:
    context = enrichment.get("context")
    if not isinstance(context, dict):
        context = {"memory_precedents": [], "trajectory_precedents": []}
    citations = enrichment.get("citations")
    if not isinstance(citations, list):
        citations = []
    record: dict[str, object] = {
        "schema_version": profile.schema_version,
        "profile": profile.name,
        "trajectory_id": trajectory.id,
        "project_fingerprint": project.id,
        "projection_version": trajectory.projection_version,
        "task": {
            "intent_summary": _redact_text(trajectory.summary),
            "scope": {
                "paths": [_redact_text(path) for path in scope_paths],
            },
        },
        "context": context,
        "actions": [
            {
                "type": _redact_text(step.event_type),
                "result": _redact_text(step.status or ""),
                "summary": _redact_text(step.summary or ""),
            }
            for step in trajectory.steps[:12]
        ],
        "outcome": {
            "label": trajectory.outcome,
            "quality_tier": trajectory.quality_tier,
        },
        "lessons": list(trajectory.labels),
        "citations": citations,
        "digests": {
            "trajectory_digest": f"sha256:{trajectory.trajectory_digest}",
            "source_event_stream_digest": (
                f"sha256:{trajectory.source_event_stream_digest}"
            ),
        },
    }
    patch_trail_summary = enrichment.get("patch_trail_summary")
    if isinstance(patch_trail_summary, dict):
        record["patch_trail_summary"] = patch_trail_summary
    if include_payloads:
        record["steps"] = compact_step_text(trajectory)
    return record


def extract_trajectory_citations(trajectory: Trajectory) -> list[dict[str, object]]:
    citations: list[dict[str, object]] = []
    seen: set[tuple[str, str, int]] = set()
    for step in trajectory.steps:
        facts = _event_core_facts(step.event_core_json)
        if facts is not None:
            for item in _citation_items_from_facts(facts):
                _append_trajectory_citation(
                    citations,
                    seen,
                    kind=str(item.get("kind", "")).strip(),
                    cited_id=str(item.get("cited_id", "")).strip(),
                    valid=bool(item.get("valid", True)),
                    source_event_type=step.event_type,
                    audit_sequence=step.audit_sequence,
                    dedupe_sequence=step.audit_sequence,
                )
    for subject in trajectory.subjects:
        if subject.subject_kind == "report_digest":
            _append_trajectory_citation(
                citations,
                seen,
                kind="report_digest",
                cited_id=subject.subject_key,
                valid=True,
                source_event_type="trajectory.subject",
                audit_sequence=None,
                dedupe_sequence=0,
            )
    citations.sort(
        key=lambda item: (
            item["audit_sequence"] is None,
            item["audit_sequence"] or 0,
            str(item["kind"]),
            str(item["cited_id"]),
        )
    )
    return citations[:MAX_CITATIONS]


def _event_core_facts(event_core_json: str) -> Mapping[str, object] | None:
    core = _load_event_core(event_core_json)
    facts = core.get("facts")
    return facts if isinstance(facts, Mapping) else None


def _citation_items_from_facts(
    facts: Mapping[str, object],
) -> list[Mapping[str, object]]:
    raw_citations = facts.get("citations")
    if not isinstance(raw_citations, list):
        return []
    return [item for item in raw_citations if isinstance(item, Mapping)]


def _append_trajectory_citation(
    citations: list[dict[str, object]],
    seen: set[tuple[str, str, int]],
    *,
    kind: str,
    cited_id: str,
    valid: bool,
    source_event_type: str,
    audit_sequence: int | None,
    dedupe_sequence: int,
) -> None:
    if not kind or not cited_id:
        return
    key = (kind, cited_id, dedupe_sequence)
    if key in seen:
        return
    seen.add(key)
    citations.append(
        {
            "kind": kind,
            "cited_id": cited_id,
            "valid": valid,
            "source_event_type": source_event_type,
            "audit_sequence": audit_sequence,
        }
    )


def trajectory_path_subjects(
    trajectory: Trajectory,
    *,
    relations: set[str],
) -> tuple[str, ...]:
    paths = [
        subject.subject_key
        for subject in trajectory.subjects
        if subject.subject_kind == "path" and subject.relation in relations
    ]
    return tuple(sorted(set(paths)))


def resolve_export_scope_paths(
    trajectory: Trajectory,
    *,
    patch_trail_payload: Mapping[str, object] | None,
) -> tuple[str, ...]:
    scope_paths = trajectory_path_subjects(trajectory, relations={"about", "touched"})
    return _effective_scope_paths(
        trajectory,
        scope_paths=scope_paths,
        patch_trail_payload=patch_trail_payload,
    )


def _effective_scope_paths(
    trajectory: Trajectory,
    *,
    scope_paths: Sequence[str],
    patch_trail_payload: Mapping[str, object] | None,
) -> tuple[str, ...]:
    if scope_paths:
        return tuple(sorted(set(scope_paths)))
    trail = patch_trail_from_mapping(patch_trail_payload or {})
    if trail is None:
        return ()
    merged = [*trail.declared_files, *trail.changed_files]
    return tuple(sorted(set(merged)))


def _memory_precedents(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    trajectory: Trajectory,
    scope_paths: Sequence[str],
) -> list[dict[str, object]]:
    precedents: list[dict[str, object]] = []
    seen: set[str] = set()

    linked_rows = conn.execute(
        """
        SELECT m.id, m.type, m.status, m.statement, e.evidence_kind
        FROM memory_evidence e
        JOIN memory_records m ON m.id = e.memory_id
        WHERE m.project_id = ?
          AND e.evidence_kind = 'trajectory'
          AND e.ref = ?
        ORDER BY m.updated_at_utc DESC, m.id ASC
        LIMIT ?
        """,
        (project_id, trajectory.id, MAX_MEMORY_PRECEDENTS),
    ).fetchall()
    for row in linked_rows:
        _append_memory_precedent(
            precedents,
            seen=seen,
            row=row,
            link_kind="trajectory_evidence",
            overlap_paths=(),
        )

    normalized_scope = [
        path
        for path in (normalize_memory_scope_path(item) for item in scope_paths)
        if path
    ]
    if not normalized_scope or len(precedents) >= MAX_MEMORY_PRECEDENTS:
        return precedents

    placeholders = ", ".join("?" for _ in normalized_scope)
    path_rows = conn.execute(
        f"""
        SELECT DISTINCT m.id, m.type, m.status, m.statement, s.subject_key
        FROM memory_records m
        JOIN memory_subjects s ON s.memory_id = m.id
        WHERE m.project_id = ?
          AND m.status = 'active'
          AND s.subject_kind = 'path'
          AND s.subject_key IN ({placeholders})
        ORDER BY m.updated_at_utc DESC, m.id ASC
        LIMIT ?
        """,
        (project_id, *normalized_scope, MAX_MEMORY_PRECEDENTS),
    ).fetchall()
    overlap_by_memory: dict[str, list[str]] = {}
    for row in path_rows:
        memory_id = str(row["id"])
        overlap_by_memory.setdefault(memory_id, []).append(str(row["subject_key"]))
    for memory_id in sorted(overlap_by_memory):
        if len(precedents) >= MAX_MEMORY_PRECEDENTS:
            break
        row = conn.execute(
            "SELECT id, type, status, statement FROM memory_records WHERE id=?",
            (memory_id,),
        ).fetchone()
        if row is None:
            continue
        overlap = tuple(sorted(set(overlap_by_memory[memory_id])))[:MAX_OVERLAP_PATHS]
        _append_memory_precedent(
            precedents,
            seen=seen,
            row=row,
            link_kind="path_overlap",
            overlap_paths=overlap,
        )
    return precedents


def _append_memory_precedent(
    precedents: list[dict[str, object]],
    *,
    seen: set[str],
    row: sqlite3.Row,
    link_kind: str,
    overlap_paths: Sequence[str],
) -> None:
    memory_id = str(row["id"])
    if memory_id in seen:
        return
    seen.add(memory_id)
    precedents.append(
        _memory_precedent_row(
            row,
            link_kind=link_kind,
            overlap_paths=overlap_paths,
        )
    )


def _trajectory_precedents(
    *,
    trajectory: Trajectory,
    scope_paths: Sequence[str],
    canonical_by_workflow: Mapping[str, Trajectory],
) -> list[dict[str, object]]:
    if not scope_paths:
        return []
    scope_set = set(scope_paths)
    candidates: list[tuple[str, str, Trajectory, tuple[str, ...]]] = []
    for candidate in canonical_by_workflow.values():
        match = _trajectory_precedent_match(
            candidate,
            trajectory=trajectory,
            scope_set=scope_set,
        )
        if match is not None:
            candidates.append(match)
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    precedents: list[dict[str, object]] = []
    for _finished, _trajectory_id, candidate, overlap in candidates[
        :MAX_TRAJECTORY_PRECEDENTS
    ]:
        precedents.append(
            {
                "trajectory_id": candidate.id,
                "workflow_id": candidate.workflow_id,
                "outcome": candidate.outcome,
                "quality_tier": candidate.quality_tier,
                "finished_at_utc": candidate.finished_at_utc,
                "overlap_paths": list(overlap),
                "summary": _preview_text(candidate.summary),
            }
        )
    return precedents


def _trajectory_precedent_match(
    candidate: Trajectory,
    *,
    trajectory: Trajectory,
    scope_set: set[str],
) -> tuple[str, str, Trajectory, tuple[str, ...]] | None:
    if (
        candidate.id == trajectory.id
        or candidate.workflow_id == trajectory.workflow_id
        or candidate.finished_at_utc >= trajectory.started_at_utc
    ):
        return None
    candidate_paths = set(
        trajectory_path_subjects(candidate, relations={"about", "touched", "untouched"})
    )
    overlap = tuple(sorted(scope_set & candidate_paths))[:MAX_OVERLAP_PATHS]
    if not overlap:
        return None
    return (candidate.finished_at_utc, candidate.id, candidate, overlap)


def _memory_precedent_row(
    row: sqlite3.Row,
    *,
    link_kind: str,
    overlap_paths: Sequence[str],
) -> dict[str, object]:
    payload: dict[str, object] = {
        "memory_id": str(row["id"]),
        "record_type": str(row["type"]),
        "status": str(row["status"]),
        "statement_preview": _preview_text(str(row["statement"])),
        "link_kind": link_kind,
    }
    if overlap_paths:
        payload["overlap_paths"] = list(overlap_paths)
    return payload


def _prefer_trajectory_projection(
    candidate: Trajectory,
    incumbent: Trajectory,
) -> bool:
    candidate_rank = projection_version_rank(candidate.projection_version)
    incumbent_rank = projection_version_rank(incumbent.projection_version)
    if candidate_rank != incumbent_rank:
        return candidate_rank > incumbent_rank
    if candidate.finished_at_utc != incumbent.finished_at_utc:
        return candidate.finished_at_utc > incumbent.finished_at_utc
    return candidate.id > incumbent.id


def _load_event_core(event_core_json: str) -> Mapping[str, object]:
    try:
        loaded = orjson.loads(event_core_json)
    except orjson.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, Mapping) else {}


def _preview_text(value: str) -> str:
    text = value.strip()
    if len(text) <= MAX_STATEMENT_PREVIEW:
        return text
    return text[: MAX_STATEMENT_PREVIEW - 3] + "..."


def _redact_text(value: str) -> str:
    return _REDACT_HOME.sub("~", value)


def trajectory_index_for_export(
    trajectories: Sequence[Trajectory],
    *,
    profile: TrajectoryExportProfile,
) -> dict[str, Trajectory]:
    canonical = select_canonical_trajectories(trajectories)
    eligible = [
        trajectory
        for trajectory in canonical
        if trajectory_eligible_for_export(trajectory, profile=profile)
    ]
    return {trajectory.workflow_id: trajectory for trajectory in eligible}


__all__ = [
    "build_export_context",
    "build_export_record",
    "extract_trajectory_citations",
    "projection_version_rank",
    "resolve_export_scope_paths",
    "select_canonical_trajectories",
    "trajectory_index_for_export",
    "trajectory_path_subjects",
]
