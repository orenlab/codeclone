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
    META_KEY_SCHEMA,
    META_KEY_VERSION,
    META_TABLE,
    TABLE_DEPENDENT,
    TABLE_NEUTRAL,
    encode_payload,
    envelope_checksum,
    identity_checksum,
    join_wire_entry,
    split_wire_entry,
)
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
    "set_identity_column",
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
    with open_store(cache_path) as conn:
        conn.execute(
            "INSERT INTO cache_entry("
            "wire_path, binding_version, stat_mtime_ns, stat_size, source_digest, "
            "git_blob_format, git_blob_id, neutral_profile, dependent_profile, "
            "binding_context, clone_channels, generation, last_used_epoch, "
            "neutral_bytes, dependent_bytes, checksum) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,1,1,?,?,?) "
            "ON CONFLICT(wire_path) DO UPDATE SET "
            "binding_version=excluded.binding_version, "
            "stat_mtime_ns=excluded.stat_mtime_ns, stat_size=excluded.stat_size, "
            "source_digest=excluded.source_digest, "
            "neutral_bytes=excluded.neutral_bytes, "
            "dependent_bytes=excluded.dependent_bytes, "
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
                identity_checksum(version=resolved, identity=identity),
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
                identity_checksum(version=resolved, identity=_identity_of(row)),
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
