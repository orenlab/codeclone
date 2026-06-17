# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from codeclone.surfaces.mcp._workspace_intent_schema import (
    INTENT_REGISTRY_SCHEMA_VERSION,
    IntentRegistrySchemaError,
    create_schema_v1,
    ensure_schema,
    get_meta,
    open_intent_registry_db,
)

_V1_CREATE_INTENTS_SQL = """
CREATE TABLE workspace_intents (
    agent_pid           INTEGER NOT NULL,
    agent_start_epoch   INTEGER NOT NULL,
    intent_id           TEXT    NOT NULL,
    declared_at_utc     TEXT    NOT NULL,
    payload_json        TEXT    NOT NULL,
    PRIMARY KEY (agent_pid, agent_start_epoch, intent_id)
)
"""

_V1_CREATE_META_SQL = """
CREATE TABLE intent_registry_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""


def _connect_v1_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute(_V1_CREATE_META_SQL)
    conn.execute(_V1_CREATE_INTENTS_SQL)
    conn.execute(
        "INSERT INTO intent_registry_meta(key, value) VALUES ('schema_version', '1')"
    )
    conn.commit()
    return conn


def test_open_intent_registry_db_creates_v2_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "intents.sqlite3"
    conn = open_intent_registry_db(db_path)
    try:
        assert get_meta(conn, "schema_version") == INTENT_REGISTRY_SCHEMA_VERSION
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(workspace_intents)")
        }
        assert {"closed_at_utc", "updated_at_utc"}.issubset(columns)
    finally:
        conn.close()


def test_create_schema_v1_seeds_meta(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "fresh.sqlite3")
    try:
        create_schema_v1(conn)
        assert get_meta(conn, "schema_version") == INTENT_REGISTRY_SCHEMA_VERSION
        assert get_meta(conn, "generator") == "codeclone"
    finally:
        conn.close()


def test_ensure_schema_migrates_v1_database(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.sqlite3"
    conn = _connect_v1_db(db_path)
    try:
        ensure_schema(conn)
        assert get_meta(conn, "schema_version") == INTENT_REGISTRY_SCHEMA_VERSION
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(workspace_intents)")
        }
        assert {"closed_at_utc", "updated_at_utc"}.issubset(columns)
    finally:
        conn.close()


def test_ensure_schema_migrates_partial_v1_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "partial.sqlite3"
    conn = _connect_v1_db(db_path)
    try:
        conn.execute("ALTER TABLE workspace_intents ADD COLUMN closed_at_utc TEXT")
        conn.commit()
        ensure_schema(conn)
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(workspace_intents)")
        }
        assert "updated_at_utc" in columns
        assert get_meta(conn, "schema_version") == INTENT_REGISTRY_SCHEMA_VERSION
    finally:
        conn.close()


def test_ensure_schema_rejects_unknown_version(tmp_path: Path) -> None:
    db_path = tmp_path / "unknown.sqlite3"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(_V1_CREATE_META_SQL)
        conn.execute(
            "INSERT INTO intent_registry_meta(key, value) "
            "VALUES ('schema_version', '999')"
        )
        conn.commit()
        with pytest.raises(
            IntentRegistrySchemaError, match="Unsupported intent registry"
        ):
            ensure_schema(conn)
    finally:
        conn.close()
