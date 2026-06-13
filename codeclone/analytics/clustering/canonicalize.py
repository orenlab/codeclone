# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import math
from collections.abc import Sequence

from ..corpus.keys import membership_digest
from .models import NOISE_LABEL, ClusterPartition


def canonicalize_partitions(
    partitions: Sequence[ClusterPartition],
    *,
    coordinates: dict[str, tuple[float, ...]],
) -> tuple[ClusterPartition, ...]:
    """Assign display order: size desc, medoid asc, membership_digest asc."""
    non_noise = [part for part in partitions if part.cluster_label != NOISE_LABEL]
    noise = [part for part in partitions if part.cluster_label == NOISE_LABEL]
    non_noise.sort(
        key=lambda part: (
            -len(part.snapshot_item_ids),
            medoid_item_id(
                member_ids=part.snapshot_item_ids,
                coordinates=coordinates,
            ),
            part.membership_digest,
        )
    )
    canonical: list[ClusterPartition] = []
    for _display_id, part in enumerate(non_noise, start=1):
        canonical.append(
            ClusterPartition(
                cluster_label=part.cluster_label,
                snapshot_item_ids=part.snapshot_item_ids,
                membership_digest=part.membership_digest,
            )
        )
    canonical.extend(noise)
    return tuple(canonical)


def display_cluster_id_map(
    partitions: Sequence[ClusterPartition],
) -> dict[int, int | None]:
    mapping: dict[int, int | None] = {}
    display = 1
    for part in partitions:
        if part.cluster_label == NOISE_LABEL:
            mapping[part.cluster_label] = None
            continue
        mapping[part.cluster_label] = display
        display += 1
    return mapping


def medoid_item_id(
    *,
    member_ids: Sequence[str],
    coordinates: dict[str, tuple[float, ...]],
) -> str:
    if not member_ids:
        return ""
    if len(member_ids) == 1:
        return member_ids[0]

    def average_distance(item_id: str) -> float:
        anchor = coordinates.get(item_id)
        if anchor is None:
            return float("inf")
        total = 0.0
        count = 0
        for other_id in member_ids:
            if other_id == item_id:
                continue
            other = coordinates.get(other_id)
            if other is None:
                continue
            total += _euclidean(anchor, other)
            count += 1
        return total / count if count else float("inf")

    return min(member_ids, key=lambda item_id: (average_distance(item_id), item_id))


def _euclidean(left: Sequence[float], right: Sequence[float]) -> float:
    return math.sqrt(float(sum((a - b) ** 2 for a, b in zip(left, right, strict=True))))


def partition_membership_map(
    partitions: Sequence[ClusterPartition],
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for part in partitions:
        digest = membership_digest(list(part.snapshot_item_ids))
        for item_id in part.snapshot_item_ids:
            mapping[item_id] = digest
    return mapping


__all__ = [
    "canonicalize_partitions",
    "display_cluster_id_map",
    "medoid_item_id",
    "partition_membership_map",
]
