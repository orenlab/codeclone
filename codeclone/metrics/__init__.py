# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from ._base import MetricAggregate, MetricFamily, MetricProjectContext
from .cohesion import cohesion_risk, compute_lcom4
from .complexity import cyclomatic_complexity, nesting_depth, risk_level
from .coupling import compute_cbo, coupling_risk
from .coverage_join import CoverageJoinParseError, build_coverage_join
from .dead_code import find_suppressed_unused, find_unused
from .dependencies import (
    build_dep_graph,
    build_import_graph,
    find_cycles,
    longest_chains,
    max_depth,
)
from .health import HealthInputs, compute_health
from .overloaded_modules import build_overloaded_modules_payload
from .registry import METRIC_FAMILIES, build_project_metrics, project_metrics_defaults

__all__ = [
    "METRIC_FAMILIES",
    "CoverageJoinParseError",
    "HealthInputs",
    "MetricAggregate",
    "MetricFamily",
    "MetricProjectContext",
    "build_coverage_join",
    "build_dep_graph",
    "build_import_graph",
    "build_overloaded_modules_payload",
    "build_project_metrics",
    "cohesion_risk",
    "compute_cbo",
    "compute_health",
    "compute_lcom4",
    "coupling_risk",
    "cyclomatic_complexity",
    "find_cycles",
    "find_suppressed_unused",
    "find_unused",
    "longest_chains",
    "max_depth",
    "nesting_depth",
    "project_metrics_defaults",
    "risk_level",
]
