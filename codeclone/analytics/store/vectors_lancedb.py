# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
import importlib
import math
import struct
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import Protocol

from ..corpus.keys import sha256_hex
from ..exceptions import AnalyticsCapabilityError, AnalyticsStoreError

_TABLE_NAME = "corpus_vectors"
_ID_QUERY_BATCH = 500


# Every argument below is declared positional-only (`/`) because that is how
# this module calls LanceDB and PyArrow, and because their own parameter names
# differ from the ones that read well here (`query` for our vector, `where` for
# our predicate, `limit` for our count, `on` for our key, `new_data` for our
# records, `i` for a PyArrow field name). A positional-or-keyword declaration
# would claim those names are callable as keywords, which is false against the
# real objects. Results we discard are typed `object` rather than `None`:
# LanceDB returns a result record.


class _LanceSearchQuery(Protocol):
    def select(self, columns: list[str], /) -> _LanceSearchQuery: ...

    def where(self, predicate: str, /) -> _LanceSearchQuery: ...

    def limit(self, k: int, /) -> _LanceSearchQuery: ...

    def to_list(self) -> list[dict[str, object]]: ...


class _LanceMergeInsert(Protocol):
    def when_matched_update_all(self) -> _LanceMergeInsert: ...

    def when_not_matched_insert_all(self) -> _LanceMergeInsert: ...

    def execute(self, records: list[dict[str, object]], /) -> object: ...


class _ArrowType(Protocol):
    @property
    def list_size(self) -> int: ...


class _ArrowField(Protocol):
    @property
    def type(self) -> _ArrowType: ...


class _ArrowSchema(Protocol):
    def field(self, name: str, /) -> _ArrowField: ...


class _LanceTable(Protocol):
    @property
    def schema(self) -> _ArrowSchema: ...

    def search(self, vector: list[float] | None = None, /) -> _LanceSearchQuery: ...

    def merge_insert(self, key: str, /) -> _LanceMergeInsert: ...

    def delete(self, predicate: str, /) -> object: ...


class _LanceConnection(Protocol):
    def open_table(self, name: str) -> _LanceTable: ...

    # `schema` is keyword-only on purpose: LanceDB's own `create_table` keeps
    # `data` in the second positional slot, so a positional schema would bind
    # to the wrong parameter. Keyword-only states the convention we call with
    # and keeps the protocol assignable from the real connection object.
    def create_table(
        self, name: str, *, schema: object, exist_ok: bool = False
    ) -> _LanceTable: ...


def _connect(path: Path) -> _LanceConnection:
    """Open the sidecar connection through the protocol this module declares.

    The import stays inside this function on purpose. `import_module` with a
    literal name is what lets a type checker see the real `lancedb.connect`,
    so this return annotation is the edge where the protocol is held against
    the actual connection object. A helper annotated `ModuleType` erases the
    module identity and leaves the binding unchecked — the same silence a
    `cast` buys, spelled differently.
    """
    try:
        lancedb = importlib.import_module("lancedb")
    except ImportError as exc:
        raise AnalyticsCapabilityError(
            "lancedb is required for analytics embeddings; "
            "install with: uv sync --extra analytics"
        ) from exc
    connection: _LanceConnection = lancedb.connect(str(path))
    return connection


def _schema(pa: ModuleType, dimension: int) -> _ArrowSchema:
    """Build the vector table schema, described by the protocol above.

    PyArrow is a compiled extension carrying no type information, so a checker
    cannot confirm this shape. The runtime pin holds `_ArrowSchema` against the
    object this function actually returns.
    """
    schema: _ArrowSchema = pa.schema(
        [
            pa.field("vector_row_key", pa.string()),
            pa.field("embedding_generation_id", pa.string()),
            pa.field("snapshot_item_id", pa.string()),
            pa.field("vector_digest", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), dimension)),
        ]
    )
    return schema


def vector_row_key(*, embedding_generation_id: str, snapshot_item_id: str) -> str:
    return sha256_hex(f"{embedding_generation_id}\n{snapshot_item_id}")


def vector_digest(vector: Sequence[float]) -> str:
    payload = b"".join(struct.pack("<f", float(value)) for value in vector)
    return hashlib.sha256(payload).hexdigest()


class AnalyticsVectorStore:
    """Separate LanceDB sidecar for analytics corpus vectors."""

    def __init__(self, *, path: Path, dimension: int) -> None:
        # PyArrow ships as a compiled extension with no type information, so
        # `ModuleType` is the honest declaration for it: its members are opaque
        # to a checker either way, and the arrow protocols below are held to
        # the real objects at runtime instead.
        pyarrow = importlib.import_module("pyarrow")
        self._dimension = dimension
        path.mkdir(parents=True, exist_ok=True)
        self._conn = _connect(path)
        self._table = self._open_or_create_table(pyarrow)

    def _open_or_create_table(self, pyarrow: ModuleType) -> _LanceTable:
        try:
            table = self._conn.open_table(_TABLE_NAME)
        except ValueError as exc:
            if f"Table '{_TABLE_NAME}' was not found" not in str(exc):
                raise
            return self._conn.create_table(
                _TABLE_NAME,
                schema=_schema(pyarrow, self._dimension),
                exist_ok=True,
            )
        field = table.schema.field("vector")
        actual_dimension = getattr(field.type, "list_size", None)
        if actual_dimension != self._dimension:
            raise AnalyticsStoreError(
                "analytics vector store dimension mismatch: "
                f"existing={actual_dimension}, configured={self._dimension}"
            )
        return table

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
            float_vector = _float_vector(vector)
            if len(float_vector) != self._dimension:
                raise AnalyticsStoreError(
                    f"vector dimension mismatch: actual={len(float_vector)}, "
                    f"expected={self._dimension}"
                )
            if not all(math.isfinite(value) for value in float_vector):
                raise AnalyticsStoreError("vectors must contain only finite values")
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
        loaded: dict[str, list[float]] = {}
        for item_id, row in self.read_vector_rows(
            embedding_generation_id=embedding_generation_id,
            snapshot_item_ids=snapshot_item_ids,
        ).items():
            vector = row.get("vector")
            if isinstance(vector, list):
                loaded[item_id] = _float_vector(vector)
        return loaded

    def read_vector_rows(
        self,
        *,
        embedding_generation_id: str,
        snapshot_item_ids: Sequence[str],
    ) -> dict[str, dict[str, object]]:
        if not snapshot_item_ids:
            return {}
        loaded: dict[str, dict[str, object]] = {}
        ordered = sorted(set(snapshot_item_ids))
        for start in range(0, len(ordered), _ID_QUERY_BATCH):
            batch = ordered[start : start + _ID_QUERY_BATCH]
            quoted = ", ".join(_sql_literal(item) for item in batch)
            rows = (
                self._table.search(None)
                .select(
                    [
                        "vector_row_key",
                        "snapshot_item_id",
                        "vector_digest",
                        "vector",
                    ]
                )
                .where(
                    "embedding_generation_id = "
                    f"{_sql_literal(embedding_generation_id)} "
                    f"AND snapshot_item_id IN ({quoted})"
                )
                .limit(len(batch))
                .to_list()
            )
            for row in rows:
                item_id = row.get("snapshot_item_id")
                vector = row.get("vector")
                if isinstance(item_id, str) and isinstance(vector, list):
                    loaded[item_id] = {
                        "vector_row_key": str(row.get("vector_row_key", "")),
                        "vector_digest": str(row.get("vector_digest", "")),
                        "vector": _float_vector(vector),
                    }
        return loaded

    def delete_generation(self, embedding_generation_id: str) -> None:
        self._table.delete(
            f"embedding_generation_id = {_sql_literal(embedding_generation_id)}"
        )

    def list_generation_item_ids(
        self,
        *,
        embedding_generation_id: str,
        limit: int,
    ) -> tuple[str, ...]:
        if limit <= 0:
            return ()
        rows = (
            self._table.search(None)
            .select(["snapshot_item_id"])
            .where(f"embedding_generation_id = {_sql_literal(embedding_generation_id)}")
            .limit(limit)
            .to_list()
        )
        return tuple(
            sorted(
                str(item_id)
                for row in rows
                if isinstance((item_id := row.get("snapshot_item_id")), str)
            )
        )

    def close(self) -> None:
        return None


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _float_vector(vector: Sequence[object]) -> list[float]:
    float_vector: list[float] = []
    for value in vector:
        if isinstance(value, bool) or not isinstance(value, str | int | float):
            msg = "vector must be a list of floats"
            raise TypeError(msg)
        float_vector.append(float(value))
    return float_vector


__all__ = ["AnalyticsVectorStore", "vector_digest", "vector_row_key"]
