# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Static capability registry for setup readiness (§8.1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal

from .....baseline import BaselineStatus
from .....config.pyproject_loader import ConfigValidationError
from .....memory.status_report import MemoryStatusReport

Availability = Literal[
    "built_in",
    "optional_extra",
    "external_tool",
    "unsupported",
]
CapabilityGroup = Literal[
    "core_analysis",
    "governed_agent_workflows",
    "project_knowledge",
    "team_and_release",
]

GROUP_ORDER: Final[tuple[CapabilityGroup, ...]] = (
    "core_analysis",
    "governed_agent_workflows",
    "project_knowledge",
    "team_and_release",
)

SETUP_EXTRA_NAMES: Final[tuple[str, ...]] = (
    "analytics",
    "coverage-xml",
    "mcp",
    "perf",
    "semantic-fastembed",
    "semantic-lancedb",
    "semantic-local",
    "token-bench",
)

InstallationAxis = Literal["installed", "missing", "unknown"]
ConfigurationAxis = Literal["configured", "unconfigured", "invalid", "not_required"]
RuntimeAxis = Literal["verified", "unavailable", "not_verified", "not_required"]


@dataclass(slots=True)
class CapabilityAxes:
    installation: InstallationAxis = "installed"
    configuration: ConfigurationAxis = "not_required"
    runtime: RuntimeAxis = "not_required"
    evidence: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DiscoverContext:
    root_path: Path
    config: dict[str, object]
    config_error: ConfigValidationError | None
    has_codeclone_section: bool
    baseline_path: Path
    baseline_status: BaselineStatus | None
    head_commit: str | None
    install_extras: dict[str, str]
    mcp_installed: bool
    memory_report: MemoryStatusReport | None = None
    audit_enabled: bool = False
    audit_db_exists: bool = False
    audit_summary_events: int = 0
    gitignore_covers_cache: bool = False
    client_config_present: bool = False


@dataclass(frozen=True, slots=True)
class ProbedCapability:
    meta: CapabilityMeta
    axes: CapabilityAxes


@dataclass(frozen=True, slots=True)
class CapabilityMeta:
    id: str
    group: CapabilityGroup
    availability: Availability
    requires_config: bool = False
    requires_runtime_proof: bool = False
    optional_extra_name: str | None = None


CAPABILITY_REGISTRY: Final[tuple[CapabilityMeta, ...]] = (
    CapabilityMeta(
        id="analysis",
        group="core_analysis",
        availability="built_in",
        requires_config=True,
    ),
    CapabilityMeta(
        id="baseline",
        group="core_analysis",
        availability="built_in",
        requires_config=True,
    ),
    CapabilityMeta(
        id="reports",
        group="core_analysis",
        availability="built_in",
    ),
    CapabilityMeta(
        id="mcp_runtime",
        group="governed_agent_workflows",
        availability="optional_extra",
        optional_extra_name="mcp",
    ),
    CapabilityMeta(
        id="controlled_change",
        group="governed_agent_workflows",
        availability="optional_extra",
        optional_extra_name="mcp",
        requires_config=True,
    ),
    CapabilityMeta(
        id="audit_and_intents",
        group="governed_agent_workflows",
        availability="built_in",
        requires_config=True,
    ),
    CapabilityMeta(
        id="engineering_memory",
        group="project_knowledge",
        availability="built_in",
        requires_config=True,
    ),
    CapabilityMeta(
        id="semantic_retrieval",
        group="project_knowledge",
        availability="optional_extra",
        optional_extra_name="semantic-local",
        requires_config=True,
    ),
    CapabilityMeta(
        id="coverage_evidence",
        group="project_knowledge",
        availability="optional_extra",
        optional_extra_name="coverage-xml",
    ),
    CapabilityMeta(
        id="analytics_cockpit",
        group="project_knowledge",
        availability="optional_extra",
        optional_extra_name="analytics",
    ),
    CapabilityMeta(
        id="ci_policy",
        group="team_and_release",
        availability="built_in",
        requires_config=True,
    ),
    CapabilityMeta(
        id="github_workflow",
        group="team_and_release",
        availability="external_tool",
        requires_config=True,
    ),
    CapabilityMeta(
        id="pre_commit_hook",
        group="team_and_release",
        availability="external_tool",
        requires_config=True,
    ),
    CapabilityMeta(
        id="workspace_hygiene",
        group="team_and_release",
        availability="built_in",
        requires_config=True,
    ),
)


def sorted_capabilities() -> tuple[CapabilityMeta, ...]:
    group_rank = {group: index for index, group in enumerate(GROUP_ORDER)}
    return tuple(
        sorted(
            CAPABILITY_REGISTRY,
            key=lambda item: (group_rank[item.group], item.id),
        )
    )


__all__ = [
    "CAPABILITY_REGISTRY",
    "GROUP_ORDER",
    "SETUP_EXTRA_NAMES",
    "Availability",
    "CapabilityAxes",
    "CapabilityGroup",
    "CapabilityMeta",
    "ConfigurationAxis",
    "DiscoverContext",
    "InstallationAxis",
    "ProbedCapability",
    "RuntimeAxis",
    "sorted_capabilities",
]
