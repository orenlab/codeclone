# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Two honesty pins on the Engineering Memory wire.

1. A record projection states when the fact was created and when it last
   changed, in every shape a record appears in. Both columns are ``NOT NULL``
   in the store and were reaching no response at all.
2. A response whose ``detail_level`` differs from the requested one names the
   level it returned *and* why, with an executable next step.

Every assertion here asserts the population it compares first: a check that
compares an empty list of records passes in silence, and that failure mode has
been paid for twice in this repository.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from codeclone.memory.enums import MemoryStatus, SubjectKind
from codeclone.memory.exceptions import MemoryContractError
from codeclone.memory.identity import make_identity_key
from codeclone.memory.models import MemoryRecord, MemorySubject, generate_memory_id
from codeclone.memory.retrieval import query_engineering_memory
from codeclone.memory.retrieval.service import get_relevant_memory
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore

from .memory_fixtures import memory_store

#: Distinct on purpose. A projection that carries ``created_at_utc`` under the
#: ``updated_at_utc`` name is a different defect from one that carries neither,
#: and only distinct values can tell them apart.
BORN_AT = "2026-06-04T15:21:46Z"
CHANGED_AT = "2026-08-30T09:12:03Z"
VERIFIED_AT = "2026-09-01T22:04:10Z"
APPROVED_AT = "2026-08-31T07:45:00Z"
BORN_ON_BRANCH = "feat/2.1-alpha"
BORN_AT_COMMIT = "004cea4c442f9bd8f7ef919cbe9fa9ec2900d5f1"

SUBJECT_PATH = "codeclone/memory/retrieval/service.py"


def _seed_dated_record(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    path: str = SUBJECT_PATH,
    statement: str = "The retrieval projection owns what reaches the wire.",
    status: MemoryStatus = "active",
    stale_reason: str | None = None,
) -> MemoryRecord:
    """One approved record whose every timestamp column differs from the rest.

    Seeded at its final status rather than transitioned into it:
    ``update_record_status`` stamps ``updated_at_utc`` with the wall clock,
    which would erase the very value these tests compare.
    """

    module_key = path.replace("/", ".").removesuffix(".py")
    record = MemoryRecord(
        id=generate_memory_id(),
        project_id=project_id,
        identity_key=make_identity_key(
            type="architecture_decision",
            subject_kind="path",
            subject_key=path,
            discriminator="projection_honesty",
        ),
        type="architecture_decision",
        status=status,
        confidence="supported",
        origin="agent",
        ingest_source="agent",
        statement=statement,
        summary=None,
        payload={"subject_path": path},
        created_at_utc=BORN_AT,
        updated_at_utc=CHANGED_AT,
        last_verified_at_utc=VERIFIED_AT,
        expires_at_utc=None,
        created_by="agent",
        verified_by=None,
        approved_by="Den Rozhnovskiy",
        approved_at_utc=APPROVED_AT,
        report_digest=None,
        code_fingerprint=None,
        stale_reason=stale_reason,
        created_on_branch=BORN_ON_BRANCH,
        created_at_commit=BORN_AT_COMMIT,
        verified_on_branch=None,
        verified_at_commit=None,
    )
    store.upsert_record(record)
    subjects: tuple[tuple[SubjectKind, str], ...] = (
        ("path", path),
        ("module", module_key),
    )
    for subject_kind, subject_key in subjects:
        store.write_subject(
            MemorySubject(
                id=generate_memory_id(prefix="subj"),
                memory_id=record.id,
                subject_kind=subject_kind,
                subject_key=subject_key,
                relation="about",
            )
        )
    return record


def _records(payload: object) -> list[dict[str, Any]]:
    """The record lane, proven non-empty before anything is asserted about it."""

    assert isinstance(payload, dict)
    records = payload.get("records")
    assert isinstance(records, list), f"no records lane in {sorted(payload)}"
    assert records, "empty record lane: this assertion would compare nothing"
    for item in records:
        assert isinstance(item, dict)
    return records


def _full_record(result: dict[str, Any]) -> dict[str, Any]:
    """The single record of a full-shape response, narrowed once."""

    payload = result["payload"]
    assert isinstance(payload, dict)
    projected = payload["record"]
    assert isinstance(projected, dict)
    return projected


def _resolution(response: dict[str, Any]) -> dict[str, Any]:
    """The detail-level reconciliation block, narrowed once."""

    resolution = response["detail_level_resolution"]
    assert isinstance(resolution, dict)
    return resolution


# --------------------------------------------------------------------------
# Defect 1 — record timestamps exist in the store and reached no response
# --------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ("for_path", "search", "drafts", "stale"))
def test_list_shapes_project_created_and_updated(tmp_path: Path, mode: str) -> None:
    """Every list shape carries both dates, with the right value in each name."""

    statuses: dict[str, MemoryStatus] = {"drafts": "draft", "stale": "stale"}
    status = statuses.get(mode, "active")
    with memory_store(tmp_path) as (root, project, store, db_path):
        _seed_dated_record(
            store,
            project_id=project.id,
            status=status,
            stale_reason="scope_files_changed" if status == "stale" else None,
        )
        result = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode=mode,
            path=SUBJECT_PATH if mode == "for_path" else None,
            query="projection" if mode == "search" else None,
            include_stale=mode == "stale",
            include_drafts=mode == "drafts",
            detail_level="compact",
        )

    assert result["detail_level"] == "compact"
    projected = _records(result["payload"])
    assert len(projected) == 1
    assert projected[0]["created_at_utc"] == BORN_AT
    assert projected[0]["updated_at_utc"] == CHANGED_AT


def test_relevant_memory_records_project_created_and_updated(tmp_path: Path) -> None:
    """The scoped retrieval lane a memory card actually reads."""

    with memory_store(tmp_path) as (_root, project, store, _db_path):
        _seed_dated_record(store, project_id=project.id)
        result = get_relevant_memory(
            store,
            project_id=project.id,
            scope_paths=(SUBJECT_PATH,),
            scope_resolved_from="explicit",
        )

    projected = _records(result)
    assert len(projected) == 1
    assert projected[0]["created_at_utc"] == BORN_AT
    assert projected[0]["updated_at_utc"] == CHANGED_AT


def test_get_mode_projects_dates_and_birth_provenance(tmp_path: Path) -> None:
    """The full shape adds who/when/where the fact was born."""

    with memory_store(tmp_path) as (root, project, store, db_path):
        record = _seed_dated_record(store, project_id=project.id)
        result = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="get",
            record_id=record.id,
        )

    projected = _full_record(result)
    assert projected["created_at_utc"] == BORN_AT
    assert projected["updated_at_utc"] == CHANGED_AT
    assert projected["last_verified_at_utc"] == VERIFIED_AT
    assert projected["approved_at_utc"] == APPROVED_AT
    assert projected["created_by"] == "agent"
    assert projected["created_on_branch"] == BORN_ON_BRANCH
    assert projected["created_at_commit"] == BORN_AT_COMMIT


def test_compact_shape_withholds_the_full_provenance_block(tmp_path: Path) -> None:
    """Compact buys the two dates a reader needs, not the whole column set.

    The opposite error of the one above: a projection that sprays every column
    into a list of twenty records costs the reader more than it tells them.
    """

    with memory_store(tmp_path) as (_root, project, store, _db_path):
        _seed_dated_record(store, project_id=project.id)
        result = get_relevant_memory(
            store,
            project_id=project.id,
            scope_paths=(SUBJECT_PATH,),
            scope_resolved_from="explicit",
        )

    projected = _records(result)
    assert len(projected) == 1
    # Reachability: the two dates the compact reader is owed did arrive, so
    # the absence below is a withheld field and not an unrun projection.
    assert projected[0]["created_at_utc"] == BORN_AT
    assert projected[0]["updated_at_utc"] == CHANGED_AT
    withheld = {
        "last_verified_at_utc",
        "approved_at_utc",
        "created_by",
        "created_on_branch",
        "created_at_commit",
    }
    assert withheld.isdisjoint(projected[0])


@pytest.mark.parametrize("detail_level", ("compact", "full"))
def test_expires_at_utc_never_reaches_the_wire(
    tmp_path: Path,
    detail_level: str,
) -> None:
    """The never-written column stays off the wire in both shapes.

    ``memory_records.expires_at_utc`` is NULL for every record the store has
    ever held. Every production construction site passes the literal ``None``,
    and record retention is decided elsewhere: ``codeclone.memory.vacuum``
    answers from status, a configured window and ``updated_at_utc``. A field
    that is always null publishes a policy that does not exist, so it is not
    projected — and this pin is what stops the next projection change from
    reintroducing it by reflex.
    """

    with memory_store(tmp_path) as (root, project, store, db_path):
        record = _seed_dated_record(store, project_id=project.id)
        assert record.expires_at_utc is None
        result = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="get" if detail_level == "full" else "for_path",
            record_id=record.id if detail_level == "full" else None,
            path=None if detail_level == "full" else SUBJECT_PATH,
            detail_level=detail_level,
        )

    if detail_level == "full":
        projected = _full_record(result)
    else:
        projected = _records(result["payload"])[0]
    assert "created_at_utc" in projected, "reachability: the projection ran"
    assert "expires_at_utc" not in projected


# --------------------------------------------------------------------------
# Defect 2 — a requested detail level was silently downgraded
# --------------------------------------------------------------------------


@pytest.mark.parametrize("requested", ("normal", "summary"))
def test_alias_detail_level_names_what_it_returned_and_why(
    tmp_path: Path,
    requested: str,
) -> None:
    """``normal``/``summary`` are accepted aliases; the response says so."""

    with memory_store(tmp_path) as (root, project, store, db_path):
        _seed_dated_record(store, project_id=project.id)
        result = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="for_path",
            path=SUBJECT_PATH,
            detail_level=requested,
        )

    assert _records(result["payload"])
    assert result["detail_level"] == "compact"
    resolution = _resolution(result)
    assert resolution["requested"] == requested
    assert resolution["effective"] == "compact"
    assert resolution["reason"] == "requested_level_is_an_alias_of_compact"
    assert "full" in str(resolution["next_step"])


def test_get_mode_states_that_the_mode_fixes_the_level(tmp_path: Path) -> None:
    """``mode=get`` returns full whatever was asked; the response admits it."""

    with memory_store(tmp_path) as (root, project, store, db_path):
        record = _seed_dated_record(store, project_id=project.id)
        result = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="get",
            record_id=record.id,
            detail_level="compact",
        )

    assert result["detail_level"] == "full"
    resolution = _resolution(result)
    assert resolution["requested"] == "compact"
    assert resolution["effective"] == "full"
    assert resolution["reason"] == "mode_projection_is_always_full"


def test_relevant_memory_alias_names_what_it_returned(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        _seed_dated_record(store, project_id=project.id)
        result = get_relevant_memory(
            store,
            project_id=project.id,
            scope_paths=(SUBJECT_PATH,),
            scope_resolved_from="explicit",
            detail_level="normal",
        )

    assert _records(result)
    assert result["detail_level"] == "compact"
    resolution = _resolution(result)
    assert resolution["requested"] == "normal"
    assert resolution["effective"] == "compact"
    assert resolution["reason"] == "requested_level_is_an_alias_of_compact"


@pytest.mark.parametrize(
    ("mode", "requested"),
    (("for_path", "compact"), ("for_path", "full"), ("get", "full")),
)
def test_honoured_detail_level_carries_no_resolution_block(
    tmp_path: Path,
    mode: str,
    requested: str,
) -> None:
    """The other direction: a level that was honoured says nothing extra.

    A stamp that fires unconditionally would tell a caller their request was
    changed when it was not, which is the same dishonesty pointed the other
    way.
    """

    with memory_store(tmp_path) as (root, project, store, db_path):
        record = _seed_dated_record(store, project_id=project.id)
        result = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode=mode,
            record_id=record.id if mode == "get" else None,
            path=SUBJECT_PATH if mode == "for_path" else None,
            detail_level=requested,
        )

    assert result["detail_level"] == requested
    assert "detail_level_resolution" not in result


def test_unknown_detail_level_is_still_a_contract_error(tmp_path: Path) -> None:
    """Naming the downgrade must not widen the accepted vocabulary."""

    with memory_store(tmp_path) as (root, project, store, db_path):
        _seed_dated_record(store, project_id=project.id)
        with pytest.raises(MemoryContractError, match="detail_level must be"):
            query_engineering_memory(
                store,
                project_id=project.id,
                root_path=root,
                backend="sqlite",
                db_path=db_path,
                mode="for_path",
                path=SUBJECT_PATH,
                detail_level="verbose",
            )
