# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import replace
from typing import cast

import pytest

from codeclone.analytics.contracts import (
    ClusterAssignmentRecord,
    ClusteringRunRecord,
    ClusterSummaryRecord,
    CorpusItemRecord,
    CorpusSnapshotRecord,
    EmbeddingGenerationRecord,
    EmbeddingItemRecord,
)
from codeclone.analytics.corpus.keys import membership_digest
from codeclone.analytics.exceptions import AnalyticsWorkflowError
from codeclone.analytics.integrity import (
    load_validated_snapshot_vectors,
    validate_generation_metadata,
    validate_persisted_run,
)
from codeclone.analytics.store.protocols import CorpusStore, VectorGenerationStore
from codeclone.analytics.store.vectors_lancedb import vector_digest, vector_row_key
from codeclone.contracts import CORPUS_EMBEDDING_CONTRACT_VERSION


def _item(item_id: str = "item-a") -> CorpusItemRecord:
    return CorpusItemRecord(
        snapshot_id="snapshot",
        representation_key=f"representation-{item_id}",
        snapshot_item_id=item_id,
        source_record_key=f"source-{item_id}",
        project_id="project",
        intent_id=f"intent-{item_id}",
        normalized_text="normalized text",
        normalized_digest="normalized-digest",
        normalizer_version="1",
        representation_digest="representation-digest",
        metadata_json="{}",
        registry_overlay_json=None,
    )


def _snapshot() -> CorpusSnapshotRecord:
    return CorpusSnapshotRecord(
        snapshot_id="snapshot",
        lane="intent",
        representation_kind="intent.description.v1",
        representation_version="2",
        source_stores_json="{}",
        source_schema_versions_json="{}",
        record_count=1,
        source_digest="source-digest",
        created_at_utc="2026-01-01T00:00:00Z",
    )


def _generation() -> EmbeddingGenerationRecord:
    return EmbeddingGenerationRecord(
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


def _embedding_item(item_id: str = "item-a") -> EmbeddingItemRecord:
    vector = [1.0, 0.0]
    return EmbeddingItemRecord(
        embedding_generation_id="embedding",
        snapshot_item_id=item_id,
        vector_row_key=vector_row_key(
            embedding_generation_id="embedding",
            snapshot_item_id=item_id,
        ),
        vector_digest=vector_digest(vector),
        dimensions=2,
    )


def _run() -> ClusteringRunRecord:
    return ClusteringRunRecord(
        clustering_run_id="run",
        snapshot_id="snapshot",
        embedding_generation_id="embedding",
        requested_parameters_json="{}",
        effective_parameters_json="{}",
        random_seed=42,
        run_digest="run-digest",
        recommended_by_heuristic=False,
        selected_by_maintainer=False,
        status="completed",
        created_at_utc="2026-01-01T00:00:00Z",
        finished_at_utc="2026-01-01T00:00:01Z",
        error_message=None,
    )


class _Store:
    def __init__(self) -> None:
        self.snapshot: CorpusSnapshotRecord | None = _snapshot()
        self.items = (_item(),)
        self.generation: EmbeddingGenerationRecord | None = _generation()
        self.embedding_items = (_embedding_item(),)
        self.run: ClusteringRunRecord | None = _run()
        digest = membership_digest(["item-a"])
        self.assignments: tuple[ClusterAssignmentRecord, ...] = (
            ClusterAssignmentRecord("run", "item-a", 0, 1.0, digest),
        )
        self.summaries: tuple[ClusterSummaryRecord, ...] = (
            ClusterSummaryRecord("run", 0, 1, digest, 1, "{}"),
        )

    def get_snapshot(self, _snapshot_id: str) -> CorpusSnapshotRecord | None:
        return self.snapshot

    def list_items(self, _snapshot_id: str) -> tuple[CorpusItemRecord, ...]:
        return self.items

    def get_embedding_generation(
        self,
        _embedding_generation_id: str,
    ) -> EmbeddingGenerationRecord | None:
        return self.generation

    def list_embedding_items(
        self,
        *,
        embedding_generation_id: str,
    ) -> tuple[EmbeddingItemRecord, ...]:
        assert embedding_generation_id == "embedding"
        return self.embedding_items

    def get_clustering_run(self, _run_id: str) -> ClusteringRunRecord | None:
        return self.run

    def list_assignments(
        self,
        _run_id: str,
    ) -> tuple[ClusterAssignmentRecord, ...]:
        return self.assignments

    def list_summaries(self, _run_id: str) -> tuple[ClusterSummaryRecord, ...]:
        return self.summaries


class _Vectors:
    def __init__(self) -> None:
        row_key = vector_row_key(
            embedding_generation_id="embedding",
            snapshot_item_id="item-a",
        )
        self.item_ids = ("item-a",)
        self.rows: dict[str, dict[str, object]] = {
            "item-a": {
                "vector_row_key": row_key,
                "vector_digest": vector_digest([1.0, 0.0]),
                "vector": [1.0, 0.0],
            }
        }

    def list_generation_item_ids(
        self,
        *,
        embedding_generation_id: str,
        limit: int,
    ) -> tuple[str, ...]:
        assert embedding_generation_id == "embedding"
        assert limit == 2
        return self.item_ids

    def read_vector_rows(
        self,
        *,
        embedding_generation_id: str,
        snapshot_item_ids: tuple[str, ...] | list[str],
    ) -> dict[str, dict[str, object]]:
        assert embedding_generation_id == "embedding"
        assert snapshot_item_ids == ["item-a"]
        return self.rows


def _as_store(store: _Store) -> CorpusStore:
    return cast(CorpusStore, store)


def _as_vectors(vectors: _Vectors) -> VectorGenerationStore:
    return cast(VectorGenerationStore, vectors)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing", "unknown embedding generation"),
        ("contract", "unsupported analytics embedding contract"),
        ("metric", "cosine/L2 preprocessing contract"),
        ("item_set", "does not match snapshot"),
        ("dimensions", "dimension mismatch in metadata"),
        ("row_key", "invalid vector row key"),
    ],
)
def test_generation_metadata_rejects_each_broken_invariant(
    mutation: str,
    message: str,
) -> None:
    store = _Store()
    if mutation == "missing":
        store.generation = None
    elif mutation == "contract":
        store.generation = replace(_generation(), embedding_contract_version="old")
    elif mutation == "metric":
        store.generation = replace(_generation(), embedding_similarity_metric="dot")
    elif mutation == "item_set":
        store.embedding_items = (_embedding_item("foreign"),)
    elif mutation == "dimensions":
        store.embedding_items = (replace(_embedding_item(), dimensions=3),)
    else:
        store.embedding_items = (replace(_embedding_item(), vector_row_key="bad"),)

    with pytest.raises(AnalyticsWorkflowError, match=message):
        validate_generation_metadata(
            store=_as_store(store),
            snapshot_id="snapshot",
            embedding_generation_id="embedding",
            items=store.items,
        )


def test_generation_metadata_accepts_complete_contract() -> None:
    store = _Store()
    generation, items = validate_generation_metadata(
        store=_as_store(store),
        snapshot_id="snapshot",
        embedding_generation_id="embedding",
        items=store.items,
    )
    assert generation == _generation()
    assert items == (_embedding_item(),)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("sidecar_set", "vector generation does not match"),
        ("row_set", "vector sidecar does not match"),
        ("payload", "invalid vector payload"),
        ("dimensions", "vector dimension mismatch"),
        ("digest", "vector digest mismatch"),
        ("row_key", "vector row key mismatch"),
    ],
)
def test_vector_loading_rejects_each_broken_invariant(
    mutation: str,
    message: str,
) -> None:
    store = _Store()
    vectors = _Vectors()
    if mutation == "sidecar_set":
        vectors.item_ids = ("foreign",)
    elif mutation == "row_set":
        vectors.rows = {}
    elif mutation == "payload":
        vectors.rows["item-a"]["vector"] = "bad"
    elif mutation == "dimensions":
        vectors.rows["item-a"]["vector"] = [1.0]
    elif mutation == "digest":
        vectors.rows["item-a"]["vector_digest"] = "bad"
    else:
        vectors.rows["item-a"]["vector_row_key"] = "bad"

    with pytest.raises(AnalyticsWorkflowError, match=message):
        load_validated_snapshot_vectors(
            store=_as_store(store),
            vector_store=_as_vectors(vectors),
            snapshot_id="snapshot",
            embedding_generation_id="embedding",
            items=store.items,
        )


def test_vector_loading_accepts_verified_float32_digest() -> None:
    store = _Store()
    assert load_validated_snapshot_vectors(
        store=_as_store(store),
        vector_store=_as_vectors(_Vectors()),
        snapshot_id="snapshot",
        embedding_generation_id="embedding",
        items=store.items,
    ) == [[1.0, 0.0]]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("snapshot", "unknown snapshot"),
        ("run", "unknown clustering run"),
        ("ownership", "belongs to snapshot"),
        ("status", "is not completed"),
        ("assignments", "assignments do not match"),
        ("summary_labels", "summaries do not match"),
        ("summary", "summary integrity mismatch"),
        ("assignment_digest", "assignment membership digest mismatch"),
    ],
)
def test_persisted_run_rejects_each_broken_invariant(
    mutation: str,
    message: str,
) -> None:
    store = _Store()
    if mutation == "snapshot":
        store.snapshot = None
    elif mutation == "run":
        store.run = None
    elif mutation == "ownership":
        store.run = replace(_run(), snapshot_id="other")
    elif mutation == "status":
        store.run = replace(_run(), status="failed")
    elif mutation == "assignments":
        store.assignments = ()
    elif mutation == "summary_labels":
        store.summaries = ()
    elif mutation == "summary":
        store.summaries = (replace(store.summaries[0], size=2),)
    else:
        store.assignments = (replace(store.assignments[0], membership_digest="bad"),)

    with pytest.raises(AnalyticsWorkflowError, match=message):
        validate_persisted_run(
            store=_as_store(store),
            snapshot_id="snapshot",
            clustering_run_id="run",
        )


def test_persisted_run_accepts_complete_contract() -> None:
    store = _Store()
    assert (
        validate_persisted_run(
            store=_as_store(store),
            snapshot_id="snapshot",
            clustering_run_id="run",
        )
        == _run()
    )
