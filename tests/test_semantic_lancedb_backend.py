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
    resolve_semantic_index,
    resolve_semantic_index_writer,
)
from codeclone.memory.semantic.models import SemanticRow

# The backend is the optional `semantic-lancedb` extra; skip when absent.
pytest.importorskip("lancedb")


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


def test_lancedb_backend_round_trip(tmp_path: Path) -> None:
    config = _config(tmp_path, dimension=4)
    writer = resolve_semantic_index_writer(config)
    assert writer is not None
    provider = resolve_embedding_provider(config)
    (vec_a,) = provider.embed(["alpha alpha"])
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
    index = resolve_semantic_index(config)
    status = index.status()
    assert status.available is True
    assert status.backend == "lancedb"


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
