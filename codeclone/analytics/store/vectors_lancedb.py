# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
import importlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast

from ..corpus.keys import sha256_hex
from ..exceptions import AnalyticsCapabilityError

_TABLE_NAME = "corpus_vectors"
_ID_QUERY_BATCH = 500


class _LanceSearchQuery(Protocol):
    def select(self, columns: list[str]) -> _LanceSearchQuery: ...

    def where(self, predicate: str) -> _LanceSearchQuery: ...

    def limit(self, k: int) -> _LanceSearchQuery: ...

    def to_list(self) -> list[dict[str, object]]: ...


class _LanceMergeInsert(Protocol):
    def when_matched_update_all(self) -> _LanceMergeInsert: ...

    def when_not_matched_insert_all(self) -> _LanceMergeInsert: ...

    def execute(self, records: list[dict[str, object]]) -> None: ...


class _LanceTable(Protocol):
    def search(self, vector: list[float] | None = None) -> _LanceSearchQuery: ...

    def merge_insert(self, key: str) -> _LanceMergeInsert: ...


class _LanceConnection(Protocol):
    def open_table(self, name: str) -> _LanceTable: ...

    def create_table(
        self, name: str, schema: object, *, exist_ok: bool = False
    ) -> _LanceTable: ...


def _load_lancedb() -> ModuleType:
    try:
        return importlib.import_module("lancedb")
    except ImportError as exc:
        raise AnalyticsCapabilityError(
            "lancedb is required for analytics embeddings; "
            "install with: uv sync --extra analytics"
        ) from exc


def _schema(pa: ModuleType, dimension: int) -> object:
    return pa.schema(
        [
            pa.field("vector_row_key", pa.string()),
            pa.field("embedding_generation_id", pa.string()),
            pa.field("snapshot_item_id", pa.string()),
            pa.field("vector_digest", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), dimension)),
        ]
    )


def vector_row_key(*, embedding_generation_id: str, snapshot_item_id: str) -> str:
    return sha256_hex(f"{embedding_generation_id}\n{snapshot_item_id}")


def vector_digest(vector: Sequence[float]) -> str:
    payload = ",".join(f"{value:.8f}" for value in vector)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class AnalyticsVectorStore:
    """Separate LanceDB sidecar for analytics corpus vectors."""

    def __init__(self, *, path: Path, dimension: int) -> None:
        lancedb = _load_lancedb()
        pyarrow = importlib.import_module("pyarrow")
        self._dimension = dimension
        path.mkdir(parents=True, exist_ok=True)
        self._conn = cast(_LanceConnection, lancedb.connect(str(path)))
        self._table = self._open_or_create_table(pyarrow)

    def _open_or_create_table(self, pyarrow: ModuleType) -> _LanceTable:
        try:
            return self._conn.open_table(_TABLE_NAME)
        except ValueError as exc:
            if f"Table '{_TABLE_NAME}' was not found" not in str(exc):
                raise
        return self._conn.create_table(
            _TABLE_NAME,
            schema=_schema(pyarrow, self._dimension),
            exist_ok=True,
        )

    def write_vectors(
        self,
        *,
        embedding_generation_id: str,
        rows: Sequence[Mapping[str, object]],
    ) -> None:
        records: list[dict[str, object]] = []
        for row in rows:
            snapshot_item_id = str(row["snapshot_item_id"])
            vector = row["vector"]
            if not isinstance(vector, list):
                msg = "vector must be a list of floats"
                raise TypeError(msg)
            float_vector = [float(value) for value in vector]
            row_key = vector_row_key(
                embedding_generation_id=embedding_generation_id,
                snapshot_item_id=snapshot_item_id,
            )
            records.append(
                {
                    "vector_row_key": row_key,
                    "embedding_generation_id": embedding_generation_id,
                    "snapshot_item_id": snapshot_item_id,
                    "vector_digest": vector_digest(float_vector),
                    "vector": float_vector,
                }
            )
        if not records:
            return
        (
            self._table.merge_insert("vector_row_key")
            .when_matched_update_all()
            .when_not_matched_insert_all()
            .execute(records)
        )

    def read_vectors(
        self,
        *,
        embedding_generation_id: str,
        snapshot_item_ids: Sequence[str],
    ) -> dict[str, list[float]]:
        if not snapshot_item_ids:
            return {}
        loaded: dict[str, list[float]] = {}
        ordered = sorted(set(snapshot_item_ids))
        for start in range(0, len(ordered), _ID_QUERY_BATCH):
            batch = ordered[start : start + _ID_QUERY_BATCH]
            quoted = ", ".join(f"'{item}'" for item in batch)
            rows = (
                self._table.search(None)
                .select(["snapshot_item_id", "vector"])
                .where(
                    f"embedding_generation_id = '{embedding_generation_id}' "
                    f"AND snapshot_item_id IN ({quoted})"
                )
                .limit(len(batch))
                .to_list()
            )
            for row in rows:
                item_id = row.get("snapshot_item_id")
                vector = row.get("vector")
                if isinstance(item_id, str) and isinstance(vector, list):
                    loaded[item_id] = [float(value) for value in vector]
        return loaded

    def close(self) -> None:
        return None


__all__ = ["AnalyticsVectorStore", "vector_digest", "vector_row_key"]
