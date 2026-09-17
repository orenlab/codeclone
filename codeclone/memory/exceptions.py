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


class MemorySchemaAuthorityError(MemorySchemaError):
    """Raised when opening the store would need to change an EXISTING schema
    version and the caller carries no migration authority.

    Covers both directions: this checkout's code is newer than the on-disk
    store (a forward migration would be needed) and this checkout's code is
    older than the on-disk store (no migration path runs backward). Either
    way the store is left byte-for-byte unchanged -- initializing a brand
    new store (no prior ``schema_version``) is unaffected and always
    allowed, since there is no existing schema to change. See
    ``codeclone.memory.schema_migrate.migrate_memory_schema_authoritative``
    for the one sanctioned way to change an existing store's version.
    """


class MemorySchemaUnrecognizedError(MemorySchemaError):
    """Raised when the file at the store path is not an engineering-memory
    store: a SQLite database holding tables of its own and no ``memory_meta``,
    or bytes SQLite cannot read as a database at all.

    Not a version mismatch -- there is no schema version to be incompatible
    with -- and not a brand-new store either: a database that already holds
    somebody's tables is not codeclone's to initialize into, and a corrupt or
    non-database file is nobody's to initialize into. The refusal is
    decided before any read-write open (``open_memory_db`` looks through a
    read-only URI first), so the file is left byte-for-byte unchanged;
    ``ensure_schema`` reaches the same decision for a caller that already
    holds a connection.
    """


class MemorySchemaMigrationInProgressError(MemorySchemaError):
    """Raised when an authoritative migration attempt loses the migration
    lease race to another live holder.

    Same ownership law as ``codeclone.canonical.store.acquire_run_lease``
    and the ``memory_projection_jobs`` lease
    (``codeclone.memory.jobs.store``): a positive-TTL grant with a fencing
    token, decided by ``codeclone.models.deadline_passed``. The refused
    caller performed no mutation; the winner is still migrating, has
    already finished, or crashed and will be reclaimable once its lease
    expires.
    """


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
    "MemorySchemaAuthorityError",
    "MemorySchemaError",
    "MemorySchemaMigrationInProgressError",
    "MemorySemanticUnavailableError",
    "SemanticChunkingInvariantError",
    "UnfitAnalysisRunError",
]
