# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

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
)


def _install_integrity_triggers(conn: sqlite3.Connection) -> None:
    for statement in _INTEGRITY_TRIGGERS:
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
    for statement in _INDEXES:
        conn.execute(statement)
    _install_integrity_triggers(conn)
    conn.execute(
        f"UPDATE {_ANALYTICS_META_TABLE} SET value=? WHERE key='schema_version'",
        (CORPUS_ANALYTICS_STORE_SCHEMA_VERSION,),
    )
    conn.commit()


def ensure_analytics_schema(conn: sqlite3.Connection) -> None:
    current = get_meta_value(
        conn, meta_table=_ANALYTICS_META_TABLE, key="schema_version"
    )
    if current == "1.0":
        _migrate_1_0_to_1_1(conn)
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
