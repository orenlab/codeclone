# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .models import SemanticHit, SemanticProjection, SemanticSource
from .projection import text_hash

SEMANTIC_CHUNK_STRATEGY_VERSION: str = "1"
TRAJECTORY_SEARCH_OVERSAMPLE: int = 4


@dataclass(frozen=True, slots=True)
class IndexedSemanticUnit:
    """One embeddable semantic index row before vector assignment."""

    row_id: str
    parent_id: str | None
    chunk_index: int | None
    chunk_count: int | None
    source: SemanticSource
    project_id: str | None
    subject_path: str | None
    kind: str
    status: str | None
    text: str
    text_hash: str


@runtime_checkable
class PassageChunker(Protocol):
    def chunk_text(self, text: str) -> tuple[str, ...]: ...


class IdentityPassageChunker:
    """Single-chunk passthrough for providers without model truncation."""

    def chunk_text(self, text: str) -> tuple[str, ...]:
        return (text,)


def trajectory_chunk_row_id(parent_id: str, chunk_index: int) -> str:
    return f"trajectory:{parent_id}:chunk:{chunk_index:03d}"


def resolve_passage_chunker(provider: object) -> PassageChunker:
    from ..embedding.fastembed_provider import FastEmbedEmbeddingProvider

    if isinstance(provider, FastEmbedEmbeddingProvider):
        return provider
    return IdentityPassageChunker()


def expand_projection(
    projection: SemanticProjection,
    chunker: PassageChunker,
) -> tuple[IndexedSemanticUnit, ...]:
    if projection.source != "trajectory":
        return (
            _single_unit(projection, row_id=projection.source_id, text=projection.text),
        )
    chunks = chunker.chunk_text(projection.text)
    if len(chunks) == 1:
        return (_single_unit(projection, row_id=projection.source_id, text=chunks[0]),)
    parent_id = projection.source_id
    count = len(chunks)
    return tuple(
        IndexedSemanticUnit(
            row_id=trajectory_chunk_row_id(parent_id, index),
            parent_id=parent_id,
            chunk_index=index,
            chunk_count=count,
            source=projection.source,
            project_id=projection.project_id,
            subject_path=projection.subject_path,
            kind=projection.kind,
            status=projection.status,
            text=chunk,
            text_hash=text_hash(chunk),
        )
        for index, chunk in enumerate(chunks)
    )


def collapse_trajectory_hits(
    hits: Sequence[SemanticHit],
    *,
    k: int,
) -> list[SemanticHit]:
    best_by_parent: dict[str, SemanticHit] = {}
    for hit in hits:
        parent_id = hit.parent_id or hit.source_id
        existing = best_by_parent.get(parent_id)
        if existing is None or hit.score > existing.score:
            best_by_parent[parent_id] = hit
    ordered = sorted(best_by_parent.values(), key=lambda item: item.score, reverse=True)
    return ordered[: max(0, k)]


def trajectory_parent_id(hit: SemanticHit) -> str:
    return hit.parent_id or hit.source_id


def _single_unit(
    projection: SemanticProjection,
    *,
    row_id: str,
    text: str,
) -> IndexedSemanticUnit:
    return IndexedSemanticUnit(
        row_id=row_id,
        parent_id=None,
        chunk_index=None,
        chunk_count=None,
        source=projection.source,
        project_id=projection.project_id,
        subject_path=projection.subject_path,
        kind=projection.kind,
        status=projection.status,
        text=text,
        text_hash=text_hash(text),
    )


__all__ = [
    "SEMANTIC_CHUNK_STRATEGY_VERSION",
    "TRAJECTORY_SEARCH_OVERSAMPLE",
    "IdentityPassageChunker",
    "IndexedSemanticUnit",
    "PassageChunker",
    "collapse_trajectory_hits",
    "expand_projection",
    "resolve_passage_chunker",
    "trajectory_chunk_row_id",
    "trajectory_parent_id",
]
