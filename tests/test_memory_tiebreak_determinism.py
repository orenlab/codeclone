# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Memory records that no score separates are ordered by content, not by row id.

A record's row id is ``generate_memory_id()`` -- a random ``uuid4``. Two stores
built from the same input (two MCP processes bootstrapping one root) hold the
same records under different ids, so an order decided by the id differs between
them. Each test here builds the SAME records twice and hands out the ids in
opposite orders; the served order must not move.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest

from codeclone.memory.enums import MemoryEpistemicRung
from codeclone.memory.models import MemoryProject, MemorySubject
from codeclone.memory.retrieval import get_relevant_memory
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore
from tests.memory_fixtures import make_module_record, memory_store

#: One timestamp for every record: the stores order by recency first, so a tie
#: only reaches the tie-break when the records were written in the same second.
_WRITTEN_AT = "2026-01-01T00:00:00Z"
_TIED = 8


def _module(index: int) -> str:
    return f"pkg.m{index}"


def _row_id(rank: int) -> str:
    return f"mem-{rank:032x}"


def _seed(
    store: SqliteEngineeringMemoryStore,
    project: MemoryProject,
    *,
    module: str,
    row_id: str,
    epistemic_rung: MemoryEpistemicRung = "supported",
) -> None:
    record = replace(
        make_module_record(project.id, module),
        id=row_id,
        epistemic_rung=epistemic_rung,
        statement=f"{module} is an analyzed Python module in project inventory.",
        created_at_utc=_WRITTEN_AT,
        updated_at_utc=_WRITTEN_AT,
        last_verified_at_utc=_WRITTEN_AT,
    )
    store.upsert_record(record)
    store.write_subject(
        MemorySubject(
            id=f"subj-{row_id}",
            memory_id=row_id,
            subject_kind="path",
            subject_key=module.replace(".", "/") + ".py",
            relation="about",
        )
    )


@contextmanager
def _tied_store(
    tmp_path: Path, *, ids_descending: bool
) -> Iterator[tuple[MemoryProject, SqliteEngineeringMemoryStore]]:
    """Eight equal records; row ids ascend with the module name or against it."""

    tmp_path.mkdir()
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        for index in range(_TIED):
            rank = _TIED - 1 - index if ids_descending else index
            _seed(store, project, module=_module(index), row_id=_row_id(rank))
        store.rebuild_project_fts(project.id)
        yield project, store


def _scoped_order(tmp_path: Path, *, ids_descending: bool) -> list[str]:
    with _tied_store(tmp_path, ids_descending=ids_descending) as (project, store):
        result = get_relevant_memory(
            store,
            project_id=project.id,
            scope_paths=[f"pkg/m{index}.py" for index in range(_TIED)],
            scope_resolved_from="scope",
            max_records=_TIED,
        )
    records = result["records"]
    assert isinstance(records, list)
    scores = {row["relevance_score"] for row in records}
    # Probe validity: every record carries the same score, so the order below
    # is decided by the tie-break and nothing else.
    assert len(records) == _TIED and len(scores) == 1, (len(records), scores)
    return [str(row["statement"]).split(" ", 1)[0] for row in records]


def test_scoped_ties_are_ordered_by_identity_not_by_row_id(tmp_path: Path) -> None:
    expected = [_module(index) for index in range(_TIED)]

    assert _scoped_order(tmp_path / "ascending", ids_descending=False) == expected
    assert _scoped_order(tmp_path / "descending", ids_descending=True) == expected


def test_score_still_decides_before_the_tiebreak(tmp_path: Path) -> None:
    """The tie-break acts on ties only: a higher score leads whatever its key."""

    with memory_store(tmp_path) as (_root, project, store, _db_path):
        # Lower identity key AND lower row id, lower score.
        _seed(store, project, module="pkg.aa", row_id=_row_id(0))
        # Higher identity key AND higher row id, higher score.
        _seed(
            store,
            project,
            module="pkg.zz",
            row_id=_row_id(1),
            epistemic_rung="verified",
        )
        result = get_relevant_memory(
            store,
            project_id=project.id,
            scope_paths=["pkg/aa.py", "pkg/zz.py"],
            scope_resolved_from="scope",
        )
    records = result["records"]
    assert isinstance(records, list)
    order = [str(row["statement"]).split(" ", 1)[0] for row in records]
    scores = [row["relevance_score"] for row in records]
    assert order == ["pkg.zz", "pkg.aa"], (order, scores)


def _search_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    ids_descending: bool,
    fts: bool,
) -> list[str]:
    with _tied_store(tmp_path, ids_descending=ids_descending) as (project, store):
        monkeypatch.setattr(store, "_fts_available", lambda: fts)
        rows = store.search_records(
            project_id=project.id,
            statement_query="analyzed module",
            match_mode="all",
        )
    return [row.statement.split(" ", 1)[0] for row in rows]


@pytest.mark.parametrize("fts", [True, False], ids=["fts", "like"])
def test_search_ties_are_ordered_by_identity_not_by_row_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fts: bool
) -> None:
    expected = [_module(index) for index in range(_TIED)]

    ascending = _search_order(
        tmp_path / "ascending", monkeypatch, ids_descending=False, fts=fts
    )
    descending = _search_order(
        tmp_path / "descending", monkeypatch, ids_descending=True, fts=fts
    )

    assert ascending == expected
    assert descending == expected
