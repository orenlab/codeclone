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
    COMPLEXITY_ALGORITHM_REVISION,
    DESIGN_METRICS_ALGORITHM_REVISION,
    GATE_LANE_MATRIX_VERSION,
    HEALTH_INPUT_MANIFEST_VERSION,
    OBSERVATION_DIGEST_VERSION,
)
from codeclone.models import (
    AdoptionCount,
    DeadCandidate,
    DeadCodeColumnarPayload,
    DeadCodeObservation,
    DigestObject,
    EvaluationContract,
    FileIdentity,
    IntegerObservation,
    IntegerObservationPayload,
    ModuleDep,
    ModuleRegistryHandle,
    ObservationBundle,
    ResolvedSourceIdentity,
    RiskObservation,
    RiskObservationPayload,
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

# RE-FROZEN AT THE 39Y LANDING, all ten descriptors below.
#
# Every descriptor carries ``canonicalization_version``, and that field IS
# WIRE_VERSION, so the sanctioned "1" -> "2" wire cutover moves all ten digests
# at once regardless of what each lane did on its own axis. The move is
# therefore mechanical and total: a re-freeze that left ANY descriptor at its
# old value would mean the wire did not reach that lane. Determinism was proven
# before repinning -- two processes and two hash seeds produce these bytes.
#
# The per-lane notes below still record each lane's own reason, because those
# reasons outlive this landing and the wire cutover does not explain them.

# The two clone lanes still on the record wire (payload_schema "1"); their
# algorithm_revision is BASELINE_FINGERPRINT_VERSION, now "3".
_ACCEPTED_V1_DESCRIPTOR_DIGESTS = {
    "clones.blocks": "ec977f5c4661c774439dac49a3561691870b72fc2f9043ee6892bc150d7620ed",
    "clones.functions": (
        "5e9a994eac0df70a5d28c053855bc0560f2468595b11e313427451f0f0abf2c6"
    ),
}
# 39W moved exactly these seven lanes to a columnar payload.
# Every lane embedding the identity table moved one payload_schema when the
# table gained the mount dimension (mount_exc exception rows): the payload
# canonicalizer serializes that field even when empty. Schema change under
# controller authorization + the maintainer's standing schema-bump
# ratification; not test-greening. The normalise-to-"1" assertion below
# still pins the frozen pre-39U value, proving only the schema changed and
# MODULE_IDENTITY_VERSION did not.
_BUMPED_DESCRIPTOR_DIGESTS = {
    "adoption_counts": (
        "cd311dcc7e9739a99c41b8a5a6e3728c305b5ab50586581e7b95cb5b44ec37bc"
    ),
    # SANCTIONED golden change, F5 lane-contract migration (ruling
    # 2026-08-26).  The lane moved payload_schema "3" -> "4": its rows name
    # their entity with the owning source identity plus the BARE symbol,
    # the way the ratified ``(SYMBOL, canonical_signature_variant)`` key
    # does, instead of the producer's glued ``module:qualname``.  This is a
    # descriptor-only move — the payload bytes are byte-identical, the
    # encoder always split the glue on its way in — so the declared schema
    # is the only record that a stored artifact meant the other spelling.
    # Confinement is proven by this table, not asserted: exactly this
    # digest moves and the other nine stay at the values pinned here.
    # Pre-bump digest was
    # b51e5ccbe85a2e79aacb8ddc924452569c64ba966d2547033a87fdfec9addea1.
    "api_surface": ("769e1ac73b8b454af0e3cc98fec991668cbb90dadbb7a8b9d5c21f97d07e136c"),
    # SANCTIONED golden change, 39Y item 3. The two design-metric lanes moved
    # to DESIGN_METRICS_ALGORITHM_REVISION "2": their metric VALUES changed
    # meaning (metric facts are no longer gated by clone floors, CBO counts the
    # imported-domain and resolved-instantiation lanes, and the coupling risk
    # bands were re-derived), while their payload SHAPE did not, so this is an
    # algorithm_revision bump and not a payload_schema bump. Confinement was
    # proven before repinning: exactly these two descriptor digests move and
    # the other eight stay byte-identical to the values pinned here.
    #
    # Re-pinned at the 39Y landing merge: these two lanes also embed the
    # identity table, so they carry the mount-dimension payload_schema bump
    # from the other parent ("3" -> "4"). Neither parent's digest survives a
    # change on the other axis; the value below is the merged descriptor's,
    # under the wire cutover recorded at the top of this block.
    "coupling_cohesion_observations": (
        "f156c753bbfcb390cca1e97766a347a5a7b60441e9f7ede6f306482415e5e618"
    ),
    # SANCTIONED golden change, 39Y cycle 2b. Brief section 6, P1-7
    # consolidation ruling: rule-3 abstentions, live-root reasons and the Y9
    # observation-kind discriminator all extend this one lane, so they land
    # under ONE coordinated payload_schema bump ("2" -> "3") rather than three.
    # Pre-bump digest was
    # 4cfcfa0b0c02d3b12d890b8a12e4b4dc0673bc50f4574ff05060629765d462f9.
    "dead_code": ("2cce4c84f810d1268df814702938b38c9652a27a2f72c15cf164b1e83be8a0cf"),
    # SANCTIONED golden change, cycle-honesty wave. Dependency rows gained
    # binding time and the PEP 810 ``is_lazy`` marker under ONE coordinated
    # payload_schema bump ("5" -> "6") together with the G4 observation
    # projection. Pre-bump digest was
    # 9487ff03b6974056e1857cfe32e4860ea0fb3596bbe3290560671b03d32b4ef8.
    #
    # SANCTIONED golden change, cycle-policy split ("6" -> "7"). Unlike every
    # other entry here this bump adds no field: the payload SHAPE and the wire
    # bytes are unchanged. What moved is what a consumer derives from the rows.
    # Through "6" the metrics reconstruction dropped each row's binding, so
    # stored deferred/lazy/typing edges read as eager — every reconstructed
    # cycle came back ``import_cycle`` and a TYPE_CHECKING-only cycle sat in
    # the baseline's cycle set. Cycle kind now decides health, --fail-cycles,
    # and novelty gating, so a "6" artifact cannot answer the questions a "7"
    # reader asks of it. Confinement proven before repinning: exactly this one
    # descriptor digest moves and the other nine stay byte-identical to the
    # values pinned here. Pre-bump digest was
    # 2c533080e26a676bbf099998b23fb129b9a7c8731e9f31df6375eb5f14f2fd2c.
    "dependencies": (
        "7bf4c16877b8a2c3e7a8bd098525350c72a9c17f3a06a675e7d83361959c61fa"
    ),
    "module_identity": (
        "6550f3624d9644ab0626b26928a6d1f5fbbaf7c672e04a7128dc6706798206c7"
    ),
    # SANCTIONED golden change, Wave D (maintainer-ratified two-metric split).
    # The lane's algorithm_revision left the shared design-metric revision for
    # COMPLEXITY_ALGORITHM_REVISION "3": the public cyclomatic_complexity is
    # now the source-level decision count, so stored revision-"2" (CFG-McCabe)
    # values must stop comparing as trusted. Payload SHAPE did not move, so
    # this is an algorithm_revision bump and not a payload_schema bump.
    # Pre-Wave-D digest was
    # 7c5d29aa39c03fb2c3b7d18b0b48dfff387f36f349224d7ea734d0689d6553c6.
    #
    # SANCTIONED golden change, F1 lane-contract migration (ruling
    # 2026-08-26, fork (b)): the risk lane left the shared integer wire for
    # payload_schema "5" — rows carry the declaration-site ``start_line`` as
    # a KEY column, because @overload groups and property/setter pairs are
    # different declarations the bare key collapsed. Confinement proven
    # before repinning: exactly this one descriptor digest moves and the
    # other nine stay byte-identical to the values pinned here (the
    # coupling lane's wire is byte-identical by sha pair). Pre-bump digest
    # was 31d043fb8d49bad2a956fa786255769caf99e7eff843e8284ddab5b3ae70ed86.
    "risk_observations": (
        "cf80f437896063ecdffb536180b12028d1b2171eb8b2ca0cbded0b4dbc19f881"
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


def test_only_semantic_authority_advances_beyond_the_39w_lane_schemas() -> None:
    contract = build_observation_contract(
        collect_metrics=True,
        collect_dependencies=True,
        collect_dead_code=True,
        collect_api_surface=True,
        collect_semantic_authority=True,
    )
    descriptors = {descriptor.name: descriptor for descriptor in contract.descriptors}

    assert {
        name: descriptor.payload_schema
        for name, descriptor in descriptors.items()
        if descriptor.payload_schema != "1"
    } == {
        "adoption_counts": "2",
        # F5 lane-contract migration: "4" is a READER bump — the wire stays
        # byte-identical to "3", but the row's identity spelling moved from
        # the producer's glued ``module:qualname`` to the bare symbol the
        # ratified family key names, so a stored "3" lane reads
        # payload_schema_outdated / unavailable until it is regenerated.
        "api_surface": "4",
        "coupling_cohesion_observations": "4",
        # 39Y cycle 2b: the single consolidated bump this phase owes.
        "dead_code": "3",
        # Cycle-honesty wave: edge binding time + PEP 810 laziness ride the
        # dependency rows — one coordinated bump with the G4 observation field.
        # "7" is the cycle-policy split's reader bump: the wire form did NOT
        # change, but cycle membership and cycle kind derived from these rows
        # did, and those now decide health, --fail-cycles, and novelty gating.
        "dependencies": "7",
        "module_identity": "4",
        # F1 lane-contract migration: "5" adds the declaration-site KEY
        # column (start_line) to the risk wire; a stored "4" lane reads
        # payload_schema_outdated / unavailable until regenerated.
        "risk_observations": "5",
        "semantic_authority": "2",
    }
    # Both clone descriptors stay on the record wire.
    assert {
        name
        for name, descriptor in descriptors.items()
        if descriptor.payload_schema == "1"
    } == {"clones.blocks", "clones.functions"}

    # module_identity carries only declared moves: normalised back, its
    # descriptor digest is still the frozen pre-39U value. The 39Y landing
    # added the second axis -- canonicalization_version follows WIRE_VERSION --
    # so undoing both is what isolates the question this guard asks, and the
    # expected digest below is deliberately NOT re-frozen: it still proves that
    # MODULE_IDENTITY_VERSION and everything else in the descriptor held still
    # while the two sanctioned fields moved.
    assert (
        _descriptor_digest(
            replace(
                descriptors["module_identity"],
                payload_schema="1",
                canonicalization_version="1",
            )
        )
        == "85ccbadac461be9e606b4d76c3e1ec52a56adf1cbaaa61d4ade0deee1659c3b6"
    )
    bumped = {
        name: _descriptor_digest(descriptors.pop(name))
        for name in (
            "adoption_counts",
            "api_surface",
            "coupling_cohesion_observations",
            "dead_code",
            "dependencies",
            "module_identity",
            "risk_observations",
        )
    }
    assert bumped == _BUMPED_DESCRIPTOR_DIGESTS
    semantic = descriptors.pop("semantic_authority")
    assert semantic.payload_schema == "2"
    assert (
        _descriptor_digest(semantic)
        == "2682e13bb88a8ee24250c9c933a6de552f93149eebf0388af0abd4e73869cf1f"
    )
    assert {descriptor.payload_schema for descriptor in descriptors.values()} == {"1"}
    assert {
        name: _descriptor_digest(descriptor) for name, descriptor in descriptors.items()
    } == _ACCEPTED_V1_DESCRIPTOR_DIGESTS


def test_design_metric_lanes_carry_their_own_algorithm_revision() -> None:
    """Each design-metric lane rides its own algorithm revision (Wave D).

    The revisions are separate from OBSERVATION_DIGEST_VERSION so that
    changing how a metric is computed invalidates only the lanes whose values
    moved. Since Wave D the two design-metric lanes are also separate from
    each other: a complexity recount (COMPLEXITY_ALGORITHM_REVISION on
    ``risk_observations``) must never invalidate coupling observations
    (DESIGN_METRICS_ALGORITHM_REVISION on ``coupling_cohesion_observations``)
    and vice versa.
    """

    contract = build_observation_contract(
        collect_metrics=True,
        collect_dependencies=True,
        collect_dead_code=True,
        collect_api_surface=True,
        collect_semantic_authority=True,
    )
    by_revision: dict[str, set[str]] = {}
    for descriptor in contract.descriptors:
        by_revision.setdefault(descriptor.algorithm_revision, set()).add(
            descriptor.name
        )

    # All three revisions must be live and pairwise distinct in the contract
    # the runtime actually built. Comparing the constants directly is a
    # tautology the type checker settles statically (they are Literals), so it
    # could never fail at runtime; reading the descriptors makes the guard
    # real. If a revision vanished, or any two collapsed onto one value, the
    # lane assertions below would pass vacuously.
    design_revision_lanes = by_revision.get(DESIGN_METRICS_ALGORITHM_REVISION, set())
    complexity_revision_lanes = by_revision.get(COMPLEXITY_ALGORITHM_REVISION, set())
    plain_revision_lanes = by_revision.get(OBSERVATION_DIGEST_VERSION, set())
    assert design_revision_lanes and complexity_revision_lanes
    assert plain_revision_lanes
    assert design_revision_lanes.isdisjoint(complexity_revision_lanes)
    assert design_revision_lanes.isdisjoint(plain_revision_lanes)
    assert complexity_revision_lanes.isdisjoint(plain_revision_lanes)
    # Revision STRINGS collide across independent axes (module_identity is
    # also "2", the clone lanes are also "3"), so the buckets above prove
    # liveness and separation while the per-lane facts are asserted by name.
    revision_by_name = {
        descriptor.name: descriptor.algorithm_revision
        for descriptor in contract.descriptors
    }
    assert (
        revision_by_name["coupling_cohesion_observations"]
        == DESIGN_METRICS_ALGORITHM_REVISION
    )
    assert revision_by_name["risk_observations"] == COMPLEXITY_ALGORITHM_REVISION
    # The lanes that kept the plain observation revision must not have moved.
    assert by_revision[OBSERVATION_DIGEST_VERSION] == {
        "adoption_counts",
        "api_surface",
        "dead_code",
        "semantic_authority",
    }


def test_dead_code_bump_leaves_every_other_lane_descriptor_byte_identical() -> None:
    """39Y cycle 2b owes exactly one lane bump — this proves it took only one.

    A payload_schema bump rewrites that lane's descriptor digest and nothing
    else. Pinning the other nine here makes an accidental second bump a test
    failure rather than a silently rewritten baseline.
    """
    contract = build_observation_contract(
        collect_metrics=True,
        collect_dependencies=True,
        collect_dead_code=True,
        collect_api_surface=True,
        collect_semantic_authority=True,
    )
    digests = {
        descriptor.name: _descriptor_digest(descriptor)
        for descriptor in contract.descriptors
    }

    unchanged = {
        name: digest for name, digest in digests.items() if name != "dead_code"
    }

    assert unchanged == {
        **_ACCEPTED_V1_DESCRIPTOR_DIGESTS,
        **{
            name: digest
            for name, digest in _BUMPED_DESCRIPTOR_DIGESTS.items()
            if name != "dead_code"
        },
        "semantic_authority": (
            "2682e13bb88a8ee24250c9c933a6de552f93149eebf0388af0abd4e73869cf1f"
        ),
    }
    assert digests["dead_code"] == _BUMPED_DESCRIPTOR_DIGESTS["dead_code"]


def _dead_code_payload(bundle: ObservationBundle) -> DeadCodeColumnarPayload:
    payload = next(
        lane.payload
        for lane in build_observation_lanes(bundle)
        if lane.descriptor.name == "dead_code"
    )
    assert isinstance(payload, DeadCodeColumnarPayload)
    return payload


def test_dead_code_lane_carries_reasons_abstentions_and_the_kind_axis() -> None:
    """Every key the schema-3 bump added must be populated by real inputs.

    A payload key nothing can populate is a dead key, so this drives all three
    contents of the consolidated bump through the projection at once:
    live-root reasons, rule-3 abstentions, and the Y9 observation-kind axis.
    """
    candidates = (
        DeadCandidate(
            qualname="pkg.mod:framework_handler",
            local_name="framework_handler",
            filepath="pkg/mod.py",
            start_line=1,
            end_line=2,
            kind="function",
            live_root_reason="external_decorator",
        ),
        DeadCandidate(
            qualname="pkg.mod:Exported.method",
            local_name="method",
            filepath="pkg/mod.py",
            start_line=4,
            end_line=5,
            kind="method",
            live_root_reason="export_root",
        ),
        DeadCandidate(
            qualname="pkg.mod:Handler.handle",
            local_name="handle",
            filepath="pkg/mod.py",
            start_line=7,
            end_line=8,
            kind="method",
        ),
        DeadCandidate(
            qualname="pkg.mod:plain_unused",
            local_name="plain_unused",
            filepath="pkg/mod.py",
            start_line=10,
            end_line=11,
            kind="function",
        ),
    )

    bundle = build_observation_bundle(
        scan_root=Path("."),
        module_registry=_registry(),
        dead_candidates=candidates,
        abstained_qualnames=frozenset({"pkg.mod:Handler.handle"}),
    )
    payload = _dead_code_payload(bundle)

    # Rows sort by (prefix, qualname, kind): Exported.method, Handler.handle,
    # framework_handler, plain_unused.
    assert payload.qualname == (
        "Exported.method",
        "Handler.handle",
        "framework_handler",
        "plain_unused",
    )
    assert {(item.row, item.reason) for item in payload.live_roots} == {
        (0, "export_root"),
        (2, "external_decorator"),
    }
    assert payload.abstained == (1,)
    # The Y9 axis is a real column today, carrying the only kind that exists.
    assert payload.observation_kinds == ("symbol",)
    assert payload.observation_kind == (0, 0, 0, 0)


def test_a_live_root_is_never_also_recorded_as_an_abstention() -> None:
    """The two states are mutually exclusive: a root is proven live.

    Without this, a symbol held live by a root rule could still be counted as
    an abstention, which would inflate the opt-in gate with symbols the
    analysis is not actually unsure about.
    """
    candidate = DeadCandidate(
        qualname="pkg.mod:rooted",
        local_name="rooted",
        filepath="pkg/mod.py",
        start_line=1,
        end_line=2,
        kind="function",
        live_root_reason="external_decorator",
    )

    bundle = build_observation_bundle(
        scan_root=Path("."),
        module_registry=_registry(),
        dead_candidates=(candidate,),
        abstained_qualnames=frozenset({"pkg.mod:rooted"}),
    )
    payload = _dead_code_payload(bundle)

    assert payload.abstained == ()
    assert {item.reason for item in payload.live_roots} == {"external_decorator"}
    with pytest.raises(ValueError, match="cannot also carry a live root"):
        DeadCodeObservation(
            entity="pkg.mod:rooted",
            candidate_kind="function",
            reference_count=0,
            reachable=False,
            runtime_marker_count=0,
            live_root_reason="external_decorator",
            abstained=True,
        )


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


def test_risk_observation_validators_refuse_the_known_bad_shapes() -> None:
    """F1 row law: the declaration site is identity and must be positive;
    the shared integer-row refusals hold unchanged beside it."""

    source = ResolvedSourceIdentity(
        file=FileIdentity(path="pkg/mod.py"),
        python_module=None,
    )
    with pytest.raises(ValueError, match="declaration site"):
        RiskObservation(
            source=source,
            qualname="run",
            dimension="cyclomatic_complexity",
            numerator=1,
            start_line=0,
        )
    with pytest.raises(ValueError, match="numerators"):
        RiskObservation(
            source=source,
            qualname="run",
            dimension="cyclomatic_complexity",
            numerator=-1,
            start_line=1,
        )
    with pytest.raises(ValueError, match="glued identities"):
        RiskObservation(
            source=source,
            qualname="pkg.mod:run",
            dimension="cyclomatic_complexity",
            numerator=1,
            start_line=1,
        )
    with pytest.raises(ValueError, match="repository-relative"):
        RiskObservation(
            source=ResolvedSourceIdentity(
                file=FileIdentity(path="/abs/pkg/mod.py"),
                python_module=None,
            ),
            qualname="run",
            dimension="cyclomatic_complexity",
            numerator=1,
            start_line=1,
        )
    with pytest.raises(ValueError, match="entity population"):
        RiskObservationPayload(
            observations=(
                RiskObservation(
                    source=source,
                    qualname="run",
                    dimension="cyclomatic_complexity",
                    numerator=1,
                    start_line=1,
                ),
            ),
            entity_population=0,
        )


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


def test_near_miss_tokens_never_reach_an_observation_lane() -> None:
    """The near-miss statement domain is exempt from the fingerprint cutover.

    Every other identity domain moved to ccfp3 at the 39Y landing, because a
    digest whose meaning changed must not be able to equal one an older
    generation minted. ``ccnm:stmt`` stayed put on one premise: its tokens are
    compared for equality inside a run and never become published identity.

    That premise had no test. This is it. A unit carrying a statement sequence
    goes through the projection, and no lane payload may contain the tokens --
    if the near-miss sequence ever starts riding a lane, the exemption is void
    and that domain has to move with the rest.
    """

    token = "deadbeefdeadbeef"
    bundle = build_observation_bundle(
        scan_root=Path("."),
        module_registry=_registry(),
        units=(
            {
                "qualname": "pkg.mod:hot",
                "filepath": "pkg/mod.py",
                "cyclomatic_complexity": 3,
                "nesting_depth": 1,
                "start_line": 1,
                "end_line": 2,
                "statement_sequence": ((token, 1, 2),),
            },
        ),
    )

    encoded = orjson.dumps(
        [
            (lane.descriptor.name, lane.payload)
            for lane in build_observation_lanes(bundle)
        ],
        default=str,
    )

    assert token.encode() not in encoded, (
        "a near-miss statement token reached an observation lane; the "
        "ccnm:stmt domain is published identity and must move with "
        "BASELINE_FINGERPRINT_VERSION"
    )
