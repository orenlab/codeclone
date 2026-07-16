# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Deterministic repository-level semantic-authority discovery."""

from __future__ import annotations

import ast
import hashlib
from collections.abc import Iterable, Sequence
from typing import Final

from ..analysis.normalizer import NormalizationConfig
from ..analysis.wire import emit_wire
from ..contracts import AUTHORITY_ANALYSIS_REVISION
from ..models import (
    AuthorityCandidate,
    AuthorityCandidateLevel,
    AuthorityGraph,
    AuthorityGraphEdge,
    AuthorityGraphNode,
    AuthoritySinkResult,
    AuthorityStatus,
    FunctionContractIR,
    FunctionContractSummary,
    FunctionRelationshipFacts,
    SemanticAuthorityResult,
)
from .ir import build_contract_ir

_AUTHORITY_DOMAIN: Final = b"ccsem1:authority\x00"
_AUTHORITY_EFFECT_DOMAIN: Final = (
    b"ccsem1:authority-effect:" + AUTHORITY_ANALYSIS_REVISION.encode("ascii") + b"\x00"
)
_AUTHORITY_EFFECT_WIRE_CONFIG: Final = NormalizationConfig(normalize_constants=False)
_LEVEL_SCORES: Final[tuple[tuple[AuthorityCandidateLevel, int], ...]] = (
    ("exact_contract_ir", 5),
    ("same_effect_signature", 4),
    ("same_output_fact_and_input_family", 3),
    ("overlapping_transform_chain", 2),
    ("divergent_projection", 1),
)


def authority_candidate_score(level: AuthorityCandidateLevel) -> int:
    """Return the closed integer rank for one discovery-candidate level."""
    return dict(_LEVEL_SCORES)[level]


def _candidate_id(
    *,
    level: AuthorityCandidateLevel,
    producers: tuple[str, ...],
    shared_fact: str,
) -> str:
    wire = "\x00".join((AUTHORITY_ANALYSIS_REVISION, level, shared_fact, *producers))
    return hashlib.sha256(_AUTHORITY_DOMAIN + wire.encode("utf-8")).hexdigest()


def _operation_tokens(contract: FunctionContractIR) -> tuple[str, ...]:
    document = contract.document
    tokens = {
        f"transform:{item.role}:{item.operation_kind}:{item.operation}"
        for item in document.transformations
    }
    tokens.update(
        f"effect:{item.kind}:{item.operation}" for item in document.side_effects
    )
    return tuple(sorted(tokens))


def _wire_row(values: Sequence[str]) -> ast.Tuple:
    return ast.Tuple(
        elts=[ast.Constant(value=value) for value in values],
        ctx=ast.Load(),
    )


def _wire_section(
    name: str,
    rows: Sequence[tuple[str, ...]],
) -> ast.Tuple:
    return ast.Tuple(
        elts=[
            ast.Constant(value=name),
            ast.Tuple(
                elts=[_wire_row(row) for row in rows],
                ctx=ast.Load(),
            ),
        ],
        ctx=ast.Load(),
    )


def _authority_effect_signature(contract: FunctionContractIR) -> str:
    document = contract.document
    projection = ast.Tuple(
        elts=[
            _wire_section(
                "transformations",
                tuple(
                    sorted(
                        (
                            item.role,
                            item.operation_kind,
                            item.operation,
                        )
                        for item in document.transformations
                    )
                ),
            ),
            _wire_section(
                "side_effects",
                tuple(
                    sorted(
                        (item.kind, item.operation) for item in document.side_effects
                    )
                ),
            ),
            _wire_section(
                "output_facts",
                tuple((fact,) for fact in sorted(document.output_facts)),
            ),
            _wire_section(
                "failure_states",
                tuple((state.kind,) for state in document.failure_states),
            ),
        ],
        ctx=ast.Load(),
    )
    wire = emit_wire(projection, _AUTHORITY_EFFECT_WIRE_CONFIG)
    return hashlib.sha256(_AUTHORITY_EFFECT_DOMAIN + wire.encode("utf-8")).hexdigest()


def _add_bucket(
    buckets: dict[str, set[str]],
    *,
    key: str,
    function: str,
) -> None:
    if key:
        buckets.setdefault(key, set()).add(function)


def _groups(
    buckets: dict[str, set[str]],
) -> Iterable[tuple[str, tuple[str, ...]]]:
    for shared_fact, functions in sorted(buckets.items()):
        producers = tuple(sorted(functions))
        if len(producers) > 1:
            yield shared_fact, producers


def _reaches_other(
    source: str,
    *,
    members: frozenset[str],
    graph: dict[str, tuple[str, ...]],
) -> bool:
    visited = {source}
    pending = list(reversed(graph.get(source, ())))
    while pending:
        node = pending.pop()
        if node in members and node != source:
            return True
        if node in visited:
            continue
        visited.add(node)
        pending.extend(reversed(graph.get(node, ())))
    return False


def _status(
    contract: FunctionContractIR,
    *,
    members: frozenset[str],
    graph: dict[str, tuple[str, ...]],
    semantic_divergence: bool,
) -> AuthorityStatus:
    if _reaches_other(contract.function, members=members, graph=graph):
        return "mixed" if semantic_divergence else "adapter"
    if contract.document.unresolved:
        return "unavailable"
    return "shadow"


def _candidate_specs(
    contracts: Sequence[FunctionContractIR],
    *,
    effect_signatures: dict[str, str],
) -> tuple[tuple[AuthorityCandidateLevel, int, str, tuple[str, ...]], ...]:
    exact: dict[str, set[str]] = {}
    signatures: dict[str, set[str]] = {}
    input_output: dict[str, set[str]] = {}
    operations: dict[str, set[str]] = {}
    roots: dict[str, set[str]] = {}
    projections: dict[str, set[str]] = {}
    by_function = {contract.function: contract for contract in contracts}

    for contract in contracts:
        document = contract.document
        module, _separator, _local = contract.function.partition(":")
        _add_bucket(exact, key=contract.wire, function=contract.function)
        _add_bucket(
            signatures,
            key=effect_signatures[contract.function],
            function=contract.function,
        )
        _add_bucket(
            input_output,
            key=(
                f"inputs={','.join(document.inputs)};"
                f"outputs={','.join(document.output_facts)}"
            ),
            function=contract.function,
        )
        for token in _operation_tokens(contract):
            _add_bucket(operations, key=token, function=contract.function)
        for root in contract.provenance_roots:
            if root != "unresolved":
                _add_bucket(roots, key=root, function=contract.function)
        if document.guards and len(document.output_facts) > 1:
            for output_fact in document.output_facts:
                _add_bucket(
                    projections,
                    key=f"guarded-output:{module}:{output_fact}",
                    function=contract.function,
                )
        if document.unresolved and "unresolved" in document.output_facts:
            _add_bucket(
                projections,
                key=f"module-unresolved:{module}",
                function=contract.function,
            )

    candidate_by_producers: dict[
        tuple[str, ...], tuple[AuthorityCandidateLevel, int, str, tuple[str, ...]]
    ] = {}

    def _record(
        level: AuthorityCandidateLevel,
        shared_fact: str,
        producers: tuple[str, ...],
    ) -> None:
        existing = candidate_by_producers.get(producers)
        score = authority_candidate_score(level)
        if existing is None or score > existing[1]:
            candidate_by_producers[producers] = (
                level,
                score,
                shared_fact,
                producers,
            )

    for _shared_fact, producers in _groups(exact):
        _record(
            "exact_contract_ir",
            f"contract_ir:{by_function[producers[0]].effect_signature}",
            producers,
        )
    for shared_fact, producers in _groups(signatures):
        if len({by_function[name].wire for name in producers}) > 1:
            _record("same_effect_signature", shared_fact, producers)
    for shared_fact, producers in _groups(input_output):
        if any(
            output != "unresolved"
            for name in producers
            for output in by_function[name].document.output_facts
        ):
            _record("same_output_fact_and_input_family", shared_fact, producers)
    for shared_fact, producers in _groups(operations):
        _record("overlapping_transform_chain", shared_fact, producers)
    for shared_fact, producers in _groups(roots):
        if len({effect_signatures[name] for name in producers}) > 1:
            _record("divergent_projection", shared_fact, producers)
    for shared_fact, producers in _groups(projections):
        if len({effect_signatures[name] for name in producers}) > 1:
            _record("divergent_projection", shared_fact, producers)

    return tuple(
        sorted(
            candidate_by_producers.values(),
            key=lambda item: (-item[1], item[3], item[2]),
        )
    )


def build_semantic_authority(
    summaries: Sequence[FunctionContractSummary],
    relationship_facts: Sequence[FunctionRelationshipFacts],
) -> SemanticAuthorityResult:
    """Build one bounded authority graph and its report-only discovery projection."""
    contract_ir = build_contract_ir(summaries, relationship_facts)
    by_function = {contract.function: contract for contract in contract_ir.contracts}
    effect_signatures = {
        contract.function: _authority_effect_signature(contract)
        for contract in contract_ir.contracts
    }
    graph_map = {
        contract.function: tuple(
            sorted(
                dependency
                for dependency in contract.document.dependencies
                if dependency in by_function
            )
        )
        for contract in contract_ir.contracts
    }
    graph = AuthorityGraph(
        nodes=tuple(
            AuthorityGraphNode(
                function=contract.function,
                effect_signature=effect_signatures[contract.function],
                producer_root_ids=contract.provenance_roots,
                output_facts=contract.document.output_facts,
                resolution_state=(
                    "unavailable" if contract.document.unresolved else "resolved"
                ),
            )
            for contract in contract_ir.contracts
        ),
        edges=tuple(
            AuthorityGraphEdge(source=source, target=target)
            for source, targets in sorted(graph_map.items())
            for target in targets
        ),
    )

    candidates: list[AuthorityCandidate] = []
    statuses_by_sink: dict[str, list[AuthorityStatus]] = {
        function: ["unavailable"]
        for function, contract in sorted(by_function.items())
        if contract.document.unresolved and not graph_map[function]
    }
    for level, score, shared_fact, producers in _candidate_specs(
        contract_ir.contracts,
        effect_signatures=effect_signatures,
    ):
        members = frozenset(producers)
        semantic_divergence = len({effect_signatures[name] for name in producers}) > 1
        statuses = tuple(
            _status(
                by_function[name],
                members=members,
                graph=graph_map,
                semantic_divergence=semantic_divergence,
            )
            for name in producers
        )
        for name, status in zip(producers, statuses, strict=True):
            statuses_by_sink.setdefault(name, []).append(status)
        candidates.append(
            AuthorityCandidate(
                candidate_id=_candidate_id(
                    level=level,
                    producers=producers,
                    shared_fact=shared_fact,
                ),
                level=level,
                score=score,
                producers=producers,
                shared_fact=shared_fact,
                independence=not any(
                    _reaches_other(name, members=members, graph=graph_map)
                    for name in producers
                ),
                semantic_divergence=semantic_divergence,
                sink_statuses=statuses,
            )
        )

    status_order: Final[dict[AuthorityStatus, int]] = {
        "unavailable": 0,
        "mixed": 1,
        "shadow": 2,
        "adapter": 3,
        "authoritative": 4,
    }
    sinks = tuple(
        AuthoritySinkResult(
            sink_identity=function,
            authority_status=min(
                statuses,
                key=lambda status: status_order[status],
            ),
            producer_root_ids=by_function[function].provenance_roots,
            effect_signature=effect_signatures[function],
            resolution_state=(
                "unavailable"
                if by_function[function].document.unresolved
                else "resolved"
            ),
        )
        for function, statuses in sorted(statuses_by_sink.items())
    )
    return SemanticAuthorityResult(
        algorithm_revision=AUTHORITY_ANALYSIS_REVISION,
        contract_ir=contract_ir,
        graph=graph,
        sinks=sinks,
        candidates=tuple(candidates),
    )


__all__ = ["authority_candidate_score", "build_semantic_authority"]
