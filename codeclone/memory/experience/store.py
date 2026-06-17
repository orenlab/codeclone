# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Experience persistence: replace-all per project, with cascading facets and
evidence. Experiences are derived state — a distillation run replaces the
project's experiences wholesale (dormant lifecycle is deferred to E.2)."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from .models import (
    Experience,
    ExperienceEvidence,
    ExperienceFacet,
    ExperienceFacetKind,
    ExperienceStatus,
)


def _use_row_factory(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row


def replace_experiences(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    experiences: Sequence[Experience],
) -> int:
    """Replace all experiences for a project with the distilled set."""
    conn.execute("DELETE FROM memory_experiences WHERE project_id=?", (project_id,))
    for experience in experiences:
        _insert_experience(conn, experience)
    conn.commit()
    return len(experiences)


def _insert_experience(conn: sqlite3.Connection, experience: Experience) -> None:
    conn.execute(
        """
        INSERT INTO memory_experiences(
            id, project_id, repo_root_digest, subject_family, signal,
            outcome_class, support, quality_min, information_value, status,
            statement, experience_digest, distillation_version,
            first_observed_at_utc, last_observed_at_utc, distilled_at_utc,
            updated_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            experience.id,
            experience.project_id,
            experience.repo_root_digest,
            experience.subject_family,
            experience.signal,
            experience.outcome_class,
            experience.support,
            experience.quality_min,
            experience.information_value,
            experience.status,
            experience.statement,
            experience.experience_digest,
            experience.distillation_version,
            experience.first_observed_at_utc,
            experience.last_observed_at_utc,
            experience.distilled_at_utc,
            experience.updated_at_utc,
        ),
    )
    conn.executemany(
        "INSERT INTO memory_experience_facets("
        "experience_id, facet_kind, facet_value, count) VALUES (?, ?, ?, ?)",
        [
            (experience.id, facet.facet_kind, facet.facet_value, facet.count)
            for facet in experience.facets
        ],
    )
    conn.executemany(
        "INSERT INTO memory_experience_evidence("
        "experience_id, trajectory_id, outcome, finished_at_utc) VALUES (?, ?, ?, ?)",
        [
            (experience.id, item.trajectory_id, item.outcome, item.finished_at_utc)
            for item in experience.evidence
        ],
    )


def count_experiences(conn: sqlite3.Connection, *, project_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM memory_experiences WHERE project_id=?",
        (project_id,),
    ).fetchone()
    return int(row[0])


def list_experiences(
    conn: sqlite3.Connection,
    *,
    project_id: str,
) -> list[Experience]:
    _use_row_factory(conn)
    rows = conn.execute(
        "SELECT * FROM memory_experiences WHERE project_id=? "
        "ORDER BY subject_family ASC, signal ASC, outcome_class ASC",
        (project_id,),
    ).fetchall()
    return [_row_to_experience(conn, row) for row in rows]


def list_experiences_for_subject_family(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    subject_family: str,
) -> list[Experience]:
    _use_row_factory(conn)
    rows = conn.execute(
        "SELECT * FROM memory_experiences WHERE project_id=? AND subject_family=? "
        "ORDER BY signal ASC, outcome_class ASC",
        (project_id, subject_family),
    ).fetchall()
    return [_row_to_experience(conn, row) for row in rows]


def find_experience(
    conn: sqlite3.Connection,
    *,
    experience_id: str,
) -> Experience | None:
    _use_row_factory(conn)
    row = conn.execute(
        "SELECT * FROM memory_experiences WHERE id=?",
        (experience_id,),
    ).fetchone()
    return _row_to_experience(conn, row) if row is not None else None


def _facets_for_experience(
    conn: sqlite3.Connection,
    experience_id: str,
) -> tuple[ExperienceFacet, ...]:
    rows = conn.execute(
        "SELECT facet_kind, facet_value, count FROM memory_experience_facets "
        "WHERE experience_id=? ORDER BY facet_kind ASC, facet_value ASC",
        (experience_id,),
    ).fetchall()
    return tuple(
        ExperienceFacet(
            facet_kind=_facet_kind(str(row["facet_kind"])),
            facet_value=str(row["facet_value"]),
            count=int(row["count"]),
        )
        for row in rows
    )


def _evidence_for_experience(
    conn: sqlite3.Connection,
    experience_id: str,
) -> tuple[ExperienceEvidence, ...]:
    rows = conn.execute(
        "SELECT trajectory_id, outcome, finished_at_utc "
        "FROM memory_experience_evidence WHERE experience_id=? "
        "ORDER BY finished_at_utc ASC, trajectory_id ASC",
        (experience_id,),
    ).fetchall()
    return tuple(
        ExperienceEvidence(
            trajectory_id=str(row["trajectory_id"]),
            outcome=str(row["outcome"]),
            finished_at_utc=str(row["finished_at_utc"]),
        )
        for row in rows
    )


def _facet_kind(value: str) -> ExperienceFacetKind:
    if value in ("agent_family", "analysis_profile", "intent_class"):
        return value  # type: ignore[return-value]
    msg = f"unknown experience facet kind: {value!r}"
    raise ValueError(msg)


def _row_to_experience(conn: sqlite3.Connection, row: sqlite3.Row) -> Experience:
    experience_id = str(row["id"])
    return Experience(
        id=experience_id,
        project_id=str(row["project_id"]),
        repo_root_digest=str(row["repo_root_digest"]),
        subject_family=str(row["subject_family"]),
        signal=str(row["signal"]),
        outcome_class=str(row["outcome_class"]),
        support=int(row["support"]),
        quality_min=int(row["quality_min"]),
        information_value=int(row["information_value"]),
        status=_status(str(row["status"])),
        statement=str(row["statement"]),
        experience_digest=str(row["experience_digest"]),
        distillation_version=str(row["distillation_version"]),
        first_observed_at_utc=str(row["first_observed_at_utc"]),
        last_observed_at_utc=str(row["last_observed_at_utc"]),
        distilled_at_utc=str(row["distilled_at_utc"]),
        updated_at_utc=str(row["updated_at_utc"]),
        facets=_facets_for_experience(conn, experience_id),
        evidence=_evidence_for_experience(conn, experience_id),
    )


def _status(value: str) -> ExperienceStatus:
    if value in ("active", "dormant"):
        return value  # type: ignore[return-value]
    msg = f"unknown experience status: {value!r}"
    raise ValueError(msg)


__all__ = [
    "count_experiences",
    "find_experience",
    "list_experiences",
    "list_experiences_for_subject_family",
    "replace_experiences",
]
