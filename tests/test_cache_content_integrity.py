# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A cached fact is served only from the bytes that were written.

Measured 2026-10-13 on fastapi @0cb4a8e2 and on this repository: the entry
checksum covered the identity and the lengths of the two lanes, never their
content. One byte changed inside a lane, length kept, was handed to the
analysis as truth -- the pydantic hook's target renamed, a dead symbol
renamed, a block hash moved -- and the warm run published other findings,
other verdicts and another run id than the cold run of the same tree, with
nothing re-walked and nothing reported.

The law pinned here is the maintainer's (ruling 2026-10-19, with the
observability ruling of 2026-10-13): the cache verifies every semantic byte
it later decodes; a record whose bytes do not match is a typed refusal --
counted by reason, warned, its file walked again -- and never a fact; a
record written by the previous generation is invalidated with a full
recompute and is never declared verified by re-signing it; an ordinary miss
stays silent.

Every damaged state is produced on disk through a raw connection, so a
backend that wrote a well-formed but wrong row could not hide behind the
helper that reads it back. Each refusal is measured against the cold run of
the same tree, and the positive control shows the same probe reading a sound
store whole, so a refusal below cannot be the refusal of every warm row.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest

import codeclone.cache.backend as cache_backend
import codeclone.cache.versioning as cache_versioning
import codeclone.core.discovery as core_discovery
from codeclone.cache.backend import TABLE_DEPENDENT, TABLE_NEUTRAL
from codeclone.cache.gc import CacheStoreGcJob
from codeclone.cache.projection import encode_segment_report_projection
from codeclone.cache.store import Cache
from codeclone.cache.versioning import CacheStatus
from codeclone.core._types import BootstrapResult, DiscoveryResult, ProcessingResult
from codeclone.core.parallelism import process
from codeclone.observability.vocabulary import COUNTER_KEYS
from tests._cache_store_fixtures import (
    META_KEY_SCHEMA,
    break_identity_checksum,
    open_store,
    read_cache_meta,
    read_lane_bytes,
    set_lane_digest_column,
    swap_lane_bytes,
    transcribe_to_schema_two,
    write_lane_bytes,
)
from tests._pipeline_fixtures import analysis_boot, discover_and_process

_MODULE = '''"""Rows in both lanes: units, a pydantic hook, a dead candidate."""

import subprocess

from pydantic.json_schema import GenerateJsonSchema


class BytesAsText(GenerateJsonSchema):
    def bytes_schema(self, schema):
        return {"type": "string"}


def run(command):
    def render(value):
        return str(value)

    return subprocess.run(render(command), check=False)
'''

_MOD = "pkg/mod.py"
_INIT = "pkg/__init__.py"

#: The closed refusal vocabulary, spelled out: a reason this list lacks, or a
#: counter it names that nothing publishes, fails here and not in a run.
_REASONS = ("corrupt", "incompatible", "undecodable", "unreadable")


def _counter(reason: str) -> str:
    return f"cache_refused_{reason}"


class _SpanCounters:
    """What one discovery span published: its name and its counters."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.counters: dict[str, int] = {}

    def set_counter(self, key: str, value: int) -> None:
        self.counters[key] = value


@dataclass(frozen=True, slots=True)
class _Warm:
    """One warm discovery and the processing that completes it."""

    load_status: CacheStatus
    discovery: DiscoveryResult
    processing: ProcessingResult
    counters: dict[str, int]
    cache: Cache

    def refusals(self) -> dict[str, int]:
        missing = [
            _counter(reason)
            for reason in _REASONS
            if _counter(reason) not in self.counters
        ]
        assert not missing, f"refusal counters not published: {missing}"
        return {reason: self.counters[_counter(reason)] for reason in _REASONS}

    def walked(self, root: Path) -> list[str]:
        return sorted(
            Path(path).relative_to(root).as_posix()
            for path in self.discovery.files_to_process
        )

    def cache_warnings(self) -> list[str]:
        return [
            warning
            for warning in self.discovery.skipped_warnings
            if warning.startswith("Cache refused")
        ]


def _boot(root: Path) -> BootstrapResult:
    return analysis_boot(root, min_loc=1, min_stmt=1, skip_metrics=False)


def _cold(tmp_path: Path) -> tuple[Path, Path, ProcessingResult]:
    root = tmp_path / "tree"
    (root / "pkg").mkdir(parents=True)
    (root / _INIT).write_text("", "utf-8")
    (root / _MOD).write_text(_MODULE, "utf-8")
    cache_path = tmp_path / "cache.sqlite3"
    cache, _discovery, processing = discover_and_process(
        _boot(root), cache_path, root=root, warm=False
    )
    cache.save()
    return root, cache_path, processing


def _warm(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
    cache_path: Path,
    *,
    after_load: Callable[[], None] | None = None,
) -> _Warm:
    observed: list[_SpanCounters] = []

    @contextmanager
    def _recording(*, name: str) -> Iterator[_SpanCounters]:
        observed.append(_SpanCounters(name))
        yield observed[-1]

    cache = Cache(cache_path, root=root)
    cache.load()
    if after_load is not None:
        after_load()
    with monkeypatch.context() as patch:
        patch.setattr(core_discovery, "span", _recording)
        discovery = core_discovery.discover(boot=_boot(root), cache=cache)
    reuse = [span for span in observed if span.name == "cache.profile_reuse"]
    assert len(reuse) == 1
    return _Warm(
        load_status=cache.load_status,
        discovery=discovery,
        processing=process(boot=_boot(root), discovery=discovery, cache=cache),
        counters=reuse[0].counters,
        cache=cache,
    )


def _facts(processing: ProcessingResult) -> dict[str, list[str]]:
    """Every family a run ends up holding, cached and walked alike."""

    families = (
        "units",
        "class_metrics",
        "module_deps",
        "dead_candidates",
        "runtime_reachability",
        "security_surfaces",
        "semantic_events",
        "function_contract_summaries",
        "nested_definitions",
        "function_relationship_facts",
        "source_stats_by_file",
        "source_digest_by_file",
    )
    held = {
        family: sorted(map(repr, getattr(processing, family))) for family in families
    }
    held["referenced_names"] = sorted(processing.referenced_names)
    held["referenced_qualnames"] = sorted(processing.referenced_qualnames)
    return held


def _no_refusal() -> dict[str, int]:
    return dict.fromkeys(_REASONS, 0)


def _only(reason: str, count: int = 1) -> dict[str, int]:
    return _no_refusal() | {reason: count}


# -- the positive control ------------------------------------------------------


def test_a_sound_store_is_read_whole_and_publishes_every_refusal_as_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same probe over an untouched store: nothing walked, nothing refused.

    Zeros are published, not omitted: an absent key means the span did not
    run, a zero means it ran and refused nothing.
    """

    root, cache_path, cold = _cold(tmp_path)
    warm = _warm(monkeypatch, root, cache_path)

    assert warm.load_status is CacheStatus.OK
    assert warm.walked(root) == []
    assert warm.refusals() == _no_refusal()
    assert warm.cache_warnings() == []
    assert _facts(warm.processing) == _facts(cold)
    assert any(
        fact.framework == "pydantic"
        for fact in warm.discovery.cached_runtime_reachability
    ), "the hook's fact must come back off the cache for the controls to mean anything"


# -- content changed under an unchanged identity -------------------------------

#: (lane, anchor, needle, replacement): one byte of one lane, length kept.
#: The target, the candidate name and the unit size are VALID for every
#: decoder -- a wrong value in a right shape -- and were served as truth; the
#: rest the decoders refused, but without a type, a count or a word.
_CONTENT_DAMAGE = {
    "dependent.pydantic-target": (
        TABLE_DEPENDENT,
        b'"rr":[',
        b"BytesAsText.bytes_schema",
        b"BytesAsText.bytes_schemX",
    ),
    "dependent.dead-candidate-name": (
        TABLE_DEPENDENT,
        b'"dc":[[',
        b'"pkg.mod:run"',
        b'"pkg.mod:ruX"',
    ),
    "neutral.unit-size": (
        TABLE_NEUTRAL,
        b'"u":[[',
        b'["run",13,17,5,',
        b'["run",13,17,9,',
    ),
    "neutral.unit-name": (TABLE_NEUTRAL, b'"u":[[', b'"run",', b'"ruX",'),
    "dependent.framework-spelling": (
        TABLE_DEPENDENT,
        b'"rr":[',
        b'"pydantic"',
        b'"pydantiq"',
    ),
    "dependent.not-an-object": (TABLE_DEPENDENT, b"", b"{", b"["),
    "neutral.not-json": (TABLE_NEUTRAL, b"", b"{", b"\xff"),
}


def _warm_after_damage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    damage: str,
    *,
    with_digest_column: bool,
) -> tuple[Path, Path, ProcessingResult, _Warm]:
    """A cold store, one lane damaged on disk, then a warm discovery over it.

    ``with_digest_column`` also rewrites the lane's digest column to the
    digest of the damaged bytes -- and NOT the identity checksum.
    """

    table, anchor, needle, replacement = _CONTENT_DAMAGE[damage]
    root, cache_path, cold = _cold(tmp_path)
    original = read_lane_bytes(cache_path, _MOD, table)
    swap_lane_bytes(
        cache_path,
        _MOD,
        table,
        anchor=anchor,
        needle=needle,
        replacement=replacement,
    )
    changed = read_lane_bytes(cache_path, _MOD, table)
    assert changed != original
    if with_digest_column:
        set_lane_digest_column(
            cache_path, _MOD, table, hashlib.sha256(changed).digest()
        )
    return root, cache_path, cold, _warm(monkeypatch, root, cache_path)


def _assert_refused_once_and_recomputed(
    warm: _Warm, root: Path, cold: ProcessingResult
) -> None:
    assert warm.walked(root) == [_MOD]
    assert _facts(warm.processing) == _facts(cold)
    assert warm.refusals() == _only("corrupt")
    (warning,) = warm.cache_warnings()
    assert "corrupt" in warning
    assert _MOD in warning


@pytest.mark.parametrize("damage", sorted(_CONTENT_DAMAGE))
def test_a_lane_whose_bytes_changed_is_refused_as_corrupt_and_recomputed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str
) -> None:
    root, cache_path, cold, warm = _warm_after_damage(
        monkeypatch, tmp_path, damage, with_digest_column=False
    )

    _assert_refused_once_and_recomputed(warm, root, cold)

    # One refusal, not a permanent cold path: the run that walked the file
    # stores its bytes again, and the next run reads the store whole.
    warm.cache.save()
    healed = _warm(monkeypatch, root, cache_path)
    assert healed.walked(root) == []
    assert healed.refusals() == _no_refusal()
    assert _facts(healed.processing) == _facts(cold)


@pytest.mark.parametrize(
    "damage", ["neutral.unit-size", "dependent.dead-candidate-name"]
)
def test_a_lane_rewritten_with_its_digest_column_is_refused_by_the_identity_checksum(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str
) -> None:
    """The digest column is inside the checksummed identity, lane by lane.

    The lane bytes AND the column that names them are rewritten together, as
    a partial migration or a restore of half a row would leave them; only the
    identity checksum still describes the original. A checksum that left a
    lane's digest out would serve these bytes as that lane's truth.
    """

    root, _cache_path, cold, warm = _warm_after_damage(
        monkeypatch, tmp_path, damage, with_digest_column=True
    )

    _assert_refused_once_and_recomputed(warm, root, cold)


# -- the decision table: every way a cached record can fail to be served --------


def _unlink_store(cache_path: Path) -> Callable[[], None]:
    def _remove() -> None:
        for leftover in cache_path.parent.glob(f"{cache_path.name}*"):
            leftover.unlink()

    return _remove


def _drop_dependent_table(cache_path: Path) -> Callable[[], None]:
    def _drop() -> None:
        with open_store(cache_path) as conn:
            conn.execute(f"DROP TABLE {TABLE_DEPENDENT}")

    return _drop


def _delete_lane_row(cache_path: Path) -> None:
    with open_store(cache_path) as conn:
        conn.execute(
            f"DELETE FROM {TABLE_DEPENDENT} WHERE file_id = "
            "(SELECT file_id FROM cache_entry WHERE wire_path = ?)",
            (_MOD,),
        )


def _lane_as_text(cache_path: Path) -> None:
    payload = read_lane_bytes(cache_path, _MOD, TABLE_NEUTRAL)
    with open_store(cache_path) as conn:
        conn.execute(
            f"UPDATE {TABLE_NEUTRAL} SET payload = ? WHERE file_id = "
            "(SELECT file_id FROM cache_entry WHERE wire_path = ?)",
            (payload.decode("utf-8"), _MOD),
        )


def _add_module(root: Path) -> None:
    (root / "pkg" / "added.py").write_text("VALUE = 1\n", "utf-8")


def _edit_source(root: Path) -> None:
    with (root / _MOD).open("a", encoding="utf-8") as handle:
        handle.write("\n\ndef added(value):\n    return value\n")


@dataclass(frozen=True, slots=True)
class _Path:
    """One row of the table: a damage, what it must be called, what is walked."""

    reason: str | None
    walked: tuple[str, ...]
    on_disk: Callable[[Path, Path], None] = lambda _root, _cache: None
    after_load: Callable[[Path], Callable[[], None]] | None = None
    count: int = 1


_DECISION_TABLE: dict[str, _Path] = {
    # An ordinary miss: nothing is wrong with the store, so nothing is said.
    # A new module moves the module manifest, so every dependent lane misses
    # on its profile: the whole tree is walked, and that is still no refusal.
    "miss.new-file": _Path(
        reason=None,
        walked=(_INIT, _MOD, "pkg/added.py"),
        on_disk=lambda root, _cache: _add_module(root),
    ),
    "miss.source-edited": _Path(
        reason=None, walked=(_MOD,), on_disk=lambda root, _cache: _edit_source(root)
    ),
    # The stored bytes are not the bytes that were written.
    "corrupt.identity-checksum": _Path(
        reason="corrupt",
        walked=(_MOD,),
        on_disk=lambda _root, cache: break_identity_checksum(cache, _MOD),
    ),
    "corrupt.lane-row-missing": _Path(
        reason="corrupt",
        walked=(_MOD,),
        on_disk=lambda _root, cache: _delete_lane_row(cache),
    ),
    "corrupt.lane-stored-as-text": _Path(
        reason="corrupt",
        walked=(_MOD,),
        on_disk=lambda _root, cache: _lane_as_text(cache),
    ),
    # Verified bytes -- exactly what some writer stored -- that are not a
    # cache entry at all.
    "undecodable.not-json": _Path(
        reason="undecodable",
        walked=(_MOD,),
        on_disk=lambda _root, cache: write_lane_bytes(
            cache, _MOD, TABLE_DEPENDENT, b"\xff\x00", as_writer=True
        ),
    ),
    "undecodable.not-an-object": _Path(
        reason="undecodable",
        walked=(_MOD,),
        on_disk=lambda _root, cache: write_lane_bytes(
            cache, _MOD, TABLE_NEUTRAL, b"[1]", as_writer=True
        ),
    ),
    # A verified entry this build cannot read: a writer and a reader that
    # disagree under one generation mark.
    "incompatible.unknown-variant": _Path(
        reason="incompatible",
        walked=(_MOD,),
        on_disk=lambda _root, cache: swap_lane_bytes(
            cache,
            _MOD,
            TABLE_DEPENDENT,
            anchor=b'"rr":[',
            needle=b'"pydantic"',
            replacement=b'"quantum!"',
            as_writer=True,
        ),
    ),
    # The store could not hand the entry back at all.
    "unreadable.store-gone": _Path(
        reason="unreadable",
        walked=(_INIT, _MOD),
        after_load=_unlink_store,
        count=2,
    ),
    "unreadable.lane-table-gone": _Path(
        reason="unreadable",
        walked=(_INIT, _MOD),
        after_load=_drop_dependent_table,
        count=2,
    ),
}


@pytest.mark.parametrize("case", sorted(_DECISION_TABLE))
def test_every_way_a_cached_record_is_not_served_has_one_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    """Typed, counted and warned -- or, for an ordinary miss, none of these.

    Each row of the table is one input that reaches one path of the reader;
    the reason, the count, the warning and the walked files are what that
    path must answer, and the facts are the cold run's in every row.
    """

    row = _DECISION_TABLE[case]
    root, cache_path, _cold_processing = _cold(tmp_path)
    row.on_disk(root, cache_path)
    cold_now = discover_and_process(
        _boot(root), tmp_path / "cold-again.sqlite3", root=root, warm=False
    )[2]

    warm = _warm(
        monkeypatch,
        root,
        cache_path,
        after_load=None if row.after_load is None else row.after_load(cache_path),
    )

    assert warm.walked(root) == sorted(row.walked)
    assert _facts(warm.processing) == _facts(cold_now)
    if row.reason is None:
        assert warm.refusals() == _no_refusal()
        assert warm.cache_warnings() == []
    else:
        assert warm.refusals() == _only(row.reason, row.count)
        (warning,) = warm.cache_warnings()
        assert row.reason in warning
        assert all(path in warning for path in row.walked)


def test_the_decision_table_names_every_refusal_reason_and_its_counter() -> None:
    """The vocabulary, the table above and the counters are one closed set."""

    members = {reason.value for reason in cache_versioning.CacheRefusal}
    exercised = {row.reason for row in _DECISION_TABLE.values()} - {None}

    assert members == set(_REASONS) == exercised
    counters = core_discovery._CACHE_REFUSAL_COUNTERS
    assert {reason.value: key for reason, key in counters.items()} == {
        reason: _counter(reason) for reason in _REASONS
    }
    assert {_counter(reason) for reason in _REASONS} <= COUNTER_KEYS


# -- singletons ------------------------------------------------------------------


def test_a_singleton_whose_bytes_changed_is_refused_and_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The segment projection is decoded and used, so it is verified too."""

    root, cache_path, _cold_processing = _cold(tmp_path)
    writer = Cache(cache_path, root=root)
    writer.load()
    writer.segment_report_projection = {
        "digest": "d" * 64,
        "suppressed": 1,
        "groups": {},
    }
    writer._dirty = True
    writer.save()
    assert (
        encode_segment_report_projection(writer.segment_report_projection, root=root)
        is not None
    )
    with open_store(cache_path) as conn:
        conn.execute(
            "UPDATE cache_singletons SET payload = "
            "CAST(replace(CAST(payload AS TEXT), '\"s\":1', '\"s\":7') AS BLOB)"
        )
        changed = conn.execute("SELECT payload FROM cache_singletons").fetchone()
    assert b'"s":7' in bytes(changed[0])

    warm = _warm(monkeypatch, root, cache_path)

    assert warm.cache.segment_report_projection is None
    assert warm.refusals() == _only("corrupt")
    (warning,) = warm.cache_warnings()
    assert "segment" in warning


def test_a_verified_singleton_this_build_cannot_decode_is_incompatible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exactly the bytes a writer stored, in a shape this build does not read."""

    root, cache_path, _cold_processing = _cold(tmp_path)
    with cache_backend.CacheBackend(cache_path) as backend:
        backend.write_singleton(
            cache_backend.SINGLETON_SEGMENT_REPORT,
            {"unexpected": 1},
            version=Cache._CACHE_VERSION,
        )

    warm = _warm(monkeypatch, root, cache_path)

    assert warm.cache.segment_report_projection is None
    assert warm.walked(root) == []
    assert warm.refusals() == _only("incompatible")
    (warning,) = warm.cache_warnings()
    assert "incompatible" in warning
    assert "segment" in warning


# -- the previous generation -------------------------------------------------------


def _previous_generation_with_a_wrong_value(
    tmp_path: Path,
) -> tuple[Path, Path, ProcessingResult]:
    """A schema-"2" store of the cold run, one value in it quietly wrong.

    The hook's target is renamed in place, length kept: a corruption that
    generation's checksum could not see. Whoever declares these rows verified
    serves it; whoever recomputes them does not.
    """

    root, cache_path, cold = _cold(tmp_path)
    old_store = tmp_path / "previous-generation.sqlite3"
    transcribe_to_schema_two(cache_path, old_store)
    swap_lane_bytes(
        old_store,
        _MOD,
        TABLE_DEPENDENT,
        anchor=b'"rr":[',
        needle=b"BytesAsText.bytes_schema",
        replacement=b"BytesAsText.bytes_schemX",
    )
    return root, old_store, cold


def test_a_store_from_the_previous_schema_is_invalidated_whole_and_never_re_signed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Typed invalidation, full recompute, a fresh store -- the old bytes gone.

    The old store carries one value-valid corruption its own generation could
    not see. Re-signing old rows with a fresh content digest would sign that
    corruption into the new generation; invalidation recomputes it away.
    """

    root, old_store, cold = _previous_generation_with_a_wrong_value(tmp_path)

    upgraded = _warm(monkeypatch, root, old_store)

    assert upgraded.load_status is CacheStatus.VERSION_MISMATCH
    assert upgraded.walked(root) == [_INIT, _MOD]
    assert upgraded.refusals() == _no_refusal()
    assert _facts(upgraded.processing) == _facts(cold)

    upgraded.cache.save()
    assert read_cache_meta(old_store)[META_KEY_SCHEMA] == (
        cache_backend.CACHE_BACKEND_SCHEMA_VERSION
    )
    for path in (_INIT, _MOD):
        for table in (TABLE_NEUTRAL, TABLE_DEPENDENT):
            assert b"bytes_schemX" not in read_lane_bytes(old_store, path, table)

    again = _warm(monkeypatch, root, old_store)

    assert again.load_status is CacheStatus.OK
    assert again.walked(root) == []
    assert again.refusals() == _no_refusal()
    assert _facts(again.processing) == _facts(cold)


def test_a_previous_schema_reached_by_the_collector_first_is_dropped_not_re_signed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The collector opens the store for writing before any run reads it.

    That open is the one place a migration could adapt the old rows -- add
    the digest columns, digest the lanes as they stand, re-mint the checksum
    -- and so declare verified whatever they hold. It drops them instead, so
    the next run recomputes the corrupted fact rather than serving it.
    """

    root, old_store, cold = _previous_generation_with_a_wrong_value(tmp_path)

    CacheStoreGcJob(
        path=old_store, version=Cache._CACHE_VERSION, now_epoch=1_700_000_000
    ).collect()
    upgraded = _warm(monkeypatch, root, old_store)

    assert upgraded.load_status is not CacheStatus.OK
    assert upgraded.walked(root) == [_INIT, _MOD]
    assert _facts(upgraded.processing) == _facts(cold)
    with open_store(old_store) as conn:
        lanes = [
            bytes(payload)
            for table in (TABLE_NEUTRAL, TABLE_DEPENDENT)
            for (payload,) in conn.execute(f"SELECT payload FROM {table}")
        ]
    assert not any(b"bytes_schemX" in lane for lane in lanes)


def test_a_previous_schema_retagged_as_current_is_not_served(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A generation mark rewritten in place does not make old rows verified."""

    root, cache_path, cold = _cold(tmp_path)
    old_store = tmp_path / "previous-generation.sqlite3"
    transcribe_to_schema_two(cache_path, old_store)
    with open_store(old_store) as conn:
        conn.execute(
            "UPDATE cache_backend_meta SET value = ? WHERE key = ?",
            (cache_backend.CACHE_BACKEND_SCHEMA_VERSION, META_KEY_SCHEMA),
        )

    upgraded = _warm(monkeypatch, root, old_store)

    assert upgraded.load_status is not CacheStatus.OK
    assert upgraded.walked(root) == [_INIT, _MOD]
    assert _facts(upgraded.processing) == _facts(cold)
