# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path

from ...audit.events import repo_root_digest
from ...audit.reader import count_audit_event_core_gaps
from ...audit.validation import DEFAULT_AUDIT_PATH, resolve_audit_path
from ...config.memory import MemoryConfig
from ..models import MemoryProject
from ..trajectory.models import TRAJECTORY_PROJECTION_VERSION
from .store import canonical_stimulus_json, latest_done_projection_job


def _audit_event_core_fingerprint(
    *,
    audit_db_path: Path,
    root_digest: str,
) -> dict[str, int]:
    if not audit_db_path.is_file():
        return {
            "event_core_count": 0,
            "event_core_max_id": 0,
            "legacy_event_count": 0,
        }
    conn = sqlite3.connect(str(audit_db_path))
    try:
        row = conn.execute(
            "SELECT COUNT(*), COALESCE(MAX(id), 0) FROM controller_events "
            "WHERE repo_root_digest=? "
            "AND workflow_id IS NOT NULL AND workflow_id != '' "
            "AND event_core_json IS NOT NULL AND event_core_sha256 IS NOT NULL",
            (root_digest,),
        ).fetchone()
        count = int(row[0]) if row is not None else 0
        max_id = int(row[1]) if row is not None else 0
    finally:
        conn.close()
    legacy = count_audit_event_core_gaps(
        db_path=audit_db_path,
        repo_root_digest=root_digest,
    )
    return {
        "event_core_count": count,
        "event_core_max_id": max_id,
        "legacy_event_count": legacy,
    }


def _memory_records_fingerprint(
    conn: sqlite3.Connection,
    *,
    project_id: str,
) -> dict[str, int | str]:
    row = conn.execute(
        "SELECT COUNT(*), COALESCE(MAX(updated_at_utc), '') "
        "FROM memory_records WHERE project_id=? AND status='active'",
        (project_id,),
    ).fetchone()
    count = int(row[0]) if row is not None else 0
    max_updated = str(row[1]) if row is not None else ""
    return {
        "active_record_count": count,
        "active_record_max_updated_at_utc": max_updated,
    }


def compute_projection_stimulus(
    *,
    conn: sqlite3.Connection,
    project: MemoryProject,
    root_path: Path,
    config: MemoryConfig,
    audit_db_path: Path | None = None,
) -> dict[str, object]:
    root_digest = repo_root_digest(root_path.resolve())
    resolved_audit = audit_db_path or resolve_audit_path(
        root_path=root_path,
        value=DEFAULT_AUDIT_PATH,
    )
    audit_fp = _audit_event_core_fingerprint(
        audit_db_path=resolved_audit,
        root_digest=root_digest,
    )
    memory_fp = _memory_records_fingerprint(conn, project_id=project.id)
    return {
        "repo_root_digest": root_digest,
        "trajectory_projection_version": TRAJECTORY_PROJECTION_VERSION,
        "trajectories_enabled": config.trajectories_enabled,
        "semantic_enabled": config.semantic.enabled,
        **audit_fp,
        **memory_fp,
    }


def stimulus_digest(stimulus: Mapping[str, object]) -> str:
    payload = canonical_stimulus_json(stimulus)
    return hashlib.sha256(payload.encode()).hexdigest()


def projection_is_stale(
    *,
    current: Mapping[str, object],
    last_applied: Mapping[str, object] | None,
) -> bool:
    if last_applied is None:
        return True
    return stimulus_digest(current) != stimulus_digest(last_applied)


def parse_stimulus_json(raw: str | None) -> dict[str, object]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def last_applied_stimulus(
    conn: sqlite3.Connection,
    *,
    project_id: str,
) -> dict[str, object] | None:
    job = latest_done_projection_job(conn, project_id=project_id)
    if job is None:
        return None
    result = parse_stimulus_json(job.result_json)
    applied = result.get("applied_stimulus")
    if isinstance(applied, dict):
        return dict(applied)
    return parse_stimulus_json(job.stimulus_json)


__all__ = [
    "compute_projection_stimulus",
    "last_applied_stimulus",
    "parse_stimulus_json",
    "projection_is_stale",
    "stimulus_digest",
]
