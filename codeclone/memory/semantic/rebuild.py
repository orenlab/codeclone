# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..embedding import embed_documents
from .models import SemanticRow

if TYPE_CHECKING:
    from ..embedding import EmbeddingProvider
    from . import SemanticIndexWriter
    from .sources import IndexSource


@dataclass(frozen=True, slots=True)
class RebuildReport:
    """Outcome of a semantic rebuild: total projections indexed, by source."""

    indexed: int
    deleted: int = 0
    by_source: dict[str, int] = field(default_factory=dict)


def rebuild_semantic_index(
    *,
    writer: SemanticIndexWriter,
    provider: EmbeddingProvider,
    sources: Sequence[IndexSource],
) -> RebuildReport:
    """Rebuild the semantic index from the given sources.

    For each available source: project -> embed -> upsert. Idempotent by the
    projection ``text_hash`` carried on each row. The index is a derived,
    rebuildable sidecar, never updated on the write hot path.
    """
    by_source: dict[str, int] = {}
    seen_ids: set[str] = set()
    for source in sources:
        if not source.available():
            continue
        indexed_ids = _index_source(source, writer=writer, provider=provider)
        if indexed_ids:
            by_source[source.name()] = len(indexed_ids)
            seen_ids |= indexed_ids
    # Reconcile: drop indexed ids no longer produced by any source.
    stale = writer.known_ids() - seen_ids
    if stale:
        writer.delete(sorted(stale))
    return RebuildReport(
        indexed=len(seen_ids),
        deleted=len(stale),
        by_source=by_source,
    )


def _index_source(
    source: IndexSource,
    *,
    writer: SemanticIndexWriter,
    provider: EmbeddingProvider,
) -> set[str]:
    projections = list(source.iter_projections())
    if not projections:
        return set()
    vectors = embed_documents(provider, [projection.text for projection in projections])
    rows = [
        SemanticRow(
            id=projection.source_id,
            source=projection.source,
            project_id=projection.project_id,
            subject_path=projection.subject_path,
            kind=projection.kind,
            status=projection.status,
            text_hash=projection.text_hash,
            embedding_model=provider.model_id,
            vector=tuple(vector),
        )
        for projection, vector in zip(projections, vectors, strict=True)
    ]
    writer.upsert(rows)
    return {projection.source_id for projection in projections}


__all__ = [
    "RebuildReport",
    "rebuild_semantic_index",
]
