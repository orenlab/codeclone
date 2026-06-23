# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SemanticSource = Literal["memory", "audit", "trajectory"]


class SemanticProjection(BaseModel):
    """Deterministic, embeddable projection of a memory record or audit event.

    Pure data: the same source object always yields the same projection text
    and the same ``text_hash`` (the idempotent upsert key).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: SemanticSource
    source_id: str = Field(min_length=1)
    project_id: str | None = None
    kind: str = Field(min_length=1)
    subject_path: str | None = None
    status: str | None = None
    text: str = Field(min_length=1)
    text_hash: str = Field(min_length=1)
    # Cheap, projection-free revision key (Stage 2). Derived identically by the
    # inventory scan and the full projection, so an unchanged source row's stored
    # revision always equals its freshly scanned one. Default "" = legacy/unknown
    # = always changed; a real projection always sets a non-empty revision.
    source_revision: str = ""


class SemanticRow(BaseModel):
    """A single indexed vector row — what the backend stores and returns.

    The final record/event is always re-loaded from SQLite / the audit DB;
    this row only carries the vector and the filter/identity columns.
    Trajectory rows may be chunked: ``parent_id`` points at the trajectory id
    while ``id`` is the chunk row id.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    source: SemanticSource
    parent_id: str | None = None
    chunk_index: int | None = None
    chunk_count: int | None = None
    project_id: str | None = None
    subject_path: str | None = None
    kind: str = Field(min_length=1)
    status: str | None = None
    text_hash: str = Field(min_length=1)
    embedding_model: str = Field(min_length=1)
    source_revision: str = ""
    vector: tuple[float, ...]


class SemanticRowFingerprint(BaseModel):
    """Identity of a stored row without its vector.

    The incremental rebuild fetches these (id + ``text_hash`` + model +
    ``source_revision``) to decide what to re-embed, so it never loads vectors to
    check freshness. ``source_revision`` guarantees a revision-changed row is
    re-embedded (and its new revision persisted) even when its text is unchanged.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    text_hash: str = Field(min_length=1)
    embedding_model: str = Field(min_length=1)
    source_revision: str = ""


class ExistingSourceRevision(BaseModel):
    """Stored revision state for one source object, grouped from its index rows.

    The incremental rebuild reads these once (a single metadata scan, no vectors)
    to partition each lane's source ids into new / unchanged / changed / deleted.
    ``source_id`` is the row ``parent_id`` for chunked trajectories, else the row
    ``id``; every row of one source shares the same ``source_revision``, so the
    grouped value is unambiguous. ``row_ids`` are all index rows for that source
    (every chunk), used to keep unchanged rows in ``seen_ids`` during reconcile.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: SemanticSource
    source_revision: str = ""
    # Embedding model the stored rows were built with; a source whose revision is
    # unchanged but whose model differs from the current provider is still stale
    # (a model swap must re-embed every lane), so the partition checks both.
    embedding_model: str = ""
    row_ids: frozenset[str]


class SemanticHit(BaseModel):
    """A semantic search candidate: id + source + proximity score."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str = Field(min_length=1)
    source: SemanticSource
    score: float
    parent_id: str | None = None
    chunk_index: int | None = None
    chunk_count: int | None = None


class SemanticIndexStatus(BaseModel):
    """Transparent status of the semantic index (the observability contract).

    ``available=false`` with a ``reason`` is the fail-clear signal; ``provider``
    surfaces ``diagnostic`` so callers know hits are not real-model recall.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    available: bool
    backend: str | None = None
    provider: str | None = None
    embedding_model: str | None = None
    dimension: int | None = None
    indexed_count: int = 0
    reason: str | None = None


class SemanticSearchResult(BaseModel):
    """A hydrated semantic search hit: the proximity score plus record/event
    metadata and a bounded preview, loaded from the source of truth.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: SemanticSource
    source_id: str = Field(min_length=1)
    score: float
    kind: str = Field(min_length=1)
    status: str | None = None
    confidence: str | None = None
    subject_path: str | None = None
    preview: str = Field(min_length=1)


__all__ = [
    "ExistingSourceRevision",
    "SemanticHit",
    "SemanticIndexStatus",
    "SemanticProjection",
    "SemanticRow",
    "SemanticRowFingerprint",
    "SemanticSearchResult",
    "SemanticSource",
]
