# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Row-addressable SQLite persistence for the disposable analysis cache.

Why this exists
---------------
The cache used to be one JSON monolith at ``.codeclone/cache.json`` (50 MB on
this repository).  That shape carried a defect class the maintainer pinned as a
strict xfail: ``save()`` ignored ``max_size_bytes`` while ``load()`` refused any
document above it, so a repository whose cache outgrew the cap lost the warm
path on *every* subsequent run, silently.  The cap existed only because the
loader had to pull the whole document into memory before it could read one
entry.  Row addressing removes that premise: an entry is read by key, so the
bytes held in memory are bounded by the row, never by the store.

Semantic boundary (hard)
------------------------
This is **disposable cache state**, not canonical run state.  It shares the
SQLite infrastructure under ``.codeclone/db/`` with the immutable run store, and
shares nothing else:

* a cache write never participates in publish correctness;
* the cache never enters ``run_id``;
* deleting the store whole must not change any analysis result.

The arrow is ``cache -> accelerates -> analysis facts -> run store``, never
back.  Cache state may lag the published run; it must never lead it.

Durability
----------
The WAL / ``busy_timeout=5000`` convention arrives through the ONE shared
connection owner (:func:`codeclone.utils.sqlite_store.open_sqlite_db`) and is
never restated here.  ``synchronous`` is this store's own decision and is
deliberately **not** the run store's ``FULL``: a cache torn by an unclean exit
is re-derived from source on the next run at the price of a cold file, whereas a
torn *run* is a lost authority record.  Paying ``FULL``'s fsync per commit to
protect state whose loss costs nothing but time is the wrong trade.  The run
store's ``FULL`` is untouched by this choice.

Integrity
---------
Each row carries its own checksum over ``{version, wire_path, entry}``, so a row
that fails verification is dropped as a single cache miss instead of
condemning the store.  The meta envelope is checksummed over
``{version, python_tag, fingerprint_version}`` for the same reason the JSON
envelope bound ``v``: a generation retagged in place must be refused, not
trusted.  Like its JSON predecessor this is an INTEGRITY check, not
authentication -- cache trust equals source trust; see
``integrity.cache_payload_checksum`` for the ruled threat model.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from types import TracebackType
from typing import Final

import orjson

from ..utils.sqlite_store import (
    initialize_schema_v1,
    open_sqlite_db,
    open_sqlite_db_readonly,
)
from .integrity import cache_envelope_checksum, verify_cache_envelope_checksum

CACHE_BACKEND_SCHEMA_VERSION: Final = "1"

#: ``synchronous`` for the disposable cache.  See the module docstring: this is
#: intentionally not the run store's ``FULL``.
CACHE_SYNCHRONOUS: Final = "NORMAL"

META_TABLE: Final = "cache_backend_meta"
META_KEY_VERSION: Final = "cache_version"
META_KEY_PYTHON_TAG: Final = "python_tag"
META_KEY_FINGERPRINT: Final = "fingerprint_version"
META_KEY_CHECKSUM: Final = "envelope_checksum"
META_KEY_GENERATION: Final = "generation"

SINGLETON_SEGMENT_REPORT: Final = "segment_report_projection"

_DDL: Final = (
    f"CREATE TABLE IF NOT EXISTS {META_TABLE}("
    "key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS cache_files("
    "wire_path TEXT PRIMARY KEY, "
    "payload BLOB NOT NULL, "
    "checksum TEXT NOT NULL, "
    "generation INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS cache_singletons("
    "key TEXT PRIMARY KEY, payload BLOB NOT NULL, checksum TEXT NOT NULL)",
)

_INDEXES: Final = (
    "CREATE INDEX IF NOT EXISTS idx_cache_files_generation ON cache_files(generation)",
)


class CacheBackendUnusable(Exception):
    """The file at the cache path is not a usable cache database."""


class CacheBackendUnreadable(CacheBackendUnusable):
    """The cache database exists but could not be opened at all.

    Kept distinct from its parent so a permission or locking failure is
    reported as *unreadable* rather than as corruption: the two ask different
    things of whoever reads the warning.
    """


class CacheBackendForeign(CacheBackendUnusable):
    """A well-formed database that is not a cache store.

    Distinct from corruption because nothing is damaged: the file is intact and
    simply belongs to something else. Reporting it as corrupt would invite a
    user to delete a healthy database of their own.
    """


def _validate_schema(connection: sqlite3.Connection) -> None:
    """Refuse a database that is not a cache store, without writing to it.

    ``load`` opens read-only on purpose.  A user is free to point
    ``--cache-path`` at any file, and creating our tables inside somebody
    else's database just to discover it is not ours would be a write performed
    by a read.  Missing tables surface here as a refusal instead.
    """

    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (META_TABLE,),
    ).fetchone()
    if row is None:
        # Raised here rather than signalled through a marker exception for the
        # opener to re-label: this is the point where the verdict is actually
        # decided, and it travels out through open_sqlite_db_readonly intact.
        msg = "cache database has no cache schema"
        raise CacheBackendForeign(msg)


def _ensure_schema(connection: sqlite3.Connection) -> None:
    # ``auto_vacuum`` is storage management, not part of the durability trio the
    # shared owner holds, and it only binds before the first table exists -- so
    # it belongs here, at schema creation, and is set exactly once.  Without it
    # a budget eviction would free pages that never return to the filesystem.
    connection.execute("PRAGMA auto_vacuum=INCREMENTAL")
    initialize_schema_v1(
        connection,
        ddl_statements=_DDL,
        index_statements=_INDEXES,
        meta_table=META_TABLE,
        seed_meta={},
    )


class CacheBackend:
    """One open connection to the cache database, for one load or one save.

    The connection is deliberately short-lived: the cache is touched exactly
    twice per run (load, save), so holding a connection between them would buy
    nothing and would keep a WAL lock alive across the whole analysis.
    """

    def __init__(self, path: Path, *, read_only: bool = False) -> None:
        self._path = path
        self._read_only = read_only
        try:
            if read_only:
                self._connection = open_sqlite_db_readonly(
                    path,
                    validate_schema=_validate_schema,
                )
            else:
                self._connection = open_sqlite_db(
                    path,
                    ensure_schema=_ensure_schema,
                    synchronous=CACHE_SYNCHRONOUS,
                )
        except sqlite3.OperationalError as exc:
            raise CacheBackendUnreadable(str(exc)) from exc
        except sqlite3.Error as exc:
            raise CacheBackendUnusable(str(exc)) from exc
        except OSError as exc:
            raise CacheBackendUnreadable(str(exc)) from exc

    def __enter__(self) -> CacheBackend:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._connection.close()

    # -- meta envelope -----------------------------------------------------

    def read_meta(self) -> dict[str, str]:
        try:
            rows = self._connection.execute(
                f"SELECT key, value FROM {META_TABLE}"
            ).fetchall()
        except sqlite3.Error as exc:
            raise CacheBackendUnusable(str(exc)) from exc
        return {
            str(key): str(value)
            for key, value in rows
            if isinstance(key, str) and isinstance(value, str)
        }

    def write_meta(
        self,
        *,
        version: str,
        python_tag: str,
        fingerprint_version: str,
        generation: int,
    ) -> None:
        checksum = envelope_checksum(
            version=version,
            python_tag=python_tag,
            fingerprint_version=fingerprint_version,
        )
        self._executemany(
            f"INSERT INTO {META_TABLE}(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (
                (META_KEY_VERSION, version),
                (META_KEY_PYTHON_TAG, python_tag),
                (META_KEY_FINGERPRINT, fingerprint_version),
                (META_KEY_CHECKSUM, checksum),
                (META_KEY_GENERATION, str(generation)),
            ),
        )

    # -- file entry rows ---------------------------------------------------

    def iter_entries(self, version: str) -> Iterator[tuple[str, object]]:
        """Yield ``(wire_path, entry)`` for every row that verifies.

        A row whose checksum or payload does not survive verification is
        skipped, not raised: a corrupt row is one cache miss, and the store
        keeps serving every other row.
        """

        try:
            cursor = self._connection.execute(
                "SELECT wire_path, payload, checksum FROM cache_files "
                "ORDER BY wire_path"
            )
            for wire_path, payload, checksum in cursor:
                if not isinstance(wire_path, str) or not isinstance(checksum, str):
                    continue
                entry = _decode_verified_row(wire_path, payload, checksum, version)
                if entry is not None:
                    yield wire_path, entry
        except sqlite3.Error as exc:
            raise CacheBackendUnusable(str(exc)) from exc

    def upsert_entries(
        self,
        entries: Mapping[str, object],
        *,
        version: str,
        generation: int,
    ) -> int:
        rows = [
            (
                wire_path,
                _encode_payload(entry),
                row_checksum(version=version, wire_path=wire_path, entry=entry),
                generation,
            )
            for wire_path, entry in sorted(entries.items())
        ]
        if not rows:
            return 0
        self._executemany(
            "INSERT INTO cache_files(wire_path, payload, checksum, generation) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(wire_path) DO UPDATE SET "
            "payload=excluded.payload, checksum=excluded.checksum, "
            "generation=excluded.generation",
            rows,
        )
        return len(rows)

    def delete_entries(self, wire_paths: Sequence[str]) -> int:
        if not wire_paths:
            return 0
        self._executemany(
            "DELETE FROM cache_files WHERE wire_path = ?",
            [(wire_path,) for wire_path in sorted(wire_paths)],
        )
        return len(wire_paths)

    def clear_entries(self) -> int:
        """Drop every row, for a store whose generation was refused."""

        removed = self.entry_count()
        self._executemany("DELETE FROM cache_files", ((),))
        return removed

    def entry_count(self) -> int:
        try:
            row = self._connection.execute(
                "SELECT COUNT(*) FROM cache_files"
            ).fetchone()
        except sqlite3.Error as exc:
            raise CacheBackendUnusable(str(exc)) from exc
        return int(row[0]) if row else 0

    def payload_bytes(self) -> int:
        """Total cached content bytes.

        The budget is measured in content, not in filesystem allocation: page
        counts move with SQLite's free-list and would make the same cache
        answer differently on two machines.
        """

        try:
            row = self._connection.execute(
                "SELECT COALESCE(SUM(LENGTH(payload)), 0) FROM cache_files"
            ).fetchone()
        except sqlite3.Error as exc:
            raise CacheBackendUnusable(str(exc)) from exc
        return int(row[0]) if row else 0

    # -- singleton payloads ------------------------------------------------

    def read_singleton(self, key: str, version: str) -> object | None:
        try:
            row = self._connection.execute(
                "SELECT payload, checksum FROM cache_singletons WHERE key = ?",
                (key,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise CacheBackendUnusable(str(exc)) from exc
        if row is None:
            return None
        payload, checksum = row
        if not isinstance(checksum, str):
            return None
        return _decode_verified_row(key, payload, checksum, version)

    def write_singleton(self, key: str, value: object, *, version: str) -> None:
        self._executemany(
            "INSERT INTO cache_singletons(key, payload, checksum) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET "
            "payload=excluded.payload, checksum=excluded.checksum",
            (
                (
                    key,
                    _encode_payload(value),
                    row_checksum(version=version, wire_path=key, entry=value),
                ),
            ),
        )

    def delete_singleton(self, key: str) -> None:
        self._executemany("DELETE FROM cache_singletons WHERE key = ?", ((key,),))

    # -- budget ------------------------------------------------------------

    def evict_to_budget(
        self,
        *,
        max_bytes: int,
        generation: int,
    ) -> tuple[int, int]:
        """Evict rows an older generation left behind, until the budget is met.

        Returns ``(evicted_rows, payload_bytes_after)``.

        The generation filter below is the whole protection: rows this run
        wrote carry ``generation`` and are never candidates, so a budget can
        never take back the entries that make the next run warm. A budget too
        small to hold even the current run is reported as over budget rather
        than enforced into uselessness.

        There was a second, explicit ``protected`` set here. Mutation testing
        (M2a, 2026-09-01) removed it and every test stayed green: it could
        only ever have held paths at the current generation, which the SQL
        already excludes, so no input could reach it. A guard nothing can trip
        is a claim the code does not keep, so it is gone and the mutation now
        aims at the filter that actually does the work.
        """

        remaining = self.payload_bytes()
        if remaining <= max_bytes:
            return 0, remaining
        try:
            candidates = self._connection.execute(
                "SELECT wire_path, LENGTH(payload) FROM cache_files "
                "WHERE generation < ? ORDER BY generation ASC, wire_path ASC",
                (generation,),
            ).fetchall()
        except sqlite3.Error as exc:
            raise CacheBackendUnusable(str(exc)) from exc

        doomed: list[tuple[str]] = []
        for wire_path, length in candidates:
            if remaining <= max_bytes:
                break
            if not isinstance(wire_path, str):
                continue
            doomed.append((wire_path,))
            remaining -= int(length)
        if not doomed:
            return 0, self.payload_bytes()
        self._executemany("DELETE FROM cache_files WHERE wire_path = ?", doomed)
        try:
            self._connection.execute("PRAGMA incremental_vacuum")
            self._connection.commit()
        except sqlite3.Error as exc:
            raise CacheBackendUnusable(str(exc)) from exc
        return len(doomed), self.payload_bytes()

    # -- internals ---------------------------------------------------------

    def _executemany(
        self,
        statement: str,
        rows: Sequence[tuple[object, ...]],
    ) -> None:
        try:
            self._connection.executemany(statement, rows)
            self._connection.commit()
        except sqlite3.Error as exc:
            raise CacheBackendUnusable(str(exc)) from exc


def envelope_checksum(
    *,
    version: str,
    python_tag: str,
    fingerprint_version: str,
) -> str:
    return cache_envelope_checksum(
        version,
        {"py": python_tag, "fp": fingerprint_version},
    )


def verify_envelope(
    *,
    version: str,
    python_tag: str,
    fingerprint_version: str,
    checksum: str,
) -> bool:
    return verify_cache_envelope_checksum(
        version,
        {"py": python_tag, "fp": fingerprint_version},
        checksum,
    )


def row_checksum(*, version: str, wire_path: str, entry: object) -> str:
    return cache_envelope_checksum(version, {"p": wire_path, "e": entry})


def _encode_payload(value: object) -> bytes:
    return orjson.dumps(value, option=orjson.OPT_SORT_KEYS)


def _decode_verified_row(
    wire_path: str,
    payload: object,
    checksum: str,
    version: str,
) -> object | None:
    if not isinstance(payload, bytes | bytearray):
        return None
    entry: object
    try:
        entry = orjson.loads(bytes(payload))
    except orjson.JSONDecodeError:
        return None
    if not verify_cache_envelope_checksum(
        version,
        {"p": wire_path, "e": entry},
        checksum,
    ):
        return None
    return entry


__all__ = [
    "CACHE_BACKEND_SCHEMA_VERSION",
    "CACHE_SYNCHRONOUS",
    "META_KEY_CHECKSUM",
    "META_KEY_FINGERPRINT",
    "META_KEY_GENERATION",
    "META_KEY_PYTHON_TAG",
    "META_KEY_VERSION",
    "META_TABLE",
    "SINGLETON_SEGMENT_REPORT",
    "CacheBackend",
    "CacheBackendForeign",
    "CacheBackendUnreadable",
    "CacheBackendUnusable",
    "envelope_checksum",
    "row_checksum",
    "verify_envelope",
]
