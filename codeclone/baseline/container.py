# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Dormant native-only BaselineContainer v3 build and bounded read boundary.

Publication and runtime cutover remain owned by Phase 39N.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from uuid import UUID

from ..contracts import BASELINE_LANE_DESCRIPTOR_VERSION
from ..models import (
    BaselineContainerV3,
    BaselineContainerV3Input,
    BaselineGenerator,
    BaselineLaneIndex,
    BaselineMeta,
    BaselineReadFailureKind,
    ContainerInspectionResult,
    ContainerReadFailure,
    ContainerReadResult,
    ContainerReadSuccess,
    ContractIndex,
    DigestObject,
    DigestObjectInput,
    EpochTransitionEvidence,
    EpochTransitionEvidenceInput,
    ModuleIdentityObservationPayload,
    NativeSourceBinding,
    NativeSourceBindingInput,
    ObservationBundle,
    ObservationContract,
    ObservationContractInput,
)
from ..observability import span
from ..observations.lanes import build_observation_lanes, observation_lane_item_count
from .container_digest import (
    canonical_container_bytes,
    compute_analysis_scope_digest,
    compute_root_digest,
    lane_digest_matches,
    root_digest_matches,
)
from .lanes import (
    BaselineLaneValidationError,
    build_baseline_lane,
    descriptor_from_input,
    is_observation_lane_name,
    lane_from_input,
    lane_is_required,
)
from .trust import current_python_tag


class _DuplicateJsonKeyError(ValueError):
    pass


def _reject_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKeyError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _utc_now_z() -> str:
    return (
        datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def _package_version() -> str:
    try:
        return version("codeclone")
    except PackageNotFoundError:
        return "dev"


def _container_contracts(bundle: ObservationBundle) -> ContractIndex:
    values: dict[str, str] = {
        "BASELINE_LANE_DESCRIPTOR_VERSION": BASELINE_LANE_DESCRIPTOR_VERSION,
        "OBSERVATION_DIGEST_VERSION": bundle.contract.observation_digest_version,
    }
    for descriptor in bundle.contract.descriptors:
        for key, value in descriptor.required_contracts:
            existing = values.get(key)
            if existing is not None and existing != value:
                raise ValueError(f"conflicting container contract {key}")
            values[key] = value
    return ContractIndex(rows=tuple(sorted(values.items())))


def _module_identity_payload(
    container: BaselineContainerV3,
) -> ModuleIdentityObservationPayload:
    payload = container.lanes["module_identity"].payload
    if not isinstance(payload, ModuleIdentityObservationPayload):
        raise ValueError("module_identity lane has the wrong payload type")
    return payload


def _validate_container_consistency(container: BaselineContainerV3) -> None:
    module_identity = _module_identity_payload(container)
    source = container.source
    if module_identity.manifest_digest != source.module_identity_manifest_digest:
        raise ValueError("source manifest digest does not match module_identity")
    if module_identity.registry_digest != source.module_registry_digest:
        raise ValueError("source registry digest does not match module_identity")
    actual_scope = compute_analysis_scope_digest(module_identity.module_registry)
    if actual_scope != source.analysis_scope_digest:
        raise ValueError("analysis scope digest does not match module_identity")
    if any(
        lane.observation_digest != source.observation_digest
        for _name, lane in container.lanes.rows
    ):
        raise ValueError("all lanes must share the source observation digest")
    descriptor_rows = tuple(lane.descriptor for _name, lane in container.lanes.rows)
    if descriptor_rows != container.observation_contract.descriptors:
        raise ValueError("container and lane descriptors are inconsistent")
    for descriptor in descriptor_rows:
        for key, value in descriptor.required_contracts:
            if container.contracts.get(key) != value:
                raise ValueError(f"container contract {key} is inconsistent")


def build_container(bundle: ObservationBundle, scope_id: UUID) -> BaselineContainerV3:
    """Build a complete native v3 container without publishing it."""

    with span(name="baseline.container.build") as build_span:
        observation_lanes = build_observation_lanes(bundle)
        lanes = tuple(
            (
                lane.descriptor.name,
                build_baseline_lane(
                    lane,
                    required=lane_is_required(lane.descriptor.name),
                    observation_digest=bundle.observation_digest,
                ),
            )
            for lane in observation_lanes
        )
        module_payload = next(
            lane.payload for _name, lane in lanes if lane.name == "module_identity"
        )
        if not isinstance(module_payload, ModuleIdentityObservationPayload):
            raise ValueError("module_identity lane has the wrong payload type")
        analyzed_paths = tuple(
            sorted(
                entry.identity.file.path
                for entry in module_payload.module_registry
                if entry.analyzed
            )
        )
        bundle_paths = tuple(identity.path for identity in bundle.analysis_scope)
        if bundle_paths != analyzed_paths:
            raise ValueError(
                "observation scope must equal the analyzed module registry subset"
            )
        source = NativeSourceBinding(
            module_identity_manifest_digest=module_payload.manifest_digest,
            module_registry_digest=module_payload.registry_digest,
            analysis_scope_digest=compute_analysis_scope_digest(
                module_payload.module_registry
            ),
            observation_digest=bundle.observation_digest,
        )
        placeholder = DigestObject(
            domain="codeclone.baseline.root.v1",
            algorithm="sha256",
            value="0" * 64,
        )
        container = BaselineContainerV3(
            format_name="codeclone-baseline",
            meta=BaselineMeta(
                container_version="3.0",
                generator=BaselineGenerator(
                    name="codeclone",
                    version=_package_version(),
                ),
                python_tag=current_python_tag(),
                created_at=_utc_now_z(),
                project_label=None,
                root_digest=placeholder,
            ),
            contracts=_container_contracts(bundle),
            baseline_scope_id=scope_id,
            observation_contract=bundle.contract,
            source=source,
            transition=None,
            lanes=BaselineLaneIndex(rows=lanes),
        )
        container = replace(
            container,
            meta=replace(container.meta, root_digest=compute_root_digest(container)),
        )
        _validate_container_consistency(container)
        build_span.set_counter("baseline_lanes", len(lanes))
        build_span.set_counter(
            "baseline_items",
            sum(observation_lane_item_count(lane) for lane in observation_lanes),
        )
        build_span.set_counter(
            "baseline_bytes",
            len(canonical_container_bytes(container)),
        )
        return container


def _digest_from_input(value: DigestObjectInput) -> DigestObject:
    return DigestObject(
        domain=value.domain,
        algorithm=value.algorithm,
        value=value.value,
    )


def _source_from_input(value: NativeSourceBindingInput) -> NativeSourceBinding:
    return NativeSourceBinding(
        module_identity_manifest_digest=_digest_from_input(
            value.module_identity_manifest_digest
        ),
        module_registry_digest=_digest_from_input(value.module_registry_digest),
        analysis_scope_digest=_digest_from_input(value.analysis_scope_digest),
        observation_digest=_digest_from_input(value.observation_digest),
    )


def _transition_from_input(
    value: EpochTransitionEvidenceInput | None,
) -> EpochTransitionEvidence | None:
    if value is None:
        return None
    return EpochTransitionEvidence(
        source_schema=value.source_schema,
        imported_lanes=value.imported_lanes,
        skipped_content=value.skipped_content,
    )


def _contract_from_input(value: ObservationContractInput) -> ObservationContract:
    names = []
    for name in value.enabled_lanes:
        if not is_observation_lane_name(name):
            raise BaselineLaneValidationError(
                "observation contract has an unknown lane"
            )
        names.append(name)
    descriptors = tuple(descriptor_from_input(item) for item in value.descriptors)
    return ObservationContract(
        observation_digest_version=value.observation_digest_version,
        enabled_lanes=tuple(names),
        descriptors=descriptors,
    )


def _read_failure(
    reason: BaselineReadFailureKind,
    detail: str,
) -> ContainerReadFailure:
    return ContainerReadFailure(reason=reason, detail=detail)


def _read_bytes(path: Path, *, limit_bytes: int) -> bytes | ContainerReadFailure:
    if limit_bytes <= 0:
        return _read_failure("too_large", "container size limit must be positive")
    try:
        size = path.stat().st_size
    except OSError as exc:
        return _read_failure("unreadable", str(exc))
    if size > limit_bytes:
        return _read_failure("too_large", "container exceeds configured size limit")
    try:
        with path.open("rb") as handle:
            raw = handle.read(limit_bytes + 1)
    except OSError as exc:
        return _read_failure("unreadable", str(exc))
    if len(raw) > limit_bytes:
        return _read_failure("too_large", "container exceeds configured size limit")
    return raw


def _validated_input(raw: bytes) -> BaselineContainerV3Input | ContainerReadFailure:
    try:
        text = raw.decode("utf-8")
        json.loads(text, object_pairs_hook=_reject_duplicate_keys)
        return BaselineContainerV3Input.model_validate_json(raw)
    except UnicodeDecodeError as exc:
        return _read_failure("invalid_json", str(exc))
    except _DuplicateJsonKeyError as exc:
        return _read_failure("invalid_json", str(exc))
    except json.JSONDecodeError as exc:
        return _read_failure("invalid_json", str(exc))
    except ValueError as exc:
        return _read_failure("invalid_container", str(exc))


def _authenticated_input(
    value: BaselineContainerV3Input,
) -> ContainerReadFailure | None:
    if value.meta.root_digest.domain != "codeclone.baseline.root.v1":
        return _read_failure("invalid_container", "wrong root digest domain")
    for name, lane in value.lanes.items():
        if lane.digest.domain != "codeclone.baseline.lane.v1":
            return _read_failure("invalid_container", f"wrong digest domain for {name}")
        if lane.observation_digest.domain != "codeclone.source-observations.v1":
            return _read_failure(
                "invalid_container", f"wrong observation digest domain for {name}"
            )
        if not lane_digest_matches(name, lane):
            return _read_failure(
                "lane_digest_mismatch", f"lane digest mismatch for {name}"
            )
    if not root_digest_matches(value):
        return _read_failure("root_digest_mismatch", "container root digest mismatch")
    return None


def _validate_raw_lane_set(
    value: BaselineContainerV3Input,
) -> ContainerReadFailure | None:
    enabled = value.observation_contract.enabled_lanes
    if enabled != tuple(sorted(set(enabled))):
        return _read_failure(
            "inconsistent_container", "enabled lane names must be sorted and unique"
        )
    lane_names = tuple(sorted(value.lanes))
    if lane_names != enabled:
        return _read_failure(
            "inconsistent_container", "lane names do not match observation contract"
        )
    descriptor_names = tuple(
        item.name for item in value.observation_contract.descriptors
    )
    if descriptor_names != enabled:
        return _read_failure(
            "inconsistent_container", "contract descriptors do not match enabled lanes"
        )
    for name, descriptor in zip(
        enabled,
        value.observation_contract.descriptors,
        strict=True,
    ):
        lane = value.lanes[name]
        descriptor_wire = descriptor.model_dump(mode="json")
        if descriptor_wire != lane.descriptor.model_dump(mode="json"):
            return _read_failure(
                "inconsistent_container", f"descriptor mismatch for lane {name}"
            )
    module_identity = value.lanes.get("module_identity")
    if module_identity is None or not module_identity.required:
        return _read_failure(
            "inconsistent_container", "module_identity must be present and required"
        )
    return None


def _container_from_input(
    value: BaselineContainerV3Input,
) -> BaselineContainerV3 | ContainerReadFailure | ContainerInspectionResult:
    if value.format != "codeclone-baseline":
        return _read_failure("unsupported_format", "unknown baseline format")
    if value.meta.container_version != "3.0":
        return _read_failure(
            "unsupported_format", "unsupported baseline container version"
        )
    if value.meta.generator.name != "codeclone":
        return _read_failure("unsupported_format", "unknown baseline generator")
    unknown = tuple(
        name for name in sorted(value.lanes) if not is_observation_lane_name(name)
    )
    unknown_required = tuple(name for name in unknown if value.lanes[name].required)
    if unknown_required:
        return _read_failure(
            "unknown_required_lane",
            f"unknown required lanes: {unknown_required!r}",
        )
    if unknown:
        return ContainerInspectionResult(
            root_digest=_digest_from_input(value.meta.root_digest),
            unknown_optional_lanes=unknown,
        )
    try:
        contract = _contract_from_input(value.observation_contract)
        lanes = BaselineLaneIndex(
            rows=tuple(
                (name, lane_from_input(name, value.lanes[name]))
                for name in contract.enabled_lanes
            )
        )
        container = BaselineContainerV3(
            format_name="codeclone-baseline",
            meta=BaselineMeta(
                container_version="3.0",
                generator=BaselineGenerator(
                    name="codeclone",
                    version=value.meta.generator.version,
                ),
                python_tag=value.meta.python_tag,
                created_at=value.meta.created_at,
                project_label=value.meta.project_label,
                root_digest=_digest_from_input(value.meta.root_digest),
            ),
            contracts=ContractIndex(rows=tuple(sorted(value.contracts.items()))),
            baseline_scope_id=value.baseline_scope_id,
            observation_contract=contract,
            source=_source_from_input(value.source),
            transition=_transition_from_input(value.transition),
            lanes=lanes,
        )
        _validate_container_consistency(container)
    except (BaselineLaneValidationError, ValueError) as exc:
        return _read_failure("inconsistent_container", str(exc))
    return container


def read_container_v3(path: Path, *, limit_bytes: int) -> ContainerReadResult:
    """Read one bounded v3 artifact; no legacy branch or publication side effect."""

    with span(name="baseline.container.read") as read_span:
        raw_or_failure = _read_bytes(path, limit_bytes=limit_bytes)
        if isinstance(raw_or_failure, ContainerReadFailure):
            read_span.set_counter("baseline_read_failures", 1)
            return raw_or_failure
        raw = raw_or_failure
        read_span.set_counter("baseline_bytes", len(raw))
        parsed = _validated_input(raw)
        if isinstance(parsed, ContainerReadFailure):
            read_span.set_counter("baseline_read_failures", 1)
            return parsed
        authentication_failure = _authenticated_input(parsed)
        if authentication_failure is not None:
            read_span.set_counter("baseline_read_failures", 1)
            if authentication_failure.reason == "root_digest_mismatch":
                read_span.set_counter("baseline_root_verification_fail", 1)
            else:
                read_span.set_counter("baseline_lane_verification_fail", 1)
            return authentication_failure
        lane_set_failure = _validate_raw_lane_set(parsed)
        if lane_set_failure is not None:
            read_span.set_counter("baseline_read_failures", 1)
            return lane_set_failure
        read_span.set_counter("baseline_root_verification_pass", 1)
        read_span.set_counter("baseline_lane_verification_pass", len(parsed.lanes))
        converted = _container_from_input(parsed)
        if isinstance(converted, (ContainerReadFailure, ContainerInspectionResult)):
            if isinstance(converted, ContainerReadFailure):
                read_span.set_counter("baseline_read_failures", 1)
            return converted
        read_span.set_counter("baseline_lanes", len(converted.lanes))
        return ContainerReadSuccess(container=converted)


__all__ = ["build_container", "read_container_v3"]
