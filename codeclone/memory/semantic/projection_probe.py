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
    ProjectionTokenProber,
    length_distribution,
    token_overflow_stats,
    truncation_stats,
)
from .chunking import PassageChunker, expand_projection
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


class _TokenDistributionPayload(TypedDict):
    raw: _DistributionPayload
    effective: _DistributionPayload


class _TruncationPayload(TypedDict):
    documents: int
    max_dropped_tokens: int


class _TrajectoryChunkingPayload(TypedDict):
    source_documents: int
    index_units: int
    multi_chunk_sources: int


class _OverflowExamplePayload(TypedDict):
    id: str
    parent_id: str | None
    chunk_index: int | None
    raw_tokens: int
    overflow_tokens: int


class LaneProjectionProbePayload(TypedDict, total=False):
    documents: int
    chars: _DistributionPayload
    tokens: _TokenDistributionPayload
    truncation: _TruncationPayload
    token_overflow: _TokenOverflowPayload
    chunking: _TrajectoryChunkingPayload
    overflow_examples: list[_OverflowExamplePayload]


class SemanticProjectionProbePayload(TypedDict):
    action: Literal["probe_semantic_projections"]
    lanes: dict[SemanticLane, LaneProjectionProbePayload]
    estimator: str
    model_max_tokens: int | None


@dataclass(slots=True)
class _ProbeUnitContext:
    row_id: str | None = None
    parent_id: str | None = None
    chunk_index: int | None = None


@dataclass(slots=True)
class _LaneSamples:
    char_counts: list[int]
    raw_token_counts: list[int]
    effective_token_counts: list[int]
    unit_contexts: list[_ProbeUnitContext | None]
    overflow_examples: list[_OverflowExamplePayload]
    source_documents: int = 0
    multi_chunk_sources: int = 0


def probe_semantic_projections(
    *,
    sources: Sequence[IndexSource],
    token_prober: ProjectionTokenProber,
    passage_chunker: PassageChunker | None = None,
) -> SemanticProjectionProbePayload:
    model_max = token_prober.max_sequence_tokens()
    by_lane: dict[SemanticLane, _LaneSamples] = {
        "memory": _LaneSamples([], [], [], [], []),
        "audit": _LaneSamples([], [], [], [], []),
        "trajectory": _LaneSamples([], [], [], [], []),
    }
    for source in sources:
        if not source.available():
            continue
        lane = _lane_name(source.name())
        samples = by_lane[lane]
        chunker = passage_chunker if lane == "trajectory" else None
        for projection in source.iter_projections():
            if chunker is None:
                _append_probe_sample(samples, token_prober, projection.text)
                continue
            samples.source_documents += 1
            units = expand_projection(projection, chunker)
            if len(units) > 1:
                samples.multi_chunk_sources += 1
            for unit in units:
                _append_probe_sample(
                    samples,
                    token_prober,
                    unit.text,
                    unit=_ProbeUnitContext(
                        row_id=unit.row_id,
                        parent_id=unit.parent_id,
                        chunk_index=unit.chunk_index,
                    ),
                )
    return {
        "action": "probe_semantic_projections",
        "estimator": token_prober.estimator_label,
        "model_max_tokens": model_max,
        "lanes": {
            lane: _lane_payload(
                samples,
                model_max_tokens=model_max,
                chunking=(
                    {
                        "source_documents": samples.source_documents,
                        "index_units": len(samples.char_counts),
                        "multi_chunk_sources": samples.multi_chunk_sources,
                    }
                    if lane == "trajectory" and passage_chunker is not None
                    else None
                ),
            )
            for lane, samples in by_lane.items()
        },
    }


def _append_probe_sample(
    samples: _LaneSamples,
    token_prober: ProjectionTokenProber,
    text: str,
    *,
    unit: _ProbeUnitContext | None = None,
) -> None:
    (counts,) = token_prober.probe_passage_token_counts([text])
    samples.char_counts.append(len(text))
    samples.raw_token_counts.append(counts.raw)
    samples.effective_token_counts.append(counts.effective)
    samples.unit_contexts.append(unit)
    model_max = token_prober.max_sequence_tokens()
    if (
        unit is not None
        and model_max is not None
        and counts.raw > model_max
        and samples.overflow_examples is not None
        and len(samples.overflow_examples) < 5
    ):
        samples.overflow_examples.append(
            {
                "id": unit.row_id or "",
                "parent_id": unit.parent_id,
                "chunk_index": unit.chunk_index,
                "raw_tokens": counts.raw,
                "overflow_tokens": counts.raw - model_max,
            }
        )


def _lane_name(name: str) -> SemanticLane:
    if name not in {"memory", "audit", "trajectory"}:
        raise ValueError(f"unknown semantic lane: {name}")
    return name  # type: ignore[return-value]


def _lane_payload(
    samples: _LaneSamples,
    *,
    model_max_tokens: int | None,
    chunking: _TrajectoryChunkingPayload | None = None,
) -> LaneProjectionProbePayload:
    char_dist = length_distribution(samples.char_counts)
    raw_dist = length_distribution(samples.raw_token_counts)
    effective_dist = length_distribution(samples.effective_token_counts)
    overflow = token_overflow_stats(
        samples.raw_token_counts,
        model_max_tokens=model_max_tokens,
    )
    truncation = truncation_stats(
        samples.raw_token_counts,
        samples.effective_token_counts,
    )
    payload: LaneProjectionProbePayload = {
        "documents": len(samples.char_counts),
        "chars": _distribution_payload(char_dist),
        "tokens": {
            "raw": _distribution_payload(raw_dist),
            "effective": _distribution_payload(effective_dist),
        },
        "truncation": {
            "documents": truncation.documents,
            "max_dropped_tokens": truncation.max_dropped_tokens,
        },
        "token_overflow": {
            "model_max_tokens": overflow.model_max_tokens,
            "over_model_limit": overflow.over_model_limit,
            "max_overflow_tokens": overflow.max_overflow_tokens,
        },
    }
    if chunking is not None:
        payload["chunking"] = chunking
    if samples.overflow_examples:
        payload["overflow_examples"] = list(samples.overflow_examples)
    return payload


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
