# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Publish→reload round-trip guards for every baseline lane.

Every decode-side invariant needs an encode-side guarantee: a lane the tool
just published must always read back. These tests pin that pair for the whole
lane registry on edge-state fixtures, so a decoder that reconstructs a state
the live pipeline never produces — the unresolved-import candidate-target
crash — fails here before it can fail on a user's baseline. The CLI-surface
leg of the same guard lives in ``tests/test_cli_baseline_roundtrip.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from uuid import UUID

import pytest

import codeclone.observations.lanes as lanes_mod
from codeclone.baseline.container import build_container, read_container_v3
from codeclone.baseline.container_digest import (
    canonical_container_bytes,
    canonical_value_bytes,
)
from codeclone.baseline.lanes import (
    decode_adoption_lane,
    decode_api_surface_lane,
    decode_dead_code_lane,
    decode_dependency_lane,
    decode_integer_lane,
    decode_module_identity_lane,
)
from codeclone.models import (
    AdoptionColumnarPayload,
    ApiParamSpec,
    ApiSurfaceColumnarPayload,
    AuthorityGovernedSink,
    AuthorityGraph,
    AuthorityRegistry,
    AuthorityRegistryEntry,
    BaselineLane,
    ClassMetrics,
    CloneObservationPayload,
    ContainerReadSuccess,
    ContractIRBuildResult,
    DeadCandidate,
    DeadCodeColumnarPayload,
    DependencyColumnarPayload,
    IntegerColumnarPayload,
    ModuleApiSurface,
    ModuleDep,
    ModuleDocstringCoverage,
    ModuleIdentityColumnarPayload,
    ModuleRegistryHandle,
    ModuleTypingCoverage,
    ObservationBundle,
    PublicSymbol,
    RuntimeReachabilityFact,
    SemanticAuthorityObservationPayload,
    SemanticAuthorityResult,
    UnreachableStatementItem,
)
from codeclone.observations.projection import build_observation_bundle
from tests._ast_metrics_helpers import module_registry_context

_SCOPE_ID = UUID("019f7fa1-8866-7242-b0bf-0ff282cafbcb")
_FUNCTION_ID = f"{'a' * 64}|0-19"
_BLOCK_ID = "|".join(("b" * 64,) * 4)


def _registry() -> ModuleRegistryHandle:
    return module_registry_context(
        filepath="pkg/mod.py",
        module_name="pkg.mod",
        inventory_modules=("pkg.dep",),
    )[1]


def _edge_state_bundle() -> ObservationBundle:
    """A bundle whose lanes carry the states a decoder must survive.

    The dependency shelf holds the shape that crashed on the Django corpus:
    an unresolved relative import that still names its requested module. The
    dead-code shelf holds a live root, an abstention, and an unreachable
    region, so every stored exception column is populated.
    """

    semantic = SemanticAuthorityResult(
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
    return build_observation_bundle(
        scan_root=Path("."),
        module_registry=_registry(),
        function_clone_keys=(_FUNCTION_ID,),
        block_clone_keys=(_BLOCK_ID,),
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
            # The Django-corpus crash shape: the relative import escapes its
            # package, stays unresolved, and still names a requested module.
            ModuleDep(
                source="pkg.mod",
                target="",
                import_type="from_import",
                line=3,
                resolution="unresolved_relative",
                level=3,
                requested_module="models",
                requested_names=("Item",),
                candidate_targets=(),
            ),
            ModuleDep(
                source="pkg.mod",
                target="",
                import_type="import",
                line=4,
                resolution="unresolved_dynamic",
                candidate_targets=(),
                mechanism="dynamic",
            ),
            ModuleDep(
                source="pkg.mod",
                target="orjson",
                import_type="import",
                line=5,
                resolution="external",
                requested_module="orjson",
                candidate_targets=("orjson",),
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
            DeadCandidate(
                qualname="pkg.mod:exported",
                local_name="exported",
                filepath="pkg/mod.py",
                start_line=7,
                end_line=8,
                kind="function",
                live_root_reason="export_root",
            ),
            DeadCandidate(
                qualname="pkg.mod:Maybe.run",
                local_name="run",
                filepath="pkg/mod.py",
                start_line=10,
                end_line=11,
                kind="method",
            ),
        ),
        abstained_qualnames=frozenset({"pkg.mod:Maybe.run"}),
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
                "qualname": "pkg.mod:flat",
                "cyclomatic_complexity": 2,
                "nesting_depth": 1,
                "unreachable_statements": (
                    UnreachableStatementItem(
                        reason="after_terminator",
                        start_line=12,
                        end_line=13,
                        statement_count=2,
                    ),
                ),
            },
        ),
        class_metrics=(
            ClassMetrics(
                qualname="pkg.mod:Thing",
                filepath="pkg/mod.py",
                start_line=1,
                end_line=3,
                cbo=2,
                lcom4=1,
                method_count=1,
                instance_var_count=0,
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
                public_symbol_total=2,
                public_symbol_documented=1,
            ),
        ),
        semantic_authority=semantic,
    )


def _empty_bundle() -> ObservationBundle:
    """A bundle whose optional lanes are all empty."""

    return build_observation_bundle(
        scan_root=Path("."),
        module_registry=_registry(),
    )


def _reencoded(name: str, lane: BaselineLane) -> object:
    """Decode one stored lane and encode the decoded rows again.

    An unknown lane name fails loudly: a new lane must add its round-trip
    mapping here before it can ship, which is exactly the guard's point.
    """

    payload = lane.payload
    assert not isinstance(payload, dict), f"{name} lane was left opaque"
    if isinstance(payload, DependencyColumnarPayload):
        return lanes_mod._encode_dependency_lane(
            decode_dependency_lane(payload).observations
        )
    if isinstance(payload, DeadCodeColumnarPayload):
        return lanes_mod._encode_dead_code_lane(
            decode_dead_code_lane(payload).candidates
        )
    if isinstance(payload, IntegerColumnarPayload):
        decoded = decode_integer_lane(payload)
        return lanes_mod._encode_integer_lane(
            decoded.observations, decoded.entity_population
        )
    if isinstance(payload, AdoptionColumnarPayload):
        return lanes_mod._encode_adoption_lane(decode_adoption_lane(payload).counts)
    if isinstance(payload, ApiSurfaceColumnarPayload):
        return lanes_mod._encode_api_surface_lane(
            decode_api_surface_lane(payload).symbols
        )
    if isinstance(payload, ModuleIdentityColumnarPayload):
        return lanes_mod._encode_module_identity_lane(
            decode_module_identity_lane(payload)
        )
    if isinstance(
        payload, (CloneObservationPayload, SemanticAuthorityObservationPayload)
    ):
        return payload
    pytest.fail(f"lane {name!r} has no round-trip mapping; add one to this guard")


@pytest.mark.parametrize("bundle_factory", [_edge_state_bundle, _empty_bundle])
def test_every_registered_lane_round_trips_through_published_bytes(
    tmp_path: Path,
    bundle_factory: Callable[[], ObservationBundle],
) -> None:
    """Publish → reload → decode → re-encode is lossless for every lane."""

    bundle = bundle_factory()
    container = build_container(bundle, _SCOPE_ID)
    target = tmp_path / "baseline.json"
    target.write_bytes(canonical_container_bytes(container))
    result = read_container_v3(target, limit_bytes=target.stat().st_size)
    assert isinstance(result, ContainerReadSuccess)
    lanes = result.container.lanes

    assert set(lanes) == set(bundle.contract.enabled_lanes)
    for name in sorted(lanes):
        stored = lanes[name].payload
        again = _reencoded(name, lanes[name])
        assert canonical_value_bytes(again) == canonical_value_bytes(stored), name
