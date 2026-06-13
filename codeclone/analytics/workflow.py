# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from ..config.analytics import AnalyticsConfig, resolve_analytics_config
from ..observability import span
from ..report.meta import current_report_timestamp_utc
from ..utils.json_io import json_text
from .clustering.canonicalize import (
    canonicalize_partitions,
    display_cluster_id_map,
    partition_membership_map,
)
from .clustering.diagnostics import (
    build_cluster_diagnostics,
    compute_centroids,
    nearest_cluster_ids,
)
from .clustering.models import (
    NOISE_LABEL,
    ClusteringParameters,
    ClusteringPipelineResult,
    ClusterPartition,
)
from .clustering.pipeline import resolve_effective_parameters, run_clustering_pipeline
from .clustering.sweep import (
    SweepCandidateResult,
    clustering_algorithm_manifest,
    iter_sweep_candidates,
    rank_sweep_results,
    run_digest,
    score_clustering_result,
)
from .contracts import (
    ClusterAssignmentRecord,
    ClusteringRunRecord,
    ClusterSummaryRecord,
    CorpusItemRecord,
)
from .corpus.snapshot import build_intent_snapshot
from .embedding.generation import (
    EmbeddingBatchResult,
    generate_embeddings_for_snapshot,
)
from .exceptions import AnalyticsWorkflowError
from .integrity import load_validated_snapshot_vectors, validate_persisted_run
from .store.protocols import SnapshotBuildResult
from .store.sqlite import SqliteCorpusAnalyticsStore
from .store.vectors_lancedb import AnalyticsVectorStore


@dataclass(frozen=True, slots=True)
class ClusterRunResult:
    clustering_run_id: str
    cluster_count: int
    noise_count: int


@dataclass(frozen=True, slots=True)
class BuildResult:
    snapshot_id: str
    embedding_generation_id: str
    clustering_run_ids: tuple[str, ...]
    recommended_run_id: str | None


def run_snapshot(
    *,
    root_path: Path,
    representation_kind: str,
    config: AnalyticsConfig | None = None,
) -> SnapshotBuildResult:
    with span(name="analytics.snapshot"):
        return build_intent_snapshot(
            root_path=root_path,
            representation_kind=representation_kind,
            config=config,
        )


def run_embed(
    *,
    root_path: Path,
    snapshot_id: str,
    config: AnalyticsConfig | None = None,
) -> EmbeddingBatchResult:
    resolved_config = config or resolve_analytics_config(root_path)
    store = SqliteCorpusAnalyticsStore.open(resolved_config.db_path)
    vector_store = AnalyticsVectorStore(
        path=resolved_config.vectors_path,
        dimension=resolved_config.embedding_dimension,
    )
    try:
        if store.get_snapshot(snapshot_id) is None:
            known = ", ".join(item.snapshot_id for item in store.list_snapshots()[:5])
            msg = f"unknown snapshot: {snapshot_id}"
            if known:
                msg = f"{msg}; known snapshots: {known}"
            raise AnalyticsWorkflowError(msg)
        with span(name="analytics.embed"):
            return generate_embeddings_for_snapshot(
                store=store,
                vector_store=vector_store,
                config=resolved_config,
                snapshot_id=snapshot_id,
            )
    finally:
        store.close()
        vector_store.close()


def run_clustering(
    *,
    root_path: Path,
    snapshot_id: str,
    embedding_generation_id: str,
    requested: ClusteringParameters | None = None,
    sweep: bool = False,
    config: AnalyticsConfig | None = None,
) -> tuple[str, ...]:
    resolved_config = config or resolve_analytics_config(root_path)
    store = SqliteCorpusAnalyticsStore.open(resolved_config.db_path)
    vector_store = AnalyticsVectorStore(
        path=resolved_config.vectors_path,
        dimension=resolved_config.embedding_dimension,
    )
    try:
        with span(name="analytics.cluster"):
            items = store.list_items(snapshot_id)
            if not items:
                raise AnalyticsWorkflowError("snapshot has no corpus items")
            vectors = load_validated_snapshot_vectors(
                store=store,
                vector_store=vector_store,
                snapshot_id=snapshot_id,
                embedding_generation_id=embedding_generation_id,
                items=items,
            )
            item_ids = [item.snapshot_item_id for item in items]
            if sweep:
                return _run_sweep(
                    store=store,
                    snapshot_id=snapshot_id,
                    embedding_generation_id=embedding_generation_id,
                    item_ids=item_ids,
                    items=items,
                    vectors=vectors,
                    config=resolved_config,
                )
            params = requested or ClusteringParameters(
                pca_dimensions=resolved_config.default_pca_dimensions,
                min_cluster_size=resolved_config.default_min_cluster_size,
                min_samples=resolved_config.default_min_samples,
                cluster_selection_method=resolved_config.default_cluster_selection_method,
            )
            run_id = _execute_single_run(
                store=store,
                snapshot_id=snapshot_id,
                embedding_generation_id=embedding_generation_id,
                item_ids=item_ids,
                items=items,
                vectors=vectors,
                requested=params,
                config=resolved_config,
                recommended_by_heuristic=False,
            )
            store.commit()
            return (run_id,)
    finally:
        store.close()
        vector_store.close()


def select_cluster_run(
    *,
    root_path: Path,
    clustering_run_id: str,
    config: AnalyticsConfig | None = None,
) -> None:
    resolved_config = config or resolve_analytics_config(root_path)
    store = SqliteCorpusAnalyticsStore.open(resolved_config.db_path)
    try:
        run = store.get_clustering_run(clustering_run_id)
        if run is None:
            raise AnalyticsWorkflowError(f"unknown clustering run: {clustering_run_id}")
        validate_persisted_run(
            store=store,
            snapshot_id=run.snapshot_id,
            clustering_run_id=clustering_run_id,
        )
        store.set_selected_run(
            snapshot_id=run.snapshot_id,
            embedding_generation_id=run.embedding_generation_id,
            clustering_run_id=clustering_run_id,
        )
        store.commit()
    finally:
        store.close()


def run_build(
    *,
    root_path: Path,
    representation_kind: str,
    sweep: bool = False,
    use_recommended: bool = False,
    config: AnalyticsConfig | None = None,
) -> BuildResult:
    resolved_config = config or resolve_analytics_config(root_path)
    if use_recommended and not sweep:
        raise AnalyticsWorkflowError("--use-recommended requires --sweep")
    with span(name="analytics.build"):
        snapshot = run_snapshot(
            root_path=root_path,
            representation_kind=representation_kind,
            config=resolved_config,
        )
        embed = run_embed(
            root_path=root_path,
            snapshot_id=snapshot.snapshot_id,
            config=resolved_config,
        )
        run_ids = run_clustering(
            root_path=root_path,
            snapshot_id=snapshot.snapshot_id,
            embedding_generation_id=embed.embedding_generation_id,
            sweep=sweep,
            config=resolved_config,
        )
        recommended: str | None = None
        if sweep and run_ids:
            store = SqliteCorpusAnalyticsStore.open(resolved_config.db_path)
            try:
                runs = store.list_clustering_runs(
                    snapshot_id=snapshot.snapshot_id,
                    embedding_generation_id=embed.embedding_generation_id,
                )
                for run in runs:
                    if run.recommended_by_heuristic:
                        recommended = run.clustering_run_id
                        break
            finally:
                store.close()
        return BuildResult(
            snapshot_id=snapshot.snapshot_id,
            embedding_generation_id=embed.embedding_generation_id,
            clustering_run_ids=run_ids,
            recommended_run_id=recommended,
        )


def _run_sweep(
    *,
    store: SqliteCorpusAnalyticsStore,
    snapshot_id: str,
    embedding_generation_id: str,
    item_ids: list[str],
    items: Sequence[CorpusItemRecord],
    vectors: list[list[float]],
    config: AnalyticsConfig,
) -> tuple[str, ...]:
    candidates = iter_sweep_candidates(
        n_samples=len(item_ids),
        n_features=len(vectors[0]) if vectors else 0,
    )
    if not candidates:
        raise AnalyticsWorkflowError(
            "corpus is too small for the configured clustering sweep"
        )
    run_ids: list[str] = []
    scored: list[SweepCandidateResult] = []
    for candidate in candidates:
        run_id = _execute_single_run(
            store=store,
            snapshot_id=snapshot_id,
            embedding_generation_id=embedding_generation_id,
            item_ids=item_ids,
            items=items,
            vectors=vectors,
            requested=candidate.requested,
            config=config,
            recommended_by_heuristic=False,
        )
        run_ids.append(run_id)
        result = store.get_clustering_run(run_id)
        if result is None:
            continue
        assignments = store.list_assignments(run_id)
        noise = sum(1 for item in assignments if item.cluster_label == NOISE_LABEL)
        cluster_labels = {
            item.cluster_label
            for item in assignments
            if item.cluster_label != NOISE_LABEL
        }
        scored.append(
            SweepCandidateResult(
                candidate=candidate,
                score=score_clustering_result(
                    cluster_count=len(cluster_labels),
                    noise_fraction=noise / len(assignments) if assignments else 1.0,
                    n_samples=len(assignments),
                ),
                cluster_count=len(cluster_labels),
                noise_fraction=noise / len(assignments) if assignments else 1.0,
            )
        )
    best = rank_sweep_results(scored)
    if best is not None and run_ids:
        best_run_id = run_ids[scored.index(best)]
        store.set_recommended_run(
            snapshot_id=snapshot_id,
            embedding_generation_id=embedding_generation_id,
            clustering_run_id=best_run_id,
        )
    store.commit()
    return tuple(run_ids)


def _execute_single_run(
    *,
    store: SqliteCorpusAnalyticsStore,
    snapshot_id: str,
    embedding_generation_id: str,
    item_ids: list[str],
    items: Sequence[CorpusItemRecord],
    vectors: list[list[float]],
    requested: ClusteringParameters,
    config: AnalyticsConfig,
    recommended_by_heuristic: bool,
) -> str:
    effective = resolve_effective_parameters(
        requested,
        n_samples=len(item_ids),
        n_features=len(vectors[0]) if vectors else 0,
    )
    if effective is None:
        raise AnalyticsWorkflowError("clustering parameters produced no valid run")
    run_id = f"run-{uuid.uuid4().hex[:16]}"
    created_at = current_report_timestamp_utc()
    algorithm_manifest = clustering_algorithm_manifest()
    run = ClusteringRunRecord(
        clustering_run_id=run_id,
        snapshot_id=snapshot_id,
        embedding_generation_id=embedding_generation_id,
        requested_parameters_json=json_text(
            {
                "pca_dimensions": requested.pca_dimensions,
                "min_cluster_size": requested.min_cluster_size,
                "min_samples": requested.min_samples,
                "cluster_selection_method": requested.cluster_selection_method,
            },
            sort_keys=True,
        ),
        effective_parameters_json=json_text(
            {
                "pca_dimensions": effective.pca_dimensions,
                "min_cluster_size": effective.min_cluster_size,
                "min_samples": effective.min_samples,
                "cluster_selection_method": effective.cluster_selection_method,
                "n_samples": effective.n_samples,
                "n_features": effective.n_features,
                "algorithm_manifest": algorithm_manifest,
            },
            sort_keys=True,
        ),
        random_seed=config.cluster_random_seed,
        run_digest=run_digest(
            snapshot_id=snapshot_id,
            embedding_generation_id=embedding_generation_id,
            effective=effective,
            random_seed=config.cluster_random_seed,
            algorithm_manifest=algorithm_manifest,
        ),
        recommended_by_heuristic=recommended_by_heuristic,
        selected_by_maintainer=False,
        status="running",
        created_at_utc=created_at,
        finished_at_utc=None,
        error_message=None,
    )
    store.insert_clustering_run(run)
    store.commit()
    try:
        pipeline = run_clustering_pipeline(
            snapshot_item_ids=item_ids,
            embeddings=vectors,
            requested=requested,
            random_seed=config.cluster_random_seed,
        )
        if pipeline is None:
            raise AnalyticsWorkflowError("clustering parameters produced no valid run")
        coordinates = dict(zip(item_ids, pipeline.reduced_coordinates, strict=True))
        partitions = canonicalize_partitions(
            pipeline.partitions,
            coordinates=coordinates,
        )
        _persist_run_artifacts(
            store=store,
            run_id=run_id,
            item_ids=item_ids,
            items=items,
            pipeline=pipeline,
            partitions=partitions,
            coordinates=coordinates,
            config=config,
        )
        store.update_clustering_run(
            replace(
                run,
                status="completed",
                finished_at_utc=current_report_timestamp_utc(),
            )
        )
        store.commit()
    except Exception as exc:
        store.rollback()
        store.update_clustering_run(
            replace(
                run,
                status="failed",
                finished_at_utc=current_report_timestamp_utc(),
                error_message=str(exc),
            )
        )
        store.commit()
        raise
    return run_id


def _persist_run_artifacts(
    *,
    store: SqliteCorpusAnalyticsStore,
    run_id: str,
    item_ids: list[str],
    items: Sequence[CorpusItemRecord],
    pipeline: ClusteringPipelineResult,
    partitions: Sequence[ClusterPartition],
    coordinates: dict[str, tuple[float, ...]],
    config: AnalyticsConfig,
) -> None:
    membership_map = partition_membership_map(partitions)
    items_by_id = {item.snapshot_item_id: item for item in items}
    strength_by_id = dict(zip(item_ids, pipeline.membership_strengths, strict=True))
    assignments: list[ClusterAssignmentRecord] = []
    for item_id, label, strength in zip(
        item_ids,
        pipeline.labels,
        pipeline.membership_strengths,
        strict=True,
    ):
        assignments.append(
            ClusterAssignmentRecord(
                clustering_run_id=run_id,
                snapshot_item_id=item_id,
                cluster_label=label,
                membership_strength=strength,
                membership_digest=membership_map.get(item_id, ""),
            )
        )
    store.insert_cluster_assignments(assignments)
    display_map = display_cluster_id_map(partitions)
    centroids = compute_centroids(partitions=partitions, coordinates=coordinates)
    summaries: list[ClusterSummaryRecord] = []
    for partition in partitions:
        diagnostics = build_cluster_diagnostics(
            partition=partition,
            items_by_id=items_by_id,
            coordinates=coordinates,
            membership_strengths=strength_by_id,
            total_items=len(items),
            min_correlation_sample_size=config.min_correlation_sample_size,
        )
        if partition.cluster_label != NOISE_LABEL:
            nearest_labels = nearest_cluster_ids(
                cluster_label=partition.cluster_label,
                centroids=centroids,
            )
            diagnostics["nearest_clusters"] = [
                display_id
                for label in nearest_labels
                if (display_id := display_map.get(label)) is not None
            ]
        summaries.append(
            ClusterSummaryRecord(
                clustering_run_id=run_id,
                cluster_label=partition.cluster_label,
                display_cluster_id=display_map.get(partition.cluster_label),
                membership_digest=partition.membership_digest,
                size=len(partition.snapshot_item_ids),
                diagnostics_json=json_text(diagnostics, sort_keys=True),
            )
        )
    store.insert_cluster_summaries(summaries)


__all__ = [
    "BuildResult",
    "ClusterRunResult",
    "run_build",
    "run_clustering",
    "run_embed",
    "run_snapshot",
    "select_cluster_run",
]
