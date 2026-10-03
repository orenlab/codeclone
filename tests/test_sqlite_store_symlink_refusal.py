# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A service database is opened only as a regular file, never through a link.

Security review 2026-10, A-04: ``.codeclone/db/cache.sqlite3`` committed as a
symbolic link to a file outside the repository made the shared opener turn an
empty file into a 49152-byte cache store and add cache tables to somebody
else's SQLite database. The refusal lives in the one opener every store goes
through, and it covers the database file and every directory between it and
``.codeclone``. ``.codeclone`` itself may be a link: then every store moves
together, which the review measured as consistent rather than as an escape.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

from codeclone.paths.workspace import WORKSPACE_DIR_NAME
from codeclone.utils import sqlite_store
from codeclone.utils.sqlite_store import open_sqlite_db, open_sqlite_db_readonly


def _create_table(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS cache_entry(x)")
    conn.commit()


def _accept_any_schema(_conn: sqlite3.Connection) -> None:
    return None


def _foreign_database(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE users(id INTEGER, name TEXT)")
        conn.execute("INSERT INTO users VALUES (1, 'alice')")
        conn.commit()
    finally:
        conn.close()


def _tables(path: Path) -> list[str]:
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute("SELECT name FROM sqlite_master ORDER BY name").fetchall()
    finally:
        conn.close()
    return [str(row[0]) for row in rows]


def _workspace_db(tmp_path: Path) -> Path:
    db_dir = tmp_path / "repo" / ".codeclone" / "db"
    db_dir.mkdir(parents=True)
    return db_dir / "cache.sqlite3"


def _open_writable(path: Path) -> sqlite3.Connection:
    return open_sqlite_db(path, ensure_schema=_create_table)


def _open_readonly(path: Path) -> sqlite3.Connection:
    return open_sqlite_db_readonly(path, validate_schema=_accept_any_schema)


_OPENERS: dict[str, Callable[[Path], sqlite3.Connection]] = {
    "writable": _open_writable,
    "readonly": _open_readonly,
}


def test_database_file_that_is_a_symlink_to_an_empty_file_is_refused(
    tmp_path: Path,
) -> None:
    victim = tmp_path / "victim.dat"
    victim.write_bytes(b"")
    db_path = _workspace_db(tmp_path)
    db_path.symlink_to(victim)

    with pytest.raises(OSError, match="symbolic link"):
        _open_writable(db_path)

    assert victim.read_bytes() == b""
    assert sorted(p.name for p in tmp_path.iterdir()) == ["repo", "victim.dat"]


@pytest.mark.parametrize("opener", sorted(_OPENERS))
def test_database_file_that_is_a_symlink_to_a_foreign_database_is_refused(
    tmp_path: Path, opener: str
) -> None:
    victim = tmp_path / "victim.sqlite3"
    _foreign_database(victim)
    before = victim.read_bytes()
    db_path = _workspace_db(tmp_path)
    db_path.symlink_to(victim)

    with pytest.raises(OSError, match="symbolic link"):
        _OPENERS[opener](db_path)

    assert victim.read_bytes() == before
    assert _tables(victim) == ["users"]


def test_directory_inside_the_workspace_that_is_a_symlink_is_refused(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    workspace = tmp_path / "repo" / ".codeclone"
    workspace.mkdir(parents=True)
    (workspace / "db").symlink_to(outside, target_is_directory=True)

    with pytest.raises(OSError, match="symbolic link"):
        _open_writable(workspace / "db" / "cache.sqlite3")

    assert list(outside.iterdir()) == []


def test_workspace_directory_that_is_itself_a_symlink_still_opens(
    tmp_path: Path,
) -> None:
    moved = tmp_path / "moved_workspace"
    (moved / "db").mkdir(parents=True)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".codeclone").symlink_to(moved, target_is_directory=True)
    db_path = repo / ".codeclone" / "db" / "cache.sqlite3"

    conn = _open_writable(db_path)
    conn.close()
    reader = _open_readonly(db_path)
    reader.close()

    assert _tables(moved / "db" / "cache.sqlite3") == ["cache_entry"]


@pytest.mark.parametrize("opener", sorted(_OPENERS))
def test_database_path_that_is_not_a_regular_file_is_refused(
    tmp_path: Path, opener: str
) -> None:
    db_path = _workspace_db(tmp_path)
    db_path.mkdir()

    with pytest.raises(OSError, match="not a regular file"):
        _OPENERS[opener](db_path)


def test_database_outside_any_workspace_opens_under_symlinked_ancestors(
    tmp_path: Path,
) -> None:
    real = tmp_path / "real_parent"
    real.mkdir()
    (tmp_path / "linked_parent").symlink_to(real, target_is_directory=True)

    conn = _open_writable(tmp_path / "linked_parent" / "store.sqlite3")
    conn.close()

    assert _tables(real / "store.sqlite3") == ["cache_entry"]


def test_workspace_name_is_the_layout_owners_name() -> None:
    assert sqlite_store._WORKSPACE_DIR_NAME == WORKSPACE_DIR_NAME
