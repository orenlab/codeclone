# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
import types
from argparse import Namespace
from dataclasses import replace
from pathlib import Path

import pytest

from codeclone.analytics import workflow
from codeclone.analytics.capabilities import check_capability
from codeclone.analytics.clustering.models import ClusteringParameters
from codeclone.analytics.clustering.pipeline import run_clustering_pipeline
from codeclone.analytics.contracts import (
    INTENT_REPRESENTATION_DESCRIPTION,
    ClusteringRunRecord,
    CorpusItemRecord,
    ProfileBatchRecord,
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
from codeclone.analytics.store.vectors_lancedb import AnalyticsVectorStore
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
from tests.fixtures.analytics.helpers import (
    open_analytics_store_and_close,
    patch_deterministic_embedding_provider,
    patch_snapshot_missing_memory_db,
    standard_eom_clustering_parameters,
    write_intent_declared_event,
)


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
    patch_snapshot_missing_memory_db(monkeypatch, config)
    snapshot = run_snapshot(
        root_path=root,
        representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
        config=config,
    )
    patch_deterministic_embedding_provider(monkeypatch, config)
    embed = run_embed(root_path=root, snapshot_id=snapshot.snapshot_id, config=config)
    return root, config, snapshot, embed


def _snapshot_vector_bundle(
    analytics_repo: tuple[Path, Path, AnalyticsConfig],
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    AnalyticsConfig,
    SnapshotBuildResult,
    EmbeddingBatchResult,
    SqliteCorpusAnalyticsStore,
    AnalyticsVectorStore,
    tuple[CorpusItemRecord, ...],
    list[str],
    list[list[float]],
]:
    from codeclone.analytics.embedding.generation import load_snapshot_vectors
    from codeclone.analytics.store.vectors_lancedb import AnalyticsVectorStore

    _root, _audit_db, config = analytics_repo
    _root, _config, snapshot, embed = _snapshot_and_embed(analytics_repo, monkeypatch)
    store = SqliteCorpusAnalyticsStore.open(config.db_path)
    vector_store = AnalyticsVectorStore(
        path=config.vectors_path,
        dimension=config.embedding_dimension,
    )
    items = store.list_items(snapshot.snapshot_id)
    item_ids = [item.snapshot_item_id for item in items]
    vectors = load_snapshot_vectors(
        vector_store=vector_store,
        embedding_generation_id=embed.embedding_generation_id,
        items=items,
    )
    return config, snapshot, embed, store, vector_store, items, item_ids, vectors


def _prepare_downgraded_legacy_db(tmp_path: Path, filename: str) -> Path:
    path = tmp_path / filename
    open_analytics_store_and_close(path)
    _seed_legacy_selection_fixture(path)
    _downgrade_analytics_schema(path, legacy_version="1.1")
    return path


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
    patch_snapshot_missing_memory_db(monkeypatch, config)
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
    params = standard_eom_clustering_parameters()
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
            requested=standard_eom_clustering_parameters(),
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
        requested=standard_eom_clustering_parameters(),
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
    assert "Categorical correlations" in html_text
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
        requested=standard_eom_clustering_parameters(),
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
    patch_snapshot_missing_memory_db(monkeypatch, config)
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
    patch_snapshot_missing_memory_db(monkeypatch, config)
    patch_deterministic_embedding_provider(monkeypatch, config)
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


def test_run_build_with_sweep_loads_profile_batch_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = resolve_analytics_config(tmp_path)
    profile_batch = ProfileBatchRecord(
        profile_batch_id="batch-1",
        snapshot_id="snapshot",
        embedding_generation_id="embedding",
        profile_id="intent-small-balanced-v1",
        profile_manifest_digest="digest",
        candidate_space_digest="space",
        started_at_utc="2026-01-01T00:00:00Z",
        finished_at_utc=None,
        status="running",
        candidate_count_planned=3,
        candidate_count_succeeded=0,
        candidate_count_failed=0,
        recommended_clustering_run_id=None,
        recommendation_rationale_json=None,
        batch_max_cluster_count=None,
        created_at_utc="2026-01-01T00:00:00Z",
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
            return ()

        def get_latest_profile_batch(
            self,
            *,
            snapshot_id: str,
            embedding_generation_id: str,
            profile_id: str,
        ) -> ProfileBatchRecord | None:
            assert snapshot_id == "snapshot"
            assert embedding_generation_id == "embedding"
            assert profile_id == "intent-small-balanced-v1"
            return profile_batch

        def close(self) -> None:
            self.closed = True

    store = _Store()
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
        lambda **_kwargs: ("run-a",),
    )
    monkeypatch.setattr(
        SqliteCorpusAnalyticsStore,
        "open",
        lambda _path: store,
    )
    monkeypatch.setattr(
        workflow,
        "_resolve_profile",
        lambda **_kwargs: types.SimpleNamespace(profile_id="intent-small-balanced-v1"),
    )
    result = run_build(
        root_path=tmp_path,
        representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
        sweep=True,
        profile_id="intent-small-balanced-v1",
        config=config,
    )
    assert result.profile_batch_id == "batch-1"
    assert result.profile_id == "intent-small-balanced-v1"
    assert store.closed is True


def test_run_embed_unknown_snapshot_reports_known_ids(
    analytics_repo: tuple[Path, Path, AnalyticsConfig],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _audit_db, config = analytics_repo
    patch_snapshot_missing_memory_db(monkeypatch, config)
    snapshot = run_snapshot(
        root_path=root,
        representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
        config=config,
    )
    with pytest.raises(AnalyticsWorkflowError, match="known snapshots") as exc_info:
        run_embed(root_path=root, snapshot_id="missing-snap", config=config)
    assert snapshot.snapshot_id in str(exc_info.value)


def test_run_embed_unknown_snapshot_without_known(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    config = resolve_analytics_config(root)
    with pytest.raises(AnalyticsWorkflowError, match=r"unknown snapshot: missing$"):
        run_embed(root_path=root, snapshot_id="missing", config=config)


@pytest.mark.skipif(
    not check_capability("cluster").available,
    reason="analytics clustering deps not installed",
)
def test_run_clustering_rejects_empty_snapshot(
    analytics_repo: tuple[Path, Path, AnalyticsConfig],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _audit_db, config = analytics_repo
    _root, _config, snapshot, embed = _snapshot_and_embed(analytics_repo, monkeypatch)
    conn = open_analytics_db(config.db_path)
    try:
        conn.execute(
            "DELETE FROM embedding_items WHERE embedding_generation_id=?",
            (embed.embedding_generation_id,),
        )
        conn.execute(
            "DELETE FROM corpus_items WHERE snapshot_id=?",
            (snapshot.snapshot_id,),
        )
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(AnalyticsWorkflowError, match="no corpus items"):
        run_clustering(
            root_path=root,
            snapshot_id=snapshot.snapshot_id,
            embedding_generation_id=embed.embedding_generation_id,
            config=config,
        )


def _seed_profile_corpus_intents(root: Path, *, count: int) -> None:
    audit_db = root / ".codeclone" / "db" / "audit.sqlite3"
    for index in range(count):
        write_intent_declared_event(
            db_path=audit_db,
            repo_root=root,
            intent_id=f"intent-profile-{index}",
            description=f"Profile corpus intent {index}",
            audit_sequence=20 + index,
        )


@pytest.mark.skipif(
    not check_capability("cluster").available,
    reason="analytics clustering deps not installed",
)
def test_run_clustering_profile_sweep_persists_batch(
    analytics_repo: tuple[Path, Path, AnalyticsConfig],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _audit_db, config = analytics_repo
    _seed_profile_corpus_intents(root, count=45)
    patch_snapshot_missing_memory_db(monkeypatch, config)
    snapshot = run_snapshot(
        root_path=root,
        representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
        config=config,
    )
    patch_deterministic_embedding_provider(monkeypatch, config)
    embed = run_embed(
        root_path=root,
        snapshot_id=snapshot.snapshot_id,
        config=config,
    )
    run_ids = run_clustering(
        root_path=root,
        snapshot_id=snapshot.snapshot_id,
        embedding_generation_id=embed.embedding_generation_id,
        profile_id="intent-small-balanced-v1",
        config=config,
    )
    assert run_ids
    store = SqliteCorpusAnalyticsStore.open_readonly(config.db_path)
    try:
        batch = store.get_latest_profile_batch(
            snapshot_id=snapshot.snapshot_id,
            embedding_generation_id=embed.embedding_generation_id,
            profile_id="intent-small-balanced-v1",
        )
        assert batch is not None
        assert batch.status in {"completed", "completed_partial"}
        assert store.list_profile_assessments(profile_batch_id=batch.profile_batch_id)
    finally:
        store.close()


@pytest.mark.skipif(
    not check_capability("cluster").available,
    reason="analytics clustering deps not installed",
)
def test_run_build_returns_profile_batch_metadata(
    analytics_repo: tuple[Path, Path, AnalyticsConfig],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _audit_db, config = analytics_repo
    _seed_profile_corpus_intents(root, count=45)
    patch_snapshot_missing_memory_db(monkeypatch, config)
    patch_deterministic_embedding_provider(monkeypatch, config)
    result = run_build(
        root_path=root,
        representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
        profile_id="intent-small-balanced-v1",
        config=config,
    )
    assert result.profile_id == "intent-small-balanced-v1"
    assert result.profile_batch_id is not None
    assert result.clustering_run_ids


@pytest.mark.skipif(
    not check_capability("cluster").available,
    reason="analytics clustering deps not installed",
)
def test_select_cluster_run_error_paths(
    analytics_repo: tuple[Path, Path, AnalyticsConfig],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _audit_db, config = analytics_repo
    _root, _config, snapshot, embed = _snapshot_and_embed(analytics_repo, monkeypatch)
    (run_id,) = run_clustering(
        root_path=root,
        snapshot_id=snapshot.snapshot_id,
        embedding_generation_id=embed.embedding_generation_id,
        requested=standard_eom_clustering_parameters(),
        config=config,
    )
    with pytest.raises(AnalyticsWorkflowError, match="unknown clustering run"):
        select_cluster_run(
            root_path=root,
            clustering_run_id="missing-run",
            config=config,
        )
    with pytest.raises(AnalyticsWorkflowError, match="not both"):
        select_cluster_run(
            root_path=root,
            clustering_run_id=run_id,
            profile_batch_id="pbatch-test",
            selection_profile_id="intent-small-balanced-v1",
            config=config,
        )
    with pytest.raises(AnalyticsWorkflowError, match="unknown analytics profile batch"):
        select_cluster_run(
            root_path=root,
            clustering_run_id=run_id,
            selection_profile_id="intent-small-discovery-v1",
            config=config,
        )


@pytest.mark.skipif(
    not check_capability("cluster").available,
    reason="analytics clustering deps not installed",
)
def test_execute_single_run_rejects_invalid_parameters(
    analytics_repo: tuple[Path, Path, AnalyticsConfig],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.analytics.embedding.generation import load_snapshot_vectors
    from codeclone.analytics.store.vectors_lancedb import AnalyticsVectorStore
    from codeclone.analytics.workflow import _execute_single_run

    _root, _audit_db, config = analytics_repo
    _root, _config, snapshot, embed = _snapshot_and_embed(analytics_repo, monkeypatch)
    store = SqliteCorpusAnalyticsStore.open(config.db_path)
    try:
        items = store.list_items(snapshot.snapshot_id)
        item_ids = [item.snapshot_item_id for item in items]
        vectors = load_snapshot_vectors(
            vector_store=AnalyticsVectorStore(
                path=config.vectors_path,
                dimension=config.embedding_dimension,
            ),
            embedding_generation_id=embed.embedding_generation_id,
            items=items,
        )
        with pytest.raises(AnalyticsWorkflowError, match="no valid run"):
            _execute_single_run(
                store=store,
                snapshot_id=snapshot.snapshot_id,
                embedding_generation_id=embed.embedding_generation_id,
                item_ids=item_ids,
                items=items,
                vectors=vectors,
                requested=ClusteringParameters(
                    pca_dimensions=9999,
                    min_cluster_size=9999,
                    min_samples=9999,
                    cluster_selection_method="eom",
                ),
                config=config,
                recommended_by_heuristic=False,
            )
    finally:
        store.close()


def test_select_cluster_run_unknown_profile_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.analytics.workflow import select_cluster_run
    from codeclone.config.analytics import resolve_analytics_config

    config = resolve_analytics_config(tmp_path)
    run = ClusteringRunRecord(
        clustering_run_id="run-a",
        snapshot_id="snapshot",
        embedding_generation_id="embedding",
        requested_parameters_json="{}",
        effective_parameters_json="{}",
        random_seed=42,
        run_digest="digest",
        recommended_by_heuristic=False,
        selected_by_maintainer=False,
        status="completed",
        created_at_utc="2026-01-01T00:00:00Z",
        finished_at_utc="2026-01-01T00:00:01Z",
        error_message=None,
    )

    class _Store:
        def get_clustering_run(
            self, clustering_run_id: str
        ) -> ClusteringRunRecord | None:
            assert clustering_run_id == "run-a"
            return run

        def get_snapshot(self, snapshot_id: str) -> object:
            return object()

        def get_latest_profile_batch(
            self,
            *,
            snapshot_id: str,
            embedding_generation_id: str,
            profile_id: str,
        ) -> None:
            return None

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        "codeclone.analytics.workflow.SqliteCorpusAnalyticsStore.open",
        lambda _path: _Store(),
    )
    monkeypatch.setattr(
        "codeclone.analytics.workflow.validate_persisted_run",
        lambda **_kwargs: run,
    )
    with pytest.raises(AnalyticsWorkflowError, match="unknown analytics profile batch"):
        select_cluster_run(
            root_path=tmp_path,
            clustering_run_id="run-a",
            selection_profile_id="missing-profile",
            config=config,
        )


def test_run_profile_sweep_rejects_missing_snapshot(
    analytics_repo: tuple[Path, Path, AnalyticsConfig],
) -> None:
    from codeclone.analytics.profiles.loader import load_bundled_profiles
    from codeclone.analytics.workflow import _run_profile_sweep

    _root, _audit_db, config = analytics_repo
    store = SqliteCorpusAnalyticsStore.open(config.db_path)
    try:
        profile = load_bundled_profiles()["intent-small-balanced-v1"]
        with pytest.raises(AnalyticsWorkflowError, match="unknown snapshot"):
            _run_profile_sweep(
                store=store,
                snapshot_id="missing",
                embedding_generation_id="missing",
                item_ids=[],
                items=[],
                vectors=[],
                profile=profile,
                config=config,
            )
    finally:
        store.close()


def test_run_profile_sweep_rejects_missing_embedding_generation(
    tmp_path: Path,
) -> None:
    from codeclone.analytics.profiles.loader import load_bundled_profiles
    from codeclone.analytics.workflow import _run_profile_sweep

    profile = load_bundled_profiles()["intent-small-balanced-v1"]

    class _Store:
        def get_snapshot(self, snapshot_id: str) -> object:
            return object()

        def get_embedding_generation(self, embedding_generation_id: str) -> None:
            return None

    with pytest.raises(AnalyticsWorkflowError, match="unknown embedding generation"):
        _run_profile_sweep(
            store=_Store(),  # type: ignore[arg-type]
            snapshot_id="snapshot",
            embedding_generation_id="missing",
            item_ids=[],
            items=[],
            vectors=[],
            profile=profile,
            config=resolve_analytics_config(tmp_path),
        )


def test_assess_and_persist_profile_batch_marks_failed_when_no_runs() -> None:
    from codeclone.analytics.contracts import ProfileBatchRecord
    from codeclone.analytics.profiles.loader import load_bundled_profiles
    from codeclone.analytics.workflow import assess_and_persist_profile_batch

    profile = load_bundled_profiles()["intent-small-balanced-v1"]
    batch = ProfileBatchRecord(
        profile_batch_id="pbatch-empty",
        profile_id=profile.profile_id,
        snapshot_id="snapshot",
        embedding_generation_id="embedding",
        profile_manifest_digest="digest",
        candidate_space_digest="space-digest",
        started_at_utc="2026-01-01T00:00:00Z",
        finished_at_utc=None,
        status="running",
        candidate_count_planned=2,
        candidate_count_succeeded=0,
        candidate_count_failed=0,
        recommended_clustering_run_id=None,
        recommendation_rationale_json=None,
        batch_max_cluster_count=None,
        created_at_utc="2026-01-01T00:00:00Z",
    )

    class _Store:
        def __init__(self) -> None:
            self.finalized: ProfileBatchRecord | None = None

        def get_profile_batch(self, profile_batch_id: str) -> ProfileBatchRecord | None:
            assert profile_batch_id == batch.profile_batch_id
            return batch

        def get_clustering_run(self, run_id: str) -> None:
            return None

        def list_assignments(self, run_id: str) -> list[object]:
            return []

        def list_summaries(self, run_id: str) -> list[object]:
            return []

        def insert_profile_assessment(self, _record: object) -> None:
            return None

        def finalize_profile_batch(self, record: ProfileBatchRecord) -> None:
            self.finalized = record

    store = _Store()
    result = assess_and_persist_profile_batch(
        store=store,  # type: ignore[arg-type]
        profile_batch_id=batch.profile_batch_id,
        profile=profile,
        profile_manifest_digest="digest",
        clustering_run_ids=(),
    )
    assert result.recommended_for_profile_run_id is None
    assert result.batch_status == "failed"
    assert store.finalized is not None
    assert store.finalized.status == "failed"


def test_select_cluster_run_resolves_profile_batch_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.analytics.contracts import ProfileBatchRecord, RunSelectionRecord
    from codeclone.analytics.workflow import select_cluster_run

    config = resolve_analytics_config(tmp_path)
    run = ClusteringRunRecord(
        clustering_run_id="run-a",
        snapshot_id="snapshot",
        embedding_generation_id="embedding",
        requested_parameters_json="{}",
        effective_parameters_json="{}",
        random_seed=42,
        run_digest="digest",
        recommended_by_heuristic=False,
        selected_by_maintainer=False,
        status="completed",
        created_at_utc="2026-01-01T00:00:00Z",
        finished_at_utc="2026-01-01T00:00:01Z",
        error_message=None,
    )
    batch = ProfileBatchRecord(
        profile_batch_id="pbatch-1",
        profile_id="intent-small-balanced-v1",
        snapshot_id="snapshot",
        embedding_generation_id="embedding",
        profile_manifest_digest="digest",
        candidate_space_digest="space",
        started_at_utc="2026-01-01T00:00:00Z",
        finished_at_utc=None,
        status="running",
        candidate_count_planned=1,
        candidate_count_succeeded=0,
        candidate_count_failed=0,
        recommended_clustering_run_id=None,
        recommendation_rationale_json=None,
        batch_max_cluster_count=None,
        created_at_utc="2026-01-01T00:00:00Z",
    )
    captured: dict[str, object] = {}

    class _Store:
        def get_clustering_run(
            self, clustering_run_id: str
        ) -> ClusteringRunRecord | None:
            assert clustering_run_id == "run-a"
            return run

        def get_latest_profile_batch(
            self,
            *,
            snapshot_id: str,
            embedding_generation_id: str,
            profile_id: str,
        ) -> ProfileBatchRecord | None:
            assert profile_id == "intent-small-balanced-v1"
            return batch

        def close(self) -> None:
            return None

    def _record(**kwargs: object) -> RunSelectionRecord:
        captured.update(kwargs)
        return RunSelectionRecord(
            selection_id="sel-1",
            snapshot_id="snapshot",
            embedding_generation_id="embedding",
            profile_batch_id="pbatch-1",
            profile_id=None,
            profile_manifest_digest=None,
            selected_run_id="run-a",
            selected_at_utc="2026-01-01T00:00:00Z",
            selected_by="local-maintainer",
            rationale=None,
            supersedes_selection_id=None,
        )

    monkeypatch.setattr(
        "codeclone.analytics.workflow.SqliteCorpusAnalyticsStore.open",
        lambda _path: _Store(),
    )
    monkeypatch.setattr(
        "codeclone.analytics.workflow.validate_persisted_run",
        lambda **_kwargs: run,
    )
    monkeypatch.setattr(
        "codeclone.analytics.workflow.record_run_selection",
        _record,
    )
    selection = select_cluster_run(
        root_path=tmp_path,
        clustering_run_id="run-a",
        selection_profile_id="intent-small-balanced-v1",
        config=config,
    )
    assert selection.selection_id == "sel-1"
    assert captured["profile_batch_id"] == "pbatch-1"


def test_run_sweep_skips_missing_persisted_run(
    analytics_repo: tuple[Path, Path, AnalyticsConfig],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.analytics.workflow import _run_sweep

    config, snapshot, embed, store, vector_store, items, item_ids, vectors = (
        _snapshot_vector_bundle(analytics_repo, monkeypatch)
    )
    try:
        monkeypatch.setattr(store, "get_clustering_run", lambda _run_id: None)
        run_ids = _run_sweep(
            store=store,
            snapshot_id=snapshot.snapshot_id,
            embedding_generation_id=embed.embedding_generation_id,
            item_ids=item_ids,
            items=items,
            vectors=vectors,
            config=config,
        )
        assert isinstance(run_ids, tuple)
    finally:
        store.close()
        vector_store.close()


def test_run_profile_sweep_rejects_empty_candidate_space(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.analytics.profiles.loader import load_bundled_profiles
    from codeclone.analytics.workflow import _run_profile_sweep
    from codeclone.contracts import CORPUS_EMBEDDING_CONTRACT_VERSION

    profile = load_bundled_profiles()["intent-small-balanced-v1"]
    kind = profile.representation_kinds[0]

    class _Snapshot:
        snapshot_id = "snapshot"
        representation_kind = kind
        record_count = 100

    class _Generation:
        embedding_contract_version = CORPUS_EMBEDDING_CONTRACT_VERSION

    class _Store:
        def get_snapshot(self, _snapshot_id: str) -> _Snapshot:
            return _Snapshot()

        def get_embedding_generation(
            self, _embedding_generation_id: str
        ) -> _Generation:
            return _Generation()

    monkeypatch.setattr(
        "codeclone.analytics.workflow.iter_profile_candidates",
        lambda **_kwargs: (),
    )
    with pytest.raises(
        AnalyticsWorkflowError,
        match="no effective clustering candidates",
    ):
        _run_profile_sweep(
            store=_Store(),  # type: ignore[arg-type]
            snapshot_id="snapshot",
            embedding_generation_id="embedding",
            item_ids=["a", "b"],
            items=[],
            vectors=[[0.1, 0.2], [0.2, 0.3]],
            profile=profile,
            config=resolve_analytics_config(tmp_path),
        )


def test_run_profile_sweep_continues_after_run_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.analytics.clustering.pipeline import resolve_effective_parameters
    from codeclone.analytics.clustering.sweep import (
        SweepCandidate,
        SweepCandidateResult,
    )
    from codeclone.analytics.profiles.loader import load_bundled_profiles
    from codeclone.analytics.workflow import ProfileSweepResult, _run_profile_sweep
    from codeclone.contracts import CORPUS_EMBEDDING_CONTRACT_VERSION

    profile = load_bundled_profiles()["intent-small-balanced-v1"]
    kind = profile.representation_kinds[0]
    requested = ClusteringParameters(2, 2, 1, "eom")
    effective = resolve_effective_parameters(
        requested,
        n_samples=10,
        n_features=384,
    )
    assert effective is not None
    candidate = SweepCandidate(
        requested=requested,
        effective=effective,
        dedupe_key="dedupe",
    )
    sweep_result = ProfileSweepResult(
        profile_batch_id="pbatch-test",
        profile_id=profile.profile_id,
        clustering_run_ids=("run-ok",),
        recommended_for_profile_run_id=None,
        profile_suitable_count=0,
        technically_valid_count=0,
        batch_status="completed_partial",
    )

    class _Snapshot:
        snapshot_id = "snapshot"
        representation_kind = kind
        record_count = 100

    class _Generation:
        embedding_contract_version = CORPUS_EMBEDDING_CONTRACT_VERSION

    class _Store:
        def __init__(self) -> None:
            self.batch_runs: list[object] = []

        def get_snapshot(self, _snapshot_id: str) -> _Snapshot:
            return _Snapshot()

        def get_embedding_generation(
            self, _embedding_generation_id: str
        ) -> _Generation:
            return _Generation()

        def insert_profile_batch(self, _record: object) -> None:
            return None

        def insert_profile_manifest_snapshot(self, _record: object) -> None:
            return None

        def insert_profile_batch_run(self, record: object) -> None:
            self.batch_runs.append(record)

        def set_recommended_run(self, **_kwargs: object) -> None:
            return None

        def commit(self) -> None:
            return None

    calls = {"count": 0}

    def _fake_execute(**_kwargs: object) -> str:
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("boom")
        return "run-ok"

    store = _Store()
    monkeypatch.setattr(
        "codeclone.analytics.workflow._validate_profile_applicability",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "codeclone.analytics.workflow.iter_profile_candidates",
        lambda **_kwargs: (candidate, candidate),
    )
    monkeypatch.setattr(
        "codeclone.analytics.workflow._execute_single_run",
        _fake_execute,
    )
    monkeypatch.setattr(
        "codeclone.analytics.workflow._score_completed_run",
        lambda **_kwargs: SweepCandidateResult(
            candidate=candidate,
            score=1.0,
            cluster_count=1,
            noise_fraction=0.0,
        ),
    )
    monkeypatch.setattr(
        "codeclone.analytics.workflow.assess_and_persist_profile_batch",
        lambda **_kwargs: sweep_result,
    )
    result = _run_profile_sweep(
        store=store,  # type: ignore[arg-type]
        snapshot_id="snapshot",
        embedding_generation_id="embedding",
        item_ids=["a", "b"],
        items=[],
        vectors=[[0.1, 0.2], [0.3, 0.4]],
        profile=profile,
        config=resolve_analytics_config(tmp_path),
    )
    assert result.clustering_run_ids == ("run-ok",)
    assert len(store.batch_runs) == 1


@pytest.mark.skipif(
    not check_capability("cluster").available,
    reason="analytics clustering deps not installed",
)
def test_execute_single_run_raises_when_pipeline_returns_none(
    analytics_repo: tuple[Path, Path, AnalyticsConfig],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.analytics.workflow import _execute_single_run

    config, snapshot, embed, store, vector_store, items, item_ids, vectors = (
        _snapshot_vector_bundle(analytics_repo, monkeypatch)
    )
    try:
        monkeypatch.setattr(
            "codeclone.analytics.workflow.run_clustering_pipeline",
            lambda **_kwargs: None,
        )
        with pytest.raises(
            AnalyticsWorkflowError,
            match="clustering parameters produced no valid run",
        ):
            _execute_single_run(
                store=store,
                snapshot_id=snapshot.snapshot_id,
                embedding_generation_id=embed.embedding_generation_id,
                item_ids=item_ids,
                items=items,
                vectors=vectors,
                requested=ClusteringParameters(2, 2, 1, "eom"),
                config=config,
                recommended_by_heuristic=False,
            )
    finally:
        store.close()
        vector_store.close()


def test_assess_and_persist_profile_batch_completed_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.analytics.clustering.sweep import clustering_algorithm_manifest
    from codeclone.analytics.contracts import ProfileBatchRecord
    from codeclone.analytics.integrity import PartitionValidityAssessment
    from codeclone.analytics.metrics.partition_metrics import RunPartitionMetrics
    from codeclone.analytics.profiles.loader import load_bundled_profiles
    from codeclone.analytics.profiles.suitability import (
        ProfileObservedMetrics,
        ProfileSuitabilityAssessment,
    )
    from codeclone.analytics.workflow import assess_and_persist_profile_batch

    profile = load_bundled_profiles()["intent-small-balanced-v1"]
    batch = ProfileBatchRecord(
        profile_batch_id="pbatch-partial",
        profile_id=profile.profile_id,
        snapshot_id="snapshot",
        embedding_generation_id="embedding",
        profile_manifest_digest="digest",
        candidate_space_digest="space-digest",
        started_at_utc="2026-01-01T00:00:00Z",
        finished_at_utc=None,
        status="running",
        candidate_count_planned=3,
        candidate_count_succeeded=0,
        candidate_count_failed=0,
        recommended_clustering_run_id=None,
        recommendation_rationale_json=None,
        batch_max_cluster_count=None,
        created_at_utc="2026-01-01T00:00:00Z",
    )
    completed_run = ClusteringRunRecord(
        clustering_run_id="run-ok",
        snapshot_id="snapshot",
        embedding_generation_id="embedding",
        requested_parameters_json='{"min_cluster_size":1}',
        effective_parameters_json=json.dumps(
            {
                "pca_dimensions": 2,
                "min_cluster_size": 1,
                "min_samples": 1,
                "cluster_selection_method": "eom",
                "n_samples": 10,
                "n_features": 384,
                "algorithm_manifest": clustering_algorithm_manifest(),
            },
            sort_keys=True,
        ),
        random_seed=42,
        run_digest="digest-ok",
        recommended_by_heuristic=False,
        selected_by_maintainer=False,
        status="completed",
        created_at_utc="2026-01-01T00:00:00Z",
        finished_at_utc="2026-01-01T00:00:01Z",
        error_message=None,
    )
    metrics = RunPartitionMetrics(
        total_items=10,
        cluster_count=2,
        noise_count=1,
        non_noise_count=9,
        noise_ratio=0.1,
        dominant_cluster_ratio=0.6,
        dominant_assigned_ratio=0.5,
        dominant_cluster_label=0,
        cluster_size_distribution=(5, 4),
        cluster_size_histogram={"5": 1, "4": 1},
    )
    assessment = ProfileSuitabilityAssessment(
        profile_id=profile.profile_id,
        profile_version=profile.profile_version,
        profile_manifest_digest="digest",
        suitable_for_profile=True,
        rejection_reasons=(),
        observed=ProfileObservedMetrics(
            non_noise_cluster_count=2,
            noise_ratio=0.1,
            dominant_cluster_ratio=0.6,
            dominant_assigned_ratio=0.5,
            non_noise_count=9,
        ),
    )

    class _Store:
        def __init__(self) -> None:
            self.finalized: ProfileBatchRecord | None = None

        def get_profile_batch(self, profile_batch_id: str) -> ProfileBatchRecord | None:
            return batch

        def get_clustering_run(self, run_id: str) -> ClusteringRunRecord | None:
            if run_id == "run-ok":
                return completed_run
            if run_id == "run-missing":
                return None
            return replace(completed_run, clustering_run_id=run_id, status="failed")

        def list_assignments(self, _run_id: str) -> list[object]:
            return []

        def list_summaries(self, _run_id: str) -> list[object]:
            return []

        def insert_profile_assessment(self, _record: object) -> None:
            return None

        def finalize_profile_batch(self, record: ProfileBatchRecord) -> None:
            self.finalized = record

    monkeypatch.setattr(
        "codeclone.analytics.workflow.assess_partition_validity",
        lambda **_kwargs: PartitionValidityAssessment(True, ()),
    )
    monkeypatch.setattr(
        "codeclone.analytics.workflow.compute_run_partition_metrics",
        lambda *_args, **_kwargs: metrics,
    )
    monkeypatch.setattr(
        "codeclone.analytics.workflow.assess_profile_suitability",
        lambda **_kwargs: assessment,
    )
    store = _Store()
    result = assess_and_persist_profile_batch(
        store=store,  # type: ignore[arg-type]
        profile_batch_id=batch.profile_batch_id,
        profile=profile,
        profile_manifest_digest="digest",
        clustering_run_ids=("run-ok", "run-missing"),
    )
    assert result.batch_status == "completed_partial"
    assert result.profile_suitable_count == 1
    assert store.finalized is not None
    assert store.finalized.status == "completed_partial"


def test_sqlite_store_profile_assessment_and_selection_guards(
    tmp_path: Path,
) -> None:
    from codeclone.analytics.contracts import (
        ClusteringRunRecord,
        CorpusSnapshotRecord,
        EmbeddingGenerationRecord,
        ProfileAssessmentRecord,
        ProfileBatchRecord,
        ProfileBatchRunRecord,
        ProfileManifestSnapshotRecord,
        RunSelectionRecord,
    )
    from codeclone.analytics.exceptions import AnalyticsStoreError
    from codeclone.analytics.profiles.loader import (
        canonical_manifest_json,
        load_bundled_profiles,
        profile_manifest_digest,
    )
    from codeclone.contracts import CORPUS_EMBEDDING_CONTRACT_VERSION

    snapshot = CorpusSnapshotRecord(
        snapshot_id="snapshot",
        lane="intent",
        representation_kind="intent.description.v1",
        representation_version="3",
        source_stores_json="{}",
        source_schema_versions_json="{}",
        record_count=2,
        source_digest="digest",
        created_at_utc="2026-01-01T00:00:00Z",
    )
    generation = EmbeddingGenerationRecord(
        embedding_generation_id="embedding",
        provider_id="fastembed",
        provider_package_version="1",
        model_id="model",
        model_revision=None,
        model_artifact_fingerprint=None,
        exact_model_artifact_reproducibility=False,
        dimensions=2,
        embedding_contract_version=CORPUS_EMBEDDING_CONTRACT_VERSION,
        embedding_similarity_metric="cosine",
        vector_preprocessing="l2_normalize",
        created_at_utc="2026-01-01T00:00:00Z",
    )
    run = ClusteringRunRecord(
        clustering_run_id="run-a",
        snapshot_id="snapshot",
        embedding_generation_id="embedding",
        requested_parameters_json="{}",
        effective_parameters_json="{}",
        random_seed=42,
        run_digest="digest",
        recommended_by_heuristic=False,
        selected_by_maintainer=False,
        status="completed",
        created_at_utc="2026-01-01T00:00:00Z",
        finished_at_utc="2026-01-01T00:00:01Z",
        error_message=None,
    )

    store = SqliteCorpusAnalyticsStore.open(tmp_path / "analytics.sqlite3")
    profile = load_bundled_profiles()["intent-small-balanced-v1"]
    digest = profile_manifest_digest(profile)
    try:
        store.insert_snapshot(snapshot, ())
        store.insert_embedding_generation(generation)
        store.insert_clustering_run(run)
        store.insert_profile_manifest_snapshot(
            ProfileManifestSnapshotRecord(
                profile_manifest_digest=digest,
                profile_id=profile.profile_id,
                profile_version=profile.profile_version,
                manifest_schema_version=profile.manifest_schema_version,
                canonical_manifest_json=canonical_manifest_json(profile),
                label=profile.label,
                description=profile.description,
                created_at_utc="2026-01-01T00:00:00Z",
            )
        )
        batch = ProfileBatchRecord(
            profile_batch_id="batch",
            snapshot_id="snapshot",
            embedding_generation_id="embedding",
            profile_id=profile.profile_id,
            profile_manifest_digest=digest,
            candidate_space_digest="space",
            started_at_utc="2026-01-01T00:00:00Z",
            finished_at_utc=None,
            status="running",
            candidate_count_planned=1,
            candidate_count_succeeded=0,
            candidate_count_failed=0,
            recommended_clustering_run_id=None,
            recommendation_rationale_json=None,
            batch_max_cluster_count=None,
            created_at_utc="2026-01-01T00:00:00Z",
        )
        store.insert_profile_batch(batch)
        store.insert_profile_batch_run(
            ProfileBatchRunRecord("batch", "run-a", 0, "8|5|1|eom")
        )
        store.insert_profile_assessment(
            ProfileAssessmentRecord(
                profile_batch_id="batch",
                clustering_run_id="run-a",
                profile_id=profile.profile_id,
                profile_version=profile.profile_version,
                profile_manifest_digest=digest,
                suitable_for_profile=False,
                rejection_reasons_json="[]",
                observed_metrics_json=None,
                assessed_digest="assessed",
            )
        )
        store.commit()
        assert (
            store.get_profile_assessment(
                profile_batch_id="batch",
                clustering_run_id="run-a",
            )
            is not None
        )
        (assessment,) = store.list_profile_assessments(profile_batch_id="batch")
        assert assessment.clustering_run_id == "run-a"

        store._conn.execute("BEGIN")
        with pytest.raises(
            AnalyticsStoreError,
            match="atomic selection recording requires a clean transaction",
        ):
            store.record_run_selection_atomic(
                RunSelectionRecord(
                    selection_id="sel-test",
                    snapshot_id="snapshot",
                    embedding_generation_id="embedding",
                    profile_batch_id="batch",
                    profile_id=profile.profile_id,
                    profile_manifest_digest=digest,
                    selected_run_id="missing-run",
                    selected_at_utc="2026-01-01T00:00:00Z",
                    selected_by="maintainer",
                    rationale=None,
                    supersedes_selection_id=None,
                )
            )
        store._conn.rollback()

        with pytest.raises(
            AnalyticsStoreError,
            match="selected run is not a member of profile batch",
        ):
            store.record_run_selection_atomic(
                RunSelectionRecord(
                    selection_id="sel-test",
                    snapshot_id="snapshot",
                    embedding_generation_id="embedding",
                    profile_batch_id="batch",
                    profile_id=profile.profile_id,
                    profile_manifest_digest=digest,
                    selected_run_id="missing-run",
                    selected_at_utc="2026-01-01T00:00:00Z",
                    selected_by="maintainer",
                    rationale=None,
                    supersedes_selection_id=None,
                )
            )

        store.record_run_selection_atomic(
            RunSelectionRecord(
                selection_id="sel-one",
                snapshot_id="snapshot",
                embedding_generation_id="embedding",
                profile_batch_id=None,
                profile_id=None,
                profile_manifest_digest=None,
                selected_run_id="run-a",
                selected_at_utc="2026-01-01T00:00:00Z",
                selected_by="maintainer",
                rationale=None,
                supersedes_selection_id=None,
            )
        )
        store._insert_run_selection(
            RunSelectionRecord(
                selection_id="sel-two",
                snapshot_id="snapshot",
                embedding_generation_id="embedding",
                profile_batch_id=None,
                profile_id=None,
                profile_manifest_digest=None,
                selected_run_id="run-a",
                selected_at_utc="2026-01-01T00:00:01Z",
                selected_by="maintainer",
                rationale=None,
                supersedes_selection_id=None,
            )
        )
        store.commit()
        with pytest.raises(
            AnalyticsStoreError,
            match="selection chain ambiguous",
        ):
            store.record_run_selection_atomic(
                RunSelectionRecord(
                    selection_id="sel-three",
                    snapshot_id="snapshot",
                    embedding_generation_id="embedding",
                    profile_batch_id=None,
                    profile_id=None,
                    profile_manifest_digest=None,
                    selected_run_id="run-a",
                    selected_at_utc="2026-01-01T00:00:02Z",
                    selected_by="maintainer",
                    rationale=None,
                    supersedes_selection_id=None,
                )
            )
    finally:
        store.close()


def _seed_legacy_selection_fixture(path: Path) -> None:
    import sqlite3

    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            INSERT INTO corpus_snapshots (
                snapshot_id, lane, representation_kind, representation_version,
                source_stores_json, source_schema_versions_json,
                record_count, source_digest, created_at_utc
            ) VALUES ('snapshot', 'intent', 'intent.description.v1', '3',
                      '{}', '{}', 0, 'digest', '2026-01-01T00:00:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO embedding_generations (
                embedding_generation_id, provider_id, provider_package_version,
                model_id, model_revision, model_artifact_fingerprint,
                exact_model_artifact_reproducibility, dimensions,
                embedding_contract_version, embedding_similarity_metric,
                vector_preprocessing, created_at_utc
            ) VALUES ('embedding', 'fastembed', '1', 'model', NULL, NULL,
                      0, 2, '2', 'cosine', 'l2_normalize',
                      '2026-01-01T00:00:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO clustering_runs (
                clustering_run_id, snapshot_id, embedding_generation_id,
                requested_parameters_json, effective_parameters_json,
                random_seed, run_digest, recommended_by_heuristic,
                selected_by_maintainer, status, created_at_utc,
                finished_at_utc, error_message
            ) VALUES ('run', 'snapshot', 'embedding', '{}', '{}', 42,
                      'run-digest', 0, 1, 'completed',
                      '2026-01-01T00:00:00Z',
                      '2026-01-01T00:00:01Z', NULL)
            """
        )
        conn.commit()
    finally:
        conn.close()


def _downgrade_analytics_schema(path: Path, *, legacy_version: str) -> None:
    import sqlite3

    conn = sqlite3.connect(path)
    try:
        trigger_names = [
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            )
        ]
        for name in trigger_names:
            conn.execute(f'DROP TRIGGER IF EXISTS "{name}"')
        conn.execute("DROP INDEX IF EXISTS idx_run_selections_scope")
        conn.execute("DROP INDEX IF EXISTS idx_profile_batches_lens")
        for table in (
            "run_selections",
            "profile_assessments",
            "profile_batch_runs",
            "profile_batches",
            "profile_manifest_snapshots",
        ):
            conn.execute(f'DROP TABLE IF EXISTS "{table}"')
        conn.execute(
            "UPDATE analytics_meta SET value=? WHERE key='schema_version'",
            (legacy_version,),
        )
        conn.commit()
    finally:
        conn.close()


def test_legacy_selection_backfill_skips_existing_selection(tmp_path: Path) -> None:
    import sqlite3

    from codeclone.analytics.schema import _backfill_legacy_selections

    path = _prepare_downgraded_legacy_db(tmp_path, "legacy.sqlite3")
    migrated = SqliteCorpusAnalyticsStore.open(path)
    migrated.close()

    conn = sqlite3.connect(path)
    try:
        before = int(conn.execute("SELECT COUNT(*) FROM run_selections").fetchone()[0])
        _backfill_legacy_selections(conn)
        conn.commit()
        after = int(conn.execute("SELECT COUNT(*) FROM run_selections").fetchone()[0])
    finally:
        conn.close()

    assert before == 1
    assert after == 1


def test_legacy_selection_backfill_creates_migration_selection(tmp_path: Path) -> None:
    path = _prepare_downgraded_legacy_db(tmp_path, "legacy-single.sqlite3")

    migrated = SqliteCorpusAnalyticsStore.open(path)
    try:
        active = migrated.get_active_run_selection(
            snapshot_id="snapshot",
            embedding_generation_id="embedding",
            profile_batch_id=None,
        )
    finally:
        migrated.close()

    assert active.record is not None
    assert active.record.selected_run_id == "run"
    assert active.record.selected_by == "legacy-migration"
