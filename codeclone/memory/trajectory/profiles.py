# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from .models import Trajectory, TrajectoryQualityTier

TRAJECTORY_EXPORT_SCHEMA_VERSION: Final = "1"

ExportProfileName = Literal[
    "agent-change-control-v1",
    "agent-memory-retrieval-v1",
    "agent-recovery-v1",
    "agent-security-hardening-v1",
]


@dataclass(frozen=True, slots=True)
class TrajectoryExportProfile:
    name: ExportProfileName
    schema_version: str
    description: str
    allowed_quality_tiers: frozenset[TrajectoryQualityTier]
    allow_partial: bool
    allow_incident: bool


EXPORT_PROFILES: Final[dict[str, TrajectoryExportProfile]] = {
    "agent-change-control-v1": TrajectoryExportProfile(
        name="agent-change-control-v1",
        schema_version=TRAJECTORY_EXPORT_SCHEMA_VERSION,
        description="Edit discipline, scope, verify, and receipt outcomes.",
        allowed_quality_tiers=frozenset({"verified", "corrected"}),
        allow_partial=False,
        allow_incident=False,
    ),
    "agent-memory-retrieval-v1": TrajectoryExportProfile(
        name="agent-memory-retrieval-v1",
        schema_version=TRAJECTORY_EXPORT_SCHEMA_VERSION,
        description="Scoped memory and trajectory context usage patterns.",
        allowed_quality_tiers=frozenset(
            {"verified", "corrected", "partial", "incident"}
        ),
        allow_partial=True,
        allow_incident=False,
    ),
    "agent-recovery-v1": TrajectoryExportProfile(
        name="agent-recovery-v1",
        schema_version=TRAJECTORY_EXPORT_SCHEMA_VERSION,
        description="Failed verify, conflict, and recovery examples.",
        allowed_quality_tiers=frozenset({"corrected", "incident", "partial"}),
        allow_partial=True,
        allow_incident=True,
    ),
    "agent-security-hardening-v1": TrajectoryExportProfile(
        name="agent-security-hardening-v1",
        schema_version=TRAJECTORY_EXPORT_SCHEMA_VERSION,
        description="Safe handling of path and security denials.",
        allowed_quality_tiers=frozenset({"verified", "corrected", "incident"}),
        allow_partial=False,
        allow_incident=True,
    ),
}


def resolve_export_profile(profile: str) -> TrajectoryExportProfile:
    normalized = profile.strip()
    resolved = EXPORT_PROFILES.get(normalized)
    if resolved is None:
        supported = ", ".join(sorted(EXPORT_PROFILES))
        msg = (
            f"Unsupported trajectory export profile: {profile!r}. "
            f"Supported: {supported}"
        )
        raise ValueError(msg)
    return resolved


def trajectory_eligible_for_export(
    trajectory: Trajectory,
    *,
    profile: TrajectoryExportProfile,
) -> bool:
    if not trajectory.source_event_stream_digest or not trajectory.trajectory_digest:
        return False
    if trajectory.quality_tier == "routine":
        return False
    if trajectory.quality_tier not in profile.allowed_quality_tiers:
        return False
    if trajectory.outcome == "partial" and not profile.allow_partial:
        return False
    return not (trajectory.quality_tier == "incident" and not profile.allow_incident)


__all__ = [
    "EXPORT_PROFILES",
    "TRAJECTORY_EXPORT_SCHEMA_VERSION",
    "ExportProfileName",
    "TrajectoryExportProfile",
    "resolve_export_profile",
    "trajectory_eligible_for_export",
]
