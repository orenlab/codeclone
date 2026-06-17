# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Deterministic Experience distillation over the trajectory corpus.

Given a set of *canonical* trajectories (deduped by workflow, newest projection
preferred — the caller's responsibility), this groups them by a structural
``PatternKey`` and emits an Experience for each key that passes BOTH filters:

1. **support** — at least ``min_support`` distinct trajectories, and
2. **informativeness** — ``information_value`` over the threshold; a pattern
   explained by a single tool identity (one ``agent_family``) is a tool quirk,
   not a system regularity, and is rejected.

The pattern key never contains a tool identity (agent / profile / intent) — those
are recorded as facets. Same trajectory set always yields byte-identical
experiences: ordering is sorted, the digest is an orjson canonical over the key
and the sorted member ids.

Pure function: no DB, no surfaces, no clock (the caller passes ``now``). The
patch-trail-based process-artifact refinement (``changed=0``) is added when the
patch trail is wired (step 3); the single-facet guard already rejects the
single-agent ``verification_incomplete`` pattern.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Sequence
from pathlib import PurePosixPath

from ...utils.json_io import json_text
from ..paths import normalize_repo_path
from ..trajectory.models import Trajectory
from .models import (
    EXPERIENCE_DISTILLATION_VERSION,
    Experience,
    ExperienceEvidence,
    ExperienceFacet,
    PatternKey,
)

EXPERIENCE_MIN_SUPPORT = 5
MIN_INFORMATION_VALUE = 50
MAX_EVIDENCE = 20
MAX_FAMILIES_PER_TRAJECTORY = 8

# Labels carried by every change-control cycle — not informative as signals.
_UBIQUITOUS_LABELS = frozenset(
    {"change_control_workflow", "patch_trail_recorded", "receipt_issued"}
)

# Signal scoring weights (see information_value).
_MULTI_AGENT_SCORE = 60
_STRUCTURAL_SIGNAL_SCORE = 25

# Outcome-derived signals (not labels): lower-confidence, may be process noise.
_SIGNAL_VERIFICATION_INCOMPLETE = "verification_incomplete"
_SIGNAL_INCIDENT_PRESENT = "incident_present"


def _agent_family(agent_key: str) -> str:
    return agent_key.split("/", 1)[0]


def _path_family(path_key: str) -> str | None:
    try:
        normalized = normalize_repo_path(path_key)
    except ValueError:
        return None
    parent = PurePosixPath(normalized).parent.as_posix()
    if parent in {"", "."}:
        return None
    return parent


def _path_families(trajectory: Trajectory) -> frozenset[str]:
    families = {
        family
        for subject in trajectory.subjects
        if subject.subject_kind == "path"
        for family in (_path_family(subject.subject_key),)
        if family is not None
    }
    return frozenset(families)


def _agent_families(trajectory: Trajectory) -> frozenset[str]:
    return frozenset(
        _agent_family(subject.subject_key)
        for subject in trajectory.subjects
        if subject.subject_kind == "agent"
    )


def _outcome_class(trajectory: Trajectory) -> str:
    return f"{trajectory.outcome}:{trajectory.quality_tier}"


def _signals(trajectory: Trajectory) -> frozenset[str]:
    signals: set[str] = {
        label for label in trajectory.labels if label not in _UBIQUITOUS_LABELS
    }
    if trajectory.outcome in {"partial", "blocked"} and (
        "verified_finish" not in trajectory.labels
    ):
        signals.add(_SIGNAL_VERIFICATION_INCOMPLETE)
    if trajectory.incident_count > 0:
        signals.add(_SIGNAL_INCIDENT_PRESENT)
    return frozenset(signals)


def pattern_keys(trajectory: Trajectory) -> frozenset[PatternKey]:
    """Structural keys a trajectory contributes to (family x signal x outcome)."""
    families = sorted(_path_families(trajectory))[:MAX_FAMILIES_PER_TRAJECTORY]
    signals = _signals(trajectory)
    outcome_class = _outcome_class(trajectory)
    return frozenset(
        PatternKey(family, signal, outcome_class)
        for family in families
        for signal in signals
    )


def _structural_signal(signal: str) -> bool:
    return signal not in {_SIGNAL_VERIFICATION_INCOMPLETE, _SIGNAL_INCIDENT_PRESENT}


def information_value(key: PatternKey, members: Sequence[Trajectory]) -> int:
    """Deterministic 0-100 score: is this a system regularity or a tool quirk?

    Cross-agent recurrence is the system signal; a structural label cause adds
    confidence. A single-agent pattern scores below the threshold by design.
    """
    agents = {family for member in members for family in _agent_families(member)}
    score = 0
    if len(agents) >= 2:
        score += _MULTI_AGENT_SCORE
    if _structural_signal(key.signal):
        score += _STRUCTURAL_SIGNAL_SCORE
    return min(100, score)


def _aggregate_facets(members: Sequence[Trajectory]) -> tuple[ExperienceFacet, ...]:
    counts: dict[str, int] = defaultdict(int)
    for member in members:
        for family in _agent_families(member):
            counts[family] += 1
    return tuple(
        ExperienceFacet("agent_family", value, counts[value])
        for value in sorted(counts)
    )


def _build_evidence(members: Sequence[Trajectory]) -> tuple[ExperienceEvidence, ...]:
    ordered = sorted(members, key=lambda member: (member.finished_at_utc, member.id))
    return tuple(
        ExperienceEvidence(member.id, member.outcome, member.finished_at_utc)
        for member in ordered[:MAX_EVIDENCE]
    )


def _experience_digest(key: PatternKey, member_ids: Sequence[str]) -> str:
    payload = {
        "subject_family": key.subject_family,
        "signal": key.signal,
        "outcome_class": key.outcome_class,
        "members": list(member_ids),
        "distillation_version": EXPERIENCE_DISTILLATION_VERSION,
    }
    canonical = json_text(payload, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _statement(
    key: PatternKey,
    members: Sequence[Trajectory],
    facets: tuple[ExperienceFacet, ...],
) -> str:
    agents = ", ".join(f"{facet.facet_value}x{facet.count}" for facet in facets)
    return (
        f"Change-control cycles under {key.subject_family} recurrently show "
        f"'{key.signal}' with outcome {key.outcome_class} "
        f"(support {len(members)}; agents: {agents})."
    )


def _build_experience(
    key: PatternKey,
    members: Sequence[Trajectory],
    *,
    info: int,
    now: str,
) -> Experience:
    member_ids = sorted(member.id for member in members)
    digest = _experience_digest(key, member_ids)
    facets = _aggregate_facets(members)
    anchor = min(members, key=lambda member: member.id)
    return Experience(
        id=f"exp-{digest[:32]}",
        project_id=anchor.project_id,
        repo_root_digest=anchor.repo_root_digest,
        subject_family=key.subject_family,
        signal=key.signal,
        outcome_class=key.outcome_class,
        support=len(members),
        quality_min=min(member.quality_score for member in members),
        information_value=info,
        status="active",
        statement=_statement(key, members, facets),
        experience_digest=digest,
        distillation_version=EXPERIENCE_DISTILLATION_VERSION,
        first_observed_at_utc=min(member.finished_at_utc for member in members),
        last_observed_at_utc=max(member.finished_at_utc for member in members),
        distilled_at_utc=now,
        updated_at_utc=now,
        facets=facets,
        evidence=_build_evidence(members),
    )


def distill_experiences(
    trajectories: Sequence[Trajectory],
    *,
    now: str,
    min_support: int = EXPERIENCE_MIN_SUPPORT,
) -> list[Experience]:
    """Distill Experiences from canonical trajectories. Deterministic.

    ``trajectories`` must already be canonical (one per workflow). ``now`` stamps
    ``distilled_at_utc`` and is excluded from the identity digest.
    """
    buckets: dict[PatternKey, list[Trajectory]] = defaultdict(list)
    for trajectory in trajectories:
        for key in pattern_keys(trajectory):
            buckets[key].append(trajectory)

    experiences: list[Experience] = []
    for key in sorted(
        buckets, key=lambda item: (item.subject_family, item.signal, item.outcome_class)
    ):
        members = buckets[key]
        if len(members) < min_support:
            continue
        info = information_value(key, members)
        if info >= MIN_INFORMATION_VALUE:
            experiences.append(_build_experience(key, members, info=info, now=now))
    return experiences


__all__ = [
    "EXPERIENCE_MIN_SUPPORT",
    "MAX_EVIDENCE",
    "MIN_INFORMATION_VALUE",
    "distill_experiences",
    "information_value",
    "pattern_keys",
]
