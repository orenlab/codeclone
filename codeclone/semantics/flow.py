# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
from dataclasses import replace

from ..analysis.cfg import CFG
from ..models import (
    FactRef,
    FunctionContractSummary,
    SemanticEvent,
    SemanticEventResolution,
)
from ..qualnames import FunctionNode

_DYNAMIC_CALL_NAMES = frozenset(
    {"eval", "exec", "getattr", "globals", "locals", "setattr", "vars"}
)


def _parameter_names(node: FunctionNode) -> tuple[str, ...]:
    args = node.args
    names = [arg.arg for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs)]
    if args.vararg is not None:
        names.append(args.vararg.arg)
    if args.kwarg is not None:
        names.append(args.kwarg.arg)
    return tuple(names)


def _event_function(event_id: str) -> str:
    function, marker, ordinal = event_id.rpartition("#")
    return function if marker and ordinal.isdigit() else ""


def _statement_line_range(statement: ast.stmt) -> tuple[int, int] | None:
    start = getattr(statement, "lineno", None)
    if not isinstance(start, int):
        return None
    end = getattr(statement, "end_lineno", start)
    return start, end if isinstance(end, int) else start


def _block_rank_by_line(graph: CFG) -> dict[int, int]:
    ranks: dict[int, int] = {}
    for rank, block in enumerate(sorted(graph.blocks, key=lambda item: item.id)):
        for statement in block.statements:
            line_range = _statement_line_range(statement)
            if line_range is None:
                continue
            start, end = line_range
            for line in range(start, end + 1):
                ranks.setdefault(line, rank)
    return ranks


def _iter_local_nodes(node: ast.AST) -> tuple[ast.AST, ...]:
    result: list[ast.AST] = []
    stack = [node]
    while stack:
        current = stack.pop()
        result.append(current)
        if isinstance(
            current,
            ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda,
        ):
            continue
        stack.extend(reversed(list(ast.iter_child_nodes(current))))
    return tuple(result)


def _call_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _root_name(node: ast.expr) -> str | None:
    current = node
    while isinstance(current, ast.Attribute):
        current = current.value
    return current.id if isinstance(current, ast.Name) else None


def _has_dynamic_flow(graph: CFG, *, parameter_names: frozenset[str]) -> bool:
    for block in sorted(graph.blocks, key=lambda item: item.id):
        for statement in block.statements:
            for node in _iter_local_nodes(statement):
                if isinstance(node, ast.Yield | ast.YieldFrom):
                    return True
                if not isinstance(node, ast.Call):
                    continue
                if _call_name(node.func) in _DYNAMIC_CALL_NAMES:
                    return True
                if _root_name(node.func) in parameter_names:
                    return True
                if not isinstance(node.func, ast.Name | ast.Attribute):
                    return True
                if any(isinstance(argument, ast.Starred) for argument in node.args):
                    return True
                if any(keyword.arg is None for keyword in node.keywords):
                    return True
    return False


def _line_call_outputs(
    events: tuple[SemanticEvent, ...],
) -> dict[int, tuple[FactRef, ...]]:
    by_line: dict[int, list[FactRef]] = {}
    for event in events:
        if event.output is None or event.kind in {
            "assign",
            "field_write",
            "serialize_field",
        }:
            continue
        by_line.setdefault(event.location[1], []).append(event.output)
    return {line: tuple(outputs) for line, outputs in sorted(by_line.items())}


def summarize_function_contract(
    *,
    function: str,
    node: FunctionNode,
    graph: CFG,
    events: tuple[SemanticEvent, ...],
) -> FunctionContractSummary:
    """Resolve bounded local provenance over one already-built function CFG."""
    function_events = tuple(
        event for event in events if _event_function(event.event_id) == function
    )
    block_ranks = _block_rank_by_line(graph)
    ordered = tuple(
        sorted(
            function_events,
            key=lambda event: (
                block_ranks.get(event.location[1], len(block_ranks)),
                event.event_id,
            ),
        )
    )
    call_outputs = _line_call_outputs(ordered)
    event_by_output = {
        event.output: event for event in ordered if event.output is not None
    }
    definitions: dict[str, FactRef] = {
        parameter: FactRef(kind="param", ref=parameter)
        for parameter in _parameter_names(node)
    }
    lineage: dict[FactRef, frozenset[str]] = {
        fact: frozenset({fact.ref}) for fact in definitions.values()
    }
    param_flows: set[tuple[str, str]] = set()
    returns_by_event: list[tuple[str, tuple[FactRef, ...]]] = []
    resolved_events: list[SemanticEvent] = []
    unresolved = _has_dynamic_flow(
        graph,
        parameter_names=frozenset(definitions),
    )

    for event in ordered:
        resolved_inputs: list[FactRef] = []
        input_lineage: set[str] = set()
        for fact in event.inputs:
            resolved = fact
            if fact.kind == "unresolved":
                resolved = definitions.get(fact.ref, fact)
                if fact.ref == "Call":
                    outputs = call_outputs.get(event.location[1], ())
                    if len(outputs) == 1:
                        resolved = outputs[0]
            if resolved not in lineage:
                producer = event_by_output.get(resolved)
                if producer is not None:
                    producer_lineage: set[str] = set()
                    for producer_input in producer.inputs:
                        resolved_producer_input = (
                            definitions.get(producer_input.ref, producer_input)
                            if producer_input.kind == "unresolved"
                            else producer_input
                        )
                        producer_lineage.update(
                            lineage.get(resolved_producer_input, ())
                        )
                    lineage[resolved] = frozenset(producer_lineage)
            resolved_inputs.append(resolved)
            input_lineage.update(lineage.get(resolved, ()))
            if resolved.kind == "unresolved":
                unresolved = True

        for parameter in sorted(input_lineage):
            param_flows.add((parameter, event.event_id))

        resolution: SemanticEventResolution = (
            "unavailable"
            if any(fact.kind == "unresolved" for fact in resolved_inputs)
            else "resolved"
        )
        resolved_event = replace(
            event,
            inputs=tuple(resolved_inputs),
            resolution=resolution,
        )
        resolved_events.append(resolved_event)

        if event.kind == "return_value":
            returns_by_event.append((event.event_id, tuple(resolved_inputs)))

        if event.kind != "assign":
            if event.output is not None:
                lineage[event.output] = frozenset(input_lineage)
            continue
        if event.output is None:
            unresolved = True
            continue
        if event.guards or not event.subject.isidentifier():
            definitions[event.subject] = FactRef(kind="unresolved", ref=event.subject)
            unresolved = True
            continue
        definitions[event.subject] = event.output
        lineage[event.output] = frozenset(input_lineage)

    return FunctionContractSummary(
        function=function,
        events=tuple(sorted(resolved_events, key=lambda event: event.event_id)),
        param_flows=tuple(sorted(param_flows, key=lambda item: (item[1], item[0]))),
        returns=tuple(
            fact for _event_id, facts in sorted(returns_by_event) for fact in facts
        ),
        unresolved_flow=unresolved,
    )


__all__ = ["summarize_function_contract"]
