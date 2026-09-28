# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The reverse membership index ``run_members(object_pk)``.

``run_members.object_pk`` is the child key of a foreign key into
``objects``, and the sweep deletes parents: every collected object makes
SQLite look for surviving members that still point at it, and the sweep's
own ``NOT IN (SELECT object_pk FROM run_members)`` asks the same question
of the whole table.  The table's key is ``(run_pk, object_pk)``, so without
a second index both questions are full scans of ``run_members``.  Measured
on one self-repository store (3 runs, 921k memberships, 1495 objects
collected): 1.397e9 VM instructions per sweep without the index, 2.03e7
with it.

Four properties are the contract, each pinned on its own:

* the index exists on every store this build accepts, keyed on
  ``object_pk`` alone, and the sweep's real statement reaches ``objects``
  through it -- read off the plan of the statement the sweep executed, not
  a restatement of it;
* it changes no answer: one store read before its index arrived and after,
  byte for byte, through every read path, and every family read comes back
  in content-address order against an oracle that sorts in Python;
* it arrives after ``auto_vacuum`` is bound, because the file mode can only
  be chosen before the first b-tree exists (DESIGN-2026-09-02 II.4a);
* a store the witness refuses is left as it was -- no index is written into
  a file of another generation on the way to refusing it.

The index is created with the store, in its creation transaction, or added
to an existing store by the one migration verb; an open never adds it (the
refusal of a store without it is pinned in
``tests/test_run_store_ddl_authority.py``).  "Before its index" below is
therefore a store written by a build that did not declare it, completed by
the verb.
"""

from __future__ import annotations

import gc
import hashlib
import io
import shutil
import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import Final

import pytest

from codeclone.canonical import (
    CanonicalModel,
    RunStore,
    StoreCompatibilityError,
    export_run,
)
from codeclone.canonical import store as store_module
from codeclone.canonical.serving import read_served_run_slices
from codeclone.canonical.store import StoredFamily, collect_garbage
from tests.test_canonical_roundtrip import fixture_model

_NS: Final = "member-index"
_TARGET: Final = "worktree"
_INDEX: Final = "idx_run_members_object"
#: Every index this build declares except the one under test, so a "before"
#: store differs from the current one by exactly that index.
_OTHER_INDEXES: Final = tuple(
    statement for statement in store_module._INDEXES if _INDEX not in statement
)
_GENERATION_1: Final = (
    Path(__file__).parent / "fixtures" / "run_store_generation_1" / "runs.sqlite3"
)


def _wider_model() -> CanonicalModel:
    """A second state sharing every fixture object and adding six.

    Chosen because it makes storage order and content-address order
    DISAGREE inside one run: the shared objects were inserted by the first
    publication and hold the low primary keys, the new ones follow, and the
    new addresses interleave with the old ones.  A read that forgot its
    ``ORDER BY`` would hand that disagreement to the caller.
    """
    model = fixture_model()
    added = {frozenset({f"late-{n}"}) for n in range(6)}
    return replace(model, coupled_sets=model.coupled_sets | added)


def _publish(path: Path, *models: CanonicalModel) -> tuple[str, ...]:
    """Publish each model in turn onto one target; the last is the head."""
    with RunStore(path) as store:
        return tuple(
            store.write_full_run(
                model, namespace=_NS, target=_TARGET, expected_generation=generation
            ).run_id
            for generation, model in enumerate(models)
        )


def _publish_two(path: Path) -> tuple[str, ...]:
    """The fixture, then the wider state on top of it."""
    return _publish(path, fixture_model(), _wider_model())


def _indexes_on_members(connection: sqlite3.Connection) -> list[str]:
    return [
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' "
            "AND tbl_name = 'run_members' AND sql IS NOT NULL ORDER BY name"
        )
    ]


def _indexes_in_file(path: Path) -> list[str]:
    """A read-only look that also sees what still sits in the WAL."""
    raw = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return _indexes_on_members(raw)
    finally:
        raw.close()


def _stored_families() -> tuple[StoredFamily[object], ...]:
    """Every declared storage family, typed, and provably all of them."""
    families = tuple(
        sorted(
            (
                value
                for value in vars(store_module).values()
                if isinstance(value, StoredFamily)
            ),
            key=lambda entry: entry.family,
        )
    )
    assert {entry.family for entry in families} == set(store_module._FAMILY_NAMESPACE)
    return families


def _without_the_index(monkeypatch: pytest.MonkeyPatch) -> None:
    """Write and open stores the way a build without the index did.

    ``raising=False`` keeps the seam honest on a build that never had the
    step: the probe-validity asserts below, not this call, are what prove
    the "before" population really carries no index.
    """
    monkeypatch.setattr(store_module, "_INDEXES", _OTHER_INDEXES, raising=False)


# -- presence and plan ------------------------------------------------------


def test_a_store_carries_the_reverse_membership_index_on_object_pk(
    tmp_path: Path,
) -> None:
    with RunStore(tmp_path / "runs.sqlite3") as store:
        connection = store._connection
        assert _indexes_on_members(connection) == [_INDEX]
        columns = [
            str(row[2]) for row in connection.execute(f"PRAGMA index_info({_INDEX})")
        ]
    assert columns == ["object_pk"], (
        "the index must lead with the foreign-key child column the sweep "
        f"deletes parents of; it is keyed on {columns}"
    )


def test_the_sweep_reaches_objects_through_the_index_not_a_table_scan(
    tmp_path: Path,
) -> None:
    """Read the plan of the statement the sweep EXECUTED.

    The object delete carries both costs: the ``NOT IN`` subquery and, under
    ``foreign_keys=ON``, one child-key lookup per deleted parent.  The query
    plan shows the first; the compiled program shows every b-tree the
    statement opens, the foreign-key scan included, so the second is read
    from there: ``run_members``' own b-tree must not be opened at all.
    """
    path = tmp_path / "runs.sqlite3"
    # Wider first: collecting it then deletes the six objects only it held.
    _publish(path, _wider_model(), fixture_model())
    executed: list[str] = []
    with RunStore(path) as store:
        connection = store._connection
        connection.set_trace_callback(executed.append)
        try:
            report = collect_garbage(store, retain_history=0)
        finally:
            connection.set_trace_callback(None)
        object_deletes = [
            statement
            for statement in executed
            if statement.lstrip().upper().startswith("DELETE FROM OBJECTS")
        ]
        assert len(object_deletes) == 1, executed
        assert dict(report.detail)["objects_collected"] > 0, (
            "the sweep collected no object, so no parent delete and no "
            "foreign-key child lookup ever ran"
        )
        statement = object_deletes[0]
        plan = [
            str(row[3]) for row in connection.execute(f"EXPLAIN QUERY PLAN {statement}")
        ]
        roots = {
            int(row[1]): str(row[0])
            for row in connection.execute(
                "SELECT name, rootpage FROM sqlite_master WHERE rootpage > 0"
            )
        }
        opened = {
            roots.get(int(row[3]), str(row[3]))
            for row in connection.execute(f"EXPLAIN {statement}")
            if row[1] in {"OpenRead", "OpenWrite"}
        }
    assert any(_INDEX in line and "(object_pk=?)" in line for line in plan), plan
    assert not any(
        line.startswith("SCAN") and "run_members" in line for line in plan
    ), plan
    assert _INDEX in opened, opened
    assert "run_members" not in opened, (
        "the sweep's object delete still opens the run_members table itself "
        f"(a full scan per foreign-key check): {sorted(opened)}"
    )


# -- D7: the file mode is bound before the first b-tree ---------------------


def test_the_index_arrives_on_a_file_whose_auto_vacuum_was_bound_first(
    tmp_path: Path,
) -> None:
    """``auto_vacuum`` can only be chosen on a file with no b-tree yet; an
    index written before the connection owner binds it would leave a fresh
    store on ``NONE`` for good (SQLite: 0 NONE, 1 FULL, 2 INCREMENTAL)."""
    with RunStore(tmp_path / "runs.sqlite3") as store:
        connection = store._connection
        mode = int(connection.execute("PRAGMA auto_vacuum").fetchone()[0])
        indexes = _indexes_on_members(connection)
    assert indexes == [_INDEX]
    assert mode == 2, f"a fresh store with the index reads auto_vacuum={mode}"


# -- determinism: the index changes no answer -------------------------------


def _read_everything(path: Path, run_ids: tuple[str, ...]) -> dict[str, object]:
    """Every read path of every run, as bytes or their deterministic repr."""
    answer: dict[str, object] = {}
    with RunStore(path, create=False) as store:
        connection = store._connection
        answer["indexes_at_read"] = _indexes_on_members(connection)
        answer["runs"] = connection.execute(
            "SELECT run_id, analysis_scope_digest, membership_digest, published "
            "FROM runs ORDER BY run_id"
        ).fetchall()
        answer["witness"] = connection.execute(
            "SELECT layer, revision, role FROM witness ORDER BY layer"
        ).fetchall()
        answer["store_meta"] = connection.execute(
            "SELECT store_epoch, storage_schema_revision, contract_epoch "
            "FROM store_meta"
        ).fetchall()
        for run_id in run_ids:
            answer[f"{run_id}:project_run"] = store.project_run(run_id)
            sink = io.BytesIO()
            envelope = export_run(store, run_id, sink)
            answer[f"{run_id}:export"] = (sink.getvalue(), repr(envelope))
            answer[f"{run_id}:served"] = repr(
                read_served_run_slices(store, run_id, root=Path("/served"))
            )
            for family in _stored_families():
                answer[f"{run_id}:family:{family.family}"] = repr(
                    store.read_family(run_id, family)
                )
    return answer


def _content_address_order(path: Path, run_id: str) -> dict[str, str]:
    """The oracle: each family's members sorted IN PYTHON by content address
    and decoded by the one member decoder -- no ``ORDER BY`` involved."""
    raw = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        run_pk, namespace = raw.execute(
            "SELECT r.run_pk, n.namespace FROM runs r "
            "JOIN namespaces n ON n.namespace_pk = r.namespace_pk "
            "WHERE r.run_id = ?",
            (run_id,),
        ).fetchone()
        members = raw.execute(
            "SELECT o.object_id, f.family, o.payload FROM run_members m "
            "JOIN objects o ON o.object_pk = m.object_pk "
            "JOIN families f ON f.family_pk = o.family_pk WHERE m.run_pk = ?",
            (run_pk,),
        ).fetchall()
    finally:
        raw.close()
    oracle: dict[str, str] = {}
    for family in _stored_families():
        collected: dict[str, list[object]] = {}
        for object_id, stored_family, payload in sorted(members):
            if stored_family == family.family:
                store_module._decode_member_object(
                    str(namespace),
                    bytes(object_id).hex(),
                    str(stored_family),
                    bytes(payload),
                    collected,
                )
        oracle[family.family] = repr(tuple(family.rows(collected)))
    return oracle


def _storage_order_disagrees(path: Path, run_id: str, family: str) -> bool:
    raw = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        ids = [
            bytes(row[0]).hex()
            for row in raw.execute(
                "SELECT o.object_id FROM run_members m "
                "JOIN objects o ON o.object_pk = m.object_pk "
                "JOIN families f ON f.family_pk = o.family_pk "
                "JOIN runs r ON r.run_pk = m.run_pk "
                "WHERE r.run_id = ? AND f.family = ? ORDER BY m.object_pk",
                (run_id, family),
            )
        ]
    finally:
        raw.close()
    return len(ids) > 1 and ids != sorted(ids)


def test_one_store_reads_byte_identically_before_and_after_its_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same file, read by a build without the index and then -- once the
    migration verb has added it -- by this one, through
    ``read_run``/``project_run``, ``export_run``, every ``read_family`` and
    the served slices: identical bytes, identical digests, identical witness
    -- and the new index is the only schema difference between the two
    reads."""
    written = tmp_path / "written.sqlite3"
    _without_the_index(monkeypatch)
    run_ids = _publish_two(written)
    before_copy = tmp_path / "before.sqlite3"
    shutil.copy(written, before_copy)
    assert _indexes_in_file(before_copy) == [], "the before-store proves nothing"

    before = _read_everything(before_copy, run_ids)
    assert before["indexes_at_read"] == []
    monkeypatch.undo()
    assert store_module.migrate_store_schema(written) == (("index", _INDEX),)
    after = _read_everything(written, run_ids)
    assert after["indexes_at_read"] == [_INDEX]

    before.pop("indexes_at_read")
    after.pop("indexes_at_read")
    assert after == before

    with closing(sqlite3.connect(written)) as raw:
        assert raw.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert raw.execute("PRAGMA foreign_key_check").fetchall() == []
    # Idempotent: the verb finds the index and adds nothing, and the next
    # open finds it too.
    assert store_module.migrate_store_schema(written) == ()
    with RunStore(written, create=False) as store:
        assert _indexes_on_members(store._connection) == [_INDEX]


def test_every_family_read_comes_back_in_content_address_order(
    tmp_path: Path,
) -> None:
    """The half of the determinism pin that does not compare the store with
    itself.  Before and after the index the planner walks the membership key
    either way, so a read that lost its ``ORDER BY`` would agree with itself
    across the index and still hand out storage order.  The oracle sorts in
    Python, and the population is proven to contain a family whose storage
    order disagrees with its content-address order."""
    path = tmp_path / "runs.sqlite3"
    _, wider_run = _publish_two(path)
    assert _storage_order_disagrees(path, wider_run, "coupled_set"), (
        "no family of the read run stores its members out of content-address "
        "order, so this pin could not see a lost ORDER BY"
    )
    read = _read_everything(path, (wider_run,))
    oracle = _content_address_order(path, wider_run)
    assert {family: read[f"{wider_run}:family:{family}"] for family in oracle} == oracle


# -- a refused store is left as it was --------------------------------------


def test_a_store_the_witness_refuses_gets_no_index(tmp_path: Path) -> None:
    """The generation-1 store is refused at open (law 7) -- and it must be
    refused WITHOUT being written.  An index created by the shared schema
    step would land in the refused file's WAL before the witness is read and
    reach the main file when the refused handle is released, so this reads
    both: the schema through a connection that sees the WAL, and the bytes
    after the refused handle is gone."""
    copy = tmp_path / "runs.sqlite3"
    shutil.copy(_GENERATION_1, copy)
    digest_before = hashlib.sha256(copy.read_bytes()).hexdigest()
    with closing(sqlite3.connect(f"file:{copy}?mode=ro", uri=True)) as raw:
        witness_before = raw.execute(
            "SELECT layer, revision, role FROM witness ORDER BY layer"
        ).fetchall()
    assert _indexes_in_file(copy) == [], "the fixture proves nothing"

    with pytest.raises(StoreCompatibilityError):
        RunStore(copy, create=False)
    assert _indexes_in_file(copy) == [], (
        "the refused open wrote the index into a store of another generation"
    )
    gc.collect()
    assert hashlib.sha256(copy.read_bytes()).hexdigest() == digest_before
    with closing(sqlite3.connect(f"file:{copy}?mode=ro", uri=True)) as raw:
        assert (
            raw.execute(
                "SELECT layer, revision, role FROM witness ORDER BY layer"
            ).fetchall()
            == witness_before
        )
    assert witness_before, "the refused store carried no witness to compare"
