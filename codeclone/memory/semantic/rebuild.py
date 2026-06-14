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
from .chunking import (
    IndexedSemanticUnit,
    PassageChunker,
    expand_projection,
    resolve_passage_chunker,
)
from .models import SemanticRow, SemanticRowFingerprint

if TYPE_CHECKING:
    from ..embedding import EmbeddingProvider
    from . import SemanticIndexWriter
    from .sources import IndexSource

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
    chunker = resolve_passage_chunker(provider)
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
                chunker=chunker,
                embed_batch_limits=limits,
            )
        if stats.seen_ids:
            by_source[source.name()] = _count_source_documents(source)
            seen_ids |= stats.seen_ids
        embedded += stats.embedded
        skipped += stats.skipped_unchanged
    deleted = 0
    with span(name="memory.semantic.reconcile") as reconcile_span:
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


def _count_source_documents(source: IndexSource) -> int:
    return sum(1 for _ in source.iter_projections())


def _index_source(
    source: IndexSource,
    *,
    writer: SemanticIndexWriter,
    provider: EmbeddingProvider,
    chunker: PassageChunker,
    embed_batch_limits: EmbedBatchLimits,
) -> _SourceIndexStats:
    seen: set[str] = set()
    embedded = 0
    skipped = 0
    for page in chunked(source.iter_projections(), _FINGERPRINT_PAGE_SIZE):
        units: list[IndexedSemanticUnit] = []
        for projection in page:
            units.extend(expand_projection(projection, chunker))
        row_ids = [unit.row_id for unit in units]
        seen.update(row_ids)
        fingerprints = writer.row_fingerprints(row_ids)
        changed = [
            unit
            for unit in units
            if _needs_embed(
                fingerprints.get(unit.row_id),
                unit,
                provider.model_id,
            )
        ]
        skipped += len(units) - len(changed)
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
    units: Sequence[IndexedSemanticUnit],
    *,
    writer: SemanticIndexWriter,
    provider: EmbeddingProvider,
    embed_batch_limits: EmbedBatchLimits,
) -> int:
    if not units:
        return 0
    texts = [unit.text for unit in units]
    char_counts = estimate_char_counts(texts)
    token_counts = estimate_document_tokens(provider, texts)
    scored: tuple[LengthScoredItem[IndexedSemanticUnit], ...] = score_lengths(
        list(units),
        char_counts=char_counts,
        token_counts=token_counts,
        source_kinds=[unit.source for unit in units],
        source_ids=[
            (
                f"{unit.parent_id or unit.row_id}:"
                f"{unit.chunk_index if unit.chunk_index is not None else 0}"
            )
            for unit in units
        ],
    )
    batches: list[EmbedBatchPlan[IndexedSemanticUnit]] = pack_adaptive_batches(
        scored, limits=embed_batch_limits
    )
    embedded = 0
    with span(name="memory.semantic.embed") as embed_span:
        if is_observability_enabled():
            embed_span.set_counter("max_documents", embed_batch_limits.max_documents)
            embed_span.set_counter(
                "max_padded_tokens", embed_batch_limits.max_padded_tokens
            )
            embed_span.set_counter("pending", len(units))
            embed_span.set_counter("batches", len(batches))
        for batch in batches:
            batch_units = [item.item for item in batch.items]
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
                [unit.text for unit in batch_units],
                infer_counters=infer_counters,
            )
            writer.upsert(
                [
                    _row(unit, vector, provider.model_id)
                    for unit, vector in zip(batch_units, vectors, strict=True)
                ]
            )
            embedded += len(batch_units)
        if is_observability_enabled():
            embed_span.set_counter("embedded", embedded)
    return embedded


def _needs_embed(
    fingerprint: SemanticRowFingerprint | None,
    unit: IndexedSemanticUnit,
    model_id: str,
) -> bool:
    if fingerprint is None:
        return True
    return (
        fingerprint.text_hash != unit.text_hash
        or fingerprint.embedding_model != model_id
    )


def _row(
    unit: IndexedSemanticUnit,
    vector: Sequence[float],
    model_id: str,
) -> SemanticRow:
    return SemanticRow(
        id=unit.row_id,
        source=unit.source,
        parent_id=unit.parent_id,
        chunk_index=unit.chunk_index,
        chunk_count=unit.chunk_count,
        project_id=unit.project_id,
        subject_path=unit.subject_path,
        kind=unit.kind,
        status=unit.status,
        text_hash=unit.text_hash,
        embedding_model=model_id,
        vector=tuple(vector),
    )


__all__ = [
    "RebuildReport",
    "rebuild_semantic_index",
]
