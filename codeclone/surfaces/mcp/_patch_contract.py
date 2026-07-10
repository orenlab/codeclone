# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Compatibility re-exports for the surface-neutral patch budget owner."""

from __future__ import annotations

from ...budget.patch_contract import (
    RELAXED_BUDGETS,
    STRICT_BUDGETS,
    VALID_PATCH_CONTRACT_MODES,
    VALID_STRICTNESS_PROFILES,
    PatchBudgets,
    PatchContractMode,
    PatchContractStatus,
    StrictnessProfile,
    baseline_status,
    budgets_for_strictness,
    detect_baseline_abuse,
)
from ...budget.patch_contract import (
    budgets_from_request as budgets_from_request,
)

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
