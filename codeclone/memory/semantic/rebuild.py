# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ...observability import is_observability_enabled, span
from ...utils.iterutils import chunked
from ..embedding import embed_documents
from ..embedding.batching import (
    EmbedBatchLimits,
    EmbedBatchPlan,
    LengthScoredItem,
    pack_adaptive_batches,
    score_lengths,
)
from ..embedding.length import estimate_char_counts, estimate_document_tokens
from .models import SemanticProjection, SemanticRow, SemanticRowFingerprint

if TYPE_CHECKING:
    from ..embedding import EmbeddingProvider
    from . import SemanticIndexWriter
    from .sources import IndexSource

DEFAULT_EMBED_BATCH_SIZE = 64
# Source projections fingerprinted per round-trip before embedding the changed
# subset — bounds the changed/unchanged partition for very large corpora.
_FINGERPRINT_PAGE_SIZE = 256


@dataclass(frozen=True, slots=True)
class RebuildReport:
    """Outcome of a semantic rebuild: indexed total, deletions, and the
    embedded vs hash-skipped split (per source)."""

    indexed: int
    deleted: int = 0
    embedded: int = 0
    skipped_unchanged: int = 0
    by_source: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _SourceIndexStats:
    seen_ids: set[str]
    embedded: int
    skipped_unchanged: int


def rebuild_semantic_index(
    *,
    writer: SemanticIndexWriter,
    provider: EmbeddingProvider,
    sources: Sequence[IndexSource],
    embed_batch_limits: EmbedBatchLimits | None = None,
) -> RebuildReport:
    """Reconcile the semantic index against its sources by content hash.

    A row is re-embedded only when its projection ``text_hash`` (or the
    embedding model) differs from the stored fingerprint; unchanged rows are
    skipped without loading their vectors, so an unchanged corpus never loads
    the embedding model. The index is a derived, rebuildable sidecar, never
    updated on the write hot path.
    """
    limits = embed_batch_limits or EmbedBatchLimits()
    by_source: dict[str, int] = {}
    seen_ids: set[str] = set()
    embedded = 0
    skipped = 0
    for source in sources:
        if not source.available():
            continue
        with span(name=f"memory.semantic.source.{source.name()}"):
            stats = _index_source(
                source,
                writer=writer,
                provider=provider,
                embed_batch_limits=limits,
            )
        if stats.seen_ids:
            by_source[source.name()] = len(stats.seen_ids)
            seen_ids |= stats.seen_ids
        embedded += stats.embedded
        skipped += stats.skipped_unchanged
    deleted = 0
    with span(name="memory.semantic.reconcile") as reconcile_span:
        # Reconcile deletions: known_ids projects ids only (no vectors), so the
        # delete pass stays cheap even on a large index.
        stale = writer.known_ids() - seen_ids
        if stale:
            writer.delete(sorted(stale))
        deleted = len(stale)
        if is_observability_enabled():
            reconcile_span.set_counter("indexed", len(seen_ids))
            reconcile_span.set_counter("deleted", deleted)
    return RebuildReport(
        indexed=len(seen_ids),
        deleted=deleted,
        embedded=embedded,
        skipped_unchanged=skipped,
        by_source=by_source,
    )


def _index_source(
    source: IndexSource,
    *,
    writer: SemanticIndexWriter,
    provider: EmbeddingProvider,
    embed_batch_limits: EmbedBatchLimits,
) -> _SourceIndexStats:
    seen: set[str] = set()
    embedded = 0
    skipped = 0
    for page in chunked(source.iter_projections(), _FINGERPRINT_PAGE_SIZE):
        ids = [projection.source_id for projection in page]
        seen.update(ids)
        fingerprints = writer.row_fingerprints(ids)
        changed = [
            projection
            for projection in page
            if _needs_embed(
                fingerprints.get(projection.source_id),
                projection,
                provider.model_id,
            )
        ]
        skipped += len(page) - len(changed)
        embedded += _embed_and_upsert(
            changed,
            writer=writer,
            provider=provider,
            embed_batch_limits=embed_batch_limits,
        )
    return _SourceIndexStats(
        seen_ids=seen,
        embedded=embedded,
        skipped_unchanged=skipped,
    )


def _embed_and_upsert(
    projections: Sequence[SemanticProjection],
    *,
    writer: SemanticIndexWriter,
    provider: EmbeddingProvider,
    embed_batch_limits: EmbedBatchLimits,
) -> int:
    if not projections:
        return 0
    texts = [projection.text for projection in projections]
    char_counts = estimate_char_counts(texts)
    token_counts = estimate_document_tokens(provider, texts)
    scored: tuple[LengthScoredItem[SemanticProjection], ...] = score_lengths(
        list(projections),
        char_counts=char_counts,
        token_counts=token_counts,
        source_kinds=[projection.source for projection in projections],
        source_ids=[projection.source_id for projection in projections],
    )
    batches: list[EmbedBatchPlan[SemanticProjection]] = pack_adaptive_batches(
        scored, limits=embed_batch_limits
    )
    embedded = 0
    with span(name="memory.semantic.embed") as embed_span:
        if is_observability_enabled():
            embed_span.set_counter("max_documents", embed_batch_limits.max_documents)
            embed_span.set_counter(
                "max_padded_tokens", embed_batch_limits.max_padded_tokens
            )
            embed_span.set_counter("pending", len(projections))
            embed_span.set_counter("batches", len(batches))
        for batch in batches:
            batch_projections = [item.item for item in batch.items]
            infer_counters = {
                "documents": len(batch.items),
                "total_chars": batch.total_chars,
                "max_chars": batch.max_chars,
                "total_tokens": batch.total_tokens,
                "max_tokens": batch.max_tokens,
                "padded_tokens": batch.padded_tokens,
                "padding_amplification_permille": batch.padding_amplification_permille,
            }
            vectors = embed_documents(
                provider,
                [projection.text for projection in batch_projections],
                infer_counters=infer_counters,
            )
            writer.upsert(
                [
                    _row(projection, vector, provider.model_id)
                    for projection, vector in zip(
                        batch_projections, vectors, strict=True
                    )
                ]
            )
            embedded += len(batch_projections)
        if is_observability_enabled():
            embed_span.set_counter("embedded", embedded)
    return embedded


def _needs_embed(
    fingerprint: SemanticRowFingerprint | None,
    projection: SemanticProjection,
    model_id: str,
) -> bool:
    if fingerprint is None:
        return True
    return (
        fingerprint.text_hash != projection.text_hash
        or fingerprint.embedding_model != model_id
    )


def _row(
    projection: SemanticProjection,
    vector: Sequence[float],
    model_id: str,
) -> SemanticRow:
    return SemanticRow(
        id=projection.source_id,
        source=projection.source,
        project_id=projection.project_id,
        subject_path=projection.subject_path,
        kind=projection.kind,
        status=projection.status,
        text_hash=projection.text_hash,
        embedding_model=model_id,
        vector=tuple(vector),
    )


__all__ = [
    "DEFAULT_EMBED_BATCH_SIZE",
    "RebuildReport",
    "rebuild_semantic_index",
]
