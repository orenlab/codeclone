# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The serving door under raw SQLite faults (storage audit RS-04, 2026-09-24).

The door's contract is that a served answer never takes the tool down: every
way the store cannot answer is a REASON the surface can branch on and count.
Measured by the storage audit on the revision-2 build, three faults walked
past the typed refusals and out of the MCP call as raw exceptions, although
the surface behind the door already holds the memory answer and asked only
whether the store agrees:

* a store another process holds the write lock on --
  ``sqlite3.OperationalError: database is locked``, five seconds later;
* a file at the store path that is not a database, or a malformed image --
  ``sqlite3.DatabaseError``;
* a member payload whose storage class is TEXT rather than BLOB, bytes
  unchanged -- ``TypeError`` out of ``bytes()`` in the member scan.

Each pin drives the real door over the real store on the fault the audit
reproduced and holds the answer to memory with a typed reason: the
transient faults (a held lock, a read-only medium, an I/O error) as
``store_unavailable`` -- a fallback the surface counts, never memory by
design, because the bytes and the generation are both fine -- and the byte
faults as ``integrity``.  The classification is the store's own typed
refusal (``StoreUnavailableError`` / ``StoreIntegrityError``), pinned
directly as well, so the door still classifies nothing on its own.

The positive control of every fault is the same door on the same store once
the fault is lifted: a pin that stayed green because the door never reached
the store cannot pass.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

import codeclone.utils.sqlite_store as sqlite_store
from codeclone.api.run_store_serving import (
    MEMORY_BY_DESIGN_REASONS,
    SERVING_REASON_INTEGRITY,
    SERVING_REASON_SERVED,
    SERVING_REASON_STORE_UNAVAILABLE,
    SERVING_REASON_UNEXPRESSIBLE,
    SERVING_REASONS,
    SERVING_SOURCE_MEMORY,
    RunStoreServingOutcome,
    read_run_store_authority_candidates,
    read_run_store_slices,
)
from codeclone.canonical import RunStore
from codeclone.canonical.errors import (
    RunStoreError,
    StoreIntegrityError,
    StoreUnavailableError,
)
from codeclone.canonical.store import FAMILY_FILE_MODULE
from codeclone.models import (
    RUN_SNAPSHOT_LINK_LINKED,
    RUN_SNAPSHOT_PUBLICATION_PUBLISHED,
    RunSnapshotLink,
)
from tests.test_canonical_roundtrip import fixture_model

_NS = "serving-faults"
_TARGET = "worktree"

Door = Callable[..., tuple[object, RunStoreServingOutcome]]
_DOORS: tuple[Door, ...] = (read_run_store_slices, read_run_store_authority_candidates)

#: What each door answers once a fault is lifted, on the distinguishing
#: fixture: the slices are served; the candidates are refused as
#: ``unexpressible`` because the fixture's population never measured the
#: authority lane.  Either is the store ANSWERING -- the control that the
#: fault, and not the door never reaching the store, produced the fallback.
_CONTROL_REASONS: dict[Door, str] = {
    read_run_store_slices: SERVING_REASON_SERVED,
    read_run_store_authority_candidates: SERVING_REASON_UNEXPRESSIBLE,
}


def _publish(path: Path) -> str:
    with RunStore(path) as store:
        return store.write_full_run(
            fixture_model(), namespace=_NS, target=_TARGET, expected_generation=0
        ).run_id


def _linked(run_id: str) -> RunSnapshotLink:
    return RunSnapshotLink(
        state=RUN_SNAPSHOT_LINK_LINKED,
        outcome=RUN_SNAPSHOT_PUBLICATION_PUBLISHED,
        store_run_id=run_id,
        analysis_scope_digest="0" * 64,
        report_run_identity="1" * 64,
    )


def _enable(monkeypatch: pytest.MonkeyPatch, store: Path) -> None:
    monkeypatch.setenv("CODECLONE_RUN_STORE_ENABLED", "1")
    monkeypatch.setenv("CODECLONE_RUN_STORE_FORCE", "1")
    monkeypatch.setenv("CODECLONE_RUN_STORE_PATH", str(store))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sidecars(path: Path) -> list[str]:
    return sorted(
        candidate.name
        for candidate in path.parent.iterdir()
        if candidate != path and candidate.name.startswith(path.name)
    )


def _hold_write_lock(path: Path) -> sqlite3.Connection:
    holder = sqlite3.connect(path, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    return holder


# -- the vocabulary ---------------------------------------------------------


def test_store_unavailable_is_a_counted_fallback_in_the_closed_vocabulary() -> None:
    assert SERVING_REASON_STORE_UNAVAILABLE == "store_unavailable"
    assert SERVING_REASON_STORE_UNAVAILABLE in SERVING_REASONS
    assert tuple(sorted(SERVING_REASONS)) == SERVING_REASONS
    assert SERVING_REASON_STORE_UNAVAILABLE not in MEMORY_BY_DESIGN_REASONS
    assert issubclass(StoreUnavailableError, RunStoreError)
    assert not issubclass(StoreUnavailableError, StoreIntegrityError)


# -- a held write lock: the store is fine, SQLite cannot serve it now -------


@pytest.mark.parametrize("door", _DOORS, ids=("slices", "candidates"))
def test_a_locked_store_is_answered_from_memory_as_unavailable(
    door: Door, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "runs.sqlite3"
    run_id = _publish(path)
    _enable(monkeypatch, path)
    # The owner's busy timeout is the five seconds the audit measured; the
    # pin shortens the WAIT and never the fault -- the holder below still
    # owns the write lock the door's open takes.
    monkeypatch.setattr(sqlite_store, "_SQLITE_BUSY_TIMEOUT_MS", 200)
    holder = _hold_write_lock(path)
    try:
        answer, outcome = door(root=tmp_path, link=_linked(run_id))
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    assert answer is None
    assert (outcome.source, outcome.reason) == (
        SERVING_SOURCE_MEMORY,
        SERVING_REASON_STORE_UNAVAILABLE,
    )
    assert outcome.store_run_id == run_id
    assert "database is locked" in outcome.detail
    assert str(path) in outcome.detail
    # Positive control: the lock lifted, the same door reaches the store.
    _answer, outcome = door(root=tmp_path, link=_linked(run_id))
    assert outcome.reason == _CONTROL_REASONS[door]


def test_the_store_itself_names_a_held_lock_as_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The classification is the store's, not the door's: a reader that
    meets the lock at open gets the typed refusal with the path in it."""
    path = tmp_path / "runs.sqlite3"
    _publish(path)
    monkeypatch.setattr(sqlite_store, "_SQLITE_BUSY_TIMEOUT_MS", 200)
    holder = _hold_write_lock(path)
    try:
        with pytest.raises(StoreUnavailableError) as refused:
            RunStore(path, create=False)
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    assert refused.value.path == str(path)
    assert "database is locked" in str(refused.value)
    assert isinstance(refused.value.__cause__, sqlite3.OperationalError)
    with RunStore(path, create=False):  # the control: the lock lifted
        pass


# -- a file that is not a store: bytes, not generation, not availability ----


@pytest.mark.parametrize("door", _DOORS, ids=("slices", "candidates"))
def test_a_file_that_is_not_a_database_is_integrity_and_is_left_alone(
    door: Door, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "runs.sqlite3"
    path.write_bytes(b"this is not a sqlite database\n" * 64)
    before = _sha(path)
    _enable(monkeypatch, path)
    answer, outcome = door(root=tmp_path, link=_linked("a" * 64))
    assert answer is None
    assert (outcome.source, outcome.reason) == (
        SERVING_SOURCE_MEMORY,
        SERVING_REASON_INTEGRITY,
    )
    assert "not a database" in outcome.detail
    assert _sha(path) == before
    assert _sidecars(path) == []


def test_a_malformed_image_is_integrity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A store truncated after publication: the header still says how many
    pages the file holds, the pages are gone.  Whether SQLite meets the
    damage at the open's look or at the member scan, the door answers
    ``integrity`` with SQLite's own words."""
    path = tmp_path / "runs.sqlite3"
    run_id = _publish(path)
    assert _sidecars(path) == [], "the publisher left its journal behind"
    size = path.stat().st_size
    with path.open("r+b") as handle:
        handle.truncate(size * 2 // 5)
    _enable(monkeypatch, path)
    answer, outcome = read_run_store_slices(root=tmp_path, link=_linked(run_id))
    assert answer is None
    assert (outcome.source, outcome.reason) == (
        SERVING_SOURCE_MEMORY,
        SERVING_REASON_INTEGRITY,
    )
    assert "malformed" in outcome.detail


# -- a member whose storage class moved: same bytes, wrong class -------------


def _retype_payloads_as_text(path: Path) -> int:
    with sqlite3.connect(path) as raw:
        moved = raw.execute(
            "UPDATE objects SET payload = CAST(payload AS TEXT)"
        ).rowcount
        raw.commit()
    return moved


@pytest.mark.parametrize("door", _DOORS, ids=("slices", "candidates"))
def test_a_member_stored_as_text_is_integrity(
    door: Door, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "runs.sqlite3"
    run_id = _publish(path)
    assert _retype_payloads_as_text(path) > 0
    _enable(monkeypatch, path)
    answer, outcome = door(root=tmp_path, link=_linked(run_id))
    assert answer is None
    assert (outcome.source, outcome.reason) == (
        SERVING_SOURCE_MEMORY,
        SERVING_REASON_INTEGRITY,
    )
    assert outcome.store_run_id == run_id
    assert "TEXT" in outcome.detail and "BLOB" in outcome.detail


def test_the_store_refuses_a_text_member_typed_at_the_family_read(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runs.sqlite3"
    run_id = _publish(path)
    with RunStore(path, create=False) as store:
        assert store.read_family(run_id, FAMILY_FILE_MODULE)  # the control
    _retype_payloads_as_text(path)
    with RunStore(path, create=False) as store:
        with pytest.raises(StoreIntegrityError, match="TEXT"):
            store.read_family(run_id, FAMILY_FILE_MODULE)
        with pytest.raises(StoreIntegrityError, match="TEXT"):
            store.read_run(run_id)


# -- damage met AFTER the open: the read paths classify for themselves ------


def test_the_store_names_damage_met_at_the_read_as_integrity(tmp_path: Path) -> None:
    """The open looked at a healthy file; the file is damaged under the open
    handle.  Both read verbs answer with the store's own word, never SQLite's
    raw ``DatabaseError``."""
    path = tmp_path / "runs.sqlite3"
    run_id = _publish(path)
    with RunStore(path, create=False) as store:
        assert store.read_family(run_id, FAMILY_FILE_MODULE)  # the control
        size = path.stat().st_size
        with path.open("r+b") as handle:
            handle.truncate(size * 2 // 5)
        with pytest.raises(StoreIntegrityError, match="malformed"):
            store.read_family(run_id, FAMILY_FILE_MODULE)
        with pytest.raises(StoreIntegrityError, match="malformed"):
            store.read_run(run_id)


class _FaultingConnection:
    """A connection whose every statement meets the fault SQLite reports on a
    corrupt image: the bridge read is proven on its own mechanism, not on
    where truncation happens to land."""

    def execute(self, *_args: object) -> object:
        raise sqlite3.DatabaseError("database disk image is malformed")


def test_the_bridge_read_names_a_database_fault_as_integrity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from codeclone.canonical.store import linked_run

    path = tmp_path / "runs.sqlite3"
    _publish(path)
    with RunStore(path, create=False) as store:
        assert linked_run(store, report_run_identity="1" * 64) is None  # control
        monkeypatch.setattr(store, "_connection", _FaultingConnection())
        with pytest.raises(StoreIntegrityError, match="malformed") as refused:
            linked_run(store, report_run_identity="1" * 64)
        assert isinstance(refused.value.__cause__, sqlite3.DatabaseError)
        monkeypatch.undo()
