# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import TYPE_CHECKING, Protocol

from .exceptions import MemoryContractError
from .models import (
    IngestionRun,
    MemoryEvidence,
    MemoryLink,
    MemoryProject,
    MemoryQuery,
    MemoryRecord,
    MemoryRevision,
    MemorySubject,
    RecordBatch,
    UpsertResult,
)

if TYPE_CHECKING:
    # Annotation-only: the lane packages import this module, so a runtime
    # import here would close a cycle.
    from .experience.models import Experience
    from .trajectory.models import Trajectory

MEMORY_ID_CANDIDATE_LIMIT = 10
"""Upper bound on candidates listed for one ambiguous short-id resolution."""


_MemoryStoreParam = str | int | float | bytes | None


def memory_id_prefix_range(prefix: str) -> tuple[str, str]:
    """Half-open ``[lo, hi)`` id range covering exactly the ``prefix`` matches.

    A lexicographic range on the primary key rather than ``LIKE``/``GLOB``:
    no escaping of wildcard characters and no case-folding surprises, and the
    index on ``id`` stays usable. Incrementing the final character is a valid
    upper bound because ids continue in lowercase hex, every continuation of
    which sorts below the incremented character.
    """
    if not prefix:
        msg = "id prefix must not be empty."
        raise MemoryContractError(msg)
    return prefix, f"{prefix[:-1]}{chr(ord(prefix[-1]) + 1)}"


def memory_id_prefix_clauses(
    *,
    prefix: str,
    project_id: str,
) -> tuple[list[str], list[_MemoryStoreParam]]:
    """The predicate every lane shares: id within range, owned by the project."""
    lo, hi = memory_id_prefix_range(prefix)
    return ["id>=?", "id<?", "project_id=?"], [lo, hi, project_id]


def count_id_prefix_matches(
    conn: sqlite3.Connection,
    *,
    table: str,
    where: str,
    params: Sequence[_MemoryStoreParam],
) -> int:
    """Exact total for a prefix predicate, independent of any candidate cap.

    Table-agnostic on purpose: each lane store owns its table name and
    visibility predicate and passes them in, so this stays the single
    implementation of *how* a prefix is counted without becoming a second
    place that knows *what* any lane's rows look like.
    """
    row = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", params).fetchone()
    return int(row[0])


class EngineeringMemoryStore(Protocol):
    def initialize(self, project: MemoryProject) -> None: ...
    def get_meta(self, key: str) -> str | None: ...
    def set_meta(self, key: str, value: str) -> None: ...
    def write_record(self, record: MemoryRecord) -> None: ...
    def upsert_record(self, record: MemoryRecord) -> UpsertResult: ...
    def find_record(self, record_id: str) -> MemoryRecord | None: ...

    # Short-id resolution, one method per lane. Lanes stay separate by
    # doctrine: there is deliberately no cross-lane resolver, because a
    # caller always knows which lane it is addressing. Each resolver applies
    # its lane's own visibility predicate plus project_id, so an object the
    # lane would not serve can neither resolve nor leak its existence.
    def resolve_record_id_prefix(
        self,
        *,
        project_id: str,
        prefix: str,
        limit: int = MEMORY_ID_CANDIDATE_LIMIT,
    ) -> tuple[list[MemoryRecord], int]: ...
    def resolve_trajectory_id_prefix(
        self,
        *,
        project_id: str,
        prefix: str,
        limit: int = MEMORY_ID_CANDIDATE_LIMIT,
    ) -> tuple[list[Trajectory], int]: ...
    def resolve_experience_id_prefix(
        self,
        *,
        project_id: str,
        prefix: str,
        limit: int = MEMORY_ID_CANDIDATE_LIMIT,
    ) -> tuple[list[Experience], int]: ...
    def find_by_identity_key(
        self, project_id: str, key: str
    ) -> MemoryRecord | None: ...
    def query_records(self, query: MemoryQuery) -> Sequence[MemoryRecord]: ...
    def write_subject(self, subject: MemorySubject) -> None: ...
    def write_evidence(self, evidence: MemoryEvidence) -> None: ...
    def write_link(self, link: MemoryLink) -> None: ...
    def write_ingestion_run(self, run: IngestionRun) -> None: ...
    def write_revision(self, revision: MemoryRevision) -> None: ...
    def mark_stale(self, record_id: str, reason: str) -> None: ...
    def persist_batch(
        self, batch: RecordBatch, *, commit: bool = True
    ) -> dict[str, int]: ...
    def close(self) -> None: ...

    @contextmanager
    def transaction(self) -> Iterator[None]: ...

    @contextmanager
    def exclusive_init_lock(self) -> Iterator[None]: ...


__all__ = [
    "MEMORY_ID_CANDIDATE_LIMIT",
    "EngineeringMemoryStore",
    "count_id_prefix_matches",
    "memory_id_prefix_clauses",
    "memory_id_prefix_range",
]
