# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..config.memory import MemoryConfig
from .enums import MemoryStatus
from .sqlite_store import SqliteEngineeringMemoryStore


@dataclass(frozen=True, slots=True)
class VacuumReport:
    deleted_by_status: dict[str, int]
    total_deleted: int


def _retention_days_for_status(
    status: MemoryStatus,
    config: MemoryConfig,
) -> int | None:
    mapping: dict[MemoryStatus, int] = {
        "stale": config.stale_retention_days,
        "draft": config.draft_retention_days,
        "rejected": config.rejected_retention_days,
        "archived": config.archived_retention_days,
    }
    days = mapping.get(status)
    if days is None or days < 0:
        return None
    return days


def run_memory_vacuum(
    store: SqliteEngineeringMemoryStore,
    config: MemoryConfig,
    *,
    commit: bool = True,
) -> VacuumReport:
    now = datetime.now(tz=timezone.utc)
    deleted_by_status: dict[str, int] = {}
    total = 0
    for status in ("stale", "draft", "rejected", "archived"):
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


__all__ = ["VacuumReport", "run_memory_vacuum"]
