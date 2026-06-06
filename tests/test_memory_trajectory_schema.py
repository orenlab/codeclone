# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sqlite3
from pathlib import Path

from codeclone.contracts import ENGINEERING_MEMORY_SCHEMA_VERSION
from codeclone.memory.schema import create_schema_v1, ensure_schema, get_meta, set_meta


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def test_fresh_memory_schema_contains_trajectory_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.sqlite3"
    conn = sqlite3.connect(db_path)
    try:
        create_schema_v1(conn)
        assert get_meta(conn, "schema_version") == ENGINEERING_MEMORY_SCHEMA_VERSION
        for table in (
            "memory_trajectories",
            "memory_trajectory_steps",
            "memory_trajectory_subjects",
            "memory_trajectory_evidence",
            "memory_trajectory_projection_runs",
        ):
            assert _table_exists(conn, table)
    finally:
        conn.close()


def test_memory_schema_migrates_1_1_to_1_2_trajectory_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.sqlite3"
    conn = sqlite3.connect(db_path)
    try:
        create_schema_v1(conn)
        for table in (
            "memory_trajectory_projection_runs",
            "memory_trajectory_evidence",
            "memory_trajectory_subjects",
            "memory_trajectory_steps",
            "memory_trajectories",
        ):
            conn.execute(f"DROP TABLE {table}")
        set_meta(conn, "schema_version", "1.1")
        conn.commit()

        ensure_schema(conn)

        assert get_meta(conn, "schema_version") == ENGINEERING_MEMORY_SCHEMA_VERSION
        assert _table_exists(conn, "memory_trajectories")
        migration = conn.execute(
            "SELECT version FROM memory_schema_migrations WHERE version='1.2'"
        ).fetchone()
        assert migration is not None
    finally:
        conn.close()
