# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import replace

from codeclone.analysis.normalizer import NormalizationConfig
from codeclone.analysis.phase_ledger import (
    PHASE_US_COUNTER_SUFFIXES,
    PHASE_VOLUME_COUNTER_SUFFIXES,
    AnalysisVolumeKey,
    PhaseLedger,
    PhaseSnapshot,
    PhaseTotals,
)
from codeclone.analysis.units import extract_units_and_stats_from_source
from codeclone.core._types import ProcessingResult
from codeclone.observability.analysis_phases import (
    apply_pipeline_process_phase_counters,
)


class _FakeSpan:
    def __init__(self) -> None:
        self.counters: dict[str, int] = {}

    def set_counter(self, key: str, value: int) -> None:
        self.counters[key] = value


def _processing_result(snapshot: PhaseSnapshot | None = None) -> ProcessingResult:
    return ProcessingResult(
        units=(),
        blocks=(),
        segments=(),
        class_metrics=(),
        module_deps=(),
        dead_candidates=(),
        referenced_names=frozenset(),
        files_analyzed=1,
        files_skipped=0,
        analyzed_lines=0,
        analyzed_functions=0,
        analyzed_methods=0,
        analyzed_classes=0,
        failed_files=(),
        source_read_failures=(),
        phase_snapshot=snapshot,
    )


def test_apply_pipeline_process_phase_counters_closed_key_set() -> None:
    snapshot = PhaseSnapshot(
        totals=PhaseTotals(parse_ns=1_500_000, unit_cfg_ns=2_000_000),
        volumes=(
            (AnalysisVolumeKey.FILES_TIMED.value, 2),
            (AnalysisVolumeKey.UNITS_ELIGIBLE.value, 5),
        ),
    )
    span = _FakeSpan()

    apply_pipeline_process_phase_counters(span, phase_snapshot=snapshot)  # type: ignore[arg-type]

    assert frozenset(span.counters) == frozenset(
        (*PHASE_US_COUNTER_SUFFIXES, *PHASE_VOLUME_COUNTER_SUFFIXES)
    )
    assert span.counters["phase_parse_us"] == 1500
    assert span.counters["phase_unit_cfg_us"] == 2000
    assert span.counters["files_timed"] == 2
    assert span.counters["units_eligible"] == 5
    assert span.counters["blocks_emitted"] == 0


def test_extract_units_records_phase_snapshot_data() -> None:
    ledger = PhaseLedger(active=True)
    source = """
def example(value):
    total = value + 1
    total += 1
    total += 2
    if total > 2:
        total += 3
    else:
        total -= 4
    total += 5
    return total
"""

    units, blocks, segments, *_ = extract_units_and_stats_from_source(
        source=source,
        filepath="pkg/example.py",
        module_name="pkg.example",
        cfg=NormalizationConfig(),
        min_loc=3,
        min_stmt=2,
        block_min_loc=3,
        block_min_stmt=2,
        segment_min_loc=3,
        segment_min_stmt=2,
        phase_ledger=ledger,
    )

    snapshot = ledger.snapshot()
    counters = snapshot.totals.counter_map_us()
    volumes = snapshot.volume_map()
    assert units
    assert blocks
    assert segments
    assert counters["phase_parse_us"] >= 0
    assert volumes["units_seen"] == 1
    assert volumes["units_eligible"] == 1
    assert volumes["units_fingerprinted"] == 1
    assert volumes["blocks_emitted"] == len(blocks)
    assert volumes["segments_emitted"] == len(segments)


def test_core_result_equality_ignores_phase_snapshot() -> None:
    base = _processing_result()
    snapshot = PhaseSnapshot(totals=PhaseTotals(parse_ns=1_000), volumes=())
    assert base == replace(base, phase_snapshot=snapshot)
