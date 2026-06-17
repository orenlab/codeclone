# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ...contracts import CORPUS_EMBEDDING_CONTRACT_VERSION


@dataclass(frozen=True, slots=True)
class ProfileApplicability:
    corpus_size_class: Literal["small_intent"]
    min_record_count: int | None = None
    max_record_count: int | None = None
    embedding_contract_versions: tuple[str, ...] = (CORPUS_EMBEDDING_CONTRACT_VERSION,)


@dataclass(frozen=True, slots=True)
class ProfileRankingPolicy:
    base_score_weight: float = 1.0
    cluster_count_weight: float = 0.0
    cluster_count_direction: Literal[
        "prefer_higher",
        "prefer_lower",
        "neutral",
    ] = "neutral"
    noise_weight: float = 0.0
    noise_direction: Literal[
        "prefer_lower",
        "prefer_higher",
        "neutral",
    ] = "prefer_lower"


@dataclass(frozen=True, slots=True)
class ProfileSearchSpace:
    pca_dimensions: tuple[int, ...]
    min_cluster_size: tuple[int, ...]
    min_samples: tuple[int, ...]
    cluster_selection_method: tuple[Literal["eom", "leaf"], ...]


@dataclass(frozen=True, slots=True)
class ProfileSuitabilityRules:
    min_non_noise_cluster_count: int | None = None
    max_non_noise_cluster_count: int | None = None
    max_dominant_cluster_ratio: float | None = None
    min_dominant_cluster_ratio: float | None = None
    min_noise_ratio: float | None = None
    max_noise_ratio: float | None = None
    min_non_noise_count: int | None = None


@dataclass(frozen=True, slots=True)
class ClusteringProfileManifest:
    manifest_schema_version: str
    profile_id: str
    profile_version: str
    lane: Literal["intent"]
    representation_kinds: tuple[str, ...]
    label: str
    description: str
    applicability: ProfileApplicability
    primary_space: ProfileSearchSpace
    suitability: ProfileSuitabilityRules
    ranking: ProfileRankingPolicy


__all__ = [
    "ClusteringProfileManifest",
    "ProfileApplicability",
    "ProfileRankingPolicy",
    "ProfileSearchSpace",
    "ProfileSuitabilityRules",
]
