# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import importlib
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast

from ...utils.iterutils import chunked
from .models import (
    ExistingSourceRevision,
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
            pa.field("parent_id", pa.string()),
            pa.field("chunk_index", pa.int32()),
            pa.field("chunk_count", pa.int32()),
            pa.field("project_id", pa.string()),
            pa.field("subject_path", pa.string()),
            pa.field("kind", pa.string()),
            pa.field("status", pa.string()),
            pa.field("text_hash", pa.string()),
            pa.field("embedding_model", pa.string()),
            pa.field("source_revision", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), dimension)),
        ]
    )


def _schema_matches(table: _LanceTable, *, dimension: int) -> bool:
    try:
        vector_type = table.schema.field("vector").type
        parent_field = table.schema.field("parent_id")
        chunk_index_field = table.schema.field("chunk_index")
        chunk_count_field = table.schema.field("chunk_count")
        # source_revision (format v3): a pre-Stage-2 table lacks it, so the
        # mismatch drives the deliberate one-time drop + full rebuild.
        source_revision_field = table.schema.field("source_revision")
    except (AttributeError, KeyError, ValueError):
        return False
    return (
        getattr(vector_type, "list_size", None) == dimension
        and parent_field is not None
        and chunk_index_field is not None
        and chunk_count_field is not None
        and source_revision_field is not None
    )


def _to_record(row: SemanticRow) -> dict[str, object]:
    return {
        "id": row.id,
        "source": row.source,
        "parent_id": row.parent_id,
        "chunk_index": row.chunk_index,
        "chunk_count": row.chunk_count,
        "project_id": row.project_id,
        "subject_path": row.subject_path,
        "kind": row.kind,
        "status": row.status,
        "text_hash": row.text_hash,
        "embedding_model": row.embedding_model,
        "source_revision": row.source_revision,
        "vector": list(row.vector),
    }


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    return int(str(value))


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


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
        if _schema_matches(table, dimension=self._dimension):
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
        return _schema_matches(table, dimension=self._dimension)

    def search(
        self, vector: Sequence[float], *, k: int, source: SemanticSource | None = None
    ) -> list[SemanticHit]:
        if self._table is None:
            return []
        query = self._table.search(list(vector))
        if source is not None:
            query = query.where(f"source = {_sql_quote(source)}")
        rows = query.limit(k).to_list()
        hits: list[SemanticHit] = []
        for row in rows:
            distance = row.get("_distance", 0)
            hits.append(
                SemanticHit(
                    source_id=str(row["id"]),
                    source=cast(SemanticSource, str(row["source"])),
                    parent_id=_optional_str(row.get("parent_id")),
                    chunk_index=_optional_int(row.get("chunk_index")),
                    chunk_count=_optional_int(row.get("chunk_count")),
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

    def existing_revisions(self) -> dict[str, ExistingSourceRevision]:
        if self._table is None:
            return {}
        total = self._table.count_rows()
        if total == 0:
            return {}
        # One metadata scan (no vectors), grouping every row back to its source
        # object: a chunked trajectory's rows share one parent_id and one
        # source_revision, so the grouped value is the source's stored revision
        # plus all of its row ids (needed to keep unchanged rows during reconcile).
        arrow = (
            self._table.search()
            .select(["id", "parent_id", "source", "source_revision", "embedding_model"])
            .limit(total)
            .to_arrow()
        )
        ids = arrow.column("id").to_pylist()
        parents = arrow.column("parent_id").to_pylist()
        sources = arrow.column("source").to_pylist()
        revisions = arrow.column("source_revision").to_pylist()
        models = arrow.column("embedding_model").to_pylist()
        row_ids_by_source: dict[str, set[str]] = defaultdict(set)
        revision_by_source: dict[str, str] = {}
        lane_by_source: dict[str, str] = {}
        model_by_source: dict[str, str] = {}
        for row_id, parent_id, source, revision, model in zip(
            ids, parents, sources, revisions, models, strict=True
        ):
            source_id = str(parent_id) if parent_id is not None else str(row_id)
            row_ids_by_source[source_id].add(str(row_id))
            revision_by_source[source_id] = "" if revision is None else str(revision)
            lane_by_source[source_id] = str(source)
            model_by_source[source_id] = "" if model is None else str(model)
        return {
            source_id: ExistingSourceRevision(
                source=cast(SemanticSource, lane_by_source[source_id]),
                source_revision=revision_by_source[source_id],
                embedding_model=model_by_source[source_id],
                row_ids=frozenset(row_ids),
            )
            for source_id, row_ids in row_ids_by_source.items()
        }

    def row_fingerprints(self, ids: Sequence[str]) -> dict[str, SemanticRowFingerprint]:
        if self._table is None or not ids:
            return {}
        result: dict[str, SemanticRowFingerprint] = {}
        for chunk in chunked(ids, _ID_QUERY_BATCH):
            clause = ", ".join(_sql_quote(value) for value in chunk)
            arrow = (
                self._table.search()
                .select(["id", "text_hash", "embedding_model", "source_revision"])
                .where(f"id IN ({clause})")
                .limit(len(chunk))
                .to_arrow()
            )
            row_ids = arrow.column("id").to_pylist()
            hashes = arrow.column("text_hash").to_pylist()
            models = arrow.column("embedding_model").to_pylist()
            revisions = arrow.column("source_revision").to_pylist()
            for row_id, text_hash, model, revision in zip(
                row_ids, hashes, models, revisions, strict=True
            ):
                result[str(row_id)] = SemanticRowFingerprint(
                    id=str(row_id),
                    text_hash=str(text_hash),
                    embedding_model=str(model),
                    source_revision="" if revision is None else str(revision),
                )
        return result

    def close(self) -> None:
        table = self._table
        self._table = None
        _close_if_available(table)
        _close_if_available(self._db)


__all__ = ["LanceDbSemanticIndex"]
