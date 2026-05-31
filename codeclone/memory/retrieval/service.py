# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath
from typing import Literal, cast

from ..enums import MemoryConfidence, MemoryRecordType, MemoryStatus
from ..exceptions import MemoryContractError
from ..models import MemoryEvidence, MemoryQuery, MemoryRecord, MemorySubject
from ..paths import normalize_repo_path
from ..sqlite_store import SqliteEngineeringMemoryStore
from ..status_report import build_memory_status_report
from .ranking import RankingContext, relevance_score

QueryMode = Literal[
    "search",
    "get",
    "for_path",
    "for_symbol",
    "stale",
    "coverage",
    "status",
]

QUERY_MODES: tuple[str, ...] = (
    "search",
    "get",
    "for_path",
    "for_symbol",
    "stale",
    "coverage",
    "status",
)


def _default_statuses(
    *,
    include_stale: bool,
    include_drafts: bool,
) -> tuple[MemoryStatus, ...]:
    statuses: list[MemoryStatus] = ["active"]
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
    if record.status == "draft" and not include_drafts:
        return False
    if record.confidence == "inferred" and not record.approved_by:
        return False
    return record.status in {"active", "stale", "draft"}


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
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": record.id,
        "type": record.type,
        "status": record.status,
        "confidence": record.confidence,
        "approved": record.approved_by is not None,
        "statement": record.statement,
        "payload": record.payload,
        "subjects": [_serialize_subject(item) for item in subjects],
        "evidence_count": evidence_count,
        "stale": record.status == "stale",
    }
    if record.stale_reason:
        payload["stale_reason"] = record.stale_reason
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
) -> tuple[list[dict[str, object]], bool]:
    scored: list[tuple[float, str, dict[str, object]]] = []
    for record in candidates:
        subjects = store.list_subjects_for_memory(record.id)
        evidence_count = store.count_evidence_for_memory(record.id)
        score = relevance_score(
            record=record,
            subjects=subjects,
            context=context,
            evidence_count=evidence_count,
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
    if not scope_paths:
        return {
            "scope_paths_with_memory": 0,
            "scope_paths_total": 0,
            "coverage_percent": 100,
        }
    with_memory = 0
    for raw_path in scope_paths:
        path = normalize_repo_path(raw_path)
        records = store.query_records(
            MemoryQuery(
                project_id=project_id,
                subject_kind="path",
                subject_key_prefix=path,
                limit=1,
            )
        )
        if records:
            with_memory += 1
            continue
        module_prefix = PurePosixPath(path).parent.as_posix()
        if module_prefix and module_prefix != ".":
            records = store.query_records(
                MemoryQuery(
                    project_id=project_id,
                    subject_kind="module",
                    subject_key_prefix=module_prefix.replace("/", "."),
                    limit=1,
                )
            )
            if records:
                with_memory += 1
    total = len(scope_paths)
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
) -> dict[str, object]:
    normalized_scope = tuple(normalize_repo_path(path) for path in (scope_paths or ()))
    normalized_symbols = frozenset(symbols or ())
    normalized_blast = frozenset(
        normalize_repo_path(path) for path in (blast_dependents or ())
    )
    context = RankingContext(
        scope_paths=frozenset(normalized_scope),
        symbols=normalized_symbols,
        blast_dependents=normalized_blast,
    )
    statuses = _default_statuses(
        include_stale=include_stale,
        include_drafts=include_drafts,
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
            include_drafts=include_drafts,
        )
    ]
    if not normalized_scope and not normalized_symbols:
        visible.sort(key=lambda item: (item.updated_at_utc, item.id), reverse=True)
        records_payload = [
            _serialize_record_summary(
                record=record,
                subjects=store.list_subjects_for_memory(record.id),
                evidence_count=store.count_evidence_for_memory(record.id),
            )
            for record in visible[:max_records]
        ]
        truncated = len(visible) > max_records
    else:
        records_payload, truncated = _rank_records(
            store,
            project_id=project_id,
            candidates=visible,
            context=context,
            max_records=max_records,
        )
    coverage = _coverage_summary(
        store,
        project_id=project_id,
        scope_paths=normalized_scope,
    )
    return {
        "project_id": project_id,
        "scope_resolved_from": scope_resolved_from,
        "records": records_payload,
        "record_count": len(records_payload),
        "truncated": truncated,
        "coverage": coverage,
    }


def _parse_filters(
    filters: Mapping[str, object] | None,
) -> tuple[
    tuple[MemoryRecordType, ...],
    tuple[MemoryStatus, ...],
    tuple[MemoryConfidence, ...],
]:
    types: list[MemoryRecordType] = []
    statuses: list[MemoryStatus] = []
    confidences: list[MemoryConfidence] = []
    if filters is None:
        return (), (), ()
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
    return tuple(types), tuple(statuses), tuple(confidences)


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
) -> dict[str, object]:
    if mode not in QUERY_MODES:
        raise MemoryContractError(
            f"Unknown query mode {mode!r}. Allowed: {', '.join(QUERY_MODES)}."
        )

    if mode == "status":
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

    if mode == "get":
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
            "payload": {
                "record": _serialize_record_summary(
                    record=record,
                    subjects=subjects,
                    evidence_count=len(evidence),
                ),
                "evidence": [_serialize_evidence(item) for item in evidence],
            },
        }

    if mode == "stale":
        records = store.query_records(
            MemoryQuery(
                project_id=project_id,
                statuses=("stale",),
                limit=max_results,
            )
        )
        payload_records = [
            _serialize_record_summary(
                record=record,
                subjects=store.list_subjects_for_memory(record.id),
                evidence_count=store.count_evidence_for_memory(record.id),
            )
            for record in records
        ]
        return {
            "mode": mode,
            "status": "ok",
            "payload": {
                "records": payload_records,
                "record_count": len(payload_records),
                "truncated": len(records) >= max_results,
            },
        }

    if mode == "coverage":
        scope_paths = [normalize_repo_path(item) for item in (scope or ())]
        coverage = _coverage_summary(
            store,
            project_id=project_id,
            scope_paths=scope_paths,
        )
        return {"mode": mode, "status": "ok", "payload": coverage}

    filter_types, filter_statuses, filter_confidences = _parse_filters(filters)
    statuses = filter_statuses or _default_statuses(
        include_stale=include_stale,
        include_drafts=include_drafts,
    )

    if mode == "search":
        if not query or not query.strip():
            raise MemoryContractError("mode=search requires query.")
        records = store.search_records(
            project_id=project_id,
            statement_query=query.strip(),
            types=filter_types,
            statuses=statuses,
            confidences=filter_confidences,
            limit=max_results + 1,
        )
    elif mode == "for_path":
        if not path:
            raise MemoryContractError("mode=for_path requires path.")
        normalized = normalize_repo_path(path)
        records = store.query_records(
            MemoryQuery(
                project_id=project_id,
                types=filter_types,
                statuses=statuses,
                subject_kind="path",
                subject_key_prefix=normalized,
                limit=max_results + 1,
            )
        )
        if len(records) < max_results + 1:
            module_key = PurePosixPath(normalized).as_posix().replace("/", ".")
            module_records = store.query_records(
                MemoryQuery(
                    project_id=project_id,
                    types=filter_types,
                    statuses=statuses,
                    subject_kind="module",
                    subject_key_prefix=module_key,
                    limit=max_results + 1,
                )
            )
            seen = {record.id for record in records}
            for record in module_records:
                if record.id not in seen:
                    records = (*records, record)
    elif mode == "for_symbol":
        if not symbol:
            raise MemoryContractError("mode=for_symbol requires symbol.")
        records = store.query_records(
            MemoryQuery(
                project_id=project_id,
                types=filter_types,
                statuses=statuses,
                subject_kind="symbol",
                subject_key=symbol.strip(),
                limit=max_results + 1,
            )
        )
    else:
        records = ()

    visible = [
        record
        for record in records
        if _record_visible(
            record,
            include_stale=include_stale,
            include_drafts=include_drafts,
        )
    ]
    truncated = len(visible) > max_results
    selected = visible[:max_results]
    payload_records = [
        _serialize_record_summary(
            record=record,
            subjects=store.list_subjects_for_memory(record.id),
            evidence_count=store.count_evidence_for_memory(record.id),
        )
        for record in selected
    ]
    return {
        "mode": mode,
        "status": "ok",
        "payload": {
            "records": payload_records,
            "record_count": len(payload_records),
            "truncated": truncated,
        },
    }


__all__ = [
    "QUERY_MODES",
    "QueryMode",
    "get_relevant_memory",
    "normalize_repo_path",
    "query_engineering_memory",
]
