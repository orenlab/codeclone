# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ..experience.models import Experience
from ..paths import normalize_memory_scope_path, repo_path_to_module_key
from ..trajectory.models import Trajectory


def _percent(covered: int, total: int) -> int | None:
    return round(covered * 100 / total) if total else None


def _trajectory_coverage(
    *,
    scope_paths: Sequence[str],
    trajectories: Sequence[Trajectory],
) -> tuple[dict[str, object], frozenset[str]]:
    normalized = tuple(normalize_memory_scope_path(path) for path in scope_paths)
    matched_paths: set[str] = set()
    agent_labels: set[str] = set()
    for trajectory in trajectories:
        subject_pairs = {
            (subject.subject_kind, subject.subject_key)
            for subject in trajectory.subjects
        }
        for path in normalized:
            if ("path", path) in subject_pairs or (
                "module",
                repo_path_to_module_key(path),
            ) in subject_pairs:
                matched_paths.add(path)
        agent_labels.update(
            key.strip()
            for kind, key in subject_pairs
            if kind == "agent" and key.strip()
        )
    total = len(normalized)
    return (
        {
            "scope_paths_with_trajectories": len(matched_paths),
            "scope_paths_total": total,
            "coverage_percent": _percent(len(matched_paths), total),
        },
        frozenset(agent_labels),
    )


def _experience_coverage(
    *,
    scope_families: frozenset[str],
    experiences: Sequence[Experience],
) -> tuple[dict[str, object], frozenset[str]]:
    matched_families = {
        experience.subject_family
        for experience in experiences
        if experience.subject_family in scope_families
    }
    agent_families = {
        facet.facet_value
        for experience in experiences
        for facet in experience.facets
        if facet.facet_kind == "agent_family" and facet.facet_value
    }
    total = len(scope_families)
    return (
        {
            "scope_families_with_experiences": len(matched_families),
            "scope_families_total": total,
            "coverage_percent": _percent(len(matched_families), total),
        },
        frozenset(agent_families),
    )


def _count(coverage: Mapping[str, object], key: str) -> int:
    value = coverage.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _observation_confidence(
    *,
    record_coverage: Mapping[str, object],
    trajectory_coverage: Mapping[str, object],
    experience_coverage: Mapping[str, object],
) -> dict[str, object]:
    basis = [
        lane
        for lane, coverage, key in (
            ("records", record_coverage, "scope_paths_with_memory"),
            (
                "trajectories",
                trajectory_coverage,
                "scope_paths_with_trajectories",
            ),
            (
                "experiences",
                experience_coverage,
                "scope_families_with_experiences",
            ),
        )
        if _count(coverage, key) > 0
    ]
    path_total = _count(record_coverage, "scope_paths_total")
    record_paths = _count(record_coverage, "scope_paths_with_memory")
    trajectory_paths = _count(
        trajectory_coverage,
        "scope_paths_with_trajectories",
    )
    level = "unknown"
    if basis:
        complete_path_evidence = (
            path_total > 0
            and record_paths >= path_total
            and trajectory_paths >= path_total
        )
        level = "supported" if complete_path_evidence else "partial"
    return {
        "level": level,
        "basis": basis,
        "note": (
            "Evidence availability only; not correctness, approval, or edit "
            "authorization."
        ),
    }


def build_context_coverage(
    *,
    record_coverage: Mapping[str, object],
    scope_paths: Sequence[str],
    scope_families: frozenset[str],
    trajectories: Sequence[Trajectory],
    experiences: Sequence[Experience],
) -> dict[str, object]:
    trajectory_coverage, trajectory_agents = _trajectory_coverage(
        scope_paths=scope_paths,
        trajectories=trajectories,
    )
    experience_coverage, experience_agents = _experience_coverage(
        scope_families=scope_families,
        experiences=experiences,
    )
    record_payload = dict(record_coverage)
    return {
        "record_coverage": record_payload,
        "trajectory_coverage": trajectory_coverage,
        "experience_coverage": experience_coverage,
        "agent_diversity": {
            "trajectory_agent_labels": sorted(trajectory_agents),
            "trajectory_agent_label_count": len(trajectory_agents),
            "experience_agent_families": sorted(experience_agents),
            "experience_agent_family_count": len(experience_agents),
        },
        "observation_confidence": _observation_confidence(
            record_coverage=record_payload,
            trajectory_coverage=trajectory_coverage,
            experience_coverage=experience_coverage,
        ),
    }


__all__ = ["build_context_coverage"]
