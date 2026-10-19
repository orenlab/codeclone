# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""What the cache backend does with bytes it cannot trust.

The backend's promise is narrow and each clause has its own pin here:

* a store it cannot reach is *unreadable*, a named refusal, never a raw
  ``OSError`` and never a file created as a side effect of looking;
* a lane, a singleton or an identity row whose stored bytes are not the ones
  written is *refused* with its reason (``CacheRecordRefused``) -- or, for an
  identity row, named by the scan that skips it -- while its healthy
  neighbour in the same store still reads back, so the refusal is about the
  damaged row and not the handle; verification comes before decoding, so a
  byte that breaks the JSON is corruption, and only bytes a writer really
  stored can be called undecodable;
* a SQLite failure reaches the caller as the cache's own
  ``CacheBackendUnusable``, which is the only error the store knows how to
  degrade on;
* a wire entry the schema could only store lossily is refused before it is
  written.

Every damaged state is produced on disk through a raw connection rather than
through ``CacheBackend`` itself, so a backend bug that wrote a well-formed but
wrong row could not hide behind the helper that reads it back.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

from codeclone.cache.backend import (
    DIGEST_ALGORITHM,
    DIGEST_DOMAINS,
    TABLE_NEUTRAL,
    CacheBackend,
    CacheBackendUnreadable,
    CacheBackendUnusable,
    CacheRecordRefused,
    IdentityRow,
    WireShapeRefused,
    scan_identities,
    singleton_checksum,
    split_wire_entry,
)
from codeclone.cache.versioning import CacheRefusal
from codeclone.models import EntryIdentity
from tests._cache_store_fixtures import (
    open_store,
    set_identity_column,
    write_lane_bytes,
)

#: Any generation mark will do: nothing here crosses a generation boundary.
_VERSION = "backend-refusal-fixture"
_DAMAGED = "damaged.py"
_HEALTHY = "healthy.py"


def _identity(wire_path: str) -> EntryIdentity:
    return EntryIdentity(
        wire_path=wire_path,
        binding_version="1",
        stat_mtime_ns=1_700_000_000_000_000_000,
        stat_size=64,
        source_digest=bytes(range(32)),
        git_blob_format=None,
        git_blob_id=None,
        neutral_profile=bytes(range(1, 33)),
        dependent_profile=bytes(range(2, 34)),
        binding_context=bytes(range(3, 35)),
        clone_channels=(),
        neutral_bytes=7,
        dependent_bytes=7,
    )


def _two_entry_store(cache_path: Path) -> dict[str, IdentityRow]:
    """One entry to damage and one to prove the handle still reads."""

    with CacheBackend(cache_path) as backend:
        backend.upsert_entries(
            [
                (_identity(path), b'{"k":1}', b'{"k":2}')
                for path in (_DAMAGED, _HEALTHY)
            ],
            version=_VERSION,
            generation=1,
            now_epoch=1_700_000_000,
        )
        backend.write_singleton(_DAMAGED, {"k": 1}, version=_VERSION)
        backend.write_singleton(_HEALTHY, {"k": 2}, version=_VERSION)
        return {
            row.identity.wire_path: row
            for row in scan_identities(backend, _VERSION).verified
        }


def _damage(cache_path: Path, statement: str, *params: object) -> None:
    with open_store(cache_path) as conn:
        conn.execute(statement, params)


@pytest.mark.parametrize(
    ("relative", "read_only"),
    [
        pytest.param("never-written.sqlite3", True, id="missing-store-read"),
        pytest.param("a-regular-file/cache.sqlite3", False, id="parent-is-a-file"),
    ],
)
def test_a_store_the_filesystem_refuses_is_unreadable(
    tmp_path: Path,
    relative: str,
    read_only: bool,
) -> None:
    """``OSError`` becomes the unreadable refusal, and looking creates nothing.

    Unreadable, not merely unusable: the store words the two differently for
    the user (fix your filesystem versus your cache is damaged), so a
    collapse into the parent class would misdirect whoever reads the warning.
    """

    (tmp_path / "a-regular-file").write_text("not a directory", "utf-8")
    cache_path = tmp_path / relative

    with pytest.raises(CacheBackendUnreadable):
        CacheBackend(cache_path, read_only=read_only)

    assert not (tmp_path / "never-written.sqlite3").exists()


def _read_neutral(backend: CacheBackend, row: IdentityRow) -> object:
    return backend.read_lane(TABLE_NEUTRAL, row.file_id, row.digests.neutral)


@pytest.mark.parametrize(
    "statement",
    [
        pytest.param(f"DELETE FROM {TABLE_NEUTRAL} WHERE file_id = ?", id="row-gone"),
        pytest.param(
            f"UPDATE {TABLE_NEUTRAL} SET payload = 'text' WHERE file_id = ?",
            id="payload-is-text",
        ),
        pytest.param(
            f"UPDATE {TABLE_NEUTRAL} SET payload = X'FF00' WHERE file_id = ?",
            id="payload-is-not-json",
        ),
        pytest.param(
            f"UPDATE {TABLE_NEUTRAL} SET payload = CAST('{{\"k\":9}}' AS BLOB) "
            "WHERE file_id = ?",
            id="payload-value-changed",
        ),
    ],
)
def test_a_lane_that_is_not_the_written_bytes_is_refused_as_corrupt(
    tmp_path: Path,
    statement: str,
) -> None:
    """Missing, retyped, broken or merely rewritten: all are corruption.

    The last case decodes perfectly -- ``{"k":9}`` is a sound lane -- and was
    served as truth while the checksum covered lengths only.
    """

    cache_path = tmp_path / "cache.sqlite3"
    rows = _two_entry_store(cache_path)
    _damage(cache_path, statement, rows[_DAMAGED].file_id)

    with CacheBackend(cache_path, read_only=True) as backend:
        with pytest.raises(CacheRecordRefused) as refused:
            _read_neutral(backend, rows[_DAMAGED])
        assert refused.value.reason is CacheRefusal.CORRUPT
        assert _read_neutral(backend, rows[_HEALTHY]) == {"k": 1}


def test_verified_lane_bytes_that_are_not_json_are_undecodable(
    tmp_path: Path,
) -> None:
    """Bytes a writer really stored, digest and all, that are no record."""

    cache_path = tmp_path / "cache.sqlite3"
    _two_entry_store(cache_path)
    write_lane_bytes(
        cache_path,
        _DAMAGED,
        TABLE_NEUTRAL,
        b"\xff\x00",
        as_writer=True,
        version=_VERSION,
    )
    with CacheBackend(cache_path, read_only=True) as backend:
        rows = {
            row.identity.wire_path: row
            for row in scan_identities(backend, _VERSION).verified
        }
        with pytest.raises(CacheRecordRefused) as refused:
            _read_neutral(backend, rows[_DAMAGED])
        assert refused.value.reason is CacheRefusal.UNDECODABLE
        assert _read_neutral(backend, rows[_HEALTHY]) == {"k": 1}


@pytest.mark.parametrize(
    ("column", "value"),
    [
        pytest.param("payload", "text", id="payload-is-text"),
        pytest.param("payload", b"\xff", id="payload-is-not-json"),
        pytest.param("payload", b'{"k":9}', id="payload-rewritten"),
        pytest.param("payload", b'{ "k":1}', id="payload-re-encoded"),
        pytest.param("checksum", b"\x00", id="checksum-is-a-blob"),
    ],
)
def test_a_singleton_that_fails_its_checks_is_refused_as_corrupt(
    tmp_path: Path,
    column: str,
    value: object,
) -> None:
    """A rewritten payload is refused by its checksum, not trusted as new data.

    The checksum covers the stored bytes, so even a re-encoding of the same
    value is bytes the writer did not store.
    """

    cache_path = tmp_path / "cache.sqlite3"
    _two_entry_store(cache_path)
    _damage(
        cache_path,
        f"UPDATE cache_singletons SET {column} = ? WHERE key = ?",
        value,
        _DAMAGED,
    )

    with CacheBackend(cache_path, read_only=True) as backend:
        with pytest.raises(CacheRecordRefused) as refused:
            backend.read_singleton(_DAMAGED, _VERSION)
        assert refused.value.reason is CacheRefusal.CORRUPT
        assert backend.read_singleton(_HEALTHY, _VERSION) == {"k": 2}
        assert backend.read_singleton("never-written", _VERSION) is None


def test_a_verified_singleton_that_is_not_json_is_undecodable(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.sqlite3"
    _two_entry_store(cache_path)
    _damage(
        cache_path,
        "UPDATE cache_singletons SET payload = ?, checksum = ? WHERE key = ?",
        b"\xff",
        singleton_checksum(version=_VERSION, key=_DAMAGED, payload=b"\xff"),
        _DAMAGED,
    )

    with CacheBackend(cache_path, read_only=True) as backend:
        with pytest.raises(CacheRecordRefused) as refused:
            backend.read_singleton(_DAMAGED, _VERSION)
        assert refused.value.reason is CacheRefusal.UNDECODABLE


def _stat_is_text(cache_path: Path) -> None:
    _damage(
        cache_path,
        "UPDATE cache_entry SET stat_mtime_ns = 'soon' WHERE wire_path = ?",
        _DAMAGED,
    )


def _digest_is_an_integer_with_a_fresh_checksum(cache_path: Path) -> None:
    # The checksum is re-minted over the damaged value on purpose: without it
    # the checksum alone would refuse the row, and the column's own type guard
    # would never be the reason the row is skipped.
    set_identity_column(cache_path, _DAMAGED, "source_digest", 5, version=_VERSION)


def _checksum_is_a_blob(cache_path: Path) -> None:
    _damage(
        cache_path,
        "UPDATE cache_entry SET checksum = X'00' WHERE wire_path = ?",
        _DAMAGED,
    )


@pytest.mark.parametrize(
    "damage",
    [
        pytest.param(_stat_is_text, id="stat-is-text"),
        pytest.param(_digest_is_an_integer_with_a_fresh_checksum, id="digest-type"),
        pytest.param(_checksum_is_a_blob, id="checksum-is-a-blob"),
    ],
)
def test_an_identity_row_that_cannot_be_rebuilt_is_skipped_and_named_corrupt(
    tmp_path: Path,
    damage: Callable[[Path], None],
) -> None:
    """Skipped by the load and named by the collector -- the same row, both ways.

    A row the load skips but the collector keeps would be re-read and
    re-skipped forever; one the collector names but the load serves would be
    deleted from under a run that trusted it.
    """

    cache_path = tmp_path / "cache.sqlite3"
    rows = _two_entry_store(cache_path)
    damage(cache_path)

    with CacheBackend(cache_path, read_only=True) as backend:
        scan = scan_identities(backend, _VERSION)
        served = [row.identity.wire_path for row in scan.verified]
        assert (served, scan.refused) == ([_HEALTHY], [_DAMAGED])
        assert backend.corrupt_ids(_VERSION) == [rows[_DAMAGED].file_id]


def test_an_identity_row_without_a_text_path_is_skipped_unnamed_and_collected(
    tmp_path: Path,
) -> None:
    """A row whose own path is damaged cannot name a file, so it names none.

    It is still refused and still collected: nothing reads it, and the sweep
    takes it, so it cannot sit in the store as a row that looks healthy.
    """

    cache_path = tmp_path / "cache.sqlite3"
    rows = _two_entry_store(cache_path)
    _damage(
        cache_path,
        "UPDATE cache_entry SET wire_path = X'00' WHERE file_id = ?",
        rows[_DAMAGED].file_id,
    )

    with CacheBackend(cache_path, read_only=True) as backend:
        scan = scan_identities(backend, _VERSION)
        assert [row.identity.wire_path for row in scan.verified] == [_HEALTHY]
        assert scan.refused == []
        assert backend.corrupt_ids(_VERSION) == [rows[_DAMAGED].file_id]


@pytest.mark.parametrize(
    ("operation", "reason"),
    [
        pytest.param(
            lambda backend: backend.write_singleton("k", {}, version=_VERSION),
            "readonly",
            id="write",
        ),
        pytest.param(lambda backend: backend.reclaim(), "readonly", id="reclaim"),
        pytest.param(
            lambda backend: scan_identities(backend, _VERSION),
            "no such table",
            id="read-without-entry-table",
        ),
    ],
)
def test_a_sqlite_failure_reaches_the_caller_as_the_caches_own_error(
    tmp_path: Path,
    operation: Callable[[CacheBackend], object],
    reason: str,
) -> None:
    """The store degrades on ``CacheBackendUnusable`` and on nothing else.

    A raw ``sqlite3`` error escaping here would pass every ``except`` the store
    has and abort the run over state that is disposable by contract.  The
    handle is read-only and the entry table is gone, and each operation meets
    one of the two for real: a write or a vacuum meets the read-only handle, a
    read meets the missing table.
    """

    cache_path = tmp_path / "cache.sqlite3"
    _two_entry_store(cache_path)
    with open_store(cache_path) as conn:
        conn.executescript(
            f"DROP TABLE {TABLE_NEUTRAL}; DROP TABLE cache_dependent; "
            "DROP TABLE cache_entry;"
        )

    with (
        CacheBackend(cache_path, read_only=True) as backend,
        pytest.raises(CacheBackendUnusable, match=reason),
    ):
        operation(backend)


class _DiskFullOnCommit:
    """A connection whose commit fails the way a full disk fails it.

    Everything but ``commit`` is the real connection, so the rows reach SQLite
    and only the durability step is refused -- the one failure a write cannot
    detect before it has already done its work.
    """

    def __init__(self, inner: sqlite3.Connection) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)

    def commit(self) -> None:
        raise sqlite3.OperationalError("database or disk is full")


def test_a_commit_the_disk_refuses_is_the_caches_own_error_and_stores_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_path = tmp_path / "cache.sqlite3"
    backend = CacheBackend(cache_path)
    monkeypatch.setattr(backend, "_connection", _DiskFullOnCommit(backend._connection))
    try:
        with pytest.raises(CacheBackendUnusable, match="disk is full"):
            backend.upsert_entries(
                [(_identity(_DAMAGED), b"{}", b"{}")],
                version=_VERSION,
                generation=1,
                now_epoch=1_700_000_000,
            )
    finally:
        backend.close()

    with CacheBackend(cache_path, read_only=True) as reader:
        assert reader.entry_count() == 0


def _wire(**overrides: object) -> dict[str, object]:
    """A wire entry the schema stores without loss, before ``overrides``."""

    def digest(key: str, fill: str) -> list[str]:
        return [DIGEST_DOMAINS[key], DIGEST_ALGORITHM, fill * 32]

    wire: dict[str, object] = {
        "cb": "1",
        "sd": digest("sd", "00"),
        "gb": ["sha1", "ab" * 20],
        "st": [1, 2],
        "bc": digest("bc", "11"),
        "np": digest("np", "22"),
        "dp": digest("dp", "33"),
        "n": {"mt": []},
        "d": {},
    }
    wire.update(overrides)
    return wire


@pytest.mark.parametrize(
    ("key", "value", "refusal"),
    [
        pytest.param("st", "12", "st must be a list", id="stat-not-a-list"),
        pytest.param("st", [1, 2, 3], "st must carry mtime_ns", id="stat-too-long"),
        pytest.param("st", ["1", 2], "st.mtime_ns must be an integer", id="stat-text"),
        pytest.param(
            "gb", ["sha1", "ab", "x"], "gb must carry an object", id="blob-too-long"
        ),
        pytest.param("gb", ["sha1", "zz"], "gb is not hexadecimal", id="blob-not-hex"),
        pytest.param(
            "sd",
            [DIGEST_DOMAINS["sd"], DIGEST_ALGORITHM],
            "sd must carry a domain",
            id="digest-too-short",
        ),
        pytest.param(
            "sd",
            ["codeclone.elsewhere.v1", DIGEST_ALGORITHM, "00" * 32],
            "sd carries domain",
            id="digest-foreign-domain",
        ),
        pytest.param(
            "np",
            [DIGEST_DOMAINS["np"], "sha512", "22" * 32],
            "np carries domain",
            id="digest-foreign-algorithm",
        ),
    ],
)
def test_a_wire_entry_the_schema_would_store_lossily_is_refused(
    key: str,
    value: object,
    refusal: str,
) -> None:
    """Refused before the write, each by the guard that names its own defect.

    The unmodified entry splits first, so every refusal below is caused by its
    one override and not by a fixture the schema never accepted.
    """

    split_wire_entry("module.py", _wire())

    with pytest.raises(WireShapeRefused, match=refusal):
        split_wire_entry("module.py", _wire(**{key: value}))
