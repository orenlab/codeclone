# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""One ``Cache`` instance across more than one save, release and lookup.

The product makes at most one save per instance, so these sequences are not
reachable from the CLI or MCP today; each pins what the store must still get
right when they happen: the identity register agrees with the rows on disk,
a refused generation is cleared once, and a release never publishes half of
what it dropped.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from codeclone.cache.store import Cache
from tests._cache_store_fixtures import write_cache_meta
from tests.test_cache import _SOURCE_CONTENT_DIGEST, _bind_module_paths

_NAMES = ("a.py", "b.py", "c.py", "d.py")


def _rows(cache_path: Path) -> list[str]:
    with sqlite3.connect(f"file:{cache_path}?mode=ro", uri=True) as connection:
        return [
            str(row[0])
            for row in connection.execute(
                "SELECT wire_path FROM cache_entry ORDER BY 1"
            )
        ]


def _payload_bytes(cache_path: Path) -> dict[str, int]:
    with sqlite3.connect(f"file:{cache_path}?mode=ro", uri=True) as connection:
        return {
            str(path): int(size)
            for path, size in connection.execute(
                "SELECT wire_path, neutral_bytes + dependent_bytes FROM cache_entry"
            )
        }


def _generation(cache_path: Path) -> str:
    with sqlite3.connect(f"file:{cache_path}?mode=ro", uri=True) as connection:
        row = connection.execute(
            "SELECT value FROM cache_backend_meta WHERE key='generation'"
        ).fetchone()
    return str(row[0])


def _cache(root: Path, *, max_size_bytes: int = 0) -> Cache:
    cache = Cache(root / "cache.sqlite3", root=root, max_size_bytes=max_size_bytes)
    _bind_module_paths(cache, *_NAMES)
    return cache


def _put(cache: Cache, name: str, *, mtime: int = 1, size: int = 10) -> None:
    cache.put_file_entry(
        name,
        {"mtime_ns": mtime, "size": size},
        [],
        [],
        [],
        source_content_digest=_SOURCE_CONTENT_DIGEST,
    )


def _seed(root: Path, *names: str) -> Path:
    cache = _cache(root)
    for index, name in enumerate(names):
        _put(cache, name, mtime=index + 1, size=10 + index)
    cache.save()
    return root / "cache.sqlite3"


def _seed_over_budget(root: Path) -> tuple[Path, int]:
    """Three rows and a budget for three and a half: one more evicts one."""
    cache_path = _seed(root, "a.py", "b.py", "c.py")
    one = max(_payload_bytes(cache_path).values())
    return cache_path, 3 * one + one // 2


def test_a_release_that_drops_unsaved_entries_publishes_no_generation(
    tmp_path: Path,
) -> None:
    cache_path = _seed(tmp_path, "a.py", "b.py")
    before = _generation(cache_path)
    cache = _cache(tmp_path)
    cache.load()
    _put(cache, "c.py", mtime=7, size=70)

    cache.release_loaded_entries(allow_dirty=True)
    cache.save()

    assert _generation(cache_path) == before
    assert _rows(cache_path) == ["a.py", "b.py"]


def test_a_release_keeps_the_deletions_it_did_not_save(tmp_path: Path) -> None:
    cache_path = _seed(tmp_path, "a.py", "b.py")
    cache = _cache(tmp_path)
    cache.load()
    assert cache.prune_file_entries([]) == 2

    cache.release_loaded_entries(allow_dirty=True)
    cache.save()

    assert _rows(cache_path) == []


def test_a_refused_generation_is_cleared_once_not_on_every_save(
    tmp_path: Path,
) -> None:
    cache_path = _seed(tmp_path, "a.py")
    write_cache_meta(cache_path, envelope_checksum="0" * 64)
    cache = _cache(tmp_path)
    cache.load()
    _put(cache, "a.py")
    _put(cache, "b.py", mtime=2, size=20)
    cache.save()
    cache.release_loaded_entries()
    _put(cache, "c.py", mtime=3, size=30)

    cache.save()

    assert _rows(cache_path) == ["a.py", "b.py", "c.py"]


def test_rows_the_budget_kept_stay_known_after_the_save(tmp_path: Path) -> None:
    cache_path, budget = _seed_over_budget(tmp_path)
    cache = _cache(tmp_path, max_size_bytes=budget)
    cache.load()
    _put(cache, "d.py", mtime=9, size=90)
    cache.save()
    assert {"b.py", "c.py"} <= set(_rows(cache_path))
    cache.release_loaded_entries()

    assert cache.get_file_entry("b.py") is not None
    assert cache.prune_file_entries(["d.py"]) == 2


def test_a_row_the_budget_evicted_is_a_miss_not_a_corruption(
    tmp_path: Path,
) -> None:
    cache_path, budget = _seed_over_budget(tmp_path)
    cache = _cache(tmp_path, max_size_bytes=budget)
    cache.load()
    assert cache.get_file_entry("a.py") is not None
    _put(cache, "d.py", mtime=9, size=90)
    cache.save()
    assert "a.py" not in _rows(cache_path)
    cache.release_loaded_entries()

    assert cache.get_file_entry("a.py") is None
    assert cache.refusal_counts()["corrupt"] == 0


def test_a_row_this_instance_wrote_is_known_after_the_save(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.sqlite3"
    cache = _cache(tmp_path)
    _put(cache, "a.py")
    cache.save()
    cache.release_loaded_entries()

    assert cache.get_file_entry("a.py") is not None
    assert cache.prune_file_entries([]) == 1
    cache.save()
    assert _rows(cache_path) == []


def test_a_row_this_instance_rewrote_is_read_back_not_refused(
    tmp_path: Path,
) -> None:
    _seed(tmp_path, "a.py")
    cache = _cache(tmp_path)
    cache.load()
    assert cache.get_file_entry("a.py") is not None
    cache.put_file_entry(
        "a.py",
        {"mtime_ns": 2, "size": 20},
        [],
        [],
        [],
        source_content_digest=_SOURCE_CONTENT_DIGEST,
        source_stats={"lines": 5, "functions": 0, "methods": 0, "classes": 0},
    )
    cache.save()
    cache.release_loaded_entries()

    entry = cache.get_file_entry("a.py")

    assert cache.refusal_counts()["corrupt"] == 0
    assert entry is not None
    assert entry.stat == {"mtime_ns": 2, "size": 20}


def test_a_release_that_dropped_only_stored_content_keeps_writes_open(
    tmp_path: Path,
) -> None:
    """Re-putting what the store already holds leaves nothing unsaved to lose."""

    cache_path = _seed(tmp_path, "a.py")
    cache = _cache(tmp_path)
    cache.load()
    assert cache.get_file_entry("a.py") is not None
    _put(cache, "a.py", mtime=1, size=10)
    assert cache._dirty is False

    cache.release_loaded_entries(allow_dirty=True)
    _put(cache, "b.py", mtime=2, size=20)
    cache.save()

    assert _rows(cache_path) == ["a.py", "b.py"]
