# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Closed observation-contract and emitted-lane validation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final

from ..contracts import (
    API_SURFACE_SIGNATURE_VERSION,
    AUTHORITY_ANALYSIS_REVISION,
    BASELINE_FINGERPRINT_VERSION,
    BASELINE_LANE_DESCRIPTOR_VERSION,
    MODULE_IDENTITY_VERSION,
    OBSERVATION_DIGEST_VERSION,
    WIRE_VERSION,
)
from ..models import (
    ObservationContract,
    ObservationLane,
    ObservationLaneDescriptor,
    ObservationLaneName,
)


class ObservationContractError(ValueError):
    """Raised when enabled and emitted observation lanes disagree."""


_ALWAYS_ENABLED: tuple[ObservationLaneName, ...] = (
    "clones.blocks",
    "clones.functions",
    "module_identity",
)
_METRICS_ENABLED: tuple[ObservationLaneName, ...] = (
    "adoption_counts",
    "coupling_cohesion_observations",
    "risk_observations",
)
# The seven columnar lanes; anything absent stays on the record wire ("1").
_PAYLOAD_SCHEMAS: Final[Mapping[ObservationLaneName, str]] = {
    "adoption_counts": "2",
    "api_surface": "2",
    "coupling_cohesion_observations": "3",
    "dead_code": "2",
    "dependencies": "4",
    "module_identity": "3",
    "risk_observations": "3",
}


def _required_contracts(name: ObservationLaneName) -> tuple[tuple[str, str], ...]:
    if name in {"clones.blocks", "clones.functions"}:
        rows = (("BASELINE_FINGERPRINT_VERSION", BASELINE_FINGERPRINT_VERSION),)
    elif name in {"dependencies", "module_identity"}:
        rows = (("MODULE_IDENTITY_VERSION", MODULE_IDENTITY_VERSION),)
    elif name == "api_surface":
        rows = (("API_SURFACE_SIGNATURE_VERSION", API_SURFACE_SIGNATURE_VERSION),)
    elif name == "semantic_authority":
        rows = (("AUTHORITY_ANALYSIS_REVISION", AUTHORITY_ANALYSIS_REVISION),)
    else:
        rows = (("OBSERVATION_DIGEST_VERSION", OBSERVATION_DIGEST_VERSION),)
    return tuple(sorted(rows))


def _algorithm_revision(name: ObservationLaneName) -> str:
    if name in {"clones.blocks", "clones.functions"}:
        return BASELINE_FINGERPRINT_VERSION
    if name in {"dependencies", "module_identity"}:
        return MODULE_IDENTITY_VERSION
    if name == "api_surface":
        return API_SURFACE_SIGNATURE_VERSION
    if name == "semantic_authority":
        return AUTHORITY_ANALYSIS_REVISION
    return OBSERVATION_DIGEST_VERSION


def lane_payload_schema(name: ObservationLaneName) -> str:
    """Return the per-lane payload schema version — the sole owner of that fact."""

    return _PAYLOAD_SCHEMAS.get(name, "1")


def _descriptor(name: ObservationLaneName) -> ObservationLaneDescriptor:
    return ObservationLaneDescriptor(
        name=name,
        descriptor_version=BASELINE_LANE_DESCRIPTOR_VERSION,
        payload_schema=lane_payload_schema(name),
        algorithm_revision=_algorithm_revision(name),
        canonicalization_version=WIRE_VERSION,
        required_contracts=_required_contracts(name),
    )


def build_observation_contract(
    *,
    collect_metrics: bool,
    collect_dependencies: bool,
    collect_dead_code: bool,
    collect_api_surface: bool,
    collect_semantic_authority: bool,
) -> ObservationContract:
    enabled = list(_ALWAYS_ENABLED)
    if collect_metrics:
        enabled.extend(_METRICS_ENABLED)
    if collect_dependencies:
        enabled.append("dependencies")
    if collect_dead_code:
        enabled.append("dead_code")
    if collect_api_surface:
        enabled.append("api_surface")
    if collect_semantic_authority:
        enabled.append("semantic_authority")
    enabled_lanes = tuple(sorted(enabled))
    return ObservationContract(
        observation_digest_version=OBSERVATION_DIGEST_VERSION,
        enabled_lanes=enabled_lanes,
        descriptors=tuple(_descriptor(name) for name in enabled_lanes),
    )


def validate_emitted_lanes(
    contract: ObservationContract,
    lanes: Sequence[ObservationLane],
) -> None:
    actual = tuple(lane.descriptor.name for lane in lanes)
    if actual != tuple(sorted(set(actual))):
        raise ObservationContractError(
            "emitted observation lanes must be sorted and duplicate-free"
        )
    expected = contract.enabled_lanes
    if actual == expected:
        return
    missing = tuple(name for name in expected if name not in actual)
    unexpected = tuple(name for name in actual if name not in expected)
    raise ObservationContractError(
        f"observation lane set mismatch: missing={missing!r} unexpected={unexpected!r}"
    )


__all__ = [
    "ObservationContractError",
    "build_observation_contract",
    "lane_payload_schema",
    "validate_emitted_lanes",
]
