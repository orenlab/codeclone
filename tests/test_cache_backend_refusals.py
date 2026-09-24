# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""What the cache backend does with bytes it cannot trust.

The backend's promise is narrow and each clause has its own pin here:

* a store it cannot reach is *unreadable*, a named refusal, never a raw
  ``OSError`` and never a file created as a side effect of looking;
* a lane, a singleton or an identity row that cannot be rebuilt faithfully is
  *absent* -- one miss -- while its healthy neighbour in the same store still
  reads back, so the refusal is about the damaged row and not the handle;
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
    WireShapeRefused,
    split_wire_entry,
)
from codeclone.models import EntryIdentity
from tests._cache_store_fixtures import open_store, set_identity_column

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


def _two_entry_store(cache_path: Path) -> dict[str, int]:
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
            identity.wire_path: file_id
            for file_id, identity in backend.iter_identities(_VERSION)
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
    ],
)
def test_a_lane_that_cannot_be_read_back_is_absent(
    tmp_path: Path,
    statement: str,
) -> None:
    cache_path = tmp_path / "cache.sqlite3"
    ids = _two_entry_store(cache_path)
    _damage(cache_path, statement, ids[_DAMAGED])

    with CacheBackend(cache_path, read_only=True) as backend:
        assert backend.read_lane(TABLE_NEUTRAL, ids[_DAMAGED]) is None
        assert backend.read_lane(TABLE_NEUTRAL, ids[_HEALTHY]) == {"k": 1}


@pytest.mark.parametrize(
    ("column", "value"),
    [
        pytest.param("payload", "text", id="payload-is-text"),
        pytest.param("payload", b"\xff", id="payload-is-not-json"),
        pytest.param("payload", b'{"k":9}', id="payload-rewritten"),
        pytest.param("checksum", b"\x00", id="checksum-is-a-blob"),
    ],
)
def test_a_singleton_that_fails_its_checks_is_absent(
    tmp_path: Path,
    column: str,
    value: object,
) -> None:
    """A rewritten payload is refused by its checksum, not trusted as new data."""

    cache_path = tmp_path / "cache.sqlite3"
    _two_entry_store(cache_path)
    _damage(
        cache_path,
        f"UPDATE cache_singletons SET {column} = ? WHERE key = ?",
        value,
        _DAMAGED,
    )

    with CacheBackend(cache_path, read_only=True) as backend:
        assert backend.read_singleton(_DAMAGED, _VERSION) is None
        assert backend.read_singleton(_HEALTHY, _VERSION) == {"k": 2}


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
    ids = _two_entry_store(cache_path)
    damage(cache_path)

    with CacheBackend(cache_path, read_only=True) as backend:
        served = [
            identity.wire_path for _id, identity in backend.iter_identities(_VERSION)
        ]
        assert served == [_HEALTHY]
        assert backend.corrupt_ids(_VERSION) == [ids[_DAMAGED]]


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
            lambda backend: backend.iter_identities(_VERSION),
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
