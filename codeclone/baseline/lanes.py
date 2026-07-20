# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Closed BaselineContainer v3 lane validation over 39L raw facts."""

from __future__ import annotations

from typing import Final, TypeGuard

from ..contracts import BASELINE_LANE_DESCRIPTOR_VERSION
from ..models import (
    AdoptionObservationPayload,
    ApiSurfaceObservationPayload,
    BaselineLane,
    BaselineLaneInput,
    CloneObservationPayload,
    DeadCodeObservationPayload,
    DependencyObservationPayload,
    DigestObject,
    IntegerObservationPayload,
    ModuleIdentityObservationPayload,
    ObservationLane,
    ObservationLaneDescriptor,
    ObservationLaneDescriptorInput,
    ObservationLaneName,
    SemanticAuthorityObservationPayload,
    parse_adoption_observation_payload,
    parse_api_surface_observation_payload,
    parse_clone_observation_payload,
    parse_dead_code_observation_payload,
    parse_dependency_observation_payload,
    parse_integer_observation_payload,
    parse_module_identity_observation_payload,
    parse_semantic_authority_observation_payload,
)
from .container_digest import canonical_value_bytes, compute_lane_digest_components

_LANE_NAMES: Final[frozenset[str]] = frozenset(
    {
        "adoption_counts",
        "api_surface",
        "clones.blocks",
        "clones.functions",
        "coupling_cohesion_observations",
        "dead_code",
        "dependencies",
        "module_identity",
        "risk_observations",
        "semantic_authority",
    }
)
_REQUIRED_LANES: Final[frozenset[ObservationLaneName]] = frozenset(
    {"clones.blocks", "clones.functions", "module_identity"}
)


class BaselineLaneValidationError(ValueError):
    """A known v3 lane does not match its declared closed schema."""


def is_observation_lane_name(value: str) -> TypeGuard[ObservationLaneName]:
    return value in _LANE_NAMES


def lane_is_required(name: ObservationLaneName) -> bool:
    return name in _REQUIRED_LANES


def descriptor_from_input(
    value: ObservationLaneDescriptorInput,
) -> ObservationLaneDescriptor:
    if not is_observation_lane_name(value.name):
        raise BaselineLaneValidationError(f"unknown observation lane {value.name!r}")
    return ObservationLaneDescriptor(
        name=value.name,
        descriptor_version=value.descriptor_version,
        payload_schema=value.payload_schema,
        algorithm_revision=value.algorithm_revision,
        canonicalization_version=value.canonicalization_version,
        required_contracts=value.required_contracts,
    )


def _expected_payload_schema(name: ObservationLaneName) -> str:
    return "2" if name == "module_identity" else "1"


def validate_descriptor(descriptor: ObservationLaneDescriptor) -> None:
    if descriptor.descriptor_version != BASELINE_LANE_DESCRIPTOR_VERSION:
        raise BaselineLaneValidationError(
            f"unsupported descriptor version for {descriptor.name}"
        )
    if descriptor.payload_schema != _expected_payload_schema(descriptor.name):
        raise BaselineLaneValidationError(
            f"unsupported payload schema for {descriptor.name}"
        )


def _validate_payload_round_trip(raw: object, payload: object) -> None:
    if canonical_value_bytes(raw) != canonical_value_bytes(payload):
        raise BaselineLaneValidationError(
            "lane payload must use the exact closed schema without aliases"
        )


def _validate_clone_ids(
    name: ObservationLaneName,
    payload: CloneObservationPayload,
) -> None:
    if payload.items != tuple(sorted(set(payload.items))):
        raise BaselineLaneValidationError("clone lane items must be sorted and unique")
    hex_chars = frozenset("0123456789abcdef")
    if name == "clones.functions":
        for item in payload.items:
            fingerprint, separator, bucket = item.partition("|")
            if (
                not separator
                or len(fingerprint) != 64
                or not set(fingerprint) <= hex_chars
                or not bucket
            ):
                raise BaselineLaneValidationError(
                    "function clone lane requires canonical fp-v2 IDs"
                )
            if bucket.endswith("+"):
                if not bucket[:-1].isascii() or not bucket[:-1].isdecimal():
                    raise BaselineLaneValidationError(
                        "function clone lane has an invalid location bucket"
                    )
            else:
                start, range_separator, end = bucket.partition("-")
                if not (
                    range_separator
                    and start.isascii()
                    and start.isdecimal()
                    and end.isascii()
                    and end.isdecimal()
                ):
                    raise BaselineLaneValidationError(
                        "function clone lane has an invalid location bucket"
                    )
        return
    for item in payload.items:
        parts = item.split("|")
        if len(parts) != 4 or any(
            len(part) != 64 or not set(part) <= hex_chars for part in parts
        ):
            raise BaselineLaneValidationError(
                "block clone lane requires canonical fp-v2 IDs"
            )


def payload_from_input(
    name: ObservationLaneName,
    raw: object,
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
    payload: (
        AdoptionObservationPayload
        | ApiSurfaceObservationPayload
        | CloneObservationPayload
        | DeadCodeObservationPayload
        | DependencyObservationPayload
        | IntegerObservationPayload
        | ModuleIdentityObservationPayload
        | SemanticAuthorityObservationPayload
    )
    try:
        if name in {"clones.blocks", "clones.functions"}:
            payload = parse_clone_observation_payload(raw)
            _validate_clone_ids(name, payload)
        elif name == "module_identity":
            payload = parse_module_identity_observation_payload(raw)
        elif name == "dependencies":
            payload = parse_dependency_observation_payload(raw)
        elif name == "api_surface":
            payload = parse_api_surface_observation_payload(raw)
        elif name == "dead_code":
            payload = parse_dead_code_observation_payload(raw)
        elif name in {"risk_observations", "coupling_cohesion_observations"}:
            payload = parse_integer_observation_payload(raw)
        elif name == "adoption_counts":
            payload = parse_adoption_observation_payload(raw)
        else:
            payload = parse_semantic_authority_observation_payload(raw)
    except ValueError as exc:
        raise BaselineLaneValidationError(
            f"invalid {name} lane payload: {exc}"
        ) from exc
    _validate_payload_round_trip(raw, payload)
    return payload


def build_baseline_lane(
    lane: ObservationLane,
    *,
    required: bool,
    observation_digest: DigestObject,
) -> BaselineLane:
    validate_descriptor(lane.descriptor)
    digest = compute_lane_digest_components(
        name=lane.descriptor.name,
        required=required,
        descriptor=lane.descriptor,
        payload=lane.payload,
    )
    return BaselineLane(
        name=lane.descriptor.name,
        required=required,
        descriptor=lane.descriptor,
        observation_digest=observation_digest,
        digest=digest,
        payload=lane.payload,
    )


def lane_from_input(
    name: ObservationLaneName,
    value: BaselineLaneInput,
) -> BaselineLane:
    descriptor = descriptor_from_input(value.descriptor)
    if descriptor.name != name:
        raise BaselineLaneValidationError("lane key does not match descriptor name")
    validate_descriptor(descriptor)
    if name == "module_identity" and not value.required:
        raise BaselineLaneValidationError("module_identity must remain required")
    payload = payload_from_input(name, value.payload)
    return BaselineLane(
        name=name,
        required=value.required,
        descriptor=descriptor,
        observation_digest=DigestObject(
            domain=value.observation_digest.domain,
            algorithm=value.observation_digest.algorithm,
            value=value.observation_digest.value,
        ),
        digest=DigestObject(
            domain=value.digest.domain,
            algorithm=value.digest.algorithm,
            value=value.digest.value,
        ),
        payload=payload,
    )


__all__ = [
    "BaselineLaneValidationError",
    "build_baseline_lane",
    "descriptor_from_input",
    "is_observation_lane_name",
    "lane_from_input",
    "lane_is_required",
    "payload_from_input",
    "validate_descriptor",
]
