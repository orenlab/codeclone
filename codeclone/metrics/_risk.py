# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from typing import Literal

RiskLevel = Literal["low", "medium", "high"]

__all__ = ["RiskLevel", "threshold_risk"]


def threshold_risk(value: int, *, low_max: int, medium_max: int) -> RiskLevel:
    if value <= low_max:
        return "low"
    if value <= medium_max:
        return "medium"
    return "high"
