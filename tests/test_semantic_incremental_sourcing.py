# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Stage 2 — semantic incremental sourcing partition.

These tests exercise ``rebuild_semantic_index`` at the layer the perf work
targets: a source is scanned for cheap revisions and only changed source ids are
re-projected/embedded. The instrumented source records exactly which ids it was
asked to project (its hydration cost), so a no-op proves zero projection — not
merely zero embedding.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

import pytest

from codeclone.memory.embedding import DeterministicHashEmbeddingProvider
from codeclone.memory.embedding.batching import EmbedBatchLimits
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


@dataclass(frozen=True, slots=True)
class _Doc:
    source_id: str
    revision: str
    projection: SemanticProjection


def _doc(
    source_id: str,
    text: str,
    *,
    revision: str | None = None,
    source: SemanticSource = "memory",
) -> _Doc:
    rev = revision if revision is not None else f"rev::{text_hash(text)}"
    projection = SemanticProjection(
        source=source,
        source_id=source_id,
        kind="contract_note" if source != "trajectory" else "trajectory",
        text=text,
        text_hash=text_hash(text),
        source_revision=rev,
    )
    return _Doc(source_id=source_id, revision=rev, projection=projection)


class _InstrumentedSource:
    """A source that records its scan/project (hydration) calls per id."""

    def __init__(
        self,
        name: str,
        docs: Sequence[_Doc],
        *,
        available: bool = True,
        scan_status: str = "complete",
        raise_on_scan: bool = False,
    ) -> None:
        self._name = name
        self._docs = list(docs)
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
        yield from (doc.projection for doc in self._docs)

    def scan(self) -> SourceScan:
        self.scan_calls += 1
        if self._raise_on_scan:
            raise SourceScanError("scan failed")
        return SourceScan(
            revisions={doc.source_id: doc.revision for doc in self._docs},
            status=self._scan_status,  # type: ignore[arg-type]
        )

    def project(self, source_ids: Sequence[str]) -> Iterator[SemanticProjection]:
        wanted = set(source_ids)
        # Only non-empty hydration is recorded — the real sources return without
        # touching their store when there is nothing to project.
        self.projected_ids.extend(doc_id for doc_id in source_ids)
        return iter([doc.projection for doc in self._docs if doc.source_id in wanted])


class _CountingWriter:
    """Faithful in-memory writer that records writes/deletes and can fail
    mid-cycle to model a crash between row upserts and reconcile."""

    def __init__(self) -> None:
        self.rows: dict[str, SemanticRow] = {}
        self.upsert_batches = 0
        self.upserted_ids: list[str] = []
        self.deleted_ids: list[str] = []
        self.fail_on_upsert_batch: int | None = None

    def search(
        self, vector: Sequence[float], *, k: int, source: str | None = None
    ) -> list[SemanticHit]:
        return []

    def status(self) -> SemanticIndexStatus:
        return SemanticIndexStatus(available=True, indexed_count=len(self.rows))

    def upsert(self, rows: Sequence[SemanticRow]) -> None:
        self.upsert_batches += 1
        if self.fail_on_upsert_batch == self.upsert_batches:
            raise RuntimeError("simulated crash before reconcile")
        for row in rows:
            self.rows[row.id] = row
            self.upserted_ids.append(row.id)

    def delete(self, ids: Sequence[str]) -> None:
        for row_id in ids:
            self.deleted_ids.append(row_id)
            self.rows.pop(row_id, None)

    def known_ids(self) -> set[str]:
        return set(self.rows)

    def row_fingerprints(self, ids: Sequence[str]) -> dict[str, SemanticRowFingerprint]:
        out: dict[str, SemanticRowFingerprint] = {}
        for row_id in ids:
            row = self.rows.get(row_id)
            if row is not None:
                out[row_id] = SemanticRowFingerprint(
                    id=row.id,
                    text_hash=row.text_hash,
                    embedding_model=row.embedding_model,
                    source_revision=row.source_revision,
                )
        return out

    def existing_revisions(self) -> dict[str, ExistingSourceRevision]:
        grouped: dict[str, list[SemanticRow]] = {}
        for row in self.rows.values():
            grouped.setdefault(row.parent_id or row.id, []).append(row)
        result: dict[str, ExistingSourceRevision] = {}
        for source_id, source_rows in grouped.items():
            head = source_rows[0]
            result[source_id] = ExistingSourceRevision(
                source=head.source,
                source_revision=head.source_revision,
                embedding_model=head.embedding_model,
                row_ids=frozenset(row.id for row in source_rows),
            )
        return result


@dataclass(slots=True)
class _Harness:
    writer: _CountingWriter = field(default_factory=_CountingWriter)
    dimension: int = 16

    def rebuild(
        self,
        sources: Sequence[_InstrumentedSource],
        *,
        limits: EmbedBatchLimits | None = None,
    ) -> RebuildReport:
        provider = DeterministicHashEmbeddingProvider(dimension=self.dimension)
        return rebuild_semantic_index(
            writer=self.writer,
            provider=provider,
            sources=list(sources),
            embed_batch_limits=limits,
        )

    def reset_counters(self) -> None:
        self.writer.upsert_batches = 0
        self.writer.upserted_ids.clear()
        self.writer.deleted_ids.clear()


def test_first_run_builds_every_row_with_a_revision() -> None:
    h = _Harness()
    report = h.rebuild(
        [_InstrumentedSource("memory", [_doc("m1", "a"), _doc("m2", "b")])]
    )
    assert report.indexed == 2
    assert report.embedded == 2
    assert set(h.writer.rows) == {"m1", "m2"}
    # Every row carries a non-empty source_revision after the full build.
    assert all(row.source_revision for row in h.writer.rows.values())


def test_unchanged_corpus_is_a_total_noop() -> None:
    h = _Harness()
    docs = [_doc("m1", "a"), _doc("m2", "b")]
    h.rebuild([_InstrumentedSource("memory", docs)])

    h.reset_counters()
    source = _InstrumentedSource("memory", docs)
    report = h.rebuild([source])

    assert report.indexed == 2
    assert report.embedded == 0
    assert report.deleted == 0
    # Scanned once; nothing projected/hydrated, embedded, written, or deleted.
    assert source.scan_calls == 1
    assert source.projected_ids == []
    assert h.writer.upserted_ids == []
    assert h.writer.deleted_ids == []


def test_one_new_record_projects_only_that_row() -> None:
    h = _Harness()
    docs = [_doc("m1", "a"), _doc("m2", "b")]
    h.rebuild([_InstrumentedSource("memory", docs)])

    h.reset_counters()
    source = _InstrumentedSource("memory", [*docs, _doc("m3", "c")])
    report = h.rebuild([source])

    assert source.projected_ids == ["m3"]
    assert report.embedded == 1
    assert h.writer.upserted_ids == ["m3"]
    assert set(h.writer.rows) == {"m1", "m2", "m3"}


def test_one_changed_record_reembeds_only_that_row() -> None:
    h = _Harness()
    h.rebuild([_InstrumentedSource("memory", [_doc("m1", "a"), _doc("m2", "b")])])

    h.reset_counters()
    # m2's text changes -> its revision changes; m1 is untouched.
    source = _InstrumentedSource("memory", [_doc("m1", "a"), _doc("m2", "b-rewritten")])
    report = h.rebuild([source])

    assert source.projected_ids == ["m2"]
    assert report.embedded == 1
    assert h.writer.upserted_ids == ["m2"]


def test_deleted_record_is_reconciled_away() -> None:
    h = _Harness()
    h.rebuild(
        [
            _InstrumentedSource(
                "memory", [_doc("m1", "a"), _doc("m2", "b"), _doc("m3", "c")]
            )
        ]
    )

    h.reset_counters()
    source = _InstrumentedSource("memory", [_doc("m1", "a"), _doc("m2", "b")])
    report = h.rebuild([source])

    assert report.deleted == 1
    assert h.writer.deleted_ids == ["m3"]
    assert "m3" not in h.writer.known_ids()
    # Survivors are unchanged: not re-projected.
    assert source.projected_ids == []


def test_failed_scan_preserves_its_lane_and_degrades() -> None:
    h = _Harness()
    # Two lanes built clean.
    h.rebuild(
        [
            _InstrumentedSource("memory", [_doc("m1", "a")]),
            _InstrumentedSource("audit", [_doc("a1", "x", source="audit")]),
        ]
    )

    h.reset_counters()
    memory = _InstrumentedSource("memory", [_doc("m1", "a")])
    audit = _InstrumentedSource(
        "audit", [_doc("a1", "x", source="audit")], raise_on_scan=True
    )
    report = h.rebuild([memory, audit])

    # The audit lane is preserved untouched and the cycle prunes nothing at all.
    assert "a1" in h.writer.known_ids()
    assert "m1" in h.writer.known_ids()
    assert report.deleted == 0
    assert report.incomplete_lanes == ("audit",)
    assert h.writer.deleted_ids == []


def test_partial_scan_forbids_destructive_reconcile_for_that_lane() -> None:
    h = _Harness()
    h.rebuild(
        [
            _InstrumentedSource("memory", [_doc("m1", "a")]),
            _InstrumentedSource("audit", [_doc("a1", "x", source="audit")]),
        ]
    )

    h.reset_counters()
    # The audit lane scans 'partial' (some rows unreadable): even though it now
    # reports no current ids, its stored row must not be pruned.
    memory = _InstrumentedSource("memory", [_doc("m1", "a")])
    audit = _InstrumentedSource("audit", [], scan_status="partial")
    report = h.rebuild([memory, audit])

    assert "a1" in h.writer.known_ids()
    assert report.deleted == 0
    assert report.incomplete_lanes == ("audit",)


def test_revision_bump_invalidates_only_that_lane_then_noop() -> None:
    h = _Harness()
    mem_v1 = [_doc("m1", "a", revision="m1@v1"), _doc("m2", "b", revision="m2@v1")]
    audit = [_doc("a1", "x", revision="a1@v1", source="audit")]
    h.rebuild(
        [_InstrumentedSource("memory", mem_v1), _InstrumentedSource("audit", audit)]
    )

    # A projection-version bump folds into every memory revision; audit is unchanged.
    h.reset_counters()
    mem_v2 = [_doc("m1", "a", revision="m1@v2"), _doc("m2", "b", revision="m2@v2")]
    memory = _InstrumentedSource("memory", mem_v2)
    audit_src = _InstrumentedSource("audit", audit)
    report = h.rebuild([memory, audit_src])

    assert sorted(memory.projected_ids) == ["m1", "m2"]
    assert audit_src.projected_ids == []  # other lane untouched (I7)
    assert report.embedded == 2

    # Back to a total no-op once the bumped revisions are stored.
    h.reset_counters()
    memory2 = _InstrumentedSource("memory", mem_v2)
    audit2 = _InstrumentedSource("audit", audit)
    report2 = h.rebuild([memory2, audit2])
    assert report2.embedded == 0
    assert memory2.projected_ids == []
    assert audit2.projected_ids == []


def test_crash_between_upserts_and_reconcile_reconverges() -> None:
    docs = [_doc("m1", "a"), _doc("m2", "b"), _doc("m3", "c")]
    h = _Harness()
    # One row per batch, and fail on the second batch: the first row lands, the
    # crash aborts before reconcile, so no rows are ever deleted.
    h.writer.fail_on_upsert_batch = 2
    one_per_batch = EmbedBatchLimits(max_documents=1, max_padded_tokens=100_000)
    with pytest.raises(RuntimeError):
        h.rebuild([_InstrumentedSource("memory", docs)], limits=one_per_batch)

    assert len(h.writer.rows) == 1  # partial state, no "completed" marker
    assert h.writer.deleted_ids == []  # reconcile never ran

    # The next rebuild re-converges: the already-stored row is unchanged, the rest
    # are embedded, and nothing is lost.
    survivor = next(iter(h.writer.rows))
    h.writer.fail_on_upsert_batch = None
    h.reset_counters()
    report = h.rebuild([_InstrumentedSource("memory", docs)])

    assert set(h.writer.rows) == {"m1", "m2", "m3"}
    assert report.embedded == 2
    assert survivor not in h.writer.upserted_ids  # the survivor was not re-embedded
