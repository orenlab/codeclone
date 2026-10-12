# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The registry is read without a write lock and without a write.

A process restoring a run asks the registry while publishers and sweeps of
other processes hold the store's write lock; its question may neither wait
for them nor change a byte of the file.  The positive control is the
registry's own write on the same handle under the same held lock: refused at
once, typed.  And a store without the registry is refused by a reader as it
stands, never completed by it.
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from pathlib import Path

import pytest

from codeclone.canonical.errors import StoreSchemaIncompleteError, StoreUnavailableError
from codeclone.canonical.store import (
    RunStore,
    finalize_execution,
    registered_execution,
    registered_report_execution,
)
from tests._run_store_execution_fixtures import (
    ROOT,
    publish,
    record_for,
    register,
    report_of,
)
from tests.test_run_store_contention import (
    _file_state,
    _write_lock_held_by_another_process,
)


def test_the_registry_answers_while_another_process_holds_the_write_lock(
    tmp_path: Path,
) -> None:
    db = tmp_path / "runs.sqlite3"
    with RunStore(db) as store:
        register(store, "a")
        pending = publish(store, "b")
    with _write_lock_held_by_another_process(db):
        before = _file_state(db)
        started = time.perf_counter()
        with RunStore(db, create=False) as reader:
            by_id = registered_execution(reader, "exec-a")
            by_report = registered_report_execution(
                reader, root=ROOT, run_id=report_of("a")[:8]
            )
            elapsed = time.perf_counter() - started
            reader._connection.execute("PRAGMA busy_timeout = 0")
            with pytest.raises(StoreUnavailableError):
                finalize_execution(
                    reader,
                    record_for(pending, execution="exec-b", report=report_of("b")),
                    expected_scope_digest=pending.analysis_scope_digest,
                )
        after = _file_state(db)
    assert by_id is not None and by_report == by_id
    assert elapsed < 1.0, f"the registry read waited {elapsed:.2f}s for the writer"
    assert after == before, "a registry read wrote to the store"


def test_a_reader_refuses_a_store_without_the_registry_and_leaves_it_as_it_was(
    tmp_path: Path,
) -> None:
    db = tmp_path / "runs.sqlite3"
    with RunStore(db) as store:
        publish(store, "a")
    with closing(sqlite3.connect(db)) as raw:
        raw.execute("DROP TRIGGER run_executions_immutable")
        raw.execute("DROP TABLE run_executions")
        raw.commit()
    before = _file_state(db)
    with pytest.raises(StoreSchemaIncompleteError):
        RunStore(db, create=False)
    assert _file_state(db) == before
