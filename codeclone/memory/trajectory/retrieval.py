# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from ..paths import normalize_memory_scope_path, repo_path_to_module_key
from ..search_index import SearchMatchMode, tokenize_query
from .agents import trajectory_agent_label
from .models import Trajectory, TrajectoryListItem
from .patch_trail import patch_trail_from_mapping, patch_trail_summary_line
from .quality import (
    compute_trajectory_quality_contract,
    serialize_trajectory_quality_contract,
)
from .step_labels import step_display_name

DEFAULT_TRAJECTORY_PREVIEW_LIMIT = 5
DEFAULT_TRAJECTORY_STEP_LIMIT = 12
COMPACT_TRAJECTORY_SUBJECT_LIMIT = 8
TRAJECTORY_PREVIEW_CHARS = 220
TrajectoryDetailLevel = Literal["compact", "full"]


def trajectory_excluded_from_default_retrieval(
    trajectory: Trajectory,
    *,
    include_routine: bool,
) -> bool:
    if include_routine:
        return False
    if trajectory.workflow_id.startswith("run:"):
        return True
    return trajectory.quality_tier == "routine"


def filter_trajectories_for_default_retrieval(
    trajectories: Sequence[Trajectory],
    *,
    include_routine: bool,
) -> tuple[Trajectory, ...]:
    return tuple(
        trajectory
        for trajectory in trajectories
        if not trajectory_excluded_from_default_retrieval(
            trajectory,
            include_routine=include_routine,
        )
    )


@dataclass(frozen=True, slots=True)
class TrajectorySearchResult:
    trajectory: Trajectory
    relevance_score: float


def trajectory_status_payload(
    *,
    count: int,
    latest_run: object | None,
) -> dict[str, object]:
    payload: dict[str, object] = {"trajectory_count": count}
    if latest_run is not None:
        payload["latest_projection"] = {
            "id": getattr(latest_run, "id", ""),
            "projection_version": getattr(latest_run, "projection_version", ""),
            "finished_at_utc": getattr(latest_run, "finished_at_utc", ""),
            "status": getattr(latest_run, "status", ""),
            "workflows_seen": getattr(latest_run, "workflows_seen", 0),
            "created": getattr(latest_run, "trajectories_created", 0),
            "updated": getattr(latest_run, "trajectories_updated", 0),
            "unchanged": getattr(latest_run, "trajectories_unchanged", 0),
            "legacy_event_count": getattr(latest_run, "legacy_event_count", 0),
        }
    else:
        payload["latest_projection"] = None
    return payload


def trajectory_list_item_to_preview(item: TrajectoryListItem) -> dict[str, object]:
    return {
        "type": "trajectory",
        "trajectory_id": item.id,
        "workflow_id": item.workflow_id,
        "outcome": item.outcome,
        "quality_tier": item.quality_tier,
        "quality_score": item.quality_score,
        "summary": _preview_text(item.summary),
        "event_count": item.event_count,
        "started_at_utc": item.started_at_utc,
        "finished_at_utc": item.finished_at_utc,
    }


def serialize_trajectory_preview(
    trajectory: Trajectory,
    *,
    relevance_score: float | None = None,
    patch_trail_payload: Mapping[str, object] | None = None,
    detail_level: TrajectoryDetailLevel = "full",
    preferred_subjects: frozenset[tuple[str, str]] = frozenset(),
) -> dict[str, object]:
    subjects = trajectory.subjects
    serialized_subjects, matched_subject_count = _preview_subjects(
        subjects,
        detail_level=detail_level,
        preferred_subjects=preferred_subjects,
    )
    payload: dict[str, object] = {
        "type": "trajectory",
        "trajectory_id": trajectory.id,
        "workflow_id": trajectory.workflow_id,
        "outcome": trajectory.outcome,
        "quality_tier": trajectory.quality_tier,
        "quality_score": trajectory.quality_score,
        "summary": _preview_text(trajectory.summary),
        "labels": list(trajectory.labels),
        "agent_label": trajectory_agent_label(trajectory),
        "subjects": serialized_subjects,
        "evidence_count": len(trajectory.evidence),
        "event_count": trajectory.event_count,
        "step_count": trajectory.step_count,
        "incident_count": trajectory.incident_count,
        "started_at_utc": trajectory.started_at_utc,
        "finished_at_utc": trajectory.finished_at_utc,
    }
    if relevance_score is not None:
        payload["relevance_score"] = round(relevance_score, 3)
    summary = serialize_patch_trail_summary(patch_trail_payload)
    if summary is not None:
        payload["patch_trail_summary"] = summary
    _add_quality_fields(
        payload,
        trajectory=trajectory,
        patch_trail_payload=patch_trail_payload,
        detail_level=detail_level,
        subject_count=len(subjects),
        matched_subject_count=matched_subject_count,
        serialized_subject_count=len(serialized_subjects),
    )
    return payload


def _preview_subjects(
    subjects: Sequence[object],
    *,
    detail_level: TrajectoryDetailLevel,
    preferred_subjects: frozenset[tuple[str, str]],
) -> tuple[list[dict[str, object]], int]:
    matched_subject_count = sum(
        (
            str(getattr(subject, "subject_kind", "")),
            str(getattr(subject, "subject_key", "")),
        )
        in preferred_subjects
        for subject in subjects
    )
    selected = (
        _compact_trajectory_subjects(
            subjects,
            preferred_subjects=preferred_subjects,
        )
        if detail_level == "compact"
        else tuple(subjects)
    )
    return [_serialize_subject(subject) for subject in selected], matched_subject_count


def _add_quality_fields(
    payload: dict[str, object],
    *,
    trajectory: Trajectory,
    patch_trail_payload: Mapping[str, object] | None,
    detail_level: TrajectoryDetailLevel,
    subject_count: int,
    matched_subject_count: int,
    serialized_subject_count: int,
) -> None:
    contract = compute_trajectory_quality_contract(
        trajectory,
        patch_trail_payload=patch_trail_payload,
    )
    if detail_level == "full":
        payload["quality_contract"] = serialize_trajectory_quality_contract(
            contract,
            trajectory=trajectory,
            patch_trail_payload=patch_trail_payload,
        )
    else:
        payload["subject_count"] = subject_count
        payload["matched_subject_count"] = matched_subject_count
        payload["subjects_truncated"] = serialized_subject_count < subject_count
    payload["complexity_score"] = contract.complexity_score
    payload["scope_accuracy"] = contract.scope_accuracy
    payload["duration_seconds"] = contract.duration_seconds
    payload["anomaly_count"] = contract.anomaly_count


def serialize_patch_trail_summary(
    payload: Mapping[str, object] | None,
) -> dict[str, object] | None:
    if payload is None:
        return None
    trail = patch_trail_from_mapping(payload)
    if trail is None:
        return None
    summary_payload = trail.to_payload(detail_level="summary")
    return {
        "summary_line": patch_trail_summary_line(trail),
        "patch_trail_digest": trail.patch_trail_digest,
        "counts": summary_payload.get("counts", {}),
        "scope_check_status": trail.scope_check_status,
        "verification_status": trail.verification_status,
    }


def serialize_trajectory_detail(
    trajectory: Trajectory,
    *,
    max_steps: int = DEFAULT_TRAJECTORY_STEP_LIMIT,
    patch_trail_payload: Mapping[str, object] | None = None,
) -> dict[str, object]:
    steps = trajectory.steps[: max(1, int(max_steps))]
    detail = {
        **serialize_trajectory_preview(
            trajectory,
            patch_trail_payload=patch_trail_payload,
        ),
        "trajectory_digest": trajectory.trajectory_digest,
        "source_event_stream_digest": trajectory.source_event_stream_digest,
        "projection_version": trajectory.projection_version,
        "intent_id": trajectory.intent_id,
        "primary_run_id": trajectory.primary_run_id,
        "first_run_id": trajectory.first_run_id,
        "last_run_id": trajectory.last_run_id,
        "report_digest": trajectory.report_digest,
        "steps": [
            {
                "step_index": step.step_index,
                "audit_sequence": step.audit_sequence,
                "event_id": step.event_id,
                "event_type": step.event_type,
                "step_label": step_display_name(
                    event_type=step.event_type,
                    status=step.status,
                ),
                "status": step.status,
                "run_id": step.run_id,
                "report_digest": step.report_digest,
                "summary": _preview_text(step.summary or ""),
                "created_at_utc": step.created_at_utc,
            }
            for step in steps
        ],
        "steps_truncated": len(trajectory.steps) > len(steps),
        "evidence": [
            {
                "evidence_kind": item.evidence_kind,
                "ref": item.ref,
                "locator": item.locator,
                "digest": item.digest,
                "created_at_utc": item.created_at_utc,
            }
            for item in trajectory.evidence
        ],
    }
    if patch_trail_payload is not None:
        trail = patch_trail_from_mapping(patch_trail_payload)
        if trail is not None:
            detail["patch_trail"] = trail.to_payload(detail_level="summary")
    return detail


def rank_trajectories_for_scope(
    trajectories: Sequence[Trajectory],
    *,
    scope_paths: Sequence[str],
    symbols: Sequence[str],
    max_results: int = DEFAULT_TRAJECTORY_PREVIEW_LIMIT,
    include_routine: bool = False,
    patch_trails: Mapping[str, Mapping[str, object]] | None = None,
    detail_level: TrajectoryDetailLevel = "full",
) -> tuple[list[dict[str, object]], bool]:
    normalized_scope = tuple(normalize_memory_scope_path(path) for path in scope_paths)
    preferred_subjects = _preferred_subjects(
        scope_paths=normalized_scope,
        symbols=symbols,
    )
    visible = filter_trajectories_for_default_retrieval(
        trajectories,
        include_routine=include_routine,
    )
    scored = _score_trajectories(
        visible,
        scope_paths=normalized_scope,
        symbols=symbols,
        query_tokens=(),
        patch_trails=patch_trails or {},
    )
    return _preview_results(
        scored,
        max_results=max_results,
        patch_trails=patch_trails or {},
        detail_level=detail_level,
        preferred_subjects=preferred_subjects,
        diversify=True,
    )


def rank_trajectories_for_query(
    trajectories: Sequence[Trajectory],
    *,
    query: str,
    max_results: int,
    match_mode: SearchMatchMode,
    include_routine: bool = False,
    detail_level: TrajectoryDetailLevel = "full",
) -> tuple[list[dict[str, object]], bool]:
    tokens = tokenize_query(query)
    if not tokens:
        return [], False
    visible = filter_trajectories_for_default_retrieval(
        trajectories,
        include_routine=include_routine,
    )
    scored = _score_trajectories(
        visible,
        scope_paths=(),
        symbols=(),
        query_tokens=tokens,
        match_mode=match_mode,
    )
    return _preview_results(
        scored,
        max_results=max_results,
        detail_level=detail_level,
    )


def filter_trajectories_for_query(
    trajectories: Sequence[Trajectory],
    *,
    query: str,
    match_mode: SearchMatchMode,
    include_routine: bool = False,
) -> tuple[TrajectorySearchResult, ...]:
    tokens = tokenize_query(query)
    if not tokens:
        return ()
    visible = filter_trajectories_for_default_retrieval(
        trajectories,
        include_routine=include_routine,
    )
    return tuple(
        _score_trajectories(
            visible,
            scope_paths=(),
            symbols=(),
            query_tokens=tokens,
            match_mode=match_mode,
        )
    )


def trajectory_subject_keys(
    *,
    scope_paths: Sequence[str],
    symbols: Sequence[str],
) -> dict[str, tuple[str, ...]]:
    paths = tuple(normalize_memory_scope_path(path) for path in scope_paths)
    modules = tuple(sorted({repo_path_to_module_key(path) for path in paths}))
    return {
        "path": paths,
        "module": modules,
        "symbol": tuple(sorted({symbol for symbol in symbols if symbol.strip()})),
    }


def _score_trajectories(
    trajectories: Sequence[Trajectory],
    *,
    scope_paths: Sequence[str],
    symbols: Sequence[str],
    query_tokens: Sequence[str],
    match_mode: SearchMatchMode = "any",
    patch_trails: Mapping[str, Mapping[str, object]] | None = None,
) -> list[TrajectorySearchResult]:
    trails = patch_trails or {}
    scored: list[TrajectorySearchResult] = []
    for trajectory in trajectories:
        score = _trajectory_relevance(
            trajectory,
            scope_paths=scope_paths,
            symbols=symbols,
            query_tokens=query_tokens,
            match_mode=match_mode,
            patch_trail_payload=trails.get(trajectory.id),
        )
        if score <= 0.0:
            continue
        scored.append(
            TrajectorySearchResult(
                trajectory=trajectory,
                relevance_score=score,
            )
        )
    scored.sort(key=lambda item: (-item.relevance_score, item.trajectory.id))
    return scored


def _trajectory_relevance(
    trajectory: Trajectory,
    *,
    scope_paths: Sequence[str],
    symbols: Sequence[str],
    query_tokens: Sequence[str],
    match_mode: SearchMatchMode,
    patch_trail_payload: Mapping[str, object] | None = None,
) -> float:
    score = 0.0
    subjects = {
        (item.subject_kind, item.subject_key, item.relation)
        for item in trajectory.subjects
    }
    subject_pairs = {(kind, key) for kind, key, _relation in subjects}
    for path in scope_paths:
        if ("path", path) in subject_pairs:
            score += 1.4
        if ("path", path, "untouched") in subjects:
            score += 0.45
        module_key = repo_path_to_module_key(path)
        if ("module", module_key) in subject_pairs:
            score += 0.8
    untouched_overlap = _patch_trail_untouched_overlap(
        scope_paths=scope_paths,
        patch_trail_payload=patch_trail_payload,
        subjects=subjects,
    )
    if untouched_overlap:
        score += 0.25 * untouched_overlap
    for symbol in symbols:
        if ("symbol", symbol) in subject_pairs:
            score += 1.2
    if query_tokens:
        haystack = _trajectory_search_text(trajectory)
        matches = [token in haystack for token in query_tokens]
        if match_mode == "all" and not all(matches):
            return 0.0
        if match_mode == "any" and not any(matches):
            return 0.0
        score += 0.4 + sum(0.15 for matched in matches if matched)
    if trajectory.quality_tier in {"corrected", "incident"}:
        score += 0.15
    return score


def _preview_results(
    results: Sequence[TrajectorySearchResult],
    *,
    max_results: int,
    patch_trails: Mapping[str, Mapping[str, object]] | None = None,
    detail_level: TrajectoryDetailLevel = "full",
    preferred_subjects: frozenset[tuple[str, str]] = frozenset(),
    diversify: bool = False,
) -> tuple[list[dict[str, object]], bool]:
    limit = max(1, int(max_results))
    truncated = len(results) > limit
    selected = (
        _select_diverse_scope_results(results, limit=limit)
        if diversify
        else results[:limit]
    )
    trails = patch_trails or {}
    return [
        serialize_trajectory_preview(
            item.trajectory,
            relevance_score=item.relevance_score,
            patch_trail_payload=trails.get(item.trajectory.id),
            detail_level=detail_level,
            preferred_subjects=preferred_subjects,
        )
        for item in selected
    ], truncated


def _select_diverse_scope_results(
    results: Sequence[TrajectorySearchResult],
    *,
    limit: int,
) -> Sequence[TrajectorySearchResult]:
    selected: list[TrajectorySearchResult] = []
    selected_ids: set[str] = set()
    seen_examples: set[tuple[str, str, str]] = set()
    for item in results:
        trajectory = item.trajectory
        example_key = (
            trajectory.outcome,
            trajectory.quality_tier,
            trajectory_agent_label(trajectory) or "",
        )
        if example_key not in seen_examples:
            selected.append(item)
            selected_ids.add(trajectory.id)
            seen_examples.add(example_key)
            if len(selected) >= limit:
                return selected
    for item in results:
        if item.trajectory.id not in selected_ids:
            selected.append(item)
            if len(selected) >= limit:
                break
    return selected


def _preferred_subjects(
    *,
    scope_paths: Sequence[str],
    symbols: Sequence[str],
) -> frozenset[tuple[str, str]]:
    subject_keys = trajectory_subject_keys(
        scope_paths=scope_paths,
        symbols=symbols,
    )
    return frozenset((kind, key) for kind, keys in subject_keys.items() for key in keys)


def _compact_trajectory_subjects(
    subjects: Sequence[object],
    *,
    preferred_subjects: frozenset[tuple[str, str]],
) -> tuple[object, ...]:
    indexed = tuple(enumerate(subjects))
    ranked = sorted(
        indexed,
        key=lambda item: _compact_subject_sort_key(
            item[1],
            index=item[0],
            preferred_subjects=preferred_subjects,
        ),
    )
    return tuple(
        subject for _index, subject in ranked[:COMPACT_TRAJECTORY_SUBJECT_LIMIT]
    )


def _compact_subject_sort_key(
    subject: object,
    *,
    index: int,
    preferred_subjects: frozenset[tuple[str, str]],
) -> tuple[int, int, int, int]:
    kind = str(getattr(subject, "subject_kind", ""))
    key = str(getattr(subject, "subject_key", ""))
    relation = str(getattr(subject, "relation", ""))
    return (
        0 if (kind, key) in preferred_subjects else 1,
        {"touched": 0, "untouched": 1, "about": 2}.get(relation, 3),
        {"path": 0, "symbol": 1, "module": 2}.get(kind, 3),
        index,
    )


def _patch_trail_untouched_overlap(
    *,
    scope_paths: Sequence[str],
    patch_trail_payload: Mapping[str, object] | None,
    subjects: set[tuple[str, str, str]],
) -> int:
    scope = set(scope_paths)
    if patch_trail_payload is not None:
        trail = patch_trail_from_mapping(patch_trail_payload)
        if trail is not None:
            return len(scope & set(trail.untouched_in_declared))
    untouched = {
        key
        for kind, key, relation in subjects
        if kind == "path" and relation == "untouched"
    }
    return len(scope & untouched)


def _trajectory_search_text(trajectory: Trajectory) -> str:
    parts: list[str] = [
        trajectory.id,
        trajectory.workflow_id,
        trajectory.outcome,
        trajectory.quality_tier,
        trajectory.summary,
        *trajectory.labels,
    ]
    parts.extend(subject.subject_key for subject in trajectory.subjects)
    parts.extend(step.event_type for step in trajectory.steps)
    parts.extend(step.summary or "" for step in trajectory.steps)
    return " ".join(part.lower() for part in parts if part)


def _serialize_subject(subject: object) -> dict[str, object]:
    return {
        "subject_kind": getattr(subject, "subject_kind", ""),
        "subject_key": getattr(subject, "subject_key", ""),
        "relation": getattr(subject, "relation", ""),
    }


def _preview_text(text: str, *, max_chars: int = TRAJECTORY_PREVIEW_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 1].rstrip()}…"


def compact_step_text(trajectory: Trajectory, *, max_steps: int = 12) -> str:
    step_parts = []
    for step in trajectory.steps[: max(1, int(max_steps))]:
        summary = f" {step.summary}" if step.summary else ""
        status = f" status={step.status}" if step.status else ""
        step_parts.append(f"{step.step_index + 1}:{step.event_type}{status}{summary}")
    return " ; ".join(step_parts)


def trajectory_semantic_text_parts(trajectory: Trajectory) -> Iterable[str]:
    yield "trajectory"
    yield f"outcome {trajectory.outcome}"
    yield f"quality {trajectory.quality_tier}"
    yield trajectory.summary
    if trajectory.labels:
        yield f"labels {' '.join(trajectory.labels)}"
    path_subjects = [
        subject.subject_key
        for subject in trajectory.subjects
        if subject.subject_kind == "path"
    ]
    if path_subjects:
        yield f"paths {' '.join(sorted(path_subjects))}"
    steps = compact_step_text(trajectory)
    if steps:
        yield f"steps {steps}"


__all__ = [
    "COMPACT_TRAJECTORY_SUBJECT_LIMIT",
    "DEFAULT_TRAJECTORY_PREVIEW_LIMIT",
    "DEFAULT_TRAJECTORY_STEP_LIMIT",
    "TrajectorySearchResult",
    "compact_step_text",
    "filter_trajectories_for_default_retrieval",
    "filter_trajectories_for_query",
    "rank_trajectories_for_query",
    "rank_trajectories_for_scope",
    "serialize_patch_trail_summary",
    "serialize_trajectory_detail",
    "serialize_trajectory_preview",
    "trajectory_excluded_from_default_retrieval",
    "trajectory_list_item_to_preview",
    "trajectory_semantic_text_parts",
    "trajectory_status_payload",
    "trajectory_subject_keys",
]
