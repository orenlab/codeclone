# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

_SQLITE_PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA foreign_keys=OFF",
    "PRAGMA busy_timeout=5000",
)


def open_sqlite_db(
    path: Path,
    *,
    ensure_schema: Callable[[sqlite3.Connection], None],
) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(path),
        isolation_level="DEFERRED",
        timeout=5.0,
        check_same_thread=False,
    )
    try:
        for statement in _SQLITE_PRAGMAS:
            conn.execute(statement)
        ensure_schema(conn)
    except Exception:
        conn.close()
        raise
    return conn


def get_meta_value(
    conn: sqlite3.Connection,
    *,
    meta_table: str,
    key: str,
) -> str | None:
    try:
        row = conn.execute(
            f"SELECT value FROM {meta_table} WHERE key = ?",
            (key,),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None:
        return None
    value = row[0]
    return value if isinstance(value, str) else None


def initialize_schema_v1(
    conn: sqlite3.Connection,
    *,
    ddl_statements: Sequence[str],
    index_statements: Sequence[str],
    meta_table: str,
    seed_meta: Mapping[str, str],
) -> None:
    for statement in ddl_statements:
        conn.execute(statement)
    for statement in index_statements:
        conn.execute(statement)
    conn.executemany(
        f"INSERT OR IGNORE INTO {meta_table}(key, value) VALUES (?, ?)",
        sorted(seed_meta.items()),
    )
    conn.commit()


__all__ = [
    "get_meta_value",
    "initialize_schema_v1",
    "open_sqlite_db",
]
