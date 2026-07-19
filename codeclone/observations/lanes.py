# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Deterministic raw-lane projection from one observation bundle."""

from __future__ import annotations

import orjson

from ..models import (
    AdoptionObservationPayload,
    ApiSurfaceObservationPayload,
    CloneObservationPayload,
    DeadCodeObservationPayload,
    DependencyObservationPayload,
    IntegerObservationPayload,
    ModuleIdentityObservationPayload,
    ObservationBundle,
    ObservationLane,
    ObservationLaneDescriptor,
    SemanticAuthorityObservationPayload,
)
from .contracts import ObservationContractError, validate_emitted_lanes


def _module_identity_payload(
    bundle: ObservationBundle,
) -> ModuleIdentityObservationPayload:
    entries = tuple(entry for _path, entry in bundle.registry.entries_by_path.rows)
    return ModuleIdentityObservationPayload(
        manifest=bundle.manifest,
        module_registry=entries,
        package_prefixes=bundle.registry.package_prefixes,
        registry_digest=bundle.registry.digest,
        entry_count=len(entries),
        null_module_count=sum(
            entry.identity.python_module is None for entry in entries
        ),
    )


def _lane_payload(
    bundle: ObservationBundle,
    descriptor: ObservationLaneDescriptor,
) -> (
    AdoptionObservationPayload
    | ApiSurfaceObservationPayload
    | CloneObservationPayload
    | DeadCodeObservationPayload
    | DependencyObservationPayload
    | IntegerObservationPayload
    | ModuleIdentityObservationPayload
    | SemanticAuthorityObservationPayload
):
    facts = bundle.structural
    name = descriptor.name
    if name == "clones.functions":
        return CloneObservationPayload(items=facts.function_clone_keys)
    if name == "clones.blocks":
        return CloneObservationPayload(items=facts.block_clone_keys)
    if name == "module_identity":
        return _module_identity_payload(bundle)
    if name == "dependencies":
        return DependencyObservationPayload(observations=facts.dependencies)
    if name == "api_surface":
        return ApiSurfaceObservationPayload(symbols=facts.api_surface)
    if name == "dead_code":
        return DeadCodeObservationPayload(candidates=facts.dead_code)
    if name == "risk_observations":
        return IntegerObservationPayload(observations=facts.risk_observations)
    if name == "adoption_counts":
        return AdoptionObservationPayload(counts=facts.adoption_counts)
    if name == "coupling_cohesion_observations":
        return IntegerObservationPayload(
            observations=facts.coupling_cohesion_observations
        )
    if bundle.semantic is None:
        raise ObservationContractError(
            "semantic_authority lane requires the accepted semantic result"
        )
    return SemanticAuthorityObservationPayload(result=bundle.semantic)


def build_observation_lanes(
    bundle: ObservationBundle,
) -> tuple[ObservationLane, ...]:
    """Build the closed enabled-lane set in canonical name order."""

    lanes = tuple(
        ObservationLane(
            descriptor=descriptor,
            payload=_lane_payload(bundle, descriptor),
        )
        for descriptor in bundle.contract.descriptors
    )
    validate_emitted_lanes(bundle.contract, lanes)
    return lanes


def canonical_observation_lane_bytes(lane: ObservationLane) -> bytes:
    """Return deterministic raw-lane bytes without assigning lane identity."""

    return orjson.dumps(lane, option=orjson.OPT_SORT_KEYS)


def observation_lane_item_count(lane: ObservationLane) -> int:
    payload = lane.payload
    if isinstance(payload, CloneObservationPayload):
        return len(payload.items)
    if isinstance(payload, ModuleIdentityObservationPayload):
        return payload.entry_count
    if isinstance(payload, DependencyObservationPayload):
        return len(payload.observations)
    if isinstance(payload, ApiSurfaceObservationPayload):
        return len(payload.symbols)
    if isinstance(payload, DeadCodeObservationPayload):
        return len(payload.candidates)
    if isinstance(payload, IntegerObservationPayload):
        return len(payload.observations)
    if isinstance(payload, AdoptionObservationPayload):
        return len(payload.counts)
    return len(payload.result.sinks) + len(payload.result.candidates)


__all__ = [
    "build_observation_lanes",
    "canonical_observation_lane_bytes",
    "observation_lane_item_count",
]
