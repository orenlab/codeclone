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
)


def ensure_analytics_schema(conn: sqlite3.Connection) -> None:
    current = get_meta_value(
        conn, meta_table=_ANALYTICS_META_TABLE, key="schema_version"
    )
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


def open_analytics_db(path: Path) -> sqlite3.Connection:
    from ..observability.sqlite_access import open_instrumented_sqlite_db

    return open_instrumented_sqlite_db(path, ensure_schema=ensure_analytics_schema)


def open_analytics_db_readonly(path: Path) -> sqlite3.Connection:
    from ..observability.sqlite_access import open_instrumented_sqlite_db_readonly

    return open_instrumented_sqlite_db_readonly(
        path,
        validate_schema=ensure_analytics_schema,
    )


__all__ = [
    "ensure_analytics_schema",
    "open_analytics_db",
    "open_analytics_db_readonly",
]
