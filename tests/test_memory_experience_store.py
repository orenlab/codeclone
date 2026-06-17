# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from codeclone.contracts import ENGINEERING_MEMORY_SCHEMA_VERSION
from codeclone.memory.experience.models import (
    EXPERIENCE_DISTILLATION_VERSION,
    Experience,
    ExperienceEvidence,
    ExperienceFacet,
)
from codeclone.memory.experience.store import (
    count_experiences,
    list_experiences,
    list_experiences_for_subject_family,
    replace_experiences,
)
from codeclone.memory.schema import open_memory_db
from codeclone.memory.schema_meta import get_meta

_NOW = "2026-06-08T00:00:00Z"
_PROJECT_ID = "proj-1"
_FAMILY = "codeclone/memory/trajectory"


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = open_memory_db(tmp_path / "memory.db")
    connection.execute(
        "INSERT INTO memory_projects(id, root, created_at_utc, updated_at_utc) "
        "VALUES (?, ?, ?, ?)",
        (_PROJECT_ID, str(tmp_path), _NOW, _NOW),
    )
    connection.commit()
    try:
        yield connection
    finally:
        connection.close()


def _experience(
    *,
    suffix: str,
    subject_family: str = _FAMILY,
    signal: str = "scope_expanded",
    facets: tuple[ExperienceFacet, ...] = (
        ExperienceFacet("agent_family", "claude-code", 3),
        ExperienceFacet("agent_family", "cursor-vscode", 2),
    ),
    evidence: tuple[ExperienceEvidence, ...] = (
        ExperienceEvidence("traj-1", "violated", _NOW),
        ExperienceEvidence("traj-2", "violated", _NOW),
    ),
) -> Experience:
    return Experience(
        id=f"exp-{suffix}",
        project_id=_PROJECT_ID,
        repo_root_digest="b080e2e3",
        subject_family=subject_family,
        signal=signal,
        outcome_class="violated:incident",
        support=5,
        quality_min=20,
        information_value=85,
        status="active",
        statement=f"statement {suffix}",
        experience_digest=f"digest-{suffix}",
        distillation_version=EXPERIENCE_DISTILLATION_VERSION,
        first_observed_at_utc=_NOW,
        last_observed_at_utc=_NOW,
        distilled_at_utc=_NOW,
        updated_at_utc=_NOW,
        facets=facets,
        evidence=evidence,
    )


def test_fresh_db_is_at_current_schema_version(conn: sqlite3.Connection) -> None:
    assert get_meta(conn, "schema_version") == ENGINEERING_MEMORY_SCHEMA_VERSION
    assert ENGINEERING_MEMORY_SCHEMA_VERSION == "1.7"


def test_replace_and_list_round_trip(conn: sqlite3.Connection) -> None:
    written = replace_experiences(
        conn,
        project_id=_PROJECT_ID,
        experiences=[
            _experience(suffix="a", signal="scope_expanded"),
            _experience(suffix="b", signal="recovered"),
        ],
    )
    assert written == 2

    loaded = list_experiences(conn, project_id=_PROJECT_ID)
    # Deterministic order is by (subject_family, signal, outcome_class):
    # "recovered" (exp-b) sorts before "scope_expanded" (exp-a).
    assert [item.id for item in loaded] == ["exp-b", "exp-a"]
    restored = loaded[1]
    assert restored.id == "exp-a"
    assert restored.support == 5
    assert restored.information_value == 85
    assert {(f.facet_value, f.count) for f in restored.facets} == {
        ("claude-code", 3),
        ("cursor-vscode", 2),
    }
    assert {item.trajectory_id for item in restored.evidence} == {"traj-1", "traj-2"}


def test_replace_is_wholesale_and_cascades(conn: sqlite3.Connection) -> None:
    replace_experiences(
        conn,
        project_id=_PROJECT_ID,
        experiences=[
            _experience(suffix="a", signal="scope_expanded"),
            _experience(suffix="b", signal="recovered"),
        ],
    )
    # Re-distillation drops "b"; replace-all must remove it and its children.
    replace_experiences(
        conn,
        project_id=_PROJECT_ID,
        experiences=[_experience(suffix="a", signal="scope_expanded")],
    )
    assert count_experiences(conn, project_id=_PROJECT_ID) == 1
    assert [item.id for item in list_experiences(conn, project_id=_PROJECT_ID)] == [
        "exp-a"
    ]
    orphan_facets = conn.execute(
        "SELECT COUNT(*) FROM memory_experience_facets WHERE experience_id=?",
        ("exp-b",),
    ).fetchone()[0]
    orphan_evidence = conn.execute(
        "SELECT COUNT(*) FROM memory_experience_evidence WHERE experience_id=?",
        ("exp-b",),
    ).fetchone()[0]
    assert orphan_facets == 0
    assert orphan_evidence == 0


def test_list_for_subject_family_filters(conn: sqlite3.Connection) -> None:
    replace_experiences(
        conn,
        project_id=_PROJECT_ID,
        experiences=[
            _experience(suffix="a", subject_family="codeclone/memory/trajectory"),
            _experience(suffix="b", subject_family="codeclone/surfaces/mcp"),
        ],
    )
    scoped = list_experiences_for_subject_family(
        conn,
        project_id=_PROJECT_ID,
        subject_family="codeclone/surfaces/mcp",
    )
    assert [item.id for item in scoped] == ["exp-b"]


def test_empty_replace_clears_project(conn: sqlite3.Connection) -> None:
    replace_experiences(
        conn,
        project_id=_PROJECT_ID,
        experiences=[_experience(suffix="a")],
    )
    replace_experiences(conn, project_id=_PROJECT_ID, experiences=[])
    assert count_experiences(conn, project_id=_PROJECT_ID) == 0


def test_private_validators_reject_unknown_values() -> None:
    from codeclone.memory.experience.store import _facet_kind, _status

    with pytest.raises(ValueError, match="unknown experience facet kind"):
        _facet_kind("not-a-facet")
    with pytest.raises(ValueError, match="unknown experience status"):
        _status("archived")
