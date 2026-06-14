# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Iterator, Sequence

from codeclone.memory.embedding.length import length_distribution
from codeclone.memory.semantic.models import SemanticProjection
from codeclone.memory.semantic.projection import text_hash
from codeclone.memory.semantic.projection_probe import probe_semantic_projections
from codeclone.memory.semantic.sources import IndexSource


class _TokenEstimator:
    def estimate_token_counts(self, texts: Sequence[str]) -> tuple[int, ...]:
        return tuple(max(1, len(text) // 4) for text in texts)

    def max_sequence_tokens(self) -> int | None:
        return 512


class _FakeSource(IndexSource):
    def __init__(self, name: str, projections: Sequence[SemanticProjection]) -> None:
        self._name = name
        self._projections = projections

    def name(self) -> str:
        return self._name

    def available(self) -> bool:
        return True

    def iter_projections(self) -> Iterator[SemanticProjection]:
        yield from self._projections


def _projection(source: str, source_id: str, text: str) -> SemanticProjection:
    return SemanticProjection(
        source=source,  # type: ignore[arg-type]
        source_id=source_id,
        kind="test",
        text=text,
        text_hash=text_hash(text),
    )


def test_length_distribution_percentiles() -> None:
    dist = length_distribution([10, 20, 30, 40, 100])
    assert dist.min == 10
    assert dist.p50 == 30
    assert dist.max == 100


def test_probe_semantic_projections_reports_lane_stats() -> None:
    payload = probe_semantic_projections(
        sources=[
            _FakeSource(
                "memory",
                [_projection("memory", "m1", "short memory note")],
            ),
            _FakeSource(
                "trajectory",
                [_projection("trajectory", "t1", "x" * 4000)],
            ),
        ],
        provider=_TokenEstimator(),
    )
    assert payload["action"] == "probe_semantic_projections"
    assert payload["model_max_tokens"] == 512
    assert payload["lanes"]["memory"]["documents"] == 1
    assert payload["lanes"]["trajectory"]["documents"] == 1
    assert payload["lanes"]["trajectory"]["chars"]["max"] == 4000
    assert payload["lanes"]["trajectory"]["tokens"]["max"] == 1000
    assert payload["lanes"]["trajectory"]["token_overflow"]["over_model_limit"] == 1
    assert (
        payload["lanes"]["trajectory"]["token_overflow"]["max_overflow_tokens"] == 488
    )
