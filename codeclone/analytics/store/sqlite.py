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
    ClusterAssignmentRecord,
    ClusteringRunRecord,
    ClusterSummaryRecord,
    CorpusItemRecord,
    CorpusSnapshotRecord,
    EmbeddingGenerationRecord,
    EmbeddingItemRecord,
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

    def set_selected_run(
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
                    selected_by_maintainer=(run.clustering_run_id == clustering_run_id),
                )
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


def _optional_str(value: object) -> str | None:
    return str(value) if isinstance(value, str) else None


def parse_json_object(text: str) -> dict[str, object]:
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise AnalyticsStoreError("expected JSON object")
    return parsed


__all__ = ["SqliteCorpusAnalyticsStore", "parse_json_object"]
