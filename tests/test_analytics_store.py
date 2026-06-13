# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import importlib
import math
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import cast

import pytest

from codeclone.analytics.contracts import (
    CorpusItemRecord,
    EmbeddingGenerationRecord,
    EmbeddingItemRecord,
)
from codeclone.analytics.embedding import generation
from codeclone.analytics.exceptions import (
    AnalyticsCapabilityError,
    AnalyticsStoreError,
    AnalyticsWorkflowError,
)
from codeclone.analytics.store.protocols import CorpusStore
from codeclone.analytics.store.sqlite import parse_json_object
from codeclone.analytics.store.vectors_lancedb import (
    AnalyticsVectorStore,
    vector_digest,
)
from codeclone.config.analytics import resolve_analytics_config


def _item(item_id: str = "item") -> CorpusItemRecord:
    return CorpusItemRecord(
        snapshot_id="snapshot",
        representation_key=f"representation-{item_id}",
        snapshot_item_id=item_id,
        source_record_key=f"source-{item_id}",
        project_id="project",
        intent_id=f"intent-{item_id}",
        normalized_text="embed this text",
        normalized_digest="normalized",
        normalizer_version="1",
        representation_digest="representation",
        metadata_json="{}",
        registry_overlay_json=None,
    )


class _Query:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.predicate = ""
        self.limit_value = 0

    def select(self, _columns: list[str]) -> _Query:
        return self

    def where(self, predicate: str) -> _Query:
        self.predicate = predicate
        return self

    def limit(self, value: int) -> _Query:
        self.limit_value = value
        return self

    def to_list(self) -> list[dict[str, object]]:
        return self.rows


class _Merge:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def when_matched_update_all(self) -> _Merge:
        return self

    def when_not_matched_insert_all(self) -> _Merge:
        return self

    def execute(self, records: list[dict[str, object]]) -> None:
        self.records = records


class _Table:
    def __init__(self, rows: list[dict[str, object]] | None = None) -> None:
        self.query = _Query(rows or [])
        self.merge = _Merge()
        self.deleted = ""
        self.schema = SimpleNamespace(
            field=lambda _name: SimpleNamespace(type=SimpleNamespace(list_size=2))
        )

    def search(self, _vector: list[float] | None = None) -> _Query:
        return self.query

    def merge_insert(self, _key: str) -> _Merge:
        return self.merge

    def delete(self, predicate: str) -> None:
        self.deleted = predicate


def _vector_store(table: _Table | None = None) -> AnalyticsVectorStore:
    store = object.__new__(AnalyticsVectorStore)
    store._dimension = 2
    store._table = table or _Table()
    return store


def test_vector_store_validates_writes_and_reads() -> None:
    store = _vector_store()
    with pytest.raises(TypeError, match="list of floats"):
        store.write_vectors(
            embedding_generation_id="embedding",
            rows=[{"snapshot_item_id": "item", "vector": (1.0, 0.0)}],
        )
    with pytest.raises(AnalyticsStoreError, match="dimension mismatch"):
        store.write_vectors(
            embedding_generation_id="embedding",
            rows=[{"snapshot_item_id": "item", "vector": [1.0]}],
        )
    with pytest.raises(AnalyticsStoreError, match="finite"):
        store.write_vectors(
            embedding_generation_id="embedding",
            rows=[{"snapshot_item_id": "item", "vector": [math.inf, 0.0]}],
        )
    store.write_vectors(embedding_generation_id="embedding", rows=[])
    store.write_vectors(
        embedding_generation_id="embedding",
        rows=[{"snapshot_item_id": "item", "vector": [1.0, 0.0]}],
    )
    (record,) = store._table.merge.records  # type: ignore[attr-defined]
    assert record["vector_digest"] == vector_digest([1.0, 0.0])

    assert (
        store.read_vector_rows(
            embedding_generation_id="embedding",
            snapshot_item_ids=(),
        )
        == {}
    )
    table = _Table(
        [
            {
                "snapshot_item_id": "item",
                "vector_row_key": "row",
                "vector_digest": "digest",
                "vector": [1, 0],
            },
            {"snapshot_item_id": 3, "vector": [1, 0]},
            {"snapshot_item_id": "bad", "vector": "not-a-vector"},
        ]
    )
    loaded_store = _vector_store(table)
    assert loaded_store.read_vectors(
        embedding_generation_id="emb'edding",
        snapshot_item_ids=("item", "item"),
    ) == {"item": [1.0, 0.0]}
    assert "emb''edding" in table.query.predicate
    loaded_store.delete_generation("emb'edding")
    assert "emb''edding" in table.deleted
    assert (
        loaded_store.list_generation_item_ids(
            embedding_generation_id="embedding",
            limit=0,
        )
        == ()
    )
    table.query.rows = [
        {"snapshot_item_id": "z"},
        {"snapshot_item_id": 3},
        {"snapshot_item_id": "a"},
    ]
    assert loaded_store.list_generation_item_ids(
        embedding_generation_id="embedding",
        limit=3,
    ) == ("a", "z")
    loaded_store.close()


def test_vector_store_open_or_create_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "codeclone.analytics.store.vectors_lancedb._schema",
        lambda _pyarrow, _dimension: "schema",
    )
    created = _Table()

    class _Connection:
        def __init__(self, error: ValueError | None = None) -> None:
            self.error = error
            self.created = False

        def open_table(self, _name: str) -> _Table:
            if self.error is not None:
                raise self.error
            return created

        def create_table(
            self,
            _name: str,
            schema: object,
            *,
            exist_ok: bool = False,
        ) -> _Table:
            assert schema == "schema"
            assert exist_ok is True
            self.created = True
            return created

    store = object.__new__(AnalyticsVectorStore)
    store._dimension = 2
    connection = _Connection(ValueError("Table 'corpus_vectors' was not found"))
    store._conn = connection
    pyarrow = cast(ModuleType, SimpleNamespace())
    assert store._open_or_create_table(pyarrow) is created
    assert connection.created is True

    store._conn = _Connection(ValueError("permission denied"))
    with pytest.raises(ValueError, match="permission denied"):
        store._open_or_create_table(pyarrow)

    wrong = _Table()
    wrong.schema = SimpleNamespace(
        field=lambda _name: SimpleNamespace(type=SimpleNamespace(list_size=3))
    )
    created.schema = wrong.schema
    store._conn = _Connection()
    with pytest.raises(AnalyticsStoreError, match="dimension mismatch"):
        store._open_or_create_table(pyarrow)


def test_optional_lancedb_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from codeclone.analytics.store import vectors_lancedb

    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda _name: (_ for _ in ()).throw(ImportError),
    )
    with pytest.raises(AnalyticsCapabilityError, match="lancedb"):
        vectors_lancedb._load_lancedb()


def test_parse_json_object_contract() -> None:
    assert parse_json_object('{"ok":true}') == {"ok": True}
    with pytest.raises(AnalyticsStoreError, match="expected JSON object"):
        parse_json_object("[]")


class _EmbeddingStore:
    def __init__(self, items: tuple[CorpusItemRecord, ...]) -> None:
        self.items = items
        self.generation: EmbeddingGenerationRecord | None = None
        self.embedding_items: tuple[EmbeddingItemRecord, ...] = ()
        self.commits = 0
        self.rollbacks = 0

    def list_items(self, _snapshot_id: str) -> tuple[CorpusItemRecord, ...]:
        return self.items

    def insert_embedding_generation(
        self,
        record: EmbeddingGenerationRecord,
    ) -> None:
        self.generation = record

    def insert_embedding_items(
        self,
        records: list[EmbeddingItemRecord],
    ) -> None:
        self.embedding_items = tuple(records)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class _EmbeddingVectors:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []
        self.missing = False

    def write_vectors(
        self,
        *,
        embedding_generation_id: str,
        rows: list[dict[str, object]],
    ) -> None:
        assert embedding_generation_id.startswith("emb-")
        self.rows = rows

    def read_vectors(
        self,
        *,
        embedding_generation_id: str,
        snapshot_item_ids: list[str],
    ) -> dict[str, list[float]]:
        assert embedding_generation_id == "embedding"
        return {} if self.missing else {"item": [1.0, 0.0]}


class _Provider:
    model_id = "custom:model"
    dimension = 2

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _text in texts]


def test_embedding_generation_contracts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = resolve_analytics_config(tmp_path)
    empty = _EmbeddingStore(())
    with pytest.raises(AnalyticsWorkflowError, match="snapshot has no items"):
        generation.generate_embeddings_for_snapshot(
            store=cast(CorpusStore, empty),
            vector_store=cast(AnalyticsVectorStore, _EmbeddingVectors()),
            config=config,
            snapshot_id="snapshot",
            provider=_Provider(),
        )

    store = _EmbeddingStore((_item(),))
    vectors = _EmbeddingVectors()
    result = generation.generate_embeddings_for_snapshot(
        store=cast(CorpusStore, store),
        vector_store=cast(AnalyticsVectorStore, vectors),
        config=config,
        snapshot_id="snapshot",
        provider=_Provider(),
    )
    assert result.item_count == 1
    assert store.generation is not None
    assert store.generation.provider_id == "custom"
    assert store.generation.model_id == "model"
    assert store.commits == 1
    assert vectors.rows[0]["vector"] == [1.0, 0.0]

    monkeypatch.setattr(
        generation,
        "embed_documents",
        lambda _provider, _texts: (_ for _ in ()).throw(RuntimeError("model failed")),
    )
    with pytest.raises(AnalyticsWorkflowError, match="model failed"):
        generation.generate_embeddings_for_snapshot(
            store=cast(CorpusStore, _EmbeddingStore((_item(),))),
            vector_store=cast(AnalyticsVectorStore, _EmbeddingVectors()),
            config=config,
            snapshot_id="snapshot",
            provider=_Provider(),
        )


def test_embedding_provider_and_vector_loading_edges(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = resolve_analytics_config(tmp_path)
    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda _name: (_ for _ in ()).throw(ImportError),
    )
    with pytest.raises(AnalyticsCapabilityError, match="fastembed"):
        generation._resolve_fastembed_provider(config)
    assert generation._provider_package_version("custom") == "unknown"

    vectors = _EmbeddingVectors()
    assert generation.load_snapshot_vectors(
        vector_store=cast(AnalyticsVectorStore, vectors),
        embedding_generation_id="embedding",
        items=(_item(),),
    ) == [[1.0, 0.0]]
    vectors.missing = True
    with pytest.raises(ValueError, match="missing vector"):
        generation.load_snapshot_vectors(
            vector_store=cast(AnalyticsVectorStore, vectors),
            embedding_generation_id="embedding",
            items=(_item(),),
        )
