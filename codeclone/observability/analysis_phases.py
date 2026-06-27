# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from ..analysis.phase_ledger import (
    PHASE_US_COUNTER_SUFFIXES,
    PHASE_VOLUME_COUNTER_SUFFIXES,
    PhaseSnapshot,
)
from .runtime import SpanHandle


def apply_pipeline_process_phase_counters(
    span: SpanHandle,
    *,
    phase_snapshot: PhaseSnapshot | None,
) -> None:
    if phase_snapshot is None:
        return

    phase_counters = phase_snapshot.totals.counter_map_us()
    for key in PHASE_US_COUNTER_SUFFIXES:
        span.set_counter(key, phase_counters.get(key, 0))

    volumes = phase_snapshot.volume_map()
    for key in PHASE_VOLUME_COUNTER_SUFFIXES:
        span.set_counter(key, volumes.get(key, 0))


__all__ = ["apply_pipeline_process_phase_counters"]
