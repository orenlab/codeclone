# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import FrozenInstanceError, asdict

import pytest

from codeclone.analysis.normalizer import NormalizationConfig
from codeclone.analysis.units import extract_units_and_stats_from_source
from codeclone.contracts import CONTRACT_IR_VERSION
from codeclone.models import (
    ContractIRBuildResult,
    EventKind,
    FactRef,
    FunctionContractIR,
    FunctionContractSummary,
    FunctionRelationshipFacts,
    RelationshipRecord,
    SemanticEvent,
)
from codeclone.semantics.ir import build_contract_ir
from tests._ast_metrics_helpers import module_registry_context


def _event(
    *,
    function: str,
    ordinal: int,
    kind: EventKind,
    subject: str,
    inputs: tuple[FactRef, ...] = (),
    output: bool = False,
    guards: tuple[str, ...] = (),
    line: int | None = None,
) -> SemanticEvent:
    event_id = f"{function}#{ordinal:06d}"
    return SemanticEvent(
        event_id=event_id,
        kind=kind,
        subject=subject,
        inputs=inputs,
        output=FactRef(kind="event", ref=event_id) if output else None,
        guards=guards,
        location=("pkg/mod.py", line if line is not None else ordinal),
        resolution="resolved",
    )


def _summary(
    function: str,
    events: tuple[SemanticEvent, ...],
    *,
    param_flows: tuple[tuple[str, str], ...] = (),
    returns: tuple[FactRef, ...] = (),
    unresolved: bool = False,
) -> FunctionContractSummary:
    return FunctionContractSummary(
        function=function,
        events=events,
        param_flows=param_flows,
        returns=returns,
        unresolved_flow=unresolved,
    )


def _relationships(
    source: str,
    *targets: tuple[str | None, int],
) -> FunctionRelationshipFacts:
    return FunctionRelationshipFacts(
        source_qualname=source,
        relationships=tuple(
            RelationshipRecord(
                relation_kind="call",
                resolution_status="resolved" if target is not None else "unresolved",
                origin_lane="production",
                source_qualname=source,
                target_qualname=target,
                path="pkg/mod.py",
                line=line,
                expression=None,
                resolution_rule="test_contract",
            )
            for target, line in targets
        ),
    )


def _renamed_contract(
    function: str, parameter: str, *, reverse: bool
) -> FunctionContractIR:
    digest_event = _event(
        function=function,
        ordinal=1 if not reverse else 2,
        kind="compute_digest",
        subject="hashlib.sha256",
        inputs=(FactRef(kind="param", ref=parameter),),
        output=True,
        guards=("if@10:true",),
        line=10,
    )
    write_event = _event(
        function=function,
        ordinal=2 if not reverse else 1,
        kind="artifact_write",
        subject="codeclone.atomic_write",
        inputs=(digest_event.output or FactRef(kind="unresolved", ref="digest"),),
        guards=("if@10:true",),
        line=20,
    )
    events = (write_event, digest_event) if reverse else (digest_event, write_event)
    summary = _summary(
        function,
        events,
        param_flows=((parameter, digest_event.event_id),),
        returns=(digest_event.output or FactRef(kind="unresolved", ref="digest"),),
    )
    relationships = _relationships(
        function,
        ("hashlib:sha256", 10),
        ("codeclone:atomic_write", 20),
    )
    return build_contract_ir((summary,), (relationships,)).contracts[0]


def _recursive_fixture(reverse: bool = False) -> ContractIRBuildResult:
    functions = ("pkg:a", "pkg:b", "pkg:c")
    summaries = tuple(_summary(function, ()) for function in functions)
    facts = (
        _relationships("pkg:a", ("pkg:b", 1)),
        _relationships("pkg:b", ("pkg:a", 1), ("pkg:c", 2)),
        _relationships("pkg:c", ("external:owner", 1)),
    )
    return build_contract_ir(
        tuple(reversed(summaries)) if reverse else summaries,
        tuple(reversed(facts)) if reverse else facts,
    )


def test_contract_ir_is_versioned_domain_separated_and_frozen() -> None:
    contract = _renamed_contract("pkg:build", "payload", reverse=False)

    assert CONTRACT_IR_VERSION == "1"
    assert (
        contract.effect_signature
        == hashlib.sha256(b"ccsem1:ir\x00" + contract.wire.encode("utf-8")).hexdigest()
    )
    assert "version=1:1" in contract.wire
    assert "pkg:build" not in contract.wire
    field_name = "unresolved"
    with pytest.raises(FrozenInstanceError):
        setattr(contract.document, field_name, True)


def test_ir_erases_local_names_locations_and_independent_operation_order() -> None:
    first = _renamed_contract("pkg:first", "payload", reverse=False)
    second = _renamed_contract("pkg:renamed", "renamed_value", reverse=True)

    assert first.document == second.document
    assert first.wire == second.wire
    assert first.effect_signature == second.effect_signature
    assert "payload" not in first.wire
    assert "if@" not in first.wire
    assert "pkg/mod.py" not in first.wire


def test_semantics_bearing_constants_change_the_effect_signature() -> None:
    def _constant_contract(value: int) -> FunctionContractIR:
        function = "pkg:constant"
        event = _event(
            function=function,
            ordinal=1,
            kind="compute_digest",
            subject="hashlib.sha256",
            inputs=(FactRef(kind="const", ref=f"int:{value}"),),
            output=True,
        )
        return build_contract_ir((_summary(function, (event,)),), ()).contracts[0]

    assert (
        _constant_contract(1).effect_signature != _constant_contract(2).effect_signature
    )


def test_unresolved_calls_and_flow_fail_closed() -> None:
    function = "pkg:dynamic"
    result = build_contract_ir(
        (_summary(function, (), unresolved=True),),
        (_relationships(function, (None, 1)),),
    )
    document = result.contracts[0].document

    assert document.unresolved is True
    assert tuple(item.kind for item in document.failure_states) == (
        "unresolved_call",
        "unresolved_flow",
    )
    assert result.contracts[0].provenance_roots == ("unresolved",)


def test_pure_builtin_vocabulary_is_closed_and_not_a_dependency() -> None:
    function = "pkg:length"
    contract = build_contract_ir(
        (_summary(function, ()),),
        (_relationships(function, ("builtins:len", 1)),),
    ).contracts[0]

    assert contract.document.dependencies == ()
    assert tuple(
        (item.operation_kind, item.operation)
        for item in contract.document.transformations
    ) == (("pure_builtin", "len"),)


def test_scc_fixpoint_terminates_without_inlining_recursive_ir() -> None:
    result = _recursive_fixture()
    contracts = {item.function: item for item in result.contracts}

    assert result.sccs == (("pkg:a", "pkg:b"), ("pkg:c",))
    assert result.fixpoint_iterations == 3
    expected_root = ("operation:canonical_operation:external:owner",)
    assert contracts["pkg:a"].provenance_roots == expected_root
    assert contracts["pkg:b"].provenance_roots == expected_root
    assert contracts["pkg:c"].provenance_roots == expected_root
    assert "external:owner" not in contracts["pkg:a"].wire


def test_ir_reuses_canonical_relationship_facts_for_real_recursive_source() -> None:
    identity, registry = module_registry_context(
        filepath="pkg/mod.py",
        module_name="pkg.mod",
    )
    _units, _blocks, _segments, _stats, metrics, _findings = (
        extract_units_and_stats_from_source(
            source=(
                "def a(value):\n"
                "    return b(value)\n"
                "\n"
                "def b(value):\n"
                "    return a(value)\n"
            ),
            filepath="pkg/mod.py",
            identity=identity,
            registry=registry,
            cfg=NormalizationConfig(),
            min_loc=100,
            min_stmt=100,
        )
    )

    result = build_contract_ir(
        metrics.semantic_facts.function_contract_summaries,
        metrics.function_relationship_facts,
    )

    assert result.sccs == (("pkg.mod:a", "pkg.mod:b"),)
    assert all(contract.document.unresolved for contract in result.contracts)


def test_ir_is_stable_under_input_shuffle_and_across_processes() -> None:
    first = _recursive_fixture()
    shuffled = _recursive_fixture(reverse=True)
    assert first == shuffled

    script = """
import dataclasses
import json
from tests.test_semantic_ir import _recursive_fixture

document = dataclasses.asdict(_recursive_fixture())
print(json.dumps(document, sort_keys=True, separators=(",", ":")))
"""
    outputs = tuple(
        subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        for _ in range(3)
    )
    assert outputs[0] == outputs[1] == outputs[2]
    expected = json.loads(
        json.dumps(asdict(first), sort_keys=True, separators=(",", ":"))
    )
    assert json.loads(outputs[0]) == expected


def test_duplicate_function_summaries_are_rejected() -> None:
    summary = _summary("pkg:duplicate", ())
    with pytest.raises(ValueError, match="duplicate function summary"):
        build_contract_ir((summary, summary), ())
