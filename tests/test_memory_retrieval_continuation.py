# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path
from typing import cast

from codeclone.memory.experience.models import Experience
from codeclone.memory.models import MemoryRecord, MemorySubject, generate_memory_id
from codeclone.memory.retrieval import (
    get_memory_projection_page,
    get_relevant_memory,
    query_engineering_memory,
)
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore
from codeclone.report.meta import current_report_timestamp_utc

from .memory_fixtures import memory_store


def test_memory_retrieval_continuation_pages_records_exactly(
    tmp_path: Path,
) -> None:
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        _seed_scoped_records(store, project_id=project.id, count=4)
        first = get_relevant_memory(
            store,
            project_id=project.id,
            scope_paths=("pkg/service.py",),
            scope_resolved_from="explicit",
            max_records=2,
        )
        page_ref = _lane_page(first, "records")
        page = get_memory_projection_page(
            store,
            project_id=project.id,
            cursor=str(page_ref["cursor"]),
            page_size=1,
        )

    _assert_page_summary(page, lane="records", returned=1, complete=False)
    items = cast("list[dict[str, object]]", page["items"])
    assert items[0]["id"] == "mem-cont-02"
    next_ref = cast("dict[str, object]", page["next"])
    assert next_ref["offset"] == 3


def test_memory_retrieval_continuation_fails_closed_on_projection_change(
    tmp_path: Path,
) -> None:
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        _seed_scoped_records(store, project_id=project.id, count=3)
        first = get_relevant_memory(
            store,
            project_id=project.id,
            scope_paths=("pkg/service.py",),
            scope_resolved_from="explicit",
            max_records=1,
        )
        cursor = str(_lane_page(first, "records")["cursor"])
        _seed_scoped_record(store, project_id=project.id, record_id="mem-cont-99")
        page = get_memory_projection_page(
            store,
            project_id=project.id,
            cursor=cursor,
        )

    assert page["status"] == "snapshot_mismatch"
    assert page["reason"] == "memory_projection_changed"
    assert page["lane"] == "records"


def test_memory_retrieval_continuation_pages_experiences_and_exact_get(
    tmp_path: Path,
) -> None:
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        store.replace_experiences(
            project_id=project.id,
            experiences=[
                _experience(
                    project.id, experience_id=f"exp-cont-0{index}", support=10 - index
                )
                for index in range(3)
            ],
        )
        first = get_relevant_memory(
            store,
            project_id=project.id,
            scope_paths=("pkg/service.py",),
            scope_resolved_from="explicit",
            max_records=1,
        )
        cursor = str(_lane_page(first, "experiences")["cursor"])
        page = get_memory_projection_page(
            store,
            project_id=project.id,
            cursor=cursor,
            page_size=2,
        )
        fetched = query_engineering_memory(
            store,
            project_id=project.id,
            root_path="unused",
            backend="sqlite",
            db_path="unused",
            mode="experience_get",
            record_id="exp-cont-01",
        )

    assert page["status"] == "ok"
    assert page["response_complete"] is True
    items = cast("list[dict[str, object]]", page["items"])
    assert [item["id"] for item in items] == ["exp-cont-01", "exp-cont-02"]
    assert fetched["status"] == "ok"
    payload = cast("dict[str, object]", fetched["payload"])
    experience = cast("dict[str, object]", payload["experience"])
    assert experience["id"] == "exp-cont-01"
    assert experience["evidence_trajectory_ids"] == []


def _lane_page(payload: dict[str, object], lane: str) -> dict[str, object]:
    continuation = cast("dict[str, object]", payload["continuation"])
    lanes = cast("dict[str, object]", continuation["lanes"])
    lane_payload = cast("dict[str, object]", lanes[lane])
    return cast("dict[str, object]", lane_payload["page"])


def _assert_page_summary(
    page: dict[str, object],
    *,
    lane: str,
    returned: int,
    complete: bool,
) -> None:
    assert {
        "status": page["status"],
        "lane": page["lane"],
        "returned": page["returned"],
        "response_complete": page["response_complete"],
    } == {
        "status": "ok",
        "lane": lane,
        "returned": returned,
        "response_complete": complete,
    }


def _seed_scoped_records(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    count: int,
) -> None:
    for index in range(count):
        _seed_scoped_record(
            store,
            project_id=project_id,
            record_id=f"mem-cont-{index:02d}",
        )


def _seed_scoped_record(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    record_id: str,
) -> None:
    now = current_report_timestamp_utc()
    store.upsert_record(
        MemoryRecord(
            id=record_id,
            project_id=project_id,
            identity_key=f"continuation:{record_id}",
            type="contract_note",
            status="active",
            confidence="verified",
            origin="system",
            ingest_source="contract",
            statement=f"continuation record {record_id}",
            summary=None,
            payload=None,
            created_at_utc=now,
            updated_at_utc=now,
            last_verified_at_utc=now,
            expires_at_utc=None,
            created_by="test",
            verified_by="test",
            approved_by="test",
            approved_at_utc=now,
            report_digest=None,
            code_fingerprint=None,
            stale_reason=None,
            created_on_branch=None,
            created_at_commit=None,
            verified_on_branch=None,
            verified_at_commit=None,
        )
    )
    store.write_subject(
        MemorySubject(
            id=generate_memory_id(prefix="subj"),
            memory_id=record_id,
            subject_kind="path",
            subject_key="pkg/service.py",
            relation="about",
        )
    )


def _experience(project_id: str, *, experience_id: str, support: int) -> Experience:
    now = current_report_timestamp_utc()
    return Experience(
        id=experience_id,
        project_id=project_id,
        repo_root_digest="digest",
        subject_family="pkg",
        signal=f"verified_finish_{experience_id}",
        outcome_class="accepted:verified",
        support=support,
        quality_min=80,
        information_value=85,
        status="active",
        statement=f"experience {experience_id}",
        experience_digest=f"digest-{experience_id}",
        distillation_version="experience-v1",
        first_observed_at_utc=now,
        last_observed_at_utc=now,
        distilled_at_utc=now,
        updated_at_utc=now,
        facets=(),
        evidence=(),
    )
