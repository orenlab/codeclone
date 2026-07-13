# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from typing import Protocol

from ..analysis.phase_ledger import (
    PHASE_US_COUNTER_SUFFIXES,
    PHASE_VOLUME_COUNTER_SUFFIXES,
    PhaseSnapshot,
)
from ..models import StageCounterSnapshot


class StageCounterSink(Protocol):
    def set_counter(self, key: str, value: int) -> None: ...


def apply_stage_counters(
    span: StageCounterSink,
    snapshot: StageCounterSnapshot,
) -> None:
    for key, value in snapshot.counters:
        span.set_counter(key, value)


def _analysis_phase_snapshot(phase_snapshot: PhaseSnapshot) -> StageCounterSnapshot:
    counters = phase_snapshot.totals.counter_map_us()
    volumes = phase_snapshot.volume_map()
    rows = tuple(
        (key, counters.get(key, 0)) for key in PHASE_US_COUNTER_SUFFIXES
    ) + tuple((key, volumes.get(key, 0)) for key in PHASE_VOLUME_COUNTER_SUFFIXES)
    return StageCounterSnapshot(rows + phase_snapshot.subphase_us)


def apply_pipeline_process_phase_counters(
    span: StageCounterSink,
    *,
    phase_snapshot: PhaseSnapshot | None,
) -> None:
    if phase_snapshot is None:
        return

    apply_stage_counters(span, _analysis_phase_snapshot(phase_snapshot))


__all__ = [
    "StageCounterSink",
    "apply_pipeline_process_phase_counters",
    "apply_stage_counters",
]
