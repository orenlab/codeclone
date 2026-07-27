# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Reader-side trust projection for authenticated BaselineContainer v3 facts."""

from __future__ import annotations

import hmac
from typing import TypeVar
from uuid import UUID

from ..contracts.errors import BaselineValidationError
from ..models import (
    BaselineContainerV3,
    BaselineLane,
    LaneTrust,
    LaneTrustReason,
    ObservationLaneDescriptor,
    RuntimeContracts,
    TrustVector,
)
from ..observability import span
from ..observations.contracts import build_observation_contract
from .container_digest import compute_lane_digest, compute_root_digest
from .lanes import lane_payload_is_opaque

_StatusT = TypeVar("_StatusT")


def _runtime_descriptor(
    runtime: RuntimeContracts,
    lane: BaselineLane,
) -> ObservationLaneDescriptor | None:
    for descriptor in runtime.lane_descriptors:
        if descriptor.name == lane.name:
            return descriptor
    return None


def _semantic_reason(
    lane: BaselineLane,
    runtime: RuntimeContracts,
) -> LaneTrustReason:
    expected = _runtime_descriptor(runtime, lane)
    if expected is None:
        return "runtime_lane_unknown"
    actual = lane.descriptor
    if actual.descriptor_version != expected.descriptor_version:
        return "descriptor_version"
    if actual.payload_schema != expected.payload_schema:
        # The reader keeps an outdated lane opaque instead of failing the whole
        # container; say so, so the operator reads "regenerate", not "corrupt".
        if lane_payload_is_opaque(lane):
            return "payload_schema_outdated"
        return "payload_schema"
    if actual.algorithm_revision != expected.algorithm_revision:
        return "algorithm_revision"
    if actual.canonicalization_version != expected.canonicalization_version:
        return "canonicalization_version"
    expected_contracts = dict(expected.required_contracts)
    if any(
        expected_contracts.get(key) != value for key, value in actual.required_contracts
    ):
        return "required_contract"
    return "compatible"


def _lane_trust(
    lane: BaselineLane,
    runtime: RuntimeContracts,
    *,
    python_matches: bool,
) -> LaneTrust:
    if not hmac.compare_digest(compute_lane_digest(lane).value, lane.digest.value):
        return LaneTrust(
            name=lane.name,
            status="unavailable",
            reason="lane_digest_mismatch",
        )
    if not python_matches:
        return LaneTrust(name=lane.name, status="unavailable", reason="python_tag")
    reason = _semantic_reason(lane, runtime)
    return LaneTrust(
        name=lane.name,
        status="trusted" if reason == "compatible" else "unavailable",
        reason=reason,
    )


def evaluate_lane_trust(
    container: BaselineContainerV3,
    runtime: RuntimeContracts,
) -> TrustVector:
    """Verify root first, then project independent semantic lane trust."""

    with span(name="baseline.container.trust") as trust_span:
        root_verified = hmac.compare_digest(
            compute_root_digest(container).value,
            container.meta.root_digest.value,
        )
        if not root_verified:
            lanes = tuple(
                LaneTrust(
                    name=name,
                    status="unavailable",
                    reason="root_digest_mismatch",
                )
                for name in container.lanes
            )
            trust_span.set_counter("baseline_root_verification_fail", 1)
            trust_span.set_counter("baseline_compatibility_fail", len(lanes))
            return TrustVector(root_verified=False, lanes=lanes)
        scope_matches = container.baseline_scope_id == runtime.baseline_scope_id
        if not scope_matches:
            lanes = tuple(
                LaneTrust(
                    name=name,
                    status="unavailable",
                    reason="baseline_scope_id",
                )
                for name in container.lanes
            )
            trust_span.set_counter("baseline_compatibility_fail", len(lanes))
            return TrustVector(root_verified=True, lanes=lanes)
        python_matches = container.meta.python_tag == runtime.python_tag
        lanes = tuple(
            _lane_trust(lane, runtime, python_matches=python_matches)
            for _name, lane in container.lanes.rows
        )
        trusted_count = sum(item.status == "trusted" for item in lanes)
        trust_span.set_counter("baseline_root_verification_pass", 1)
        trust_span.set_counter("baseline_compatibility_pass", trusted_count)
        trust_span.set_counter(
            "baseline_compatibility_fail",
            len(lanes) - trusted_count,
        )
        return TrustVector(root_verified=True, lanes=lanes)


def evaluate_container_trust(
    container: BaselineContainerV3,
    *,
    python_tag: str,
    baseline_scope_id: UUID,
) -> TrustVector:
    """Evaluate one container against the current runtime contract projection."""

    return evaluate_lane_trust(
        container,
        runtime_contracts_for_container(
            container,
            python_tag=python_tag,
            baseline_scope_id=baseline_scope_id,
        ),
    )


def map_container_read_failure(
    reason: str,
    *,
    too_large: _StatusT,
    invalid_json: _StatusT,
    integrity_failed: _StatusT,
    schema_mismatch: _StatusT,
    invalid_type: _StatusT,
) -> _StatusT:
    """Map the sole reader's failure vocabulary to one surface status enum."""

    if reason == "too_large":
        return too_large
    if reason == "invalid_json":
        return invalid_json
    if reason in {"lane_digest_mismatch", "root_digest_mismatch"}:
        return integrity_failed
    if reason == "unsupported_format":
        return schema_mismatch
    return invalid_type


def unavailable_container_lanes(
    container: BaselineContainerV3 | None,
    *,
    python_tag: str,
    baseline_scope_id: UUID,
    missing_message: str,
    missing_status: str,
    root_message: str,
    integrity_status: str,
) -> tuple[LaneTrust, ...]:
    """Require a root-authenticated container and return unavailable lanes."""

    if container is None:
        raise BaselineValidationError(missing_message, status=missing_status)
    vector = evaluate_container_trust(
        container,
        python_tag=python_tag,
        baseline_scope_id=baseline_scope_id,
    )
    if not vector.root_verified:
        raise BaselineValidationError(root_message, status=integrity_status)
    return tuple(item for item in vector.lanes if item.status != "trusted")


def runtime_contracts_for_container(
    container: BaselineContainerV3,
    *,
    python_tag: str,
    baseline_scope_id: UUID,
) -> RuntimeContracts:
    """Build current-runtime descriptors for the lane set persisted in a container."""

    names = set(container.lanes)
    contract = build_observation_contract(
        collect_metrics=bool(
            names
            & {
                "adoption_counts",
                "coupling_cohesion_observations",
                "risk_observations",
            }
        ),
        collect_dependencies="dependencies" in names,
        collect_dead_code="dead_code" in names,
        collect_api_surface="api_surface" in names,
        collect_semantic_authority="semantic_authority" in names,
    )
    return RuntimeContracts(
        python_tag=python_tag,
        baseline_scope_id=baseline_scope_id,
        lane_descriptors=contract.descriptors,
    )


__all__ = [
    "evaluate_container_trust",
    "evaluate_lane_trust",
    "map_container_read_failure",
    "runtime_contracts_for_container",
    "unavailable_container_lanes",
]
