# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ...core._types import FileProcessResult as ProcessingResult
from ...core._types import OutputPaths

ReportPathOrigin = Literal["default", "explicit"]


@dataclass(frozen=True, slots=True)
class ChangedCloneGate:
    changed_paths: tuple[str, ...]
    new_func: frozenset[str]
    new_block: frozenset[str]
    total_clone_groups: int
    findings_total: int
    findings_new: int
    findings_known: int


__all__ = [
    "ChangedCloneGate",
    "OutputPaths",
    "ProcessingResult",
    "ReportPathOrigin",
]
