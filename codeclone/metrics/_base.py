# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..models import (
        ClassMetrics,
        DeadCandidate,
        GroupItemLike,
        ModuleApiSurface,
        ModuleDep,
        ModuleDocstringCoverage,
        ModuleTypingCoverage,
        SecuritySurface,
    )

MetricResult = dict[str, object]


@dataclass(frozen=True, slots=True)
class MetricAggregate:
    project_fields: dict[str, object]
    artifacts: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class MetricProjectContext:
    units: tuple[GroupItemLike, ...]
    class_metrics: tuple[ClassMetrics, ...]
    module_deps: tuple[ModuleDep, ...]
    dead_candidates: tuple[DeadCandidate, ...]
    referenced_names: frozenset[str]
    referenced_qualnames: frozenset[str]
    security_surfaces: tuple[SecuritySurface, ...] = ()
    typing_modules: tuple[ModuleTypingCoverage, ...] = ()
    docstring_modules: tuple[ModuleDocstringCoverage, ...] = ()
    api_modules: tuple[ModuleApiSurface, ...] = ()
    files_found: int = 0
    files_analyzed_or_cached: int = 0
    function_clone_groups: int = 0
    block_clone_groups: int = 0
    skip_dependencies: bool = False
    skip_dead_code: bool = False
    memo: dict[str, MetricResult] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MetricFamily:
    name: str
    compute: Callable[[MetricProjectContext], MetricResult]
    aggregate: Callable[[list[MetricResult]], MetricAggregate]
    report_section: str
    baseline_key: str | None
    gate_keys: tuple[str, ...]
    skippable_flag: str | None
