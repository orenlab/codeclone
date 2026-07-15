# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..models import MetricProjectContext

MetricResult = dict[str, object]


@dataclass(frozen=True, slots=True)
class MetricAggregate:
    project_fields: dict[str, object]
    artifacts: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MetricFamily:
    name: str
    compute: Callable[[MetricProjectContext], MetricResult]
    aggregate: Callable[[list[MetricResult]], MetricAggregate]
    report_section: str
    baseline_key: str | None
    gate_keys: tuple[str, ...]
    skippable_flag: str | None
