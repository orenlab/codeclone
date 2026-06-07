# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sqlite3

_CREATE_TRAJECTORIES_SQL = """
CREATE TABLE IF NOT EXISTS memory_trajectories (
    id                         TEXT PRIMARY KEY,
    project_id                 TEXT NOT NULL,
    repo_root_digest           TEXT NOT NULL,
    workflow_id                TEXT NOT NULL,
    intent_id                  TEXT,
    primary_run_id             TEXT,
    first_run_id               TEXT,
    last_run_id                TEXT,
    report_digest              TEXT,
    outcome                    TEXT NOT NULL,
    quality_tier               TEXT NOT NULL,
    quality_score              INTEGER NOT NULL,
    labels_json                TEXT NOT NULL,
    summary                    TEXT NOT NULL,
    trajectory_digest          TEXT NOT NULL,
    source_event_stream_digest TEXT NOT NULL,
    projection_version         TEXT NOT NULL,
    event_count                INTEGER NOT NULL,
    step_count                 INTEGER NOT NULL,
    incident_count             INTEGER NOT NULL,
    started_at_utc             TEXT NOT NULL,
    finished_at_utc            TEXT NOT NULL,
    projected_at_utc           TEXT NOT NULL,
    updated_at_utc             TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES memory_projects(id),
    UNIQUE(project_id, workflow_id, projection_version)
)
"""

_CREATE_TRAJECTORY_STEPS_SQL = """
CREATE TABLE IF NOT EXISTS memory_trajectory_steps (
    trajectory_id      TEXT NOT NULL,
    step_index         INTEGER NOT NULL,
    audit_sequence     INTEGER NOT NULL,
    event_id           TEXT NOT NULL,
    event_type         TEXT NOT NULL,
    status             TEXT,
    run_id             TEXT,
    report_digest      TEXT,
    event_core_sha256  TEXT NOT NULL,
    event_core_json    TEXT NOT NULL,
    summary            TEXT,
    created_at_utc     TEXT NOT NULL,
    PRIMARY KEY(trajectory_id, step_index),
    FOREIGN KEY(trajectory_id) REFERENCES memory_trajectories(id) ON DELETE CASCADE
)
"""

_CREATE_TRAJECTORY_SUBJECTS_SQL = """
CREATE TABLE IF NOT EXISTS memory_trajectory_subjects (
    trajectory_id  TEXT NOT NULL,
    subject_kind   TEXT NOT NULL,
    subject_key    TEXT NOT NULL,
    relation       TEXT NOT NULL DEFAULT 'about',
    PRIMARY KEY(trajectory_id, subject_kind, subject_key, relation),
    FOREIGN KEY(trajectory_id) REFERENCES memory_trajectories(id) ON DELETE CASCADE
)
"""

_CREATE_TRAJECTORY_EVIDENCE_SQL = """
CREATE TABLE IF NOT EXISTS memory_trajectory_evidence (
    trajectory_id    TEXT NOT NULL,
    evidence_kind    TEXT NOT NULL,
    ref              TEXT NOT NULL,
    locator          TEXT,
    digest           TEXT,
    created_at_utc   TEXT NOT NULL,
    PRIMARY KEY(trajectory_id, evidence_kind, ref),
    FOREIGN KEY(trajectory_id) REFERENCES memory_trajectories(id) ON DELETE CASCADE
)
"""

_CREATE_TRAJECTORY_PATCH_TRAILS_SQL = """
CREATE TABLE IF NOT EXISTS memory_trajectory_patch_trails (
    trajectory_id          TEXT PRIMARY KEY,
    patch_trail_digest     TEXT NOT NULL,
    patch_trail_json       TEXT NOT NULL,
    schema_version         TEXT NOT NULL,
    projected_at_utc       TEXT NOT NULL,
    FOREIGN KEY(trajectory_id) REFERENCES memory_trajectories(id) ON DELETE CASCADE
)
"""

_CREATE_TRAJECTORY_PATCH_TRAILS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_trajectory_patch_trails_digest
ON memory_trajectory_patch_trails(patch_trail_digest)
"""

_CREATE_TRAJECTORY_PROJECTION_RUNS_SQL = """
CREATE TABLE IF NOT EXISTS memory_trajectory_projection_runs (
    id                     TEXT PRIMARY KEY,
    project_id             TEXT NOT NULL,
    repo_root_digest       TEXT NOT NULL,
    projection_version     TEXT NOT NULL,
    started_at_utc         TEXT NOT NULL,
    finished_at_utc        TEXT NOT NULL,
    status                 TEXT NOT NULL,
    workflows_seen         INTEGER NOT NULL,
    trajectories_created   INTEGER NOT NULL,
    trajectories_updated   INTEGER NOT NULL,
    trajectories_unchanged INTEGER NOT NULL,
    legacy_event_count     INTEGER NOT NULL,
    message                TEXT,
    FOREIGN KEY(project_id) REFERENCES memory_projects(id)
)
"""

TRAJECTORY_DDL_STATEMENTS = (
    _CREATE_TRAJECTORIES_SQL,
    _CREATE_TRAJECTORY_STEPS_SQL,
    _CREATE_TRAJECTORY_SUBJECTS_SQL,
    _CREATE_TRAJECTORY_EVIDENCE_SQL,
    _CREATE_TRAJECTORY_PATCH_TRAILS_SQL,
    _CREATE_TRAJECTORY_PROJECTION_RUNS_SQL,
)

TRAJECTORY_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_trajectories_project_workflow "
    "ON memory_trajectories(project_id, workflow_id)",
    "CREATE INDEX IF NOT EXISTS idx_trajectories_outcome "
    "ON memory_trajectories(project_id, outcome, quality_tier)",
    "CREATE INDEX IF NOT EXISTS idx_trajectories_updated "
    "ON memory_trajectories(project_id, updated_at_utc)",
    "CREATE INDEX IF NOT EXISTS idx_trajectory_steps_event "
    "ON memory_trajectory_steps(event_type, audit_sequence)",
    "CREATE INDEX IF NOT EXISTS idx_trajectory_subjects_key "
    "ON memory_trajectory_subjects(subject_kind, subject_key)",
    _CREATE_TRAJECTORY_PATCH_TRAILS_INDEX_SQL.strip(),
    "CREATE INDEX IF NOT EXISTS idx_projection_runs_project_time "
    "ON memory_trajectory_projection_runs(project_id, started_at_utc)",
)


def create_patch_trails_schema(conn: sqlite3.Connection) -> None:
    conn.execute(_CREATE_TRAJECTORY_PATCH_TRAILS_SQL)
    conn.execute(_CREATE_TRAJECTORY_PATCH_TRAILS_INDEX_SQL)
    conn.commit()


def create_trajectory_schema(conn: sqlite3.Connection) -> None:
    for statement in TRAJECTORY_DDL_STATEMENTS:
        conn.execute(statement)
    for statement in TRAJECTORY_INDEX_SQL:
        conn.execute(statement)
    conn.commit()


__all__ = [
    "TRAJECTORY_DDL_STATEMENTS",
    "TRAJECTORY_INDEX_SQL",
    "create_patch_trails_schema",
    "create_trajectory_schema",
]
