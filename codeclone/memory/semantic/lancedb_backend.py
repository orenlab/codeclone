# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import importlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .models import SemanticHit, SemanticIndexStatus, SemanticRow

# This module is importable in the base install. The optional vector DB packages
# are loaded only when a LanceDB backend instance is constructed.

_TABLE_NAME = "semantic_index"
_SCHEMA_MISMATCH_REASON = "schema_mismatch"


def _schema(pa: Any, dimension: int) -> Any:
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
        self._db = lancedb.connect(str(path))
        self._table: Any | None = self._open_table(create=create)

    def _open_table(self, *, create: bool) -> Any | None:
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

    def _open_existing_table(self) -> Any | None:
        try:
            return self._db.open_table(_TABLE_NAME)
        except ValueError as exc:
            if f"Table '{_TABLE_NAME}' was not found" in str(exc):
                return None
            raise

    def _create_table(self) -> Any:
        return self._db.create_table(
            _TABLE_NAME, schema=_schema(self._pa, self._dimension), exist_ok=False
        )

    def _schema_matches(self, table: Any) -> bool:
        try:
            vector_type = table.schema.field("vector").type
        except (AttributeError, KeyError, ValueError):
            return False
        return getattr(vector_type, "list_size", None) == self._dimension

    def search(self, vector: Sequence[float], *, k: int) -> list[SemanticHit]:
        if self._table is None:
            return []
        rows = self._table.search(list(vector)).limit(k).to_list()
        return [
            SemanticHit(
                source_id=str(row["id"]),
                source=row["source"],
                # lancedb returns L2 _distance (smaller is closer); map to a
                # bounded proximity score where higher means more similar.
                score=1.0 / (1.0 + float(row["_distance"])),
            )
            for row in rows
        ]

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
        column = self._table.to_arrow().column("id").to_pylist()
        return {str(value) for value in column}


__all__ = ["LanceDbSemanticIndex"]
