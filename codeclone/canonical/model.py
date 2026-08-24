# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The canonical normalized model container (F-3 SS4-SS6), wave-1 families.

Multiplicity is impossible by type (§6.1): every set-valued relation is a
``frozenset`` of semantic references, so insertion order and duplicates are
not part of the API.  Canonical order appears only in normalization and in
the wire projection.

``output_facts`` is deliberately an ordered tuple, not a set: measured on
the frozen corpus, 1 157 of 12 244 rows are not sorted-deduplicated, so the
producer's order is a fact and canonizing it away would lose an entity.

Wave-1 family subset: ``file_modules · contracts · graph_nodes · sink_roles
· candidates · semantic_edges`` plus the standalone ``coupled_sets`` value
sets.  ``dependency_edges`` is deferred to wave 2: its logical row key was
never measured from the producer, and inventing one here would be exactly
the manual-tail defect the facts-order sanction forbids.

The container mirrors the wire: :class:`CanonicalFacts` is the ``facts``
section (record tables), :class:`CanonicalModel` adds the identity domains,
the scope, and the standalone value sets.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from typing import TypeVar

from codeclone.canonical.errors import CanonicalModelError
from codeclone.canonical.identity import (
    AnalysisFile,
    EffectRoot,
    FileId,
    KnownModule,
    ModuleId,
    OperationRoot,
    ProducerRoot,
    SymbolId,
    canonical_key,
)


@dataclass(frozen=True, slots=True)
class FileModuleRelation:
    """The ``FILE ↔ MODULE`` relation — a table, never a column (§2.3)."""

    file: FileId
    module: ModuleId


@dataclass(frozen=True, slots=True)
class ContractRow:
    """Function contract fact; logical key: ``function`` (S5.A).

    ``effect_signature`` is carried as an analysis fact in the wave-1
    subset: its derivation basis (the stored ``wire`` document) is not part
    of this subset, and derivability is a property of the (value, place)
    pair, not of the field name (S8.V.3).
    """

    function: SymbolId
    effect_signature: str
    root_set: frozenset[EffectRoot]


@dataclass(frozen=True, slots=True)
class GraphNodeRow:
    """Semantic graph node fact; logical key: ``function`` (S5.A)."""

    function: SymbolId
    effect_signature: str
    root_set: frozenset[EffectRoot]
    output_facts: tuple[str, ...]
    resolution_state: str


@dataclass(frozen=True, slots=True)
class SinkRoleRow:
    """SINK role payload: only what the role itself owns (§8.1)."""

    symbol: SymbolId
    authority_status: str


@dataclass(frozen=True, slots=True)
class CandidateRow:
    """Authority candidate; natural key ``(level, shared_fact, producer_set)``.

    ``candidate_id`` and ``score`` are class-B contract-derived values with
    one formula owner and are never stored (§5.1, §8.0).
    """

    level: str
    shared_fact: str
    producer_set: frozenset[SymbolId]


@dataclass(frozen=True, slots=True)
class SemanticEdge:
    """Simple-graph edge; the pair is both logical key and full content (§5.2)."""

    source: SymbolId
    target: SymbolId


@dataclass(frozen=True, slots=True)
class CanonicalFacts:
    """The record tables of one model state — the wire's ``facts`` section."""

    contracts: frozenset[ContractRow] = field(default_factory=frozenset)
    graph_nodes: frozenset[GraphNodeRow] = field(default_factory=frozenset)
    sink_roles: frozenset[SinkRoleRow] = field(default_factory=frozenset)
    candidates: frozenset[CandidateRow] = field(default_factory=frozenset)
    semantic_edges: frozenset[SemanticEdge] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class CanonicalModel:
    """One canonical semantic model state — the shared truth of both
    representations (SQLite and canonical JSON)."""

    files: frozenset[FileId] = field(default_factory=frozenset)
    modules: frozenset[ModuleId] = field(default_factory=frozenset)
    analyzed_files: frozenset[FileId] = field(default_factory=frozenset)
    file_modules: frozenset[FileModuleRelation] = field(default_factory=frozenset)
    facts: CanonicalFacts = field(default_factory=CanonicalFacts)
    coupled_sets: frozenset[frozenset[str]] = field(default_factory=frozenset)

    def normalize(self) -> CanonicalModel:
        """Return the canonically completed model (idempotent, law L1)."""
        return _normalized(self)


_RowT = TypeVar("_RowT")


def _unique_by_key(
    rows: Iterable[_RowT], key_name: str, key_of: Callable[[_RowT], object]
) -> None:
    seen: dict[object, object] = {}
    for row in rows:
        key = key_of(row)
        if key in seen and seen[key] != row:
            raise CanonicalModelError(
                f"two facts share one logical key {key_name}={key!r}"
            )
        seen[key] = row


def _candidate_natural_key(row: CandidateRow) -> tuple[object, ...]:
    return (
        row.level,
        row.shared_fact,
        tuple(sorted(canonical_key(p) for p in row.producer_set)),
    )


class _DomainClosure:
    """Referential closure of the identity domains — never invents facts."""

    def __init__(self, model: CanonicalModel) -> None:
        self.files = set(model.files)
        self.modules = set(model.modules)
        self.symbols: set[SymbolId] = set()

    def see_symbol(self, symbol: SymbolId) -> None:
        self.symbols.add(symbol)
        self.files.add(symbol.file)

    def see_root(self, root: EffectRoot) -> None:
        if isinstance(root, ProducerRoot):
            self.see_symbol(root.target)
        elif isinstance(root, OperationRoot):
            head = root.target.head
            if isinstance(head, KnownModule):
                self.modules.add(head.module)
            elif isinstance(head, AnalysisFile):
                self.files.add(head.file)


def _normalized(model: CanonicalModel) -> CanonicalModel:
    """Complete the domains to their closure and prove every key law
    (idempotent; never invents facts, never reorders — order is a
    projection concern)."""
    closure = _DomainClosure(model)
    facts = model.facts
    for relation in model.file_modules:
        closure.files.add(relation.file)
        closure.modules.add(relation.module)
    for contract in facts.contracts:
        closure.see_symbol(contract.function)
        for root in contract.root_set:
            closure.see_root(root)
    for node in facts.graph_nodes:
        closure.see_symbol(node.function)
        for root in node.root_set:
            closure.see_root(root)
    for sink in facts.sink_roles:
        closure.see_symbol(sink.symbol)
    for candidate in facts.candidates:
        for producer in candidate.producer_set:
            closure.see_symbol(producer)
    for edge in facts.semantic_edges:
        closure.see_symbol(edge.source)
        closure.see_symbol(edge.target)
    closure.files.update(model.analyzed_files)

    _unique_by_key(
        facts.contracts,
        "contracts.function",
        lambda row: canonical_key(row.function),
    )
    _unique_by_key(
        facts.graph_nodes,
        "graph_nodes.function",
        lambda row: canonical_key(row.function),
    )
    _unique_by_key(
        facts.sink_roles,
        "sink_roles.symbol",
        lambda row: canonical_key(row.symbol),
    )
    _unique_by_key(facts.candidates, "candidates.natural_key", _candidate_natural_key)

    function_symbols = {row.function for row in facts.contracts}
    for candidate in facts.candidates:
        for producer in candidate.producer_set:
            if producer not in function_symbols:
                raise CanonicalModelError(
                    "producer set references a symbol without the "
                    f"FUNCTION role: {producer!r}"
                )

    return replace(
        model,
        files=frozenset(closure.files),
        modules=frozenset(closure.modules),
    )
