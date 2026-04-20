# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from .evaluator import (
    GateResult,
    GateState,
    MetricGateConfig,
    evaluate_gate_state,
    evaluate_gates,
    gate_state_from_project_metrics,
    metric_gate_reasons,
    metric_gate_reasons_for_state,
    summarize_metrics_diff,
)
from .reasons import (
    parse_metric_reason_entry,
    policy_context,
    print_gating_failure_block,
)

__all__ = [
    "GateResult",
    "GateState",
    "MetricGateConfig",
    "evaluate_gate_state",
    "evaluate_gates",
    "gate_state_from_project_metrics",
    "metric_gate_reasons",
    "metric_gate_reasons_for_state",
    "parse_metric_reason_entry",
    "policy_context",
    "print_gating_failure_block",
    "summarize_metrics_diff",
]
