# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The analysis cache's storage: a schema shaped by its measured access path.

Why this shape
--------------
The cache was one JSON monolith at ``.codeclone/cache.json`` (50 MB here).
``save()`` ignored ``max_size_bytes`` while ``load()`` refused any document
above it, so a repository whose cache outgrew the cap lost the warm path on
every later run, silently.  Row addressing removed that premise: an entry is
read by key, so what a load holds is bounded by the row, not by the store.

Row addressing alone was not enough, and the measurement said so.  A first
form kept the whole wire entry as one BLOB per file -- a document in a column.
Measured on this repository (i7-7700T, A/B/B/A interleaved, medians): cold,
warm and delta times were indistinguishable from the monolith's, because the
within-form spread exceeded the between-form difference.  Only write volume
and concurrency moved.  A shape that cannot express what the reader actually
asks for cannot pay, however it is addressed.

So the schema follows the access path, which is measurable rather than
arguable.  ``core.discovery`` calls ``get_file_entry`` once per discovered
file, then proves content identity, then asks ``cache_reuse_decision`` -- and
only on a hit does it touch a payload.  Every one of those steps reads the
same handful of small facts: the stat pair, the source digest, the git blob
id, the binding context, the two profile digests, the binding version, and
the materialised clone channels.  Measured over this repository's 52 MB
store, those facts are **0.48%** of it; the two heavy lanes are the rest
(``n`` 61.1%, ``d`` 37.6%).

Hence three tables:

``cache_entry``
    One row per file, typed columns, every fact a validity decision reads and
    nothing else -- 247 KB for 1133 files.  Integers are stored as integers,
    so a stat comparison is a comparison and not a JSON decode; digests are
    raw bytes rather than hex text, and their domain and algorithm live in
    the schema below because they are constant per column.  A constant
    repeated 1133 times is not data.

``cache_neutral`` / ``cache_dependent``
    The two heavy lanes, keyed by ``file_id``, fetched only when that lane is
    actually reused.  They are separate tables because they are separately
    invalidated: a module manifest move changes every ``dependent_profile``
    and no ``neutral_profile``, so it rewrites 1133 dependent rows and leaves
    32 MB of neutral payload untouched.  One table could not express that.

Indexes, each with a measured reason:

``ux_entry_path``   the ``wire_path`` lookup, and the conflict target the
                    upsert names -- without the UNIQUE constraint the
                    write path has no ``ON CONFLICT`` to resolve, so this
                    one is structural, not an optimisation.
``ix_entry_gen``    eviction ordering, oldest generation first.
``ix_entry_used``   the TTL sweep -- covering, so it never reads a table row.

All three together cost +3.7% on the insert path and 94 KB.  Each is proved
reachable by a mutation that drops it: an index whose absence changes neither
the query plan nor a number is not an index this store keeps.

Semantic boundary (hard)
------------------------
This is **disposable cache state**, not canonical run state.  It shares the
SQLite infrastructure under ``.codeclone/db/`` with the immutable run store,
and shares nothing else:

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
is re-derived from source at the price of a cold file, whereas a torn *run* is
a lost authority record.  The run store's ``FULL`` is untouched by this choice.

Integrity
---------
Each entry carries a checksum over its identity, so a row that fails
verification is dropped as one cache miss instead of condemning the store.
The meta envelope is checksummed over
``{version, python_tag, fingerprint_version}`` for the same reason the JSON
envelope bound ``v``: a generation retagged in place must be refused, not
trusted.  Like its predecessor this is an INTEGRITY check, not authentication
-- cache trust equals source trust; see ``integrity.cache_payload_checksum``
for the ruled threat model.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from pathlib import Path
from types import TracebackType
from typing import Final

import orjson

from ..models import EntryIdentity
from ..utils.sqlite_store import (
    initialize_schema_v1,
    open_sqlite_db,
    open_sqlite_db_readonly,
)
from .integrity import cache_envelope_checksum, verify_cache_envelope_checksum

CACHE_BACKEND_SCHEMA_VERSION: Final = "2"

#: ``synchronous`` for the disposable cache.  See the module docstring: this
#: is intentionally not the run store's ``FULL``.
CACHE_SYNCHRONOUS: Final = "NORMAL"

META_TABLE: Final = "cache_backend_meta"
META_KEY_VERSION: Final = "cache_version"
META_KEY_PYTHON_TAG: Final = "python_tag"
META_KEY_FINGERPRINT: Final = "fingerprint_version"
META_KEY_CHECKSUM: Final = "envelope_checksum"
META_KEY_GENERATION: Final = "generation"
META_KEY_SCHEMA: Final = "schema_version"

SINGLETON_SEGMENT_REPORT: Final = "segment_report_projection"

TABLE_NEUTRAL: Final = "cache_neutral"
TABLE_DEPENDENT: Final = "cache_dependent"

#: Digest domain and algorithm per identity column.  These are constant for
#: every entry, so they belong to the schema and not to 1133 copies of
#: themselves.  A write whose digest disagrees is refused rather than stored
#: lossily -- see :func:`split_wire_entry`.
DIGEST_DOMAINS: Final[dict[str, str]] = {
    "sd": "codeclone.source-content.v1",
    "bc": "codeclone.cache.binding-context.v1",
    "np": "codeclone.cache.profile.neutral.v1",
    "dp": "codeclone.cache.profile.dependent.v1",
}
DIGEST_ALGORITHM: Final = "sha256"

_DDL: Final = (
    f"CREATE TABLE IF NOT EXISTS {META_TABLE}("
    "key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    # Every column below is read by a validity decision; nothing else is here.
    "CREATE TABLE IF NOT EXISTS cache_entry("
    "file_id INTEGER PRIMARY KEY, "
    "wire_path TEXT NOT NULL, "
    "binding_version TEXT NOT NULL, "
    "stat_mtime_ns INTEGER NOT NULL, "
    "stat_size INTEGER NOT NULL, "
    "source_digest BLOB NOT NULL, "
    "git_blob_format TEXT, "
    "git_blob_id BLOB, "
    "neutral_profile BLOB NOT NULL, "
    "dependent_profile BLOB NOT NULL, "
    "binding_context BLOB NOT NULL, "
    "clone_channels TEXT NOT NULL, "
    "generation INTEGER NOT NULL, "
    "last_used_epoch INTEGER NOT NULL, "
    "neutral_bytes INTEGER NOT NULL, "
    "dependent_bytes INTEGER NOT NULL, "
    "checksum TEXT NOT NULL)",
    f"CREATE TABLE IF NOT EXISTS {TABLE_NEUTRAL}("
    "file_id INTEGER PRIMARY KEY REFERENCES cache_entry(file_id) "
    "ON DELETE CASCADE, payload BLOB NOT NULL)",
    f"CREATE TABLE IF NOT EXISTS {TABLE_DEPENDENT}("
    "file_id INTEGER PRIMARY KEY REFERENCES cache_entry(file_id) "
    "ON DELETE CASCADE, payload BLOB NOT NULL)",
    "CREATE TABLE IF NOT EXISTS cache_singletons("
    "key TEXT PRIMARY KEY, payload BLOB NOT NULL, checksum TEXT NOT NULL)",
)

_INDEXES: Final = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_entry_path ON cache_entry(wire_path)",
    "CREATE INDEX IF NOT EXISTS ix_entry_gen ON cache_entry(generation)",
    "CREATE INDEX IF NOT EXISTS ix_entry_used ON cache_entry(last_used_epoch)",
)

_IDENTITY_COLUMNS: Final = (
    "file_id, wire_path, binding_version, stat_mtime_ns, stat_size, "
    "source_digest, git_blob_format, git_blob_id, neutral_profile, "
    "dependent_profile, binding_context, clone_channels, generation, "
    "last_used_epoch, neutral_bytes, dependent_bytes, checksum"
)
_CHECKSUM_AT: Final = 16


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

    Distinct from corruption because nothing is damaged: the file is intact
    and simply belongs to something else.  Reporting it as corrupt would
    invite a user to delete a healthy database of their own.
    """


class WireShapeRefused(Exception):
    """A wire entry the schema cannot store without losing something.

    Raised instead of writing a lossy row.  The identity columns drop each
    digest's domain and algorithm because they are schema constants; if an
    entry ever carries different ones, that is a contract change and the cache
    must say so rather than quietly rebuild the wrong digest on read.
    """


def _validate_schema(connection: sqlite3.Connection) -> None:
    """Refuse a database that is not a cache store, without writing to it.

    ``load`` opens read-only on purpose.  A user is free to point
    ``--cache-path`` at any file, and creating our tables inside somebody
    else's database just to discover it is not ours would be a write performed
    by a read.  A missing schema surfaces here as a refusal instead.
    """

    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (META_TABLE,),
    ).fetchone()
    if row is None:
        msg = "cache database has no cache schema"
        raise CacheBackendForeign(msg)


def _ensure_schema(connection: sqlite3.Connection) -> None:
    # ``auto_vacuum`` is storage management, not part of the durability trio
    # the shared owner holds, and it only binds before the first table exists
    # -- so it belongs here, at schema creation, and is set exactly once.
    # Without it a GC sweep would free pages that never return to the
    # filesystem.
    connection.execute("PRAGMA auto_vacuum=INCREMENTAL")
    connection.execute("PRAGMA foreign_keys=ON")
    initialize_schema_v1(
        connection,
        ddl_statements=_DDL,
        index_statements=_INDEXES,
        meta_table=META_TABLE,
        seed_meta={META_KEY_SCHEMA: CACHE_BACKEND_SCHEMA_VERSION},
    )


class CacheBackend:
    """One open connection to the cache database, for one load or one save.

    The connection is deliberately short-lived: the cache is touched a small,
    bounded number of times per run, so holding one between them would buy
    nothing and would keep a WAL lock alive across the whole analysis.

    ``queries``, ``writes`` and ``rows`` count the SQLite work this handle did.
    The caller reads them back into the ``db_queries`` / ``db_writes`` /
    ``db_rows`` span counters, which is what puts the cache into the observer's
    ``db_cost`` section.  A cache whose work cannot be looked at is a black
    box, and the store that accelerates every run is the last place that should
    be one.
    """

    def __init__(self, path: Path, *, read_only: bool = False) -> None:
        self._path = path
        self._read_only = read_only
        self.queries = 0
        self.writes = 0
        self.rows = 0
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
                    foreign_keys=True,
                    synchronous=CACHE_SYNCHRONOUS,
                )
        except CacheBackendForeign:
            raise
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
        rows = self._query(f"SELECT key, value FROM {META_TABLE}").fetchall()
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
                (META_KEY_SCHEMA, CACHE_BACKEND_SCHEMA_VERSION),
            ),
        )

    # -- identity ----------------------------------------------------------

    def iter_identities(self, version: str) -> list[tuple[int, EntryIdentity]]:
        """Yield ``(file_id, identity)`` for every row whose checksum holds.

        This is the whole of a load.  The lanes stay on disk until somebody
        asks for one, which is the point of the schema.

        A list rather than a generator: the caller drains it into a dict
        immediately, so lazily yielding bought nothing and kept a cursor open
        across the whole loop.
        """

        rows = self._query(
            f"SELECT {_IDENTITY_COLUMNS} FROM cache_entry ORDER BY wire_path"
        ).fetchall()
        resolved = (_verified_identity(row, version) for row in rows)
        return [found for found in resolved if found is not None]

    # -- lanes -------------------------------------------------------------

    def read_lane(self, table: str, file_id: int) -> object | None:
        row = self._query(
            f"SELECT payload FROM {table} WHERE file_id = ?", (file_id,)
        ).fetchone()
        if row is None:
            return None
        payload = row[0]
        if not isinstance(payload, bytes | bytearray):
            return None
        try:
            decoded: object = orjson.loads(bytes(payload))
        except orjson.JSONDecodeError:
            return None
        return decoded

    # -- writes ------------------------------------------------------------

    def upsert_entries(
        self,
        entries: Sequence[tuple[EntryIdentity, bytes, bytes]],
        *,
        version: str,
        generation: int,
        now_epoch: int,
    ) -> int:
        """Write identity and both lanes for the entries this run moved."""

        if not entries:
            return 0
        self._executemany(
            "INSERT INTO cache_entry("
            "wire_path, binding_version, stat_mtime_ns, stat_size, "
            "source_digest, git_blob_format, git_blob_id, neutral_profile, "
            "dependent_profile, binding_context, clone_channels, generation, "
            "last_used_epoch, neutral_bytes, dependent_bytes, checksum) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(wire_path) DO UPDATE SET "
            "binding_version=excluded.binding_version, "
            "stat_mtime_ns=excluded.stat_mtime_ns, "
            "stat_size=excluded.stat_size, "
            "source_digest=excluded.source_digest, "
            "git_blob_format=excluded.git_blob_format, "
            "git_blob_id=excluded.git_blob_id, "
            "neutral_profile=excluded.neutral_profile, "
            "dependent_profile=excluded.dependent_profile, "
            "binding_context=excluded.binding_context, "
            "clone_channels=excluded.clone_channels, "
            "generation=excluded.generation, "
            "last_used_epoch=excluded.last_used_epoch, "
            "neutral_bytes=excluded.neutral_bytes, "
            "dependent_bytes=excluded.dependent_bytes, "
            "checksum=excluded.checksum",
            [
                (
                    identity.wire_path,
                    identity.binding_version,
                    identity.stat_mtime_ns,
                    identity.stat_size,
                    identity.source_digest,
                    identity.git_blob_format,
                    identity.git_blob_id,
                    identity.neutral_profile,
                    identity.dependent_profile,
                    identity.binding_context,
                    ",".join(identity.clone_channels),
                    generation,
                    now_epoch,
                    identity.neutral_bytes,
                    identity.dependent_bytes,
                    identity_checksum(version=version, identity=identity),
                )
                for identity, _neutral, _dependent in entries
            ],
            commit=False,
        )
        ids = self._file_ids([identity.wire_path for identity, _n, _d in entries])
        for table, index in ((TABLE_NEUTRAL, 1), (TABLE_DEPENDENT, 2)):
            self._executemany(
                f"INSERT INTO {table}(file_id, payload) VALUES (?,?) "
                "ON CONFLICT(file_id) DO UPDATE SET payload=excluded.payload",
                [
                    (ids[row[0].wire_path], row[index])
                    for row in entries
                    if row[0].wire_path in ids
                ],
                commit=False,
            )
        self._commit()
        return len(entries)

    def touch(self, wire_paths: Sequence[str], *, now_epoch: int) -> int:
        """Record that these entries were used, for the TTL sweep.

        A recency mark is an integer write on an indexed column, never a
        payload rewrite: an entry read on every run must not age out merely
        because its contents never changed.
        """

        ordered = sorted(set(wire_paths))
        if not ordered:
            return 0
        self._executemany(
            "UPDATE cache_entry SET last_used_epoch = ? WHERE wire_path = ?",
            [(now_epoch, wire_path) for wire_path in ordered],
        )
        return len(ordered)

    def delete_entries(self, wire_paths: Sequence[str]) -> int:
        return self._delete_where("wire_path", wire_paths)

    def delete_by_ids(self, file_ids: Sequence[int]) -> int:
        return self._delete_where("file_id", file_ids)

    def clear_entries(self) -> int:
        removed = self.entry_count()
        self._executemany("DELETE FROM cache_entry", ((),))
        return removed

    # -- accounting --------------------------------------------------------

    def entry_count(self) -> int:
        row = self._query("SELECT COUNT(*) FROM cache_entry").fetchone()
        return int(row[0]) if row else 0

    def payload_bytes(self) -> int:
        """Total cached content bytes, read off the identity columns.

        Accounting never opens a lane: the sizes are written beside the
        identity precisely so a budget question costs one small scan.
        """

        row = self._query(
            "SELECT COALESCE(SUM(neutral_bytes + dependent_bytes), 0) FROM cache_entry"
        ).fetchone()
        return int(row[0]) if row else 0

    def eviction_candidates(self, *, generation: int) -> list[tuple[int, str, int]]:
        """Rows an older generation left behind, oldest first.

        The generation filter is the whole protection for the current run:
        rows this run wrote carry ``generation`` and are never candidates, so
        a budget can never take back the entries that make the next run warm.
        """

        return [
            (int(file_id), str(wire_path), int(size))
            for file_id, wire_path, size in self._query(
                "SELECT file_id, wire_path, neutral_bytes + dependent_bytes "
                "FROM cache_entry WHERE generation < ? "
                "ORDER BY generation ASC, wire_path ASC",
                (generation,),
            ).fetchall()
        ]

    def expired_ids(self, *, older_than_epoch: int) -> list[int]:
        """Entries untouched since the deadline.  Served by a covering index."""

        return [
            int(row[0])
            for row in self._query(
                "SELECT file_id FROM cache_entry WHERE last_used_epoch < ?",
                (older_than_epoch,),
            ).fetchall()
        ]

    def orphan_ids(self, live_wire_paths: frozenset[str]) -> list[int]:
        """Entries for files the repository no longer has."""

        return [
            int(file_id)
            for file_id, wire_path in self._query(
                "SELECT file_id, wire_path FROM cache_entry"
            ).fetchall()
            if str(wire_path) not in live_wire_paths
        ]

    def corrupt_ids(self, version: str) -> list[int]:
        """Entries whose identity checksum no longer holds."""

        return [
            int(row[0])
            for row in self._query(
                f"SELECT {_IDENTITY_COLUMNS} FROM cache_entry"
            ).fetchall()
            if _verified_identity(row, version) is None
        ]

    def reclaim(self) -> None:
        """Return freed pages to the filesystem after a sweep."""

        try:
            self._connection.execute("PRAGMA incremental_vacuum")
            self._connection.commit()
        except sqlite3.Error as exc:
            raise CacheBackendUnusable(str(exc)) from exc

    # -- singleton payloads ------------------------------------------------

    def read_singleton(self, key: str, version: str) -> object | None:
        row = self._query(
            "SELECT payload, checksum FROM cache_singletons WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        payload, checksum = row
        if not isinstance(checksum, str) or not isinstance(payload, bytes | bytearray):
            return None
        try:
            value: object = orjson.loads(bytes(payload))
        except orjson.JSONDecodeError:
            return None
        if not verify_cache_envelope_checksum(
            version, {"p": key, "e": value}, checksum
        ):
            return None
        return value

    def write_singleton(self, key: str, value: object, *, version: str) -> None:
        self._executemany(
            "INSERT INTO cache_singletons(key, payload, checksum) VALUES (?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET "
            "payload=excluded.payload, checksum=excluded.checksum",
            (
                (
                    key,
                    encode_payload(value),
                    cache_envelope_checksum(version, {"p": key, "e": value}),
                ),
            ),
        )

    def delete_singleton(self, key: str) -> None:
        self._executemany("DELETE FROM cache_singletons WHERE key = ?", ((key,),))

    # -- internals ---------------------------------------------------------

    def _file_ids(self, wire_paths: Sequence[str]) -> dict[str, int]:
        found: dict[str, int] = {}
        for wire_path in wire_paths:
            row = self._query(
                "SELECT file_id FROM cache_entry WHERE wire_path = ?", (wire_path,)
            ).fetchone()
            if row is not None:
                found[wire_path] = int(row[0])
        return found

    def _delete_where(self, column: str, values: Sequence[object]) -> int:
        """Delete by one indexed column.

        The column name is never caller data: both callers name a literal, so
        this interpolation cannot carry anything a user supplied, and the
        values stay bound.
        """

        ordered = sorted(set(values), key=repr)
        if not ordered:
            return 0
        self._executemany(
            f"DELETE FROM cache_entry WHERE {column} = ?",
            [(value,) for value in ordered],
        )
        return len(ordered)

    def _query(self, statement: str, params: tuple[object, ...] = ()) -> sqlite3.Cursor:
        self.queries += 1
        try:
            return self._connection.execute(statement, params)
        except sqlite3.Error as exc:
            raise CacheBackendUnusable(str(exc)) from exc

    def _executemany(
        self,
        statement: str,
        rows: Sequence[tuple[object, ...]],
        *,
        commit: bool = True,
    ) -> None:
        self.queries += 1
        self.writes += 1
        self.rows += len(rows)
        try:
            self._connection.executemany(statement, rows)
            if commit:
                self._connection.commit()
        except sqlite3.Error as exc:
            raise CacheBackendUnusable(str(exc)) from exc

    def _commit(self) -> None:
        try:
            self._connection.commit()
        except sqlite3.Error as exc:
            raise CacheBackendUnusable(str(exc)) from exc


# -- wire <-> schema ---------------------------------------------------------


def split_wire_entry(
    wire_path: str, wire: dict[str, object]
) -> tuple[EntryIdentity, bytes, bytes]:
    """Take one encoded wire entry apart into identity and two lane payloads.

    The digest domains and the algorithm are checked rather than stored: they
    are schema constants, and an entry carrying different ones could not be
    rebuilt faithfully on read, so it is refused instead of silently reshaped.
    """

    neutral = dict(_as_dict(wire.get("n"), "n"))
    dependent = _as_dict(wire.get("d"), "d")
    channels = tuple(str(c) for c in _as_list(neutral.pop("mt", []), "n.mt"))
    stat = _as_list(wire.get("st"), "st")
    if len(stat) != 2:
        raise WireShapeRefused("st must carry mtime_ns and size")
    git_blob = wire.get("gb")
    if git_blob is None:
        blob_format: str | None = None
        blob_id: bytes | None = None
    else:
        pair = _as_list(git_blob, "gb")
        if len(pair) != 2:
            raise WireShapeRefused("gb must carry an object format and an id")
        blob_format = str(pair[0])
        blob_id = _unhex(str(pair[1]), "gb")
    neutral_bytes = encode_payload(neutral)
    dependent_bytes = encode_payload(dependent)
    identity = EntryIdentity(
        wire_path=wire_path,
        binding_version=str(wire.get("cb", "")),
        stat_mtime_ns=_as_int(stat[0], "st.mtime_ns"),
        stat_size=_as_int(stat[1], "st.size"),
        source_digest=_digest_value(wire.get("sd"), "sd"),
        git_blob_format=blob_format,
        git_blob_id=blob_id,
        neutral_profile=_digest_value(wire.get("np"), "np"),
        dependent_profile=_digest_value(wire.get("dp"), "dp"),
        binding_context=_digest_value(wire.get("bc"), "bc"),
        clone_channels=channels,
        neutral_bytes=len(neutral_bytes),
        dependent_bytes=len(dependent_bytes),
    )
    return identity, neutral_bytes, dependent_bytes


def join_wire_entry(
    identity: EntryIdentity,
    neutral: object,
    dependent: object,
) -> dict[str, object]:
    """Rebuild the wire entry the encoder produced.

    The inverse of :func:`split_wire_entry`; the round trip is pinned by test,
    because a schema that cannot hand the encoder's own dict back is a schema
    that quietly changes answers.
    """

    neutral_dict = dict(_as_dict(neutral, "neutral"))
    neutral_dict["mt"] = list(identity.clone_channels)
    return {
        "cb": identity.binding_version,
        "sd": _digest_row(identity.source_digest, "sd"),
        "gb": (
            None
            if identity.git_blob_id is None
            else [identity.git_blob_format, identity.git_blob_id.hex()]
        ),
        "st": [identity.stat_mtime_ns, identity.stat_size],
        "bc": _digest_row(identity.binding_context, "bc"),
        "np": _digest_row(identity.neutral_profile, "np"),
        "dp": _digest_row(identity.dependent_profile, "dp"),
        "n": neutral_dict,
        "d": _as_dict(dependent, "dependent"),
    }


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


def identity_checksum(*, version: str, identity: EntryIdentity) -> str:
    return cache_envelope_checksum(version, identity_preimage(identity))


def identity_preimage(identity: EntryIdentity) -> dict[str, object]:
    """The bytes an entry's checksum covers: its whole identity, path included.

    The path is inside the scope so a row copied under another key is refused
    rather than served as that other file's facts.
    """

    return {
        "p": identity.wire_path,
        "cb": identity.binding_version,
        "st": [identity.stat_mtime_ns, identity.stat_size],
        "sd": identity.source_digest.hex(),
        "gb": (
            None
            if identity.git_blob_id is None
            else [identity.git_blob_format, identity.git_blob_id.hex()]
        ),
        "np": identity.neutral_profile.hex(),
        "dp": identity.dependent_profile.hex(),
        "bc": identity.binding_context.hex(),
        "mt": list(identity.clone_channels),
        "nb": identity.neutral_bytes,
        "db": identity.dependent_bytes,
    }


def encode_payload(value: object) -> bytes:
    return orjson.dumps(value, option=orjson.OPT_SORT_KEYS)


def _verified_identity(
    row: tuple[object, ...], version: str
) -> tuple[int, EntryIdentity] | None:
    identity = _identity_from_row(row)
    if identity is None:
        return None
    checksum = row[_CHECKSUM_AT]
    if not isinstance(checksum, str):
        return None
    if not verify_cache_envelope_checksum(
        version, identity_preimage(identity), checksum
    ):
        return None
    return int(str(row[0])), identity


def _identity_from_row(row: tuple[object, ...]) -> EntryIdentity | None:
    try:
        return EntryIdentity(
            wire_path=str(row[1]),
            binding_version=str(row[2]),
            stat_mtime_ns=_as_int(row[3], "stat_mtime_ns"),
            stat_size=_as_int(row[4], "stat_size"),
            source_digest=_as_bytes(row[5]),
            git_blob_format=None if row[6] is None else str(row[6]),
            git_blob_id=None if row[7] is None else _as_bytes(row[7]),
            neutral_profile=_as_bytes(row[8]),
            dependent_profile=_as_bytes(row[9]),
            binding_context=_as_bytes(row[10]),
            clone_channels=tuple(c for c in str(row[11]).split(",") if c),
            neutral_bytes=_as_int(row[14], "neutral_bytes"),
            dependent_bytes=_as_int(row[15], "dependent_bytes"),
        )
    except (TypeError, ValueError, WireShapeRefused):
        return None


def _as_bytes(value: object) -> bytes:
    if not isinstance(value, bytes | bytearray):
        raise TypeError("expected a BLOB column")
    return bytes(value)


def _as_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise WireShapeRefused(f"{label} must be an integer")
    return value


def _unhex(value: str, label: str) -> bytes:
    try:
        return bytes.fromhex(value)
    except ValueError as exc:
        raise WireShapeRefused(f"{label} is not hexadecimal") from exc


def _digest_value(value: object, key: str) -> bytes:
    row = _as_list(value, key)
    if len(row) != 3:
        raise WireShapeRefused(f"{key} must carry a domain, algorithm and value")
    domain, algorithm, digest = (str(row[0]), str(row[1]), str(row[2]))
    if domain != DIGEST_DOMAINS[key] or algorithm != DIGEST_ALGORITHM:
        raise WireShapeRefused(
            f"{key} carries domain {domain!r}/{algorithm!r}, but the schema "
            f"stores {DIGEST_DOMAINS[key]!r}/{DIGEST_ALGORITHM!r} as constants"
        )
    return _unhex(digest, key)


def _digest_row(value: bytes, key: str) -> list[str]:
    return [DIGEST_DOMAINS[key], DIGEST_ALGORITHM, value.hex()]


def _as_dict(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise WireShapeRefused(f"{label} must be an object")
    return {str(k): v for k, v in value.items()}


def _as_list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise WireShapeRefused(f"{label} must be a list")
    return list(value)


__all__ = [
    "CACHE_BACKEND_SCHEMA_VERSION",
    "CACHE_SYNCHRONOUS",
    "DIGEST_ALGORITHM",
    "DIGEST_DOMAINS",
    "META_KEY_CHECKSUM",
    "META_KEY_FINGERPRINT",
    "META_KEY_GENERATION",
    "META_KEY_PYTHON_TAG",
    "META_KEY_SCHEMA",
    "META_KEY_VERSION",
    "META_TABLE",
    "SINGLETON_SEGMENT_REPORT",
    "TABLE_DEPENDENT",
    "TABLE_NEUTRAL",
    "CacheBackend",
    "CacheBackendForeign",
    "CacheBackendUnreadable",
    "CacheBackendUnusable",
    "EntryIdentity",
    "WireShapeRefused",
    "encode_payload",
    "envelope_checksum",
    "identity_checksum",
    "identity_preimage",
    "join_wire_entry",
    "split_wire_entry",
    "verify_envelope",
]
