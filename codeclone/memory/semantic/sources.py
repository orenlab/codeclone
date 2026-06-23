# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from ...audit.schema import open_audit_db_readonly
from ...audit.validation import AuditSchemaError
from ..models import MemoryQuery, MemoryRecord, MemorySubject
from ..trajectory.models import Trajectory, TrajectoryListItem
from .models import SemanticProjection
from .projection import (
    INDEXED_AUDIT_EVENTS,
    audit_content_token,
    is_indexed_memory_type,
    memory_content_token,
    project_audit_event,
    project_memory_record,
    project_trajectory,
    source_revision,
    trajectory_content_token,
)

# Live, retrievable statuses. rejected/archived/superseded are not surfaced by
# retrieval, so they are not embedded.
_INDEXED_STATUSES: frozenset[str] = frozenset({"active", "draft", "stale"})
_PAGE_SIZE = 200

# How completely a source could enumerate its current rows this cycle. Only a
# ``complete`` scan lets the rebuild prune that lane's stale rows; a degraded
# scan preserves the lane (Stage 1's all-or-nothing scan_failed gate, per lane).
ScanStatus = Literal["complete", "partial", "failed"]


class SourceScanError(Exception):
    """A source could not enumerate its current rows (a transient read failure).

    The rebuild treats the lane as *incomplete* and preserves it: a failed read
    must never masquerade as an empty source, or reconcile would delete the
    whole lane. ``available()`` returning False is a different, deliberate state
    (the source is off) and is reconciled as a complete-empty lane.
    """


@dataclass(frozen=True, slots=True)
class SourceScan:
    """A lane's full revision inventory plus how complete the scan was.

    ``revisions`` maps every current source id to its cheap ``source_revision``
    (no projection built, no full hydration). The rebuild diffs this against the
    stored revisions to project only what changed. ``status`` gates destructive
    reconcile: a degraded scan preserves the lane instead of pruning it.
    """

    revisions: dict[str, str]
    status: ScanStatus = "complete"


def _primary_path(subjects: Sequence[MemorySubject]) -> str | None:
    for subject in subjects:
        if subject.subject_kind == "path":
            return subject.subject_key
    return None


class IndexSource(Protocol):
    """A source of deterministic projections to feed the semantic index.

    Each source reports availability, scans a cheap revision inventory, and
    projects either every row (``iter_projections``, used by the projection
    probe) or only a changed subset (``project``, used by the incremental
    rebuild).
    """

    def name(self) -> str: ...

    def available(self) -> bool: ...

    def iter_projections(self) -> Iterator[SemanticProjection]: ...

    def scan(self) -> SourceScan:
        """Cheap full inventory of current source ids -> ``source_revision``,
        with no projection built and no full hydration. A read failure degrades
        the returned ``status`` instead of raising, so the rebuild preserves the
        lane rather than pruning it."""
        ...

    def project(self, source_ids: Sequence[str]) -> Iterator[SemanticProjection]:
        """Build deterministic projections for ``source_ids`` only (the changed
        subset from the revision partition). Empty ids yields nothing."""
        ...


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
        for records in self._iter_pages():
            yield from self._project_page(records)

    def scan(self) -> SourceScan:
        # Cheap inventory: single-table record scan, no subjects join and no
        # projection text built. Only the indexed prose/decision subset gets a
        # revision; everything else is not embedded, so it has no row to track.
        revisions: dict[str, str] = {}
        for records in self._iter_pages():
            for record in records:
                if self._is_indexed(record):
                    revisions[record.id] = source_revision(
                        source_kind="memory",
                        source_id=record.id,
                        content_token=memory_content_token(record),
                    )
        return SourceScan(revisions=revisions)

    def project(self, source_ids: Sequence[str]) -> Iterator[SemanticProjection]:
        wanted = set(source_ids)
        if not wanted:
            return
        for records in self._iter_pages():
            yield from self._project_page(records, wanted=wanted)

    def _iter_pages(self) -> Iterator[Sequence[MemoryRecord]]:
        offset = 0
        while True:
            records = self._store.query_records(
                MemoryQuery(
                    project_id=self._project_id,
                    limit=_PAGE_SIZE,
                    offset=offset,
                )
            )
            yield records
            if len(records) < _PAGE_SIZE:
                return
            offset += _PAGE_SIZE

    @staticmethod
    def _is_indexed(record: MemoryRecord) -> bool:
        return (
            is_indexed_memory_type(record.type) and record.status in _INDEXED_STATUSES
        )

    def _project_page(
        self,
        records: Sequence[MemoryRecord],
        *,
        wanted: set[str] | None = None,
    ) -> Iterator[SemanticProjection]:
        indexed = [
            record
            for record in records
            if self._is_indexed(record) and (wanted is None or record.id in wanted)
        ]
        # One batched subject load per page instead of a query per record; only
        # the projected (changed) subset pays the subjects join.
        subjects_by_id = self._store.list_subjects_for_memories(
            [record.id for record in indexed]
        )
        for record in indexed:
            yield project_memory_record(
                record,
                subject_path=_primary_path(subjects_by_id.get(record.id, [])),
            )


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
        for page in self._iter_list_pages():
            yield from self._hydrate_and_project(item.id for item in page)

    def scan(self) -> SourceScan:
        # Cheap inventory: the list scan already returns each trajectory_digest,
        # so a revision is derivable without hydrating (no find_trajectories) —
        # this is the lever that removes the full-hydration cost on an unchanged
        # corpus.
        revisions: dict[str, str] = {}
        for page in self._iter_list_pages():
            for item in page:
                revisions[item.id] = source_revision(
                    source_kind="trajectory",
                    source_id=item.id,
                    content_token=trajectory_content_token(
                        trajectory_digest=item.trajectory_digest
                    ),
                )
        return SourceScan(revisions=revisions)

    def project(self, source_ids: Sequence[str]) -> Iterator[SemanticProjection]:
        wanted = list(source_ids)
        if not wanted:
            return
        yield from self._hydrate_and_project(wanted)

    def _iter_list_pages(self) -> Iterator[Sequence[TrajectoryListItem]]:
        offset = 0
        while True:
            items = self._store.list_trajectories(
                project_id=self._project_id,
                limit=_PAGE_SIZE + offset,
            )
            page = items[offset : offset + _PAGE_SIZE]
            yield page
            if len(page) < _PAGE_SIZE:
                return
            offset += _PAGE_SIZE

    def _hydrate_and_project(
        self, trajectory_ids: Iterable[str]
    ) -> Iterator[SemanticProjection]:
        # Batch-hydrate instead of one find_trajectory per id.
        for trajectory in self._store.find_trajectories(list(trajectory_ids)):
            yield project_trajectory(trajectory)


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
        yield from self._iter_event_projections(only_ids=None)

    def scan(self) -> SourceScan:
        # Audit events are immutable, so a row's revision is just the projection
        # version: a new event_id is the only thing that changes the lane. An
        # unavailable source is a deliberate complete-empty lane (off, not
        # failed); a transient read failure degrades to ``failed`` (preserve).
        if not self.available():
            return SourceScan(revisions={})
        try:
            rows = self._fetch_event_rows(
                columns=("event_id", "summary"), only_ids=None
            )
        except SourceScanError:
            return SourceScan(revisions={}, status="failed")
        revisions: dict[str, str] = {}
        for event_id, summary in rows:
            if not isinstance(summary, str) or not summary.strip():
                continue
            eid = str(event_id)
            revisions[eid] = source_revision(
                source_kind="audit",
                source_id=eid,
                content_token=audit_content_token(),
            )
        return SourceScan(revisions=revisions)

    def project(self, source_ids: Sequence[str]) -> Iterator[SemanticProjection]:
        wanted = set(source_ids)
        if not wanted or not self.available():
            return
        yield from self._iter_event_projections(only_ids=wanted)

    def _iter_event_projections(
        self, *, only_ids: set[str] | None
    ) -> Iterator[SemanticProjection]:
        for event_id, event_type, summary in self._fetch_event_rows(
            columns=("event_id", "event_type", "summary"), only_ids=only_ids
        ):
            if not isinstance(summary, str) or not summary.strip():
                continue
            yield project_audit_event(
                event_id=str(event_id),
                event_type=str(event_type),
                summary=summary,
            )

    def _fetch_event_rows(
        self,
        *,
        columns: Sequence[str],
        only_ids: set[str] | None,
    ) -> list[tuple[object, ...]]:
        """Open the audit DB read-only and fetch the forensic event rows, raising
        ``SourceScanError`` on any read failure. ``columns`` is a fixed internal
        allow-list (never user input); ``only_ids`` adds an ``event_id IN (...)``
        filter for the changed-subset projection."""
        event_types = tuple(sorted(INDEXED_AUDIT_EVENTS))
        type_placeholders = ", ".join("?" for _ in event_types)
        sql = (
            f"SELECT {', '.join(columns)} FROM controller_events "
            "WHERE summary IS NOT NULL AND summary != '' "
            f"AND event_type IN ({type_placeholders}) "
        )
        params: list[object] = list(event_types)
        if only_ids is not None:
            id_placeholders = ", ".join("?" for _ in only_ids)
            sql += f"AND event_id IN ({id_placeholders}) "
            params.extend(sorted(only_ids))
        sql += "ORDER BY created_at_utc ASC, id ASC"
        try:
            conn = open_audit_db_readonly(self._db_path)
        except (sqlite3.Error, AuditSchemaError, OSError) as exc:
            raise SourceScanError("audit source could not open its database") from exc
        try:
            return conn.execute(sql, params).fetchall()
        except (sqlite3.Error, AuditSchemaError) as exc:
            raise SourceScanError("audit source could not read its events") from exc
        finally:
            conn.close()


__all__ = [
    "AuditIndexSource",
    "IndexSource",
    "MemoryIndexSource",
    "ScanStatus",
    "SourceScan",
    "SourceScanError",
    "TrajectoryIndexSource",
]
