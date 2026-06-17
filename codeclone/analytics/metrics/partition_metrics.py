# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..clustering.models import NOISE_LABEL
from ..contracts import ClusterAssignmentRecord, ClusterSummaryRecord


@dataclass(frozen=True, slots=True)
class RunPartitionMetrics:
    total_items: int
    cluster_count: int
    noise_count: int
    non_noise_count: int
    noise_ratio: float
    dominant_cluster_ratio: float
    dominant_assigned_ratio: float | None
    dominant_cluster_label: int | None
    cluster_size_distribution: tuple[int, ...]
    cluster_size_histogram: dict[str, int]


def compute_run_partition_metrics(
    assignments: Sequence[ClusterAssignmentRecord],
    summaries: Sequence[ClusterSummaryRecord],
) -> RunPartitionMetrics:
    total_items = len(assignments)
    noise_count = sum(
        assignment.cluster_label == NOISE_LABEL for assignment in assignments
    )
    non_noise_summaries = [
        summary for summary in summaries if summary.cluster_label != NOISE_LABEL
    ]
    ordered = sorted(
        non_noise_summaries,
        key=lambda summary: (
            -summary.size,
            summary.membership_digest,
            summary.cluster_label,
        ),
    )
    sizes = tuple(summary.size for summary in ordered)
    largest = ordered[0] if ordered else None
    non_noise_count = total_items - noise_count
    return RunPartitionMetrics(
        total_items=total_items,
        cluster_count=len(non_noise_summaries),
        noise_count=noise_count,
        non_noise_count=non_noise_count,
        noise_ratio=noise_count / total_items if total_items else 0.0,
        dominant_cluster_ratio=(
            largest.size / total_items if largest is not None and total_items else 0.0
        ),
        dominant_assigned_ratio=(
            largest.size / non_noise_count
            if largest is not None and non_noise_count
            else None
        ),
        dominant_cluster_label=largest.cluster_label if largest is not None else None,
        cluster_size_distribution=sizes,
        cluster_size_histogram=_cluster_size_histogram(sizes),
    )


def _cluster_size_histogram(sizes: Sequence[int]) -> dict[str, int]:
    result = {"1-3": 0, "4-7": 0, "8-15": 0, "16-31": 0, "32-63": 0, "64+": 0}
    for size in sizes:
        if size <= 3:
            result["1-3"] += 1
        elif size <= 7:
            result["4-7"] += 1
        elif size <= 15:
            result["8-15"] += 1
        elif size <= 31:
            result["16-31"] += 1
        elif size <= 63:
            result["32-63"] += 1
        else:
            result["64+"] += 1
    return result


__all__ = ["RunPartitionMetrics", "compute_run_partition_metrics"]
