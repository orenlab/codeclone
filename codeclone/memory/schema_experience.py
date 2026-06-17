# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Experience Layer persistence schema (mirrors schema_trajectory).

Derived state: experiences are rebuilt from trajectories, not a source of
truth. Facets and evidence cascade-delete with their parent experience.
"""

from __future__ import annotations

import sqlite3

_CREATE_EXPERIENCES_SQL = """
CREATE TABLE IF NOT EXISTS memory_experiences (
    id                    TEXT PRIMARY KEY,
    project_id            TEXT NOT NULL,
    repo_root_digest      TEXT NOT NULL,
    subject_family        TEXT NOT NULL,
    signal                TEXT NOT NULL,
    outcome_class         TEXT NOT NULL,
    support               INTEGER NOT NULL,
    quality_min           INTEGER NOT NULL,
    information_value     INTEGER NOT NULL,
    status                TEXT NOT NULL DEFAULT 'active',
    statement             TEXT NOT NULL,
    experience_digest     TEXT NOT NULL,
    distillation_version  TEXT NOT NULL,
    first_observed_at_utc TEXT NOT NULL,
    last_observed_at_utc  TEXT NOT NULL,
    distilled_at_utc      TEXT NOT NULL,
    updated_at_utc        TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES memory_projects(id),
    UNIQUE(project_id, subject_family, signal, outcome_class, distillation_version)
)
"""

_CREATE_EXPERIENCE_FACETS_SQL = """
CREATE TABLE IF NOT EXISTS memory_experience_facets (
    experience_id  TEXT NOT NULL,
    facet_kind     TEXT NOT NULL,
    facet_value    TEXT NOT NULL,
    count          INTEGER NOT NULL,
    PRIMARY KEY(experience_id, facet_kind, facet_value),
    FOREIGN KEY(experience_id) REFERENCES memory_experiences(id) ON DELETE CASCADE
)
"""

_CREATE_EXPERIENCE_EVIDENCE_SQL = """
CREATE TABLE IF NOT EXISTS memory_experience_evidence (
    experience_id    TEXT NOT NULL,
    trajectory_id    TEXT NOT NULL,
    outcome          TEXT NOT NULL,
    finished_at_utc  TEXT NOT NULL,
    PRIMARY KEY(experience_id, trajectory_id),
    FOREIGN KEY(experience_id) REFERENCES memory_experiences(id) ON DELETE CASCADE
)
"""

EXPERIENCE_DDL_STATEMENTS = (
    _CREATE_EXPERIENCES_SQL,
    _CREATE_EXPERIENCE_FACETS_SQL,
    _CREATE_EXPERIENCE_EVIDENCE_SQL,
)

EXPERIENCE_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_experiences_project_family "
    "ON memory_experiences(project_id, subject_family)",
    "CREATE INDEX IF NOT EXISTS idx_experiences_digest "
    "ON memory_experiences(project_id, experience_digest)",
)


def create_experience_schema(conn: sqlite3.Connection) -> None:
    for statement in EXPERIENCE_DDL_STATEMENTS:
        conn.execute(statement)
    for statement in EXPERIENCE_INDEX_SQL:
        conn.execute(statement)
    conn.commit()


__all__ = [
    "EXPERIENCE_DDL_STATEMENTS",
    "EXPERIENCE_INDEX_SQL",
    "create_experience_schema",
]
