# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from pathlib import Path

from codeclone.memory.embedding import DeterministicHashEmbeddingProvider
from codeclone.memory.models import MemoryRecord, MemorySubject
from codeclone.memory.retrieval.semantic import semantic_search
from codeclone.memory.semantic.models import (
    SemanticHit,
    SemanticIndexStatus,
    SemanticSearchResult,
)
from tests.memory_fixtures import insert_audit_event, make_module_record

_PROVIDER = DeterministicHashEmbeddingProvider(dimension=8)
_NO_AUDIT = Path("does-not-exist.sqlite3")


class _FakeIndex:
    def __init__(self, hits: list[SemanticHit]) -> None:
        self._hits = hits

    def search(self, vector: Sequence[float], *, k: int) -> list[SemanticHit]:
        return self._hits[:k]

    def status(self) -> SemanticIndexStatus:
        return SemanticIndexStatus(available=True, indexed_count=len(self._hits))


class _FakeStore:
    def __init__(
        self,
        records: dict[str, MemoryRecord],
        subjects: dict[str, list[MemorySubject]],
    ) -> None:
        self._records = records
        self._subjects = subjects

    def find_record(self, record_id: str) -> MemoryRecord | None:
        return self._records.get(record_id)

    def list_subjects_for_memory(self, memory_id: str) -> list[MemorySubject]:
        return self._subjects.get(memory_id, [])


def _record(*, statement: str) -> MemoryRecord:
    return dataclasses.replace(
        make_module_record("proj-1", "codeclone/x.py"),
        id="mem-1",
        type="contract_note",
        statement=statement,
    )


def _search(
    index: _FakeIndex, store: _FakeStore | None, *, audit: Path = _NO_AUDIT
) -> list[SemanticSearchResult]:
    return semantic_search(
        index=index,
        provider=_PROVIDER,
        store=store,
        audit_db_path=audit,
        query="recover after restart",
        limit=10,
        preview_chars=160,
    )


def test_hydrates_memory_hit() -> None:
    record = _record(statement="recover after MCP restart uses the checkpoint")
    store = _FakeStore(
        {record.id: record},
        {
            record.id: [
                MemorySubject(
                    id="s1",
                    memory_id=record.id,
                    subject_kind="path",
                    subject_key="codeclone/x.py",
                )
            ]
        },
    )
    index = _FakeIndex([SemanticHit(source_id=record.id, source="memory", score=0.9)])

    (result,) = _search(index, store)
    assert (result.source, result.kind, result.status, result.confidence) == (
        "memory",
        "contract_note",
        "active",
        "supported",
    )
    assert result.subject_path == "codeclone/x.py"
    assert "recover after MCP restart" in result.preview


def test_stale_memory_hit_is_skipped() -> None:
    index = _FakeIndex([SemanticHit(source_id="gone", source="memory", score=0.9)])
    assert _search(index, _FakeStore({}, {})) == []


def test_memory_hits_skipped_without_store() -> None:
    index = _FakeIndex([SemanticHit(source_id="mem-1", source="memory", score=0.9)])
    assert _search(index, None) == []


def test_preview_is_bounded() -> None:
    record = _record(statement="x " * 500)
    store = _FakeStore({record.id: record}, {})
    index = _FakeIndex([SemanticHit(source_id=record.id, source="memory", score=0.5)])

    (result,) = _search(index, store)
    assert len(result.preview) <= 160


def test_hydrates_audit_hit_from_summary(tmp_path: Path) -> None:
    # Unit boundary: hydration reads event_type/status/summary from a
    # controller_events row. The writer's summary population (Bug B) is
    # covered separately in test_semantic_sources.py, so a controlled row
    # via the real schema keeps this test focused on the retrieval mapping.
    audit_db = tmp_path / "audit.sqlite3"
    insert_audit_event(
        audit_db,
        event_id="evt-1",
        event_type="intent.declared",
        status="active",
        summary="recover after MCP restart",
    )
    index = _FakeIndex([SemanticHit(source_id="evt-1", source="audit", score=0.8)])
    (result,) = _search(index, None, audit=audit_db)
    assert result.source == "audit"
    assert result.kind == "intent.declared"
    assert result.status == "active"
    assert result.subject_path is None
    assert "recover after MCP restart" in result.preview
