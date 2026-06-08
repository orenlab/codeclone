# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Exercise LanceDB backend without the optional ``semantic-lancedb`` extra."""

from __future__ import annotations

import importlib
import re
from pathlib import Path
from types import ModuleType

import pytest

from codeclone.memory.semantic.lancedb_backend import LanceDbSemanticIndex
from codeclone.memory.semantic.models import SemanticRow


class _FakeVectorType:
    def __init__(self, list_size: int) -> None:
        self.list_size = list_size


class _FakeSchema:
    def __init__(self, list_size: int) -> None:
        self._list_size = list_size

    def field(self, name: str) -> object:
        if name != "vector":
            raise KeyError(name)
        return type("Field", (), {"type": _FakeVectorType(self._list_size)})()


class _FakeMergeInsert:
    def __init__(self, table: _FakeTable) -> None:
        self._table = table

    def when_matched_update_all(self) -> _FakeMergeInsert:
        return self

    def when_not_matched_insert_all(self) -> _FakeMergeInsert:
        return self

    def execute(self, records: list[dict[str, object]]) -> None:
        by_id = {str(row["id"]): row for row in records}
        self._table._rows = list(by_id.values())


class _FakeTable:
    def __init__(
        self, *, list_size: int, rows: list[dict[str, object]] | None = None
    ) -> None:
        self.schema = _FakeSchema(list_size)
        self._rows = list(rows or [])
        self._search_vector: list[float] | None = None
        self._search_limit: int | None = None
        self._select: list[str] | None = None
        self._where: str | None = None
        self.closed = False

    def search(self, vector: list[float] | None = None) -> _FakeTable:
        self._search_vector = list(vector) if vector is not None else None
        self._select = None
        self._where = None
        return self

    def select(self, columns: list[str]) -> _FakeTable:
        self._select = list(columns)
        return self

    def where(self, predicate: str) -> _FakeTable:
        self._where = predicate
        return self

    def limit(self, k: int) -> _FakeTable:
        self._search_limit = k
        return self

    def to_list(self) -> list[dict[str, object]]:
        return [
            {
                "id": row["id"],
                "source": row["source"],
                "_distance": 0.5,
            }
            for row in self._rows
        ]

    def count_rows(self) -> int:
        return len(self._rows)

    def merge_insert(self, _key: str) -> _FakeMergeInsert:
        return _FakeMergeInsert(self)

    def delete(self, clause: str) -> None:
        drop = set(re.findall(r"'([^']*)'", clause))
        self._rows = [row for row in self._rows if str(row["id"]) not in drop]

    def to_arrow(self) -> _FakeArrowTable:
        rows = self._rows
        if self._where:
            keep = set(re.findall(r"'([^']*)'", self._where))
            rows = [row for row in rows if str(row["id"]) in keep]
        columns = self._select or ["id"]
        return _FakeArrowTable({col: [row.get(col) for row in rows] for col in columns})

    def close(self) -> None:
        self.closed = True


class _FakeArrowTable:
    def __init__(self, columns: dict[str, list[object]]) -> None:
        self._columns = columns

    def column(self, name: str) -> _FakeArrowColumn:
        if name not in self._columns:
            raise KeyError(name)
        return _FakeArrowColumn(self._columns[name])


class _FakeArrowColumn:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def to_pylist(self) -> list[object]:
        return list(self._values)


class _FakeDb:
    def __init__(self) -> None:
        self._table: _FakeTable | None = None
        self.dropped = False
        self.closed = False

    def open_table(self, name: str) -> _FakeTable:
        if name != "semantic_index":
            raise ValueError(f"unexpected table {name}")
        if self._table is None:
            raise ValueError("Table 'semantic_index' was not found")
        return self._table

    def create_table(
        self, name: str, schema: object, exist_ok: bool = False
    ) -> _FakeTable:
        del name, schema, exist_ok
        self._table = _FakeTable(list_size=4)
        return self._table

    def drop_table(self, name: str) -> None:
        del name
        self.dropped = True
        self._table = None

    def close(self) -> None:
        self.closed = True


def _install_fake_lancedb(
    monkeypatch: pytest.MonkeyPatch,
    *,
    list_size: int = 4,
    with_table: bool = True,
) -> _FakeDb:
    fake_db = _FakeDb()

    def _connect(_path: str) -> _FakeDb:
        return fake_db

    lancedb_mod = ModuleType("lancedb")
    lancedb_mod.connect = _connect  # type: ignore[attr-defined]

    pa_mod = ModuleType("pyarrow")
    pa_mod.schema = lambda fields: {"fields": fields}  # type: ignore[attr-defined]

    def _field(name: str, _type: object) -> tuple[str, object]:
        return (name, _type)

    pa_mod.field = _field  # type: ignore[attr-defined]
    pa_mod.list_ = lambda _item, _size: object()  # type: ignore[attr-defined]
    pa_mod.string = lambda: object()  # type: ignore[attr-defined]
    pa_mod.float32 = lambda: object()  # type: ignore[attr-defined]

    original = importlib.import_module

    def _import(name: str, package: str | None = None) -> ModuleType:
        if name == "lancedb":
            return lancedb_mod
        if name == "pyarrow":
            return pa_mod
        return original(name, package)

    monkeypatch.setattr(importlib, "import_module", _import)
    if with_table:
        fake_db._table = _FakeTable(list_size=list_size)
    return fake_db


def _row(record_id: str, vector: list[float]) -> SemanticRow:
    return SemanticRow(
        id=record_id,
        source="memory",
        kind="contract_note",
        text_hash=f"h-{record_id}",
        embedding_model="diagnostic-hash-v1",
        vector=tuple(vector),
    )


def test_lancedb_backend_mocked_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_lancedb(monkeypatch)
    index = LanceDbSemanticIndex(path=tmp_path / "idx.lance", dimension=4, create=True)
    index.upsert([_row("a", [0.0, 0.0, 0.0, 0.0]), _row("b", [1.0, 1.0, 1.0, 1.0])])
    assert index.known_ids() == {"a", "b"}
    status = index.status()
    assert status.available is True
    assert status.backend == "lancedb"
    assert status.indexed_count == 2
    hits = index.search([0.0, 0.0, 0.0, 0.0], k=2)
    assert hits[0].source_id == "a"
    index.delete(["a"])
    assert index.known_ids() == {"b"}


def test_lancedb_backend_mocked_not_built_and_schema_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_db = _install_fake_lancedb(monkeypatch, list_size=4, with_table=False)
    missing = LanceDbSemanticIndex(
        path=tmp_path / "missing.lance", dimension=4, create=False
    )
    assert missing.status().reason == "not_built"
    assert missing.search([0.0, 0.0, 0.0, 0.0], k=1) == []
    missing.upsert([])
    missing.delete(["x"])

    fake_db._table = _FakeTable(list_size=4)
    read_mismatch = LanceDbSemanticIndex(
        path=tmp_path / "mismatch.lance", dimension=8, create=False
    )
    assert read_mismatch.status().reason == "schema_mismatch"

    writer = LanceDbSemanticIndex(
        path=tmp_path / "mismatch.lance", dimension=8, create=True
    )
    assert fake_db.dropped is True
    writer.upsert([_row("fresh", [0.0] * 8)])
    assert writer.known_ids() == {"fresh"}


def test_lancedb_backend_mocked_close_releases_available_handles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_db = _install_fake_lancedb(monkeypatch)
    index = LanceDbSemanticIndex(path=tmp_path / "idx.lance", dimension=4)
    table = fake_db._table
    assert table is not None

    index.close()

    assert table.closed is True
    assert fake_db.closed is True
    assert index.search([0.0, 0.0, 0.0, 0.0], k=1) == []


class _OpenTableFailsDb(_FakeDb):
    def open_table(self, name: str) -> _FakeTable:
        del name
        raise ValueError("unexpected lancedb failure")


def test_lancedb_backend_mocked_open_table_propagates_unknown_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_db = _OpenTableFailsDb()
    fake_db._table = None
    _install_fake_lancedb(monkeypatch, with_table=False)
    lancedb_mod = importlib.import_module("lancedb")
    monkeypatch.setattr(lancedb_mod, "connect", lambda _path: fake_db)
    with pytest.raises(ValueError, match="unexpected lancedb failure"):
        LanceDbSemanticIndex(path=tmp_path / "broken.lance", dimension=4, create=False)


def test_lancedb_backend_mocked_sql_quote_escapes_apostrophe() -> None:
    from codeclone.memory.semantic import lancedb_backend as backend_mod

    assert backend_mod._sql_quote("it's") == "'it''s'"
