# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Remediation shape guidance for MCP get_remediation."""

from __future__ import annotations

from typing import Final

from ....domain.findings import (
    CATEGORY_CLONE,
    CATEGORY_COHESION,
    CATEGORY_COMPLEXITY,
    CATEGORY_COUPLING,
    CATEGORY_DEAD_CODE,
    CATEGORY_DEPENDENCY,
    CATEGORY_STRUCTURAL,
)

REMEDIATION_CLONE_TYPE1: Final = (
    "Keep one canonical implementation and route callers through it."
)
REMEDIATION_CLONE_TYPE2: Final = (
    "Extract shared implementation with explicit parameters."
)
REMEDIATION_CLONE_BLOCK: Final = (
    "Extract the repeated statement sequence into a helper."
)
REMEDIATION_STRUCTURAL: Final = (
    "Extract the repeated branch family into a named helper."
)
REMEDIATION_COMPLEXITY: Final = "Split the function into smaller named steps."
REMEDIATION_COUPLING: Final = (
    "Isolate responsibilities and invert unnecessary dependencies."
)
REMEDIATION_COHESION: Final = "Split the class by responsibility boundary."
REMEDIATION_DEAD_CODE: Final = (
    "Delete the unused symbol or document intentional reachability."
)
REMEDIATION_DEPENDENCY: Final = (
    "Break the cycle by moving shared abstractions to a lower layer."
)
REMEDIATION_DEFAULT: Final = (
    "Extract the repeated logic into a shared, named abstraction."
)


def safe_refactor_shape(
    *,
    category: str,
    clone_type: str,
    title: str,
) -> str:
    if category == CATEGORY_CLONE and clone_type == "Type-1":
        return REMEDIATION_CLONE_TYPE1
    if category == CATEGORY_CLONE and clone_type == "Type-2":
        return REMEDIATION_CLONE_TYPE2
    if category == CATEGORY_CLONE and "Block" in title:
        return REMEDIATION_CLONE_BLOCK
    if category == CATEGORY_STRUCTURAL:
        return REMEDIATION_STRUCTURAL
    if category == CATEGORY_COMPLEXITY:
        return REMEDIATION_COMPLEXITY
    if category == CATEGORY_COUPLING:
        return REMEDIATION_COUPLING
    if category == CATEGORY_COHESION:
        return REMEDIATION_COHESION
    if category == CATEGORY_DEAD_CODE:
        return REMEDIATION_DEAD_CODE
    if category == CATEGORY_DEPENDENCY:
        return REMEDIATION_DEPENDENCY
    return REMEDIATION_DEFAULT
