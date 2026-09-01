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

Corpus ratios in this module are DATED OBSERVATIONS, never invariants: a
population moves with the tree, so a ratio describes one corpus at one
revision.  A ratio carrying a revision stamp (``2 379/2 379 @ 95e4210b,
2026-08-30``) was re-measured then; a ratio WITHOUT one is of unknown
vintage and must be re-measured before it is relied on.  The invariant
the ratios support — the key is total on its family — is enforced by
``_unique_by_key`` on every ingest, not by these numbers.

Wave family subset: ``file_modules · contracts · graph_nodes · sink_roles
· candidates · semantic_edges · dependency_relations ·
dependency_occurrences · violations · coupling_cohesion_observations ·
api_symbols · risk_observations · run_scalars`` plus the standalone
``coupled_sets`` value sets.

``dependency_relations`` / ``dependency_occurrences`` (ratified split,
ruling 2026-08-24 §2): dependencies are TWO objects.  The **relation**
``(source, target, dependency_type)`` is the semantic entity — the graph
that gate and SCC read; ``line`` is never added to it (that would merely
reproduce the metrics dialect).  The **occurrence** is location evidence
bound to a relation: its producer row key is measured, not invented —
``metrics/dependencies.py:_unique_sorted_edges`` dedups on
``(source, target, import_type, line)``, unique on 5 244 of 5 244 corpus
rows; dropping ``line`` collides 926 (two occurrences of one relation),
and the 861 distinct endpoints split MODULE 860 / FILE 1 — the ratified
``DependencyEndpoint`` union.  ``binding`` and ``is_lazy`` are occurrence
payload, not key: two occurrences under one producer key may not disagree.
Location is evidence, never identity: the row key dedups evidence rows and
never names the entity.  A relation may stand with zero occurrences; an
occurrence whose relation the model does not carry is refused.

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
from dataclasses import dataclass, field, fields, replace
from itertools import pairwise
from typing import TypeVar

from codeclone.canonical.api_identity import signature_variant
from codeclone.canonical.errors import CanonicalModelError
from codeclone.canonical.identity import (
    ADOPTION_FEATURES,
    API_PARAMETER_KINDS,
    API_SYMBOL_KINDS,
    API_VISIBILITIES,
    CLONE_KINDS,
    COUPLING_COHESION_DIMENSIONS,
    DEAD_CODE_CANDIDATE_KINDS,
    DEAD_CODE_OBSERVATION_KINDS,
    DEPENDENCY_BINDINGS,
    DEPENDENCY_CYCLE_KINDS,
    IMPORT_TYPES,
    LIVE_ROOT_REASONS,
    PRODUCER_EXECUTION_STATES,
    RISK_DIMENSIONS,
    SECURITY_CLASSIFICATION_MODES,
    SECURITY_EVIDENCE_KINDS,
    SECURITY_LOCATION_SCOPES,
    SECURITY_SOURCE_KINDS,
    SECURITY_SURFACE_CATEGORIES,
    VIOLATION_KINDS,
    AnalysisFile,
    DeadCodeEntity,
    DependencyEndpoint,
    EffectRoot,
    FileId,
    FileLine,
    KnownModule,
    ModuleId,
    ModuleSymbol,
    OperationRoot,
    ProducerRoot,
    ScopeRef,
    SourceLocation,
    SymbolId,
    canonical_key,
    dead_code_entity_key,
    endpoint_key,
    source_location_key,
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
    """SINK role payload: only what the role itself owns (§8.1).

    Nine published columns are absent, and none of them was canonicalized:
    ``effect_signature``, ``producer_root_ids`` and ``resolution_state``
    belong to the function CONTRACT and are read off the same
    ``by_function`` entry the producer builds the graph node from — the
    §8.V.3 test lands inside the subset, so storing them would be one fact
    in two places.  ``source_kind`` is a document-layer ranking term over a
    producer list a sink row does not carry, ``algorithm_revision`` is run
    provenance, and ``score``/``independence``/``semantic_divergence``/
    ``suppressed`` are the union container's placeholders: the authority
    producer emits no such key on a sink item at all.  The one owner that
    rebuilds them is ``codeclone.canonical.authority_projection``.
    """

    symbol: SymbolId
    authority_status: str


@dataclass(frozen=True, slots=True)
class CandidateRow:
    """Authority candidate; natural key ``(level, shared_fact, producer_set)``.

    The key IS the row: every other published column is closed by a verdict
    rather than stored (step 8).  ``candidate_id`` and ``score`` are class-B
    contract-derived values with one formula owner (§5.1, §8.0);
    ``independence``, ``semantic_divergence`` and ``sink_statuses`` are
    conclusions the stored authority graph settles, so carrying them would
    be the same fact in two places; ``source_kind`` is a document-layer
    ranking term, ``algorithm_revision`` is run provenance, and
    ``suppressed`` is the union container's placeholder — the producer emits
    no such key on a candidate.  The one owner that rebuilds them all is
    ``codeclone.canonical.authority_projection``.
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
class DependencyRelationRow:
    """The dependency ENTITY: ``(source, target, dependency_type)``.

    The ratified split (ruling 2026-08-24 §2): the relation is the whole
    fact — the triple is both logical key and full content, like
    :class:`SemanticEdge`.  Gate and SCC consume this graph.  ``line`` is
    deliberately NOT here: adding it would reproduce the metrics dialect
    and turn one entity into as many rows as it has evidence sites.
    """

    source: DependencyEndpoint
    target: DependencyEndpoint
    dependency_type: str

    def __post_init__(self) -> None:
        if self.dependency_type not in IMPORT_TYPES:
            raise CanonicalModelError(
                f"unknown dependency_type: {self.dependency_type!r}"
            )


@dataclass(frozen=True, slots=True)
class DependencyOccurrenceRow:
    """Location EVIDENCE bound to one dependency relation.

    ``location is evidence, not identity``: the entity is ``relation``;
    ``line`` only distinguishes evidence rows (producer row key
    ``(relation, line)``, measured — 926 corpus collisions without it).
    ``binding`` and ``is_lazy`` are occurrence payload: one relation may
    bind at import time on one line and deferred on another.  Two
    occurrences sharing the row key with different payload are a producer
    defect and are refused, not last-writer-silenced.
    """

    relation: DependencyRelationRow
    line: int
    binding: str
    is_lazy: bool

    def __post_init__(self) -> None:
        if self.binding not in DEPENDENCY_BINDINGS:
            raise CanonicalModelError(f"unknown dependency binding: {self.binding!r}")
        if isinstance(self.line, bool) or self.line < 0:
            raise CanonicalModelError(
                f"dependency line must be a non-negative int: {self.line!r}"
            )


@dataclass(frozen=True, slots=True)
class DependencyCycleRow:
    """F7 runtime dependency cycle fact (wave 4).

    The family law, pinned by the distinguishing corpus: ONE row per module
    set, the kind classified exactly once by the one producer owner
    (``metrics/dependencies.runtime_cycle_facts``) — a deferred back-edge
    over a pair that already carries an import-time cycle never births a
    second row.  The natural key spells ``(kind, sorted module set)`` on the
    wire, but uniqueness is proven on the module SET alone, so two rows
    disagreeing only in kind are refused as a producer defect.  Gate and
    SCC read the relation graph; this family stores the classification
    VERDICT as an analysis fact and never re-derives it on read.

    ``modules`` is MODULE-domain, never strings (ruling 2026-08-24 §2), and
    carries at least two members (the producer's Tarjan floor:
    ``len(component) > 1`` — a self-loop is never emitted).  The legacy
    row's ``member_paths`` is deliberately NOT here: it is the registry's
    FILE-MODULE projection — a table, never a column (§2.3) — declared
    ``representation_projection`` in the registry and re-derivable from
    ``file_modules``; storing it per row would be a second spelling of the
    same relation.
    """

    kind: str
    modules: frozenset[ModuleId]

    def __post_init__(self) -> None:
        if self.kind not in DEPENDENCY_CYCLE_KINDS:
            raise CanonicalModelError(f"unknown dependency cycle kind: {self.kind!r}")
        if len(self.modules) < 2:
            raise CanonicalModelError(
                "a dependency cycle names at least two modules "
                "(the producer's Tarjan floor drops self-loops)"
            )


@dataclass(frozen=True, slots=True)
class CloneItemRow:
    """One member of an emitted clone group: the unit and its span.

    The span IS part of the member's identity — the corpus's block group
    carries an intra-function pair (one SYMBOL, two spans), so group arity
    and item identity are different measurements and a span-blind member
    would silently collapse the pair.  Per-kind item metrics (``loc``,
    ``fingerprint``, ``size``, ``segment_hash``…) stay with the legacy
    document for a later wave — the wave subset decides what is carried
    (the candidate-scoring precedent).
    """

    symbol: SymbolId
    start_line: int
    end_line: int

    def __post_init__(self) -> None:
        if isinstance(self.start_line, bool) or self.start_line < 1:
            raise CanonicalModelError(
                f"clone item start line must be a positive int: {self.start_line!r}"
            )
        if isinstance(self.end_line, bool) or self.end_line < self.start_line:
            raise CanonicalModelError(
                "clone item end line must be an int not before its start: "
                f"{self.end_line!r}"
            )


@dataclass(frozen=True, slots=True)
class CloneGroupRow:
    """F8 emitted clone group fact (wave 4).

    Logical key — the producer's own: ``(clone_kind, group_key)``.  The
    kind is a KEY component (one producer key string may exist under two
    kinds), and ``group_key`` is the producer's fp-v2 grouping key whose
    meaning is owned by the clone fingerprint generation.  The family is
    the EMITTED population only: ``clones.suppressed`` is a different
    population (ruling 2026-08-24 §10) and never enters it.  A group names
    at least two members — every detector tier groups occurrences, and a
    group of one asserts a grouping the producer never made.
    """

    clone_kind: str
    group_key: str
    items: frozenset[CloneItemRow]

    def __post_init__(self) -> None:
        if self.clone_kind not in CLONE_KINDS:
            raise CanonicalModelError(f"unknown clone kind: {self.clone_kind!r}")
        if not self.group_key:
            raise CanonicalModelError("clone group key must be non-empty")
        if len(self.items) < 2:
            raise CanonicalModelError(
                "a clone group names at least two items (a group of one is "
                "not a grouping the producer makes)"
            )


@dataclass(frozen=True, slots=True)
class DeadCodeObservationRow:
    """F4 dead-code observation fact (wave 4, slice K3).

    Logical key: ``(entity, observation_kind)`` — and it is NOT total on
    this lane.  Measured on the self-repo corpus (14 826/14 827 @ 95e4210b,
    2026-08-30; a dated observation of one corpus at one revision, never an
    invariant): the ingest ``frozenset`` collapses one repeat, so the model
    carries one row fewer than the report the same run emitted.

    That collapse is NOT "one fact stated twice".  The two colliding rows
    are the getter and the setter of ``MCPSession._agent_label`` — two
    declarations, at source lines 191 and 197 — and they arrive
    byte-identical only because this lane's row shape carries no
    declaration site.  The producer is not uniform about that: it emits ONE
    row for an ``@overload`` family (the stubs are dropped upstream) and
    TWO for a property/setter pair, while the F1 lane, which does carry
    ``start_line``, emits both declarations.  So a real declaration is
    lost, silently, before any model guard can see it.

    What a byte-identical repeat SHOULD be — a refusal, a counted
    multiplicity, or a collapse with a receipt — decides wire and identity
    semantics and is an open ruling; this docstring states the measurement,
    not a resolution.  Two DIFFERING rows under one key stay refused.

    The entity is the RATIFIED tagged reference (ruling 2026-08-24 §2):
    the variant is part of the identity, and an unclassifiable reference
    is refused at the oracle, not guessed into a domain.  The counts are
    observed facts (zero measured);
    ``abstained`` and ``live_root_reason`` are mutually exclusive by the
    producer's contract — an abstention outranks a root reason and the two
    never coexist on one row.
    """

    entity: DeadCodeEntity
    observation_kind: str
    candidate_kind: str
    reference_count: int
    reachable: bool
    runtime_marker_count: int
    source_markers: tuple[tuple[str, str], ...]
    live_root_reason: str | None
    abstained: bool

    def __post_init__(self) -> None:
        if self.observation_kind not in DEAD_CODE_OBSERVATION_KINDS:
            raise CanonicalModelError(
                f"unknown dead-code observation kind: {self.observation_kind!r}"
            )
        if self.candidate_kind not in DEAD_CODE_CANDIDATE_KINDS:
            raise CanonicalModelError(
                f"unknown dead-code candidate kind: {self.candidate_kind!r}"
            )
        for count in (self.reference_count, self.runtime_marker_count):
            if isinstance(count, bool) or count < 0:
                raise CanonicalModelError(
                    f"dead-code counts must be non-negative ints: {count!r}"
                )
        if self.source_markers != tuple(sorted(set(self.source_markers))):
            raise CanonicalModelError(
                "dead-code source markers must be sorted and unique"
            )
        if any(not key or not value for key, value in self.source_markers):
            raise CanonicalModelError(
                "dead-code source markers must be non-empty pairs"
            )
        if self.live_root_reason is not None and (
            self.live_root_reason not in LIVE_ROOT_REASONS
        ):
            raise CanonicalModelError(
                f"unknown live root reason: {self.live_root_reason!r}"
            )
        if self.abstained and self.live_root_reason is not None:
            raise CanonicalModelError(
                "an abstained dead-code observation cannot also carry a "
                "live root (the two are mutually exclusive by contract)"
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

    Of the six published columns this row does not carry, every one is
    rebuilt by ``codeclone.canonical.authority_projection``:
    ``producer_root_ids`` is ``root_set`` rendered, ``source_kind`` is a
    document-layer ranking term over the stored producer set,
    ``algorithm_revision`` is run provenance, and
    ``score``/``independence``/``semantic_divergence`` are union
    placeholders the producer emits no key for.

    ``locations`` used to be a seventh, and it is STORED rather than
    derived because it failed the §8.V.3 test where the other six pass: the
    producer distills it from ``FunctionContractSummary.events``, and that
    event stream is no family of this subset, so the basis lay OUTSIDE and
    closing it was a canonicalization decision rather than a projection.

    What is stored is the DISTILLED witness, not the event stream: the
    producer's own selection (deduplicated, ordered, first three) as a tuple
    of tagged :data:`~codeclone.canonical.identity.SourceLocation` values,
    and three laws ride it.

    * **Canonical order, not arrival order.** The tuple is strictly
      increasing under
      :func:`~codeclone.canonical.identity.source_location_key`, so the row
      a set of sites produces does not depend on the order the events
      happened to arrive in.
    * **No accidental collapse.** *Strictly* increasing, so two sites that
      differ at all — same path, different line included — stay two
      evidence points.  A repeat is REFUSED rather than deduplicated:
      silently absorbing one would lose an evidence point exactly where a
      count is what a reader relies on.
    * **No silent drop.** A site the FILE domain cannot admit rides the
      ``UnresolvedLocation`` variant verbatim (the grammar owner is
      ``canonical.semantic_grammar.parse_source_location``).  It is never
      dropped, because a dropped site shortens the tuple and an emptied
      tuple reads as "the producer had nothing to say".

    The published location struct carries two more slots, and both are
    derived rather than stored.  ``qualname`` is the violation's OWN
    ``sink_identity`` — the producer keys its per-function location table by
    the summary's function and stamps that same string on every row of it,
    then attaches the sink's entry to the violation — so storing it would be
    the same fact twice.  ``end_line`` equals ``start_line`` because
    ``SemanticEvent.location`` is ``(path, line)``: one line, never a span.
    Neither derivation can rot in silence — the projection equivalence
    compares the whole published row byte for byte, so a producer that grew
    a real span or a second qualname turns that comparison red.
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
    locations: tuple[SourceLocation, ...]

    def __post_init__(self) -> None:
        if not self.contract_id:
            raise CanonicalModelError("violation contract_id must be non-empty")
        if self.kind not in VIOLATION_KINDS:
            raise CanonicalModelError(f"unknown violation kind: {self.kind!r}")
        keys: list[tuple[bytes, int, str]] = [
            source_location_key(location) for location in self.locations
        ]
        if any(earlier >= later for earlier, later in pairwise(keys)):
            raise CanonicalModelError(
                "violation locations must be strictly increasing under the "
                f"canonical location key: {self.locations!r}"
            )


@dataclass(frozen=True, slots=True)
class CouplingCohesionRow:
    """F2 per-class design-metric observation (wave 4).

    Logical key — measured from the producer, never invented:
    ``(SYMBOL, dimension)``, unique on the corpus (2 091/2 091 at
    ratification, 2 379/2 379 @ 95e4210b 2026-08-30)
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
class RiskObservationRow:
    """F1 per-declaration risk observation (ruling 2026-08-26, fork (b)).

    Logical key — the RATIFIED form: ``(SYMBOL, dimension, start_line)``,
    spelling the registry's ``(file, qualname, dimension, start_line)``.
    The bare site-blind key is blind to 4 measured declaration groups:
    ``@overload`` families of 4, 4 and 3 declarations plus one
    property/setter pair of 2, so 13 rows collapse onto 4 keys and 9 rows
    are lost (9 of 20 001 @ 95e4210b, 2026-08-30 — a dated observation, not
    an invariant; the note this replaced said "three ``@overload`` triples
    and one pair", whose own arithmetic gives 7, not the 9 it claimed).
    Every group is *different declarations sharing one name*, so
    deduplication is indefensible.  ``start_line`` is the producer-native
    discriminator (the ``complexity.items`` precedent, 14 040/14 040 unique
    @ 95e4210b) and here it IS identity — the named exception to the
    dependency rule that location is evidence (ruling §2), admitted by the
    maintainer's fork (b).  ``numerator`` is payload and strictly positive:
    the producer drops zero rows, so absence already means zero.  No
    FUNCTION-role requirement: these symbols name any measured unit.
    """

    symbol: SymbolId
    dimension: str
    numerator: int
    start_line: int

    def __post_init__(self) -> None:
        if self.dimension not in RISK_DIMENSIONS:
            raise CanonicalModelError(f"unknown risk dimension: {self.dimension!r}")
        if isinstance(self.numerator, bool) or self.numerator < 1:
            raise CanonicalModelError(
                f"risk numerator must be a positive int: {self.numerator!r}"
            )
        if isinstance(self.start_line, bool) or self.start_line < 1:
            raise CanonicalModelError(
                f"risk declaration site must be a positive int: {self.start_line!r}"
            )


@dataclass(frozen=True, slots=True)
class ApiParameterFact:
    """One parameter of an F5 API symbol signature (wave 4).

    ``annotation_digest`` follows the producer's own bijection
    (``observations/projection.py:_component_digest``): an empty annotation
    basis IS absence, so an empty digest string here would spell absence as
    a value and is refused.
    """

    name: str
    kind: str
    has_default: bool
    annotation_digest: str | None

    def __post_init__(self) -> None:
        if not self.name:
            raise CanonicalModelError("api parameter name must be non-empty")
        if self.kind not in API_PARAMETER_KINDS:
            raise CanonicalModelError(f"unknown api parameter kind: {self.kind!r}")
        if self.annotation_digest is not None and not self.annotation_digest:
            raise CanonicalModelError(
                "api parameter annotation digest must be non-empty when "
                "present (the producer spells absence as absence)"
            )


@dataclass(frozen=True, slots=True)
class ApiSymbolRow:
    """F5 public API symbol fact (wave 4).

    Logical key — the RATIFIED form, not the bare measured one:
    ``(SYMBOL, canonical_signature_variant)``.  The bare ``(FILE, symbol)``
    key is 10 140/10 143 on the frozen corpus — the three lost groups are
    ``@overload`` declarations differing only in signature, so the variant
    (one formula owner: ``api_signature_identity_contract.v1``) is the
    discriminator.  ``symbol_kind`` and ``visibility`` are payload, never
    key.  No FUNCTION-role requirement: API symbols name modules' public
    surface, not contract functions.
    """

    symbol: SymbolId
    symbol_kind: str
    visibility: str
    parameters: tuple[ApiParameterFact, ...]
    returns_digest: str | None

    def __post_init__(self) -> None:
        if self.symbol_kind not in API_SYMBOL_KINDS:
            raise CanonicalModelError(f"unknown api symbol kind: {self.symbol_kind!r}")
        if self.visibility not in API_VISIBILITIES:
            raise CanonicalModelError(f"unknown api visibility: {self.visibility!r}")
        if self.returns_digest is not None and not self.returns_digest:
            raise CanonicalModelError(
                "api returns digest must be non-empty when present"
            )


@dataclass(frozen=True, slots=True)
class AdoptionCountRow:
    """F3 per-scope adoption count (wave 4).

    Logical key — the producer's own: ``(scope, feature)``, unique on the
    corpus (2 614/2 614 at ratification, 2 671/2 671 @ 95e4210b
    2026-08-30).  The scope is the RATIFIED
    tagged ScopeRef (ruling 2026-08-24 §2): the producer resolves it as
    ``identity.python_module.module`` when the file has a module identity
    and the analyzed path otherwise (``analysis/units.py``), so the
    reference is MODULE | FILE by construction — never a polymorphic
    string, and the variant IS identity.  The counters are observed facts:
    the producer drops zero-denominator scopes (absence already means
    unmeasured), so the denominator floor is 1; a ZERO numerator is a
    MEASURED value (a module with none of its N parameters annotated is a
    fact — 16 of 46 corpus rows), unlike the F2 floor; and a numerator
    above its denominator cannot be produced, so it is refused as a
    defect, never clamped.
    """

    scope: ScopeRef
    feature: str
    numerator: int
    denominator: int

    def __post_init__(self) -> None:
        if self.feature not in ADOPTION_FEATURES:
            raise CanonicalModelError(f"unknown adoption feature: {self.feature!r}")
        if isinstance(self.numerator, bool) or self.numerator < 0:
            raise CanonicalModelError(
                f"adoption numerator must be a non-negative int: {self.numerator!r}"
            )
        if isinstance(self.denominator, bool) or self.denominator < 1:
            raise CanonicalModelError(
                "adoption denominator must be a positive int (the producer "
                f"drops zero-denominator scopes): {self.denominator!r}"
            )
        if self.numerator > self.denominator:
            raise CanonicalModelError(
                "adoption numerator cannot exceed its denominator: "
                f"{self.numerator!r}/{self.denominator!r}"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class SecuritySurfaceRow:
    """F10 security-surface fact (wave 4, slice 5).

    Logical key — measured, never invented: ``(FILE, start_line,
    evidence_symbol)``.  The packet's exhaustive 1-3-field enumeration
    found exactly SIX unique 3-keys with ``evidence_symbol`` in every one
    (377/377 at recon, 387/387 at the ratification HEAD, 406/406 @
    95e4210b, 2026-08-30 — dated observations of one corpus at three
    revisions, not an invariant; the population moves with the tree, the
    key's totality is what the model law proves on every run), and this is
    the ratified pick.  Two symbols may share one
    line (the s5 ``eval(compile(...))`` datum) and one symbol may repeat
    across lines — both key components carry measured weight.

    ``source_kind`` is the classification VERDICT of the one producer
    owner, stored as an analysis fact and never re-derived on read (the F7
    kind precedent); its meaning is owned by SOURCE_KIND_POLICY_VERSION.
    ``capability`` is the producer's catalog entry — an open string whose
    meaning is owned by SECURITY_SURFACE_CATALOG_VERSION, never a wire
    vocabulary.  ``qualname`` is the LOCAL name of the hosting unit and is
    absent exactly on module-scope rows (the head is the file itself);
    the producer's glued ``head:local`` spelling never enters the model.
    The legacy row's ``module`` field is the registry's FILE-MODULE
    projection — verified at ingest, re-derivable from ``file_modules``,
    never stored (the F7 ``member_paths`` precedent).
    """

    file: FileId
    start_line: int
    end_line: int
    evidence_symbol: str
    qualname: str | None
    location_scope: str
    category: str
    capability: str
    evidence_kind: str
    classification_mode: str
    source_kind: str

    def __post_init__(self) -> None:
        if self.category not in SECURITY_SURFACE_CATEGORIES:
            raise CanonicalModelError(f"unknown surface category: {self.category!r}")
        if self.location_scope not in SECURITY_LOCATION_SCOPES:
            raise CanonicalModelError(
                f"unknown surface location scope: {self.location_scope!r}"
            )
        if self.evidence_kind not in SECURITY_EVIDENCE_KINDS:
            raise CanonicalModelError(
                f"unknown surface evidence kind: {self.evidence_kind!r}"
            )
        if self.classification_mode not in SECURITY_CLASSIFICATION_MODES:
            raise CanonicalModelError(
                f"unknown surface classification mode: {self.classification_mode!r}"
            )
        if self.source_kind not in SECURITY_SOURCE_KINDS:
            raise CanonicalModelError(
                f"unknown surface source kind: {self.source_kind!r}"
            )
        if not self.evidence_symbol:
            raise CanonicalModelError("surface evidence symbol must be non-empty")
        if not self.capability:
            raise CanonicalModelError("surface capability must be non-empty")
        if isinstance(self.start_line, bool) or self.start_line < 1:
            raise CanonicalModelError(
                f"surface start line must be a positive int: {self.start_line!r}"
            )
        if isinstance(self.end_line, bool) or self.end_line < self.start_line:
            raise CanonicalModelError(
                "surface end line must be an int not before its start: "
                f"{self.end_line!r}"
            )
        if self.location_scope == "module":
            if self.qualname is not None:
                raise CanonicalModelError(
                    "a module-scope surface carries no local name (the head "
                    f"is the file itself): {self.qualname!r}"
                )
        elif not self.qualname:
            raise CanonicalModelError(
                f"a {self.location_scope}-scope surface requires a local name"
            )
        elif ":" in self.qualname:
            raise CanonicalModelError(
                f"surface local name must not be a glued identity: {self.qualname!r}"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class RunScalars:
    """F9 run-level analysis scalars (wave 4) — ONE record per snapshot.

    The ratified form (ruling 2026-08-24 §1): a run-level analysis fact,
    never a tabular entity — there is no entity key because there is no
    entity row; inventing one would manufacture identity the producer never
    asserted.  Every scalar is an observed count of the realized run
    population; zero is a MEASURED value here (a run with zero classes is a
    fact), unlike the F2 floor where the producer drops zero rows.
    Strictly derivable values are deliberately NOT included (later derived).
    """

    classes: int
    files_analyzed: int
    files_cached: int
    files_found: int
    files_skipped: int
    functions: int
    methods: int
    parsed_lines: int
    source_io_skipped: int
    unsupported_construct_skipped: int

    def __post_init__(self) -> None:
        for scalar_field in fields(self):
            value = getattr(self, scalar_field.name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise CanonicalModelError(
                    f"run scalar {scalar_field.name} must be a "
                    f"non-negative int: {value!r}"
                )


@dataclass(frozen=True, slots=True)
class AnalysisPopulation:
    """The run-level execution-population authority (RULING-2026-08-31 §3).

    "We analyzed this population" is a semantic statement of its own:
    fifteen families at zero rows without this witness are not a
    canonical fact.  ONE record per analysis snapshot — a singleton
    authority, never a row family — carrying the realized profile and
    the per-producer-family execution states.  The ratified five-state
    law lives in the ``PRODUCER_EXECUTION_STATES`` vocabulary:
    ``complete`` with a zero count, ``not_executed``, ``disabled``,
    ``truncated`` and ``unavailable`` are five different statements, and
    a zero count is admissible ONLY as the result of an executed
    measurement — absence of execution never projects to zero.

    What is deliberately NOT here, and why:

    * ``analyzed_scope`` / ``analyzed_files`` / the source-universe
      witness already ride the model (``CanonicalModel.analyzed_files``,
      ``files``); respelling them in this record would be the same fact
      in two places — the drift class §21 of the backend brief names as
      the main implementation hazard.
    * the file-population state (four states) is derivable from
      ``run_scalars`` counters through its one contract owner
      (``codeclone.contracts.observed_population``) — a
      contract-derived value, never a stored analysis fact.
    * the population receipts of the ratified composition
      (``candidate_count`` / ``examined_count`` / ``returned_count`` and
      the pipeline truncation state/reason) are NOT witnessed by any
      legacy document this model can ingest today; landing their columns
      now would force fabricated zeros — exactly what the hard law
      forbids — so they join with the producer wiring that can witness
      them, as a pre-freeze draft column addition.

    ``producer_states`` keys are producer/metric family names as the run
    pronounced them — an open vocabulary whose meaning the producer
    registry (identity ruling I1) will own; the states themselves are
    the closed ratified vocabulary.
    """

    analysis_mode: str
    analysis_profile: tuple[tuple[str, int], ...]
    producer_states: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not self.analysis_mode:
            raise CanonicalModelError("analysis_mode must be a non-empty string")
        profile_names = [name for name, _value in self.analysis_profile]
        if profile_names != sorted(set(profile_names)):
            raise CanonicalModelError(
                "analysis_profile must be sorted and unique by parameter name"
            )
        for name, value in self.analysis_profile:
            if not name:
                raise CanonicalModelError("analysis_profile parameter name is empty")
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise CanonicalModelError(
                    f"analysis_profile parameter {name} must be a "
                    f"non-negative int: {value!r}"
                )
        family_names = [family for family, _state in self.producer_states]
        if family_names != sorted(set(family_names)):
            raise CanonicalModelError(
                "producer_states must be sorted and unique by family name"
            )
        for family, state in self.producer_states:
            if not family:
                raise CanonicalModelError("producer_states family name is empty")
            if state not in PRODUCER_EXECUTION_STATES:
                raise CanonicalModelError(
                    f"producer state {state!r} of family {family} is outside "
                    f"the ratified execution-state vocabulary"
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
    dependency_relations: frozenset[DependencyRelationRow] = field(
        default_factory=frozenset
    )
    dependency_occurrences: frozenset[DependencyOccurrenceRow] = field(
        default_factory=frozenset
    )
    dependency_cycles: frozenset[DependencyCycleRow] = field(default_factory=frozenset)
    clone_groups: frozenset[CloneGroupRow] = field(default_factory=frozenset)
    dead_code_observations: frozenset[DeadCodeObservationRow] = field(
        default_factory=frozenset
    )
    violations: frozenset[ViolationRow] = field(default_factory=frozenset)
    coupling_cohesion_observations: frozenset[CouplingCohesionRow] = field(
        default_factory=frozenset
    )
    api_symbols: frozenset[ApiSymbolRow] = field(default_factory=frozenset)
    risk_observations: frozenset[RiskObservationRow] = field(default_factory=frozenset)
    adoption_counts: frozenset[AdoptionCountRow] = field(default_factory=frozenset)
    security_surfaces: frozenset[SecuritySurfaceRow] = field(default_factory=frozenset)
    # F9: one record per analysis snapshot; None is the absent record —
    # never an all-zero fake (zero is measured in this family).
    run_scalars: RunScalars | None = None
    # RULING-2026-08-31 §3: the execution-population singleton; None is
    # the absent record — a legacy document that never declared what it
    # computed stays honestly unwitnessed, never fabricated.
    analysis_population: AnalysisPopulation | None = None


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
    """Refuse two DIFFERING facts under one logical key.

    A repeat that is byte-identical to the row already seen is swallowed
    here instead of refused, and that branch is UNREACHABLE on every
    population this repository can build: all 14 call sites read a
    ``frozenset``-typed family off the fact houses, and a set cannot hold
    two equal rows — the repeat has already been absorbed upstream, so this
    prover never meets one.  ``test_canonical_roundtrip`` pins both halves
    of that claim (the branch's behaviour, and that every keyed family is a
    frozenset), because an unexecuted unreachability claim rots.

    The branch is kept, not deleted, and the reason is a boundary, not
    taste: deleting it would make a byte-identical repeat a REFUSAL, and
    what such a repeat IS — refusal, counted multiplicity, or a collapse
    with a receipt — is the open wire/identity ruling that
    ``DeadCodeObservationRow`` documents.  Read it as a hazard, not as
    tolerance: the day a family becomes a SEQUENCE (a list or tuple, keyed
    the same way), this branch silently accepts a duplicated row — measured
    directly, not reasoned — and would mask exactly the loss class the F4
    lane already exhibits at ingest.  Whoever makes a family a sequence
    must decide this branch first.
    """
    seen: dict[object, object] = {}
    for row in rows:
        key = key_of(row)
        if key in seen:
            byte_identical_repeat = seen[key] == row
            if not byte_identical_repeat:
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


def _dependency_relation_key(row: DependencyRelationRow) -> tuple[object, ...]:
    return (
        endpoint_key(row.source),
        endpoint_key(row.target),
        row.dependency_type,
    )


def _dependency_occurrence_key(row: DependencyOccurrenceRow) -> tuple[object, ...]:
    # The producer's dedup key, verbatim (metrics/dependencies.py):
    # (source, target, import_type, line) — binding and is_lazy are payload.
    return (*_dependency_relation_key(row.relation), row.line)


def _dependency_cycle_set_key(row: DependencyCycleRow) -> tuple[object, ...]:
    # The family law: the module SET alone names the entity (one row per
    # set, kind classified once).  Keying on (kind, modules) instead would
    # let the two kinds coexist on one set — the exact defect the corpus
    # pins out of existence.
    return tuple(sorted(canonical_key(module) for module in row.modules))


def _clone_group_natural_key(row: CloneGroupRow) -> tuple[object, ...]:
    return (row.clone_kind.encode("utf-8"), row.group_key.encode("utf-8"))


def _dead_code_observation_key(row: DeadCodeObservationRow) -> tuple[object, ...]:
    return (*dead_code_entity_key(row.entity), row.observation_kind)


def _api_symbol_natural_key(row: ApiSymbolRow) -> tuple[object, ...]:
    # The ratified F5 key: the SYMBOL plus the canonical signature variant,
    # computed through its ONE formula owner — never a second spelling.
    return (
        canonical_key(row.symbol),
        signature_variant(parameters=row.parameters, returns_digest=row.returns_digest),
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

    def see_dead_code_entity(self, entity: DeadCodeEntity) -> None:
        if isinstance(entity, SymbolId):
            self.see_symbol(entity)
        elif isinstance(entity, ModuleSymbol):
            self.modules.add(entity.module)
        # OpaqueEntity: the head has no domain to admit — that is its point.

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
        for location in violation.locations:
            # The security-surface precedent: an evidence FILE joins the
            # domain because the wire addresses it by ordinal.  The
            # unresolved variant contributes nothing — having no domain to
            # join is exactly what it asserts.
            if isinstance(location, FileLine):
                self.files.add(location.file)


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
    for dependency_relation in facts.dependency_relations:
        closure.see_endpoint(dependency_relation.source)
        closure.see_endpoint(dependency_relation.target)
    for occurrence in facts.dependency_occurrences:
        closure.see_endpoint(occurrence.relation.source)
        closure.see_endpoint(occurrence.relation.target)
    for cycle in facts.dependency_cycles:
        closure.modules.update(cycle.modules)
    for group in facts.clone_groups:
        for item in group.items:
            closure.see_symbol(item.symbol)
    for dead_observation in facts.dead_code_observations:
        closure.see_dead_code_entity(dead_observation.entity)
    for violation in facts.violations:
        closure.see_violation(violation)
    for observation in facts.coupling_cohesion_observations:
        closure.see_symbol(observation.symbol)
    for api_symbol in facts.api_symbols:
        closure.see_symbol(api_symbol.symbol)
    for risk_observation in facts.risk_observations:
        closure.see_symbol(risk_observation.symbol)
    for adoption in facts.adoption_counts:
        closure.see_endpoint(adoption.scope)
    for surface in facts.security_surfaces:
        closure.files.add(surface.file)
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
        facts.dependency_occurrences,
        "dependency_occurrences.producer_key",
        _dependency_occurrence_key,
    )
    _unique_by_key(
        facts.dependency_cycles,
        "dependency_cycles.modules",
        _dependency_cycle_set_key,
    )
    _unique_by_key(facts.clone_groups, "clone_groups.key", _clone_group_natural_key)
    _unique_by_key(
        facts.dead_code_observations,
        "dead_code_observations.key",
        _dead_code_observation_key,
    )
    _unique_by_key(facts.violations, "violations.natural_key", _violation_natural_key)
    _unique_by_key(
        facts.coupling_cohesion_observations,
        "coupling_cohesion_observations.key",
        lambda row: (canonical_key(row.symbol), row.dimension),
    )
    _unique_by_key(facts.api_symbols, "api_symbols.key", _api_symbol_natural_key)
    _unique_by_key(
        facts.risk_observations,
        "risk_observations.key",
        lambda row: (canonical_key(row.symbol), row.dimension, row.start_line),
    )
    _unique_by_key(
        facts.adoption_counts,
        "adoption_counts.key",
        lambda row: (endpoint_key(row.scope), row.feature),
    )
    _unique_by_key(
        facts.security_surfaces,
        "security_surfaces.key",
        lambda row: (*canonical_key(row.file), row.start_line, row.evidence_symbol),
    )


def _prove_occurrence_relations(facts: AnalysisFacts) -> None:
    """Stage 2-bis: every occurrence is BOUND to a carried relation.

    Evidence without its entity is a dangling row; normalization refuses it
    rather than inventing the relation (it never invents facts).  The
    converse is free: a relation may stand with zero occurrences.
    """
    for occurrence in facts.dependency_occurrences:
        if occurrence.relation not in facts.dependency_relations:
            raise CanonicalModelError(
                "dependency occurrence references a relation the model does "
                f"not carry: {occurrence.relation!r}"
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
    _prove_occurrence_relations(model.facts.analysis)
    _prove_function_roles(model.facts.analysis)
    return replace(
        model,
        files=frozenset(closure.files),
        modules=frozenset(closure.modules),
    )
