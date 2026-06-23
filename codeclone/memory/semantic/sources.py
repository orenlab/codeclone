# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Protocol

from ...audit.schema import open_audit_db_readonly
from ...audit.validation import AuditSchemaError
from ..models import MemoryQuery, MemoryRecord, MemorySubject
from ..trajectory.models import Trajectory, TrajectoryListItem
from .models import SemanticProjection
from .projection import (
    INDEXED_AUDIT_EVENTS,
    is_indexed_memory_type,
    project_audit_event,
    project_memory_record,
    project_trajectory,
)

# Live, retrievable statuses. rejected/archived/superseded are not surfaced by
# retrieval, so they are not embedded.
_INDEXED_STATUSES: frozenset[str] = frozenset({"active", "draft", "stale"})
_PAGE_SIZE = 200


class SourceScanError(Exception):
    """A source could not enumerate its current rows (a transient read failure).

    The rebuild treats the lane as *incomplete* and preserves it: a failed read
    must never masquerade as an empty source, or reconcile would delete the
    whole lane. ``available()`` returning False is a different, deliberate state
    (the source is off) and is reconciled as a complete-empty lane.
    """


def _primary_path(subjects: Sequence[MemorySubject]) -> str | None:
    for subject in subjects:
        if subject.subject_kind == "path":
            return subject.subject_key
    return None


class IndexSource(Protocol):
    """A source of deterministic projections to feed the semantic index.

    Each source reports availability and yields projections (or nothing); a
    rebuild iterates the available sources.
    """

    def name(self) -> str: ...

    def available(self) -> bool: ...

    def iter_projections(self) -> Iterator[SemanticProjection]: ...


class _MemoryReadStore(Protocol):
    """Minimal read surface MemoryIndexSource needs from the memory store."""

    def query_records(self, query: MemoryQuery) -> Sequence[MemoryRecord]: ...

    def list_subjects_for_memories(
        self, memory_ids: Sequence[str]
    ) -> dict[str, list[MemorySubject]]: ...


class _TrajectoryReadStore(Protocol):
    def list_trajectories(
        self,
        *,
        project_id: str,
        limit: int = 20,
    ) -> list[TrajectoryListItem]: ...

    def find_trajectories(self, trajectory_ids: Sequence[str]) -> list[Trajectory]: ...


class MemoryIndexSource:
    """Engineering Memory as a semantic index source.

    Always available (SQLite is truth). Yields deterministic projections for
    the prose/decision record subset only; structural records and
    non-retrievable statuses are skipped.
    """

    def __init__(self, store: _MemoryReadStore, *, project_id: str) -> None:
        self._store = store
        self._project_id = project_id

    def name(self) -> str:
        return "memory"

    def available(self) -> bool:
        return True

    def iter_projections(self) -> Iterator[SemanticProjection]:
        offset = 0
        while True:
            records = self._store.query_records(
                MemoryQuery(
                    project_id=self._project_id,
                    limit=_PAGE_SIZE,
                    offset=offset,
                )
            )
            indexed = [
                record
                for record in records
                if is_indexed_memory_type(record.type)
                and record.status in _INDEXED_STATUSES
            ]
            # One batched subject load per page instead of a query per record.
            subjects_by_id = self._store.list_subjects_for_memories(
                [record.id for record in indexed]
            )
            for record in indexed:
                yield project_memory_record(
                    record,
                    subject_path=_primary_path(subjects_by_id.get(record.id, [])),
                )
            if len(records) < _PAGE_SIZE:
                return
            offset += _PAGE_SIZE


class TrajectoryIndexSource:
    """Trajectory memory as a semantic source.

    Trajectories are derived projections over audit event core. The semantic
    source embeds their deterministic, bounded projection text only.
    """

    def __init__(self, store: _TrajectoryReadStore, *, project_id: str) -> None:
        self._store = store
        self._project_id = project_id

    def name(self) -> str:
        return "trajectory"

    def available(self) -> bool:
        return True

    def iter_projections(self) -> Iterator[SemanticProjection]:
        offset = 0
        while True:
            items = self._store.list_trajectories(
                project_id=self._project_id,
                limit=_PAGE_SIZE + offset,
            )
            page = items[offset : offset + _PAGE_SIZE]
            # Batch-hydrate the page instead of one find_trajectory per item.
            for trajectory in self._store.find_trajectories([item.id for item in page]):
                yield project_trajectory(trajectory)
            if len(page) < _PAGE_SIZE:
                return
            offset += _PAGE_SIZE


class AuditIndexSource:
    """Audit trail as an availability-gated semantic index source.

    Available only when audit is enabled and the DB file exists. Projects the
    bounded ``controller_events.summary`` column for forensic incident types.
    A missing DB, a pre-Bug-B schema without the ``summary`` column, or empty
    summaries simply contribute nothing — this source never raises.
    """

    def __init__(self, *, enabled: bool, db_path: Path) -> None:
        self._enabled = enabled
        self._db_path = db_path

    def name(self) -> str:
        return "audit"

    def available(self) -> bool:
        return self._enabled and self._db_path.is_file()

    def iter_projections(self) -> Iterator[SemanticProjection]:
        if not self.available():
            return
        yield from self._read_projections()

    def _read_projections(self) -> Iterator[SemanticProjection]:
        event_types = tuple(sorted(INDEXED_AUDIT_EVENTS))
        placeholders = ", ".join("?" for _ in event_types)
        try:
            conn = open_audit_db_readonly(self._db_path)
        except (sqlite3.Error, AuditSchemaError, OSError) as exc:
            raise SourceScanError("audit source could not open its database") from exc
        try:
            rows = conn.execute(
                "SELECT event_id, event_type, summary FROM controller_events "
                "WHERE summary IS NOT NULL AND summary != '' "
                f"AND event_type IN ({placeholders}) "
                "ORDER BY created_at_utc ASC, id ASC",
                event_types,
            ).fetchall()
        except (sqlite3.Error, AuditSchemaError) as exc:
            raise SourceScanError("audit source could not read its events") from exc
        finally:
            conn.close()
        for event_id, event_type, summary in rows:
            if not isinstance(summary, str) or not summary.strip():
                continue
            yield project_audit_event(
                event_id=str(event_id),
                event_type=str(event_type),
                summary=summary,
            )


__all__ = [
    "AuditIndexSource",
    "IndexSource",
    "MemoryIndexSource",
    "SourceScanError",
    "TrajectoryIndexSource",
]
