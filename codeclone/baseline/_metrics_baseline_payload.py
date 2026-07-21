# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from ..models import MetricsSnapshot, ProjectMetrics


def snapshot_from_project_metrics(project_metrics: ProjectMetrics) -> MetricsSnapshot:
    return MetricsSnapshot(
        max_complexity=int(project_metrics.complexity_max),
        high_risk_functions=tuple(sorted(set(project_metrics.high_risk_functions))),
        max_coupling=int(project_metrics.coupling_max),
        high_coupling_classes=tuple(sorted(set(project_metrics.high_risk_classes))),
        max_cohesion=int(project_metrics.cohesion_max),
        low_cohesion_classes=tuple(sorted(set(project_metrics.low_cohesion_classes))),
        dependency_cycles=tuple(
            sorted({tuple(cycle) for cycle in project_metrics.dependency_cycles})
        ),
        dependency_max_depth=int(project_metrics.dependency_max_depth),
        dead_code_items=tuple(
            sorted({item.qualname for item in project_metrics.dead_code})
        ),
        health_score=int(project_metrics.health.total),
        health_grade=project_metrics.health.grade,
        typing_param_permille=_permille(
            project_metrics.typing_param_annotated,
            project_metrics.typing_param_total,
        ),
        typing_return_permille=_permille(
            project_metrics.typing_return_annotated,
            project_metrics.typing_return_total,
        ),
        docstring_permille=_permille(
            project_metrics.docstring_public_documented,
            project_metrics.docstring_public_total,
        ),
        typing_any_count=int(project_metrics.typing_any_count),
    )


def _permille(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        return 0
    return round((1000.0 * float(numerator)) / float(denominator))


__all__ = [
    "snapshot_from_project_metrics",
]
