# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""How the cache store degrades, and the one place it does not yet.

The store is disposable acceleration state: deleting it must change no
answer, so nothing it holds may abort a run.  Each test here induces one
concrete loss -- a lane gone, the store file gone, a generation mark damaged,
a sweep refused -- and pins what the store makes of it: one miss, a restarted
counter, a loud failed save, never a silent wrong answer.

The producer side is pinned beside it, because it is the same promise seen
from the write path: a row that under-claims what its units carry would be
read back as a smaller truth than the one that was computed.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from codeclone.cache.backend import TABLE_NEUTRAL, CacheBackend, CacheBackendUnusable
from codeclone.cache.store import Cache
from codeclone.cache.versioning import LEGACY_CACHE_MONOLITH_FILENAME, CacheStatus
from codeclone.contracts.errors import CacheError
from codeclone.models import CloneArtifactChannel, DigestObject, NearMissElement, Unit
from codeclone.utils.repo_paths import PathOutsideRepoError
from tests._ast_metrics_helpers import module_registry_context
from tests._cache_store_fixtures import (
    META_KEY_GENERATION,
    drop_cache_meta,
    open_store,
    read_cache_meta,
    read_identity_columns,
    write_cache_meta,
)

_SOURCE_DIGEST = DigestObject(
    domain="codeclone.source-content.v1",
    algorithm="sha256",
    value="0" * 64,
)


def _source_path(module: str) -> str:
    return module.replace(".", "/") + ".py"


def _registered(cache: Cache, *modules: str) -> Cache:
    cache.bind_module_registry(
        module_registry_context(
            filepath=_source_path(modules[0]),
            module_name=modules[0],
            inventory_modules=modules[1:],
        )[1]
    )
    return cache


def _put(
    cache: Cache,
    module: str,
    *,
    units: tuple[Unit, ...] = (),
    channels: tuple[CloneArtifactChannel, ...] = (),
) -> None:
    assert cache.root is not None
    cache.put_file_entry(
        str(cache.root / _source_path(module)),
        {"mtime_ns": 1, "size": 10},
        list(units),
        [],
        [],
        source_content_digest=_SOURCE_DIGEST,
        materialized_clone_channels=channels,
    )


def _saved_store(root: Path, *modules: str) -> Path:
    """A store holding one empty entry per module, written the product's way."""

    cache_path = root / "cache.sqlite3"
    writer = _registered(Cache(cache_path, root=root), *modules)
    for module in modules:
        _put(writer, module)
    writer.save()
    return cache_path


def _loaded(root: Path, cache_path: Path) -> Cache:
    cache = Cache(cache_path, root=root)
    cache.load()
    return cache


@pytest.mark.parametrize(
    ("statement", "neighbour_survives"),
    [
        pytest.param(
            f"DELETE FROM {TABLE_NEUTRAL} WHERE file_id = "
            "(SELECT file_id FROM cache_entry WHERE wire_path = 'alpha.py')",
            True,
            id="lane-row-gone",
        ),
        pytest.param(f"DROP TABLE {TABLE_NEUTRAL}", False, id="lane-table-gone"),
    ],
)
def test_a_lane_the_load_never_read_costs_its_entry_not_the_run(
    tmp_path: Path,
    statement: str,
    neighbour_survives: bool,
) -> None:
    """The load reads identity only, so a lost lane surfaces at the lookup.

    There it is one miss, and the register stops naming the entry, so the run
    re-analyses that file and the next save replaces the row -- as the
    ``_materialize`` contract says.  A lost row costs its own entry; a lost
    table costs every lookup, and still not the run.
    """

    root = tmp_path.resolve()
    cache_path = _saved_store(root, "alpha", "beta")
    with open_store(cache_path) as conn:
        conn.execute(statement)

    cache = _loaded(root, cache_path)
    alpha = str(root / "alpha.py")

    assert cache.load_status is CacheStatus.OK
    assert cache.get_file_entry(alpha) is None
    assert alpha not in cache._identity, "the register still names a lost entry"
    beta_served = cache.get_file_entry(str(root / "beta.py")) is not None
    assert beta_served is neighbour_survives


def test_a_store_removed_between_load_and_lookup_is_a_miss_not_a_crash(
    tmp_path: Path,
) -> None:
    """The lane reader opens lazily, after the load, so it can find nothing.

    The code draws a line here that the lane test above does not: a store
    that cannot be opened says nothing against any one row, so the register
    keeps naming the entry, whereas a lane that fails to decode is evidence
    against its row, which is dropped.  The reader's own refusal is what keeps
    the two apart -- without it the failure falls through to the lane handler
    and the entry is forgotten as if its row were damaged.
    """

    root = tmp_path.resolve()
    cache_path = _saved_store(root, "alpha")
    cache = _loaded(root, cache_path)
    alpha = str(root / "alpha.py")
    for leftover in root.glob(f"{cache_path.name}*"):
        leftover.unlink()

    assert cache.get_file_entry(alpha) is None
    assert alpha in cache._identity, "an unopenable store is not a damaged row"
    assert cache.load_status is CacheStatus.OK


@pytest.mark.parametrize(
    "mark",
    [pytest.param(None, id="mark-missing"), pytest.param("soon", id="mark-text")],
)
def test_a_damaged_generation_mark_restarts_the_count_not_the_store(
    tmp_path: Path,
    mark: str | None,
) -> None:
    """The mark only orders saves for eviction; it is outside the checksum.

    So damage to it is not a reason to refuse the store: the load succeeds,
    the count restarts from zero, and the next save is generation one.
    """

    root = tmp_path.resolve()
    cache_path = _saved_store(root, "alpha", "beta")
    if mark is None:
        drop_cache_meta(cache_path, META_KEY_GENERATION)
    else:
        write_cache_meta(cache_path, **{META_KEY_GENERATION: mark})

    cache = _loaded(root, cache_path)
    assert cache.load_status is CacheStatus.OK
    assert cache.prune_file_entries([str(root / "beta.py")]) == 1
    cache.save()

    assert read_cache_meta(cache_path)[META_KEY_GENERATION] == "1"


def _monolith_written(monolith: Path, _monkeypatch: pytest.MonkeyPatch) -> None:
    monolith.write_text("{}", "utf-8")


def _monolith_unstattable(monolith: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original = Path.exists

    def exists(self: Path) -> bool:
        if self == monolith:
            raise PermissionError("denied")
        return original(self)

    monkeypatch.setattr(Path, "exists", exists)


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        pytest.param(lambda _m, _p: None, None, id="absent"),
        pytest.param(
            _monolith_written,
            "Superseded JSON cache detected at {monolith}; delete this obsolete file.",
            id="present",
        ),
        pytest.param(
            _monolith_unstattable,
            "Superseded JSON cache check failed: denied",
            id="unstattable",
        ),
    ],
)
def test_the_superseded_json_cache_is_named_where_the_managed_layout_left_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    condition: Callable[[Path, pytest.MonkeyPatch], None],
    expected: str | None,
) -> None:
    """Named, never deleted: the file is the user's, not this tool's any more.

    A check that cannot even stat the file says so rather than guessing
    either way, and a workspace without one says nothing at all.
    """

    workspace = tmp_path / ".codeclone"
    workspace.mkdir()
    monolith = workspace / LEGACY_CACHE_MONOLITH_FILENAME
    condition(monolith, monkeypatch)

    warning = Cache(workspace / "db" / "cache.sqlite3").load_warning

    assert warning == (None if expected is None else expected.format(monolith=monolith))


def test_a_budget_sweep_the_store_refuses_fails_the_save_loudly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A save whose size bound could not be enforced is not a successful save.

    The fault is injected where SQLite would raise it -- inside the collector's
    own sweep -- so it travels the collector's refusal path to the store.
    """

    root = tmp_path.resolve()
    cache = _loaded(root, _saved_store(root, "alpha", "beta"))
    assert cache.prune_file_entries([str(root / "beta.py")]) == 1

    def sweep_refused(_backend: CacheBackend, _version: str) -> list[int]:
        raise CacheBackendUnusable("disk I/O error")

    monkeypatch.setattr(CacheBackend, "corrupt_ids", sweep_refused)

    with pytest.raises(CacheError, match="Failed to save cache: disk I/O error"):
        cache.save()


def test_pruning_an_entry_the_run_already_holds_removes_its_row(
    tmp_path: Path,
) -> None:
    """``del``, not ``pop``: only a tracked removal reaches the next save."""

    root = tmp_path.resolve()
    cache_path = _saved_store(root, "alpha", "beta")
    cache = _loaded(root, cache_path)
    alpha = str(root / "alpha.py")
    assert cache.get_file_entry(alpha) is not None

    assert cache.prune_file_entries([str(root / "beta.py")]) == 1
    assert alpha not in cache.data["files"]
    cache.save()

    assert set(read_identity_columns(cache_path)) == {"beta.py"}


_CANONICAL: tuple[NearMissElement, ...] = (("Assign", 1, 1),)


@pytest.mark.parametrize(
    ("renamed_fingerprint", "renamed_sequence", "channels", "refusal"),
    [
        pytest.param(
            "digest",
            (),
            ("near_miss",),
            "renamed-structure digests",
            id="digest-unclaimed",
        ),
        pytest.param(
            "",
            _CANONICAL,
            (),
            "renamed-canonical sequences",
            id="canonical-unclaimed",
        ),
        pytest.param("digest", (), ("renamed_structure",), None, id="digest-claimed"),
        pytest.param("", _CANONICAL, ("near_miss",), None, id="canonical-near-miss"),
    ],
)
def test_a_witness_must_claim_every_renamed_artifact_its_units_carry(
    tmp_path: Path,
    renamed_fingerprint: str,
    renamed_sequence: tuple[NearMissElement, ...],
    channels: tuple[CloneArtifactChannel, ...],
    refusal: str | None,
) -> None:
    """Both directions: an under-claim is refused, a sufficient claim is not.

    The renamed-canonical sequence feeds both tiers, so either claim covers it;
    a guard that demanded one specific claim would refuse an honest row.
    """

    root = tmp_path.resolve()
    cache = _registered(Cache(root / "cache.sqlite3", root=root), "alpha")
    unit = Unit(
        qualname="alpha:widen",
        filepath=str(root / "alpha.py"),
        start_line=1,
        end_line=2,
        loc=2,
        stmt_count=1,
        fingerprint="fingerprint",
        loc_bucket="0-19",
        renamed_fingerprint=renamed_fingerprint,
        renamed_statement_sequence=renamed_sequence,
    )

    if refusal is not None:
        with pytest.raises(ValueError, match=refusal):
            _put(cache, "alpha", units=(unit,), channels=channels)
        return
    _put(cache, "alpha", units=(unit,), channels=channels)
    assert str(root / "alpha.py") in cache.data["files"]


def test_a_files_map_that_cannot_say_what_moved_is_saved_in_full(
    tmp_path: Path,
) -> None:
    """The declared fallback: the old cost, never a wrong answer.

    ``CacheData`` types the map as a plain ``dict``, and a caller holding one
    has no record of what moved.  The save then rewrites everything it holds
    -- here the materialised ``beta`` as well as the re-put ``alpha`` -- where
    a tracking map would have rewritten ``alpha`` alone.
    """

    root = tmp_path.resolve()
    cache_path = _saved_store(root, "alpha", "beta")
    cache = _registered(_loaded(root, cache_path), "alpha", "beta")
    assert cache.get_file_entry(str(root / "beta.py")) is not None

    cache.data["files"] = dict(cache.data["files"])
    _put(cache, "alpha")
    cache.save()

    rows = read_identity_columns(cache_path)
    assert {path: row["generation"] for path, row in rows.items()} == {
        "alpha.py": 2,
        "beta.py": 2,
    }


@pytest.mark.xfail(
    strict=True,
    raises=PathOutsideRepoError,
    reason=(
        "DEFECT (coverage-push-gate wave, 2026-09-24): Cache.load lets "
        "PathOutsideRepoError escape when a cached file's directory has since "
        "become a symlink out of the root; a disposable cache aborts the run"
    ),
)
def test_a_cached_directory_that_now_links_outside_the_root_does_not_abort_the_load(
    tmp_path: Path,
) -> None:
    """A real layout change, not a forged row: every checksum still verifies.

    ``pkg/`` was a directory when the store was written and is a symlink to a
    tree outside the repository now.  The row's wire path resolves outside the
    root, and the load's containment check raises a ``ValueError`` that none
    of its handlers catch -- so the store that "must never change an answer"
    ends the run instead of costing one entry.
    """

    root = tmp_path.resolve() / "project"
    (root / "pkg").mkdir(parents=True)
    cache_path = _saved_store(root, "pkg.mod")
    shared = tmp_path.resolve() / "shared"
    shutil.move(str(root / "pkg"), str(shared))
    (root / "pkg").symlink_to(shared, target_is_directory=True)

    cache = _loaded(root, cache_path)

    assert cache.load_status is not CacheStatus.MISSING
