# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from ..contracts import (
    ClusterAssignmentRecord,
    ClusteringRunRecord,
    ClusterSummaryRecord,
    CorpusItemRecord,
    CorpusSnapshotRecord,
    EmbeddingGenerationRecord,
    EmbeddingItemRecord,
)


class CorpusStore(Protocol):
    def insert_snapshot(
        self,
        snapshot: CorpusSnapshotRecord,
        items: Sequence[CorpusItemRecord],
    ) -> None: ...

    def get_snapshot(self, snapshot_id: str) -> CorpusSnapshotRecord | None: ...

    def list_snapshots(self) -> tuple[CorpusSnapshotRecord, ...]: ...

    def list_items(self, snapshot_id: str) -> tuple[CorpusItemRecord, ...]: ...

    def insert_embedding_generation(
        self,
        generation: EmbeddingGenerationRecord,
    ) -> None: ...

    def insert_embedding_items(
        self,
        items: Sequence[EmbeddingItemRecord],
    ) -> None: ...

    def get_embedding_generation(
        self,
        embedding_generation_id: str,
    ) -> EmbeddingGenerationRecord | None: ...

    def list_embedding_items(
        self,
        *,
        embedding_generation_id: str,
    ) -> tuple[EmbeddingItemRecord, ...]: ...

    def insert_clustering_run(self, run: ClusteringRunRecord) -> None: ...

    def update_clustering_run(self, run: ClusteringRunRecord) -> None: ...

    def get_clustering_run(
        self,
        clustering_run_id: str,
    ) -> ClusteringRunRecord | None: ...

    def list_clustering_runs(
        self,
        *,
        snapshot_id: str,
        embedding_generation_id: str | None = None,
    ) -> tuple[ClusteringRunRecord, ...]: ...

    def set_recommended_run(
        self,
        *,
        snapshot_id: str,
        embedding_generation_id: str,
        clustering_run_id: str,
    ) -> None: ...

    def set_selected_run(
        self,
        *,
        snapshot_id: str,
        embedding_generation_id: str,
        clustering_run_id: str,
    ) -> None: ...

    def insert_cluster_assignments(
        self,
        assignments: Sequence[ClusterAssignmentRecord],
    ) -> None: ...

    def insert_cluster_summaries(
        self,
        summaries: Sequence[ClusterSummaryRecord],
    ) -> None: ...

    def list_assignments(
        self,
        clustering_run_id: str,
    ) -> tuple[ClusterAssignmentRecord, ...]: ...

    def list_summaries(
        self,
        clustering_run_id: str,
    ) -> tuple[ClusterSummaryRecord, ...]: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def close(self) -> None: ...


class VectorGenerationStore(Protocol):
    def write_vectors(
        self,
        *,
        embedding_generation_id: str,
        rows: Sequence[Mapping[str, object]],
    ) -> None: ...

    def read_vectors(
        self,
        *,
        embedding_generation_id: str,
        snapshot_item_ids: Sequence[str],
    ) -> dict[str, list[float]]: ...

    def read_vector_rows(
        self,
        *,
        embedding_generation_id: str,
        snapshot_item_ids: Sequence[str],
    ) -> dict[str, dict[str, object]]: ...

    def list_generation_item_ids(
        self,
        *,
        embedding_generation_id: str,
        limit: int,
    ) -> tuple[str, ...]: ...

    def delete_generation(self, embedding_generation_id: str) -> None: ...

    def close(self) -> None: ...


class CorpusSnapshotReader(Protocol):
    def read_items(self, snapshot_id: str) -> tuple[CorpusItemRecord, ...]: ...


@dataclass(frozen=True, slots=True)
class SnapshotBuildResult:
    snapshot_id: str
    source_digest: str
    record_count: int


__all__ = [
    "CorpusSnapshotReader",
    "CorpusStore",
    "SnapshotBuildResult",
    "VectorGenerationStore",
]
