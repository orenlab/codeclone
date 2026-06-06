# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from ..embedding import embed_query
from ..semantic.models import SemanticSearchResult

if TYPE_CHECKING:
    from ..embedding import EmbeddingProvider
    from ..models import MemoryRecord, MemorySubject
    from ..semantic import SemanticHit, SemanticIndex
    from ..trajectory.models import Trajectory


class _RecordStore(Protocol):
    def find_record(self, record_id: str) -> MemoryRecord | None: ...

    def list_subjects_for_memory(self, memory_id: str) -> list[MemorySubject]: ...


def semantic_search(
    *,
    index: SemanticIndex,
    provider: EmbeddingProvider,
    store: _RecordStore | None,
    audit_db_path: Path,
    query: str,
    limit: int,
    preview_chars: int,
) -> list[SemanticSearchResult]:
    """Embed the query, search the index, and hydrate hits from the source.

    The index supplies ids + proximity only; the returned record/event is
    always loaded from SQLite / the audit DB (truth never lives in the vector
    row). Stale hits whose record/event no longer exists are skipped.
    """
    vector = embed_query(provider, query)
    results: list[SemanticSearchResult] = []
    for hit in index.search(vector, k=limit):
        if hit.source == "memory":
            hydrated = (
                _hydrate_memory(hit, store, preview_chars)
                if store is not None
                else None
            )
        elif hit.source == "audit":
            hydrated = _hydrate_audit(hit, audit_db_path, preview_chars)
        else:
            hydrated = (
                _hydrate_trajectory(hit, store, preview_chars)
                if store is not None
                else None
            )
        if hydrated is not None:
            results.append(hydrated)
    return results


def _hydrate_memory(
    hit: SemanticHit, store: _RecordStore, preview_chars: int
) -> SemanticSearchResult | None:
    record = store.find_record(hit.source_id)
    if record is None:
        return None
    return SemanticSearchResult(
        source="memory",
        source_id=hit.source_id,
        score=hit.score,
        kind=record.type,
        status=record.status,
        confidence=record.confidence,
        subject_path=_primary_path(store.list_subjects_for_memory(record.id)),
        preview=_preview(record.statement, preview_chars),
    )


def _hydrate_audit(
    hit: SemanticHit, audit_db_path: Path, preview_chars: int
) -> SemanticSearchResult | None:
    row = audit_event_row(audit_db_path, hit.source_id)
    if row is None:
        return None
    event_type, status, summary = row
    return SemanticSearchResult(
        source="audit",
        source_id=hit.source_id,
        score=hit.score,
        kind=event_type,
        status=status,
        confidence=None,
        subject_path=None,
        preview=_preview(summary, preview_chars),
    )


def _hydrate_trajectory(
    hit: SemanticHit, store: _RecordStore, preview_chars: int
) -> SemanticSearchResult | None:
    find_trajectory = getattr(store, "find_trajectory", None)
    if not callable(find_trajectory):
        return None
    typed_find = cast("Callable[[str], Trajectory | None]", find_trajectory)
    trajectory = typed_find(hit.source_id)
    if trajectory is None:
        return None
    return SemanticSearchResult(
        source="trajectory",
        source_id=hit.source_id,
        score=hit.score,
        kind="trajectory",
        status=trajectory.outcome,
        confidence=None,
        subject_path=_primary_trajectory_path(trajectory),
        preview=_preview(trajectory.summary, preview_chars),
    )


def audit_event_row(
    audit_db_path: Path, event_id: str
) -> tuple[str, str | None, str] | None:
    if not audit_db_path.is_file():
        return None
    try:
        conn = sqlite3.connect(str(audit_db_path))
    except sqlite3.Error:
        return None
    try:
        row = conn.execute(
            "SELECT event_type, status, summary FROM controller_events "
            "WHERE event_id = ?",
            (event_id,),
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    if row is None or not isinstance(row[2], str) or not row[2].strip():
        return None
    status = str(row[1]) if row[1] is not None else None
    return str(row[0]), status, row[2]


def _primary_path(subjects: Sequence[MemorySubject]) -> str | None:
    for subject in subjects:
        if subject.subject_kind == "path":
            return subject.subject_key
    return None


def _primary_trajectory_path(trajectory: Trajectory) -> str | None:
    for subject in trajectory.subjects:
        if subject.subject_kind == "path":
            return subject.subject_key
    return None


def _preview(text: str, preview_chars: int) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= preview_chars:
        return cleaned
    return cleaned[: max(1, preview_chars - 1)].rstrip() + "…"


__all__ = ["audit_event_row", "semantic_search"]
