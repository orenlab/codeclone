# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

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
    EffectiveClusteringParameters,
)
from .clustering.pipeline import resolve_effective_parameters, run_clustering_pipeline
from .clustering.sweep import (
    SweepCandidate,
    SweepCandidateResult,
    candidate_space_digest,
    clustering_algorithm_manifest,
    iter_profile_candidates,
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
    ProfileAssessmentRecord,
    ProfileBatchRecord,
    ProfileBatchRunRecord,
    ProfileManifestSnapshotRecord,
    RunSelectionRecord,
)
from .corpus.keys import sha256_hex
from .corpus.snapshot import build_intent_snapshot
from .embedding.generation import (
    EmbeddingBatchResult,
    generate_embeddings_for_snapshot,
)
from .exceptions import AnalyticsStoreError, AnalyticsWorkflowError
from .integrity import (
    assess_partition_validity,
    load_validated_snapshot_vectors,
    validate_persisted_run,
)
from .metrics.partition_metrics import compute_run_partition_metrics
from .profiles.loader import canonical_manifest_json, profile_manifest_digest
from .profiles.models import ClusteringProfileManifest, ProfileSearchSpace
from .profiles.ranking import ProfileRankedRun, rank_profile_recommendations
from .profiles.registry import get_profile, resolve_profile_registry
from .profiles.suitability import (
    assess_profile_suitability,
    profile_assessment_digest,
)
from .store.protocols import CorpusStore, SnapshotBuildResult
from .store.sqlite import SqliteCorpusAnalyticsStore, parse_json_object
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
    profile_id: str | None = None
    profile_batch_id: str | None = None
    recommended_for_profile_run_id: str | None = None


@dataclass(frozen=True, slots=True)
class ProfileSweepResult:
    profile_batch_id: str
    profile_id: str
    clustering_run_ids: tuple[str, ...]
    recommended_for_profile_run_id: str | None
    profile_suitable_count: int
    technically_valid_count: int
    batch_status: Literal["completed", "completed_partial", "failed"]


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
    sweep_grid: ProfileSearchSpace | None = None,
    profile_id: str | None = None,
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
            if profile_id is not None:
                profile = _resolve_profile(
                    config=resolved_config,
                    profile_id=profile_id,
                )
                return _run_profile_sweep(
                    store=store,
                    snapshot_id=snapshot_id,
                    embedding_generation_id=embedding_generation_id,
                    item_ids=item_ids,
                    items=items,
                    vectors=vectors,
                    profile=profile,
                    config=resolved_config,
                ).clustering_run_ids
            if sweep:
                return _run_sweep(
                    store=store,
                    snapshot_id=snapshot_id,
                    embedding_generation_id=embedding_generation_id,
                    item_ids=item_ids,
                    items=items,
                    vectors=vectors,
                    config=resolved_config,
                    sweep_grid=sweep_grid,
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
    profile_batch_id: str | None = None,
    selection_profile_id: str | None = None,
    selected_by: str = "local-maintainer",
    rationale: str | None = None,
    config: AnalyticsConfig | None = None,
) -> RunSelectionRecord:
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
        if profile_batch_id is not None and selection_profile_id is not None:
            raise AnalyticsWorkflowError(
                "selection profile scope must use a batch id or profile id, not both"
            )
        resolved_batch_id = profile_batch_id
        if selection_profile_id is not None:
            batch = store.get_latest_profile_batch(
                snapshot_id=run.snapshot_id,
                embedding_generation_id=run.embedding_generation_id,
                profile_id=selection_profile_id,
            )
            if batch is None:
                raise AnalyticsWorkflowError(
                    f"unknown analytics profile batch for: {selection_profile_id}"
                )
            resolved_batch_id = batch.profile_batch_id
        return record_run_selection(
            store=store,
            snapshot_id=run.snapshot_id,
            embedding_generation_id=run.embedding_generation_id,
            selected_run_id=clustering_run_id,
            profile_batch_id=resolved_batch_id,
            selected_by=selected_by,
            rationale=rationale,
        )
    finally:
        store.close()


def run_build(
    *,
    root_path: Path,
    representation_kind: str,
    sweep: bool = False,
    use_recommended: bool = False,
    requested: ClusteringParameters | None = None,
    sweep_grid: ProfileSearchSpace | None = None,
    profile_id: str | None = None,
    config: AnalyticsConfig | None = None,
) -> BuildResult:
    resolved_config = config or resolve_analytics_config(root_path)
    effective_sweep = sweep or profile_id is not None
    if use_recommended and not effective_sweep:
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
            requested=requested,
            sweep=effective_sweep,
            sweep_grid=sweep_grid,
            profile_id=profile_id,
            config=resolved_config,
        )
        recommended: str | None = None
        profile_batch: ProfileBatchRecord | None = None
        if effective_sweep:
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
                if profile_id is not None:
                    resolved_profile = _resolve_profile(
                        config=resolved_config,
                        profile_id=profile_id,
                    )
                    profile_batch = store.get_latest_profile_batch(
                        snapshot_id=snapshot.snapshot_id,
                        embedding_generation_id=embed.embedding_generation_id,
                        profile_id=resolved_profile.profile_id,
                    )
            finally:
                store.close()
        return BuildResult(
            snapshot_id=snapshot.snapshot_id,
            embedding_generation_id=embed.embedding_generation_id,
            clustering_run_ids=run_ids,
            recommended_run_id=recommended,
            profile_id=profile_batch.profile_id if profile_batch is not None else None,
            profile_batch_id=(
                profile_batch.profile_batch_id if profile_batch is not None else None
            ),
            recommended_for_profile_run_id=(
                profile_batch.recommended_clustering_run_id
                if profile_batch is not None
                else None
            ),
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
    sweep_grid: ProfileSearchSpace | None = None,
) -> tuple[str, ...]:
    selected_grid = sweep_grid or _config_sweep_grid(config)
    candidates = iter_sweep_candidates(
        n_samples=len(item_ids),
        n_features=len(vectors[0]) if vectors else 0,
        grid=selected_grid,
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


def _run_profile_sweep(
    *,
    store: SqliteCorpusAnalyticsStore,
    snapshot_id: str,
    embedding_generation_id: str,
    item_ids: list[str],
    items: Sequence[CorpusItemRecord],
    vectors: list[list[float]],
    profile: ClusteringProfileManifest,
    config: AnalyticsConfig,
) -> ProfileSweepResult:
    snapshot = store.get_snapshot(snapshot_id)
    generation = store.get_embedding_generation(embedding_generation_id)
    if snapshot is None:
        raise AnalyticsWorkflowError(f"unknown snapshot: {snapshot_id}")
    if generation is None:
        raise AnalyticsWorkflowError(
            f"unknown embedding generation: {embedding_generation_id}"
        )
    _validate_profile_applicability(
        profile=profile,
        representation_kind=snapshot.representation_kind,
        record_count=snapshot.record_count,
        embedding_contract_version=generation.embedding_contract_version,
    )
    candidates = iter_profile_candidates(
        profile=profile,
        n_samples=len(item_ids),
        n_features=len(vectors[0]) if vectors else 0,
    )
    if not candidates:
        raise AnalyticsWorkflowError(
            "profile incompatible with corpus: no effective clustering candidates"
        )
    manifest_digest = profile_manifest_digest(profile)
    space_digest = candidate_space_digest(
        candidates,
        fixed_parameters={"random_seed": config.cluster_random_seed},
    )
    started_at = _execution_timestamp_utc()
    profile_batch_id = new_profile_batch_id(
        snapshot_id=snapshot_id,
        embedding_generation_id=embedding_generation_id,
        profile_manifest_digest=manifest_digest,
        candidate_space_digest=space_digest,
        started_at_utc=started_at,
    )
    store.insert_profile_manifest_snapshot(
        ProfileManifestSnapshotRecord(
            profile_manifest_digest=manifest_digest,
            profile_id=profile.profile_id,
            profile_version=profile.profile_version,
            manifest_schema_version=profile.manifest_schema_version,
            canonical_manifest_json=canonical_manifest_json(profile),
            label=profile.label,
            description=profile.description,
            created_at_utc=started_at,
        )
    )
    store.insert_profile_batch(
        ProfileBatchRecord(
            profile_batch_id=profile_batch_id,
            snapshot_id=snapshot_id,
            embedding_generation_id=embedding_generation_id,
            profile_id=profile.profile_id,
            profile_manifest_digest=manifest_digest,
            candidate_space_digest=space_digest,
            started_at_utc=started_at,
            finished_at_utc=None,
            status="running",
            candidate_count_planned=len(candidates),
            candidate_count_succeeded=0,
            candidate_count_failed=0,
            recommended_clustering_run_id=None,
            recommendation_rationale_json=None,
            batch_max_cluster_count=None,
            created_at_utc=started_at,
        )
    )
    store.commit()
    run_ids: list[str] = []
    scored: list[SweepCandidateResult] = []
    for ordinal, candidate in enumerate(candidates):
        try:
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
        except Exception:
            continue
        store.insert_profile_batch_run(
            ProfileBatchRunRecord(
                profile_batch_id=profile_batch_id,
                clustering_run_id=run_id,
                candidate_ordinal=ordinal,
                candidate_dedupe_key=candidate.dedupe_key,
            )
        )
        run_ids.append(run_id)
        scored.append(
            _score_completed_run(
                store=store,
                clustering_run_id=run_id,
                candidate=candidate,
            )
        )
    best = rank_sweep_results(scored)
    if best is not None:
        best_run_id = run_ids[scored.index(best)]
        store.set_recommended_run(
            snapshot_id=snapshot_id,
            embedding_generation_id=embedding_generation_id,
            clustering_run_id=best_run_id,
        )
    result = assess_and_persist_profile_batch(
        store=store,
        profile_batch_id=profile_batch_id,
        profile=profile,
        profile_manifest_digest=manifest_digest,
        clustering_run_ids=run_ids,
    )
    store.commit()
    return result


def assess_and_persist_profile_batch(
    *,
    store: CorpusStore,
    profile_batch_id: str,
    profile: ClusteringProfileManifest,
    profile_manifest_digest: str,
    clustering_run_ids: Sequence[str],
) -> ProfileSweepResult:
    batch = store.get_profile_batch(profile_batch_id)
    if batch is None:
        raise AnalyticsWorkflowError(f"unknown profile batch: {profile_batch_id}")
    ranked: list[ProfileRankedRun] = []
    technically_valid_count = 0
    all_cluster_counts: list[int] = []
    for run_id in clustering_run_ids:
        run = store.get_clustering_run(run_id)
        if run is None or run.status != "completed":
            continue
        validity = assess_partition_validity(
            store=store,
            snapshot_id=run.snapshot_id,
            clustering_run_id=run_id,
        )
        metrics = None
        if validity.technically_valid:
            technically_valid_count += 1
            metrics = compute_run_partition_metrics(
                store.list_assignments(run_id),
                store.list_summaries(run_id),
            )
            all_cluster_counts.append(metrics.cluster_count)
        assessment = assess_profile_suitability(
            profile=profile,
            validity=validity,
            metrics=metrics,
        )
        store.insert_profile_assessment(
            ProfileAssessmentRecord(
                profile_batch_id=profile_batch_id,
                clustering_run_id=run_id,
                profile_id=profile.profile_id,
                profile_version=profile.profile_version,
                profile_manifest_digest=profile_manifest_digest,
                suitable_for_profile=assessment.suitable_for_profile,
                rejection_reasons_json=json_text(
                    list(assessment.rejection_reasons),
                    sort_keys=True,
                ),
                observed_metrics_json=(
                    json_text(asdict(assessment.observed), sort_keys=True)
                    if assessment.observed is not None
                    else None
                ),
                assessed_digest=profile_assessment_digest(
                    profile_batch_id=profile_batch_id,
                    clustering_run_id=run_id,
                    run_digest=run.run_digest,
                    profile_manifest_digest=profile_manifest_digest,
                    assessment=assessment,
                ),
            )
        )
        if assessment.suitable_for_profile and metrics is not None:
            ranked.append(
                ProfileRankedRun(
                    clustering_run_id=run_id,
                    base_score=score_clustering_result(
                        cluster_count=metrics.cluster_count,
                        noise_fraction=metrics.noise_ratio,
                        n_samples=metrics.total_items,
                    ),
                    profile_score=0.0,
                    effective=_effective_parameters_from_run(run),
                    metrics=metrics,
                )
            )
    winner, rationale = rank_profile_recommendations(
        profile=profile,
        candidates=ranked,
    )
    succeeded = len(clustering_run_ids)
    failed = batch.candidate_count_planned - succeeded
    status: Literal["completed", "completed_partial", "failed"]
    if succeeded == 0:
        status = "failed"
    elif failed:
        status = "completed_partial"
    else:
        status = "completed"
    finalized = replace(
        batch,
        finished_at_utc=_execution_timestamp_utc(),
        status=status,
        candidate_count_succeeded=succeeded,
        candidate_count_failed=failed,
        recommended_clustering_run_id=(
            winner.clustering_run_id if winner is not None else None
        ),
        recommendation_rationale_json=(
            json_text(asdict(rationale), sort_keys=True)
            if rationale is not None
            else None
        ),
        batch_max_cluster_count=(
            max(all_cluster_counts) if all_cluster_counts else None
        ),
    )
    store.finalize_profile_batch(finalized)
    return ProfileSweepResult(
        profile_batch_id=profile_batch_id,
        profile_id=profile.profile_id,
        clustering_run_ids=tuple(clustering_run_ids),
        recommended_for_profile_run_id=finalized.recommended_clustering_run_id,
        profile_suitable_count=len(ranked),
        technically_valid_count=technically_valid_count,
        batch_status=status,
    )


def record_run_selection(
    *,
    store: CorpusStore,
    snapshot_id: str,
    embedding_generation_id: str,
    selected_run_id: str,
    profile_batch_id: str | None,
    selected_by: str,
    rationale: str | None,
) -> RunSelectionRecord:
    normalized_selected_by = selected_by.strip()
    if not normalized_selected_by:
        raise AnalyticsWorkflowError("selected_by must not be empty")
    profile_id: str | None = None
    manifest_digest: str | None = None
    if profile_batch_id is not None:
        batch = store.get_profile_batch(profile_batch_id)
        if batch is None:
            raise AnalyticsWorkflowError(f"unknown profile batch: {profile_batch_id}")
        profile_id = batch.profile_id
        manifest_digest = batch.profile_manifest_digest
    record = RunSelectionRecord(
        selection_id=f"sel-{uuid.uuid4().hex[:16]}",
        snapshot_id=snapshot_id,
        embedding_generation_id=embedding_generation_id,
        profile_batch_id=profile_batch_id,
        profile_id=profile_id,
        profile_manifest_digest=manifest_digest,
        selected_run_id=selected_run_id,
        selected_at_utc=_execution_timestamp_utc(),
        selected_by=normalized_selected_by,
        rationale=rationale.strip() if rationale and rationale.strip() else None,
        supersedes_selection_id=None,
    )
    try:
        return store.record_run_selection_atomic(record)
    except AnalyticsStoreError as exc:
        raise AnalyticsWorkflowError(str(exc)) from exc


def new_profile_batch_id(
    *,
    snapshot_id: str,
    embedding_generation_id: str,
    profile_manifest_digest: str,
    candidate_space_digest: str,
    started_at_utc: str,
) -> str:
    payload = "|".join(
        (
            snapshot_id,
            embedding_generation_id,
            profile_manifest_digest,
            candidate_space_digest,
            started_at_utc,
        )
    )
    return f"pbatch-{sha256_hex(payload)[:16]}"


def _resolve_profile(
    *,
    config: AnalyticsConfig,
    profile_id: str,
) -> ClusteringProfileManifest:
    selected_id = profile_id
    if profile_id == "auto":
        if config.default_profile_id is None:
            raise AnalyticsWorkflowError("default_profile_id not configured")
        selected_id = config.default_profile_id
    registry = resolve_profile_registry(
        profile_paths=config.profile_paths,
        default_profile_id=config.default_profile_id,
    )
    return get_profile(registry, selected_id)


def _config_sweep_grid(config: AnalyticsConfig) -> ProfileSearchSpace:
    return ProfileSearchSpace(
        pca_dimensions=config.sweep_pca_dimensions,
        min_cluster_size=config.sweep_min_cluster_sizes,
        min_samples=config.sweep_min_samples,
        cluster_selection_method=config.sweep_selection_methods,
    )


def _validate_profile_applicability(
    *,
    profile: ClusteringProfileManifest,
    representation_kind: str,
    record_count: int,
    embedding_contract_version: str,
) -> None:
    if representation_kind not in profile.representation_kinds:
        raise AnalyticsWorkflowError(
            "profile incompatible with corpus: representation kind "
            f"{representation_kind}"
        )
    applicability = profile.applicability
    if (
        applicability.min_record_count is not None
        and record_count < applicability.min_record_count
    ):
        raise AnalyticsWorkflowError(
            "profile incompatible with corpus: record count below minimum"
        )
    if (
        applicability.max_record_count is not None
        and record_count > applicability.max_record_count
    ):
        raise AnalyticsWorkflowError(
            "profile incompatible with corpus: record count above maximum"
        )
    if embedding_contract_version not in applicability.embedding_contract_versions:
        raise AnalyticsWorkflowError(
            "profile incompatible with corpus: embedding contract "
            f"{embedding_contract_version}"
        )


def _score_completed_run(
    *,
    store: CorpusStore,
    clustering_run_id: str,
    candidate: SweepCandidate,
) -> SweepCandidateResult:
    assignments = store.list_assignments(clustering_run_id)
    noise_count = sum(
        assignment.cluster_label == NOISE_LABEL for assignment in assignments
    )
    cluster_labels = {
        assignment.cluster_label
        for assignment in assignments
        if assignment.cluster_label != NOISE_LABEL
    }
    noise_fraction = noise_count / len(assignments) if assignments else 1.0
    return SweepCandidateResult(
        candidate=candidate,
        score=score_clustering_result(
            cluster_count=len(cluster_labels),
            noise_fraction=noise_fraction,
            n_samples=len(assignments),
        ),
        cluster_count=len(cluster_labels),
        noise_fraction=noise_fraction,
    )


def _effective_parameters_from_run(
    run: ClusteringRunRecord,
) -> EffectiveClusteringParameters:
    value = parse_json_object(run.effective_parameters_json)
    try:
        pca_dimensions = value["pca_dimensions"]
        min_cluster_size = value["min_cluster_size"]
        min_samples = value["min_samples"]
        method = value["cluster_selection_method"]
        n_samples = value["n_samples"]
        n_features = value["n_features"]
    except KeyError as exc:
        raise AnalyticsWorkflowError(
            "clustering run effective parameters are incomplete: "
            f"{run.clustering_run_id}"
        ) from exc
    if (
        isinstance(pca_dimensions, bool)
        or not isinstance(pca_dimensions, int)
        or isinstance(min_cluster_size, bool)
        or not isinstance(min_cluster_size, int)
        or isinstance(min_samples, bool)
        or not isinstance(min_samples, int)
        or not isinstance(method, str)
        or isinstance(n_samples, bool)
        or not isinstance(n_samples, int)
        or isinstance(n_features, bool)
        or not isinstance(n_features, int)
    ):
        raise AnalyticsWorkflowError(
            f"clustering run effective parameters are invalid: {run.clustering_run_id}"
        )
    return EffectiveClusteringParameters(
        pca_dimensions=pca_dimensions,
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        cluster_selection_method=method,
        n_samples=n_samples,
        n_features=n_features,
    )


def _execution_timestamp_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


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
    "ProfileSweepResult",
    "assess_and_persist_profile_batch",
    "new_profile_batch_id",
    "record_run_selection",
    "run_build",
    "run_clustering",
    "run_embed",
    "run_snapshot",
    "select_cluster_run",
]
