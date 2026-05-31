# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sqlite3

from ..report.meta import current_report_timestamp_utc
from .exceptions import MemorySchemaError
from .schema_fts import CREATE_MEMORY_RECORDS_FTS_SQL
from .schema_meta import get_meta, set_meta


def migrate_memory_schema(conn: sqlite3.Connection) -> None:
    from ..contracts import ENGINEERING_MEMORY_SCHEMA_VERSION

    current = get_meta(conn, "schema_version")
    if current is None:
        return
    if current == ENGINEERING_MEMORY_SCHEMA_VERSION:
        return
    if current == "1.0" and ENGINEERING_MEMORY_SCHEMA_VERSION == "1.1":
        _migrate_1_0_to_1_1(conn)
        return
    msg = (
        f"Unsupported engineering memory schema migration: {current!r} "
        f"→ {ENGINEERING_MEMORY_SCHEMA_VERSION!r}"
    )
    raise MemorySchemaError(msg)


def _migrate_1_0_to_1_1(conn: sqlite3.Connection) -> None:
    conn.execute(CREATE_MEMORY_RECORDS_FTS_SQL)
    now = current_report_timestamp_utc()
    set_meta(conn, "schema_version", "1.1")
    conn.execute(
        "INSERT OR IGNORE INTO memory_schema_migrations(version, applied_at_utc) "
        "VALUES (?, ?)",
        ("1.1", now),
    )
    conn.commit()


__all__ = ["migrate_memory_schema"]
