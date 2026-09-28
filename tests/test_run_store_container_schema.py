# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The container of the canonical run store, as the store-schema audit
(2026-09-28, five repositories, 2.3k to 327k objects) measured it should be.

Three changes of the CONTAINER, and only of the container:

* ``objects.object_id`` holds the 32 bytes of the digest, not its 64-character
  hex spelling -- the file shrank 10.4-15.1 % after ten runs and the automatic
  ``UNIQUE`` index 43.6 %, with no timing worse than noise.  Hex is spoken
  only at the API boundary, and the byte order of the BLOB is the order of
  its lowercase hex, so every ``ORDER BY object_id`` keeps its answer;
* a ``families`` lookup table, with ``objects.family_pk`` instead of the
  family name repeated in every row;
* an index on ``objects(family_pk)``, and a family read that starts from it
  with the join order PINNED by ``CROSS JOIN``: the planner does not choose
  the index on its own without ``ANALYZE`` (measured), and a read that walked
  the whole membership of a run to return one family's rows was O(run) -- the
  audit's positive control visited 327 354 rows to return one.

None of it moves a content address, the membership digest or a run id: those
are computed from hex digests and family NAMES, never from the storage
representation (``tests/test_canonical_export.py`` holds the known answers).
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Final

import pytest

from codeclone.canonical import RunStore, StoreIntegrityError
from codeclone.canonical import store as store_module
from tests.test_canonical_roundtrip import fixture_model

_NS: Final = "container"
_TARGET: Final = "worktree"


def _published(path: Path) -> tuple[str, dict[str, int]]:
    with RunStore(path) as store:
        receipt = store.write_full_run(
            fixture_model(), namespace=_NS, target=_TARGET, expected_generation=0
        )
    return receipt.run_id, receipt.family_counts


def _columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")]


def test_an_object_id_is_stored_as_the_32_bytes_of_its_digest(
    tmp_path: Path,
) -> None:
    """Every stored address is a 32-byte BLOB whose hex is the address the
    API speaks: the content addresses a read proves against are exactly the
    stored bytes, spelled in lowercase hex."""
    path = tmp_path / "runs.sqlite3"
    run_id, family_counts = _published(path)
    with closing(sqlite3.connect(path)) as raw:
        shapes = raw.execute(
            "SELECT DISTINCT typeof(object_id), length(object_id) FROM objects"
        ).fetchall()
        assert shapes == [("blob", 32)]
        stored = {
            bytes(row[0]).hex() for row in raw.execute("SELECT object_id FROM objects")
        }
    assert len(stored) == sum(family_counts.values())
    spoken: list[str] = []
    real = store_module._decode_member_object

    def _record(
        namespace: str,
        object_id_value: str,
        family: str,
        payload: bytes,
        into: dict[str, list[object]],
    ) -> None:
        spoken.append(object_id_value)
        real(namespace, object_id_value, family, payload, into)

    with RunStore(path, create=False) as store:
        store_module._decode_member_object = _record
        try:
            store.read_run(run_id)
        finally:
            store_module._decode_member_object = real
    assert set(spoken) == stored
    assert spoken == sorted(spoken), "a full read no longer walks address order"


def test_a_family_name_is_stored_once_in_its_lookup_table(tmp_path: Path) -> None:
    path = tmp_path / "runs.sqlite3"
    _, family_counts = _published(path)
    with closing(sqlite3.connect(path)) as raw:
        assert _columns(raw, "objects") == [
            "object_pk",
            "namespace_pk",
            "object_id",
            "family_pk",
            "payload",
        ]
        assert _columns(raw, "families") == ["family_pk", "family"]
        per_family = dict(
            raw.execute(
                "SELECT f.family, count(*) FROM objects o "
                "JOIN families f ON f.family_pk = o.family_pk GROUP BY f.family"
            ).fetchall()
        )
        names = [str(row[0]) for row in raw.execute("SELECT family FROM families")]
    assert per_family == family_counts
    assert sorted(names) == sorted(family_counts)


def _executed_family_read(path: Path, run_id: str) -> tuple[str, list[str]]:
    """The statement ``read_family`` actually executed, and its plan."""
    executed: list[str] = []
    with RunStore(path, create=False) as store:
        connection = store._connection
        connection.set_trace_callback(executed.append)
        try:
            rows = store.read_family(run_id, store_module.FAMILY_COUPLED_SET)
        finally:
            connection.set_trace_callback(None)
        assert rows, "the read family is empty, so no plan could be exercised"
        scans = [
            statement
            for statement in executed
            if "run_members" in statement and "payload" in statement
        ]
        assert len(scans) == 1, executed
        plan = [
            str(row[3]) for row in connection.execute(f"EXPLAIN QUERY PLAN {scans[0]}")
        ]
    return scans[0], plan


def test_a_family_read_starts_from_the_family_index(tmp_path: Path) -> None:
    """Read the plan of the statement the read EXECUTED: the family's own
    objects are found through ``idx_objects_family`` and each one's
    membership is proven by one equality probe on both ``object_pk`` and
    ``run_pk`` (the planner may take the primary key or the covering
    ``idx_run_members_object``; both are one probe) -- never a walk of the
    run's whole membership."""
    path = tmp_path / "runs.sqlite3"
    run_id, _ = _published(path)
    _, plan = _executed_family_read(path, run_id)
    objects_step = next(
        (index for index, line in enumerate(plan) if " o " in f" {line} "), None
    )
    members_step = next(
        (index for index, line in enumerate(plan) if " m " in f" {line} "), None
    )
    assert objects_step is not None and members_step is not None, plan
    assert objects_step < members_step, f"the read starts from the run: {plan}"
    assert "USING INDEX idx_objects_family (family_pk=?)" in plan[objects_step], plan
    members = plan[members_step]
    assert members.startswith("SEARCH m"), plan
    assert "object_pk=?" in members and "run_pk=?" in members, plan
    assert not any(line.startswith("SCAN") for line in plan), plan


def test_the_container_refuses_an_address_that_is_not_32_bytes(
    tmp_path: Path,
) -> None:
    """``UNIQUE (namespace_pk, object_id)`` refuses a duplicate address only
    while every address has one storage class: SQLite never equates a TEXT
    value with a BLOB, so the hex spelling of a stored address would be a
    second row for the same object.  The column refuses anything but the
    32 bytes, on a real insert."""
    path = tmp_path / "runs.sqlite3"
    _published(path)
    with closing(sqlite3.connect(path)) as raw:
        blob, namespace_pk, family_pk = raw.execute(
            "SELECT object_id, namespace_pk, family_pk FROM objects LIMIT 1"
        ).fetchone()
        # The hex spelling, a 32-character TEXT (only the storage-class half
        # of the check refuses it), and one byte short and one byte long.
        spellings = (
            bytes(blob).hex(),
            bytes(blob).hex()[:32],
            bytes(blob)[:31],
            bytes(blob) + b"\x00",
        )
        for spelling in spellings:
            with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint"):
                raw.execute(
                    "INSERT INTO objects (namespace_pk, object_id, family_pk, payload) "
                    "VALUES (?, ?, ?, ?)",
                    (namespace_pk, spelling, family_pk, b"{}"),
                )
        # Positive control on the same statement: a well-formed new address is
        # admitted, and the stored one is refused by UNIQUE, not by the check.
        raw.execute(
            "INSERT INTO objects (namespace_pk, object_id, family_pk, payload) "
            "VALUES (?, ?, ?, ?)",
            (namespace_pk, b"\x00" * 32, family_pk, b"{}"),
        )
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            raw.execute(
                "INSERT INTO objects (namespace_pk, object_id, family_pk, payload) "
                "VALUES (?, ?, ?, ?)",
                (namespace_pk, bytes(blob), family_pk, b"{}"),
            )


def test_a_stored_address_of_another_shape_is_an_integrity_refusal(
    tmp_path: Path,
) -> None:
    """The column refuses anything but 32 bytes; a file whose bytes were
    changed outside the store -- here with SQLite's own switch that skips
    ``CHECK`` -- can still hold one, and a read refuses it typed, naming the
    address, instead of dying on a raw ``TypeError`` or re-hashing a value
    that was never an address."""
    path = tmp_path / "runs.sqlite3"
    run_id, _ = _published(path)
    with closing(sqlite3.connect(path)) as raw:
        raw.execute("PRAGMA ignore_check_constraints = ON")
        raw.execute(
            "UPDATE objects SET object_id = hex(object_id) WHERE object_pk = "
            "(SELECT MIN(object_pk) FROM objects)"
        )
        raw.commit()
        assert raw.execute(
            "SELECT count(*) FROM objects WHERE typeof(object_id) = 'text'"
        ).fetchone() == (1,), "the probe changed no stored address"
    with (
        RunStore(path, create=False) as store,
        pytest.raises(StoreIntegrityError, match="cannot address its object"),
    ):
        store.read_run(run_id)
