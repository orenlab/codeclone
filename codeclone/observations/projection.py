# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Single projection owner for canonical pre-baseline source facts."""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

import orjson

from ..models import (
    AdoptionCount,
    ApiParameterObservation,
    ApiSymbolObservation,
    ClassMetrics,
    DeadCandidate,
    DeadCodeObservation,
    DigestObject,
    FileIdentity,
    GroupItemLike,
    ImportObservation,
    IntegerObservation,
    ModuleApiSurface,
    ModuleDep,
    ModuleDocstringCoverage,
    ModuleRegistryHandle,
    ModuleTypingCoverage,
    ObservationBundle,
    ResolvedSourceIdentity,
    RuntimeReachabilityFact,
    SemanticAuthorityResult,
    StructuralObservationFacts,
)
from ..paths.module_identity import repository_relative_path
from ..utils.coerce import as_int, as_str
from .contracts import ObservationContractError, build_observation_contract

_OBSERVATION_DIGEST_DOMAIN = b"codeclone.source-observations.v1\x00"


def _observation_source(
    filepath: str,
    registry: ModuleRegistryHandle,
    scan_root: Path,
) -> ResolvedSourceIdentity:
    relative = repository_relative_path(root=scan_root, path=Path(filepath))
    entry = registry.entries_by_path.get(relative)
    if entry is None:
        raise ObservationContractError(
            f"observation source is absent from the module registry: {relative}"
        )
    return entry.identity


def _bare_qualname(qualname: str) -> str:
    """Split the producer-glued ``module:qualname`` — the sole split site."""

    return qualname.rsplit(":", 1)[-1]


def _integer_observation_sort_key(row: IntegerObservation) -> tuple[str, str, str]:
    return (row.source.file.path, row.qualname, row.dimension)


def _source_identity(
    source: str,
    registry: ModuleRegistryHandle,
) -> ResolvedSourceIdentity:
    entry = registry.entries_by_module.get(source)
    if entry is None:
        entry = registry.entries_by_path.get(source)
    if entry is None:
        raise ObservationContractError(
            f"dependency source is absent from the module registry: {source}"
        )
    return entry.identity


def _dependency_observations(
    dependencies: Sequence[ModuleDep],
    registry: ModuleRegistryHandle,
) -> tuple[ImportObservation, ...]:
    rows = tuple(
        ImportObservation(
            source=_source_identity(dependency.source, registry),
            syntax_kind=dependency.import_type,
            level=dependency.level,
            requested_module=dependency.requested_module,
            requested_names=dependency.requested_names,
            resolution=dependency.resolution,
            candidate_targets=dependency.candidate_targets,
            resolved_target=(
                None
                if dependency.resolution
                in {"unresolved_relative", "unresolved_dynamic"}
                else dependency.target
            ),
            inventory_expansion=dependency.inventory_expansion,
            mechanism=dependency.mechanism,
        )
        for dependency in dependencies
    )
    return tuple(
        sorted(
            rows,
            key=lambda row: (
                row.source.file.path,
                row.syntax_kind,
                row.mechanism,
                row.level,
                row.requested_module or "",
                row.requested_names,
                row.resolution,
                row.candidate_targets,
                row.resolved_target or "",
                row.inventory_expansion,
            ),
        )
    )


def _component_digest(value: str) -> DigestObject | None:
    if not value:
        return None
    return DigestObject(domain="ccapi1:sig", algorithm="sha256", value=value)


def _api_surface_observations(
    modules: Sequence[ModuleApiSurface],
    registry: ModuleRegistryHandle,
) -> tuple[ApiSymbolObservation, ...]:
    rows: list[ApiSymbolObservation] = []
    for module in modules:
        entry = registry.entries_by_module.get(module.module)
        if entry is None:
            # Observation lanes are bounded by the canonical registry scope.
            continue
        rows.extend(
            ApiSymbolObservation(
                owner=entry.identity,
                symbol=symbol.qualname,
                symbol_kind=symbol.kind,
                visibility=symbol.exported_via,
                parameters=tuple(
                    ApiParameterObservation(
                        name=parameter.name,
                        kind=parameter.kind,
                        has_default=parameter.has_default,
                        annotation_digest=_component_digest(parameter.annotation_hash),
                    )
                    for parameter in symbol.params
                ),
                returns_digest=_component_digest(symbol.returns_hash),
            )
            for symbol in module.symbols
        )
    return tuple(
        sorted(
            rows,
            key=lambda row: (
                row.owner.file.path,
                row.symbol,
                row.symbol_kind,
                row.visibility,
            ),
        )
    )


def _dead_code_observations(
    candidates: Sequence[DeadCandidate],
    *,
    referenced_names: frozenset[str],
    referenced_qualnames: frozenset[str],
    runtime_reachability: Sequence[RuntimeReachabilityFact],
) -> tuple[DeadCodeObservation, ...]:
    runtime_counts = Counter(fact.target_qualname for fact in runtime_reachability)
    rows = (
        DeadCodeObservation(
            entity=candidate.qualname,
            candidate_kind=candidate.kind,
            reference_count=int(
                candidate.local_name in referenced_names
                or candidate.qualname in referenced_qualnames
            ),
            reachable=runtime_counts[candidate.qualname] > 0,
            runtime_marker_count=runtime_counts[candidate.qualname],
        )
        for candidate in candidates
    )
    return tuple(sorted(rows, key=lambda row: (row.entity, row.candidate_kind)))


def _risk_observations(
    units: Sequence[GroupItemLike],
    registry: ModuleRegistryHandle,
    scan_root: Path,
) -> tuple[IntegerObservation, ...]:
    rows: list[IntegerObservation] = []
    for unit in units:
        source = _observation_source(as_str(unit.get("filepath")), registry, scan_root)
        qualname = _bare_qualname(as_str(unit.get("qualname")))
        for dimension in ("cyclomatic_complexity", "nesting_depth"):
            numerator = max(0, as_int(unit.get(dimension)))
            if not numerator:
                continue
            rows.append(
                IntegerObservation(
                    source=source,
                    qualname=qualname,
                    dimension=dimension,
                    numerator=numerator,
                )
            )
    return tuple(sorted(rows, key=_integer_observation_sort_key))


def _adoption_counts(
    typing_modules: Sequence[ModuleTypingCoverage],
    docstring_modules: Sequence[ModuleDocstringCoverage],
) -> tuple[AdoptionCount, ...]:
    rows: list[AdoptionCount] = []
    for typing_module in typing_modules:
        if typing_module.params_total > 0:
            rows.append(
                AdoptionCount(
                    scope=typing_module.module,
                    feature="typing.parameters",
                    numerator=typing_module.params_annotated,
                    denominator=typing_module.params_total,
                )
            )
        if typing_module.returns_total > 0:
            rows.append(
                AdoptionCount(
                    scope=typing_module.module,
                    feature="typing.returns",
                    numerator=typing_module.returns_annotated,
                    denominator=typing_module.returns_total,
                )
            )
    for docstring_module in docstring_modules:
        if docstring_module.public_symbol_total <= 0:
            continue
        rows.append(
            AdoptionCount(
                scope=docstring_module.module,
                feature="docstrings.public_symbols",
                numerator=docstring_module.public_symbol_documented,
                denominator=docstring_module.public_symbol_total,
            )
        )
    return tuple(sorted(rows, key=lambda row: (row.scope, row.feature)))


def _coupling_cohesion_observations(
    class_metrics: Sequence[ClassMetrics],
    registry: ModuleRegistryHandle,
    scan_root: Path,
) -> tuple[IntegerObservation, ...]:
    rows: list[IntegerObservation] = []
    for item in class_metrics:
        source = _observation_source(item.filepath, registry, scan_root)
        qualname = _bare_qualname(item.qualname)
        for dimension, numerator in (
            ("cbo", item.cbo),
            ("lcom4", item.lcom4),
            ("methods", item.method_count),
            ("instance_variables", item.instance_var_count),
        ):
            if not numerator:
                continue
            rows.append(
                IntegerObservation(
                    source=source,
                    qualname=qualname,
                    dimension=dimension,
                    numerator=numerator,
                )
            )
    return tuple(sorted(rows, key=_integer_observation_sort_key))


def _observation_digest(
    *,
    contract: object,
    analysis_scope: tuple[FileIdentity, ...],
    registry: ModuleRegistryHandle,
    structural: StructuralObservationFacts,
    semantic: SemanticAuthorityResult | None,
) -> DigestObject:
    canonical = orjson.dumps(
        {
            "analysis_scope": analysis_scope,
            "module_identity_manifest": registry.manifest,
            "module_registry": registry,
            "observation_contract": contract,
            "semantic": semantic,
            "source_fact_families": structural,
        },
        option=orjson.OPT_SORT_KEYS,
    )
    return DigestObject(
        domain="codeclone.source-observations.v1",
        algorithm="sha256",
        value=hashlib.sha256(_OBSERVATION_DIGEST_DOMAIN + canonical).hexdigest(),
    )


def build_observation_bundle(
    *,
    scan_root: Path,
    module_registry: ModuleRegistryHandle,
    function_clone_keys: Sequence[str] = (),
    block_clone_keys: Sequence[str] = (),
    module_deps: Sequence[ModuleDep] = (),
    api_modules: Sequence[ModuleApiSurface] = (),
    dead_candidates: Sequence[DeadCandidate] = (),
    referenced_names: frozenset[str] = frozenset(),
    referenced_qualnames: frozenset[str] = frozenset(),
    runtime_reachability: Sequence[RuntimeReachabilityFact] = (),
    units: Sequence[GroupItemLike] = (),
    class_metrics: Sequence[ClassMetrics] = (),
    typing_modules: Sequence[ModuleTypingCoverage] = (),
    docstring_modules: Sequence[ModuleDocstringCoverage] = (),
    semantic_authority: SemanticAuthorityResult | None = None,
    collect_metrics: bool = True,
    collect_dependencies: bool = True,
    collect_dead_code: bool = True,
    collect_api_surface: bool = True,
) -> ObservationBundle:
    contract = build_observation_contract(
        collect_metrics=collect_metrics,
        collect_dependencies=collect_dependencies,
        collect_dead_code=collect_dead_code,
        collect_api_surface=collect_api_surface,
        collect_semantic_authority=semantic_authority is not None,
    )
    structural = StructuralObservationFacts(
        function_clone_keys=tuple(sorted(set(function_clone_keys))),
        block_clone_keys=tuple(sorted(set(block_clone_keys))),
        dependencies=(
            _dependency_observations(module_deps, module_registry)
            if collect_dependencies
            else ()
        ),
        api_surface=(
            _api_surface_observations(api_modules, module_registry)
            if collect_api_surface
            else ()
        ),
        dead_code=(
            _dead_code_observations(
                dead_candidates,
                referenced_names=referenced_names,
                referenced_qualnames=referenced_qualnames,
                runtime_reachability=runtime_reachability,
            )
            if collect_dead_code
            else ()
        ),
        risk_observations=(
            _risk_observations(units, module_registry, scan_root)
            if collect_metrics
            else ()
        ),
        risk_entity_population=len(units) if collect_metrics else 0,
        adoption_counts=(
            _adoption_counts(typing_modules, docstring_modules)
            if collect_metrics
            else ()
        ),
        coupling_cohesion_observations=(
            _coupling_cohesion_observations(class_metrics, module_registry, scan_root)
            if collect_metrics
            else ()
        ),
        coupling_cohesion_entity_population=(
            len(class_metrics) if collect_metrics else 0
        ),
    )
    analysis_scope = tuple(
        entry.identity.file
        for _path, entry in module_registry.entries_by_path.rows
        if entry.analyzed
    )
    observation_digest = _observation_digest(
        contract=contract,
        analysis_scope=analysis_scope,
        registry=module_registry,
        structural=structural,
        semantic=semantic_authority,
    )
    return ObservationBundle(
        contract=contract,
        analysis_scope=analysis_scope,
        manifest=module_registry.manifest,
        registry=module_registry,
        semantic=semantic_authority,
        structural=structural,
        observation_digest=observation_digest,
    )


__all__ = ["build_observation_bundle"]
