# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import importlib
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast

from ...utils.iterutils import chunked
from .models import (
    SemanticHit,
    SemanticIndexStatus,
    SemanticRow,
    SemanticRowFingerprint,
    SemanticSource,
)

# This module is importable in the base install. The optional vector DB packages
# are loaded only when a LanceDB backend instance is constructed.

_TABLE_NAME = "semantic_index"
_SCHEMA_MISMATCH_REASON = "schema_mismatch"
# LanceDB `id IN (...)` filter batch — bounds the predicate size per query.
_ID_QUERY_BATCH = 500


class _LanceSearchQuery(Protocol):
    def select(self, columns: list[str]) -> _LanceSearchQuery: ...

    def where(self, predicate: str) -> _LanceSearchQuery: ...

    def limit(self, k: int) -> _LanceSearchQuery: ...

    def to_list(self) -> list[dict[str, object]]: ...

    def to_arrow(self) -> _ArrowTable: ...


class _LanceMergeInsert(Protocol):
    def when_matched_update_all(self) -> _LanceMergeInsert: ...

    def when_not_matched_insert_all(self) -> _LanceMergeInsert: ...

    def execute(self, records: list[dict[str, object]]) -> None: ...


class _LanceField(Protocol):
    type: object


class _LanceSchema(Protocol):
    def field(self, name: str) -> _LanceField: ...


class _ArrowColumn(Protocol):
    def to_pylist(self) -> list[object]: ...


class _ArrowTable(Protocol):
    def column(self, name: str) -> _ArrowColumn: ...


class _LanceTable(Protocol):
    schema: _LanceSchema

    def search(self, vector: list[float] | None = None) -> _LanceSearchQuery: ...

    def count_rows(self) -> int: ...

    def merge_insert(self, key: str) -> _LanceMergeInsert: ...

    def delete(self, clause: str) -> None: ...


class _LanceConnection(Protocol):
    def open_table(self, name: str) -> _LanceTable: ...

    def create_table(
        self, name: str, schema: object, *, exist_ok: bool = False
    ) -> _LanceTable: ...

    def drop_table(self, name: str) -> None: ...


def _schema(pa: ModuleType, dimension: int) -> object:
    return pa.schema(
        [
            pa.field("id", pa.string()),
            pa.field("source", pa.string()),
            pa.field("project_id", pa.string()),
            pa.field("subject_path", pa.string()),
            pa.field("kind", pa.string()),
            pa.field("status", pa.string()),
            pa.field("text_hash", pa.string()),
            pa.field("embedding_model", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), dimension)),
        ]
    )


def _to_record(row: SemanticRow) -> dict[str, object]:
    return {
        "id": row.id,
        "source": row.source,
        "project_id": row.project_id,
        "subject_path": row.subject_path,
        "kind": row.kind,
        "status": row.status,
        "text_hash": row.text_hash,
        "embedding_model": row.embedding_model,
        "vector": list(row.vector),
    }


def _sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _as_float(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return float(str(value))


def _close_if_available(target: object | None) -> None:
    if target is None:
        return
    close = getattr(target, "close", None)
    if callable(close):
        close()


class LanceDbSemanticIndex:
    """LanceDB-backed semantic index (read + write); implements
    SemanticIndexWriter. The table is keyed by ``id`` (merge-insert upsert) and
    carries the projection metadata plus the embedding vector.
    """

    def __init__(self, *, path: Path, dimension: int, create: bool = False) -> None:
        self._dimension = dimension
        self._unavailable_reason: str | None = None
        lancedb = importlib.import_module("lancedb")
        self._pa = importlib.import_module("pyarrow")
        self._db: _LanceConnection = lancedb.connect(str(path))
        self._table: _LanceTable | None = self._open_table(create=create)

    def _open_table(self, *, create: bool) -> _LanceTable | None:
        table = self._open_existing_table()
        if table is None:
            if create:
                return self._create_table()
            return None
        if self._schema_matches(table):
            return table
        self._unavailable_reason = _SCHEMA_MISMATCH_REASON
        if not create:
            return None
        self._db.drop_table(_TABLE_NAME)
        self._unavailable_reason = None
        return self._create_table()

    def _open_existing_table(self) -> _LanceTable | None:
        try:
            return self._db.open_table(_TABLE_NAME)
        except ValueError as exc:
            if f"Table '{_TABLE_NAME}' was not found" in str(exc):
                return None
            raise

    def _create_table(self) -> _LanceTable:
        return self._db.create_table(
            _TABLE_NAME, schema=_schema(self._pa, self._dimension), exist_ok=False
        )

    def _schema_matches(self, table: _LanceTable) -> bool:
        try:
            vector_type = table.schema.field("vector").type
        except (AttributeError, KeyError, ValueError):
            return False
        return getattr(vector_type, "list_size", None) == self._dimension

    def search(self, vector: Sequence[float], *, k: int) -> list[SemanticHit]:
        if self._table is None:
            return []
        rows = self._table.search(list(vector)).limit(k).to_list()
        hits: list[SemanticHit] = []
        for row in rows:
            distance = row.get("_distance", 0)
            hits.append(
                SemanticHit(
                    source_id=str(row["id"]),
                    source=cast(SemanticSource, str(row["source"])),
                    # lancedb returns L2 _distance (smaller is closer); map to a
                    # bounded proximity score where higher means more similar.
                    score=1.0 / (1.0 + _as_float(distance)),
                )
            )
        return hits

    def status(self) -> SemanticIndexStatus:
        if self._table is None:
            return SemanticIndexStatus(
                available=False,
                backend="lancedb",
                dimension=self._dimension,
                reason=self._unavailable_reason or "not_built",
            )
        return SemanticIndexStatus(
            available=True,
            backend="lancedb",
            dimension=self._dimension,
            indexed_count=self._table.count_rows(),
        )

    def upsert(self, rows: Sequence[SemanticRow]) -> None:
        if not rows:
            return
        if self._table is None:
            self._table = self._open_table(create=True)
        assert self._table is not None
        records = [_to_record(row) for row in rows]
        (
            self._table.merge_insert("id")
            .when_matched_update_all()
            .when_not_matched_insert_all()
            .execute(records)
        )

    def delete(self, ids: Sequence[str]) -> None:
        if not ids:
            return
        if self._table is None:
            return
        clause = ", ".join(_sql_quote(value) for value in ids)
        self._table.delete(f"id IN ({clause})")

    def known_ids(self) -> set[str]:
        if self._table is None:
            return set()
        total = self._table.count_rows()
        if total == 0:
            return set()
        # Metadata scan projecting only the id column: vectors are never read.
        arrow = self._table.search().select(["id"]).limit(total).to_arrow()
        return {str(value) for value in arrow.column("id").to_pylist()}

    def row_fingerprints(self, ids: Sequence[str]) -> dict[str, SemanticRowFingerprint]:
        if self._table is None or not ids:
            return {}
        result: dict[str, SemanticRowFingerprint] = {}
        for chunk in chunked(ids, _ID_QUERY_BATCH):
            clause = ", ".join(_sql_quote(value) for value in chunk)
            arrow = (
                self._table.search()
                .select(["id", "text_hash", "embedding_model"])
                .where(f"id IN ({clause})")
                .limit(len(chunk))
                .to_arrow()
            )
            row_ids = arrow.column("id").to_pylist()
            hashes = arrow.column("text_hash").to_pylist()
            models = arrow.column("embedding_model").to_pylist()
            for row_id, text_hash, model in zip(row_ids, hashes, models, strict=True):
                result[str(row_id)] = SemanticRowFingerprint(
                    id=str(row_id),
                    text_hash=str(text_hash),
                    embedding_model=str(model),
                )
        return result

    def close(self) -> None:
        table = self._table
        self._table = None
        _close_if_available(table)
        _close_if_available(self._db)


__all__ = ["LanceDbSemanticIndex"]
