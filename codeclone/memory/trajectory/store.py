# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
import sqlite3
import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

import orjson

from ...audit.events import repo_root_digest
from ...audit.reader import (
    AuditRecord,
    count_audit_event_core_gaps,
    read_audit_event_core_records,
)
from ...report.meta import current_report_timestamp_utc
from ...utils.json_io import json_text
from ..models import MemoryProject
from ..search_index import SearchMatchMode, tokenize_query
from .models import (
    TRAJECTORY_PROJECTION_VERSION,
    Trajectory,
    TrajectoryEvidence,
    TrajectoryListItem,
    TrajectoryProjectionResult,
    TrajectoryProjectionRun,
    TrajectoryStep,
    TrajectorySubject,
)
from .patch_trail_projector import project_patch_trail_from_audit
from .projector import project_trajectory
from .quality import apply_trajectory_quality_score


def rebuild_trajectories_from_audit(
    *,
    conn: sqlite3.Connection,
    project: MemoryProject,
    root_path: Path,
    audit_db_path: Path,
    projection_version: str = TRAJECTORY_PROJECTION_VERSION,
) -> TrajectoryProjectionResult:
    root_digest = repo_root_digest(root_path.resolve())
    started = current_report_timestamp_utc()
    events = read_audit_event_core_records(
        db_path=audit_db_path,
        repo_root_digest=root_digest,
    )
    legacy_event_count = count_audit_event_core_gaps(
        db_path=audit_db_path,
        repo_root_digest=root_digest,
    )
    grouped = _group_by_workflow(events)
    created = updated = unchanged = 0
    trajectories: list[Trajectory] = []
    for workflow_id, records in grouped.items():
        patch_trail = project_patch_trail_from_audit(
            records=records,
            repo_root_digest=root_digest,
        )
        patch_trail_digest = (
            patch_trail.patch_trail_digest if patch_trail is not None else None
        )
        trajectory = project_trajectory(
            project_id=project.id,
            repo_root_digest=root_digest,
            workflow_id=workflow_id,
            records=records,
            projection_version=projection_version,
            projected_at_utc=started,
            patch_trail_digest=patch_trail_digest,
        )
        patch_payload = (
            patch_trail._canonical_dict(include_digest=True)
            if patch_trail is not None
            else None
        )
        trajectory = apply_trajectory_quality_score(
            trajectory,
            patch_trail_payload=patch_payload,
            patch_trail_digest=patch_trail_digest,
        )
        action = upsert_trajectory(conn, trajectory)
        if patch_trail is not None:
            upsert_trajectory_patch_trail(
                conn,
                trajectory_id=trajectory.id,
                patch_trail_json=_json_object(
                    patch_trail._canonical_dict(include_digest=True)
                ),
                patch_trail_digest=patch_trail.patch_trail_digest,
                schema_version=patch_trail.schema_version,
                projected_at_utc=started,
            )
        supersede_stale_projection_trajectories(
            conn,
            project_id=project.id,
            workflow_id=workflow_id,
            keep_trajectory_id=trajectory.id,
            keep_trajectory_digest=trajectory.trajectory_digest,
        )
        if action == "created":
            created += 1
        elif action == "updated":
            updated += 1
        else:
            unchanged += 1
        trajectories.append(trajectory)
    finished = current_report_timestamp_utc()
    run = TrajectoryProjectionRun(
        id=_projection_run_id(
            project_id=project.id,
            repo_root_digest=root_digest,
            projection_version=projection_version,
            started_at_utc=started,
            workflow_count=len(grouped),
        ),
        project_id=project.id,
        repo_root_digest=root_digest,
        projection_version=projection_version,
        started_at_utc=started,
        finished_at_utc=finished,
        status="ok",
        workflows_seen=len(grouped),
        trajectories_created=created,
        trajectories_updated=updated,
        trajectories_unchanged=unchanged,
        legacy_event_count=legacy_event_count,
        message=None,
    )
    write_projection_run(conn, run)
    conn.commit()
    return TrajectoryProjectionResult(run=run, trajectories=tuple(trajectories))


def upsert_trajectory(conn: sqlite3.Connection, trajectory: Trajectory) -> str:
    existing = conn.execute(
        "SELECT trajectory_digest FROM memory_trajectories WHERE id=?",
        (trajectory.id,),
    ).fetchone()
    action = (
        "created"
        if existing is None
        else "unchanged"
        if str(existing[0]) == trajectory.trajectory_digest
        else "updated"
    )
    if action == "unchanged":
        conn.execute(
            "UPDATE memory_trajectories SET projected_at_utc=?, updated_at_utc=? "
            "WHERE id=?",
            (trajectory.projected_at_utc, trajectory.updated_at_utc, trajectory.id),
        )
        return action
    conn.execute(
        """
        INSERT INTO memory_trajectories(
            id, project_id, repo_root_digest, workflow_id, intent_id,
            primary_run_id, first_run_id, last_run_id, report_digest,
            outcome, quality_tier, quality_score, labels_json, summary,
            trajectory_digest,
            source_event_stream_digest, projection_version, event_count,
            step_count, incident_count, started_at_utc, finished_at_utc,
            projected_at_utc, updated_at_utc
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        ON CONFLICT(id) DO UPDATE SET
            intent_id=excluded.intent_id,
            primary_run_id=excluded.primary_run_id,
            first_run_id=excluded.first_run_id,
            last_run_id=excluded.last_run_id,
            report_digest=excluded.report_digest,
            outcome=excluded.outcome,
            quality_tier=excluded.quality_tier,
            quality_score=excluded.quality_score,
            labels_json=excluded.labels_json,
            summary=excluded.summary,
            trajectory_digest=excluded.trajectory_digest,
            source_event_stream_digest=excluded.source_event_stream_digest,
            event_count=excluded.event_count,
            step_count=excluded.step_count,
            incident_count=excluded.incident_count,
            started_at_utc=excluded.started_at_utc,
            finished_at_utc=excluded.finished_at_utc,
            projected_at_utc=excluded.projected_at_utc,
            updated_at_utc=excluded.updated_at_utc
        """,
        (
            trajectory.id,
            trajectory.project_id,
            trajectory.repo_root_digest,
            trajectory.workflow_id,
            trajectory.intent_id,
            trajectory.primary_run_id,
            trajectory.first_run_id,
            trajectory.last_run_id,
            trajectory.report_digest,
            trajectory.outcome,
            trajectory.quality_tier,
            trajectory.quality_score,
            _json_array(trajectory.labels),
            trajectory.summary,
            trajectory.trajectory_digest,
            trajectory.source_event_stream_digest,
            trajectory.projection_version,
            trajectory.event_count,
            trajectory.step_count,
            trajectory.incident_count,
            trajectory.started_at_utc,
            trajectory.finished_at_utc,
            trajectory.projected_at_utc,
            trajectory.updated_at_utc,
        ),
    )
    conn.execute(
        "DELETE FROM memory_trajectory_steps WHERE trajectory_id=?", (trajectory.id,)
    )
    conn.execute(
        "DELETE FROM memory_trajectory_subjects WHERE trajectory_id=?",
        (trajectory.id,),
    )
    conn.execute(
        "DELETE FROM memory_trajectory_evidence WHERE trajectory_id=?",
        (trajectory.id,),
    )
    _insert_steps(conn, trajectory)
    _insert_subjects(conn, trajectory.id, trajectory.subjects)
    _insert_evidence(conn, trajectory.id, trajectory.evidence)
    return action


def supersede_stale_projection_trajectories(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    workflow_id: str,
    keep_trajectory_id: str,
    keep_trajectory_digest: str,
) -> int:
    stale_rows = conn.execute(
        """
        SELECT id FROM memory_trajectories
        WHERE project_id=? AND workflow_id=? AND id != ?
        """,
        (project_id, workflow_id, keep_trajectory_id),
    ).fetchall()
    removed = 0
    for row in stale_rows:
        old_id = str(row["id"])
        conn.execute(
            """
            UPDATE memory_evidence
            SET ref=?, digest=?
            WHERE evidence_kind='trajectory' AND ref=?
            """,
            (keep_trajectory_id, keep_trajectory_digest, old_id),
        )
        conn.execute("DELETE FROM memory_trajectories WHERE id=?", (old_id,))
        removed += 1
    return removed


def list_canonical_trajectories_for_export(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    limit: int = 10_000,
) -> list[Trajectory]:
    rows = conn.execute(
        """
        SELECT id FROM memory_trajectories
        WHERE project_id=?
        ORDER BY finished_at_utc DESC, id ASC
        LIMIT ?
        """,
        (project_id, max(1, int(limit))),
    ).fetchall()
    trajectories = _find_trajectories_by_ids(conn, [str(row["id"]) for row in rows])
    from .export_context import select_canonical_trajectories

    return select_canonical_trajectories(trajectories)


def write_projection_run(
    conn: sqlite3.Connection,
    run: TrajectoryProjectionRun,
) -> None:
    conn.execute(
        """
        INSERT INTO memory_trajectory_projection_runs(
            id, project_id, repo_root_digest, projection_version, started_at_utc,
            finished_at_utc, status, workflows_seen, trajectories_created,
            trajectories_updated, trajectories_unchanged, legacy_event_count, message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run.id,
            run.project_id,
            run.repo_root_digest,
            run.projection_version,
            run.started_at_utc,
            run.finished_at_utc,
            run.status,
            run.workflows_seen,
            run.trajectories_created,
            run.trajectories_updated,
            run.trajectories_unchanged,
            run.legacy_event_count,
            run.message,
        ),
    )


def list_trajectories(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    limit: int = 20,
) -> list[TrajectoryListItem]:
    rows = conn.execute(
        """
        SELECT id, workflow_id, outcome, quality_tier, quality_score, event_count,
               started_at_utc, finished_at_utc, summary
        FROM memory_trajectories
        WHERE project_id=?
        ORDER BY finished_at_utc DESC, id ASC
        LIMIT ?
        """,
        (project_id, max(1, int(limit))),
    ).fetchall()
    return [
        TrajectoryListItem(
            id=str(row["id"]),
            workflow_id=str(row["workflow_id"]),
            outcome=str(row["outcome"]),
            quality_tier=str(row["quality_tier"]),
            quality_score=int(row["quality_score"]),
            event_count=int(row["event_count"]),
            started_at_utc=str(row["started_at_utc"]),
            finished_at_utc=str(row["finished_at_utc"]),
            summary=str(row["summary"]),
        )
        for row in rows
    ]


def list_trajectories_for_subjects(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    subjects: Mapping[str, Sequence[str]],
    limit: int = 20,
) -> list[Trajectory]:
    pairs = tuple(
        (kind, key)
        for kind, keys in sorted(subjects.items())
        for key in sorted(set(keys))
        if key
    )
    if not pairs:
        return []
    clauses = " OR ".join(
        "(s.subject_kind=? AND s.subject_key=?)" for _kind, _key in pairs
    )
    params: list[object] = [project_id]
    for kind, key in pairs:
        params.extend([kind, key])
    rows = conn.execute(
        f"""
        SELECT DISTINCT t.id, t.finished_at_utc
        FROM memory_trajectories t
        JOIN memory_trajectory_subjects s ON s.trajectory_id = t.id
        WHERE t.project_id=? AND ({clauses})
        ORDER BY t.finished_at_utc DESC, t.id ASC
        LIMIT ?
        """,
        (*params, max(1, int(limit))),
    ).fetchall()
    return _find_trajectories_by_ids(conn, [str(row["id"]) for row in rows])


def search_trajectories(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    query: str,
    limit: int = 20,
    match_mode: SearchMatchMode = "any",
) -> list[Trajectory]:
    tokens = tokenize_query(query)
    if not tokens:
        return []
    token_clauses: list[str] = []
    params: list[object] = [project_id]
    for token in tokens:
        escaped = _escape_like(token)
        token_clauses.append(
            "("
            "LOWER(t.summary) LIKE ? ESCAPE '\\' OR "
            "LOWER(t.workflow_id) LIKE ? ESCAPE '\\' OR "
            "LOWER(t.labels_json) LIKE ? ESCAPE '\\' OR "
            "EXISTS ("
            "SELECT 1 FROM memory_trajectory_subjects s "
            "WHERE s.trajectory_id=t.id AND "
            "LOWER(s.subject_key) LIKE ? ESCAPE '\\'"
            ") OR "
            "EXISTS ("
            "SELECT 1 FROM memory_trajectory_steps st "
            "WHERE st.trajectory_id=t.id AND "
            "(LOWER(st.event_type) LIKE ? ESCAPE '\\' OR "
            "LOWER(COALESCE(st.summary, '')) LIKE ? ESCAPE '\\')"
            ")"
            ")"
        )
        needle = f"%{escaped}%"
        params.extend([needle, needle, needle, needle, needle, needle])
    joiner = " AND " if match_mode == "all" else " OR "
    rows = conn.execute(
        f"""
        SELECT t.id
        FROM memory_trajectories t
        WHERE t.project_id=? AND ({joiner.join(token_clauses)})
        ORDER BY t.finished_at_utc DESC, t.id ASC
        LIMIT ?
        """,
        (*params, max(1, int(limit))),
    ).fetchall()
    return _find_trajectories_by_ids(conn, [str(row["id"]) for row in rows])


def find_trajectory(conn: sqlite3.Connection, trajectory_id: str) -> Trajectory | None:
    row = conn.execute(
        "SELECT * FROM memory_trajectories WHERE id=?",
        (trajectory_id,),
    ).fetchone()
    if row is None:
        return None
    steps = _steps_for_trajectory(conn, trajectory_id)
    subjects = _subjects_for_trajectory(conn, trajectory_id)
    evidence = _evidence_for_trajectory(conn, trajectory_id)
    return Trajectory(
        id=str(row["id"]),
        project_id=str(row["project_id"]),
        repo_root_digest=str(row["repo_root_digest"]),
        workflow_id=str(row["workflow_id"]),
        intent_id=_optional_text(row["intent_id"]),
        primary_run_id=_optional_text(row["primary_run_id"]),
        first_run_id=_optional_text(row["first_run_id"]),
        last_run_id=_optional_text(row["last_run_id"]),
        report_digest=_optional_text(row["report_digest"]),
        outcome=str(row["outcome"]),  # type: ignore[arg-type]
        quality_tier=str(row["quality_tier"]),  # type: ignore[arg-type]
        quality_score=int(row["quality_score"]),
        labels=tuple(orjson.loads(str(row["labels_json"]))),
        summary=str(row["summary"]),
        trajectory_digest=str(row["trajectory_digest"]),
        source_event_stream_digest=str(row["source_event_stream_digest"]),
        projection_version=str(row["projection_version"]),
        event_count=int(row["event_count"]),
        step_count=int(row["step_count"]),
        incident_count=int(row["incident_count"]),
        started_at_utc=str(row["started_at_utc"]),
        finished_at_utc=str(row["finished_at_utc"]),
        projected_at_utc=str(row["projected_at_utc"]),
        updated_at_utc=str(row["updated_at_utc"]),
        steps=tuple(steps),
        subjects=tuple(subjects),
        evidence=tuple(evidence),
    )


def _find_trajectories_by_ids(
    conn: sqlite3.Connection,
    ids: Sequence[str],
) -> list[Trajectory]:
    hydrated: list[Trajectory] = []
    for trajectory_id in ids:
        trajectory = find_trajectory(conn, trajectory_id)
        if trajectory is not None:
            hydrated.append(trajectory)
    return hydrated


def count_trajectories(conn: sqlite3.Connection, *, project_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM memory_trajectories WHERE project_id=?",
        (project_id,),
    ).fetchone()
    return int(row[0]) if row is not None else 0


def latest_projection_run(
    conn: sqlite3.Connection,
    *,
    project_id: str,
) -> TrajectoryProjectionRun | None:
    row = conn.execute(
        "SELECT * FROM memory_trajectory_projection_runs WHERE project_id=? "
        "ORDER BY finished_at_utc DESC, id DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    if row is None:
        return None
    return TrajectoryProjectionRun(
        id=str(row["id"]),
        project_id=str(row["project_id"]),
        repo_root_digest=str(row["repo_root_digest"]),
        projection_version=str(row["projection_version"]),
        started_at_utc=str(row["started_at_utc"]),
        finished_at_utc=str(row["finished_at_utc"]),
        status=str(row["status"]),
        workflows_seen=int(row["workflows_seen"]),
        trajectories_created=int(row["trajectories_created"]),
        trajectories_updated=int(row["trajectories_updated"]),
        trajectories_unchanged=int(row["trajectories_unchanged"]),
        legacy_event_count=int(row["legacy_event_count"]),
        message=_optional_text(row["message"]),
    )


def _group_by_workflow(
    events: Sequence[AuditRecord],
) -> dict[str, tuple[AuditRecord, ...]]:
    grouped: defaultdict[str, list[AuditRecord]] = defaultdict(list)
    for event in events:
        if event.workflow_id:
            grouped[event.workflow_id].append(event)
    return {
        workflow_id: tuple(
            sorted(records, key=lambda item: (item.audit_sequence or 0, item.event_id))
        )
        for workflow_id, records in sorted(grouped.items())
    }


def _insert_steps(conn: sqlite3.Connection, trajectory: Trajectory) -> None:
    conn.executemany(
        """
        INSERT INTO memory_trajectory_steps(
            trajectory_id, step_index, audit_sequence, event_id, event_type, status,
            run_id, report_digest, event_core_sha256, event_core_json, summary,
            created_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                trajectory.id,
                step.step_index,
                step.audit_sequence,
                step.event_id,
                step.event_type,
                step.status,
                step.run_id,
                step.report_digest,
                step.event_core_sha256,
                step.event_core_json,
                step.summary,
                step.created_at_utc,
            )
            for step in trajectory.steps
        ],
    )


def _insert_subjects(
    conn: sqlite3.Connection,
    trajectory_id: str,
    subjects: Iterable[TrajectorySubject],
) -> None:
    conn.executemany(
        """
        INSERT OR IGNORE INTO memory_trajectory_subjects(
            trajectory_id, subject_kind, subject_key, relation
        ) VALUES (?, ?, ?, ?)
        """,
        [
            (trajectory_id, subject.subject_kind, subject.subject_key, subject.relation)
            for subject in subjects
        ],
    )


def _insert_evidence(
    conn: sqlite3.Connection,
    trajectory_id: str,
    evidence: Iterable[TrajectoryEvidence],
) -> None:
    conn.executemany(
        """
        INSERT OR IGNORE INTO memory_trajectory_evidence(
            trajectory_id, evidence_kind, ref, locator, digest, created_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                trajectory_id,
                item.evidence_kind,
                item.ref,
                item.locator,
                item.digest,
                item.created_at_utc,
            )
            for item in evidence
        ],
    )


def _steps_for_trajectory(
    conn: sqlite3.Connection,
    trajectory_id: str,
) -> list[TrajectoryStep]:
    rows = conn.execute(
        "SELECT * FROM memory_trajectory_steps WHERE trajectory_id=? "
        "ORDER BY step_index ASC",
        (trajectory_id,),
    ).fetchall()
    return [
        TrajectoryStep(
            step_index=int(row["step_index"]),
            audit_sequence=int(row["audit_sequence"]),
            event_id=str(row["event_id"]),
            event_type=str(row["event_type"]),
            status=_optional_text(row["status"]),
            run_id=_optional_text(row["run_id"]),
            report_digest=_optional_text(row["report_digest"]),
            event_core_sha256=str(row["event_core_sha256"]),
            event_core_json=str(row["event_core_json"]),
            summary=_optional_text(row["summary"]),
            created_at_utc=str(row["created_at_utc"]),
        )
        for row in rows
    ]


def _subjects_for_trajectory(
    conn: sqlite3.Connection,
    trajectory_id: str,
) -> list[TrajectorySubject]:
    rows = conn.execute(
        "SELECT subject_kind, subject_key, relation FROM memory_trajectory_subjects "
        "WHERE trajectory_id=? ORDER BY subject_kind ASC, subject_key ASC",
        (trajectory_id,),
    ).fetchall()
    return [
        TrajectorySubject(
            subject_kind=str(row["subject_kind"]),
            subject_key=str(row["subject_key"]),
            relation=str(row["relation"]),
        )
        for row in rows
    ]


def _evidence_for_trajectory(
    conn: sqlite3.Connection,
    trajectory_id: str,
) -> list[TrajectoryEvidence]:
    rows = conn.execute(
        "SELECT evidence_kind, ref, locator, digest, created_at_utc "
        "FROM memory_trajectory_evidence WHERE trajectory_id=? "
        "ORDER BY created_at_utc ASC, evidence_kind ASC, ref ASC",
        (trajectory_id,),
    ).fetchall()
    return [
        TrajectoryEvidence(
            evidence_kind=str(row["evidence_kind"]),
            ref=str(row["ref"]),
            locator=_optional_text(row["locator"]),
            digest=_optional_text(row["digest"]),
            created_at_utc=str(row["created_at_utc"]),
        )
        for row in rows
    ]


def _projection_run_id(
    *,
    project_id: str,
    repo_root_digest: str,
    projection_version: str,
    started_at_utc: str,
    workflow_count: int,
) -> str:
    payload = json_text(
        {
            "project_id": project_id,
            "repo_root_digest": repo_root_digest,
            "projection_version": projection_version,
            "started_at_utc": started_at_utc,
            "workflow_count": workflow_count,
            "nonce": uuid.uuid4().hex,
        },
        sort_keys=True,
    )
    return f"trajrun-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def _json_array(values: Sequence[str]) -> str:
    return json_text(list(values), sort_keys=True)


def _json_object(payload: Mapping[str, object]) -> str:
    return json_text(payload, sort_keys=True)


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_").lower()


def upsert_trajectory_patch_trail(
    conn: sqlite3.Connection,
    *,
    trajectory_id: str,
    patch_trail_json: str,
    patch_trail_digest: str,
    schema_version: str,
    projected_at_utc: str,
) -> None:
    conn.execute(
        """
        INSERT INTO memory_trajectory_patch_trails(
            trajectory_id, patch_trail_digest, patch_trail_json,
            schema_version, projected_at_utc
        ) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(trajectory_id) DO UPDATE SET
            patch_trail_digest=excluded.patch_trail_digest,
            patch_trail_json=excluded.patch_trail_json,
            schema_version=excluded.schema_version,
            projected_at_utc=excluded.projected_at_utc
        """,
        (
            trajectory_id,
            patch_trail_digest,
            patch_trail_json,
            schema_version,
            projected_at_utc,
        ),
    )


def load_trajectory_patch_trail(
    conn: sqlite3.Connection,
    *,
    trajectory_id: str,
) -> dict[str, object] | None:
    row = conn.execute(
        """
        SELECT patch_trail_json
        FROM memory_trajectory_patch_trails
        WHERE trajectory_id=?
        """,
        (trajectory_id,),
    ).fetchone()
    if row is None:
        return None
    loaded = orjson.loads(str(row["patch_trail_json"]))
    return loaded if isinstance(loaded, dict) else None


__all__ = [
    "count_trajectories",
    "find_trajectory",
    "latest_projection_run",
    "list_trajectories",
    "list_trajectories_for_subjects",
    "load_trajectory_patch_trail",
    "rebuild_trajectories_from_audit",
    "search_trajectories",
    "upsert_trajectory",
    "upsert_trajectory_patch_trail",
    "write_projection_run",
]
