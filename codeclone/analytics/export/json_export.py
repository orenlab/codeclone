# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json

from ...contracts import CORPUS_EXPORT_SCHEMA_VERSION
from ...utils.json_io import json_text
from ..clustering.models import NOISE_LABEL
from ..clustering.sweep import score_clustering_result
from ..contracts import (
    ClusterAssignmentRecord,
    ClusteringRunRecord,
    ClusterSummaryRecord,
    CorpusItemRecord,
    CorpusSnapshotRecord,
    EmbeddingGenerationRecord,
    EmbeddingItemRecord,
)
from ..exceptions import AnalyticsWorkflowError
from ..integrity import validate_generation_metadata, validate_persisted_run
from ..store.sqlite import SqliteCorpusAnalyticsStore

_REPRODUCIBILITY_NOTE = (
    "Full vector reproducibility is not guaranteed from model id alone."
)


def export_clustering_json(
    *,
    store: SqliteCorpusAnalyticsStore,
    snapshot_id: str,
    clustering_run_id: str,
) -> str:
    snapshot, generation = _validated_context(
        store=store,
        snapshot_id=snapshot_id,
        clustering_run_id=clustering_run_id,
    )
    run = validate_persisted_run(
        store=store,
        snapshot_id=snapshot_id,
        clustering_run_id=clustering_run_id,
    )
    detail = _run_detail(store=store, run=run)
    payload: dict[str, object] = {
        "schema_version": CORPUS_EXPORT_SCHEMA_VERSION,
        "snapshot": _snapshot_dict(snapshot),
        "embedding_generation": _generation_dict(generation),
        "embedding_items": [
            _embedding_item_dict(item)
            for item in store.list_embedding_items(
                embedding_generation_id=run.embedding_generation_id
            )
        ],
        "clustering_run": detail["run"],
        "clusters": detail["clusters"],
        "assignments": detail["assignments"],
        "noise_items": detail["noise_items"],
        "items": [_item_dict(item) for item in store.list_items(snapshot_id)],
        "exact_model_artifact_reproducibility": (
            generation.exact_model_artifact_reproducibility
        ),
        "reproducibility_statement": (
            None
            if generation.exact_model_artifact_reproducibility
            else _REPRODUCIBILITY_NOTE
        ),
        "sweep_candidates": [
            _run_summary(store=store, run=candidate)
            for candidate in store.list_clustering_runs(
                snapshot_id=snapshot_id,
                embedding_generation_id=run.embedding_generation_id,
            )
            if candidate.status == "completed"
        ],
    }
    return json_text(payload, sort_keys=True, indent=True, trailing_newline=True)


def export_sweep_comparison_json(
    *,
    store: SqliteCorpusAnalyticsStore,
    snapshot_id: str,
    embedding_generation_id: str,
) -> str:
    snapshot = store.get_snapshot(snapshot_id)
    if snapshot is None:
        raise AnalyticsWorkflowError(f"unknown snapshot: {snapshot_id}")
    generation = store.get_embedding_generation(embedding_generation_id)
    if generation is None:
        raise AnalyticsWorkflowError(
            f"unknown embedding generation: {embedding_generation_id}"
        )
    validate_generation_metadata(
        store=store,
        snapshot_id=snapshot_id,
        embedding_generation_id=embedding_generation_id,
        items=store.list_items(snapshot_id),
    )
    candidates: list[dict[str, object]] = []
    for run in store.list_clustering_runs(
        snapshot_id=snapshot_id,
        embedding_generation_id=embedding_generation_id,
    ):
        if run.status != "completed":
            continue
        validate_persisted_run(
            store=store,
            snapshot_id=snapshot_id,
            clustering_run_id=run.clustering_run_id,
        )
        candidates.append(_run_detail(store=store, run=run))
    payload = {
        "schema_version": CORPUS_EXPORT_SCHEMA_VERSION,
        "snapshot": _snapshot_dict(snapshot),
        "embedding_generation": _generation_dict(generation),
        "embedding_items": [
            _embedding_item_dict(item)
            for item in store.list_embedding_items(
                embedding_generation_id=embedding_generation_id
            )
        ],
        "candidates": candidates,
        "exact_model_artifact_reproducibility": (
            generation.exact_model_artifact_reproducibility
        ),
        "reproducibility_statement": (
            None
            if generation.exact_model_artifact_reproducibility
            else _REPRODUCIBILITY_NOTE
        ),
    }
    return json_text(payload, sort_keys=True, indent=True, trailing_newline=True)


def _validated_context(
    *,
    store: SqliteCorpusAnalyticsStore,
    snapshot_id: str,
    clustering_run_id: str,
) -> tuple[CorpusSnapshotRecord, EmbeddingGenerationRecord]:
    run = validate_persisted_run(
        store=store,
        snapshot_id=snapshot_id,
        clustering_run_id=clustering_run_id,
    )
    snapshot = store.get_snapshot(snapshot_id)
    generation = store.get_embedding_generation(run.embedding_generation_id)
    assert snapshot is not None
    assert generation is not None
    return snapshot, generation


def _run_detail(
    *,
    store: SqliteCorpusAnalyticsStore,
    run: ClusteringRunRecord,
) -> dict[str, object]:
    assignments = store.list_assignments(run.clustering_run_id)
    summaries = store.list_summaries(run.clustering_run_id)
    noise_items = [
        item.snapshot_item_id
        for item in assignments
        if item.cluster_label == NOISE_LABEL
    ]
    cluster_count = len(
        {
            item.cluster_label
            for item in assignments
            if item.cluster_label != NOISE_LABEL
        }
    )
    noise_fraction = len(noise_items) / len(assignments) if assignments else 1.0
    return {
        "run": {
            **_run_dict(run),
            "score": score_clustering_result(
                cluster_count=cluster_count,
                noise_fraction=noise_fraction,
                n_samples=len(assignments),
            ),
            "cluster_count": cluster_count,
            "noise_count": len(noise_items),
            "noise_fraction": noise_fraction,
        },
        "clusters": [_summary_dict(summary) for summary in summaries],
        "assignments": [_assignment_dict(item) for item in assignments],
        "noise_items": noise_items,
    }


def _run_summary(
    *,
    store: SqliteCorpusAnalyticsStore,
    run: ClusteringRunRecord,
) -> dict[str, object]:
    detail = _run_detail(store=store, run=run)
    payload = detail["run"]
    assert isinstance(payload, dict)
    return dict(payload)


def _snapshot_dict(snapshot: CorpusSnapshotRecord) -> dict[str, object]:
    return {
        "snapshot_id": snapshot.snapshot_id,
        "lane": snapshot.lane,
        "representation_kind": snapshot.representation_kind,
        "representation_version": snapshot.representation_version,
        "source_stores": json.loads(snapshot.source_stores_json),
        "source_schema_versions": json.loads(snapshot.source_schema_versions_json),
        "record_count": snapshot.record_count,
        "source_digest": snapshot.source_digest,
        "created_at_utc": snapshot.created_at_utc,
    }


def _run_dict(run: ClusteringRunRecord) -> dict[str, object]:
    effective_parameters = json.loads(run.effective_parameters_json)
    algorithm_manifest = (
        effective_parameters.get("algorithm_manifest", {})
        if isinstance(effective_parameters, dict)
        else {}
    )
    return {
        "clustering_run_id": run.clustering_run_id,
        "snapshot_id": run.snapshot_id,
        "embedding_generation_id": run.embedding_generation_id,
        "requested_parameters": json.loads(run.requested_parameters_json),
        "effective_parameters": effective_parameters,
        "algorithm_manifest": algorithm_manifest,
        "random_seed": run.random_seed,
        "run_digest": run.run_digest,
        "recommended_by_heuristic": run.recommended_by_heuristic,
        "selected_by_maintainer": run.selected_by_maintainer,
        "status": run.status,
        "created_at_utc": run.created_at_utc,
        "finished_at_utc": run.finished_at_utc,
        "error_message": run.error_message,
    }


def _summary_dict(summary: ClusterSummaryRecord) -> dict[str, object]:
    return {
        "cluster_label": summary.cluster_label,
        "display_cluster_id": summary.display_cluster_id,
        "membership_digest": summary.membership_digest,
        "size": summary.size,
        "diagnostics": json.loads(summary.diagnostics_json),
    }


def _assignment_dict(assignment: ClusterAssignmentRecord) -> dict[str, object]:
    return {
        "snapshot_item_id": assignment.snapshot_item_id,
        "cluster_label": assignment.cluster_label,
        "membership_strength": assignment.membership_strength,
        "membership_digest": assignment.membership_digest,
    }


def _item_dict(item: CorpusItemRecord) -> dict[str, object]:
    return {
        "snapshot_item_id": item.snapshot_item_id,
        "intent_id": item.intent_id,
        "normalized_digest": item.normalized_digest,
        "representation_digest": item.representation_digest,
        "metadata": json.loads(item.metadata_json),
        "registry_overlay": (
            json.loads(item.registry_overlay_json)
            if item.registry_overlay_json is not None
            else None
        ),
    }


def _generation_dict(
    generation: EmbeddingGenerationRecord,
) -> dict[str, object]:
    return {
        "embedding_generation_id": generation.embedding_generation_id,
        "provider_id": generation.provider_id,
        "provider_package_version": generation.provider_package_version,
        "model_id": generation.model_id,
        "model_revision": generation.model_revision,
        "model_artifact_fingerprint": generation.model_artifact_fingerprint,
        "exact_model_artifact_reproducibility": (
            generation.exact_model_artifact_reproducibility
        ),
        "dimensions": generation.dimensions,
        "embedding_contract_version": generation.embedding_contract_version,
        "embedding_similarity_metric": generation.embedding_similarity_metric,
        "vector_preprocessing": generation.vector_preprocessing,
        "created_at_utc": generation.created_at_utc,
    }


def _embedding_item_dict(item: EmbeddingItemRecord) -> dict[str, object]:
    return {
        "snapshot_item_id": item.snapshot_item_id,
        "vector_row_key": item.vector_row_key,
        "vector_digest": item.vector_digest,
        "dimensions": item.dimensions,
    }


__all__ = ["export_clustering_json", "export_sweep_comparison_json"]
