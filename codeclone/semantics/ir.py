# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Canonical Contract IR lowering over existing semantic and relationship facts."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from typing import Final

from ..contracts import CONTRACT_IR_VERSION
from ..models import (
    PURE_BUILTIN_OPERATIONS,
    ContractIRBuildResult,
    ContractIRDocument,
    ContractIRFailureKind,
    ContractIRFailureState,
    ContractIROperationKind,
    ContractIRSideEffect,
    ContractIRSideEffectKind,
    ContractIRTransformation,
    ContractIRTransformationRole,
    FactRef,
    FunctionContractIR,
    FunctionContractSummary,
    FunctionRelationshipFacts,
    RelationshipRecord,
    SemanticEvent,
)

_IR_DOMAIN: Final = b"ccsem1:ir\x00"
_PURE_BUILTINS: Final = frozenset(PURE_BUILTIN_OPERATIONS)
_TRANSFORMATION_ROLES: Final[dict[str, ContractIRTransformationRole]] = {
    "compatibility_check": "compatibility_check",
    "compute_digest": "compute_digest",
    "construct": "construct",
    "resolve_identity": "resolve_identity",
}
_SIDE_EFFECT_KINDS: Final[dict[str, ContractIRSideEffectKind]] = {
    "artifact_write": "artifact_write",
    "field_write": "field_write",
    "publish_event": "publish_event",
    "security_observation": "security_observation",
    "serialize_field": "serialize_field",
}


def _event_suffix(event_id: str) -> str:
    _function, marker, ordinal = event_id.rpartition("#")
    return ordinal if marker and ordinal.isdigit() else ""


def _event_subject(event: SemanticEvent) -> str:
    if event.kind in {"assign", "field_write", "return_value", "serialize_field"}:
        return event.kind
    return event.subject


def _precanonical_fact(fact: FactRef) -> str:
    if fact.kind == "const":
        return f"const:{fact.ref}"
    if fact.kind == "event":
        return "event"
    return fact.kind


def _event_sort_key(event: SemanticEvent) -> tuple[object, ...]:
    return (
        event.kind,
        _event_subject(event),
        tuple(_precanonical_fact(fact) for fact in event.inputs),
        bool(event.output),
        tuple(guard.rpartition(":")[2] for guard in event.guards),
        _event_suffix(event.event_id),
    )


def _event_tokens(events: Sequence[SemanticEvent]) -> dict[str, str]:
    return {
        event.event_id: f"event:{index}"
        for index, event in enumerate(sorted(events, key=_event_sort_key))
    }


def _parameter_tokens(
    summary: FunctionContractSummary,
    *,
    event_tokens: dict[str, str],
) -> dict[str, str]:
    flow_events: dict[str, set[str]] = {}
    for parameter, event_id in summary.param_flows:
        flow_events.setdefault(parameter, set()).add(
            event_tokens.get(event_id, "event:unresolved")
        )
    ordered = sorted(
        flow_events,
        key=lambda parameter: (tuple(sorted(flow_events[parameter])), parameter),
    )
    return {parameter: f"param:{index}" for index, parameter in enumerate(ordered)}


def _canonical_fact(
    fact: FactRef,
    *,
    event_tokens: dict[str, str],
    parameter_tokens: dict[str, str],
) -> str:
    match fact.kind:
        case "const":
            return f"const:{fact.ref}"
        case "event":
            return event_tokens.get(fact.ref, "event:unresolved")
        case "param":
            return parameter_tokens.get(fact.ref, "param:unresolved")
        case "unresolved":
            return "unresolved"


def _guard_tokens(events: Sequence[SemanticEvent]) -> dict[str, str]:
    bases = sorted(
        {
            guard.rpartition(":")[0]
            for event in sorted(events, key=_event_sort_key)
            for guard in event.guards
        },
        key=lambda base: next(
            index
            for index, event in enumerate(sorted(events, key=_event_sort_key))
            if any(guard.rpartition(":")[0] == base for guard in event.guards)
        ),
    )
    return {base: f"guard:{index}" for index, base in enumerate(bases)}


def _canonical_guards(
    event: SemanticEvent,
    *,
    guard_tokens: dict[str, str],
) -> tuple[str, ...]:
    result: list[str] = []
    for guard in event.guards:
        base, marker, branch = guard.rpartition(":")
        token = guard_tokens.get(base, "guard:unresolved")
        result.append(f"{token}:{branch}" if marker else token)
    return tuple(sorted(result))


def _builtin_name(operation: str) -> str | None:
    candidate = operation.rsplit(":", 1)[-1].rsplit(".", 1)[-1]
    return candidate if candidate in _PURE_BUILTINS else None


def _operation(operation: str) -> tuple[ContractIROperationKind, str]:
    builtin = _builtin_name(operation)
    return (
        ("pure_builtin", builtin)
        if builtin is not None
        else ("canonical_operation", operation)
    )


def _relationship_sort_key(record: RelationshipRecord) -> tuple[object, ...]:
    return (
        record.line,
        record.resolution_status,
        record.target_qualname or "",
        record.resolution_rule or "",
    )


def _relationships_by_function(
    facts: Sequence[FunctionRelationshipFacts],
) -> dict[str, tuple[RelationshipRecord, ...]]:
    result: dict[str, list[RelationshipRecord]] = {}
    for item in facts:
        result.setdefault(item.source_qualname, []).extend(
            record for record in item.relationships if record.relation_kind == "call"
        )
    return {
        function: tuple(sorted(records, key=_relationship_sort_key))
        for function, records in sorted(result.items())
    }


def _matching_relationship(
    event: SemanticEvent,
    relationships: Sequence[RelationshipRecord],
    *,
    used: set[int],
) -> RelationshipRecord | None:
    candidates = [
        (index, record)
        for index, record in enumerate(relationships)
        if index not in used and record.line == event.location[1]
    ]
    if not candidates:
        return None
    index, record = min(candidates, key=lambda item: _relationship_sort_key(item[1]))
    used.add(index)
    return record


def _transformation_sort_key(
    item: ContractIRTransformation,
) -> tuple[object, ...]:
    return (
        item.role,
        item.operation_kind,
        item.operation,
        item.inputs,
        item.outputs,
        item.guards,
    )


def _side_effect_sort_key(item: ContractIRSideEffect) -> tuple[object, ...]:
    return (item.kind, item.operation, item.inputs, item.guards)


def _lower_document(
    summary: FunctionContractSummary,
    *,
    relationships: Sequence[RelationshipRecord],
) -> ContractIRDocument:
    event_tokens = _event_tokens(summary.events)
    parameter_tokens = _parameter_tokens(summary, event_tokens=event_tokens)
    guard_tokens = _guard_tokens(summary.events)
    transformations: list[ContractIRTransformation] = []
    side_effects: list[ContractIRSideEffect] = []
    dependencies: set[str] = set()
    used_relationships: set[int] = set()
    unresolved_call = False

    for event in sorted(summary.events, key=_event_sort_key):
        inputs = tuple(
            _canonical_fact(
                fact,
                event_tokens=event_tokens,
                parameter_tokens=parameter_tokens,
            )
            for fact in event.inputs
        )
        outputs = (
            ()
            if event.output is None
            else (
                _canonical_fact(
                    event.output,
                    event_tokens=event_tokens,
                    parameter_tokens=parameter_tokens,
                ),
            )
        )
        guards = _canonical_guards(event, guard_tokens=guard_tokens)
        role = _TRANSFORMATION_ROLES.get(event.kind)
        if role is not None:
            relationship = _matching_relationship(
                event,
                relationships,
                used=used_relationships,
            )
            operation = (
                relationship.target_qualname
                if relationship is not None and relationship.target_qualname is not None
                else event.subject
            )
            operation_kind, canonical_operation = _operation(operation)
            transformations.append(
                ContractIRTransformation(
                    role=role,
                    operation_kind=operation_kind,
                    operation=canonical_operation,
                    inputs=inputs,
                    outputs=outputs,
                    guards=guards,
                )
            )
            if operation_kind == "canonical_operation":
                dependencies.add(canonical_operation)

        side_effect_kind = _SIDE_EFFECT_KINDS.get(event.kind)
        if side_effect_kind is not None:
            operation = (
                side_effect_kind
                if side_effect_kind in {"field_write", "serialize_field"}
                else event.subject
            )
            side_effects.append(
                ContractIRSideEffect(
                    kind=side_effect_kind,
                    operation=operation,
                    inputs=inputs,
                    guards=guards,
                )
            )

    for index, relationship in enumerate(relationships):
        if index in used_relationships:
            continue
        target = relationship.target_qualname
        if relationship.resolution_status == "unresolved" or target is None:
            unresolved_call = True
            continue
        operation_kind, operation = _operation(target)
        transformations.append(
            ContractIRTransformation(
                role="call",
                operation_kind=operation_kind,
                operation=operation,
                inputs=(),
                outputs=(),
                guards=(),
            )
        )
        if operation_kind == "canonical_operation":
            dependencies.add(operation)

    failure_kinds: list[ContractIRFailureKind] = []
    if unresolved_call:
        failure_kinds.append("unresolved_call")
    if summary.unresolved_flow:
        failure_kinds.append("unresolved_flow")
    failure_states = tuple(ContractIRFailureState(kind=kind) for kind in failure_kinds)
    all_guards = tuple(
        sorted(
            {
                guard
                for event in summary.events
                for guard in _canonical_guards(event, guard_tokens=guard_tokens)
            }
        )
    )
    return ContractIRDocument(
        inputs=tuple(sorted(parameter_tokens.values())),
        guards=all_guards,
        transformations=tuple(sorted(transformations, key=_transformation_sort_key)),
        dependencies=tuple(sorted(dependencies)),
        output_facts=tuple(
            sorted(
                _canonical_fact(
                    fact,
                    event_tokens=event_tokens,
                    parameter_tokens=parameter_tokens,
                )
                for fact in summary.returns
            )
        ),
        side_effects=tuple(sorted(side_effects, key=_side_effect_sort_key)),
        failure_states=failure_states,
        unresolved=summary.unresolved_flow or unresolved_call,
    )


def _atom(value: str) -> str:
    return f"{len(value.encode('utf-8'))}:{value}"


def _sequence(values: Iterable[str]) -> str:
    return "[" + ",".join(_atom(value) for value in values) + "]"


def contract_ir_wire(document: ContractIRDocument) -> str:
    """Serialize one Contract IR document through an explicit, stable whitelist."""
    transformations = (
        "Transformation("
        f"role={_atom(item.role)},"
        f"operation_kind={_atom(item.operation_kind)},"
        f"operation={_atom(item.operation)},"
        f"inputs={_sequence(item.inputs)},"
        f"outputs={_sequence(item.outputs)},"
        f"guards={_sequence(item.guards)}"
        ")"
        for item in document.transformations
    )
    side_effects = (
        "SideEffect("
        f"kind={_atom(item.kind)},"
        f"operation={_atom(item.operation)},"
        f"inputs={_sequence(item.inputs)},"
        f"guards={_sequence(item.guards)}"
        ")"
        for item in document.side_effects
    )
    failures = (
        f"FailureState(kind={_atom(item.kind)})" for item in document.failure_states
    )
    return (
        "ContractIR("
        f"version={_atom(CONTRACT_IR_VERSION)},"
        f"inputs={_sequence(document.inputs)},"
        f"guards={_sequence(document.guards)},"
        f"transformations=[{','.join(transformations)}],"
        f"dependencies={_sequence(document.dependencies)},"
        f"output_facts={_sequence(document.output_facts)},"
        f"side_effects=[{','.join(side_effects)}],"
        f"failure_states=[{','.join(failures)}],"
        f"unresolved={'true' if document.unresolved else 'false'}"
        ")"
    )


def contract_ir_digest(document: ContractIRDocument) -> str:
    """Return the domain-separated semantic effect signature for ``document``."""
    return hashlib.sha256(_IR_DOMAIN + contract_ir_wire(document).encode()).hexdigest()


def _strongly_connected_components(
    graph: dict[str, frozenset[str]],
) -> tuple[tuple[str, ...], ...]:
    visited: set[str] = set()
    finish_order: list[str] = []
    for start in sorted(graph):
        if start not in visited:
            pending: list[tuple[str, bool]] = [(start, False)]
            while pending:
                node, expanded = pending.pop()
                if expanded:
                    finish_order.append(node)
                elif node not in visited:
                    visited.add(node)
                    pending.append((node, True))
                    pending.extend(
                        (neighbor, False)
                        for neighbor in sorted(graph[node], reverse=True)
                        if neighbor not in visited
                    )

    reverse_graph: dict[str, set[str]] = {node: set() for node in graph}
    for source, targets in graph.items():
        for target in targets:
            reverse_graph[target].add(source)

    components: list[tuple[str, ...]] = []
    assigned: set[str] = set()
    for start in reversed(finish_order):
        if start not in assigned:
            component: set[str] = set()
            pending_nodes = [start]
            while pending_nodes:
                node = pending_nodes.pop()
                if node not in assigned:
                    assigned.add(node)
                    component.add(node)
                    pending_nodes.extend(
                        neighbor
                        for neighbor in sorted(reverse_graph[node], reverse=True)
                        if neighbor not in assigned
                    )
            components.append(tuple(sorted(component)))
    return tuple(sorted(components))


def _direct_roots(
    function: str,
    document: ContractIRDocument,
    *,
    functions: frozenset[str],
) -> frozenset[str]:
    roots = {
        f"operation:{item.operation_kind}:{item.operation}"
        for item in document.transformations
        if item.operation not in functions
    }
    roots.update(
        f"effect:{item.kind}:{item.operation}" for item in document.side_effects
    )
    if document.unresolved:
        roots.add("unresolved")
    if not roots and not document.dependencies:
        roots.add(f"producer:{function}")
    return frozenset(roots)


def _provenance_fixpoint(
    documents: dict[str, ContractIRDocument],
) -> tuple[dict[str, frozenset[str]], int]:
    functions = frozenset(documents)
    roots = {
        function: _direct_roots(function, document, functions=functions)
        for function, document in documents.items()
    }
    iterations = 0
    while True:
        iterations += 1
        updated = {
            function: roots[function].union(
                *(
                    roots[dependency]
                    for dependency in document.dependencies
                    if dependency in roots
                )
            )
            for function, document in documents.items()
        }
        if updated == roots:
            return roots, iterations
        roots = updated


def build_contract_ir(
    summaries: Sequence[FunctionContractSummary],
    relationship_facts: Sequence[FunctionRelationshipFacts],
) -> ContractIRBuildResult:
    """Lower bounded facts and resolve recursive provenance without inlining."""
    by_function: dict[str, FunctionContractSummary] = {}
    for summary in summaries:
        if summary.function in by_function:
            raise ValueError(f"duplicate function summary: {summary.function}")
        by_function[summary.function] = summary
    relationships = _relationships_by_function(relationship_facts)
    documents = {
        function: _lower_document(
            summary,
            relationships=relationships.get(function, ()),
        )
        for function, summary in sorted(by_function.items())
    }
    functions = frozenset(documents)
    graph = {
        function: frozenset(
            dependency
            for dependency in document.dependencies
            if dependency in functions
        )
        for function, document in documents.items()
    }
    sccs = _strongly_connected_components(graph)
    provenance, iterations = _provenance_fixpoint(documents)
    contracts = tuple(
        FunctionContractIR(
            function=function,
            document=document,
            wire=contract_ir_wire(document),
            effect_signature=contract_ir_digest(document),
            provenance_roots=tuple(sorted(provenance[function])),
        )
        for function, document in sorted(documents.items())
    )
    return ContractIRBuildResult(
        contracts=contracts,
        sccs=sccs,
        fixpoint_iterations=iterations,
    )


__all__ = ["build_contract_ir", "contract_ir_digest", "contract_ir_wire"]
