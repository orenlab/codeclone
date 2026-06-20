# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum
from time import perf_counter_ns
from types import TracebackType
from typing import Literal


class AnalysisPhaseKey(str, Enum):
    PARSE = "parse"
    QUALNAME = "qualname"
    MODULE_WALK = "module_walk"
    RELATIONSHIP = "relationship"
    SUPPRESSIONS = "suppressions"
    UNIT_CFG = "unit_cfg"
    UNIT_NORMALIZE_CFG = "unit_normalize_cfg"
    UNIT_STRUCTURAL = "unit_structural"
    UNIT_NORMALIZE_STMT = "unit_normalize_stmt"
    UNIT_BLOCKS = "unit_blocks"
    UNIT_SEGMENTS = "unit_segments"
    CLASS_METRICS = "class_metrics"
    DEAD_CODE = "dead_code"
    MODULE_PASSES = "module_passes"


class AnalysisVolumeKey(str, Enum):
    FILES_TIMED = "files_timed"
    UNITS_SEEN = "units_seen"
    UNITS_ELIGIBLE = "units_eligible"
    UNITS_FINGERPRINTED = "units_fingerprinted"
    BLOCKS_EMITTED = "blocks_emitted"
    SEGMENTS_EMITTED = "segments_emitted"


PHASE_US_COUNTER_SUFFIXES: tuple[str, ...] = tuple(
    f"phase_{key.value}_us" for key in AnalysisPhaseKey
)
PHASE_VOLUME_COUNTER_SUFFIXES: tuple[str, ...] = tuple(
    key.value for key in AnalysisVolumeKey
)


@dataclass(frozen=True, slots=True)
class PhaseTotals:
    parse_ns: int = 0
    qualname_ns: int = 0
    module_walk_ns: int = 0
    relationship_ns: int = 0
    suppressions_ns: int = 0
    unit_cfg_ns: int = 0
    unit_normalize_cfg_ns: int = 0
    unit_structural_ns: int = 0
    unit_normalize_stmt_ns: int = 0
    unit_blocks_ns: int = 0
    unit_segments_ns: int = 0
    class_metrics_ns: int = 0
    dead_code_ns: int = 0
    module_passes_ns: int = 0

    def merge(self, other: PhaseTotals) -> PhaseTotals:
        return PhaseTotals(
            **{
                field.name: getattr(self, field.name) + getattr(other, field.name)
                for field in fields(self)
            }
        )

    def counter_map_us(self) -> dict[str, int]:
        return {
            f"phase_{key.value}_us": getattr(self, f"{key.value}_ns") // 1000
            for key in AnalysisPhaseKey
        }


@dataclass(frozen=True, slots=True)
class PhaseSnapshot:
    totals: PhaseTotals
    volumes: tuple[tuple[str, int], ...]

    @classmethod
    def empty(cls) -> PhaseSnapshot:
        return cls(totals=PhaseTotals(), volumes=())

    def merge(self, other: PhaseSnapshot) -> PhaseSnapshot:
        merged_volumes = self.volume_map()
        for key, value in other.volumes:
            merged_volumes[key] = merged_volumes.get(key, 0) + value
        return PhaseSnapshot(
            totals=self.totals.merge(other.totals),
            volumes=tuple(sorted(merged_volumes.items())),
        )

    def volume_map(self) -> dict[str, int]:
        return dict(self.volumes)


class _InertPhaseContext:
    __slots__ = ()

    def __enter__(self) -> None:
        return None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> Literal[False]:
        return False


_INERT_PHASE_CONTEXT = _InertPhaseContext()


class _ActivePhaseContext:
    __slots__ = ("_key", "_ledger", "_started_ns")

    def __init__(self, ledger: PhaseLedger, key: AnalysisPhaseKey) -> None:
        self._ledger = ledger
        self._key = key
        self._started_ns: int | None = None

    def __enter__(self) -> None:
        self._started_ns = perf_counter_ns()
        return None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> Literal[False]:
        started = self._started_ns
        if started is not None:
            self._ledger._add_elapsed(self._key, perf_counter_ns() - started)
        return False


class PhaseLedger:
    __slots__ = ("_active", "_totals", "_volumes")

    def __init__(self, *, active: bool) -> None:
        self._active = active
        self._totals: dict[AnalysisPhaseKey, int] = {}
        self._volumes: dict[AnalysisVolumeKey, int] = {}

    @property
    def active(self) -> bool:
        return self._active

    def phase(self, key: AnalysisPhaseKey) -> _InertPhaseContext | _ActivePhaseContext:
        if not isinstance(key, AnalysisPhaseKey):
            raise TypeError("phase key must be an AnalysisPhaseKey")
        if not self._active:
            return _INERT_PHASE_CONTEXT
        return _ActivePhaseContext(self, key)

    def add_volume(self, key: AnalysisVolumeKey, value: int = 1) -> None:
        if not isinstance(key, AnalysisVolumeKey):
            raise TypeError("volume key must be an AnalysisVolumeKey")
        if not self._active:
            return
        self._volumes[key] = self._volumes.get(key, 0) + value

    def snapshot(self) -> PhaseSnapshot:
        totals = PhaseTotals(
            **{f"{key.value}_ns": self._totals.get(key, 0) for key in AnalysisPhaseKey}
        )
        return PhaseSnapshot(
            totals=totals,
            volumes=tuple(
                sorted((key.value, value) for key, value in self._volumes.items())
            ),
        )

    def _add_elapsed(self, key: AnalysisPhaseKey, elapsed_ns: int) -> None:
        self._totals[key] = self._totals.get(key, 0) + elapsed_ns


INERT_PHASE_LEDGER = PhaseLedger(active=False)


__all__ = [
    "INERT_PHASE_LEDGER",
    "PHASE_US_COUNTER_SUFFIXES",
    "PHASE_VOLUME_COUNTER_SUFFIXES",
    "AnalysisPhaseKey",
    "AnalysisVolumeKey",
    "PhaseLedger",
    "PhaseSnapshot",
    "PhaseTotals",
]
