# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ...utils.sqlite_store import get_meta_value

_INTENT_REGISTRY_META_TABLE = "intent_registry_meta"
_SUPPORTED_REGISTRY_SCHEMA_VERSIONS = frozenset({"1", "2"})


def _validate_registry_readonly_schema(conn: sqlite3.Connection) -> None:
    version = get_meta_value(
        conn,
        meta_table=_INTENT_REGISTRY_META_TABLE,
        key="schema_version",
    )
    if version not in _SUPPORTED_REGISTRY_SCHEMA_VERSIONS:
        msg = f"unsupported intent registry schema version: {version!r}"
        raise sqlite3.DatabaseError(msg)


def read_registry_overlay(
    registry_db: Path,
    *,
    intent_id: str,
) -> dict[str, object] | None:
    """Optional live coordination overlay; excluded from corpus digests."""

    if not registry_db.is_file():
        return None
    try:
        from ...observability.sqlite_access import open_instrumented_sqlite_db_readonly

        conn = open_instrumented_sqlite_db_readonly(
            registry_db,
            validate_schema=_validate_registry_readonly_schema,
        )
    except (OSError, sqlite3.Error):
        return None
    try:
        row = conn.execute(
            """
            SELECT payload_json, declared_at_utc, closed_at_utc
            FROM workspace_intents
            WHERE intent_id=?
            ORDER BY declared_at_utc DESC, agent_pid DESC, intent_id ASC
            LIMIT 1
            """,
            (intent_id,),
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    if row is None:
        return None
    payload_json = row[0]
    status: str | None = None
    if isinstance(payload_json, str):
        try:
            parsed = json.loads(payload_json)
            if isinstance(parsed, dict):
                raw_status = parsed.get("status")
                if isinstance(raw_status, str):
                    status = raw_status
        except json.JSONDecodeError:
            status = None
    return {
        "present": True,
        "status": status,
        "declared_at_utc": row[1],
        "closed_at_utc": row[2],
    }


__all__ = ["read_registry_overlay"]
