# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Literal, cast

from ...config.memory_defaults import DEFAULT_MEMORY_STATEMENT_PREVIEW_CHARS
from ...contracts import SEMANTIC_INDEX_FORMAT_VERSION
from ...observability import is_observability_enabled, record_counter, span
from ..embedding import embed_query
from ..enums import LinkRelation, MemoryConfidence, MemoryRecordType, MemoryStatus
from ..exceptions import MemoryContractError, MemorySemanticUnavailableError
from ..experience.models import Experience
from ..models import MemoryEvidence, MemoryQuery, MemoryRecord, MemorySubject
from ..paths import (
    MEMORY_RETRIEVAL_SCOPE_REQUIRED_ERROR,
    normalize_memory_scope_path,
    normalize_memory_scope_paths,
    normalize_repo_path,
    repo_path_to_module_key,
    subject_matches_scope,
)
from ..search_index import SearchMatchMode
from ..sqlite_store import SqliteEngineeringMemoryStore
from ..status_report import build_memory_status_report
from ..trajectory.analytics import (
    build_trajectory_agent_stats_payload,
    build_trajectory_anomalies_payload,
    build_trajectory_dashboard_payload,
)
from ..trajectory.retrieval import (
    DEFAULT_TRAJECTORY_PREVIEW_LIMIT,
    filter_trajectories_for_default_retrieval,
    rank_trajectories_for_query,
    rank_trajectories_for_scope,
    serialize_trajectory_detail,
    serialize_trajectory_preview,
    trajectory_status_payload,
    trajectory_subject_keys,
)
from .context_coverage import build_context_coverage
from .ranking import (
    RankingContext,
    reciprocal_rank_fusion,
    relevance_score,
    retrieval_lane,
)
from .semantic import audit_event_row

if TYPE_CHECKING:
    from pathlib import Path

    from ..embedding import EmbeddingProvider
    from ..semantic import SemanticIndex
    from ..semantic.models import SemanticHit, SemanticIndexStatus

QueryMode = Literal[
    "search",
    "get",
    "for_path",
    "for_symbol",
    "stale",
    "drafts",
    "coverage",
    "status",
    "trajectory_status",
    "trajectory_search",
    "trajectory_get",
    "trajectory_anomalies",
    "trajectory_agents",
    "trajectory_dashboard",
]

QUERY_MODES: tuple[str, ...] = (
    "search",
    "get",
    "for_path",
    "for_symbol",
    "stale",
    "drafts",
    "coverage",
    "status",
    "trajectory_status",
    "trajectory_search",
    "trajectory_get",
    "trajectory_anomalies",
    "trajectory_agents",
    "trajectory_dashboard",
)

MemoryDetailLevel = Literal["compact", "full"]


def _normalize_detail_level(detail_level: str) -> MemoryDetailLevel:
    if detail_level == "full":
        return "full"
    if detail_level in {"compact", "summary", "normal"}:
        return "compact"
    raise MemoryContractError("detail_level must be compact, summary, normal, or full.")


def _statement_preview(
    statement: str,
    *,
    max_chars: int = DEFAULT_MEMORY_STATEMENT_PREVIEW_CHARS,
) -> str:
    if len(statement) <= max_chars:
        return statement
    trimmed = statement[: max_chars - 1].rstrip()
    return f"{trimmed}…"


def query_records_for_repo_path(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    rel_path: str,
    limit: int,
    types: tuple[MemoryRecordType, ...] = (),
    statuses: tuple[MemoryStatus, ...] = ("active", "historical", "stale"),
) -> tuple[MemoryRecord, ...]:
    normalized = normalize_repo_path(rel_path)
    records = store.query_records(
        MemoryQuery(
            project_id=project_id,
            types=types,
            statuses=statuses,
            subject_kind="path",
            subject_key_prefix=normalized,
            limit=limit,
        )
    )
    if len(records) >= limit:
        return tuple(records[:limit])

    module_key = repo_path_to_module_key(normalized)
    module_records = store.query_records(
        MemoryQuery(
            project_id=project_id,
            types=types,
            statuses=statuses,
            subject_kind="module",
            subject_key_prefix=module_key,
            limit=limit,
        )
    )
    seen = {record.id for record in records}
    merged = list(records)
    for record in module_records:
        if record.id in seen:
            continue
        merged.append(record)
        seen.add(record.id)
        if len(merged) >= limit:
            break
    return tuple(merged[:limit])


def path_has_memory(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    rel_path: str,
) -> bool:
    return bool(
        query_records_for_repo_path(
            store,
            project_id=project_id,
            rel_path=rel_path,
            limit=1,
            statuses=("active", "historical", "stale"),
        )
    )


def _default_statuses(
    *,
    include_stale: bool,
    include_drafts: bool,
) -> tuple[MemoryStatus, ...]:
    statuses: list[MemoryStatus] = ["active", "historical"]
    if include_stale:
        statuses.append("stale")
    if include_drafts:
        statuses.append("draft")
    return tuple(statuses)


def _record_visible(
    record: MemoryRecord,
    *,
    include_stale: bool,
    include_drafts: bool,
) -> bool:
    if record.status == "stale" and not include_stale:
        return False
    if record.status == "historical":
        return True
    if record.status == "draft":
        return include_drafts
    if record.confidence == "inferred" and not record.approved_by:
        return False
    return record.status in {"active", "stale", "draft"}


def _retrieval_policy(*, include_drafts: bool) -> dict[str, object]:
    return {
        "drafts_included": include_drafts,
        "memory_does_not_authorize_edits": True,
        "memory_does_not_override_findings": True,
        "trajectories_do_not_authorize_edits": True,
        "experiences_do_not_authorize_edits": True,
        # Per-record guardrail lives here once, not duplicated on every record:
        # status is the single source of truth (status=="draft" => unverified).
        "status_is_authoritative": True,
        "draft_records_are_unverified": True,
    }


DEFAULT_EXPERIENCE_PREVIEW_LIMIT = 10
COMPACT_MEMORY_SUBJECT_LIMIT = 6

_MEMORY_SUBJECT_KIND_ORDER = {
    "path": 0,
    "module": 1,
    "symbol": 2,
    "intent": 3,
    "workflow": 4,
}


def _scope_family(path: str) -> str | None:
    """Directory family of a scope path — the experience subject_family unit."""
    try:
        normalized = normalize_repo_path(path)
    except ValueError:
        return None
    parent = PurePosixPath(normalized).parent.as_posix()
    return None if parent in {"", "."} else parent


def _scope_families(scope_paths: Sequence[str]) -> frozenset[str]:
    return frozenset(
        family
        for path in scope_paths
        for family in (_scope_family(path),)
        if family is not None
    )


def _serialize_experience(
    experience: Experience,
    *,
    detail_level: MemoryDetailLevel,
) -> dict[str, object]:
    statement_length = len(experience.statement)
    statement = (
        experience.statement
        if detail_level == "full"
        else _statement_preview(experience.statement)
    )
    payload: dict[str, object] = {
        "id": experience.id,
        "subject_family": experience.subject_family,
        "signal": experience.signal,
        "outcome_class": experience.outcome_class,
        "support": experience.support,
        "information_value": experience.information_value,
        "status": experience.status,
        "statement": statement,
    }
    agent_facet_items = sorted(
        (
            (facet.facet_value, facet.count)
            for facet in experience.facets
            if facet.facet_kind == "agent_family"
        ),
        key=lambda item: (-item[1], item[0]),
    )
    agent_facets: list[dict[str, object]] = [
        {"agent_family": family, "count": count} for family, count in agent_facet_items
    ]
    payload.update(
        _experience_detail_payload(
            experience,
            detail_level=detail_level,
            statement_length=statement_length,
            statement=statement,
            agent_facets=agent_facets,
        )
    )
    return payload


def _experience_detail_payload(
    experience: Experience,
    *,
    detail_level: MemoryDetailLevel,
    statement_length: int,
    statement: str,
    agent_facets: list[dict[str, object]],
) -> dict[str, object]:
    if detail_level == "full":
        return {
            "agent_facets": agent_facets,
            "evidence_trajectory_ids": [
                item.trajectory_id for item in experience.evidence
            ],
        }
    payload: dict[str, object] = {
        "statement_length": statement_length,
        "evidence_count": len(experience.evidence),
        "agent_family_count": len(agent_facets),
        "multi_agent": len(agent_facets) > 1,
    }
    if agent_facets:
        payload["dominant_agent_facet"] = agent_facets[0]
    if statement_length > len(statement):
        payload["statement_truncated"] = True
    return payload


def _matching_experiences(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    families: frozenset[str],
) -> list[Experience]:
    """Active advisory experiences matching the requested scope families."""
    if not families:
        return []
    matched = [
        experience
        for experience in store.list_experiences(project_id=project_id)
        if experience.status == "active" and experience.subject_family in families
    ]
    matched.sort(
        key=lambda experience: (
            -experience.support,
            -experience.information_value,
            experience.id,
        )
    )
    return matched


def _serialize_relevant_experiences(
    experiences: Sequence[Experience],
    *,
    max_results: int,
    detail_level: MemoryDetailLevel,
) -> list[dict[str, object]]:
    return [
        _serialize_experience(experience, detail_level=detail_level)
        for experience in experiences[:max_results]
    ]


def _serialize_subject(subject: MemorySubject) -> dict[str, object]:
    return {
        "subject_kind": subject.subject_kind,
        "subject_key": subject.subject_key,
        "relation": subject.relation,
    }


def _memory_subject_priority(
    subject: MemorySubject,
    *,
    context: RankingContext | None,
) -> tuple[object, ...]:
    key = subject.subject_key.replace("\\", "/").strip("/")
    context_group = 3
    context_score = 0.0
    if context is not None:
        if key in context.symbols:
            context_group = 0
            context_score = 1.0
        else:
            scope_score = subject_matches_scope(key, scope_paths=context.scope_paths)
            if scope_score > 0.0:
                context_group = 1
                context_score = scope_score
            elif key in context.blast_dependents:
                context_group = 2
                context_score = 0.7
    return (
        context_group,
        -context_score,
        _MEMORY_SUBJECT_KIND_ORDER.get(subject.subject_kind, 99),
        key,
        subject.relation,
        subject.id,
    )


def _preview_memory_subjects(
    subjects: Sequence[MemorySubject],
    *,
    detail_level: MemoryDetailLevel,
    context: RankingContext | None,
) -> list[MemorySubject]:
    if detail_level == "full":
        return list(subjects)
    return sorted(
        subjects,
        key=lambda subject: _memory_subject_priority(subject, context=context),
    )[:COMPACT_MEMORY_SUBJECT_LIMIT]


def _serialize_evidence(evidence: MemoryEvidence) -> dict[str, object]:
    return {
        "id": evidence.id,
        "evidence_kind": evidence.evidence_kind,
        "ref": evidence.ref,
        "locator": evidence.locator,
        "quote": evidence.quote,
        "digest": evidence.digest,
        "created_at_utc": evidence.created_at_utc,
    }


def _retrieval_lane_payload(record: MemoryRecord) -> dict[str, object]:
    lane = retrieval_lane(record)
    return {"retrieval_lane": lane} if lane is not None else {}


def _serialize_record_summary(
    *,
    record: MemoryRecord,
    subjects: Sequence[MemorySubject],
    evidence_count: int,
    relevance_score: float | None = None,
    detail_level: MemoryDetailLevel = "compact",
    context: RankingContext | None = None,
) -> dict[str, object]:
    statement_length = len(record.statement)
    if detail_level == "full":
        statement_value: str = record.statement
    else:
        statement_value = _statement_preview(record.statement)
    serialized_subjects = _preview_memory_subjects(
        subjects,
        detail_level=detail_level,
        context=context,
    )
    payload: dict[str, object] = {
        "id": record.id,
        "type": record.type,
        "status": record.status,
        "confidence": record.confidence,
        "approved": record.approved_by is not None,
        "statement": statement_value,
        "statement_length": statement_length,
        "subjects": [_serialize_subject(item) for item in serialized_subjects],
        "evidence_count": evidence_count,
    }
    if detail_level == "full":
        payload["payload"] = record.payload
    else:
        payload["subject_count"] = len(subjects)
        payload["subjects_truncated"] = len(serialized_subjects) < len(subjects)
        if statement_length > len(statement_value):
            payload["statement_truncated"] = True
    if record.stale_reason:
        payload["stale_reason"] = record.stale_reason
    payload.update(_retrieval_lane_payload(record))
    if relevance_score is not None:
        payload["relevance_score"] = relevance_score
    return payload


# Bounded down-rank for a record refuted by a 1-hop neighbour; mirrors the
# stale -0.5 lever. Truth is corrected, never silently returned.
_CONFLICT_PENALTY = 0.5
_CONFLICT_RELATIONS: tuple[LinkRelation, ...] = ("contradicts", "supersedes")


def _record_relations(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    record_ids: Sequence[str],
) -> dict[str, dict[str, list[str]]]:
    """1-hop contradicts/supersedes neighbours per record (deterministic).

    The other endpoint may be outside ``record_ids``; it is surfaced as a
    relation id, never promoted into the result set.
    """
    links = store.list_links_for_records(
        project_id=project_id,
        record_ids=record_ids,
        relations=_CONFLICT_RELATIONS,
    )
    raw: dict[str, dict[str, set[str]]] = {}

    def bucket(record_id: str) -> dict[str, set[str]]:
        return raw.setdefault(
            record_id,
            {"contradicted_by": set(), "superseded_by": set(), "supersedes": set()},
        )

    for link in links:
        if link.relation == "contradicts":
            bucket(link.from_memory_id)["contradicted_by"].add(link.to_memory_id)
            bucket(link.to_memory_id)["contradicted_by"].add(link.from_memory_id)
        else:  # supersedes
            bucket(link.from_memory_id)["supersedes"].add(link.to_memory_id)
            bucket(link.to_memory_id)["superseded_by"].add(link.from_memory_id)

    wanted = set(record_ids)
    relations: dict[str, dict[str, list[str]]] = {}
    for record_id, groups in raw.items():
        if record_id not in wanted:
            continue
        compact = {key: sorted(values) for key, values in groups.items() if values}
        if compact:
            relations[record_id] = compact
    return relations


def _apply_conflict_penalty(
    score: float, relations: dict[str, list[str]] | None
) -> float:
    if relations is not None and (
        relations.get("contradicted_by") or relations.get("superseded_by")
    ):
        return round(score - _CONFLICT_PENALTY, 4)
    return score


def _rank_records(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    candidates: Sequence[MemoryRecord],
    context: RankingContext,
    max_records: int,
    detail_level: MemoryDetailLevel,
    lexical_ranks: Mapping[str, int] | None = None,
    vector_ranks: Mapping[str, int] | None = None,
) -> tuple[list[dict[str, object]], bool]:
    # Fusion mode (hybrid search) supplies the lexical (BM25) and/or vector
    # rankings. There the metadata relevance_score is only a deterministic
    # tie-break, so the vector signal must NOT also be folded into it via
    # semantic_proximity (avoid double-counting). Scoped retrieval supplies
    # neither map and keeps relevance_score as the sole ordering signal.
    fusion_enabled = lexical_ranks is not None or vector_ranks is not None
    lexical_map = lexical_ranks or {}
    vector_map = vector_ranks or {}
    candidate_ids = tuple(record.id for record in candidates)
    subjects_by_id = store.list_subjects_for_memories(candidate_ids)
    evidence_counts = store.count_evidence_for_memories(candidate_ids)
    base: list[tuple[float, MemoryRecord, list[MemorySubject], int]] = []
    for record in candidates:
        subjects = subjects_by_id[record.id]
        evidence_count = evidence_counts[record.id]
        score = relevance_score(
            record=record,
            subjects=subjects,
            context=context,
            evidence_count=evidence_count,
        )
        if score <= 0.0 and (context.scope_paths or context.symbols):
            continue
        base.append((score, record, subjects, evidence_count))
    relations = _record_relations(
        store, project_id=project_id, record_ids=[item[1].id for item in base]
    )
    scored: list[tuple[float, float, str, dict[str, object]]] = []
    for score, record, subjects, evidence_count in base:
        record_relations = relations.get(record.id)
        adjusted = _apply_conflict_penalty(score, record_relations)
        if fusion_enabled:
            primary = reciprocal_rank_fusion(
                lexical_rank=lexical_map.get(record.id),
                vector_rank=vector_map.get(record.id),
            )
        else:
            primary = adjusted
        summary = _serialize_record_summary(
            record=record,
            subjects=subjects,
            evidence_count=evidence_count,
            relevance_score=adjusted,
            detail_level=detail_level,
            context=context,
        )
        if record_relations is not None:
            summary["relations"] = record_relations
        scored.append((primary, adjusted, record.id, summary))
    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    truncated = len(scored) > max_records
    return [item[3] for item in scored[:max_records]], truncated


def _coverage_summary(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    scope_paths: Sequence[str],
) -> dict[str, object]:
    normalized = normalize_memory_scope_paths(scope_paths)
    with_memory = 0
    for raw_path in normalized:
        if path_has_memory(
            store,
            project_id=project_id,
            rel_path=raw_path,
        ):
            with_memory += 1
    total = len(normalized)
    percent = round(with_memory * 100 / total) if total else 100
    return {
        "scope_paths_with_memory": with_memory,
        "scope_paths_total": total,
        "coverage_percent": percent,
        "coverage_kind": "record_subject_coverage",
    }


def get_relevant_memory(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    scope_paths: Sequence[str] | None = None,
    symbols: Sequence[str] | None = None,
    blast_dependents: Sequence[str] | None = None,
    scope_resolved_from: str,
    max_records: int = 20,
    include_stale: bool = False,
    include_drafts: bool = False,
    include_routine: bool = False,
    detail_level: str = "compact",
) -> dict[str, object]:
    normalized_detail = _normalize_detail_level(detail_level)
    raw_scope = scope_paths or ()
    normalized_symbols = frozenset(symbols or ())
    if not raw_scope and not normalized_symbols:
        raise MemoryContractError(MEMORY_RETRIEVAL_SCOPE_REQUIRED_ERROR)
    normalized_scope = tuple(normalize_memory_scope_path(path) for path in raw_scope)
    normalized_blast = frozenset(
        normalize_memory_scope_path(path) for path in (blast_dependents or ())
    )
    effective_include_drafts = include_drafts or bool(normalized_scope)
    context = RankingContext.from_scope(
        scope_paths=normalized_scope,
        symbols=tuple(normalized_symbols),
        blast_dependents=tuple(normalized_blast),
    )
    statuses = _default_statuses(
        include_stale=include_stale,
        include_drafts=effective_include_drafts,
    )
    candidates = store.query_records(
        MemoryQuery(project_id=project_id, statuses=statuses, limit=5000)
    )
    visible = [
        record
        for record in candidates
        if _record_visible(
            record,
            include_stale=include_stale,
            include_drafts=effective_include_drafts,
        )
    ]
    records_payload, truncated = _rank_records(
        store,
        project_id=project_id,
        candidates=visible,
        context=context,
        max_records=max_records,
        detail_level=normalized_detail,
    )
    trajectory_candidates = store.list_trajectories_for_subjects(
        project_id=project_id,
        subjects=trajectory_subject_keys(
            scope_paths=normalized_scope,
            symbols=tuple(normalized_symbols),
        ),
        limit=max(DEFAULT_TRAJECTORY_PREVIEW_LIMIT * 3, max_records),
    )
    patch_trails = _load_patch_trails_for_trajectories(
        store,
        trajectory_ids=tuple(item.id for item in trajectory_candidates),
    )
    trajectories_payload, trajectories_truncated = rank_trajectories_for_scope(
        trajectory_candidates,
        scope_paths=normalized_scope,
        symbols=tuple(normalized_symbols),
        max_results=min(max_records, DEFAULT_TRAJECTORY_PREVIEW_LIMIT),
        include_routine=include_routine,
        patch_trails=patch_trails,
        detail_level=normalized_detail,
    )
    matching_experiences = _matching_experiences(
        store,
        project_id=project_id,
        families=_scope_families(normalized_scope),
    )
    experiences_payload = _serialize_relevant_experiences(
        matching_experiences,
        max_results=min(max_records, DEFAULT_EXPERIENCE_PREVIEW_LIMIT),
        detail_level=normalized_detail,
    )
    coverage: dict[str, object]
    if normalized_scope:
        coverage = build_context_coverage(
            record_coverage=_coverage_summary(
                store,
                project_id=project_id,
                scope_paths=normalized_scope,
            ),
            scope_paths=normalized_scope,
            scope_families=_scope_families(normalized_scope),
            trajectories=filter_trajectories_for_default_retrieval(
                trajectory_candidates,
                include_routine=include_routine,
            ),
            experiences=matching_experiences,
            detail_level=normalized_detail,
        )
    else:
        coverage = {
            "record_coverage": {
                "scope_paths_with_memory": 0,
                "scope_paths_total": 0,
                "coverage_percent": None,
            },
            "coverage_note": "symbol_scoped_retrieval",
        }
    payload: dict[str, object] = {
        "project_id": project_id,
        "scope_resolved_from": scope_resolved_from,
        "records": records_payload,
        "trajectories": trajectories_payload,
        "experiences": experiences_payload,
        "record_count": len(records_payload),
        "trajectory_count": len(trajectories_payload),
        "experience_count": len(experiences_payload),
        "truncated": truncated,
        "trajectories_truncated": trajectories_truncated,
        "coverage": coverage,
        "detail_level": normalized_detail,
        "retrieval_policy": _retrieval_policy(include_drafts=effective_include_drafts),
    }
    return payload


def _load_patch_trails_for_trajectories(
    store: SqliteEngineeringMemoryStore,
    *,
    trajectory_ids: Sequence[str],
) -> dict[str, dict[str, object]]:
    return store.load_trajectory_patch_trails(trajectory_ids)


def _parse_filters(
    filters: Mapping[str, object] | None,
) -> tuple[
    tuple[MemoryRecordType, ...],
    tuple[MemoryStatus, ...],
    tuple[MemoryConfidence, ...],
    SearchMatchMode,
    bool,
]:
    types: list[MemoryRecordType] = []
    statuses: list[MemoryStatus] = []
    confidences: list[MemoryConfidence] = []
    match_mode: SearchMatchMode = "any"
    include_routine = False
    if filters is None:
        return (), (), (), match_mode, include_routine
    raw_types = filters.get("types")
    if isinstance(raw_types, list):
        types.extend(cast(MemoryRecordType, str(item)) for item in raw_types)
    raw_statuses = filters.get("statuses")
    if isinstance(raw_statuses, list):
        statuses.extend(cast(MemoryStatus, str(item)) for item in raw_statuses)
    raw_confidences = filters.get("confidences")
    if isinstance(raw_confidences, list):
        confidences.extend(
            cast(MemoryConfidence, str(item)) for item in raw_confidences
        )
    raw_match = filters.get("match_mode")
    if raw_match in {"all", "any"}:
        match_mode = cast(SearchMatchMode, raw_match)
    if bool(filters.get("include_routine")):
        include_routine = True
    return (
        tuple(types),
        tuple(statuses),
        tuple(confidences),
        match_mode,
        include_routine,
    )


def _handle_status_mode(
    *,
    mode: str,
    root_path: object,
    db_path: object,
    backend: str,
) -> dict[str, object]:
    from pathlib import Path

    if not isinstance(root_path, Path) or not isinstance(db_path, Path):
        raise TypeError("root_path and db_path must be Path instances")
    report = build_memory_status_report(
        root_path=root_path,
        db_path=db_path,
        backend=backend,
    )
    payload = {
        "schema_version": report.schema_version,
        "project_id": report.project_id,
        "project_root": report.project_root,
        "backend": report.backend,
        "db_path": str(report.db_path),
        "db_exists": report.db_exists,
        "record_count": report.record_count,
        "records_by_type": report.records_by_type,
        "records_by_status": report.records_by_status,
        "last_analysis_fingerprint": report.last_analysis_fingerprint,
        "last_init_run_id": report.last_init_run_id,
    }
    return {"mode": mode, "status": "ok", "payload": payload}


def _handle_get_mode(
    store: SqliteEngineeringMemoryStore,
    *,
    mode: str,
    project_id: str,
    record_id: str | None,
) -> dict[str, object]:
    if not record_id:
        raise MemoryContractError("mode=get requires record_id.")
    record = store.find_record(record_id)
    if record is None or record.project_id != project_id:
        return {
            "mode": mode,
            "status": "not_found",
            "payload": {"record_id": record_id},
        }
    subjects = store.list_subjects_for_memory(record.id)
    evidence = store.list_evidence_for_memory(record.id)
    return {
        "mode": mode,
        "status": "ok",
        "detail_level": "full",
        "payload": {
            "record": _serialize_record_summary(
                record=record,
                subjects=subjects,
                evidence_count=len(evidence),
                detail_level="full",
            ),
            "evidence": [_serialize_evidence(item) for item in evidence],
        },
    }


def _serialize_list_mode_records(
    store: SqliteEngineeringMemoryStore,
    *,
    records: Sequence[MemoryRecord],
    detail_level: MemoryDetailLevel,
) -> list[dict[str, object]]:
    return [
        _serialize_record_summary(
            record=record,
            subjects=store.list_subjects_for_memory(record.id),
            evidence_count=store.count_evidence_for_memory(record.id),
            detail_level=detail_level,
        )
        for record in records
    ]


def _handle_stale_mode(
    store: SqliteEngineeringMemoryStore,
    *,
    mode: str,
    project_id: str,
    max_results: int,
    detail_level: MemoryDetailLevel,
) -> dict[str, object]:
    records = store.query_records(
        MemoryQuery(
            project_id=project_id,
            statuses=("stale",),
            limit=max_results,
        )
    )
    payload_records = _serialize_list_mode_records(
        store,
        records=records,
        detail_level=detail_level,
    )
    return {
        "mode": mode,
        "status": "ok",
        "detail_level": detail_level,
        "payload": {
            "records": payload_records,
            "record_count": len(payload_records),
            "truncated": len(records) >= max_results,
        },
    }


def _handle_coverage_mode(
    store: SqliteEngineeringMemoryStore,
    *,
    mode: str,
    project_id: str,
    scope: Sequence[str] | None,
) -> dict[str, object]:
    scope_paths = normalize_memory_scope_paths(scope or ())
    coverage = _coverage_summary(
        store,
        project_id=project_id,
        scope_paths=scope_paths,
    )
    return {"mode": mode, "status": "ok", "payload": coverage}


def _handle_trajectory_status_mode(
    store: SqliteEngineeringMemoryStore,
    *,
    mode: str,
    project_id: str,
) -> dict[str, object]:
    return {
        "mode": mode,
        "status": "ok",
        "payload": trajectory_status_payload(
            count=store.count_trajectories(project_id=project_id),
            latest_run=store.latest_trajectory_projection_run(project_id=project_id),
        ),
    }


def _handle_trajectory_get_mode(
    store: SqliteEngineeringMemoryStore,
    *,
    mode: str,
    project_id: str,
    record_id: str | None,
) -> dict[str, object]:
    trajectory_id = _require_query_field(
        record_id,
        mode=mode,
        field="record_id containing trajectory_id",
    )
    trajectory = store.find_trajectory(trajectory_id)
    if trajectory is None or trajectory.project_id != project_id:
        return {
            "mode": mode,
            "status": "not_found",
            "payload": {"trajectory_id": trajectory_id},
        }
    patch_trail_payload = store.load_trajectory_patch_trail(trajectory_id)
    return {
        "mode": mode,
        "status": "ok",
        "detail_level": "full",
        "payload": {
            "trajectory": serialize_trajectory_detail(
                trajectory,
                patch_trail_payload=patch_trail_payload,
            )
        },
    }


def _handle_trajectory_search_mode(
    store: SqliteEngineeringMemoryStore,
    *,
    mode: str,
    project_id: str,
    query: str | None,
    max_results: int,
    match_mode: SearchMatchMode,
    include_routine: bool = False,
    detail_level: MemoryDetailLevel = "compact",
) -> dict[str, object]:
    statement = _require_query_field(query, mode=mode, field="query")
    candidates = store.search_trajectories(
        project_id=project_id,
        query=statement,
        limit=max_results + 1,
        match_mode=match_mode,
    )
    trajectories, truncated = rank_trajectories_for_query(
        candidates,
        query=statement,
        max_results=max_results,
        match_mode=match_mode,
        include_routine=include_routine,
        detail_level=detail_level,
    )
    return {
        "mode": mode,
        "status": "ok",
        "detail_level": detail_level,
        "payload": {
            "trajectories": trajectories,
            "trajectory_count": len(trajectories),
            "truncated": truncated,
            "retrieval_policy": _retrieval_policy(include_drafts=False),
        },
    }


def _handle_trajectory_anomalies_mode(
    store: SqliteEngineeringMemoryStore,
    *,
    mode: str,
    project_id: str,
    max_results: int,
    include_routine: bool = False,
    detail_level: MemoryDetailLevel = "compact",
) -> dict[str, object]:
    return {
        "mode": mode,
        "status": "ok",
        "detail_level": detail_level,
        "payload": build_trajectory_anomalies_payload(
            store,
            project_id=project_id,
            max_results=max_results,
            include_routine=include_routine,
            detail_level=detail_level,
        ),
    }


def _handle_trajectory_agents_mode(
    store: SqliteEngineeringMemoryStore,
    *,
    mode: str,
    project_id: str,
    include_routine: bool = False,
) -> dict[str, object]:
    return {
        "mode": mode,
        "status": "ok",
        "detail_level": "compact",
        "payload": build_trajectory_agent_stats_payload(
            store,
            project_id=project_id,
            include_routine=include_routine,
        ),
    }


def _handle_trajectory_dashboard_mode(
    store: SqliteEngineeringMemoryStore,
    *,
    mode: str,
    project_id: str,
    max_results: int,
    include_routine: bool = False,
    detail_level: MemoryDetailLevel = "compact",
) -> dict[str, object]:
    return {
        "mode": mode,
        "status": "ok",
        "detail_level": detail_level,
        "payload": build_trajectory_dashboard_payload(
            store,
            project_id=project_id,
            max_results=max_results,
            include_routine=include_routine,
            detail_level=detail_level,
        ),
    }


def _search_statuses_for_mode(
    mode: str,
    *,
    filter_statuses: tuple[MemoryStatus, ...],
    include_stale: bool,
    include_drafts: bool,
) -> tuple[MemoryStatus, ...]:
    if mode != "search":
        return filter_statuses or _default_statuses(
            include_stale=include_stale,
            include_drafts=include_drafts,
        )
    if filter_statuses:
        return filter_statuses
    if include_stale:
        return _default_statuses(include_stale=True, include_drafts=include_drafts)
    return _default_statuses(include_stale=False, include_drafts=include_drafts)


def _require_query_field(value: str | None, *, mode: str, field: str) -> str:
    text = value.strip() if value else ""
    if not text:
        raise MemoryContractError(f"mode={mode} requires {field}.")
    return text


def _fetch_search_mode_records(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    query: str | None,
    filter_types: tuple[MemoryRecordType, ...],
    statuses: tuple[MemoryStatus, ...],
    filter_confidences: tuple[MemoryConfidence, ...],
    max_results: int,
    match_mode: SearchMatchMode,
) -> tuple[MemoryRecord, ...]:
    statement = _require_query_field(query, mode="search", field="query")
    return tuple(
        store.search_records(
            project_id=project_id,
            statement_query=statement,
            types=filter_types,
            statuses=statuses,
            confidences=filter_confidences,
            limit=max_results + 1,
            match_mode=match_mode,
        )
    )


def _fetch_for_path_mode_records(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    path: str | None,
    filter_types: tuple[MemoryRecordType, ...],
    statuses: tuple[MemoryStatus, ...],
    max_results: int,
) -> tuple[MemoryRecord, ...]:
    rel_path = normalize_memory_scope_path(
        _require_query_field(path, mode="for_path", field="path")
    )
    return query_records_for_repo_path(
        store,
        project_id=project_id,
        rel_path=rel_path,
        limit=max_results + 1,
        types=filter_types,
        statuses=statuses,
    )


def _fetch_for_symbol_mode_records(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    symbol: str | None,
    filter_types: tuple[MemoryRecordType, ...],
    statuses: tuple[MemoryStatus, ...],
    max_results: int,
) -> tuple[MemoryRecord, ...]:
    symbol_key = _require_query_field(symbol, mode="for_symbol", field="symbol")
    records = store.query_records(
        MemoryQuery(
            project_id=project_id,
            types=filter_types,
            statuses=statuses,
            subject_kind="symbol",
            subject_key=symbol_key,
            limit=max_results + 1,
        )
    )
    if records:
        return tuple(records)

    module_prefix = symbol_key.rsplit(".", maxsplit=1)[0]
    if module_prefix == symbol_key:
        return ()
    module_records = store.query_records(
        MemoryQuery(
            project_id=project_id,
            types=filter_types,
            statuses=statuses,
            subject_kind="module",
            subject_key=module_prefix,
            limit=max_results + 1,
        )
    )
    return tuple(module_records)


def _records_for_list_mode(
    store: SqliteEngineeringMemoryStore,
    *,
    mode: str,
    project_id: str,
    path: str | None,
    symbol: str | None,
    query: str | None,
    filter_types: tuple[MemoryRecordType, ...],
    statuses: tuple[MemoryStatus, ...],
    filter_confidences: tuple[MemoryConfidence, ...],
    max_results: int,
    match_mode: SearchMatchMode,
) -> tuple[MemoryRecord, ...]:
    if mode == "search":
        return _fetch_search_mode_records(
            store,
            project_id=project_id,
            query=query,
            filter_types=filter_types,
            statuses=statuses,
            filter_confidences=filter_confidences,
            max_results=max_results,
            match_mode=match_mode,
        )
    if mode == "for_path":
        return _fetch_for_path_mode_records(
            store,
            project_id=project_id,
            path=path,
            filter_types=filter_types,
            statuses=statuses,
            max_results=max_results,
        )
    if mode == "for_symbol":
        return _fetch_for_symbol_mode_records(
            store,
            project_id=project_id,
            symbol=symbol,
            filter_types=filter_types,
            statuses=statuses,
            max_results=max_results,
        )
    return ()


def _search_payload_body(
    payload_records: list[dict[str, object]],
    *,
    truncated: bool,
    include_drafts: bool,
    audit_events: list[dict[str, object]] | None = None,
    trajectories: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    body: dict[str, object] = {
        "records": payload_records,
        "record_count": len(payload_records),
        "truncated": truncated,
        "retrieval_policy": _retrieval_policy(include_drafts=include_drafts),
    }
    if audit_events is not None:
        body["audit_events"] = audit_events
    if trajectories is not None:
        body["trajectories"] = trajectories
    return body


def _semantic_disabled_block() -> dict[str, object]:
    return {
        "used": False,
        "backend": None,
        "provider": None,
        "model": None,
        "index_version": None,
        "reason": "disabled",
    }


def _semantic_status_block(
    status: SemanticIndexStatus,
    *,
    used: bool,
    provider_label: str | None,
    model: str | None,
    reason: str | None = None,
) -> dict[str, object]:
    return {
        "used": used,
        "backend": status.backend,
        "provider": provider_label,
        "model": model,
        "index_version": SEMANTIC_INDEX_FORMAT_VERSION if used else None,
        "reason": None if used else reason or status.reason,
    }


def _semantic_hits(
    *,
    index: SemanticIndex,
    provider: EmbeddingProvider,
    query: str,
    k: int,
) -> tuple[dict[str, float], list[SemanticHit], list[SemanticHit]]:
    # Search each lane with its own top-k budget so a dense source (e.g. audit)
    # cannot crowd memory hits out of one shared top-k (#3). The index applies
    # the source filter, so results arrive already lane-scoped.
    # The embed is the expensive step (lazy model load); give it its own span so
    # embedding load time is observable separately from the vector search.
    with span(name="retrieval.embed_query"):
        vector = embed_query(provider, query)
    proximity: dict[str, float] = {}
    for hit in index.search(vector, k=k, source="memory"):
        proximity.setdefault(hit.source_id, hit.score)
    audit_hits = list(index.search(vector, k=k, source="audit"))
    trajectory_hits = list(index.search(vector, k=k, source="trajectory"))
    return proximity, audit_hits, trajectory_hits


def _record_search_telemetry(
    *,
    fts_records: Sequence[MemoryRecord],
    proximity: Mapping[str, float],
    audit_hits: Sequence[SemanticHit],
    trajectory_hits: Sequence[SemanticHit],
    candidates: Sequence[MemoryRecord],
) -> None:
    # Lane-hit telemetry for the hybrid search, attributed to the active span.
    # No-op outside an observability span; the caller guards the call so the
    # set-math below is skipped entirely when observability is disabled.
    candidate_ids = {record.id for record in candidates}
    overlap = sum(1 for record in fts_records if record.id in proximity)
    filtered = sum(1 for record_id in proximity if record_id not in candidate_ids)
    record_counter("retrieval.fts_hits", len(fts_records))
    record_counter("retrieval.vector_memory_hits", len(proximity))
    record_counter("retrieval.vector_audit_hits", len(audit_hits))
    record_counter("retrieval.vector_trajectory_hits", len(trajectory_hits))
    record_counter("retrieval.fts_vector_overlap", overlap)
    record_counter("retrieval.semantic_filtered", filtered)


def _hydrate_audit_events(
    audit_db_path: Path | None, hits: Sequence[SemanticHit]
) -> list[dict[str, object]]:
    if audit_db_path is None:
        return []
    events: list[dict[str, object]] = []
    for hit in hits:
        row = audit_event_row(audit_db_path, hit.source_id)
        if row is None:
            continue
        event_type, status, summary = row
        events.append(
            {
                "event_id": hit.source_id,
                "event_type": event_type,
                "status": status,
                "summary": _statement_preview(summary),
                "score": hit.score,
            }
        )
    return events


def _hydrate_trajectory_hits(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    hits: Sequence[SemanticHit],
    detail_level: MemoryDetailLevel,
) -> list[dict[str, object]]:
    trajectories: list[dict[str, object]] = []
    for hit in hits:
        trajectory = store.find_trajectory(hit.source_id)
        if trajectory is None or trajectory.project_id != project_id:
            continue
        payload = (
            serialize_trajectory_detail(trajectory, max_steps=4)
            if detail_level == "full"
            else serialize_trajectory_preview(
                trajectory,
                detail_level="compact",
            )
        )
        payload["semantic_score"] = hit.score
        trajectories.append(payload)
    return trajectories


def _record_passes_filters(
    record: MemoryRecord,
    *,
    types: tuple[MemoryRecordType, ...],
    statuses: tuple[MemoryStatus, ...],
    confidences: tuple[MemoryConfidence, ...],
) -> bool:
    # Mirror the types/statuses/confidences predicate the FTS branch applies in
    # SQL (store.search_records), so semantic candidates cannot bypass the
    # public query filter contract. An empty category tuple means "no filter".
    return (
        (not types or record.type in types)
        and (not statuses or record.status in statuses)
        and (not confidences or record.confidence in confidences)
    )


def _semantic_search_candidates(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    fts_records: Sequence[MemoryRecord],
    proximity: Mapping[str, float],
    filter_types: tuple[MemoryRecordType, ...],
    statuses: tuple[MemoryStatus, ...],
    filter_confidences: tuple[MemoryConfidence, ...],
) -> list[MemoryRecord]:
    seen = {record.id for record in fts_records}
    candidates = list(fts_records)
    for record_id in proximity:
        if record_id in seen:
            continue
        record = store.find_record(record_id)
        if (
            record is not None
            and record.project_id == project_id
            and _record_passes_filters(
                record,
                types=filter_types,
                statuses=statuses,
                confidences=filter_confidences,
            )
        ):
            candidates.append(record)
            seen.add(record_id)
    return candidates


def _handle_semantic_search_mode(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    query: str | None,
    filter_types: tuple[MemoryRecordType, ...],
    statuses: tuple[MemoryStatus, ...],
    filter_confidences: tuple[MemoryConfidence, ...],
    match_mode: SearchMatchMode,
    max_results: int,
    detail_level: MemoryDetailLevel,
    include_stale: bool,
    include_drafts: bool,
    semantic_index: SemanticIndex | None,
    embedding_provider: EmbeddingProvider | None,
    provider_label: str | None,
    semantic_reason: str | None,
    audit_db_path: Path | None,
) -> dict[str, object]:
    statement = _require_query_field(query, mode="search", field="query")
    fts_records = _fetch_search_mode_records(
        store,
        project_id=project_id,
        query=statement,
        filter_types=filter_types,
        statuses=statuses,
        filter_confidences=filter_confidences,
        max_results=max_results,
        match_mode=match_mode,
    )
    status = semantic_index.status() if semantic_index is not None else None
    proximity: dict[str, float] = {}
    audit_hits: list[SemanticHit] = []
    trajectory_hits: list[SemanticHit] = []
    used_block: dict[str, object] | None = None
    if (
        semantic_index is not None
        and embedding_provider is not None
        and status is not None
        and status.available
    ):
        try:
            proximity, audit_hits, trajectory_hits = _semantic_hits(
                index=semantic_index,
                provider=embedding_provider,
                query=statement,
                k=max_results,
            )
        except MemorySemanticUnavailableError as exc:
            # The embedding model loads lazily, so an unavailable model (e.g.
            # download disabled and not cached) first surfaces here. Degrade to
            # FTS-only with the reason rather than failing the whole query.
            semantic_reason = str(exc)
        else:
            used_block = _semantic_status_block(
                status,
                used=True,
                provider_label=provider_label,
                model=embedding_provider.model_id,
            )
    if used_block is not None:
        candidates = _semantic_search_candidates(
            store,
            project_id=project_id,
            fts_records=fts_records,
            proximity=proximity,
            filter_types=filter_types,
            statuses=statuses,
            filter_confidences=filter_confidences,
        )
        audit_events = _hydrate_audit_events(audit_db_path, audit_hits)
        trajectories = _hydrate_trajectory_hits(
            store,
            project_id=project_id,
            hits=trajectory_hits,
            detail_level=detail_level,
        )
        semantic_block = used_block
    else:
        candidates = list(fts_records)
        audit_events = []
        trajectories = []
        semantic_block = (
            _semantic_status_block(
                status,
                used=False,
                provider_label=provider_label,
                model=None,
                reason=semantic_reason,
            )
            if status is not None
            else _semantic_disabled_block()
        )
    if is_observability_enabled():
        _record_search_telemetry(
            fts_records=fts_records,
            proximity=proximity,
            audit_hits=audit_hits,
            trajectory_hits=trajectory_hits,
            candidates=candidates,
        )
    effective_stale = include_stale or "stale" in statuses
    visible = [
        record
        for record in candidates
        if _record_visible(
            record,
            include_stale=effective_stale,
            include_drafts=include_drafts,
        )
    ]
    context = RankingContext.from_scope(scope_paths=(), symbols=(), blast_dependents=())
    # Reciprocal-rank-fusion inputs: the FTS list is already BM25-ordered, and
    # the vector hits are ranked by descending proximity (id breaks ties for
    # determinism). _rank_records fuses these and uses metadata only to break
    # ties, so a strong lexical/vector match is no longer re-sorted away by
    # metadata boosts.
    lexical_ranks = {record.id: rank for rank, record in enumerate(fts_records)}
    vector_ranks = {
        record_id: rank
        for rank, record_id in enumerate(
            sorted(proximity, key=lambda rid: (-proximity[rid], rid))
        )
    }
    payload_records, truncated = _rank_records(
        store,
        project_id=project_id,
        candidates=visible,
        context=context,
        max_records=max_results,
        detail_level=detail_level,
        lexical_ranks=lexical_ranks,
        vector_ranks=vector_ranks,
    )
    return {
        "mode": "search",
        "status": "ok",
        "detail_level": detail_level,
        "semantic": semantic_block,
        "payload": _search_payload_body(
            payload_records,
            truncated=truncated,
            include_drafts=include_drafts,
            audit_events=audit_events,
            trajectories=trajectories,
        ),
    }


def query_engineering_memory(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    root_path: object,
    backend: str,
    db_path: object,
    mode: str,
    record_id: str | None = None,
    path: str | None = None,
    symbol: str | None = None,
    query: str | None = None,
    scope: Sequence[str] | None = None,
    filters: Mapping[str, object] | None = None,
    max_results: int = 20,
    include_stale: bool = False,
    include_drafts: bool = False,
    detail_level: str = "compact",
    semantic: bool = False,
    semantic_index: SemanticIndex | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    provider_label: str | None = None,
    semantic_reason: str | None = None,
    audit_db_path: Path | None = None,
) -> dict[str, object]:
    if mode not in QUERY_MODES:
        raise MemoryContractError(
            f"Unknown query mode {mode!r}. Allowed: {', '.join(QUERY_MODES)}."
        )

    normalized_detail = _normalize_detail_level(detail_level)
    effective_include_drafts = include_drafts or mode in {"for_path", "for_symbol"}

    if mode == "status":
        return _handle_status_mode(
            mode=mode,
            root_path=root_path,
            db_path=db_path,
            backend=backend,
        )
    if mode == "get":
        return _handle_get_mode(
            store,
            mode=mode,
            project_id=project_id,
            record_id=record_id,
        )
    if mode == "stale":
        return _handle_stale_mode(
            store,
            mode=mode,
            project_id=project_id,
            max_results=max_results,
            detail_level=normalized_detail,
        )
    if mode == "drafts":
        records = store.query_records(
            MemoryQuery(
                project_id=project_id,
                statuses=("draft",),
                limit=max_results,
            )
        )
        payload_records = _serialize_list_mode_records(
            store,
            records=records,
            detail_level=normalized_detail,
        )
        return {
            "mode": mode,
            "status": "ok",
            "detail_level": normalized_detail,
            "payload": {
                "records": payload_records,
                "record_count": len(payload_records),
                "truncated": len(records) >= max_results,
            },
        }
    if mode == "coverage":
        return _handle_coverage_mode(
            store,
            mode=mode,
            project_id=project_id,
            scope=scope,
        )
    if mode == "trajectory_status":
        return _handle_trajectory_status_mode(
            store,
            mode=mode,
            project_id=project_id,
        )
    if mode == "trajectory_get":
        return _handle_trajectory_get_mode(
            store,
            mode=mode,
            project_id=project_id,
            record_id=record_id,
        )

    filter_types, filter_statuses, filter_confidences, match_mode, include_routine = (
        _parse_filters(filters)
    )
    if mode == "trajectory_anomalies":
        return _handle_trajectory_anomalies_mode(
            store,
            mode=mode,
            project_id=project_id,
            max_results=max_results,
            include_routine=include_routine,
            detail_level=normalized_detail,
        )
    if mode == "trajectory_agents":
        return _handle_trajectory_agents_mode(
            store,
            mode=mode,
            project_id=project_id,
            include_routine=include_routine,
        )
    if mode == "trajectory_dashboard":
        return _handle_trajectory_dashboard_mode(
            store,
            mode=mode,
            project_id=project_id,
            max_results=max_results,
            include_routine=include_routine,
            detail_level=normalized_detail,
        )
    if mode == "trajectory_search":
        return _handle_trajectory_search_mode(
            store,
            mode=mode,
            project_id=project_id,
            query=query,
            max_results=max_results,
            match_mode=match_mode,
            include_routine=include_routine,
            detail_level=normalized_detail,
        )
    statuses = _search_statuses_for_mode(
        mode,
        filter_statuses=filter_statuses,
        include_stale=include_stale,
        include_drafts=effective_include_drafts,
    )
    if mode == "search" and semantic:
        return _handle_semantic_search_mode(
            store,
            project_id=project_id,
            query=query,
            filter_types=filter_types,
            statuses=statuses,
            filter_confidences=filter_confidences,
            match_mode=match_mode,
            max_results=max_results,
            detail_level=normalized_detail,
            include_stale=include_stale,
            include_drafts=effective_include_drafts,
            semantic_index=semantic_index,
            embedding_provider=embedding_provider,
            provider_label=provider_label,
            semantic_reason=semantic_reason,
            audit_db_path=audit_db_path,
        )
    records = _records_for_list_mode(
        store,
        mode=mode,
        project_id=project_id,
        path=path,
        symbol=symbol,
        query=query,
        filter_types=filter_types,
        statuses=statuses,
        filter_confidences=filter_confidences,
        max_results=max_results,
        match_mode=match_mode,
    )
    visible = [
        record
        for record in records
        if _record_visible(
            record,
            include_stale=include_stale or (mode == "search" and "stale" in statuses),
            include_drafts=effective_include_drafts,
        )
    ]
    truncated = len(visible) > max_results
    selected = visible[:max_results]
    payload_records = _serialize_list_mode_records(
        store,
        records=selected,
        detail_level=normalized_detail,
    )
    return {
        "mode": mode,
        "status": "ok",
        "detail_level": normalized_detail,
        "payload": _search_payload_body(
            payload_records,
            truncated=truncated,
            include_drafts=effective_include_drafts,
        ),
    }


__all__ = [
    "COMPACT_MEMORY_SUBJECT_LIMIT",
    "QUERY_MODES",
    "MemoryDetailLevel",
    "QueryMode",
    "get_relevant_memory",
    "normalize_repo_path",
    "path_has_memory",
    "query_engineering_memory",
    "query_records_for_repo_path",
]
