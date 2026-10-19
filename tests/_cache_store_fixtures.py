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

import hashlib
import json
import sqlite3
from pathlib import Path

import orjson

from codeclone.cache.backend import (
    META_KEY_CHECKSUM,
    META_KEY_FINGERPRINT,
    META_KEY_GENERATION,
    META_KEY_PYTHON_TAG,
    META_KEY_SCHEMA,
    META_KEY_VERSION,
    META_TABLE,
    TABLE_DEPENDENT,
    TABLE_NEUTRAL,
    LaneDigests,
    encode_payload,
    envelope_checksum,
    identity_checksum,
    join_wire_entry,
    lane_digests,
    split_wire_entry,
)
from codeclone.cache.integrity import cache_envelope_checksum
from codeclone.cache.store import Cache
from codeclone.models import EntryIdentity

__all__ = [
    "META_KEY_CHECKSUM",
    "META_KEY_FINGERPRINT",
    "META_KEY_GENERATION",
    "META_KEY_PYTHON_TAG",
    "META_KEY_SCHEMA",
    "META_KEY_VERSION",
    "META_TABLE",
    "TABLE_DEPENDENT",
    "TABLE_NEUTRAL",
    "break_identity_checksum",
    "drop_cache_meta",
    "envelope_checksum",
    "index_names",
    "open_store",
    "overwrite_lane",
    "read_cache_meta",
    "read_cache_rows",
    "read_identity_columns",
    "read_lane_bytes",
    "set_identity_column",
    "set_lane_digest_column",
    "sole_cache_row",
    "swap_lane_bytes",
    "transcribe_to_schema_two",
    "write_cache_meta",
    "write_cache_row",
    "write_lane_bytes",
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


def read_identity_columns(cache_path: Path) -> dict[str, dict[str, object]]:
    """The identity row per path, as columns -- what a validity decision reads.

    Deliberately not reassembled into a wire entry: a test about the schema
    should be able to see that ``stat_mtime_ns`` is an integer in an integer
    column, not a number that survived a JSON round trip.
    """

    with open_store(cache_path) as conn:
        conn.row_factory = sqlite3.Row
        return {
            str(row["wire_path"]): dict(row)
            for row in conn.execute("SELECT * FROM cache_entry")
        }


def read_cache_rows(cache_path: Path) -> dict[str, object]:
    """Every stored entry, rebuilt into the wire shape the encoder produced.

    The reassembly goes through the product's own ``join_wire_entry``, so a
    test that reads a field is reading what the cache would hand the decoder.
    """

    rows: dict[str, object] = {}
    with open_store(cache_path) as conn:
        conn.row_factory = sqlite3.Row
        for row in conn.execute("SELECT * FROM cache_entry"):
            file_id = int(row["file_id"])
            neutral = conn.execute(
                f"SELECT payload FROM {TABLE_NEUTRAL} WHERE file_id = ?", (file_id,)
            ).fetchone()
            dependent = conn.execute(
                f"SELECT payload FROM {TABLE_DEPENDENT} WHERE file_id = ?", (file_id,)
            ).fetchone()
            if neutral is None or dependent is None:
                continue
            identity = _identity_of(row)
            rows[str(row["wire_path"])] = join_wire_entry(
                identity,
                json.loads(bytes(neutral[0])),
                json.loads(bytes(dependent[0])),
            )
    return rows


def write_cache_row(
    cache_path: Path,
    wire_path: str,
    entry: object,
    *,
    version: str | None = None,
) -> None:
    """Store one complete wire entry, split across the schema as the cache does.

    ``version`` mints the identity checksum under a different generation mark,
    which is how a test forges a row the running build must refuse.
    """

    resolved = Cache._CACHE_VERSION if version is None else version
    assert isinstance(entry, dict)
    identity, neutral, dependent = split_wire_entry(
        wire_path, {str(k): v for k, v in entry.items()}
    )
    digests = lane_digests(neutral, dependent)
    with open_store(cache_path) as conn:
        conn.execute(
            "INSERT INTO cache_entry("
            "wire_path, binding_version, stat_mtime_ns, stat_size, source_digest, "
            "git_blob_format, git_blob_id, neutral_profile, dependent_profile, "
            "binding_context, clone_channels, generation, last_used_epoch, "
            "neutral_bytes, dependent_bytes, neutral_digest, dependent_digest, "
            "checksum) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,1,1,?,?,?,?,?) "
            "ON CONFLICT(wire_path) DO UPDATE SET "
            "binding_version=excluded.binding_version, "
            "stat_mtime_ns=excluded.stat_mtime_ns, stat_size=excluded.stat_size, "
            "source_digest=excluded.source_digest, "
            "neutral_bytes=excluded.neutral_bytes, "
            "dependent_bytes=excluded.dependent_bytes, "
            "neutral_digest=excluded.neutral_digest, "
            "dependent_digest=excluded.dependent_digest, "
            "checksum=excluded.checksum",
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
                identity.neutral_bytes,
                identity.dependent_bytes,
                digests.neutral,
                digests.dependent,
                identity_checksum(version=resolved, identity=identity, digests=digests),
            ),
        )
        file_id = int(
            conn.execute(
                "SELECT file_id FROM cache_entry WHERE wire_path = ?", (wire_path,)
            ).fetchone()[0]
        )
        for table, payload in ((TABLE_NEUTRAL, neutral), (TABLE_DEPENDENT, dependent)):
            conn.execute(
                f"INSERT INTO {table}(file_id, payload) VALUES (?,?) "
                "ON CONFLICT(file_id) DO UPDATE SET payload=excluded.payload",
                (file_id, payload),
            )


def overwrite_lane(
    cache_path: Path, wire_path: str, table: str, payload: object
) -> int:
    """Replace one lane's bytes, leaving the identity row intact.

    The schema's own failure mode: identity says an entry exists and its
    checksum holds, but the lane behind it does not decode. That has to cost
    one entry and not the store.
    """

    raw = payload if isinstance(payload, bytes) else encode_payload(payload)
    with open_store(cache_path) as conn:
        file_id = int(
            conn.execute(
                "SELECT file_id FROM cache_entry WHERE wire_path = ?", (wire_path,)
            ).fetchone()[0]
        )
        conn.execute(
            f"UPDATE {table} SET payload = ? WHERE file_id = ?", (raw, file_id)
        )
    return file_id


def set_identity_column(
    cache_path: Path,
    wire_path: str,
    column: str,
    value: object,
    *,
    version: str | None = None,
) -> None:
    """Change one identity column and re-mint the row's checksum.

    Without the re-mint the row would fail the integrity gate and every test
    using this would pass for that reason instead of the one it names.
    """

    resolved = Cache._CACHE_VERSION if version is None else version
    with open_store(cache_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute(
            f"UPDATE cache_entry SET {column} = ? WHERE wire_path = ?",
            (value, wire_path),
        )
        row = conn.execute(
            "SELECT * FROM cache_entry WHERE wire_path = ?", (wire_path,)
        ).fetchone()
        conn.execute(
            "UPDATE cache_entry SET checksum = ? WHERE wire_path = ?",
            (
                identity_checksum(
                    version=resolved,
                    identity=_identity_of(row),
                    digests=_digests_of(row),
                ),
                wire_path,
            ),
        )


def break_identity_checksum(cache_path: Path, wire_path: str) -> None:
    with open_store(cache_path) as conn:
        conn.execute(
            "UPDATE cache_entry SET checksum = 'wrong' WHERE wire_path = ?",
            (wire_path,),
        )


def index_names(cache_path: Path) -> set[str]:
    """Indexes the store actually created, for the per-index mutation tests."""

    with open_store(cache_path) as conn:
        return {
            str(name)
            for (name,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' "
                "AND name NOT LIKE 'sqlite_%'"
            )
        }


def sole_cache_row(cache_path: Path) -> tuple[str, object]:
    rows = read_cache_rows(cache_path)
    assert len(rows) == 1, rows
    return next(iter(rows.items()))


def _identity_of(row: sqlite3.Row) -> EntryIdentity:
    return EntryIdentity(
        wire_path=str(row["wire_path"]),
        binding_version=str(row["binding_version"]),
        stat_mtime_ns=int(row["stat_mtime_ns"]),
        stat_size=int(row["stat_size"]),
        source_digest=bytes(row["source_digest"]),
        git_blob_format=(
            None if row["git_blob_format"] is None else str(row["git_blob_format"])
        ),
        git_blob_id=(None if row["git_blob_id"] is None else bytes(row["git_blob_id"])),
        neutral_profile=bytes(row["neutral_profile"]),
        dependent_profile=bytes(row["dependent_profile"]),
        binding_context=bytes(row["binding_context"]),
        clone_channels=tuple(c for c in str(row["clone_channels"]).split(",") if c),
        neutral_bytes=int(row["neutral_bytes"]),
        dependent_bytes=int(row["dependent_bytes"]),
    )


#: The content-digest column that names each lane's bytes, where the store has
#: one. Looked up on the live table rather than assumed, so these helpers also
#: run against a store that predates the columns.
_LANE_DIGEST_COLUMNS = {
    TABLE_NEUTRAL: "neutral_digest",
    TABLE_DEPENDENT: "dependent_digest",
}


def _file_id(conn: sqlite3.Connection, wire_path: str) -> int:
    row = conn.execute(
        "SELECT file_id FROM cache_entry WHERE wire_path = ?", (wire_path,)
    ).fetchone()
    assert row is not None, wire_path
    return int(row[0])


def _entry_columns(conn: sqlite3.Connection) -> set[str]:
    return {str(row[1]) for row in conn.execute("PRAGMA table_info(cache_entry)")}


def read_lane_bytes(cache_path: Path, wire_path: str, table: str) -> bytes:
    with open_store(cache_path) as conn:
        row = conn.execute(
            f"SELECT payload FROM {table} WHERE file_id = ?",
            (_file_id(conn, wire_path),),
        ).fetchone()
    assert row is not None, (wire_path, table)
    return bytes(row[0])


def write_lane_bytes(
    cache_path: Path,
    wire_path: str,
    table: str,
    payload: bytes,
    *,
    as_writer: bool,
    version: str | None = None,
) -> None:
    """Replace one lane's stored bytes.

    ``as_writer=False`` changes the bytes under an untouched identity row --
    what a torn write, a stale backup restored over half a store or a flipped
    bit does. ``as_writer=True`` also stores what a writer that produced these
    bytes would have stored beside them: where the store keeps a content
    digest, the lane's digest column and the identity checksum are re-minted
    over the new bytes. That is the only way a test reaches the readers that
    sit BEHIND the integrity check -- a consistent row this build still cannot
    read -- without the check refusing it first.
    """

    resolved = Cache._CACHE_VERSION if version is None else version
    with open_store(cache_path) as conn:
        conn.row_factory = sqlite3.Row
        file_id = _file_id(conn, wire_path)
        conn.execute(
            f"UPDATE {table} SET payload = ? WHERE file_id = ?", (payload, file_id)
        )
        column = _LANE_DIGEST_COLUMNS[table]
        if not as_writer or column not in _entry_columns(conn):
            return
        conn.execute(
            f"UPDATE cache_entry SET {column} = ? WHERE file_id = ?",
            (hashlib.sha256(payload).digest(), file_id),
        )
        _remint_identity_checksum(conn, file_id, version=resolved)


def swap_lane_bytes(
    cache_path: Path,
    wire_path: str,
    table: str,
    *,
    anchor: bytes,
    needle: bytes,
    replacement: bytes,
    as_writer: bool = False,
) -> None:
    """Replace the first ``needle`` after ``anchor`` in one lane, length kept.

    The swap is asserted to land: a needle that matched nothing would leave
    the warm run reading a sound row, and a test would pass over a corruption
    that never happened.
    """

    assert len(needle) == len(replacement) and needle != replacement
    payload = read_lane_bytes(cache_path, wire_path, table)
    start = payload.find(anchor)
    assert start >= 0, (anchor, wire_path, table)
    at = payload.find(needle, start)
    assert at >= 0, (needle, wire_path, table)
    changed = payload[:at] + replacement + payload[at + len(needle) :]
    assert len(changed) == len(payload)
    write_lane_bytes(cache_path, wire_path, table, changed, as_writer=as_writer)


def set_lane_digest_column(
    cache_path: Path, wire_path: str, table: str, digest: bytes
) -> None:
    """Overwrite one lane's digest column and NOT the identity checksum.

    Against a store without the column there is nothing to overwrite; the
    lane bytes a caller changed beside it are then guarded by nothing at all,
    which is the defect the column exists to close.
    """

    with open_store(cache_path) as conn:
        column = _LANE_DIGEST_COLUMNS[table]
        if column not in _entry_columns(conn):
            return
        conn.execute(
            f"UPDATE cache_entry SET {column} = ? WHERE wire_path = ?",
            (digest, wire_path),
        )


def _remint_identity_checksum(
    conn: sqlite3.Connection, file_id: int, *, version: str
) -> None:
    row = conn.execute(
        "SELECT * FROM cache_entry WHERE file_id = ?", (file_id,)
    ).fetchone()
    conn.execute(
        "UPDATE cache_entry SET checksum = ? WHERE file_id = ?",
        (
            identity_checksum(
                version=version, identity=_identity_of(row), digests=_digests_of(row)
            ),
            file_id,
        ),
    )


def _digests_of(row: sqlite3.Row) -> LaneDigests:
    return LaneDigests(
        neutral=bytes(row["neutral_digest"]),
        dependent=bytes(row["dependent_digest"]),
    )


# -- the previous physical generation -----------------------------------------
#
# Byte for byte the schema bd7223a3 created (``CACHE_BACKEND_SCHEMA_VERSION``
# "2"), and the checksum it minted: the identity alone, lane lengths included,
# lane CONTENT not. A literal on purpose -- a helper that derived it from the
# running build would describe whatever the build now is, not what a user's
# disk already holds.

_SCHEMA_TWO = "2"
_SCHEMA_TWO_DDL = (
    f"CREATE TABLE {META_TABLE}(key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE TABLE cache_entry("
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
    f"CREATE TABLE {TABLE_NEUTRAL}("
    "file_id INTEGER PRIMARY KEY REFERENCES cache_entry(file_id) "
    "ON DELETE CASCADE, payload BLOB NOT NULL)",
    f"CREATE TABLE {TABLE_DEPENDENT}("
    "file_id INTEGER PRIMARY KEY REFERENCES cache_entry(file_id) "
    "ON DELETE CASCADE, payload BLOB NOT NULL)",
    "CREATE TABLE cache_singletons("
    "key TEXT PRIMARY KEY, payload BLOB NOT NULL, checksum TEXT NOT NULL)",
    "CREATE UNIQUE INDEX ux_entry_path ON cache_entry(wire_path)",
    "CREATE INDEX ix_entry_gen ON cache_entry(generation, wire_path)",
    "CREATE INDEX ix_entry_used ON cache_entry(last_used_epoch)",
)
_SCHEMA_TWO_COLUMNS = (
    "file_id",
    "wire_path",
    "binding_version",
    "stat_mtime_ns",
    "stat_size",
    "source_digest",
    "git_blob_format",
    "git_blob_id",
    "neutral_profile",
    "dependent_profile",
    "binding_context",
    "clone_channels",
    "generation",
    "last_used_epoch",
    "neutral_bytes",
    "dependent_bytes",
)


def _schema_two_checksum(version: str, row: sqlite3.Row) -> str:
    identity = _identity_of(row)
    return cache_envelope_checksum(
        version,
        {
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
        },
    )


def transcribe_to_schema_two(source: Path, target: Path) -> None:
    """Write ``source``'s entries as the previous generation would have.

    Every identity column, every lane byte and every singleton is carried
    over unchanged; only the shape is the old one: no content digests, the
    old identity checksum, the old singleton checksum (over the decoded
    value) and ``schema_version`` "2". A row that verified there is exactly
    a row a user's disk holds after running bd7223a3.
    """

    meta = read_cache_meta(source)
    version = meta[META_KEY_VERSION]
    with open_store(source) as src, open_store(target) as dst:
        src.row_factory = sqlite3.Row
        for statement in _SCHEMA_TWO_DDL:
            dst.execute(statement)
        placeholders = ",".join("?" * (len(_SCHEMA_TWO_COLUMNS) + 1))
        for row in src.execute("SELECT * FROM cache_entry ORDER BY file_id"):
            dst.execute(
                f"INSERT INTO cache_entry({','.join(_SCHEMA_TWO_COLUMNS)}, checksum) "
                f"VALUES ({placeholders})",
                (
                    *(row[column] for column in _SCHEMA_TWO_COLUMNS),
                    _schema_two_checksum(version, row),
                ),
            )
        for table in (TABLE_NEUTRAL, TABLE_DEPENDENT):
            dst.executemany(
                f"INSERT INTO {table}(file_id, payload) VALUES (?, ?)",
                src.execute(f"SELECT file_id, payload FROM {table}").fetchall(),
            )
        for key, payload in src.execute("SELECT key, payload FROM cache_singletons"):
            value = orjson.loads(bytes(payload))
            dst.execute(
                "INSERT INTO cache_singletons(key, payload, checksum) VALUES (?,?,?)",
                (
                    key,
                    bytes(payload),
                    cache_envelope_checksum(version, {"p": key, "e": value}),
                ),
            )
        dst.executemany(
            f"INSERT INTO {META_TABLE}(key, value) VALUES (?, ?)",
            sorted(
                {
                    **{
                        key: value
                        for key, value in meta.items()
                        if key != META_KEY_SCHEMA
                    },
                    META_KEY_SCHEMA: _SCHEMA_TWO,
                    META_KEY_CHECKSUM: envelope_checksum(
                        version=version,
                        python_tag=meta[META_KEY_PYTHON_TAG],
                        fingerprint_version=meta[META_KEY_FINGERPRINT],
                    ),
                }.items()
            ),
        )
