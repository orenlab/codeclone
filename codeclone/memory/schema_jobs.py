# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sqlite3

_CREATE_PROJECTION_JOBS_SQL = """
CREATE TABLE IF NOT EXISTS memory_projection_jobs (
    id                TEXT PRIMARY KEY,
    project_id        TEXT NOT NULL,
    job_kind          TEXT NOT NULL,
    status            TEXT NOT NULL,
    trigger           TEXT NOT NULL,
    requested_at_utc  TEXT NOT NULL,
    started_at_utc    TEXT,
    finished_at_utc   TEXT,
    claimed_by        TEXT,
    attempt           INTEGER NOT NULL DEFAULT 0,
    stimulus_json     TEXT NOT NULL,
    result_json       TEXT,
    error_message     TEXT,
    flush_claimed_by  TEXT,
    FOREIGN KEY(project_id) REFERENCES memory_projects(id)
)
"""

PROJECTION_JOBS_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_projection_jobs_project_status "
    "ON memory_projection_jobs(project_id, status, requested_at_utc)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_projection_jobs_pending "
    "ON memory_projection_jobs(project_id, job_kind) "
    "WHERE status = 'pending'",
)

PROJECTION_JOBS_DDL_STATEMENTS = (_CREATE_PROJECTION_JOBS_SQL,)


def create_projection_jobs_schema(conn: sqlite3.Connection) -> None:
    for statement in PROJECTION_JOBS_DDL_STATEMENTS:
        conn.execute(statement)
    for statement in PROJECTION_JOBS_INDEX_SQL:
        conn.execute(statement)


__all__ = [
    "PROJECTION_JOBS_DDL_STATEMENTS",
    "PROJECTION_JOBS_INDEX_SQL",
    "create_projection_jobs_schema",
]
