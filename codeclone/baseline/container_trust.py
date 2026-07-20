# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Reader-side trust projection for authenticated BaselineContainer v3 facts."""

from __future__ import annotations

import hmac

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
from .container_digest import compute_lane_digest, compute_root_digest


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


__all__ = ["evaluate_lane_trust"]
