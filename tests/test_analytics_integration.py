# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.analytics.capabilities import check_capability
from codeclone.analytics.clustering.models import ClusteringParameters
from codeclone.analytics.clustering.pipeline import run_clustering_pipeline
from codeclone.analytics.contracts import INTENT_REPRESENTATION_DESCRIPTION
from codeclone.analytics.embedding.generation import EmbeddingBatchResult
from codeclone.analytics.schema import open_analytics_db
from codeclone.analytics.store.protocols import SnapshotBuildResult
from codeclone.analytics.store.sqlite import SqliteCorpusAnalyticsStore
from codeclone.analytics.workflow import (
    run_clustering,
    run_embed,
    run_snapshot,
    select_cluster_run,
)
from codeclone.config.analytics import AnalyticsConfig, resolve_analytics_config
from codeclone.memory.embedding import DeterministicHashEmbeddingProvider
from tests.fixtures.analytics.helpers import write_intent_declared_event


@pytest.fixture
def analytics_repo(tmp_path: Path) -> tuple[Path, Path, AnalyticsConfig]:
    root = tmp_path / "repo"
    root.mkdir()
    audit_db = root / ".codeclone" / "db" / "audit.sqlite3"
    audit_db.parent.mkdir(parents=True)
    write_intent_declared_event(
        db_path=audit_db,
        repo_root=root,
        intent_id="intent-a",
        description="Implement corpus analytics slice",
        audit_sequence=1,
    )
    write_intent_declared_event(
        db_path=audit_db,
        repo_root=root,
        intent_id="intent-b",
        description="Refactor clustering pipeline",
        audit_sequence=2,
    )
    for index in range(3, 13):
        write_intent_declared_event(
            db_path=audit_db,
            repo_root=root,
            intent_id=f"intent-{index}",
            description=f"Intent workload {index} for clustering",
            audit_sequence=index,
        )
    config = resolve_analytics_config(root)
    return root, audit_db, config


def _snapshot_and_embed(
    analytics_repo: tuple[Path, Path, AnalyticsConfig],
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, AnalyticsConfig, SnapshotBuildResult, EmbeddingBatchResult]:
    """Build a snapshot and embed it with the deterministic provider, with the
    memory DB stubbed out so the corpus is audit-only."""
    root, _audit_db, config = analytics_repo
    monkeypatch.setattr(
        "codeclone.analytics.corpus.snapshot.resolve_memory_db_path",
        lambda _root: config.db_path.parent / "missing.sqlite3",
    )
    snapshot = run_snapshot(
        root_path=root,
        representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
        config=config,
    )
    provider = DeterministicHashEmbeddingProvider(dimension=config.embedding_dimension)
    monkeypatch.setattr(
        "codeclone.analytics.embedding.generation._resolve_fastembed_provider",
        lambda _config: provider,
    )
    embed = run_embed(root_path=root, snapshot_id=snapshot.snapshot_id, config=config)
    return root, config, snapshot, embed


def test_embedding_lancedb_only(
    analytics_repo: tuple[Path, Path, AnalyticsConfig],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _root, config, _snapshot, embed = _snapshot_and_embed(analytics_repo, monkeypatch)
    conn = open_analytics_db(config.db_path)
    try:
        rows = conn.execute(
            "SELECT vector_row_key, vector_digest FROM embedding_items "
            "WHERE embedding_generation_id=?",
            (embed.embedding_generation_id,),
        ).fetchall()
        assert rows
        for row in rows:
            assert row[0]
            assert row[1]
        blob_rows = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='embedding_items'"
        ).fetchone()
        assert blob_rows is not None
        assert "BLOB" not in str(blob_rows[0]).upper()
    finally:
        conn.close()


def test_inspect_commands_without_fastembed(
    analytics_repo: tuple[Path, Path, AnalyticsConfig],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _audit_db, config = analytics_repo
    monkeypatch.setattr(
        "codeclone.analytics.corpus.snapshot.resolve_memory_db_path",
        lambda _root: config.db_path.parent / "missing.sqlite3",
    )
    snapshot = run_snapshot(
        root_path=root,
        representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
        config=config,
    )
    store = SqliteCorpusAnalyticsStore.open_readonly(config.db_path)
    try:
        runs = store.list_clustering_runs(snapshot_id=snapshot.snapshot_id)
        assert runs == ()
    finally:
        store.close()
    assert check_capability("base").available is True


@pytest.mark.skipif(
    not check_capability("cluster").available,
    reason="analytics clustering deps not installed",
)
def test_cluster_partition_deterministic(
    analytics_repo: tuple[Path, Path, AnalyticsConfig],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _root, config, snapshot, embed = _snapshot_and_embed(analytics_repo, monkeypatch)
    params = ClusteringParameters(
        pca_dimensions=8,
        min_cluster_size=3,
        min_samples=1,
        cluster_selection_method="eom",
    )
    store = SqliteCorpusAnalyticsStore.open(config.db_path)
    vector_store_path = config.vectors_path
    try:
        from codeclone.analytics.embedding.generation import load_snapshot_vectors
        from codeclone.analytics.store.vectors_lancedb import AnalyticsVectorStore

        items = store.list_items(snapshot.snapshot_id)
        vectors = load_snapshot_vectors(
            vector_store=AnalyticsVectorStore(
                path=vector_store_path,
                dimension=config.embedding_dimension,
            ),
            embedding_generation_id=embed.embedding_generation_id,
            items=items,
        )
        item_ids = [item.snapshot_item_id for item in items]
        first = run_clustering_pipeline(
            snapshot_item_ids=item_ids,
            embeddings=vectors,
            requested=params,
        )
        second = run_clustering_pipeline(
            snapshot_item_ids=item_ids,
            embeddings=vectors,
            requested=params,
        )
        assert first is not None and second is not None
        first_digests = sorted(part.membership_digest for part in first.partitions)
        second_digests = sorted(part.membership_digest for part in second.partitions)
        assert first_digests == second_digests
    finally:
        store.close()


@pytest.mark.skipif(
    not check_capability("cluster").available,
    reason="analytics clustering deps not installed",
)
def test_sweep_selection_flags(
    analytics_repo: tuple[Path, Path, AnalyticsConfig],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, config, snapshot, embed = _snapshot_and_embed(analytics_repo, monkeypatch)
    run_ids = run_clustering(
        root_path=root,
        snapshot_id=snapshot.snapshot_id,
        embedding_generation_id=embed.embedding_generation_id,
        sweep=True,
        config=config,
    )
    store = SqliteCorpusAnalyticsStore.open(config.db_path)
    try:
        runs = store.list_clustering_runs(
            snapshot_id=snapshot.snapshot_id,
            embedding_generation_id=embed.embedding_generation_id,
        )
        recommended = [run for run in runs if run.recommended_by_heuristic]
        assert len(recommended) == 1
        assert all(not run.selected_by_maintainer for run in runs)
        select_cluster_run(root_path=root, clustering_run_id=run_ids[0], config=config)
        runs = store.list_clustering_runs(
            snapshot_id=snapshot.snapshot_id,
            embedding_generation_id=embed.embedding_generation_id,
        )
        selected = [run for run in runs if run.selected_by_maintainer]
        assert len(selected) == 1
        assert selected[0].clustering_run_id == run_ids[0]
    finally:
        store.close()


def test_no_semantic_index_reuse(
    analytics_repo: tuple[Path, Path, AnalyticsConfig],
) -> None:
    _root, _audit_db, config = analytics_repo
    assert config.vectors_path.name == "corpus_vectors"
    assert ".codeclone/analytics/corpus_vectors" in config.vectors_path.as_posix()
