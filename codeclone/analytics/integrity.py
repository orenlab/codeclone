# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from ..contracts import CORPUS_EMBEDDING_CONTRACT_VERSION
from .contracts import (
    ClusteringRunRecord,
    CorpusItemRecord,
    EmbeddingGenerationRecord,
    EmbeddingItemRecord,
)
from .corpus.keys import membership_digest
from .exceptions import AnalyticsWorkflowError
from .store.protocols import CorpusStore, VectorGenerationStore
from .store.vectors_lancedb import vector_digest, vector_row_key


def validate_generation_metadata(
    *,
    store: CorpusStore,
    snapshot_id: str,
    embedding_generation_id: str,
    items: Sequence[CorpusItemRecord],
) -> tuple[EmbeddingGenerationRecord, tuple[EmbeddingItemRecord, ...]]:
    generation = store.get_embedding_generation(embedding_generation_id)
    if generation is None:
        raise AnalyticsWorkflowError(
            f"unknown embedding generation: {embedding_generation_id}"
        )
    if generation.embedding_contract_version != CORPUS_EMBEDDING_CONTRACT_VERSION:
        raise AnalyticsWorkflowError(
            "unsupported analytics embedding contract: "
            f"{generation.embedding_contract_version}; "
            f"expected {CORPUS_EMBEDDING_CONTRACT_VERSION}. "
            "Generate a new analytics embedding batch."
        )
    if (
        generation.embedding_similarity_metric != "cosine"
        or generation.vector_preprocessing != "l2_normalize"
    ):
        raise AnalyticsWorkflowError(
            "embedding generation does not match the fixed analytics "
            "cosine/L2 preprocessing contract"
        )
    expected_ids = {item.snapshot_item_id for item in items}
    embedding_items = store.list_embedding_items(
        embedding_generation_id=embedding_generation_id
    )
    actual_ids = {item.snapshot_item_id for item in embedding_items}
    if actual_ids != expected_ids:
        raise AnalyticsWorkflowError(
            "embedding generation does not match snapshot "
            f"{snapshot_id}: missing={len(expected_ids - actual_ids)}, "
            f"foreign={len(actual_ids - expected_ids)}"
        )
    for item in embedding_items:
        if item.dimensions != generation.dimensions:
            raise AnalyticsWorkflowError(
                "embedding dimension mismatch in metadata for "
                f"{item.snapshot_item_id}: item={item.dimensions}, "
                f"generation={generation.dimensions}"
            )
        expected_key = vector_row_key(
            embedding_generation_id=embedding_generation_id,
            snapshot_item_id=item.snapshot_item_id,
        )
        if item.vector_row_key != expected_key:
            raise AnalyticsWorkflowError(
                f"invalid vector row key for {item.snapshot_item_id}"
            )
    return generation, embedding_items


def load_validated_snapshot_vectors(
    *,
    store: CorpusStore,
    vector_store: VectorGenerationStore,
    snapshot_id: str,
    embedding_generation_id: str,
    items: Sequence[CorpusItemRecord],
) -> list[list[float]]:
    generation, embedding_items = validate_generation_metadata(
        store=store,
        snapshot_id=snapshot_id,
        embedding_generation_id=embedding_generation_id,
        items=items,
    )
    metadata_by_id = {item.snapshot_item_id: item for item in embedding_items}
    sidecar_ids = set(
        vector_store.list_generation_item_ids(
            embedding_generation_id=embedding_generation_id,
            limit=len(metadata_by_id) + 1,
        )
    )
    if sidecar_ids != set(metadata_by_id):
        raise AnalyticsWorkflowError(
            "analytics vector generation does not match embedding metadata: "
            f"missing={len(set(metadata_by_id) - sidecar_ids)}, "
            f"foreign={len(sidecar_ids - set(metadata_by_id))}"
        )
    rows = vector_store.read_vector_rows(
        embedding_generation_id=embedding_generation_id,
        snapshot_item_ids=[item.snapshot_item_id for item in items],
    )
    if set(rows) != set(metadata_by_id):
        raise AnalyticsWorkflowError(
            "analytics vector sidecar does not match embedding metadata: "
            f"missing={len(set(metadata_by_id) - set(rows))}, "
            f"foreign={len(set(rows) - set(metadata_by_id))}"
        )
    vectors: list[list[float]] = []
    for corpus_item in items:
        item_id = corpus_item.snapshot_item_id
        row = rows[item_id]
        metadata = metadata_by_id[item_id]
        vector = row["vector"]
        if not isinstance(vector, list):
            raise AnalyticsWorkflowError(f"invalid vector payload for {item_id}")
        typed_vector = [float(value) for value in vector]
        if len(typed_vector) != generation.dimensions:
            raise AnalyticsWorkflowError(
                f"vector dimension mismatch for {item_id}: "
                f"actual={len(typed_vector)}, expected={generation.dimensions}"
            )
        actual_digest = vector_digest(typed_vector)
        if (
            row["vector_digest"] != actual_digest
            or metadata.vector_digest != actual_digest
        ):
            raise AnalyticsWorkflowError(f"vector digest mismatch for {item_id}")
        if row["vector_row_key"] != metadata.vector_row_key:
            raise AnalyticsWorkflowError(f"vector row key mismatch for {item_id}")
        vectors.append(typed_vector)
    return vectors


def validate_persisted_run(
    *,
    store: CorpusStore,
    snapshot_id: str,
    clustering_run_id: str,
) -> ClusteringRunRecord:
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
    if run.status != "completed":
        raise AnalyticsWorkflowError(
            f"clustering run is not completed: {clustering_run_id} ({run.status})"
        )
    items = store.list_items(snapshot_id)
    validate_generation_metadata(
        store=store,
        snapshot_id=snapshot_id,
        embedding_generation_id=run.embedding_generation_id,
        items=items,
    )
    expected_ids = {item.snapshot_item_id for item in items}
    assignments = store.list_assignments(clustering_run_id)
    actual_ids = {item.snapshot_item_id for item in assignments}
    if actual_ids != expected_ids:
        raise AnalyticsWorkflowError(
            "clustering assignments do not match snapshot items: "
            f"missing={len(expected_ids - actual_ids)}, "
            f"foreign={len(actual_ids - expected_ids)}"
        )
    members_by_label: defaultdict[int, list[str]] = defaultdict(list)
    for assignment in assignments:
        members_by_label[assignment.cluster_label].append(assignment.snapshot_item_id)
    summaries = store.list_summaries(clustering_run_id)
    if {item.cluster_label for item in summaries} != set(members_by_label):
        raise AnalyticsWorkflowError("cluster summaries do not match assignments")
    for summary in summaries:
        members = members_by_label[summary.cluster_label]
        digest = membership_digest(members)
        if summary.size != len(members) or summary.membership_digest != digest:
            raise AnalyticsWorkflowError(
                f"cluster summary integrity mismatch for label {summary.cluster_label}"
            )
        if any(
            item.membership_digest != digest
            for item in assignments
            if item.cluster_label == summary.cluster_label
        ):
            raise AnalyticsWorkflowError(
                "assignment membership digest mismatch for label "
                f"{summary.cluster_label}"
            )
    return run


__all__ = [
    "load_validated_snapshot_vectors",
    "validate_generation_metadata",
    "validate_persisted_run",
]
