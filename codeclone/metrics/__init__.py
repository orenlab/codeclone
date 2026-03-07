"""Public metrics API."""

from __future__ import annotations

from .cohesion import cohesion_risk, compute_lcom4
from .complexity import cyclomatic_complexity, nesting_depth, risk_level
from .coupling import compute_cbo, coupling_risk
from .dead_code import find_unused
from .dependencies import (
    build_dep_graph,
    build_import_graph,
    find_cycles,
    longest_chains,
    max_depth,
)
from .health import HealthInputs, compute_health

__all__ = [
    "HealthInputs",
    "build_dep_graph",
    "build_import_graph",
    "cohesion_risk",
    "compute_cbo",
    "compute_health",
    "compute_lcom4",
    "coupling_risk",
    "cyclomatic_complexity",
    "find_cycles",
    "find_unused",
    "longest_chains",
    "max_depth",
    "nesting_depth",
    "risk_level",
]
