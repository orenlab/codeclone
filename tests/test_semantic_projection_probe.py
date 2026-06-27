# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Iterator, Sequence

from codeclone.memory.embedding.length import (
    PlanningTextTokenEstimator,
    truncation_stats,
)
from codeclone.memory.semantic.models import SemanticProjection
from codeclone.memory.semantic.projection import text_hash
from codeclone.memory.semantic.projection_probe import probe_semantic_projections
from codeclone.memory.semantic.sources import IndexSource, SourceScan


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

    def scan(self) -> SourceScan:
        return SourceScan(
            revisions={p.source_id: p.source_revision for p in self._projections}
        )

    def project(self, source_ids: Sequence[str]) -> Iterator[SemanticProjection]:
        wanted = set(source_ids)
        yield from (p for p in self._projections if p.source_id in wanted)


def _projection(source: str, source_id: str, text: str) -> SemanticProjection:
    return SemanticProjection(
        source=source,  # type: ignore[arg-type]
        source_id=source_id,
        kind="test",
        text=text,
        text_hash=text_hash(text),
    )


def test_length_distribution_percentiles() -> None:
    from codeclone.memory.embedding.length import length_distribution

    dist = length_distribution([10, 20, 30, 40, 100])
    assert dist.min == 10
    assert dist.p50 == 30
    assert dist.max == 100


def test_truncation_stats_counts_dropped_tokens() -> None:
    stats = truncation_stats([600, 100], [512, 100])
    assert stats.documents == 1
    assert stats.max_dropped_tokens == 88


def test_probe_semantic_projections_reports_lane_stats() -> None:
    estimator = PlanningTextTokenEstimator(
        mode="chars_approx",
        model_max_tokens=512,
    )
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
        token_prober=estimator,
    )
    assert payload["action"] == "probe_semantic_projections"
    assert payload["estimator"] == "chars_approx"
    assert payload["model_max_tokens"] == 512
    assert payload["lanes"]["memory"]["documents"] == 1
    assert payload["lanes"]["trajectory"]["documents"] == 1
    assert payload["lanes"]["trajectory"]["chars"]["max"] == 4000
    assert payload["lanes"]["trajectory"]["tokens"]["raw"]["max"] == 1000
    assert payload["lanes"]["trajectory"]["tokens"]["effective"]["max"] == 1000
    assert payload["lanes"]["trajectory"]["truncation"]["documents"] == 0
    assert payload["lanes"]["trajectory"]["token_overflow"]["over_model_limit"] == 1
    assert (
        payload["lanes"]["trajectory"]["token_overflow"]["max_overflow_tokens"] == 488
    )


def test_probe_trajectory_with_chunker_measures_index_units() -> None:
    from typing import cast

    from codeclone.memory.embedding.length import (
        PassageTokenCounts,
        ProjectionTokenProber,
    )

    class _SplitChunker:
        def chunk_text(self, text: str) -> tuple[str, ...]:
            midpoint = max(1, len(text) // 2)
            return (text[:midpoint], text[midpoint:])

    class _TruncatingProber:
        estimator_label = "test_tokenizer"

        def max_sequence_tokens(self) -> int | None:
            return 512

        def probe_passage_token_counts(
            self,
            texts: Sequence[str],
        ) -> tuple[PassageTokenCounts, ...]:
            counts: list[PassageTokenCounts] = []
            for text in texts:
                raw = len(text) // 4
                effective = min(raw, 512)
                counts.append(PassageTokenCounts(raw=raw, effective=effective))
            return tuple(counts)

    payload = probe_semantic_projections(
        sources=[
            _FakeSource(
                "trajectory",
                [_projection("trajectory", "t1", "x" * 4000)],
            ),
        ],
        token_prober=cast(ProjectionTokenProber, _TruncatingProber()),
        passage_chunker=_SplitChunker(),
    )
    trajectory = payload["lanes"]["trajectory"]
    assert trajectory["chunking"] == {
        "source_documents": 1,
        "index_units": 2,
        "multi_chunk_sources": 1,
    }
    assert trajectory["documents"] == 2
    assert trajectory["truncation"]["documents"] == 0
    assert trajectory["token_overflow"]["over_model_limit"] == 0


def test_probe_trajectory_without_chunker_keeps_source_projection_stats() -> None:
    estimator = PlanningTextTokenEstimator(
        mode="chars_approx",
        model_max_tokens=512,
    )
    payload = probe_semantic_projections(
        sources=[
            _FakeSource(
                "trajectory",
                [_projection("trajectory", "t1", "x" * 4000)],
            ),
        ],
        token_prober=estimator,
    )
    trajectory = payload["lanes"]["trajectory"]
    assert trajectory["documents"] == 1
    assert "chunking" not in trajectory
    assert trajectory["token_overflow"]["over_model_limit"] == 1


def test_probe_collects_overflow_examples_for_trajectory_units() -> None:
    from typing import cast

    from codeclone.memory.embedding.length import (
        PassageTokenCounts,
        ProjectionTokenProber,
    )

    class _OverflowProber:
        estimator_label = "test_tokenizer"

        def max_sequence_tokens(self) -> int | None:
            return 512

        def probe_passage_token_counts(
            self,
            texts: Sequence[str],
        ) -> tuple[PassageTokenCounts, ...]:
            return tuple(PassageTokenCounts(raw=600, effective=512) for _ in texts)

    class _SingleChunker:
        def chunk_text(self, text: str) -> tuple[str, ...]:
            return ("fits", "overflow")

    payload = probe_semantic_projections(
        sources=[
            _FakeSource(
                "trajectory",
                [_projection("trajectory", "t1", "long trajectory")],
            ),
        ],
        token_prober=cast(ProjectionTokenProber, _OverflowProber()),
        passage_chunker=_SingleChunker(),
    )
    trajectory = payload["lanes"]["trajectory"]
    examples = trajectory["overflow_examples"]
    assert len(examples) == 2
    assert all(example["raw_tokens"] == 600 for example in examples)
    assert all(example["overflow_tokens"] == 88 for example in examples)
    assert examples[0]["parent_id"] == "t1"
    assert examples[0]["chunk_index"] == 0
    assert examples[1]["chunk_index"] == 1


def test_probe_defaults_to_planning_estimator_without_exact_tokens() -> None:
    from codeclone.config.memory import SemanticConfig
    from codeclone.memory.semantic.rebuild_workflow import (
        _resolve_projection_token_prober,
    )

    config = SemanticConfig(embedding_provider="fastembed")
    prober = _resolve_projection_token_prober(config, exact_tokens=False)
    assert prober.estimator_label == "chars_approx"
