# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..clustering.models import EffectiveClusteringParameters
from ..metrics.partition_metrics import RunPartitionMetrics
from .loader import profile_manifest_digest
from .models import ClusteringProfileManifest, ProfileRankingPolicy


@dataclass(frozen=True, slots=True)
class ProfileRankedRun:
    clustering_run_id: str
    base_score: float
    profile_score: float
    effective: EffectiveClusteringParameters
    metrics: RunPartitionMetrics


@dataclass(frozen=True, slots=True)
class ProfileRecommendationRationale:
    profile_id: str
    profile_manifest_digest: str
    base_score: float
    profile_score: float
    cluster_count_term: float
    noise_term: float
    ranking_policy: ProfileRankingPolicy


def compute_profile_rank_score(
    *,
    policy: ProfileRankingPolicy,
    base_score: float,
    metrics: RunPartitionMetrics,
    batch_max_cluster_count: int,
) -> tuple[float, float, float]:
    denominator = max(batch_max_cluster_count, 1)
    cluster_norm = metrics.cluster_count / denominator
    cluster_term = _direction_term(
        weight=policy.cluster_count_weight,
        value=cluster_norm,
        direction=policy.cluster_count_direction,
    )
    noise_term = _direction_term(
        weight=policy.noise_weight,
        value=metrics.noise_ratio,
        direction=policy.noise_direction,
    )
    profile_score = policy.base_score_weight * base_score + cluster_term + noise_term
    return profile_score, cluster_term, noise_term


def rank_profile_recommendations(
    *,
    profile: ClusteringProfileManifest,
    candidates: Sequence[ProfileRankedRun],
) -> tuple[ProfileRankedRun | None, ProfileRecommendationRationale | None]:
    if not candidates:
        return None, None
    batch_max = max(candidate.metrics.cluster_count for candidate in candidates)
    scored: list[tuple[ProfileRankedRun, float, float]] = []
    for candidate in candidates:
        profile_score, cluster_term, noise_term = compute_profile_rank_score(
            policy=profile.ranking,
            base_score=candidate.base_score,
            metrics=candidate.metrics,
            batch_max_cluster_count=batch_max,
        )
        scored.append(
            (
                ProfileRankedRun(
                    clustering_run_id=candidate.clustering_run_id,
                    base_score=candidate.base_score,
                    profile_score=profile_score,
                    effective=candidate.effective,
                    metrics=candidate.metrics,
                ),
                cluster_term,
                noise_term,
            )
        )
    winner, cluster_term, noise_term = min(
        scored,
        key=lambda item: (
            -item[0].profile_score,
            item[0].effective.pca_dimensions,
            item[0].effective.min_cluster_size,
            item[0].effective.min_samples,
            item[0].effective.cluster_selection_method,
        ),
    )
    return winner, ProfileRecommendationRationale(
        profile_id=profile.profile_id,
        profile_manifest_digest=profile_manifest_digest(profile),
        base_score=winner.base_score,
        profile_score=winner.profile_score,
        cluster_count_term=cluster_term,
        noise_term=noise_term,
        ranking_policy=profile.ranking,
    )


def _direction_term(*, weight: float, value: float, direction: str) -> float:
    if direction == "prefer_higher":
        return weight * value
    if direction == "prefer_lower":
        return weight * (1.0 - value)
    return 0.0


__all__ = [
    "ProfileRankedRun",
    "ProfileRecommendationRationale",
    "compute_profile_rank_score",
    "rank_profile_recommendations",
]
