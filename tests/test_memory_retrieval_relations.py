# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path
from typing import cast

from codeclone.memory.enums import LinkRelation
from codeclone.memory.models import MemoryLink, generate_memory_id
from codeclone.memory.retrieval.service import get_relevant_memory
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore
from codeclone.report.meta import current_report_timestamp_utc

from .memory_fixtures import memory_store, seed_path_subject_record


def _link(
    store: SqliteEngineeringMemoryStore,
    project_id: str,
    *,
    src: str,
    dst: str,
    relation: LinkRelation,
) -> None:
    store.write_link(
        MemoryLink(
            id=generate_memory_id(prefix="link"),
            project_id=project_id,
            from_memory_id=src,
            to_memory_id=dst,
            relation=relation,
            created_by="test",
            created_at_utc=current_report_timestamp_utc(),
        )
    )
    store.commit()


def _records(result: dict[str, object]) -> list[dict[str, object]]:
    records = result["records"]
    assert isinstance(records, list)
    return [cast("dict[str, object]", record) for record in records]


def _hit(records: list[dict[str, object]], record_id: str) -> dict[str, object]:
    for record in records:
        if record["id"] == record_id:
            return record
    raise AssertionError(f"record not found: {record_id}")


def test_superseded_record_is_down_ranked_with_relation(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (_root, project, store, _db):
        a = seed_path_subject_record(
            store, project_id=project.id, path="pkg/a.py", statement="current approach"
        )
        b = seed_path_subject_record(
            store, project_id=project.id, path="pkg/b.py", statement="old approach"
        )
        _link(store, project.id, src=a.id, dst=b.id, relation="supersedes")

        records = _records(
            get_relevant_memory(
                store,
                project_id=project.id,
                scope_paths=("pkg/a.py", "pkg/b.py"),
                scope_resolved_from="explicit",
            )
        )
        a_hit = _hit(records, a.id)
        b_hit = _hit(records, b.id)

        assert a_hit["relations"] == {"supersedes": [b.id]}
        assert b_hit["relations"] == {"superseded_by": [a.id]}
        # The superseded record is bounded-down-ranked; the newer one is not.
        a_score = cast("float", a_hit["relevance_score"])
        b_score = cast("float", b_hit["relevance_score"])
        assert round(a_score - b_score, 4) == 0.5


def test_contradicted_records_surface_contradicted_by(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (_root, project, store, _db):
        a = seed_path_subject_record(
            store, project_id=project.id, path="pkg/a.py", statement="X holds"
        )
        b = seed_path_subject_record(
            store, project_id=project.id, path="pkg/b.py", statement="X does not hold"
        )
        _link(store, project.id, src=b.id, dst=a.id, relation="contradicts")

        records = _records(
            get_relevant_memory(
                store,
                project_id=project.id,
                scope_paths=("pkg/a.py", "pkg/b.py"),
                scope_resolved_from="explicit",
            )
        )
        # The conflict surfaces on both sides; neither returns silently.
        assert _hit(records, a.id)["relations"] == {"contradicted_by": [b.id]}
        assert _hit(records, b.id)["relations"] == {"contradicted_by": [a.id]}


def test_unlinked_record_has_no_relations(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (_root, project, store, _db):
        a = seed_path_subject_record(
            store, project_id=project.id, path="pkg/a.py", statement="standalone"
        )
        records = _records(
            get_relevant_memory(
                store,
                project_id=project.id,
                scope_paths=("pkg/a.py",),
                scope_resolved_from="explicit",
            )
        )
        assert "relations" not in _hit(records, a.id)
