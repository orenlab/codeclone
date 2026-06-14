# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
from collections.abc import Mapping

from ...contracts import CORPUS_EXPORT_SCHEMA_VERSION
from ...utils.json_io import json_text
from ..contracts import (
    ClusteringRunRecord,
    CorpusItemRecord,
    CorpusSnapshotRecord,
    EmbeddingGenerationRecord,
    EmbeddingItemRecord,
)
from ..exceptions import AnalyticsWorkflowError
from ..report.interpret import (
    INTERPRETATION_CONTRACT_VERSION,
    build_sweep_comparison_projection,
    content_disclosure,
    enrich_run_for_export,
)
from ..store.sqlite import SqliteCorpusAnalyticsStore

_REPRODUCIBILITY_NOTE = (
    "Full vector reproducibility is not guaranteed from model id alone."
)
_MISSING_GENERATION_NOTE = (
    "Embedding generation metadata is unavailable; interpretation is limited "
    "to persisted diagnostic facts."
)


def export_clustering_json(
    *,
    store: SqliteCorpusAnalyticsStore,
    snapshot_id: str,
    clustering_run_id: str,
) -> str:
    snapshot, run = _owned_context(
        store=store,
        snapshot_id=snapshot_id,
        clustering_run_id=clustering_run_id,
    )
    generation = store.get_embedding_generation(run.embedding_generation_id)
    projection = enrich_run_for_export(store=store, snapshot=snapshot, run=run)
    payload: dict[str, object] = {
        "schema_version": CORPUS_EXPORT_SCHEMA_VERSION,
        "interpretation_contract_version": INTERPRETATION_CONTRACT_VERSION,
        "snapshot": _snapshot_dict(snapshot),
        "embedding_generation": _generation_dict(generation),
        "embedding_items": _embedding_items(
            store=store,
            generation=generation,
            embedding_generation_id=run.embedding_generation_id,
        ),
        "clustering_run": projection["run"],
        "exact_model_artifact_reproducibility": (
            generation.exact_model_artifact_reproducibility
            if generation is not None
            else None
        ),
        "reproducibility_statement": _reproducibility_statement(generation),
        "sweep_candidates": _single_export_sweep_candidates(
            store=store,
            snapshot=snapshot,
            embedding_generation_id=run.embedding_generation_id,
        ),
    }
    payload.update(
        _full_projection_payload(
            store=store,
            snapshot=snapshot,
            projection=projection,
        )
    )
    payload["content_disclosure"] = content_disclosure(payload)
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
    candidates, comparison_summary = build_sweep_comparison_projection(
        store=store,
        snapshot=snapshot,
        embedding_generation_id=embedding_generation_id,
    )
    payload: dict[str, object] = {
        "schema_version": CORPUS_EXPORT_SCHEMA_VERSION,
        "interpretation_contract_version": INTERPRETATION_CONTRACT_VERSION,
        "snapshot": _snapshot_dict(snapshot),
        "embedding_generation": _generation_dict(generation),
        "embedding_items": _embedding_items(
            store=store,
            generation=generation,
            embedding_generation_id=embedding_generation_id,
        ),
        "candidates": candidates,
        "comparison_summary": comparison_summary,
        "exact_model_artifact_reproducibility": (
            generation.exact_model_artifact_reproducibility
            if generation is not None
            else None
        ),
        "reproducibility_statement": _reproducibility_statement(generation),
    }
    payload["content_disclosure"] = content_disclosure(payload)
    return json_text(payload, sort_keys=True, indent=True, trailing_newline=True)


def _owned_context(
    *,
    store: SqliteCorpusAnalyticsStore,
    snapshot_id: str,
    clustering_run_id: str,
) -> tuple[CorpusSnapshotRecord, ClusteringRunRecord]:
    snapshot = store.get_snapshot(snapshot_id)
    if snapshot is None:
        raise AnalyticsWorkflowError(f"unknown snapshot: {snapshot_id}")
    run = store.get_clustering_run(clustering_run_id)
    if run is None:
        raise AnalyticsWorkflowError(f"unknown clustering run: {clustering_run_id}")
    if run.snapshot_id != snapshot_id:
        raise AnalyticsWorkflowError(
            f"clustering run {clustering_run_id} belongs to snapshot "
            f"{run.snapshot_id}, not {snapshot_id}"
        )
    return snapshot, run


def _single_export_sweep_candidates(
    *,
    store: SqliteCorpusAnalyticsStore,
    snapshot: CorpusSnapshotRecord,
    embedding_generation_id: str,
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for candidate in store.list_clustering_runs(
        snapshot_id=snapshot.snapshot_id,
        embedding_generation_id=embedding_generation_id,
    ):
        if candidate.status != "completed":
            continue
        projection = enrich_run_for_export(
            store=store,
            snapshot=snapshot,
            run=candidate,
        )
        run_payload = projection.get("run")
        result.append(dict(run_payload) if isinstance(run_payload, Mapping) else {})
    return result


def _full_projection_payload(
    *,
    store: SqliteCorpusAnalyticsStore,
    snapshot: CorpusSnapshotRecord,
    projection: Mapping[str, object],
) -> dict[str, object]:
    if "clusters" not in projection:
        return {}
    return {
        "clusters": projection["clusters"],
        "assignments": projection["assignments"],
        "noise_items": projection["noise_items"],
        "items": [_item_dict(item) for item in store.list_items(snapshot.snapshot_id)],
    }


def _snapshot_dict(snapshot: CorpusSnapshotRecord) -> dict[str, object]:
    return {
        "snapshot_id": snapshot.snapshot_id,
        "lane": snapshot.lane,
        "representation_kind": snapshot.representation_kind,
        "representation_version": snapshot.representation_version,
        "source_stores": _json_object_or_none(snapshot.source_stores_json),
        "source_schema_versions": _json_object_or_none(
            snapshot.source_schema_versions_json
        ),
        "record_count": snapshot.record_count,
        "source_digest": snapshot.source_digest,
        "created_at_utc": snapshot.created_at_utc,
    }


def _item_dict(item: CorpusItemRecord) -> dict[str, object]:
    return {
        "snapshot_item_id": item.snapshot_item_id,
        "intent_id": item.intent_id,
        "normalized_digest": item.normalized_digest,
        "representation_digest": item.representation_digest,
        "metadata": _json_object_or_none(item.metadata_json),
        "registry_overlay": (
            _json_object_or_none(item.registry_overlay_json)
            if item.registry_overlay_json is not None
            else None
        ),
    }


def _generation_dict(
    generation: EmbeddingGenerationRecord | None,
) -> dict[str, object] | None:
    if generation is None:
        return None
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


def _embedding_items(
    *,
    store: SqliteCorpusAnalyticsStore,
    generation: EmbeddingGenerationRecord | None,
    embedding_generation_id: str,
) -> list[dict[str, object]]:
    if generation is None:
        return []
    return [
        _embedding_item_dict(item)
        for item in store.list_embedding_items(
            embedding_generation_id=embedding_generation_id
        )
    ]


def _embedding_item_dict(item: EmbeddingItemRecord) -> dict[str, object]:
    return {
        "snapshot_item_id": item.snapshot_item_id,
        "vector_row_key": item.vector_row_key,
        "vector_digest": item.vector_digest,
        "dimensions": item.dimensions,
    }


def _reproducibility_statement(
    generation: EmbeddingGenerationRecord | None,
) -> str | None:
    if generation is None:
        return _MISSING_GENERATION_NOTE
    if generation.exact_model_artifact_reproducibility:
        return None
    return _REPRODUCIBILITY_NOTE


def _json_object_or_none(text: str) -> dict[str, object] | None:
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


__all__ = ["export_clustering_json", "export_sweep_comparison_json"]
