# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from typing import Final

SEVERITY_CRITICAL: Final = "critical"
SEVERITY_WARNING: Final = "warning"
SEVERITY_INFO: Final = "info"

SEVERITY_RANK: Final[dict[str, int]] = {
    SEVERITY_CRITICAL: 3,
    SEVERITY_WARNING: 2,
    SEVERITY_INFO: 1,
}
SEVERITY_ORDER: Final[dict[str, int]] = {
    SEVERITY_CRITICAL: 0,
    SEVERITY_WARNING: 1,
    SEVERITY_INFO: 2,
}

EFFORT_EASY: Final = "easy"
EFFORT_MODERATE: Final = "moderate"
EFFORT_HARD: Final = "hard"

EFFORT_WEIGHT: Final[dict[str, int]] = {
    EFFORT_EASY: 1,
    EFFORT_MODERATE: 2,
    EFFORT_HARD: 3,
}

RISK_LOW: Final = "low"
RISK_MEDIUM: Final = "medium"
RISK_HIGH: Final = "high"

CONFIDENCE_LOW: Final = "low"
CONFIDENCE_MEDIUM: Final = "medium"
CONFIDENCE_HIGH: Final = "high"

__all__ = [
    "CONFIDENCE_HIGH",
    "CONFIDENCE_LOW",
    "CONFIDENCE_MEDIUM",
    "EFFORT_EASY",
    "EFFORT_HARD",
    "EFFORT_MODERATE",
    "EFFORT_WEIGHT",
    "RISK_HIGH",
    "RISK_LOW",
    "RISK_MEDIUM",
    "SEVERITY_CRITICAL",
    "SEVERITY_INFO",
    "SEVERITY_ORDER",
    "SEVERITY_RANK",
    "SEVERITY_WARNING",
]
