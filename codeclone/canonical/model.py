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
:class:`ComparisonFacts` (canonical epoch E2: internal model and store state
until the wire-revision bump) and :class:`EvaluationFacts` (canonical epoch
E3: the same, for the evaluation tier); :class:`CanonicalModel` adds the
identity domains, the scope, and the standalone value sets.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, fields, replace
from itertools import chain, pairwise
from typing import TypeVar

from codeclone.canonical.analysis_rows import (
    COVERAGE_JOIN_INVALID,
    CloneItemRow,
    CohesionHotspotRow,
    ComplexityHotspotRow,
    CouplingHotspotRow,
    CoverageJoinRecord,
    CoverageUnitRow,
    DeadCodeSummaryRecord,
    DeadSymbolGroupRow,
    OverloadedModuleRow,
    StructuralGroupRow,
    SuppressedCloneGroupRow,
    UnreachableStatementRow,
)
from codeclone.canonical.api_identity import signature_variant
from codeclone.canonical.comparison_rows import (
    AVAILABILITY_COMPARED,
    CLONE_NOVELTY_LANES,
    COMPARED_LANES,
    DELTA_FAMILY_TERMS,
    LANE_TRUSTED,
    NOVELTY_FAMILY_ID_PREFIXES,
    NOVELTY_UNAVAILABLE,
    OBSERVATION_LANES,
    BaselineWitnessRecord,
    ComparisonAvailabilityRow,
    DisabledCapabilityRow,
    FindingNoveltyRow,
    LaneTrustRow,
    MetricDeltaRow,
    MetricsBaselineWitnessRecord,
    baseline_identity,
)
from codeclone.canonical.errors import CanonicalModelError
from codeclone.canonical.evaluation_rows import (
    HEALTH_INPUT_LANES,
    EvaluationContractRecord,
    EvaluationRequestRecord,
    FindingEvaluationRow,
    GateOutcomeRecord,
    HealthResultRecord,
    HotlistRow,
    UnitRiskRow,
)
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
    IMPORT_MECHANISMS,
    IMPORT_RESOLUTIONS,
    IMPORT_TYPES,
    LIVE_ROOT_REASONS,
    PRODUCER_EXECUTION_STATES,
    RELATIONSHIP_KINDS,
    RELATIONSHIP_ORIGIN_LANES,
    RELATIONSHIP_RESOLUTION_RULES,
    RISK_DIMENSIONS,
    SECURITY_CLASSIFICATION_MODES,
    SECURITY_EVIDENCE_KINDS,
    SECURITY_LOCATION_SCOPES,
    SECURITY_SOURCE_KINDS,
    SECURITY_SURFACE_CATEGORIES,
    UNRESOLVED_IMPORT_RESOLUTIONS,
    VIOLATION_KINDS,
    AnalysisFile,
    DeadCodeEntity,
    DependencyEndpoint,
    EffectRoot,
    FileId,
    FileLine,
    ImportTarget,
    KnownModule,
    ModuleId,
    ModuleSymbol,
    OpaqueDottedHead,
    OperationRoot,
    ProducerRoot,
    RelationshipTarget,
    ScopeRef,
    SourceLocation,
    SymbolId,
    UnresolvedTarget,
    canonical_key,
    dead_code_entity_key,
    endpoint_key,
    import_target_key,
    relationship_target_key,
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


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportObservationRow:
    """One import the module walk OBSERVED (canonical model revision 2).

    The population the dependency lane deliberately does not carry: that
    lane keeps internal, source-bearing edges so the gate and the SCC pass
    consume one graph (the ratified selection law, ``metrics/dependencies``),
    and this family is a DIFFERENT population contract — every ``ModuleDep``
    the producer serves, external and unresolved targets included.  Measured
    at f117a8ad on this repository: 11 445 served rows, of which 6 491
    ``analyzed``, 4 932 ``external``, 22 ``unresolved_dynamic``; the
    dependency lane carried the 6 491.  The sanction that admitted this
    family forbids widening the dependency families instead.

    Logical key — the WHOLE observation.  The producer keys nothing here:
    ``core/parallelism`` sorts the served rows and never deduplicates them,
    and the row shape is what one import statement asserts, so two equal
    rows would be one statement observed twice — measured 11 445/11 445
    distinct on every field @ f117a8ad, 9/9 on the serving corpus.  A set
    cannot hold two equal rows, and the serving projection compares the
    served MULTISET against the store's so a repeat that appeared would be
    visible rather than absorbed.

    ``target`` is the tagged union decided by the producer's own
    ``resolution`` and checked against the run's registry (the laws below):
    an ``analyzed`` import names a MODULE or FILE the run carries, the two
    ``unresolved_*`` resolutions carry no target and no candidate (the
    producer's own ``ImportObservation`` law, restated at the model so a
    contradicting row is refused rather than stored), and every other
    resolution rides an opaque dotted head — a string outside the registry
    with no right to a MODULE identity.  ``dependency_type`` is the served
    ``import_type`` under the name the dependency families already use for
    the same vocabulary.  ``line`` admits zero for the reason
    ``DependencyOccurrenceRow`` does (a coerced zero is storable and visibly
    zero); ``level`` is the relative-import depth; ``requested_module`` is
    absent on a bare relative import (190 of 11 445 @ f117a8ad).
    """

    source: DependencyEndpoint
    target: ImportTarget
    dependency_type: str
    line: int
    resolution: str
    mechanism: str
    binding: str
    is_lazy: bool
    level: int
    requested_module: str | None
    requested_names: tuple[str, ...]
    candidate_targets: tuple[str, ...]
    inventory_expansion: bool

    def __post_init__(self) -> None:
        _prove_import_vocabularies(self)
        _prove_import_payload(self)
        _prove_import_target_law(self)


def _prove_import_vocabularies(row: ImportObservationRow) -> None:
    """The four closed vocabularies of an import observation."""
    if row.dependency_type not in IMPORT_TYPES:
        raise CanonicalModelError(f"unknown dependency_type: {row.dependency_type!r}")
    if row.resolution not in IMPORT_RESOLUTIONS:
        raise CanonicalModelError(f"unknown import resolution: {row.resolution!r}")
    if row.mechanism not in IMPORT_MECHANISMS:
        raise CanonicalModelError(f"unknown import mechanism: {row.mechanism!r}")
    if row.binding not in DEPENDENCY_BINDINGS:
        raise CanonicalModelError(f"unknown dependency binding: {row.binding!r}")


def _prove_import_payload(row: ImportObservationRow) -> None:
    """The producer's own payload laws: non-negative ints, an absent-or-
    non-empty requested module, sorted names, sorted unique candidates."""
    for name, value in (("line", row.line), ("level", row.level)):
        if isinstance(value, bool) or value < 0:
            raise CanonicalModelError(
                f"import observation {name} must be a non-negative int: {value!r}"
            )
    if row.requested_module is not None and not row.requested_module:
        raise CanonicalModelError(
            "import observation requested_module is absent or non-empty, "
            "never the empty string"
        )
    if list(row.requested_names) != sorted(row.requested_names) or any(
        not name for name in row.requested_names
    ):
        raise CanonicalModelError(
            "import observation requested names must be sorted, non-empty "
            f"strings: {row.requested_names!r}"
        )
    if row.candidate_targets != tuple(sorted(set(row.candidate_targets))) or (
        any(not target for target in row.candidate_targets)
    ):
        raise CanonicalModelError(
            "import candidate targets must be sorted, unique, non-empty "
            f"strings: {row.candidate_targets!r}"
        )


def _prove_import_target_law(row: ImportObservationRow) -> None:
    """The classification decides the variant, and the row may not
    contradict it (the laws in the row's docstring)."""
    unresolved = row.resolution in UNRESOLVED_IMPORT_RESOLUTIONS
    if unresolved != isinstance(row.target, UnresolvedTarget):
        raise CanonicalModelError(
            f"an import classified {row.resolution!r} "
            f"{'carries no' if unresolved else 'carries a'} target; "
            f"the row says otherwise: {row.target!r}"
        )
    if unresolved and row.candidate_targets:
        raise CanonicalModelError("an unresolved import carries no candidate targets")
    if row.resolution == "unresolved_dynamic" and row.mechanism != "dynamic":
        raise CanonicalModelError("only a dynamic load can be unresolved_dynamic")
    if row.resolution == "analyzed":
        if not isinstance(row.target, ModuleId | FileId):
            raise CanonicalModelError(
                "an import classified analyzed names a MODULE or FILE of "
                f"the run, not {row.target!r}"
            )
    elif not unresolved and not isinstance(row.target, OpaqueDottedHead):
        raise CanonicalModelError(
            f"an import classified {row.resolution!r} names a head outside "
            f"the run's registry (an opaque dotted head), not {row.target!r}"
        )


def relationship_resolution_status(target: RelationshipTarget) -> str:
    """The served ``resolution_status``, derived from the target variant.

    The producer sets it by exactly this rule (``_relationship_record``:
    ``"resolved" if target_qualname is not None else "unresolved"``), so a
    stored column would be the same fact twice; the registry declares the
    field a representation projection and this is its one owner.
    """
    return "unresolved" if isinstance(target, UnresolvedTarget) else "resolved"


@dataclass(frozen=True, slots=True, kw_only=True)
class RelationshipObservationRow:
    """One call/reference RECORD of a function (canonical model revision 2).

    The served ``relationship_facts`` slice, which revision 1 could not
    express: ``semantic_edges`` filled two of its eight fields, from a
    different lane, with no way to say "unresolved" — and roughly half of
    the population is unresolved (49 475 of 112 967 records @ f117a8ad on
    this repository; 8 of 17 on the serving corpus).

    Logical key — the observation: ``(source, target, relation_kind,
    origin_lane, line, expression, resolution_rule)``.  ``occurrence_count``
    is payload and the family's honest answer to multiplicity: the producer
    emits one record per call/reference EXPRESSION, so ``f(g(), g())`` is
    two identical records on one line, and a set-valued family would
    silently collapse them — measured @ f117a8ad: 112 967 records, 111 587
    distinct on every field, 1 342 groups repeated on one line (the largest
    three times).  The count is the number of records the producer emitted for the
    observation, so the served tuple is reconstructible exactly: expand each
    row ``occurrence_count`` times and sort by the producer's own key.  An
    artificial per-line ordinal was rejected: the producer records no such
    discriminator, and an identity nobody asserted is a guessed identity.

    ``target`` is the tagged union (:data:`RelationshipTarget`); the served
    ``resolution_status`` is DERIVED from it (:func:`relationship_resolution_status`)
    and the served ``path`` from the source SYMBOL's file plus the serving
    root — both declared representation projections, never stored.  A
    ``reference`` record always names a target: the producer emits one only
    once it resolved the expression, and an unresolved reference row would
    assert an observation the producer never made.  ``line`` is positive
    (the producer clamps ``max(1, lineno)``); ``expression`` is the unparsed
    source text and is absent, never empty (``ast.unparse(...) or None``);
    ``resolution_rule`` is the producer's closed mechanism vocabulary.
    """

    source: SymbolId
    target: RelationshipTarget
    relation_kind: str
    origin_lane: str
    line: int
    expression: str | None
    resolution_rule: str | None
    occurrence_count: int

    def __post_init__(self) -> None:
        if self.relation_kind not in RELATIONSHIP_KINDS:
            raise CanonicalModelError(
                f"unknown relationship kind: {self.relation_kind!r}"
            )
        if self.origin_lane not in RELATIONSHIP_ORIGIN_LANES:
            raise CanonicalModelError(
                f"unknown relationship origin lane: {self.origin_lane!r}"
            )
        if isinstance(self.line, bool) or self.line < 1:
            raise CanonicalModelError(
                f"relationship line must be a positive int: {self.line!r}"
            )
        if isinstance(self.occurrence_count, bool) or self.occurrence_count < 1:
            raise CanonicalModelError(
                "relationship occurrence count must be a positive int: "
                f"{self.occurrence_count!r}"
            )
        if self.expression is not None and not self.expression:
            raise CanonicalModelError(
                "relationship expression is absent or non-empty, never the empty string"
            )
        if self.resolution_rule is not None and (
            self.resolution_rule not in RELATIONSHIP_RESOLUTION_RULES
        ):
            raise CanonicalModelError(
                f"unknown relationship resolution rule: {self.resolution_rule!r}"
            )
        if self.relation_kind == "reference" and isinstance(
            self.target, UnresolvedTarget
        ):
            raise CanonicalModelError(
                "a reference record always names its target (the producer "
                "emits a reference only once it resolved the expression)"
            )


# ``CloneItemRow`` lives in ``codeclone.canonical.analysis_rows`` since E1:
# the suppressed clone family shares the member shape, and one row type
# keeps the member law in one spelling.  The name stays importable here.


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
class UnitSpanRow:
    """The DECLARATION entity: which unit exists, and what source range it
    occupies.  Logical key: ``(SYMBOL, start_line)``.

    This family is the missing half of a split this model already ratified
    once for dependencies (ruling 2026-08-24 §2, relation vs occurrence).
    The producer's ``complexity`` row is TWO objects glued together: the
    declaration — ``(SYMBOL, start_line, end_line)``, an identity/extent
    fact — and the risk OBSERVATION about it, ``(SYMBOL, dimension,
    start_line) -> numerator``.  Only the second was carried, so the span
    was dropped and the served ``unit_inventory`` slice could not be
    expressed from the store.

    Why the span is NOT a column of :class:`RiskObservationRow`, measured
    rather than argued: ``dimension`` sits in that family's key, so one
    declaration owns one row PER measured dimension — 6 675 of 15 934
    declarations carry two (@ 4512acf0, 2026-09-03, a dated observation).
    Storing the span there would put one fact in two places, and worse,
    ``_unique_by_key`` could not police it: two rows of one declaration
    differing only in ``dimension`` may carry CONTRADICTING spans and the
    prover never meets them, because they do not share a key.  The pin for
    exactly that is ``tests/test_unit_span_owner.py``, which drives the
    real prover on both key spellings.

    ``start_line`` is a key component for the same measured reason it is
    one on the risk family: different declarations share one qualname
    (``@overload`` families, property/setter pairs), so the bare SYMBOL is
    not total.  ``end_line`` is payload and is refused below its start: a
    span is a range, and a row that admitted ``end < start`` would let the
    store answer with a value the source never had.  Both floors are
    positive — a zero site would spell "no declaration" as a declaration,
    and the producer never emits one (``analysis/units.py`` carries
    ``ast`` positions, and a unit that cannot name its site is refused
    upstream by the risk lane already).

    Not to be confused with the :class:`~codeclone.canonical.identity.FileLine`
    law: a semantic EVENT is one line and never a span, so a stored
    ``end_line`` there would be the same fact twice.  A parsed declaration
    genuinely has two ends (``ast.AST.end_lineno``), and that is the
    difference between evidence and extent.
    """

    symbol: SymbolId
    start_line: int
    end_line: int

    def __post_init__(self) -> None:
        if isinstance(self.start_line, bool) or self.start_line < 1:
            raise CanonicalModelError(
                f"unit span start must be a positive int: {self.start_line!r}"
            )
        if isinstance(self.end_line, bool) or self.end_line < self.start_line:
            raise CanonicalModelError(
                f"unit span end must be an int not before its start: {self.end_line!r}"
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

    Entity consistency: this family declares NOTHING to
    ``_prove_entity_consistency``, and the emptiness is measured rather
    than forgotten.  The record key ``(SYMBOL, dimension, start_line)`` IS
    ``(declaration, dimension)``, so the only field left outside it is
    ``numerator`` — per-dimension by construction and therefore never
    entity-invariant.  6 682 of 15 949 declarations carry two rows @
    eec81fdb (9 267 carry one: the producer drops a zero ``nesting_depth``)
    and nothing those pairs carry can contradict, so a rule here would be a
    guard no input can trip.  The day a source span, or any other
    declaration-wide fact, becomes a COLUMN on this row, that statement
    stops holding and the field must be declared: two rows of ONE
    declaration differing only in ``dimension`` do not share a key, so
    ``_unique_by_key`` would never compare their spans — it would accept
    ``end_line`` 42 and 999 for one declaration in silence.
    ``test_canonical_roundtrip`` executes the field list so the day cannot
    pass unnoticed.
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

    Entity consistency — the family law this row owns: the logical key
    names the RECORD, but ``source_kind`` names the FILE.
    ``paths.classify_source_kind`` reads the path and nothing else, so
    every row of one file carries the same verdict; the key cannot prove
    it, because two rows of one file differ on ``start_line`` or
    ``evidence_symbol`` and are therefore two legitimate records that
    ``_unique_by_key`` never compares.  ``_prove_entity_consistency``
    proves it instead — 112 of 220 files carry more than one row (342 of
    450 rows @ eec81fdb), none disagreeing.

    Left FREE, each for a measured reason, because refusing a legitimate
    record set would be the worse defect:

    * ``end_line`` — the span of the OBSERVED node, not of the entity:
      ``semantics/events.py:_emit_security`` takes it from
      ``ast_node_end_line(node)``, so the s5 ``eval(compile(...))`` datum
      can legitimately end two rows of one start line on two different
      lines.  The maintainer's example field is exactly the one that must
      NOT be constrained here.
    * ``qualname`` and ``location_scope`` — the hosting unit, taken from
      the visitor's scope at the observed node.  Site-invariant only if one
      start line cannot host two scopes, and this repository carries no
      proof of that (a lambda body opens one on its own line), so they wait
      for a measurement rather than ride on 4 agreeing sites.
    * ``category``, ``capability``, ``evidence_kind``,
      ``classification_mode`` — verdicts about the EVIDENCE, which is what
      the key's third component distinguishes; ``eval`` and ``compile`` on
      one line legitimately carry two capabilities.
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

    ``files_observed`` is ONE number on purpose: how many of the found files
    this run read, parsed fresh or served off the cache alike.  How those
    split between the two is execution provenance -- the report keeps it
    (``inventory.files.analyzed`` / ``.cached``) and its own identity law
    refuses to let it reach a digest -- and a snapshot that stored the split
    gave one tree two store runs, a cold one and a warm one, under one report
    identity (DET-01, measured 2026-09-25).
    """

    classes: int
    files_found: int
    files_observed: int
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
    # Canonical model revision 2: the two served observation families.  A
    # legacy report document carries neither (the surface serves them from
    # the parent's memory), so the ingest oracle answers them empty and the
    # producer-native snapshot is their one source.
    import_observations: frozenset[ImportObservationRow] = field(
        default_factory=frozenset
    )
    relationship_observations: frozenset[RelationshipObservationRow] = field(
        default_factory=frozenset
    )
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
    unit_spans: frozenset[UnitSpanRow] = field(default_factory=frozenset)
    # Canonical epoch E1 (2026-09-25): the published finding groups, the
    # overloaded-module facts and the external coverage join, each the
    # population the document publishes (``codeclone.canonical.analysis_rows``).
    suppressed_clone_groups: frozenset[SuppressedCloneGroupRow] = field(
        default_factory=frozenset
    )
    structural_groups: frozenset[StructuralGroupRow] = field(default_factory=frozenset)
    dead_symbol_groups: frozenset[DeadSymbolGroupRow] = field(default_factory=frozenset)
    unreachable_statement_groups: frozenset[UnreachableStatementRow] = field(
        default_factory=frozenset
    )
    complexity_hotspots: frozenset[ComplexityHotspotRow] = field(
        default_factory=frozenset
    )
    coupling_hotspots: frozenset[CouplingHotspotRow] = field(default_factory=frozenset)
    cohesion_hotspots: frozenset[CohesionHotspotRow] = field(default_factory=frozenset)
    overloaded_modules: frozenset[OverloadedModuleRow] = field(
        default_factory=frozenset
    )
    coverage_units: frozenset[CoverageUnitRow] = field(default_factory=frozenset)
    # F9: one record per analysis snapshot; None is the absent record —
    # never an all-zero fake (zero is measured in this family).
    run_scalars: RunScalars | None = None
    # RULING-2026-08-31 §3: the execution-population singleton; None is
    # the absent record — a legacy document that never declared what it
    # computed stays honestly unwitnessed, never fabricated.
    analysis_population: AnalysisPopulation | None = None
    # E1: the coverage join's own record (None: the run was handed no
    # coverage report) and the dead-code population counters (None: the
    # dead-code lane never ran, the clones-only mode).
    coverage_join: CoverageJoinRecord | None = None
    dead_code_summary: DeadCodeSummaryRecord | None = None


@dataclass(frozen=True, slots=True)
class ComparisonFacts:
    """The comparison-tier fact house: this run compared against ONE baseline.

    Canonical epoch E2 (2026-09-26, ruling of the same day): the residents
    the ratified §4 grammar names — baseline witnesses, per-lane trust and
    availability, disabled capabilities, novelty annotations, deltas — are
    carried here and stored as rows, and they are NOT emitted: the wire and
    the report document of this revision carry no comparison section, and
    the section joins with its own wire-revision bump.  Emitting it earlier
    would make a revision-1 artifact carry semantics its revision does not
    declare.  A model decoded from the wire therefore carries this house
    EMPTY, which reads "not witnessed by this artifact" — ``baseline_witness``
    is ``None`` and the model refuses every other comparison row without it —
    never "compared, nothing found".

    The two witnesses are records (one per run, ``None`` is the typed
    absence) and always exist on a witnessed run; the delta families exist
    whole exactly when their comparison ran.  The rest are keyed row sets.
    The laws that bind them to one another are proved on every normalization
    (:func:`_prove_comparison_facts`).

    Every row of this house is a MEMBER of the store run (decision D-10,
    2026-09-28): the store run id is the digest of what the run states, and a
    comparison is stated against one container, so one analysis compared
    against two baselines is two store runs over one scope receipt.
    """

    baseline_witness: BaselineWitnessRecord | None = None
    metrics_baseline_witness: MetricsBaselineWitnessRecord | None = None
    lane_trust: frozenset[LaneTrustRow] = field(default_factory=frozenset)
    comparison_availability: frozenset[ComparisonAvailabilityRow] = field(
        default_factory=frozenset
    )
    disabled_capabilities: frozenset[DisabledCapabilityRow] = field(
        default_factory=frozenset
    )
    clone_novelty: frozenset[FindingNoveltyRow] = field(default_factory=frozenset)
    complexity_novelty: frozenset[FindingNoveltyRow] = field(default_factory=frozenset)
    coupling_novelty: frozenset[FindingNoveltyRow] = field(default_factory=frozenset)
    dependency_cycle_novelty: frozenset[FindingNoveltyRow] = field(
        default_factory=frozenset
    )
    dead_symbol_novelty: frozenset[FindingNoveltyRow] = field(default_factory=frozenset)
    adoption_delta: frozenset[MetricDeltaRow] = field(default_factory=frozenset)
    api_surface_delta: frozenset[MetricDeltaRow] = field(default_factory=frozenset)
    # Canonical epoch E3: the health score's delta, an annotation of the
    # evaluation house's ``health_result`` (proved in ``_normalized``).
    health_delta: frozenset[MetricDeltaRow] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class EvaluationFacts:
    """The evaluation-tier fact house: what this run concluded under the
    evaluation it was given.

    Canonical epoch E3 (2026-09-27, the E2 ruling applied to the next tier):
    the residents the ratified §4 grammar names — the realized evaluation
    contract, the request, the gate outcome, the health verdict, the band of
    every measured unit, the verdict on every finding and the document's
    selections — are carried here and stored as rows, and NOT emitted: the
    wire of this revision carries no evaluation section.  A model decoded
    from the wire carries this house EMPTY, which reads "not witnessed by this
    artifact" — the three evaluation records are ``None`` and the model
    refuses every other evaluation row without them — never "evaluated,
    nothing concluded".

    The four records are one per evaluated run (``None`` is the typed
    absence; ``health_result`` is absent exactly when the metrics never ran);
    the rest are keyed row sets.  The laws binding them are proved on every
    normalization (:func:`_prove_evaluation_facts`).

    Every row of this house is a MEMBER of the store run, the gate request
    included (decision D-10, 2026-09-28: the request is a member of the run,
    not a key beside it): a run's evaluation is what it concluded under ITS
    request, so one analysis gated under two requests is two store runs over
    one scope receipt and two report identities
    (``tests/test_run_store_identity_bridge.py`` holds the transition).
    """

    evaluation_contract: EvaluationContractRecord | None = None
    evaluation_request: EvaluationRequestRecord | None = None
    gate_outcome: GateOutcomeRecord | None = None
    health_result: HealthResultRecord | None = None
    finding_evaluation: frozenset[FindingEvaluationRow] = field(
        default_factory=frozenset
    )
    unit_risk_result: frozenset[UnitRiskRow] = field(default_factory=frozenset)
    hotlist_selection: frozenset[HotlistRow] = field(default_factory=frozenset)


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


def _prove_entity_invariants(
    rows: Iterable[_RowT],
    entity_name: str,
    entity_of: Callable[[_RowT], object],
    invariants: tuple[tuple[str, Callable[[_RowT], str | int]], ...],
) -> None:
    """Refuse two records of ONE entity that disagree ABOUT that entity.

    ``_unique_by_key`` proves RECORD identity: one logical key names at
    most one fact.  It is blind BY CONSTRUCTION to a contradiction that
    crosses a key component — two rows whose keys differ are two
    legitimate records, so the prover never compares them, however
    impossible their contents are together.  Measured @ eec81fdb on this
    repository: 112 of 220 files carry more than one ``security_surfaces``
    row (342 of 450 rows), and every one of those rows repeats a verdict
    that belongs to the FILE and not to the row.

    So a second, weaker identity is proved here: records sharing an ENTITY
    must agree about the fields that describe that entity.  WHICH fields
    those are is a family law, decided by the family's semantic owner and
    stated on its row class — never a generic rule that teaches the key
    prover to ignore part of a key, because a component ignored for one
    family would stop naming the record on every other.

    A field that legitimately varies between the records of one entity is
    NOT entity-invariant and must stay off the list: refusing a legitimate
    record set is a worse defect than the hole it closes.  Each family's
    row class states what it left free, and why.
    """
    observed: dict[object, dict[str, set[str | int]]] = {}
    for row in rows:
        entity = entity_of(row)
        fields = observed.get(entity)
        if fields is None:
            fields = {name: set() for name, _ in invariants}
            observed[entity] = fields
        for name, read in invariants:
            fields[name].add(read(row))
    # Sorted: every family reaching this prover is a frozenset, so an
    # unsorted walk would make WHICH contradiction is reported depend on
    # hash order — a refusal naming a different row per process is not a
    # reproducible receipt.
    for entity, fields in sorted(observed.items(), key=lambda item: repr(item[0])):
        for name, _ in invariants:
            values = fields[name]
            if len(values) > 1:
                raise CanonicalModelError(
                    f"two facts of one {entity_name}={entity!r} disagree on "
                    f"the entity-invariant field {name!r}: {sorted(values)!r}"
                )


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


def _import_observation_key(row: ImportObservationRow) -> tuple[object, ...]:
    # The whole observation is the key (see the row class): every field
    # enters, in one fixed order, so two rows collide only when they say
    # exactly the same thing.
    return (
        endpoint_key(row.source),
        import_target_key(row.target),
        row.dependency_type,
        row.line,
        row.resolution,
        row.mechanism,
        row.binding,
        row.is_lazy,
        row.level,
        row.requested_module or "",
        row.requested_names,
        row.candidate_targets,
        row.inventory_expansion,
    )


def _relationship_observation_key(
    row: RelationshipObservationRow,
) -> tuple[object, ...]:
    # The observation, without its multiplicity: ``occurrence_count`` is the
    # one payload field, so two rows of one observation differing only in
    # their count collide here and are refused.
    return (
        canonical_key(row.source),
        relationship_target_key(row.target),
        row.relation_kind,
        row.origin_lane,
        row.line,
        row.expression or "",
        row.resolution_rule or "",
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

    def see_import_target(self, target: ImportTarget) -> None:
        # The opaque head and the nullary variant have no domain to admit —
        # that is what each of them asserts.
        if isinstance(target, ModuleId | FileId):
            self.see_endpoint(target)

    def see_relationship_target(self, target: RelationshipTarget) -> None:
        if isinstance(target, SymbolId):
            self.see_symbol(target)

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


#: The families whose identity contribution is exactly ONE ``symbol`` column.
#: Named as a union rather than left to inference: a chain over heterogeneous
#: row types widens to ``object``, and reaching ``.symbol`` off ``object`` is
#: the untyped hole this repository refuses.
_SymbolCarrier = (
    SinkRoleRow
    | CouplingCohesionRow
    | ApiSymbolRow
    | RiskObservationRow
    | UnitSpanRow
    | DeadSymbolGroupRow
    | UnreachableStatementRow
    | ComplexityHotspotRow
    | CouplingHotspotRow
    | CohesionHotspotRow
    | CoverageUnitRow
)


def _close_epoch_one_domains(closure: _DomainClosure, facts: AnalysisFacts) -> None:
    """Stage 1 for the E1 families that contribute identity through
    something other than one ``symbol`` column: the member sites of the
    suppressed and structural groups, and the FILE of an overloaded module.
    (The six site-keyed families ride the shared ``symbol`` loop below.)"""
    for suppressed_group in facts.suppressed_clone_groups:
        for item in suppressed_group.items:
            closure.see_symbol(item.symbol)
    for structural_group in facts.structural_groups:
        for site in structural_group.occurrences:
            closure.see_symbol(site.symbol)
    for overloaded in facts.overloaded_modules:
        closure.files.add(overloaded.file)


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
    for import_observation in facts.import_observations:
        closure.see_endpoint(import_observation.source)
        closure.see_import_target(import_observation.target)
    for relationship in facts.relationship_observations:
        closure.see_symbol(relationship.source)
        closure.see_relationship_target(relationship.target)
    for group in facts.clone_groups:
        for item in group.items:
            closure.see_symbol(item.symbol)
    _close_epoch_one_domains(closure, facts)
    for dead_observation in facts.dead_code_observations:
        closure.see_dead_code_entity(dead_observation.entity)
    for violation in facts.violations:
        closure.see_violation(violation)
    # Eleven families contribute identity through ONE ``symbol`` column and
    # nothing else, so they share one loop.  Spelling them as identical
    # loops made this function's branch count grow with the family list --
    # measured when ``unit_spans`` landed and pushed it over the complexity
    # threshold -- while the closure it computes never differed.
    symbol_rows: Iterable[_SymbolCarrier] = chain(
        facts.sink_roles,
        facts.coupling_cohesion_observations,
        facts.api_symbols,
        facts.risk_observations,
        facts.unit_spans,
        facts.dead_symbol_groups,
        facts.unreachable_statement_groups,
        facts.complexity_hotspots,
        facts.coupling_hotspots,
        facts.cohesion_hotspots,
        facts.coverage_units,
    )
    for symbol_row in symbol_rows:
        closure.see_symbol(symbol_row.symbol)
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
    _unique_by_key(
        facts.import_observations,
        "import_observations.observation",
        _import_observation_key,
    )
    _unique_by_key(
        facts.relationship_observations,
        "relationship_observations.observation",
        _relationship_observation_key,
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
    # The declaration key carries NO dimension: that is the whole point of
    # the family.  Under the risk key two rows of one declaration differing
    # only in ``dimension`` could carry contradicting spans and never meet
    # this prover; under this key they collide and are refused.
    _unique_by_key(
        facts.unit_spans,
        "unit_spans.key",
        lambda row: (canonical_key(row.symbol), row.start_line),
    )
    _prove_epoch_one_keys(facts)


#: The E1 families keyed by the declaration site ``(SYMBOL, start_line)``:
#: the ``unit_spans`` key, for the same measured reason — different
#: declarations share one qualname, and the document's own identities
#: (``dead_code:{qualname}``, ``design:{category}:{qualname}``) are blind
#: to them.
_SiteKeyed = (
    DeadSymbolGroupRow
    | UnreachableStatementRow
    | ComplexityHotspotRow
    | CouplingHotspotRow
    | CohesionHotspotRow
    | CoverageUnitRow
)


def _site_key(row: _SiteKeyed) -> tuple[object, ...]:
    return (canonical_key(row.symbol), row.start_line)


def _prove_epoch_one_keys(facts: AnalysisFacts) -> None:
    """Stage 2 for the E1 families: the producer's own group keys, the
    declaration-site key, and the FILE key of the overloaded modules."""
    _unique_by_key(
        facts.suppressed_clone_groups,
        "suppressed_clone_groups.key",
        lambda row: (row.clone_kind.encode("utf-8"), row.group_key.encode("utf-8")),
    )
    _unique_by_key(
        facts.structural_groups,
        "structural_groups.key",
        lambda row: (
            row.finding_kind.encode("utf-8"),
            row.finding_key.encode("utf-8"),
        ),
    )
    # Six call sites rather than a loop over a table: the roundtrip pin
    # reads every ``_unique_by_key`` site off the fact house by name, so
    # the family each key proves stays visible to it.
    _unique_by_key(facts.dead_symbol_groups, "dead_symbol_groups.key", _site_key)
    _unique_by_key(
        facts.unreachable_statement_groups,
        "unreachable_statement_groups.key",
        _site_key,
    )
    _unique_by_key(facts.complexity_hotspots, "complexity_hotspots.key", _site_key)
    _unique_by_key(facts.coupling_hotspots, "coupling_hotspots.key", _site_key)
    _unique_by_key(facts.cohesion_hotspots, "cohesion_hotspots.key", _site_key)
    _unique_by_key(facts.coverage_units, "coverage_units.key", _site_key)
    _unique_by_key(
        facts.overloaded_modules,
        "overloaded_modules.file",
        lambda row: canonical_key(row.file),
    )


def _prove_coverage_join(facts: AnalysisFacts) -> None:
    """Stage 2-quater: coverage units belong to a readable coverage join.

    A unit row without the join record would be an observation of a report
    the run never had, and a unit under an ``invalid`` join would be a
    measurement the producer says it could not make — both are refused,
    never dropped.  The converse is legitimate: a readable report may map
    no unit at all.
    """
    if not facts.coverage_units:
        return
    record = facts.coverage_join
    if record is None:
        raise CanonicalModelError(
            "coverage units carried without a coverage join record: the run "
            "was handed no coverage report to measure them from"
        )
    if record.status == COVERAGE_JOIN_INVALID:
        raise CanonicalModelError(
            "coverage units carried under an invalid coverage join: the "
            "producer measured nothing from an unreadable report"
        )


def _prove_entity_consistency(facts: AnalysisFacts) -> None:
    """Stage 2-ter: records of one entity agree ABOUT that entity (S5.B).

    One declaration per family, and the declaration is the family's own
    law — see each row class for the reasoning and for the fields it
    deliberately leaves free.  A family ABSENT from this table carries no
    entity-invariant field outside its logical key, and that is a measured
    statement rather than an omission: ``RiskObservationRow`` is the family
    whose key already IS ``(declaration, dimension)``, so nothing its two
    rows carry can contradict, and ``test_canonical_roundtrip`` executes
    that emptiness so it cannot rot into an unguarded span column.
    """
    _prove_entity_invariants(
        facts.security_surfaces,
        "security_surfaces.file",
        lambda row: canonical_key(row.file),
        (("source_kind", lambda row: row.source_kind),),
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


#: A comparison row or record of the comparison house (everything but the
#: witness itself): each one names the baseline it was compared against.
_ComparedRow = (
    MetricsBaselineWitnessRecord
    | LaneTrustRow
    | ComparisonAvailabilityRow
    | DisabledCapabilityRow
    | FindingNoveltyRow
    | MetricDeltaRow
)


def novelty_families(
    comparison: ComparisonFacts,
) -> tuple[tuple[str, frozenset[FindingNoveltyRow]], ...]:
    """The five novelty families by grammar name, in name order — the one
    enumeration the model laws, the store walk and the projections share."""
    return (
        ("clone_novelty", comparison.clone_novelty),
        ("complexity_novelty", comparison.complexity_novelty),
        ("coupling_novelty", comparison.coupling_novelty),
        ("dead_symbol_novelty", comparison.dead_symbol_novelty),
        ("dependency_cycle_novelty", comparison.dependency_cycle_novelty),
    )


def _compared_rows(comparison: ComparisonFacts) -> Iterable[_ComparedRow]:
    metrics_witness = comparison.metrics_baseline_witness
    rows: Iterable[_ComparedRow] = chain(
        () if metrics_witness is None else (metrics_witness,),
        comparison.lane_trust,
        comparison.comparison_availability,
        comparison.disabled_capabilities,
        comparison.adoption_delta,
        comparison.api_surface_delta,
        comparison.health_delta,
        *(rows for _family, rows in novelty_families(comparison)),
    )
    return rows


def _prove_comparison_keys(comparison: ComparisonFacts) -> None:
    """Stage 2 for the comparison house: one row per lane, one novelty per
    published finding, each novelty filed under its own subject family."""
    _unique_by_key(comparison.lane_trust, "lane_trust.lane", lambda row: row.lane)
    _unique_by_key(
        comparison.comparison_availability,
        "comparison_availability.lane",
        lambda row: row.lane,
    )
    _unique_by_key(
        comparison.disabled_capabilities,
        "disabled_capabilities.lane",
        lambda row: row.lane,
    )
    _unique_by_key(
        comparison.adoption_delta, "adoption_delta.delta", lambda row: row.delta
    )
    _unique_by_key(
        comparison.api_surface_delta, "api_surface_delta.delta", lambda row: row.delta
    )
    _unique_by_key(comparison.health_delta, "health_delta.delta", lambda row: row.delta)
    # Five call sites rather than a loop, for the reason the E1 site-keyed
    # families give: the roundtrip pin reads every ``_unique_by_key`` site
    # off the house by name.
    _unique_by_key(
        comparison.clone_novelty, "clone_novelty.id", lambda row: row.finding_id
    )
    _unique_by_key(
        comparison.complexity_novelty,
        "complexity_novelty.id",
        lambda row: row.finding_id,
    )
    _unique_by_key(
        comparison.coupling_novelty, "coupling_novelty.id", lambda row: row.finding_id
    )
    _unique_by_key(
        comparison.dead_symbol_novelty,
        "dead_symbol_novelty.id",
        lambda row: row.finding_id,
    )
    _unique_by_key(
        comparison.dependency_cycle_novelty,
        "dependency_cycle_novelty.id",
        lambda row: row.finding_id,
    )
    for family, rows in novelty_families(comparison):
        prefixes = NOVELTY_FAMILY_ID_PREFIXES[family]
        for row in rows:
            if not row.finding_id.startswith(prefixes) or row.finding_id in prefixes:
                raise CanonicalModelError(
                    f"{family} carries {row.finding_id!r}, which is not a "
                    f"finding of its subject family ({', '.join(prefixes)})"
                )


def _prove_one_baseline(comparison: ComparisonFacts) -> None:
    """Every comparison fact of a run names the ONE baseline its witness
    names — and none exists without the witness.

    A novelty with no witness would be a verdict about a comparison nobody
    can name; a row naming another container would put two baselines under
    one run.  Both are refused, never dropped.
    """
    witness = comparison.baseline_witness
    rows = list(_compared_rows(comparison))
    if witness is None:
        if rows:
            raise CanonicalModelError(
                "comparison facts carried without the baseline witness: "
                "nothing says what they were compared against"
            )
        return
    if comparison.metrics_baseline_witness is None:
        raise CanonicalModelError(
            "a witnessed comparison names the clone baseline but not the "
            "metrics baseline read from the same container"
        )
    identity = baseline_identity(witness)
    for row in rows:
        if baseline_identity(row) != identity:
            raise CanonicalModelError(
                f"{type(row).__name__} names the baseline "
                f"{baseline_identity(row)!r}, the run's witness names "
                f"{identity!r}: one run is compared against one baseline"
            )


def _prove_lane_partition(comparison: ComparisonFacts) -> None:
    """The four availability states partition the lanes.

    Every observation lane is either trust-assessed or a disabled
    capability, never both; every lane a comparison has a term for carries
    EXACTLY ONE of an availability row (three words) and a disabled row (the
    fourth state) — the four states are never folded into three, and no lane
    is left without one.
    """
    if comparison.baseline_witness is None:
        return
    trusted = {row.lane for row in comparison.lane_trust}
    disabled = {row.lane for row in comparison.disabled_capabilities}
    both = sorted(trusted & disabled)
    if both:
        raise CanonicalModelError(
            f"lanes {both!r} are both trust-assessed and disabled"
        )
    missing = sorted(set(OBSERVATION_LANES) - trusted - disabled)
    if missing:
        raise CanonicalModelError(
            f"lanes {missing!r} are neither trust-assessed nor disabled"
        )
    available = {row.lane for row in comparison.comparison_availability}
    for lane in COMPARED_LANES:
        if (lane in available) == (lane in disabled):
            raise CanonicalModelError(
                f"lane {lane!r} must carry exactly one of an availability "
                "row and a disabled capability"
            )


def _prove_comparison_results(comparison: ComparisonFacts) -> None:
    """A result exists exactly when its comparison ran.

    A delta family is present — every one of its terms, and none of another
    family's — iff its lane is ``compared`` (zero is admissible only as a
    measured result); a clone finding is ``new`` or ``known`` only under a
    compared clone lane.
    """
    availability = {
        row.lane: row.availability for row in comparison.comparison_availability
    }
    _prove_delta_families(comparison, availability)
    _prove_health_delta(comparison)
    _prove_clone_verdicts(comparison, availability)


def _prove_delta_families(
    comparison: ComparisonFacts, availability: dict[str, str]
) -> None:
    for family, lane, rows in (
        ("adoption_delta", "adoption_counts", comparison.adoption_delta),
        ("api_surface_delta", "api_surface", comparison.api_surface_delta),
    ):
        terms = {row.delta for row in rows}
        compared = availability.get(lane) == AVAILABILITY_COMPARED
        if compared != bool(terms):
            raise CanonicalModelError(
                f"the {lane} delta is {'present' if terms else 'absent'} while "
                f"the lane is {availability.get(lane, 'disabled')!r}"
            )
        if terms and terms != set(DELTA_FAMILY_TERMS[family]):
            raise CanonicalModelError(
                f"{family} states {sorted(terms)!r}, not exactly its terms "
                f"{list(DELTA_FAMILY_TERMS[family])!r}"
            )


def _prove_health_delta(comparison: ComparisonFacts) -> None:
    """The health delta (canonical epoch E3) states exactly its one term, and
    only when no health input lane the container was assessed for is
    untrusted: a delta against a lane the comparison could not vouch for
    compares the run with nothing.  A health input lane the run did not
    enable is not trust-assessed and does not refuse the delta — the
    document states it that way (the enrichment reads the container's trust
    vector), and the store states what the document states."""
    terms = {row.delta for row in comparison.health_delta}
    if not terms:
        return
    if terms != set(DELTA_FAMILY_TERMS["health_delta"]):
        raise CanonicalModelError(
            f"health_delta states {sorted(terms)!r}, not exactly its term"
        )
    untrusted = sorted(
        row.lane
        for row in comparison.lane_trust
        if row.lane in HEALTH_INPUT_LANES and row.status != LANE_TRUSTED
    )
    if untrusted:
        raise CanonicalModelError(
            f"a health delta is stated while the health input lanes "
            f"{untrusted!r} are untrusted"
        )


def _prove_clone_verdicts(
    comparison: ComparisonFacts, availability: dict[str, str]
) -> None:
    for row in comparison.clone_novelty:
        if row.novelty == NOVELTY_UNAVAILABLE:
            continue
        lane = next(
            lane
            for prefix, lane in CLONE_NOVELTY_LANES.items()
            if row.finding_id.startswith(prefix)
        )
        if availability.get(lane) != AVAILABILITY_COMPARED:
            raise CanonicalModelError(
                f"clone finding {row.finding_id!r} is {row.novelty!r} while "
                f"{lane} is {availability.get(lane, 'disabled')!r}"
            )


def _prove_comparison_facts(comparison: ComparisonFacts) -> None:
    """Stage 4: the comparison house's keys and cross-family laws."""
    _prove_comparison_keys(comparison)
    _prove_one_baseline(comparison)
    _prove_lane_partition(comparison)
    _prove_comparison_results(comparison)


def _prove_evaluation_keys(evaluation: EvaluationFacts) -> None:
    """Stage 2 for the evaluation house: one verdict per finding, one band
    per measured unit, one finding per rank and one rank per finding of each
    selection."""
    _unique_by_key(
        evaluation.finding_evaluation,
        "finding_evaluation.id",
        lambda row: row.finding_id,
    )
    _unique_by_key(
        evaluation.unit_risk_result,
        "unit_risk_result.key",
        lambda row: (row.dimension, canonical_key(row.symbol), row.start_line),
    )
    _unique_by_key(
        evaluation.hotlist_selection,
        "hotlist_selection.rank",
        lambda row: (row.hotlist, row.rank),
    )
    _unique_by_key(
        evaluation.hotlist_selection,
        "hotlist_selection.id",
        lambda row: (row.hotlist, row.finding_id),
    )


def _prove_one_request(evaluation: EvaluationFacts) -> None:
    """The evaluation is witnessed whole or not at all, and one run is
    evaluated under ONE request.

    The contract, the request and the outcome are one document section
    (``evaluation`` / ``contracts.evaluation``): a run carries all three or
    none, every other evaluation fact needs them, and all three name the
    same request digest — a verdict under one policy beside a contract of
    another would be two evaluations under one run.
    """
    records = (
        evaluation.evaluation_contract,
        evaluation.evaluation_request,
        evaluation.gate_outcome,
    )
    witnessed = [record is not None for record in records]
    if any(witnessed) and not all(witnessed):
        raise CanonicalModelError(
            "the evaluation is witnessed in part: the contract, the request and "
            "the gate outcome are one section"
        )
    contract, request, outcome = records
    if contract is None or request is None or outcome is None:
        if evaluation != EvaluationFacts():
            raise CanonicalModelError(
                "evaluation facts carried without the evaluation witness: "
                "nothing says what they were evaluated under"
            )
        return
    digests = {
        contract.gate_thresholds_digest,
        request.gate_thresholds_digest,
        outcome.gate_thresholds_digest,
    }
    if len(digests) != 1:
        raise CanonicalModelError(
            f"one run is evaluated under one request, not {sorted(digests)!r}"
        )


def _prove_health_dating(evaluation: EvaluationFacts) -> None:
    """A health verdict is dated by the contract it was computed under: the
    contract carries the health parameters exactly when a verdict exists, and
    the verdict's revision and manifest are the contract's."""
    contract = evaluation.evaluation_contract
    health = evaluation.health_result
    if contract is None:
        return
    if (health is None) != (not contract.health_params):
        raise CanonicalModelError(
            "the health parameters ride the contract exactly when a health "
            "verdict exists"
        )
    if health is not None and (
        health.health_algorithm_revision,
        health.health_input_manifest_version,
    ) != (contract.health_algorithm_revision, contract.health_input_manifest_version):
        raise CanonicalModelError(
            "the health verdict is dated by another contract than the run's"
        )


def _prove_selections(evaluation: EvaluationFacts, files: frozenset[FileId]) -> None:
    """Every selection ranks from one without a gap, and every band names a
    unit of a file this run carries — the evaluation never widens the
    identity domains the wire addresses."""
    ranks: dict[str, list[int]] = {}
    for row in evaluation.hotlist_selection:
        ranks.setdefault(row.hotlist, []).append(row.rank)
    for hotlist, positions in sorted(ranks.items()):
        if sorted(positions) != list(range(1, len(positions) + 1)):
            raise CanonicalModelError(f"the {hotlist} selection skips a rank")
    for unit in evaluation.unit_risk_result:
        if unit.symbol.file not in files:
            raise CanonicalModelError(
                f"a band names {unit.symbol!r}, a unit of no file of the run"
            )


def _prove_evaluation_facts(facts: CanonicalFacts, files: frozenset[FileId]) -> None:
    """Stage 5: the evaluation house's keys and laws, and the one law across
    houses — the health delta annotates a health verdict that exists and
    states a score."""
    evaluation = facts.evaluation
    _prove_evaluation_keys(evaluation)
    _prove_one_request(evaluation)
    _prove_health_dating(evaluation)
    _prove_selections(evaluation, files)
    health = evaluation.health_result
    if facts.comparison.health_delta and (health is None or health.score is None):
        raise CanonicalModelError("a health delta annotates no stated health score")


def _normalized(model: CanonicalModel) -> CanonicalModel:
    """Complete the domains to their closure and prove every key law
    (idempotent; never invents facts, never reorders — order is a
    projection concern)."""
    closure = _close_domains(model)
    _prove_logical_keys(model.facts.analysis)
    _prove_entity_consistency(model.facts.analysis)
    _prove_occurrence_relations(model.facts.analysis)
    _prove_coverage_join(model.facts.analysis)
    _prove_function_roles(model.facts.analysis)
    _prove_comparison_facts(model.facts.comparison)
    _prove_evaluation_facts(model.facts, frozenset(closure.files))
    return replace(
        model,
        files=frozenset(closure.files),
        modules=frozenset(closure.modules),
    )
