# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import importlib
import math
import sqlite3
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
from codeclone.analytics.schema import ensure_analytics_schema
from codeclone.analytics.store.protocols import CorpusStore
from codeclone.analytics.store.sqlite import (
    SqliteCorpusAnalyticsStore,
    parse_json_object,
)
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


@pytest.mark.parametrize("legacy_version", ["1.0", "1.1"])
def test_store_migration_reaches_1_2_and_is_idempotent(
    tmp_path: Path,
    legacy_version: str,
) -> None:
    path = tmp_path / f"analytics-{legacy_version}.sqlite3"
    store = SqliteCorpusAnalyticsStore.open(path)
    store.close()
    _remove_control_plane(path, legacy_version=legacy_version)

    conn = sqlite3.connect(path)
    try:
        ensure_analytics_schema(conn)
        ensure_analytics_schema(conn)
        version = conn.execute(
            "SELECT value FROM analytics_meta WHERE key='schema_version'"
        ).fetchone()
        tables = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()

    assert version == ("1.2",)
    assert {
        "profile_manifest_snapshots",
        "profile_batches",
        "profile_batch_runs",
        "profile_assessments",
        "run_selections",
    } <= tables


def test_store_migration_backfills_one_legacy_selection(tmp_path: Path) -> None:
    path = tmp_path / "analytics.sqlite3"
    store = SqliteCorpusAnalyticsStore.open(path)
    store.close()
    _seed_legacy_selection(path)
    _remove_control_plane(path, legacy_version="1.1")

    migrated = SqliteCorpusAnalyticsStore.open(path)
    try:
        active = migrated.get_active_run_selection(
            snapshot_id="snapshot",
            embedding_generation_id="embedding",
            profile_batch_id=None,
        )
    finally:
        migrated.close()

    assert active.ambiguous is False
    assert active.record is not None
    assert active.record.selection_id.startswith("sel-legacy-")
    assert active.record.selected_run_id == "run"
    assert active.record.selected_by == "legacy-migration"


def _seed_legacy_selection(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            INSERT INTO corpus_snapshots (
                snapshot_id, lane, representation_kind, representation_version,
                source_stores_json, source_schema_versions_json,
                record_count, source_digest, created_at_utc
            ) VALUES ('snapshot', 'intent', 'intent.description.v1', '3',
                      '{}', '{}', 0, 'digest', '2026-01-01T00:00:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO embedding_generations (
                embedding_generation_id, provider_id, provider_package_version,
                model_id, model_revision, model_artifact_fingerprint,
                exact_model_artifact_reproducibility, dimensions,
                embedding_contract_version, embedding_similarity_metric,
                vector_preprocessing, created_at_utc
            ) VALUES ('embedding', 'fastembed', '1', 'model', NULL, NULL,
                      0, 2, '2', 'cosine', 'l2_normalize',
                      '2026-01-01T00:00:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO clustering_runs (
                clustering_run_id, snapshot_id, embedding_generation_id,
                requested_parameters_json, effective_parameters_json,
                random_seed, run_digest, recommended_by_heuristic,
                selected_by_maintainer, status, created_at_utc,
                finished_at_utc, error_message
            ) VALUES ('run', 'snapshot', 'embedding', '{}', '{}', 42,
                      'run-digest', 0, 1, 'completed',
                      '2026-01-01T00:00:00Z',
                      '2026-01-01T00:00:01Z', NULL)
            """
        )
        conn.commit()
    finally:
        conn.close()


def _remove_control_plane(path: Path, *, legacy_version: str) -> None:
    conn = sqlite3.connect(path)
    try:
        trigger_names = [
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            )
        ]
        for name in trigger_names:
            conn.execute(f'DROP TRIGGER IF EXISTS "{name}"')
        conn.execute("DROP INDEX IF EXISTS idx_run_selections_scope")
        conn.execute("DROP INDEX IF EXISTS idx_profile_batches_lens")
        for table in (
            "run_selections",
            "profile_assessments",
            "profile_batch_runs",
            "profile_batches",
            "profile_manifest_snapshots",
        ):
            conn.execute(f'DROP TABLE IF EXISTS "{table}"')
        conn.execute(
            "UPDATE analytics_meta SET value=? WHERE key='schema_version'",
            (legacy_version,),
        )
        conn.commit()
    finally:
        conn.close()
