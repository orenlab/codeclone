# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from ..contracts import population_carries_score
from ..models import DependencyCycleFact, MetricsSnapshot, ProjectMetrics


def _cycle_facts(
    project_metrics: ProjectMetrics,
) -> tuple[DependencyCycleFact, ...]:
    """Pair each cycle with its kind for the snapshot the diff compares.

    Details are aligned with cycles by index at their producer. When they are
    absent or misaligned the classification simply was not recorded, and every
    cycle takes the conservative ``import_cycle`` reading — the same fallback
    the suggestion and finding projections apply, so no surface quietly
    downgrades a cycle just because the kind went missing.
    """

    details = project_metrics.dependency_cycle_details
    cycles = project_metrics.dependency_cycles
    aligned = len(details) == len(cycles)
    return tuple(
        sorted(
            {
                DependencyCycleFact(
                    modules=tuple(cycle),
                    kind=details[index].kind if aligned else "import_cycle",
                )
                for index, cycle in enumerate(cycles)
            },
            key=lambda fact: (fact.modules, fact.kind),
        )
    )


def snapshot_from_project_metrics(project_metrics: ProjectMetrics) -> MetricsSnapshot:
    # The current half of the refusal wave 7 taught the baseline half to
    # carry (``metrics_baseline._snapshot``): ``compute_health`` withholds the
    # number over a population that carries none, and its zero total is a
    # placeholder, not a measurement. Converting it with ``int()`` here turned
    # the refusal back into a measured zero, so an empty or unread current run
    # against a good baseline published ``health_delta = 0 - good`` -- the
    # whole stored score as a regression no code caused (`B8`, `G4`). The
    # population owner answers the yes/no; this module adds no second one.
    health_measured = population_carries_score(project_metrics.health.population)
    return MetricsSnapshot(
        max_complexity=int(project_metrics.complexity_max),
        high_risk_functions=tuple(sorted(set(project_metrics.high_risk_functions))),
        max_coupling=int(project_metrics.coupling_max),
        high_coupling_classes=tuple(sorted(set(project_metrics.high_risk_classes))),
        max_cohesion=int(project_metrics.cohesion_max),
        low_cohesion_classes=tuple(sorted(set(project_metrics.low_cohesion_classes))),
        dependency_cycles=_cycle_facts(project_metrics),
        dependency_max_depth=int(project_metrics.dependency_max_depth),
        dead_code_items=tuple(
            sorted({item.qualname for item in project_metrics.dead_code})
        ),
        health_score=(int(project_metrics.health.total) if health_measured else None),
        health_grade=project_metrics.health.grade if health_measured else None,
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
