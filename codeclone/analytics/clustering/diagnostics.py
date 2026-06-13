# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..contracts import CorpusItemRecord
from .canonicalize import medoid_item_id
from .models import NOISE_LABEL, ClusterPartition


@dataclass(frozen=True, slots=True)
class CorrelationCell:
    numerator: int
    denominator: int
    rate: float | None
    insufficient_sample: bool


@dataclass(frozen=True, slots=True)
class NoiseExplorerFlags:
    short_text: bool
    long_text: bool
    multiple_paragraphs: bool
    high_conjunction_count: bool
    template_match: bool
    low_membership_strength: bool


def cluster_size_percent(size: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return (size / total) * 100.0


def metadata_distribution(
    items: Sequence[CorpusItemRecord],
    *,
    field: str,
) -> dict[str, CorrelationCell]:
    counts: Counter[str] = Counter()
    for item in items:
        payload = _metadata_object(item.metadata_json)
        value = payload.get(field)
        key = str(value) if value is not None else "null"
        counts[key] += 1
    total = len(items)
    return {
        key: _cell(count, total, min_sample_size=5)
        for key, count in sorted(counts.items())
    }


def correlation_rate(
    *,
    numerator: int,
    denominator: int,
    min_sample_size: int,
) -> CorrelationCell:
    return _cell(numerator, denominator, min_sample_size=min_sample_size)


def build_cluster_diagnostics(
    *,
    partition: ClusterPartition,
    items_by_id: Mapping[str, CorpusItemRecord],
    coordinates: Mapping[str, tuple[float, ...]],
    membership_strengths: Mapping[str, float | None],
    total_items: int,
    min_correlation_sample_size: int,
) -> dict[str, object]:
    member_items = [
        items_by_id[item_id]
        for item_id in partition.snapshot_item_ids
        if item_id in items_by_id
    ]
    size = len(member_items)
    medoid = medoid_item_id(
        member_ids=partition.snapshot_item_ids,
        coordinates=dict(coordinates),
    )
    strengths = [
        membership_strengths.get(item_id) for item_id in partition.snapshot_item_ids
    ]
    avg_strength = _average([value for value in strengths if value is not None])
    metadata_fields = (
        "agent_family",
        "outcome",
        "quality_tier",
        "scope_check_status",
        "verification_status",
    )
    distributions = {
        field: {
            key: {
                "numerator": cell.numerator,
                "denominator": cell.denominator,
                "rate": cell.rate,
                "insufficient_sample": cell.insufficient_sample,
            }
            for key, cell in metadata_distribution(
                member_items,
                field=field,
            ).items()
        }
        for field in metadata_fields
    }
    return {
        "cluster_label": partition.cluster_label,
        "membership_digest": partition.membership_digest,
        "size": size,
        "size_percent": cluster_size_percent(size, total_items),
        "medoid_snapshot_item_id": medoid,
        "average_membership_strength": avg_strength,
        "representatives": list(partition.snapshot_item_ids[:5]),
        "metadata_distributions": distributions,
        "min_correlation_sample_size": min_correlation_sample_size,
    }


def noise_explorer_flags(
    *,
    item: CorpusItemRecord,
    membership_strength: float | None,
    strength_threshold: float = 0.2,
) -> NoiseExplorerFlags:
    text = item.normalized_text
    conjunctions = len(re.findall(r"\b(and|or|but|while|whereas)\b", text, re.I))
    return NoiseExplorerFlags(
        short_text=len(text) < 40,
        long_text=len(text) > 800,
        multiple_paragraphs=text.count("\n\n") >= 2,
        high_conjunction_count=conjunctions >= 4,
        template_match=text.startswith("<"),
        low_membership_strength=(
            membership_strength is not None and membership_strength < strength_threshold
        ),
    )


def nearest_cluster_ids(
    *,
    cluster_label: int,
    centroids: Mapping[int, tuple[float, ...]],
    limit: int = 3,
) -> tuple[int, ...]:
    origin = centroids.get(cluster_label)
    if origin is None:
        return ()
    distances: list[tuple[float, int]] = []
    for label, centroid in centroids.items():
        if label in (cluster_label, NOISE_LABEL):
            continue
        distances.append((_euclidean(origin, centroid), label))
    distances.sort(key=lambda item: (item[0], item[1]))
    return tuple(label for _distance, label in distances[:limit])


def compute_centroids(
    *,
    partitions: Sequence[ClusterPartition],
    coordinates: Mapping[str, tuple[float, ...]],
) -> dict[int, tuple[float, ...]]:
    centroids: dict[int, tuple[float, ...]] = {}
    for partition in partitions:
        if partition.cluster_label == NOISE_LABEL:
            continue
        vectors = [
            coordinates[item_id]
            for item_id in partition.snapshot_item_ids
            if item_id in coordinates
        ]
        if not vectors:
            continue
        dim = len(vectors[0])
        sums = [0.0] * dim
        for vector in vectors:
            for index, value in enumerate(vector):
                sums[index] += value
        count = float(len(vectors))
        centroids[partition.cluster_label] = tuple(value / count for value in sums)
    return centroids


def _metadata_object(text: str) -> dict[str, object]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _cell(numerator: int, denominator: int, *, min_sample_size: int) -> CorrelationCell:
    insufficient = denominator < min_sample_size
    rate = (numerator / denominator) if denominator and not insufficient else None
    return CorrelationCell(
        numerator=numerator,
        denominator=denominator,
        rate=rate,
        insufficient_sample=insufficient,
    )


def _average(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _euclidean(left: Sequence[float], right: Sequence[float]) -> float:
    return math.sqrt(float(sum((a - b) ** 2 for a, b in zip(left, right, strict=True))))


__all__ = [
    "CorrelationCell",
    "NoiseExplorerFlags",
    "build_cluster_diagnostics",
    "cluster_size_percent",
    "compute_centroids",
    "correlation_rate",
    "metadata_distribution",
    "nearest_cluster_ids",
    "noise_explorer_flags",
]
