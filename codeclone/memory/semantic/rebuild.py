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
from .models import ExistingSourceRevision, SemanticRow, SemanticRowFingerprint
from .sources import SourceScanError

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
    embedded vs skipped-unchanged split (per source).

    ``incomplete_lanes`` names sources whose scan was degraded this cycle; those
    lanes were preserved (no pruning) instead of reconciled, so the rebuild is
    advisory-degraded rather than authoritative for them.
    """

    indexed: int
    deleted: int = 0
    embedded: int = 0
    skipped_unchanged: int = 0
    by_source: dict[str, int] = field(default_factory=dict)
    incomplete_lanes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _SourceIndexStats:
    seen_ids: set[str]
    embedded: int
    skipped_unchanged: int
    document_count: int = 0


def rebuild_semantic_index(
    *,
    writer: SemanticIndexWriter,
    provider: EmbeddingProvider,
    sources: Sequence[IndexSource],
    embed_batch_limits: EmbedBatchLimits | None = None,
) -> RebuildReport:
    """Reconcile the semantic index against its sources by source revision.

    Each source is scanned for a cheap ``source_revision`` per current row (no
    projection, no full hydration). Only sources whose revision differs from the
    stored one are re-projected and re-embedded; an unchanged source is never
    sourced past the scan, so an unchanged corpus does no projection, embedding,
    or row writes. A source whose scan is degraded preserves its lane (its stored
    rows are kept and never pruned). The index is a derived, rebuildable sidecar,
    never updated on the write hot path.
    """
    limits = embed_batch_limits or EmbedBatchLimits()
    chunker = resolve_passage_chunker(provider)
    # One metadata scan of the stored rows, diffed per source against each
    # source's cheap revision scan. A degraded source (SourceScanError or a
    # non-complete scan status) preserves its lane: pruning, which is
    # destructive, is gated off for the whole cycle and the lane's stored rows
    # stay in seen_ids — a transient failure must never masquerade as an empty
    # source and delete still-live rows.
    existing = writer.existing_revisions()
    scanned: list[tuple[str, _SourceIndexStats]] = []
    incomplete_lanes: list[str] = []
    for source in sources:
        if not source.available():
            continue
        stats = _scan_source(
            source,
            writer=writer,
            provider=provider,
            chunker=chunker,
            existing=existing,
            embed_batch_limits=limits,
        )
        if stats is None:
            incomplete_lanes.append(source.name())
        else:
            scanned.append((source.name(), stats))
    seen_ids = {row_id for _, stats in scanned for row_id in stats.seen_ids}
    seen_ids |= _preserved_lane_rows(existing, incomplete_lanes)
    deleted = _reconcile(writer, seen_ids=seen_ids, prune=not incomplete_lanes)
    return RebuildReport(
        indexed=len(seen_ids),
        deleted=deleted,
        embedded=sum(stats.embedded for _, stats in scanned),
        skipped_unchanged=sum(stats.skipped_unchanged for _, stats in scanned),
        by_source={
            name: stats.document_count
            for name, stats in scanned
            if stats.document_count
        },
        incomplete_lanes=tuple(incomplete_lanes),
    )


def _preserved_lane_rows(
    existing: dict[str, ExistingSourceRevision],
    incomplete_lanes: Sequence[str],
) -> set[str]:
    """Every stored row id of a degraded lane, so reconcile keeps it this cycle."""
    if not incomplete_lanes:
        return set()
    lanes = set(incomplete_lanes)
    return {
        row_id
        for ex in existing.values()
        if ex.source in lanes
        for row_id in ex.row_ids
    }


def _scan_source(
    source: IndexSource,
    *,
    writer: SemanticIndexWriter,
    provider: EmbeddingProvider,
    chunker: PassageChunker,
    existing: dict[str, ExistingSourceRevision],
    embed_batch_limits: EmbedBatchLimits,
) -> _SourceIndexStats | None:
    """Index one source, or None when its scan was degraded (lane preserved)."""
    try:
        with span(name=f"memory.semantic.source.{source.name()}"):
            return _index_source(
                source,
                writer=writer,
                provider=provider,
                chunker=chunker,
                existing=existing,
                embed_batch_limits=embed_batch_limits,
            )
    except SourceScanError:
        return None


def _reconcile(
    writer: SemanticIndexWriter,
    *,
    seen_ids: set[str],
    prune: bool,
) -> int:
    """Delete rows absent from this rebuild. Pruning is skipped when ``prune`` is
    false (a source could not be read), so a transient read failure never deletes
    still-live rows; the deletions are simply deferred to the next clean rebuild."""
    with span(name="memory.semantic.reconcile") as reconcile_span:
        deleted = 0
        if prune:
            stale = writer.known_ids() - seen_ids
            if stale:
                writer.delete(sorted(stale))
            deleted = len(stale)
        if is_observability_enabled():
            reconcile_span.set_counter("indexed", len(seen_ids))
            reconcile_span.set_counter("deleted", deleted)
    return deleted


def _index_source(
    source: IndexSource,
    *,
    writer: SemanticIndexWriter,
    provider: EmbeddingProvider,
    chunker: PassageChunker,
    existing: dict[str, ExistingSourceRevision],
    embed_batch_limits: EmbedBatchLimits,
) -> _SourceIndexStats | None:
    scan = source.scan()
    if scan.status != "complete":
        return None
    lane = source.name()
    stored = {sid: ex for sid, ex in existing.items() if ex.source == lane}
    seen: set[str] = set()
    changed_ids: list[str] = []
    unchanged_rows = 0
    for source_id, revision in scan.revisions.items():
        ex = stored.get(source_id)
        # NEW (absent) / CHANGED (revision differs) / legacy ("" stored revision)
        # / model-swapped (rows built with a different embedding model) are all
        # re-projected; an unchanged source contributes its stored rows to
        # seen_ids without any projection or embedding.
        if (
            ex is None
            or ex.source_revision == ""
            or ex.source_revision != revision
            or ex.embedding_model != provider.model_id
        ):
            changed_ids.append(source_id)
        else:
            seen.update(ex.row_ids)
            unchanged_rows += len(ex.row_ids)
    changed_seen, embedded, skipped = _project_and_embed(
        source,
        changed_ids,
        writer=writer,
        provider=provider,
        chunker=chunker,
        embed_batch_limits=embed_batch_limits,
    )
    seen |= changed_seen
    return _SourceIndexStats(
        seen_ids=seen,
        embedded=embedded,
        skipped_unchanged=unchanged_rows + skipped,
        document_count=len(scan.revisions),
    )


def _project_and_embed(
    source: IndexSource,
    source_ids: Sequence[str],
    *,
    writer: SemanticIndexWriter,
    provider: EmbeddingProvider,
    chunker: PassageChunker,
    embed_batch_limits: EmbedBatchLimits,
) -> tuple[set[str], int, int]:
    """Project + embed only the changed ``source_ids``; returns their row ids
    (for seen_ids), the embedded count, and the text-hash/model skip count. Each
    batch is upserted (source_revision + vector together) before reconcile runs,
    so a crash mid-cycle leaves rows the next rebuild re-converges."""
    seen: set[str] = set()
    embedded = 0
    skipped = 0
    for page in chunked(source.project(source_ids), _FINGERPRINT_PAGE_SIZE):
        units: list[IndexedSemanticUnit] = []
        for projection in page:
            units.extend(expand_projection(projection, chunker))
        row_ids = [unit.row_id for unit in units]
        seen.update(row_ids)
        fingerprints = writer.row_fingerprints(row_ids)
        changed = [
            unit
            for unit in units
            if _needs_embed(fingerprints.get(unit.row_id), unit, provider.model_id)
        ]
        skipped += len(units) - len(changed)
        embedded += _embed_and_upsert(
            changed,
            writer=writer,
            provider=provider,
            embed_batch_limits=embed_batch_limits,
        )
    return seen, embedded, skipped


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
        or fingerprint.source_revision != unit.source_revision
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
        source_revision=unit.source_revision,
        vector=tuple(vector),
    )


__all__ = [
    "RebuildReport",
    "rebuild_semantic_index",
]
