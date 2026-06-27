# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Iterator, Sequence

from codeclone.memory.embedding.batching import EmbedBatchLimits
from codeclone.memory.semantic.models import (
    ExistingSourceRevision,
    SemanticHit,
    SemanticIndexStatus,
    SemanticProjection,
    SemanticRow,
    SemanticRowFingerprint,
)
from codeclone.memory.semantic.projection import text_hash
from codeclone.memory.semantic.rebuild import rebuild_semantic_index
from codeclone.memory.semantic.sources import SourceScan


class _InMemoryWriter:
    """Faithful in-memory SemanticIndexWriter: stores rows, answers fingerprint
    lookups from the stored text_hash/model — never returns vectors to check
    freshness."""

    def __init__(self) -> None:
        self.rows: dict[str, SemanticRow] = {}

    def search(
        self, vector: Sequence[float], *, k: int, source: str | None = None
    ) -> list[SemanticHit]:
        return []

    def status(self) -> SemanticIndexStatus:
        return SemanticIndexStatus(available=True)

    def upsert(self, rows: Sequence[SemanticRow]) -> None:
        for row in rows:
            self.rows[row.id] = row

    def delete(self, ids: Sequence[str]) -> None:
        for row_id in ids:
            self.rows.pop(row_id, None)

    def known_ids(self) -> set[str]:
        return set(self.rows)

    def row_fingerprints(self, ids: Sequence[str]) -> dict[str, SemanticRowFingerprint]:
        out: dict[str, SemanticRowFingerprint] = {}
        for row_id in ids:
            row = self.rows.get(row_id)
            if row is not None:
                out[row_id] = SemanticRowFingerprint(
                    id=row_id,
                    text_hash=row.text_hash,
                    embedding_model=row.embedding_model,
                    source_revision=row.source_revision,
                )
        return out

    def existing_revisions(self) -> dict[str, ExistingSourceRevision]:
        # Single-pass accumulation: every row of a source shares its revision and
        # model, so each row just folds its id into the (immutably rebuilt) entry.
        revisions: dict[str, ExistingSourceRevision] = {}
        for row in self.rows.values():
            key = row.parent_id or row.id
            seen = revisions.get(key)
            row_ids = seen.row_ids | {row.id} if seen else frozenset({row.id})
            revisions[key] = ExistingSourceRevision(
                source=row.source,
                source_revision=row.source_revision,
                embedding_model=row.embedding_model,
                row_ids=row_ids,
            )
        return revisions


class _CountingProvider:
    def __init__(self, model_id: str = "test-model") -> None:
        self.model_id = model_id
        self.dimension = 3
        self.embed_calls = 0
        self.embedded_texts = 0

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        batch = list(texts)
        self.embed_calls += 1
        self.embedded_texts += len(batch)
        return [[float(len(text)), 0.0, 0.0] for text in batch]

    def embed_documents(
        self,
        texts: Sequence[str],
        *,
        infer_counters: object | None = None,
    ) -> list[list[float]]:
        return self.embed(texts)

    def estimate_token_counts(self, texts: Sequence[str]) -> tuple[int, ...]:
        return tuple(max(1, len(text) // 4) for text in texts)

    def max_sequence_tokens(self) -> int | None:
        return None


class _FakeSource:
    def __init__(self, projections: Sequence[SemanticProjection]) -> None:
        self._projections = list(projections)

    def name(self) -> str:
        return "memory"

    def available(self) -> bool:
        return True

    def iter_projections(self) -> Iterator[SemanticProjection]:
        yield from self._projections

    def scan(self) -> SourceScan:
        return SourceScan(
            revisions={p.source_id: p.source_revision for p in self._projections}
        )

    def project(self, source_ids: Sequence[str]) -> Iterator[SemanticProjection]:
        wanted = set(source_ids)
        return iter([p for p in self._projections if p.source_id in wanted])


def _projection(source_id: str, text: str) -> SemanticProjection:
    return SemanticProjection(
        source="memory",
        source_id=source_id,
        kind="memory",
        text=text,
        text_hash=text_hash(text),
        # Simulate a content-derived revision: changed text -> changed revision,
        # so the partition skips re-projecting unchanged ids on the second run.
        source_revision=f"rev::{text_hash(text)}",
    )


def _corpus(count: int) -> list[SemanticProjection]:
    return [_projection(f"id-{i}", f"text {i}") for i in range(count)]


def test_first_run_embeds_all() -> None:
    writer, provider = _InMemoryWriter(), _CountingProvider()
    report = rebuild_semantic_index(
        writer=writer, provider=provider, sources=[_FakeSource(_corpus(100))]
    )
    assert report.indexed == 100
    assert report.embedded == 100
    assert report.skipped_unchanged == 0
    assert provider.embedded_texts == 100


def test_unchanged_corpus_embeds_nothing_on_second_run() -> None:
    writer = _InMemoryWriter()
    corpus = _corpus(100)
    rebuild_semantic_index(
        writer=writer, provider=_CountingProvider(), sources=[_FakeSource(corpus)]
    )
    provider = _CountingProvider()
    report = rebuild_semantic_index(
        writer=writer, provider=provider, sources=[_FakeSource(corpus)]
    )
    assert report.indexed == 100
    assert report.embedded == 0
    assert report.skipped_unchanged == 100
    # The model is never asked to embed — this is what bounds RSS.
    assert provider.embed_calls == 0
    assert provider.embedded_texts == 0


def test_changed_text_re_embeds_only_that_row() -> None:
    writer = _InMemoryWriter()
    corpus = _corpus(10)
    rebuild_semantic_index(
        writer=writer, provider=_CountingProvider(), sources=[_FakeSource(corpus)]
    )
    changed = list(corpus)
    changed[3] = _projection("id-3", "text 3 rewritten")
    provider = _CountingProvider()
    report = rebuild_semantic_index(
        writer=writer, provider=provider, sources=[_FakeSource(changed)]
    )
    assert report.embedded == 1
    assert report.skipped_unchanged == 9
    assert provider.embedded_texts == 1


def test_embedding_model_change_re_embeds_all() -> None:
    writer = _InMemoryWriter()
    corpus = _corpus(5)
    rebuild_semantic_index(
        writer=writer,
        provider=_CountingProvider(model_id="model-a"),
        sources=[_FakeSource(corpus)],
    )
    provider = _CountingProvider(model_id="model-b")
    report = rebuild_semantic_index(
        writer=writer, provider=provider, sources=[_FakeSource(corpus)]
    )
    assert report.embedded == 5
    assert report.skipped_unchanged == 0


def test_removed_source_id_is_reconciled() -> None:
    writer = _InMemoryWriter()
    corpus = _corpus(5)
    rebuild_semantic_index(
        writer=writer, provider=_CountingProvider(), sources=[_FakeSource(corpus)]
    )
    report = rebuild_semantic_index(
        writer=writer,
        provider=_CountingProvider(),
        sources=[_FakeSource(corpus[:4])],
    )
    assert report.deleted == 1
    assert "id-4" not in writer.known_ids()


def test_changed_rows_embedded_in_bounded_batches() -> None:
    writer = _InMemoryWriter()
    provider = _CountingProvider()
    rebuild_semantic_index(
        writer=writer,
        provider=provider,
        sources=[_FakeSource(_corpus(10))],
        embed_batch_limits=EmbedBatchLimits(max_documents=3, max_padded_tokens=100_000),
    )
    # 10 new rows, batch size 3 -> 4 embed calls (3+3+3+1); peak RAM bounded.
    assert provider.embed_calls == 4
    assert provider.embedded_texts == 10
