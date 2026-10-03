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

#: The repository workspace directory, spelled as ``paths.workspace`` spells
#: it (``WORKSPACE_DIR_NAME``); this ring cannot import that owner, and a test
#: pins the two together. The workspace directory itself may be a link -- then
#: every store moves with it -- but nothing below it may be.
_WORKSPACE_DIR_NAME = ".codeclone"


class UnsafeDatabasePathError(OSError):
    """A service database path that is a symbolic link or not a regular file.

    An ``OSError`` on purpose: every store already treats a database it cannot
    open as an operating-system failure and degrades or refuses in its own
    typed way, so this refusal reaches each of them by the route they have.
    """


def _refuse_unsafe_database_path(path: Path) -> None:
    """Refuse a database file reached through a link, or one that is no file.

    A repository can commit the cache database in its workspace directory as
    a symbolic link to any file the user owns; opening it turned an empty
    file into a cache store and added cache tables to somebody else's SQLite
    database (security review 2026-10, A-04). The database file is checked, and so is
    every directory between it and the workspace directory when the path lies
    in one. Directories above the workspace are the user's own layout and are
    not judged here: a temporary directory behind ``/var -> /private/var`` is
    an ordinary place for a store.
    """

    inside_workspace: list[Path] = []
    for parent in path.parents:
        if parent.name == _WORKSPACE_DIR_NAME:
            break
        inside_workspace.append(parent)
    else:
        inside_workspace = []
    for component in (path, *inside_workspace):
        if component.is_symlink():
            raise UnsafeDatabasePathError(
                f"The CodeClone database path {component} is a symbolic link, "
                "and CodeClone never opens its databases through one; remove "
                "the link and run again."
            )
    if path.exists() and not path.is_file():
        raise UnsafeDatabasePathError(
            f"The CodeClone database path {path} is not a regular file; "
            "remove what is there and run again."
        )


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

    A path that is a symbolic link, or that runs through one inside the
    workspace directory, is refused before any directory is created or any
    file is opened (:func:`_refuse_unsafe_database_path`).
    """
    _refuse_unsafe_database_path(path)
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

    _refuse_unsafe_database_path(path)
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
    "UnsafeDatabasePathError",
    "get_meta_value",
    "initialize_schema_v1",
    "open_sqlite_db",
    "open_sqlite_db_readonly",
]
