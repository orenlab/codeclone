# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Sequence

from codeclone.memory.experience.distiller import (
    MIN_INFORMATION_VALUE,
    distill_experiences,
    information_value,
    pattern_keys,
)
from codeclone.memory.trajectory.models import Trajectory, TrajectorySubject

_NOW = "2026-06-08T00:00:00Z"
_FAMILY = "codeclone/memory/trajectory"


def _subjects(*, agent: str, paths: Sequence[str]) -> tuple[TrajectorySubject, ...]:
    items = [TrajectorySubject("agent", agent, "actor")]
    items.extend(TrajectorySubject("path", path, "about") for path in paths)
    return tuple(items)


def _traj(
    *,
    index: int,
    agent: str,
    outcome: str = "violated",
    quality_tier: str = "incident",
    quality_score: int = 20,
    labels: tuple[str, ...] = ("change_control_workflow", "scope_expanded"),
    incident_count: int = 0,
    paths: Sequence[str] = (f"{_FAMILY}/store.py",),
) -> Trajectory:
    finished = f"2026-06-0{index}T10:00:00Z"
    return Trajectory(
        id=f"traj-{index:032d}",
        project_id="proj-1",
        repo_root_digest="b080e2e3",
        workflow_id=f"intent:intent-{index}",
        intent_id=f"intent-{index}",
        primary_run_id=None,
        first_run_id=None,
        last_run_id=None,
        report_digest=None,
        outcome=outcome,  # type: ignore[arg-type]
        quality_tier=quality_tier,  # type: ignore[arg-type]
        quality_score=quality_score,
        labels=labels,  # type: ignore[arg-type]
        summary=f"cycle {index}",
        trajectory_digest=f"digest-{index}",
        source_event_stream_digest=f"stream-{index}",
        projection_version="trajectory-v3",
        event_count=2,
        step_count=2,
        incident_count=incident_count,
        started_at_utc=finished,
        finished_at_utc=finished,
        projected_at_utc=_NOW,
        updated_at_utc=_NOW,
        steps=(),
        subjects=_subjects(agent=agent, paths=paths),
        evidence=(),
    )


def _multi_agent_cohort(count: int = 5) -> list[Trajectory]:
    # 3 claude + (count-3) cursor on the same family/signal/outcome.
    agents = ["claude-code/2.1"] * 3 + ["cursor-vscode/1.0"] * (count - 3)
    return [_traj(index=i + 1, agent=agents[i]) for i in range(count)]


def _single_agent_verification_cohort(count: int = 5) -> list[Trajectory]:
    # The live cursor pattern: same agent, partial, no structural label.
    return [
        _traj(
            index=i + 1,
            agent="cursor-vscode/1.0",
            outcome="partial",
            quality_tier="partial",
            quality_score=40,
            labels=("change_control_workflow",),
        )
        for i in range(count)
    ]


def test_pattern_keys_exclude_tool_identity_and_use_family_signal_outcome() -> None:
    keys = pattern_keys(_traj(index=1, agent="claude-code/2.1"))
    assert len(keys) == 1
    key = next(iter(keys))
    assert (key.subject_family, key.signal, key.outcome_class) == (
        "codeclone/memory/trajectory",
        "scope_expanded",
        "violated:incident",
    )


def test_single_agent_pattern_is_rejected() -> None:
    # Canonical negative: the live cursor verify-not-reached pattern. Support is
    # met (5) but it is one tool's quirk, not a system regularity.
    cohort = _single_agent_verification_cohort(5)
    assert distill_experiences(cohort, now=_NOW) == []


def test_multi_agent_pattern_is_distilled_with_facets() -> None:
    experiences = distill_experiences(_multi_agent_cohort(5), now=_NOW)
    assert len(experiences) == 1
    experience = experiences[0]
    assert experience.subject_family == _FAMILY
    assert experience.signal == "scope_expanded"
    assert experience.outcome_class == "violated:incident"
    assert experience.support == 5
    assert experience.information_value >= MIN_INFORMATION_VALUE
    # agent is a facet, not part of identity: one experience, per-agent breakdown.
    facets = {(f.facet_kind, f.facet_value): f.count for f in experience.facets}
    assert facets == {
        ("agent_family", "claude-code"): 3,
        ("agent_family", "cursor-vscode"): 2,
    }


def test_support_threshold_blocks_below_minimum() -> None:
    assert distill_experiences(_multi_agent_cohort(4), now=_NOW) == []
    assert len(distill_experiences(_multi_agent_cohort(5), now=_NOW)) == 1


def test_distillation_is_deterministic() -> None:
    cohort = _multi_agent_cohort(5)
    first = distill_experiences(cohort, now=_NOW)
    second = distill_experiences(list(reversed(cohort)), now=_NOW)
    assert first == second
    assert first[0].id.startswith("exp-")
    assert first[0].experience_digest == second[0].experience_digest


def test_evidence_references_member_trajectories() -> None:
    cohort = _multi_agent_cohort(5)
    experience = distill_experiences(cohort, now=_NOW)[0]
    member_ids = {member.id for member in cohort}
    assert {item.trajectory_id for item in experience.evidence} <= member_ids
    assert len(experience.evidence) == 5


def test_information_value_single_agent_below_threshold() -> None:
    cohort = _single_agent_verification_cohort(5)
    key = next(iter(pattern_keys(cohort[0])))
    assert information_value(key, cohort) < MIN_INFORMATION_VALUE
