# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The publication's cheaper road leaves every stored byte where it was.

The publication path was made cheaper (one normalization, one shared sort, a
per-family address prefix, no object lookup for a run that is already
published).  None of that may change what the store holds, so this module
holds the store itself: after every step of one publication sequence, every
table is dumped in primary-key order -- the rowids of objects and
memberships included -- and digested, and the digests are known-answer
values recorded on the tree before the change (``7448116c``).

The sequence is the publication's own store road (``_publish_and_collect``:
the write, the sweep that follows it, and the publisher's lease release) and
walks the four cases the cost work touches: a first publication into an
empty store, a republication of a run the store already holds, an edit
publishing a new run, and a sweep that collects a run -- then back to the
first run after it was collected, which re-inserts its object under a new
rowid.

The model is the roundtrip fixture (every family non-empty), not an
analysis: its rows are fixed strings and integers, so the digests are a
property of the store code alone and do not move with the interpreter that
analysed anything.  The positive controls show the instrument sees what it
is pinned against: one changed payload byte, and the same rows inserted in
another order.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from codeclone.canonical import StoreIntegrityError
from codeclone.canonical import store as store_module
from codeclone.canonical.model import CanonicalModel
from codeclone.canonical.store import (
    RunStore,
    RunStoreGcJob,
    collect_garbage,
    release_run_lease,
)
from codeclone.core import canonical_snapshot as canonical_snapshot_module
from codeclone.core.canonical_snapshot import (
    RUN_SNAPSHOT_NAMESPACE,
    _publish_and_collect,
)
from codeclone.models import CANONICAL_HEAD_TARGET
from tests.test_canonical_roundtrip import evaluated_fixture_model

#: Every table of the store, each in its primary-key order, rowid included
#: where the key is not the rowid itself.
_TABLES: tuple[tuple[str, str], ...] = (
    ("store_meta", "SELECT * FROM store_meta ORDER BY id"),
    ("witness", "SELECT rowid, * FROM witness ORDER BY layer"),
    ("namespaces", "SELECT * FROM namespaces ORDER BY namespace_pk"),
    ("families", "SELECT * FROM families ORDER BY family_pk"),
    ("objects", "SELECT * FROM objects ORDER BY object_pk"),
    ("runs", "SELECT * FROM runs ORDER BY run_pk"),
    ("run_members", "SELECT * FROM run_members ORDER BY run_pk, object_pk"),
    ("heads", "SELECT * FROM heads ORDER BY namespace_pk, target"),
    (
        "head_history",
        "SELECT * FROM head_history ORDER BY namespace_pk, target, generation",
    ),
    ("run_leases", "SELECT rowid, * FROM run_leases ORDER BY lease_id"),
    ("retained_runs", "SELECT * FROM retained_runs ORDER BY run_pk"),
    (
        "run_report_links",
        "SELECT * FROM run_report_links ORDER BY report_run_identity, run_pk",
    ),
)

_BASE_RUN = "ea1ec89d4c5fc86b24699950e063474cb78a184988d55f3fa8e4b2f756e8dbe9"
_EDIT_RUN = "f67f49f6209ff1851e7ca86a4bb7217717ae6380a87530b8a01296f1501a56b2"

#: ``(step, run id, new objects, runs collected by its sweep, store digest)``
#: recorded on ``7448116c``, before the publication cost work.
_KNOWN_SEQUENCE: tuple[tuple[str, str, int, int, str], ...] = (
    (
        "first",
        _BASE_RUN,
        153,
        0,
        "3c9aee3c1592c22b6fd814702a7da5a5069bedb23280fb3d14cd96c4901ac3e0",
    ),
    (
        "republish",
        _BASE_RUN,
        0,
        0,
        "9b55d15189ad9b7fb5154ec7124de0f4f7e074559fe8ca88b0790ccb4e81cac6",
    ),
    (
        "republish",
        _BASE_RUN,
        0,
        0,
        "07889f2b2096692fb7474981653b11b17e803e1f58f7c1f5a1843210934c295a",
    ),
    (
        "edit",
        _EDIT_RUN,
        1,
        0,
        "d6902a1cb3fc16a8269f896ec5961f9bd8f82479c0bb4ad3eb6d0312a41e7a20",
    ),
    (
        "republish edit, sweep collects the first run",
        _EDIT_RUN,
        0,
        1,
        "e9f7dcee7f1ce18c6e767a822062bef7376f7c44093055449c1f2480bee3d8b0",
    ),
    (
        "republish edit",
        _EDIT_RUN,
        0,
        0,
        "3d9f0158258eb9447454c9b71858cfcb931c6c4a4d0b4afc34ec73b88ac9bd6c",
    ),
    (
        "back to the collected first run",
        _BASE_RUN,
        1,
        0,
        "24fd5e0a8dec3f0e06a7fe87d93f2f99cb68120acc57cef6693f985ee283d23d",
    ),
    (
        "republish, sweep collects the edit",
        _BASE_RUN,
        0,
        1,
        "6f2a6ba83474ae43c8405790cd8c77a8a61f7abba616f635a9873a4d2fc1d0d7",
    ),
)


def _cell(value: object) -> list[str]:
    """One stored value, spelled with its storage class."""
    if isinstance(value, bytes):
        return ["b", value.hex()]
    if isinstance(value, int):
        return ["i", str(value)]
    if isinstance(value, str):
        return ["s", value]
    assert value is None, f"unexpected stored value {value!r}"
    return ["n", ""]


def _store_digest(path: Path) -> str:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        digest = hashlib.sha256()
        for table, sql in _TABLES:
            rows = [[_cell(value) for value in row] for row in connection.execute(sql)]
            digest.update(json.dumps([table, rows]).encode("utf-8"))
    finally:
        connection.close()
    return digest.hexdigest()


def _edited(model: CanonicalModel) -> CanonicalModel:
    """A neighbour run: one object of the first run gone, one new object."""
    dropped = min(model.coupled_sets, key=sorted)
    return replace(
        model,
        coupled_sets=frozenset(
            {*(model.coupled_sets - {dropped}), frozenset({"EditedRun"})}
        ),
    )


@pytest.fixture(autouse=True)
def _the_recorded_sweep(monkeypatch: pytest.MonkeyPatch) -> None:
    """The sweep the known answers were recorded under: the head-generation
    window of two, the publication's policy on ``7448116c``.

    What this module holds is the WRITE road -- the bytes a publication, a
    republication and a collection leave behind -- and that road did not
    change when the publication's retention became the registry's window
    (recovery wave, 2026-10-12): the window holds REGISTERED runs, this
    sequence registers none, and under it every superseded run would leave at
    the next step, a different sequence altogether.  The window is pinned
    where it is the subject (``test_run_store_retention``,
    ``test_run_store_gc_owner``); here the sweep stays the one the digests
    record, so a digest that moves still says the write road moved."""

    def recorded_sweep(store: RunStore) -> object:
        return RunStoreGcJob(store=store, retain_history=2).collect()

    monkeypatch.setattr(
        canonical_snapshot_module, "_collect_after_publication", recorded_sweep
    )


def _publish_step(path: Path, model: CanonicalModel) -> tuple[str, int, int]:
    """One publication's store road: write, sweep, release the lease."""
    with RunStore(path) as store:
        receipt, lease, collection = _publish_and_collect(
            store,
            model,
            namespace=RUN_SNAPSHOT_NAMESPACE,
            target=CANONICAL_HEAD_TARGET,
        )
        assert release_run_lease(store, lease)
    collected = dict(collection.collected).get("unreachable", 0)
    return receipt.run_id, receipt.new_objects, collected


def _run_sequence(path: Path) -> list[tuple[str, int, int, str]]:
    base = evaluated_fixture_model()
    edit = _edited(base)
    observed = []
    for model in (base, base, base, edit, edit, edit, base, base):
        run_id, new_objects, collected = _publish_step(path, model)
        observed.append((run_id, new_objects, collected, _store_digest(path)))
    return observed


def _expected() -> list[tuple[str, int, int, str]]:
    return [row[1:] for row in _KNOWN_SEQUENCE]


def test_the_publication_sequence_leaves_every_stored_byte_where_it_was(
    tmp_path: Path,
) -> None:
    """Every step of the sequence, against the store the old road left."""
    observed = _run_sequence(tmp_path / "runs.sqlite3")
    for (step, *_), expected, actual in zip(
        _KNOWN_SEQUENCE, _expected(), observed, strict=True
    ):
        assert actual == expected, f"step {step!r} stored different bytes"


def test_the_digest_sees_one_changed_payload_byte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Positive control: the same sequence with one byte appended to every
    payload is a different store from its first step on."""
    original = store_module._payload_bytes
    monkeypatch.setattr(
        store_module, "_payload_bytes", lambda value: original(value) + b" "
    )
    observed = _run_sequence(tmp_path / "runs.sqlite3")
    assert all(
        actual[3] != expected[3]
        for expected, actual in zip(_expected(), observed, strict=True)
    )


def test_the_digest_sees_the_same_rows_inserted_in_another_order(
    tmp_path: Path,
) -> None:
    """Positive control: a store holding the very same objects, runs and
    memberships, with the objects inserted in reverse order -- only the
    rowids differ -- is not the store the sequence pins."""
    path = tmp_path / "runs.sqlite3"
    _publish_step(path, evaluated_fixture_model())
    assert _store_digest(path) == _KNOWN_SEQUENCE[0][4]
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        rows = connection.execute(
            "SELECT object_pk, namespace_pk, object_id, family_pk, payload "
            "FROM objects ORDER BY object_pk"
        ).fetchall()
        remap = {old[0]: new_pk for new_pk, old in enumerate(reversed(rows), start=1)}
        members = connection.execute(
            "SELECT run_pk, object_pk FROM run_members"
        ).fetchall()
        connection.execute("DELETE FROM run_members")
        connection.execute("DELETE FROM objects")
        connection.executemany(
            "INSERT INTO objects (object_pk, namespace_pk, object_id, family_pk, "
            "payload) VALUES (?, ?, ?, ?, ?)",
            [(remap[row[0]], *row[1:]) for row in reversed(rows)],
        )
        connection.executemany(
            "INSERT INTO run_members (run_pk, object_pk) VALUES (?, ?)",
            [(run_pk, remap[object_pk]) for run_pk, object_pk in members],
        )
        connection.commit()
    with RunStore(path) as store:
        # Same content: the run still reads back, proven member by member.
        assert store.read_run(_BASE_RUN) == evaluated_fixture_model().normalize()
    assert _store_digest(path) != _KNOWN_SEQUENCE[0][4]


# -- one normalization: the store's ------------------------------------------


def test_the_store_normalizes_what_it_is_handed_into_the_same_bytes(
    tmp_path: Path,
) -> None:
    """The producer builder no longer normalizes; the store always does.

    A model handed over un-normalized and the same model normalized first
    publish the same store, byte for byte.  The fixture is one whose
    normalization changes it, so a store that stopped normalizing would
    store the un-closed domains and could not agree."""
    raw = evaluated_fixture_model()
    assert raw != raw.normalize(), "the fixture must need its normalization"
    first, second = tmp_path / "raw.sqlite3", tmp_path / "normalized.sqlite3"
    assert _publish_step(first, raw)[0] == _BASE_RUN
    assert _publish_step(second, raw.normalize())[0] == _BASE_RUN
    assert _store_digest(first) == _store_digest(second) == _KNOWN_SEQUENCE[0][4]


# -- the address prefix and the shared sort ----------------------------------


def test_the_prefix_hasher_is_the_object_address_for_every_family() -> None:
    payloads = (b"", b"{}", b'{"a":"\\u0000"}', b"\x00\xff" * 40)
    for family in sorted(store_module._FAMILY_NAMESPACE):
        for namespace in ("codeclone.analysis", "lineage-alpha"):
            address = store_module._object_id_hasher(namespace, family)
            for payload in payloads:
                assert address(payload) == store_module._object_id(
                    namespace, family, payload
                ), (family, namespace, payload)


def test_the_shared_sort_digests_the_membership_the_reads_digest() -> None:
    ids = [hashlib.sha256(bytes([value])).hexdigest() for value in range(40)]
    assert store_module._sorted_membership_digest(
        sorted(ids)
    ) == store_module._membership_digest(list(reversed(ids)))


# -- republication: no lookup, the lock decides, the bytes are still proven --


def test_a_republication_looks_no_object_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The lookup before the lock runs for a run the store lacks and not for
    one it already holds published."""
    calls: list[int] = []
    original = store_module._prepare_object_lookup

    def counted(*args: object, **kwargs: object) -> object:
        calls.append(1)
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(store_module, "_prepare_object_lookup", counted)
    path = tmp_path / "runs.sqlite3"
    base = evaluated_fixture_model()
    _publish_step(path, base)
    assert len(calls) == 1
    _publish_step(path, base)
    _publish_step(path, base)
    assert len(calls) == 1, "a republication looked its objects up"
    _publish_step(path, _edited(base))
    assert len(calls) == 2, "a new run skipped its lookup"


def test_a_run_collected_between_the_look_and_the_lock_is_written_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The run is published when the publisher looks and gone when it takes
    the lock: the row read under the lock decides, so the run is written in
    full -- and the store is the one a publisher that never saw the run
    leaves."""
    base, edit = evaluated_fixture_model(), _edited(evaluated_fixture_model())
    raced, control = tmp_path / "raced.sqlite3", tmp_path / "control.sqlite3"
    for path in (raced, control):
        with RunStore(path) as store:
            store.write_full_run(
                base,
                namespace=RUN_SNAPSHOT_NAMESPACE,
                target="a",
                expected_generation=0,
            )
            store.write_full_run(
                edit,
                namespace=RUN_SNAPSHOT_NAMESPACE,
                target="a",
                expected_generation=1,
            )
    with RunStore(control) as store:
        collect_garbage(store, retain_history=0)
    original = store_module._published_before_the_lock
    seen: list[bool] = []

    def collected_after_the_look(connection: sqlite3.Connection, run_id: str) -> bool:
        published = original(connection, run_id)
        seen.append(published)
        with RunStore(raced) as other:
            collect_garbage(other, retain_history=0)
        return published

    monkeypatch.setattr(
        store_module, "_published_before_the_lock", collected_after_the_look
    )
    with RunStore(raced) as store:
        receipt = store.write_full_run(
            base, namespace=RUN_SNAPSHOT_NAMESPACE, target="b", expected_generation=0
        )
        assert store.read_run(receipt.run_id) == base.normalize()
    monkeypatch.undo()
    assert seen == [True], "the publisher must have seen the run published"
    assert receipt.run_id == _BASE_RUN and receipt.new_objects == 1
    with RunStore(control) as store:
        store.write_full_run(
            base, namespace=RUN_SNAPSHOT_NAMESPACE, target="b", expected_generation=0
        )
    assert _store_digest(raced) == _store_digest(control)


def test_a_republication_still_proves_the_stored_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No object is written for a published run, and its members are still
    proven against the staged bytes under the lock: a member corrupted in
    the open transaction is a refused publication, not a silent one."""
    path = tmp_path / "runs.sqlite3"
    base = evaluated_fixture_model()
    _publish_step(path, base)
    with RunStore(path) as store:

        def corrupt_one_member() -> None:
            store._connection.execute(
                "UPDATE objects SET payload = ? WHERE object_pk = "
                "(SELECT MIN(object_pk) FROM objects)",
                (b"{}",),
            )

        monkeypatch.setattr(store, "_before_publish", corrupt_one_member)
        with pytest.raises(StoreIntegrityError, match="publish refused"):
            store.write_full_run(
                base,
                namespace=RUN_SNAPSHOT_NAMESPACE,
                target=CANONICAL_HEAD_TARGET,
                expected_generation=1,
            )
    assert _store_digest(path) == _KNOWN_SEQUENCE[0][4]


def test_an_unpublished_run_row_is_completed_and_not_duplicated(
    tmp_path: Path,
) -> None:
    """A run row present but never flipped published is not a republication:
    the full road runs, keeps that row and its membership, writes nothing it
    already holds, and flips it."""
    path = tmp_path / "runs.sqlite3"
    base = evaluated_fixture_model()
    _publish_step(path, base)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE runs SET published = 0 WHERE run_id = ?", (_BASE_RUN,)
        )
        connection.commit()
    with RunStore(path) as store:
        receipt = store.write_full_run(
            base,
            namespace=RUN_SNAPSHOT_NAMESPACE,
            target=CANONICAL_HEAD_TARGET,
            expected_generation=1,
        )
        assert receipt.run_id == _BASE_RUN and receipt.new_objects == 0
        assert store.read_run(_BASE_RUN) == base.normalize()
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT run_pk, published FROM runs").fetchall() == [
            (1, 1)
        ]
        members = connection.execute("SELECT count(*) FROM run_members").fetchone()
        assert members == (153,)
