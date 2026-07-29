# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from codeclone.memory.exceptions import MemoryContractError
from codeclone.memory.governance import record_candidate
from codeclone.memory.models import generate_memory_id
from codeclone.memory.retrieval import query_engineering_memory
from codeclone.memory.retrieval.service import get_relevant_memory
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore
from codeclone.report.meta import current_report_timestamp_utc

from .memory_fixtures import memory_store, seed_path_subject_record


def _insert_memory_record_row(
    store: object,
    *,
    project_id: str,
    record_id: str,
    record_type: str,
    path: str,
    schema_version: str = "1.7",
    statement: str = "legacy non-canonical memory record",
) -> None:
    from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore

    assert isinstance(store, SqliteEngineeringMemoryStore)
    now = current_report_timestamp_utc()
    store._conn.execute(
        """
        INSERT INTO memory_records(
            id, project_id, identity_key, type, status, confidence, origin,
            ingest_source, statement, summary, payload_json, created_at_utc,
            updated_at_utc, last_verified_at_utc, expires_at_utc, created_by,
            verified_by, approved_by, approved_at_utc, report_digest,
            code_fingerprint, stale_reason, created_on_branch, created_at_commit,
            verified_on_branch, verified_at_commit, schema_version
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?
        )
        """,
        (
            record_id,
            project_id,
            f"{record_type}:path:{path}:legacy",
            record_type,
            "active",
            "inferred",
            "agent",
            "agent",
            statement,
            None,
            None,
            now,
            now,
            None,
            None,
            "legacy-test",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            schema_version,
        ),
    )
    store._conn.execute(
        """
        INSERT INTO memory_subjects(id, memory_id, subject_kind, subject_key, relation)
        VALUES (?, ?, ?, ?, ?)
        """,
        (generate_memory_id(prefix="subj"), record_id, "path", path, "about"),
    )
    store._conn.commit()


def test_query_engineering_memory_get_stale_drafts_coverage(
    tmp_path: Path,
) -> None:
    with memory_store(tmp_path) as (root, project, store, db_path):
        active = seed_path_subject_record(
            store,
            project_id=project.id,
            path="pkg/active.py",
            statement="active path record",
        )
        draft = record_candidate(
            store,
            project=project,
            record_type="change_rationale",
            statement="draft for drafts mode",
            subject_path="pkg/active.py",
            max_candidates=100,
        )
        store.mark_stale(active.id, reason="test")

        get_payload = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="get",
            record_id=active.id,
        )
        stale_payload = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="stale",
            max_results=10,
        )
        drafts_payload = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="drafts",
            max_results=10,
        )
        coverage_payload = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="coverage",
            scope=["pkg/active.py", "pkg/missing.py"],
        )

    assert get_payload["status"] == "ok"
    get_result = get_payload["payload"]
    assert isinstance(get_result, dict)
    record_summary = get_result.get("record")
    assert isinstance(record_summary, dict)
    assert record_summary.get("id") == active.id

    stale_records = stale_payload["payload"]
    assert isinstance(stale_records, dict)
    assert stale_records.get("record_count", 0) >= 1

    draft_records = drafts_payload["payload"]
    assert isinstance(draft_records, dict)
    assert any(
        item.get("id") == draft.id
        for item in draft_records.get("records", [])
        if isinstance(item, dict)
    )

    coverage = coverage_payload["payload"]
    assert isinstance(coverage, dict)
    assert coverage.get("scope_paths_total") == 2


def test_query_engineering_memory_coverage_accepts_path_alias(
    tmp_path: Path,
) -> None:
    with memory_store(tmp_path) as (root, project, store, db_path):
        coverage_payload = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="coverage",
            path="pkg/active.py",
        )
    coverage = coverage_payload["payload"]
    assert isinstance(coverage, dict)
    assert coverage.get("scope_paths_total") == 1


def test_query_engineering_memory_get_missing_record(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (root, project, store, db_path):
        result = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="get",
            record_id=_full_id("mem", "0"),
        )
    assert result["status"] == "not_found"


def test_memory_retrieval_quarantines_legacy_invalid_record_type(
    tmp_path: Path,
) -> None:
    with memory_store(tmp_path) as (root, project, store, db_path):
        record_id = _full_id("mem", "1")
        _insert_memory_record_row(
            store,
            project_id=project.id,
            record_id=record_id,
            record_type="decision",
            path="pkg/legacy.py",
        )

        for_path = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="for_path",
            path="pkg/legacy.py",
            max_results=10,
            include_stale=True,
        )
        get_payload = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="get",
            record_id=record_id,
        )
        relevant = get_relevant_memory(
            store,
            project_id=project.id,
            scope_paths=("pkg/legacy.py",),
            scope_resolved_from="test",
            max_records=5,
            include_stale=True,
        )

    assert for_path["status"] == "ok"
    payload = for_path["payload"]
    assert isinstance(payload, dict)
    assert payload["record_count"] == 0
    assert get_payload["status"] == "not_found"
    assert relevant["record_count"] == 0


def test_memory_retrieval_quarantines_legacy_record_schema_version(
    tmp_path: Path,
) -> None:
    with memory_store(tmp_path) as (root, project, store, db_path):
        record_id = _full_id("mem", "2")
        _insert_memory_record_row(
            store,
            project_id=project.id,
            record_id=record_id,
            record_type="risk_note",
            path="pkg/legacy.py",
            schema_version="0",
        )

        payload = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="for_path",
            path="pkg/legacy.py",
            max_results=10,
            include_stale=True,
        )
        get_payload = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="get",
            record_id=record_id,
        )

    assert payload["status"] == "ok"
    assert isinstance(payload["payload"], dict)
    assert payload["payload"]["record_count"] == 0
    assert get_payload["status"] == "not_found"


def test_query_engineering_memory_rejects_invalid_filter_literals(
    tmp_path: Path,
) -> None:
    with (
        memory_store(tmp_path) as (root, project, store, db_path),
        pytest.raises(MemoryContractError, match="record_type"),
    ):
        query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root,
            backend="sqlite",
            db_path=db_path,
            mode="search",
            query="legacy",
            filters={"types": ["decision"]},
        )


def test_handle_semantic_search_disabled_block(tmp_path: Path) -> None:
    from codeclone.memory.retrieval.service import _handle_semantic_search_mode

    with memory_store(tmp_path) as (_root, project, store, _db_path):
        payload = _handle_semantic_search_mode(
            store,
            project_id=project.id,
            query="recover checkpoint",
            filter_types=(),
            statuses=("active",),
            filter_confidences=(),
            match_mode="any",
            max_results=5,
            detail_level="compact",
            include_stale=False,
            include_drafts=False,
            semantic_index=None,
            embedding_provider=None,
            provider_label=None,
            semantic_reason=None,
            audit_db_path=None,
        )
    semantic = cast(dict[str, object], payload["semantic"])
    assert semantic["used"] is False
    assert semantic["reason"] == "disabled"


_SHARED_HEX = "abcd1234"
_LONE_HEX = "beef5678"
_LANES = (
    ("mem", "get", "record_id", "record"),
    ("traj", "trajectory_get", "trajectory_id", "trajectory"),
    ("exp", "experience_get", "experience_id", "experience"),
)


def _full_id(family: str, fill: str) -> str:
    """A syntactically valid full id: family prefix plus 32 hex characters."""
    return f"{family}-{fill * 32}"


def _hex_id(family: str, hex_prefix: str, suffix: str) -> str:
    """Valid full id opening with ``hex_prefix`` and made unique by ``suffix``."""
    return f"{family}-{f'{hex_prefix}{suffix}'.ljust(32, '0')}"


def _seed_record(
    store: object,
    *,
    project_id: str,
    record_id: str,
    statement: str,
    schema_version: str | None = None,
) -> None:
    from codeclone.contracts import ENGINEERING_MEMORY_SCHEMA_VERSION

    _insert_memory_record_row(
        store,
        project_id=project_id,
        record_id=record_id,
        record_type="risk_note",
        path=f"pkg/{record_id}.py",
        schema_version=schema_version or ENGINEERING_MEMORY_SCHEMA_VERSION,
        statement=statement,
    )


def _seed_trajectory(store: object, *, project_id: str, trajectory_id: str) -> None:
    from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore
    from codeclone.memory.trajectory.models import (
        TRAJECTORY_PROJECTION_VERSION,
        Trajectory,
    )
    from codeclone.memory.trajectory.store import upsert_trajectory

    assert isinstance(store, SqliteEngineeringMemoryStore)
    now = current_report_timestamp_utc()
    upsert_trajectory(
        store.connection,
        Trajectory(
            id=trajectory_id,
            project_id=project_id,
            repo_root_digest="digest",
            workflow_id=f"intent:{trajectory_id}",
            intent_id=trajectory_id,
            primary_run_id="run-1",
            first_run_id="run-1",
            last_run_id="run-1",
            report_digest=None,
            outcome="accepted",
            quality_tier="verified",
            quality_score=90,
            labels=(),
            summary=f"trajectory {trajectory_id}",
            trajectory_digest=f"digest-{trajectory_id}",
            source_event_stream_digest="stream",
            projection_version=TRAJECTORY_PROJECTION_VERSION,
            event_count=1,
            step_count=0,
            incident_count=0,
            started_at_utc=now,
            finished_at_utc=now,
            projected_at_utc=now,
            updated_at_utc=now,
            steps=(),
            subjects=(),
            evidence=(),
        ),
    )
    store.connection.commit()


def _seed_experiences(
    store: object,
    *,
    project_id: str,
    experience_ids: tuple[str, ...],
) -> None:
    from codeclone.memory.experience.models import Experience
    from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore

    assert isinstance(store, SqliteEngineeringMemoryStore)
    now = current_report_timestamp_utc()
    store.replace_experiences(
        project_id=project_id,
        experiences=[
            Experience(
                id=experience_id,
                project_id=project_id,
                repo_root_digest="digest",
                subject_family="pkg",
                signal=f"verified_finish_{experience_id}",
                outcome_class="accepted:verified",
                support=3,
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
            for experience_id in experience_ids
        ],
    )


def _seed_foreign_project(store: object) -> str:
    """Register a second project so a foreign-owned row can exist at all."""
    from codeclone.memory.models import MemoryProject
    from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore

    assert isinstance(store, SqliteEngineeringMemoryStore)
    now = current_report_timestamp_utc()
    project = MemoryProject(
        id="proj-foreign",
        root="/foreign",
        git_remote=None,
        git_branch=None,
        git_head=None,
        python_tag=None,
        created_at_utc=now,
        updated_at_utc=now,
    )
    store.initialize(project)
    return project.id


def _seed_all_lanes(store: object, *, project_id: str) -> None:
    """Seed each lane with two shared-prefix objects and one lone-prefix object."""
    for family in ("mem", "traj", "exp"):
        ids = (
            _hex_id(family, _SHARED_HEX, "aa"),
            _hex_id(family, _SHARED_HEX, "bb"),
            _hex_id(family, _LONE_HEX, "cc"),
        )
        if family == "mem":
            for object_id in ids:
                _seed_record(
                    store,
                    project_id=project_id,
                    record_id=object_id,
                    statement=f"record {object_id}",
                )
        elif family == "traj":
            for object_id in ids:
                _seed_trajectory(store, project_id=project_id, trajectory_id=object_id)
        else:
            _seed_experiences(store, project_id=project_id, experience_ids=ids)


def _query(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    mode: str,
    record_id: str,
) -> dict[str, object]:
    return query_engineering_memory(
        store,
        project_id=project_id,
        root_path="unused",
        backend="sqlite",
        db_path="unused",
        mode=mode,
        record_id=record_id,
    )


@pytest.mark.parametrize(("family", "mode", "not_found_key", "payload_key"), _LANES)
def test_short_id_resolves_unique_prefix(
    tmp_path: Path,
    family: str,
    mode: str,
    not_found_key: str,
    payload_key: str,
) -> None:
    del not_found_key
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        _seed_all_lanes(store, project_id=project.id)
        short = f"{family}-{_LONE_HEX}"
        result = _query(store, project_id=project.id, mode=mode, record_id=short)

    assert result["status"] == "ok"
    payload = cast("dict[str, object]", result["payload"])
    assert payload_key in payload
    assert payload["resolution"] == {
        "requested": short,
        "resolved": _hex_id(family, _LONE_HEX, "cc"),
    }


@pytest.mark.parametrize(("family", "mode", "not_found_key", "payload_key"), _LANES)
def test_short_id_ambiguous_lists_sorted_candidates(
    tmp_path: Path,
    family: str,
    mode: str,
    not_found_key: str,
    payload_key: str,
) -> None:
    del not_found_key, payload_key
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        _seed_all_lanes(store, project_id=project.id)
        short = f"{family}-{_SHARED_HEX}"
        result = _query(store, project_id=project.id, mode=mode, record_id=short)

    assert result["status"] == "ambiguous"
    payload = cast("dict[str, object]", result["payload"])
    assert payload["requested"] == short
    assert payload["candidate_count"] == 2
    candidates = cast("list[dict[str, object]]", payload["candidates"])
    assert [item["id"] for item in candidates] == [
        _hex_id(family, _SHARED_HEX, "aa"),
        _hex_id(family, _SHARED_HEX, "bb"),
    ]
    for item in candidates:
        assert isinstance(item["kind"], str)
        assert isinstance(item["status"], str)
        assert len(cast("str", item["preview"])) <= 80


@pytest.mark.parametrize(("family", "mode", "not_found_key", "payload_key"), _LANES)
def test_short_id_without_match_is_not_found(
    tmp_path: Path,
    family: str,
    mode: str,
    not_found_key: str,
    payload_key: str,
) -> None:
    del payload_key
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        _seed_all_lanes(store, project_id=project.id)
        short = f"{family}-99999999"
        result = _query(store, project_id=project.id, mode=mode, record_id=short)

    assert result["status"] == "not_found"
    assert result["payload"] == {not_found_key: short}


@pytest.mark.parametrize(("family", "mode", "not_found_key", "payload_key"), _LANES)
def test_full_id_response_carries_no_resolution_key(
    tmp_path: Path,
    family: str,
    mode: str,
    not_found_key: str,
    payload_key: str,
) -> None:
    del not_found_key
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        _seed_all_lanes(store, project_id=project.id)
        full = _hex_id(family, _LONE_HEX, "cc")
        served = _query(store, project_id=project.id, mode=mode, record_id=full)
        missing = _query(
            store,
            project_id=project.id,
            mode=mode,
            record_id=_full_id(family, "7"),
        )

    assert served["status"] == "ok"
    payload = cast("dict[str, object]", served["payload"])
    assert payload_key in payload
    assert "resolution" not in payload
    assert missing["status"] == "not_found"
    assert "resolution" not in cast("dict[str, object]", missing["payload"])


@pytest.mark.parametrize(("family", "mode", "not_found_key", "payload_key"), _LANES)
def test_short_id_below_minimum_length_is_a_contract_error(
    tmp_path: Path,
    family: str,
    mode: str,
    not_found_key: str,
    payload_key: str,
) -> None:
    del not_found_key, payload_key
    with (
        memory_store(tmp_path) as (_root, project, store, _db_path),
        pytest.raises(MemoryContractError, match="at least 8 hex characters"),
    ):
        _query(
            store,
            project_id=project.id,
            mode=mode,
            record_id=f"{family}-abc",
        )


@pytest.mark.parametrize(("family", "mode", "not_found_key", "payload_key"), _LANES)
def test_id_family_mismatch_is_a_contract_error(
    tmp_path: Path,
    family: str,
    mode: str,
    not_found_key: str,
    payload_key: str,
) -> None:
    del not_found_key, payload_key
    with (
        memory_store(tmp_path) as (_root, project, store, _db_path),
        pytest.raises(MemoryContractError, match=f"family '{family}'"),
    ):
        _query(
            store,
            project_id=project.id,
            mode=mode,
            record_id="wrongfamily-abcd1234",
        )


@pytest.mark.parametrize(("family", "mode", "not_found_key", "payload_key"), _LANES)
def test_id_without_separator_is_a_contract_error(
    tmp_path: Path,
    family: str,
    mode: str,
    not_found_key: str,
    payload_key: str,
) -> None:
    del not_found_key, payload_key
    with (
        memory_store(tmp_path) as (_root, project, store, _db_path),
        pytest.raises(MemoryContractError, match=f"family '{family}'"),
    ):
        _query(store, project_id=project.id, mode=mode, record_id="abcd1234")


@pytest.mark.parametrize(("family", "mode", "not_found_key", "payload_key"), _LANES)
def test_malformed_id_tail_is_a_contract_error(
    tmp_path: Path,
    family: str,
    mode: str,
    not_found_key: str,
    payload_key: str,
) -> None:
    del not_found_key, payload_key
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        with pytest.raises(MemoryContractError, match="malformed"):
            _query(
                store,
                project_id=project.id,
                mode=mode,
                record_id=f"{family}-zzzzzzzz",
            )
        with pytest.raises(MemoryContractError, match="at most 32 hex"):
            _query(
                store,
                project_id=project.id,
                mode=mode,
                record_id=f"{family}-{'a' * 33}",
            )


def test_short_id_resolution_ignores_non_canonical_and_foreign_records(
    tmp_path: Path,
) -> None:
    """Resolution and retrieval share one visibility, so hidden rows cannot leak."""
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        _seed_all_lanes(store, project_id=project.id)
        _seed_record(
            store,
            project_id=project.id,
            record_id=_hex_id("mem", _SHARED_HEX, "dd"),
            statement="non-canonical schema version",
            schema_version="0",
        )
        _seed_record(
            store,
            project_id=_seed_foreign_project(store),
            record_id=_hex_id("mem", _SHARED_HEX, "ee"),
            statement="foreign project record",
        )
        ambiguous = _query(
            store,
            project_id=project.id,
            mode="get",
            record_id=f"mem-{_SHARED_HEX}",
        )
        hidden = _query(
            store,
            project_id=project.id,
            mode="get",
            record_id=f"mem-{_SHARED_HEX}dd",
        )
        foreign = _query(
            store,
            project_id=project.id,
            mode="get",
            record_id=f"mem-{_SHARED_HEX}ee",
        )

    payload = cast("dict[str, object]", ambiguous["payload"])
    assert payload["candidate_count"] == 2
    candidate_ids = [
        item["id"] for item in cast("list[dict[str, object]]", payload["candidates"])
    ]
    assert _hex_id("mem", _SHARED_HEX, "dd") not in candidate_ids
    assert _hex_id("mem", _SHARED_HEX, "ee") not in candidate_ids
    # Hidden rows are not_found, never "ambiguous" and never served.
    assert hidden["status"] == "not_found"
    assert foreign["status"] == "not_found"


def test_short_id_candidates_are_capped_with_an_exact_total(tmp_path: Path) -> None:
    import json

    with memory_store(tmp_path) as (_root, project, store, _db_path):
        for index in range(11):
            _seed_record(
                store,
                project_id=project.id,
                record_id=_hex_id("mem", _SHARED_HEX, f"{index:02d}"),
                statement=f"record number {index}",
            )
        first = _query(
            store,
            project_id=project.id,
            mode="get",
            record_id=f"mem-{_SHARED_HEX}",
        )
        second = _query(
            store,
            project_id=project.id,
            mode="get",
            record_id=f"mem-{_SHARED_HEX}",
        )

    payload = cast("dict[str, object]", first["payload"])
    candidates = cast("list[dict[str, object]]", payload["candidates"])
    assert payload["candidate_count"] == 11
    assert len(candidates) == 10
    assert [item["id"] for item in candidates] == sorted(
        cast("str", item["id"]) for item in candidates
    )
    # Determinism: identical input against identical state is byte-identical.
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_short_id_preview_is_truncated_to_the_candidate_width(
    tmp_path: Path,
) -> None:
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        for suffix in ("aa", "bb"):
            _seed_record(
                store,
                project_id=project.id,
                record_id=_hex_id("mem", _SHARED_HEX, suffix),
                statement="x" * 200,
            )
        result = _query(
            store,
            project_id=project.id,
            mode="get",
            record_id=f"mem-{_SHARED_HEX}",
        )

    payload = cast("dict[str, object]", result["payload"])
    candidates = cast("list[dict[str, object]]", payload["candidates"])
    assert all(len(cast("str", item["preview"])) == 80 for item in candidates)


def test_uppercase_and_padded_short_id_normalizes_before_resolving(
    tmp_path: Path,
) -> None:
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        _seed_all_lanes(store, project_id=project.id)
        result = _query(
            store,
            project_id=project.id,
            mode="get",
            record_id=f"  MEM-{_LONE_HEX.upper()}  ",
        )

    assert result["status"] == "ok"
    payload = cast("dict[str, object]", result["payload"])
    resolution = cast("dict[str, object]", payload["resolution"])
    assert resolution["resolved"] == _hex_id("mem", _LONE_HEX, "cc")


def test_store_rejects_an_empty_id_prefix(tmp_path: Path) -> None:
    with (
        memory_store(tmp_path) as (_root, project, store, _db_path),
        pytest.raises(MemoryContractError, match="must not be empty"),
    ):
        store.resolve_record_id_prefix(project_id=project.id, prefix="")


@pytest.mark.parametrize(("family", "mode", "not_found_key", "payload_key"), _LANES)
def test_empty_id_keeps_the_existing_required_field_error(
    tmp_path: Path,
    family: str,
    mode: str,
    not_found_key: str,
    payload_key: str,
) -> None:
    """Decision-table row 1: an absent id is unchanged by short-id resolution."""
    del family, not_found_key, payload_key
    with (
        memory_store(tmp_path) as (_root, project, store, _db_path),
        pytest.raises(MemoryContractError, match=f"mode={mode} requires"),
    ):
        _query(store, project_id=project.id, mode=mode, record_id="   ")
