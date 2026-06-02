# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import lancedb  # type: ignore[import-untyped]  # 0.33 ships no py.typed/stubs
import pyarrow as pa

from .models import SemanticHit, SemanticIndexStatus, SemanticRow

# Module-level lancedb/pyarrow imports are intentional: this module is the
# isolation boundary. The factory imports it inside a try/except, so when the
# optional `semantic-lancedb` extra is absent the ImportError is caught and the
# index degrades to Unavailable — the rest of the memory package never imports
# a vector DB at module level.

_TABLE_NAME = "semantic_index"


def _schema(dimension: int) -> pa.Schema:
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

    def __init__(self, *, path: Path, dimension: int) -> None:
        self._dimension = dimension
        self._db = lancedb.connect(str(path))
        # Idempotent open-or-create. A membership check against list_tables()
        # is unreliable (it returns a paginated result object, not a list), so
        # let lancedb open the table when it exists and create it otherwise.
        self._table = self._db.create_table(
            _TABLE_NAME, schema=_schema(dimension), exist_ok=True
        )

    def search(self, vector: Sequence[float], *, k: int) -> list[SemanticHit]:
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
        return SemanticIndexStatus(
            available=True,
            backend="lancedb",
            dimension=self._dimension,
            indexed_count=self._table.count_rows(),
        )

    def upsert(self, rows: Sequence[SemanticRow]) -> None:
        if not rows:
            return
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
        clause = ", ".join(_sql_quote(value) for value in ids)
        self._table.delete(f"id IN ({clause})")

    def known_ids(self) -> set[str]:
        column = self._table.to_arrow().column("id").to_pylist()
        return {str(value) for value in column}


__all__ = ["LanceDbSemanticIndex"]
