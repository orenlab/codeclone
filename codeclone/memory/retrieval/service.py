# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Literal, cast

from ...config.memory_defaults import DEFAULT_MEMORY_STATEMENT_PREVIEW_CHARS
from ...contracts import SEMANTIC_INDEX_FORMAT_VERSION
from ..embedding import embed_query
from ..enums import MemoryConfidence, MemoryRecordType, MemoryStatus
from ..exceptions import MemoryContractError
from ..models import MemoryEvidence, MemoryQuery, MemoryRecord, MemorySubject
from ..paths import (
    MEMORY_RETRIEVAL_SCOPE_REQUIRED_ERROR,
    normalize_memory_scope_path,
    normalize_memory_scope_paths,
    normalize_repo_path,
    repo_path_to_module_key,
)
from ..search_index import SearchMatchMode
from ..sqlite_store import SqliteEngineeringMemoryStore
from ..status_report import build_memory_status_report
from .ranking import RankingContext, relevance_score
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
    }


def _serialize_subject(subject: MemorySubject) -> dict[str, object]:
    return {
        "subject_kind": subject.subject_kind,
        "subject_key": subject.subject_key,
        "relation": subject.relation,
    }


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


def _serialize_record_summary(
    *,
    record: MemoryRecord,
    subjects: Sequence[MemorySubject],
    evidence_count: int,
    relevance_score: float | None = None,
    detail_level: MemoryDetailLevel = "compact",
) -> dict[str, object]:
    statement_length = len(record.statement)
    if detail_level == "full":
        statement_value: str = record.statement
    else:
        statement_value = _statement_preview(record.statement)
    payload: dict[str, object] = {
        "id": record.id,
        "type": record.type,
        "status": record.status,
        "confidence": record.confidence,
        "approved": record.approved_by is not None,
        "statement": statement_value,
        "statement_length": statement_length,
        "subjects": [_serialize_subject(item) for item in subjects],
        "evidence_count": evidence_count,
        "stale": record.status == "stale",
    }
    if detail_level == "full":
        payload["payload"] = record.payload
    elif detail_level == "compact" and statement_length > len(statement_value):
        payload["statement_truncated"] = True
    if record.stale_reason:
        payload["stale_reason"] = record.stale_reason
    if record.status == "draft":
        payload["draft_unverified"] = True
    if relevance_score is not None:
        payload["relevance_score"] = relevance_score
    return payload


def _rank_records(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    candidates: Sequence[MemoryRecord],
    context: RankingContext,
    max_records: int,
    detail_level: MemoryDetailLevel,
    proximity: Mapping[str, float] | None = None,
) -> tuple[list[dict[str, object]], bool]:
    proximity_map = proximity or {}
    scored: list[tuple[float, str, dict[str, object]]] = []
    for record in candidates:
        subjects = store.list_subjects_for_memory(record.id)
        evidence_count = store.count_evidence_for_memory(record.id)
        score = relevance_score(
            record=record,
            subjects=subjects,
            context=context,
            evidence_count=evidence_count,
            semantic_proximity=proximity_map.get(record.id, 0.0),
        )
        if score <= 0.0 and (context.scope_paths or context.symbols):
            continue
        scored.append(
            (
                score,
                record.id,
                _serialize_record_summary(
                    record=record,
                    subjects=subjects,
                    evidence_count=evidence_count,
                    relevance_score=score,
                    detail_level=detail_level,
                ),
            )
        )
    scored.sort(key=lambda item: (-item[0], item[1]))
    truncated = len(scored) > max_records
    selected = scored[:max_records]
    return [item[2] for item in selected], truncated


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
    coverage: dict[str, object]
    if normalized_scope:
        coverage = _coverage_summary(
            store,
            project_id=project_id,
            scope_paths=normalized_scope,
        )
    else:
        coverage = {
            "scope_paths_with_memory": 0,
            "scope_paths_total": 0,
            "coverage_percent": None,
            "coverage_note": "symbol_scoped_retrieval",
        }
    return {
        "project_id": project_id,
        "scope_resolved_from": scope_resolved_from,
        "records": records_payload,
        "record_count": len(records_payload),
        "truncated": truncated,
        "coverage": coverage,
        "detail_level": normalized_detail,
        "retrieval_policy": _retrieval_policy(include_drafts=effective_include_drafts),
    }


def _parse_filters(
    filters: Mapping[str, object] | None,
) -> tuple[
    tuple[MemoryRecordType, ...],
    tuple[MemoryStatus, ...],
    tuple[MemoryConfidence, ...],
    SearchMatchMode,
]:
    types: list[MemoryRecordType] = []
    statuses: list[MemoryStatus] = []
    confidences: list[MemoryConfidence] = []
    match_mode: SearchMatchMode = "any"
    if filters is None:
        return (), (), (), match_mode
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
    return tuple(types), tuple(statuses), tuple(confidences), match_mode


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
) -> dict[str, object]:
    body: dict[str, object] = {
        "records": payload_records,
        "record_count": len(payload_records),
        "truncated": truncated,
        "retrieval_policy": _retrieval_policy(include_drafts=include_drafts),
    }
    if audit_events is not None:
        body["audit_events"] = audit_events
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
) -> tuple[dict[str, float], list[SemanticHit]]:
    vector = embed_query(provider, query)
    proximity: dict[str, float] = {}
    audit_hits: list[SemanticHit] = []
    for hit in index.search(vector, k=k):
        if hit.source == "memory":
            proximity.setdefault(hit.source_id, hit.score)
        elif hit.source == "audit":
            audit_hits.append(hit)
    return proximity, audit_hits


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


def _semantic_search_candidates(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    fts_records: Sequence[MemoryRecord],
    proximity: Mapping[str, float],
) -> list[MemoryRecord]:
    seen = {record.id for record in fts_records}
    candidates = list(fts_records)
    for record_id in proximity:
        if record_id in seen:
            continue
        record = store.find_record(record_id)
        if record is not None and record.project_id == project_id:
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
    if (
        semantic_index is not None
        and embedding_provider is not None
        and status is not None
        and status.available
    ):
        proximity, audit_hits = _semantic_hits(
            index=semantic_index,
            provider=embedding_provider,
            query=statement,
            k=max_results,
        )
        candidates = _semantic_search_candidates(
            store,
            project_id=project_id,
            fts_records=fts_records,
            proximity=proximity,
        )
        audit_events = _hydrate_audit_events(audit_db_path, audit_hits)
        semantic_block = _semantic_status_block(
            status,
            used=True,
            provider_label=provider_label,
            model=embedding_provider.model_id,
        )
    else:
        proximity = {}
        candidates = list(fts_records)
        audit_events = []
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
    payload_records, truncated = _rank_records(
        store,
        project_id=project_id,
        candidates=visible,
        context=context,
        max_records=max_results,
        detail_level=detail_level,
        proximity=proximity,
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

    filter_types, filter_statuses, filter_confidences, match_mode = _parse_filters(
        filters
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
    "QUERY_MODES",
    "MemoryDetailLevel",
    "QueryMode",
    "get_relevant_memory",
    "normalize_repo_path",
    "path_has_memory",
    "query_engineering_memory",
    "query_records_for_repo_path",
]
