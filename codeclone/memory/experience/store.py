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
from collections.abc import Callable, Sequence
from typing import TypeVar

from ...utils.iterutils import chunked
from .models import (
    Experience,
    ExperienceEvidence,
    ExperienceFacet,
    ExperienceFacetKind,
    ExperienceStatus,
)

_SQLITE_IN_QUERY_BATCH = 500
_T = TypeVar("_T")
_FACETS_BATCH_SQL = (
    "SELECT experience_id, facet_kind, facet_value, count "
    "FROM memory_experience_facets "
    "WHERE experience_id IN ({placeholders}) "
    "ORDER BY experience_id ASC, facet_kind ASC, facet_value ASC"
)
_EVIDENCE_BATCH_SQL = (
    "SELECT experience_id, trajectory_id, outcome, finished_at_utc "
    "FROM memory_experience_evidence "
    "WHERE experience_id IN ({placeholders}) "
    "ORDER BY experience_id ASC, finished_at_utc ASC, trajectory_id ASC"
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
    if not experiences:
        conn.execute("DELETE FROM memory_experiences WHERE project_id=?", (project_id,))
        conn.commit()
        return 0

    new_by_digest = {
        experience.experience_digest: experience for experience in experiences
    }
    stored_by_digest = _experiences_by_digest(conn, project_id=project_id)
    existing_digests = set(stored_by_digest)
    new_digests = set(new_by_digest)

    remove_digests = existing_digests - new_digests
    refresh: list[Experience] = []
    for digest in sorted(new_digests):
        incoming = new_by_digest[digest]
        stored = stored_by_digest.get(digest)
        if stored is None:
            refresh.append(incoming)
            continue
        if _experience_content_key(stored) != _experience_content_key(incoming):
            remove_digests.add(digest)
            refresh.append(incoming)

    if not remove_digests and not refresh:
        return len(experiences)

    for batch in chunked(tuple(sorted(remove_digests)), _SQLITE_IN_QUERY_BATCH):
        placeholders = ", ".join("?" for _ in batch)
        conn.execute(
            f"DELETE FROM memory_experiences WHERE project_id=? "
            f"AND experience_digest IN ({placeholders})",
            (project_id, *batch),
        )
    if refresh:
        _batch_insert_experiences(conn, refresh)
    conn.commit()
    return len(experiences)


def _experiences_by_digest(
    conn: sqlite3.Connection,
    *,
    project_id: str,
) -> dict[str, Experience]:
    _use_row_factory(conn)
    rows = conn.execute(
        "SELECT * FROM memory_experiences WHERE project_id=?",
        (project_id,),
    ).fetchall()
    if not rows:
        return {}
    return {
        experience.experience_digest: experience
        for experience in _hydrate_experience_rows(conn, rows)
    }


def _group_rows_by_experience_id(
    conn: sqlite3.Connection,
    *,
    ids: Sequence[str],
    sql: str,
    build: Callable[[sqlite3.Row], _T],
) -> dict[str, list[_T]]:
    grouped: dict[str, list[_T]] = {experience_id: [] for experience_id in ids}
    for batch in chunked(tuple(ids), _SQLITE_IN_QUERY_BATCH):
        placeholders = ", ".join("?" for _ in batch)
        rows = conn.execute(sql.format(placeholders=placeholders), batch).fetchall()
        for row in rows:
            grouped.setdefault(str(row["experience_id"]), []).append(build(row))
    return grouped


def _hydrate_experience_rows(
    conn: sqlite3.Connection,
    rows: Sequence[sqlite3.Row],
) -> list[Experience]:
    experience_ids = [str(row["id"]) for row in rows]
    facets_by_id = _group_rows_by_experience_id(
        conn,
        ids=experience_ids,
        sql=_FACETS_BATCH_SQL,
        build=_row_to_facet,
    )
    evidence_by_id = _group_rows_by_experience_id(
        conn,
        ids=experience_ids,
        sql=_EVIDENCE_BATCH_SQL,
        build=_row_to_evidence,
    )
    return [
        _row_to_experience(
            row,
            facets=tuple(facets_by_id.get(str(row["id"]), [])),
            evidence=tuple(evidence_by_id.get(str(row["id"]), [])),
        )
        for row in rows
    ]


def _experience_content_key(experience: Experience) -> tuple[object, ...]:
    """Comparable payload excluding distill timestamps refreshed every run."""
    return (
        experience.id,
        experience.repo_root_digest,
        experience.subject_family,
        experience.signal,
        experience.outcome_class,
        experience.support,
        experience.quality_min,
        experience.information_value,
        experience.status,
        experience.statement,
        experience.distillation_version,
        experience.first_observed_at_utc,
        experience.last_observed_at_utc,
        experience.facets,
        experience.evidence,
    )


def _batch_insert_experiences(
    conn: sqlite3.Connection,
    experiences: Sequence[Experience],
) -> None:
    conn.executemany(
        """
        INSERT INTO memory_experiences(
            id, project_id, repo_root_digest, subject_family, signal,
            outcome_class, support, quality_min, information_value, status,
            statement, experience_digest, distillation_version,
            first_observed_at_utc, last_observed_at_utc, distilled_at_utc,
            updated_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
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
            )
            for experience in experiences
        ],
    )
    facet_rows = [
        (experience.id, facet.facet_kind, facet.facet_value, facet.count)
        for experience in experiences
        for facet in experience.facets
    ]
    if facet_rows:
        conn.executemany(
            "INSERT INTO memory_experience_facets("
            "experience_id, facet_kind, facet_value, count) VALUES (?, ?, ?, ?)",
            facet_rows,
        )
    evidence_rows = [
        (experience.id, item.trajectory_id, item.outcome, item.finished_at_utc)
        for experience in experiences
        for item in experience.evidence
    ]
    if evidence_rows:
        conn.executemany(
            "INSERT INTO memory_experience_evidence("
            "experience_id, trajectory_id, outcome, finished_at_utc) "
            "VALUES (?, ?, ?, ?)",
            evidence_rows,
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
    return _hydrate_experience_rows(conn, rows)


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
    return _hydrate_experience_rows(conn, rows)


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
    if row is None:
        return None
    return _hydrate_experience_rows(conn, [row])[0]


def _row_to_facet(row: sqlite3.Row) -> ExperienceFacet:
    return ExperienceFacet(
        facet_kind=_facet_kind(str(row["facet_kind"])),
        facet_value=str(row["facet_value"]),
        count=int(row["count"]),
    )


def _row_to_evidence(row: sqlite3.Row) -> ExperienceEvidence:
    return ExperienceEvidence(
        trajectory_id=str(row["trajectory_id"]),
        outcome=str(row["outcome"]),
        finished_at_utc=str(row["finished_at_utc"]),
    )


def _facet_kind(value: str) -> ExperienceFacetKind:
    if value in ("agent_family", "analysis_profile", "intent_class"):
        return value  # type: ignore[return-value]
    msg = f"unknown experience facet kind: {value!r}"
    raise ValueError(msg)


def _row_to_experience(
    row: sqlite3.Row,
    *,
    facets: tuple[ExperienceFacet, ...] | None = None,
    evidence: tuple[ExperienceEvidence, ...] | None = None,
) -> Experience:
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
        facets=facets if facets is not None else (),
        evidence=evidence if evidence is not None else (),
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
