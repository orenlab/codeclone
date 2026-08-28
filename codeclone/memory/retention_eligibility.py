# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""Whether age has made a stored artifact deletable — never that it must go.

``memory.receipt_retention_days`` and ``memory.trajectory_retention_days`` do
not mean "older than N days, therefore DELETE". They mean: age may make an
artifact a *candidate* for deletion, and only if nothing retained, approved,
solved, or audited still requires it as evidence. Age is a condition of
eligibility, never an authority to destroy history.

The whole rule::

    old enough AND unreferenced AND not rooted AND lifecycle allows deletion
        -> eligible

Every conjunct has to be *provable*. Where the reference graph cannot prove
one, the answer is a refusal that names what is missing — not a guess, and
never a silent grant. That is the same law as "incomplete roots imply no
sweep": an unknown referrer is indistinguishable from a live one, so the only
safe reading of "we do not know" is "keep".

This module answers the question. It never deletes, and it holds no store
handle with which it could: the sweeper that would act on an ``eligible``
verdict is a separate, later concern, and no verdict here reaches one today.

Two arms of one ordered rule:

* :func:`artifact_sweep_eligibility` answers the part that does not depend on
  any single artifact — is retention configured, is the graph complete, has
  any lifecycle state been ratified as disposable. A refusal here applies to
  every artifact of the kind, so a caller learns it without enumerating.
* :func:`artifact_candidate_eligibility` runs that same check first and then
  the per-artifact conjuncts. The shared prefix is called, not restated, so
  the two arms cannot drift into two rules.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Final, Literal, Protocol

#: Stored artifacts whose retention is configured under ``[tool.codeclone.memory]``.
ArtifactKind = Literal["receipt", "trajectory"]

ARTIFACT_KIND_VALUES: Final[tuple[ArtifactKind, ...]] = ("receipt", "trajectory")

#: The one outcome that permits deletion. Everything else is a refusal.
ELIGIBLE: Final = "eligible"

# Kind-level refusals: they hold for every artifact of the kind at once.
RETENTION_UNCONFIGURED: Final = "retention_unconfigured"
REFERENCES_UNPROVABLE: Final = "references_unprovable"
ROOTS_UNPROVABLE: Final = "roots_unprovable"
LIFECYCLE_UNRATIFIED: Final = "lifecycle_unratified"

# Artifact-level refusals: this artifact, on this evidence.
AGE_UNPROVABLE: Final = "age_unprovable"
TOO_YOUNG: Final = "too_young"
REFERENCED: Final = "referenced"
ROOTED: Final = "rooted"
LIFECYCLE_RETAINS: Final = "lifecycle_retains"

#: Every outcome the decision can return. Declared in one place so the set is
#: knowable without grepping the branches, and pinned complete by test.
ARTIFACT_RETENTION_OUTCOMES: Final[frozenset[str]] = frozenset(
    {
        ELIGIBLE,
        RETENTION_UNCONFIGURED,
        REFERENCES_UNPROVABLE,
        ROOTS_UNPROVABLE,
        LIFECYCLE_UNRATIFIED,
        AGE_UNPROVABLE,
        TOO_YOUNG,
        REFERENCED,
        ROOTED,
        LIFECYCLE_RETAINS,
    }
)

#: Stand-in source for a kind nothing declares sources for. No graph can
#: resolve it, so an undeclared kind refuses instead of sailing through the
#: completeness checks with an empty requirement.
UNDECLARED_ARTIFACT_KIND: Final = "undeclared_artifact_kind"

#: Where a referrer to an artifact of each kind can live, as measured on this
#: schema. A receipt is cited by ``memory_evidence`` rows of evidence kind
#: ``receipt``; a trajectory by ``memory_evidence`` rows of kind ``trajectory``
#: and by ``memory_experience_evidence``, which keys distilled experiences to
#: the trajectories they were distilled from.
ARTIFACT_REFERENCE_SOURCES: Final[Mapping[ArtifactKind, tuple[str, ...]]] = {
    "receipt": ("memory_evidence",),
    "trajectory": ("memory_evidence", "memory_experience_evidence"),
}

#: What can *root* an artifact: a state that still requires it as evidence,
#: so that deleting the artifact would strand the state rather than merely
#: forget an old row. The four are the retained, approved, solved and audit
#: states of the governance model; none of them is queryable as a root index
#: on this build, which is why every production sweep refuses.
ARTIFACT_ROOT_SOURCES: Final[Mapping[ArtifactKind, tuple[str, ...]]] = {
    "receipt": ("retained_state", "approved_state", "solved_state", "audit_state"),
    "trajectory": ("retained_state", "approved_state", "solved_state", "audit_state"),
}

_TIMESTAMP_FORMAT: Final = "%Y-%m-%dT%H:%M:%SZ"


class ArtifactRetentionOwner(Protocol):
    """The retention owner, seen from the decision that consults it.

    Deliberately narrow: exactly the two questions this module is allowed to
    ask. Coupling to the questions rather than to a class keeps the authority
    edge testable by substitution — hand the decision a different owner and
    the verdict must change with it.
    """

    def eligibility_days(self, kind: ArtifactKind) -> int | None:
        """Age in days after which deletion of *kind* may be considered."""

    def deletable_lifecycles(self, kind: ArtifactKind) -> tuple[str, ...]:
        """Lifecycle states of *kind* whose age-based deletion is ratified."""


def _declared_sources(
    table: Mapping[ArtifactKind, tuple[str, ...]],
    kind: ArtifactKind,
) -> tuple[str, ...]:
    """Sources a kind requires, failing closed for an undeclared kind."""
    return table.get(kind, (UNDECLARED_ARTIFACT_KIND,))


class ArtifactReferenceGraph:
    """What a caller can actually prove about who holds an artifact.

    Two separate facts, kept apart on purpose. *Which sources it resolved* is
    the completeness of the graph: a source it did not resolve is a blind
    spot, and a blind spot forbids deletion no matter what the resolved
    sources say. *Which refs came back* is the content: the referrers and
    roots it did find.

    Claiming a source without resolving it would turn the refusal into a
    guess, so the constructor takes resolved sources explicitly and defaults
    to none.
    """

    __slots__ = (
        "referenced_refs",
        "resolved_reference_sources",
        "resolved_root_sources",
        "rooted_refs",
    )

    def __init__(
        self,
        *,
        resolved_reference_sources: Sequence[str] = (),
        resolved_root_sources: Sequence[str] = (),
        referenced_refs: Sequence[str] = (),
        rooted_refs: Sequence[str] = (),
    ) -> None:
        self.resolved_reference_sources = frozenset(resolved_reference_sources)
        self.resolved_root_sources = frozenset(resolved_root_sources)
        self.referenced_refs = frozenset(referenced_refs)
        self.rooted_refs = frozenset(rooted_refs)

    def missing_reference_sources(self, kind: ArtifactKind) -> tuple[str, ...]:
        """Declared referrer sources this graph did not resolve."""
        declared = _declared_sources(ARTIFACT_REFERENCE_SOURCES, kind)
        return tuple(
            source
            for source in declared
            if source not in self.resolved_reference_sources
        )

    def missing_root_sources(self, kind: ArtifactKind) -> tuple[str, ...]:
        """Declared root sources this graph did not resolve."""
        declared = _declared_sources(ARTIFACT_ROOT_SOURCES, kind)
        return tuple(
            source for source in declared if source not in self.resolved_root_sources
        )


class ArtifactCandidate:
    """One stored artifact, described by what a sweeper would know about it."""

    __slots__ = ("kind", "lifecycle_state", "ref", "updated_at_utc")

    def __init__(
        self,
        *,
        kind: ArtifactKind,
        ref: str,
        updated_at_utc: str,
        lifecycle_state: str,
    ) -> None:
        self.kind = kind
        self.ref = ref
        self.updated_at_utc = updated_at_utc
        self.lifecycle_state = lifecycle_state


class RetentionEligibility:
    """The verdict: one outcome, and what was missing when it was a refusal.

    ``missing_sources`` is the executable part of a refusal — it names the
    reference or root sources that would have to be resolved before the same
    question could be answered any other way.
    """

    __slots__ = ("kind", "missing_sources", "outcome", "ref")

    def __init__(
        self,
        *,
        kind: ArtifactKind,
        outcome: str,
        ref: str | None = None,
        missing_sources: tuple[str, ...] = (),
    ) -> None:
        self.kind = kind
        self.outcome = outcome
        self.ref = ref
        self.missing_sources = missing_sources

    @property
    def eligible(self) -> bool:
        """Whether deletion is permitted. Only ever true for :data:`ELIGIBLE`."""
        return self.outcome == ELIGIBLE


def production_artifact_reference_graph() -> ArtifactReferenceGraph:
    """The graph this build can honestly assemble: an empty one.

    No resolver exists yet for either declared reference source, and no root
    index exists at all, so every source in :data:`ARTIFACT_REFERENCE_SOURCES`
    and :data:`ARTIFACT_ROOT_SOURCES` is unresolved. That is not a placeholder
    standing in for work assumed done: it is the measured state of the store,
    and it is what makes every production sweep refuse.

    Receipts additionally have no population inside the memory store at all —
    they live in the audit log as ``review_receipt.created`` events — so
    resolving their referrer source would still not make them sweepable from
    here.
    """
    return ArtifactReferenceGraph()


def artifact_sweep_eligibility(
    *,
    policy: ArtifactRetentionOwner,
    kind: ArtifactKind,
    graph: ArtifactReferenceGraph,
) -> RetentionEligibility:
    """Whether any artifact of *kind* could be deleted on age at all.

    The conjuncts that do not depend on which artifact is in hand, in the
    order a refusal is most fundamental. A caller that gets a refusal here has
    its answer for the whole kind and must not enumerate candidates.
    """
    if policy.eligibility_days(kind) is None:
        return RetentionEligibility(kind=kind, outcome=RETENTION_UNCONFIGURED)
    missing_references = graph.missing_reference_sources(kind)
    if missing_references:
        return RetentionEligibility(
            kind=kind,
            outcome=REFERENCES_UNPROVABLE,
            missing_sources=missing_references,
        )
    missing_roots = graph.missing_root_sources(kind)
    if missing_roots:
        return RetentionEligibility(
            kind=kind,
            outcome=ROOTS_UNPROVABLE,
            missing_sources=missing_roots,
        )
    if not policy.deletable_lifecycles(kind):
        return RetentionEligibility(kind=kind, outcome=LIFECYCLE_UNRATIFIED)
    return RetentionEligibility(kind=kind, outcome=ELIGIBLE)


def _age_in_days(updated_at_utc: str, now: datetime) -> int | None:
    try:
        stamped = datetime.strptime(updated_at_utc, _TIMESTAMP_FORMAT)
    except ValueError:
        return None
    return (now - stamped.replace(tzinfo=timezone.utc)).days


def artifact_candidate_eligibility(
    *,
    policy: ArtifactRetentionOwner,
    candidate: ArtifactCandidate,
    graph: ArtifactReferenceGraph,
    now: datetime,
) -> RetentionEligibility:
    """The full rule for one artifact.

    Runs the kind-level arm first — a blind spot in the graph outranks
    anything this artifact could say about itself — then the per-artifact
    conjuncts: old enough, unreferenced, not rooted, lifecycle permits.
    """
    kind = candidate.kind
    days = policy.eligibility_days(kind)
    sweep = artifact_sweep_eligibility(policy=policy, kind=kind, graph=graph)
    if days is None or not sweep.eligible:
        # ``days is None`` is the very fact the gate reports as
        # RETENTION_UNCONFIGURED; naming it again narrows the type without
        # introducing a second rule about it.
        return RetentionEligibility(
            kind=kind,
            outcome=sweep.outcome,
            ref=candidate.ref,
            missing_sources=sweep.missing_sources,
        )
    age_days = _age_in_days(candidate.updated_at_utc, now)
    if age_days is None:
        return RetentionEligibility(
            kind=kind, outcome=AGE_UNPROVABLE, ref=candidate.ref
        )
    if age_days < days:
        return RetentionEligibility(kind=kind, outcome=TOO_YOUNG, ref=candidate.ref)
    if candidate.ref in graph.referenced_refs:
        return RetentionEligibility(kind=kind, outcome=REFERENCED, ref=candidate.ref)
    if candidate.ref in graph.rooted_refs:
        return RetentionEligibility(kind=kind, outcome=ROOTED, ref=candidate.ref)
    if candidate.lifecycle_state not in policy.deletable_lifecycles(kind):
        return RetentionEligibility(
            kind=kind, outcome=LIFECYCLE_RETAINS, ref=candidate.ref
        )
    return RetentionEligibility(kind=kind, outcome=ELIGIBLE, ref=candidate.ref)


__all__ = [
    "AGE_UNPROVABLE",
    "ARTIFACT_KIND_VALUES",
    "ARTIFACT_REFERENCE_SOURCES",
    "ARTIFACT_RETENTION_OUTCOMES",
    "ARTIFACT_ROOT_SOURCES",
    "ELIGIBLE",
    "LIFECYCLE_RETAINS",
    "LIFECYCLE_UNRATIFIED",
    "REFERENCED",
    "REFERENCES_UNPROVABLE",
    "RETENTION_UNCONFIGURED",
    "ROOTED",
    "ROOTS_UNPROVABLE",
    "TOO_YOUNG",
    "UNDECLARED_ARTIFACT_KIND",
    "ArtifactCandidate",
    "ArtifactKind",
    "ArtifactReferenceGraph",
    "ArtifactRetentionOwner",
    "RetentionEligibility",
    "artifact_candidate_eligibility",
    "artifact_sweep_eligibility",
    "production_artifact_reference_graph",
]
