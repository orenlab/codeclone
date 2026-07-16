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
