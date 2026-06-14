# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from ..contracts import CORPUS_ANALYTICS_STORE_SCHEMA_VERSION
from ..report.meta import current_report_timestamp_utc
from ..utils.sqlite_store import (
    get_meta_value,
    initialize_schema_v1,
)
from .exceptions import AnalyticsStoreError

_ANALYTICS_META_TABLE = "analytics_meta"

_CONTROL_PLANE_DDL = (
    """
    CREATE TABLE IF NOT EXISTS profile_manifest_snapshots (
        profile_manifest_digest TEXT PRIMARY KEY,
        profile_id TEXT NOT NULL,
        profile_version TEXT NOT NULL,
        manifest_schema_version TEXT NOT NULL,
        canonical_manifest_json TEXT NOT NULL,
        label TEXT NOT NULL,
        description TEXT NOT NULL,
        created_at_utc TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS profile_batches (
        profile_batch_id TEXT PRIMARY KEY,
        snapshot_id TEXT NOT NULL,
        embedding_generation_id TEXT NOT NULL,
        profile_id TEXT NOT NULL,
        profile_manifest_digest TEXT NOT NULL,
        candidate_space_digest TEXT NOT NULL,
        started_at_utc TEXT NOT NULL,
        finished_at_utc TEXT,
        status TEXT NOT NULL,
        candidate_count_planned INTEGER NOT NULL,
        candidate_count_succeeded INTEGER NOT NULL DEFAULT 0,
        candidate_count_failed INTEGER NOT NULL DEFAULT 0,
        recommended_clustering_run_id TEXT,
        recommendation_rationale_json TEXT,
        batch_max_cluster_count INTEGER,
        created_at_utc TEXT NOT NULL,
        FOREIGN KEY (snapshot_id)
            REFERENCES corpus_snapshots(snapshot_id),
        FOREIGN KEY (embedding_generation_id)
            REFERENCES embedding_generations(embedding_generation_id),
        FOREIGN KEY (profile_manifest_digest)
            REFERENCES profile_manifest_snapshots(profile_manifest_digest),
        FOREIGN KEY (recommended_clustering_run_id)
            REFERENCES clustering_runs(clustering_run_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS profile_batch_runs (
        profile_batch_id TEXT NOT NULL,
        clustering_run_id TEXT NOT NULL,
        candidate_ordinal INTEGER NOT NULL,
        candidate_dedupe_key TEXT NOT NULL,
        PRIMARY KEY (profile_batch_id, clustering_run_id),
        UNIQUE (profile_batch_id, candidate_dedupe_key),
        FOREIGN KEY (profile_batch_id)
            REFERENCES profile_batches(profile_batch_id),
        FOREIGN KEY (clustering_run_id)
            REFERENCES clustering_runs(clustering_run_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS profile_assessments (
        profile_batch_id TEXT NOT NULL,
        clustering_run_id TEXT NOT NULL,
        profile_id TEXT NOT NULL,
        profile_version TEXT NOT NULL,
        profile_manifest_digest TEXT NOT NULL,
        suitable_for_profile INTEGER NOT NULL,
        rejection_reasons_json TEXT NOT NULL,
        observed_metrics_json TEXT,
        assessed_digest TEXT NOT NULL,
        PRIMARY KEY (profile_batch_id, clustering_run_id),
        FOREIGN KEY (profile_batch_id)
            REFERENCES profile_batches(profile_batch_id),
        FOREIGN KEY (clustering_run_id)
            REFERENCES clustering_runs(clustering_run_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS run_selections (
        selection_id TEXT PRIMARY KEY,
        snapshot_id TEXT NOT NULL,
        embedding_generation_id TEXT NOT NULL,
        profile_batch_id TEXT,
        profile_id TEXT,
        profile_manifest_digest TEXT,
        selected_run_id TEXT NOT NULL,
        selected_at_utc TEXT NOT NULL,
        selected_by TEXT NOT NULL,
        rationale TEXT,
        supersedes_selection_id TEXT,
        FOREIGN KEY (selected_run_id)
            REFERENCES clustering_runs(clustering_run_id),
        FOREIGN KEY (supersedes_selection_id)
            REFERENCES run_selections(selection_id),
        FOREIGN KEY (profile_batch_id)
            REFERENCES profile_batches(profile_batch_id)
    )
    """,
)

_DDL = (
    """
    CREATE TABLE IF NOT EXISTS corpus_snapshots (
        snapshot_id TEXT PRIMARY KEY,
        lane TEXT NOT NULL,
        representation_kind TEXT NOT NULL,
        representation_version TEXT NOT NULL,
        source_stores_json TEXT NOT NULL,
        source_schema_versions_json TEXT NOT NULL,
        record_count INTEGER NOT NULL,
        source_digest TEXT NOT NULL,
        created_at_utc TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS corpus_items (
        snapshot_id TEXT NOT NULL,
        representation_key TEXT NOT NULL,
        snapshot_item_id TEXT NOT NULL,
        source_record_key TEXT NOT NULL,
        project_id TEXT NOT NULL,
        intent_id TEXT NOT NULL,
        normalized_text TEXT NOT NULL,
        normalized_digest TEXT NOT NULL,
        normalizer_version TEXT NOT NULL,
        representation_digest TEXT NOT NULL,
        metadata_json TEXT NOT NULL,
        registry_overlay_json TEXT,
        PRIMARY KEY (snapshot_id, representation_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS embedding_generations (
        embedding_generation_id TEXT PRIMARY KEY,
        provider_id TEXT NOT NULL,
        provider_package_version TEXT NOT NULL,
        model_id TEXT NOT NULL,
        model_revision TEXT,
        model_artifact_fingerprint TEXT,
        exact_model_artifact_reproducibility INTEGER NOT NULL,
        dimensions INTEGER NOT NULL,
        embedding_contract_version TEXT NOT NULL,
        embedding_similarity_metric TEXT NOT NULL,
        vector_preprocessing TEXT NOT NULL,
        created_at_utc TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS embedding_items (
        embedding_generation_id TEXT NOT NULL,
        snapshot_item_id TEXT NOT NULL,
        vector_row_key TEXT NOT NULL,
        vector_digest TEXT NOT NULL,
        dimensions INTEGER NOT NULL,
        PRIMARY KEY (embedding_generation_id, snapshot_item_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS clustering_runs (
        clustering_run_id TEXT PRIMARY KEY,
        snapshot_id TEXT NOT NULL,
        embedding_generation_id TEXT NOT NULL,
        requested_parameters_json TEXT NOT NULL,
        effective_parameters_json TEXT NOT NULL,
        random_seed INTEGER NOT NULL,
        run_digest TEXT NOT NULL,
        recommended_by_heuristic INTEGER NOT NULL DEFAULT 0,
        selected_by_maintainer INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL,
        created_at_utc TEXT NOT NULL,
        finished_at_utc TEXT,
        error_message TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cluster_assignments (
        clustering_run_id TEXT NOT NULL,
        snapshot_item_id TEXT NOT NULL,
        cluster_label INTEGER NOT NULL,
        membership_strength REAL,
        membership_digest TEXT NOT NULL,
        PRIMARY KEY (clustering_run_id, snapshot_item_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cluster_summaries (
        clustering_run_id TEXT NOT NULL,
        cluster_label INTEGER NOT NULL,
        display_cluster_id INTEGER,
        membership_digest TEXT NOT NULL,
        size INTEGER NOT NULL,
        diagnostics_json TEXT NOT NULL,
        PRIMARY KEY (clustering_run_id, cluster_label)
    )
    """,
    *_CONTROL_PLANE_DDL,
    f"""
    CREATE TABLE IF NOT EXISTS {_ANALYTICS_META_TABLE} (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
)

_INDEXES = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_corpus_items_snapshot_item "
    "ON corpus_items(snapshot_id, snapshot_item_id)",
    "CREATE INDEX IF NOT EXISTS idx_corpus_items_intent "
    "ON corpus_items(project_id, intent_id)",
    "CREATE INDEX IF NOT EXISTS idx_clustering_runs_snapshot "
    "ON clustering_runs(snapshot_id, embedding_generation_id)",
    "CREATE INDEX IF NOT EXISTS idx_cluster_assignments_run "
    "ON cluster_assignments(clustering_run_id, cluster_label)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_embedding_items_vector_row_key "
    "ON embedding_items(vector_row_key)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_cluster_summaries_display "
    "ON cluster_summaries(clustering_run_id, display_cluster_id) "
    "WHERE display_cluster_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_profile_batches_lens "
    "ON profile_batches("
    "snapshot_id, embedding_generation_id, profile_id, started_at_utc"
    ")",
    "CREATE INDEX IF NOT EXISTS idx_run_selections_scope "
    "ON run_selections("
    "snapshot_id, embedding_generation_id, profile_batch_id, selected_at_utc"
    ")",
)

_CONTROL_PLANE_INDEX_MARKERS = (
    "idx_profile_batches_lens",
    "idx_run_selections_scope",
)

_INTEGRITY_TRIGGERS = (
    """
    CREATE TRIGGER IF NOT EXISTS analytics_corpus_item_snapshot_guard
    BEFORE INSERT ON corpus_items
    WHEN NOT EXISTS (
        SELECT 1 FROM corpus_snapshots WHERE snapshot_id=NEW.snapshot_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'unknown corpus snapshot');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS analytics_corpus_item_snapshot_update_guard
    BEFORE UPDATE OF snapshot_id ON corpus_items
    WHEN NOT EXISTS (
        SELECT 1 FROM corpus_snapshots WHERE snapshot_id=NEW.snapshot_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'unknown corpus snapshot');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS analytics_snapshot_delete_guard
    BEFORE DELETE ON corpus_snapshots
    WHEN EXISTS (
        SELECT 1 FROM corpus_items WHERE snapshot_id=OLD.snapshot_id
    ) OR EXISTS (
        SELECT 1 FROM clustering_runs WHERE snapshot_id=OLD.snapshot_id
    ) OR EXISTS (
        SELECT 1 FROM profile_batches WHERE snapshot_id=OLD.snapshot_id
    ) OR EXISTS (
        SELECT 1 FROM run_selections WHERE snapshot_id=OLD.snapshot_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'corpus snapshot is still referenced');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS analytics_corpus_item_delete_guard
    BEFORE DELETE ON corpus_items
    WHEN EXISTS (
        SELECT 1 FROM embedding_items
        WHERE snapshot_item_id=OLD.snapshot_item_id
    ) OR EXISTS (
        SELECT 1 FROM cluster_assignments
        WHERE snapshot_item_id=OLD.snapshot_item_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'corpus item is still referenced');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS analytics_embedding_item_generation_guard
    BEFORE INSERT ON embedding_items
    WHEN NOT EXISTS (
        SELECT 1 FROM embedding_generations
        WHERE embedding_generation_id=NEW.embedding_generation_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'unknown embedding generation');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS analytics_embedding_item_update_guard
    BEFORE UPDATE OF embedding_generation_id, snapshot_item_id
    ON embedding_items
    WHEN NOT EXISTS (
        SELECT 1 FROM embedding_generations
        WHERE embedding_generation_id=NEW.embedding_generation_id
    ) OR NOT EXISTS (
        SELECT 1 FROM corpus_items
        WHERE snapshot_item_id=NEW.snapshot_item_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'invalid embedding item reference');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS analytics_generation_delete_guard
    BEFORE DELETE ON embedding_generations
    WHEN EXISTS (
        SELECT 1 FROM embedding_items
        WHERE embedding_generation_id=OLD.embedding_generation_id
    ) OR EXISTS (
        SELECT 1 FROM clustering_runs
        WHERE embedding_generation_id=OLD.embedding_generation_id
    ) OR EXISTS (
        SELECT 1 FROM profile_batches
        WHERE embedding_generation_id=OLD.embedding_generation_id
    ) OR EXISTS (
        SELECT 1 FROM run_selections
        WHERE embedding_generation_id=OLD.embedding_generation_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'embedding generation is still referenced');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS analytics_embedding_item_snapshot_guard
    BEFORE INSERT ON embedding_items
    WHEN NOT EXISTS (
        SELECT 1 FROM corpus_items
        WHERE snapshot_item_id=NEW.snapshot_item_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'unknown snapshot item');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS analytics_clustering_run_guard
    BEFORE INSERT ON clustering_runs
    WHEN NOT EXISTS (
        SELECT 1 FROM corpus_snapshots WHERE snapshot_id=NEW.snapshot_id
    ) OR NOT EXISTS (
        SELECT 1 FROM embedding_generations
        WHERE embedding_generation_id=NEW.embedding_generation_id
    ) OR NEW.status NOT IN ('pending', 'running', 'completed', 'failed')
    BEGIN
        SELECT RAISE(ABORT, 'invalid clustering run reference or status');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS analytics_clustering_run_update_guard
    BEFORE UPDATE OF snapshot_id, embedding_generation_id, status
    ON clustering_runs
    WHEN NOT EXISTS (
        SELECT 1 FROM corpus_snapshots WHERE snapshot_id=NEW.snapshot_id
    ) OR NOT EXISTS (
        SELECT 1 FROM embedding_generations
        WHERE embedding_generation_id=NEW.embedding_generation_id
    ) OR NEW.status NOT IN ('pending', 'running', 'completed', 'failed')
    BEGIN
        SELECT RAISE(ABORT, 'invalid clustering run reference or status');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS analytics_clustering_run_delete_guard
    BEFORE DELETE ON clustering_runs
    WHEN EXISTS (
        SELECT 1 FROM cluster_assignments
        WHERE clustering_run_id=OLD.clustering_run_id
    ) OR EXISTS (
        SELECT 1 FROM cluster_summaries
        WHERE clustering_run_id=OLD.clustering_run_id
    ) OR EXISTS (
        SELECT 1 FROM profile_batch_runs
        WHERE clustering_run_id=OLD.clustering_run_id
    ) OR EXISTS (
        SELECT 1 FROM profile_assessments
        WHERE clustering_run_id=OLD.clustering_run_id
    ) OR EXISTS (
        SELECT 1 FROM run_selections
        WHERE selected_run_id=OLD.clustering_run_id
    ) OR EXISTS (
        SELECT 1 FROM profile_batches
        WHERE recommended_clustering_run_id=OLD.clustering_run_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'clustering run is still referenced');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS analytics_assignment_guard
    BEFORE INSERT ON cluster_assignments
    WHEN NOT EXISTS (
        SELECT 1
        FROM clustering_runs AS run
        JOIN corpus_items AS item ON item.snapshot_id=run.snapshot_id
        WHERE run.clustering_run_id=NEW.clustering_run_id
          AND item.snapshot_item_id=NEW.snapshot_item_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'assignment does not belong to run snapshot');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS analytics_assignment_update_guard
    BEFORE UPDATE OF clustering_run_id, snapshot_item_id
    ON cluster_assignments
    WHEN NOT EXISTS (
        SELECT 1
        FROM clustering_runs AS run
        JOIN corpus_items AS item ON item.snapshot_id=run.snapshot_id
        WHERE run.clustering_run_id=NEW.clustering_run_id
          AND item.snapshot_item_id=NEW.snapshot_item_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'assignment does not belong to run snapshot');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS analytics_summary_guard
    BEFORE INSERT ON cluster_summaries
    WHEN NOT EXISTS (
        SELECT 1 FROM clustering_runs
        WHERE clustering_run_id=NEW.clustering_run_id
    ) OR NOT EXISTS (
        SELECT 1 FROM cluster_assignments
        WHERE clustering_run_id=NEW.clustering_run_id
          AND cluster_label=NEW.cluster_label
    )
    BEGIN
        SELECT RAISE(ABORT, 'summary has no matching run assignments');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS analytics_summary_update_guard
    BEFORE UPDATE OF clustering_run_id, cluster_label
    ON cluster_summaries
    WHEN NOT EXISTS (
        SELECT 1 FROM clustering_runs
        WHERE clustering_run_id=NEW.clustering_run_id
    ) OR NOT EXISTS (
        SELECT 1 FROM cluster_assignments
        WHERE clustering_run_id=NEW.clustering_run_id
          AND cluster_label=NEW.cluster_label
    )
    BEGIN
        SELECT RAISE(ABORT, 'summary has no matching run assignments');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS analytics_profile_batch_guard
    BEFORE INSERT ON profile_batches
    WHEN NOT EXISTS (
        SELECT 1 FROM corpus_snapshots WHERE snapshot_id=NEW.snapshot_id
    ) OR NOT EXISTS (
        SELECT 1 FROM embedding_generations
        WHERE embedding_generation_id=NEW.embedding_generation_id
    ) OR NEW.status != 'running'
      OR NEW.candidate_count_planned <= 0
      OR NEW.candidate_count_succeeded != 0
      OR NEW.candidate_count_failed != 0
      OR NEW.finished_at_utc IS NOT NULL
      OR NEW.recommended_clustering_run_id IS NOT NULL
      OR NEW.recommendation_rationale_json IS NOT NULL
      OR NEW.batch_max_cluster_count IS NOT NULL
    BEGIN
        SELECT RAISE(ABORT, 'invalid profile batch');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS analytics_profile_batch_update_guard
    BEFORE UPDATE ON profile_batches
    WHEN NEW.profile_batch_id != OLD.profile_batch_id
      OR NEW.snapshot_id != OLD.snapshot_id
      OR NEW.embedding_generation_id != OLD.embedding_generation_id
      OR NEW.profile_id != OLD.profile_id
      OR NEW.profile_manifest_digest != OLD.profile_manifest_digest
      OR NEW.candidate_space_digest != OLD.candidate_space_digest
      OR NEW.started_at_utc != OLD.started_at_utc
      OR NEW.created_at_utc != OLD.created_at_utc
      OR OLD.status != 'running'
      OR NEW.status NOT IN ('completed', 'completed_partial', 'failed')
      OR NEW.candidate_count_planned <= 0
      OR NEW.candidate_count_succeeded < 0
      OR NEW.candidate_count_failed < 0
      OR NEW.finished_at_utc IS NULL
      OR NEW.candidate_count_succeeded + NEW.candidate_count_failed
         != NEW.candidate_count_planned
      OR (
          NEW.status = 'completed'
          AND NEW.candidate_count_failed != 0
      )
      OR (
          NEW.status = 'completed_partial'
          AND (
              NEW.candidate_count_succeeded = 0
              OR NEW.candidate_count_failed = 0
          )
      )
      OR (
          NEW.status = 'failed'
          AND NEW.candidate_count_succeeded != 0
      )
      OR (
          (NEW.recommended_clustering_run_id IS NULL)
          != (NEW.recommendation_rationale_json IS NULL)
      )
      OR (
          NEW.recommended_clustering_run_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM profile_batch_runs
              WHERE profile_batch_id=NEW.profile_batch_id
                AND clustering_run_id=NEW.recommended_clustering_run_id
          )
      )
    BEGIN
        SELECT RAISE(ABORT, 'immutable profile batch identity changed');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS analytics_profile_batch_run_guard
    BEFORE INSERT ON profile_batch_runs
    WHEN NEW.candidate_ordinal < 0
      OR NOT EXISTS (
        SELECT 1
        FROM profile_batches AS batch
        JOIN clustering_runs AS run
          ON run.snapshot_id=batch.snapshot_id
         AND run.embedding_generation_id=batch.embedding_generation_id
        WHERE batch.profile_batch_id=NEW.profile_batch_id
          AND run.clustering_run_id=NEW.clustering_run_id
          AND batch.status='running'
          AND run.status='completed'
      )
    BEGIN
        SELECT RAISE(ABORT, 'profile batch run scope mismatch');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS analytics_profile_assessment_guard
    BEFORE INSERT ON profile_assessments
    WHEN NEW.suitable_for_profile NOT IN (0, 1)
      OR NOT EXISTS (
        SELECT 1
        FROM profile_batch_runs AS member
        JOIN profile_batches AS batch
          ON batch.profile_batch_id=member.profile_batch_id
        JOIN profile_manifest_snapshots AS manifest
          ON manifest.profile_manifest_digest=batch.profile_manifest_digest
        WHERE member.profile_batch_id=NEW.profile_batch_id
          AND member.clustering_run_id=NEW.clustering_run_id
          AND batch.profile_id=NEW.profile_id
          AND batch.profile_manifest_digest=NEW.profile_manifest_digest
          AND batch.status='running'
          AND manifest.profile_version=NEW.profile_version
      )
    BEGIN
        SELECT RAISE(ABORT, 'profile assessment scope mismatch');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS analytics_run_selection_guard
    BEFORE INSERT ON run_selections
    WHEN NOT EXISTS (
        SELECT 1 FROM clustering_runs AS run
        WHERE run.clustering_run_id=NEW.selected_run_id
          AND run.snapshot_id=NEW.snapshot_id
          AND run.embedding_generation_id=NEW.embedding_generation_id
    ) OR (
        NEW.profile_batch_id IS NOT NULL
        AND NOT EXISTS (
            SELECT 1
            FROM profile_batch_runs AS member
            JOIN profile_batches AS batch
              ON batch.profile_batch_id=member.profile_batch_id
            WHERE member.profile_batch_id=NEW.profile_batch_id
              AND member.clustering_run_id=NEW.selected_run_id
              AND batch.profile_id=NEW.profile_id
              AND batch.profile_manifest_digest=NEW.profile_manifest_digest
        )
    ) OR (
        NEW.profile_batch_id IS NULL
        AND (
            NEW.profile_id IS NOT NULL
            OR NEW.profile_manifest_digest IS NOT NULL
        )
    )
    BEGIN
        SELECT RAISE(ABORT, 'selection scope mismatch');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS analytics_profile_manifest_update_guard
    BEFORE UPDATE ON profile_manifest_snapshots
    BEGIN
        SELECT RAISE(ABORT, 'profile manifest snapshot is immutable');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS analytics_profile_manifest_delete_guard
    BEFORE DELETE ON profile_manifest_snapshots
    BEGIN
        SELECT RAISE(ABORT, 'profile manifest snapshot is immutable');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS analytics_profile_batch_delete_guard
    BEFORE DELETE ON profile_batches
    BEGIN
        SELECT RAISE(ABORT, 'profile batch is immutable');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS analytics_profile_batch_run_update_guard
    BEFORE UPDATE ON profile_batch_runs
    BEGIN
        SELECT RAISE(ABORT, 'profile batch membership is immutable');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS analytics_profile_batch_run_delete_guard
    BEFORE DELETE ON profile_batch_runs
    BEGIN
        SELECT RAISE(ABORT, 'profile batch membership is immutable');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS analytics_profile_assessment_update_guard
    BEFORE UPDATE ON profile_assessments
    BEGIN
        SELECT RAISE(ABORT, 'profile assessment is immutable');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS analytics_profile_assessment_delete_guard
    BEFORE DELETE ON profile_assessments
    BEGIN
        SELECT RAISE(ABORT, 'profile assessment is immutable');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS analytics_run_selection_update_guard
    BEFORE UPDATE ON run_selections
    BEGIN
        SELECT RAISE(ABORT, 'run selection is append-only');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS analytics_run_selection_delete_guard
    BEFORE DELETE ON run_selections
    BEGIN
        SELECT RAISE(ABORT, 'run selection is append-only');
    END
    """,
)

_CONTROL_PLANE_TRIGGER_MARKERS = (
    "analytics_profile_batch_guard",
    "analytics_profile_batch_update_guard",
    "analytics_profile_batch_run_guard",
    "analytics_profile_assessment_guard",
    "analytics_run_selection_guard",
    "analytics_profile_manifest_update_guard",
    "analytics_profile_manifest_delete_guard",
    "analytics_profile_batch_delete_guard",
    "analytics_profile_batch_run_update_guard",
    "analytics_profile_batch_run_delete_guard",
    "analytics_profile_assessment_update_guard",
    "analytics_profile_assessment_delete_guard",
    "analytics_run_selection_update_guard",
    "analytics_run_selection_delete_guard",
)


def _install_indexes(
    conn: sqlite3.Connection,
    *,
    include_control_plane: bool,
) -> None:
    for statement in _INDEXES:
        if not include_control_plane and any(
            marker in statement for marker in _CONTROL_PLANE_INDEX_MARKERS
        ):
            continue
        conn.execute(statement)


def _install_integrity_triggers(
    conn: sqlite3.Connection,
    *,
    include_control_plane: bool = True,
) -> None:
    for statement in _INTEGRITY_TRIGGERS:
        if not include_control_plane and (
            any(marker in statement for marker in _CONTROL_PLANE_TRIGGER_MARKERS)
            or "profile_" in statement
            or "run_selections" in statement
        ):
            continue
        conn.execute(statement)


def _migrate_1_0_to_1_1(conn: sqlite3.Connection) -> None:
    orphan_checks = (
        (
            "corpus_items",
            "SELECT COUNT(*) FROM corpus_items AS item "
            "LEFT JOIN corpus_snapshots AS snap "
            "ON snap.snapshot_id=item.snapshot_id "
            "WHERE snap.snapshot_id IS NULL",
        ),
        (
            "embedding_items",
            "SELECT COUNT(*) FROM embedding_items AS item "
            "LEFT JOIN embedding_generations AS generation "
            "ON generation.embedding_generation_id=item.embedding_generation_id "
            "LEFT JOIN corpus_items AS corpus "
            "ON corpus.snapshot_item_id=item.snapshot_item_id "
            "WHERE generation.embedding_generation_id IS NULL "
            "OR corpus.snapshot_item_id IS NULL",
        ),
        (
            "clustering_runs",
            "SELECT COUNT(*) FROM clustering_runs AS run "
            "LEFT JOIN corpus_snapshots AS snap "
            "ON snap.snapshot_id=run.snapshot_id "
            "LEFT JOIN embedding_generations AS generation "
            "ON generation.embedding_generation_id=run.embedding_generation_id "
            "WHERE snap.snapshot_id IS NULL "
            "OR generation.embedding_generation_id IS NULL "
            "OR run.status NOT IN ('pending','running','completed','failed')",
        ),
        (
            "cluster_assignments",
            "SELECT COUNT(*) FROM cluster_assignments AS assignment "
            "LEFT JOIN clustering_runs AS run "
            "ON run.clustering_run_id=assignment.clustering_run_id "
            "LEFT JOIN corpus_items AS item "
            "ON item.snapshot_id=run.snapshot_id "
            "AND item.snapshot_item_id=assignment.snapshot_item_id "
            "WHERE run.clustering_run_id IS NULL "
            "OR item.snapshot_item_id IS NULL",
        ),
        (
            "cluster_summaries",
            "SELECT COUNT(*) FROM cluster_summaries AS summary "
            "LEFT JOIN clustering_runs AS run "
            "ON run.clustering_run_id=summary.clustering_run_id "
            "LEFT JOIN cluster_assignments AS assignment "
            "ON assignment.clustering_run_id=summary.clustering_run_id "
            "AND assignment.cluster_label=summary.cluster_label "
            "WHERE run.clustering_run_id IS NULL "
            "OR assignment.snapshot_item_id IS NULL",
        ),
        (
            "embedding_items.vector_row_key",
            "SELECT COUNT(*) FROM ("
            "SELECT vector_row_key FROM embedding_items "
            "GROUP BY vector_row_key HAVING COUNT(*) > 1"
            ")",
        ),
        (
            "cluster_summaries.display_cluster_id",
            "SELECT COUNT(*) FROM ("
            "SELECT clustering_run_id, display_cluster_id "
            "FROM cluster_summaries "
            "WHERE display_cluster_id IS NOT NULL "
            "GROUP BY clustering_run_id, display_cluster_id "
            "HAVING COUNT(*) > 1"
            ")",
        ),
    )
    for table, query in orphan_checks:
        count = int(conn.execute(query).fetchone()[0])
        if count:
            raise AnalyticsStoreError(
                f"cannot migrate analytics schema: {table} has {count} "
                "invalid reference(s)"
            )
    _install_indexes(conn, include_control_plane=False)
    _install_integrity_triggers(conn, include_control_plane=False)
    conn.execute(
        f"UPDATE {_ANALYTICS_META_TABLE} SET value=? WHERE key='schema_version'",
        ("1.1",),
    )
    conn.commit()


def _migrate_1_1_to_1_2(conn: sqlite3.Connection) -> None:
    for statement in _CONTROL_PLANE_DDL:
        conn.execute(statement)
    for trigger in (
        "analytics_snapshot_delete_guard",
        "analytics_generation_delete_guard",
        "analytics_clustering_run_delete_guard",
    ):
        conn.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    _install_indexes(conn, include_control_plane=True)
    _install_integrity_triggers(conn)
    _backfill_legacy_selections(conn)
    conn.execute(
        f"UPDATE {_ANALYTICS_META_TABLE} SET value=? WHERE key='schema_version'",
        ("1.2",),
    )
    conn.commit()


def _backfill_legacy_selections(conn: sqlite3.Connection) -> None:
    scopes = conn.execute(
        """
        SELECT snapshot_id, embedding_generation_id, COUNT(*) AS selected_count
        FROM clustering_runs
        WHERE selected_by_maintainer=1
        GROUP BY snapshot_id, embedding_generation_id
        ORDER BY snapshot_id, embedding_generation_id
        """
    ).fetchall()
    for snapshot_id, embedding_generation_id, selected_count in scopes:
        existing = conn.execute(
            """
            SELECT 1 FROM run_selections
            WHERE snapshot_id=? AND embedding_generation_id=?
              AND profile_batch_id IS NULL
            LIMIT 1
            """,
            (snapshot_id, embedding_generation_id),
        ).fetchone()
        if existing is not None:
            continue
        if int(selected_count) > 1:
            scope = f"{snapshot_id}|{embedding_generation_id}"
            suffix = hashlib.sha256(scope.encode("utf-8")).hexdigest()[:16]
            conn.execute(
                f"INSERT OR REPLACE INTO {_ANALYTICS_META_TABLE}(key, value) "
                "VALUES (?, ?)",
                (
                    f"diagnostic.LEGACY_SELECTION_AMBIGUOUS.{suffix}",
                    json.dumps(
                        {
                            "code": "LEGACY_SELECTION_AMBIGUOUS",
                            "snapshot_id": str(snapshot_id),
                            "embedding_generation_id": str(embedding_generation_id),
                            "selected_count": int(selected_count),
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                ),
            )
            continue
        run = conn.execute(
            """
            SELECT clustering_run_id, finished_at_utc, created_at_utc
            FROM clustering_runs
            WHERE snapshot_id=? AND embedding_generation_id=?
              AND selected_by_maintainer=1
            """,
            (snapshot_id, embedding_generation_id),
        ).fetchone()
        if run is None:
            continue
        run_id = str(run[0])
        identity = f"{snapshot_id}|{embedding_generation_id}|{run_id}"
        selection_id = (
            "sel-legacy-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO run_selections (
                selection_id, snapshot_id, embedding_generation_id,
                profile_batch_id, profile_id, profile_manifest_digest,
                selected_run_id, selected_at_utc, selected_by, rationale,
                supersedes_selection_id
            ) VALUES (?, ?, ?, NULL, NULL, NULL, ?, ?, ?, NULL, NULL)
            """,
            (
                selection_id,
                snapshot_id,
                embedding_generation_id,
                run_id,
                str(run[1] or run[2]),
                "legacy-migration",
            ),
        )


def ensure_analytics_schema(conn: sqlite3.Connection) -> None:
    current = get_meta_value(
        conn, meta_table=_ANALYTICS_META_TABLE, key="schema_version"
    )
    if current == "1.0":
        _migrate_1_0_to_1_1(conn)
        current = "1.1"
    if current == "1.1":
        _migrate_1_1_to_1_2(conn)
        return
    if current is not None and current != CORPUS_ANALYTICS_STORE_SCHEMA_VERSION:
        raise AnalyticsStoreError(f"unsupported analytics schema version: {current}")
    if current is None:
        initialize_schema_v1(
            conn,
            ddl_statements=_DDL,
            index_statements=_INDEXES,
            meta_table=_ANALYTICS_META_TABLE,
            seed_meta={
                "schema_version": CORPUS_ANALYTICS_STORE_SCHEMA_VERSION,
                "created_at_utc": current_report_timestamp_utc(),
            },
        )
        _install_integrity_triggers(conn)
        conn.commit()


def validate_analytics_schema(conn: sqlite3.Connection) -> None:
    current = get_meta_value(
        conn, meta_table=_ANALYTICS_META_TABLE, key="schema_version"
    )
    if current != CORPUS_ANALYTICS_STORE_SCHEMA_VERSION:
        raise AnalyticsStoreError(
            "analytics store requires writable migration to schema "
            f"{CORPUS_ANALYTICS_STORE_SCHEMA_VERSION}; found {current or 'missing'}"
        )


def open_analytics_db(path: Path) -> sqlite3.Connection:
    from ..observability.sqlite_access import open_instrumented_sqlite_db

    return open_instrumented_sqlite_db(
        path,
        ensure_schema=ensure_analytics_schema,
        foreign_keys=True,
    )


def open_analytics_db_readonly(path: Path) -> sqlite3.Connection:
    from ..observability.sqlite_access import open_instrumented_sqlite_db_readonly

    return open_instrumented_sqlite_db_readonly(
        path,
        validate_schema=validate_analytics_schema,
    )


__all__ = [
    "ensure_analytics_schema",
    "open_analytics_db",
    "open_analytics_db_readonly",
    "validate_analytics_schema",
]
