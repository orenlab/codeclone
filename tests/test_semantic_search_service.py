# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from codeclone.memory.embedding import EmbeddingProvider
from codeclone.memory.exceptions import MemorySemanticUnavailableError
from codeclone.memory.retrieval import query_engineering_memory
from codeclone.memory.semantic.models import SemanticHit, SemanticIndexStatus
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore
from tests.memory_fixtures import (
    insert_audit_event,
    make_module_record,
    memory_store,
    seed_document_link,
    seed_module_role,
)


class _FakeProvider:
    model_id = "diagnostic-hash-v1"
    dimension = 8

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [[0.0] * self.dimension for _ in texts]


class _FakeIndex:
    def __init__(
        self,
        hits: list[SemanticHit],
        *,
        available: bool = True,
        reason: str | None = None,
    ) -> None:
        self._hits = hits
        self._available = available
        self._reason = reason

    def search(
        self, vector: Sequence[float], *, k: int, source: str | None = None
    ) -> list[SemanticHit]:
        hits = (
            self._hits
            if source is None
            else [hit for hit in self._hits if hit.source == source]
        )
        return hits[:k]

    def status(self) -> SemanticIndexStatus:
        return SemanticIndexStatus(
            available=self._available,
            backend="fake",
            reason=self._reason,
            indexed_count=len(self._hits),
        )


def _search(
    store: SqliteEngineeringMemoryStore,
    *,
    root: Path,
    project_id: str,
    db_path: Path,
    query: str,
    index: _FakeIndex,
    audit: Path | None = None,
    filters: Mapping[str, object] | None = None,
    provider: EmbeddingProvider | None = None,
) -> dict[str, object]:
    return query_engineering_memory(
        store,
        project_id=project_id,
        root_path=root,
        backend="sqlite",
        db_path=db_path,
        mode="search",
        query=query,
        semantic=True,
        semantic_index=index,
        embedding_provider=provider or _FakeProvider(),
        provider_label="diagnostic",
        audit_db_path=audit,
        filters=filters,
    )


def _record_ids(result: dict[str, object]) -> list[str]:
    payload = result["payload"]
    assert isinstance(payload, dict)
    records = payload["records"]
    assert isinstance(records, list)
    return [item["id"] for item in records if isinstance(item, dict)]


def test_hybrid_merges_semantic_only_record(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, db_path):
        fts = seed_module_role(
            store,
            project_id=project.id,
            file_path="codeclone/a.py",
            statement="alpha beta gamma",
        )
        semantic_only = seed_module_role(
            store,
            project_id=project.id,
            file_path="codeclone/b.py",
            statement="delta epsilon zeta",
        )
        index = _FakeIndex(
            [SemanticHit(source_id=semantic_only.id, source="memory", score=0.9)]
        )
        result = _search(
            store,
            root=root,
            project_id=project.id,
            db_path=db_path,
            query="alpha",
            index=index,
        )
    block = result["semantic"]
    assert isinstance(block, dict)
    assert block["used"] is True
    assert block["provider"] == "diagnostic"
    assert block["model"] == "diagnostic-hash-v1"
    assert block["backend"] == "fake"
    ids = _record_ids(result)
    # FTS hit and the semantic-only record are merged into one ranked list.
    assert fts.id in ids
    assert semantic_only.id in ids


def test_semantic_only_record_respects_type_filter(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, db_path):
        kept = seed_document_link(
            store,
            project_id=project.id,
            doc_file="codeclone/a.py",
            ref_path="codeclone/a.py",
            statement="alpha beta gamma",
        )
        filtered = seed_module_role(
            store,
            project_id=project.id,
            file_path="codeclone/b.py",
            statement="delta epsilon zeta",
        )
        index = _FakeIndex(
            [SemanticHit(source_id=filtered.id, source="memory", score=0.9)]
        )
        result = _search(
            store,
            root=root,
            project_id=project.id,
            db_path=db_path,
            query="alpha",
            index=index,
            filters={"types": ["document_link"]},
        )
    ids = _record_ids(result)
    # FTS hit kept; the semantic-only module_role no longer bypasses the filter.
    assert kept.id in ids
    assert filtered.id not in ids


def test_semantic_hits_searches_each_source_with_its_own_budget() -> None:
    from codeclone.memory.retrieval import service as retrieval_service

    captured: list[tuple[str | None, int]] = []

    class _RecordingIndex:
        def search(
            self, vector: Sequence[float], *, k: int, source: str | None = None
        ) -> list[SemanticHit]:
            captured.append((source, k))
            return []

        def status(self) -> SemanticIndexStatus:
            return SemanticIndexStatus(available=True)

    proximity, audit_hits, trajectory_hits = retrieval_service._semantic_hits(
        index=_RecordingIndex(),
        provider=_FakeProvider(),
        query="alpha",
        k=7,
    )

    # Each lane is searched independently with the full k budget, so a dense
    # source (e.g. audit) cannot crowd another lane out of one shared top-k.
    assert len(captured) == 3
    assert dict(captured) == {"memory": 7, "audit": 7, "trajectory": 7}
    assert proximity == {}
    assert audit_hits == []
    assert trajectory_hits == []


def test_rank_records_lets_rrf_lead_over_metadata(tmp_path: Path) -> None:
    from codeclone.memory.retrieval import service as retrieval_service
    from codeclone.memory.retrieval.ranking import RankingContext

    with memory_store(tmp_path) as (_root, project, store, _db_path):
        # module_role carries a smaller type boost than document_link, so under
        # the old metadata-led ordering doc_link would sort first.
        lexical_top = seed_module_role(
            store,
            project_id=project.id,
            file_path="codeclone/a.py",
            statement="alpha",
        )
        meta_rich = seed_document_link(
            store,
            project_id=project.id,
            doc_file="codeclone/b.py",
            ref_path="codeclone/b.py",
            statement="beta",
        )
        context = RankingContext.from_scope(
            scope_paths=(), symbols=(), blast_dependents=()
        )
        payload, _truncated = retrieval_service._rank_records(
            store,
            project_id=project.id,
            candidates=[lexical_top, meta_rich],
            context=context,
            max_records=10,
            detail_level="compact",
            lexical_ranks={lexical_top.id: 0, meta_rich.id: 1},
            vector_ranks={},
        )

    ids = [item["id"] for item in payload]
    # RRF leads: the BM25 rank-0 match wins even though document_link has the
    # higher metadata boost. Metadata only breaks ties.
    assert ids == [lexical_top.id, meta_rich.id]


class _FailingProvider:
    model_id = "diagnostic-hash-v1"
    dimension = 8

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        raise MemorySemanticUnavailableError("model unavailable (download disabled)")


def test_semantic_search_degrades_to_fts_when_model_unavailable(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, db_path):
        fts = seed_module_role(
            store,
            project_id=project.id,
            file_path="codeclone/a.py",
            statement="alpha beta gamma",
        )
        index = _FakeIndex([SemanticHit(source_id=fts.id, source="memory", score=0.9)])
        result = _search(
            store,
            root=root,
            project_id=project.id,
            db_path=db_path,
            query="alpha",
            index=index,
            provider=_FailingProvider(),
        )
    block = result["semantic"]
    assert isinstance(block, dict)
    # The lazy model load fails at embed; the query degrades to FTS-only and
    # surfaces the reason instead of raising.
    assert block["used"] is False
    assert "model unavailable" in str(block["reason"])
    assert fts.id in _record_ids(result)


def test_record_search_telemetry_emits_lane_counters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.memory.retrieval import service as service_module

    captured: dict[str, int] = {}
    monkeypatch.setattr(
        service_module,
        "record_counter",
        lambda key, value=1: captured.__setitem__(key, value),
    )
    record_a = dataclasses.replace(make_module_record("proj", "codeclone/a.py"), id="a")
    record_b = dataclasses.replace(make_module_record("proj", "codeclone/b.py"), id="b")
    service_module._record_search_telemetry(
        fts_records=[record_a, record_b],
        proximity={"b": 0.9, "c": 0.8},  # b overlaps FTS; c is vector-only
        audit_hits=[SemanticHit(source_id="e1", source="audit", score=0.5)],
        trajectory_hits=[],
        candidates=[record_a, record_b],  # c was dropped by the filter
    )
    assert captured == {
        "retrieval.fts_hits": 2,
        "retrieval.vector_memory_hits": 2,
        "retrieval.vector_audit_hits": 1,
        "retrieval.vector_trajectory_hits": 0,
        "retrieval.fts_vector_overlap": 1,
        "retrieval.semantic_filtered": 1,
    }


def test_unavailable_index_falls_back_to_fts(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, db_path):
        fts = seed_module_role(
            store,
            project_id=project.id,
            file_path="codeclone/a.py",
            statement="alpha beta gamma",
        )
        index = _FakeIndex([], available=False, reason="lancedb_not_installed")
        result = _search(
            store,
            root=root,
            project_id=project.id,
            db_path=db_path,
            query="alpha",
            index=index,
        )
    block = result["semantic"]
    assert isinstance(block, dict)
    assert block["used"] is False
    assert block["reason"] == "lancedb_not_installed"
    assert fts.id in _record_ids(result)


def _audit_events(result: dict[str, object]) -> list[dict[str, object]]:
    payload = result["payload"]
    assert isinstance(payload, dict)
    events = payload["audit_events"]
    assert isinstance(events, list)
    return [item for item in events if isinstance(item, dict)]


def test_audit_events_typed_separate(tmp_path: Path) -> None:
    audit_db = tmp_path / "audit.sqlite3"
    insert_audit_event(
        audit_db,
        event_id="evt-1",
        event_type="patch_contract.violated",
        status="violated",
        summary="patch contract violated: 1 regression(s); structural_regressions",
    )
    with memory_store(tmp_path) as (root, project, store, db_path):
        record = seed_module_role(
            store,
            project_id=project.id,
            file_path="codeclone/a.py",
            statement="alpha beta",
        )
        index = _FakeIndex(
            [
                SemanticHit(source_id=record.id, source="memory", score=0.9),
                SemanticHit(source_id="evt-1", source="audit", score=0.8),
            ]
        )
        result = _search(
            store,
            root=root,
            project_id=project.id,
            db_path=db_path,
            query="alpha",
            index=index,
            audit=audit_db,
        )
    # The memory record stays in payload.records; the audit incident is
    # returned typed-separate in payload.audit_events (never co-ranked).
    assert record.id in _record_ids(result)
    assert "evt-1" not in _record_ids(result)
    events = _audit_events(result)
    assert len(events) == 1
    event = events[0]
    assert event["event_id"] == "evt-1"
    assert event["event_type"] == "patch_contract.violated"
    assert event["status"] == "violated"
    assert "patch contract violated" in str(event["summary"])
