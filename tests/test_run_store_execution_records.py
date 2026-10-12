# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The run store's execution registry (``canonical.executions``).

Finalization joins the snapshot, the record, the bridge edge and the end of
the publisher's lease in one fenced transaction; a process killed before its
commit leaves none of them, one killed after leaves all of them.  The registry
answers by the execution it names or by the newest execution of one report
under one root, proves every row against its own digest before handing its
bytes back, and states availability off the run row it reads in the same
snapshot -- so a record survives its run as the proof of its expiry, and the
absence of a record proves nothing.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import textwrap
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest

from codeclone.canonical import store as store_module
from codeclone.canonical.errors import (
    ExecutionRecordError,
    RunReportLinkError,
    StoreIntegrityError,
    StoreSchemaIncompleteError,
    UnknownRunError,
)
from codeclone.canonical.executions import (
    EXECUTION_AVAILABLE,
    EXECUTION_EXPIRED,
    EXECUTION_NOT_PUBLISHED,
    ExecutionRecord,
    RegisteredExecution,
    RetentionWindow,
)
from codeclone.canonical.store import (
    RunStore,
    collect_garbage,
    finalize_execution,
    link_run_report,
    linked_run,
    migrate_store_schema,
    registered_execution,
    registered_report_execution,
)
from tests._run_store_execution_fixtures import (
    CONTRACT,
    ROOT,
    model_for,
    publish,
    record_for,
    register,
    report_of,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _rows(
    path: Path, sql: str, params: tuple[object, ...] = ()
) -> list[tuple[object, ...]]:
    with closing(sqlite3.connect(path)) as raw:
        return list(raw.execute(sql, params))


def _leases(path: Path) -> list[str]:
    return [str(row[0]) for row in _rows(path, "SELECT lease_id FROM run_leases")]


# -- the schema: declared like an index, completed by the verb ---------------


def test_a_new_store_holds_the_registry_and_its_immutability_trigger(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runs.sqlite3"
    RunStore(path).close()
    objects = {
        (str(kind), str(name))
        for kind, name in _rows(
            path,
            "SELECT type, name FROM sqlite_master WHERE name LIKE 'run_executions%'",
        )
    }
    assert objects == {
        ("table", "run_executions"),
        ("trigger", "run_executions_immutable"),
    }


def test_a_store_written_before_the_registry_is_refused_and_completed_by_the_verb(
    tmp_path: Path,
) -> None:
    """The schema audit's fifth question, kept: a store of this generation
    without the registry is refused untouched and completed by the verb,
    which keeps the witness, the epoch and every run."""
    path = tmp_path / "runs.sqlite3"
    with RunStore(path) as store:
        receipt = publish(store, "a")
    with closing(sqlite3.connect(path)) as raw:
        raw.execute("DROP TRIGGER run_executions_immutable")
        raw.execute("DROP TABLE run_executions")
        raw.commit()
    keep = (
        "SELECT * FROM store_meta "
        "UNION ALL SELECT layer, revision, role, NULL FROM witness"
    )
    before = (_rows(path, keep), _rows(path, "SELECT run_id FROM runs"))
    with pytest.raises(StoreSchemaIncompleteError) as refused:
        RunStore(path, create=False)
    assert refused.value.missing == (
        ("table", "run_executions"),
        ("trigger", "run_executions_immutable"),
    )
    assert migrate_store_schema(path) == (
        ("table", "run_executions"),
        ("trigger", "run_executions_immutable"),
    )
    assert (_rows(path, keep), _rows(path, "SELECT run_id FROM runs")) == before
    with RunStore(path, create=False) as store:
        assert store.head(namespace="registry-ns", target="registry-target") is not None
        assert receipt.run_id in {
            str(r[0]) for r in _rows(path, "SELECT run_id FROM runs")
        }


def test_the_registry_names_its_run_by_content_address_and_never_by_foreign_key(
    tmp_path: Path,
) -> None:
    """A build that predates the registry opens this store (an open refuses
    only what a store LACKS) and sweeps it knowing nothing of the table.
    Measured by the schema audit: a row holding a foreign key into ``runs``
    turns that sweep into ``FOREIGN KEY constraint failed``; a row by content
    address lets it collect the run and keep the record -- which the
    registry then answers as expired, with proof."""
    path = tmp_path / "runs.sqlite3"
    with RunStore(path) as store:
        old = register(store, "a")
        register(store, "b")
        # A registry-blind sweep: no window, no history -- the run of "a" is
        # neither head nor leased nor retained.
        report = collect_garbage(store, retain_history=0)
        assert report.collected == (("unreachable", 1),)
        answered = registered_report_execution(store, root=ROOT, run_id=report_of("a"))
    assert _rows(path, "PRAGMA foreign_key_list(run_executions)") == []
    assert answered is not None
    assert answered.availability == EXECUTION_EXPIRED
    assert answered.record == old.registered.record


# -- finalization: one atom ----------------------------------------------------


def test_finalization_writes_the_record_the_edge_and_ends_the_publisher_lease(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runs.sqlite3"
    with RunStore(path) as store:
        receipt = publish(store, "a", lease=("publication:test:a", 3600))
        other = publish(store, "b", lease=("publication:test:b", 3600))
        record = record_for(receipt, execution="exec-a", report=report_of("a"))
        registered = finalize_execution(
            store,
            record,
            expected_scope_digest=receipt.analysis_scope_digest,
            publisher_lease="publication:test:a",
        )
        assert registered.availability == EXECUTION_AVAILABLE
        assert registered_execution(store, "exec-a") == registered
        edge = linked_run(store, report_run_identity=report_of("a"))
    assert edge is not None and edge.run_id == receipt.run_id
    # Only the named lease, and only on the finalized run, ended.
    assert _leases(path) == ["publication:test:b"]
    assert other.run_id != receipt.run_id


def test_a_finalization_naming_another_runs_lease_ends_nothing_of_it(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runs.sqlite3"
    with RunStore(path) as store:
        receipt = publish(store, "a", lease=("publication:test:a", 3600))
        publish(store, "b", lease=("publication:test:b", 3600))
        finalize_execution(
            store,
            record_for(receipt, execution="exec-a", report=report_of("a")),
            expected_scope_digest=receipt.analysis_scope_digest,
            publisher_lease="publication:test:b",
        )
    assert sorted(_leases(path)) == ["publication:test:a", "publication:test:b"]


@pytest.mark.parametrize("cause", ["not_published", "scope", "twice"])
def test_a_refused_finalization_writes_nothing(tmp_path: Path, cause: str) -> None:
    path = tmp_path / "runs.sqlite3"
    with RunStore(path) as store:
        receipt = publish(store, "a", lease=("publication:test:a", 3600))
        record = record_for(receipt, execution="exec-a", report=report_of("a"))
        scope = receipt.analysis_scope_digest
        expected: type[Exception]
        if cause == "twice":
            finalize_execution(store, record, expected_scope_digest=scope)
            record = record_for(receipt, execution="exec-a", report=report_of("b"))
            expected = ExecutionRecordError
        elif cause == "scope":
            scope = "0" * 64
            expected = RunReportLinkError
        else:
            record = record_for(
                replace(receipt, run_id="f" * 64),
                execution="exec-a",
                report=report_of("a"),
            )
            expected = UnknownRunError
        before = (
            _rows(path, "SELECT execution_event_id FROM run_executions"),
            _rows(path, "SELECT report_run_identity FROM run_report_links"),
            _leases(path),
        )
        with pytest.raises(expected):
            finalize_execution(
                store,
                record,
                expected_scope_digest=scope,
                publisher_lease="publication:test:a",
            )
    after = (
        _rows(path, "SELECT execution_event_id FROM run_executions"),
        _rows(path, "SELECT report_run_identity FROM run_report_links"),
        _leases(path),
    )
    assert after == before


def test_a_finalization_that_dies_before_its_commit_leaves_nothing_visible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "runs.sqlite3"

    def die(_store: RunStore) -> None:
        raise RuntimeError("killed at the finalization seam")

    with RunStore(path) as store:
        receipt = publish(store, "a", lease=("publication:test:a", 3600))
        monkeypatch.setattr(store_module, "_before_finalize_commit", die)
        with pytest.raises(RuntimeError, match="finalization seam"):
            finalize_execution(
                store,
                record_for(receipt, execution="exec-a", report=report_of("a")),
                expected_scope_digest=receipt.analysis_scope_digest,
                publisher_lease="publication:test:a",
            )
        assert registered_execution(store, "exec-a") is None
    assert _rows(path, "SELECT * FROM run_executions") == []
    assert _rows(path, "SELECT * FROM run_report_links") == []
    assert _leases(path) == ["publication:test:a"]


_CHILD = textwrap.dedent(
    """
    import os, sys
    import codeclone.canonical.store as store_module
    from codeclone.canonical.store import RunStore, finalize_execution
    from tests._run_store_execution_fixtures import publish, record_for, report_of

    path, when = sys.argv[1], sys.argv[2]
    store = RunStore(path)
    receipt = publish(store, "a", lease=("publication:test:a", 3600))
    if when == "before_commit":
        store_module._before_finalize_commit = lambda store: os._exit(17)
    finalize_execution(
        store,
        record_for(receipt, execution="exec-a", report=report_of("a")),
        expected_scope_digest=receipt.analysis_scope_digest,
        publisher_lease="publication:test:a",
    )
    os._exit(23)
    """
)


@pytest.mark.parametrize(
    ("when", "code", "visible"),
    [("before_commit", 17, False), ("after_commit", 23, True)],
)
def test_a_process_killed_around_the_finalization_commit_leaves_one_side_whole(
    tmp_path: Path, when: str, code: int, visible: bool
) -> None:
    """A real process, killed with ``os._exit`` -- no ``finally``, no
    rollback of its own: before the commit nothing of the finalization is
    visible and the publisher's lease still holds the run; after it all of
    it is, and the lease is gone."""
    path = tmp_path / "runs.sqlite3"
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("CODECLONE_")
    }
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-B", "-c", _CHILD, str(path), when],
        cwd=_REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == code, result.stderr
    published = _rows(path, "SELECT run_id FROM runs WHERE published = 1")
    assert len(published) == 1
    records = _rows(path, "SELECT execution_event_id FROM run_executions")
    edges = _rows(path, "SELECT report_run_identity FROM run_report_links")
    assert (records != [], edges != [], _leases(path) == []) == (
        visible,
        visible,
        visible,
    )


def test_a_finalized_record_is_immutable_inside_sqlite(tmp_path: Path) -> None:
    path = tmp_path / "runs.sqlite3"
    with RunStore(path) as store:
        register(store, "a")
    with (
        closing(sqlite3.connect(path)) as raw,
        pytest.raises(sqlite3.IntegrityError, match="immutable once finalized"),
    ):
        raw.execute("UPDATE run_executions SET finalized_at = finalized_at + 1")
    with RunStore(path, create=False) as store:
        answered = registered_execution(store, "exec-a")
    assert answered is not None and answered.availability == EXECUTION_AVAILABLE


# -- reads: proven bytes, availability off the run row ------------------------


@pytest.mark.parametrize("damage", ["overlay_bytes", "overlay_as_text", "identity"])
def test_a_record_that_does_not_prove_against_its_digest_is_an_integrity_refusal(
    tmp_path: Path, damage: str
) -> None:
    path = tmp_path / "runs.sqlite3"
    with RunStore(path) as store:
        register(store, "a")
    statement = {
        "overlay_bytes": "UPDATE run_executions SET overlay = x'00'",
        "overlay_as_text": "UPDATE run_executions SET overlay = 'overlay'",
        "identity": "UPDATE run_executions SET root = '/elsewhere'",
    }[damage]
    with closing(sqlite3.connect(path)) as raw:
        raw.execute("DROP TRIGGER run_executions_immutable")
        if damage == "overlay_as_text":
            # The CHECK holds the storage class; the damage is a file
            # written around it, so the column's check is dropped with it.
            raw.execute("PRAGMA ignore_check_constraints = ON")
        raw.execute(statement)
        # Put the guard back so the store is complete again: the damage is
        # the bytes, and only the bytes.
        raw.execute(store_module._TRIGGERS[0])
        raw.commit()
    with RunStore(path, create=False) as store, pytest.raises(StoreIntegrityError):
        registered_execution(store, "exec-a")


def test_two_edges_for_one_report_resolve_through_the_newest_execution(
    tmp_path: Path,
) -> None:
    """The blank-lines population of the run-restoration audit: one report
    identity over two store runs.  The bridge refuses to choose; the
    registry names the run of the newest execution of that report."""
    report = report_of("same-report")
    with RunStore(tmp_path / "runs.sqlite3") as store:
        first = register(store, "a", execution="exec-1", report=report)
        second = register(store, "b", execution="exec-2", report=report)
        with pytest.raises(RunReportLinkError, match="cannot choose"):
            linked_run(store, report_run_identity=report)
        newest = registered_report_execution(store, root=ROOT, run_id=report)
        by_prefix = registered_report_execution(store, root=ROOT, run_id=report[:8])
        named = registered_execution(store, "exec-1")
    assert newest is not None and by_prefix == newest
    assert newest.record.store_run_id == second.receipt.run_id
    assert named is not None
    assert named.record.store_run_id == first.receipt.run_id


def test_a_prefix_naming_two_reports_is_refused_never_resolved_to_the_first(
    tmp_path: Path,
) -> None:
    left = "ab" + "0" * 62
    right = "ab" + "1" * 62
    with RunStore(tmp_path / "runs.sqlite3") as store:
        register(store, "a", execution="exec-a", report=left)
        register(store, "b", execution="exec-b", report=right)
        with pytest.raises(ExecutionRecordError, match="ambiguous"):
            registered_report_execution(store, root=ROOT, run_id="ab")
        unique = registered_report_execution(store, root=ROOT, run_id="ab1")
        not_hex = registered_report_execution(store, root=ROOT, run_id="ab%")
    assert unique is not None and unique.record.execution_event_id == "exec-b"
    assert not_hex is None


def test_a_report_is_found_only_under_the_root_its_execution_ran_under(
    tmp_path: Path,
) -> None:
    with RunStore(tmp_path / "runs.sqlite3") as store:
        register(store, "a", root="/checkout/one")
        here = registered_report_execution(
            store, root="/checkout/one", run_id=report_of("a")
        )
        elsewhere = registered_report_execution(
            store, root="/checkout/two", run_id=report_of("a")
        )
    assert here is not None
    assert elsewhere is None


def test_expired_needs_a_record_and_never_was_answers_nothing(
    tmp_path: Path,
) -> None:
    """``expired`` is stated only of a run the registry has a record of; a
    run it never recorded is ``None`` -- no proof that it ever existed."""
    with RunStore(tmp_path / "runs.sqlite3") as store:
        register(store, "a")
        register(store, "b")
        collect_garbage(store, retain_history=0)
        expired = registered_report_execution(store, root=ROOT, run_id=report_of("a"))
        never = registered_report_execution(store, root=ROOT, run_id=report_of("never"))
        never_by_id = registered_execution(store, "exec-never")
    assert expired is not None and expired.availability == EXECUTION_EXPIRED
    assert never is None
    assert never_by_id is None


def test_a_record_whose_run_row_is_not_published_is_not_available(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runs.sqlite3"
    with RunStore(path) as store:
        register(store, "a")
        register(store, "b")
    with closing(sqlite3.connect(path)) as raw:
        raw.execute(
            "UPDATE runs SET published = 0 WHERE run_id = ?",
            (
                _rows(
                    path,
                    "SELECT store_run_id FROM run_executions "
                    "WHERE execution_event_id = 'exec-a'",
                )[0][0],
            ),
        )
        raw.commit()
    with RunStore(path, create=False) as store:
        answered = registered_execution(store, "exec-a")
    assert answered is not None
    assert answered.availability == EXECUTION_NOT_PUBLISHED


# -- the value types ------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    [
        "execution_event_id",
        "root",
        "report_run_identity",
        "store_run_id",
        "record_contract",
    ],
)
def test_an_execution_record_names_every_identity_it_carries(field: str) -> None:
    values: dict[str, object] = {
        "execution_event_id": "e",
        "root": "/r",
        "report_run_identity": "a" * 64,
        "store_run_id": "b" * 64,
        "record_contract": CONTRACT,
        "overlay": b"x",
    }
    values[field] = ""
    with pytest.raises(ExecutionRecordError, match=field):
        ExecutionRecord(**values)  # type: ignore[arg-type]


def test_an_execution_overlay_is_bytes_and_an_availability_is_named() -> None:
    record = ExecutionRecord(
        execution_event_id="e",
        root="/r",
        report_run_identity="a" * 64,
        store_run_id="b" * 64,
        record_contract=CONTRACT,
        overlay=b"x",
    )
    with pytest.raises(ExecutionRecordError, match="bytes"):
        ExecutionRecord(
            execution_event_id="e",
            root="/r",
            report_run_identity="a" * 64,
            store_run_id="b" * 64,
            record_contract=CONTRACT,
            overlay="x",  # type: ignore[arg-type]
        )
    with pytest.raises(ExecutionRecordError, match="availability"):
        RegisteredExecution(record=record, finalized_at=0, availability="served")


@pytest.mark.parametrize(
    "field", ["max_runs", "max_age_seconds", "max_execution_records"]
)
@pytest.mark.parametrize("value", [0, -1, True])
def test_a_retention_window_is_three_positive_counts(field: str, value: object) -> None:
    values: dict[str, object] = {
        "max_runs": 4,
        "max_age_seconds": 60,
        "max_execution_records": 8,
    }
    values[field] = value
    with pytest.raises(ExecutionRecordError, match=field):
        RetentionWindow(**values)  # type: ignore[arg-type]


def test_model_for_gives_each_label_its_own_run(tmp_path: Path) -> None:
    """The fixtures' own control: two labels, two runs; one label twice,
    one run."""
    with RunStore(tmp_path / "runs.sqlite3") as store:
        a = publish(store, "a")
        b = publish(store, "b")
        again = publish(store, "a")
    assert a.run_id != b.run_id
    assert again.run_id == a.run_id
    assert model_for("a") == model_for("a")


def test_link_run_report_still_states_an_edge_without_a_record(tmp_path: Path) -> None:
    """The bridge write a surface without executions (the CLI) uses is the
    same edge, written alone: no record appears for it."""
    path = tmp_path / "runs.sqlite3"
    with RunStore(path) as store:
        receipt = publish(store, "a")
        link_run_report(
            store,
            run_id=receipt.run_id,
            report_run_identity=report_of("a"),
            expected_scope_digest=receipt.analysis_scope_digest,
        )
        assert (
            registered_report_execution(store, root=ROOT, run_id=report_of("a")) is None
        )
    assert len(_rows(path, "SELECT * FROM run_report_links")) == 1
