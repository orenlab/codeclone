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
    foreign_keys: bool = False,
    synchronous: str | None = None,
) -> sqlite3.Connection:
    """Open a SQLite database with standard pragmas.

    *synchronous* overrides the default ``NORMAL`` level.  Pass ``"FULL"``
    for stores where every commit must survive an unclean process exit
    (e.g. engineering memory).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(path),
        isolation_level="DEFERRED",
        timeout=5.0,
        check_same_thread=False,
    )
    try:
        pragmas: tuple[str, ...] = _SQLITE_PRAGMAS
        if foreign_keys:
            pragmas = tuple(
                "PRAGMA foreign_keys=ON" if stmt.endswith("foreign_keys=OFF") else stmt
                for stmt in pragmas
            )
        if synchronous is not None:
            allowed = ("NORMAL", "FULL", "EXTRA", "OFF")
            upper = synchronous.upper()
            if upper not in allowed:
                msg = f"synchronous must be one of {allowed}, got {synchronous!r}"
                raise ValueError(msg)
            pragmas = tuple(
                f"PRAGMA synchronous={upper}"
                if stmt.startswith("PRAGMA synchronous=")
                else stmt
                for stmt in pragmas
            )
        for statement in pragmas:
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
