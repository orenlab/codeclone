# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from codeclone.analysis.normalizer import NormalizationConfig
from codeclone.analysis.units import extract_units_and_stats_from_source
from codeclone.contracts import AUTHORITY_ANALYSIS_REVISION
from codeclone.models import (
    AuthorityCandidateLevel,
    AuthorityRegistry,
    AuthorityRegistryEntry,
    EventKind,
    FactRef,
    FunctionContractSummary,
    FunctionRelationshipFacts,
    RelationshipRecord,
    SemanticEvent,
)
from codeclone.paths.module_identity.inventory import build_module_registry
from codeclone.semantics.authority import (
    authority_candidate_score,
    build_semantic_authority,
)
from codeclone.semantics.registry import (
    AuthorityRegistryError,
    parse_authority_registry,
)

_HASH_ROOT = "operation:canonical_operation:hashlib.sha256"
_STRIP_ROOT = "operation:pure_builtin:strip"


def _authority_registry(
    *,
    owner: str,
    required_provenance: tuple[str, ...] = (_HASH_ROOT,),
    adapters: tuple[str, ...] = (),
) -> AuthorityRegistry:
    return AuthorityRegistry(
        version="1",
        entries=(
            AuthorityRegistryEntry(
                contract_id="example.contract/v1",
                canonical_owner=owner,
                allowed_adapters=adapters,
                forbidden_raw_inputs=(),
                required_provenance=required_provenance,
            ),
        ),
    )


def _event(
    function: str,
    *,
    ordinal: int,
    kind: EventKind = "compute_digest",
    subject: str = "hashlib.sha256",
    guards: tuple[str, ...] = (),
) -> SemanticEvent:
    event_id = f"{function}#{ordinal:06d}"
    return SemanticEvent(
        event_id=event_id,
        kind=kind,
        subject=subject,
        inputs=(FactRef(kind="param", ref="value"),),
        output=FactRef(kind="event", ref=event_id),
        guards=guards,
        location=("pkg/mod.py", ordinal),
        resolution="resolved",
    )


def _summary(
    function: str,
    *events: SemanticEvent,
    unresolved: bool = False,
) -> FunctionContractSummary:
    return FunctionContractSummary(
        function=function,
        events=events,
        param_flows=tuple(("value", event.event_id) for event in events),
        returns=(events[-1].output,)
        if events and events[-1].output is not None
        else (),
        unresolved_flow=unresolved,
    )


def _relationship(
    source: str,
    target: str | None,
    *,
    line: int,
) -> FunctionRelationshipFacts:
    return FunctionRelationshipFacts(
        source_qualname=source,
        relationships=(
            RelationshipRecord(
                relation_kind="call",
                resolution_status="resolved" if target is not None else "unresolved",
                origin_lane="production",
                source_qualname=source,
                target_qualname=target,
                path="pkg/mod.py",
                line=line,
                expression=None,
                resolution_rule="semantic_authority_test",
            ),
        ),
    )


def test_candidate_levels_have_a_closed_integer_order() -> None:
    levels: tuple[AuthorityCandidateLevel, ...] = (
        "exact_contract_ir",
        "same_effect_signature",
        "same_output_fact_and_input_family",
        "overlapping_transform_chain",
        "divergent_projection",
    )
    assert tuple(authority_candidate_score(level) for level in levels) == (
        5,
        4,
        3,
        2,
        1,
    )


def test_authority_registry_is_closed_sorted_and_versioned() -> None:
    registry = parse_authority_registry(
        [
            {
                "contract_id": "example.contract/v1",
                "canonical_owner": "pkg.mod:owner",
                "allowed_adapters": ["pkg.mod:adapter"],
                "forbidden_raw_inputs": ["raw:payload"],
                "required_provenance": [_HASH_ROOT],
            }
        ]
    )

    assert registry.version == "1"
    assert registry.entries[0].contract_id == "example.contract/v1"
    assert parse_authority_registry(registry) is registry
    assert parse_authority_registry(None).entries == ()
    with pytest.raises(AuthorityRegistryError, match="unknown"):
        parse_authority_registry(
            [
                {
                    "contract_id": "example.contract/v1",
                    "canonical_owner": "pkg.mod:owner",
                    "allowed_adapters": [],
                    "forbidden_raw_inputs": [],
                    "required_provenance": [_HASH_ROOT],
                    "extra": True,
                }
            ]
        )
    with pytest.raises(AuthorityRegistryError, match="sorted"):
        parse_authority_registry(
            [
                {
                    "contract_id": "example.contract/v1",
                    "canonical_owner": "pkg.mod:owner",
                    "allowed_adapters": ["pkg.mod:z", "pkg.mod:a"],
                    "forbidden_raw_inputs": [],
                    "required_provenance": [_HASH_ROOT],
                }
            ]
        )


def test_authority_registry_rejects_every_noncanonical_boundary() -> None:
    def row(**overrides: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "contract_id": "example.contract/v1",
            "canonical_owner": "pkg.mod:owner",
            "allowed_adapters": [],
            "forbidden_raw_inputs": [],
            "required_provenance": [_HASH_ROOT],
        }
        payload.update(overrides)
        return payload

    missing = row()
    del missing["required_provenance"]
    invalid_cases: tuple[tuple[object, str], ...] = (
        ("not-a-sequence", "array of tables"),
        (["not-a-table"], "must be a table"),
        ([missing], "missing authority registry key"),
        ([row(contract_id=" ")], "non-empty string"),
        ([row(contract_id="invalid")], "<name>/v<positive-int>"),
        ([row(canonical_owner="invalid")], "module:symbol identity"),
        ([row(allowed_adapters="pkg.mod:adapter")], r"list\[str\]"),
        ([row(allowed_adapters=["invalid"])], "module:symbol identities"),
        ([row(allowed_adapters=["pkg.mod:owner"])], "repeat canonical_owner"),
        (
            [
                row(
                    contract_id="z.contract/v1",
                    canonical_owner="pkg.mod:z_owner",
                ),
                row(
                    contract_id="a.contract/v1",
                    canonical_owner="pkg.mod:a_owner",
                ),
            ],
            "sorted by contract_id",
        ),
        (
            [
                row(),
                row(canonical_owner="pkg.mod:other"),
            ],
            "contract_id values must be unique",
        ),
        (
            [
                row(),
                row(contract_id="example.other/v1"),
            ],
            "canonical_owner values must be unique",
        ),
    )

    for value, message in invalid_cases:
        with pytest.raises(AuthorityRegistryError, match=message):
            parse_authority_registry(value)


def test_governed_adapter_is_legal_and_suppression_does_not_legalize_shadow() -> None:
    owner_name = "pkg.mod:owner"
    adapter_name = "pkg.mod:adapter"
    shadow_name = "pkg.mod:shadow"
    owner = _summary(owner_name, _event(owner_name, ordinal=1))
    adapter = _summary(adapter_name, _event(adapter_name, ordinal=1))
    shadow = _summary(shadow_name, _event(shadow_name, ordinal=1))
    result = build_semantic_authority(
        (shadow, adapter, owner),
        (_relationship(adapter_name, owner_name, line=1),),
        registry=_authority_registry(owner=owner_name, adapters=(adapter_name,)),
        suppressed_rules={
            shadow_name: frozenset({"duplicate-responsibility"}),
        },
    )

    statuses = {
        sink.sink_identity: sink.authority_status for sink in result.governed_sinks
    }
    assert statuses[owner_name] == "authoritative"
    assert statuses[adapter_name] == "adapter"
    assert statuses[shadow_name] == "shadow"
    shadow_violations = tuple(
        item for item in result.violations if item.sink_identity == shadow_name
    )
    assert shadow_violations
    assert all(item.suppressed for item in shadow_violations)
    assert not any(item.sink_identity == adapter_name for item in result.violations)


def test_enforcement_emits_all_six_closed_violation_kinds() -> None:
    owner_name = "pkg.mod:owner"
    owner = _summary(owner_name, _event(owner_name, ordinal=1))
    first_name = "pkg.mod:first"
    second_name = "pkg.mod:second"
    exact_result = build_semantic_authority(
        (
            owner,
            _summary(first_name, _event(first_name, ordinal=1)),
            _summary(second_name, _event(second_name, ordinal=1)),
        ),
        (),
        registry=_authority_registry(owner=owner_name),
    )

    projection_name = "pkg.mod:projection"
    projection = _summary(
        projection_name,
        _event(projection_name, ordinal=1),
        _event(
            projection_name,
            ordinal=2,
            kind="resolve_identity",
            subject="str.strip",
        ),
    )
    projection_result = build_semantic_authority(
        (owner, projection),
        (),
        registry=_authority_registry(owner=owner_name),
    )

    mixed_name = "pkg.mod:mixed"
    mixed = _summary(
        mixed_name,
        _event(mixed_name, ordinal=1),
        _event(
            mixed_name,
            ordinal=2,
            kind="resolve_identity",
            subject="str.strip",
        ),
    )
    mixed_result = build_semantic_authority(
        (owner, mixed),
        (_relationship(mixed_name, owner_name, line=1),),
        registry=_authority_registry(owner=owner_name),
    )

    failed_owner = _summary(
        owner_name,
        _event(owner_name, ordinal=1),
        unresolved=True,
    )
    failure_result = build_semantic_authority(
        (failed_owner, _summary(first_name, _event(first_name, ordinal=1))),
        (),
        registry=_authority_registry(owner=owner_name),
    )

    different_name = "pkg.mod:different"
    different = _summary(
        different_name,
        _event(
            different_name,
            ordinal=1,
            kind="resolve_identity",
            subject="str.strip",
        ),
    )
    canonicalization_result = build_semantic_authority(
        (owner, different),
        (),
        registry=_authority_registry(
            owner=owner_name,
            required_provenance=(_HASH_ROOT, _STRIP_ROOT),
        ),
    )

    kinds = {
        violation.kind
        for result in (
            exact_result,
            projection_result,
            mixed_result,
            failure_result,
            canonicalization_result,
        )
        for violation in result.violations
    }
    assert kinds == {
        "multiple_independent_producers",
        "shadow_projection",
        "owner_bypass",
        "reconstructed_contract",
        "divergent_failure_semantics",
        "divergent_canonicalization",
    }


def test_exact_independent_producers_are_report_only_shadow_candidates() -> None:
    first = _summary("pkg.mod:first", _event("pkg.mod:first", ordinal=1))
    second = _summary("pkg.mod:second", _event("pkg.mod:second", ordinal=1))

    result = build_semantic_authority((second, first), ())

    assert result.algorithm_revision == AUTHORITY_ANALYSIS_REVISION == "1"
    assert result.candidates[0].level == "exact_contract_ir"
    assert result.candidates[0].score == 5
    assert result.candidates[0].producers == (
        "pkg.mod:first",
        "pkg.mod:second",
    )
    assert result.candidates[0].independence is True
    assert len({contract.wire for contract in result.contract_ir.contracts}) == 1
    assert len({node.effect_signature for node in result.graph.nodes}) == 1
    assert {sink.authority_status for sink in result.sinks} == {"shadow"}
    field_name = "algorithm_revision"
    with pytest.raises(FrozenInstanceError):
        setattr(result, field_name, "2")


def test_effect_signature_erases_guards_but_exact_ir_remains_stronger() -> None:
    first = _summary("pkg.mod:first", _event("pkg.mod:first", ordinal=1))
    guarded = _summary(
        "pkg.mod:guarded",
        _event(
            "pkg.mod:guarded",
            ordinal=1,
            guards=("feature_enabled:truthy",),
        ),
    )

    result = build_semantic_authority((guarded, first), ())

    assert len({contract.wire for contract in result.contract_ir.contracts}) == 2
    assert len({node.effect_signature for node in result.graph.nodes}) == 1
    assert result.candidates[0].level == "same_effect_signature"


def test_owner_consulted_then_changed_is_mixed_and_dynamic_is_unavailable() -> None:
    owner = _summary("pkg.mod:owner", _event("pkg.mod:owner", ordinal=1))
    mixed_call = _event("pkg.mod:mixed", ordinal=1)
    mixed_edit = _event(
        "pkg.mod:mixed",
        ordinal=2,
        kind="resolve_identity",
        subject="str.strip",
    )
    mixed = _summary("pkg.mod:mixed", mixed_call, mixed_edit)
    dynamic = _summary(
        "pkg.mod:dynamic",
        _event("pkg.mod:dynamic", ordinal=1),
        unresolved=True,
    )

    result = build_semantic_authority(
        (dynamic, mixed, owner),
        (
            _relationship("pkg.mod:mixed", "pkg.mod:owner", line=1),
            _relationship("pkg.mod:dynamic", None, line=1),
        ),
    )
    statuses = {sink.sink_identity: sink.authority_status for sink in result.sinks}

    assert statuses["pkg.mod:mixed"] == "mixed"
    assert statuses["pkg.mod:dynamic"] == "unavailable"
    assert statuses["pkg.mod:owner"] == "shadow"
    assert any(candidate.semantic_divergence for candidate in result.candidates)


def test_authority_graph_is_stable_under_input_shuffle() -> None:
    first = _summary("pkg.mod:first", _event("pkg.mod:first", ordinal=1))
    second = _summary("pkg.mod:second", _event("pkg.mod:second", ordinal=1))

    forward = build_semantic_authority((first, second), ())
    reverse = build_semantic_authority((second, first), ())

    assert forward == reverse


def test_frozen_incident_corpus_flags_all_classes_and_fail_closed_states() -> None:
    root = Path("tests/fixtures/semantic_authority").resolve()
    registry = build_module_registry(root=root)
    summaries: list[FunctionContractSummary] = []
    relationships: list[FunctionRelationshipFacts] = []
    for path in sorted(root.glob("*.py")):
        entry = registry.entries_by_path[path.name]
        _units, _blocks, _segments, _stats, metrics, _findings = (
            extract_units_and_stats_from_source(
                source=path.read_text("utf-8"),
                filepath=path.name,
                identity=entry.identity,
                registry=registry,
                cfg=NormalizationConfig(),
                min_loc=100,
                min_stmt=100,
            )
        )
        summaries.extend(metrics.semantic_facts.function_contract_summaries)
        relationships.extend(metrics.function_relationship_facts)

    result = build_semantic_authority(summaries, relationships)
    producer_sets = tuple(
        frozenset(candidate.producers) for candidate in result.candidates
    )
    statuses = {sink.sink_identity: sink.authority_status for sink in result.sinks}

    assert any(
        {
            "module_identity_producers:scanner_module_name",
            "module_identity_producers:blast_radius_module_name",
            "module_identity_producers:memory_module_key",
            "module_identity_producers:inventory_module_key",
            "module_identity_producers:renderer_module_prefix",
        }.issubset(producers)
        for producers in producer_sets
    )
    assert any(
        {
            "compatibility_checkers:baseline_compatibility",
            "compatibility_checkers:metrics_baseline_compatibility",
            "compatibility_checkers:cache_compatibility",
            "compatibility_checkers:memory_compatibility",
        }.issubset(producers)
        for producers in producer_sets
    )
    assert any(
        {
            "dual_artifact_writers:update_clone_baseline",
            "dual_artifact_writers:update_metrics_baseline",
        }.issubset(producers)
        or {
            "dual_artifact_writers:publish_baseline_updated",
            "dual_artifact_writers:update_metrics_baseline",
        }.issubset(producers)
        for producers in producer_sets
    )
    assert any(
        {
            "volatile_run_identity:report_run_identity",
            "volatile_run_identity:publish_run_reference",
        }.issubset(producers)
        for producers in producer_sets
    )
    assert statuses["module_identity_producers:mixed_module_name"] == "mixed"
    assert statuses["module_identity_producers:dynamic_module_name"] == ("unavailable")


def test_authority_bucket_and_reachability_helpers() -> None:
    from codeclone.semantics.authority import (
        _add_bucket,
        _candidate_for_sink,
        _reaches_other,
    )

    buckets: dict[str, set[str]] = {}
    _add_bucket(buckets, key="", function="pkg.mod:f")
    assert buckets == {}
    _add_bucket(buckets, key="fact", function="pkg.mod:f")
    assert buckets == {"fact": {"pkg.mod:f"}}

    diamond = {
        "a": ("b", "c"),
        "b": ("e",),
        "c": ("e",),
    }
    # e is visited twice; the second visit must be skipped, not looped.
    assert _reaches_other("a", members=frozenset({"missing"}), graph=diamond) is False
    assert _reaches_other("a", members=frozenset({"e"}), graph=diamond) is True

    assert _candidate_for_sink("pkg.mod:f", candidates=()) is None
