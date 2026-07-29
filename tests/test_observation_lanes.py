# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import TypeVar

import orjson
import pytest

import codeclone.observations.lanes as lanes_mod
from codeclone.baseline.lanes import (
    BaselineLaneValidationError,
    decode_adoption_lane,
    decode_api_surface_lane,
    decode_dead_code_lane,
    decode_dependency_lane,
    decode_integer_lane,
    decode_module_identity_lane,
)
from codeclone.models import (
    AdoptionColumnarPayload,
    ApiParameterDef,
    ApiParamSpec,
    ApiSurfaceColumnarPayload,
    ApiSymbolObservation,
    AuthorityGovernedSink,
    AuthorityGraph,
    AuthorityRegistry,
    AuthorityRegistryEntry,
    ClassMetrics,
    CloneObservationPayload,
    ContractIRBuildResult,
    DeadCandidate,
    DeadCodeColumnarPayload,
    DeadCodeMarkerException,
    DependencyColumnarPayload,
    DigestObject,
    DynamicLoadArgument,
    FileIdentity,
    ImportObservation,
    IntegerColumnarPayload,
    LanePayload,
    ModuleApiSurface,
    ModuleDep,
    ModuleDocstringCoverage,
    ModuleIdentityColumnarPayload,
    ModuleRegistryHandle,
    ModuleTypingCoverage,
    ObservationBundle,
    ObservationLaneName,
    PublicSymbol,
    PythonModuleIdentity,
    ResolvedSourceIdentity,
    RuntimeReachabilityFact,
    SemanticAuthorityObservationPayload,
    SemanticAuthorityResult,
    ThinIdentityTable,
    derive_python_module_identity,
)
from codeclone.observations.contracts import ObservationContractError
from codeclone.observations.lanes import (
    build_observation_lanes,
    canonical_observation_lane_bytes,
)
from codeclone.observations.projection import build_observation_bundle
from tests._ast_metrics_helpers import module_registry_context


def _registry() -> ModuleRegistryHandle:
    return module_registry_context(
        filepath="pkg/mod.py",
        module_name="pkg.mod",
        inventory_modules=("pkg.dep",),
    )[1]


def _contains_float(value: object) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(_contains_float(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_float(item) for item in value)
    return False


def test_semantic_authority_lane_is_the_compact_d10_projection_only() -> None:
    result = SemanticAuthorityResult(
        algorithm_revision="1",
        contract_ir=ContractIRBuildResult(
            contracts=(),
            sccs=(),
            fixpoint_iterations=1,
        ),
        graph=AuthorityGraph(nodes=(), edges=()),
        sinks=(),
        candidates=(),
        registry=AuthorityRegistry(
            version="1",
            entries=(
                AuthorityRegistryEntry(
                    contract_id="example.contract/v1",
                    canonical_owner="pkg.mod:owner",
                    allowed_adapters=(),
                    forbidden_raw_inputs=(),
                    required_provenance=("producer:pkg.mod:owner",),
                ),
            ),
        ),
        governed_sinks=(
            AuthorityGovernedSink(
                contract_id="example.contract/v1",
                sink_identity="pkg.mod:owner",
                authority_status="authoritative",
                producer_root_ids=("producer:pkg.mod:owner",),
                effect_signature="1" * 64,
                resolution_state="resolved",
            ),
        ),
    )
    bundle = build_observation_bundle(
        scan_root=Path("."),
        module_registry=_registry(),
        semantic_authority=result,
    )
    semantic_lane = next(
        lane
        for lane in build_observation_lanes(bundle)
        if lane.descriptor.name == "semantic_authority"
    )

    assert semantic_lane.descriptor.payload_schema == "2"
    assert isinstance(semantic_lane.payload, SemanticAuthorityObservationPayload)
    assert orjson.loads(orjson.dumps(semantic_lane.payload)) == {
        "observations": [
            {
                "algorithm_revision": "1",
                "authority_status": "authoritative",
                "contract_id": "example.contract/v1",
                "effect_signature": "1" * 64,
                "producer_root_ids": ["producer:pkg.mod:owner"],
                "resolution_state": "resolved",
                "sink_identity": "pkg.mod:owner",
            }
        ]
    }


def _bundle() -> ObservationBundle:
    return build_observation_bundle(
        scan_root=Path("."),
        module_registry=_registry(),
        function_clone_keys=(f"{'a' * 64}|0-19",),
        block_clone_keys=("|".join(("b" * 64,) * 4),),
        module_deps=(
            ModuleDep(
                source="pkg.mod",
                target="pkg.dep",
                import_type="from_import",
                line=2,
                resolution="analyzed",
                requested_module="pkg.dep",
                requested_names=("value",),
                candidate_targets=("pkg.dep",),
            ),
        ),
        api_modules=(
            ModuleApiSurface(
                module="pkg.mod",
                filepath="pkg/mod.py",
                symbols=(
                    PublicSymbol(
                        qualname="pkg.mod:run",
                        kind="function",
                        start_line=1,
                        end_line=2,
                        params=(
                            ApiParamSpec(
                                name="left",
                                kind="pos_or_kw",
                                has_default=False,
                                annotation_hash="1" * 64,
                            ),
                            ApiParamSpec(
                                name="right",
                                kind="kw_only",
                                has_default=True,
                            ),
                        ),
                        returns_hash="2" * 64,
                        exported_via="all",
                    ),
                ),
            ),
        ),
        dead_candidates=(
            DeadCandidate(
                qualname="pkg.mod:unused",
                local_name="unused",
                filepath="pkg/mod.py",
                start_line=4,
                end_line=5,
                kind="function",
            ),
        ),
        runtime_reachability=(
            RuntimeReachabilityFact(
                target_qualname="pkg.mod:unused",
                filepath="pkg/mod.py",
                start_line=4,
                end_line=5,
                target_kind="function",
                framework="click",
                edge_kind="registers_command",
                confidence="high",
                evidence="decorator",
                evidence_symbol="click.command",
            ),
        ),
        units=(
            {
                "filepath": "pkg/mod.py",
                "qualname": "pkg.mod:run",
                "cyclomatic_complexity": 3,
                "nesting_depth": 1,
            },
        ),
        class_metrics=(
            ClassMetrics(
                qualname="pkg.mod:Service",
                filepath="pkg/mod.py",
                start_line=8,
                end_line=12,
                cbo=2,
                lcom4=1,
                method_count=2,
                instance_var_count=1,
                risk_coupling="low",
                risk_cohesion="low",
            ),
        ),
        typing_modules=(
            ModuleTypingCoverage(
                module="pkg.mod",
                filepath="pkg/mod.py",
                callable_count=1,
                params_total=2,
                params_annotated=1,
                returns_total=1,
                returns_annotated=1,
                any_annotation_count=0,
            ),
        ),
        docstring_modules=(
            ModuleDocstringCoverage(
                module="pkg.mod",
                filepath="pkg/mod.py",
                public_symbol_total=1,
                public_symbol_documented=1,
            ),
        ),
    )


def test_raw_lanes_are_closed_policy_free_and_component_structured() -> None:
    lanes = build_observation_lanes(_bundle())
    by_name = {lane.descriptor.name: lane for lane in lanes}

    assert tuple(by_name) == tuple(sorted(by_name))
    api_payload = by_name["api_surface"].payload
    assert isinstance(api_payload, ApiSurfaceColumnarPayload)
    symbol = decode_api_surface_lane(api_payload).symbols[0]
    assert tuple(parameter.name for parameter in symbol.parameters) == (
        "left",
        "right",
    )
    assert symbol.parameters[0].annotation_digest is not None
    assert symbol.parameters[1].annotation_digest is None
    assert symbol.returns_digest is not None

    raw = b"".join(canonical_observation_lane_bytes(lane) for lane in lanes)
    assert b"signature_digest" not in raw
    assert b"health_score" not in raw
    assert b"health_grade" not in raw
    assert b"permille" not in raw
    assert not _contains_float(
        orjson.loads(
            b"["
            + b",".join(canonical_observation_lane_bytes(lane) for lane in lanes)
            + b"]"
        )
    )


def test_module_identity_lane_preserves_canonical_inventory_facts() -> None:
    registry = module_registry_context(
        filepath="pkg/mod.py",
        module_name="pkg.mod",
        known_internal_modules=("pkg.hidden",),
    )[1]
    bundle = build_observation_bundle(scan_root=Path("."), module_registry=registry)
    lanes = {lane.descriptor.name: lane for lane in build_observation_lanes(bundle)}
    payload = lanes["module_identity"].payload

    assert isinstance(payload, ModuleIdentityColumnarPayload)
    decoded = decode_module_identity_lane(payload)
    assert payload.manifest_digest is registry.manifest_digest
    assert payload.manifest_digest != payload.registry_digest
    assert decoded.module_registry == tuple(
        entry for _path, entry in registry.entries_by_path.rows
    )
    assert tuple(entry.analyzed for entry in decoded.module_registry) == (False, True)
    assert tuple(entry.internality for entry in decoded.module_registry) == (
        "known_internal_not_analyzed",
        "analyzed",
    )


def test_lane_projection_performs_no_hashing() -> None:
    source = Path(lanes_mod.__file__).read_text(encoding="utf-8")

    assert "hashlib" not in source
    assert "sha256" not in source


@pytest.mark.parametrize(
    ("function_keys", "block_keys", "message"),
    (
        ((f"{'a' * 32}|0-19",), (), "function clone"),
        ((), ("|".join(("b" * 32,) * 4),), "block clone"),
    ),
)
def test_invalid_fp_v1_clone_key_is_rejected(
    function_keys: tuple[str, ...],
    block_keys: tuple[str, ...],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        build_observation_bundle(
            scan_root=Path("."),
            module_registry=_registry(),
            function_clone_keys=function_keys,
            block_clone_keys=block_keys,
        )


def test_canonical_fp_v2_clone_ids_are_preserved_byte_for_byte() -> None:
    function_id = f"{'a' * 64}|20+"
    block_id = "|".join(("b" * 64, "c" * 64, "d" * 64, "e" * 64))
    bundle = build_observation_bundle(
        scan_root=Path("."),
        module_registry=_registry(),
        function_clone_keys=(function_id,),
        block_clone_keys=(block_id,),
    )
    lanes = {lane.descriptor.name: lane for lane in build_observation_lanes(bundle)}

    function_payload = lanes["clones.functions"].payload
    block_payload = lanes["clones.blocks"].payload
    assert isinstance(function_payload, CloneObservationPayload)
    assert isinstance(block_payload, CloneObservationPayload)
    assert function_payload.items == (function_id,)
    assert block_payload.items == (block_id,)


def test_api_facts_outside_canonical_registry_scope_are_absent() -> None:
    bundle = build_observation_bundle(
        scan_root=Path("."),
        module_registry=_registry(),
        api_modules=(
            ModuleApiSurface(
                module=".ignored.tool",
                filepath=".ignored/tool.py",
                symbols=(
                    PublicSymbol(
                        qualname=".ignored.tool:run",
                        kind="function",
                        start_line=1,
                        end_line=2,
                        exported_via="name",
                    ),
                ),
            ),
        ),
    )

    assert bundle.structural.api_surface == ()


def test_zero_observations_are_absent_while_the_population_still_counts_them() -> None:
    bundle = build_observation_bundle(
        scan_root=Path("."),
        module_registry=_registry(),
        units=(
            {
                "filepath": "pkg/mod.py",
                "qualname": "pkg.mod:flat",
                "cyclomatic_complexity": 1,
                "nesting_depth": 0,
            },
        ),
        class_metrics=(
            ClassMetrics(
                qualname="pkg.mod:Empty",
                filepath="pkg/mod.py",
                start_line=1,
                end_line=2,
                cbo=0,
                lcom4=0,
                method_count=0,
                instance_var_count=0,
                risk_coupling="low",
                risk_cohesion="low",
            ),
        ),
    )
    lanes = {lane.descriptor.name: lane for lane in build_observation_lanes(bundle)}

    risk = lanes["risk_observations"].payload
    coupling = lanes["coupling_cohesion_observations"].payload
    assert isinstance(risk, IntegerColumnarPayload)
    assert isinstance(coupling, IntegerColumnarPayload)
    risk_rows = decode_integer_lane(risk)
    coupling_rows = decode_integer_lane(coupling)

    # The zero-valued nesting_depth row is absent; the observed function still counts.
    assert tuple(
        (item.qualname, item.dimension, item.numerator)
        for item in risk_rows.observations
    ) == (("flat", "cyclomatic_complexity", 1),)
    assert risk.entity_population == 1

    # A class whose every dimension is zero emits nothing and stays in the population.
    assert coupling_rows.observations == ()
    assert coupling.entity_population == 1


def _columnar_bundle() -> ObservationBundle:
    """A bundle whose seven columnar lanes all carry rows."""

    return _bundle()


def _lane_bytes(bundle: ObservationBundle) -> dict[str, bytes]:
    return {
        lane.descriptor.name: canonical_observation_lane_bytes(lane)
        for lane in build_observation_lanes(bundle)
    }


def test_columnar_lanes_are_input_order_independent_and_stable() -> None:
    bundle = _columnar_bundle()
    facts = bundle.structural
    reversed_bundle = replace(
        bundle,
        structural=replace(
            facts,
            dependencies=tuple(reversed(facts.dependencies)),
            api_surface=tuple(reversed(facts.api_surface)),
            dead_code=tuple(reversed(facts.dead_code)),
            risk_observations=tuple(reversed(facts.risk_observations)),
            adoption_counts=tuple(reversed(facts.adoption_counts)),
            coupling_cohesion_observations=tuple(
                reversed(facts.coupling_cohesion_observations)
            ),
        ),
    )

    first = _lane_bytes(bundle)
    assert first == _lane_bytes(bundle)
    assert first == _lane_bytes(reversed_bundle)


_Payload = TypeVar("_Payload")


def _payload(
    lanes: Mapping[ObservationLaneName, LanePayload],
    name: ObservationLaneName,
    expected: type[_Payload],
) -> _Payload:
    """Fetch one lane payload already narrowed to its wire model."""

    payload = lanes[name]
    assert isinstance(payload, expected), name
    return payload


def test_columnar_lanes_round_trip_every_row_and_derive_every_identity() -> None:
    lanes = {
        lane.descriptor.name: lane.payload
        for lane in build_observation_lanes(_columnar_bundle())
    }
    facts = _columnar_bundle().structural

    risk = _payload(lanes, "risk_observations", IntegerColumnarPayload)
    coupling = _payload(lanes, "coupling_cohesion_observations", IntegerColumnarPayload)
    dead = _payload(lanes, "dead_code", DeadCodeColumnarPayload)
    deps = _payload(lanes, "dependencies", DependencyColumnarPayload)
    api = _payload(lanes, "api_surface", ApiSurfaceColumnarPayload)
    adoption = _payload(lanes, "adoption_counts", AdoptionColumnarPayload)

    assert sorted(decode_integer_lane(risk).observations, key=repr) == sorted(
        facts.risk_observations, key=repr
    )
    assert sorted(decode_integer_lane(coupling).observations, key=repr) == sorted(
        facts.coupling_cohesion_observations, key=repr
    )
    assert sorted(decode_dead_code_lane(dead).candidates, key=repr) == sorted(
        facts.dead_code, key=repr
    )
    assert sorted(decode_dependency_lane(deps).observations, key=repr) == sorted(
        facts.dependencies, key=repr
    )
    assert sorted(decode_api_surface_lane(api).symbols, key=repr) == sorted(
        facts.api_surface, key=repr
    )
    assert sorted(decode_adoption_lane(adoption).counts, key=repr) == sorted(
        facts.adoption_counts, key=repr
    )

    # The identity rule reproduces every recorded identity from its path alone.
    for table in (
        risk.identities,
        coupling.identities,
        deps.identities,
        api.identities,
    ):
        for position, path in enumerate(table.paths):
            assert table.identity(position).file.path == path

    # The glued strings are rebuilt from their split components.
    for row, symbol in enumerate(decode_api_surface_lane(api).symbols):
        owner = symbol.owner.python_module
        assert owner is not None
        assert symbol.symbol == f"{owner.module}:{api.name[row]}"
    for row, candidate in enumerate(decode_dead_code_lane(dead).candidates):
        prefix = dead.prefixes[dead.prefix[row]]
        assert candidate.entity == f"{prefix}:{dead.qualname[row]}"


def _integer_payload(
    *,
    qualnames: tuple[str, ...] = ("run",),
    dimensions: tuple[str, ...] = ("cbo",),
    identity: tuple[int, ...] = (0,),
    qualname: tuple[int, ...] = (0,),
    dimension: tuple[int, ...] = (0,),
    numerator: tuple[int, ...] = (1,),
    entity_population: int = 1,
) -> IntegerColumnarPayload:
    return IntegerColumnarPayload(
        identities=ThinIdentityTable(paths=("pkg/mod.py",)),
        qualnames=qualnames,
        dimensions=dimensions,
        identity=identity,
        qualname=qualname,
        dimension=dimension,
        numerator=numerator,
        entity_population=entity_population,
    )


def test_columnar_canonical_form_rejects_each_malformed_shape() -> None:
    _integer_payload()

    with pytest.raises(ValueError, match="sorted and duplicate-free"):
        _integer_payload(qualnames=("run", "run"))
    with pytest.raises(ValueError, match="sorted and duplicate-free"):
        _integer_payload(dimensions=("lcom4", "cbo"))
    with pytest.raises(ValueError, match="equal column lengths"):
        _integer_payload(numerator=(1, 2))
    with pytest.raises(ValueError, match="outside its table"):
        _integer_payload(qualname=(7,))
    with pytest.raises(ValueError, match="entity population"):
        _integer_payload(entity_population=0)
    with pytest.raises(ValueError, match="non-negative"):
        _integer_payload(numerator=(-1,))
    with pytest.raises(ValueError, match="must be sorted"):
        _integer_payload(
            qualnames=("alpha", "beta"),
            qualname=(1, 0),
            identity=(0, 0),
            dimension=(0, 0),
            numerator=(1, 1),
            entity_population=2,
        )
    with pytest.raises(ValueError, match="strictly ascending"):
        DeadCodeColumnarPayload(
            prefixes=("pkg.mod",),
            kinds=("function",),
            prefix=(0, 0),
            qualname=("a", "b"),
            kind=(0, 0),
            reference_count=(0, 0),
            reachable_true=(1, 0),
        )
    with pytest.raises(ValueError, match="digest values require"):
        ApiSurfaceColumnarPayload(
            identities=ThinIdentityTable(paths=("pkg/mod.py",)),
            digests=("a" * 64,),
            digest_meta=None,
            symbol_kinds=("function",),
            visibilities=("all",),
            parameter_defs=(),
            parameter_lists=((),),
            owner=(0,),
            name=("run",),
            symbol_kind=(0,),
            visibility=(0,),
            returns_digest=(None,),
            parameters=(0,),
        )


def _identity(path: str, *, module: str | None) -> ResolvedSourceIdentity:
    return ResolvedSourceIdentity(
        file=FileIdentity(path=path),
        python_module=(
            None
            if module is None
            else replace(derive_python_module_identity(path), module=module)
        ),
    )


def test_identity_table_refuses_conflicting_and_unencodable_identities() -> None:
    first = _identity("pkg/mod.py", module="pkg.mod")
    second = _identity("pkg/mod.py", module=None)
    with pytest.raises(ObservationContractError, match="conflicting identities"):
        lanes_mod._identity_table([first, second])

    # A module name the path cannot produce is a lossy encoding, not an exception.
    with pytest.raises(ObservationContractError, match="cannot be encoded"):
        lanes_mod._identity_table([_identity("pkg/mod.py", module="other.name")])


def _mounted_identity(
    path: str,
    *,
    module: str,
    package: str,
    is_package: bool,
    mount_path: str,
    module_prefix: str = "",
) -> ResolvedSourceIdentity:
    del module_prefix
    return ResolvedSourceIdentity(
        file=FileIdentity(path=path),
        python_module=PythonModuleIdentity(
            module=module,
            package=package,
            is_package=is_package,
            mount_path=mount_path,
            origin="import_mount",
            node_kind="regular_package" if is_package else "module_file",
        ),
    )


def test_identity_table_encodes_non_root_import_mounts() -> None:
    """Modules named relative to a non-root mount must survive the thin wire.

    Under a src layout the importable name is ``acme``, not ``src.acme`` — the
    mount is the naming origin, so the wire has to carry it as an exception
    instead of assuming every module is named after its full path.
    """
    identities = [
        _mounted_identity(
            "src/acme/__init__.py",
            module="acme",
            package="acme",
            is_package=True,
            mount_path="src",
        ),
        _mounted_identity(
            "src/acme/service.py",
            module="acme.service",
            package="acme",
            is_package=False,
            mount_path="src",
        ),
    ]

    table, index = lanes_mod._identity_table(identities)

    for identity in identities:
        assert table.identity(index[identity.file.path]) == identity


def test_identity_table_keeps_root_mount_rows_free_of_exceptions() -> None:
    """The default mount stays the contract: root-mount rows encode unchanged."""
    identities = [_identity("pkg/mod.py", module="pkg.mod")]

    table, _index = lanes_mod._identity_table(identities)

    assert table.mount_exc == ()


def test_api_surface_lane_refuses_two_digest_domains() -> None:
    owner = _identity("pkg/mod.py", module="pkg.mod")

    def symbol(name: str, digest: DigestObject) -> ApiSymbolObservation:
        return ApiSymbolObservation(
            owner=owner,
            symbol=f"pkg.mod:{name}",
            symbol_kind="function",
            visibility="all",
            parameters=(),
            returns_digest=digest,
        )

    symbols = (
        symbol(
            "alpha",
            DigestObject(domain="ccapi1:sig", algorithm="sha256", value="a" * 64),
        ),
        symbol(
            "beta",
            DigestObject(
                domain="codeclone.source-observations.v1",
                algorithm="sha256",
                value="b" * 64,
            ),
        ),
    )

    with pytest.raises(ObservationContractError, match="one digest domain"):
        lanes_mod._encode_api_surface_lane(symbols)


def test_columnar_models_reject_the_remaining_malformed_shapes() -> None:
    with pytest.raises(ValueError, match="non-negative/positive"):
        AdoptionColumnarPayload(
            scopes=("pkg.mod",),
            features=("typing",),
            scope=(0,),
            feature=(0,),
            numerator=(1,),
            denominator=(0,),
        )
    with pytest.raises(ValueError, match="cannot exceed"):
        AdoptionColumnarPayload(
            scopes=("pkg.mod",),
            features=("typing",),
            scope=(0,),
            feature=(0,),
            numerator=(3,),
            denominator=(2,),
        )
    with pytest.raises(ValueError, match="must be sorted"):
        AdoptionColumnarPayload(
            scopes=("a", "b"),
            features=("typing",),
            scope=(1, 0),
            feature=(0, 0),
            numerator=(1, 1),
            denominator=(2, 2),
        )
    with pytest.raises(ValueError, match="non-negative"):
        DeadCodeColumnarPayload(
            prefixes=("pkg.mod",),
            kinds=("function",),
            prefix=(0,),
            qualname=("a",),
            kind=(0,),
            reference_count=(-1,),
        )
    with pytest.raises(ValueError, match="must be sorted"):
        DeadCodeColumnarPayload(
            prefixes=("pkg.mod",),
            kinds=("function",),
            prefix=(0, 0),
            qualname=("b", "a"),
            kind=(0, 0),
            reference_count=(0, 0),
        )
    with pytest.raises(ValueError, match="non-negative"):
        DeadCodeMarkerException(row=0, runtime_marker_count=-1, source_markers=())
    with pytest.raises(ValueError, match="sorted and unique"):
        DeadCodeMarkerException(
            row=0, runtime_marker_count=1, source_markers=(("z", "1"), ("a", "1"))
        )
    with pytest.raises(ValueError, match="paths must be sorted"):
        ThinIdentityTable(paths=("b.py", "a.py"))
    with pytest.raises(ValueError, match="repository-relative"):
        ThinIdentityTable(paths=("/abs.py",))
    with pytest.raises(ValueError, match="cannot carry a node kind"):
        ThinIdentityTable(
            paths=("pkg/mod.py",),
            module_null=(0,),
            node_kind_exc=((0, "module_file"),),
        )

    with pytest.raises(ValueError, match="parameter_defs table"):
        _api_payload(
            parameter_defs=(
                ApiParameterDef(
                    name="b",
                    kind="pos_or_kw",
                    has_default=False,
                    annotation_digest=None,
                ),
                ApiParameterDef(
                    name="a",
                    kind="pos_or_kw",
                    has_default=False,
                    annotation_digest=None,
                ),
            )
        )
    with pytest.raises(ValueError, match="parameter_lists table"):
        _api_payload(parameter_lists=((), ()))
    with pytest.raises(ValueError, match="must be sorted"):
        _api_payload(
            owner=(0, 0),
            name=("b", "a"),
            symbol_kind=(0, 0),
            visibility=(0, 0),
            returns_digest=(None, None),
            parameters=(0, 0),
        )


def _api_payload(
    *,
    parameter_defs: tuple[ApiParameterDef, ...] = (),
    parameter_lists: tuple[tuple[int, ...], ...] = ((),),
    owner: tuple[int, ...] = (0,),
    name: tuple[str, ...] = ("run",),
    symbol_kind: tuple[int, ...] = (0,),
    visibility: tuple[int, ...] = (0,),
    returns_digest: tuple[int | None, ...] = (None,),
    parameters: tuple[int, ...] = (0,),
) -> ApiSurfaceColumnarPayload:
    return ApiSurfaceColumnarPayload(
        identities=ThinIdentityTable(paths=("pkg/mod.py",)),
        digests=(),
        digest_meta=None,
        symbol_kinds=("function",),
        visibilities=("all",),
        parameter_defs=parameter_defs,
        parameter_lists=parameter_lists,
        owner=owner,
        name=name,
        symbol_kind=symbol_kind,
        visibility=visibility,
        returns_digest=returns_digest,
        parameters=parameters,
    )


def test_decoder_rejects_values_outside_a_closed_vocabulary() -> None:
    with pytest.raises(BaselineLaneValidationError, match="unknown dead-code"):
        decode_dead_code_lane(
            DeadCodeColumnarPayload(
                prefixes=("pkg.mod",),
                kinds=("mystery",),
                prefix=(0,),
                qualname=("run",),
                kind=(0,),
                reference_count=(0,),
            )
        )


def test_thin_identity_table_serves_null_modules_and_kind_exceptions() -> None:
    table = ThinIdentityTable(
        paths=("pkg/__init__.py", "pkg/mod.py", "scripts/tool.py"),
        module_null=(2,),
        node_kind_exc=((1, "regular_package"),),
    )

    package = table.identity(0).python_module
    assert package is not None
    assert (package.module, package.is_package, package.node_kind) == (
        "pkg",
        True,
        "regular_package",
    )
    forced = table.identity(1).python_module
    assert forced is not None
    assert (forced.node_kind, forced.is_package) == ("regular_package", True)
    assert table.identity(2).python_module is None


def test_dependency_decode_derives_empty_candidates_without_a_target() -> None:
    payload = DependencyColumnarPayload(
        identities=ThinIdentityTable(paths=("pkg/mod.py",)),
        modules=(),
        resolutions=("unresolved_relative",),
        syntax_kinds=("from_import",),
        source=(0,),
        requested_module=(None,),
        requested_names=((),),
        resolution=(0,),
        resolved_target=(None,),
        syntax_kind=(0,),
        level=(1,),
    )
    observation = decode_dependency_lane(payload).observations[0]

    assert observation.candidate_targets == ()
    assert observation.resolved_target is None
    assert observation.resolution == "unresolved_relative"


def _dependency_payload(
    *,
    source: tuple[int, ...] = (0,),
    requested_module: tuple[int | None, ...] = (0,),
    requested_names: tuple[tuple[int, ...], ...] = ((),),
    resolution: tuple[int, ...] = (0,),
    resolved_target: tuple[int | None, ...] = (0,),
    syntax_kind: tuple[int, ...] = (0,),
    level: tuple[int, ...] = (0,),
) -> DependencyColumnarPayload:
    return DependencyColumnarPayload(
        identities=ThinIdentityTable(paths=("pkg/mod.py",)),
        modules=("alpha", "beta"),
        resolutions=("analyzed",),
        syntax_kinds=("from_import",),
        source=source,
        requested_module=requested_module,
        requested_names=requested_names,
        resolution=resolution,
        resolved_target=resolved_target,
        syntax_kind=syntax_kind,
        level=level,
    )


def test_dependency_columnar_form_rejects_bad_levels_and_unsorted_rows() -> None:
    _dependency_payload()

    with pytest.raises(ValueError, match="level must be non-negative"):
        _dependency_payload(level=(-1,))
    with pytest.raises(ValueError, match="must be sorted"):
        _dependency_payload(
            source=(0, 0),
            requested_module=(1, 0),
            requested_names=((), ()),
            resolution=(0, 0),
            resolved_target=(0, 0),
            syntax_kind=(0, 0),
            level=(0, 0),
        )
    with pytest.raises(ValueError, match="outside its table"):
        _dependency_payload(requested_names=((9,),))


def _mixed_mechanism_bundle() -> ObservationBundle:
    """A bundle whose dependency shelf carries both mechanisms."""

    bundle = _bundle()
    facts = bundle.structural
    static_dep = facts.dependencies[0]
    return replace(
        bundle,
        structural=replace(
            facts,
            dependencies=(
                static_dep,
                replace(
                    static_dep,
                    syntax_kind="import",
                    requested_module="pkg.plugin",
                    requested_names=(),
                    resolved_target="pkg.plugin",
                    candidate_targets=("pkg.plugin",),
                    mechanism="dynamic",
                ),
                replace(
                    static_dep,
                    syntax_kind="import",
                    resolution="unresolved_dynamic",
                    requested_module=None,
                    requested_names=(),
                    resolved_target=None,
                    candidate_targets=(),
                    mechanism="dynamic",
                ),
            ),
        ),
    )


def _dependency_lane_payload(bundle: ObservationBundle) -> DependencyColumnarPayload:
    lane = next(
        lane
        for lane in build_observation_lanes(bundle)
        if lane.descriptor.name == "dependencies"
    )
    payload = lane.payload
    assert isinstance(payload, DependencyColumnarPayload)
    return payload


def test_dependency_mechanism_survives_the_columnar_round_trip() -> None:
    bundle = _mixed_mechanism_bundle()
    payload = _dependency_lane_payload(bundle)

    # The discriminator rides as an exception list, so only dynamic rows are
    # named and the static majority costs nothing on the wire.
    assert payload.mechanism_dynamic != ()
    assert len(payload.mechanism_dynamic) == 2

    decoded = decode_dependency_lane(payload)
    mechanisms = [row.mechanism for row in decoded.observations]
    assert mechanisms.count("dynamic") == 2
    assert mechanisms.count("static") == 1

    # Bijection: the opaque row keeps no target and no candidates, and the
    # resolved dynamic row keeps both.
    opaque = [
        row for row in decoded.observations if row.resolution == "unresolved_dynamic"
    ]
    assert len(opaque) == 1
    assert opaque[0].mechanism == "dynamic"
    assert opaque[0].resolved_target is None
    assert opaque[0].candidate_targets == ()
    resolved_dynamic = [
        row
        for row in decoded.observations
        if row.mechanism == "dynamic" and row.resolution != "unresolved_dynamic"
    ]
    assert len(resolved_dynamic) == 1
    assert resolved_dynamic[0].resolved_target == "pkg.plugin"
    assert resolved_dynamic[0].candidate_targets == ("pkg.plugin",)


def test_dependency_mechanism_is_order_independent_and_byte_stable() -> None:
    bundle = _mixed_mechanism_bundle()
    facts = bundle.structural
    reversed_bundle = replace(
        bundle,
        structural=replace(facts, dependencies=tuple(reversed(facts.dependencies))),
    )

    first = _lane_bytes(bundle)["dependencies"]
    again = _lane_bytes(bundle)["dependencies"]
    shuffled = _lane_bytes(reversed_bundle)["dependencies"]

    assert first == again == shuffled
    # A wire that lost the discriminator would collide with the static-only
    # encoding; it must not.
    assert first != _lane_bytes(_bundle())["dependencies"]


def _static_observation() -> ImportObservation:
    return _bundle().structural.dependencies[0]


def test_unresolved_import_observations_refuse_a_target_or_candidates() -> None:
    base = _static_observation()

    with pytest.raises(ValueError, match="cannot have a target"):
        replace(
            base,
            resolution="unresolved_dynamic",
            mechanism="dynamic",
            resolved_target="pkg.plugin",
            candidate_targets=(),
        )
    with pytest.raises(ValueError, match="cannot have candidate targets"):
        replace(
            base,
            resolution="unresolved_dynamic",
            mechanism="dynamic",
            resolved_target=None,
            candidate_targets=("pkg.plugin",),
        )


def test_resolved_import_observation_requires_a_target() -> None:
    with pytest.raises(ValueError, match="require a target"):
        replace(_static_observation(), resolved_target=None, candidate_targets=())


def test_only_a_dynamic_load_can_be_unresolved_dynamic() -> None:
    # A static import statement always names something; if it resolved to
    # nothing it is unresolved_relative, never unresolved_dynamic.
    with pytest.raises(ValueError, match="only a dynamic load"):
        replace(
            _static_observation(),
            resolution="unresolved_dynamic",
            mechanism="static",
            resolved_target=None,
            candidate_targets=(),
        )


def test_dynamic_load_argument_is_either_a_name_or_honestly_absent() -> None:
    assert DynamicLoadArgument(module=None).module is None
    assert DynamicLoadArgument(module="pkg.plugin").module == "pkg.plugin"

    # An empty string is neither: it would claim a resolved import of nothing.
    with pytest.raises(ValueError, match="cannot be empty"):
        DynamicLoadArgument(module="")
