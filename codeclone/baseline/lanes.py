# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Closed BaselineContainer v3 lane validation over 39L raw facts."""

from __future__ import annotations

from typing import Final, TypeGuard, TypeVar

from ..contracts import BASELINE_LANE_DESCRIPTOR_VERSION
from ..models import (
    AdoptionColumnarPayload,
    AdoptionCount,
    AdoptionObservationPayload,
    ApiParameterObservation,
    ApiSurfaceColumnarPayload,
    ApiSurfaceObservationPayload,
    ApiSymbolKind,
    ApiSymbolObservation,
    ApiVisibility,
    BaselineLane,
    BaselineLaneInput,
    CloneObservationPayload,
    DeadCodeCandidateKind,
    DeadCodeColumnarPayload,
    DeadCodeObservation,
    DeadCodeObservationPayload,
    DependencyColumnarPayload,
    DependencyObservationPayload,
    DependencyResolution,
    DigestObject,
    ImportObservation,
    ImportSyntaxKind,
    IntegerColumnarPayload,
    IntegerObservation,
    IntegerObservationPayload,
    ModuleIdentityColumnarPayload,
    ModuleIdentityObservationPayload,
    ModuleInventoryEntry,
    ObservationLane,
    ObservationLaneDescriptor,
    ObservationLaneDescriptorInput,
    ObservationLaneName,
    OpaqueLanePayload,
    ResolvedSourceIdentity,
    SemanticAuthorityObservationPayload,
    parse_adoption_columnar_payload,
    parse_api_surface_columnar_payload,
    parse_clone_observation_payload,
    parse_dead_code_columnar_payload,
    parse_dependency_columnar_payload,
    parse_integer_columnar_payload,
    parse_module_identity_columnar_payload,
    parse_semantic_authority_observation_payload,
)
from ..observations.contracts import lane_payload_schema
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


_Narrowed = TypeVar("_Narrowed", bound=str)


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


def validate_descriptor(descriptor: ObservationLaneDescriptor) -> None:
    """Check one descriptor for internal consistency only.

    Schema currency is deliberately *not* checked here: an artifact is read
    against its own recorded descriptors, and a lane whose payload schema is
    no longer the current one is kept opaque and reported by lane trust.
    """

    if descriptor.descriptor_version != BASELINE_LANE_DESCRIPTOR_VERSION:
        raise BaselineLaneValidationError(
            f"unsupported descriptor version for {descriptor.name}"
        )


def lane_payload_is_opaque(lane: BaselineLane) -> bool:
    """Return whether the lane payload was left unparsed by the reader."""

    return isinstance(lane.payload, dict)


def decode_integer_lane(payload: IntegerColumnarPayload) -> IntegerObservationPayload:
    """Rebuild the typed integer observations from their columnar wire form."""

    return IntegerObservationPayload(
        observations=tuple(
            IntegerObservation(
                source=payload.identities.identity(payload.identity[row]),
                qualname=payload.qualnames[payload.qualname[row]],
                dimension=payload.dimensions[payload.dimension[row]],
                numerator=payload.numerator[row],
            )
            for row in range(len(payload.identity))
        ),
        entity_population=payload.entity_population,
    )


def decode_adoption_lane(
    payload: AdoptionColumnarPayload,
) -> AdoptionObservationPayload:
    """Rebuild the typed adoption counts from their columnar wire form."""

    return AdoptionObservationPayload(
        counts=tuple(
            AdoptionCount(
                scope=payload.scopes[payload.scope[row]],
                feature=payload.features[payload.feature[row]],
                numerator=payload.numerator[row],
                denominator=payload.denominator[row],
            )
            for row in range(len(payload.scope))
        )
    )


def decode_dead_code_lane(
    payload: DeadCodeColumnarPayload,
) -> DeadCodeObservationPayload:
    """Rebuild the typed dead-code candidates from their columnar wire form."""

    reachable = frozenset(payload.reachable_true)
    markers = {item.row: item for item in payload.markers}
    return DeadCodeObservationPayload(
        candidates=tuple(
            DeadCodeObservation(
                entity=f"{payload.prefixes[payload.prefix[row]]}:{payload.qualname[row]}",
                candidate_kind=_narrowed(
                    payload.kinds[payload.kind[row]],
                    _DEAD_CODE_KINDS,
                    "dead-code candidate kind",
                ),
                reference_count=payload.reference_count[row],
                reachable=row in reachable,
                runtime_marker_count=(
                    markers[row].runtime_marker_count if row in markers else 0
                ),
                source_markers=(markers[row].source_markers if row in markers else ()),
            )
            for row in range(len(payload.prefix))
        )
    )


def decode_api_surface_lane(
    payload: ApiSurfaceColumnarPayload,
) -> ApiSurfaceObservationPayload:
    """Rebuild the typed api symbols from their columnar wire form."""

    meta = payload.digest_meta

    def digest(reference: int | None) -> DigestObject | None:
        if reference is None or meta is None:
            return None
        return DigestObject(
            domain=meta.domain,
            algorithm=meta.algorithm,
            value=payload.digests[reference],
        )

    parameters = tuple(
        tuple(
            ApiParameterObservation(
                name=payload.parameter_defs[reference].name,
                kind=payload.parameter_defs[reference].kind,
                has_default=payload.parameter_defs[reference].has_default,
                annotation_digest=digest(
                    payload.parameter_defs[reference].annotation_digest
                ),
            )
            for reference in definition_list
        )
        for definition_list in payload.parameter_lists
    )
    return ApiSurfaceObservationPayload(
        symbols=tuple(
            ApiSymbolObservation(
                owner=payload.identities.identity(payload.owner[row]),
                symbol=_api_symbol(
                    payload.identities.identity(payload.owner[row]), payload.name[row]
                ),
                symbol_kind=_narrowed(
                    payload.symbol_kinds[payload.symbol_kind[row]],
                    _API_SYMBOL_KINDS,
                    "api symbol kind",
                ),
                visibility=_narrowed(
                    payload.visibilities[payload.visibility[row]],
                    _API_VISIBILITIES,
                    "api visibility",
                ),
                parameters=parameters[payload.parameters[row]],
                returns_digest=digest(payload.returns_digest[row]),
            )
            for row in range(len(payload.owner))
        )
    )


def _api_symbol(owner: ResolvedSourceIdentity, name: str) -> str:
    module = owner.python_module
    return f"{module.module}:{name}" if module is not None else name


_DEAD_CODE_KINDS: Final[tuple[DeadCodeCandidateKind, ...]] = (
    "class",
    "function",
    "import",
    "method",
)
_API_SYMBOL_KINDS: Final[tuple[ApiSymbolKind, ...]] = (
    "class",
    "constant",
    "function",
    "method",
)
_API_VISIBILITIES: Final[tuple[ApiVisibility, ...]] = ("all", "name")
_SYNTAX_KINDS: Final[tuple[ImportSyntaxKind, ...]] = ("from_import", "import")
_RESOLUTIONS: Final[tuple[DependencyResolution, ...]] = (
    "analyzed",
    "external",
    "known_internal_not_analyzed",
    "unresolved_relative",
)


def _narrowed(
    value: str,
    vocabulary: tuple[_Narrowed, ...],
    label: str,
) -> _Narrowed:
    """Map one wire string back to its closed vocabulary, or fail typed."""

    for allowed in vocabulary:
        if allowed == value:
            return allowed
    raise BaselineLaneValidationError(f"unknown {label} {value!r}")


def decode_dependency_lane(
    payload: DependencyColumnarPayload,
) -> DependencyObservationPayload:
    """Rebuild the typed import observations from their columnar wire form."""

    expanded = frozenset(payload.inventory_expansion)

    def module(reference: int | None) -> str | None:
        return None if reference is None else payload.modules[reference]

    return DependencyObservationPayload(
        observations=tuple(
            ImportObservation(
                source=payload.identities.identity(payload.source[row]),
                syntax_kind=_narrowed(
                    payload.syntax_kinds[payload.syntax_kind[row]],
                    _SYNTAX_KINDS,
                    "import syntax kind",
                ),
                level=payload.level[row],
                requested_module=module(payload.requested_module[row]),
                requested_names=tuple(
                    payload.modules[name] for name in payload.requested_names[row]
                ),
                resolution=_narrowed(
                    payload.resolutions[payload.resolution[row]],
                    _RESOLUTIONS,
                    "dependency resolution",
                ),
                candidate_targets=_candidate_targets(
                    module(payload.resolved_target[row]),
                    module(payload.requested_module[row]),
                ),
                resolved_target=module(payload.resolved_target[row]),
                inventory_expansion=row in expanded,
            )
            for row in range(len(payload.source))
        )
    )


def _candidate_targets(resolved: str | None, requested: str | None) -> tuple[str, ...]:
    """Derive the candidate targets the wire no longer stores."""

    if resolved is not None:
        return (resolved,)
    return () if requested is None else (requested,)


def decode_module_identity_lane(
    payload: ModuleIdentityColumnarPayload,
) -> ModuleIdentityObservationPayload:
    """Rebuild the typed registry entries from their columnar wire form."""

    overrides = {item.row: item for item in payload.other}
    entries = tuple(
        ModuleInventoryEntry(
            identity=payload.identities.identity(row),
            analyzed=overrides[row].analyzed if row in overrides else True,
            internality=(
                overrides[row].internality if row in overrides else "analyzed"
            ),
        )
        for row in range(len(payload.identities.paths))
    )
    return ModuleIdentityObservationPayload(
        manifest=payload.manifest,
        manifest_digest=payload.manifest_digest,
        module_registry=entries,
        package_prefixes=payload.package_prefixes,
        registry_digest=payload.registry_digest,
        entry_count=len(entries),
        null_module_count=len(payload.identities.module_null),
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
    AdoptionColumnarPayload
    | ApiSurfaceColumnarPayload
    | CloneObservationPayload
    | DeadCodeColumnarPayload
    | DependencyColumnarPayload
    | IntegerColumnarPayload
    | ModuleIdentityColumnarPayload
    | SemanticAuthorityObservationPayload
):
    payload: (
        AdoptionColumnarPayload
        | ApiSurfaceColumnarPayload
        | CloneObservationPayload
        | DeadCodeColumnarPayload
        | DependencyColumnarPayload
        | IntegerColumnarPayload
        | ModuleIdentityColumnarPayload
        | SemanticAuthorityObservationPayload
    )
    try:
        if name in {"clones.blocks", "clones.functions"}:
            payload = parse_clone_observation_payload(raw)
            _validate_clone_ids(name, payload)
        elif name == "module_identity":
            payload = parse_module_identity_columnar_payload(raw)
        elif name == "dependencies":
            payload = parse_dependency_columnar_payload(raw)
        elif name == "api_surface":
            payload = parse_api_surface_columnar_payload(raw)
        elif name == "dead_code":
            payload = parse_dead_code_columnar_payload(raw)
        elif name in {"risk_observations", "coupling_cohesion_observations"}:
            payload = parse_integer_columnar_payload(raw)
        elif name == "adoption_counts":
            payload = parse_adoption_columnar_payload(raw)
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
    payload: (
        AdoptionColumnarPayload
        | ApiSurfaceColumnarPayload
        | CloneObservationPayload
        | DeadCodeColumnarPayload
        | DependencyColumnarPayload
        | IntegerColumnarPayload
        | ModuleIdentityColumnarPayload
        | SemanticAuthorityObservationPayload
        | OpaqueLanePayload
    )
    if descriptor.payload_schema != lane_payload_schema(name):
        # Outdated schema: keep the recorded bytes, do not parse them into a
        # model that no longer describes them. Lane trust reports the state.
        if not isinstance(value.payload, dict):
            raise BaselineLaneValidationError(
                f"lane payload for {name} must be a JSON object"
            )
        payload = value.payload
    else:
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
    "decode_adoption_lane",
    "decode_api_surface_lane",
    "decode_dead_code_lane",
    "decode_dependency_lane",
    "decode_integer_lane",
    "decode_module_identity_lane",
    "descriptor_from_input",
    "is_observation_lane_name",
    "lane_from_input",
    "lane_is_required",
    "lane_payload_is_opaque",
    "payload_from_input",
    "validate_descriptor",
]
