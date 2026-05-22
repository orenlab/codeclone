# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Final, Literal

from ...contracts import DEFAULT_COVERAGE_MIN

StrictnessProfile = Literal["ci", "strict", "relaxed"]
PatchContractMode = Literal["budget", "verify"]

VALID_PATCH_CONTRACT_MODES: Final[frozenset[str]] = frozenset({"budget", "verify"})
VALID_STRICTNESS_PROFILES: Final[frozenset[str]] = frozenset(
    {"ci", "strict", "relaxed"}
)


class PatchContractStatus(str, Enum):
    ACCEPTED = "accepted"
    VIOLATED = "violated"
    UNVERIFIED = "unverified"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class PatchBudgets:
    clone_regression: int = 0
    dead_code_regression: bool = False
    dependency_cycle: bool = False
    coverage_hotspot: bool = False
    complexity_delta: int = -1
    coupling_delta: int = -1
    cohesion_delta: int = -1
    health_floor: int = -1
    typing_regression: bool = False
    docstring_regression: bool = False
    api_break: bool = False
    coverage_min: int = DEFAULT_COVERAGE_MIN

    def to_payload(self) -> dict[str, object]:
        return {
            "clone_regression": self.clone_regression,
            "dead_code_regression": self.dead_code_regression,
            "dependency_cycle": self.dependency_cycle,
            "coverage_hotspot": self.coverage_hotspot,
            "complexity_delta": self.complexity_delta,
            "coupling_delta": self.coupling_delta,
            "cohesion_delta": self.cohesion_delta,
            "health_floor": self.health_floor,
            "typing_regression": self.typing_regression,
            "docstring_regression": self.docstring_regression,
            "api_break": self.api_break,
            "coverage_min": self.coverage_min,
        }


STRICT_BUDGETS: Final[PatchBudgets] = PatchBudgets(
    clone_regression=0,
    dead_code_regression=True,
    dependency_cycle=True,
    coverage_hotspot=True,
    complexity_delta=10,
    coupling_delta=5,
    cohesion_delta=3,
    health_floor=70,
    typing_regression=True,
    docstring_regression=True,
    api_break=True,
    coverage_min=80,
)

RELAXED_BUDGETS: Final[PatchBudgets] = PatchBudgets(
    clone_regression=-1,
    dead_code_regression=False,
    dependency_cycle=False,
    coverage_hotspot=False,
    complexity_delta=-1,
    coupling_delta=-1,
    cohesion_delta=-1,
    health_floor=-1,
    typing_regression=False,
    docstring_regression=False,
    api_break=False,
    coverage_min=-1,
)


def budgets_from_request(
    *,
    coverage_min: int | None,
    complexity_threshold: int | None,
    coupling_threshold: int | None,
    cohesion_threshold: int | None,
) -> PatchBudgets:
    return PatchBudgets(
        clone_regression=0,
        complexity_delta=_none_to_unlimited(complexity_threshold),
        coupling_delta=_none_to_unlimited(coupling_threshold),
        cohesion_delta=_none_to_unlimited(cohesion_threshold),
        coverage_min=coverage_min if coverage_min is not None else DEFAULT_COVERAGE_MIN,
    )


def budgets_for_strictness(
    *,
    strictness: StrictnessProfile,
    coverage_min: int | None,
    complexity_threshold: int | None,
    coupling_threshold: int | None,
    cohesion_threshold: int | None,
) -> PatchBudgets:
    if strictness == "strict":
        return STRICT_BUDGETS
    if strictness == "relaxed":
        return RELAXED_BUDGETS
    return budgets_from_request(
        coverage_min=coverage_min,
        complexity_threshold=complexity_threshold,
        coupling_threshold=coupling_threshold,
        cohesion_threshold=cohesion_threshold,
    )


def detect_baseline_abuse(
    *,
    before_gate_would_fail: bool,
    after_gate_would_fail: bool,
    after_baseline_status: str,
    regressions: int,
    changed_files: int,
    intent_available: bool,
) -> dict[str, object]:
    baseline_updated = after_baseline_status == "updated"
    triggers: list[str] = []
    if baseline_updated and (regressions > 0 or changed_files > 0):
        triggers.append("baseline_changed_with_functional_code")
    if baseline_updated and regressions > 0:
        triggers.append("baseline_updated_while_regressions_present")
    if baseline_updated and not intent_available:
        triggers.append("baseline_updated_without_intent")
    if baseline_updated and before_gate_would_fail and not after_gate_would_fail:
        triggers.append("ci_greened_by_accepting_debt")
    return {
        "detected": bool(triggers),
        "triggers": triggers,
    }


def baseline_status(report_document: Mapping[str, object]) -> str:
    meta = _as_mapping(report_document.get("meta"))
    baseline = _as_mapping(meta.get("baseline"))
    return str(baseline.get("status", "")).strip()


def _none_to_unlimited(value: int | None) -> int:
    return value if value is not None else -1


def _as_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


__all__ = [
    "RELAXED_BUDGETS",
    "STRICT_BUDGETS",
    "VALID_PATCH_CONTRACT_MODES",
    "VALID_STRICTNESS_PROFILES",
    "PatchBudgets",
    "PatchContractMode",
    "PatchContractStatus",
    "StrictnessProfile",
    "baseline_status",
    "budgets_for_strictness",
    "detect_baseline_abuse",
]
