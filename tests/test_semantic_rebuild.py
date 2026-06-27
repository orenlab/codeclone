# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

from collections.abc import Iterator, Sequence

import pytest

from codeclone.memory.embedding import DeterministicHashEmbeddingProvider
from codeclone.memory.semantic import RebuildReport, rebuild_semantic_index
from codeclone.memory.semantic.models import (
    ExistingSourceRevision,
    SemanticHit,
    SemanticIndexStatus,
    SemanticProjection,
    SemanticRow,
    SemanticRowFingerprint,
    SemanticSource,
)
from codeclone.memory.semantic.projection import text_hash
from codeclone.memory.semantic.sources import SourceScan, SourceScanError


class _FakeWriter:
    def __init__(self) -> None:
        self.rows: list[SemanticRow] = []

    def search(
        self, vector: Sequence[float], *, k: int, source: str | None = None
    ) -> list[SemanticHit]:
        rows = (
            self.rows
            if source is None
            else [row for row in self.rows if row.source == source]
        )
        return [
            SemanticHit(source_id=row.id, source=row.source, score=0.0)
            for row in rows[:k]
        ]

    def status(self) -> SemanticIndexStatus:
        return SemanticIndexStatus(
            available=True, backend="fake", indexed_count=len(self.rows)
        )

    def upsert(self, rows: Sequence[SemanticRow]) -> None:
        self.rows.extend(rows)

    def delete(self, ids: Sequence[str]) -> None:
        drop = set(ids)
        self.rows = [row for row in self.rows if row.id not in drop]

    def known_ids(self) -> set[str]:
        return {row.id for row in self.rows}

    def row_fingerprints(self, ids: Sequence[str]) -> dict[str, SemanticRowFingerprint]:
        by_id = {row.id: row for row in self.rows}
        return {
            row_id: SemanticRowFingerprint(
                id=row_id,
                text_hash=by_id[row_id].text_hash,
                embedding_model=by_id[row_id].embedding_model,
                source_revision=by_id[row_id].source_revision,
            )
            for row_id in ids
            if row_id in by_id
        }

    def existing_revisions(self) -> dict[str, ExistingSourceRevision]:
        by_source: dict[str, list[SemanticRow]] = {}
        for row in self.rows:
            by_source.setdefault(row.parent_id or row.id, []).append(row)
        return {
            source_id: ExistingSourceRevision(
                source=grouped[0].source,
                source_revision=grouped[0].source_revision,
                embedding_model=grouped[0].embedding_model,
                row_ids=frozenset(row.id for row in grouped),
            )
            for source_id, grouped in by_source.items()
        }


class _FakeSource:
    def __init__(
        self,
        name: str,
        projections: list[SemanticProjection],
        *,
        available: bool = True,
        scan_status: str = "complete",
        raise_on_scan: bool = False,
    ) -> None:
        self._name = name
        self._projections = projections
        self._available = available
        self._scan_status = scan_status
        self._raise_on_scan = raise_on_scan
        self.scan_calls = 0
        self.projected_ids: list[str] = []

    def name(self) -> str:
        return self._name

    def available(self) -> bool:
        return self._available

    def iter_projections(self) -> Iterator[SemanticProjection]:
        yield from self._projections

    def scan(self) -> SourceScan:
        self.scan_calls += 1
        if self._raise_on_scan:
            raise SourceScanError("read failed")
        return SourceScan(
            revisions={p.source_id: p.source_revision for p in self._projections},
            status=self._scan_status,  # type: ignore[arg-type]
        )

    def project(self, source_ids: Sequence[str]) -> Iterator[SemanticProjection]:
        wanted = set(source_ids)
        self.projected_ids.extend(source_ids)
        return iter([p for p in self._projections if p.source_id in wanted])


def _projection(source_id: str, text: str) -> SemanticProjection:
    return SemanticProjection(
        source="memory",
        source_id=source_id,
        kind="contract_note",
        text=text,
        text_hash=text_hash(text),
        source_revision=f"rev-{source_id}",
    )


def test_rebuild_embeds_and_upserts() -> None:
    writer = _FakeWriter()
    provider = DeterministicHashEmbeddingProvider(dimension=32)
    source = _FakeSource(
        "memory",
        [_projection("mem-1", "alpha beta"), _projection("mem-2", "gamma delta")],
    )

    report = rebuild_semantic_index(writer=writer, provider=provider, sources=[source])

    assert isinstance(report, RebuildReport)
    assert report.indexed == 2
    assert report.by_source == {"memory": 2}
    # The lane is scanned once (cheap revisions) and only the changed ids are
    # projected — the expensive source is never iterated wholesale for the report.
    assert source.scan_calls == 1
    assert sorted(source.projected_ids) == ["mem-1", "mem-2"]
    assert {row.id for row in writer.rows} == {"mem-1", "mem-2"}
    assert all(len(row.vector) == 32 for row in writer.rows)
    assert all(row.embedding_model == "diagnostic-hash-v1" for row in writer.rows)


def test_rebuild_skips_unavailable_sources() -> None:
    writer = _FakeWriter()
    provider = DeterministicHashEmbeddingProvider(dimension=16)
    source = _FakeSource("audit", [_projection("evt-1", "x y")], available=False)

    report = rebuild_semantic_index(writer=writer, provider=provider, sources=[source])

    assert report.indexed == 0
    assert report.by_source == {}
    assert writer.rows == []


def test_rebuild_prunes_stale_ids() -> None:
    writer = _FakeWriter()
    writer.rows = [
        SemanticRow(
            id="old",
            source="memory",
            kind="contract_note",
            text_hash="h",
            embedding_model="diagnostic-hash-v1",
            vector=(0.0, 1.0),
        )
    ]
    provider = DeterministicHashEmbeddingProvider(dimension=8)
    source = _FakeSource("memory", [_projection("new", "fresh note")])

    report = rebuild_semantic_index(writer=writer, provider=provider, sources=[source])

    assert report.indexed == 1
    assert report.deleted == 1
    assert {row.id for row in writer.rows} == {"new"}


def test_rebuild_available_source_with_empty_projections() -> None:
    writer = _FakeWriter()
    provider = DeterministicHashEmbeddingProvider(dimension=8)
    source = _FakeSource("memory", [], available=True)

    report = rebuild_semantic_index(writer=writer, provider=provider, sources=[source])

    assert report.indexed == 0
    assert report.by_source == {}
    assert writer.rows == []


class _FixedChunker:
    def __init__(self, chunks: tuple[str, ...]) -> None:
        self._chunks = chunks

    def chunk_text(self, text: str) -> tuple[str, ...]:
        return self._chunks


def test_rebuild_indexes_trajectory_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    import codeclone.memory.semantic.rebuild as rebuild_mod

    monkeypatch.setattr(
        rebuild_mod,
        "resolve_passage_chunker",
        lambda _provider: _FixedChunker(("chunk-a", "chunk-b")),
    )
    writer = _FakeWriter()
    provider = DeterministicHashEmbeddingProvider(dimension=16)
    projection = SemanticProjection(
        source="trajectory",
        source_id="traj-1",
        kind="trajectory",
        text="long trajectory",
        text_hash=text_hash("long trajectory"),
        source_revision="rev-traj-1",
    )
    source = _FakeSource("trajectory", [projection])

    report = rebuild_semantic_index(writer=writer, provider=provider, sources=[source])

    assert report.indexed == 2
    assert report.by_source == {"trajectory": 1}
    assert {row.id for row in writer.rows} == {
        "trajectory:traj-1:chunk:000",
        "trajectory:traj-1:chunk:001",
    }
    assert all(row.parent_id == "traj-1" for row in writer.rows)


def _stored_row(row_id: str, source: SemanticSource) -> SemanticRow:
    return SemanticRow(
        id=row_id,
        source=source,
        kind="contract_note",
        text_hash=text_hash(row_id),
        embedding_model="diagnostic-hash-v1",
        vector=tuple([0.0] * 32),
    )


def test_rebuild_defers_pruning_when_a_source_read_fails() -> None:
    writer = _FakeWriter()
    provider = DeterministicHashEmbeddingProvider(dimension=32)
    # Pre-existing rows in two lanes.
    writer.rows.extend(
        [_stored_row("mem-old", "memory"), _stored_row("aud-1", "audit")]
    )
    # The memory lane scans clean (yields nothing, so mem-old would be stale), but
    # the audit lane's read fails — pruning is destructive, so it is deferred.
    report = rebuild_semantic_index(
        writer=writer,
        provider=provider,
        sources=[
            _FakeSource("memory", []),
            _FakeSource("audit", [], raise_on_scan=True),
        ],
    )

    known = writer.known_ids()
    # Nothing is deleted: a failed read must never delete still-live rows, even
    # in lanes that scanned clean. The deletions wait for the next clean rebuild.
    assert "mem-old" in known
    assert "aud-1" in known
    assert report.deleted == 0
