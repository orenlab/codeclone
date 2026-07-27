# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import orjson
import pytest

from codeclone.contracts import (
    GATE_LANE_MATRIX_VERSION,
    HEALTH_INPUT_MANIFEST_VERSION,
)
from codeclone.models import (
    AdoptionCount,
    DeadCodeObservation,
    DigestObject,
    EvaluationContract,
    FileIdentity,
    IntegerObservation,
    IntegerObservationPayload,
    ModuleDep,
    ModuleRegistryHandle,
    ResolvedSourceIdentity,
)
from codeclone.observations.contracts import (
    ObservationContractError,
    build_observation_contract,
    validate_emitted_lanes,
)
from codeclone.observations.lanes import build_observation_lanes
from codeclone.observations.projection import build_observation_bundle
from codeclone.report.gates.evaluator import HEALTH_INPUT_LANES
from tests._ast_metrics_helpers import module_registry_context


def _registry() -> ModuleRegistryHandle:
    return module_registry_context(
        filepath="pkg/mod.py",
        module_name="pkg.mod",
        inventory_modules=("pkg.dep",),
    )[1]


TEST_OBSERVATION_BUNDLE = build_observation_bundle(
    scan_root=Path("."), module_registry=_registry()
)

_ACCEPTED_V1_DESCRIPTOR_DIGESTS = {
    "adoption_counts": (
        "26c87d090b1e6f745df028d8266471b99a7dd3742d5f55c66df8c7bc001f88ee"
    ),
    "api_surface": "8efe1f19bf4d29d1abb654af4a3601ada7861960b46f8130cd22d52fa5f15609",
    "clones.blocks": "1d178dfa537ab09521500e1170b954c058e3de3564597d30911c561d89282cf1",
    "clones.functions": (
        "7f87a5ec435e59c109da4cdf8eaf57441795e48a3d6431dfae3abb874c9f9c23"
    ),
    "dead_code": "845f17059d61b386e07822620c6f5387e37f52a1192a0471ce85d245d81564d8",
    "dependencies": "cf680b2291c90af360cf33045736d00cb5cd2e47d6f2446ca28abb6f843e272c",
    "semantic_authority": (
        "af551458e4577c554d38b66386ccf53ea0cdd7dd6dae0327203a24aa60acac68"
    ),
}
# 39U bumped exactly these two lanes to payload schema "2".
_BUMPED_DESCRIPTOR_DIGESTS = {
    "coupling_cohesion_observations": (
        "157ae814a6f05b33b6181bfc409f4ef31f4e13832dceb0ea044fb75fa869dca2"
    ),
    "risk_observations": (
        "b40b0d362f530b2006393558ae770d82926e03484aef14b773bc4cd4b8022aa4"
    ),
}


def _descriptor_digest(descriptor: object) -> str:
    payload = orjson.dumps(descriptor, option=orjson.OPT_SORT_KEYS)
    return hashlib.sha256(payload).hexdigest()


def test_observation_contract_is_closed_and_semantic_absence_is_real() -> None:
    bundle = build_observation_bundle(
        scan_root=Path("."),
        module_registry=_registry(),
        collect_api_surface=False,
    )
    lanes = build_observation_lanes(bundle)

    assert bundle.semantic is None
    assert "semantic_authority" not in bundle.contract.enabled_lanes
    assert "api_surface" not in bundle.contract.enabled_lanes
    assert "module_identity" in bundle.contract.enabled_lanes
    assert tuple(lane.descriptor.name for lane in lanes) == (
        bundle.contract.enabled_lanes
    )


def test_only_the_two_infected_lanes_and_module_identity_advance_payload_schema() -> (
    None
):
    contract = build_observation_contract(
        collect_metrics=True,
        collect_dependencies=True,
        collect_dead_code=True,
        collect_api_surface=True,
        collect_semantic_authority=True,
    )
    descriptors = {descriptor.name: descriptor for descriptor in contract.descriptors}

    assert {
        name
        for name, descriptor in descriptors.items()
        if descriptor.payload_schema == "2"
    } == {"coupling_cohesion_observations", "module_identity", "risk_observations"}

    module_identity = descriptors.pop("module_identity")
    assert _descriptor_digest(replace(module_identity, payload_schema="1")) == (
        "85ccbadac461be9e606b4d76c3e1ec52a56adf1cbaaa61d4ade0deee1659c3b6"
    )
    bumped = {
        name: _descriptor_digest(descriptors.pop(name))
        for name in ("coupling_cohesion_observations", "risk_observations")
    }
    assert bumped == _BUMPED_DESCRIPTOR_DIGESTS
    assert {descriptor.payload_schema for descriptor in descriptors.values()} == {"1"}
    assert {
        name: _descriptor_digest(descriptor) for name, descriptor in descriptors.items()
    } == _ACCEPTED_V1_DESCRIPTOR_DIGESTS


def test_missing_emitted_lane_is_a_typed_contract_failure() -> None:
    bundle = build_observation_bundle(scan_root=Path("."), module_registry=_registry())
    lanes = build_observation_lanes(bundle)

    with pytest.raises(ObservationContractError, match="missing="):
        validate_emitted_lanes(bundle.contract, lanes[:-1])


def test_evaluation_contract_cannot_change_observation_identity() -> None:
    bundle = build_observation_bundle(scan_root=Path("."), module_registry=_registry())
    before = EvaluationContract(
        health_algorithm_revision="1",
        gate_algorithm_revision="1",
        gate_thresholds_digest="1" * 64,
        gate_lane_matrix_version=GATE_LANE_MATRIX_VERSION,
        health_input_manifest_version=HEALTH_INPUT_MANIFEST_VERSION,
        health_input_lanes=HEALTH_INPUT_LANES,
        active_gate_lane_requirements=(),
    )
    after = replace(before, gate_thresholds_digest="2" * 64)

    assert before != after
    assert bundle.digest() == bundle.observation_digest
    with pytest.raises(ValueError, match="matrix versions"):
        replace(before, gate_lane_matrix_version="")
    with pytest.raises(ValueError, match="health input lanes"):
        replace(
            before,
            health_input_lanes=("module_identity", "clones.functions"),
        )
    with pytest.raises(ValueError, match="gate requirements"):
        replace(
            before,
            active_gate_lane_requirements=(
                ("z", ("module_identity",)),
                ("a", ("module_identity",)),
            ),
        )
    with pytest.raises(ValueError, match="active gate lanes"):
        replace(
            before,
            active_gate_lane_requirements=(
                ("gate", ("module_identity", "clones.functions")),
            ),
        )


def test_observation_bundle_digest_is_input_order_independent() -> None:
    function_a = f"{'a' * 64}|0-19"
    function_b = f"{'b' * 64}|20+"
    block_c = "|".join(("c" * 64, "1" * 64, "2" * 64, "3" * 64))
    block_d = "|".join(("d" * 64, "4" * 64, "5" * 64, "6" * 64))
    first = build_observation_bundle(
        scan_root=Path("."),
        module_registry=_registry(),
        function_clone_keys=(function_b, function_a),
        block_clone_keys=(block_d, block_c),
    )
    second = build_observation_bundle(
        scan_root=Path("."),
        module_registry=_registry(),
        function_clone_keys=(function_a, function_b),
        block_clone_keys=(block_c, block_d),
    )

    assert first.structural == second.structural
    assert first.digest() == second.digest()


def test_lane_descriptor_and_contract_reject_noncanonical_shapes() -> None:
    bundle = TEST_OBSERVATION_BUNDLE
    descriptor = bundle.contract.descriptors[0]

    with pytest.raises(ValueError, match="sorted"):
        replace(
            descriptor,
            required_contracts=(
                ("z", "1"),
                ("a", "1"),
            ),
        )
    with pytest.raises(ValueError, match="unique"):
        replace(
            descriptor,
            required_contracts=(
                ("key", "1"),
                ("key", "2"),
            ),
        )
    with pytest.raises(ValueError, match="non-empty"):
        replace(descriptor, payload_schema="")
    with pytest.raises(ValueError, match="digest version"):
        replace(bundle.contract, observation_digest_version="")
    with pytest.raises(ValueError, match="sorted and unique"):
        replace(
            bundle.contract,
            enabled_lanes=("module_identity", "clones.blocks"),
        )
    with pytest.raises(ValueError, match="exactly match"):
        replace(bundle.contract, descriptors=bundle.contract.descriptors[:-1])
    with pytest.raises(ValueError, match="module_identity"):
        replace(
            bundle.contract,
            enabled_lanes=("clones.blocks", "clones.functions"),
            descriptors=tuple(
                item
                for item in bundle.contract.descriptors
                if item.name in {"clones.blocks", "clones.functions"}
            ),
        )


def test_observation_models_reject_invalid_counts_and_evaluation_contracts() -> None:
    with pytest.raises(ValueError, match="algorithm revisions"):
        EvaluationContract(
            health_algorithm_revision="",
            gate_algorithm_revision="1",
            gate_thresholds_digest="1" * 64,
            gate_lane_matrix_version=GATE_LANE_MATRIX_VERSION,
            health_input_manifest_version=HEALTH_INPUT_MANIFEST_VERSION,
            health_input_lanes=HEALTH_INPUT_LANES,
            active_gate_lane_requirements=(),
        )
    with pytest.raises(ValueError, match="64 lowercase hex"):
        EvaluationContract(
            health_algorithm_revision="1",
            gate_algorithm_revision="1",
            gate_thresholds_digest="x" * 64,
            gate_lane_matrix_version=GATE_LANE_MATRIX_VERSION,
            health_input_manifest_version=HEALTH_INPUT_MANIFEST_VERSION,
            health_input_lanes=HEALTH_INPUT_LANES,
            active_gate_lane_requirements=(),
        )
    with pytest.raises(ValueError, match="non-negative"):
        DeadCodeObservation(
            entity="pkg.mod:run",
            candidate_kind="function",
            reference_count=-1,
            reachable=False,
            runtime_marker_count=0,
        )
    with pytest.raises(ValueError, match="sorted and unique"):
        DeadCodeObservation(
            entity="pkg.mod:run",
            candidate_kind="function",
            reference_count=0,
            reachable=False,
            runtime_marker_count=0,
            source_markers=(("z", "1"), ("a", "1")),
        )
    source = ResolvedSourceIdentity(
        file=FileIdentity(path="pkg/mod.py"),
        python_module=None,
    )
    with pytest.raises(ValueError, match="numerators"):
        IntegerObservation(
            source=source,
            qualname="run",
            dimension="risk",
            numerator=-1,
        )
    with pytest.raises(ValueError, match="repository-relative"):
        IntegerObservation(
            source=ResolvedSourceIdentity(
                file=FileIdentity(path="/abs/pkg/mod.py"),
                python_module=None,
            ),
            qualname="run",
            dimension="risk",
            numerator=1,
        )
    with pytest.raises(ValueError, match="glued identities"):
        IntegerObservation(
            source=source,
            qualname="pkg.mod:run",
            dimension="risk",
            numerator=1,
        )
    with pytest.raises(ValueError, match="non-empty"):
        IntegerObservation(
            source=source,
            qualname="",
            dimension="risk",
            numerator=1,
        )
    with pytest.raises(ValueError, match="entity population must be non-negative"):
        IntegerObservationPayload(observations=(), entity_population=-1)
    with pytest.raises(ValueError, match="entity population"):
        IntegerObservationPayload(
            observations=(
                IntegerObservation(
                    source=source,
                    qualname="run",
                    dimension="risk",
                    numerator=1,
                ),
            ),
            entity_population=0,
        )
    with pytest.raises(ValueError, match="non-negative/positive"):
        AdoptionCount(scope="pkg.mod", feature="typing", numerator=0, denominator=0)
    with pytest.raises(ValueError, match="cannot exceed"):
        AdoptionCount(scope="pkg.mod", feature="typing", numerator=2, denominator=1)


def test_bundle_rejects_invalid_cross_links_and_digest_contracts() -> None:
    bundle = TEST_OBSERVATION_BUNDLE
    with pytest.raises(ValueError, match="scope must be sorted and unique"):
        replace(bundle, analysis_scope=bundle.analysis_scope * 2)
    with pytest.raises(ValueError, match="wrong digest domain"):
        replace(
            bundle,
            observation_digest=DigestObject(
                domain="codeclone.source-content.v1",
                algorithm="sha256",
                value="1" * 64,
            ),
        )
    semantic_contract = build_observation_contract(
        collect_metrics=True,
        collect_dependencies=True,
        collect_dead_code=True,
        collect_api_surface=True,
        collect_semantic_authority=True,
    )
    with pytest.raises(ValueError, match="semantic lane presence"):
        replace(bundle, contract=semantic_contract)


def test_dependency_sources_resolve_by_path_or_fail_typed() -> None:
    path_dependency = ModuleDep(
        source="pkg/mod.py",
        target="pkg.dep",
        import_type="from_import",
        line=1,
        resolution="analyzed",
        requested_module="pkg.dep",
        requested_names=("value",),
        candidate_targets=("pkg.dep",),
    )
    bundle = build_observation_bundle(
        scan_root=Path("."),
        module_registry=_registry(),
        module_deps=(path_dependency,),
    )
    assert bundle.structural.dependencies[0].source.file.path == "pkg/mod.py"

    with pytest.raises(ObservationContractError, match="dependency source"):
        build_observation_bundle(
            scan_root=Path("."),
            module_registry=_registry(),
            module_deps=(replace(path_dependency, source="missing.py"),),
        )


def test_duplicate_emitted_lanes_are_a_typed_contract_failure() -> None:
    bundle = TEST_OBSERVATION_BUNDLE
    lanes = build_observation_lanes(bundle)
    with pytest.raises(ObservationContractError, match="sorted and duplicate-free"):
        validate_emitted_lanes(bundle.contract, (lanes[0], lanes[0]))


def test_observation_sources_must_exist_in_the_module_registry() -> None:
    with pytest.raises(
        ObservationContractError, match="absent from the module registry"
    ):
        build_observation_bundle(
            scan_root=Path("."),
            module_registry=_registry(),
            units=(
                {
                    "filepath": "pkg/ghost.py",
                    "qualname": "pkg.ghost:run",
                    "cyclomatic_complexity": 1,
                    "nesting_depth": 0,
                },
            ),
        )
