# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from urllib.parse import quote

_SQLITE_PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA foreign_keys=OFF",
)
_SQLITE_BUSY_TIMEOUT_MS = 5000


_SYNCHRONOUS_LEVELS = ("NORMAL", "FULL", "EXTRA", "OFF")
_AUTO_VACUUM_LEVELS = ("NONE", "FULL", "INCREMENTAL")


def _pragma_choice(name: str, value: str, allowed: tuple[str, ...]) -> str:
    """One optional pragma value, refused by name unless it is one of *allowed*.

    Both overrides this helper opens with are the same shape — a caller's
    word checked against a closed set and upper-cased — and stating that
    shape twice is how the second one drifts from the first.
    """

    level = value.upper()
    if level not in allowed:
        msg = f"{name} must be one of {allowed}, got {value!r}"
        raise ValueError(msg)
    return level


def open_sqlite_db(
    path: Path,
    *,
    ensure_schema: Callable[[sqlite3.Connection], None],
    foreign_keys: bool = False,
    synchronous: str | None = None,
    auto_vacuum: str | None = None,
    factory: type[sqlite3.Connection] | None = None,
) -> sqlite3.Connection:
    """Open a SQLite database with standard pragmas.

    *synchronous* overrides the default ``NORMAL`` level.  Pass ``"FULL"``
    for stores where every commit must survive an unclean process exit
    (e.g. engineering memory).  *factory* overrides the connection class
    (e.g. an observability-instrumented subclass); ``None`` keeps the stdlib
    default so this base helper stays decoupled from optional instrumentation.

    *auto_vacuum* is the one pragma that cannot be decided later: SQLite
    reads it from the header, and on a database that already holds a table
    a change is a silent no-op until a full ``VACUUM`` rewrites the file.
    It is therefore issued FIRST, ahead of every other pragma and ahead of
    *ensure_schema*, so a store that wants its freed pages back can ask for
    that on the only occasion the question is still open.  A store that does
    not pass it keeps SQLite's default (``NONE``): freed pages stay on the
    freelist and are reused, never returned.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # Only pass ``factory`` when supplied so the default path stays byte-identical
    # to a bare ``sqlite3.connect`` (some callers and test doubles replace
    # ``connect`` without a ``factory`` parameter).
    if factory is None:
        conn = sqlite3.connect(
            str(path),
            isolation_level="DEFERRED",
            timeout=5.0,
            check_same_thread=False,
        )
    else:
        conn = sqlite3.connect(
            str(path),
            isolation_level="DEFERRED",
            timeout=5.0,
            check_same_thread=False,
            factory=factory,
        )
    try:
        conn.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS}")
        pragmas: tuple[str, ...] = _SQLITE_PRAGMAS
        if foreign_keys:
            pragmas = tuple(
                "PRAGMA foreign_keys=ON" if stmt.endswith("foreign_keys=OFF") else stmt
                for stmt in pragmas
            )
        if auto_vacuum is not None:
            level = _pragma_choice("auto_vacuum", auto_vacuum, _AUTO_VACUUM_LEVELS)
            pragmas = (f"PRAGMA auto_vacuum={level}", *pragmas)
        if synchronous is not None:
            level = _pragma_choice("synchronous", synchronous, _SYNCHRONOUS_LEVELS)
            pragmas = tuple(
                f"PRAGMA synchronous={level}"
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


def open_sqlite_db_readonly(
    path: Path,
    *,
    validate_schema: Callable[[sqlite3.Connection], None],
    factory: type[sqlite3.Connection] | None = None,
) -> sqlite3.Connection:
    """Open an existing SQLite database without allowing writes or creation."""

    resolved = path.resolve(strict=True)
    uri = f"file:{quote(str(resolved), safe='/')}?mode=ro"
    if factory is None:
        conn = sqlite3.connect(uri, uri=True)
    else:
        conn = sqlite3.connect(uri, uri=True, factory=factory)
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        validate_schema(conn)
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
    "open_sqlite_db_readonly",
]
