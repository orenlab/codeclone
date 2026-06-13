# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import importlib
import math
import types
from collections.abc import Sequence
from typing import Any

from ..corpus.keys import membership_digest
from ..exceptions import AnalyticsCapabilityError
from .models import (
    NOISE_LABEL,
    ClusteringParameters,
    ClusteringPipelineResult,
    ClusterPartition,
    EffectiveClusteringParameters,
)


def resolve_effective_parameters(
    requested: ClusteringParameters,
    *,
    n_samples: int,
    n_features: int,
) -> EffectiveClusteringParameters | None:
    effective_pca = min(requested.pca_dimensions, n_samples - 1, n_features)
    eligible = n_samples
    if (
        requested.min_cluster_size > eligible
        or requested.min_samples > eligible
        or effective_pca < 2
    ):
        return None
    return EffectiveClusteringParameters(
        pca_dimensions=effective_pca,
        min_cluster_size=requested.min_cluster_size,
        min_samples=requested.min_samples,
        cluster_selection_method=requested.cluster_selection_method,
        n_samples=n_samples,
        n_features=n_features,
    )


def _l2_normalize(matrix: list[list[float]]) -> list[list[float]]:
    normalized: list[list[float]] = []
    for row in matrix:
        norm = math.sqrt(sum(value * value for value in row)) or 1.0
        normalized.append([value / norm for value in row])
    return normalized


def _load_sklearn_pca() -> Any:  # Any: optional sklearn import boundary
    try:
        decomposition = importlib.import_module("sklearn.decomposition")
    except ImportError as exc:
        raise AnalyticsCapabilityError(
            "scikit-learn is required for analytics clustering; "
            "install with: uv sync --extra analytics"
        ) from exc
    return decomposition.PCA


def _load_hdbscan() -> types.ModuleType:
    try:
        return importlib.import_module("hdbscan")
    except ImportError as exc:
        raise AnalyticsCapabilityError(
            "hdbscan is required for analytics clustering; "
            "install with: uv sync --extra analytics"
        ) from exc


def run_clustering_pipeline(
    *,
    snapshot_item_ids: Sequence[str],
    embeddings: Sequence[Sequence[float]],
    requested: ClusteringParameters,
    random_seed: int = 42,
) -> ClusteringPipelineResult | None:
    if len(snapshot_item_ids) != len(embeddings):
        msg = "snapshot_item_ids and embeddings length mismatch"
        raise ValueError(msg)
    if not snapshot_item_ids:
        return None
    n_samples = len(snapshot_item_ids)
    n_features = len(embeddings[0]) if embeddings else 0
    effective = resolve_effective_parameters(
        requested,
        n_samples=n_samples,
        n_features=n_features,
    )
    if effective is None:
        return None

    matrix = _l2_normalize([list(row) for row in embeddings])
    pca_cls = _load_sklearn_pca()
    reducer = pca_cls(
        n_components=effective.pca_dimensions,
        whiten=False,
        svd_solver="full",
        random_state=random_seed,
    )
    reduced = reducer.fit_transform(matrix)
    reduced_rows = [tuple(float(value) for value in row) for row in reduced.tolist()]

    hdbscan = _load_hdbscan()
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=effective.min_cluster_size,
        min_samples=effective.min_samples,
        metric="euclidean",
        cluster_selection_method=effective.cluster_selection_method,
        core_dist_n_jobs=1,
    )
    labels_raw = clusterer.fit_predict(reduced)
    labels = tuple(int(value) for value in labels_raw.tolist())
    probabilities = getattr(clusterer, "probabilities_", None)
    if probabilities is not None:
        strengths: list[float | None] = [
            float(value) for value in probabilities.tolist()
        ]
    else:
        strengths = [None for _ in labels]

    by_label: dict[int, list[str]] = {}
    for item_id, label in zip(snapshot_item_ids, labels, strict=True):
        by_label.setdefault(label, []).append(item_id)

    partitions: list[ClusterPartition] = []
    for label, members in sorted(by_label.items()):
        ordered = sorted(members)
        partitions.append(
            ClusterPartition(
                cluster_label=label,
                snapshot_item_ids=tuple(ordered),
                membership_digest=membership_digest(ordered),
            )
        )

    return ClusteringPipelineResult(
        partitions=tuple(partitions),
        labels=labels,
        membership_strengths=tuple(strengths),
        reduced_coordinates=tuple(reduced_rows),
        effective_parameters=effective,
    )


def is_noise_label(label: int) -> bool:
    return label == NOISE_LABEL


__all__ = [
    "is_noise_label",
    "resolve_effective_parameters",
    "run_clustering_pipeline",
]
