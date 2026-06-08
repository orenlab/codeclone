# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Experience Layer domain model.

An Experience is a deterministic *signal extraction* over the trajectory
corpus: a structural regularity observed across many trajectories, with those
trajectories as evidence. It is the third knowledge tier after Engineering
Memory ("what we know") and Trajectory ("what happened"): "what we have
repeatedly observed".

Invariant: the pattern key describes a *structural situation*, never a tool
identity. Agent / profile / intent are recorded as facets, never folded into
``PatternKey`` — keying by agent would fragment support and hide cross-agent
regularities. See ``specs/rfc-experience-layer.md``.

This module is pure data (frozen dataclasses); distillation lives in
``distiller`` and persistence in ``store``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ...contracts import EXPERIENCE_DISTILLATION_VERSION

ExperienceStatus = Literal["active", "dormant"]
ExperienceFacetKind = Literal["agent_family", "analysis_profile", "intent_class"]


@dataclass(frozen=True, slots=True)
class PatternKey:
    """Structural identity of an Experience. Never includes tool identity."""

    subject_family: str
    signal: str
    outcome_class: str


@dataclass(frozen=True, slots=True)
class ExperienceFacet:
    """A non-key breakdown dimension (e.g. agent_family) with its member count."""

    facet_kind: ExperienceFacetKind
    facet_value: str
    count: int


@dataclass(frozen=True, slots=True)
class ExperienceEvidence:
    """A contributing trajectory: the proof that the pattern was observed."""

    trajectory_id: str
    outcome: str
    finished_at_utc: str


@dataclass(frozen=True, slots=True)
class Experience:
    """A distilled structural regularity over the trajectory corpus.

    Advisory and machine-owned: it never asserts truth and never authorizes
    edits. Promotion into durable Engineering Memory is a separate, optional,
    human-governed step.
    """

    id: str
    project_id: str
    repo_root_digest: str
    subject_family: str
    signal: str
    outcome_class: str
    support: int
    quality_min: int
    information_value: int
    status: ExperienceStatus
    statement: str
    experience_digest: str
    distillation_version: str
    first_observed_at_utc: str
    last_observed_at_utc: str
    distilled_at_utc: str
    updated_at_utc: str
    facets: tuple[ExperienceFacet, ...]
    evidence: tuple[ExperienceEvidence, ...]


__all__ = [
    "EXPERIENCE_DISTILLATION_VERSION",
    "Experience",
    "ExperienceEvidence",
    "ExperienceFacet",
    "ExperienceFacetKind",
    "ExperienceStatus",
    "PatternKey",
]
