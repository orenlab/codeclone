# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ClusteringParameters:
    pca_dimensions: int
    min_cluster_size: int
    min_samples: int
    cluster_selection_method: str


@dataclass(frozen=True, slots=True)
class EffectiveClusteringParameters:
    pca_dimensions: int
    min_cluster_size: int
    min_samples: int
    cluster_selection_method: str
    n_samples: int
    n_features: int


@dataclass(frozen=True, slots=True)
class ClusterPartition:
    cluster_label: int
    snapshot_item_ids: tuple[str, ...]
    membership_digest: str


@dataclass(frozen=True, slots=True)
class ClusteringPipelineResult:
    partitions: tuple[ClusterPartition, ...]
    labels: tuple[int, ...]
    membership_strengths: tuple[float | None, ...]
    reduced_coordinates: tuple[tuple[float, ...], ...]
    effective_parameters: EffectiveClusteringParameters


NOISE_LABEL = -1


__all__ = [
    "NOISE_LABEL",
    "ClusterPartition",
    "ClusteringParameters",
    "ClusteringPipelineResult",
    "EffectiveClusteringParameters",
]
