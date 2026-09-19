# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""``mode="status"`` carries the store state the status report decided.

``build_memory_status_report`` names one of four mutually exclusive states --
``absent`` / ``unrecognized`` / ``incompatible`` / ``ready`` -- and the CLI
(``memory status``, ``setup status``) prints it.  The MCP status payload used
to project every other field of that report and drop the discriminator, so an
``incompatible`` store and a file that is not a store both came back as
``db_exists: true`` with zero records: indistinguishable from an empty
``ready`` store.  The payload now carries ``state`` read off the same report
it already projects -- one producer, no second classification -- and
``db_exists`` stays the fact the report derives from ``state``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from codeclone.memory.retrieval import service as retrieval_service
from codeclone.memory.retrieval.service import query_engineering_memory
from codeclone.memory.schema import open_memory_db
from codeclone.memory.status_report import (
    MemoryStatusReport,
    MemoryStoreState,
    build_memory_status_report,
)
from tests.memory_fixtures import (
    memory_project_db_paths,
    memory_store,
    root_with_foreign_sqlite_at_memory_store_path,
    root_with_not_a_database_at_memory_store_path,
    root_with_old_engineering_memory_store,
)

#: The closed key set of the ``mode="status"`` payload.  ``state`` sits next
#: to the ``db_exists`` it is the source of; every other key is the projection
#: the payload always carried.
_STATUS_PAYLOAD_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "project_id",
        "project_root",
        "backend",
        "db_path",
        "state",
        "db_exists",
        "record_count",
        "records_by_type",
        "records_by_status",
        "last_analysis_fingerprint",
        "last_init_run_id",
    }
)


# ── the five store shapes, one per state (two for ``unrecognized``) ─────────


def _root_with_no_store(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir(exist_ok=True)
    _project, db_path = memory_project_db_paths(root)
    assert not db_path.exists()
    return root


def _root_with_current_store(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir(exist_ok=True)
    _project, db_path = memory_project_db_paths(root)
    open_memory_db(db_path).close()
    return root


def _root_with_old_store(tmp_path: Path) -> Path:
    return root_with_old_engineering_memory_store(tmp_path, version="1.7")


_STORE_SHAPES: tuple[tuple[str, Callable[[Path], Path], MemoryStoreState], ...] = (
    ("absent", _root_with_no_store, "absent"),
    ("foreign-sqlite", root_with_foreign_sqlite_at_memory_store_path, "unrecognized"),
    ("not-a-database", root_with_not_a_database_at_memory_store_path, "unrecognized"),
    ("store-1.7", _root_with_old_store, "incompatible"),
    ("store-current", _root_with_current_store, "ready"),
)


def _status_payload(root: Path, db_path: Path) -> dict[str, object]:
    """The payload straight from the producer every status transport shares."""
    result = retrieval_service._handle_status_mode(
        mode="status",
        root_path=root,
        db_path=db_path,
        backend="sqlite",
    )
    payload = result["payload"]
    assert isinstance(payload, dict)
    return payload


# ── the payload carries the report's state, never its own ───────────────────


@pytest.mark.parametrize(
    ("make_root", "expected_state"),
    [(make_root, state) for _name, make_root, state in _STORE_SHAPES],
    ids=[name for name, _make_root, _state in _STORE_SHAPES],
)
def test_status_payload_carries_the_state_the_report_decided(
    tmp_path: Path,
    make_root: Callable[[Path], Path],
    expected_state: MemoryStoreState,
) -> None:
    root = make_root(tmp_path)
    _project, db_path = memory_project_db_paths(root)
    report = build_memory_status_report(
        root_path=root,
        db_path=db_path,
        backend="sqlite",
    )
    # Positive control on the fixture: the producer really decides this state,
    # so an agreeing payload below agrees about something.
    assert report.state == expected_state

    payload = _status_payload(root, db_path)

    assert payload["state"] == expected_state
    assert payload["state"] == report.state
    assert payload["db_exists"] is report.db_exists
    assert payload["db_exists"] is (expected_state != "absent")


def test_status_payload_key_set_is_closed(tmp_path: Path) -> None:
    """One key added, none renamed, none dropped.

    The exact set, not a subset: a consumer that learned ``state`` from this
    payload must not lose it to a later projection rewrite, and the keys that
    predate it must not drift out under the same rewrite.
    """
    root = _root_with_current_store(tmp_path)
    _project, db_path = memory_project_db_paths(root)

    payload = _status_payload(root, db_path)

    assert set(payload) == _STATUS_PAYLOAD_KEYS


def test_public_status_query_carries_the_state(tmp_path: Path) -> None:
    """The public entry point hands out the same payload, ``state`` included."""
    with memory_store(tmp_path) as (root, project, store, db_path):
        status = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="status",
        )

    payload = status["payload"]
    assert isinstance(payload, dict)
    assert payload["state"] == "ready"
    assert payload["db_exists"] is True


def test_db_exists_in_the_payload_is_the_report_derivation_not_a_disk_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``db_exists`` is read off the report, where it is derived from ``state``.

    On every real store shape above a fresh ``db_path.exists()`` happens to
    agree with ``state != "absent"``, so those fixtures cannot tell the
    derivation from a second computation.  This can: a report that says
    ``incompatible`` about a path with no file behind it.  The report is not
    constructible with the two facts disagreeing, and the payload must not
    reintroduce the disagreement by probing the disk on its own.
    """
    missing = tmp_path / "repo" / ".codeclone" / "memory" / "never-created.sqlite3"
    report = MemoryStatusReport(
        db_path=missing,
        schema_version="1.7",
        project_id="proj-test",
        project_root=str(tmp_path / "repo"),
        backend="sqlite",
        git_available=False,
        git_branch=None,
        git_head=None,
        last_analysis_fingerprint=None,
        last_init_run_id=None,
        record_count=0,
        records_by_type={},
        records_by_status={},
        state="incompatible",
    )
    assert report.db_exists is True
    monkeypatch.setattr(
        retrieval_service,
        "build_memory_status_report",
        lambda **_kwargs: report,
    )

    payload = _status_payload(tmp_path / "repo", missing)

    assert payload["state"] == "incompatible"
    assert payload["db_exists"] is True
    assert not missing.exists()
