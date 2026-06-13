# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ...utils.json_io import json_text
from ..corpus.keys import sha256_hex
from .models import ClusteringParameters, EffectiveClusteringParameters
from .pipeline import resolve_effective_parameters

SWEEP_PCA_DIMENSIONS = (32, 64, 128)
SWEEP_MIN_CLUSTER_SIZES = (5, 8, 12, 15)
SWEEP_MIN_SAMPLES = (1, 3, 5)
SWEEP_SELECTION_METHODS = ("eom", "leaf")


@dataclass(frozen=True, slots=True)
class SweepCandidate:
    requested: ClusteringParameters
    effective: EffectiveClusteringParameters
    dedupe_key: str


@dataclass(frozen=True, slots=True)
class SweepCandidateResult:
    candidate: SweepCandidate
    score: float
    cluster_count: int
    noise_fraction: float


def iter_sweep_candidates(
    *,
    n_samples: int,
    n_features: int,
) -> tuple[SweepCandidate, ...]:
    seen: set[str] = set()
    candidates: list[SweepCandidate] = []
    for pca_dimensions in SWEEP_PCA_DIMENSIONS:
        for min_cluster_size in SWEEP_MIN_CLUSTER_SIZES:
            for min_samples in SWEEP_MIN_SAMPLES:
                for method in SWEEP_SELECTION_METHODS:
                    requested = ClusteringParameters(
                        pca_dimensions=pca_dimensions,
                        min_cluster_size=min_cluster_size,
                        min_samples=min_samples,
                        cluster_selection_method=method,
                    )
                    effective = resolve_effective_parameters(
                        requested,
                        n_samples=n_samples,
                        n_features=n_features,
                    )
                    if effective is None:
                        continue
                    dedupe_key = json_text(
                        {
                            "pca_dimensions": effective.pca_dimensions,
                            "min_cluster_size": effective.min_cluster_size,
                            "min_samples": effective.min_samples,
                            "cluster_selection_method": (
                                effective.cluster_selection_method
                            ),
                        },
                        sort_keys=True,
                    )
                    if dedupe_key in seen:
                        continue
                    seen.add(dedupe_key)
                    candidates.append(
                        SweepCandidate(
                            requested=requested,
                            effective=effective,
                            dedupe_key=dedupe_key,
                        )
                    )
    return tuple(candidates)


def rank_sweep_results(
    results: Sequence[SweepCandidateResult],
) -> SweepCandidateResult | None:
    if not results:
        return None
    return min(
        results,
        key=lambda item: (
            -item.score,
            item.candidate.effective.pca_dimensions,
            item.candidate.effective.min_cluster_size,
            item.candidate.effective.min_samples,
            item.candidate.effective.cluster_selection_method,
        ),
    )


def score_clustering_result(
    *,
    cluster_count: int,
    noise_fraction: float,
    n_samples: int,
) -> float:
    if n_samples == 0:
        return 0.0
    cluster_bonus = min(cluster_count, 12) / 12.0
    noise_penalty = noise_fraction
    return cluster_bonus - noise_penalty


def run_digest(
    *,
    snapshot_id: str,
    embedding_generation_id: str,
    effective: EffectiveClusteringParameters,
    random_seed: int,
) -> str:
    payload = {
        "snapshot_id": snapshot_id,
        "embedding_generation_id": embedding_generation_id,
        "effective_parameters": {
            "pca_dimensions": effective.pca_dimensions,
            "min_cluster_size": effective.min_cluster_size,
            "min_samples": effective.min_samples,
            "cluster_selection_method": effective.cluster_selection_method,
        },
        "random_seed": random_seed,
    }
    return sha256_hex(json_text(payload, sort_keys=True))


__all__ = [
    "SWEEP_MIN_CLUSTER_SIZES",
    "SWEEP_MIN_SAMPLES",
    "SWEEP_PCA_DIMENSIONS",
    "SWEEP_SELECTION_METHODS",
    "SweepCandidate",
    "SweepCandidateResult",
    "iter_sweep_candidates",
    "rank_sweep_results",
    "run_digest",
    "score_clustering_result",
]
