# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from codeclone.memory.experience.models import (
    EXPERIENCE_DISTILLATION_VERSION,
    Experience,
    ExperienceEvidence,
    ExperienceFacet,
    PatternKey,
)


def _experience(**overrides: Any) -> Experience:
    fields: dict[str, Any] = {
        "id": "exp-1",
        "project_id": "proj-1",
        "repo_root_digest": "b080e2e3",
        "subject_family": "codeclone/memory/trajectory/",
        "signal": "scope_expanded",
        "outcome_class": "violated:scope",
        "support": 5,
        "quality_min": 20,
        "information_value": 70,
        "status": "active",
        "statement": "Changes here recurrently expand scope and violate.",
        "experience_digest": "abc123",
        "distillation_version": EXPERIENCE_DISTILLATION_VERSION,
        "first_observed_at_utc": "2026-01-01T00:00:00Z",
        "last_observed_at_utc": "2026-02-01T00:00:00Z",
        "distilled_at_utc": "2026-02-02T00:00:00Z",
        "updated_at_utc": "2026-02-02T00:00:00Z",
        "facets": (ExperienceFacet("agent_family", "claude-code", 3),),
        "evidence": (ExperienceEvidence("traj-1", "violated", "2026-01-01T00:00:00Z"),),
    }
    fields.update(overrides)
    return Experience(**fields)


def test_distillation_version_is_v1() -> None:
    assert EXPERIENCE_DISTILLATION_VERSION == "experience-v1"


def test_pattern_key_is_value_equal_and_hashable() -> None:
    key = PatternKey("codeclone/memory/", "scope_expanded", "violated:scope")
    same = PatternKey("codeclone/memory/", "scope_expanded", "violated:scope")
    other = PatternKey(
        "codeclone/memory/", "verify_not_reached", "partial:verification"
    )

    assert key == same
    assert key != other
    # Real distiller contract: PatternKey buckets trajectories deterministically.
    bucket: dict[PatternKey, int] = {key: 1}
    assert bucket[same] == 1
    assert other not in bucket


def test_experience_is_frozen() -> None:
    experience = _experience()
    with pytest.raises(FrozenInstanceError):
        experience.support = 6  # type: ignore[misc]


def test_experience_holds_immutable_collections() -> None:
    experience = _experience(
        facets=(
            ExperienceFacet("agent_family", "claude-code", 3),
            ExperienceFacet("agent_family", "cursor-vscode", 2),
        ),
    )
    assert isinstance(experience.facets, tuple)
    assert isinstance(experience.evidence, tuple)
    assert experience.facets[1].facet_value == "cursor-vscode"
    assert experience.evidence[0].trajectory_id == "traj-1"
