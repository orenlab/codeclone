# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import fields

import pytest

from codeclone.analysis import phase_ledger as phase_mod
from codeclone.analysis.phase_ledger import (
    INERT_PHASE_LEDGER,
    PHASE_US_COUNTER_SUFFIXES,
    PHASE_VOLUME_COUNTER_SUFFIXES,
    AnalysisPhaseKey,
    AnalysisVolumeKey,
    PhaseLedger,
    PhaseSnapshot,
    PhaseTotals,
)


def test_phase_enum_derived_counter_suffixes() -> None:
    assert (
        tuple(f"phase_{key.value}_us" for key in AnalysisPhaseKey)
        == PHASE_US_COUNTER_SUFFIXES
    )
    assert (
        tuple(key.value for key in AnalysisVolumeKey) == PHASE_VOLUME_COUNTER_SUFFIXES
    )
    assert tuple(field.name for field in fields(PhaseTotals)) == tuple(
        f"{key.value}_ns" for key in AnalysisPhaseKey
    )


def test_phase_ledger_inert_does_not_call_perf_counter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def _forbidden() -> int:
        nonlocal calls
        calls += 1
        raise AssertionError("inert phase must not read the clock")

    monkeypatch.setattr(phase_mod, "perf_counter_ns", _forbidden)
    with INERT_PHASE_LEDGER.phase(AnalysisPhaseKey.PARSE):
        pass
    INERT_PHASE_LEDGER.add_volume(AnalysisVolumeKey.UNITS_SEEN)
    assert calls == 0


def test_phase_ledger_records_elapsed_and_volumes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticks = iter((1_000, 2_501, 10_000, 13_499))
    monkeypatch.setattr(phase_mod, "perf_counter_ns", lambda: next(ticks))

    ledger = PhaseLedger(active=True)
    with ledger.phase(AnalysisPhaseKey.PARSE):
        pass
    with ledger.phase(AnalysisPhaseKey.UNIT_CFG):
        pass
    ledger.add_volume(AnalysisVolumeKey.UNITS_SEEN)
    ledger.add_volume(AnalysisVolumeKey.UNITS_SEEN, 2)

    snapshot = ledger.snapshot()
    assert snapshot.totals.counter_map_us()["phase_parse_us"] == 1
    assert snapshot.totals.counter_map_us()["phase_unit_cfg_us"] == 3
    assert snapshot.volume_map() == {"units_seen": 3}


def test_phase_snapshot_merge_is_deterministic() -> None:
    left = PhaseSnapshot(
        totals=PhaseTotals(parse_ns=1_000),
        volumes=(("units_seen", 1),),
    )
    right = PhaseSnapshot(
        totals=PhaseTotals(parse_ns=2_000, unit_blocks_ns=3_000),
        volumes=(("files_timed", 2), ("units_seen", 3)),
    )

    merged = left.merge(right)
    assert merged.totals.counter_map_us()["phase_parse_us"] == 3
    assert merged.totals.counter_map_us()["phase_unit_blocks_us"] == 3
    assert merged.volumes == (("files_timed", 2), ("units_seen", 4))


def test_phase_ledger_rejects_raw_string_keys() -> None:
    ledger = PhaseLedger(active=True)
    with pytest.raises(TypeError):
        ledger.phase("parse")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        ledger.add_volume("files_timed")  # type: ignore[arg-type]
