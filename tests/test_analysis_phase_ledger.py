# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import fields

import pytest

from codeclone.analysis import phase_ledger as phase_mod
from codeclone.analysis.normalizer import NormalizationConfig
from codeclone.analysis.phase_ledger import (
    INERT_PHASE_LEDGER,
    MODULE_PASSES_SUBPHASE_US_COUNTER_SUFFIXES,
    PHASE_US_COUNTER_SUFFIXES,
    PHASE_VOLUME_COUNTER_SUFFIXES,
    AnalysisPhaseKey,
    AnalysisVolumeKey,
    PhaseLedger,
    PhaseSnapshot,
    PhaseTotals,
)
from codeclone.analysis.units import extract_units_and_stats_from_source
from codeclone.observability.vocabulary import COUNTER_KEYS
from tests._ast_metrics_helpers import module_registry_context


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


def test_phase_ledger_records_subphase_us_only_when_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticks = iter((1_000, 4_000))
    monkeypatch.setattr(phase_mod, "perf_counter_ns", lambda: next(ticks))

    inert = PhaseLedger(active=False)
    assert inert.run_subphase_us("subphase_module_passes_adoption_us", lambda: 7) == 7
    assert inert.snapshot().subphase_us == ()

    ledger = PhaseLedger(active=True)
    assert (
        ledger.run_subphase_us(
            "subphase_module_passes_adoption_us",
            lambda: "ok",
        )
        == "ok"
    )
    assert ledger.snapshot().subphase_us == (("subphase_module_passes_adoption_us", 3),)


def test_phase_snapshot_merge_merges_subphase_us() -> None:
    left = PhaseSnapshot(
        totals=PhaseTotals(),
        volumes=(),
        subphase_us=(("subphase_module_passes_adoption_us", 10),),
    )
    right = PhaseSnapshot(
        totals=PhaseTotals(),
        volumes=(),
        subphase_us=(
            ("subphase_module_passes_adoption_us", 5),
            ("subphase_module_passes_security_us", 7),
        ),
    )
    merged = left.merge(right)
    assert merged.subphase_us == (
        ("subphase_module_passes_adoption_us", 15),
        ("subphase_module_passes_security_us", 7),
    )


def test_phase_ledger_rejects_raw_string_keys() -> None:
    ledger = PhaseLedger(active=True)
    with pytest.raises(TypeError):
        ledger.phase("parse")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        ledger.add_volume("files_timed")  # type: ignore[arg-type]


def test_module_bindings_work_is_attributed_to_a_phase() -> None:
    """Scope-graph construction belongs to the ledger, not to its blind spot.

    `_module_bindings` is a full-tree recursion run once per file. While it sat
    outside every `phase()` block it never reached the denominator, so every
    phase share was reported against a worker time that excluded it.
    """

    source = (
        "import os\n"
        "import sys\n"
        "from collections import OrderedDict\n"
        "from . import sibling\n"
        "\n"
        "\n"
        "def outer(value: int) -> int:\n"
        "    def inner(inner_value: int) -> int:\n"
        "        return inner_value + len(os.sep) + len(sys.platform)\n"
        "\n"
        "    return inner(value) + len(OrderedDict()) + len(dir(sibling))\n"
    )
    identity, registry = module_registry_context(
        filepath="pkg/mod.py",
        module_name="pkg.mod",
    )
    ledger = PhaseLedger(active=True)

    extract_units_and_stats_from_source(
        source=source,
        filepath="pkg/mod.py",
        identity=identity,
        registry=registry,
        cfg=NormalizationConfig(),
        min_loc=1,
        min_stmt=1,
        phase_ledger=ledger,
    )

    totals = ledger.snapshot().totals
    assert totals.module_bindings_ns > 0
    assert "phase_module_bindings_us" in PHASE_US_COUNTER_SUFFIXES


def test_every_phase_counter_is_in_the_reviewed_vocabulary() -> None:
    """A new phase key is inert until the observer vocabulary admits it.

    The ledger derives its counter names from `AnalysisPhaseKey`, but the
    observer validates every key against a reviewed allowlist and raises
    `ObservabilityVocabularyError` on an unknown one. Adding a phase without
    registering its counter therefore passes the suite and fails only on a real
    profiled run, which is exactly where the measurement was needed.
    """

    derived = set(PHASE_US_COUNTER_SUFFIXES) | set(
        MODULE_PASSES_SUBPHASE_US_COUNTER_SUFFIXES
    )
    missing = sorted(derived - COUNTER_KEYS)
    assert not missing, f"phase counters absent from the reviewed vocabulary: {missing}"
