# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

import orjson
import pytest

import codeclone.observations.lanes as lanes_mod
from codeclone.models import (
    ApiParamSpec,
    ApiSurfaceObservationPayload,
    ClassMetrics,
    CloneObservationPayload,
    DeadCandidate,
    IntegerObservationPayload,
    ModuleApiSurface,
    ModuleDep,
    ModuleDocstringCoverage,
    ModuleIdentityObservationPayload,
    ModuleRegistryHandle,
    ModuleTypingCoverage,
    ObservationBundle,
    PublicSymbol,
    RuntimeReachabilityFact,
)
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
    assert isinstance(api_payload, ApiSurfaceObservationPayload)
    symbol = api_payload.symbols[0]
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

    assert isinstance(payload, ModuleIdentityObservationPayload)
    assert payload.manifest_digest is registry.manifest_digest
    assert payload.manifest_digest != payload.registry_digest
    assert payload.module_registry == tuple(
        entry for _path, entry in registry.entries_by_path.rows
    )
    assert tuple(entry.analyzed for entry in payload.module_registry) == (False, True)
    assert tuple(entry.internality for entry in payload.module_registry) == (
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
    assert isinstance(risk, IntegerObservationPayload)
    assert isinstance(coupling, IntegerObservationPayload)

    # The zero-valued nesting_depth row is absent; the observed function still counts.
    assert tuple(
        (item.qualname, item.dimension, item.numerator) for item in risk.observations
    ) == (("flat", "cyclomatic_complexity", 1),)
    assert risk.entity_population == 1

    # A class whose every dimension is zero emits nothing and stays in the population.
    assert coupling.observations == ()
    assert coupling.entity_population == 1
