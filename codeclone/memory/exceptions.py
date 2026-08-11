# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations


class MemoryError(RuntimeError):
    """Base error for engineering memory operations."""


class MemorySchemaError(MemoryError):
    """Raised for unsupported or corrupt engineering memory database schemas."""


class MemoryContractError(MemoryError):
    """Raised when memory record or config contracts are violated."""


class MemoryInitLockError(MemoryError):
    """Raised when the memory init advisory lock cannot be acquired."""


class MemoryCapacityError(MemoryContractError):
    """Raised when memory store capacity limits are exceeded."""


class UnfitAnalysisRunError(MemoryContractError):
    """Raised when a run is not fit to be a source of durable memory.

    Ingest refuses rather than degrades here for one case only: a run that
    observed none of the population it found. Its extractors still speak —
    module roles come from the *found* file registry — so accepting would
    store "this module was analyzed" about files nobody opened, at the same
    ``active``/``supported`` grade as a real measurement. The message names
    the population state; a caller that needs the structured facts re-reads
    them from the report with ``read_run_fitness`` rather than receiving a
    second copy on the exception.
    """


class MemorySemanticUnavailableError(MemoryError):
    """Raised when a semantic provider/backend is required but unavailable.

    Read paths never raise this — they degrade to FTS/structural and report
    ``semantic.used=false``. It is raised only by explicit semantic operations
    (e.g. resolving a real embedding provider whose dependency is missing).
    """


class SemanticChunkingInvariantError(MemoryContractError):
    """Raised when passage model input still exceeds the token window after chunking."""


__all__ = [
    "MemoryCapacityError",
    "MemoryContractError",
    "MemoryError",
    "MemoryInitLockError",
    "MemorySchemaError",
    "MemorySemanticUnavailableError",
    "SemanticChunkingInvariantError",
    "UnfitAnalysisRunError",
]
