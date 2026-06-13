# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ClusteringRunStatus = Literal["pending", "running", "completed", "failed"]
IntentRepresentationKind = Literal[
    "intent.description.v1",
    "intent.description_with_frame.v1",
]
CorpusLane = Literal["intent"]

INTENT_REPRESENTATION_DESCRIPTION = "intent.description.v1"
INTENT_REPRESENTATION_DESCRIPTION_WITH_FRAME = "intent.description_with_frame.v1"


@dataclass(frozen=True, slots=True)
class CorpusItemRecord:
    snapshot_id: str
    representation_key: str
    snapshot_item_id: str
    source_record_key: str
    project_id: str
    intent_id: str
    normalized_text: str
    normalized_digest: str
    normalizer_version: str
    representation_digest: str
    metadata_json: str
    registry_overlay_json: str | None


@dataclass(frozen=True, slots=True)
class CorpusSnapshotRecord:
    snapshot_id: str
    lane: CorpusLane
    representation_kind: str
    representation_version: str
    source_stores_json: str
    source_schema_versions_json: str
    record_count: int
    source_digest: str
    created_at_utc: str


@dataclass(frozen=True, slots=True)
class EmbeddingGenerationRecord:
    embedding_generation_id: str
    provider_id: str
    provider_package_version: str
    model_id: str
    model_revision: str | None
    model_artifact_fingerprint: str | None
    exact_model_artifact_reproducibility: bool
    dimensions: int
    embedding_contract_version: str
    embedding_similarity_metric: str
    vector_preprocessing: str
    created_at_utc: str


@dataclass(frozen=True, slots=True)
class EmbeddingItemRecord:
    embedding_generation_id: str
    snapshot_item_id: str
    vector_row_key: str
    vector_digest: str
    dimensions: int


@dataclass(frozen=True, slots=True)
class ClusteringRunRecord:
    clustering_run_id: str
    snapshot_id: str
    embedding_generation_id: str
    requested_parameters_json: str
    effective_parameters_json: str
    random_seed: int
    run_digest: str
    recommended_by_heuristic: bool
    selected_by_maintainer: bool
    status: ClusteringRunStatus
    created_at_utc: str
    finished_at_utc: str | None
    error_message: str | None


@dataclass(frozen=True, slots=True)
class ClusterAssignmentRecord:
    clustering_run_id: str
    snapshot_item_id: str
    cluster_label: int
    membership_strength: float | None
    membership_digest: str


@dataclass(frozen=True, slots=True)
class ClusterSummaryRecord:
    clustering_run_id: str
    cluster_label: int
    display_cluster_id: int | None
    membership_digest: str
    size: int
    diagnostics_json: str


__all__ = [
    "INTENT_REPRESENTATION_DESCRIPTION",
    "INTENT_REPRESENTATION_DESCRIPTION_WITH_FRAME",
    "ClusterAssignmentRecord",
    "ClusterSummaryRecord",
    "ClusteringRunRecord",
    "ClusteringRunStatus",
    "CorpusItemRecord",
    "CorpusLane",
    "CorpusSnapshotRecord",
    "EmbeddingGenerationRecord",
    "EmbeddingItemRecord",
    "IntentRepresentationKind",
]
