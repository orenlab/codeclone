# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import asdict, dataclass

from ...utils.json_io import json_text
from ..corpus.keys import sha256_hex
from ..integrity import PartitionValidityAssessment
from ..metrics.partition_metrics import RunPartitionMetrics
from .loader import profile_manifest_digest
from .models import ClusteringProfileManifest


@dataclass(frozen=True, slots=True)
class ProfileObservedMetrics:
    non_noise_cluster_count: int
    noise_ratio: float
    dominant_cluster_ratio: float
    dominant_assigned_ratio: float | None
    non_noise_count: int


@dataclass(frozen=True, slots=True)
class ProfileSuitabilityAssessment:
    profile_id: str
    profile_version: str
    profile_manifest_digest: str
    suitable_for_profile: bool
    rejection_reasons: tuple[str, ...]
    observed: ProfileObservedMetrics | None


def assess_profile_suitability(
    *,
    profile: ClusteringProfileManifest,
    validity: PartitionValidityAssessment,
    metrics: RunPartitionMetrics | None,
) -> ProfileSuitabilityAssessment:
    digest = profile_manifest_digest(profile)
    if not validity.technically_valid:
        return ProfileSuitabilityAssessment(
            profile_id=profile.profile_id,
            profile_version=profile.profile_version,
            profile_manifest_digest=digest,
            suitable_for_profile=False,
            rejection_reasons=("technically_invalid",),
            observed=None,
        )
    if metrics is None:
        raise ValueError("technically valid partition requires metrics")
    observed = ProfileObservedMetrics(
        non_noise_cluster_count=metrics.cluster_count,
        noise_ratio=metrics.noise_ratio,
        dominant_cluster_ratio=metrics.dominant_cluster_ratio,
        dominant_assigned_ratio=metrics.dominant_assigned_ratio,
        non_noise_count=metrics.non_noise_count,
    )
    rules = profile.suitability
    reasons: list[str] = []
    _append_below(
        reasons,
        observed.non_noise_cluster_count,
        rules.min_non_noise_cluster_count,
        "too_few_clusters",
    )
    _append_above(
        reasons,
        observed.non_noise_cluster_count,
        rules.max_non_noise_cluster_count,
        "too_many_clusters",
    )
    _append_above(
        reasons,
        observed.dominant_cluster_ratio,
        rules.max_dominant_cluster_ratio,
        "dominant_ratio_above_max",
    )
    _append_below(
        reasons,
        observed.dominant_cluster_ratio,
        rules.min_dominant_cluster_ratio,
        "dominant_ratio_below_min",
    )
    _append_above(
        reasons,
        observed.noise_ratio,
        rules.max_noise_ratio,
        "noise_ratio_above_max",
    )
    _append_below(
        reasons,
        observed.noise_ratio,
        rules.min_noise_ratio,
        "noise_ratio_below_min",
    )
    _append_below(
        reasons,
        observed.non_noise_count,
        rules.min_non_noise_count,
        "insufficient_assigned_mass",
    )
    ordered = tuple(sorted(reasons))
    return ProfileSuitabilityAssessment(
        profile_id=profile.profile_id,
        profile_version=profile.profile_version,
        profile_manifest_digest=digest,
        suitable_for_profile=not ordered,
        rejection_reasons=ordered,
        observed=observed,
    )


def profile_assessment_digest(
    *,
    profile_batch_id: str,
    clustering_run_id: str,
    run_digest: str,
    profile_manifest_digest: str,
    assessment: ProfileSuitabilityAssessment,
) -> str:
    payload = {
        "profile_batch_id": profile_batch_id,
        "clustering_run_id": clustering_run_id,
        "run_digest": run_digest,
        "profile_id": assessment.profile_id,
        "profile_version": assessment.profile_version,
        "profile_manifest_digest": profile_manifest_digest,
        "suitable_for_profile": assessment.suitable_for_profile,
        "rejection_reasons": list(assessment.rejection_reasons),
        "observed": (
            asdict(assessment.observed) if assessment.observed is not None else None
        ),
    }
    return sha256_hex(json_text(payload, sort_keys=True))


def _append_below(
    reasons: list[str],
    actual: int | float,
    minimum: int | float | None,
    code: str,
) -> None:
    if minimum is not None and actual < minimum:
        reasons.append(code)


def _append_above(
    reasons: list[str],
    actual: int | float,
    maximum: int | float | None,
    code: str,
) -> None:
    if maximum is not None and actual > maximum:
        reasons.append(code)


__all__ = [
    "ProfileObservedMetrics",
    "ProfileSuitabilityAssessment",
    "assess_profile_suitability",
    "profile_assessment_digest",
]
