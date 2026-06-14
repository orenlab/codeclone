# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Literal

from ...utils.json_io import json_text
from ..corpus.keys import sha256_hex
from ..profiles.models import ClusteringProfileManifest, ProfileSearchSpace
from .models import ClusteringParameters, EffectiveClusteringParameters
from .pipeline import resolve_effective_parameters

SWEEP_PCA_DIMENSIONS = (32, 64, 128)
SWEEP_MIN_CLUSTER_SIZES = (5, 8, 12, 15)
SWEEP_MIN_SAMPLES = (1, 3, 5)
SWEEP_SELECTION_METHODS: tuple[Literal["eom", "leaf"], ...] = ("eom", "leaf")


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
    grid: ProfileSearchSpace | None = None,
) -> tuple[SweepCandidate, ...]:
    selected_grid = grid or ProfileSearchSpace(
        pca_dimensions=SWEEP_PCA_DIMENSIONS,
        min_cluster_size=SWEEP_MIN_CLUSTER_SIZES,
        min_samples=SWEEP_MIN_SAMPLES,
        cluster_selection_method=SWEEP_SELECTION_METHODS,
    )
    return iter_grid_candidates(
        grid=selected_grid,
        n_samples=n_samples,
        n_features=n_features,
    )


def iter_grid_candidates(
    *,
    grid: ProfileSearchSpace,
    n_samples: int,
    n_features: int,
) -> tuple[SweepCandidate, ...]:
    seen: set[str] = set()
    candidates: list[SweepCandidate] = []
    for pca_dimensions in grid.pca_dimensions:
        for min_cluster_size in grid.min_cluster_size:
            for min_samples in grid.min_samples:
                for method in grid.cluster_selection_method:
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
                    if effective is not None:
                        dedupe_key = candidate_dedupe_key(effective)
                        if dedupe_key not in seen:
                            seen.add(dedupe_key)
                            candidates.append(
                                SweepCandidate(
                                    requested=requested,
                                    effective=effective,
                                    dedupe_key=dedupe_key,
                                )
                            )
    return tuple(
        sorted(
            candidates,
            key=lambda item: (
                item.effective.pca_dimensions,
                item.effective.min_cluster_size,
                item.effective.min_samples,
                item.effective.cluster_selection_method,
            ),
        )
    )


def iter_profile_candidates(
    *,
    profile: ClusteringProfileManifest,
    n_samples: int,
    n_features: int,
) -> tuple[SweepCandidate, ...]:
    return iter_grid_candidates(
        grid=profile.primary_space,
        n_samples=n_samples,
        n_features=n_features,
    )


def candidate_dedupe_key(effective: EffectiveClusteringParameters) -> str:
    return "|".join(
        (
            str(effective.pca_dimensions),
            str(effective.min_cluster_size),
            str(effective.min_samples),
            effective.cluster_selection_method,
        )
    )


def candidate_space_digest(
    candidates: Sequence[SweepCandidate],
    *,
    fixed_parameters: dict[str, object] | None = None,
) -> str:
    return sha256_hex(
        json_text(
            {
                "candidate_dedupe_keys": sorted(
                    candidate.dedupe_key for candidate in candidates
                ),
                "fixed_parameters": fixed_parameters or {},
            },
            sort_keys=True,
        )
    )


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
    algorithm_manifest: dict[str, object],
) -> str:
    payload = {
        "snapshot_id": snapshot_id,
        "embedding_generation_id": embedding_generation_id,
        "effective_parameters": {
            "pca_dimensions": effective.pca_dimensions,
            "min_cluster_size": effective.min_cluster_size,
            "min_samples": effective.min_samples,
            "cluster_selection_method": effective.cluster_selection_method,
            "n_samples": effective.n_samples,
            "n_features": effective.n_features,
        },
        "random_seed": random_seed,
        "algorithm_manifest": algorithm_manifest,
    }
    return sha256_hex(json_text(payload, sort_keys=True))


def clustering_algorithm_manifest() -> dict[str, object]:
    return {
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
        "numpy_version": _package_version("numpy"),
        "scipy_version": _package_version("scipy"),
        "scikit_learn_version": _package_version("scikit-learn"),
        "hdbscan_version": _package_version("hdbscan"),
        "vector_preprocessing": "l2_normalize",
        "pca_solver": "full",
        "pca_whiten": False,
        "clustering_input": "pca_reduced_coordinates",
        "hdbscan_implementation": "hdbscan",
        "clustering_metric": "euclidean",
        "hdbscan_core_dist_n_jobs": 1,
    }


def _package_version(distribution: str) -> str:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return "unknown"


__all__ = [
    "SWEEP_MIN_CLUSTER_SIZES",
    "SWEEP_MIN_SAMPLES",
    "SWEEP_PCA_DIMENSIONS",
    "SWEEP_SELECTION_METHODS",
    "SweepCandidate",
    "SweepCandidateResult",
    "candidate_dedupe_key",
    "candidate_space_digest",
    "clustering_algorithm_manifest",
    "iter_grid_candidates",
    "iter_profile_candidates",
    "iter_sweep_candidates",
    "rank_sweep_results",
    "run_digest",
    "score_clustering_result",
]
