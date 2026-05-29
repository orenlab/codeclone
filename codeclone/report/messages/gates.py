# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Metric gate reason prefix strings (generation and parsing)."""

from __future__ import annotations

from typing import Final

GATE_REASON_NEW_HIGH_RISK_FUNCTIONS: Final = (
    "New high-risk functions vs metrics baseline: "
)
GATE_REASON_NEW_HIGH_COUPLING: Final = "New high-coupling classes vs metrics baseline: "
GATE_REASON_NEW_CYCLES: Final = "New dependency cycles vs metrics baseline: "
GATE_REASON_NEW_DEAD_CODE: Final = "New dead code items vs metrics baseline: "
GATE_REASON_HEALTH_REGRESSION: Final = (
    "Health score regressed vs metrics baseline: delta="
)
GATE_REASON_TYPING_REGRESSION: Final = "Typing coverage regressed vs metrics baseline: "
GATE_REASON_DOCSTRING_REGRESSION: Final = (
    "Docstring coverage regressed vs metrics baseline: delta="
)
GATE_REASON_API_BREAKING: Final = "Public API breaking changes vs metrics baseline: "
GATE_REASON_COVERAGE_HOTSPOTS: Final = "Coverage hotspots detected: "
GATE_REASON_CYCLES_DETECTED: Final = "Dependency cycles detected: "
GATE_REASON_DEAD_CODE_DETECTED: Final = "Dead code detected (high confidence): "
GATE_REASON_COMPLEXITY_THRESHOLD: Final = "Complexity threshold exceeded: "
GATE_REASON_COUPLING_THRESHOLD: Final = "Coupling threshold exceeded: "
GATE_REASON_COHESION_THRESHOLD: Final = "Cohesion threshold exceeded: "
GATE_REASON_HEALTH_THRESHOLD: Final = "Health score below threshold: "
GATE_REASON_TYPING_THRESHOLD: Final = "Typing coverage below threshold: "
GATE_REASON_DOCSTRING_THRESHOLD: Final = "Docstring coverage below threshold: "

GATE_SUFFIX_CYCLES: Final = " cycle(s)"
GATE_SUFFIX_ITEMS: Final = " item(s)"

GATE_FAILURE_HEADER: Final = "GATING FAILURE [{code}]"
