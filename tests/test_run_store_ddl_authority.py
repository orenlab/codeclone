# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Who may write the run store's schema: a creation, or the migration verb.

Ruling 2026-09-23: an open does not migrate and a read does not write.  The
store's DDL -- every table of ``_SCHEMA`` and every index of ``INDEXES`` --
runs in exactly two places:

* the transaction that creates a NEW store, together with its witness, so a
  schema without a witness is never visible and a creation that dies leaves
  nothing behind;
* ``codeclone run-store migrate --path PATH``, which decides under one write
  lock, witness first: another generation, or a file stating none, is
  refused as an open refuses it; a store of this generation gets the
  declared objects it lacks, and nothing else moves.

Every open of an EXISTING file reads the witness first and then the schema,
and refuses an incomplete one -- publisher, reader and MCP alike -- naming
the verb with the store's path; the file is left byte for byte as it was,
``-wal`` and ``-shm`` and the journal mode included.

The open takes that decision twice, on one function: in a look BEFORE the
shared connection owner (whose ``PRAGMA journal_mode=WAL`` would otherwise
be the first write into a rollback-journal file) and again under the write
lock (the file may change between the two).  Each mechanism has a population
only it can decide, and each is pinned on that population alone -- a pin
that ran both would stay green with either one broken.

Every byte-state comparison below is taken with no SQLite connection open
on the file: a connection is what creates ``-wal``/``-shm``, and a probe
that opened one would measure itself.

The command a refusal names is run here the way a user runs it -- the module
entry point in a child process -- and the surfaces that meet the refusal
in-process (the CLI verb's exit codes, MCP serving) are pinned in
``tests/test_run_store_schema_surfaces.py``, on the ring they live on.
"""

from __future__ import annotations

import hashlib
import os
import re
import shlex
import sqlite3
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import closing
from pathlib import Path
from typing import Any, Final, cast

import pytest

from codeclone.canonical import (
    RunStore,
    RunStoreError,
    StoreCompatibilityError,
    UnknownRunError,
)
from codeclone.canonical import errors as store_errors
from codeclone.canonical import store as store_module
from codeclone.core.canonical_snapshot import publish_run_snapshot
from codeclone.models import RUN_SNAPSHOT_PUBLICATION_FAILED, RunSnapshotPublication
from codeclone.utils.sqlite_store import open_sqlite_db
from tests._run_store_schema_evidence import (
    INDEX,
    JOURNAL_BYTES,
    byte_state,
    copy_generation_1,
    drop_the_index,
    empty_file,
    foreign_schema,
)
from tests.conftest import RunStoreCorpusRunner
from tests.test_canonical_roundtrip import fixture_model
from tests.test_run_store_producer_wiring import (  # noqa: F401
    _FULL_METRICS_ARGS,
    corpus,
)

_NS: Final = "ddl-authority"
_TARGET: Final = "worktree"
_MISSING: Final = (("index", INDEX),)
_REPO_ROOT: Final = Path(__file__).resolve().parents[1]
_ROLLBACK: Final = b"\x01\x01"


# -- instruments --------------------------------------------------------------


def _look(path: Path) -> sqlite3.Connection:
    """A read of a file that leaves nothing behind once closed.

    ``mode=ro`` would create ``-wal``/``-shm`` it cannot remove; a
    read-write connection that writes nothing removes them as the last one
    out, and ``query_only`` makes sure it writes nothing.
    """
    connection = sqlite3.connect(f"file:{path}?mode=rw", uri=True)
    connection.execute("PRAGMA query_only=ON")
    return connection


def _objects(path: Path) -> set[tuple[str, str]]:
    with closing(_look(path)) as connection:
        return {
            (str(kind), str(name))
            for kind, name in connection.execute(
                "SELECT type, name FROM sqlite_master "
                "WHERE type IN ('table', 'index') AND name NOT LIKE 'sqlite%'"
            )
        }


def _identity_rows(path: Path) -> tuple[object, ...]:
    """Everything the verb must leave alone: witness, epoch, every run."""
    with closing(_look(path)) as connection:
        return (
            connection.execute(
                "SELECT layer, revision, role FROM witness ORDER BY layer"
            ).fetchall(),
            connection.execute(
                "SELECT store_epoch, storage_schema_revision, contract_epoch "
                "FROM store_meta"
            ).fetchall(),
            connection.execute(
                "SELECT run_id, analysis_scope_digest, membership_digest, published "
                "FROM runs ORDER BY run_id"
            ).fetchall(),
            connection.execute("SELECT count(*) FROM run_members").fetchall(),
        )


def _publish(path: Path) -> str:
    with RunStore(path) as store:
        return store.write_full_run(
            fixture_model(), namespace=_NS, target=_TARGET, expected_generation=0
        ).run_id


def _store_without_the_index(path: Path) -> str:
    """A published store, then its index dropped; the run id it holds."""
    run_id = _publish(path)
    drop_the_index(path)
    assert (("index", INDEX)) not in _objects(path), "the population proves nothing"
    assert byte_state(path)["-wal"] is None, "a connection is still open on it"
    return run_id


def _to_rollback_journal(path: Path) -> None:
    with closing(sqlite3.connect(path)) as raw:
        assert raw.execute("PRAGMA journal_mode=DELETE").fetchone()[0] == "delete"
    assert Path(path).read_bytes()[JOURNAL_BYTES] == _ROLLBACK


def _command_for(path: Path) -> str:
    return str(store_errors.STORE_SCHEMA_MIGRATE_COMMAND).format(
        path=shlex.quote(str(path))
    )


def _spelled_command(refusal: StoreCompatibilityError) -> list[str]:
    """The command the refusal names, as argv -- taken from its words."""
    found = re.findall(r"`([^`]+)`", refusal.next_step)
    assert len(found) == 1, refusal.next_step
    return shlex.split(found[0])


def _run_spelled(argv: list[str]) -> tuple[int, str]:
    """Run a ``codeclone ...`` command line as a user runs it: the module
    entry point in a child process; its exit code and stdout."""
    assert argv[0] == "codeclone", argv
    environment = os.environ.copy()
    environment["PYTHONPATH"] = (
        str(_REPO_ROOT) + os.pathsep + environment.get("PYTHONPATH", "")
    )
    environment["NO_COLOR"] = "1"
    done = subprocess.run(
        [sys.executable, "-m", "codeclone.main", *argv[1:]],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )
    return done.returncode, done.stdout


@pytest.fixture
def owner_opens(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[Path]]:
    """The look before the connection owner passed, and the file changed
    after it: only the decision under the write lock is left to refuse.

    Yields every path the connection owner opened, so a test proves the
    owner was REACHED -- a look that still refused would leave the lock's
    decision unexercised and the pin green for the wrong reason.
    """
    monkeypatch.setattr(
        store_module,
        "_look_before_opening",
        lambda _path, *, create: None,
        raising=False,
    )
    opened: list[Path] = []

    def owner(path: Path, **kwargs: Any) -> sqlite3.Connection:
        opened.append(path)
        return open_sqlite_db(path, **kwargs)

    monkeypatch.setattr(store_module, "open_sqlite_db", owner)
    yield opened


# -- (i) a new store: DDL and witness in one transaction ----------------------


#: What each statement of a creation is, by its leading words.
_STATEMENT_KINDS: Final = (
    ("BEGIN IMMEDIATE", "begin"),
    ("COMMIT", "commit"),
    ("CREATE ", "create"),
    ("INSERT INTO WITNESS", "witness"),
    ("INSERT INTO STORE_META", "witness"),
)


def _statement_kind(statement: str) -> str:
    head = " ".join(statement.split()).upper()
    return next(
        (kind for prefix, kind in _STATEMENT_KINDS if head.startswith(prefix)),
        "other",
    )


def test_a_new_store_is_its_whole_schema_and_its_witness_committed_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Read off the statements the creation EXECUTED: every CREATE and both
    witness inserts sit inside one ``BEGIN IMMEDIATE`` .. ``COMMIT``, and
    nothing creates a schema object outside it."""
    executed: list[str] = []
    real_connect = sqlite3.connect

    def traced(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        connection = cast("sqlite3.Connection", real_connect(*args, **kwargs))
        connection.set_trace_callback(executed.append)
        return connection

    monkeypatch.setattr(sqlite3, "connect", traced)
    with RunStore(tmp_path / "runs.sqlite3") as store:
        fence = store._fence
    monkeypatch.undo()

    kinds = [_statement_kind(statement) for statement in executed]
    assert (kinds.count("begin"), kinds.count("commit")) == (1, 1), executed
    begin, commit = kinds.index("begin"), kinds.index("commit")
    outside = kinds[:begin] + kinds[commit:]
    inside = kinds[begin:commit]
    assert "create" not in outside, executed
    assert inside.count("witness") == len(store_module._WITNESS_LAYERS) + 1
    assert inside.count("create") == len(store_module._declared_schema_objects())
    assert fence[0] == 1
    assert _objects(tmp_path / "runs.sqlite3") == set(
        store_module._declared_schema_objects()
    )
    assert ("index", INDEX) in _objects(tmp_path / "runs.sqlite3")


def test_a_creation_that_dies_before_its_commit_leaves_no_schema_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Death between the DDL and the witness: nothing of the store is
    visible, and the next creator finds an empty file and makes the store."""
    path = tmp_path / "runs.sqlite3"

    def dies() -> str:
        raise RuntimeError("the creator died before its witness")

    monkeypatch.setattr(store_module, "_contract_epoch", dies)
    with pytest.raises(RuntimeError, match="died before its witness"):
        RunStore(path)
    monkeypatch.undo()
    assert path.exists()
    assert _objects(path) == set(), "a schema without a witness was committed"

    with RunStore(path) as store:
        assert store._fence[0] == 1
    assert ("table", "witness") in _objects(path)


# -- an accepted open of an existing store writes nothing ---------------------


@pytest.mark.parametrize("create", [False, True], ids=["reader", "publisher"])
def test_an_accepted_open_of_an_existing_store_writes_nothing(
    tmp_path: Path, create: bool
) -> None:
    """A read does not write, and neither does an open that decides nothing.

    Measured 2026-09-23: the connection owner's ``auto_vacuum`` pragma
    rewrote the header of an existing incremental store on EVERY open --
    change counter +1, readers included -- before a witness was read.  The
    mode can only be chosen before the first b-tree, so it is asked of a
    new file alone, and a store created that way still carries it.
    """
    path = tmp_path / "runs.sqlite3"
    run_id = _publish(path)
    before = byte_state(path)
    with RunStore(path, create=create) as store:
        assert store.project_run(run_id)
        mode = int(store._connection.execute("PRAGMA auto_vacuum").fetchone()[0])
    assert byte_state(path) == before
    assert mode == 2, "the store lost its incremental auto-vacuum"


# -- (ii) an existing store without the index ---------------------------------


@pytest.mark.parametrize("create", [False, True], ids=["reader", "publisher"])
def test_an_open_refuses_a_store_without_the_index_and_the_named_verb_completes_it(
    tmp_path: Path, create: bool
) -> None:
    path = tmp_path / "runs.sqlite3"
    run_id = _publish(path)
    with RunStore(path, create=False) as store:
        projected = store.project_run(run_id)
    drop_the_index(path)
    assert ("index", INDEX) not in _objects(path), "the population proves nothing"
    identity = _identity_rows(path)
    before = byte_state(path)

    with pytest.raises(StoreCompatibilityError) as caught:
        RunStore(path, create=create)
    assert byte_state(path) == before, "the refused open touched the file"

    refusal = caught.value
    assert type(refusal) is store_errors.StoreSchemaIncompleteError
    assert isinstance(refusal, store_errors.StoreSchemaIncompleteError)
    assert (refusal.missing, refusal.path, refusal.diverging) == (
        _MISSING,
        str(path),
        (),
    )
    assert f"`{_command_for(path)}`" in refusal.next_step
    assert refusal.next_step in str(refusal)
    assert f"index {INDEX}" in str(refusal)

    argv = _spelled_command(refusal)
    assert argv[:3] == ["codeclone", "run-store", "migrate"]
    code, out = _run_spelled(argv)
    assert (code, f"added index {INDEX}" in out) == (0, True), out

    assert ("index", INDEX) in _objects(path)
    assert _identity_rows(path) == identity, "the verb moved more than the schema"
    with RunStore(path, create=create) as store:
        assert store.project_run(run_id) == projected

    completed = byte_state(path)
    code, out = _run_spelled(argv)
    assert (code, "nothing to migrate" in out) == (0, True), out
    assert byte_state(path) == completed, "a complete store was written"


@pytest.mark.parametrize("population", ["without_index", "generation_1"])
def test_the_decision_under_the_write_lock_refuses_alone(
    tmp_path: Path, population: str, owner_opens: list[Path]
) -> None:
    """The look passed and the file changed: the owner has opened it, and the
    decision under the lock still refuses and leaves it as it was -- the
    refused handle closed, so no ``-wal``/``-shm`` outlives the refusal."""
    path = tmp_path / "runs.sqlite3"
    if population == "generation_1":
        copy_generation_1(path)
    else:
        _store_without_the_index(path)
    owner_opens.clear()
    before = byte_state(path)
    with pytest.raises(StoreCompatibilityError) as caught:
        RunStore(path, create=False)
    assert owner_opens == [path], "the owner never opened it: the look decided"
    assert byte_state(path) == before
    expected = (
        StoreCompatibilityError
        if population == "generation_1"
        else store_errors.StoreSchemaIncompleteError
    )
    assert type(caught.value) is expected


@pytest.mark.parametrize("population", ["without_index", "generation_1"])
def test_the_look_refuses_before_the_owner_can_change_the_journal_mode(
    tmp_path: Path, population: str
) -> None:
    """A rollback-journal file: the connection owner's first statement would
    turn it into WAL, a header write before any witness is read.  Only the
    look before the owner can refuse it untouched."""
    path = tmp_path / "runs.sqlite3"
    if population == "generation_1":
        copy_generation_1(path)
    else:
        _store_without_the_index(path)
    _to_rollback_journal(path)
    before = byte_state(path)
    assert before["journal"] == _ROLLBACK
    with pytest.raises(StoreCompatibilityError) as caught:
        RunStore(path, create=False)
    assert byte_state(path) == before
    expected = (
        StoreCompatibilityError
        if population == "generation_1"
        else store_errors.StoreSchemaIncompleteError
    )
    assert type(caught.value) is expected


# -- (iii) the verb refuses what is not a store of this generation ------------


_NOT_A_STORE: Final[dict[str, tuple[Callable[[Path], None], type[RunStoreError]]]] = {
    "generation_1": (copy_generation_1, StoreCompatibilityError),
    "foreign_schema": (foreign_schema, StoreCompatibilityError),
    "empty_file": (empty_file, UnknownRunError),
}


@pytest.mark.parametrize("population", sorted(_NOT_A_STORE))
def test_the_verb_refuses_what_is_not_this_generation_and_writes_nothing(
    tmp_path: Path, population: str
) -> None:
    path = tmp_path / "runs.sqlite3"
    build, refusal_type = _NOT_A_STORE[population]
    build(path)
    before = byte_state(path)
    with pytest.raises(refusal_type) as caught:
        store_module.migrate_store_schema(path)
    assert type(caught.value) is refusal_type
    assert byte_state(path) == before


def test_the_verb_refuses_an_absent_path_without_creating_it(
    tmp_path: Path,
) -> None:
    absent = tmp_path / "nowhere" / "runs.sqlite3"
    with pytest.raises(UnknownRunError) as caught:
        store_module.migrate_store_schema(absent)
    assert caught.value.reason == "run_store_absent"
    assert not absent.parent.exists()


def test_the_verb_refuses_a_generation_one_store_with_its_migration_path(
    tmp_path: Path,
) -> None:
    """The same words an open says: every diverging layer, both revisions."""
    path = tmp_path / "runs.sqlite3"
    copy_generation_1(path)
    with pytest.raises(StoreCompatibilityError) as caught:
        store_module.migrate_store_schema(path)
    assert type(caught.value) is StoreCompatibilityError
    assert caught.value.diverging == (
        ("canonical_model", "1", "3"),
        ("canonical_wire", "0", "2"),
        ("storage_schema", "1", "2"),
    )
    assert ("index", INDEX) not in _objects(path)


# -- an existing file that is no store: refused, never adopted ----------------


def test_a_file_with_a_schema_and_no_witness_is_refused_not_adopted(
    tmp_path: Path,
) -> None:
    """A witness is written only by the creation of a store; a file that
    already holds somebody's schema states no generation and is refused."""
    path = tmp_path / "runs.sqlite3"
    foreign_schema(path)
    before = byte_state(path)
    with pytest.raises(StoreCompatibilityError) as caught:
        RunStore(path)
    assert byte_state(path) == before
    assert _objects(path) == {("table", "notes")}
    declared = {layer for layer, _revision, _role in store_module._WITNESS_LAYERS}
    assert {layer for layer, _s, _d in caught.value.diverging} == declared
    assert all(stored is None for _l, stored, _d in caught.value.diverging)


def test_an_empty_file_is_a_new_store_to_a_creator_and_no_store_to_a_reader(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runs.sqlite3"
    path.write_bytes(b"")
    with pytest.raises(UnknownRunError) as caught:
        RunStore(path, create=False)
    assert caught.value.reason == "run_store_absent"
    assert byte_state(path) == {
        "main": hashlib.sha256(b"").hexdigest(),
        "-wal": None,
        "-shm": None,
        "journal": b"",
    }
    with RunStore(path) as store:
        assert store._fence[0] == 1
    assert _objects(path) == set(store_module._declared_schema_objects())


# -- (v) a publication into an incomplete store --------------------------------


def test_a_publication_into_a_store_without_the_index_is_refused_whole(
    corpus: Path,  # noqa: F811
    run_store_cli: RunStoreCorpusRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Through the real CLI waterfall: the publisher opens with
    ``create=True`` and meets the same refusal; the analysis finishes, the
    publication is ``failed`` with the refusal's own words, and the store is
    untouched -- no run row, no membership, not a byte."""
    store = corpus / "runs.sqlite3"
    run_store_cli(corpus, *_FULL_METRICS_ARGS, store=store)
    drop_the_index(store)
    identity = _identity_rows(store)
    assert identity[2], "the first run published nothing to protect"
    before = byte_state(store)

    publications: list[RunSnapshotPublication] = []

    def recording(**kwargs: Any) -> RunSnapshotPublication:
        publication = publish_run_snapshot(**kwargs)
        publications.append(publication)
        return publication

    monkeypatch.setattr("codeclone.core.reporting.publish_run_snapshot", recording)
    run_store_cli(corpus, *_FULL_METRICS_ARGS, store=store)

    assert len(publications) == 1
    publication = publications[0]
    assert publication.outcome == RUN_SNAPSHOT_PUBLICATION_FAILED
    reason = publication.reason
    assert reason.startswith("StoreSchemaIncompleteError: "), reason
    assert f"`{_command_for(store)}`" in reason
    assert byte_state(store) == before
    assert _identity_rows(store) == identity
