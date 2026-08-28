# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Final

from ..config.memory import MemoryConfig
from .enums import MemoryStatus
from .sqlite_store import SqliteEngineeringMemoryStore

#: Statuses whose age-based deletion policy is ratified. These are terminal or
#: non-authoritative records: a draft nobody promoted, a rejected candidate, an
#: archived record. Deleting them on age loses no established knowledge.
RETENTION_ENFORCED_STATUSES: Final[tuple[MemoryStatus, ...]] = (
    "draft",
    "rejected",
    "archived",
)

#: Statuses whose retention is configurable and deliberately not applied.
#:
#: ``memory.active_retention_days`` and ``memory.stale_retention_days`` are
#: declared, validated and materialized onto :class:`MemoryConfig`, and this
#: module is their owner of record. They are withheld from the vacuum on
#: purpose: "older than N days" is a plausible reading of the names and a
#: destructive one. ``active`` is live, approved knowledge, and ``stale`` is a
#: reviewable state that staleness refresh can move back out — neither is
#: terminal, so age alone does not establish that a record is disposable.
#: Engineering Memory already carries lifecycle semantics (supersession,
#: archival, staleness) that a bare age threshold would cut across.
#:
#: Applying a policy here requires an explicit retention ruling, not an
#: inference from the key names. Until then the configured value is resolved
#: and reportable through :func:`unenforced_retention_days` but never deletes.
RETENTION_UNENFORCED_STATUSES: Final[tuple[MemoryStatus, ...]] = (
    "active",
    "stale",
)

#: Every status carrying a ``<status>_retention_days`` config key. Enforced
#: statuses lead so the ratified deletion order is unchanged by the gate.
RETENTION_CONFIGURED_STATUSES: Final[tuple[MemoryStatus, ...]] = (
    *RETENTION_ENFORCED_STATUSES,
    *RETENTION_UNENFORCED_STATUSES,
)


@dataclass(frozen=True, slots=True)
class VacuumReport:
    deleted_by_status: dict[str, int]
    total_deleted: int


def configured_retention_days(
    status: MemoryStatus,
    config: MemoryConfig,
) -> int | None:
    """Resolve the configured retention for *status*, enforced or not.

    Returns ``None`` when the status carries no retention key or when the
    configured value is negative, which means "keep forever".
    """
    mapping: dict[MemoryStatus, int] = {
        "active": config.active_retention_days,
        "stale": config.stale_retention_days,
        "draft": config.draft_retention_days,
        "rejected": config.rejected_retention_days,
        "archived": config.archived_retention_days,
    }
    days = mapping.get(status)
    if days is None or days < 0:
        return None
    return days


def unenforced_retention_days(config: MemoryConfig) -> dict[str, int]:
    """Report configured retentions that no ratified policy applies.

    These values are read from configuration and deliberately not acted on.
    See :data:`RETENTION_UNENFORCED_STATUSES` for why.
    """
    resolved: dict[str, int] = {}
    for status in RETENTION_UNENFORCED_STATUSES:
        days = configured_retention_days(status, config)
        if days is not None:
            resolved[status] = days
    return dict(sorted(resolved.items()))


def _retention_days_for_status(
    status: MemoryStatus,
    config: MemoryConfig,
) -> int | None:
    if status not in RETENTION_ENFORCED_STATUSES:
        return None
    return configured_retention_days(status, config)


def run_memory_vacuum(
    store: SqliteEngineeringMemoryStore,
    config: MemoryConfig,
    *,
    commit: bool = True,
) -> VacuumReport:
    now = datetime.now(tz=timezone.utc)
    deleted_by_status: dict[str, int] = {}
    total = 0
    for status in RETENTION_CONFIGURED_STATUSES:
        days = _retention_days_for_status(status, config)
        if days is None:
            continue
        cutoff = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        count = store.delete_records_older_than(
            status=status,
            updated_before_utc=cutoff,
            commit=False,
        )
        if count:
            deleted_by_status[status] = count
            total += count
    if commit:
        store.commit()
    return VacuumReport(
        deleted_by_status=dict(sorted(deleted_by_status.items())),
        total_deleted=total,
    )


__all__ = [
    "RETENTION_CONFIGURED_STATUSES",
    "RETENTION_ENFORCED_STATUSES",
    "RETENTION_UNENFORCED_STATUSES",
    "VacuumReport",
    "configured_retention_days",
    "run_memory_vacuum",
    "unenforced_retention_days",
]
