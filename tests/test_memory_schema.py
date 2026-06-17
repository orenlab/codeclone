# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from codeclone.contracts import ENGINEERING_MEMORY_SCHEMA_VERSION
from codeclone.memory.exceptions import MemorySchemaError
from codeclone.memory.schema import (
    create_schema_v1,
    ensure_schema,
    get_meta,
    open_memory_db,
)
from codeclone.memory.schema_migrate import migrate_memory_schema


def test_open_memory_db_enables_foreign_keys(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.sqlite3"
    conn = open_memory_db(db_path)
    try:
        row = conn.execute("PRAGMA foreign_keys").fetchone()
        assert row is not None
        assert int(row[0]) == 1
        assert get_meta(conn, "schema_version") == ENGINEERING_MEMORY_SCHEMA_VERSION
    finally:
        conn.close()


def test_create_schema_v1_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.sqlite3"
    conn = sqlite3.connect(db_path)
    try:
        create_schema_v1(conn)
        create_schema_v1(conn)
        assert get_meta(conn, "schema_version") == ENGINEERING_MEMORY_SCHEMA_VERSION
    finally:
        conn.close()


def test_ensure_schema_migrates_1_0_to_1_1(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.sqlite3"
    conn = sqlite3.connect(db_path)
    try:
        from codeclone.memory.schema import set_meta

        create_schema_v1(conn)
        set_meta(conn, "schema_version", "1.0")
        conn.commit()
        ensure_schema(conn)
        assert get_meta(conn, "schema_version") == ENGINEERING_MEMORY_SCHEMA_VERSION
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE name='memory_records_fts'"
        ).fetchone()
        assert row is not None
    finally:
        conn.close()


def test_ensure_schema_rejects_unsupported_version(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.sqlite3"
    conn = open_memory_db(db_path)
    try:
        conn.execute(
            "UPDATE memory_meta SET value=? WHERE key='schema_version'",
            ("9.9",),
        )
        conn.commit()
        with pytest.raises(MemorySchemaError, match="Unsupported engineering memory"):
            ensure_schema(conn)
    finally:
        conn.close()


def test_migrate_memory_schema_noop_without_meta(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.sqlite3"
    conn = sqlite3.connect(db_path)
    try:
        migrate_memory_schema(conn)
        assert get_meta(conn, "schema_version") is None
    finally:
        conn.close()


def test_migrate_memory_schema_noop_when_already_current(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.sqlite3"
    conn = open_memory_db(db_path)
    try:
        migrate_memory_schema(conn)
        assert get_meta(conn, "schema_version") == ENGINEERING_MEMORY_SCHEMA_VERSION
    finally:
        conn.close()


def test_ensure_schema_raises_on_unsupported_version(tmp_path: Path) -> None:
    from codeclone.memory.schema import create_schema_v1, ensure_schema, set_meta

    db_path = tmp_path / "memory.sqlite3"
    conn = sqlite3.connect(db_path)
    try:
        create_schema_v1(conn)
        set_meta(conn, "schema_version", "0.0")
        conn.commit()
        with (
            patch(
                "codeclone.memory.schema_migrate.migrate_memory_schema",
                lambda _conn: None,
            ),
            pytest.raises(MemorySchemaError, match="Unsupported engineering memory"),
        ):
            ensure_schema(conn)
    finally:
        conn.close()
