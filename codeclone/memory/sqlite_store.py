# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import cast

from ..report.meta import current_report_timestamp_utc
from ..utils.iterutils import chunked
from .enums import LinkRelation
from .experience.models import Experience
from .locks import memory_init_lock
from .models import (
    IngestionRun,
    MemoryEvidence,
    MemoryLink,
    MemoryProject,
    MemoryQuery,
    MemoryRecord,
    MemoryRevision,
    MemorySubject,
    RecordBatch,
    UpsertAction,
    UpsertResult,
    generate_memory_id,
    parse_payload_json,
    payload_json_text,
)
from .schema import get_meta, open_memory_db, set_meta
from .search_index import (
    SearchMatchMode,
    build_search_text,
    fts_match_expression,
    tokenize_query,
)
from .trajectory.models import (
    Trajectory,
    TrajectoryListItem,
    TrajectoryProjectionResult,
    TrajectoryProjectionRun,
)

_SQLITE_IN_QUERY_BATCH = 500


class SqliteEngineeringMemoryStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._closed = False
        self._conn = open_memory_db(db_path)
        self._conn.row_factory = sqlite3.Row

    @property
    def db_path(self) -> Path:
        return self._db_path

    def initialize(self, project: MemoryProject) -> None:
        now = current_report_timestamp_utc()
        self._conn.execute(
            """
            INSERT INTO memory_projects(
                id, root, git_remote, git_branch, git_head, python_tag,
                created_at_utc, updated_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                root=excluded.root,
                git_remote=excluded.git_remote,
                git_branch=excluded.git_branch,
                git_head=excluded.git_head,
                python_tag=excluded.python_tag,
                updated_at_utc=excluded.updated_at_utc
            """,
            (
                project.id,
                project.root,
                project.git_remote,
                project.git_branch,
                project.git_head,
                project.python_tag,
                project.created_at_utc,
                project.updated_at_utc,
            ),
        )
        set_meta(self._conn, "project_id", project.id)
        set_meta(self._conn, "project_root", project.root)
        set_meta(self._conn, "updated_at_utc", now)
        self._conn.commit()

    def get_meta(self, key: str) -> str | None:
        return get_meta(self._conn, key)

    def set_meta(self, key: str, value: str) -> None:
        set_meta(self._conn, key, value)
        set_meta(self._conn, "updated_at_utc", current_report_timestamp_utc())
        self._conn.commit()

    def rebuild_trajectories_from_audit(
        self,
        *,
        project: MemoryProject,
        root_path: Path,
        audit_db_path: Path,
    ) -> TrajectoryProjectionResult:
        from .trajectory.store import rebuild_trajectories_from_audit

        return rebuild_trajectories_from_audit(
            conn=self._conn,
            project=project,
            root_path=root_path,
            audit_db_path=audit_db_path,
        )

    def rebuild_trajectories_incremental(
        self,
        *,
        project: MemoryProject,
        root_path: Path,
        audit_db_path: Path,
        after_event_core_id: int,
    ) -> TrajectoryProjectionResult:
        from .trajectory.store import rebuild_trajectories_incremental

        return rebuild_trajectories_incremental(
            conn=self._conn,
            project=project,
            root_path=root_path,
            audit_db_path=audit_db_path,
            after_event_core_id=after_event_core_id,
        )

    def count_trajectories(self, *, project_id: str) -> int:
        from .trajectory.store import count_trajectories

        return count_trajectories(self._conn, project_id=project_id)

    def latest_trajectory_projection_run(
        self,
        *,
        project_id: str,
    ) -> TrajectoryProjectionRun | None:
        from .trajectory.store import latest_projection_run

        return latest_projection_run(self._conn, project_id=project_id)

    def list_trajectories(
        self,
        *,
        project_id: str,
        limit: int = 20,
    ) -> list[TrajectoryListItem]:
        from .trajectory.store import list_trajectories

        return list_trajectories(self._conn, project_id=project_id, limit=limit)

    def list_trajectories_for_subjects(
        self,
        *,
        project_id: str,
        subjects: Mapping[str, Sequence[str]],
        limit: int = 20,
    ) -> list[Trajectory]:
        from .trajectory.store import list_trajectories_for_subjects

        return list_trajectories_for_subjects(
            self._conn,
            project_id=project_id,
            subjects=subjects,
            limit=limit,
        )

    def search_trajectories(
        self,
        *,
        project_id: str,
        query: str,
        limit: int = 20,
        match_mode: SearchMatchMode = "any",
    ) -> list[Trajectory]:
        from .trajectory.store import search_trajectories

        return search_trajectories(
            self._conn,
            project_id=project_id,
            query=query,
            limit=limit,
            match_mode=match_mode,
        )

    def find_trajectory(self, trajectory_id: str) -> Trajectory | None:
        from .trajectory.store import find_trajectory

        return find_trajectory(self._conn, trajectory_id)

    def find_trajectories(
        self,
        trajectory_ids: Sequence[str],
    ) -> list[Trajectory]:
        from .trajectory.store import find_trajectories_by_ids

        return find_trajectories_by_ids(self._conn, trajectory_ids)

    def load_trajectory_patch_trail(
        self,
        trajectory_id: str,
    ) -> dict[str, object] | None:
        from .trajectory.store import load_trajectory_patch_trail

        return load_trajectory_patch_trail(self._conn, trajectory_id=trajectory_id)

    def load_trajectory_patch_trails(
        self,
        trajectory_ids: Sequence[str],
    ) -> dict[str, dict[str, object]]:
        from .trajectory.store import load_trajectory_patch_trails

        return load_trajectory_patch_trails(
            self._conn,
            trajectory_ids=trajectory_ids,
        )

    def find_trajectory_patch_trails_for_lookup(
        self,
        *,
        project_id: str,
        patch_trail_digest: str | None = None,
        run_id: str | None = None,
    ) -> tuple[list[dict[str, object]], int]:
        from .trajectory.store import find_trajectory_patch_trails_for_lookup

        return find_trajectory_patch_trails_for_lookup(
            self._conn,
            project_id=project_id,
            patch_trail_digest=patch_trail_digest,
            run_id=run_id,
        )

    def list_canonical_trajectories_for_export(
        self,
        *,
        project_id: str,
        limit: int = 10_000,
    ) -> list[Trajectory]:
        from .trajectory.store import list_canonical_trajectories_for_export

        return list_canonical_trajectories_for_export(
            self._conn,
            project_id=project_id,
            limit=limit,
        )

    def replace_experiences(
        self,
        *,
        project_id: str,
        experiences: Sequence[Experience],
    ) -> int:
        from .experience.store import replace_experiences

        return replace_experiences(
            self._conn, project_id=project_id, experiences=experiences
        )

    def list_experiences(self, *, project_id: str) -> list[Experience]:
        from .experience.store import list_experiences

        return list_experiences(self._conn, project_id=project_id)

    def count_experiences(self, *, project_id: str) -> int:
        from .experience.store import count_experiences

        return count_experiences(self._conn, project_id=project_id)

    def find_experience(self, experience_id: str) -> Experience | None:
        from .experience.store import find_experience

        return find_experience(self._conn, experience_id=experience_id)

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def write_record(self, record: MemoryRecord) -> None:
        self._insert_record(record)
        self._conn.commit()

    def _commit_upsert_result(
        self,
        *,
        action: UpsertAction,
        record_id: str,
        sync_fts: bool,
        revision_written: bool = False,
        commit: bool = True,
    ) -> UpsertResult:
        if commit:
            self._conn.commit()
        if sync_fts:
            self.sync_fts_record(record_id)
        return UpsertResult(
            action=action,
            record_id=record_id,
            revision_written=revision_written,
        )

    def upsert_record(
        self, record: MemoryRecord, *, commit: bool = True
    ) -> UpsertResult:
        existing = self.find_by_identity_key(record.project_id, record.identity_key)
        now = current_report_timestamp_utc()
        if existing is not None and (
            existing.origin == "human" or existing.approved_by
        ):
            self._conn.execute(
                """
                UPDATE memory_records
                SET last_verified_at_utc=?, updated_at_utc=?,
                    verified_on_branch=?, verified_at_commit=?
                WHERE id=?
                """,
                (
                    now,
                    now,
                    record.verified_on_branch,
                    record.verified_at_commit,
                    existing.id,
                ),
            )
            if commit:
                self._conn.commit()
            return UpsertResult(action="skipped", record_id=existing.id)

        revision_written = False
        action: UpsertAction
        if existing is None:
            self._insert_record(record)
            target_id = record.id
            action = "created"
        elif _record_content_equal(existing, record):
            self._conn.execute(
                """
                UPDATE memory_records SET
                    last_verified_at_utc=?, updated_at_utc=?,
                    verified_on_branch=?, verified_at_commit=?,
                    report_digest=?, code_fingerprint=?,
                    status='active', stale_reason=NULL
                WHERE id=?
                """,
                (
                    now,
                    now,
                    record.verified_on_branch,
                    record.verified_at_commit,
                    record.report_digest,
                    record.code_fingerprint,
                    existing.id,
                ),
            )
            target_id = existing.id
            action = "unchanged"
        else:
            revision_number = self._next_revision_number(existing.id)
            self.write_revision(
                MemoryRevision(
                    id=generate_memory_id(prefix="rev"),
                    memory_id=existing.id,
                    revision_number=revision_number,
                    previous_statement=existing.statement,
                    new_statement=record.statement,
                    previous_payload=existing.payload,
                    new_payload=record.payload,
                    reason="upsert_content_changed",
                    changed_by=record.created_by,
                    changed_at_utc=now,
                    branch=record.verified_on_branch,
                    commit=record.verified_at_commit,
                )
            )
            self._conn.execute(
                """
                UPDATE memory_records SET
                    statement=?, summary=?, payload_json=?, status=?, confidence=?,
                    ingest_source=?, updated_at_utc=?, last_verified_at_utc=?,
                    report_digest=?, code_fingerprint=?, verified_on_branch=?,
                    verified_at_commit=?, schema_version=?
                WHERE id=?
                """,
                (
                    record.statement,
                    record.summary,
                    payload_json_text(record.payload),
                    record.status,
                    record.confidence,
                    record.ingest_source,
                    now,
                    now,
                    record.report_digest,
                    record.code_fingerprint,
                    record.verified_on_branch,
                    record.verified_at_commit,
                    record.schema_version,
                    existing.id,
                ),
            )
            target_id = existing.id
            action = "updated"
            revision_written = True

        return self._commit_upsert_result(
            action=action,
            record_id=target_id,
            sync_fts=True,
            revision_written=revision_written,
            commit=commit,
        )

    def find_record(self, record_id: str) -> MemoryRecord | None:
        row = self._conn.execute(
            "SELECT * FROM memory_records WHERE id=?",
            (record_id,),
        ).fetchone()
        if row is None:
            return None
        return _record_from_row(row)

    def find_by_identity_key(self, project_id: str, key: str) -> MemoryRecord | None:
        row = self._conn.execute(
            "SELECT * FROM memory_records WHERE project_id=? AND identity_key=?",
            (project_id, key),
        ).fetchone()
        if row is None:
            return None
        return _record_from_row(row)

    def query_records(self, query: MemoryQuery) -> Sequence[MemoryRecord]:
        clauses = ["project_id=?"]
        params: list[object] = [query.project_id]
        if query.types:
            placeholders = ", ".join("?" for _ in query.types)
            clauses.append(f"type IN ({placeholders})")
            params.extend(query.types)
        if query.statuses:
            placeholders = ", ".join("?" for _ in query.statuses)
            clauses.append(f"status IN ({placeholders})")
            params.extend(query.statuses)
        if query.subject_kind and query.subject_key:
            clauses.append(
                "id IN (SELECT memory_id FROM memory_subjects "
                "WHERE subject_kind=? AND subject_key=?)"
            )
            params.extend([query.subject_kind, query.subject_key])
        elif query.subject_kind and query.subject_key_prefix:
            clauses.append(
                "id IN (SELECT memory_id FROM memory_subjects "
                "WHERE subject_kind=? AND subject_key LIKE ?)"
            )
            params.extend([query.subject_kind, f"{query.subject_key_prefix}%"])
        where = " AND ".join(clauses)
        rows = self._conn.execute(
            f"SELECT * FROM memory_records WHERE {where} "
            "ORDER BY updated_at_utc DESC, id ASC LIMIT ? OFFSET ?",
            (*params, query.limit, query.offset),
        ).fetchall()
        return [_record_from_row(row) for row in rows]

    def list_subjects_for_memory(self, memory_id: str) -> list[MemorySubject]:
        rows = self._conn.execute(
            """
            SELECT MIN(id) AS id, memory_id, subject_kind, subject_key, relation
            FROM memory_subjects
            WHERE memory_id=?
            GROUP BY memory_id, subject_kind, subject_key, relation
            ORDER BY subject_kind ASC, subject_key ASC, id ASC
            """,
            (memory_id,),
        ).fetchall()
        return [
            MemorySubject(
                id=str(row["id"]),
                memory_id=str(row["memory_id"]),
                subject_kind=str(row["subject_kind"]),  # type: ignore[arg-type]
                subject_key=str(row["subject_key"]),
                relation=str(row["relation"]),  # type: ignore[arg-type]
            )
            for row in rows
        ]

    def list_subjects_for_memories(
        self,
        memory_ids: Sequence[str],
    ) -> dict[str, list[MemorySubject]]:
        normalized_ids = tuple(sorted(set(memory_ids)))
        grouped: dict[str, list[MemorySubject]] = {
            memory_id: [] for memory_id in normalized_ids
        }
        for batch in chunked(normalized_ids, _SQLITE_IN_QUERY_BATCH):
            placeholders = ", ".join("?" for _ in batch)
            rows = self._conn.execute(
                f"""
                SELECT MIN(id) AS id, memory_id, subject_kind, subject_key, relation
                FROM memory_subjects
                WHERE memory_id IN ({placeholders})
                GROUP BY memory_id, subject_kind, subject_key, relation
                ORDER BY memory_id ASC, subject_kind ASC, subject_key ASC, id ASC
                """,
                batch,
            ).fetchall()
            for row in rows:
                memory_id = str(row["memory_id"])
                grouped[memory_id].append(
                    MemorySubject(
                        id=str(row["id"]),
                        memory_id=memory_id,
                        subject_kind=str(row["subject_kind"]),  # type: ignore[arg-type]
                        subject_key=str(row["subject_key"]),
                        relation=str(row["relation"]),  # type: ignore[arg-type]
                    )
                )
        return grouped

    def list_evidence_for_memory(self, memory_id: str) -> list[MemoryEvidence]:
        rows = self._conn.execute(
            """
            SELECT id, memory_id, evidence_kind, ref, locator, quote, digest,
                   created_at_utc
            FROM memory_evidence
            WHERE memory_id=?
            ORDER BY created_at_utc ASC, id ASC
            """,
            (memory_id,),
        ).fetchall()
        return [
            MemoryEvidence(
                id=str(row["id"]),
                memory_id=str(row["memory_id"]),
                evidence_kind=str(row["evidence_kind"]),  # type: ignore[arg-type]
                ref=str(row["ref"]),
                locator=str(row["locator"]) if row["locator"] is not None else None,
                quote=str(row["quote"]) if row["quote"] is not None else None,
                digest=str(row["digest"]) if row["digest"] is not None else None,
                created_at_utc=str(row["created_at_utc"]),
            )
            for row in rows
        ]

    def count_evidence_for_memory(self, memory_id: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM memory_evidence WHERE memory_id=?",
            (memory_id,),
        ).fetchone()
        return int(row[0]) if row is not None else 0

    def count_evidence_for_memories(
        self,
        memory_ids: Sequence[str],
    ) -> dict[str, int]:
        normalized_ids = tuple(sorted(set(memory_ids)))
        counts = dict.fromkeys(normalized_ids, 0)
        for batch in chunked(normalized_ids, _SQLITE_IN_QUERY_BATCH):
            placeholders = ", ".join("?" for _ in batch)
            rows = self._conn.execute(
                f"""
                SELECT memory_id, COUNT(*) AS evidence_count
                FROM memory_evidence
                WHERE memory_id IN ({placeholders})
                GROUP BY memory_id
                ORDER BY memory_id ASC
                """,
                batch,
            ).fetchall()
            for row in rows:
                counts[str(row["memory_id"])] = int(row["evidence_count"])
        return counts

    def search_records(
        self,
        *,
        project_id: str,
        statement_query: str,
        types: Sequence[str] = (),
        statuses: Sequence[str] = (),
        confidences: Sequence[str] = (),
        limit: int = 100,
        match_mode: SearchMatchMode = "any",
    ) -> list[MemoryRecord]:
        if self._fts_available():
            ranked = self._search_records_fts(
                project_id=project_id,
                statement_query=statement_query,
                types=types,
                statuses=statuses,
                confidences=confidences,
                limit=limit,
                match_mode=match_mode,
            )
            if ranked is not None:
                return ranked
        return self._search_records_like(
            project_id=project_id,
            statement_query=statement_query,
            types=types,
            statuses=statuses,
            confidences=confidences,
            limit=limit,
            match_mode=match_mode,
        )

    def sync_fts_record(self, memory_id: str) -> None:
        if not self._fts_available():
            return
        record = self.find_record(memory_id)
        if record is None:
            self._conn.execute(
                "DELETE FROM memory_records_fts WHERE memory_id=?",
                (memory_id,),
            )
            return
        subjects = self.list_subjects_for_memory(memory_id)
        self._upsert_fts_record(record, subjects)

    def rebuild_project_fts(self, project_id: str) -> int:
        if not self._fts_available():
            return 0
        self._conn.execute(
            "DELETE FROM memory_records_fts WHERE project_id=?",
            (project_id,),
        )
        count = 0
        for record in self.list_records_for_project(project_id):
            subjects = self.list_subjects_for_memory(record.id)
            self._upsert_fts_record(record, subjects)
            count += 1
        self._conn.commit()
        return count

    def _fts_available(self) -> bool:
        row = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE name='memory_records_fts'"
        ).fetchone()
        return row is not None

    def _upsert_fts_record(
        self,
        record: MemoryRecord,
        subjects: Sequence[MemorySubject],
    ) -> None:
        search_text = build_search_text(record=record, subjects=subjects)
        self._conn.execute(
            "DELETE FROM memory_records_fts WHERE memory_id=?",
            (record.id,),
        )
        self._conn.execute(
            """
            INSERT INTO memory_records_fts(
                memory_id, project_id, record_type, ingest_source, status, search_text
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                record.id,
                record.project_id,
                record.type,
                record.ingest_source,
                record.status,
                search_text,
            ),
        )

    def _search_records_fts(
        self,
        *,
        project_id: str,
        statement_query: str,
        types: Sequence[str],
        statuses: Sequence[str],
        confidences: Sequence[str],
        limit: int,
        match_mode: SearchMatchMode,
    ) -> list[MemoryRecord] | None:
        match_expr = fts_match_expression(statement_query, match_mode=match_mode)
        if match_expr is None:
            return []
        clauses = [
            "memory_records_fts MATCH ?",
            "memory_records_fts.project_id = ?",
        ]
        params: list[object] = [match_expr, project_id]
        _append_search_filters(
            clauses,
            params,
            types,
            statuses,
            confidences,
            type_column="memory_records_fts.record_type",
            status_column="memory_records_fts.status",
            confidence_via_subquery=True,
        )
        where = " AND ".join(clauses)
        rows = self._conn.execute(
            f"""
            SELECT memory_records.*
            FROM memory_records_fts
            JOIN memory_records ON memory_records.id = memory_records_fts.memory_id
            WHERE {where}
            ORDER BY bm25(memory_records_fts), memory_records.updated_at_utc DESC,
                     memory_records.id ASC
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()
        return [_record_from_row(row) for row in rows]

    def _search_records_like(
        self,
        *,
        project_id: str,
        statement_query: str,
        types: Sequence[str],
        statuses: Sequence[str],
        confidences: Sequence[str],
        limit: int,
        match_mode: SearchMatchMode,
    ) -> list[MemoryRecord]:
        tokens = tokenize_query(statement_query)
        if not tokens:
            return []
        clauses = ["project_id=?"]
        params: list[object] = [project_id]
        token_clauses: list[str] = []
        for token in tokens:
            token_clauses.append(
                "(LOWER(statement) LIKE ? ESCAPE '\\' OR LOWER(COALESCE(summary, '')) "
                "LIKE ? ESCAPE '\\')"
            )
            escaped = _escape_like(token)
            params.extend([f"%{escaped}%", f"%{escaped}%"])
        joiner = " AND " if match_mode == "all" else " OR "
        clauses.append(f"({joiner.join(token_clauses)})")
        _append_search_filters(
            clauses,
            params,
            types,
            statuses,
            confidences,
            type_column="type",
            status_column="status",
            confidence_via_subquery=False,
        )
        where = " AND ".join(clauses)
        rows = self._conn.execute(
            f"SELECT * FROM memory_records WHERE {where} "
            "ORDER BY updated_at_utc DESC, id ASC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [_record_from_row(row) for row in rows]

    def write_subject(self, subject: MemorySubject, *, commit: bool = True) -> None:
        existing = self._conn.execute(
            """
            SELECT id FROM memory_subjects
            WHERE memory_id=? AND subject_kind=? AND subject_key=? AND relation=?
            LIMIT 1
            """,
            (
                subject.memory_id,
                subject.subject_kind,
                subject.subject_key,
                subject.relation,
            ),
        ).fetchone()
        if existing is not None:
            return
        self._conn.execute(
            """
            INSERT INTO memory_subjects(
                id, memory_id, subject_kind, subject_key, relation
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                subject.id,
                subject.memory_id,
                subject.subject_kind,
                subject.subject_key,
                subject.relation,
            ),
        )
        if commit:
            self._conn.commit()  # standalone writes must survive store.close()

    def prune_duplicate_subjects(self, *, commit: bool = True) -> int:
        before = self._conn.execute("SELECT COUNT(*) FROM memory_subjects").fetchone()
        before_count = int(before[0]) if before is not None else 0
        self._conn.execute(
            """
            DELETE FROM memory_subjects
            WHERE id NOT IN (
                SELECT MIN(id)
                FROM memory_subjects
                GROUP BY memory_id, subject_kind, subject_key, relation
            )
            """
        )
        after = self._conn.execute("SELECT COUNT(*) FROM memory_subjects").fetchone()
        after_count = int(after[0]) if after is not None else 0
        removed = max(0, before_count - after_count)
        if commit and removed:
            self._conn.commit()
        return removed

    def write_evidence(self, evidence: MemoryEvidence) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO memory_evidence(
                id, memory_id, evidence_kind, ref, locator, quote, digest,
                created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evidence.id,
                evidence.memory_id,
                evidence.evidence_kind,
                evidence.ref,
                evidence.locator,
                evidence.quote,
                evidence.digest,
                evidence.created_at_utc,
            ),
        )

    def write_link(self, link: MemoryLink) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO memory_links(
                id, project_id, from_memory_id, to_memory_id, relation,
                created_by, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                link.id,
                link.project_id,
                link.from_memory_id,
                link.to_memory_id,
                link.relation,
                link.created_by,
                link.created_at_utc,
            ),
        )

    def list_links_for_records(
        self,
        *,
        project_id: str,
        record_ids: Sequence[str],
        relations: Sequence[LinkRelation],
    ) -> list[MemoryLink]:
        """Typed links (in either direction) touching the given records.

        The 1-hop neighbourhood for honest retrieval: deterministic order, the
        other endpoint may be outside the queried set (surfaced as a relation,
        never as a new scope hit).
        """
        ids = list(record_ids)
        rels = list(relations)
        if not ids or not rels:
            return []
        id_ph = ",".join("?" * len(ids))
        rel_ph = ",".join("?" * len(rels))
        rows = self._conn.execute(
            "SELECT id, project_id, from_memory_id, to_memory_id, relation, "
            "created_by, created_at_utc FROM memory_links "
            f"WHERE project_id=? AND relation IN ({rel_ph}) "
            f"AND (from_memory_id IN ({id_ph}) OR to_memory_id IN ({id_ph})) "
            "ORDER BY from_memory_id ASC, to_memory_id ASC, relation ASC",
            (project_id, *rels, *ids, *ids),
        ).fetchall()
        return [
            MemoryLink(
                id=str(row["id"]),
                project_id=str(row["project_id"]),
                from_memory_id=str(row["from_memory_id"]),
                to_memory_id=str(row["to_memory_id"]),
                relation=cast(LinkRelation, str(row["relation"])),
                created_by=str(row["created_by"]),
                created_at_utc=str(row["created_at_utc"]),
            )
            for row in rows
        ]

    def write_ingestion_run(self, run: IngestionRun) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO memory_ingestion_runs(
                id, project_id, mode, started_at_utc, finished_at_utc, status,
                analysis_fingerprint, report_digest, branch, "commit",
                records_created, records_updated, records_marked_stale,
                candidates_created, contradictions_found, message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.id,
                run.project_id,
                run.mode,
                run.started_at_utc,
                run.finished_at_utc,
                run.status,
                run.analysis_fingerprint,
                run.report_digest,
                run.branch,
                run.commit,
                run.records_created,
                run.records_updated,
                run.records_marked_stale,
                run.candidates_created,
                run.contradictions_found,
                run.message,
            ),
        )
        self._conn.commit()

    def write_revision(self, revision: MemoryRevision) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO memory_revisions(
                id, memory_id, revision_number, previous_statement, new_statement,
                previous_payload, new_payload, reason, changed_by, changed_at_utc,
                branch, "commit"
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                revision.id,
                revision.memory_id,
                revision.revision_number,
                revision.previous_statement,
                revision.new_statement,
                payload_json_text(revision.previous_payload),
                payload_json_text(revision.new_payload),
                revision.reason,
                revision.changed_by,
                revision.changed_at_utc,
                revision.branch,
                revision.commit,
            ),
        )

    def _update_lifecycle_status(
        self,
        record_id: str,
        *,
        status: str,
        stale_reason: str | None,
        commit: bool,
    ) -> None:
        now = current_report_timestamp_utc()
        self._conn.execute(
            """
            UPDATE memory_records
            SET status=?, stale_reason=?, updated_at_utc=?
            WHERE id=?
            """,
            (status, stale_reason, now, record_id),
        )
        if commit:
            self._conn.commit()
        self.sync_fts_record(record_id)

    def mark_stale(self, record_id: str, reason: str, *, commit: bool = True) -> None:
        self._update_lifecycle_status(
            record_id,
            status="stale",
            stale_reason=reason,
            commit=commit,
        )

    def mark_historical(self, record_id: str, *, commit: bool = True) -> None:
        self._update_lifecycle_status(
            record_id,
            status="historical",
            stale_reason=None,
            commit=commit,
        )

    def restore_anchor_active(self, record_id: str, *, commit: bool = True) -> None:
        self._update_lifecycle_status(
            record_id,
            status="active",
            stale_reason=None,
            commit=commit,
        )

    def list_records_for_project(
        self,
        project_id: str,
        *,
        statuses: tuple[str, ...] = (),
        limit: int = 10000,
    ) -> list[MemoryRecord]:
        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            rows = self._conn.execute(
                f"SELECT * FROM memory_records WHERE project_id=? "
                f"AND status IN ({placeholders}) "
                "ORDER BY updated_at_utc DESC, id ASC LIMIT ?",
                (project_id, *statuses, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM memory_records WHERE project_id=? "
                "ORDER BY updated_at_utc DESC, id ASC LIMIT ?",
                (project_id, limit),
            ).fetchall()
        return [_record_from_row(row) for row in rows]

    def update_record_status(
        self,
        record_id: str,
        *,
        status: str,
        approved_by: str | None = None,
        approved_at_utc: str | None = None,
        stale_reason: str | None = None,
        commit: bool = True,
    ) -> None:
        now = current_report_timestamp_utc()
        self._conn.execute(
            """
            UPDATE memory_records
            SET status=?, approved_by=COALESCE(?, approved_by),
                approved_at_utc=COALESCE(?, approved_at_utc),
                stale_reason=?, updated_at_utc=?
            WHERE id=?
            """,
            (status, approved_by, approved_at_utc, stale_reason, now, record_id),
        )
        if commit:
            self._conn.commit()

    def count_records_by_status(self, project_id: str, status: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM memory_records WHERE project_id=? AND status=?",
            (project_id, status),
        ).fetchone()
        return int(row[0]) if row is not None else 0

    def delete_records_older_than(
        self,
        *,
        status: str,
        updated_before_utc: str,
        commit: bool = True,
    ) -> int:
        rows = self._conn.execute(
            "SELECT id FROM memory_records WHERE status=? AND updated_at_utc < ?",
            (status, updated_before_utc),
        ).fetchall()
        ids = [str(row["id"]) for row in rows]
        for record_id in ids:
            self._conn.execute(
                "DELETE FROM memory_records WHERE id=?",
                (record_id,),
            )
        if commit:
            self._conn.commit()
        return len(ids)

    def next_revision_number(self, memory_id: str) -> int:
        return self._next_revision_number(memory_id)

    def persist_batch(
        self, batch: RecordBatch, *, commit: bool = True
    ) -> dict[str, int]:
        stats = {"created": 0, "updated": 0, "unchanged": 0, "skipped": 0}
        record_id_map: dict[str, str] = {}
        for record in batch.records:
            result = self.upsert_record(record, commit=False)
            record_id_map[record.id] = result.record_id
            stats[result.action] = stats.get(result.action, 0) + 1
        for subject in batch.subjects:
            mapped_id = record_id_map.get(subject.memory_id, subject.memory_id)
            self.write_subject(
                MemorySubject(
                    id=subject.id,
                    memory_id=mapped_id,
                    subject_kind=subject.subject_kind,
                    subject_key=subject.subject_key,
                    relation=subject.relation,
                ),
                commit=False,
            )
        for evidence in batch.evidence:
            mapped_id = record_id_map.get(evidence.memory_id, evidence.memory_id)
            self.write_evidence(
                MemoryEvidence(
                    id=evidence.id,
                    memory_id=mapped_id,
                    evidence_kind=evidence.evidence_kind,
                    ref=evidence.ref,
                    locator=evidence.locator,
                    quote=evidence.quote,
                    digest=evidence.digest,
                    created_at_utc=evidence.created_at_utc,
                )
            )
        for link in batch.links:
            self.write_link(link)
        touched_ids = set(record_id_map.values())
        for memory_id in touched_ids:
            self.sync_fts_record(memory_id)
        if commit:
            self._conn.commit()
        return stats

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._conn.close()

    def __del__(self) -> None:
        with suppress(Exception):
            self.close()

    def commit(self) -> None:
        self._conn.commit()

    def count_records(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM memory_records").fetchone()
        return int(row[0]) if row is not None else 0

    def count_records_grouped(self, *, column: str) -> dict[str, int]:
        if column not in {"type", "status", "origin"}:
            msg = f"unsupported count column: {column}"
            raise ValueError(msg)
        rows = self._conn.execute(
            f"SELECT {column}, COUNT(*) FROM memory_records "
            f"GROUP BY {column} ORDER BY {column}"
        ).fetchall()
        return {str(row[0]): int(row[1]) for row in rows}

    @contextmanager
    def transaction(self) -> Iterator[None]:
        try:
            yield
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    @contextmanager
    def exclusive_init_lock(self) -> Iterator[None]:
        lock_path = self._db_path.parent / ".memory_init.lock"
        with memory_init_lock(lock_path):
            yield

    def _insert_record(self, record: MemoryRecord) -> None:
        self._conn.execute(
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
                record.id,
                record.project_id,
                record.identity_key,
                record.type,
                record.status,
                record.confidence,
                record.origin,
                record.ingest_source,
                record.statement,
                record.summary,
                payload_json_text(record.payload),
                record.created_at_utc,
                record.updated_at_utc,
                record.last_verified_at_utc,
                record.expires_at_utc,
                record.created_by,
                record.verified_by,
                record.approved_by,
                record.approved_at_utc,
                record.report_digest,
                record.code_fingerprint,
                record.stale_reason,
                record.created_on_branch,
                record.created_at_commit,
                record.verified_on_branch,
                record.verified_at_commit,
                record.schema_version,
            ),
        )

    def _next_revision_number(self, memory_id: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(revision_number), 0) FROM memory_revisions "
            "WHERE memory_id=?",
            (memory_id,),
        ).fetchone()
        current = int(row[0]) if row is not None else 0
        return current + 1


def _append_in_filter(
    clauses: list[str],
    params: list[object],
    values: Sequence[str],
    column: str,
) -> None:
    if not values:
        return
    placeholders = ", ".join("?" for _ in values)
    clauses.append(f"{column} IN ({placeholders})")
    params.extend(values)


def _append_confidence_filter(
    clauses: list[str],
    params: list[object],
    confidences: Sequence[str],
    *,
    via_subquery: bool,
) -> None:
    if not confidences:
        return
    placeholders = ", ".join("?" for _ in confidences)
    if via_subquery:
        clauses.append(
            "memory_records.id IN ("
            f"SELECT id FROM memory_records WHERE confidence IN ({placeholders})"
            ")"
        )
    else:
        clauses.append(f"confidence IN ({placeholders})")
    params.extend(confidences)


def _append_search_filters(
    clauses: list[str],
    params: list[object],
    types: Sequence[str],
    statuses: Sequence[str],
    confidences: Sequence[str],
    *,
    type_column: str,
    status_column: str,
    confidence_via_subquery: bool,
) -> None:
    _append_in_filter(clauses, params, types, type_column)
    _append_in_filter(clauses, params, statuses, status_column)
    _append_confidence_filter(
        clauses,
        params,
        confidences,
        via_subquery=confidence_via_subquery,
    )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def record_content_equal(left: MemoryRecord, right: MemoryRecord) -> bool:
    return left.statement == right.statement and left.payload == right.payload


def _record_content_equal(left: MemoryRecord, right: MemoryRecord) -> bool:
    return record_content_equal(left, right)


def _record_from_row(row: sqlite3.Row) -> MemoryRecord:
    payload = parse_payload_json(row["payload_json"])
    return MemoryRecord(
        id=str(row["id"]),
        project_id=str(row["project_id"]),
        identity_key=str(row["identity_key"]),
        type=str(row["type"]),  # type: ignore[arg-type]
        status=str(row["status"]),  # type: ignore[arg-type]
        confidence=str(row["confidence"]),  # type: ignore[arg-type]
        origin=str(row["origin"]),  # type: ignore[arg-type]
        ingest_source=str(row["ingest_source"]),  # type: ignore[arg-type]
        statement=str(row["statement"]),
        summary=str(row["summary"]) if row["summary"] is not None else None,
        payload=payload,
        created_at_utc=str(row["created_at_utc"]),
        updated_at_utc=str(row["updated_at_utc"]),
        last_verified_at_utc=(
            str(row["last_verified_at_utc"])
            if row["last_verified_at_utc"] is not None
            else None
        ),
        expires_at_utc=(
            str(row["expires_at_utc"]) if row["expires_at_utc"] is not None else None
        ),
        created_by=str(row["created_by"]),
        verified_by=str(row["verified_by"]) if row["verified_by"] is not None else None,
        approved_by=str(row["approved_by"]) if row["approved_by"] is not None else None,
        approved_at_utc=(
            str(row["approved_at_utc"]) if row["approved_at_utc"] is not None else None
        ),
        report_digest=(
            str(row["report_digest"]) if row["report_digest"] is not None else None
        ),
        code_fingerprint=(
            str(row["code_fingerprint"])
            if row["code_fingerprint"] is not None
            else None
        ),
        stale_reason=(
            str(row["stale_reason"]) if row["stale_reason"] is not None else None
        ),
        created_on_branch=(
            str(row["created_on_branch"])
            if row["created_on_branch"] is not None
            else None
        ),
        created_at_commit=(
            str(row["created_at_commit"])
            if row["created_at_commit"] is not None
            else None
        ),
        verified_on_branch=(
            str(row["verified_on_branch"])
            if row["verified_on_branch"] is not None
            else None
        ),
        verified_at_commit=(
            str(row["verified_at_commit"])
            if row["verified_at_commit"] is not None
            else None
        ),
        schema_version=str(row["schema_version"]),
    )


__all__ = ["SqliteEngineeringMemoryStore"]
