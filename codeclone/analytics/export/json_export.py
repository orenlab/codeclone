# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json

from ...contracts import CORPUS_EXPORT_SCHEMA_VERSION
from ...utils.json_io import json_text
from ..contracts import ClusteringRunRecord, CorpusItemRecord, CorpusSnapshotRecord
from ..store.sqlite import SqliteCorpusAnalyticsStore


def export_clustering_json(
    *,
    store: SqliteCorpusAnalyticsStore,
    snapshot_id: str,
    clustering_run_id: str,
) -> str:
    snapshot = store.get_snapshot(snapshot_id)
    if snapshot is None:
        msg = f"unknown snapshot: {snapshot_id}"
        raise ValueError(msg)
    run = store.get_clustering_run(clustering_run_id)
    if run is None:
        msg = f"unknown clustering run: {clustering_run_id}"
        raise ValueError(msg)
    items = store.list_items(snapshot_id)
    assignments = store.list_assignments(clustering_run_id)
    summaries = store.list_summaries(clustering_run_id)
    generation = store.get_embedding_generation(run.embedding_generation_id)
    payload: dict[str, object] = {
        "schema_version": CORPUS_EXPORT_SCHEMA_VERSION,
        "snapshot": _snapshot_dict(snapshot),
        "embedding_generation": _generation_dict(generation) if generation else None,
        "clustering_run": _run_dict(run),
        "clusters": [_summary_dict(summary) for summary in summaries],
        "assignments": [_assignment_dict(item) for item in assignments],
        "items": [_item_dict(item) for item in items],
        "exact_model_artifact_reproducibility": (
            generation.exact_model_artifact_reproducibility if generation else False
        ),
    }
    return json_text(payload, sort_keys=True, indent=True, trailing_newline=True)


def export_sweep_comparison_json(
    *,
    store: SqliteCorpusAnalyticsStore,
    snapshot_id: str,
    embedding_generation_id: str,
) -> str:
    runs = store.list_clustering_runs(
        snapshot_id=snapshot_id,
        embedding_generation_id=embedding_generation_id,
    )
    payload = {
        "schema_version": CORPUS_EXPORT_SCHEMA_VERSION,
        "snapshot_id": snapshot_id,
        "embedding_generation_id": embedding_generation_id,
        "candidates": [_run_dict(run) for run in runs],
    }
    return json_text(payload, sort_keys=True, indent=True, trailing_newline=True)


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
    return {
        "clustering_run_id": run.clustering_run_id,
        "snapshot_id": run.snapshot_id,
        "embedding_generation_id": run.embedding_generation_id,
        "requested_parameters": json.loads(run.requested_parameters_json),
        "effective_parameters": json.loads(run.effective_parameters_json),
        "random_seed": run.random_seed,
        "run_digest": run.run_digest,
        "recommended_by_heuristic": run.recommended_by_heuristic,
        "selected_by_maintainer": run.selected_by_maintainer,
        "status": run.status,
        "created_at_utc": run.created_at_utc,
        "finished_at_utc": run.finished_at_utc,
        "error_message": run.error_message,
    }


def _summary_dict(summary: object) -> dict[str, object]:
    from ..contracts import ClusterSummaryRecord

    assert isinstance(summary, ClusterSummaryRecord)
    return {
        "cluster_label": summary.cluster_label,
        "display_cluster_id": summary.display_cluster_id,
        "membership_digest": summary.membership_digest,
        "size": summary.size,
        "diagnostics": json.loads(summary.diagnostics_json),
    }


def _assignment_dict(assignment: object) -> dict[str, object]:
    from ..contracts import ClusterAssignmentRecord

    assert isinstance(assignment, ClusterAssignmentRecord)
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


def _generation_dict(generation: object) -> dict[str, object]:
    from ..contracts import EmbeddingGenerationRecord

    assert isinstance(generation, EmbeddingGenerationRecord)
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


__all__ = ["export_clustering_json", "export_sweep_comparison_json"]
