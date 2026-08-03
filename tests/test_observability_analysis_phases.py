# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

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
from codeclone.models import StageCounterSnapshot
from codeclone.observability.analysis_phases import (
    apply_pipeline_process_phase_counters,
    apply_stage_counters,
)
from tests._ast_metrics_helpers import module_registry_context


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

    apply_pipeline_process_phase_counters(span, phase_snapshot=snapshot)

    assert frozenset(span.counters) >= frozenset(
        (*PHASE_US_COUNTER_SUFFIXES, *PHASE_VOLUME_COUNTER_SUFFIXES)
    )
    assert span.counters["phase_parse_us"] == 1500
    assert span.counters["phase_unit_cfg_us"] == 2000
    assert span.counters["files_timed"] == 2
    assert span.counters["units_eligible"] == 5
    assert span.counters["blocks_emitted"] == 0


def test_apply_pipeline_process_phase_counters_emits_subphase_us() -> None:
    snapshot = PhaseSnapshot(
        totals=PhaseTotals(),
        volumes=(),
        subphase_us=(
            ("subphase_module_passes_adoption_us", 11),
            ("subphase_module_passes_security_us", 22),
        ),
    )
    span = _FakeSpan()

    apply_pipeline_process_phase_counters(span, phase_snapshot=snapshot)

    assert span.counters["subphase_module_passes_adoption_us"] == 11
    assert span.counters["subphase_module_passes_security_us"] == 22


def test_stage_counter_snapshot_merges_and_applies_once() -> None:
    left = StageCounterSnapshot((("files_analyzed", 2), ("failed_files", 1)))
    right = StageCounterSnapshot((("files_analyzed", 3), ("cache_hits", 4)))
    span = _FakeSpan()

    apply_stage_counters(span, left.merge(right))

    assert span.counters == {
        "cache_hits": 4,
        "failed_files": 1,
        "files_analyzed": 5,
    }


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

    identity, registry = module_registry_context(
        filepath="pkg/example.py",
        module_name="pkg.example",
    )
    units, blocks, segments, *_ = extract_units_and_stats_from_source(
        source=source,
        filepath="pkg/example.py",
        identity=identity,
        registry=registry,
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


def test_phase39l_pipeline_owns_each_observation_span_once() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "codeclone/core/pipeline.py").read_text(encoding="utf-8")

    assert source.count('span(name="observations.build")') == 1
    assert source.count('span(name="observations.lanes.build")') == 1


@pytest.mark.parametrize(
    ("module_path", "span_name"),
    [
        ("codeclone/baseline/container.py", "baseline.container.build"),
        ("codeclone/baseline/container.py", "baseline.container.read"),
        ("codeclone/baseline/container_trust.py", "baseline.container.trust"),
        ("codeclone/core/reporting.py", "report.build"),
        ("codeclone/report/gates/evaluator.py", "report.evaluate"),
        ("codeclone/core/reporting.py", "report.render"),
    ],
)
def test_each_instrumented_span_has_exactly_one_owner(
    module_path: str,
    span_name: str,
) -> None:
    """One module opens each span once; a second opener would double-count."""

    source = (Path(__file__).resolve().parents[1] / module_path).read_text(
        encoding="utf-8"
    )
    assert source.count(f'span(name="{span_name}")') == 1


def test_phase39n_publisher_owns_publication_span_once() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "codeclone/baseline/publish.py").read_text(encoding="utf-8")

    assert source.count('span(name="baseline.container.publish")') == 1
