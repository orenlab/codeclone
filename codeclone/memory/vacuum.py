# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping
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
#: declared, validated and materialized onto :class:`MemoryConfig`, and
#: :class:`MemoryRetentionPolicy` is their owner of record. They are withheld
#: from deletion on purpose: "older than N days" is a plausible reading of the
#: names and a destructive one. ``active`` is live, approved knowledge, and
#: ``stale`` is a reviewable state that staleness refresh can move back out —
#: neither is terminal, so age alone does not establish that a record is
#: disposable. Engineering Memory already carries lifecycle semantics
#: (supersession, archival, staleness) that a bare age threshold would cut
#: across.
#:
#: Applying a policy here requires an explicit retention ruling, not an
#: inference from the key names. Until then the configured value is resolved
#: and reportable but never deletes.
RETENTION_UNENFORCED_STATUSES: Final[tuple[MemoryStatus, ...]] = (
    "active",
    "stale",
)


class MemoryRetentionPolicy:
    """Canonical owner of memory retention authority.

    A configuration key is enforced only if a structural path exists from its
    canonical config owner to the production decision it claims to control.
    Validation, documentation, reporting, or a field on a policy object are
    not enforcement witnesses.

    This class is that path's middle term. It resolves the retention keys off
    :class:`MemoryConfig`, it declares which statuses the deletion policy is
    ratified for, and it answers the only two questions the vacuum is allowed
    to ask: which statuses are governed at all, and how old a record of a
    given status must be before deletion is permitted.

    The vacuum must take its population from :attr:`governed_statuses` rather
    than restate one. A consumer that iterates its own list still deletes the
    same rows today, but the authority edge is severed: the withheld statuses
    stop reaching the decision, and this class plus its rationale decay into
    unreachable prose while every observable byte stays identical.
    """

    __slots__ = ("days_by_status", "enforced", "withheld")

    def __init__(
        self,
        *,
        enforced: tuple[MemoryStatus, ...],
        withheld: tuple[MemoryStatus, ...],
        days_by_status: Mapping[MemoryStatus, int],
    ) -> None:
        self.enforced = enforced
        self.withheld = withheld
        self.days_by_status = days_by_status

    @classmethod
    def from_config(cls, config: MemoryConfig) -> MemoryRetentionPolicy:
        """Resolve the policy from configuration — the config edge."""
        return cls(
            enforced=RETENTION_ENFORCED_STATUSES,
            withheld=RETENTION_UNENFORCED_STATUSES,
            days_by_status={
                "active": config.active_retention_days,
                "stale": config.stale_retention_days,
                "draft": config.draft_retention_days,
                "rejected": config.rejected_retention_days,
                "archived": config.archived_retention_days,
            },
        )

    @property
    def governed_statuses(self) -> tuple[MemoryStatus, ...]:
        """Every status this policy governs, ratified or withheld.

        The single source of truth about the population that must reach the
        retention decision. Enforced statuses lead so the ratified deletion
        order is unchanged by the withheld ones.
        """
        return (*self.enforced, *self.withheld)

    def configured_days(self, status: MemoryStatus) -> int | None:
        """The configured retention for *status*, ratified or not.

        ``None`` when the status carries no retention key or the configured
        value is negative, which means "keep forever".
        """
        days = self.days_by_status.get(status)
        if days is None or days < 0:
            return None
        return days

    def deletion_days(self, status: MemoryStatus) -> int | None:
        """Age after which deleting *status* is permitted, else ``None``.

        Withheld statuses resolve to ``None`` here even when configured: the
        value reached its owner and the owner declined to act on it.
        """
        if status not in self.enforced:
            return None
        return self.configured_days(status)

    def withheld_days(self) -> dict[str, int]:
        """Configured retentions that no ratified policy applies."""
        resolved: dict[str, int] = {}
        for status in self.withheld:
            days = self.configured_days(status)
            if days is not None:
                resolved[status] = days
        return dict(sorted(resolved.items()))


@dataclass(frozen=True, slots=True)
class VacuumReport:
    deleted_by_status: dict[str, int]
    total_deleted: int


def unenforced_retention_days(config: MemoryConfig) -> dict[str, int]:
    """Report configured retentions that no ratified policy applies.

    These values are read from configuration and deliberately not acted on.
    See :data:`RETENTION_UNENFORCED_STATUSES` for why.
    """
    return MemoryRetentionPolicy.from_config(config).withheld_days()


def run_memory_vacuum(
    store: SqliteEngineeringMemoryStore,
    config: MemoryConfig,
    *,
    commit: bool = True,
) -> VacuumReport:
    policy = MemoryRetentionPolicy.from_config(config)
    now = datetime.now(tz=timezone.utc)
    deleted_by_status: dict[str, int] = {}
    total = 0
    for status in policy.governed_statuses:
        days = policy.deletion_days(status)
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
    "RETENTION_ENFORCED_STATUSES",
    "RETENTION_UNENFORCED_STATUSES",
    "MemoryRetentionPolicy",
    "VacuumReport",
    "run_memory_vacuum",
    "unenforced_retention_days",
]
