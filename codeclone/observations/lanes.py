# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Deterministic raw-lane projection from one observation bundle."""

from __future__ import annotations

from collections.abc import Sequence

import orjson

from ..models import (
    AdoptionColumnarPayload,
    AdoptionCount,
    ApiParameterDef,
    ApiParameterObservation,
    ApiSurfaceColumnarPayload,
    ApiSymbolObservation,
    CloneObservationPayload,
    DeadCodeColumnarPayload,
    DeadCodeMarkerException,
    DeadCodeObservation,
    DependencyColumnarPayload,
    DigestMeta,
    ImportObservation,
    IntegerColumnarPayload,
    IntegerObservation,
    LanePayload,
    ModuleEntryException,
    ModuleIdentityColumnarPayload,
    ModuleIdentityObservationPayload,
    ObservationBundle,
    ObservationLane,
    ObservationLaneDescriptor,
    PythonModuleNodeKind,
    ResolvedSourceIdentity,
    SemanticAuthorityObservation,
    SemanticAuthorityObservationPayload,
    ThinIdentityTable,
    _null_first,
    derive_python_module_identity,
    python_module_mount_row,
)
from .contracts import ObservationContractError, validate_emitted_lanes


def _identity_table(
    identities: Sequence[ResolvedSourceIdentity],
) -> tuple[ThinIdentityTable, dict[str, int]]:
    """Build the thin identity table and refuse one it could not rebuild."""

    by_path: dict[str, ResolvedSourceIdentity] = {}
    for identity in identities:
        existing = by_path.setdefault(identity.file.path, identity)
        if existing != identity:
            raise ObservationContractError(
                f"conflicting identities recorded for {identity.file.path}"
            )
    paths = tuple(sorted(by_path))
    index = {path: position for position, path in enumerate(paths)}
    mount_rows: list[tuple[int, str, str]] = []
    node_kind_rows: list[tuple[int, PythonModuleNodeKind]] = []
    for path in paths:
        module = by_path[path].python_module
        if module is None:
            continue
        row = python_module_mount_row(path, module)
        mount_path, module_prefix = (".", "") if row is None else row
        if row is not None:
            mount_rows.append((index[path], mount_path, module_prefix))
        if module != derive_python_module_identity(
            path, mount_path=mount_path, module_prefix=module_prefix
        ):
            node_kind_rows.append((index[path], module.node_kind))
    table = ThinIdentityTable(
        paths=paths,
        module_null=tuple(
            index[path] for path in paths if by_path[path].python_module is None
        ),
        node_kind_exc=tuple(node_kind_rows),
        mount_exc=tuple(mount_rows),
    )
    for path in paths:
        if table.identity(index[path]) != by_path[path]:
            raise ObservationContractError(
                f"identity for {path} cannot be encoded without loss"
            )
    return table, index


def _encode_integer_lane(
    observations: Sequence[IntegerObservation],
    entity_population: int,
) -> IntegerColumnarPayload:
    table, index = _identity_table([item.source for item in observations])
    qualnames = tuple(sorted({item.qualname for item in observations}))
    dimensions = tuple(sorted({item.dimension for item in observations}))
    qualname_index = {value: position for position, value in enumerate(qualnames)}
    dimension_index = {value: position for position, value in enumerate(dimensions)}
    rows = sorted(
        observations,
        key=lambda item: (item.source.file.path, item.qualname, item.dimension),
    )
    return IntegerColumnarPayload(
        identities=table,
        qualnames=qualnames,
        dimensions=dimensions,
        identity=tuple(index[item.source.file.path] for item in rows),
        qualname=tuple(qualname_index[item.qualname] for item in rows),
        dimension=tuple(dimension_index[item.dimension] for item in rows),
        numerator=tuple(item.numerator for item in rows),
        entity_population=entity_population,
    )


def _encode_adoption_lane(
    counts: Sequence[AdoptionCount],
) -> AdoptionColumnarPayload:
    scopes = tuple(sorted({item.scope for item in counts}))
    features = tuple(sorted({item.feature for item in counts}))
    scope_index = {value: position for position, value in enumerate(scopes)}
    feature_index = {value: position for position, value in enumerate(features)}
    rows = sorted(counts, key=lambda item: (item.scope, item.feature))
    return AdoptionColumnarPayload(
        scopes=scopes,
        features=features,
        scope=tuple(scope_index[item.scope] for item in rows),
        feature=tuple(feature_index[item.feature] for item in rows),
        numerator=tuple(item.numerator for item in rows),
        denominator=tuple(item.denominator for item in rows),
    )


def _encode_dead_code_lane(
    candidates: Sequence[DeadCodeObservation],
) -> DeadCodeColumnarPayload:
    split = tuple(
        (item.entity.rsplit(":", 1)[0], item.entity.rsplit(":", 1)[-1], item)
        for item in candidates
    )
    prefixes = tuple(sorted({prefix for prefix, _qualname, _item in split}))
    kinds = tuple(sorted({item.candidate_kind for _prefix, _qualname, item in split}))
    prefix_index = {value: position for position, value in enumerate(prefixes)}
    kind_index = {value: position for position, value in enumerate(kinds)}
    rows = sorted(split, key=lambda row: (row[0], row[1], row[2].candidate_kind))
    return DeadCodeColumnarPayload(
        prefixes=prefixes,
        kinds=kinds,
        prefix=tuple(prefix_index[prefix] for prefix, _qualname, _item in rows),
        qualname=tuple(qualname for _path, qualname, _item in rows),
        kind=tuple(
            kind_index[item.candidate_kind] for _prefix, _qualname, item in rows
        ),
        reference_count=tuple(
            item.reference_count for _prefix, _qualname, item in rows
        ),
        reachable_true=tuple(
            position
            for position, (_prefix, _qualname, item) in enumerate(rows)
            if item.reachable
        ),
        markers=tuple(
            DeadCodeMarkerException(
                row=position,
                runtime_marker_count=item.runtime_marker_count,
                source_markers=item.source_markers,
            )
            for position, (_prefix, _qualname, item) in enumerate(rows)
            if item.runtime_marker_count or item.source_markers
        ),
    )


def _encode_api_surface_lane(
    symbols: Sequence[ApiSymbolObservation],
) -> ApiSurfaceColumnarPayload:
    table, index = _identity_table([item.owner for item in symbols])
    metas: set[DigestMeta] = set()
    values: set[str] = set()
    for item in symbols:
        for digest in (
            item.returns_digest,
            *(p.annotation_digest for p in item.parameters),
        ):
            if digest is not None:
                metas.add(DigestMeta(algorithm=digest.algorithm, domain=digest.domain))
                values.add(digest.value)
    if len(metas) > 1:
        raise ObservationContractError("api surface lane requires one digest domain")
    meta = next(iter(metas), None)
    digests = tuple(sorted(values))
    digest_index = {value: position for position, value in enumerate(digests)}
    symbol_kinds = tuple(sorted({item.symbol_kind for item in symbols}))
    visibilities = tuple(sorted({item.visibility for item in symbols}))

    def definition(parameter: ApiParameterObservation) -> ApiParameterDef:
        return ApiParameterDef(
            name=parameter.name,
            kind=parameter.kind,
            has_default=parameter.has_default,
            annotation_digest=(
                None
                if parameter.annotation_digest is None
                else digest_index[parameter.annotation_digest.value]
            ),
        )

    definitions = tuple(
        sorted(
            {
                definition(parameter)
                for item in symbols
                for parameter in item.parameters
            },
            key=lambda item: (
                item.name,
                item.kind,
                item.has_default,
                -1 if item.annotation_digest is None else item.annotation_digest,
            ),
        )
    )
    definition_index = {value: position for position, value in enumerate(definitions)}
    lists = tuple(
        sorted(
            {
                tuple(
                    definition_index[definition(parameter)]
                    for parameter in item.parameters
                )
                for item in symbols
            }
        )
    )
    list_index = {value: position for position, value in enumerate(lists)}
    kind_index = {value: position for position, value in enumerate(symbol_kinds)}
    visibility_index = {value: position for position, value in enumerate(visibilities)}

    def row_key(
        item: ApiSymbolObservation,
    ) -> tuple[str, str, str, str, tuple[int, str], tuple[object, ...]]:
        return (
            item.owner.file.path,
            item.symbol.rsplit(":", 1)[-1],
            item.symbol_kind,
            item.visibility,
            _null_first(
                None if item.returns_digest is None else item.returns_digest.value
            ),
            tuple(
                (
                    parameter.name,
                    parameter.kind,
                    parameter.has_default,
                    _null_first(
                        None
                        if parameter.annotation_digest is None
                        else parameter.annotation_digest.value
                    ),
                )
                for parameter in item.parameters
            ),
        )

    rows = sorted(symbols, key=row_key)
    return ApiSurfaceColumnarPayload(
        identities=table,
        digests=digests,
        digest_meta=meta,
        symbol_kinds=symbol_kinds,
        visibilities=visibilities,
        parameter_defs=definitions,
        parameter_lists=lists,
        owner=tuple(index[item.owner.file.path] for item in rows),
        name=tuple(item.symbol.rsplit(":", 1)[-1] for item in rows),
        symbol_kind=tuple(kind_index[item.symbol_kind] for item in rows),
        visibility=tuple(visibility_index[item.visibility] for item in rows),
        returns_digest=tuple(
            None
            if item.returns_digest is None
            else digest_index[item.returns_digest.value]
            for item in rows
        ),
        parameters=tuple(
            list_index[tuple(definition_index[definition(p)] for p in item.parameters)]
            for item in rows
        ),
    )


def _encode_dependency_lane(
    observations: Sequence[ImportObservation],
) -> DependencyColumnarPayload:
    table, index = _identity_table([item.source for item in observations])
    modules = tuple(
        sorted(
            {value for item in observations if (value := item.requested_module)}
            | {value for item in observations if (value := item.resolved_target)}
            | {name for item in observations for name in item.requested_names}
        )
    )
    module_index = {value: position for position, value in enumerate(modules)}
    resolutions = tuple(sorted({item.resolution for item in observations}))
    syntax_kinds = tuple(sorted({item.syntax_kind for item in observations}))
    resolution_index = {value: position for position, value in enumerate(resolutions)}
    syntax_index = {value: position for position, value in enumerate(syntax_kinds)}
    rows = sorted(
        observations,
        key=lambda item: (
            item.source.file.path,
            _null_first(item.requested_module),
            item.requested_names,
            item.syntax_kind,
            item.mechanism,
            item.level,
            item.resolution,
            _null_first(item.resolved_target),
            item.inventory_expansion,
        ),
    )
    return DependencyColumnarPayload(
        identities=table,
        modules=modules,
        resolutions=resolutions,
        syntax_kinds=syntax_kinds,
        source=tuple(index[item.source.file.path] for item in rows),
        requested_module=tuple(
            None
            if item.requested_module is None
            else module_index[item.requested_module]
            for item in rows
        ),
        requested_names=tuple(
            tuple(module_index[name] for name in item.requested_names) for item in rows
        ),
        resolution=tuple(resolution_index[item.resolution] for item in rows),
        resolved_target=tuple(
            None if item.resolved_target is None else module_index[item.resolved_target]
            for item in rows
        ),
        syntax_kind=tuple(syntax_index[item.syntax_kind] for item in rows),
        level=tuple(item.level for item in rows),
        inventory_expansion=tuple(
            position for position, item in enumerate(rows) if item.inventory_expansion
        ),
        mechanism_dynamic=tuple(
            position
            for position, item in enumerate(rows)
            if item.mechanism == "dynamic"
        ),
    )


def _encode_module_identity_lane(
    payload: ModuleIdentityObservationPayload,
) -> ModuleIdentityColumnarPayload:
    table, index = _identity_table(
        [entry.identity for entry in payload.module_registry]
    )
    return ModuleIdentityColumnarPayload(
        identities=table,
        manifest=payload.manifest,
        manifest_digest=payload.manifest_digest,
        registry_digest=payload.registry_digest,
        package_prefixes=payload.package_prefixes,
        other=tuple(
            ModuleEntryException(
                row=index[entry.identity.file.path],
                analyzed=entry.analyzed,
                internality=entry.internality,
            )
            for entry in sorted(
                payload.module_registry, key=lambda item: item.identity.file.path
            )
            if not entry.analyzed or entry.internality != "analyzed"
        ),
    )


def _module_identity_payload(
    bundle: ObservationBundle,
) -> ModuleIdentityObservationPayload:
    entries = tuple(entry for _path, entry in bundle.registry.entries_by_path.rows)
    return ModuleIdentityObservationPayload(
        manifest=bundle.manifest,
        manifest_digest=bundle.registry.manifest_digest,
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
) -> LanePayload:
    facts = bundle.structural
    name = descriptor.name
    if name == "clones.functions":
        return CloneObservationPayload(items=facts.function_clone_keys)
    if name == "clones.blocks":
        return CloneObservationPayload(items=facts.block_clone_keys)
    if name == "module_identity":
        return _encode_module_identity_lane(_module_identity_payload(bundle))
    if name == "dependencies":
        return _encode_dependency_lane(facts.dependencies)
    if name == "api_surface":
        return _encode_api_surface_lane(facts.api_surface)
    if name == "dead_code":
        return _encode_dead_code_lane(facts.dead_code)
    if name == "risk_observations":
        return _encode_integer_lane(
            facts.risk_observations, facts.risk_entity_population
        )
    if name == "adoption_counts":
        return _encode_adoption_lane(facts.adoption_counts)
    if name == "coupling_cohesion_observations":
        return _encode_integer_lane(
            facts.coupling_cohesion_observations,
            facts.coupling_cohesion_entity_population,
        )
    if bundle.semantic is None:
        raise ObservationContractError(
            "semantic_authority lane requires the accepted semantic result"
        )
    return SemanticAuthorityObservationPayload(
        observations=tuple(
            SemanticAuthorityObservation(
                contract_id=item.contract_id,
                sink_identity=item.sink_identity,
                authority_status=item.authority_status,
                producer_root_ids=item.producer_root_ids,
                effect_signature=item.effect_signature,
                resolution_state=item.resolution_state,
                algorithm_revision=bundle.semantic.algorithm_revision,
            )
            for item in bundle.semantic.governed_sinks
        )
    )


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
    """Return the row count of one lane, whatever wire form it carries."""

    payload = lane.payload
    if isinstance(payload, CloneObservationPayload):
        return len(payload.items)
    if isinstance(payload, ModuleIdentityColumnarPayload):
        return len(payload.identities.paths)
    if isinstance(payload, DependencyColumnarPayload):
        return len(payload.source)
    if isinstance(payload, ApiSurfaceColumnarPayload):
        return len(payload.owner)
    if isinstance(payload, DeadCodeColumnarPayload):
        return len(payload.prefix)
    if isinstance(payload, IntegerColumnarPayload):
        return len(payload.identity)
    if isinstance(payload, AdoptionColumnarPayload):
        return len(payload.scope)
    if isinstance(payload, SemanticAuthorityObservationPayload):
        return len(payload.observations)
    raise ObservationContractError(f"lane payload has no row count: {type(payload)}")


__all__ = [
    "build_observation_lanes",
    "canonical_observation_lane_bytes",
    "observation_lane_item_count",
]
