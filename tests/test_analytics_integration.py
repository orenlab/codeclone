# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

from codeclone.analytics import workflow
from codeclone.analytics.capabilities import check_capability
from codeclone.analytics.clustering.models import ClusteringParameters
from codeclone.analytics.clustering.pipeline import run_clustering_pipeline
from codeclone.analytics.contracts import (
    INTENT_REPRESENTATION_DESCRIPTION,
    ClusteringRunRecord,
)
from codeclone.analytics.embedding.generation import (
    EmbeddingBatchResult,
    generate_embeddings_for_snapshot,
)
from codeclone.analytics.exceptions import AnalyticsWorkflowError
from codeclone.analytics.export.json_export import export_clustering_json
from codeclone.analytics.schema import open_analytics_db
from codeclone.analytics.store.protocols import SnapshotBuildResult
from codeclone.analytics.store.sqlite import SqliteCorpusAnalyticsStore
from codeclone.analytics.workflow import (
    BuildResult,
    run_build,
    run_clustering,
    run_embed,
    run_snapshot,
    select_cluster_run,
)
from codeclone.config.analytics import AnalyticsConfig, resolve_analytics_config
from codeclone.config.observability import ObservabilityConfig
from codeclone.contracts import CORPUS_EXPORT_SCHEMA_VERSION
from codeclone.memory.embedding import DeterministicHashEmbeddingProvider
from codeclone.observability import bootstrap, operation, shutdown
from codeclone.observability.store.schema import (
    observability_store_path,
    open_observability_store,
)
from codeclone.surfaces.cli.analytics import _write_build_exports
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


@pytest.mark.skipif(
    not check_capability("cluster").available,
    reason="analytics clustering deps not installed",
)
def test_clustering_rejects_missing_embedding_generation_manifest(
    analytics_repo: tuple[Path, Path, AnalyticsConfig],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, config, snapshot, embed = _snapshot_and_embed(analytics_repo, monkeypatch)
    conn = open_analytics_db(config.db_path)
    try:
        conn.execute(
            "DELETE FROM embedding_items WHERE embedding_generation_id=?",
            (embed.embedding_generation_id,),
        )
        conn.execute(
            "DELETE FROM embedding_generations WHERE embedding_generation_id=?",
            (embed.embedding_generation_id,),
        )
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(AnalyticsWorkflowError, match="unknown embedding generation"):
        run_clustering(
            root_path=root,
            snapshot_id=snapshot.snapshot_id,
            embedding_generation_id=embed.embedding_generation_id,
            config=config,
        )


@pytest.mark.skipif(
    not check_capability("cluster").available,
    reason="analytics clustering deps not installed",
)
def test_clustering_rejects_stale_embedding_contract(
    analytics_repo: tuple[Path, Path, AnalyticsConfig],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, config, snapshot, embed = _snapshot_and_embed(analytics_repo, monkeypatch)
    conn = open_analytics_db(config.db_path)
    try:
        conn.execute(
            "UPDATE embedding_generations "
            "SET embedding_contract_version='1' "
            "WHERE embedding_generation_id=?",
            (embed.embedding_generation_id,),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(
        AnalyticsWorkflowError,
        match="unsupported analytics embedding contract",
    ):
        run_clustering(
            root_path=root,
            snapshot_id=snapshot.snapshot_id,
            embedding_generation_id=embed.embedding_generation_id,
            config=config,
        )


@pytest.mark.skipif(
    not check_capability("cluster").available,
    reason="analytics clustering deps not installed",
)
def test_clustering_rejects_foreign_vector_in_generation(
    analytics_repo: tuple[Path, Path, AnalyticsConfig],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, config, snapshot, embed = _snapshot_and_embed(analytics_repo, monkeypatch)
    from codeclone.analytics.store.vectors_lancedb import AnalyticsVectorStore

    vector_store = AnalyticsVectorStore(
        path=config.vectors_path,
        dimension=config.embedding_dimension,
    )
    try:
        vector_store.write_vectors(
            embedding_generation_id=embed.embedding_generation_id,
            rows=[
                {
                    "snapshot_item_id": "foreign-item",
                    "vector": [0.0] * config.embedding_dimension,
                }
            ],
        )
    finally:
        vector_store.close()

    with pytest.raises(
        AnalyticsWorkflowError,
        match="vector generation does not match embedding metadata",
    ):
        run_clustering(
            root_path=root,
            snapshot_id=snapshot.snapshot_id,
            embedding_generation_id=embed.embedding_generation_id,
            config=config,
        )


@pytest.mark.skipif(
    not check_capability("cluster").available,
    reason="analytics clustering deps not installed",
)
def test_failed_clustering_run_is_persisted_without_partial_artifacts(
    analytics_repo: tuple[Path, Path, AnalyticsConfig],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, config, snapshot, embed = _snapshot_and_embed(analytics_repo, monkeypatch)
    monkeypatch.setattr(
        "codeclone.analytics.workflow.run_clustering_pipeline",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("pipeline failed")),
    )

    with pytest.raises(RuntimeError, match="pipeline failed"):
        run_clustering(
            root_path=root,
            snapshot_id=snapshot.snapshot_id,
            embedding_generation_id=embed.embedding_generation_id,
            requested=ClusteringParameters(
                pca_dimensions=8,
                min_cluster_size=3,
                min_samples=1,
                cluster_selection_method="eom",
            ),
            config=config,
        )

    store = SqliteCorpusAnalyticsStore.open_readonly(config.db_path)
    try:
        (run,) = store.list_clustering_runs(
            snapshot_id=snapshot.snapshot_id,
            embedding_generation_id=embed.embedding_generation_id,
        )
        assert run.status == "failed"
        assert run.finished_at_utc is not None
        assert run.error_message == "pipeline failed"
        assert store.list_assignments(run.clustering_run_id) == ()
        assert store.list_summaries(run.clustering_run_id) == ()
    finally:
        store.close()


@pytest.mark.skipif(
    not check_capability("cluster").available,
    reason="analytics clustering deps not installed",
)
def test_exports_are_complete_and_report_span_is_observable(
    analytics_repo: tuple[Path, Path, AnalyticsConfig],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, config, snapshot, embed = _snapshot_and_embed(analytics_repo, monkeypatch)
    (run_id,) = run_clustering(
        root_path=root,
        snapshot_id=snapshot.snapshot_id,
        embedding_generation_id=embed.embedding_generation_id,
        requested=ClusteringParameters(
            pca_dimensions=8,
            min_cluster_size=3,
            min_samples=1,
            cluster_selection_method="eom",
        ),
        config=config,
    )
    json_out = root / "artifacts" / "analytics.json"
    html_out = root / "artifacts" / "analytics.html"
    args = Namespace(
        json_out=json_out,
        html_out=html_out,
        sweep=False,
        use_recommended=False,
    )
    bootstrap(ObservabilityConfig(enabled=True), root=root)
    try:
        with operation(name="test.analytics.report", surface="cli"):
            _write_build_exports(
                args=args,
                root=root,
                build_result=BuildResult(
                    snapshot_id=snapshot.snapshot_id,
                    embedding_generation_id=embed.embedding_generation_id,
                    clustering_run_ids=(run_id,),
                    recommended_run_id=None,
                ),
            )
    finally:
        shutdown()

    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["schema_version"] == CORPUS_EXPORT_SCHEMA_VERSION
    assert payload["snapshot"]["snapshot_id"] == snapshot.snapshot_id
    assert payload["embedding_generation"]["embedding_generation_id"] == (
        embed.embedding_generation_id
    )
    assert payload["embedding_items"]
    assert payload["assignments"]
    assert payload["clusters"]
    assert payload["sweep_candidates"]
    assert payload["exact_model_artifact_reproducibility"] is False
    assert "not guaranteed" in payload["reproducibility_statement"]

    html_text = html_out.read_text(encoding="utf-8")
    assert "Corpus Analytics Cluster Report" in html_text
    assert "Metadata correlations" in html_text
    assert "Numerator" in html_text
    assert "Denominator" in html_text
    assert "Full vector reproducibility is not guaranteed" in html_text

    conn = open_observability_store(observability_store_path(root))
    try:
        span_names = {row[0] for row in conn.execute("SELECT name FROM platform_spans")}
    finally:
        conn.close()
    assert "analytics.report" in span_names


@pytest.mark.skipif(
    not check_capability("cluster").available,
    reason="analytics clustering deps not installed",
)
def test_export_rejects_run_from_other_snapshot(
    analytics_repo: tuple[Path, Path, AnalyticsConfig],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, config, first_snapshot, embed = _snapshot_and_embed(
        analytics_repo, monkeypatch
    )
    (run_id,) = run_clustering(
        root_path=root,
        snapshot_id=first_snapshot.snapshot_id,
        embedding_generation_id=embed.embedding_generation_id,
        requested=ClusteringParameters(
            pca_dimensions=8,
            min_cluster_size=3,
            min_samples=1,
            cluster_selection_method="eom",
        ),
        config=config,
    )
    second_snapshot = run_snapshot(
        root_path=root,
        representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
        config=config,
    )
    store = SqliteCorpusAnalyticsStore.open_readonly(config.db_path)
    try:
        with pytest.raises(AnalyticsWorkflowError, match="belongs to snapshot"):
            export_clustering_json(
                store=store,
                snapshot_id=second_snapshot.snapshot_id,
                clustering_run_id=run_id,
            )
    finally:
        store.close()


def test_embedding_failure_rolls_back_metadata_and_cleans_vectors(
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
    store = SqliteCorpusAnalyticsStore.open(config.db_path)
    deleted: list[str] = []

    class FailingVectorStore:
        def write_vectors(self, **_kwargs: object) -> None:
            raise OSError("sidecar write failed")

        def delete_generation(self, embedding_generation_id: str) -> None:
            deleted.append(embedding_generation_id)

    provider = DeterministicHashEmbeddingProvider(dimension=config.embedding_dimension)
    try:
        with pytest.raises(OSError, match="sidecar write failed"):
            generate_embeddings_for_snapshot(
                store=store,
                vector_store=FailingVectorStore(),  # type: ignore[arg-type]
                config=config,
                snapshot_id=snapshot.snapshot_id,
                provider=provider,
            )
        assert store.list_embedding_items(embedding_generation_id=deleted[0]) == ()
        assert store.get_embedding_generation(deleted[0]) is None
    finally:
        store.close()


@pytest.mark.skipif(
    not check_capability("cluster").available,
    reason="analytics clustering deps not installed",
)
def test_sweep_rejects_corpus_with_no_valid_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    write_intent_declared_event(
        db_path=root / ".codeclone/db/audit.sqlite3",
        repo_root=root,
        intent_id="intent-a",
        description="Only one intent",
    )
    config = resolve_analytics_config(root)
    monkeypatch.setattr(
        "codeclone.analytics.corpus.snapshot.resolve_memory_db_path",
        lambda _root: config.db_path.parent / "missing.sqlite3",
    )
    monkeypatch.setattr(
        "codeclone.analytics.embedding.generation._resolve_fastembed_provider",
        lambda _config: DeterministicHashEmbeddingProvider(
            dimension=config.embedding_dimension
        ),
    )
    snapshot = run_snapshot(
        root_path=root,
        representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
        config=config,
    )
    embed = run_embed(
        root_path=root,
        snapshot_id=snapshot.snapshot_id,
        config=config,
    )
    with pytest.raises(AnalyticsWorkflowError, match="too small"):
        run_clustering(
            root_path=root,
            snapshot_id=snapshot.snapshot_id,
            embedding_generation_id=embed.embedding_generation_id,
            sweep=True,
            config=config,
        )


def test_run_build_reports_recommended_run_without_selecting_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = resolve_analytics_config(tmp_path)
    monkeypatch.setattr(
        workflow,
        "run_snapshot",
        lambda **_kwargs: SnapshotBuildResult("snapshot", "digest", 12),
    )
    monkeypatch.setattr(
        workflow,
        "run_embed",
        lambda **_kwargs: EmbeddingBatchResult("embedding", 12),
    )
    monkeypatch.setattr(
        workflow,
        "run_clustering",
        lambda **_kwargs: ("run-a", "run-b"),
    )
    runs = (
        ClusteringRunRecord(
            clustering_run_id="run-a",
            snapshot_id="snapshot",
            embedding_generation_id="embedding",
            requested_parameters_json="{}",
            effective_parameters_json="{}",
            random_seed=42,
            run_digest="digest-a",
            recommended_by_heuristic=False,
            selected_by_maintainer=False,
            status="completed",
            created_at_utc="2026-01-01T00:00:00Z",
            finished_at_utc="2026-01-01T00:00:01Z",
            error_message=None,
        ),
        ClusteringRunRecord(
            clustering_run_id="run-b",
            snapshot_id="snapshot",
            embedding_generation_id="embedding",
            requested_parameters_json="{}",
            effective_parameters_json="{}",
            random_seed=42,
            run_digest="digest-b",
            recommended_by_heuristic=True,
            selected_by_maintainer=False,
            status="completed",
            created_at_utc="2026-01-01T00:00:00Z",
            finished_at_utc="2026-01-01T00:00:01Z",
            error_message=None,
        ),
    )

    class _Store:
        closed = False

        def list_clustering_runs(
            self,
            *,
            snapshot_id: str,
            embedding_generation_id: str | None = None,
        ) -> tuple[ClusteringRunRecord, ...]:
            assert snapshot_id == "snapshot"
            assert embedding_generation_id == "embedding"
            return runs

        def close(self) -> None:
            self.closed = True

    store = _Store()
    monkeypatch.setattr(
        SqliteCorpusAnalyticsStore,
        "open",
        lambda _path: store,
    )
    result = run_build(
        root_path=tmp_path,
        representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
        sweep=True,
        use_recommended=True,
        config=config,
    )
    assert result == BuildResult(
        snapshot_id="snapshot",
        embedding_generation_id="embedding",
        clustering_run_ids=("run-a", "run-b"),
        recommended_run_id="run-b",
    )
    assert store.closed is True

    with pytest.raises(AnalyticsWorkflowError, match="requires --sweep"):
        run_build(
            root_path=tmp_path,
            representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
            sweep=False,
            use_recommended=True,
            config=config,
        )
