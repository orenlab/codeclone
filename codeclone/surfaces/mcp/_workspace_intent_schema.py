# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sqlite3
from pathlib import Path

from ... import __version__
from ...report.meta import current_report_timestamp_utc
from ...utils.sqlite_store import (
    get_meta_value,
    initialize_schema_v1,
    open_sqlite_db,
)

INTENT_REGISTRY_SCHEMA_VERSION = "2"

_INTENT_META_TABLE = "intent_registry_meta"

_CREATE_INTENTS_SQL = """
CREATE TABLE IF NOT EXISTS workspace_intents (
    agent_pid           INTEGER NOT NULL,
    agent_start_epoch   INTEGER NOT NULL,
    intent_id           TEXT    NOT NULL,
    declared_at_utc     TEXT    NOT NULL,
    payload_json        TEXT    NOT NULL,
    closed_at_utc       TEXT,
    updated_at_utc      TEXT    NOT NULL,
    PRIMARY KEY (agent_pid, agent_start_epoch, intent_id)
)
"""

_CREATE_META_SQL = """
CREATE TABLE IF NOT EXISTS intent_registry_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""

_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_workspace_intents_intent_id "
    "ON workspace_intents(intent_id)",
    "CREATE INDEX IF NOT EXISTS idx_workspace_intents_declared "
    "ON workspace_intents(declared_at_utc, agent_pid, intent_id)",
    "CREATE INDEX IF NOT EXISTS idx_workspace_intents_closed "
    "ON workspace_intents(closed_at_utc)",
)


class IntentRegistrySchemaError(RuntimeError):
    """Raised for unsupported or corrupt intent registry database schemas."""


def open_intent_registry_db(path: Path) -> sqlite3.Connection:
    return open_sqlite_db(path, ensure_schema=ensure_schema)


def ensure_schema(conn: sqlite3.Connection) -> None:
    current = get_meta(conn, "schema_version")
    if current is None:
        create_schema_v1(conn)
    elif current == "1":
        _migrate_v1_to_v2(conn)
    elif current != INTENT_REGISTRY_SCHEMA_VERSION:
        raise IntentRegistrySchemaError(
            f"Unsupported intent registry schema version: {current}"
        )


def create_schema_v1(conn: sqlite3.Connection) -> None:
    initialize_schema_v1(
        conn,
        ddl_statements=(_CREATE_INTENTS_SQL, _CREATE_META_SQL),
        index_statements=_INDEX_SQL,
        meta_table=_INTENT_META_TABLE,
        seed_meta={
            "schema_version": INTENT_REGISTRY_SCHEMA_VERSION,
            "generator": "codeclone",
            "codeclone_version": __version__,
            "created_at_utc": current_report_timestamp_utc(),
        },
    )


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    existing = {
        row[1]
        for row in conn.execute("PRAGMA table_info(workspace_intents)").fetchall()
    }
    if "closed_at_utc" not in existing:
        conn.execute("ALTER TABLE workspace_intents ADD COLUMN closed_at_utc TEXT")
    if "updated_at_utc" not in existing:
        conn.execute(
            "ALTER TABLE workspace_intents "
            "ADD COLUMN updated_at_utc TEXT NOT NULL DEFAULT ''"
        )
    conn.execute(
        """
        UPDATE workspace_intents
        SET updated_at_utc = declared_at_utc
        WHERE updated_at_utc = ''
        """
    )
    conn.execute(
        f"UPDATE {_INTENT_META_TABLE} SET value = ? WHERE key = 'schema_version'",
        (INTENT_REGISTRY_SCHEMA_VERSION,),
    )
    for statement in _INDEX_SQL:
        conn.execute(statement)
    conn.commit()


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    return get_meta_value(conn, meta_table=_INTENT_META_TABLE, key=key)


__all__ = [
    "INTENT_REGISTRY_SCHEMA_VERSION",
    "IntentRegistrySchemaError",
    "create_schema_v1",
    "ensure_schema",
    "get_meta",
    "open_intent_registry_db",
]
