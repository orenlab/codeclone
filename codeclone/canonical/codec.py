# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Deterministic canonical JSON codec vNext (F-3 §7), wire revision 0.

The codec owns its own serializer: the legacy ``orjson OPT_SORT_KEYS``
canonizer sorts the top level and silently turns NaN into ``null`` — both
violate this contract, so it is never called here.

Wire grammar (root keys, declared order — every reference points backward,
never forward)::

    format · revisions · values · domains · sets · scope · facts ·
    comparison · evaluation · integrity

``comparison`` and ``evaluation`` (canonical epoch E4, the generation that
also moved the wire revision) carry the two houses the model grew in epochs
E2 and E3.  Each names every family of its house, in sorted order, even when
the house is empty -- an unwitnessed run is a ``comparison`` member whose
witness record is ``{}``, never a member a reader could take for "not
emitted".  A record family is ONE object of its stored fields (``{}`` is its
absence); a row family is one column per stored field.  The cells are the
store's own row form (:mod:`codeclone.canonical.tier_storage`) and admit
what that form holds and the analysis tables do not: ``null``, ``true`` /
``false`` and signed integers.  A cell no row decoder admits is refused
(``W27``); well-formed rows whose house breaks its law are refused (``W28``).

Canonical byte laws implemented here:

* one lexical form per finite float — ``repr(value)`` shortest round-trip;
  NaN and the infinities are refused, never substituted (W06);
* one escape form per string — only mandatory JSON escapes, short forms
  where JSON defines them, lowercase ``\\u00xx`` for the rest of C0; no
  Unicode normalization ever (§7.9);
* integers in ``[0, 2**31 - 1]`` for every ordinal and counter (W07);
* the ``integrity`` member seals the preceding members: its digest is
  ``sha256(DOMAIN + body)`` where *body* is exactly the serialized bytes of
  all preceding root members — keys, colons and commas included, outer
  braces excluded — so a third party recomputes it one way only;
* a decoded document must re-encode to the identical bytes (W24) — one
  semantic document has exactly one byte encoding.

Wave-1.5 additions:

* dependency facts — endpoint slots are the ratified polymorphic
  ``[tag, ordinal]`` pairs over ``MODULE | FILE``.  The ratified split
  (ruling 2026-08-24 §2) carries them as TWO tables:
  ``dependency_relations`` (the entity triple ``source · target ·
  dependency_type``) and ``dependency_occurrences`` (location evidence
  bound to a relation; producer row key ``(relation, line)``).  An
  occurrence whose triple names no relation row is refused (W26) — the
  wire never carries dangling evidence;
* ``violations`` — the second class-B handle family;
* sparse boolean columns (``is_lazy``, ``suppressed``): a strictly
  increasing list of true row positions, omitted when no row is true;
* contract-derived public handles (``candidate_id``, ``violation_id``) are
  computed at projection time through their one formula owner
  (:mod:`codeclone.canonical.authority_identity`), never stored; the
  decoder recomputes each handle and refuses a mismatch (W25).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass
from itertools import pairwise
from typing import Any, TypeVar, cast

from codeclone.canonical.analysis_rows import (
    OVERLOADED_MODULE_COUNTERS,
    OVERLOADED_MODULE_SCORES,
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
    overloaded_module_row,
)
from codeclone.canonical.api_identity import signature_variant
from codeclone.canonical.authority_identity import (
    candidate_handle,
    legacy_symbol_key,
    violation_handle,
)
from codeclone.canonical.errors import (
    CanonicalModelError,
    StoreIntegrityError,
    WireDecodeError,
)
from codeclone.canonical.identity import (
    ADOPTION_FEATURES,
    API_PARAMETER_KINDS,
    API_SYMBOL_KINDS,
    API_VISIBILITIES,
    CLONE_KINDS,
    COUPLING_COHESION_DIMENSIONS,
    COVERAGE_JOIN_STATUSES,
    COVERAGE_UNIT_STATUSES,
    DEAD_CODE_CANDIDATE_KINDS,
    DEAD_CODE_OBSERVATION_KINDS,
    DEAD_SYMBOL_CONFIDENCES,
    DEAD_SYMBOL_REASONS,
    DEPENDENCY_BINDINGS,
    DEPENDENCY_CYCLE_KINDS,
    DOMAIN_TAG_FILE,
    DOMAIN_TAG_MODULE,
    DOMAIN_TAG_SYMBOL,
    EFFECT_KINDS,
    HEAD_TAG_OPAQUE,
    IMPORT_MECHANISMS,
    IMPORT_RESOLUTIONS,
    IMPORT_TYPES,
    LIVE_ROOT_REASONS,
    LOCATION_TAG_UNRESOLVED,
    OPERATION_KINDS,
    OVERLOADED_CANDIDATE_STATUSES,
    PRODUCER_EXECUTION_STATES,
    RELATIONSHIP_KINDS,
    RELATIONSHIP_ORIGIN_LANES,
    RELATIONSHIP_RESOLUTION_RULES,
    RISK_DIMENSIONS,
    ROOT_FAMILY_EFFECT,
    ROOT_FAMILY_OPERATION,
    ROOT_FAMILY_PRODUCER,
    ROOT_FAMILY_UNRESOLVED,
    SECURITY_CLASSIFICATION_MODES,
    SECURITY_EVIDENCE_KINDS,
    SECURITY_LOCATION_SCOPES,
    SECURITY_SOURCE_KINDS,
    SECURITY_SURFACE_CATEGORIES,
    STRUCTURAL_FINDING_KINDS,
    TARGET_TAG_UNRESOLVED,
    UNREACHABLE_REASONS,
    VIOLATION_KINDS,
    WORLD_CONTRACTS,
    AnalysisFile,
    DependencyEndpoint,
    EffectLabelRoot,
    EffectRoot,
    FileId,
    FileLine,
    ImportTarget,
    KnownModule,
    ModuleId,
    ModuleSymbol,
    OpaqueDottedHead,
    OpaqueEntity,
    OperationHead,
    OperationRoot,
    OperationTarget,
    ProducerRoot,
    RelationshipTarget,
    SourceLocation,
    SymbolId,
    UnresolvedLocation,
    UnresolvedRoot,
    UnresolvedTarget,
    canonical_key,
    dead_code_entity_key,
    root_family,
    source_location_key,
)
from codeclone.canonical.model import (
    AdoptionCountRow,
    AnalysisFacts,
    AnalysisPopulation,
    ApiParameterFact,
    ApiSymbolRow,
    CandidateRow,
    CanonicalFacts,
    CanonicalModel,
    CloneGroupRow,
    ComparisonFacts,
    ContractRow,
    CouplingCohesionRow,
    DeadCodeObservationRow,
    DependencyCycleRow,
    DependencyOccurrenceRow,
    DependencyRelationRow,
    EvaluationFacts,
    FileModuleRelation,
    GraphNodeRow,
    ImportObservationRow,
    RelationshipObservationRow,
    RiskObservationRow,
    RunScalars,
    SecuritySurfaceRow,
    SemanticEdge,
    SinkRoleRow,
    UnitSpanRow,
    ViolationRow,
    prove_tier_facts,
)
from codeclone.canonical.registry import (
    is_record_family,
    sparse_bool_wire_columns,
    wire_columns,
    wire_fact_family_order,
)
from codeclone.canonical.tier_storage import (
    TierFamily,
    TierHouse,
    comparison_house,
    evaluation_house,
    tier_families,
    tier_rows,
)
from codeclone.contracts import (
    AUTHORITY_ANALYSIS_REVISION,
    CANONICAL_MODEL_REVISION,
    CANONICAL_WIRE_REVISION,
    CONTRACT_IR_VERSION,
    MODULE_IDENTITY_VERSION,
)

_FORMAT_NAME = "codeclone-canonical"
_ROOT_KEYS = (
    "format",
    "revisions",
    "values",
    "domains",
    "sets",
    "scope",
    "facts",
    "comparison",
    "evaluation",
    "integrity",
)
#: A tier cell's integer range: the analysis ordinal range, mirrored below
#: zero, because a delta is signed.
_MIN_TIER_INT = -(2**31)
_DOMAIN_KEYS = ("files", "modules", "symbols", "effect_roots")
_SET_KEYS = ("coupled_sets", "producer_sets", "root_sets")
_REVISION_KEYS = (
    "authority_analysis",
    "canonical_model",
    "contract_ir",
    "module_identity",
)
_SUPPORTED_REVISIONS = {
    "authority_analysis": AUTHORITY_ANALYSIS_REVISION,
    "canonical_model": CANONICAL_MODEL_REVISION,
    "contract_ir": CONTRACT_IR_VERSION,
    "module_identity": MODULE_IDENTITY_VERSION,
}
_INTEGRITY_MARKER = b',"integrity":'
_MAX_INT = 2**31 - 1
_ROOT_FAMILIES = (
    ROOT_FAMILY_OPERATION,
    ROOT_FAMILY_PRODUCER,
    ROOT_FAMILY_EFFECT,
    ROOT_FAMILY_UNRESOLVED,
)
_VARIANT_SLOTS: dict[str, frozenset[str]] = {
    ROOT_FAMILY_OPERATION: frozenset({"head", "local_name", "operation_kind"}),
    ROOT_FAMILY_PRODUCER: frozenset({"target"}),
    ROOT_FAMILY_EFFECT: frozenset({"effect_kind", "label"}),
    ROOT_FAMILY_UNRESOLVED: frozenset(),
}
_EFFECT_ROOT_SPARSE_COLUMNS = (
    "effect_kind",
    "head",
    "label",
    "local_name",
    "operation_kind",
    "target",
)
_KNOWN_REFERENCE_TAGS = frozenset(
    {
        DOMAIN_TAG_FILE,
        DOMAIN_TAG_MODULE,
        "symbol",
        "effect_root",
        HEAD_TAG_OPAQUE,
        TARGET_TAG_UNRESOLVED,
    }
)
_HEAD_TAGS = frozenset({DOMAIN_TAG_FILE, DOMAIN_TAG_MODULE, HEAD_TAG_OPAQUE})
# Wire revision 1: the tagged target slots of the two revision-2 families.
# The import slot admits the endpoint tags, an opaque head and the nullary
# variant; the relationship slot admits a symbol, an opaque head:local and
# the nullary variant.  Neither admits the other's tags (W09).
_IMPORT_TARGET_TAGS = frozenset(
    {DOMAIN_TAG_FILE, DOMAIN_TAG_MODULE, HEAD_TAG_OPAQUE, TARGET_TAG_UNRESOLVED}
)
_RELATIONSHIP_TARGET_TAGS = frozenset(
    {DOMAIN_TAG_SYMBOL, HEAD_TAG_OPAQUE, TARGET_TAG_UNRESOLVED}
)

_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\f": "\\f",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}


_WIRE_INTEGRITY_DOMAIN_PREFIX = "cc-canonical-wire:"


def _wire_integrity_domain(wire_revision: str) -> bytes:
    """Domain-separation prefix of the inner seal, derived from the revision.

    One owner: :func:`stream_canonical_wire` seeds its hasher here and
    :func:`_check_integrity` recomputes through the same bytes, so the
    preimage a document is sealed with and the preimage it is checked
    against cannot drift apart -- the two-spellings defect class, closed by
    construction, as :func:`codeclone.canonical.export.artifact_domain`
    already closes it for the outer seal.  Both callers pass this process's
    own ``CANONICAL_WIRE_REVISION``, never the revision a document claims,
    which would let a forgery choose the domain it is checked under.

    What the generation inside the domain is FOR is asymmetric, and only
    the second role justifies it.  For the in-process reader it is
    redundant: :func:`_decode_format_and_revisions` refuses a foreign
    generation (``W21``) before the seal is ever recomputed.  For an
    EXTERNAL verifier -- anything that rehashes this domain plus the body
    without running this decoder -- it is the only thing binding the seal
    to a generation, which is why a literal here that merely agreed with
    the revision was a latent defect and not a cosmetic one.
    """
    return f"{_WIRE_INTEGRITY_DOMAIN_PREFIX}{wire_revision}\x00".encode()


def canonical_string_lexeme(value: str) -> str:
    """The one canonical JSON lexeme of a string (§7.9)."""
    out = ['"']
    for char in value:
        code = ord(char)
        if 0xD800 <= code <= 0xDFFF:
            raise CanonicalModelError("lone surrogate is not canonical string content")
        escape = _ESCAPES.get(char)
        if escape is not None:
            out.append(escape)
        elif code < 0x20:
            out.append(f"\\u{code:04x}")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def canonical_float_lexeme(value: float) -> str:
    """The one canonical JSON lexeme of a finite float."""
    if value != value or value in (float("inf"), float("-inf")):
        raise CanonicalModelError("NaN and Infinity are refused, not encoded")
    return repr(value)


class _Obj:
    """A JSON object with explicit, contract-declared member order."""

    __slots__ = ("items",)

    def __init__(self, items: Sequence[tuple[str, object]]) -> None:
        self.items = list(items)


def _member_lexeme(key: str, value: object) -> str:
    """The one lexeme of one object member — the same spelling whether the
    member rides inside ``_write`` or is streamed chunk by chunk."""
    return f"{canonical_string_lexeme(key)}:{_write(value)}"


def _write(value: object) -> str:
    if isinstance(value, _Obj):
        members = ",".join(_member_lexeme(key, item) for key, item in value.items)
        return "{" + members + "}"
    if isinstance(value, str):
        return canonical_string_lexeme(value)
    if isinstance(value, bool):
        raise CanonicalModelError("wire revision 0 declares no boolean slots")
    if isinstance(value, int):
        if not 0 <= value <= _MAX_INT:
            raise CanonicalModelError(f"integer out of wire range: {value}")
        return str(value)
    if isinstance(value, float):
        return canonical_float_lexeme(value)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_write(item) for item in value) + "]"
    raise CanonicalModelError(f"value has no wire form: {value!r}")


def _write_tier(value: object) -> str:
    """The one lexical form of a comparison or evaluation cell.

    The analysis grammar declares no boolean, null or negative slot and
    :func:`_write` refuses all three; a tier row holds each of them (a
    witness's ``loaded``, an absent reason, a negative delta), so its cells
    are written here, under the same string, float and array laws.
    """
    if isinstance(value, _Obj):
        members = ",".join(
            f"{canonical_string_lexeme(key)}:{_write_tier(item)}"
            for key, item in value.items
        )
        return "{" + members + "}"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        if not _MIN_TIER_INT <= value <= _MAX_INT:
            raise CanonicalModelError(f"integer out of wire range: {value}")
        return str(value)
    if isinstance(value, list):
        return "[" + ",".join(_write_tier(item) for item in value) + "]"
    return _write(value)


# ---------------------------------------------------------------------------
# Encoder
# ---------------------------------------------------------------------------

_ValueT = TypeVar("_ValueT")


def _ordinals(values: Sequence[_ValueT]) -> dict[_ValueT, int]:
    return {value: ordinal for ordinal, value in enumerate(values)}


def _sorted_domain(values: Iterable[_ValueT]) -> list[_ValueT]:
    return sorted(set(values), key=canonical_key)


def referenced_symbols(facts: AnalysisFacts) -> set[SymbolId]:
    """SYMBOL-domain contribution of one facts subset (F-3 §7.2).

    Exactly the symbols the wire's ``symbols`` table carries: fact-row
    references plus producer-root targets of contract and graph-node root
    sets.  Callable per family, so the run-store's bounded exporter can
    union contributions without ever holding the complete facts.
    """
    referenced: set[SymbolId] = set()
    for contract in facts.contracts:
        referenced.add(contract.function)
        referenced.update(
            root.target for root in contract.root_set if isinstance(root, ProducerRoot)
        )
    for node in facts.graph_nodes:
        referenced.add(node.function)
        referenced.update(
            root.target for root in node.root_set if isinstance(root, ProducerRoot)
        )
    referenced.update(row.symbol for row in facts.sink_roles)
    for candidate in facts.candidates:
        referenced.update(candidate.producer_set)
    for edge in facts.semantic_edges:
        referenced.add(edge.source)
        referenced.add(edge.target)
    for violation in facts.violations:
        referenced.add(violation.sink_identity)
        referenced.add(violation.canonical_owner)
        referenced.update(violation.producer_set)
    for group in facts.clone_groups:
        referenced.update(item.symbol for item in group.items)
    referenced.update(
        row.entity
        for row in facts.dead_code_observations
        if isinstance(row.entity, SymbolId)
    )
    referenced.update(row.symbol for row in facts.coupling_cohesion_observations)
    referenced.update(row.symbol for row in facts.api_symbols)
    referenced.update(row.symbol for row in facts.risk_observations)
    referenced.update(row.symbol for row in facts.unit_spans)
    referenced.update(_relationship_symbols(facts.relationship_observations))
    referenced.update(_epoch_one_symbols(facts))
    return referenced


def _epoch_one_symbols(facts: AnalysisFacts) -> Iterator[SymbolId]:
    """The SYMBOL references the canonical epoch E1 families carry: every
    member site of a suppressed clone group or a structural group, and the
    one ``symbol`` of each site-keyed row."""
    for suppressed_group in facts.suppressed_clone_groups:
        yield from (item.symbol for item in suppressed_group.items)
    for structural_group in facts.structural_groups:
        yield from (item.symbol for item in structural_group.occurrences)
    yield from (row.symbol for row in _site_keyed_rows(facts))


def _site_keyed_rows(facts: AnalysisFacts) -> Iterator[_SiteRow]:
    """The E1 rows whose only identity contribution is one ``symbol``."""
    yield from facts.dead_symbol_groups
    yield from facts.unreachable_statement_groups
    yield from facts.complexity_hotspots
    yield from facts.coupling_hotspots
    yield from facts.cohesion_hotspots
    yield from facts.coverage_units


#: The E1 rows keyed by the declaration site ``(SYMBOL, start_line)``.
_SiteRow = (
    DeadSymbolGroupRow
    | UnreachableStatementRow
    | ComplexityHotspotRow
    | CouplingHotspotRow
    | CohesionHotspotRow
    | CoverageUnitRow
)


def _relationship_symbols(
    rows: Iterable[RelationshipObservationRow],
) -> Iterator[SymbolId]:
    """The SYMBOL references a relationship family carries: every source,
    and every target that resolved to a symbol of the run."""
    for row in rows:
        yield row.source
        if isinstance(row.target, SymbolId):
            yield row.target


def _root_carriers(
    facts: AnalysisFacts,
) -> Iterable[frozenset[EffectRoot]]:
    for row in facts.contracts:
        yield row.root_set
    for node in facts.graph_nodes:
        yield node.root_set
    for violation in facts.violations:
        yield violation.root_set


def fact_root_sets(facts: AnalysisFacts) -> set[frozenset[EffectRoot]]:
    """Every distinct root set carried by one facts subset."""
    return set(_root_carriers(facts))


def fact_producer_sets(facts: AnalysisFacts) -> set[frozenset[SymbolId]]:
    """Every distinct producer set carried by one facts subset."""
    producer_sets = {row.producer_set for row in facts.candidates}
    producer_sets.update(row.producer_set for row in facts.violations)
    return producer_sets


@dataclass(slots=True)
class WirePlan:
    """Projection plan of one model state: the sorted identity domains,
    their ordinals, and the interned set tables — everything the wire needs
    besides the fact rows themselves.

    :func:`plan_from_parts` is the one spelling of domain sorting and set
    interning for both wire producers: the in-memory encoder and the
    run-store's bounded exporter build the same plan from two row sources.
    """

    files: list[FileId]
    modules: list[ModuleId]
    symbols: list[SymbolId]
    roots: list[EffectRoot]
    file_ordinal: dict[FileId, int]
    module_ordinal: dict[ModuleId, int]
    symbol_ordinal: dict[SymbolId, int]
    root_ordinal: dict[EffectRoot, int]
    labels: list[str]
    coupled_tables: list[tuple[int, ...]]
    producer_set_tables: list[tuple[int, ...]]
    root_set_tables: list[tuple[int, ...]]
    producer_set_ordinal: dict[tuple[int, ...], int]
    root_set_ordinal: dict[tuple[int, ...], int]
    analyzed_files: frozenset[FileId]
    file_modules: frozenset[FileModuleRelation]


def plan_from_parts(
    *,
    files: Iterable[FileId],
    modules: Iterable[ModuleId],
    symbols: Iterable[SymbolId],
    root_sets: Iterable[frozenset[EffectRoot]],
    producer_sets: Iterable[frozenset[SymbolId]],
    coupled_sets: Iterable[frozenset[str]],
    analyzed_files: frozenset[FileId],
    file_modules: frozenset[FileModuleRelation],
) -> WirePlan:
    """Assemble the projection plan from collected identity parts.

    The EFFECT_ROOT domain is derived from the root sets themselves —
    exactly the union the wire's ``root_sets`` tables reference (§7.2).
    """
    root_set_values = set(root_sets)
    producer_set_values = set(producer_sets)
    coupled_values = set(coupled_sets)
    sorted_files = _sorted_domain(files)
    sorted_modules = _sorted_domain(modules)
    sorted_symbols = _sorted_domain(symbols)
    sorted_roots = _sorted_domain(
        root for row_set in root_set_values for root in row_set
    )
    symbol_ordinal = _ordinals(sorted_symbols)
    root_ordinal = _ordinals(sorted_roots)
    labels = sorted({label for group in coupled_values for label in group})
    label_ordinal = _ordinals(labels)
    coupled_tables = sorted(
        tuple(sorted(label_ordinal[label] for label in group))
        for group in coupled_values
    )
    producer_set_tables = sorted(
        {
            tuple(sorted(symbol_ordinal[p] for p in producer_set))
            for producer_set in producer_set_values
        }
    )
    root_set_tables = sorted(
        {tuple(sorted(root_ordinal[r] for r in row_set)) for row_set in root_set_values}
    )
    return WirePlan(
        files=sorted_files,
        modules=sorted_modules,
        symbols=sorted_symbols,
        roots=sorted_roots,
        file_ordinal=_ordinals(sorted_files),
        module_ordinal=_ordinals(sorted_modules),
        symbol_ordinal=symbol_ordinal,
        root_ordinal=root_ordinal,
        labels=labels,
        coupled_tables=coupled_tables,
        producer_set_tables=producer_set_tables,
        root_set_tables=root_set_tables,
        producer_set_ordinal=_ordinals(producer_set_tables),
        root_set_ordinal=_ordinals(root_set_tables),
        analyzed_files=analyzed_files,
        file_modules=file_modules,
    )


def _head_value(
    head: OperationHead,
    module_ordinal: Mapping[ModuleId, int],
    file_ordinal: Mapping[FileId, int],
) -> object:
    if isinstance(head, KnownModule):
        return [DOMAIN_TAG_MODULE, module_ordinal[head.module]]
    if isinstance(head, AnalysisFile):
        return [DOMAIN_TAG_FILE, file_ordinal[head.file]]
    return [HEAD_TAG_OPAQUE, head.text]


def _encode_effect_roots(plan: WirePlan) -> _Obj:
    family_column: list[str] = []
    sparse: dict[str, list[tuple[str, object]]] = {
        name: [] for name in _EFFECT_ROOT_SPARSE_COLUMNS
    }
    for position, root in enumerate(plan.roots):
        family_column.append(root_family(root))
        key = str(position)
        if isinstance(root, OperationRoot):
            sparse["head"].append(
                (
                    key,
                    _head_value(
                        root.target.head, plan.module_ordinal, plan.file_ordinal
                    ),
                )
            )
            sparse["local_name"].append((key, root.target.local_name))
            sparse["operation_kind"].append((key, root.operation_kind))
        elif isinstance(root, ProducerRoot):
            sparse["target"].append((key, plan.symbol_ordinal[root.target]))
        elif isinstance(root, EffectLabelRoot):
            sparse["effect_kind"].append((key, root.effect_kind))
            sparse["label"].append((key, root.label))
    members: list[tuple[str, object]] = [("family", family_column)]
    members.extend(
        (name, _Obj(sparse[name]))
        for name in _EFFECT_ROOT_SPARSE_COLUMNS
        if sparse[name]
    )
    return _Obj(members)


def _producer_set_key(
    producer_set: frozenset[SymbolId], plan: WirePlan
) -> tuple[int, ...]:
    return tuple(sorted(plan.symbol_ordinal[p] for p in producer_set))


def _root_set_ref(row_set: frozenset[EffectRoot], plan: WirePlan) -> int:
    return plan.root_set_ordinal[tuple(sorted(plan.root_ordinal[r] for r in row_set))]


def _candidate_rows(facts: AnalysisFacts, plan: WirePlan) -> list[dict[str, object]]:
    handle_symbols = {p for row in facts.candidates for p in row.producer_set}
    legacy_keys = legacy_symbol_keys(handle_symbols, plan.file_modules)
    return [
        {
            "candidate_id": candidate_handle(
                level=row.level,
                shared_fact=row.shared_fact,
                producers=[legacy_keys[p] for p in row.producer_set],
            ),
            "level": row.level,
            "producer_set": plan.producer_set_ordinal[
                _producer_set_key(row.producer_set, plan)
            ],
            "shared_fact": row.shared_fact,
        }
        for row in sorted(
            facts.candidates,
            key=lambda row: (
                row.level.encode("utf-8"),
                row.shared_fact.encode("utf-8"),
                _producer_set_key(row.producer_set, plan),
            ),
        )
    ]


def _relation_sort_key(
    relation: DependencyRelationRow, plan: WirePlan
) -> tuple[object, ...]:
    return (
        *_endpoint_sort_key(relation.source, plan.module_ordinal, plan.file_ordinal),
        *_endpoint_sort_key(relation.target, plan.module_ordinal, plan.file_ordinal),
        relation.dependency_type,
    )


def _dependency_relation_rows(
    facts: AnalysisFacts, plan: WirePlan
) -> list[dict[str, object]]:
    return [
        {
            "dependency_type": row.dependency_type,
            "source": _endpoint_value(
                row.source, plan.module_ordinal, plan.file_ordinal
            ),
            "target": _endpoint_value(
                row.target, plan.module_ordinal, plan.file_ordinal
            ),
        }
        for row in sorted(
            facts.dependency_relations,
            key=lambda row: _relation_sort_key(row, plan),
        )
    ]


def _dependency_occurrence_rows(
    facts: AnalysisFacts, plan: WirePlan
) -> list[dict[str, object]]:
    return [
        {
            "binding": row.binding,
            "dependency_type": row.relation.dependency_type,
            "is_lazy": row.is_lazy,
            "line": row.line,
            "source": _endpoint_value(
                row.relation.source, plan.module_ordinal, plan.file_ordinal
            ),
            "target": _endpoint_value(
                row.relation.target, plan.module_ordinal, plan.file_ordinal
            ),
        }
        for row in sorted(
            facts.dependency_occurrences,
            key=lambda row: (*_relation_sort_key(row.relation, plan), row.line),
        )
    ]


def _dead_code_entity_value(entity: object, plan: WirePlan) -> list[object]:
    """The tagged wire slot of one dead-code entity — the variant IS the
    identity, so the tag is emitted, never re-derived by a reader."""
    if isinstance(entity, SymbolId):
        return [DOMAIN_TAG_SYMBOL, plan.symbol_ordinal[entity]]
    if isinstance(entity, ModuleSymbol):
        return [DOMAIN_TAG_MODULE, plan.module_ordinal[entity.module], entity.qualname]
    if isinstance(entity, OpaqueEntity):
        return [HEAD_TAG_OPAQUE, entity.head, entity.qualname]
    raise CanonicalModelError(f"value is not a dead-code entity: {entity!r}")


def _dead_code_observation_rows(
    facts: AnalysisFacts, plan: WirePlan
) -> list[dict[str, object]]:
    return [
        {
            "abstained": row.abstained,
            "candidate_kind": row.candidate_kind,
            "entity": _dead_code_entity_value(row.entity, plan),
            "live_root_reason": row.live_root_reason or "",
            "observation_kind": row.observation_kind,
            "reachable": row.reachable,
            "reference_count": row.reference_count,
            "runtime_marker_count": row.runtime_marker_count,
            "source_markers": [list(pair) for pair in row.source_markers],
            "start_line": row.start_line,
        }
        for row in sorted(facts.dead_code_observations, key=_dead_code_wire_key)
    ]


def _dead_code_wire_key(row: DeadCodeObservationRow) -> tuple[object, ...]:
    """The row order of the family on the wire: its key, byte-ordered --
    ``(entity, observation_kind, start_line)`` (ruling 2026-09-28)."""
    return (
        *dead_code_entity_key(row.entity),
        row.observation_kind.encode("utf-8"),
        row.start_line,
    )


def _clone_group_rows(facts: AnalysisFacts, plan: WirePlan) -> list[dict[str, object]]:
    # Row order is the (clone_kind, group_key) byte key; every item cell is
    # [symbol ordinal, start, end], sorted — two levels, neither of which
    # may leak set iteration order.
    return [
        {
            "clone_kind": row.clone_kind,
            "group_key": row.group_key,
            "items": sorted(
                [plan.symbol_ordinal[item.symbol], item.start_line, item.end_line]
                for item in row.items
            ),
        }
        for row in sorted(
            facts.clone_groups,
            key=lambda row: (
                row.clone_kind.encode("utf-8"),
                row.group_key.encode("utf-8"),
            ),
        )
    ]


def _dependency_cycle_rows(
    facts: AnalysisFacts, plan: WirePlan
) -> list[dict[str, object]]:
    # Row order IS the entity key: the module-set ordinal tuple.  The kind
    # deliberately never enters the sort key — one set carries one row, so
    # a kind tiebreaker could only leak classification into row order.
    keyed = sorted(
        (tuple(sorted(plan.module_ordinal[m] for m in row.modules)), row.kind)
        for row in facts.dependency_cycles
    )
    return [{"kind": kind, "modules": list(ordinals)} for ordinals, kind in keyed]


def _source_location_value(
    location: SourceLocation, file_ordinal: Mapping[FileId, int]
) -> list[object]:
    """One evidence site as a ``[tag, ref, line]`` cell.

    The polymorphic slot the ratified dependency endpoints already use,
    widened by one cell for the line: the tag decides how ``ref`` is read,
    so a FILE-headed site rides an ordinal into the FILE domain and an
    unresolved site rides its own string — which is the whole point of the
    variant, since that string has no domain to be an ordinal into.
    """
    if isinstance(location, FileLine):
        return [DOMAIN_TAG_FILE, file_ordinal[location.file], location.line]
    return [LOCATION_TAG_UNRESOLVED, location.path, location.line]


def _violation_rows(facts: AnalysisFacts, plan: WirePlan) -> list[dict[str, object]]:
    handle_symbols: set[SymbolId] = set()
    for violation in facts.violations:
        handle_symbols.add(violation.sink_identity)
        handle_symbols.update(violation.producer_set)
    legacy_keys = legacy_symbol_keys(handle_symbols, plan.file_modules)
    return [
        {
            "authority_status": row.authority_status,
            "canonical_owner": plan.symbol_ordinal[row.canonical_owner],
            "contract_id": row.contract_id,
            "effect_signature": row.effect_signature,
            "kind": row.kind,
            # The stored tuple IS the canonical order (the model refuses any
            # other), so the cells are emitted as they stand: sorting here
            # would be a second ordering owner, and a second owner is how
            # two spellings of one law start to disagree.
            "locations": [
                _source_location_value(location, plan.file_ordinal)
                for location in row.locations
            ],
            "producer_set": plan.producer_set_ordinal[
                _producer_set_key(row.producer_set, plan)
            ],
            "resolution_state": row.resolution_state,
            "root_set": _root_set_ref(row.root_set, plan),
            "sink_identity": plan.symbol_ordinal[row.sink_identity],
            "suppressed": row.suppressed,
            "violation_id": violation_handle(
                contract_id=row.contract_id,
                kind=row.kind,
                sink_identity=legacy_keys[row.sink_identity],
                producers=[legacy_keys[p] for p in row.producer_set],
            ),
        }
        for row in sorted(
            facts.violations,
            key=lambda row: (
                row.contract_id.encode("utf-8"),
                row.kind.encode("utf-8"),
                plan.symbol_ordinal[row.sink_identity],
                _producer_set_key(row.producer_set, plan),
            ),
        )
    ]


def _coupling_cohesion_rows(
    facts: AnalysisFacts, plan: WirePlan
) -> list[dict[str, object]]:
    return [
        {
            "dimension": row.dimension,
            "numerator": row.numerator,
            "symbol": plan.symbol_ordinal[row.symbol],
        }
        for row in sorted(
            facts.coupling_cohesion_observations,
            key=lambda row: (
                plan.symbol_ordinal[row.symbol],
                row.dimension.encode("utf-8"),
            ),
        )
    ]


def _risk_observation_rows(
    facts: AnalysisFacts, plan: WirePlan
) -> list[dict[str, object]]:
    # F1 key order: (symbol, dimension, start_line) — symbol ordinals are
    # assigned in canonical-key order, so this spells the registry's
    # (file, qualname, dimension, start_line).
    return [
        {
            "dimension": row.dimension,
            "numerator": row.numerator,
            "start_line": row.start_line,
            "symbol": plan.symbol_ordinal[row.symbol],
        }
        for row in sorted(
            facts.risk_observations,
            key=lambda row: (
                plan.symbol_ordinal[row.symbol],
                row.dimension.encode("utf-8"),
                row.start_line,
            ),
        )
    ]


def _unit_span_rows(facts: AnalysisFacts, plan: WirePlan) -> list[dict[str, object]]:
    # Declaration key order: (symbol, start_line) — symbol ordinals are
    # assigned in canonical-key order, so this spells (file, qualname,
    # start_line).  No dimension: the span belongs to the declaration, not
    # to any measurement of it.
    return [
        {
            "end_line": row.end_line,
            "start_line": row.start_line,
            "symbol": plan.symbol_ordinal[row.symbol],
        }
        for row in sorted(
            facts.unit_spans,
            key=lambda row: (plan.symbol_ordinal[row.symbol], row.start_line),
        )
    ]


def _api_parameter_cell(parameter: ApiParameterFact) -> list[object]:
    """One wire cell per parameter: ``[name, kind, default, annotation?]``.

    The annotation slot is OMITTED when absent (the producer's own
    bijection: an empty basis is absence, never a value) and the default
    marker is an integer — wire revision 0 declares no boolean slots.
    """
    cell: list[object] = [
        parameter.name,
        parameter.kind,
        1 if parameter.has_default else 0,
    ]
    if parameter.annotation_digest is not None:
        cell.append(parameter.annotation_digest)
    return cell


def _api_symbol_rows(facts: AnalysisFacts, plan: WirePlan) -> list[dict[str, object]]:
    keyed = sorted(
        (
            plan.symbol_ordinal[row.symbol],
            signature_variant(
                parameters=row.parameters, returns_digest=row.returns_digest
            ),
            row,
        )
        for row in facts.api_symbols
    )
    return [
        {
            "parameters": [_api_parameter_cell(p) for p in row.parameters],
            "returns_digest": row.returns_digest or "",
            "signature_variant": variant,
            "symbol": ordinal,
            "symbol_kind": row.symbol_kind,
            "visibility": row.visibility,
        }
        for ordinal, variant, row in keyed
    ]


def _adoption_count_rows(
    facts: AnalysisFacts, plan: WirePlan
) -> list[dict[str, object]]:
    # F3 key order: (scope, feature) — the scope through the ONE endpoint
    # construction (tag, then ordinal), the feature by bytes.
    return [
        {
            "denominator": row.denominator,
            "feature": row.feature,
            "numerator": row.numerator,
            "scope": _endpoint_value(row.scope, plan.module_ordinal, plan.file_ordinal),
        }
        for row in sorted(
            facts.adoption_counts,
            key=lambda row: (
                _endpoint_sort_key(row.scope, plan.module_ordinal, plan.file_ordinal),
                row.feature.encode("utf-8"),
            ),
        )
    ]


def _security_surface_rows(
    facts: AnalysisFacts, plan: WirePlan
) -> list[dict[str, object]]:
    # F10 key order: (file, start_line, evidence_symbol) -- file ordinals
    # are assigned in canonical-key order; the absent module-scope local
    # name rides the empty string (the F5 returns precedent).
    return [
        {
            "capability": row.capability,
            "category": row.category,
            "classification_mode": row.classification_mode,
            "end_line": row.end_line,
            "evidence_kind": row.evidence_kind,
            "evidence_symbol": row.evidence_symbol,
            "file": plan.file_ordinal[row.file],
            "location_scope": row.location_scope,
            "qualname": row.qualname or "",
            "source_kind": row.source_kind,
            "start_line": row.start_line,
        }
        for row in sorted(
            facts.security_surfaces,
            key=lambda row: (
                plan.file_ordinal[row.file],
                row.start_line,
                row.evidence_symbol.encode("utf-8"),
            ),
        )
    ]


def _contract_rows(facts: AnalysisFacts, plan: WirePlan) -> list[dict[str, object]]:
    return [
        {
            "effect_signature": row.effect_signature,
            "function": plan.symbol_ordinal[row.function],
            "root_set": _root_set_ref(row.root_set, plan),
        }
        for row in sorted(
            facts.contracts, key=lambda row: plan.symbol_ordinal[row.function]
        )
    ]


def _file_module_rows(facts: AnalysisFacts, plan: WirePlan) -> list[dict[str, object]]:
    del facts  # the relation rides the plan, not the fact tables (§2.3)
    return [
        {
            "file": plan.file_ordinal[rel.file],
            "module": plan.module_ordinal[rel.module],
        }
        for rel in sorted(
            plan.file_modules,
            key=lambda rel: (
                plan.file_ordinal[rel.file],
                plan.module_ordinal[rel.module],
            ),
        )
    ]


def _graph_node_rows(facts: AnalysisFacts, plan: WirePlan) -> list[dict[str, object]]:
    return [
        {
            "effect_signature": row.effect_signature,
            "function": plan.symbol_ordinal[row.function],
            "output_facts": list(row.output_facts),
            "resolution_state": row.resolution_state,
            "root_set": _root_set_ref(row.root_set, plan),
        }
        for row in sorted(
            facts.graph_nodes, key=lambda row: plan.symbol_ordinal[row.function]
        )
    ]


def _analysis_population_rows(
    facts: AnalysisFacts, plan: WirePlan
) -> list[dict[str, object]]:
    del plan  # a record has no ordinals to resolve
    if facts.analysis_population is None:
        return []
    record = facts.analysis_population
    return [
        {
            "analysis_mode": record.analysis_mode,
            "analysis_profile": [
                [name, value] for name, value in record.analysis_profile
            ],
            "producer_states": [
                [family, state] for family, state in record.producer_states
            ],
        }
    ]


def _run_scalars_rows(facts: AnalysisFacts, plan: WirePlan) -> list[dict[str, object]]:
    del plan  # a record has no ordinals to resolve
    if facts.run_scalars is None:
        return []
    return [asdict(facts.run_scalars)]


def _semantic_edge_rows(
    facts: AnalysisFacts, plan: WirePlan
) -> list[dict[str, object]]:
    return [
        {
            "source": plan.symbol_ordinal[edge.source],
            "target": plan.symbol_ordinal[edge.target],
        }
        for edge in sorted(
            facts.semantic_edges,
            key=lambda e: (
                plan.symbol_ordinal[e.source],
                plan.symbol_ordinal[e.target],
            ),
        )
    ]


def _sink_role_rows(facts: AnalysisFacts, plan: WirePlan) -> list[dict[str, object]]:
    return [
        {
            "authority_status": row.authority_status,
            "symbol": plan.symbol_ordinal[row.symbol],
        }
        for row in sorted(
            facts.sink_roles, key=lambda row: plan.symbol_ordinal[row.symbol]
        )
    ]


def _import_target_sort_key(target: ImportTarget, plan: WirePlan) -> tuple[object, ...]:
    """The tagged slot's order: tag first, then the variant's own ordinal
    or text.  Two slots compare past the tag only when the tags agree, so
    an ordinal never meets a text."""
    if isinstance(target, UnresolvedTarget):
        return (TARGET_TAG_UNRESOLVED, 0)
    if isinstance(target, OpaqueDottedHead):
        return (HEAD_TAG_OPAQUE, target.text)
    return _endpoint_sort_key(target, plan.module_ordinal, plan.file_ordinal)


def _import_target_value(target: ImportTarget, plan: WirePlan) -> list[object]:
    """The tagged wire slot of one import target — the variant IS the
    identity, so the tag is emitted, never re-derived by a reader; the
    nullary variant is its tag alone (the ``unresolved`` root precedent)."""
    if isinstance(target, UnresolvedTarget):
        return [TARGET_TAG_UNRESOLVED]
    if isinstance(target, OpaqueDottedHead):
        return [HEAD_TAG_OPAQUE, target.text]
    return _endpoint_value(target, plan.module_ordinal, plan.file_ordinal)


def _import_observation_sort_key(
    row: ImportObservationRow, plan: WirePlan
) -> tuple[object, ...]:
    # The whole observation is the row's identity, so the whole observation
    # is its order: every column, in one fixed sequence, nested so that no
    # slot of one shape ever lines up against a slot of another.
    return (
        _endpoint_sort_key(row.source, plan.module_ordinal, plan.file_ordinal),
        _import_target_sort_key(row.target, plan),
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


def _import_observation_rows(
    facts: AnalysisFacts, plan: WirePlan
) -> list[dict[str, object]]:
    return [
        {
            "binding": row.binding,
            "candidate_targets": list(row.candidate_targets),
            "dependency_type": row.dependency_type,
            "inventory_expansion": row.inventory_expansion,
            "is_lazy": row.is_lazy,
            "level": row.level,
            "line": row.line,
            "mechanism": row.mechanism,
            # Absent rides as the empty string, which the producer never
            # emits (``requested_module`` is a statement's own text or
            # ``None``) — the ``live_root_reason`` spelling.
            "requested_module": row.requested_module or "",
            "requested_names": list(row.requested_names),
            "resolution": row.resolution,
            "source": _endpoint_value(
                row.source, plan.module_ordinal, plan.file_ordinal
            ),
            "target": _import_target_value(row.target, plan),
        }
        for row in sorted(
            facts.import_observations,
            key=lambda row: _import_observation_sort_key(row, plan),
        )
    ]


def _relationship_target_sort_key(
    target: RelationshipTarget, plan: WirePlan
) -> tuple[object, ...]:
    if isinstance(target, UnresolvedTarget):
        return (TARGET_TAG_UNRESOLVED, 0)
    if isinstance(target, SymbolId):
        return (DOMAIN_TAG_SYMBOL, plan.symbol_ordinal[target])
    return (HEAD_TAG_OPAQUE, target.head, target.qualname)


def _relationship_target_value(
    target: RelationshipTarget, plan: WirePlan
) -> list[object]:
    """The tagged wire slot of one relationship target (the dead-code entity
    construction: ``[symbol, ordinal]`` or ``[opaque, head, qualname]``,
    plus the nullary variant as its tag alone)."""
    if isinstance(target, UnresolvedTarget):
        return [TARGET_TAG_UNRESOLVED]
    if isinstance(target, SymbolId):
        return [DOMAIN_TAG_SYMBOL, plan.symbol_ordinal[target]]
    return [HEAD_TAG_OPAQUE, target.head, target.qualname]


def _relationship_observation_sort_key(
    row: RelationshipObservationRow, plan: WirePlan
) -> tuple[object, ...]:
    # The observation key (``occurrence_count`` is payload and never
    # enters: two rows of one observation cannot coexist in the model).
    return (
        plan.symbol_ordinal[row.source],
        _relationship_target_sort_key(row.target, plan),
        row.relation_kind,
        row.origin_lane,
        row.line,
        row.expression or "",
        row.resolution_rule or "",
    )


def _relationship_observation_rows(
    facts: AnalysisFacts, plan: WirePlan
) -> list[dict[str, object]]:
    return [
        {
            # Absent rides as the empty string, which the producer never
            # emits for either column (``ast.unparse(...) or None``; a rule
            # is a closed vocabulary member or ``None``).
            "expression": row.expression or "",
            "line": row.line,
            "occurrence_count": row.occurrence_count,
            "origin_lane": row.origin_lane,
            "relation_kind": row.relation_kind,
            "resolution_rule": row.resolution_rule or "",
            "source": plan.symbol_ordinal[row.source],
            "target": _relationship_target_value(row.target, plan),
        }
        for row in sorted(
            facts.relationship_observations,
            key=lambda row: _relationship_observation_sort_key(row, plan),
        )
    ]


def _member_cells(members: Iterable[CloneItemRow], plan: WirePlan) -> list[list[int]]:
    """The sorted ``[symbol ordinal, start, end]`` cells of a member set —
    the clone-item cell, shared by every E1 family that carries sites."""
    return sorted(
        [plan.symbol_ordinal[item.symbol], item.start_line, item.end_line]
        for item in members
    )


def _site_order(row: _SiteRow, plan: WirePlan) -> tuple[int, int]:
    return (plan.symbol_ordinal[row.symbol], row.start_line)


def _suppressed_clone_group_rows(
    facts: AnalysisFacts, plan: WirePlan
) -> list[dict[str, object]]:
    return [
        {
            "clone_kind": row.clone_kind,
            "group_key": row.group_key,
            "items": _member_cells(row.items, plan),
            "matched_patterns": list(row.matched_patterns),
            "suppression_rule": row.suppression_rule,
            "suppression_source": row.suppression_source,
        }
        for row in sorted(
            facts.suppressed_clone_groups,
            key=lambda row: (
                row.clone_kind.encode("utf-8"),
                row.group_key.encode("utf-8"),
            ),
        )
    ]


def _structural_group_rows(
    facts: AnalysisFacts, plan: WirePlan
) -> list[dict[str, object]]:
    return [
        {
            "finding_key": row.finding_key,
            "finding_kind": row.finding_kind,
            "occurrences": _member_cells(row.occurrences, plan),
            "signature": [list(pair) for pair in row.signature],
        }
        for row in sorted(
            facts.structural_groups,
            key=lambda row: (
                row.finding_kind.encode("utf-8"),
                row.finding_key.encode("utf-8"),
            ),
        )
    ]


def _dead_symbol_group_rows(
    facts: AnalysisFacts, plan: WirePlan
) -> list[dict[str, object]]:
    return [
        {
            "candidate_kind": row.candidate_kind,
            "confidence": row.confidence,
            "end_line": row.end_line,
            "reason": row.reason,
            "start_line": row.start_line,
            "symbol": plan.symbol_ordinal[row.symbol],
            "test_reference_sources": list(row.test_reference_sources),
        }
        for row in sorted(
            facts.dead_symbol_groups, key=lambda row: _site_order(row, plan)
        )
    ]


def _unreachable_statement_rows(
    facts: AnalysisFacts, plan: WirePlan
) -> list[dict[str, object]]:
    return [
        {
            "end_line": row.end_line,
            "reason": row.reason,
            "start_line": row.start_line,
            "statement_count": row.statement_count,
            "symbol": plan.symbol_ordinal[row.symbol],
        }
        for row in sorted(
            facts.unreachable_statement_groups,
            key=lambda row: _site_order(row, plan),
        )
    ]


def _complexity_hotspot_rows(
    facts: AnalysisFacts, plan: WirePlan
) -> list[dict[str, object]]:
    return [
        {
            "cyclomatic_complexity": row.cyclomatic_complexity,
            "end_line": row.end_line,
            "nesting_depth": row.nesting_depth,
            "start_line": row.start_line,
            "symbol": plan.symbol_ordinal[row.symbol],
        }
        for row in sorted(
            facts.complexity_hotspots, key=lambda row: _site_order(row, plan)
        )
    ]


def _coupling_hotspot_rows(
    facts: AnalysisFacts, plan: WirePlan
) -> list[dict[str, object]]:
    return [
        {
            "cbo": row.cbo,
            "coupled_classes": list(row.coupled_classes),
            "end_line": row.end_line,
            "start_line": row.start_line,
            "symbol": plan.symbol_ordinal[row.symbol],
        }
        for row in sorted(
            facts.coupling_hotspots, key=lambda row: _site_order(row, plan)
        )
    ]


def _cohesion_hotspot_rows(
    facts: AnalysisFacts, plan: WirePlan
) -> list[dict[str, object]]:
    return [
        {
            "end_line": row.end_line,
            "instance_var_count": row.instance_var_count,
            "lcom4": row.lcom4,
            "method_count": row.method_count,
            "start_line": row.start_line,
            "symbol": plan.symbol_ordinal[row.symbol],
        }
        for row in sorted(
            facts.cohesion_hotspots, key=lambda row: _site_order(row, plan)
        )
    ]


def _overloaded_module_rows(
    facts: AnalysisFacts, plan: WirePlan
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for row in sorted(
        facts.overloaded_modules, key=lambda row: plan.file_ordinal[row.file]
    ):
        cells: dict[str, object] = {
            counter: getattr(row, counter) for counter in OVERLOADED_MODULE_COUNTERS
        }
        cells.update((score, getattr(row, score)) for score in OVERLOADED_MODULE_SCORES)
        cells["candidate_reasons"] = list(row.candidate_reasons)
        cells["candidate_status"] = row.candidate_status
        cells["file"] = plan.file_ordinal[row.file]
        cells["source_kind"] = row.source_kind
        rows.append(cells)
    return rows


def _coverage_unit_rows(
    facts: AnalysisFacts, plan: WirePlan
) -> list[dict[str, object]]:
    return [
        {
            "coverage_status": row.coverage_status,
            "covered_lines": row.covered_lines,
            "end_line": row.end_line,
            "executable_lines": row.executable_lines,
            "start_line": row.start_line,
            "symbol": plan.symbol_ordinal[row.symbol],
        }
        for row in sorted(facts.coverage_units, key=lambda row: _site_order(row, plan))
    ]


def _coverage_join_rows(
    facts: AnalysisFacts, plan: WirePlan
) -> list[dict[str, object]]:
    del plan  # a record has no ordinals to resolve
    record = facts.coverage_join
    if record is None:
        return []
    return [
        {
            "files": record.files,
            "hotspot_threshold_percent": record.hotspot_threshold_percent,
            "invalid_reason": record.invalid_reason or "",
            "source": record.source,
            "status": record.status,
        }
    ]


def _dead_code_summary_rows(
    facts: AnalysisFacts, plan: WirePlan
) -> list[dict[str, object]]:
    del plan  # a record has no ordinals to resolve
    if facts.dead_code_summary is None:
        return []
    return [asdict(facts.dead_code_summary)]


_FAMILY_ROW_BUILDERS: dict[
    str, Callable[[AnalysisFacts, WirePlan], list[dict[str, object]]]
] = {
    "adoption_counts": _adoption_count_rows,
    "analysis_population": _analysis_population_rows,
    "api_symbols": _api_symbol_rows,
    "candidates": _candidate_rows,
    "clone_groups": _clone_group_rows,
    "cohesion_hotspots": _cohesion_hotspot_rows,
    "complexity_hotspots": _complexity_hotspot_rows,
    "contracts": _contract_rows,
    "coupling_cohesion_observations": _coupling_cohesion_rows,
    "coupling_hotspots": _coupling_hotspot_rows,
    "coverage_join": _coverage_join_rows,
    "coverage_units": _coverage_unit_rows,
    "dead_code_observations": _dead_code_observation_rows,
    "dead_code_summary": _dead_code_summary_rows,
    "dead_symbol_groups": _dead_symbol_group_rows,
    "dependency_cycles": _dependency_cycle_rows,
    "dependency_occurrences": _dependency_occurrence_rows,
    "dependency_relations": _dependency_relation_rows,
    "file_modules": _file_module_rows,
    "graph_nodes": _graph_node_rows,
    "import_observations": _import_observation_rows,
    "overloaded_modules": _overloaded_module_rows,
    "relationship_observations": _relationship_observation_rows,
    "risk_observations": _risk_observation_rows,
    "run_scalars": _run_scalars_rows,
    "security_surfaces": _security_surface_rows,
    "semantic_edges": _semantic_edge_rows,
    "sink_roles": _sink_role_rows,
    "structural_groups": _structural_group_rows,
    "suppressed_clone_groups": _suppressed_clone_group_rows,
    "unit_spans": _unit_span_rows,
    "unreachable_statement_groups": _unreachable_statement_rows,
    "violations": _violation_rows,
}


def fact_family_rows(
    family: str, facts: AnalysisFacts, plan: WirePlan
) -> list[dict[str, object]]:
    """Wire rows of one fact family, in canonical row order.

    Only the named family's rows are read from ``facts`` — the provider may
    carry a single family at a time (bounded working memory, brief law 11).
    """
    return _FAMILY_ROW_BUILDERS[family](facts, plan)


def legacy_symbol_keys(
    symbols: Iterable[SymbolId], file_modules: frozenset[FileModuleRelation]
) -> dict[SymbolId, str]:
    """Project symbols back to the producer's ModuleKey-headed keys.

    The reverse of the measured lossless normalization (F-3 §2.1.8): the
    head is the file's registry module when the relation names exactly one,
    the analysis path otherwise.  A file with two modules has no
    deterministic legacy head, so the projection refuses instead of
    guessing — the class-B handles hash these keys and a guess would be a
    silently wrong identity.
    """
    module_of: dict[FileId, ModuleId] = {}
    ambiguous: set[FileId] = set()
    for relation in file_modules:
        if relation.file in module_of and module_of[relation.file] != relation.module:
            ambiguous.add(relation.file)
        module_of[relation.file] = relation.module
    keys: dict[SymbolId, str] = {}
    for symbol in symbols:
        if symbol.file in ambiguous:
            raise CanonicalModelError(
                "legacy producer key needs an unambiguous FILE-MODULE "
                f"relation, and {symbol.file.path!r} has more than one module"
            )
        module = module_of.get(symbol.file)
        head = module.module if module is not None else symbol.file.path
        keys[symbol] = legacy_symbol_key(head, symbol.qualname)
    return keys


def _endpoint_sort_key(
    endpoint: DependencyEndpoint,
    module_ordinal: Mapping[ModuleId, int],
    file_ordinal: Mapping[FileId, int],
) -> tuple[str, int]:
    if isinstance(endpoint, ModuleId):
        return (DOMAIN_TAG_MODULE, module_ordinal[endpoint])
    return (DOMAIN_TAG_FILE, file_ordinal[endpoint])


def _endpoint_value(
    endpoint: DependencyEndpoint,
    module_ordinal: Mapping[ModuleId, int],
    file_ordinal: Mapping[FileId, int],
) -> list[object]:
    tag, ordinal = _endpoint_sort_key(endpoint, module_ordinal, file_ordinal)
    return [tag, ordinal]


def _domains_member(plan: WirePlan) -> _Obj:
    return _Obj(
        [
            ("files", _Obj([("path", [f.path for f in plan.files])])),
            ("modules", _Obj([("module", [m.module for m in plan.modules])])),
            (
                "symbols",
                _Obj(
                    [
                        ("file", [plan.file_ordinal[s.file] for s in plan.symbols]),
                        ("qualname", [s.qualname for s in plan.symbols]),
                    ]
                ),
            ),
            ("effect_roots", _encode_effect_roots(plan)),
        ]
    )


def _leading_members(plan: WirePlan) -> list[tuple[str, object]]:
    """The six root members preceding ``facts``, in declared order (§7.1)."""
    return [
        (
            "format",
            _Obj([("name", _FORMAT_NAME), ("wire", CANONICAL_WIRE_REVISION)]),
        ),
        (
            "revisions",
            _Obj([(key, _SUPPORTED_REVISIONS[key]) for key in _REVISION_KEYS]),
        ),
        ("values", _Obj([("coupled_class_labels", plan.labels)])),
        ("domains", _domains_member(plan)),
        (
            "sets",
            _Obj(
                [
                    ("coupled_sets", [list(t) for t in plan.coupled_tables]),
                    ("producer_sets", [list(t) for t in plan.producer_set_tables]),
                    ("root_sets", [list(t) for t in plan.root_set_tables]),
                ]
            ),
        ),
        (
            "scope",
            _Obj(
                [
                    (
                        "analyzed_files",
                        sorted(plan.file_ordinal[f] for f in plan.analyzed_files),
                    )
                ]
            ),
        ),
    ]


def _family_member(family: str, rows: Sequence[dict[str, object]]) -> _Obj:
    """The wire member of one fact family: columnar, sparse booleans as
    strictly increasing true positions, omitted when no row is true.

    A RECORD family (F9) is ONE record object instead: its members are the
    record's scalars in canonical column order, and the absent record is
    the empty member — never an all-zero fake."""
    if is_record_family(family):
        if not rows:
            return _Obj([])
        (record,) = rows
        return _Obj([(column, record[column]) for column in wire_columns(family)])
    sparse = set(sparse_bool_wire_columns(family))
    members: list[tuple[str, object]] = []
    for column in wire_columns(family):
        if column in sparse:
            positions = [position for position, row in enumerate(rows) if row[column]]
            if positions:  # omitted list means: no row is true (§7.6)
                members.append((column, positions))
        else:
            members.append((column, [row[column] for row in rows]))
    return _Obj(members)


def _tier_family_member(
    family: TierFamily, rows: Sequence[Mapping[str, object]]
) -> _Obj:
    """One family of a house: a record object (``{}`` when absent) or one
    column per stored field, rows in the storage writer's order."""
    columns = family.columns
    for row in rows:
        if tuple(sorted(row)) != columns:
            raise CanonicalModelError(
                f"{family.name} row fields {sorted(row)!r} are not the declared "
                f"stored fields {list(columns)!r}"
            )
    if family.record:
        return _Obj([(column, rows[0][column]) for column in columns] if rows else [])
    return _Obj([(column, [row[column] for row in rows]) for column in columns])


def _tier_member(house: TierHouse, facts: ComparisonFacts | EvaluationFacts) -> str:
    """The lexeme of one house's root member, every family named."""
    rows = tier_rows(house, facts)
    member = _Obj(
        [
            (family.name, _tier_family_member(family, rows.get(family.name, [])))
            for family in tier_families(house)
        ]
    )
    return f"{canonical_string_lexeme(house)}:{_write_tier(member)}"


def _integrity_tail(digest: str) -> str:
    """The sealing tail after the hashed body: the integrity member only."""
    integrity = _Obj([("algorithm", "sha256"), ("value", digest)])
    return f',"integrity":{_write(integrity)}'


def stream_canonical_wire(
    plan: WirePlan,
    facts_for_family: Callable[[str], AnalysisFacts],
    write: Callable[[bytes], object],
    tiers: Callable[[], tuple[ComparisonFacts, EvaluationFacts]],
) -> None:
    """Write the one canonical byte encoding of one model state.

    The single wire emitter: :func:`encode_canonical_json` runs it over an
    in-memory model, the run-store's exporter over per-family scans.
    ``facts_for_family`` is called once per fact family, in wire order, and
    only that family's rows are read — bounded working memory (brief law
    11) is the provider's right by construction, never an accident.  The
    ``integrity`` member seals the body exactly as the decoder recomputes
    it: sha256 over the wire domain plus every emitted byte between the
    outer braces that precedes the integrity tail.  ``tiers`` is called once,
    after the facts, for the comparison and evaluation houses: they are small
    beside the analysis, and a house is emitted whole or its laws cannot be
    read off it.
    """
    hasher = hashlib.sha256(_wire_integrity_domain(CANONICAL_WIRE_REVISION))

    def emit(text: str) -> None:
        data = text.encode("utf-8")
        hasher.update(data)
        write(data)

    write(b"{")
    for index, (key, value) in enumerate(_leading_members(plan)):
        emit(("," if index else "") + _member_lexeme(key, value))
    emit(',"facts":{')
    for index, family in enumerate(wire_fact_family_order()):
        rows = fact_family_rows(family, facts_for_family(family), plan)
        emit(
            ("," if index else "")
            + _member_lexeme(family, _family_member(family, rows))
        )
    emit("}")
    comparison, evaluation = tiers()
    emit("," + _tier_member("comparison", comparison))
    emit("," + _tier_member("evaluation", evaluation))
    write(_integrity_tail(hasher.hexdigest()).encode("utf-8"))
    write(b"}")


def encode_canonical_json(model: CanonicalModel) -> bytes:
    """Project a canonical model to its one canonical byte encoding."""
    model = model.normalize()
    facts = model.facts.analysis
    plan = plan_from_parts(
        files=model.files,
        modules=model.modules,
        symbols=referenced_symbols(facts),
        root_sets=fact_root_sets(facts),
        producer_sets=fact_producer_sets(facts),
        coupled_sets=model.coupled_sets,
        analyzed_files=model.analyzed_files,
        file_modules=model.file_modules,
    )
    out = bytearray()
    stream_canonical_wire(
        plan,
        lambda _family: facts,
        out.extend,
        lambda: (model.facts.comparison, model.facts.evaluation),
    )
    return bytes(out)


# ---------------------------------------------------------------------------
# Decoder
# ---------------------------------------------------------------------------


def _refuse(code: str, detail: str) -> WireDecodeError:
    return WireDecodeError(code, detail)


def _pairs_hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
    seen = set()
    for key, _value in pairs:
        if key in seen:
            raise _refuse("W03", f"duplicate object key {key!r}")
        seen.add(key)
    return dict(pairs)


def _parse_constant(text: str) -> object:
    raise _refuse("W06", f"non-finite literal {text!r}")


def _parse_float(text: str) -> float:
    value = float(text)
    if text != repr(value):
        raise _refuse(
            "W24", f"float lexeme {text!r} is not the canonical {repr(value)!r}"
        )
    return value


def _expect_object(
    value: object, declared: Sequence[str], where: str
) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise _refuse("W01", f"{where} is not an object")
    keys = list(value.keys())
    if set(keys) != set(declared):
        raise _refuse(
            "W01",
            f"{where} keys {keys!r} do not match the declared set {list(declared)!r}",
        )
    if keys != list(declared):
        raise _refuse("W02", f"{where} keys {keys!r} are not in the declared order")
    return cast("Mapping[str, object]", value)


def _expect_string(value: object, where: str) -> str:
    if value is None:
        raise _refuse("W18", f"{where} is null where the contract forbids null")
    if not isinstance(value, str):
        raise _refuse("W18", f"{where} is not a string")
    for char in value:
        if 0xD800 <= ord(char) <= 0xDFFF:
            raise _refuse("W05", f"{where} carries a lone surrogate")
    return value


def _expect_wire_int(value: object, where: str) -> int:
    if value is None:
        raise _refuse("W18", f"{where} is null where the contract forbids null")
    if isinstance(value, bool):
        raise _refuse("W18", f"{where} is a boolean where an integer is declared")
    if isinstance(value, float):
        raise _refuse("W07", f"{where} is fractional where an integer is declared")
    if not isinstance(value, int):
        raise _refuse("W18", f"{where} is not an integer")
    if not 0 <= value <= _MAX_INT:
        raise _refuse("W07", f"{where} integer {value} outside [0, 2**31-1]")
    return value


def _expect_ordinal(value: object, size: int, where: str) -> int:
    ordinal = _expect_wire_int(value, where)
    if ordinal >= size:
        raise _refuse("W10", f"{where} ordinal {ordinal} outside table of {size}")
    return ordinal


def _expect_list(value: object, where: str) -> list[object]:
    if not isinstance(value, list):
        raise _refuse("W18", f"{where} is not an array")
    return cast("list[object]", value)


def _expect_strictly_increasing(rows: Sequence[Any], where: str) -> None:
    # Any: each call site passes one homogeneous key shape (int tuples or
    # byte tuples); the comparison itself is the canonical-order check.
    for left, right in pairwise(rows):
        if left == right:
            raise _refuse("W13", f"{where} carries a duplicate canonical key")
        if left > right:
            raise _refuse("W12", f"{where} is not in canonical order")


def _expect_increasing_elements(values: Sequence[int], where: str) -> None:
    for left, right in pairwise(values):
        if right <= left:
            raise _refuse("W14", f"{where} elements are not strictly increasing")


def _decode_file_path(value: object, where: str) -> str:
    text = _expect_string(value, where)
    try:
        FileId(text)
    except CanonicalModelError as error:
        raise _refuse("W17", f"{where}: {error}") from error
    return text


def _decode_sparse_map(value: object, row_count: int, where: str) -> dict[int, object]:
    if not isinstance(value, dict):
        raise _refuse("W18", f"{where} is not a sparse map object")
    entries = cast("dict[str, object]", value)
    positions: dict[int, object] = {}
    previous = -1
    for key, item in entries.items():
        if not key.isdigit() or (len(key) > 1 and key.startswith("0")):
            raise _refuse(
                "W19", f"{where} key {key!r} is not a canonical decimal position"
            )
        position = int(key)
        if position >= row_count:
            raise _refuse("W19", f"{where} position {position} outside the row range")
        if position <= previous:
            raise _refuse("W02", f"{where} positions are not in canonical order")
        previous = position
        positions[position] = item
    return positions


def _expect_tagged_pair(value: object, where: str) -> tuple[str, object]:
    """One reading of a polymorphic ``[tag, value]`` reference slot."""
    pair = _expect_list(value, where)
    if len(pair) != 2:
        raise _refuse("W18", f"{where} is not a [tag, value] pair")
    tag = _expect_string(pair[0], f"{where}.tag")
    if tag not in _KNOWN_REFERENCE_TAGS:
        raise _refuse("W08", f"unknown reference tag {tag!r}")
    return tag, pair[1]


def _decode_head(
    value: object, files: Sequence[FileId], modules: Sequence[ModuleId], where: str
) -> OperationHead:
    tag, slot = _expect_tagged_pair(value, where)
    if tag not in _HEAD_TAGS:
        raise _refuse(
            "W09", f"reference tag {tag!r} is not admitted for an operation head"
        )
    if tag == DOMAIN_TAG_MODULE:
        return KnownModule(modules[_expect_ordinal(slot, len(modules), where)])
    if tag == DOMAIN_TAG_FILE:
        return AnalysisFile(files[_expect_ordinal(slot, len(files), where)])
    text = _expect_string(slot, where)
    if not text:
        raise _refuse("W18", f"{where} opaque head is empty")
    return OpaqueDottedHead(text)


def _decode_root_row(
    family: str,
    position: int,
    sparse: Mapping[str, dict[int, object]],
    files: Sequence[FileId],
    modules: Sequence[ModuleId],
    symbols: Sequence[SymbolId],
) -> EffectRoot:
    if family == ROOT_FAMILY_OPERATION:
        kind = _expect_string(
            sparse["operation_kind"][position],
            f"effect_roots.operation_kind[{position}]",
        )
        if kind not in OPERATION_KINDS:
            raise _refuse("W08", f"unknown operation_kind tag {kind!r}")
        head = _decode_head(
            sparse["head"][position], files, modules, f"effect_roots.head[{position}]"
        )
        local_name = _expect_string(
            sparse["local_name"][position], f"effect_roots.local_name[{position}]"
        )
        if not local_name and not isinstance(head, OpaqueDottedHead):
            # Empty local names exist only where the producer asserted one
            # opaque dotted string (measured: 21 of 1 080 corpus targets).
            raise _refuse(
                "W18",
                f"effect_roots.local_name[{position}] is empty under a non-opaque head",
            )
        return OperationRoot(kind, OperationTarget(head, local_name))
    if family == ROOT_FAMILY_PRODUCER:
        ordinal = _expect_ordinal(
            sparse["target"][position],
            len(symbols),
            f"effect_roots.target[{position}]",
        )
        return ProducerRoot(symbols[ordinal])
    if family == ROOT_FAMILY_EFFECT:
        kind = _expect_string(
            sparse["effect_kind"][position], f"effect_roots.effect_kind[{position}]"
        )
        if kind not in EFFECT_KINDS:
            raise _refuse("W08", f"unknown effect_kind tag {kind!r}")
        label = _expect_string(
            sparse["label"][position], f"effect_roots.label[{position}]"
        )
        if not label:
            raise _refuse("W18", f"effect_roots.label[{position}] is empty")
        return EffectLabelRoot(kind, label)
    return UnresolvedRoot()


def _decode_effect_roots(
    value: object,
    files: Sequence[FileId],
    modules: Sequence[ModuleId],
    symbols: Sequence[SymbolId],
) -> list[EffectRoot]:
    if not isinstance(value, dict):
        raise _refuse("W01", "domains.effect_roots is not an object")
    table = cast("dict[str, object]", value)
    keys = list(table.keys())
    if not keys or keys[0] != "family":
        raise _refuse(
            "W02", "effect_roots discriminator column 'family' must come first"
        )
    tail = keys[1:]
    if any(key not in _EFFECT_ROOT_SPARSE_COLUMNS for key in tail):
        raise _refuse("W01", f"effect_roots carries unknown columns: {tail!r}")
    if tail != sorted(tail):
        raise _refuse("W02", "effect_roots variant columns are not in canonical order")
    family_column = _expect_list(table["family"], "effect_roots.family")
    families: list[str] = []
    for index, item in enumerate(family_column):
        family = _expect_string(item, f"effect_roots.family[{index}]")
        if family not in _ROOT_FAMILIES:
            raise _refuse("W08", f"unknown effect-root family tag {family!r}")
        families.append(family)
    sparse = {
        name: _decode_sparse_map(table[name], len(families), f"effect_roots.{name}")
        for name in tail
    }
    for name, positions in sparse.items():
        for position in positions:
            if name not in _VARIANT_SLOTS[families[position]]:
                raise _refuse(
                    "W20",
                    f"variant slot {name!r} is not consistent with family "
                    f"{families[position]!r} at row {position}",
                )
    roots: list[EffectRoot] = []
    for position, family in enumerate(families):
        for slot in _VARIANT_SLOTS[family]:
            if slot not in sparse or position not in sparse[slot]:
                raise _refuse(
                    "W20",
                    f"mandatory variant slot {slot!r} missing for family "
                    f"{family!r} at row {position}",
                )
        roots.append(
            _decode_root_row(family, position, sparse, files, modules, symbols)
        )
    _expect_strictly_increasing(
        [canonical_key(root) for root in roots], "domains.effect_roots"
    )
    return roots


def _decode_set_table(
    value: object, element_count: int, where: str
) -> list[tuple[int, ...]]:
    table = _expect_list(value, where)
    decoded: list[tuple[int, ...]] = []
    for index, row in enumerate(table):
        elements = _expect_list(row, f"{where}[{index}]")
        ordinals = [
            _expect_ordinal(item, element_count, f"{where}[{index}]")
            for item in elements
        ]
        _expect_increasing_elements(ordinals, f"{where}[{index}]")
        decoded.append(tuple(ordinals))
    _expect_strictly_increasing(decoded, where)
    return decoded


def _expect_table_keys(
    family: str, table: Mapping[str, object], sparse_names: set[str]
) -> list[str]:
    """Prove the column key set and order of one record table (W01, W02)."""
    declared = wire_columns(family)
    keys = list(table.keys())
    unknown = [key for key in keys if key not in declared]
    if unknown:
        raise _refuse("W01", f"facts.{family} carries unknown columns {unknown!r}")
    missing = [
        name for name in declared if name not in keys and name not in sparse_names
    ]
    if missing:
        raise _refuse("W01", f"facts.{family} is missing columns {missing!r}")
    if keys != [name for name in declared if name in keys]:
        raise _refuse("W02", f"facts.{family} columns are not in canonical order")
    return keys


def _decode_sparse_positions(value: object, row_count: int, where: str) -> set[int]:
    """Decode one sparse boolean column: strictly increasing true positions."""
    decoded = [_expect_wire_int(item, where) for item in _expect_list(value, where)]
    _expect_increasing_elements(decoded, where)
    for position in decoded:
        if position >= row_count:
            raise _refuse(
                "W10", f"{where} position {position} outside table of {row_count}"
            )
    return set(decoded)


def _decode_columns(
    family: str, value: object
) -> tuple[dict[str, list[object]], dict[str, set[int]], int]:
    """Decode one record table: plain columns, sparse booleans, row count.

    A sparse boolean column may be absent (no row is true); every plain
    column is mandatory and all plain columns must agree on length (W15).
    """
    sparse_names = set(sparse_bool_wire_columns(family))
    if not isinstance(value, dict):
        raise _refuse("W01", f"facts.{family} is not an object")
    table = cast("dict[str, object]", value)
    keys = _expect_table_keys(family, table, sparse_names)
    columns = {
        name: _expect_list(table[name], f"facts.{family}.{name}")
        for name in keys
        if name not in sparse_names
    }
    lengths = {len(column) for column in columns.values()}
    if len(lengths) > 1:
        raise _refuse(
            "W15", f"facts.{family} columns have diverging lengths {lengths!r}"
        )
    row_count = lengths.pop() if lengths else 0
    flags = {
        name: (
            _decode_sparse_positions(table[name], row_count, f"facts.{family}.{name}")
            if name in table
            else set[int]()
        )
        for name in sparse_names
    }
    return columns, flags, row_count


def _parse_document(data: bytes) -> object:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise _refuse("W05", f"document is not UTF-8: {error}") from error
    decoder = json.JSONDecoder(
        object_pairs_hook=_pairs_hook,
        parse_float=_parse_float,
        parse_constant=_parse_constant,
    )
    try:
        document, end = decoder.raw_decode(text)
    except json.JSONDecodeError as error:
        raise _refuse("W01", f"document is not a JSON object: {error}") from error
    if text[end:]:
        raise _refuse("W04", "bytes after the end of the document")
    return document


def _root_member(document: object, key: str) -> object:
    """One root member of a document not yet judged by its shape."""
    return document.get(key) if isinstance(document, dict) else None


def _decode_format_and_revisions(document: object) -> None:
    """The revision fence: taken BEFORE the root's shape is judged, so a
    document of another generation -- whose root the declared member list
    of this one need not fit -- is named for its generation (``W21``), never
    for its shape (``W01``)."""
    fmt = _expect_object(_root_member(document, "format"), ("name", "wire"), "format")
    name = _expect_string(fmt["name"], "format.name")
    if name != _FORMAT_NAME:
        raise _refuse(
            "W21", f"format declares an incompatible generation: name {name!r}"
        )
    wire = _expect_string(fmt["wire"], "format.wire")
    if wire != CANONICAL_WIRE_REVISION:
        # A foreign generation is named on both sides and handed its
        # migration path: a reader meeting a generation-0 document has
        # nothing else to go on, and "incompatible" alone told it neither
        # which generation it holds nor what to do about it.
        raise _refuse(
            "W21",
            f"format declares wire generation {wire!r}; this build reads "
            f"{CANONICAL_WIRE_REVISION!r} only. next_step: re-export the run "
            "from a store this build can open, or re-run the analysis with the "
            "run store enabled to publish it under this generation",
        )
    revisions_raw = _root_member(document, "revisions")
    if not isinstance(revisions_raw, dict):
        raise _refuse("W21", "revisions member is not an object")
    revisions_view = cast("dict[str, object]", revisions_raw)
    if set(revisions_view.keys()) != set(_REVISION_KEYS):
        raise _refuse(
            "W21",
            f"revisions are incomplete: {sorted(revisions_view.keys())!r} "
            f"against declared {list(_REVISION_KEYS)!r}",
        )
    revisions = _expect_object(revisions_raw, _REVISION_KEYS, "revisions")
    for key, expected_value in _SUPPORTED_REVISIONS.items():
        if _expect_string(revisions[key], f"revisions.{key}") != expected_value:
            raise _refuse(
                "W21",
                f"revisions.{key} declares an incompatible generation "
                f"{revisions[key]!r} (supported: {expected_value!r})",
            )


def _decode_values(root: Mapping[str, object]) -> list[str]:
    values_section = _expect_object(root["values"], ("coupled_class_labels",), "values")
    labels = [
        _expect_string(item, f"values.coupled_class_labels[{index}]")
        for index, item in enumerate(
            _expect_list(
                values_section["coupled_class_labels"], "values.coupled_class_labels"
            )
        )
    ]
    _expect_strictly_increasing(
        [label.encode("utf-8") for label in labels], "values.coupled_class_labels"
    )
    return labels


def _decode_files(domains: Mapping[str, object]) -> list[FileId]:
    files_table = _expect_object(domains["files"], ("path",), "domains.files")
    files = [
        FileId(_decode_file_path(item, f"domains.files.path[{index}]"))
        for index, item in enumerate(
            _expect_list(files_table["path"], "domains.files.path")
        )
    ]
    _expect_strictly_increasing([canonical_key(f) for f in files], "domains.files")
    return files


def _decode_modules(domains: Mapping[str, object]) -> list[ModuleId]:
    modules_table = _expect_object(domains["modules"], ("module",), "domains.modules")
    modules = []
    for index, item in enumerate(
        _expect_list(modules_table["module"], "domains.modules.module")
    ):
        text = _expect_string(item, f"domains.modules.module[{index}]")
        if not text:
            raise _refuse("W18", f"domains.modules.module[{index}] is empty")
        modules.append(ModuleId(text))
    _expect_strictly_increasing([canonical_key(m) for m in modules], "domains.modules")
    return modules


def _decode_symbols(
    domains: Mapping[str, object], files: Sequence[FileId]
) -> list[SymbolId]:
    symbols_table = _expect_object(
        domains["symbols"], ("file", "qualname"), "domains.symbols"
    )
    file_column = _expect_list(symbols_table["file"], "domains.symbols.file")
    qualname_column = _expect_list(
        symbols_table["qualname"], "domains.symbols.qualname"
    )
    if len(file_column) != len(qualname_column):
        raise _refuse("W15", "domains.symbols columns have diverging lengths")
    symbols = []
    for index in range(len(file_column)):
        ordinal = _expect_ordinal(
            file_column[index], len(files), f"domains.symbols.file[{index}]"
        )
        qualname = _expect_string(
            qualname_column[index], f"domains.symbols.qualname[{index}]"
        )
        if not qualname:
            raise _refuse("W18", f"domains.symbols.qualname[{index}] is empty")
        symbols.append(SymbolId(files[ordinal], qualname))
    _expect_strictly_increasing([canonical_key(s) for s in symbols], "domains.symbols")
    return symbols


def _decode_candidates(
    facts: Mapping[str, object],
    symbols: Sequence[SymbolId],
    producer_tables: Sequence[tuple[int, ...]],
) -> tuple[list[CandidateRow], list[str]]:
    columns, _flags, row_count = _decode_columns("candidates", facts["candidates"])
    rows = []
    handles = []
    keys = []
    for index in range(row_count):
        level = _expect_string(
            columns["level"][index], f"facts.candidates.level[{index}]"
        )
        shared_fact = _expect_string(
            columns["shared_fact"][index], f"facts.candidates.shared_fact[{index}]"
        )
        set_ordinal = _expect_ordinal(
            columns["producer_set"][index],
            len(producer_tables),
            f"facts.candidates.producer_set[{index}]",
        )
        rows.append(
            CandidateRow(
                level,
                shared_fact,
                frozenset(symbols[o] for o in producer_tables[set_ordinal]),
            )
        )
        handles.append(
            _expect_string(
                columns["candidate_id"][index],
                f"facts.candidates.candidate_id[{index}]",
            )
        )
        keys.append((level.encode("utf-8"), shared_fact.encode("utf-8"), set_ordinal))
    _expect_strictly_increasing(keys, "facts.candidates")
    return rows, handles


def _decode_contracts(
    facts: Mapping[str, object],
    symbols: Sequence[SymbolId],
    roots: Sequence[EffectRoot],
    root_tables: Sequence[tuple[int, ...]],
) -> tuple[frozenset[ContractRow], set[int]]:
    columns, _flags, row_count = _decode_columns("contracts", facts["contracts"])
    rows = []
    ordinals = []
    for index in range(row_count):
        ordinal = _expect_ordinal(
            columns["function"][index],
            len(symbols),
            f"facts.contracts.function[{index}]",
        )
        set_ordinal = _expect_ordinal(
            columns["root_set"][index],
            len(root_tables),
            f"facts.contracts.root_set[{index}]",
        )
        rows.append(
            ContractRow(
                symbols[ordinal],
                _expect_string(
                    columns["effect_signature"][index],
                    f"facts.contracts.effect_signature[{index}]",
                ),
                frozenset(roots[r] for r in root_tables[set_ordinal]),
            )
        )
        ordinals.append(ordinal)
    _expect_strictly_increasing(ordinals, "facts.contracts")
    return frozenset(rows), set(ordinals)


def _decode_file_modules(
    facts: Mapping[str, object],
    files: Sequence[FileId],
    modules: Sequence[ModuleId],
) -> frozenset[FileModuleRelation]:
    columns, _flags, row_count = _decode_columns("file_modules", facts["file_modules"])
    rows = []
    keys = []
    for index in range(row_count):
        file_ref = _expect_ordinal(
            columns["file"][index], len(files), f"facts.file_modules.file[{index}]"
        )
        module_ref = _expect_ordinal(
            columns["module"][index],
            len(modules),
            f"facts.file_modules.module[{index}]",
        )
        rows.append(FileModuleRelation(files[file_ref], modules[module_ref]))
        keys.append((file_ref, module_ref))
    _expect_strictly_increasing(keys, "facts.file_modules")
    return frozenset(rows)


def _decode_graph_nodes(
    facts: Mapping[str, object],
    symbols: Sequence[SymbolId],
    roots: Sequence[EffectRoot],
    root_tables: Sequence[tuple[int, ...]],
) -> frozenset[GraphNodeRow]:
    columns, _flags, row_count = _decode_columns("graph_nodes", facts["graph_nodes"])
    rows = []
    ordinals = []
    for index in range(row_count):
        ordinal = _expect_ordinal(
            columns["function"][index],
            len(symbols),
            f"facts.graph_nodes.function[{index}]",
        )
        set_ordinal = _expect_ordinal(
            columns["root_set"][index],
            len(root_tables),
            f"facts.graph_nodes.root_set[{index}]",
        )
        output_facts = tuple(
            _expect_string(item, f"facts.graph_nodes.output_facts[{index}]")
            for item in _expect_list(
                columns["output_facts"][index],
                f"facts.graph_nodes.output_facts[{index}]",
            )
        )
        rows.append(
            GraphNodeRow(
                symbols[ordinal],
                _expect_string(
                    columns["effect_signature"][index],
                    f"facts.graph_nodes.effect_signature[{index}]",
                ),
                frozenset(roots[r] for r in root_tables[set_ordinal]),
                output_facts,
                _expect_string(
                    columns["resolution_state"][index],
                    f"facts.graph_nodes.resolution_state[{index}]",
                ),
            )
        )
        ordinals.append(ordinal)
    _expect_strictly_increasing(ordinals, "facts.graph_nodes")
    return frozenset(rows)


def _decode_semantic_edges(
    facts: Mapping[str, object], symbols: Sequence[SymbolId]
) -> frozenset[SemanticEdge]:
    columns, _flags, row_count = _decode_columns(
        "semantic_edges", facts["semantic_edges"]
    )
    rows = []
    keys = []
    for index in range(row_count):
        source = _expect_ordinal(
            columns["source"][index],
            len(symbols),
            f"facts.semantic_edges.source[{index}]",
        )
        target = _expect_ordinal(
            columns["target"][index],
            len(symbols),
            f"facts.semantic_edges.target[{index}]",
        )
        rows.append(SemanticEdge(symbols[source], symbols[target]))
        keys.append((source, target))
    _expect_strictly_increasing(keys, "facts.semantic_edges")
    return frozenset(rows)


def _decode_sink_roles(
    facts: Mapping[str, object], symbols: Sequence[SymbolId]
) -> frozenset[SinkRoleRow]:
    columns, _flags, row_count = _decode_columns("sink_roles", facts["sink_roles"])
    rows = []
    ordinals = []
    for index in range(row_count):
        ordinal = _expect_ordinal(
            columns["symbol"][index],
            len(symbols),
            f"facts.sink_roles.symbol[{index}]",
        )
        rows.append(
            SinkRoleRow(
                symbols[ordinal],
                _expect_string(
                    columns["authority_status"][index],
                    f"facts.sink_roles.authority_status[{index}]",
                ),
            )
        )
        ordinals.append(ordinal)
    _expect_strictly_increasing(ordinals, "facts.sink_roles")
    return frozenset(rows)


def _decode_endpoint(
    value: object,
    files: Sequence[FileId],
    modules: Sequence[ModuleId],
    where: str,
    what: str = "a dependency endpoint",
) -> tuple[DependencyEndpoint, tuple[str, int]]:
    """One reading of a MODULE|FILE reference slot — the dependency
    endpoints and the F3 ScopeRef share it, so two unions never grow two
    decoders (``what`` only names the refused slot's contract)."""
    tag, slot = _expect_tagged_pair(value, where)
    table: Sequence[DependencyEndpoint]
    if tag == DOMAIN_TAG_MODULE:
        table = modules
    elif tag == DOMAIN_TAG_FILE:
        table = files
    else:
        raise _refuse("W09", f"reference tag {tag!r} is not admitted for {what}")
    ordinal = _expect_ordinal(slot, len(table), where)
    return table[ordinal], (tag, ordinal)


def _decode_relation_triple(
    columns: Mapping[str, list[object]],
    index: int,
    files: Sequence[FileId],
    modules: Sequence[ModuleId],
    family: str,
) -> tuple[DependencyRelationRow, tuple[object, ...]]:
    """One reading of the relation triple, shared by both dependency tables."""
    source, source_key = _decode_endpoint(
        columns["source"][index], files, modules, f"facts.{family}.source[{index}]"
    )
    target, target_key = _decode_endpoint(
        columns["target"][index], files, modules, f"facts.{family}.target[{index}]"
    )
    dependency_type = _expect_string(
        columns["dependency_type"][index],
        f"facts.{family}.dependency_type[{index}]",
    )
    if dependency_type not in IMPORT_TYPES:
        raise _refuse("W08", f"unknown dependency_type tag {dependency_type!r}")
    relation = DependencyRelationRow(source, target, dependency_type)
    return relation, (*source_key, *target_key, dependency_type)


def _decode_dependency_relations(
    facts: Mapping[str, object],
    files: Sequence[FileId],
    modules: Sequence[ModuleId],
) -> tuple[frozenset[DependencyRelationRow], set[tuple[object, ...]]]:
    columns, _flags, row_count = _decode_columns(
        "dependency_relations", facts["dependency_relations"]
    )
    rows = []
    keys = []
    for index in range(row_count):
        relation, key = _decode_relation_triple(
            columns, index, files, modules, "dependency_relations"
        )
        rows.append(relation)
        keys.append(key)
    _expect_strictly_increasing(keys, "facts.dependency_relations")
    return frozenset(rows), set(keys)


def _decode_dependency_occurrences(
    facts: Mapping[str, object],
    files: Sequence[FileId],
    modules: Sequence[ModuleId],
    relation_keys: set[tuple[object, ...]],
) -> frozenset[DependencyOccurrenceRow]:
    columns, flags, row_count = _decode_columns(
        "dependency_occurrences", facts["dependency_occurrences"]
    )
    lazy_positions = flags["is_lazy"]
    rows = []
    keys = []
    for index in range(row_count):
        relation, relation_key = _decode_relation_triple(
            columns, index, files, modules, "dependency_occurrences"
        )
        if relation_key not in relation_keys:
            # The occurrence is evidence BOUND to a relation: a triple that
            # names no relation row is dangling evidence, refused loudly.
            raise _refuse(
                "W26",
                f"facts.dependency_occurrences[{index}] names a relation "
                "the dependency_relations table does not carry",
            )
        binding = _expect_string(
            columns["binding"][index], f"facts.dependency_occurrences.binding[{index}]"
        )
        if binding not in DEPENDENCY_BINDINGS:
            raise _refuse("W08", f"unknown dependency binding tag {binding!r}")
        line = _expect_wire_int(
            columns["line"][index], f"facts.dependency_occurrences.line[{index}]"
        )
        rows.append(
            DependencyOccurrenceRow(relation, line, binding, index in lazy_positions)
        )
        keys.append((*relation_key, line))
    _expect_strictly_increasing(keys, "facts.dependency_occurrences")
    return frozenset(rows)


_DEAD_CODE_ENTITY_TAGS = frozenset(
    {DOMAIN_TAG_SYMBOL, DOMAIN_TAG_MODULE, HEAD_TAG_OPAQUE}
)


def _decode_dead_code_entity(
    value: object,
    symbols: Sequence[SymbolId],
    modules: Sequence[ModuleId],
    where: str,
) -> SymbolId | ModuleSymbol | OpaqueEntity:
    slot = _expect_list(value, where)
    if not slot:
        raise _refuse("W18", f"{where} entity slot is empty")
    tag = _expect_string(slot[0], f"{where}.tag")
    if tag not in _KNOWN_REFERENCE_TAGS:
        raise _refuse("W08", f"unknown reference tag {tag!r}")
    if tag not in _DEAD_CODE_ENTITY_TAGS:
        raise _refuse(
            "W09", f"reference tag {tag!r} is not admitted for a dead-code entity"
        )
    if tag == DOMAIN_TAG_SYMBOL:
        if len(slot) != 2:
            raise _refuse("W18", f"{where} is not a [symbol, ordinal] slot")
        return symbols[_expect_ordinal(slot[1], len(symbols), where)]
    if len(slot) != 3:
        raise _refuse("W18", f"{where} is not a [tag, head, qualname] slot")
    qualname = _expect_string(slot[2], f"{where}.qualname")
    if not qualname:
        raise _refuse("W18", f"{where}.qualname is empty")
    if tag == DOMAIN_TAG_MODULE:
        return ModuleSymbol(
            modules[_expect_ordinal(slot[1], len(modules), where)], qualname
        )
    head = _expect_string(slot[1], f"{where}.head")
    if not head:
        raise _refuse("W18", f"{where}.head is empty")
    return OpaqueEntity(head, qualname)


def _decode_dead_code_markers(value: object, where: str) -> tuple[tuple[str, str], ...]:
    pairs = []
    for position, item in enumerate(_expect_list(value, where)):
        cell = _expect_list(item, f"{where}[{position}]")
        if len(cell) != 2:
            raise _refuse("W18", f"{where}[{position}] is not a [key, value] pair")
        key = _expect_string(cell[0], f"{where}[{position}].key")
        marker = _expect_string(cell[1], f"{where}[{position}].value")
        if not key or not marker:
            raise _refuse("W18", f"{where}[{position}] carries an empty member")
        pairs.append((key, marker))
    _expect_strictly_increasing(
        [(key.encode("utf-8"), marker.encode("utf-8")) for key, marker in pairs],
        where,
    )
    return tuple(pairs)


def _decode_dead_code_row(
    columns: Mapping[str, list[object]],
    flags: Mapping[str, set[int]],
    index: int,
    symbols: Sequence[SymbolId],
    modules: Sequence[ModuleId],
) -> DeadCodeObservationRow:
    prefix = "facts.dead_code_observations"
    observation_kind = _expect_string(
        columns["observation_kind"][index], f"{prefix}.observation_kind[{index}]"
    )
    if observation_kind not in DEAD_CODE_OBSERVATION_KINDS:
        raise _refuse("W08", f"unknown dead-code observation kind {observation_kind!r}")
    candidate_kind = _expect_string(
        columns["candidate_kind"][index], f"{prefix}.candidate_kind[{index}]"
    )
    if candidate_kind not in DEAD_CODE_CANDIDATE_KINDS:
        raise _refuse("W08", f"unknown dead-code candidate kind {candidate_kind!r}")
    reason_raw = _expect_string(
        columns["live_root_reason"][index], f"{prefix}.live_root_reason[{index}]"
    )
    if reason_raw and reason_raw not in LIVE_ROOT_REASONS:
        raise _refuse("W08", f"unknown live root reason {reason_raw!r}")
    abstained = index in flags["abstained"]
    if abstained and reason_raw:
        raise _refuse(
            "W20",
            f"{prefix}[{index}] is abstained and carries a live root — the "
            "two are mutually exclusive by contract",
        )
    return DeadCodeObservationRow(
        entity=_decode_dead_code_entity(
            columns["entity"][index], symbols, modules, f"{prefix}.entity[{index}]"
        ),
        observation_kind=observation_kind,
        start_line=_decode_declaration_site(
            columns["start_line"][index], f"{prefix}.start_line[{index}]"
        ),
        candidate_kind=candidate_kind,
        reference_count=_expect_wire_int(
            columns["reference_count"][index], f"{prefix}.reference_count[{index}]"
        ),
        reachable=index in flags["reachable"],
        runtime_marker_count=_expect_wire_int(
            columns["runtime_marker_count"][index],
            f"{prefix}.runtime_marker_count[{index}]",
        ),
        source_markers=_decode_dead_code_markers(
            columns["source_markers"][index], f"{prefix}.source_markers[{index}]"
        ),
        live_root_reason=reason_raw or None,
        abstained=abstained,
    )


def _decode_declaration_site(value: object, where: str) -> int:
    """A declaration site on the wire: an int in ``[1, 2**31-1]``."""
    start_line = _expect_wire_int(value, where)
    if start_line < 1:
        raise _refuse(
            "W07",
            f"{where} is {start_line}, outside the declaration-site domain "
            "[1, 2**31-1] (a zero site would spell no declaration as a "
            "declaration)",
        )
    return start_line


def _decode_dead_code_observations(
    facts: Mapping[str, object],
    symbols: Sequence[SymbolId],
    modules: Sequence[ModuleId],
) -> frozenset[DeadCodeObservationRow]:
    columns, flags, row_count = _decode_columns(
        "dead_code_observations", facts["dead_code_observations"]
    )
    rows = [
        _decode_dead_code_row(columns, flags, index, symbols, modules)
        for index in range(row_count)
    ]
    _expect_strictly_increasing(
        list(map(_dead_code_wire_key, rows)), "facts.dead_code_observations"
    )
    return frozenset(rows)


def _decode_clone_item(
    value: object, symbols: Sequence[SymbolId], where: str
) -> tuple[tuple[int, int, int], CloneItemRow]:
    cell = _expect_list(value, where)
    if len(cell) != 3:
        raise _refuse("W18", f"{where} is not a [symbol, start, end] cell")
    ordinal = _expect_ordinal(cell[0], len(symbols), where)
    start_line = _expect_wire_int(cell[1], f"{where}.start")
    if start_line < 1:
        raise _refuse(
            "W07",
            f"{where}.start is {start_line}, outside the span domain [1, 2**31-1]",
        )
    end_line = _expect_wire_int(cell[2], f"{where}.end")
    if end_line < start_line:
        raise _refuse("W18", f"{where}.end precedes its start")
    return (ordinal, start_line, end_line), CloneItemRow(
        symbols[ordinal], start_line, end_line
    )


def _decode_clone_groups(
    facts: Mapping[str, object], symbols: Sequence[SymbolId]
) -> frozenset[CloneGroupRow]:
    columns, _flags, row_count = _decode_columns("clone_groups", facts["clone_groups"])
    rows = []
    keys = []
    for index in range(row_count):
        kind = _expect_string(
            columns["clone_kind"][index], f"facts.clone_groups.clone_kind[{index}]"
        )
        if kind not in CLONE_KINDS:
            raise _refuse("W08", f"unknown clone kind tag {kind!r}")
        group_key = _expect_string(
            columns["group_key"][index], f"facts.clone_groups.group_key[{index}]"
        )
        if not group_key:
            raise _refuse("W18", f"facts.clone_groups.group_key[{index}] is empty")
        where = f"facts.clone_groups.items[{index}]"
        cells = _expect_list(columns["items"][index], where)
        if len(cells) < 2:
            raise _refuse(
                "W18",
                f"{where} names fewer than two members (a group of one is "
                "not a grouping the producer makes)",
            )
        decoded = [_decode_clone_item(cell, symbols, where) for cell in cells]
        _expect_strictly_increasing([key for key, _item in decoded], where)
        rows.append(
            CloneGroupRow(kind, group_key, frozenset(item for _key, item in decoded))
        )
        keys.append((kind.encode("utf-8"), group_key.encode("utf-8")))
    _expect_strictly_increasing(keys, "facts.clone_groups")
    return frozenset(rows)


def _decode_dependency_cycles(
    facts: Mapping[str, object], modules: Sequence[ModuleId]
) -> frozenset[DependencyCycleRow]:
    columns, _flags, row_count = _decode_columns(
        "dependency_cycles", facts["dependency_cycles"]
    )
    rows = []
    keys = []
    for index in range(row_count):
        kind = _expect_string(
            columns["kind"][index], f"facts.dependency_cycles.kind[{index}]"
        )
        if kind not in DEPENDENCY_CYCLE_KINDS:
            raise _refuse("W08", f"unknown dependency cycle kind tag {kind!r}")
        where = f"facts.dependency_cycles.modules[{index}]"
        ordinals = [
            _expect_ordinal(item, len(modules), where)
            for item in _expect_list(columns["modules"][index], where)
        ]
        _expect_increasing_elements(ordinals, where)
        if len(ordinals) < 2:
            raise _refuse(
                "W18",
                f"{where} names fewer than two modules (a cycle has no "
                "self-loops: the producer's Tarjan floor)",
            )
        rows.append(DependencyCycleRow(kind, frozenset(modules[o] for o in ordinals)))
        keys.append(tuple(ordinals))
    # The module-set tuple is the entity key: a duplicate set — with any
    # kind — refuses in-band (W13), spelling the classified-once law.
    _expect_strictly_increasing(keys, "facts.dependency_cycles")
    return frozenset(rows)


def _decode_coupling_cohesion(
    facts: Mapping[str, object], symbols: Sequence[SymbolId]
) -> frozenset[CouplingCohesionRow]:
    columns, _flags, row_count = _decode_columns(
        "coupling_cohesion_observations", facts["coupling_cohesion_observations"]
    )
    rows = []
    keys = []
    for index in range(row_count):
        dimension = _expect_string(
            columns["dimension"][index],
            f"facts.coupling_cohesion_observations.dimension[{index}]",
        )
        if dimension not in COUPLING_COHESION_DIMENSIONS:
            raise _refuse(
                "W08", f"unknown coupling/cohesion dimension tag {dimension!r}"
            )
        numerator = _expect_wire_int(
            columns["numerator"][index],
            f"facts.coupling_cohesion_observations.numerator[{index}]",
        )
        if numerator < 1:
            raise _refuse(
                "W07",
                f"facts.coupling_cohesion_observations.numerator[{index}] "
                f"is {numerator}, outside the family's declared domain "
                "[1, 2**31-1] (a zero row would present absence as a "
                "measured value)",
            )
        ordinal = _expect_ordinal(
            columns["symbol"][index],
            len(symbols),
            f"facts.coupling_cohesion_observations.symbol[{index}]",
        )
        rows.append(CouplingCohesionRow(symbols[ordinal], dimension, numerator))
        keys.append((ordinal, dimension.encode("utf-8")))
    _expect_strictly_increasing(keys, "facts.coupling_cohesion_observations")
    return frozenset(rows)


def _decode_risk_observations(
    facts: Mapping[str, object], symbols: Sequence[SymbolId]
) -> frozenset[RiskObservationRow]:
    columns, _flags, row_count = _decode_columns(
        "risk_observations", facts["risk_observations"]
    )
    rows = []
    keys = []
    for index in range(row_count):
        dimension = _expect_string(
            columns["dimension"][index],
            f"facts.risk_observations.dimension[{index}]",
        )
        if dimension not in RISK_DIMENSIONS:
            raise _refuse("W08", f"unknown risk dimension tag {dimension!r}")
        numerator = _expect_wire_int(
            columns["numerator"][index],
            f"facts.risk_observations.numerator[{index}]",
        )
        if numerator < 1:
            raise _refuse(
                "W07",
                f"facts.risk_observations.numerator[{index}] is "
                f"{numerator}, outside the family's declared domain "
                "[1, 2**31-1] (a zero row would present absence as a "
                "measured value)",
            )
        start_line = _expect_wire_int(
            columns["start_line"][index],
            f"facts.risk_observations.start_line[{index}]",
        )
        if start_line < 1:
            raise _refuse(
                "W07",
                f"facts.risk_observations.start_line[{index}] is "
                f"{start_line}, outside the declaration-site domain "
                "[1, 2**31-1] (a zero site would spell no declaration "
                "as a declaration)",
            )
        ordinal = _expect_ordinal(
            columns["symbol"][index],
            len(symbols),
            f"facts.risk_observations.symbol[{index}]",
        )
        rows.append(
            RiskObservationRow(symbols[ordinal], dimension, numerator, start_line)
        )
        keys.append((ordinal, dimension.encode("utf-8"), start_line))
    _expect_strictly_increasing(keys, "facts.risk_observations")
    return frozenset(rows)


def _decode_unit_spans(
    facts: Mapping[str, object], symbols: Sequence[SymbolId]
) -> frozenset[UnitSpanRow]:
    columns, _flags, row_count = _decode_columns("unit_spans", facts["unit_spans"])
    rows = []
    keys = []
    for index in range(row_count):
        start_line = _expect_wire_int(
            columns["start_line"][index],
            f"facts.unit_spans.start_line[{index}]",
        )
        if start_line < 1:
            raise _refuse(
                "W07",
                f"facts.unit_spans.start_line[{index}] is "
                f"{start_line}, outside the declaration-site domain "
                "[1, 2**31-1] (a zero site would spell no declaration "
                "as a declaration)",
            )
        end_line = _expect_wire_int(
            columns["end_line"][index],
            f"facts.unit_spans.end_line[{index}]",
        )
        if end_line < start_line:
            raise _refuse(
                "W07",
                f"facts.unit_spans.end_line[{index}] is {end_line}, before "
                f"its own start {start_line} (a span is a range, and a "
                "backwards one would answer with a value no source had)",
            )
        ordinal = _expect_ordinal(
            columns["symbol"][index],
            len(symbols),
            f"facts.unit_spans.symbol[{index}]",
        )
        rows.append(UnitSpanRow(symbols[ordinal], start_line, end_line))
        keys.append((ordinal, start_line))
    _expect_strictly_increasing(keys, "facts.unit_spans")
    return frozenset(rows)


def _decode_api_parameter(value: object, where: str) -> ApiParameterFact:
    cell = _expect_list(value, where)
    if len(cell) not in (3, 4):
        raise _refuse(
            "W18", f"{where} is not a [name, kind, default, annotation?] cell"
        )
    name = _expect_string(cell[0], f"{where}.name")
    if not name:
        raise _refuse("W18", f"{where}.name is empty")
    kind = _expect_string(cell[1], f"{where}.kind")
    if kind not in API_PARAMETER_KINDS:
        raise _refuse("W08", f"unknown api parameter kind tag {kind!r}")
    default_marker = _expect_wire_int(cell[2], f"{where}.default")
    if default_marker not in (0, 1):
        raise _refuse("W18", f"{where}.default is not a 0/1 marker")
    annotation: str | None = None
    if len(cell) == 4:
        annotation = _expect_string(cell[3], f"{where}.annotation")
        if not annotation:
            # An empty annotation digest would spell absence as a value;
            # the canonical spelling of absence is the omitted slot.
            raise _refuse("W18", f"{where}.annotation is empty")
    return ApiParameterFact(name, kind, default_marker == 1, annotation)


def _decode_api_symbols(
    facts: Mapping[str, object], symbols: Sequence[SymbolId]
) -> frozenset[ApiSymbolRow]:
    columns, _flags, row_count = _decode_columns("api_symbols", facts["api_symbols"])
    rows = []
    keys = []
    for index in range(row_count):
        ordinal = _expect_ordinal(
            columns["symbol"][index],
            len(symbols),
            f"facts.api_symbols.symbol[{index}]",
        )
        symbol_kind = _expect_string(
            columns["symbol_kind"][index], f"facts.api_symbols.symbol_kind[{index}]"
        )
        if symbol_kind not in API_SYMBOL_KINDS:
            raise _refuse("W08", f"unknown api symbol kind tag {symbol_kind!r}")
        visibility = _expect_string(
            columns["visibility"][index], f"facts.api_symbols.visibility[{index}]"
        )
        if visibility not in API_VISIBILITIES:
            raise _refuse("W08", f"unknown api visibility tag {visibility!r}")
        parameters = tuple(
            _decode_api_parameter(item, f"facts.api_symbols.parameters[{index}]")
            for item in _expect_list(
                columns["parameters"][index],
                f"facts.api_symbols.parameters[{index}]",
            )
        )
        returns_raw = _expect_string(
            columns["returns_digest"][index],
            f"facts.api_symbols.returns_digest[{index}]",
        )
        declared_variant = _expect_string(
            columns["signature_variant"][index],
            f"facts.api_symbols.signature_variant[{index}]",
        )
        returns_digest = returns_raw or None
        expected_variant = signature_variant(
            parameters=parameters, returns_digest=returns_digest
        )
        if declared_variant != expected_variant:
            raise _refuse(
                "W25",
                f"facts.api_symbols.signature_variant[{index}] does not "
                "match its formula owner",
            )
        rows.append(
            ApiSymbolRow(
                symbols[ordinal], symbol_kind, visibility, parameters, returns_digest
            )
        )
        keys.append((ordinal, declared_variant.encode("utf-8")))
    _expect_strictly_increasing(keys, "facts.api_symbols")
    return frozenset(rows)


def _decode_adoption_counts(
    facts: Mapping[str, object],
    files: Sequence[FileId],
    modules: Sequence[ModuleId],
) -> frozenset[AdoptionCountRow]:
    columns, _flags, row_count = _decode_columns(
        "adoption_counts", facts["adoption_counts"]
    )
    rows = []
    keys = []
    for index in range(row_count):
        scope, scope_key = _decode_endpoint(
            columns["scope"][index],
            files,
            modules,
            f"facts.adoption_counts.scope[{index}]",
            what="an adoption scope",
        )
        feature = _expect_string(
            columns["feature"][index], f"facts.adoption_counts.feature[{index}]"
        )
        if feature not in ADOPTION_FEATURES:
            raise _refuse("W08", f"unknown adoption feature tag {feature!r}")
        numerator = _expect_wire_int(
            columns["numerator"][index],
            f"facts.adoption_counts.numerator[{index}]",
        )
        denominator = _expect_wire_int(
            columns["denominator"][index],
            f"facts.adoption_counts.denominator[{index}]",
        )
        if denominator < 1:
            raise _refuse(
                "W07",
                f"facts.adoption_counts.denominator[{index}] is "
                f"{denominator}, outside the family's declared domain "
                "[1, 2**31-1] (the producer drops zero-denominator scopes, "
                "so a stored zero would present an unmeasured scope as "
                "measured)",
            )
        if numerator > denominator:
            raise _refuse(
                "W18",
                f"facts.adoption_counts.numerator[{index}] exceeds its "
                f"denominator ({numerator} of {denominator})",
            )
        rows.append(AdoptionCountRow(scope, feature, numerator, denominator))
        keys.append((*scope_key, feature.encode("utf-8")))
    _expect_strictly_increasing(keys, "facts.adoption_counts")
    return frozenset(rows)


_SURFACE_VOCABULARIES: dict[str, tuple[str, ...]] = {
    "category": SECURITY_SURFACE_CATEGORIES,
    "classification_mode": SECURITY_CLASSIFICATION_MODES,
    "evidence_kind": SECURITY_EVIDENCE_KINDS,
    "location_scope": SECURITY_LOCATION_SCOPES,
    "source_kind": SECURITY_SOURCE_KINDS,
}


def _decode_security_surface_row(
    columns: Mapping[str, list[object]],
    index: int,
    files: Sequence[FileId],
) -> tuple[SecuritySurfaceRow, tuple[object, ...]]:
    prefix = "facts.security_surfaces"
    vocabulary_values: dict[str, str] = {}
    for column, vocabulary in _SURFACE_VOCABULARIES.items():
        value = _expect_string(columns[column][index], f"{prefix}.{column}[{index}]")
        if value not in vocabulary:
            raise _refuse(
                "W08", f"unknown surface {column.replace('_', ' ')} tag {value!r}"
            )
        vocabulary_values[column] = value
    ordinal = _expect_ordinal(
        columns["file"][index], len(files), f"{prefix}.file[{index}]"
    )
    evidence_symbol = _expect_string(
        columns["evidence_symbol"][index], f"{prefix}.evidence_symbol[{index}]"
    )
    if not evidence_symbol:
        raise _refuse("W18", f"{prefix}.evidence_symbol[{index}] is empty")
    capability = _expect_string(
        columns["capability"][index], f"{prefix}.capability[{index}]"
    )
    if not capability:
        raise _refuse("W18", f"{prefix}.capability[{index}] is empty")
    start_line = _expect_wire_int(
        columns["start_line"][index], f"{prefix}.start_line[{index}]"
    )
    if start_line < 1:
        raise _refuse(
            "W07",
            f"{prefix}.start_line[{index}] is {start_line}, outside the "
            "span domain [1, 2**31-1]",
        )
    end_line = _expect_wire_int(
        columns["end_line"][index], f"{prefix}.end_line[{index}]"
    )
    if end_line < start_line:
        raise _refuse("W18", f"{prefix}.end_line[{index}] precedes its start")
    qualname_raw = _expect_string(
        columns["qualname"][index], f"{prefix}.qualname[{index}]"
    )
    location_scope = vocabulary_values["location_scope"]
    if location_scope == "module" and qualname_raw:
        raise _refuse(
            "W20",
            f"{prefix}[{index}] is module-scope and carries a local name "
            "-- the head is the file itself",
        )
    if location_scope != "module" and not qualname_raw:
        raise _refuse(
            "W20",
            f"{prefix}[{index}] is {location_scope}-scope and carries no local name",
        )
    row = SecuritySurfaceRow(
        file=files[ordinal],
        start_line=start_line,
        end_line=end_line,
        evidence_symbol=evidence_symbol,
        qualname=qualname_raw or None,
        location_scope=location_scope,
        category=vocabulary_values["category"],
        capability=capability,
        evidence_kind=vocabulary_values["evidence_kind"],
        classification_mode=vocabulary_values["classification_mode"],
        source_kind=vocabulary_values["source_kind"],
    )
    return row, (ordinal, start_line, evidence_symbol.encode("utf-8"))


def _decode_security_surfaces(
    facts: Mapping[str, object], files: Sequence[FileId]
) -> frozenset[SecuritySurfaceRow]:
    columns, _flags, row_count = _decode_columns(
        "security_surfaces", facts["security_surfaces"]
    )
    rows = []
    keys = []
    for index in range(row_count):
        row, key = _decode_security_surface_row(columns, index, files)
        rows.append(row)
        keys.append(key)
    _expect_strictly_increasing(keys, "facts.security_surfaces")
    return frozenset(rows)


def _decode_string_pairs(value: object, where: str) -> list[tuple[str, str]]:
    """A wire list of two-string pairs, shape-checked pair by pair."""
    pairs = _expect_list(value, where)
    decoded: list[tuple[str, str]] = []
    for index, pair in enumerate(pairs):
        items = _expect_list(pair, f"{where}[{index}]")
        if len(items) != 2:
            raise _refuse("W01", f"{where}[{index}] is not a two-element pair")
        decoded.append(
            (
                _expect_string(items[0], f"{where}[{index}][0]"),
                _expect_string(items[1], f"{where}[{index}][1]"),
            )
        )
    return decoded


def _decode_analysis_population(
    facts: Mapping[str, object],
) -> AnalysisPopulation | None:
    """The execution-population record member, or its typed absence."""
    where = "facts.analysis_population"
    value = facts["analysis_population"]
    if not isinstance(value, dict):
        raise _refuse("W01", f"{where} is not an object")
    table = cast("dict[str, object]", value)
    keys = list(table.keys())
    if not keys:
        return None
    declared = list(wire_columns("analysis_population"))
    if set(keys) != set(declared):
        raise _refuse(
            "W01",
            f"{where} keys {keys!r} do not match the declared set {declared!r}",
        )
    if keys != declared:
        raise _refuse("W02", f"{where} keys are not in canonical order")
    mode = _expect_string(table["analysis_mode"], f"{where}.analysis_mode")
    if not mode:
        raise _refuse("W18", f"{where}.analysis_mode is empty")
    profile_pairs = _expect_list(table["analysis_profile"], f"{where}.analysis_profile")
    profile: list[tuple[str, int]] = []
    for index, pair in enumerate(profile_pairs):
        pair_where = f"{where}.analysis_profile[{index}]"
        items = _expect_list(pair, pair_where)
        if len(items) != 2:
            raise _refuse("W01", f"{pair_where} is not a two-element pair")
        profile.append(
            (
                _expect_string(items[0], f"{pair_where}[0]"),
                _expect_wire_int(items[1], f"{pair_where}[1]"),
            )
        )
    states = _decode_string_pairs(table["producer_states"], f"{where}.producer_states")
    for family, state in states:
        if state not in PRODUCER_EXECUTION_STATES:
            raise _refuse(
                "W08",
                f"{where}.producer_states carries unknown execution state "
                f"{state!r} for family {family!r}",
            )
    for name, pairs in (
        ("analysis_profile", [name for name, _v in profile]),
        ("producer_states", [family for family, _s in states]),
    ):
        if pairs != sorted(set(pairs)):
            raise _refuse("W02", f"{where}.{name} pairs are not sorted and unique")
    return AnalysisPopulation(
        analysis_mode=mode,
        analysis_profile=tuple(profile),
        producer_states=tuple(states),
    )


def _decode_run_scalars(facts: Mapping[str, object]) -> RunScalars | None:
    """The F9 record member: one record object, or its typed absence."""
    value = facts["run_scalars"]
    if not isinstance(value, dict):
        raise _refuse("W01", "facts.run_scalars is not an object")
    table = cast("dict[str, object]", value)
    keys = list(table.keys())
    if not keys:
        return None
    declared = list(wire_columns("run_scalars"))
    if set(keys) != set(declared):
        raise _refuse(
            "W01",
            f"facts.run_scalars keys {keys!r} do not match the declared "
            f"set {declared!r}",
        )
    if keys != declared:
        raise _refuse("W02", "facts.run_scalars keys are not in canonical order")
    values = {
        name: _expect_wire_int(table[name], f"facts.run_scalars.{name}")
        for name in declared
    }
    return RunScalars(**values)


# ---------------------------------------------------------------------------
# Canonical epoch E1: the finding-group, coverage and overloaded families.
# ---------------------------------------------------------------------------

_ConstructedT = TypeVar("_ConstructedT")


def _construct(
    where: str, factory: Callable[..., _ConstructedT], *args: object, **kwargs: object
) -> _ConstructedT:
    """Build one row through its model law, refusing typed (W18) when the
    law refuses: a model error must never escape the decoder untyped."""
    try:
        return factory(*args, **kwargs)
    except CanonicalModelError as error:
        raise _refuse("W18", f"{where}: {error}") from error


def _expect_wire_float(value: object, where: str) -> float:
    """One float cell: finite by the parser's own refusal (W06), typed here.

    An integer lexeme is refused where a float is declared: the writer emits
    ``repr(float)`` and ``1`` is not the canonical form of ``1.0`` (W24)."""
    if isinstance(value, bool) or not isinstance(value, float):
        raise _refuse("W18", f"{where} is not a float lexeme")
    if value < 0.0:
        raise _refuse("W07", f"{where} float {value!r} is negative")
    return value


def _decode_site(
    columns: Mapping[str, list[object]],
    family: str,
    index: int,
    symbols: Sequence[SymbolId],
) -> tuple[tuple[int, int], SymbolId, int, int]:
    """The declaration-site columns of one E1 row: ``(symbol, start_line,
    end_line)`` under the ``unit_spans`` laws (positive site, a range end
    never before its start), plus the row's canonical order key."""
    where = f"facts.{family}"
    ordinal = _expect_ordinal(
        columns["symbol"][index], len(symbols), f"{where}.symbol[{index}]"
    )
    start_line = _expect_wire_int(
        columns["start_line"][index], f"{where}.start_line[{index}]"
    )
    if start_line < 1:
        raise _refuse("W07", f"{where}.start_line[{index}] is {start_line}, not a site")
    end_line = _expect_wire_int(
        columns["end_line"][index], f"{where}.end_line[{index}]"
    )
    if end_line < start_line:
        raise _refuse("W07", f"{where}.end_line[{index}] precedes its start")
    return (ordinal, start_line), symbols[ordinal], start_line, end_line


def _decode_member_cells(
    value: object, symbols: Sequence[SymbolId], where: str, *, floor: int
) -> frozenset[CloneItemRow]:
    """A sorted member-cell list of at least ``floor`` sites."""
    cells = _expect_list(value, where)
    if len(cells) < floor:
        raise _refuse("W18", f"{where} names fewer than {floor} members")
    decoded = [_decode_clone_item(cell, symbols, where) for cell in cells]
    _expect_strictly_increasing([key for key, _item in decoded], where)
    return frozenset(item for _key, item in decoded)


def _decode_group_keyed_rows(
    family: str,
    facts: Mapping[str, object],
    kind_column: str,
    key_column: str,
    kinds: tuple[str, ...],
) -> Iterator[tuple[int, str, str, Mapping[str, list[object]]]]:
    """The producer-keyed E1 families: rows ordered by ``(kind, key)``
    bytes, the kind a closed vocabulary and the key non-empty."""
    columns, _flags, row_count = _decode_columns(family, facts[family])
    keys = []
    for index in range(row_count):
        where = f"facts.{family}"
        kind = _expect_vocabulary(
            columns[kind_column][index],
            kinds,
            f"{where}.{kind_column}[{index}]",
            kind_column,
        )
        key = _expect_string(
            columns[key_column][index], f"{where}.{key_column}[{index}]"
        )
        if not key:
            raise _refuse("W18", f"{where}.{key_column}[{index}] is empty")
        keys.append((kind.encode("utf-8"), key.encode("utf-8")))
        yield index, kind, key, columns
    _expect_strictly_increasing(keys, f"facts.{family}")


def _decode_suppressed_clone_groups(
    facts: Mapping[str, object], symbols: Sequence[SymbolId]
) -> frozenset[SuppressedCloneGroupRow]:
    rows = []
    for index, kind, key, columns in _decode_group_keyed_rows(
        "suppressed_clone_groups", facts, "clone_kind", "group_key", CLONE_KINDS
    ):
        where = f"facts.suppressed_clone_groups[{index}]"
        rows.append(
            _construct(
                where,
                SuppressedCloneGroupRow,
                clone_kind=kind,
                group_key=key,
                items=_decode_member_cells(
                    columns["items"][index], symbols, f"{where}.items", floor=2
                ),
                suppression_rule=_expect_string(
                    columns["suppression_rule"][index], f"{where}.suppression_rule"
                ),
                suppression_source=_expect_string(
                    columns["suppression_source"][index],
                    f"{where}.suppression_source",
                ),
                matched_patterns=tuple(
                    _decode_strings(
                        columns["matched_patterns"][index],
                        f"{where}.matched_patterns",
                    )
                ),
            )
        )
    return frozenset(rows)


def _decode_structural_groups(
    facts: Mapping[str, object], symbols: Sequence[SymbolId]
) -> frozenset[StructuralGroupRow]:
    rows = []
    for index, kind, key, columns in _decode_group_keyed_rows(
        "structural_groups",
        facts,
        "finding_kind",
        "finding_key",
        STRUCTURAL_FINDING_KINDS,
    ):
        where = f"facts.structural_groups[{index}]"
        signature = _decode_string_pairs(
            columns["signature"][index], f"{where}.signature"
        )
        _expect_strictly_increasing(
            [(pair[0].encode("utf-8"),) for pair in signature], f"{where}.signature"
        )
        rows.append(
            _construct(
                where,
                StructuralGroupRow,
                finding_kind=kind,
                finding_key=key,
                signature=tuple(signature),
                occurrences=_decode_member_cells(
                    columns["occurrences"][index],
                    symbols,
                    f"{where}.occurrences",
                    floor=1,
                ),
            )
        )
    return frozenset(rows)


def _decode_site_rows(
    family: str,
    facts: Mapping[str, object],
    symbols: Sequence[SymbolId],
    build: Callable[
        [Mapping[str, list[object]], int, SymbolId, int, int], _ConstructedT
    ],
) -> frozenset[_ConstructedT]:
    """The six site-keyed E1 families through one row walk: decode the
    site, hand the remaining columns to the family's builder, prove the
    canonical order."""
    columns, _flags, row_count = _decode_columns(family, facts[family])
    rows: list[_ConstructedT] = []
    keys = []
    for index in range(row_count):
        key, symbol, start_line, end_line = _decode_site(
            columns, family, index, symbols
        )
        rows.append(
            _construct(
                f"facts.{family}[{index}]",
                build,
                columns,
                index,
                symbol,
                start_line,
                end_line,
            )
        )
        keys.append(key)
    _expect_strictly_increasing(keys, f"facts.{family}")
    return frozenset(rows)


def _column_int(
    columns: Mapping[str, list[object]], family: str, name: str, index: int
) -> int:
    return _expect_wire_int(columns[name][index], f"facts.{family}.{name}[{index}]")


def _column_words(
    columns: Mapping[str, list[object]],
    family: str,
    name: str,
    index: int,
    vocabulary: tuple[str, ...],
) -> str:
    return _expect_vocabulary(
        columns[name][index], vocabulary, f"facts.{family}.{name}[{index}]", name
    )


def _dead_symbol_group(
    columns: Mapping[str, list[object]],
    index: int,
    symbol: SymbolId,
    start_line: int,
    end_line: int,
) -> DeadSymbolGroupRow:
    family = "dead_symbol_groups"
    return DeadSymbolGroupRow(
        symbol=symbol,
        start_line=start_line,
        end_line=end_line,
        candidate_kind=_column_words(
            columns, family, "candidate_kind", index, DEAD_CODE_CANDIDATE_KINDS
        ),
        confidence=_column_words(
            columns, family, "confidence", index, DEAD_SYMBOL_CONFIDENCES
        ),
        reason=_column_words(columns, family, "reason", index, DEAD_SYMBOL_REASONS),
        test_reference_sources=tuple(
            _decode_strings(
                columns["test_reference_sources"][index],
                f"facts.{family}.test_reference_sources[{index}]",
            )
        ),
    )


def _unreachable_statement(
    columns: Mapping[str, list[object]],
    index: int,
    symbol: SymbolId,
    start_line: int,
    end_line: int,
) -> UnreachableStatementRow:
    family = "unreachable_statement_groups"
    return UnreachableStatementRow(
        symbol=symbol,
        start_line=start_line,
        end_line=end_line,
        reason=_column_words(columns, family, "reason", index, UNREACHABLE_REASONS),
        statement_count=_column_int(columns, family, "statement_count", index),
    )


def _complexity_hotspot(
    columns: Mapping[str, list[object]],
    index: int,
    symbol: SymbolId,
    start_line: int,
    end_line: int,
) -> ComplexityHotspotRow:
    family = "complexity_hotspots"
    return ComplexityHotspotRow(
        symbol=symbol,
        start_line=start_line,
        end_line=end_line,
        cyclomatic_complexity=_column_int(
            columns, family, "cyclomatic_complexity", index
        ),
        nesting_depth=_column_int(columns, family, "nesting_depth", index),
    )


def _coupling_hotspot(
    columns: Mapping[str, list[object]],
    index: int,
    symbol: SymbolId,
    start_line: int,
    end_line: int,
) -> CouplingHotspotRow:
    family = "coupling_hotspots"
    return CouplingHotspotRow(
        symbol=symbol,
        start_line=start_line,
        end_line=end_line,
        cbo=_column_int(columns, family, "cbo", index),
        coupled_classes=tuple(
            _decode_strings(
                columns["coupled_classes"][index],
                f"facts.{family}.coupled_classes[{index}]",
            )
        ),
    )


def _cohesion_hotspot(
    columns: Mapping[str, list[object]],
    index: int,
    symbol: SymbolId,
    start_line: int,
    end_line: int,
) -> CohesionHotspotRow:
    family = "cohesion_hotspots"
    return CohesionHotspotRow(
        symbol=symbol,
        start_line=start_line,
        end_line=end_line,
        lcom4=_column_int(columns, family, "lcom4", index),
        method_count=_column_int(columns, family, "method_count", index),
        instance_var_count=_column_int(columns, family, "instance_var_count", index),
    )


def _coverage_unit(
    columns: Mapping[str, list[object]],
    index: int,
    symbol: SymbolId,
    start_line: int,
    end_line: int,
) -> CoverageUnitRow:
    family = "coverage_units"
    return CoverageUnitRow(
        symbol=symbol,
        start_line=start_line,
        end_line=end_line,
        executable_lines=_column_int(columns, family, "executable_lines", index),
        covered_lines=_column_int(columns, family, "covered_lines", index),
        coverage_status=_column_words(
            columns, family, "coverage_status", index, COVERAGE_UNIT_STATUSES
        ),
    )


def _decode_overloaded_modules(
    facts: Mapping[str, object], files: Sequence[FileId]
) -> frozenset[OverloadedModuleRow]:
    family = "overloaded_modules"
    columns, _flags, row_count = _decode_columns(family, facts[family])
    rows = []
    ordinals = []
    for index in range(row_count):
        where = f"facts.{family}"
        ordinal = _expect_ordinal(
            columns["file"][index], len(files), f"{where}.file[{index}]"
        )
        counters = {
            name: _column_int(columns, family, name, index)
            for name in OVERLOADED_MODULE_COUNTERS
        }
        scores = {
            name: _expect_wire_float(columns[name][index], f"{where}.{name}[{index}]")
            for name in OVERLOADED_MODULE_SCORES
        }
        rows.append(
            _construct(
                f"{where}[{index}]",
                overloaded_module_row,
                file=files[ordinal],
                source_kind=_column_words(
                    columns, family, "source_kind", index, SECURITY_SOURCE_KINDS
                ),
                candidate_status=_column_words(
                    columns,
                    family,
                    "candidate_status",
                    index,
                    OVERLOADED_CANDIDATE_STATUSES,
                ),
                candidate_reasons=tuple(
                    _decode_strings(
                        columns["candidate_reasons"][index],
                        f"{where}.candidate_reasons[{index}]",
                    )
                ),
                counters=counters,
                scores=scores,
            )
        )
        ordinals.append((ordinal,))
    _expect_strictly_increasing(ordinals, f"facts.{family}")
    return frozenset(rows)


def _record_member(
    family: str, facts: Mapping[str, object]
) -> Mapping[str, object] | None:
    """One record wire member (the F9 shape): its declared keys in order,
    or ``None`` for the empty member — the typed absence."""
    where = f"facts.{family}"
    value = facts[family]
    if not isinstance(value, dict):
        raise _refuse("W01", f"{where} is not an object")
    table = cast("dict[str, object]", value)
    keys = list(table.keys())
    if not keys:
        return None
    declared = list(wire_columns(family))
    if set(keys) != set(declared):
        raise _refuse(
            "W01", f"{where} keys {keys!r} do not match the declared set {declared!r}"
        )
    if keys != declared:
        raise _refuse("W02", f"{where} keys are not in canonical order")
    return table


def _decode_coverage_join(facts: Mapping[str, object]) -> CoverageJoinRecord | None:
    family = "coverage_join"
    table = _record_member(family, facts)
    if table is None:
        return None
    where = f"facts.{family}"
    reason = _expect_string(table["invalid_reason"], f"{where}.invalid_reason")
    return _construct(
        where,
        CoverageJoinRecord,
        status=_expect_vocabulary(
            table["status"], COVERAGE_JOIN_STATUSES, f"{where}.status", "status"
        ),
        source=_expect_string(table["source"], f"{where}.source"),
        files=_expect_wire_int(table["files"], f"{where}.files"),
        hotspot_threshold_percent=_expect_wire_int(
            table["hotspot_threshold_percent"], f"{where}.hotspot_threshold_percent"
        ),
        invalid_reason=reason or None,
    )


def _decode_dead_code_summary(
    facts: Mapping[str, object],
) -> DeadCodeSummaryRecord | None:
    family = "dead_code_summary"
    table = _record_member(family, facts)
    if table is None:
        return None
    where = f"facts.{family}"
    counters = {
        name: _expect_wire_int(table[name], f"{where}.{name}")
        for name in wire_columns(family)
        if name != "world_contract"
    }
    return _construct(
        where,
        DeadCodeSummaryRecord,
        world_contract=_expect_vocabulary(
            table["world_contract"],
            WORLD_CONTRACTS,
            f"{where}.world_contract",
            "world_contract",
        ),
        **counters,
    )


def _decode_source_location(
    value: object, files: Sequence[FileId], where: str
) -> SourceLocation:
    """One ``[tag, ref, line]`` evidence cell, read back into its variant."""
    cell = _expect_list(value, where)
    if len(cell) != 3:
        raise _refuse("W18", f"{where} is not a [tag, ref, line] cell")
    tag = _expect_string(cell[0], f"{where}.tag")
    line = _expect_wire_int(cell[2], f"{where}.line")
    if tag == DOMAIN_TAG_FILE:
        return FileLine(files[_expect_ordinal(cell[1], len(files), where)], line)
    if tag == LOCATION_TAG_UNRESOLVED:
        return UnresolvedLocation(_expect_string(cell[1], f"{where}.path"), line)
    raise _refuse("W09", f"reference tag {tag!r} is not admitted for a source location")


def _decode_source_locations(
    value: object, files: Sequence[FileId], where: str
) -> tuple[SourceLocation, ...]:
    """The evidence tuple, proved to carry the model's own ordering law.

    ``_expect_strictly_increasing`` over ``source_location_key`` is the same
    law ``ViolationRow`` enforces, read through the same owner — so the wire
    refuses a reordered or collapsed tuple as a typed W02 instead of letting
    a model error escape the decoder, and neither side can drift from the
    other without moving that one function.
    """
    locations = tuple(
        _decode_source_location(cell, files, f"{where}[{position}]")
        for position, cell in enumerate(_expect_list(value, where))
    )
    _expect_strictly_increasing(
        [source_location_key(location) for location in locations], where
    )
    return locations


def _decode_strings(value: object, where: str) -> list[str]:
    """One string column cell that holds a list of strings."""
    return [
        _expect_string(item, f"{where}[{position}]")
        for position, item in enumerate(_expect_list(value, where))
    ]


def _expect_vocabulary(
    value: object, vocabulary: tuple[str, ...], where: str, what: str
) -> str:
    """One closed-vocabulary cell: a string, and a member (W08)."""
    text = _expect_string(value, where)
    if text not in vocabulary:
        raise _refuse("W08", f"unknown {what} tag {text!r}")
    return text


def _decode_target_slot(
    value: object, admitted: frozenset[str], where: str, what: str
) -> tuple[list[object], str]:
    """The shared prologue of the two revision-2 target slots: a non-empty
    list, a known reference tag (W08), and one admitted for this slot (W09).
    One spelling, so the two unions never grow two readings of a tag."""
    slot = _expect_list(value, where)
    if not slot:
        raise _refuse("W18", f"{where} target slot is empty")
    tag = _expect_string(slot[0], f"{where}.tag")
    if tag not in _KNOWN_REFERENCE_TAGS:
        raise _refuse("W08", f"unknown reference tag {tag!r}")
    if tag not in admitted:
        raise _refuse("W09", f"reference tag {tag!r} is not admitted for {what}")
    return slot, tag


def _decode_import_target(
    value: object,
    files: Sequence[FileId],
    modules: Sequence[ModuleId],
    where: str,
) -> tuple[ImportTarget, tuple[object, ...]]:
    """One tagged import-target slot and its order key."""
    slot, tag = _decode_target_slot(
        value, _IMPORT_TARGET_TAGS, where, "an import target"
    )
    if tag == TARGET_TAG_UNRESOLVED:
        if len(slot) != 1:
            raise _refuse("W18", f"{where} unresolved target carries a value")
        return UnresolvedTarget(), (tag, 0)
    if tag == HEAD_TAG_OPAQUE:
        if len(slot) != 2:
            raise _refuse("W18", f"{where} is not an [opaque, text] slot")
        text = _expect_string(slot[1], f"{where}.text")
        if not text:
            raise _refuse("W18", f"{where} opaque head is empty")
        return OpaqueDottedHead(text), (tag, text)
    endpoint, key = _decode_endpoint(value, files, modules, where, "an import target")
    return endpoint, key


def _decode_import_observations(
    facts: Mapping[str, object],
    files: Sequence[FileId],
    modules: Sequence[ModuleId],
) -> frozenset[ImportObservationRow]:
    prefix = "facts.import_observations"
    columns, flags, row_count = _decode_columns(
        "import_observations", facts["import_observations"]
    )
    rows = []
    keys = []
    for index in range(row_count):
        source, source_key = _decode_endpoint(
            columns["source"][index], files, modules, f"{prefix}.source[{index}]"
        )
        target, target_key = _decode_import_target(
            columns["target"][index], files, modules, f"{prefix}.target[{index}]"
        )
        dependency_type = _expect_vocabulary(
            columns["dependency_type"][index],
            IMPORT_TYPES,
            f"{prefix}.dependency_type[{index}]",
            "dependency_type",
        )
        resolution = _expect_vocabulary(
            columns["resolution"][index],
            IMPORT_RESOLUTIONS,
            f"{prefix}.resolution[{index}]",
            "import resolution",
        )
        mechanism = _expect_vocabulary(
            columns["mechanism"][index],
            IMPORT_MECHANISMS,
            f"{prefix}.mechanism[{index}]",
            "import mechanism",
        )
        binding = _expect_vocabulary(
            columns["binding"][index],
            DEPENDENCY_BINDINGS,
            f"{prefix}.binding[{index}]",
            "dependency binding",
        )
        line = _expect_wire_int(columns["line"][index], f"{prefix}.line[{index}]")
        level = _expect_wire_int(columns["level"][index], f"{prefix}.level[{index}]")
        requested_module = _expect_string(
            columns["requested_module"][index], f"{prefix}.requested_module[{index}]"
        )
        requested_names = _decode_strings(
            columns["requested_names"][index], f"{prefix}.requested_names[{index}]"
        )
        candidate_targets = _decode_strings(
            columns["candidate_targets"][index],
            f"{prefix}.candidate_targets[{index}]",
        )
        is_lazy = index in flags["is_lazy"]
        inventory_expansion = index in flags["inventory_expansion"]
        try:
            row = ImportObservationRow(
                source=source,
                target=target,
                dependency_type=dependency_type,
                line=line,
                resolution=resolution,
                mechanism=mechanism,
                binding=binding,
                is_lazy=is_lazy,
                level=level,
                requested_module=requested_module or None,
                requested_names=tuple(requested_names),
                candidate_targets=tuple(candidate_targets),
                inventory_expansion=inventory_expansion,
            )
        except CanonicalModelError as error:
            # The cross-column laws (a resolution against its target variant,
            # the producer's candidate law) are the model's; the wire
            # refuses the contradiction under its contract code rather than
            # letting a model error escape the decoder.
            raise _refuse("W20", f"{prefix}[{index}]: {error}") from error
        rows.append(row)
        keys.append(
            (
                source_key,
                target_key,
                dependency_type,
                line,
                resolution,
                mechanism,
                binding,
                is_lazy,
                level,
                requested_module,
                tuple(requested_names),
                tuple(candidate_targets),
                inventory_expansion,
            )
        )
    _expect_strictly_increasing(keys, prefix)
    return frozenset(rows)


def _decode_relationship_target(
    value: object, symbols: Sequence[SymbolId], where: str
) -> tuple[RelationshipTarget, tuple[object, ...]]:
    """One tagged relationship-target slot and its order key."""
    slot, tag = _decode_target_slot(
        value, _RELATIONSHIP_TARGET_TAGS, where, "a relationship target"
    )
    if tag == TARGET_TAG_UNRESOLVED:
        if len(slot) != 1:
            raise _refuse("W18", f"{where} unresolved target carries a value")
        return UnresolvedTarget(), (tag, 0)
    if tag == DOMAIN_TAG_SYMBOL:
        if len(slot) != 2:
            raise _refuse("W18", f"{where} is not a [symbol, ordinal] slot")
        ordinal = _expect_ordinal(slot[1], len(symbols), where)
        return symbols[ordinal], (tag, ordinal)
    if len(slot) != 3:
        raise _refuse("W18", f"{where} is not an [opaque, head, qualname] slot")
    head = _expect_string(slot[1], f"{where}.head")
    qualname = _expect_string(slot[2], f"{where}.qualname")
    if not head or not qualname:
        raise _refuse("W18", f"{where} opaque target has an empty head or qualname")
    return OpaqueEntity(head, qualname), (tag, head, qualname)


def _decode_relationship_observations(
    facts: Mapping[str, object], symbols: Sequence[SymbolId]
) -> frozenset[RelationshipObservationRow]:
    prefix = "facts.relationship_observations"
    columns, _flags, row_count = _decode_columns(
        "relationship_observations", facts["relationship_observations"]
    )
    rows = []
    keys = []
    for index in range(row_count):
        source_ordinal = _expect_ordinal(
            columns["source"][index], len(symbols), f"{prefix}.source[{index}]"
        )
        target, target_key = _decode_relationship_target(
            columns["target"][index], symbols, f"{prefix}.target[{index}]"
        )
        relation_kind = _expect_vocabulary(
            columns["relation_kind"][index],
            RELATIONSHIP_KINDS,
            f"{prefix}.relation_kind[{index}]",
            "relationship kind",
        )
        origin_lane = _expect_vocabulary(
            columns["origin_lane"][index],
            RELATIONSHIP_ORIGIN_LANES,
            f"{prefix}.origin_lane[{index}]",
            "relationship origin lane",
        )
        line = _expect_wire_int(columns["line"][index], f"{prefix}.line[{index}]")
        if line < 1:
            raise _refuse(
                "W07",
                f"{prefix}.line[{index}] is {line}, outside the producer's "
                "positive line domain",
            )
        occurrence_count = _expect_wire_int(
            columns["occurrence_count"][index], f"{prefix}.occurrence_count[{index}]"
        )
        if occurrence_count < 1:
            raise _refuse(
                "W07",
                f"{prefix}.occurrence_count[{index}] is {occurrence_count}; a "
                "stored observation was observed at least once",
            )
        expression = _expect_string(
            columns["expression"][index], f"{prefix}.expression[{index}]"
        )
        resolution_rule = _expect_string(
            columns["resolution_rule"][index], f"{prefix}.resolution_rule[{index}]"
        )
        if resolution_rule and resolution_rule not in RELATIONSHIP_RESOLUTION_RULES:
            raise _refuse(
                "W08", f"unknown relationship resolution rule tag {resolution_rule!r}"
            )
        try:
            row = RelationshipObservationRow(
                source=symbols[source_ordinal],
                target=target,
                relation_kind=relation_kind,
                origin_lane=origin_lane,
                line=line,
                expression=expression or None,
                resolution_rule=resolution_rule or None,
                occurrence_count=occurrence_count,
            )
        except CanonicalModelError as error:
            raise _refuse("W20", f"{prefix}[{index}]: {error}") from error
        rows.append(row)
        keys.append(
            (
                source_ordinal,
                target_key,
                relation_kind,
                origin_lane,
                line,
                expression,
                resolution_rule,
            )
        )
    _expect_strictly_increasing(keys, prefix)
    return frozenset(rows)


def _decode_violations(
    facts: Mapping[str, object],
    symbols: Sequence[SymbolId],
    files: Sequence[FileId],
    roots: Sequence[EffectRoot],
    root_tables: Sequence[tuple[int, ...]],
    producer_tables: Sequence[tuple[int, ...]],
    function_ordinals: set[int],
) -> tuple[list[ViolationRow], list[str]]:
    columns, flags, row_count = _decode_columns("violations", facts["violations"])
    suppressed_positions = flags["suppressed"]
    rows = []
    handles = []
    keys = []
    for index in range(row_count):
        contract_id = _expect_string(
            columns["contract_id"][index], f"facts.violations.contract_id[{index}]"
        )
        if not contract_id:
            raise _refuse("W18", f"facts.violations.contract_id[{index}] is empty")
        kind = _expect_string(columns["kind"][index], f"facts.violations.kind[{index}]")
        if kind not in VIOLATION_KINDS:
            raise _refuse("W08", f"unknown violation kind tag {kind!r}")
        sink_ordinal = _expect_ordinal(
            columns["sink_identity"][index],
            len(symbols),
            f"facts.violations.sink_identity[{index}]",
        )
        if sink_ordinal not in function_ordinals:
            raise _refuse(
                "W16",
                f"violation sink references symbol ordinal {sink_ordinal} "
                "without the FUNCTION role",
            )
        owner_ordinal = _expect_ordinal(
            columns["canonical_owner"][index],
            len(symbols),
            f"facts.violations.canonical_owner[{index}]",
        )
        producer_set_ordinal = _expect_ordinal(
            columns["producer_set"][index],
            len(producer_tables),
            f"facts.violations.producer_set[{index}]",
        )
        root_set_ordinal = _expect_ordinal(
            columns["root_set"][index],
            len(root_tables),
            f"facts.violations.root_set[{index}]",
        )
        rows.append(
            ViolationRow(
                contract_id=contract_id,
                kind=kind,
                sink_identity=symbols[sink_ordinal],
                canonical_owner=symbols[owner_ordinal],
                authority_status=_expect_string(
                    columns["authority_status"][index],
                    f"facts.violations.authority_status[{index}]",
                ),
                effect_signature=_expect_string(
                    columns["effect_signature"][index],
                    f"facts.violations.effect_signature[{index}]",
                ),
                resolution_state=_expect_string(
                    columns["resolution_state"][index],
                    f"facts.violations.resolution_state[{index}]",
                ),
                root_set=frozenset(roots[r] for r in root_tables[root_set_ordinal]),
                producer_set=frozenset(
                    symbols[o] for o in producer_tables[producer_set_ordinal]
                ),
                suppressed=index in suppressed_positions,
                locations=_decode_source_locations(
                    columns["locations"][index],
                    files,
                    f"facts.violations.locations[{index}]",
                ),
            )
        )
        handles.append(
            _expect_string(
                columns["violation_id"][index],
                f"facts.violations.violation_id[{index}]",
            )
        )
        keys.append(
            (
                contract_id.encode("utf-8"),
                kind.encode("utf-8"),
                sink_ordinal,
                producer_set_ordinal,
            )
        )
    _expect_strictly_increasing(keys, "facts.violations")
    return rows, handles


def _verify_public_handles(
    candidates: Sequence[CandidateRow],
    candidate_handles: Sequence[str],
    violations: Sequence[ViolationRow],
    violation_handles: Sequence[str],
    file_modules: frozenset[FileModuleRelation],
) -> None:
    """Recompute every class-B handle through its one formula owner (W25)."""
    handle_symbols: set[SymbolId] = set()
    for row in candidates:
        handle_symbols.update(row.producer_set)
    for violation in violations:
        handle_symbols.add(violation.sink_identity)
        handle_symbols.update(violation.producer_set)
    try:
        legacy_keys = legacy_symbol_keys(handle_symbols, file_modules)
    except CanonicalModelError as error:
        raise _refuse("W25", f"public handles are unverifiable: {error}") from error
    for index, row in enumerate(candidates):
        expected = candidate_handle(
            level=row.level,
            shared_fact=row.shared_fact,
            producers=[legacy_keys[p] for p in row.producer_set],
        )
        if candidate_handles[index] != expected:
            raise _refuse(
                "W25",
                f"facts.candidates.candidate_id[{index}] does not match its "
                "formula owner",
            )
    for index, violation in enumerate(violations):
        expected = violation_handle(
            contract_id=violation.contract_id,
            kind=violation.kind,
            sink_identity=legacy_keys[violation.sink_identity],
            producers=[legacy_keys[p] for p in violation.producer_set],
        )
        if violation_handles[index] != expected:
            raise _refuse(
                "W25",
                f"facts.violations.violation_id[{index}] does not match its "
                "formula owner",
            )


def _check_function_role(
    producer_tables: Sequence[tuple[int, ...]], function_ordinals: set[int]
) -> None:
    for table in producer_tables:
        for ordinal in table:
            if ordinal not in function_ordinals:
                raise _refuse(
                    "W16",
                    f"producer set references symbol ordinal {ordinal} "
                    "without the FUNCTION role",
                )


def _check_integrity(data: bytes, root: Mapping[str, object]) -> None:
    integrity = _expect_object(root["integrity"], ("algorithm", "value"), "integrity")
    if _expect_string(integrity["algorithm"], "integrity.algorithm") != "sha256":
        raise _refuse("W23", "integrity algorithm is not sha256")
    declared_digest = _expect_string(integrity["value"], "integrity.value")
    marker_at = data.rfind(_INTEGRITY_MARKER)
    if marker_at < 0:
        raise _refuse("W24", "integrity member is not in canonical byte form")
    body = data[1:marker_at]
    recomputed = hashlib.sha256(
        _wire_integrity_domain(CANONICAL_WIRE_REVISION) + body
    ).hexdigest()
    if declared_digest != recomputed:
        raise _refuse(
            "W23",
            "integrity digest does not seal the preceding members "
            f"(declared {declared_digest[:12]}…, recomputed {recomputed[:12]}…)",
        )


def _tier_family_rows(
    member: object, family: TierFamily, where: str
) -> list[Mapping[str, object]]:
    """The stored rows one family member of a house spells, before any
    cell is judged: a record object (``{}`` is no record) or equal-length
    columns, one per stored field, in the declared order."""
    if family.record:
        if member == {}:
            return []
        return [_expect_object(member, family.columns, where)]
    table = _expect_object(member, family.columns, where)
    columns = [
        _expect_list(table[column], f"{where}.{column}") for column in family.columns
    ]
    lengths = sorted({len(column) for column in columns})
    if len(lengths) > 1:
        raise _refuse("W15", f"{where} columns have diverging lengths {lengths!r}")
    return [
        dict(zip(family.columns, cells, strict=True))
        for cells in zip(*columns, strict=True)
    ]


def _decode_tier_house(
    root: Mapping[str, object], house: TierHouse
) -> dict[str, list[object]]:
    """One house member's rows, each read by its family's one decoder.  A
    cell that decoder does not admit is ``W27``, named with its family."""
    families = tier_families(house)
    section = _expect_object(root[house], [family.name for family in families], house)
    decoded: dict[str, list[object]] = {}
    for family in families:
        where = f"{house}.{family.name}"
        try:
            decoded[family.name] = [
                family.decode(row, where)
                for row in _tier_family_rows(section[family.name], family, where)
            ]
        except (StoreIntegrityError, CanonicalModelError) as error:
            raise _refuse("W27", f"{where}: {error}") from error
    return decoded


def _decode_tiers(
    root: Mapping[str, object], analysis: AnalysisFacts, files: frozenset[FileId]
) -> CanonicalFacts:
    """The facts of the document: its analysis house and the two tier houses
    it carries, the tiers' laws proven before the seal (``W28``)."""
    facts = CanonicalFacts(
        analysis=analysis,
        comparison=comparison_house(_decode_tier_house(root, "comparison")),
        evaluation=evaluation_house(_decode_tier_house(root, "evaluation")),
    )
    try:
        prove_tier_facts(facts, files)
    except CanonicalModelError as error:
        raise _refuse(
            "W28", f"a comparison or evaluation law refuses: {error}"
        ) from error
    return facts


def decode_canonical_json(data: bytes) -> CanonicalModel:
    """Decode canonical bytes into the canonical semantic model.

    Refusals are typed (``W``-codes) and never degrade silently; a document
    that decodes successfully re-encodes to the identical bytes.
    """
    document = _parse_document(data)
    _decode_format_and_revisions(document)
    root = _expect_object(document, _ROOT_KEYS, "document root")
    labels = _decode_values(root)
    domains = _expect_object(root["domains"], _DOMAIN_KEYS, "domains")
    files = _decode_files(domains)
    modules = _decode_modules(domains)
    symbols = _decode_symbols(domains, files)
    roots = _decode_effect_roots(domains["effect_roots"], files, modules, symbols)

    sets_section = _expect_object(root["sets"], _SET_KEYS, "sets")
    coupled_tables = _decode_set_table(
        sets_section["coupled_sets"], len(labels), "sets.coupled_sets"
    )
    producer_tables = _decode_set_table(
        sets_section["producer_sets"], len(symbols), "sets.producer_sets"
    )
    root_tables = _decode_set_table(
        sets_section["root_sets"], len(roots), "sets.root_sets"
    )

    scope = _expect_object(root["scope"], ("analyzed_files",), "scope")
    analyzed_ordinals = [
        _expect_ordinal(item, len(files), "scope.analyzed_files")
        for item in _expect_list(scope["analyzed_files"], "scope.analyzed_files")
    ]
    _expect_increasing_elements(analyzed_ordinals, "scope.analyzed_files")

    facts_section = _expect_object(root["facts"], wire_fact_family_order(), "facts")
    candidates, candidate_handles = _decode_candidates(
        facts_section, symbols, producer_tables
    )
    contracts, function_ordinals = _decode_contracts(
        facts_section, symbols, roots, root_tables
    )
    file_modules = _decode_file_modules(facts_section, files, modules)
    graph_nodes = _decode_graph_nodes(facts_section, symbols, roots, root_tables)
    semantic_edges = _decode_semantic_edges(facts_section, symbols)
    sink_roles = _decode_sink_roles(facts_section, symbols)
    dependency_relations, relation_keys = _decode_dependency_relations(
        facts_section, files, modules
    )
    dependency_occurrences = _decode_dependency_occurrences(
        facts_section, files, modules, relation_keys
    )
    dependency_cycles = _decode_dependency_cycles(facts_section, modules)
    import_observations = _decode_import_observations(facts_section, files, modules)
    relationship_observations = _decode_relationship_observations(
        facts_section, symbols
    )
    clone_groups = _decode_clone_groups(facts_section, symbols)
    dead_code_observations = _decode_dead_code_observations(
        facts_section, symbols, modules
    )
    coupling_cohesion = _decode_coupling_cohesion(facts_section, symbols)
    api_symbols = _decode_api_symbols(facts_section, symbols)
    risk_observations = _decode_risk_observations(facts_section, symbols)
    unit_spans = _decode_unit_spans(facts_section, symbols)
    adoption_counts = _decode_adoption_counts(facts_section, files, modules)
    security_surfaces = _decode_security_surfaces(facts_section, files)
    run_scalars = _decode_run_scalars(facts_section)
    analysis_population = _decode_analysis_population(facts_section)
    # Canonical epoch E1: every member is decoded BEFORE the seal is
    # checked, like every member above it, so a malformed E1 cell answers
    # with its own typed code and never hides behind W23.
    suppressed_clone_groups = _decode_suppressed_clone_groups(facts_section, symbols)
    structural_groups = _decode_structural_groups(facts_section, symbols)
    dead_symbol_groups = _decode_site_rows(
        "dead_symbol_groups", facts_section, symbols, _dead_symbol_group
    )
    unreachable_statement_groups = _decode_site_rows(
        "unreachable_statement_groups", facts_section, symbols, _unreachable_statement
    )
    complexity_hotspots = _decode_site_rows(
        "complexity_hotspots", facts_section, symbols, _complexity_hotspot
    )
    coupling_hotspots = _decode_site_rows(
        "coupling_hotspots", facts_section, symbols, _coupling_hotspot
    )
    cohesion_hotspots = _decode_site_rows(
        "cohesion_hotspots", facts_section, symbols, _cohesion_hotspot
    )
    overloaded_modules = _decode_overloaded_modules(facts_section, files)
    coverage_units = _decode_site_rows(
        "coverage_units", facts_section, symbols, _coverage_unit
    )
    coverage_join = _decode_coverage_join(facts_section)
    dead_code_summary = _decode_dead_code_summary(facts_section)
    violations, violation_handles = _decode_violations(
        facts_section,
        symbols,
        files,
        roots,
        root_tables,
        producer_tables,
        function_ordinals,
    )
    _check_function_role(producer_tables, function_ordinals)
    _verify_public_handles(
        candidates, candidate_handles, violations, violation_handles, file_modules
    )
    analysis = AnalysisFacts(
        contracts=contracts,
        graph_nodes=graph_nodes,
        sink_roles=sink_roles,
        candidates=frozenset(candidates),
        semantic_edges=semantic_edges,
        dependency_relations=dependency_relations,
        dependency_occurrences=dependency_occurrences,
        dependency_cycles=dependency_cycles,
        import_observations=import_observations,
        relationship_observations=relationship_observations,
        clone_groups=clone_groups,
        dead_code_observations=dead_code_observations,
        violations=frozenset(violations),
        coupling_cohesion_observations=coupling_cohesion,
        api_symbols=api_symbols,
        risk_observations=risk_observations,
        unit_spans=unit_spans,
        adoption_counts=adoption_counts,
        security_surfaces=security_surfaces,
        suppressed_clone_groups=suppressed_clone_groups,
        structural_groups=structural_groups,
        dead_symbol_groups=dead_symbol_groups,
        unreachable_statement_groups=unreachable_statement_groups,
        complexity_hotspots=complexity_hotspots,
        coupling_hotspots=coupling_hotspots,
        cohesion_hotspots=cohesion_hotspots,
        overloaded_modules=overloaded_modules,
        coverage_units=coverage_units,
        run_scalars=run_scalars,
        analysis_population=analysis_population,
        coverage_join=coverage_join,
        dead_code_summary=dead_code_summary,
    )
    facts = _decode_tiers(root, analysis, frozenset(files))
    _check_integrity(data, root)

    model = CanonicalModel(
        files=frozenset(files),
        modules=frozenset(modules),
        analyzed_files=frozenset(files[o] for o in analyzed_ordinals),
        file_modules=file_modules,
        facts=facts,
        coupled_sets=frozenset(
            frozenset(labels[o] for o in table) for table in coupled_tables
        ),
    )
    if encode_canonical_json(model) != data:
        raise _refuse(
            "W24", "document bytes are not the canonical encoding of their model"
        )
    return model
