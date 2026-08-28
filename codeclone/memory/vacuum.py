# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Final

from ..config.memory import MemoryConfig
from .enums import MemoryStatus
from .retention_eligibility import (
    ArtifactKind,
    artifact_sweep_eligibility,
    production_artifact_reference_graph,
)
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

#: Artifact lifecycle states whose age-based deletion is ratified, per kind.
#:
#: Empty for every kind, and that emptiness is the ruling, not an oversight.
#: ``memory.receipt_retention_days`` and ``memory.trajectory_retention_days``
#: make age a *condition* of eligibility; they are not an authority to destroy
#: a receipt or a trajectory history. Declaring a state disposable here is a
#: retention decision about evidence, and no such decision has been taken, so
#: the owner answers "none" and the eligibility rule refuses.
#:
#: A kind is listed even with an empty tuple: the entry is the record that the
#: question was asked for that kind and answered, which a missing key would
#: not be.
RATIFIED_DELETABLE_ARTIFACT_LIFECYCLES: Final[
    Mapping[ArtifactKind, tuple[str, ...]]
] = {
    "receipt": (),
    "trajectory": (),
}


def _positive_days(days: int | None) -> int | None:
    """A configured retention, or ``None`` for absent and "keep forever"."""
    if days is None or days < 0:
        return None
    return days


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

    Stored artifacts — receipts and trajectories — are governed on the same
    path but a different footing. For them age is a *condition* of
    eligibility, never an authority, so this class hands
    :mod:`codeclone.memory.retention_eligibility` two facts and no verdict:
    the configured age, and which artifact lifecycle states a ruling has
    declared disposable. The verdict is the rule's, and today it is always a
    refusal.

    The vacuum must take its population from :attr:`governed_statuses` rather
    than restate one. A consumer that iterates its own list still deletes the
    same rows today, but the authority edge is severed: the withheld statuses
    stop reaching the decision, and this class plus its rationale decay into
    unreachable prose while every observable byte stays identical.
    """

    __slots__ = ("days_by_artifact", "days_by_status", "enforced", "withheld")

    def __init__(
        self,
        *,
        enforced: tuple[MemoryStatus, ...],
        withheld: tuple[MemoryStatus, ...],
        days_by_status: Mapping[MemoryStatus, int],
        days_by_artifact: Mapping[ArtifactKind, int] | None = None,
    ) -> None:
        self.enforced = enforced
        self.withheld = withheld
        self.days_by_status = days_by_status
        self.days_by_artifact: Mapping[ArtifactKind, int] = (
            {} if days_by_artifact is None else days_by_artifact
        )

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
            days_by_artifact={
                "receipt": config.receipt_retention_days,
                "trajectory": config.trajectory_retention_days,
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

    @property
    def governed_artifacts(self) -> tuple[ArtifactKind, ...]:
        """Every stored artifact kind whose retention configuration exists.

        Derived from the resolved keys rather than restated, so the population
        that reaches the eligibility rule cannot drift from the population
        configuration declares.
        """
        return tuple(sorted(self.days_by_artifact))

    def configured_days(self, status: MemoryStatus) -> int | None:
        """The configured retention for *status*, ratified or not.

        ``None`` when the status carries no retention key or the configured
        value is negative, which means "keep forever".
        """
        return _positive_days(self.days_by_status.get(status))

    def eligibility_days(self, kind: ArtifactKind) -> int | None:
        """Age after which an artifact of *kind* may be *considered*, else None.

        Not a deletion age. This value is one conjunct of the eligibility rule
        in :mod:`codeclone.memory.retention_eligibility`, which still has to
        establish that nothing references or roots the artifact before any
        deletion could follow. ``None`` means "keep forever" — the key is
        absent or configured negative.
        """
        return _positive_days(self.days_by_artifact.get(kind))

    def deletable_lifecycles(self, kind: ArtifactKind) -> tuple[str, ...]:
        """Lifecycle states of *kind* whose age-based deletion is ratified.

        Empty for every kind on this build. See
        :data:`RATIFIED_DELETABLE_ARTIFACT_LIFECYCLES` for why that is a
        decision rather than a gap.
        """
        return RATIFIED_DELETABLE_ARTIFACT_LIFECYCLES.get(kind, ())

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
    #: Per artifact kind, the retention outcome the vacuum was given for it.
    #: Every value is a refusal on this build; ``eligible`` would mean the
    #: eligibility rule found nothing left to object to, not that anything was
    #: swept — the vacuum deletes records only.
    artifact_sweep: dict[str, str] = field(default_factory=dict)


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
    # Artifacts first, and only as a question. The rule is asked whether age
    # has made receipts or trajectories deletable at all; it answers with a
    # refusal naming what it could not prove, and the vacuum has no artifact
    # deletion to gate on the answer. Building one belongs to whoever can
    # first resolve the referrer and root sources the refusal names.
    graph = production_artifact_reference_graph()
    artifact_sweep: dict[str, str] = {
        kind: artifact_sweep_eligibility(policy=policy, kind=kind, graph=graph).outcome
        for kind in policy.governed_artifacts
    }
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
        artifact_sweep=artifact_sweep,
    )


__all__ = [
    "RATIFIED_DELETABLE_ARTIFACT_LIFECYCLES",
    "RETENTION_ENFORCED_STATUSES",
    "RETENTION_UNENFORCED_STATUSES",
    "MemoryRetentionPolicy",
    "VacuumReport",
    "run_memory_vacuum",
    "unenforced_retention_days",
]
