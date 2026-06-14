# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, TypedDict

from ..embedding.length import (
    LengthDistribution,
    PlanningTextTokenEstimator,
    TokenEstimatingProvider,
    length_distribution,
    token_overflow_stats,
)
from .sources import IndexSource

SemanticLane = Literal["memory", "audit", "trajectory"]


class _DistributionPayload(TypedDict):
    min: int
    p50: int
    p75: int
    p95: int
    p99: int
    max: int


class _TokenOverflowPayload(TypedDict):
    model_max_tokens: int | None
    over_model_limit: int
    max_overflow_tokens: int


class LaneProjectionProbePayload(TypedDict):
    documents: int
    chars: _DistributionPayload
    tokens: _DistributionPayload
    token_overflow: _TokenOverflowPayload


class SemanticProjectionProbePayload(TypedDict):
    action: Literal["probe_semantic_projections"]
    lanes: dict[SemanticLane, LaneProjectionProbePayload]
    estimator: str
    model_max_tokens: int | None


@dataclass(frozen=True, slots=True)
class _LaneSamples:
    char_counts: list[int]
    token_counts: list[int]


def probe_semantic_projections(
    *,
    sources: Sequence[IndexSource],
    token_estimator: TokenEstimatingProvider,
) -> SemanticProjectionProbePayload:
    model_max = token_estimator.max_sequence_tokens()
    by_lane: dict[SemanticLane, _LaneSamples] = {
        "memory": _LaneSamples([], []),
        "audit": _LaneSamples([], []),
        "trajectory": _LaneSamples([], []),
    }
    for source in sources:
        if not source.available():
            continue
        lane = _lane_name(source.name())
        samples = by_lane[lane]
        for projection in source.iter_projections():
            text = projection.text
            char_count = len(text)
            (token_count,) = token_estimator.estimate_token_counts([text])
            samples.char_counts.append(char_count)
            samples.token_counts.append(token_count)
    return {
        "action": "probe_semantic_projections",
        "estimator": _probe_estimator_label(token_estimator),
        "model_max_tokens": model_max,
        "lanes": {
            lane: _lane_payload(samples, model_max_tokens=model_max)
            for lane, samples in by_lane.items()
        },
    }


def _probe_estimator_label(token_estimator: TokenEstimatingProvider) -> str:
    if isinstance(token_estimator, PlanningTextTokenEstimator):
        return token_estimator.estimator_label
    return "chars_approx"


def _lane_name(name: str) -> SemanticLane:
    if name not in {"memory", "audit", "trajectory"}:
        raise ValueError(f"unknown semantic lane: {name}")
    return name  # type: ignore[return-value]


def _lane_payload(
    samples: _LaneSamples,
    *,
    model_max_tokens: int | None,
) -> LaneProjectionProbePayload:
    char_dist = length_distribution(samples.char_counts)
    token_dist = length_distribution(samples.token_counts)
    overflow = token_overflow_stats(
        samples.token_counts,
        model_max_tokens=model_max_tokens,
    )
    return {
        "documents": len(samples.char_counts),
        "chars": _distribution_payload(char_dist),
        "tokens": _distribution_payload(token_dist),
        "token_overflow": {
            "model_max_tokens": overflow.model_max_tokens,
            "over_model_limit": overflow.over_model_limit,
            "max_overflow_tokens": overflow.max_overflow_tokens,
        },
    }


def _distribution_payload(distribution: LengthDistribution) -> _DistributionPayload:
    return {
        "min": distribution.min,
        "p50": distribution.p50,
        "p75": distribution.p75,
        "p95": distribution.p95,
        "p99": distribution.p99,
        "max": distribution.max,
    }


__all__ = [
    "LaneProjectionProbePayload",
    "SemanticLane",
    "SemanticProjectionProbePayload",
    "probe_semantic_projections",
]
