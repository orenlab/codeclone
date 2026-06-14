# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from ..contracts import (
    ActiveSelectionResult,
    ClusterAssignmentRecord,
    ClusteringRunRecord,
    ClusterSummaryRecord,
    CorpusItemRecord,
    CorpusSnapshotRecord,
    EmbeddingGenerationRecord,
    EmbeddingItemRecord,
    ProfileAssessmentRecord,
    ProfileBatchRecord,
    ProfileBatchRunRecord,
    ProfileManifestSnapshotRecord,
    RunSelectionRecord,
)
from ..exceptions import AnalyticsStoreError
from ..schema import open_analytics_db, open_analytics_db_readonly


class SqliteCorpusAnalyticsStore:
    """SQLite implementation of CorpusStore."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.row_factory = sqlite3.Row

    @classmethod
    def open(cls, path: Path) -> SqliteCorpusAnalyticsStore:
        return cls(open_analytics_db(path))

    @classmethod
    def open_readonly(cls, path: Path) -> SqliteCorpusAnalyticsStore:
        return cls(open_analytics_db_readonly(path))

    def insert_snapshot(
        self,
        snapshot: CorpusSnapshotRecord,
        items: Sequence[CorpusItemRecord],
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO corpus_snapshots (
                snapshot_id, lane, representation_kind, representation_version,
                source_stores_json, source_schema_versions_json,
                record_count, source_digest, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.snapshot_id,
                snapshot.lane,
                snapshot.representation_kind,
                snapshot.representation_version,
                snapshot.source_stores_json,
                snapshot.source_schema_versions_json,
                snapshot.record_count,
                snapshot.source_digest,
                snapshot.created_at_utc,
            ),
        )
        self._conn.executemany(
            """
            INSERT INTO corpus_items (
                snapshot_id, representation_key, snapshot_item_id,
                source_record_key, project_id, intent_id,
                normalized_text, normalized_digest, normalizer_version,
                representation_digest, metadata_json, registry_overlay_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.snapshot_id,
                    item.representation_key,
                    item.snapshot_item_id,
                    item.source_record_key,
                    item.project_id,
                    item.intent_id,
                    item.normalized_text,
                    item.normalized_digest,
                    item.normalizer_version,
                    item.representation_digest,
                    item.metadata_json,
                    item.registry_overlay_json,
                )
                for item in items
            ],
        )

    def get_snapshot(self, snapshot_id: str) -> CorpusSnapshotRecord | None:
        row = self._conn.execute(
            "SELECT * FROM corpus_snapshots WHERE snapshot_id=?",
            (snapshot_id,),
        ).fetchone()
        return _snapshot_from_row(row) if row is not None else None

    def list_snapshots(self) -> tuple[CorpusSnapshotRecord, ...]:
        rows = self._conn.execute(
            "SELECT * FROM corpus_snapshots "
            "ORDER BY created_at_utc DESC, snapshot_id ASC"
        ).fetchall()
        return tuple(_snapshot_from_row(row) for row in rows)

    def list_items(self, snapshot_id: str) -> tuple[CorpusItemRecord, ...]:
        rows = self._conn.execute(
            "SELECT * FROM corpus_items WHERE snapshot_id=? "
            "ORDER BY source_record_key ASC, representation_key ASC",
            (snapshot_id,),
        ).fetchall()
        return tuple(_item_from_row(row) for row in rows)

    def insert_embedding_generation(
        self,
        generation: EmbeddingGenerationRecord,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO embedding_generations (
                embedding_generation_id, provider_id, provider_package_version,
                model_id, model_revision, model_artifact_fingerprint,
                exact_model_artifact_reproducibility, dimensions,
                embedding_contract_version, embedding_similarity_metric,
                vector_preprocessing, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                generation.embedding_generation_id,
                generation.provider_id,
                generation.provider_package_version,
                generation.model_id,
                generation.model_revision,
                generation.model_artifact_fingerprint,
                int(generation.exact_model_artifact_reproducibility),
                generation.dimensions,
                generation.embedding_contract_version,
                generation.embedding_similarity_metric,
                generation.vector_preprocessing,
                generation.created_at_utc,
            ),
        )

    def insert_embedding_items(
        self,
        items: Sequence[EmbeddingItemRecord],
    ) -> None:
        self._conn.executemany(
            """
            INSERT INTO embedding_items (
                embedding_generation_id, snapshot_item_id,
                vector_row_key, vector_digest, dimensions
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    item.embedding_generation_id,
                    item.snapshot_item_id,
                    item.vector_row_key,
                    item.vector_digest,
                    item.dimensions,
                )
                for item in items
            ],
        )

    def get_embedding_generation(
        self,
        embedding_generation_id: str,
    ) -> EmbeddingGenerationRecord | None:
        row = self._conn.execute(
            "SELECT * FROM embedding_generations WHERE embedding_generation_id=?",
            (embedding_generation_id,),
        ).fetchone()
        return _generation_from_row(row) if row is not None else None

    def list_embedding_items(
        self,
        *,
        embedding_generation_id: str,
    ) -> tuple[EmbeddingItemRecord, ...]:
        rows = self._conn.execute(
            "SELECT * FROM embedding_items WHERE embedding_generation_id=? "
            "ORDER BY snapshot_item_id ASC",
            (embedding_generation_id,),
        ).fetchall()
        return tuple(_embedding_item_from_row(row) for row in rows)

    def insert_clustering_run(self, run: ClusteringRunRecord) -> None:
        self._conn.execute(
            """
            INSERT INTO clustering_runs (
                clustering_run_id, snapshot_id, embedding_generation_id,
                requested_parameters_json, effective_parameters_json,
                random_seed, run_digest, recommended_by_heuristic,
                selected_by_maintainer, status, created_at_utc,
                finished_at_utc, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.clustering_run_id,
                run.snapshot_id,
                run.embedding_generation_id,
                run.requested_parameters_json,
                run.effective_parameters_json,
                run.random_seed,
                run.run_digest,
                int(run.recommended_by_heuristic),
                int(run.selected_by_maintainer),
                run.status,
                run.created_at_utc,
                run.finished_at_utc,
                run.error_message,
            ),
        )

    def update_clustering_run(self, run: ClusteringRunRecord) -> None:
        self._conn.execute(
            """
            UPDATE clustering_runs SET
                requested_parameters_json=?,
                effective_parameters_json=?,
                random_seed=?,
                run_digest=?,
                recommended_by_heuristic=?,
                selected_by_maintainer=?,
                status=?,
                finished_at_utc=?,
                error_message=?
            WHERE clustering_run_id=?
            """,
            (
                run.requested_parameters_json,
                run.effective_parameters_json,
                run.random_seed,
                run.run_digest,
                int(run.recommended_by_heuristic),
                int(run.selected_by_maintainer),
                run.status,
                run.finished_at_utc,
                run.error_message,
                run.clustering_run_id,
            ),
        )

    def get_clustering_run(
        self,
        clustering_run_id: str,
    ) -> ClusteringRunRecord | None:
        row = self._conn.execute(
            "SELECT * FROM clustering_runs WHERE clustering_run_id=?",
            (clustering_run_id,),
        ).fetchone()
        return _run_from_row(row) if row is not None else None

    def list_clustering_runs(
        self,
        *,
        snapshot_id: str,
        embedding_generation_id: str | None = None,
    ) -> tuple[ClusteringRunRecord, ...]:
        if embedding_generation_id is None:
            rows = self._conn.execute(
                "SELECT * FROM clustering_runs WHERE snapshot_id=? "
                "ORDER BY created_at_utc ASC, clustering_run_id ASC",
                (snapshot_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM clustering_runs WHERE snapshot_id=? "
                "AND embedding_generation_id=? "
                "ORDER BY created_at_utc ASC, clustering_run_id ASC",
                (snapshot_id, embedding_generation_id),
            ).fetchall()
        return tuple(_run_from_row(row) for row in rows)

    def set_recommended_run(
        self,
        *,
        snapshot_id: str,
        embedding_generation_id: str,
        clustering_run_id: str,
    ) -> None:
        for run in self.list_clustering_runs(
            snapshot_id=snapshot_id,
            embedding_generation_id=embedding_generation_id,
        ):
            self.update_clustering_run(
                replace(
                    run,
                    recommended_by_heuristic=(
                        run.clustering_run_id == clustering_run_id
                    ),
                )
            )

    def insert_profile_manifest_snapshot(
        self,
        record: ProfileManifestSnapshotRecord,
    ) -> None:
        self._conn.execute(
            """
            INSERT OR IGNORE INTO profile_manifest_snapshots (
                profile_manifest_digest, profile_id, profile_version,
                manifest_schema_version, canonical_manifest_json,
                label, description, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.profile_manifest_digest,
                record.profile_id,
                record.profile_version,
                record.manifest_schema_version,
                record.canonical_manifest_json,
                record.label,
                record.description,
                record.created_at_utc,
            ),
        )
        existing = self.get_profile_manifest_snapshot(record.profile_manifest_digest)
        normalized_existing = (
            replace(existing, created_at_utc=record.created_at_utc)
            if existing is not None
            else None
        )
        if normalized_existing != record:
            raise AnalyticsStoreError(
                "profile manifest digest collision or snapshot mismatch"
            )

    def get_profile_manifest_snapshot(
        self,
        profile_manifest_digest: str,
    ) -> ProfileManifestSnapshotRecord | None:
        row = self._conn.execute(
            """
            SELECT * FROM profile_manifest_snapshots
            WHERE profile_manifest_digest=?
            """,
            (profile_manifest_digest,),
        ).fetchone()
        return _profile_manifest_snapshot_from_row(row) if row is not None else None

    def insert_profile_batch(self, record: ProfileBatchRecord) -> None:
        self._conn.execute(
            """
            INSERT INTO profile_batches (
                profile_batch_id, snapshot_id, embedding_generation_id,
                profile_id, profile_manifest_digest, candidate_space_digest,
                started_at_utc, finished_at_utc, status,
                candidate_count_planned, candidate_count_succeeded,
                candidate_count_failed, recommended_clustering_run_id,
                recommendation_rationale_json, batch_max_cluster_count,
                created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            _profile_batch_values(record),
        )

    def finalize_profile_batch(self, record: ProfileBatchRecord) -> None:
        cursor = self._conn.execute(
            """
            UPDATE profile_batches SET
                finished_at_utc=?,
                status=?,
                candidate_count_succeeded=?,
                candidate_count_failed=?,
                recommended_clustering_run_id=?,
                recommendation_rationale_json=?,
                batch_max_cluster_count=?
            WHERE profile_batch_id=?
            """,
            (
                record.finished_at_utc,
                record.status,
                record.candidate_count_succeeded,
                record.candidate_count_failed,
                record.recommended_clustering_run_id,
                record.recommendation_rationale_json,
                record.batch_max_cluster_count,
                record.profile_batch_id,
            ),
        )
        if cursor.rowcount != 1:
            raise AnalyticsStoreError(
                f"unknown profile batch: {record.profile_batch_id}"
            )

    def get_profile_batch(
        self,
        profile_batch_id: str,
    ) -> ProfileBatchRecord | None:
        row = self._conn.execute(
            "SELECT * FROM profile_batches WHERE profile_batch_id=?",
            (profile_batch_id,),
        ).fetchone()
        return _profile_batch_from_row(row) if row is not None else None

    def get_latest_profile_batch(
        self,
        *,
        snapshot_id: str,
        embedding_generation_id: str,
        profile_id: str,
    ) -> ProfileBatchRecord | None:
        row = self._conn.execute(
            """
            SELECT * FROM profile_batches
            WHERE snapshot_id=? AND embedding_generation_id=? AND profile_id=?
            ORDER BY started_at_utc DESC, profile_batch_id ASC
            LIMIT 1
            """,
            (snapshot_id, embedding_generation_id, profile_id),
        ).fetchone()
        return _profile_batch_from_row(row) if row is not None else None

    def insert_profile_batch_run(self, record: ProfileBatchRunRecord) -> None:
        self._conn.execute(
            """
            INSERT INTO profile_batch_runs (
                profile_batch_id, clustering_run_id,
                candidate_ordinal, candidate_dedupe_key
            ) VALUES (?, ?, ?, ?)
            """,
            (
                record.profile_batch_id,
                record.clustering_run_id,
                record.candidate_ordinal,
                record.candidate_dedupe_key,
            ),
        )

    def list_profile_batch_run_records(
        self,
        *,
        profile_batch_id: str,
    ) -> tuple[ProfileBatchRunRecord, ...]:
        rows = self._conn.execute(
            """
            SELECT * FROM profile_batch_runs
            WHERE profile_batch_id=?
            ORDER BY candidate_ordinal ASC, candidate_dedupe_key ASC
            """,
            (profile_batch_id,),
        ).fetchall()
        return tuple(_profile_batch_run_from_row(row) for row in rows)

    def list_clustering_runs_for_batch(
        self,
        *,
        profile_batch_id: str,
    ) -> tuple[ClusteringRunRecord, ...]:
        rows = self._conn.execute(
            """
            SELECT run.*
            FROM profile_batch_runs AS member
            JOIN clustering_runs AS run
              ON run.clustering_run_id=member.clustering_run_id
            WHERE member.profile_batch_id=?
            ORDER BY member.candidate_ordinal ASC, member.candidate_dedupe_key ASC
            """,
            (profile_batch_id,),
        ).fetchall()
        return tuple(_run_from_row(row) for row in rows)

    def list_profile_batch_ids_for_run(
        self,
        *,
        clustering_run_id: str,
    ) -> tuple[str, ...]:
        rows = self._conn.execute(
            """
            SELECT profile_batch_id FROM profile_batch_runs
            WHERE clustering_run_id=?
            ORDER BY profile_batch_id ASC
            """,
            (clustering_run_id,),
        ).fetchall()
        return tuple(str(row[0]) for row in rows)

    def insert_profile_assessment(
        self,
        record: ProfileAssessmentRecord,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO profile_assessments (
                profile_batch_id, clustering_run_id, profile_id,
                profile_version, profile_manifest_digest,
                suitable_for_profile, rejection_reasons_json,
                observed_metrics_json, assessed_digest
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.profile_batch_id,
                record.clustering_run_id,
                record.profile_id,
                record.profile_version,
                record.profile_manifest_digest,
                int(record.suitable_for_profile),
                record.rejection_reasons_json,
                record.observed_metrics_json,
                record.assessed_digest,
            ),
        )

    def get_profile_assessment(
        self,
        *,
        profile_batch_id: str,
        clustering_run_id: str,
    ) -> ProfileAssessmentRecord | None:
        row = self._conn.execute(
            """
            SELECT * FROM profile_assessments
            WHERE profile_batch_id=? AND clustering_run_id=?
            """,
            (profile_batch_id, clustering_run_id),
        ).fetchone()
        return _profile_assessment_from_row(row) if row is not None else None

    def list_profile_assessments(
        self,
        *,
        profile_batch_id: str,
    ) -> tuple[ProfileAssessmentRecord, ...]:
        rows = self._conn.execute(
            """
            SELECT assessment.*
            FROM profile_assessments AS assessment
            JOIN profile_batch_runs AS member
              ON member.profile_batch_id=assessment.profile_batch_id
             AND member.clustering_run_id=assessment.clustering_run_id
            WHERE assessment.profile_batch_id=?
            ORDER BY member.candidate_ordinal ASC
            """,
            (profile_batch_id,),
        ).fetchall()
        return tuple(_profile_assessment_from_row(row) for row in rows)

    def get_active_run_selection(
        self,
        *,
        snapshot_id: str,
        embedding_generation_id: str,
        profile_batch_id: str | None,
    ) -> ActiveSelectionResult:
        rows = self._active_selection_rows(
            snapshot_id=snapshot_id,
            embedding_generation_id=embedding_generation_id,
            profile_batch_id=profile_batch_id,
        )
        return ActiveSelectionResult(
            _run_selection_from_row(rows[0]) if rows else None,
            len(rows) > 1,
        )

    def record_run_selection_atomic(
        self,
        record: RunSelectionRecord,
    ) -> RunSelectionRecord:
        if self._conn.in_transaction:
            raise AnalyticsStoreError(
                "atomic selection recording requires a clean transaction"
            )
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            rows = self._active_selection_rows(
                snapshot_id=record.snapshot_id,
                embedding_generation_id=record.embedding_generation_id,
                profile_batch_id=record.profile_batch_id,
            )
            if len(rows) > 1:
                raise AnalyticsStoreError(
                    "selection chain ambiguous: multiple active selections"
                )
            previous = _run_selection_from_row(rows[0]) if rows else None
            persisted = replace(
                record,
                supersedes_selection_id=(
                    previous.selection_id if previous is not None else None
                ),
            )
            batch_mismatch = (
                persisted.profile_batch_id is not None
                and not self._run_in_profile_batch(
                    profile_batch_id=persisted.profile_batch_id,
                    clustering_run_id=persisted.selected_run_id,
                )
            )
            if batch_mismatch:
                raise AnalyticsStoreError(
                    "selected run is not a member of profile batch: "
                    f"{persisted.profile_batch_id}"
                )
            self._insert_run_selection(persisted)
            if persisted.profile_batch_id is None:
                self._conn.execute(
                    """
                    UPDATE clustering_runs
                    SET selected_by_maintainer=(
                        clustering_run_id=?
                    )
                    WHERE snapshot_id=? AND embedding_generation_id=?
                    """,
                    (
                        persisted.selected_run_id,
                        persisted.snapshot_id,
                        persisted.embedding_generation_id,
                    ),
                )
            self._conn.commit()
            return persisted
        except BaseException:
            self._conn.rollback()
            raise

    def _active_selection_rows(
        self,
        *,
        snapshot_id: str,
        embedding_generation_id: str,
        profile_batch_id: str | None,
    ) -> list[sqlite3.Row]:
        return list(
            self._conn.execute(
                """
                SELECT selection.*
                FROM run_selections AS selection
                WHERE selection.snapshot_id=?
                  AND selection.embedding_generation_id=?
                  AND selection.profile_batch_id IS ?
                  AND NOT EXISTS (
                      SELECT 1 FROM run_selections AS successor
                      WHERE successor.supersedes_selection_id=
                            selection.selection_id
                  )
                ORDER BY selection.selected_at_utc DESC,
                         selection.selection_id ASC
                """,
                (snapshot_id, embedding_generation_id, profile_batch_id),
            ).fetchall()
        )

    def _run_in_profile_batch(
        self,
        *,
        profile_batch_id: str,
        clustering_run_id: str,
    ) -> bool:
        return (
            self._conn.execute(
                """
                SELECT 1 FROM profile_batch_runs
                WHERE profile_batch_id=? AND clustering_run_id=?
                """,
                (profile_batch_id, clustering_run_id),
            ).fetchone()
            is not None
        )

    def _insert_run_selection(self, record: RunSelectionRecord) -> None:
        self._conn.execute(
            """
            INSERT INTO run_selections (
                selection_id, snapshot_id, embedding_generation_id,
                profile_batch_id, profile_id, profile_manifest_digest,
                selected_run_id, selected_at_utc, selected_by, rationale,
                supersedes_selection_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.selection_id,
                record.snapshot_id,
                record.embedding_generation_id,
                record.profile_batch_id,
                record.profile_id,
                record.profile_manifest_digest,
                record.selected_run_id,
                record.selected_at_utc,
                record.selected_by,
                record.rationale,
                record.supersedes_selection_id,
            ),
        )

    def insert_cluster_assignments(
        self,
        assignments: Sequence[ClusterAssignmentRecord],
    ) -> None:
        self._conn.executemany(
            """
            INSERT INTO cluster_assignments (
                clustering_run_id, snapshot_item_id, cluster_label,
                membership_strength, membership_digest
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    item.clustering_run_id,
                    item.snapshot_item_id,
                    item.cluster_label,
                    item.membership_strength,
                    item.membership_digest,
                )
                for item in assignments
            ],
        )

    def insert_cluster_summaries(
        self,
        summaries: Sequence[ClusterSummaryRecord],
    ) -> None:
        self._conn.executemany(
            """
            INSERT INTO cluster_summaries (
                clustering_run_id, cluster_label, display_cluster_id,
                membership_digest, size, diagnostics_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.clustering_run_id,
                    item.cluster_label,
                    item.display_cluster_id,
                    item.membership_digest,
                    item.size,
                    item.diagnostics_json,
                )
                for item in summaries
            ],
        )

    def list_assignments(
        self,
        clustering_run_id: str,
    ) -> tuple[ClusterAssignmentRecord, ...]:
        rows = self._conn.execute(
            "SELECT * FROM cluster_assignments WHERE clustering_run_id=? "
            "ORDER BY snapshot_item_id ASC",
            (clustering_run_id,),
        ).fetchall()
        return tuple(_assignment_from_row(row) for row in rows)

    def list_summaries(
        self,
        clustering_run_id: str,
    ) -> tuple[ClusterSummaryRecord, ...]:
        rows = self._conn.execute(
            "SELECT * FROM cluster_summaries WHERE clustering_run_id=? "
            "ORDER BY display_cluster_id ASC NULLS LAST, cluster_label ASC",
            (clustering_run_id,),
        ).fetchall()
        return tuple(_summary_from_row(row) for row in rows)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()


def _snapshot_from_row(row: sqlite3.Row) -> CorpusSnapshotRecord:
    return CorpusSnapshotRecord(
        snapshot_id=str(row["snapshot_id"]),
        lane=str(row["lane"]),  # type: ignore[arg-type]
        representation_kind=str(row["representation_kind"]),
        representation_version=str(row["representation_version"]),
        source_stores_json=str(row["source_stores_json"]),
        source_schema_versions_json=str(row["source_schema_versions_json"]),
        record_count=int(row["record_count"]),
        source_digest=str(row["source_digest"]),
        created_at_utc=str(row["created_at_utc"]),
    )


def _item_from_row(row: sqlite3.Row) -> CorpusItemRecord:
    overlay = row["registry_overlay_json"]
    return CorpusItemRecord(
        snapshot_id=str(row["snapshot_id"]),
        representation_key=str(row["representation_key"]),
        snapshot_item_id=str(row["snapshot_item_id"]),
        source_record_key=str(row["source_record_key"]),
        project_id=str(row["project_id"]),
        intent_id=str(row["intent_id"]),
        normalized_text=str(row["normalized_text"]),
        normalized_digest=str(row["normalized_digest"]),
        normalizer_version=str(row["normalizer_version"]),
        representation_digest=str(row["representation_digest"]),
        metadata_json=str(row["metadata_json"]),
        registry_overlay_json=str(overlay) if overlay is not None else None,
    )


def _generation_from_row(row: sqlite3.Row) -> EmbeddingGenerationRecord:
    return EmbeddingGenerationRecord(
        embedding_generation_id=str(row["embedding_generation_id"]),
        provider_id=str(row["provider_id"]),
        provider_package_version=str(row["provider_package_version"]),
        model_id=str(row["model_id"]),
        model_revision=_optional_str(row["model_revision"]),
        model_artifact_fingerprint=_optional_str(row["model_artifact_fingerprint"]),
        exact_model_artifact_reproducibility=bool(
            int(row["exact_model_artifact_reproducibility"])
        ),
        dimensions=int(row["dimensions"]),
        embedding_contract_version=str(row["embedding_contract_version"]),
        embedding_similarity_metric=str(row["embedding_similarity_metric"]),
        vector_preprocessing=str(row["vector_preprocessing"]),
        created_at_utc=str(row["created_at_utc"]),
    )


def _embedding_item_from_row(row: sqlite3.Row) -> EmbeddingItemRecord:
    return EmbeddingItemRecord(
        embedding_generation_id=str(row["embedding_generation_id"]),
        snapshot_item_id=str(row["snapshot_item_id"]),
        vector_row_key=str(row["vector_row_key"]),
        vector_digest=str(row["vector_digest"]),
        dimensions=int(row["dimensions"]),
    )


def _run_from_row(row: sqlite3.Row) -> ClusteringRunRecord:
    return ClusteringRunRecord(
        clustering_run_id=str(row["clustering_run_id"]),
        snapshot_id=str(row["snapshot_id"]),
        embedding_generation_id=str(row["embedding_generation_id"]),
        requested_parameters_json=str(row["requested_parameters_json"]),
        effective_parameters_json=str(row["effective_parameters_json"]),
        random_seed=int(row["random_seed"]),
        run_digest=str(row["run_digest"]),
        recommended_by_heuristic=bool(int(row["recommended_by_heuristic"])),
        selected_by_maintainer=bool(int(row["selected_by_maintainer"])),
        status=str(row["status"]),  # type: ignore[arg-type]
        created_at_utc=str(row["created_at_utc"]),
        finished_at_utc=_optional_str(row["finished_at_utc"]),
        error_message=_optional_str(row["error_message"]),
    )


def _assignment_from_row(row: sqlite3.Row) -> ClusterAssignmentRecord:
    strength = row["membership_strength"]
    return ClusterAssignmentRecord(
        clustering_run_id=str(row["clustering_run_id"]),
        snapshot_item_id=str(row["snapshot_item_id"]),
        cluster_label=int(row["cluster_label"]),
        membership_strength=float(strength) if strength is not None else None,
        membership_digest=str(row["membership_digest"]),
    )


def _summary_from_row(row: sqlite3.Row) -> ClusterSummaryRecord:
    display = row["display_cluster_id"]
    return ClusterSummaryRecord(
        clustering_run_id=str(row["clustering_run_id"]),
        cluster_label=int(row["cluster_label"]),
        display_cluster_id=int(display) if display is not None else None,
        membership_digest=str(row["membership_digest"]),
        size=int(row["size"]),
        diagnostics_json=str(row["diagnostics_json"]),
    )


def _profile_manifest_snapshot_from_row(
    row: sqlite3.Row,
) -> ProfileManifestSnapshotRecord:
    return ProfileManifestSnapshotRecord(
        profile_manifest_digest=str(row["profile_manifest_digest"]),
        profile_id=str(row["profile_id"]),
        profile_version=str(row["profile_version"]),
        manifest_schema_version=str(row["manifest_schema_version"]),
        canonical_manifest_json=str(row["canonical_manifest_json"]),
        label=str(row["label"]),
        description=str(row["description"]),
        created_at_utc=str(row["created_at_utc"]),
    )


def _profile_batch_values(record: ProfileBatchRecord) -> tuple[object, ...]:
    return (
        record.profile_batch_id,
        record.snapshot_id,
        record.embedding_generation_id,
        record.profile_id,
        record.profile_manifest_digest,
        record.candidate_space_digest,
        record.started_at_utc,
        record.finished_at_utc,
        record.status,
        record.candidate_count_planned,
        record.candidate_count_succeeded,
        record.candidate_count_failed,
        record.recommended_clustering_run_id,
        record.recommendation_rationale_json,
        record.batch_max_cluster_count,
        record.created_at_utc,
    )


def _profile_batch_from_row(row: sqlite3.Row) -> ProfileBatchRecord:
    return ProfileBatchRecord(
        profile_batch_id=str(row["profile_batch_id"]),
        snapshot_id=str(row["snapshot_id"]),
        embedding_generation_id=str(row["embedding_generation_id"]),
        profile_id=str(row["profile_id"]),
        profile_manifest_digest=str(row["profile_manifest_digest"]),
        candidate_space_digest=str(row["candidate_space_digest"]),
        started_at_utc=str(row["started_at_utc"]),
        finished_at_utc=_optional_str(row["finished_at_utc"]),
        status=str(row["status"]),  # type: ignore[arg-type]
        candidate_count_planned=int(row["candidate_count_planned"]),
        candidate_count_succeeded=int(row["candidate_count_succeeded"]),
        candidate_count_failed=int(row["candidate_count_failed"]),
        recommended_clustering_run_id=_optional_str(
            row["recommended_clustering_run_id"]
        ),
        recommendation_rationale_json=_optional_str(
            row["recommendation_rationale_json"]
        ),
        batch_max_cluster_count=(
            int(row["batch_max_cluster_count"])
            if row["batch_max_cluster_count"] is not None
            else None
        ),
        created_at_utc=str(row["created_at_utc"]),
    )


def _profile_batch_run_from_row(row: sqlite3.Row) -> ProfileBatchRunRecord:
    return ProfileBatchRunRecord(
        profile_batch_id=str(row["profile_batch_id"]),
        clustering_run_id=str(row["clustering_run_id"]),
        candidate_ordinal=int(row["candidate_ordinal"]),
        candidate_dedupe_key=str(row["candidate_dedupe_key"]),
    )


def _profile_assessment_from_row(row: sqlite3.Row) -> ProfileAssessmentRecord:
    return ProfileAssessmentRecord(
        profile_batch_id=str(row["profile_batch_id"]),
        clustering_run_id=str(row["clustering_run_id"]),
        profile_id=str(row["profile_id"]),
        profile_version=str(row["profile_version"]),
        profile_manifest_digest=str(row["profile_manifest_digest"]),
        suitable_for_profile=bool(int(row["suitable_for_profile"])),
        rejection_reasons_json=str(row["rejection_reasons_json"]),
        observed_metrics_json=_optional_str(row["observed_metrics_json"]),
        assessed_digest=str(row["assessed_digest"]),
    )


def _run_selection_from_row(row: sqlite3.Row) -> RunSelectionRecord:
    return RunSelectionRecord(
        selection_id=str(row["selection_id"]),
        snapshot_id=str(row["snapshot_id"]),
        embedding_generation_id=str(row["embedding_generation_id"]),
        profile_batch_id=_optional_str(row["profile_batch_id"]),
        profile_id=_optional_str(row["profile_id"]),
        profile_manifest_digest=_optional_str(row["profile_manifest_digest"]),
        selected_run_id=str(row["selected_run_id"]),
        selected_at_utc=str(row["selected_at_utc"]),
        selected_by=str(row["selected_by"]),
        rationale=_optional_str(row["rationale"]),
        supersedes_selection_id=_optional_str(row["supersedes_selection_id"]),
    )


def _optional_str(value: object) -> str | None:
    return str(value) if isinstance(value, str) else None


def parse_json_object(text: str) -> dict[str, object]:
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise AnalyticsStoreError("expected JSON object")
    return parsed


__all__ = ["SqliteCorpusAnalyticsStore", "parse_json_object"]
