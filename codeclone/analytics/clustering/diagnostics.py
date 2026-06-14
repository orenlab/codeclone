# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from ..contracts import ClusterAssignmentRecord, CorpusItemRecord
from ..integrity import validate_cluster_diagnostic_refs
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


@dataclass(frozen=True, slots=True)
class MetadataDisplayValue:
    kind: Literal["unknown", "confirmed_none", "empty_collection", "value"]
    display: str


@dataclass(frozen=True, slots=True)
class ItemPreview:
    snapshot_item_id: str
    source_record_id: str
    source_kind: str
    intent_id: str | None
    normalized_text_preview: str
    membership_strength: float | None
    agent_family: MetadataDisplayValue
    outcome: MetadataDisplayValue
    quality_tier: MetadataDisplayValue
    scope_check_status: MetadataDisplayValue
    verification_status: MetadataDisplayValue


@dataclass(frozen=True, slots=True)
class NumericFieldSummary:
    field: str
    known_count: int
    unknown_count: int
    min: int | None
    p25: float | None
    median: float | None
    p75: float | None
    max: int | None
    mean: float | None
    buckets: dict[str, int]


EMPTY_MEANS_CONFIRMED_NONE_FIELDS = frozenset({"anomaly_kinds"})
MAX_PREVIEW_CHARACTERS = 240
_MISSING = object()


def cluster_size_percent(size: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return (size / total) * 100.0


def metadata_distribution(
    items: Sequence[CorpusItemRecord],
    *,
    field: str,
    min_sample_size: int,
) -> dict[str, CorrelationCell]:
    counts: Counter[str] = Counter()
    for item in items:
        payload = _metadata_object(item.metadata_json)
        for key in _metadata_values(payload.get(field)):
            counts[key] += 1
    total = len(items)
    return {
        key: _cell(count, total, min_sample_size=min_sample_size)
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
        "scope_expanded",
        "anomaly_kinds",
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
                min_sample_size=min_correlation_sample_size,
            ).items()
        }
        for field in metadata_fields
    }
    representatives = _representative_ids(
        member_ids=partition.snapshot_item_ids,
        medoid=medoid,
        coordinates=coordinates,
        membership_strengths=membership_strengths,
    )
    boundary_items = _boundary_ids(
        member_ids=partition.snapshot_item_ids,
        medoid=medoid,
        coordinates=coordinates,
        membership_strengths=membership_strengths,
    )
    diagnostics: dict[str, object] = {
        "cluster_label": partition.cluster_label,
        "membership_digest": partition.membership_digest,
        "size": size,
        "size_percent": cluster_size_percent(size, total_items),
        "medoid_snapshot_item_id": medoid,
        "average_membership_strength": avg_strength,
        "representatives": list(representatives),
        "boundary_items": list(boundary_items),
        "metadata_distributions": distributions,
        "min_correlation_sample_size": min_correlation_sample_size,
    }
    if partition.cluster_label == NOISE_LABEL:
        diagnostics["noise_items"] = [
            {
                "snapshot_item_id": item.snapshot_item_id,
                "flags": _flags_dict(
                    noise_explorer_flags(
                        item=item,
                        membership_strength=membership_strengths.get(
                            item.snapshot_item_id
                        ),
                    )
                ),
            }
            for item in sorted(member_items, key=lambda entry: entry.snapshot_item_id)
        ]
    else:
        validate_cluster_diagnostic_refs(
            cluster_label=partition.cluster_label,
            diagnostics=diagnostics,
            items_by_id=items_by_id,
            assigned_item_ids=partition.snapshot_item_ids,
        )
    return diagnostics


def build_item_preview(
    item: CorpusItemRecord,
    assignment: ClusterAssignmentRecord | None,
    *,
    source_kind: str,
    source_record_id: str,
) -> ItemPreview:
    metadata = _metadata_object(item.metadata_json)
    return ItemPreview(
        snapshot_item_id=item.snapshot_item_id,
        source_record_id=source_record_id,
        source_kind=source_kind,
        intent_id=item.intent_id if source_kind == "intent_historical" else None,
        normalized_text_preview=truncate_preview(item.normalized_text),
        membership_strength=(
            assignment.membership_strength if assignment is not None else None
        ),
        agent_family=metadata_display_value(metadata, "agent_family"),
        outcome=metadata_display_value(metadata, "outcome"),
        quality_tier=metadata_display_value(metadata, "quality_tier"),
        scope_check_status=metadata_display_value(metadata, "scope_check_status"),
        verification_status=metadata_display_value(metadata, "verification_status"),
    )


def truncate_preview(text: str) -> str:
    if len(text) <= MAX_PREVIEW_CHARACTERS:
        return text
    return text[: MAX_PREVIEW_CHARACTERS - 1] + "\u2026"


def preview_digest(preview: str) -> str:
    return hashlib.sha256(preview.encode("utf-8")).hexdigest()


def metadata_display_value(
    metadata: Mapping[str, object],
    field: str,
) -> MetadataDisplayValue:
    value = metadata.get(field, _MISSING)
    if value is _MISSING or value is None:
        return MetadataDisplayValue(kind="unknown", display="unknown")
    if isinstance(value, list):
        if not value:
            if field in EMPTY_MEANS_CONFIRMED_NONE_FIELDS:
                return MetadataDisplayValue(
                    kind="confirmed_none",
                    display="none (confirmed empty)",
                )
            return MetadataDisplayValue(
                kind="empty_collection",
                display="empty collection",
            )
        return MetadataDisplayValue(
            kind="value",
            display=", ".join(sorted({str(item) for item in value})),
        )
    if isinstance(value, bool):
        return MetadataDisplayValue(
            kind="value",
            display="true" if value else "false",
        )
    return MetadataDisplayValue(kind="value", display=str(value))


def numeric_field_summary(
    items: Sequence[CorpusItemRecord],
    *,
    field: str,
) -> NumericFieldSummary:
    values: list[int] = []
    for item in items:
        if field == "description_length":
            values.append(len(item.normalized_text))
            continue
        value = _metadata_object(item.metadata_json).get(field)
        if isinstance(value, int) and not isinstance(value, bool):
            values.append(value)
    values.sort()
    unknown_count = len(items) - len(values)
    return NumericFieldSummary(
        field=field,
        known_count=len(values),
        unknown_count=unknown_count,
        min=values[0] if values else None,
        p25=linear_percentile(values, 25.0),
        median=linear_percentile(values, 50.0),
        p75=linear_percentile(values, 75.0),
        max=values[-1] if values else None,
        mean=(sum(values) / len(values)) if values else None,
        buckets=_numeric_buckets(field, values),
    )


def linear_percentile(
    sorted_values: Sequence[float],
    q: float,
) -> float | None:
    if not 0.0 <= q <= 100.0:
        raise ValueError("percentile q must be between 0 and 100")
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    rank = (len(sorted_values) - 1) * (q / 100.0)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return float(sorted_values[lower])
    lower_value = sorted_values[lower]
    upper_value = sorted_values[upper]
    return float(lower_value + (rank - lower) * (upper_value - lower_value))


def _numeric_buckets(field: str, values: Sequence[int]) -> dict[str, int]:
    if field == "description_length":
        buckets = {"0-39": 0, "40-119": 0, "120-399": 0, "400+": 0}
        for value in values:
            if value < 40:
                buckets["0-39"] += 1
            elif value < 120:
                buckets["40-119"] += 1
            elif value < 400:
                buckets["120-399"] += 1
            else:
                buckets["400+"] += 1
        return buckets
    buckets = {"0": 0, "1-3": 0, "4-10": 0, "11+": 0}
    for value in values:
        if value == 0:
            buckets["0"] += 1
        elif value <= 3:
            buckets["1-3"] += 1
        elif value <= 10:
            buckets["4-10"] += 1
        else:
            buckets["11+"] += 1
    return buckets


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


def _metadata_values(value: object) -> tuple[str, ...]:
    if value is None:
        return ("null",)
    if isinstance(value, list):
        normalized = tuple(sorted({str(item) for item in value}))
        return normalized or ("none",)
    if isinstance(value, bool):
        return ("true" if value else "false",)
    return (str(value),)


def _representative_ids(
    *,
    member_ids: Sequence[str],
    medoid: str,
    coordinates: Mapping[str, tuple[float, ...]],
    membership_strengths: Mapping[str, float | None],
    limit: int = 5,
) -> tuple[str, ...]:
    if not member_ids:
        return ()
    ordered = sorted(
        (item_id for item_id in member_ids if item_id != medoid),
        key=lambda item_id: (
            -_strength(membership_strengths.get(item_id)),
            _distance_from(item_id, medoid, coordinates),
            item_id,
        ),
    )
    return tuple(([medoid] if medoid else []) + ordered)[:limit]


def _boundary_ids(
    *,
    member_ids: Sequence[str],
    medoid: str,
    coordinates: Mapping[str, tuple[float, ...]],
    membership_strengths: Mapping[str, float | None],
    limit: int = 5,
) -> tuple[str, ...]:
    ordered = sorted(
        member_ids,
        key=lambda item_id: (
            _strength(membership_strengths.get(item_id)),
            -_distance_from(item_id, medoid, coordinates),
            item_id,
        ),
    )
    return tuple(ordered[:limit])


def _strength(value: float | None) -> float:
    return value if value is not None else 1.0


def _distance_from(
    item_id: str,
    anchor_id: str,
    coordinates: Mapping[str, tuple[float, ...]],
) -> float:
    item = coordinates.get(item_id)
    anchor = coordinates.get(anchor_id)
    if item is None or anchor is None:
        return float("inf")
    return _euclidean(item, anchor)


def _flags_dict(flags: NoiseExplorerFlags) -> dict[str, bool]:
    return {
        "short_text": flags.short_text,
        "long_text": flags.long_text,
        "multiple_paragraphs": flags.multiple_paragraphs,
        "high_conjunction_count": flags.high_conjunction_count,
        "template_match": flags.template_match,
        "low_membership_strength": flags.low_membership_strength,
    }


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
    "EMPTY_MEANS_CONFIRMED_NONE_FIELDS",
    "MAX_PREVIEW_CHARACTERS",
    "CorrelationCell",
    "ItemPreview",
    "MetadataDisplayValue",
    "NoiseExplorerFlags",
    "NumericFieldSummary",
    "build_cluster_diagnostics",
    "build_item_preview",
    "cluster_size_percent",
    "compute_centroids",
    "correlation_rate",
    "linear_percentile",
    "metadata_display_value",
    "metadata_distribution",
    "nearest_cluster_ids",
    "noise_explorer_flags",
    "numeric_field_summary",
    "preview_digest",
    "truncate_preview",
]
