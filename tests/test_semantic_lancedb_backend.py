# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.config.memory import SemanticConfig
from codeclone.memory.embedding import resolve_embedding_provider
from codeclone.memory.semantic import (
    SemanticIndexWriter,
    resolve_semantic_index,
    resolve_semantic_index_writer,
)
from codeclone.memory.semantic.models import SemanticRow

# The backend is the optional `semantic-lancedb` extra; skip when absent.
pytest.importorskip("lancedb")

from codeclone.memory.semantic.lancedb_backend import LanceDbSemanticIndex


def _config(tmp_path: Path, *, dimension: int) -> SemanticConfig:
    return SemanticConfig(
        enabled=True,
        index_path=str(tmp_path / "semantic_index.lance"),
        dimension=dimension,
    )


def _row(record_id: str, vector: list[float]) -> SemanticRow:
    return SemanticRow(
        id=record_id,
        source="memory",
        kind="contract_note",
        text_hash=f"h-{record_id}",
        embedding_model="diagnostic-hash-v1",
        vector=tuple(vector),
    )


def _writer_and_vector(
    tmp_path: Path,
    *,
    dimension: int,
    text: str,
) -> tuple[SemanticIndexWriter, list[float], SemanticConfig]:
    config = _config(tmp_path, dimension=dimension)
    writer = resolve_semantic_index_writer(config)
    assert writer is not None
    provider = resolve_embedding_provider(config)
    (vector,) = provider.embed([text])
    return writer, vector, config


def test_lancedb_backend_round_trip(tmp_path: Path) -> None:
    writer, vec_a, config = _writer_and_vector(
        tmp_path, dimension=4, text="alpha alpha"
    )
    provider = resolve_embedding_provider(config)
    (vec_b,) = provider.embed(["beta beta beta"])

    writer.upsert([_row("a", vec_a), _row("b", vec_b)])
    assert writer.known_ids() == {"a", "b"}

    status = writer.status()
    assert status.available is True
    assert status.backend == "lancedb"
    assert status.dimension == 4
    assert status.indexed_count == 2

    hits = writer.search(vec_a, k=2)
    assert hits[0].source_id == "a"  # closest to its own embedding
    assert hits[0].score >= hits[-1].score

    writer.delete(["a"])
    assert writer.known_ids() == {"b"}


def test_lancedb_backend_resolves_as_read_index(tmp_path: Path) -> None:
    config = _config(tmp_path, dimension=8)
    index_path = tmp_path / "semantic_index.lance"
    assert not index_path.exists()

    index = resolve_semantic_index(config)
    status = index.status()
    assert status.available is False
    assert status.backend is None
    assert status.reason == "not_built"
    assert index.search([0.0] * 8, k=3) == []
    assert not index_path.exists()

    writer = resolve_semantic_index_writer(config)
    assert writer is not None
    writer.upsert([_row("built", [0.0] * 8)])

    built = resolve_semantic_index(config)
    status = built.status()
    assert status.available is True
    assert status.backend == "lancedb"
    assert status.indexed_count == 1


def test_lancedb_backend_reopens_existing_table(tmp_path: Path) -> None:
    # Regression: a second backend on the same path must OPEN the existing
    # table, not crash with "Table already exists".
    config = _config(tmp_path, dimension=4)
    first = resolve_semantic_index_writer(config)
    assert first is not None
    provider = resolve_embedding_provider(config)
    (vec,) = provider.embed(["persisted"])
    first.upsert([_row("keep", vec)])

    second = resolve_semantic_index_writer(config)
    assert second is not None
    assert second.known_ids() == {"keep"}
    assert second.status().indexed_count == 1


def test_lancedb_backend_read_reports_schema_mismatch(
    tmp_path: Path,
) -> None:
    writer, vec, config = _writer_and_vector(
        tmp_path, dimension=4, text="old dimension"
    )
    writer.upsert([_row("old", vec)])

    read_mismatch = LanceDbSemanticIndex(
        path=Path(config.index_path),
        dimension=8,
        create=False,
    )

    status = read_mismatch.status()
    assert status.available is False
    assert status.reason == "schema_mismatch"
    assert read_mismatch.search([0.0] * 8, k=3) == []

    original = LanceDbSemanticIndex(
        path=Path(config.index_path),
        dimension=4,
        create=False,
    )
    assert original.known_ids() == {"old"}


def test_lancedb_backend_writer_recreates_schema_mismatch(
    tmp_path: Path,
) -> None:
    old_writer, vec, old_config = _writer_and_vector(
        tmp_path, dimension=4, text="old dimension"
    )
    old_writer.upsert([_row("old", vec)])

    new_writer = LanceDbSemanticIndex(
        path=Path(old_config.index_path),
        dimension=8,
        create=True,
    )

    assert new_writer.status().available is True
    assert new_writer.status().dimension == 8
    assert new_writer.known_ids() == set()
    new_writer.upsert([_row("new", [0.0] * 8)])
    assert new_writer.known_ids() == {"new"}


def test_lancedb_backend_upsert_is_idempotent_by_id(tmp_path: Path) -> None:
    config = _config(tmp_path, dimension=4)
    writer = resolve_semantic_index_writer(config)
    assert writer is not None
    provider = resolve_embedding_provider(config)
    (vec,) = provider.embed(["one"])

    writer.upsert([_row("dup", vec)])
    writer.upsert([_row("dup", vec)])  # same id -> merge, not duplicate
    assert writer.known_ids() == {"dup"}
    assert writer.status().indexed_count == 1


def test_lancedb_backend_no_table_search_and_delete_are_noops(tmp_path: Path) -> None:
    index = LanceDbSemanticIndex(
        path=tmp_path / "empty.lance", dimension=4, create=False
    )
    assert index.status().available is False
    assert index.status().reason == "not_built"
    assert index.search([0.0, 0.0, 0.0, 0.0], k=3) == []
    assert index.known_ids() == set()
    index.delete([])
    index.delete(["missing-table"])
    index.upsert([])


def test_lancedb_backend_upsert_creates_table_and_delete_nonempty(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, dimension=4)
    writer = LanceDbSemanticIndex(
        path=Path(config.index_path), dimension=config.dimension, create=False
    )
    assert writer._table is None
    provider = resolve_embedding_provider(config)
    (vec,) = provider.embed(["create on first upsert"])
    writer.upsert([_row("first", vec)])
    assert writer.status().indexed_count == 1
    writer.delete(["first"])
    assert writer.known_ids() == set()


def test_lancedb_backend_open_table_propagates_unexpected_value_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index = LanceDbSemanticIndex(
        path=tmp_path / "broken.lance", dimension=4, create=False
    )

    def _boom(_name: str) -> object:
        raise ValueError("unexpected lancedb failure")

    monkeypatch.setattr(index._db, "open_table", _boom)
    with pytest.raises(ValueError, match="unexpected lancedb failure"):
        index._open_table(create=False)
