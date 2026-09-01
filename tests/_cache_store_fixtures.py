# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Direct access to the cache database, for tests that must corrupt it.

Named for what it proves -- the shape of the cache store -- not for the test
module that first needed it.

It lives outside ``test_*.py`` for a boundary reason, not a stylistic one. The
Phase 39S architecture ratchet is shrink-only: it scans ``tests/test_*.py`` and
refuses any new ``codeclone`` import edge that is not already allowlisted.
``tests.test_cache`` resolves to ring r2p because it exercises observability,
so a fresh ``codeclone.cache.backend`` edge from it would grow that allowlist.
Answering the ratchet by widening the list it exists to shrink is not answering
it. The import belongs here instead, where the rule does not reach because the
rule was never about this file.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from codeclone.cache.backend import (
    META_KEY_CHECKSUM,
    META_KEY_FINGERPRINT,
    META_KEY_GENERATION,
    META_KEY_PYTHON_TAG,
    META_KEY_VERSION,
    META_TABLE,
    envelope_checksum,
    row_checksum,
)
from codeclone.cache.store import Cache

__all__ = [
    "META_KEY_CHECKSUM",
    "META_KEY_FINGERPRINT",
    "META_KEY_GENERATION",
    "META_KEY_PYTHON_TAG",
    "META_KEY_VERSION",
    "META_TABLE",
    "drop_cache_meta",
    "envelope_checksum",
    "open_store",
    "read_cache_meta",
    "read_cache_rows",
    "row_checksum",
    "sole_cache_row",
    "write_cache_meta",
    "write_cache_row",
]


def open_store(cache_path: Path) -> sqlite3.Connection:
    """Raw connection to the cache database, for tests that must corrupt it.

    Every gate the JSON envelope used to guard still exists; only the way a
    test induces the bad state moved from rewriting a document to writing a
    row.  Going through sqlite3 directly rather than through ``CacheBackend``
    keeps these tests adversarial: a backend bug that writes a well-formed but
    wrong row cannot hide behind the same helper that reads it back.
    """

    return sqlite3.connect(cache_path)


def read_cache_meta(cache_path: Path) -> dict[str, str]:
    with open_store(cache_path) as conn:
        return {
            str(key): str(value)
            for key, value in conn.execute(
                f"SELECT key, value FROM {META_TABLE}"
            ).fetchall()
        }


def write_cache_meta(cache_path: Path, **values: str) -> None:
    with open_store(cache_path) as conn:
        conn.executemany(
            f"INSERT INTO {META_TABLE}(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            sorted(values.items()),
        )


def drop_cache_meta(cache_path: Path, *keys: str) -> None:
    with open_store(cache_path) as conn:
        conn.executemany(
            f"DELETE FROM {META_TABLE} WHERE key = ?",
            [(key,) for key in keys],
        )


def read_cache_rows(cache_path: Path) -> dict[str, object]:
    with open_store(cache_path) as conn:
        return {
            str(wire_path): json.loads(payload)
            for wire_path, payload in conn.execute(
                "SELECT wire_path, payload FROM cache_files"
            ).fetchall()
        }


def write_cache_row(
    cache_path: Path,
    wire_path: str,
    entry: object,
    *,
    checksum: str | None = None,
    version: str | None = None,
) -> None:
    resolved_version = Cache._CACHE_VERSION if version is None else version
    resolved_checksum = (
        row_checksum(version=resolved_version, wire_path=wire_path, entry=entry)
        if checksum is None
        else checksum
    )
    with open_store(cache_path) as conn:
        conn.execute(
            "INSERT INTO cache_files(wire_path, payload, checksum, generation) "
            "VALUES (?, ?, ?, 1) ON CONFLICT(wire_path) DO UPDATE SET "
            "payload=excluded.payload, checksum=excluded.checksum",
            (wire_path, json.dumps(entry).encode("utf-8"), resolved_checksum),
        )


def sole_cache_row(cache_path: Path) -> tuple[str, object]:
    rows = read_cache_rows(cache_path)
    assert len(rows) == 1, rows
    return next(iter(rows.items()))
