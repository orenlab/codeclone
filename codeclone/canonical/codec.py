# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Deterministic canonical JSON codec vNext (F-3 §7), wire revision 0.

The codec owns its own serializer: the legacy ``orjson OPT_SORT_KEYS``
canonizer sorts the top level and silently turns NaN into ``null`` — both
violate this contract, so it is never called here.

Wire revision 0 grammar (root keys, declared order — every reference points
backward, never forward)::

    format · revisions · values · domains · sets · scope · facts · integrity

``comparison`` and ``evaluation`` join in later waves with a wire revision
bump: emitting an empty object today would present "not populated by this
model revision" as "measured empty", which the four-state law forbids.

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
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from itertools import pairwise
from typing import Any, TypeVar, cast

from codeclone.canonical.api_identity import signature_variant
from codeclone.canonical.authority_identity import (
    candidate_handle,
    legacy_symbol_key,
    violation_handle,
)
from codeclone.canonical.errors import CanonicalModelError, WireDecodeError
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
    DOMAIN_TAG_FILE,
    DOMAIN_TAG_MODULE,
    DOMAIN_TAG_SYMBOL,
    EFFECT_KINDS,
    HEAD_TAG_OPAQUE,
    IMPORT_TYPES,
    LIVE_ROOT_REASONS,
    LOCATION_TAG_UNRESOLVED,
    OPERATION_KINDS,
    PRODUCER_EXECUTION_STATES,
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
    VIOLATION_KINDS,
    AnalysisFile,
    DependencyEndpoint,
    EffectLabelRoot,
    EffectRoot,
    FileId,
    FileLine,
    KnownModule,
    ModuleId,
    ModuleSymbol,
    OpaqueDottedHead,
    OpaqueEntity,
    OperationHead,
    OperationRoot,
    OperationTarget,
    ProducerRoot,
    SourceLocation,
    SymbolId,
    UnresolvedLocation,
    UnresolvedRoot,
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
    CloneItemRow,
    ContractRow,
    CouplingCohesionRow,
    DeadCodeObservationRow,
    DependencyCycleRow,
    DependencyOccurrenceRow,
    DependencyRelationRow,
    FileModuleRelation,
    GraphNodeRow,
    RiskObservationRow,
    RunScalars,
    SecuritySurfaceRow,
    SemanticEdge,
    SinkRoleRow,
    UnitSpanRow,
    ViolationRow,
)
from codeclone.canonical.registry import (
    is_record_family,
    sparse_bool_wire_columns,
    wire_columns,
    wire_fact_family_order,
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
    "integrity",
)
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
_INTEGRITY_DOMAIN = b"cc-canonical-wire:0\x00"
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
    {DOMAIN_TAG_FILE, DOMAIN_TAG_MODULE, "symbol", "effect_root", HEAD_TAG_OPAQUE}
)
_HEAD_TAGS = frozenset({DOMAIN_TAG_FILE, DOMAIN_TAG_MODULE, HEAD_TAG_OPAQUE})

_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\f": "\\f",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}


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
    return referenced


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
        }
        for row in sorted(
            facts.dead_code_observations,
            key=lambda row: (
                *dead_code_entity_key(row.entity),
                row.observation_kind.encode("utf-8"),
            ),
        )
    ]


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


_FAMILY_ROW_BUILDERS: dict[
    str, Callable[[AnalysisFacts, WirePlan], list[dict[str, object]]]
] = {
    "adoption_counts": _adoption_count_rows,
    "analysis_population": _analysis_population_rows,
    "api_symbols": _api_symbol_rows,
    "candidates": _candidate_rows,
    "clone_groups": _clone_group_rows,
    "contracts": _contract_rows,
    "coupling_cohesion_observations": _coupling_cohesion_rows,
    "dead_code_observations": _dead_code_observation_rows,
    "dependency_cycles": _dependency_cycle_rows,
    "dependency_occurrences": _dependency_occurrence_rows,
    "dependency_relations": _dependency_relation_rows,
    "file_modules": _file_module_rows,
    "graph_nodes": _graph_node_rows,
    "risk_observations": _risk_observation_rows,
    "run_scalars": _run_scalars_rows,
    "security_surfaces": _security_surface_rows,
    "semantic_edges": _semantic_edge_rows,
    "sink_roles": _sink_role_rows,
    "unit_spans": _unit_span_rows,
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


def _integrity_tail(digest: str) -> str:
    """The sealing tail after the hashed body: the integrity member only."""
    integrity = _Obj([("algorithm", "sha256"), ("value", digest)])
    return f',"integrity":{_write(integrity)}'


def stream_canonical_wire(
    plan: WirePlan,
    facts_for_family: Callable[[str], AnalysisFacts],
    write: Callable[[bytes], object],
) -> None:
    """Write the one canonical byte encoding of one model state.

    The single wire emitter: :func:`encode_canonical_json` runs it over an
    in-memory model, the run-store's exporter over per-family scans.
    ``facts_for_family`` is called once per fact family, in wire order, and
    only that family's rows are read — bounded working memory (brief law
    11) is the provider's right by construction, never an accident.  The
    ``integrity`` member seals the body exactly as the decoder recomputes
    it: sha256 over the wire domain plus every emitted byte between the
    outer braces that precedes the integrity tail.
    """
    hasher = hashlib.sha256(_INTEGRITY_DOMAIN)

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
    stream_canonical_wire(plan, lambda _family: facts, out.extend)
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


def _parse_document(data: bytes) -> Mapping[str, object]:
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
    return _expect_object(document, _ROOT_KEYS, "document root")


def _decode_format_and_revisions(root: Mapping[str, object]) -> None:
    fmt = _expect_object(root["format"], ("name", "wire"), "format")
    if (
        _expect_string(fmt["name"], "format.name") != _FORMAT_NAME
        or _expect_string(fmt["wire"], "format.wire") != CANONICAL_WIRE_REVISION
    ):
        raise _refuse("W21", "format declares an incompatible generation")
    revisions_raw = root["revisions"]
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


def _decode_dead_code_observations(
    facts: Mapping[str, object],
    symbols: Sequence[SymbolId],
    modules: Sequence[ModuleId],
) -> frozenset[DeadCodeObservationRow]:
    columns, flags, row_count = _decode_columns(
        "dead_code_observations", facts["dead_code_observations"]
    )
    rows = []
    keys = []
    for index in range(row_count):
        row = _decode_dead_code_row(columns, flags, index, symbols, modules)
        rows.append(row)
        keys.append(
            (*dead_code_entity_key(row.entity), row.observation_kind.encode("utf-8"))
        )
    _expect_strictly_increasing(keys, "facts.dead_code_observations")
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
    recomputed = hashlib.sha256(_INTEGRITY_DOMAIN + body).hexdigest()
    if declared_digest != recomputed:
        raise _refuse(
            "W23",
            "integrity digest does not seal the preceding members "
            f"(declared {declared_digest[:12]}…, recomputed {recomputed[:12]}…)",
        )


def decode_canonical_json(data: bytes) -> CanonicalModel:
    """Decode canonical bytes into the canonical semantic model.

    Refusals are typed (``W``-codes) and never degrade silently; a document
    that decodes successfully re-encodes to the identical bytes.
    """
    root = _parse_document(data)
    _decode_format_and_revisions(root)
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
    _check_integrity(data, root)

    model = CanonicalModel(
        files=frozenset(files),
        modules=frozenset(modules),
        analyzed_files=frozenset(files[o] for o in analyzed_ordinals),
        file_modules=file_modules,
        facts=CanonicalFacts(
            analysis=AnalysisFacts(
                contracts=contracts,
                graph_nodes=graph_nodes,
                sink_roles=sink_roles,
                candidates=frozenset(candidates),
                semantic_edges=semantic_edges,
                dependency_relations=dependency_relations,
                dependency_occurrences=dependency_occurrences,
                dependency_cycles=dependency_cycles,
                clone_groups=clone_groups,
                dead_code_observations=dead_code_observations,
                violations=frozenset(violations),
                coupling_cohesion_observations=coupling_cohesion,
                api_symbols=api_symbols,
                risk_observations=risk_observations,
                unit_spans=unit_spans,
                adoption_counts=adoption_counts,
                security_surfaces=security_surfaces,
                run_scalars=run_scalars,
                analysis_population=analysis_population,
            )
        ),
        coupled_sets=frozenset(
            frozenset(labels[o] for o in table) for table in coupled_tables
        ),
    )
    if encode_canonical_json(model) != data:
        raise _refuse(
            "W24", "document bytes are not the canonical encoding of their model"
        )
    return model
