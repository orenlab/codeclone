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

Wave family subset: ``file_modules · contracts · graph_nodes · sink_roles
· candidates · semantic_edges · dependency_edges · violations ·
coupling_cohesion_observations`` plus the standalone ``coupled_sets``
value sets.

``dependency_edges`` (wave 1.5): the logical row key is **measured from the
producer**, not invented — ``metrics/dependencies.py:_unique_sorted_edges``
dedups and sorts on ``(source, target, import_type, line)``; on the frozen
corpus the key is unique on 5 244 of 5 244 rows, dropping ``line`` collides
926 of them, and the 861 distinct endpoints split MODULE 860 / FILE 1 —
the ratified ``DependencyEndpoint`` union.  ``binding`` and ``is_lazy`` are
payload, not key: two rows under one producer key may not disagree.

``violations`` (wave 1.5): natural key ``(contract_id, kind, sink_identity,
PRODUCER_SET)`` under the ``AUTHORITY_ANALYSIS_REVISION`` namespace — the
preimage of the class-B ``violation_id`` handle, owned by
``codeclone.canonical.authority_identity``.  The row carries the violation's
own analysis facts; ``locations`` stays with the legacy producer for a later
wave (a record-in-record wire shape the revision-0 grammar does not carry).

The fact container is a three-house composition (ruling 2026-08-24 §4,
variant v): :class:`CanonicalFacts` is the pure composition root over
:class:`AnalysisFacts` (the wire's ``facts`` record tables),
:class:`ComparisonFacts` and :class:`EvaluationFacts` (born empty under the
ratified grammar); :class:`CanonicalModel` adds the identity domains, the
scope, and the standalone value sets.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from typing import TypeVar

from codeclone.canonical.errors import CanonicalModelError
from codeclone.canonical.identity import (
    COUPLING_COHESION_DIMENSIONS,
    DEPENDENCY_BINDINGS,
    IMPORT_TYPES,
    VIOLATION_KINDS,
    AnalysisFile,
    DependencyEndpoint,
    EffectRoot,
    FileId,
    KnownModule,
    ModuleId,
    OperationRoot,
    ProducerRoot,
    SymbolId,
    canonical_key,
    endpoint_key,
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
class DependencyEdgeRow:
    """Module dependency fact over the ratified endpoint union.

    Logical key — measured from the producer's own dedup, never invented:
    ``(source, target, import_type, line)``.  ``binding`` and ``is_lazy``
    are payload; two rows sharing the key with different payload are a
    producer defect and are refused, not last-writer-silenced.
    """

    source: DependencyEndpoint
    target: DependencyEndpoint
    import_type: str
    line: int
    binding: str
    is_lazy: bool

    def __post_init__(self) -> None:
        if self.import_type not in IMPORT_TYPES:
            raise CanonicalModelError(f"unknown import_type: {self.import_type!r}")
        if self.binding not in DEPENDENCY_BINDINGS:
            raise CanonicalModelError(f"unknown dependency binding: {self.binding!r}")
        if isinstance(self.line, bool) or self.line < 0:
            raise CanonicalModelError(
                f"dependency line must be a non-negative int: {self.line!r}"
            )


@dataclass(frozen=True, slots=True)
class ViolationRow:
    """Authority violation fact; natural key ``(contract_id, kind,
    sink_identity, producer_set)`` under the analysis-revision namespace.

    ``violation_id`` is the class-B handle of that key — never stored here,
    emitted on the wire by the projector through its one formula owner.
    ``sink_identity`` and every producer must carry the FUNCTION role (the
    producer indexes the contract table with both); ``canonical_owner`` is a
    registry declaration and carries no role requirement.
    """

    contract_id: str
    kind: str
    sink_identity: SymbolId
    canonical_owner: SymbolId
    authority_status: str
    effect_signature: str
    resolution_state: str
    root_set: frozenset[EffectRoot]
    producer_set: frozenset[SymbolId]
    suppressed: bool

    def __post_init__(self) -> None:
        if not self.contract_id:
            raise CanonicalModelError("violation contract_id must be non-empty")
        if self.kind not in VIOLATION_KINDS:
            raise CanonicalModelError(f"unknown violation kind: {self.kind!r}")


@dataclass(frozen=True, slots=True)
class CouplingCohesionRow:
    """F2 per-class design-metric observation (wave 4).

    Logical key — measured from the producer, never invented:
    ``(SYMBOL, dimension)``, 2 091/2 091 unique on the frozen corpus
    (``observations/projection.py`` keys rows by source file, bare qualname
    and dimension; SYMBOL is the ratified FILE-headed spelling of the same
    entity).  ``numerator`` is payload and strictly positive: the producer
    drops zero rows, so absence already means zero and a stored zero would
    smuggle the forbidden third state into the family.  No FUNCTION-role
    requirement: these symbols name classes, not contract functions.
    """

    symbol: SymbolId
    dimension: str
    numerator: int

    def __post_init__(self) -> None:
        if self.dimension not in COUPLING_COHESION_DIMENSIONS:
            raise CanonicalModelError(
                f"unknown coupling/cohesion dimension: {self.dimension!r}"
            )
        if isinstance(self.numerator, bool) or self.numerator < 1:
            raise CanonicalModelError(
                f"coupling/cohesion numerator must be a positive int: "
                f"{self.numerator!r}"
            )


@dataclass(frozen=True, slots=True)
class AnalysisFacts:
    """The analysis-tier record tables — the wire's ``facts`` section.

    One of the three ratified fact houses (ruling 2026-08-24 §4): normalized
    findings and facts the ANALYSIS of one source state established.  Every
    family the wave-1..4 model carries is analysis-tier, so every family
    lives here.
    """

    contracts: frozenset[ContractRow] = field(default_factory=frozenset)
    graph_nodes: frozenset[GraphNodeRow] = field(default_factory=frozenset)
    sink_roles: frozenset[SinkRoleRow] = field(default_factory=frozenset)
    candidates: frozenset[CandidateRow] = field(default_factory=frozenset)
    semantic_edges: frozenset[SemanticEdge] = field(default_factory=frozenset)
    dependency_edges: frozenset[DependencyEdgeRow] = field(default_factory=frozenset)
    violations: frozenset[ViolationRow] = field(default_factory=frozenset)
    coupling_cohesion_observations: frozenset[CouplingCohesionRow] = field(
        default_factory=frozenset
    )


@dataclass(frozen=True, slots=True)
class ComparisonFacts:
    """The comparison-tier fact house — born empty, and legitimately so.

    The ratified §4 grammar names its future residents: baseline
    state/scope/root witnesses, per-lane trust, availability/refusal,
    novelty facts, metric-baseline identity and results, deltas, disabled
    capabilities.  Zero families is the CURRENT state, not an omission:
    comparison facts join with their own wire-revision bump, because
    emitting an empty section today would present "not populated by this
    model revision" as "measured empty" (the four-state law forbids it).
    """


@dataclass(frozen=True, slots=True)
class EvaluationFacts:
    """The evaluation-tier fact house — born empty, and legitimately so.

    The ratified §4 grammar names its future residents: evaluation contract
    revisions, the evaluation request, health results, gate inputs and
    outcomes, verdict/refusal facts.  Zero families is the CURRENT state
    for the same four-state reason as :class:`ComparisonFacts`.
    """


@dataclass(frozen=True, slots=True)
class CanonicalFacts:
    """The fact root: PURE COMPOSITION of the three tier houses.

    Maintainer form (ruling, variant v): the root owns nothing but the
    composition — no formulas, no routing policy, no derived values, no
    proxy methods outward.  A helper that needs a family reaches through
    the owning house (``facts.analysis.contracts``), never through a root
    forwarder — a forwarder would rebuild the undifferentiated bag one
    level up.  The pin lives in
    ``tests/test_canonical_facts_composition.py`` and reads this class's
    SOURCE, so a smuggled method cannot hide behind byte-identical runtime
    behavior.
    """

    analysis: AnalysisFacts = field(default_factory=AnalysisFacts)
    comparison: ComparisonFacts = field(default_factory=ComparisonFacts)
    evaluation: EvaluationFacts = field(default_factory=EvaluationFacts)


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


def _dependency_edge_key(row: DependencyEdgeRow) -> tuple[object, ...]:
    # The producer's dedup key, verbatim (metrics/dependencies.py):
    # (source, target, import_type, line) — binding and is_lazy are payload.
    return (
        endpoint_key(row.source),
        endpoint_key(row.target),
        row.import_type,
        row.line,
    )


def _violation_natural_key(row: ViolationRow) -> tuple[object, ...]:
    return (
        row.contract_id,
        row.kind,
        canonical_key(row.sink_identity),
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

    def see_rooted_function(
        self, function: SymbolId, root_set: frozenset[EffectRoot]
    ) -> None:
        self.see_symbol(function)
        for root in root_set:
            self.see_root(root)

    def see_endpoint(self, endpoint: DependencyEndpoint) -> None:
        if isinstance(endpoint, ModuleId):
            self.modules.add(endpoint)
        else:
            self.files.add(endpoint)

    def see_violation(self, violation: ViolationRow) -> None:
        self.see_symbol(violation.sink_identity)
        self.see_symbol(violation.canonical_owner)
        for producer in violation.producer_set:
            self.see_symbol(producer)
        for root in violation.root_set:
            self.see_root(root)


def _close_domains(model: CanonicalModel) -> _DomainClosure:
    """Stage 1: complete the identity domains to their referential closure."""
    closure = _DomainClosure(model)
    facts = model.facts.analysis
    for relation in model.file_modules:
        closure.files.add(relation.file)
        closure.modules.add(relation.module)
    for contract in facts.contracts:
        closure.see_rooted_function(contract.function, contract.root_set)
    for node in facts.graph_nodes:
        closure.see_rooted_function(node.function, node.root_set)
    for sink in facts.sink_roles:
        closure.see_symbol(sink.symbol)
    for candidate in facts.candidates:
        for producer in candidate.producer_set:
            closure.see_symbol(producer)
    for edge in facts.semantic_edges:
        closure.see_symbol(edge.source)
        closure.see_symbol(edge.target)
    for dep in facts.dependency_edges:
        closure.see_endpoint(dep.source)
        closure.see_endpoint(dep.target)
    for violation in facts.violations:
        closure.see_violation(violation)
    for observation in facts.coupling_cohesion_observations:
        closure.see_symbol(observation.symbol)
    closure.files.update(model.analyzed_files)
    return closure


def _prove_logical_keys(facts: AnalysisFacts) -> None:
    """Stage 2: one logical key names at most one fact, per family (S5.A)."""
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
    _unique_by_key(
        facts.dependency_edges,
        "dependency_edges.producer_key",
        _dependency_edge_key,
    )
    _unique_by_key(facts.violations, "violations.natural_key", _violation_natural_key)
    _unique_by_key(
        facts.coupling_cohesion_observations,
        "coupling_cohesion_observations.key",
        lambda row: (canonical_key(row.symbol), row.dimension),
    )


def _prove_function_roles(facts: AnalysisFacts) -> None:
    """Stage 3: producers and violation sinks carry the FUNCTION role."""
    function_symbols = {row.function for row in facts.contracts}
    producer_sets = [row.producer_set for row in facts.candidates]
    producer_sets.extend(row.producer_set for row in facts.violations)
    for producer_set in producer_sets:
        for producer in producer_set:
            if producer not in function_symbols:
                raise CanonicalModelError(
                    "producer set references a symbol without the "
                    f"FUNCTION role: {producer!r}"
                )
    for violation in facts.violations:
        if violation.sink_identity not in function_symbols:
            raise CanonicalModelError(
                "violation sink references a symbol without the "
                f"FUNCTION role: {violation.sink_identity!r}"
            )


def _normalized(model: CanonicalModel) -> CanonicalModel:
    """Complete the domains to their closure and prove every key law
    (idempotent; never invents facts, never reorders — order is a
    projection concern)."""
    closure = _close_domains(model)
    _prove_logical_keys(model.facts.analysis)
    _prove_function_roles(model.facts.analysis)
    return replace(
        model,
        files=frozenset(closure.files),
        modules=frozenset(closure.modules),
    )
