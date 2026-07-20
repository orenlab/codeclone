# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Canonical BaselineContainer v3 wire and digest ownership."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from typing import Literal

from ..cache.integrity import canonical_json
from ..contracts import BASELINE_LANE_DIGEST_DOMAIN, BASELINE_ROOT_DIGEST_DOMAIN
from ..models import (
    BaselineContainerV3,
    BaselineContainerV3Input,
    BaselineLane,
    BaselineLaneInput,
    DigestObject,
    DigestObjectInput,
    ModuleInventoryEntry,
    ObservationLaneDescriptor,
    ObservationLaneDescriptorInput,
)

_ANALYSIS_SCOPE_DIGEST_DOMAIN = b"codeclone.analysis-scope.v1\0"


def _canonical_bytes(value: object) -> bytes:
    return canonical_json(_json_ready(value)).encode("utf-8")


def canonical_value_bytes(value: object) -> bytes:
    """Normalize one v3 component with the container's sole JSON rules."""

    return _canonical_bytes(value)


def _json_ready(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return _json_ready(asdict(value))
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


def _digest(
    *,
    prefix: bytes,
    document: object,
    domain: Literal[
        "codeclone.analysis-scope.v1",
        "codeclone.baseline.lane.v1",
        "codeclone.baseline.root.v1",
    ],
) -> DigestObject:
    digest = hashlib.sha256()
    digest.update(prefix)
    digest.update(_canonical_bytes(document))
    return DigestObject(domain=domain, algorithm="sha256", value=digest.hexdigest())


def _digest_document(value: DigestObject | DigestObjectInput) -> object:
    if isinstance(value, DigestObjectInput):
        return value.model_dump(mode="json")
    return _json_ready(value)


def _descriptor_document(
    value: ObservationLaneDescriptor | ObservationLaneDescriptorInput,
) -> object:
    if isinstance(value, ObservationLaneDescriptorInput):
        return value.model_dump(mode="json")
    return _json_ready(value)


def compute_analysis_scope_digest(
    entries: Sequence[ModuleInventoryEntry],
) -> DigestObject:
    """Bind exactly the canonical analyzed FileIdentity path set."""

    paths = tuple(
        sorted(entry.identity.file.path for entry in entries if entry.analyzed)
    )
    if paths != tuple(sorted(set(paths))):
        raise ValueError("analyzed module inventory paths must be unique")
    return _digest(
        prefix=_ANALYSIS_SCOPE_DIGEST_DOMAIN,
        document={"paths": paths},
        domain="codeclone.analysis-scope.v1",
    )


def compute_lane_digest_components(
    *,
    name: str,
    required: bool,
    descriptor: ObservationLaneDescriptor | ObservationLaneDescriptorInput,
    payload: object,
) -> DigestObject:
    """Hash one lane under the sole v1 lane-digest domain."""

    document = {
        "name": name,
        "required": required,
        "descriptor": _descriptor_document(descriptor),
        "payload": payload,
    }
    return _digest(
        prefix=BASELINE_LANE_DIGEST_DOMAIN.encode("utf-8"),
        document=document,
        domain="codeclone.baseline.lane.v1",
    )


def compute_lane_digest(lane: BaselineLane) -> DigestObject:
    return compute_lane_digest_components(
        name=lane.name,
        required=lane.required,
        descriptor=lane.descriptor,
        payload=lane.payload,
    )


def _lane_identity_document(
    *,
    required: bool,
    descriptor: ObservationLaneDescriptor | ObservationLaneDescriptorInput,
    observation_digest: DigestObject | DigestObjectInput,
    digest: DigestObject | DigestObjectInput,
) -> dict[str, object]:
    return {
        "required": required,
        "descriptor": _descriptor_document(descriptor),
        "observation_digest": _digest_document(observation_digest),
        "digest": _digest_document(digest),
    }


def _root_digest(
    *,
    format_name: str,
    container_version: str,
    generator_name: str,
    python_tag: str,
    contracts: Mapping[str, str],
    baseline_scope_id: str,
    observation_contract: object,
    source: object,
    transition: object,
    lane_identities: Mapping[str, object],
) -> DigestObject:
    document = {
        "format": format_name,
        "container_version": container_version,
        "generator_name": generator_name,
        "python_tag": python_tag,
        "contracts": dict(sorted(contracts.items())),
        "baseline_scope_id": baseline_scope_id,
        "observation_contract": observation_contract,
        "source": source,
        "transition": transition,
        "lanes": {name: lane_identities[name] for name in sorted(lane_identities)},
    }
    return _digest(
        prefix=BASELINE_ROOT_DIGEST_DOMAIN.encode("utf-8"),
        document=document,
        domain="codeclone.baseline.root.v1",
    )


def compute_root_digest(container: BaselineContainerV3) -> DigestObject:
    lane_identities: dict[str, object] = {
        name: _lane_identity_document(
            required=lane.required,
            descriptor=lane.descriptor,
            observation_digest=lane.observation_digest,
            digest=lane.digest,
        )
        for name, lane in container.lanes.rows
    }
    return _root_digest(
        format_name=container.format_name,
        container_version=container.meta.container_version,
        generator_name=container.meta.generator.name,
        python_tag=container.meta.python_tag,
        contracts=container.contracts,
        baseline_scope_id=str(container.baseline_scope_id),
        observation_contract=container.observation_contract,
        source=container.source,
        transition=container.transition,
        lane_identities=lane_identities,
    )


def compute_input_root_digest(container: BaselineContainerV3Input) -> DigestObject:
    lane_identities: dict[str, object] = {
        name: _lane_identity_document(
            required=lane.required,
            descriptor=lane.descriptor,
            observation_digest=lane.observation_digest,
            digest=lane.digest,
        )
        for name, lane in container.lanes.items()
    }
    transition = (
        None
        if container.transition is None
        else container.transition.model_dump(mode="json")
    )
    return _root_digest(
        format_name=container.format,
        container_version=container.meta.container_version,
        generator_name=container.meta.generator.name,
        python_tag=container.meta.python_tag,
        contracts=container.contracts,
        baseline_scope_id=str(container.baseline_scope_id),
        observation_contract=container.observation_contract.model_dump(mode="json"),
        source=container.source.model_dump(mode="json"),
        transition=transition,
        lane_identities=lane_identities,
    )


def lane_digest_matches(name: str, lane: BaselineLaneInput) -> bool:
    actual = compute_lane_digest_components(
        name=name,
        required=lane.required,
        descriptor=lane.descriptor,
        payload=lane.payload,
    )
    return hmac.compare_digest(actual.value, lane.digest.value)


def root_digest_matches(container: BaselineContainerV3Input) -> bool:
    actual = compute_input_root_digest(container)
    return hmac.compare_digest(actual.value, container.meta.root_digest.value)


def lane_document(lane: BaselineLane) -> dict[str, object]:
    return {
        "required": lane.required,
        "descriptor": lane.descriptor,
        "observation_digest": lane.observation_digest,
        "digest": lane.digest,
        "payload": lane.payload,
    }


def container_document(container: BaselineContainerV3) -> dict[str, object]:
    """Return the sole canonical v3 JSON projection consumed by 39N."""

    return {
        "format": container.format_name,
        "meta": {
            "container_version": container.meta.container_version,
            "generator": container.meta.generator,
            "python_tag": container.meta.python_tag,
            "created_at": container.meta.created_at,
            "project_label": container.meta.project_label,
            "root_digest": container.meta.root_digest,
        },
        "contracts": dict(container.contracts.items()),
        "baseline_scope_id": str(container.baseline_scope_id),
        "observation_contract": container.observation_contract,
        "source": container.source,
        "transition": container.transition,
        "lanes": {name: lane_document(lane) for name, lane in container.lanes.rows},
    }


def canonical_container_bytes(container: BaselineContainerV3) -> bytes:
    return _canonical_bytes(container_document(container))


__all__ = [
    "canonical_container_bytes",
    "compute_analysis_scope_digest",
    "compute_input_root_digest",
    "compute_lane_digest",
    "compute_lane_digest_components",
    "compute_root_digest",
    "container_document",
    "lane_digest_matches",
    "root_digest_matches",
]
