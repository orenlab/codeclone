# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""SQLite run-store of the canonical model — backend wave 2 (state is
written; no incrementality).

The store holds **immutable content-addressed fact objects** and **run
membership snapshots** over them (brief §3): two runs may share storage,
but a run never semantically depends on another run, and deleting a
neighbour never makes a run unreadable.  The store is separate from the
analysis cache by law (brief §2.1): nothing here is required to
reconstruct a cache, and no cache write participates in the authoritative
publish transaction.

Walls held here, and where:

* ``cache != truth`` — this module never touches the analysis cache.
* ``run != previous run + patch`` — a run is a full membership snapshot;
  there are no delta chains and no inter-run references.
* ``SQLite ID != canonical ID`` (wall 3) — every internal ``*_pk`` stays
  inside this module; the API speaks ``run_id`` / ``object_id`` content
  digests only, and both are recomputed from bytes, never from rowids.
* ``normalized != expanded legacy`` — the store persists canonical model
  rows; the legacy report shape never enters.

Storage payload bytes are a *storage representation* of the one canonical
model (F-3 §13: one semantic model, two representations).  They are not a
second truth: law L8 (``project(store) == project(model)``) is proven by
reading a run back and re-encoding it byte-identically, and every stored
payload re-hashes to its own content address on read.

Cross-version safety (brief §4): the store carries a **layered
compatibility witness**; ``open`` refuses an incompatible generation (law
7), and every mutating transaction re-reads the store generation and
refuses when it moved under the handle — fencing on each mutation, not
only at ``open`` (§4.2).

Atomic publish (brief §10): objects, run row, and membership are staged
inside one immediate transaction with ``published = 0``; digests are
re-verified **from the database rows**, the run flips to ``published = 1``
and the target head advances by compare-and-swap — all in the same
transaction.  Death anywhere leaves the previous head true; readers never
see an unpublished run.  A publisher whose expected generation is stale
keeps its run as a valid immutable run but does not advance the head
(brief §6.1) — monotonic head advancement, law 8.

Object identity follows F-3 §5.0.0/§5.0.1: the content address is
``H(namespace · family · family contract namespace · payload)``, so a
model-local identity shares storage only inside one semantic namespace,
and a fact never silently crosses a producer revision.

Bounded export (wave 3): ``export_run`` births the authoritative canonical
bytes straight from the store — byte-identical to ``project_run`` without
ever materializing the complete model (brief law 11).  Pass one proves
every stored byte and collects the projection plan; pass two streams one
fact family at a time through the codec's single wire emitter.  The export
is pinned to one run identity resolved exactly once (§11.1, the
``_pin_export`` seam), and its envelope separates the artifact digest
(projection-layer identity, wire revision inside the domain) from the run
identity (analysis layers only) — brief §5.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from types import TracebackType
from typing import Final, Generic, Protocol, TypeVar

from codeclone.canonical.api_identity import signature_variant
from codeclone.canonical.codec import (
    WirePlan,
    encode_canonical_json,
    fact_producer_sets,
    fact_root_sets,
    plan_from_parts,
    referenced_symbols,
    stream_canonical_wire,
)
from codeclone.canonical.errors import (
    CanonicalModelError,
    RunReportLinkError,
    RunStoreError,
    StoreCompatibilityError,
    StoreFenceError,
    StoreIntegrityError,
    UnknownRunError,
)
from codeclone.canonical.export import (
    ByteSink,
    ExportEnvelope,
    WitnessLayer,
    artifact_domain,
)
from codeclone.canonical.identity import (
    DOMAIN_TAG_FILE,
    LOCATION_TAG_UNRESOLVED,
    AnalysisFile,
    DeadCodeEntity,
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
    ViolationRow,
)
from codeclone.contracts import (
    ADOPTION_COVERAGE_POLICY_VERSION,
    API_SURFACE_SIGNATURE_VERSION,
    AUTHORITY_ANALYSIS_REVISION,
    BASELINE_FINGERPRINT_VERSION,
    CANONICAL_MODEL_REVISION,
    CANONICAL_WIRE_REVISION,
    COMPLEXITY_ALGORITHM_REVISION,
    CONTRACT_IR_VERSION,
    DESIGN_METRICS_ALGORITHM_REVISION,
    LIVENESS_POLICY_VERSION,
    MODULE_IDENTITY_VERSION,
    SECURITY_SURFACE_CATALOG_VERSION,
    SOURCE_KIND_POLICY_VERSION,
    STATEMENT_REACHABILITY_POLICY_VERSION,
    STORAGE_SCHEMA_REVISION,
)
from codeclone.models import (
    GC_COLLECT_UNREACHABLE,
    GC_HOLD_HEAD,
    GC_HOLD_HISTORY,
    GC_HOLD_LEASE,
    GC_HOLD_RETAINED,
    GC_HOLD_STAGING,
    GcJobReport,
    deadline_passed,
)
from codeclone.observability import SpanHandle, span
from codeclone.utils.sqlite_store import open_sqlite_db

_RowT = TypeVar("_RowT")

_DOMAIN_PREFIX: Final = f"cc-run-store:{STORAGE_SCHEMA_REVISION}\x00".encode()
_DOMAIN_OBJECT: Final = _DOMAIN_PREFIX + b"object\x00"
_DOMAIN_RUN: Final = _DOMAIN_PREFIX + b"run\x00"
_DOMAIN_SCOPE: Final = _DOMAIN_PREFIX + b"scope\x00"
_DOMAIN_MEMBERSHIP: Final = _DOMAIN_PREFIX + b"membership\x00"
_DOMAIN_CONTRACT_EPOCH: Final = _DOMAIN_PREFIX + b"contract-epoch\x00"

# Layered compatibility witness (brief §4.1).  ``analysis`` layers enter the
# run identity through the layer list ``_run_id`` joins; the ``projection``
# layer (wire revision) does not, and a projection revision therefore never
# reaches back into semantic run identity (brief §5).
#
# ``storage`` is out of that LIST and, measured 2026-09-01 on the first bump
# this constant ever took, is NOT out of the identity: STORAGE_SCHEMA_REVISION
# is spelled into ``_DOMAIN_PREFIX`` below, so it sits inside every object id,
# the scope receipt, the membership digest and the run domain — a bump resets
# all four.  The role split is what keeps the layer out of the joined list;
# it was never what kept it out of the addresses, and the earlier wording here
# ("storage physics is not semantics") claimed a property nothing executed.
# ``test_the_storage_revision_is_inside_every_store_content_address`` now
# holds the measured relation as a derivation.  Whether a storage bump SHOULD
# reset the analysis identities is the layer owner's decision and is open.
#
# All layers participate in the witness comparison and in the fenced contract
# epoch.
_WITNESS_LAYERS: Final[tuple[tuple[str, str, str], ...]] = (
    ("authority_analysis", AUTHORITY_ANALYSIS_REVISION, "analysis"),
    ("canonical_model", CANONICAL_MODEL_REVISION, "analysis"),
    ("canonical_wire", CANONICAL_WIRE_REVISION, "projection"),
    ("contract_ir", CONTRACT_IR_VERSION, "analysis"),
    ("module_identity", MODULE_IDENTITY_VERSION, "analysis"),
    ("storage_schema", STORAGE_SCHEMA_REVISION, "storage"),
)


_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS store_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    store_epoch INTEGER NOT NULL,
    storage_schema_revision TEXT NOT NULL,
    contract_epoch TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS witness (
    layer TEXT PRIMARY KEY,
    revision TEXT NOT NULL,
    role TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS namespaces (
    namespace_pk INTEGER PRIMARY KEY,
    namespace TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS objects (
    object_pk INTEGER PRIMARY KEY,
    namespace_pk INTEGER NOT NULL REFERENCES namespaces(namespace_pk),
    object_id TEXT NOT NULL,
    family TEXT NOT NULL,
    payload BLOB NOT NULL,
    UNIQUE (namespace_pk, object_id)
);
CREATE TABLE IF NOT EXISTS runs (
    run_pk INTEGER PRIMARY KEY,
    namespace_pk INTEGER NOT NULL REFERENCES namespaces(namespace_pk),
    run_id TEXT NOT NULL UNIQUE,
    analysis_scope_digest TEXT NOT NULL,
    membership_digest TEXT NOT NULL,
    published INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS run_members (
    run_pk INTEGER NOT NULL REFERENCES runs(run_pk),
    object_pk INTEGER NOT NULL REFERENCES objects(object_pk),
    PRIMARY KEY (run_pk, object_pk)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS heads (
    namespace_pk INTEGER NOT NULL REFERENCES namespaces(namespace_pk),
    target TEXT NOT NULL,
    generation INTEGER NOT NULL,
    run_pk INTEGER NOT NULL REFERENCES runs(run_pk),
    PRIMARY KEY (namespace_pk, target)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS head_history (
    namespace_pk INTEGER NOT NULL REFERENCES namespaces(namespace_pk),
    target TEXT NOT NULL,
    generation INTEGER NOT NULL,
    run_pk INTEGER NOT NULL REFERENCES runs(run_pk),
    PRIMARY KEY (namespace_pk, target, generation)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS run_leases (
    lease_id TEXT PRIMARY KEY,
    run_pk INTEGER NOT NULL REFERENCES runs(run_pk),
    kind TEXT NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS retained_runs (
    run_pk INTEGER PRIMARY KEY REFERENCES runs(run_pk)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS run_report_links (
    report_run_identity TEXT NOT NULL,
    run_pk INTEGER NOT NULL REFERENCES runs(run_pk),
    PRIMARY KEY (report_run_identity, run_pk)
) WITHOUT ROWID;
"""


# ---------------------------------------------------------------------------
# Storage row codec — the storage representation of model rows.
# ---------------------------------------------------------------------------


def _payload_bytes(value: object) -> bytes:
    """The one storage byte form; ``_object_id`` hashes exactly this.

    ``sort_keys=True`` is a determinism owner, not tidiness: it is what
    makes two spellings of the same row map to one content address.  No
    family in :func:`_model_rows` currently reaches it (every row dict is
    written alphabetically already), so only
    ``test_storage_payload_bytes_ignore_mapping_key_order`` keeps it
    honest — the guard was measured to survive the full suite without it.
    """
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise CanonicalModelError(f"value has no storage form: {error}") from error


def _symbol_value(symbol: SymbolId) -> list[str]:
    return [symbol.file.path, symbol.qualname]


def _decode_symbol(value: object, where: str) -> SymbolId:
    if not isinstance(value, list) or len(value) != 2:
        raise StoreIntegrityError(f"{where}: stored symbol is not a [path, qualname]")
    path, qualname = value
    if not isinstance(path, str) or not isinstance(qualname, str):
        raise StoreIntegrityError(f"{where}: stored symbol is not a [path, qualname]")
    return SymbolId(FileId(path), qualname)


def _endpoint_value(endpoint: DependencyEndpoint) -> list[str]:
    if isinstance(endpoint, ModuleId):
        return ["module", endpoint.module]
    return ["file", endpoint.path]


def _decode_endpoint(value: object, where: str) -> DependencyEndpoint:
    if not isinstance(value, list) or len(value) != 2:
        raise StoreIntegrityError(f"{where}: stored endpoint is not a [tag, value]")
    tag, text = value
    if not isinstance(tag, str) or not isinstance(text, str):
        raise StoreIntegrityError(f"{where}: stored endpoint is not a [tag, value]")
    if tag == "module":
        return ModuleId(text)
    if tag == "file":
        return FileId(text)
    raise StoreIntegrityError(f"{where}: unknown endpoint tag {tag!r}")


def _head_value(head: OperationHead) -> list[str]:
    if isinstance(head, KnownModule):
        return ["module", head.module.module]
    if isinstance(head, AnalysisFile):
        return ["file", head.file.path]
    return ["opaque", head.text]


def _decode_head(value: object, where: str) -> OperationHead:
    if not isinstance(value, list) or len(value) != 2:
        raise StoreIntegrityError(f"{where}: stored head is not a [tag, value]")
    tag, text = value
    if not isinstance(tag, str) or not isinstance(text, str):
        raise StoreIntegrityError(f"{where}: stored head is not a [tag, value]")
    if tag == "module":
        return KnownModule(ModuleId(text))
    if tag == "file":
        return AnalysisFile(FileId(text))
    if tag == "opaque":
        return OpaqueDottedHead(text)
    raise StoreIntegrityError(f"{where}: unknown head tag {tag!r}")


def _root_value(root: EffectRoot) -> list[object]:
    if isinstance(root, OperationRoot):
        return [
            "operation",
            root.operation_kind,
            _head_value(root.target.head),
            root.target.local_name,
        ]
    if isinstance(root, ProducerRoot):
        return ["producer", *_symbol_value(root.target)]
    if isinstance(root, EffectLabelRoot):
        return ["effect", root.effect_kind, root.label]
    return ["unresolved"]


def _root_strings(
    first: object, second: object, where: str, what: str
) -> tuple[str, str]:
    """The shared string-pair guard of the operation and effect variants."""
    if not isinstance(first, str) or not isinstance(second, str):
        raise StoreIntegrityError(f"{where}: malformed {what} root")
    return first, second


def _decode_root(value: object, where: str) -> EffectRoot:
    if not isinstance(value, list) or not value or not isinstance(value[0], str):
        raise StoreIntegrityError(f"{where}: stored root has no family tag")
    family = value[0]
    if family == "unresolved" and len(value) == 1:
        return UnresolvedRoot()
    if family == "operation" and len(value) == 4:
        kind, local_name = _root_strings(value[1], value[3], where, "operation")
        return OperationRoot(
            kind, OperationTarget(_decode_head(value[2], where), local_name)
        )
    if family == "producer" and len(value) == 3:
        return ProducerRoot(_decode_symbol(value[1:], where))
    if family == "effect" and len(value) == 3:
        return EffectLabelRoot(*_root_strings(value[1], value[2], where, "effect"))
    raise StoreIntegrityError(f"{where}: unknown stored root family {family!r}")


def _dead_code_entity_value(entity: DeadCodeEntity) -> list[str]:
    if isinstance(entity, SymbolId):
        return ["symbol", entity.file.path, entity.qualname]
    if isinstance(entity, ModuleSymbol):
        return ["module", entity.module.module, entity.qualname]
    return ["opaque", entity.head, entity.qualname]


def _decode_dead_code_entity_value(value: object, where: str) -> DeadCodeEntity:
    if not isinstance(value, list) or len(value) != 3:
        raise StoreIntegrityError(
            f"{where}: stored dead-code entity is not a [tag, head, qualname]"
        )
    tag, head, qualname = value
    if (
        not isinstance(tag, str)
        or not isinstance(head, str)
        or not isinstance(qualname, str)
    ):
        raise StoreIntegrityError(
            f"{where}: stored dead-code entity is not a [tag, head, qualname]"
        )
    if tag == "symbol":
        return SymbolId(FileId(head), qualname)
    if tag == "module":
        return ModuleSymbol(ModuleId(head), qualname)
    if tag == "opaque":
        return OpaqueEntity(head, qualname)
    raise StoreIntegrityError(f"{where}: unknown dead-code entity tag {tag!r}")


def _source_location_value(location: SourceLocation) -> list[object]:
    """One evidence site in the store's own tagged spelling.

    The store keeps paths as PATHS rather than domain ordinals (the
    ``_symbol_value`` law here), so a FILE-headed site spells its file path
    and an unresolved site spells the string the producer asserted; the tag
    keeps the two apart, because the second one is not a FILE identity and
    must never be read back as one.
    """
    if isinstance(location, FileLine):
        return [DOMAIN_TAG_FILE, location.file.path, location.line]
    return [LOCATION_TAG_UNRESOLVED, location.path, location.line]


def _decode_source_location(value: object, where: str) -> SourceLocation:
    if not isinstance(value, list) or len(value) != 3:
        raise StoreIntegrityError(
            f"{where}: stored source location is not a [tag, path, line]"
        )
    tag, path, line = value
    if not isinstance(tag, str) or not isinstance(path, str):
        raise StoreIntegrityError(
            f"{where}: stored source location is not a [tag, path, line]"
        )
    if isinstance(line, bool) or not isinstance(line, int):
        raise StoreIntegrityError(f"{where}: stored source location line is not an int")
    if tag == DOMAIN_TAG_FILE:
        return FileLine(FileId(path), line)
    if tag == LOCATION_TAG_UNRESOLVED:
        return UnresolvedLocation(path, line)
    raise StoreIntegrityError(f"{where}: unknown source location tag {tag!r}")


def _decode_source_locations(value: object, where: str) -> tuple[SourceLocation, ...]:
    if not isinstance(value, list):
        raise StoreIntegrityError(f"{where}: stored source locations is not an array")
    return tuple(_decode_source_location(item, where) for item in value)


def _sorted_symbols(symbols: frozenset[SymbolId]) -> list[list[str]]:
    return [_symbol_value(s) for s in sorted(symbols, key=canonical_key)]


def _sorted_roots(roots: frozenset[EffectRoot]) -> list[list[object]]:
    return [_root_value(r) for r in sorted(roots, key=canonical_key)]


def _decode_symbol_set(value: object, where: str) -> frozenset[SymbolId]:
    if not isinstance(value, list):
        raise StoreIntegrityError(f"{where}: stored symbol set is not an array")
    return frozenset(_decode_symbol(item, where) for item in value)


def _decode_root_set(value: object, where: str) -> frozenset[EffectRoot]:
    if not isinstance(value, list):
        raise StoreIntegrityError(f"{where}: stored root set is not an array")
    return frozenset(_decode_root(item, where) for item in value)


def _identity_rows(model: CanonicalModel) -> Iterator[tuple[str, dict[str, object]]]:
    """Identity and scope rows of one model — the storage spelling of the
    export's ``_IDENTITY_FAMILIES``, split from the fact tables so neither
    half re-derives the other.

    The doubled ``sorted`` over ``coupled_sets`` is two different jobs, not
    one redundancy: the INNER call orders the labels that land in the
    payload and therefore in the content address (a determinism owner —
    dropping it moves ``run_id`` between interpreters), the OUTER call only
    orders rows (a passenger, see :func:`_model_rows`).  Collapsing the two
    into one call silently deletes an owner.
    """
    for file_id in sorted(model.files, key=canonical_key):
        yield "file", {"path": file_id.path}
    for module in sorted(model.modules, key=canonical_key):
        yield "module", {"module": module.module}
    for file_id in sorted(model.analyzed_files, key=canonical_key):
        yield "analyzed_file", {"path": file_id.path}
    for relation in sorted(
        model.file_modules,
        key=lambda rel: (canonical_key(rel.file), canonical_key(rel.module)),
    ):
        yield (
            "file_module",
            {"file": relation.file.path, "module": relation.module.module},
        )
    for labels in sorted(sorted(group) for group in model.coupled_sets):
        yield "coupled_set", {"labels": list(labels)}


def _model_rows(model: CanonicalModel) -> Iterator[tuple[str, dict[str, object]]]:
    """Every storage row of one normalized model, in a fixed row order.

    That row order is INSURANCE against arbitrary ``frozenset`` iteration,
    not the owner of determinism, and it reaches no observable output:
    ``write_full_run`` keys the staged rows by content address, inserts
    them under ``sorted(staged)``, every member read orders by
    ``object_id``, and :func:`_membership_digest` sorts its own input.
    Measured twice — dropping a component of a sort key here (wave F10) and
    reversing the whole walk (ruling C1, 2026-08-28) both survive the full
    suite.  **Do not build a pin on this order**: it would be hollow by
    construction, and the C1 ruling says storage row order is not guarded.

    The owners live downstream, each with its own pin:

    * :func:`_payload_bytes` — mapping key order inside a row payload;
    * :func:`_sorted_symbols`, :func:`_sorted_roots` and the inner label
      sort of :func:`_identity_rows` — set order inside a row payload;
    * :func:`analysis_scope_digest` and :func:`_membership_digest` — the
      two digests ``run_id`` is derived from;
    * the codec's ``_sorted_domain`` and per-family row keys — the wire.
    """
    facts = model.facts.analysis
    yield from _identity_rows(model)
    for contract in sorted(
        facts.contracts, key=lambda row: canonical_key(row.function)
    ):
        yield (
            "contract",
            {
                "effect_signature": contract.effect_signature,
                "function": _symbol_value(contract.function),
                "root_set": _sorted_roots(contract.root_set),
            },
        )
    for node in sorted(facts.graph_nodes, key=lambda row: canonical_key(row.function)):
        yield (
            "graph_node",
            {
                "effect_signature": node.effect_signature,
                "function": _symbol_value(node.function),
                "output_facts": list(node.output_facts),
                "resolution_state": node.resolution_state,
                "root_set": _sorted_roots(node.root_set),
            },
        )
    for sink in sorted(facts.sink_roles, key=lambda row: canonical_key(row.symbol)):
        yield (
            "sink_role",
            {
                "authority_status": sink.authority_status,
                "symbol": _symbol_value(sink.symbol),
            },
        )
    for candidate in sorted(
        facts.candidates,
        key=lambda row: (row.level, row.shared_fact, _sorted_symbols(row.producer_set)),
    ):
        yield (
            "candidate",
            {
                "level": candidate.level,
                "producer_set": _sorted_symbols(candidate.producer_set),
                "shared_fact": candidate.shared_fact,
            },
        )
    for edge in sorted(
        facts.semantic_edges,
        key=lambda row: (canonical_key(row.source), canonical_key(row.target)),
    ):
        yield (
            "semantic_edge",
            {
                "source": _symbol_value(edge.source),
                "target": _symbol_value(edge.target),
            },
        )
    for dependency_relation in sorted(
        facts.dependency_relations,
        key=lambda row: (
            _endpoint_value(row.source),
            _endpoint_value(row.target),
            row.dependency_type,
        ),
    ):
        yield (
            "dependency_relation",
            {
                "dependency_type": dependency_relation.dependency_type,
                "source": _endpoint_value(dependency_relation.source),
                "target": _endpoint_value(dependency_relation.target),
            },
        )
    for occurrence in sorted(
        facts.dependency_occurrences,
        key=lambda row: (
            _endpoint_value(row.relation.source),
            _endpoint_value(row.relation.target),
            row.relation.dependency_type,
            row.line,
        ),
    ):
        yield (
            "dependency_occurrence",
            {
                "binding": occurrence.binding,
                "dependency_type": occurrence.relation.dependency_type,
                "is_lazy": occurrence.is_lazy,
                "line": occurrence.line,
                "source": _endpoint_value(occurrence.relation.source),
                "target": _endpoint_value(occurrence.relation.target),
            },
        )
    for cycle in sorted(
        facts.dependency_cycles,
        key=lambda row: sorted(module.module for module in row.modules),
    ):
        yield (
            "dependency_cycle",
            {
                "kind": cycle.kind,
                "modules": sorted(module.module for module in cycle.modules),
            },
        )
    for group in sorted(
        facts.clone_groups, key=lambda row: (row.clone_kind, row.group_key)
    ):
        yield (
            "clone_group",
            {
                "clone_kind": group.clone_kind,
                "group_key": group.group_key,
                "items": sorted(
                    [*_symbol_value(item.symbol), item.start_line, item.end_line]
                    for item in group.items
                ),
            },
        )
    for dead_observation in sorted(
        facts.dead_code_observations,
        key=lambda row: (*dead_code_entity_key(row.entity), row.observation_kind),
    ):
        yield (
            "dead_code_observation",
            {
                "abstained": dead_observation.abstained,
                "candidate_kind": dead_observation.candidate_kind,
                "entity": _dead_code_entity_value(dead_observation.entity),
                "live_root_reason": dead_observation.live_root_reason,
                "observation_kind": dead_observation.observation_kind,
                "reachable": dead_observation.reachable,
                "reference_count": dead_observation.reference_count,
                "runtime_marker_count": dead_observation.runtime_marker_count,
                "source_markers": [
                    list(pair) for pair in dead_observation.source_markers
                ],
            },
        )
    for violation in sorted(
        facts.violations,
        key=lambda row: (
            row.contract_id,
            row.kind,
            canonical_key(row.sink_identity),
            _sorted_symbols(row.producer_set),
        ),
    ):
        yield (
            "violation",
            {
                "authority_status": violation.authority_status,
                "canonical_owner": _symbol_value(violation.canonical_owner),
                "contract_id": violation.contract_id,
                "effect_signature": violation.effect_signature,
                "kind": violation.kind,
                "producer_set": _sorted_symbols(violation.producer_set),
                "locations": [
                    _source_location_value(location) for location in violation.locations
                ],
                "resolution_state": violation.resolution_state,
                "root_set": _sorted_roots(violation.root_set),
                "sink_identity": _symbol_value(violation.sink_identity),
                "suppressed": violation.suppressed,
            },
        )
    yield from _observation_model_rows(facts)


def _observation_model_rows(
    facts: AnalysisFacts,
) -> Iterator[tuple[str, dict[str, object]]]:
    """Storage rows of the observation-lane families (F1/F2/F3/F5/F9).

    Split from :func:`_model_rows` so the row walk stays a walk — the F3
    landing pushed it over the complexity gate's high-risk floor, and the
    honest answer is structure, not a wider allowlist.
    """
    for observation in sorted(
        facts.coupling_cohesion_observations,
        key=lambda row: (canonical_key(row.symbol), row.dimension),
    ):
        yield (
            "coupling_cohesion_observation",
            {
                "dimension": observation.dimension,
                "numerator": observation.numerator,
                "symbol": _symbol_value(observation.symbol),
            },
        )
    for risk_observation in sorted(
        facts.risk_observations,
        key=lambda row: (canonical_key(row.symbol), row.dimension, row.start_line),
    ):
        yield (
            "risk_observation",
            {
                "dimension": risk_observation.dimension,
                "numerator": risk_observation.numerator,
                "start_line": risk_observation.start_line,
                "symbol": _symbol_value(risk_observation.symbol),
            },
        )
    for adoption in sorted(
        facts.adoption_counts,
        key=lambda row: (_endpoint_value(row.scope), row.feature),
    ):
        yield (
            "adoption_count",
            {
                "denominator": adoption.denominator,
                "feature": adoption.feature,
                "numerator": adoption.numerator,
                "scope": _endpoint_value(adoption.scope),
            },
        )
    for surface in sorted(
        facts.security_surfaces,
        key=lambda row: (
            canonical_key(row.file),
            row.start_line,
            row.evidence_symbol,
        ),
    ):
        yield (
            "security_surface",
            {
                "capability": surface.capability,
                "category": surface.category,
                "classification_mode": surface.classification_mode,
                "end_line": surface.end_line,
                "evidence_kind": surface.evidence_kind,
                "evidence_symbol": surface.evidence_symbol,
                "file": surface.file.path,
                "location_scope": surface.location_scope,
                "qualname": surface.qualname,
                "source_kind": surface.source_kind,
                "start_line": surface.start_line,
            },
        )
    for api_symbol in sorted(
        facts.api_symbols,
        key=lambda row: (
            canonical_key(row.symbol),
            signature_variant(
                parameters=row.parameters, returns_digest=row.returns_digest
            ),
        ),
    ):
        yield (
            "api_symbol",
            {
                "parameters": [
                    [p.name, p.kind, p.has_default, p.annotation_digest]
                    for p in api_symbol.parameters
                ],
                "returns_digest": api_symbol.returns_digest,
                "symbol": _symbol_value(api_symbol.symbol),
                "symbol_kind": api_symbol.symbol_kind,
                "visibility": api_symbol.visibility,
            },
        )
    if facts.run_scalars is not None:
        # F9: exactly one record per snapshot — a run-level fact, no rows.
        yield ("run_scalar", dict(sorted(asdict(facts.run_scalars).items())))
    if facts.analysis_population is not None:
        # RULING-2026-08-31 §3: the execution-population singleton.
        record = facts.analysis_population
        yield (
            "analysis_population",
            {
                "analysis_mode": record.analysis_mode,
                "analysis_profile": [
                    [name, value] for name, value in record.analysis_profile
                ],
                "producer_states": [
                    [family, state] for family, state in record.producer_states
                ],
            },
        )


def _require_field(row: Mapping[str, object], key: str, where: str) -> object:
    if key not in row:
        raise StoreIntegrityError(f"{where}: stored row is missing {key!r}")
    return row[key]


def _require_str(row: Mapping[str, object], key: str, where: str) -> str:
    value = _require_field(row, key, where)
    if not isinstance(value, str):
        raise StoreIntegrityError(f"{where}: stored field {key!r} is not a string")
    return value


def _require_str_list(row: Mapping[str, object], key: str, where: str) -> list[str]:
    values = _require_field(row, key, where)
    if not isinstance(values, list):
        raise StoreIntegrityError(f"{where}: stored field {key!r} is not an array")
    items: list[str] = []
    for item in values:
        if not isinstance(item, str):
            raise StoreIntegrityError(
                f"{where}: stored field {key!r} carries a non-string"
            )
        items.append(item)
    return items


def _require_bool(row: Mapping[str, object], key: str, where: str) -> bool:
    value = _require_field(row, key, where)
    if not isinstance(value, bool):
        raise StoreIntegrityError(f"{where}: stored field {key!r} is not a boolean")
    return value


def _require_line(row: Mapping[str, object], key: str, where: str) -> int:
    value = _require_field(row, key, where)
    if isinstance(value, bool) or not isinstance(value, int):
        raise StoreIntegrityError(f"{where}: stored field {key!r} is not an int")
    return value


def _row_symbol(row: Mapping[str, object], key: str, where: str) -> SymbolId:
    return _decode_symbol(_require_field(row, key, where), where)


def _decode_file_row(row: Mapping[str, object], where: str) -> FileId:
    return FileId(_require_str(row, "path", where))


def _decode_module_row(row: Mapping[str, object], where: str) -> ModuleId:
    return ModuleId(_require_str(row, "module", where))


def _decode_file_module_row(
    row: Mapping[str, object], where: str
) -> FileModuleRelation:
    return FileModuleRelation(
        FileId(_require_str(row, "file", where)),
        ModuleId(_require_str(row, "module", where)),
    )


def _decode_coupled_row(row: Mapping[str, object], where: str) -> frozenset[str]:
    return frozenset(_require_str_list(row, "labels", where))


def _decode_contract_row(row: Mapping[str, object], where: str) -> ContractRow:
    return ContractRow(
        function=_row_symbol(row, "function", where),
        effect_signature=_require_str(row, "effect_signature", where),
        root_set=_decode_root_set(_require_field(row, "root_set", where), where),
    )


def _decode_graph_node_row(row: Mapping[str, object], where: str) -> GraphNodeRow:
    return GraphNodeRow(
        function=_row_symbol(row, "function", where),
        effect_signature=_require_str(row, "effect_signature", where),
        root_set=_decode_root_set(_require_field(row, "root_set", where), where),
        output_facts=tuple(_require_str_list(row, "output_facts", where)),
        resolution_state=_require_str(row, "resolution_state", where),
    )


def _decode_sink_role_row(row: Mapping[str, object], where: str) -> SinkRoleRow:
    return SinkRoleRow(
        symbol=_row_symbol(row, "symbol", where),
        authority_status=_require_str(row, "authority_status", where),
    )


def _decode_candidate_row(row: Mapping[str, object], where: str) -> CandidateRow:
    return CandidateRow(
        level=_require_str(row, "level", where),
        shared_fact=_require_str(row, "shared_fact", where),
        producer_set=_decode_symbol_set(
            _require_field(row, "producer_set", where), where
        ),
    )


def _decode_semantic_edge_row(row: Mapping[str, object], where: str) -> SemanticEdge:
    return SemanticEdge(
        source=_row_symbol(row, "source", where),
        target=_row_symbol(row, "target", where),
    )


def _decode_dependency_relation_row(
    row: Mapping[str, object], where: str
) -> DependencyRelationRow:
    return DependencyRelationRow(
        source=_decode_endpoint(_require_field(row, "source", where), where),
        target=_decode_endpoint(_require_field(row, "target", where), where),
        dependency_type=_require_str(row, "dependency_type", where),
    )


def _decode_dependency_occurrence_row(
    row: Mapping[str, object], where: str
) -> DependencyOccurrenceRow:
    return DependencyOccurrenceRow(
        relation=_decode_dependency_relation_row(row, where),
        line=_require_line(row, "line", where),
        binding=_require_str(row, "binding", where),
        is_lazy=_require_bool(row, "is_lazy", where),
    )


def _decode_dead_code_markers_value(
    value: object, where: str
) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list):
        raise StoreIntegrityError(f"{where}: stored markers are not an array")
    pairs = []
    for item in value:
        if not isinstance(item, list) or len(item) != 2:
            raise StoreIntegrityError(
                f"{where}: stored marker is not a [key, value] pair"
            )
        key, marker = item
        if not isinstance(key, str) or not isinstance(marker, str):
            raise StoreIntegrityError(
                f"{where}: stored marker is not a [key, value] pair"
            )
        pairs.append((key, marker))
    return tuple(pairs)


def _decode_dead_code_observation_row(
    row: Mapping[str, object], where: str
) -> DeadCodeObservationRow:
    """Shape guards only: vocabularies, count floors, and the
    abstention/root exclusivity have exactly one owner — the model law
    (``DeadCodeObservationRow``), wrapped by ``_collect_row``."""
    reason = _require_field(row, "live_root_reason", where)
    if reason is not None and not isinstance(reason, str):
        raise StoreIntegrityError(
            f"{where}: stored field 'live_root_reason' is not a string"
        )
    return DeadCodeObservationRow(
        entity=_decode_dead_code_entity_value(
            _require_field(row, "entity", where), where
        ),
        observation_kind=_require_str(row, "observation_kind", where),
        candidate_kind=_require_str(row, "candidate_kind", where),
        reference_count=_require_line(row, "reference_count", where),
        reachable=_require_bool(row, "reachable", where),
        runtime_marker_count=_require_line(row, "runtime_marker_count", where),
        source_markers=_decode_dead_code_markers_value(
            _require_field(row, "source_markers", where), where
        ),
        live_root_reason=reason,
        abstained=_require_bool(row, "abstained", where),
    )


def _decode_clone_item_value(value: object, where: str) -> CloneItemRow:
    if not isinstance(value, list) or len(value) != 4:
        raise StoreIntegrityError(
            f"{where}: stored clone item is not a [path, qualname, start, end] row"
        )
    path, qualname, start_line, end_line = value
    if not isinstance(path, str) or not isinstance(qualname, str):
        raise StoreIntegrityError(f"{where}: stored clone item names are not strings")
    if (
        isinstance(start_line, bool)
        or not isinstance(start_line, int)
        or isinstance(end_line, bool)
        or not isinstance(end_line, int)
    ):
        raise StoreIntegrityError(f"{where}: stored clone item span is not an int")
    return CloneItemRow(SymbolId(FileId(path), qualname), start_line, end_line)


def _decode_clone_group_row(row: Mapping[str, object], where: str) -> CloneGroupRow:
    """Shape guards only: the kind vocabulary, key floor, and two-item
    floor have exactly one owner — the model law (``CloneGroupRow``),
    whose refusal ``_collect_row`` wraps into a typed integrity error."""
    items = _require_field(row, "items", where)
    if not isinstance(items, list):
        raise StoreIntegrityError(f"{where}: stored field 'items' is not an array")
    return CloneGroupRow(
        clone_kind=_require_str(row, "clone_kind", where),
        group_key=_require_str(row, "group_key", where),
        items=frozenset(_decode_clone_item_value(item, where) for item in items),
    )


def _decode_dependency_cycle_row(
    row: Mapping[str, object], where: str
) -> DependencyCycleRow:
    """Shape guards only: the kind vocabulary and the two-module floor have
    exactly one owner — the model law (``DependencyCycleRow``), whose
    refusal ``_collect_row`` wraps into a typed integrity error."""
    return DependencyCycleRow(
        kind=_require_str(row, "kind", where),
        modules=frozenset(
            ModuleId(module) for module in _require_str_list(row, "modules", where)
        ),
    )


def _decode_adoption_count_row(
    row: Mapping[str, object], where: str
) -> AdoptionCountRow:
    """Shape guards only: the feature vocabulary and both count floors
    have exactly one owner — the model law (``AdoptionCountRow``), whose
    refusal ``_collect_row`` wraps into a typed integrity error."""
    return AdoptionCountRow(
        scope=_decode_endpoint(_require_field(row, "scope", where), where),
        feature=_require_str(row, "feature", where),
        numerator=_require_line(row, "numerator", where),
        denominator=_require_line(row, "denominator", where),
    )


def _decode_coupling_cohesion_row(
    row: Mapping[str, object], where: str
) -> CouplingCohesionRow:
    """Shape guards only: the numerator floor and the dimension vocabulary
    have exactly one owner — the model law (``CouplingCohesionRow``), whose
    refusal ``_collect_row`` wraps into a typed integrity error.  A second
    spelling of either domain here would be the G2 drift class."""
    return CouplingCohesionRow(
        symbol=_row_symbol(row, "symbol", where),
        dimension=_require_str(row, "dimension", where),
        numerator=_require_line(row, "numerator", where),
    )


def _decode_risk_observation_row(
    row: Mapping[str, object], where: str
) -> RiskObservationRow:
    """Shape guards only: the numerator/site floors and the dimension
    vocabulary have exactly one owner — the model law
    (``RiskObservationRow``), whose refusal ``_collect_row`` wraps into a
    typed integrity error.  A second spelling here would be the G2 drift
    class."""
    return RiskObservationRow(
        symbol=_row_symbol(row, "symbol", where),
        dimension=_require_str(row, "dimension", where),
        numerator=_require_line(row, "numerator", where),
        start_line=_require_line(row, "start_line", where),
    )


def _decode_api_parameter_value(value: object, where: str) -> ApiParameterFact:
    if not isinstance(value, list) or len(value) != 4:
        raise StoreIntegrityError(
            f"{where}: stored api parameter is not a "
            "[name, kind, has_default, annotation] row"
        )
    name, kind, has_default, annotation = value
    if not isinstance(name, str) or not isinstance(kind, str):
        raise StoreIntegrityError(
            f"{where}: stored api parameter names are not strings"
        )
    if not isinstance(has_default, bool):
        raise StoreIntegrityError(
            f"{where}: stored api default marker is not a boolean"
        )
    if annotation is not None and not isinstance(annotation, str):
        raise StoreIntegrityError(f"{where}: stored api annotation is not a string")
    return ApiParameterFact(name, kind, has_default, annotation)


def _decode_api_symbol_row(row: Mapping[str, object], where: str) -> ApiSymbolRow:
    parameters = _require_field(row, "parameters", where)
    if not isinstance(parameters, list):
        raise StoreIntegrityError(f"{where}: stored field 'parameters' is not an array")
    returns_digest = _require_field(row, "returns_digest", where)
    if returns_digest is not None and not isinstance(returns_digest, str):
        raise StoreIntegrityError(
            f"{where}: stored field 'returns_digest' is not a string"
        )
    return ApiSymbolRow(
        symbol=_row_symbol(row, "symbol", where),
        symbol_kind=_require_str(row, "symbol_kind", where),
        visibility=_require_str(row, "visibility", where),
        parameters=tuple(
            _decode_api_parameter_value(item, where) for item in parameters
        ),
        returns_digest=returns_digest,
    )


def _decode_security_surface_row(
    row: Mapping[str, object], where: str
) -> SecuritySurfaceRow:
    """Shape guards only: the vocabularies, span floors, and the
    scope/local-name binding have exactly one owner -- the model law
    (``SecuritySurfaceRow``), whose refusal ``_collect_row`` wraps into a
    typed integrity error."""
    qualname = _require_field(row, "qualname", where)
    if qualname is not None and not isinstance(qualname, str):
        raise StoreIntegrityError(f"{where}: stored field 'qualname' is not a string")
    return SecuritySurfaceRow(
        file=FileId(_require_str(row, "file", where)),
        start_line=_require_line(row, "start_line", where),
        end_line=_require_line(row, "end_line", where),
        evidence_symbol=_require_str(row, "evidence_symbol", where),
        qualname=qualname,
        location_scope=_require_str(row, "location_scope", where),
        category=_require_str(row, "category", where),
        capability=_require_str(row, "capability", where),
        evidence_kind=_require_str(row, "evidence_kind", where),
        classification_mode=_require_str(row, "classification_mode", where),
        source_kind=_require_str(row, "source_kind", where),
    )


def _decode_stored_pairs(value: object, where: str) -> list[tuple[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise StoreIntegrityError(f"{where}: stored pairs are not a list")
    pairs: list[tuple[str, object]] = []
    for item in value:
        if (
            not isinstance(item, Sequence)
            or isinstance(item, (str, bytes))
            or len(item) != 2
            or not isinstance(item[0], str)
        ):
            raise StoreIntegrityError(
                f"{where}: stored pair is not a [name, value] list"
            )
        pairs.append((item[0], item[1]))
    return pairs


def _decode_analysis_population_row(
    row: Mapping[str, object], where: str
) -> AnalysisPopulation:
    mode = _require_str(row, "analysis_mode", where)
    profile: list[tuple[str, int]] = []
    for name, value in _decode_stored_pairs(
        _require_field(row, "analysis_profile", where), f"{where}.analysis_profile"
    ):
        if isinstance(value, bool) or not isinstance(value, int):
            raise StoreIntegrityError(
                f"{where}.analysis_profile: stored value of {name!r} is not an int"
            )
        profile.append((name, value))
    states: list[tuple[str, str]] = []
    for family, state in _decode_stored_pairs(
        _require_field(row, "producer_states", where), f"{where}.producer_states"
    ):
        if not isinstance(state, str):
            raise StoreIntegrityError(
                f"{where}.producer_states: stored state of {family!r} is not a string"
            )
        states.append((family, state))
    return AnalysisPopulation(
        analysis_mode=mode,
        analysis_profile=tuple(profile),
        producer_states=tuple(states),
    )


def _decode_run_scalar_row(row: Mapping[str, object], where: str) -> RunScalars:
    return RunScalars(
        classes=_require_line(row, "classes", where),
        files_analyzed=_require_line(row, "files_analyzed", where),
        files_cached=_require_line(row, "files_cached", where),
        files_found=_require_line(row, "files_found", where),
        files_skipped=_require_line(row, "files_skipped", where),
        functions=_require_line(row, "functions", where),
        methods=_require_line(row, "methods", where),
        parsed_lines=_require_line(row, "parsed_lines", where),
        source_io_skipped=_require_line(row, "source_io_skipped", where),
        unsupported_construct_skipped=_require_line(
            row, "unsupported_construct_skipped", where
        ),
    )


def _decode_violation_row(row: Mapping[str, object], where: str) -> ViolationRow:
    return ViolationRow(
        contract_id=_require_str(row, "contract_id", where),
        kind=_require_str(row, "kind", where),
        sink_identity=_row_symbol(row, "sink_identity", where),
        canonical_owner=_row_symbol(row, "canonical_owner", where),
        authority_status=_require_str(row, "authority_status", where),
        effect_signature=_require_str(row, "effect_signature", where),
        resolution_state=_require_str(row, "resolution_state", where),
        root_set=_decode_root_set(_require_field(row, "root_set", where), where),
        producer_set=_decode_symbol_set(
            _require_field(row, "producer_set", where), where
        ),
        suppressed=_require_bool(row, "suppressed", where),
        locations=_decode_source_locations(
            _require_field(row, "locations", where), f"{where}.locations"
        ),
    )


# ---------------------------------------------------------------------------
# The family registry — the one place a storage family is declared
# ---------------------------------------------------------------------------


class _FamilyEntry(Protocol):
    """The registry's erased face — what a caller still needs from an entry
    once the row type has done its work at declaration time."""

    @property
    def family(self) -> str: ...

    @property
    def namespace(self) -> str: ...

    def decode_into(
        self, into: dict[str, list[object]], row: Mapping[str, object], where: str
    ) -> None: ...


@dataclass(frozen=True)
class _Family(Generic[_RowT]):
    """One storage family: its name, the contract namespace of its content
    address, the decoder that reads its stored row, and the type that
    decoder produces — the mechanical inverse of one family of
    :func:`_model_rows`.

    ``decode`` and ``row_type`` bind the SAME ``_RowT``, so a family's row
    type is ONE declaration rather than an agreement between two that
    nothing checks: a decoder that stops producing its declared type is a
    type error here (mypy ``Argument "decode" ... has incompatible type``;
    ty ``invalid-argument-type``), and a family cannot be declared at all
    without saying what it decodes to.

    :meth:`rows` is why the model assembly needs no ``cast``.  Decoded rows
    wait in an untyped per-family mapping — heterogeneous by construction,
    since the family is a string read from the database — and the row type
    is recovered by CHECKING it against the declaration, never by asserting
    it.  A row filed under the wrong family is a typed refusal instead of a
    silently wrong model.
    """

    family: str
    namespace: str
    decode: Callable[[Mapping[str, object], str], _RowT]
    row_type: type[_RowT]

    def decode_into(
        self, into: dict[str, list[object]], row: Mapping[str, object], where: str
    ) -> None:
        into.setdefault(self.family, []).append(self.decode(row, where))

    def rows(self, collected: Mapping[str, list[object]]) -> list[_RowT]:
        decoded: list[_RowT] = []
        for row in collected.get(self.family, []):
            if not isinstance(row, self.row_type):
                raise StoreIntegrityError(
                    f"family {self.family!r} carries a {type(row).__name__}, "
                    f"not a {self.row_type.__name__}"
                )
            decoded.append(row)
        return decoded


# Every storage family, declared once.  The namespace half is the family
# contract namespace of F-3 §5.0.1: a fact's content address carries the
# revision of the contract that gives it meaning, so a fact identity never
# silently crosses a producer revision.

# F3: counting meaning — what counts as an annotated parameter or a
# documented public symbol — is owned by the adoption-coverage policy, so a
# policy bump never lets these facts silently share content addresses
# across generations.
_FAMILY_ADOPTION_COUNT: Final = _Family(
    family="adoption_count",
    namespace=f"adoption_coverage:{ADOPTION_COVERAGE_POLICY_VERSION}",
    decode=_decode_adoption_count_row,
    row_type=AdoptionCountRow,
)
_FAMILY_ANALYSIS_POPULATION: Final = _Family(
    family="analysis_population",
    namespace=f"canonical_model:{CANONICAL_MODEL_REVISION}",
    decode=_decode_analysis_population_row,
    row_type=AnalysisPopulation,
)
_FAMILY_ANALYZED_FILE: Final = _Family(
    family="analyzed_file",
    namespace=f"module_identity:{MODULE_IDENTITY_VERSION}",
    decode=_decode_file_row,
    row_type=FileId,
)
# F5: signature meaning is owned by the API signature contract — a
# signature-algorithm revision never lets these facts silently share
# content addresses across generations.
_FAMILY_API_SYMBOL: Final = _Family(
    family="api_symbol",
    namespace=f"api_surface_signature:{API_SURFACE_SIGNATURE_VERSION}",
    decode=_decode_api_symbol_row,
    row_type=ApiSymbolRow,
)
_FAMILY_CANDIDATE: Final = _Family(
    family="candidate",
    namespace=f"authority_analysis:{AUTHORITY_ANALYSIS_REVISION}",
    decode=_decode_candidate_row,
    row_type=CandidateRow,
)
# F8: group_key meaning is owned by the clone fingerprint generation — a
# fingerprint-generation bump never lets these facts silently share content
# addresses across generations.
_FAMILY_CLONE_GROUP: Final = _Family(
    family="clone_group",
    namespace=f"clone_fingerprint:{BASELINE_FINGERPRINT_VERSION}",
    decode=_decode_clone_group_row,
    row_type=CloneGroupRow,
)
_FAMILY_CONTRACT: Final = _Family(
    family="contract",
    namespace=f"contract_ir:{CONTRACT_IR_VERSION}",
    decode=_decode_contract_row,
    row_type=ContractRow,
)
_FAMILY_COUPLED_SET: Final = _Family(
    family="coupled_set",
    namespace=f"canonical_model:{CANONICAL_MODEL_REVISION}",
    decode=_decode_coupled_row,
    row_type=frozenset,
)
# F2: the Wave D lane split put coupling/cohesion meaning on the design
# metrics revision (complexity moved to its own), so a design-metrics
# recount never lets these facts silently share content addresses.
_FAMILY_COUPLING_COHESION: Final = _Family(
    family="coupling_cohesion_observation",
    namespace=f"design_metrics:{DESIGN_METRICS_ALGORITHM_REVISION}",
    decode=_decode_coupling_cohesion_row,
    row_type=CouplingCohesionRow,
)
# F4: TWO policy owners give this family meaning — liveness for symbol
# rows, statement reachability for unreachable-statement rows — so both
# revisions enter the content-address namespace and neither can bump
# silently under the other.
_FAMILY_DEAD_CODE_OBSERVATION: Final = _Family(
    family="dead_code_observation",
    namespace=(
        f"liveness:{LIVENESS_POLICY_VERSION}"
        f":statement_reachability:{STATEMENT_REACHABILITY_POLICY_VERSION}"
    ),
    decode=_decode_dead_code_observation_row,
    row_type=DeadCodeObservationRow,
)
# F7: the cycle verdict is a canonical-model analysis fact over the
# relation graph; no separate cycle-algorithm revision exists, and the
# relation families it reads share this namespace.
_FAMILY_DEPENDENCY_CYCLE: Final = _Family(
    family="dependency_cycle",
    namespace=f"canonical_model:{CANONICAL_MODEL_REVISION}",
    decode=_decode_dependency_cycle_row,
    row_type=DependencyCycleRow,
)
_FAMILY_DEPENDENCY_OCCURRENCE: Final = _Family(
    family="dependency_occurrence",
    namespace=f"canonical_model:{CANONICAL_MODEL_REVISION}",
    decode=_decode_dependency_occurrence_row,
    row_type=DependencyOccurrenceRow,
)
_FAMILY_DEPENDENCY_RELATION: Final = _Family(
    family="dependency_relation",
    namespace=f"canonical_model:{CANONICAL_MODEL_REVISION}",
    decode=_decode_dependency_relation_row,
    row_type=DependencyRelationRow,
)
_FAMILY_FILE: Final = _Family(
    family="file",
    namespace=f"module_identity:{MODULE_IDENTITY_VERSION}",
    decode=_decode_file_row,
    row_type=FileId,
)
_FAMILY_FILE_MODULE: Final = _Family(
    family="file_module",
    namespace=f"module_identity:{MODULE_IDENTITY_VERSION}",
    decode=_decode_file_module_row,
    row_type=FileModuleRelation,
)
_FAMILY_GRAPH_NODE: Final = _Family(
    family="graph_node",
    namespace=f"contract_ir:{CONTRACT_IR_VERSION}",
    decode=_decode_graph_node_row,
    row_type=GraphNodeRow,
)
_FAMILY_MODULE: Final = _Family(
    family="module",
    namespace=f"module_identity:{MODULE_IDENTITY_VERSION}",
    decode=_decode_module_row,
    row_type=ModuleId,
)
# F1: the risk lane rides COMPLEXITY_ALGORITHM_REVISION (the Wave D
# two-metric split), so a complexity recount never lets these facts
# silently share content addresses across generations.
_FAMILY_RISK_OBSERVATION: Final = _Family(
    family="risk_observation",
    namespace=f"complexity_metrics:{COMPLEXITY_ALGORITHM_REVISION}",
    decode=_decode_risk_observation_row,
    row_type=RiskObservationRow,
)
_FAMILY_RUN_SCALAR: Final = _Family(
    family="run_scalar",
    namespace=f"canonical_model:{CANONICAL_MODEL_REVISION}",
    decode=_decode_run_scalar_row,
    row_type=RunScalars,
)
# F10: TWO policy owners give this family meaning -- the detector catalog
# (which symbols and capabilities exist) and the source-kind classification
# verdict -- so both revisions enter the content-address namespace and
# neither can bump silently under the other (the F4 two-owner precedent).
_FAMILY_SECURITY_SURFACE: Final = _Family(
    family="security_surface",
    namespace=(
        f"security_surface_catalog:{SECURITY_SURFACE_CATALOG_VERSION}"
        f":source_kind:{SOURCE_KIND_POLICY_VERSION}"
    ),
    decode=_decode_security_surface_row,
    row_type=SecuritySurfaceRow,
)
_FAMILY_SEMANTIC_EDGE: Final = _Family(
    family="semantic_edge",
    namespace=f"contract_ir:{CONTRACT_IR_VERSION}",
    decode=_decode_semantic_edge_row,
    row_type=SemanticEdge,
)
_FAMILY_SINK_ROLE: Final = _Family(
    family="sink_role",
    namespace=f"authority_analysis:{AUTHORITY_ANALYSIS_REVISION}",
    decode=_decode_sink_role_row,
    row_type=SinkRoleRow,
)
_FAMILY_VIOLATION: Final = _Family(
    family="violation",
    namespace=f"authority_analysis:{AUTHORITY_ANALYSIS_REVISION}",
    decode=_decode_violation_row,
    row_type=ViolationRow,
)

_FAMILIES: Final[tuple[_FamilyEntry, ...]] = (
    _FAMILY_ADOPTION_COUNT,
    _FAMILY_ANALYSIS_POPULATION,
    _FAMILY_ANALYZED_FILE,
    _FAMILY_API_SYMBOL,
    _FAMILY_CANDIDATE,
    _FAMILY_CLONE_GROUP,
    _FAMILY_CONTRACT,
    _FAMILY_COUPLED_SET,
    _FAMILY_COUPLING_COHESION,
    _FAMILY_DEAD_CODE_OBSERVATION,
    _FAMILY_DEPENDENCY_CYCLE,
    _FAMILY_DEPENDENCY_OCCURRENCE,
    _FAMILY_DEPENDENCY_RELATION,
    _FAMILY_FILE,
    _FAMILY_FILE_MODULE,
    _FAMILY_GRAPH_NODE,
    _FAMILY_MODULE,
    _FAMILY_RISK_OBSERVATION,
    _FAMILY_RUN_SCALAR,
    _FAMILY_SECURITY_SURFACE,
    _FAMILY_SEMANTIC_EDGE,
    _FAMILY_SINK_ROLE,
    _FAMILY_VIOLATION,
)

# Derived, never restated: the reader dispatch and the content address read
# the SAME declarations, so a family cannot exist for one and be missing for
# the other.  Dispatch is total over _FAMILY_NAMESPACE by construction; an
# unknown family is a typed integrity refusal, never a silent skip.
_FAMILY_READER: Final[dict[str, _FamilyEntry]] = {
    entry.family: entry for entry in _FAMILIES
}
_FAMILY_NAMESPACE: Final[dict[str, str]] = {
    entry.family: entry.namespace for entry in _FAMILIES
}


def _collect_row(
    family: str, row: Mapping[str, object], where: str, into: dict[str, list[object]]
) -> None:
    entry = _FAMILY_READER.get(family)
    if entry is None:
        raise StoreIntegrityError(f"{where}: unknown stored family {family!r}")
    try:
        entry.decode_into(into, row, where)
    except CanonicalModelError as error:
        raise StoreIntegrityError(f"{where}: {error}") from error


def _collected_model(collected: Mapping[str, list[object]]) -> CanonicalModel:
    """Assemble decoded family rows into one canonical model."""
    run_scalar_rows = _FAMILY_RUN_SCALAR.rows(collected)
    if len(run_scalar_rows) > 1:
        # F9 law: ONE record per analysis snapshot — two stored records are
        # a writer defect, refused loudly, never last-reader-silenced.
        raise StoreIntegrityError(
            "run carries more than one run_scalars record; the family is "
            "one record per analysis snapshot"
        )
    population_rows = _FAMILY_ANALYSIS_POPULATION.rows(collected)
    if len(population_rows) > 1:
        # RULING-2026-08-31 §3: a singleton authority — two stored records
        # are a writer defect, refused loudly, never last-reader-silenced.
        raise StoreIntegrityError(
            "run carries more than one analysis_population record; the "
            "family is one record per analysis snapshot"
        )
    return CanonicalModel(
        files=frozenset(_FAMILY_FILE.rows(collected)),
        modules=frozenset(_FAMILY_MODULE.rows(collected)),
        analyzed_files=frozenset(_FAMILY_ANALYZED_FILE.rows(collected)),
        file_modules=frozenset(_FAMILY_FILE_MODULE.rows(collected)),
        facts=CanonicalFacts(
            analysis=AnalysisFacts(
                contracts=frozenset(_FAMILY_CONTRACT.rows(collected)),
                graph_nodes=frozenset(_FAMILY_GRAPH_NODE.rows(collected)),
                sink_roles=frozenset(_FAMILY_SINK_ROLE.rows(collected)),
                candidates=frozenset(_FAMILY_CANDIDATE.rows(collected)),
                semantic_edges=frozenset(_FAMILY_SEMANTIC_EDGE.rows(collected)),
                dependency_relations=frozenset(
                    _FAMILY_DEPENDENCY_RELATION.rows(collected)
                ),
                dependency_occurrences=frozenset(
                    _FAMILY_DEPENDENCY_OCCURRENCE.rows(collected)
                ),
                dependency_cycles=frozenset(_FAMILY_DEPENDENCY_CYCLE.rows(collected)),
                clone_groups=frozenset(_FAMILY_CLONE_GROUP.rows(collected)),
                dead_code_observations=frozenset(
                    _FAMILY_DEAD_CODE_OBSERVATION.rows(collected)
                ),
                violations=frozenset(_FAMILY_VIOLATION.rows(collected)),
                coupling_cohesion_observations=frozenset(
                    _FAMILY_COUPLING_COHESION.rows(collected)
                ),
                api_symbols=frozenset(_FAMILY_API_SYMBOL.rows(collected)),
                risk_observations=frozenset(_FAMILY_RISK_OBSERVATION.rows(collected)),
                adoption_counts=frozenset(_FAMILY_ADOPTION_COUNT.rows(collected)),
                security_surfaces=frozenset(_FAMILY_SECURITY_SURFACE.rows(collected)),
                run_scalars=run_scalar_rows[0] if run_scalar_rows else None,
                analysis_population=(population_rows[0] if population_rows else None),
            )
        ),
        coupled_sets=frozenset(_FAMILY_COUPLED_SET.rows(collected)),
    )


# ---------------------------------------------------------------------------
# Digests
# ---------------------------------------------------------------------------


def _object_id(namespace: str, family: str, payload: bytes) -> str:
    preimage = b"\x00".join(
        (
            _DOMAIN_OBJECT + namespace.encode("utf-8"),
            family.encode("utf-8"),
            _FAMILY_NAMESPACE[family].encode("utf-8"),
            payload,
        )
    )
    return hashlib.sha256(preimage).hexdigest()


def analysis_scope_digest(analyzed_files: frozenset[FileId]) -> str:
    """Scope receipt digest (brief §7.1, wave-2 minimal honest input): the
    canonical digest of the analyzed-file identity set.

    The sort is a determinism owner: it is the only thing standing between
    ``run_id`` and the interpreter's ``frozenset`` layout.  Dropping it was
    measured to move ``run_id`` between hash seeds while staying green on
    the known-answer literals at seed 1 — the hash-seed pin in
    ``tests/test_canonical_store.py`` is what catches it by construction.
    """
    paths = sorted(file_id.path for file_id in analyzed_files)
    return hashlib.sha256(_DOMAIN_SCOPE + _payload_bytes(paths)).hexdigest()


def _membership_digest(object_ids: Sequence[str]) -> str:
    """Digest of a run's member set — order-free by owning its own sort.

    Because the sort lives here, no caller has to supply an ordered list:
    ``write_full_run`` passes staged-dict order and
    :func:`_verify_staged_membership` passes SQL order, and the two must
    agree.  Dropping the sort splits them and publish refuses.
    """
    joined = "\x00".join(sorted(object_ids)).encode("utf-8")
    return hashlib.sha256(_DOMAIN_MEMBERSHIP + joined).hexdigest()


def _run_id(namespace: str, scope_digest: str, membership_digest: str) -> str:
    analysis_layers = [
        f"{layer}:{revision}"
        for layer, revision, role in _WITNESS_LAYERS
        if role == "analysis"
    ]
    preimage = b"\x00".join(
        (
            _DOMAIN_RUN + namespace.encode("utf-8"),
            "\x00".join(analysis_layers).encode("utf-8"),
            scope_digest.encode("utf-8"),
            membership_digest.encode("utf-8"),
        )
    )
    return hashlib.sha256(preimage).hexdigest()


def _contract_epoch() -> str:
    layers = [f"{layer}:{revision}" for layer, revision, _role in _WITNESS_LAYERS]
    return hashlib.sha256(
        _DOMAIN_CONTRACT_EPOCH + "\x00".join(layers).encode("utf-8")
    ).hexdigest()


# ---------------------------------------------------------------------------
# Store transaction steps (module-level: RunStore owns transactions and
# lifecycle; the pure steps live here, in the codec's function-per-step
# style)
# ---------------------------------------------------------------------------


def _open_witness(cursor: sqlite3.Cursor) -> tuple[int, str, str]:
    """Create-or-verify the layered witness; returns the fence triple.

    Law 7: an existing store whose witness is not this process's declared
    generation is refused, never reinterpreted.
    """
    meta = cursor.execute(
        "SELECT store_epoch, storage_schema_revision, contract_epoch "
        "FROM store_meta WHERE id = 1"
    ).fetchone()
    if meta is None:
        for layer, revision, role in _WITNESS_LAYERS:
            cursor.execute(
                "INSERT INTO witness (layer, revision, role) VALUES (?, ?, ?)",
                (layer, revision, role),
            )
        epoch = _contract_epoch()
        cursor.execute(
            "INSERT INTO store_meta "
            "(id, store_epoch, storage_schema_revision, contract_epoch) "
            "VALUES (1, 1, ?, ?)",
            (STORAGE_SCHEMA_REVISION, epoch),
        )
        return (1, STORAGE_SCHEMA_REVISION, epoch)
    stored = dict(cursor.execute("SELECT layer, revision FROM witness ORDER BY layer"))
    declared = {layer: revision for layer, revision, _role in _WITNESS_LAYERS}
    if stored != declared:
        diverging = sorted(set(stored.items()) ^ set(declared.items()))
        raise StoreCompatibilityError(
            "store witness is not this process's declared generation; "
            f"diverging layers: {diverging!r}. Refusing the stored "
            "generation (law 7)."
        )
    return (int(meta[0]), str(meta[1]), str(meta[2]))


def _fence_guard(cursor: sqlite3.Cursor, fence: tuple[int, str, str]) -> None:
    """Refuse the mutation when the store generation moved under the handle
    (brief §4.2: fencing on every mutation, not only at open)."""
    row = cursor.execute(
        "SELECT store_epoch, storage_schema_revision, contract_epoch "
        "FROM store_meta WHERE id = 1"
    ).fetchone()
    current = (int(row[0]), str(row[1]), str(row[2])) if row else None
    if current != fence:
        raise StoreFenceError(
            f"store generation moved under this handle (held {fence!r}, "
            f"current {current!r}); write refused"
        )


@contextmanager
def _fenced_transaction(store: RunStore) -> Iterator[sqlite3.Cursor]:
    """One fenced IMMEDIATE transaction over a store's connection — the one
    spelling shared by every GC-side mutation (brief §4.2: fencing on every
    mutation), a module-level step like :func:`_fence_guard` it wraps."""
    cursor = store._connection.cursor()
    cursor.execute("BEGIN IMMEDIATE")
    try:
        _fence_guard(cursor, store._fence)
        yield cursor
        cursor.execute("COMMIT")
    except BaseException:
        cursor.execute("ROLLBACK")
        raise


# ---------------------------------------------------------------------------
# Operational measurement.  Diagnostics only: the store's state produces
# these numbers, and nothing reads them back — no canonical fact, no run
# identity and no publish decision depends on a measurement or on whether
# the observer is running at all (pinned by the observer OFF/ON witness).
# ---------------------------------------------------------------------------


def _elapsed_us(started: float) -> int:
    """Whole microseconds since ``started``; the counter lane is integral."""
    return int((time.perf_counter() - started) * 1_000_000)


def _database_bytes(cursor: sqlite3.Cursor) -> int:
    """The database's own page arithmetic.

    Not the file size: in WAL mode the main file only grows at a
    checkpoint, so a publish's growth would be attributed to whichever
    later publish happened to trigger one.
    """
    page_count = int(cursor.execute("PRAGMA page_count").fetchone()[0])
    page_size = int(cursor.execute("PRAGMA page_size").fetchone()[0])
    return page_count * page_size


def _require_publish_inputs(namespace: str, target: str) -> None:
    if not namespace:
        raise RunStoreError("namespace must be non-empty")
    if not target:
        raise RunStoreError("target must be non-empty")


def _verify_staged_membership(
    cursor: sqlite3.Cursor, run_pk: int, namespace: str, membership: str
) -> None:
    """Re-verify the staged run from the database rows themselves before
    the publish flip (brief §10: verify digests inside the transaction).

    Every member's bytes must still hash to its own content address: a
    publish that sealed corrupted staging would produce a published run no
    reader can decode — law 5 promises the previous generation or the next
    COMPLETE one, never a published-but-unreadable state.  The membership
    digest over the member ids must reproduce as well.
    """
    stored_ids: list[str] = []
    for object_id_value, family, payload in cursor.execute(
        "SELECT o.object_id, o.family, o.payload FROM run_members m "
        "JOIN objects o ON o.object_pk = m.object_pk "
        "WHERE m.run_pk = ? ORDER BY o.object_id",
        (run_pk,),
    ):
        stored_id = str(object_id_value)
        if _object_id(namespace, str(family), bytes(payload)) != stored_id:
            raise StoreIntegrityError(
                f"staged object {stored_id[:12]}… does not hash to its "
                "content address; publish refused"
            )
        stored_ids.append(stored_id)
    if _membership_digest(stored_ids) != membership:
        raise RunStoreError(
            "staged membership does not reproduce its digest; publish refused"
        )


def _published_run_row(
    source: sqlite3.Connection | sqlite3.Cursor, run_id: str
) -> tuple[int, str, str, str]:
    """The one spelling of the published-run lookup.

    ``source`` is a connection on the read paths and the OPEN cursor of a
    fenced transaction on the write path: the edge writer must read the row
    it is about to address inside the same transaction that writes the
    edge, or the row could be collected between the two statements.
    """
    row = source.execute(
        "SELECT r.run_pk, n.namespace, r.analysis_scope_digest, "
        "r.membership_digest FROM runs r "
        "JOIN namespaces n ON n.namespace_pk = r.namespace_pk "
        "WHERE r.run_id = ? AND r.published = 1",
        (run_id,),
    ).fetchone()
    if row is None:
        raise UnknownRunError(f"run {run_id!r} is not a published run")
    return (int(row[0]), str(row[1]), str(row[2]), str(row[3]))


def _decode_member_object(
    namespace: str,
    object_id_value: str,
    family: str,
    payload: bytes,
    into: dict[str, list[object]],
) -> None:
    """Prove one stored member against its content address and decode it
    into the typed bucket its family declares.

    The one spelling of the member read: the full-model reconstruction and
    the bounded exporter both pass every stored byte through here, so a
    corrupt payload is the same typed refusal on either path.
    """
    if _object_id(namespace, family, payload) != object_id_value:
        raise StoreIntegrityError(
            f"object {object_id_value[:12]}… does not hash to its "
            "content address; store bytes are corrupt"
        )
    try:
        row = json.loads(payload)
    except ValueError as error:
        raise StoreIntegrityError(
            f"object {object_id_value[:12]}… payload is not storage JSON: {error}"
        ) from error
    if not isinstance(row, dict):
        raise StoreIntegrityError(
            f"object {object_id_value[:12]}… payload is not a row"
        )
    _collect_row(family, row, f"{family} object", into)


def _prove_run_digests(
    *,
    object_ids: Sequence[str],
    analyzed_files: frozenset[FileId],
    namespace: str,
    scope_digest: str,
    membership: str,
    run_id: str,
) -> None:
    """The one spelling of the run-proof tail, shared by the materializing
    read path and the bounded exporter: the membership digest, the scope
    receipt, and the run identity must recompute from the stored rows —
    any disagreement is a typed refusal, never a silently different run."""
    if _membership_digest(list(object_ids)) != membership:
        raise StoreIntegrityError(
            f"run {run_id!r} membership does not reproduce its digest"
        )
    if analysis_scope_digest(analyzed_files) != scope_digest:
        raise StoreIntegrityError(
            f"run {run_id!r} scope receipt does not reproduce its digest"
        )
    if _run_id(namespace, scope_digest, membership) != run_id:
        raise StoreIntegrityError(
            f"run {run_id!r} identity does not recompute from its parts"
        )


def _reconstruct_run(
    connection: sqlite3.Connection,
    *,
    run_pk: int,
    namespace: str,
    scope_digest: str,
    membership: str,
    run_id: str,
) -> CanonicalModel:
    """Rebuild one published run, proving every stored byte on the way.

    Every payload is re-hashed against its content address, the membership
    digest, the scope receipt, and the run identity are recomputed from the
    stored rows; any disagreement is a typed refusal, never a silently
    different model.
    """
    collected: dict[str, list[object]] = {}
    object_ids: list[str] = []
    rows = connection.execute(
        "SELECT o.object_id, o.family, o.payload FROM run_members m "
        "JOIN objects o ON o.object_pk = m.object_pk "
        "WHERE m.run_pk = ? ORDER BY o.object_id",
        (run_pk,),
    )
    for object_id_value, family, payload in rows:
        family_name = str(family)
        if family_name not in _FAMILY_NAMESPACE:
            raise StoreIntegrityError(
                f"run {run_id!r} carries unknown family {family_name!r}"
            )
        _decode_member_object(
            namespace, str(object_id_value), family_name, bytes(payload), collected
        )
        object_ids.append(str(object_id_value))
    model = _collected_model(collected)
    _prove_run_digests(
        object_ids=object_ids,
        analyzed_files=model.analyzed_files,
        namespace=namespace,
        scope_digest=scope_digest,
        membership=membership,
        run_id=run_id,
    )
    return model.normalize()


# ---------------------------------------------------------------------------
# Bounded export (backend wave 3)
# ---------------------------------------------------------------------------

# Families whose rows are identity/scope state rather than fact tables; the
# export's first pass turns them directly into the projection plan.
_IDENTITY_FAMILIES: Final = frozenset(
    {"analyzed_file", "coupled_set", "file", "file_module", "module"}
)

# Wire fact-table name -> storage family name. The wire speaks the
# registry's plural table names; storage rows carry the singular family of
# the content address.  A missing entry is a loud KeyError, and a wrong one
# turns a family empty — which the byte-parity oracle against
# ``project_run`` catches (measured during wave 3: the first draft scanned
# wire names and exported eight empty tables).
_WIRE_FAMILY_STORAGE: Final[dict[str, str]] = {
    "adoption_counts": "adoption_count",
    "analysis_population": "analysis_population",
    "api_symbols": "api_symbol",
    "candidates": "candidate",
    "clone_groups": "clone_group",
    "contracts": "contract",
    "coupling_cohesion_observations": "coupling_cohesion_observation",
    "dead_code_observations": "dead_code_observation",
    "dependency_cycles": "dependency_cycle",
    "dependency_occurrences": "dependency_occurrence",
    "dependency_relations": "dependency_relation",
    "file_modules": "file_module",
    "graph_nodes": "graph_node",
    "risk_observations": "risk_observation",
    "run_scalars": "run_scalar",
    "security_surfaces": "security_surface",
    "semantic_edges": "semantic_edge",
    "sink_roles": "sink_role",
    "violations": "violation",
}

_MEMBER_FAMILY_SQL: Final = (
    "SELECT o.object_id, o.payload FROM run_members m "
    "JOIN objects o ON o.object_pk = m.object_pk "
    "WHERE m.run_pk = ? AND o.family = ? ORDER BY o.object_id"
)


class _ArtifactStream:
    """Counting, artifact-hashing wrapper around one export sink.

    The artifact digest preimage is seeded from the one domain owner
    (:func:`codeclone.canonical.export.artifact_domain`) and covers every
    byte written — the projection-layer identity of these bytes, which the
    run identity deliberately is not (brief §5).
    """

    __slots__ = ("_hasher", "_sink", "byte_count")

    def __init__(self, sink: ByteSink) -> None:
        self._sink = sink
        self._hasher = hashlib.sha256(artifact_domain())
        self.byte_count = 0

    def write(self, data: bytes) -> None:
        self._hasher.update(data)
        self._sink.write(data)
        self.byte_count += len(data)

    def digest(self) -> str:
        return self._hasher.hexdigest()


def _scan_run_family(
    connection: sqlite3.Connection,
    run_pk: int,
    namespace: str,
    family: str,
    object_ids: list[str],
    into: dict[str, list[object]],
) -> None:
    """Decode one family of one run into its bucket, row by row, proving
    every byte."""
    for object_id_value, payload in connection.execute(
        _MEMBER_FAMILY_SQL, (run_pk, family)
    ):
        stored_id = str(object_id_value)
        _decode_member_object(namespace, stored_id, family, bytes(payload), into)
        object_ids.append(stored_id)


def _family_facts(
    connection: sqlite3.Connection, run_pk: int, namespace: str, wire_family: str
) -> AnalysisFacts:
    """One fact family of one run — the bounded provider of the second
    export pass.  Only this family's rows are alive at a time."""
    family = _WIRE_FAMILY_STORAGE[wire_family]
    object_ids: list[str] = []
    rows: dict[str, list[object]] = {}
    _scan_run_family(connection, run_pk, namespace, family, object_ids, rows)
    return _collected_model(rows).facts.analysis


def _export_plan(
    connection: sqlite3.Connection,
    *,
    run_pk: int,
    namespace: str,
    scope_digest: str,
    membership: str,
    run_id: str,
) -> WirePlan:
    """First export pass: prove the run and collect the projection plan.

    Streams every member once — content address per object, membership
    digest, scope receipt, and run identity are all recomputed from the
    stored rows before the first output byte exists.  Fact rows contribute
    their identity-domain and set-table parts family by family and are
    dropped; the complete model is never materialized (brief law 11).
    """
    stored_families = {
        str(row[0])
        for row in connection.execute(
            "SELECT DISTINCT o.family FROM run_members m "
            "JOIN objects o ON o.object_pk = m.object_pk "
            "WHERE m.run_pk = ?",
            (run_pk,),
        )
    }
    unknown = sorted(stored_families - set(_FAMILY_NAMESPACE))
    if unknown:
        raise StoreIntegrityError(
            f"run {run_id!r} carries unknown families {unknown!r}"
        )
    object_ids: list[str] = []
    identity_rows: dict[str, list[object]] = {}
    symbols: set[SymbolId] = set()
    root_sets: set[frozenset[EffectRoot]] = set()
    producer_sets: set[frozenset[SymbolId]] = set()
    for family in sorted(_FAMILY_NAMESPACE):
        if family in _IDENTITY_FAMILIES:
            _scan_run_family(
                connection, run_pk, namespace, family, object_ids, identity_rows
            )
            continue
        rows: dict[str, list[object]] = {}
        _scan_run_family(connection, run_pk, namespace, family, object_ids, rows)
        facts = _collected_model(rows).facts.analysis
        symbols |= referenced_symbols(facts)
        root_sets |= fact_root_sets(facts)
        producer_sets |= fact_producer_sets(facts)
    skeleton = _collected_model(identity_rows)
    _prove_run_digests(
        object_ids=object_ids,
        analyzed_files=skeleton.analyzed_files,
        namespace=namespace,
        scope_digest=scope_digest,
        membership=membership,
        run_id=run_id,
    )
    return plan_from_parts(
        files=skeleton.files,
        modules=skeleton.modules,
        symbols=symbols,
        root_sets=root_sets,
        producer_sets=producer_sets,
        coupled_sets=skeleton.coupled_sets,
        analyzed_files=skeleton.analyzed_files,
        file_modules=skeleton.file_modules,
    )


def _witness_state(connection: sqlite3.Connection) -> tuple[WitnessLayer, ...]:
    """The store's layered witness as stored — the envelope's linkage is to
    the store generation, not to process constants."""
    return tuple(
        WitnessLayer(layer=str(row[0]), revision=str(row[1]), role=str(row[2]))
        for row in connection.execute(
            "SELECT layer, revision, role FROM witness ORDER BY layer"
        )
    )


def _stream_export(
    connection: sqlite3.Connection,
    sink: ByteSink,
    *,
    run_pk: int,
    namespace: str,
    scope_digest: str,
    membership: str,
    run_id: str,
) -> ExportEnvelope:
    """Both export passes of one pinned run: prove, then stream.

    Pass one proves the run and collects the projection plan row by row;
    pass two re-reads one fact family at a time through the single wire
    emitter.  Nothing reaches ``sink`` before the whole run has proven its
    digests.  The caller resolved the run identity exactly once and fired
    the snapshot seam (§11.1) before entering.
    """
    plan = _export_plan(
        connection,
        run_pk=run_pk,
        namespace=namespace,
        scope_digest=scope_digest,
        membership=membership,
        run_id=run_id,
    )
    stream = _ArtifactStream(sink)
    stream_canonical_wire(
        plan,
        lambda family: _family_facts(connection, run_pk, namespace, family),
        stream.write,
    )
    return ExportEnvelope(
        run_id=run_id,
        artifact_digest=stream.digest(),
        byte_count=stream.byte_count,
        wire_revision=CANONICAL_WIRE_REVISION,
        witness=_witness_state(connection),
    )


# ---------------------------------------------------------------------------
# Garbage collection (ruling 2026-08-24 §8) — the run-store job of the
# unified GC point (contract: codeclone.models; runtime door:
# codeclone.api.gc).  Pure sweep steps live here in the
# module's function-per-step style; RunStore owns the one transaction.
#
# The roots, each with an owner who sets it and an owner who clears it:
#
# * heads — set by the publish CAS; cleared only by being superseded.
#   Durable by design: the head is the truth pointer and must survive any
#   process death.  The root is "every row of the heads table", never "the
#   one latest run" — so when publication admissibility (ruling 2026-08-31
#   I2-D) splits heads by profile identity, every profile's head roots its
#   run with no change here; only the history window below must then gain
#   the profile dimension in its key and grouping.
# * retained history — appended by the publish CAS (same transaction);
#   pruned by the sweep beyond the caller's ``retain_history`` window.
# * leases (active/session/export) — granted by a consumer with a
#   mandatory positive TTL; cleared by release or by the deadline law at
#   sweep time.  A dead owner stops renewing, the deadline passes, the
#   grant dissolves — an eternal lease has no representation.
# * explicit retention — set and cleared by a deliberate operator call,
#   never by liveness: its owner is a decision, not a process.
# * staging — a publish's unpublished rows live only inside its own
#   IMMEDIATE transaction, which SQLite serializes against the sweep's, so
#   live staging is unreachable by construction; a COMMITTED unpublished
#   run (a future multi-transaction staging path) is protected and
#   reported, never guessed at.
#
# What a sweep never touches, and the mechanism that holds it: victims are
# the complement of the root union, and even a wrong complement cannot
# delete a rooted run — heads, head_history, run_leases and retained_runs
# all carry ``REFERENCES runs(run_pk)`` under ``PRAGMA foreign_keys=ON``,
# so deleting a still-rooted run is a constraint refusal that aborts the
# whole transaction.  Objects are deleted only when no membership row
# references them, and ``run_members.object_pk`` is itself a foreign key —
# a shared immutable object with one surviving reader is undeletable twice
# over.  ``store_meta``, ``witness`` and ``namespaces`` appear in no sweep
# statement at all.
# ---------------------------------------------------------------------------

_GC_JOB_NAME: Final = "canonical_run_store"

#: The closed lease vocabulary of §8: an in-flight operation, an MCP
#: session pinned to a run, a multi-call export.  One mechanism, three
#: grant kinds — the kind is provenance for debugging, never semantics.
_LEASE_KINDS: Final[frozenset[str]] = frozenset({"active", "export", "session"})


def _lease_now() -> int:
    """The lease clock: whole unix seconds, read at grant and at sweep.

    The deadline is enforced by the sweep's clock through the shared
    deadline law, never by the grant owner's continued existence.
    """
    return int(time.time())


def _sweep_expired_leases(cursor: sqlite3.Cursor, now: int) -> tuple[int, set[int]]:
    """Dissolve expired leases; return (expired_count, live-leased run pks).

    Every lease row passes through :func:`codeclone.models.deadline_passed`
    — the one spelling of expiry — so the sweep and the workspace-intent
    lifecycle cannot drift apart on the boundary.
    """
    rows = cursor.execute(
        "SELECT lease_id, run_pk, expires_at FROM run_leases ORDER BY lease_id"
    ).fetchall()
    expired = [str(row[0]) for row in rows if deadline_passed(int(row[2]), now)]
    live = {int(row[1]) for row in rows if not deadline_passed(int(row[2]), now)}
    cursor.executemany(
        "DELETE FROM run_leases WHERE lease_id = ?",
        [(lease_id,) for lease_id in expired],
    )
    return len(expired), live


def _prune_head_history(
    cursor: sqlite3.Cursor, retain_history: int
) -> tuple[int, set[int]]:
    """Prune history beyond the per-target window; return (pruned, kept pks).

    The newest ``retain_history`` generations of every (namespace, target)
    stay and root their runs; everything older stops rooting and its rows
    leave, so the history table cannot grow without bound between sweeps.
    """
    rows = cursor.execute(
        "SELECT namespace_pk, target, generation, run_pk FROM head_history "
        "ORDER BY namespace_pk, target, generation DESC"
    ).fetchall()
    pruned: list[tuple[int, str, int]] = []
    kept: set[int] = set()
    depth: dict[tuple[int, str], int] = {}
    for namespace_pk, target, generation, run_pk in rows:
        key = (int(namespace_pk), str(target))
        rank = depth.get(key, 0)
        depth[key] = rank + 1
        if rank < retain_history:
            kept.add(int(run_pk))
        else:
            pruned.append((int(namespace_pk), str(target), int(generation)))
    cursor.executemany(
        "DELETE FROM head_history "
        "WHERE namespace_pk = ? AND target = ? AND generation = ?",
        pruned,
    )
    return len(pruned), kept


def _attribute_runs(
    runs: Sequence[tuple[int, int]],
    *,
    head_run_pks: set[int],
    history_run_pks: set[int],
    retained_run_pks: set[int],
    lease_run_pks: set[int],
) -> tuple[dict[str, int], list[int]]:
    """Attribute every run to exactly one hold reason, or to the victims.

    Priority is fixed and documented (head, history, retained, lease,
    staging — the more durable root wins the attribution) so the receipt's
    arithmetic ``candidates == held + collected`` balances by construction
    and the same store state always yields the same numbers.
    """
    held = {
        GC_HOLD_HEAD: 0,
        GC_HOLD_HISTORY: 0,
        GC_HOLD_LEASE: 0,
        GC_HOLD_RETAINED: 0,
        GC_HOLD_STAGING: 0,
    }
    victims: list[int] = []
    for run_pk, published in runs:
        if run_pk in head_run_pks:
            held[GC_HOLD_HEAD] += 1
        elif run_pk in history_run_pks:
            held[GC_HOLD_HISTORY] += 1
        elif run_pk in retained_run_pks:
            held[GC_HOLD_RETAINED] += 1
        elif run_pk in lease_run_pks:
            held[GC_HOLD_LEASE] += 1
        elif published == 0:
            held[GC_HOLD_STAGING] += 1
        else:
            victims.append(run_pk)
    return held, victims


def _run_pk_column(cursor: sqlite3.Cursor, sql: str) -> set[int]:
    """One root table's run pks."""
    return {int(row[0]) for row in cursor.execute(sql)}


# ---------------------------------------------------------------------------
# Public receipts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HeadState:
    """One target head: operational namespace only, never canonical
    semantics (brief §6)."""

    namespace: str
    target: str
    generation: int
    run_id: str


@dataclass(frozen=True, slots=True)
class PublishReceipt:
    """Outcome of one full-run publish.

    ``head_advanced`` is a typed outcome, not an error: a stale publisher's
    run is stored as a valid immutable run but does not move the head
    (brief §6.1); ``generation`` and ``head_run_id`` always describe the
    head after this call.
    """

    run_id: str
    analysis_scope_digest: str
    head_advanced: bool
    generation: int
    head_run_id: str
    object_count: int
    new_objects: int
    shared_objects: int
    family_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class RunReportEdge:
    """One edge of the persisted identity bridge.

    Two addresses from two domains, kept apart exactly as the ruling keeps
    their names apart, plus the evidence that joins them: the run row's own
    scope receipt, which a holder of the report document re-derives without
    the store.  The edge asserts nothing a third party cannot check.
    """

    #: Store domain — the analysis state this edge addresses.
    run_id: str
    #: Report domain — the evaluated identity that answered it.
    report_run_identity: str
    #: The joining evidence, read off the run row.
    analysis_scope_digest: str


def _ensure_schema(connection: sqlite3.Connection) -> None:
    """Idempotent DDL of the store, run by the shared connection owner.

    DDL statements are not implicitly transacted by the sqlite3 module, so
    the CREATEs run in autocommit; the witness handshake that follows in
    ``RunStore._initialize`` gets its own immediate transaction.
    (``executescript`` would commit an open transaction — never used here.)
    """
    for statement in _SCHEMA.split(";"):
        if statement.strip():
            connection.execute(statement)


class RunStore:
    """The wave-2 canonical run-store over one SQLite file."""

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        # The ratified connection convention (ruling 2026-08-24 §5) arrives
        # through the ONE shared connection owner — WAL and busy_timeout
        # 5000 are the owner's, never restated here.  ``synchronous=FULL``
        # is this store's explicit override: the durability of a published
        # immutable run is not weakened to NORMAL as a side effect of
        # unification (NORMAL would be a separate measured decision).
        self._connection = open_sqlite_db(
            Path(self._path),
            ensure_schema=_ensure_schema,
            foreign_keys=True,
            synchronous="FULL",
        )
        self._fence: tuple[int, str, str] = (0, "", "")
        self._initialize()

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> RunStore:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    # -- open-time witness (law 7) ----------------------------------------

    def _initialize(self) -> None:
        # The DDL already ran inside the shared connection owner
        # (``_ensure_schema``); only the witness handshake remains, in its
        # own immediate transaction.
        cursor = self._connection.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        try:
            fence = _open_witness(cursor)
            cursor.execute("COMMIT")
        except BaseException:
            cursor.execute("ROLLBACK")
            raise
        self._fence = fence

    # -- fencing on every mutation (brief §4.2) ---------------------------

    def bump_store_epoch(self) -> int:
        """Advance the store epoch (the migration actor's move).

        Itself a fenced mutation: a stale handle cannot bump either.
        """
        cursor = self._connection.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        try:
            _fence_guard(cursor, self._fence)
            new_epoch = self._fence[0] + 1
            cursor.execute(
                "UPDATE store_meta SET store_epoch = ? WHERE id = 1", (new_epoch,)
            )
            cursor.execute("COMMIT")
        except BaseException:
            cursor.execute("ROLLBACK")
            raise
        self._fence = (new_epoch, self._fence[1], self._fence[2])
        return new_epoch

    # -- write path --------------------------------------------------------

    def _before_publish(self) -> None:
        """Crash-injection seam for the atomicity law (§10); production no-op.

        The staging rows written before this point must never become visible
        to a reader if the transaction dies here.
        """

    def write_full_run(
        self,
        model: CanonicalModel,
        *,
        namespace: str,
        target: str,
        expected_generation: int,
    ) -> PublishReceipt:
        """Stage and atomically publish one full run (brief §10).

        The head advances only from ``expected_generation`` (CAS, law 8);
        a stale publisher's run stays stored, unpublished to no one —
        readable by ``run_id`` — but the head does not move.

        This wrapper owns the outcome of one publish call and nothing
        else.  A stale publisher is a head conflict, never a failure: it
        stored a valid immutable run and lost only the race for the head,
        and folding the two together would hide contention inside an
        error rate.  ``_publish_full_run`` owns the measurements.
        """
        with span(name="canonical.store.publish") as publish_span:
            publish_span.set_counter("canonical_store_publish_attempts", 1)
            try:
                receipt = self._publish_full_run(
                    publish_span,
                    model,
                    namespace=namespace,
                    target=target,
                    expected_generation=expected_generation,
                )
            except BaseException:
                publish_span.set_counter("canonical_store_publish_failures", 1)
                raise
            publish_span.set_counter("canonical_store_publish_successes", 1)
            return receipt

    def _publish_full_run(
        self,
        publish_span: SpanHandle,
        model: CanonicalModel,
        *,
        namespace: str,
        target: str,
        expected_generation: int,
    ) -> PublishReceipt:
        """The publish itself, measured in its two operational phases.

        Staging is CPU over the model; the transaction is where a second
        publisher waits.  They are timed apart because one publish that
        got slower answers a different question depending on which half
        moved, and the span's own duration cannot separate them.
        """
        _require_publish_inputs(namespace, target)
        ingest_started = time.perf_counter()
        model = model.normalize()

        staged: dict[str, tuple[str, bytes]] = {}
        family_counts: dict[str, int] = {}
        for family, row in _model_rows(model):
            payload = _payload_bytes(row)
            object_id = _object_id(namespace, family, payload)
            staged[object_id] = (family, payload)
            family_counts[family] = family_counts.get(family, 0) + 1
        scope_digest = analysis_scope_digest(model.analyzed_files)
        membership = _membership_digest(list(staged))
        run_id = _run_id(namespace, scope_digest, membership)
        publish_span.set_counter(
            "canonical_store_ingest_duration", _elapsed_us(ingest_started)
        )

        cursor = self._connection.cursor()
        membership_rows = 0
        # Started before BEGIN IMMEDIATE on purpose: the wait for the write
        # lock is the contention this number exists to show.
        write_started = time.perf_counter()
        cursor.execute("BEGIN IMMEDIATE")
        try:
            _fence_guard(cursor, self._fence)
            namespace_pk = self._namespace_pk(cursor, namespace)
            new_objects = 0
            object_pks: list[int] = []
            # Insertion order is insurance, not identity: it decides rowids
            # only, and rowids never escape (wall 3).  Measured — reversing
            # this sort survives the full suite, so nothing pins it and the
            # C1 ruling says nothing should.
            for object_id_value in sorted(staged):
                family, payload = staged[object_id_value]
                existing = cursor.execute(
                    "SELECT object_pk FROM objects "
                    "WHERE namespace_pk = ? AND object_id = ?",
                    (namespace_pk, object_id_value),
                ).fetchone()
                if existing is None:
                    cursor.execute(
                        "INSERT INTO objects "
                        "(namespace_pk, object_id, family, payload) "
                        "VALUES (?, ?, ?, ?)",
                        (namespace_pk, object_id_value, family, payload),
                    )
                    object_pks.append(int(cursor.lastrowid or 0))
                    new_objects += 1
                else:
                    object_pks.append(int(existing[0]))
            existing_run = cursor.execute(
                "SELECT run_pk, published FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if existing_run is None:
                cursor.execute(
                    "INSERT INTO runs "
                    "(namespace_pk, run_id, analysis_scope_digest, "
                    "membership_digest, published) VALUES (?, ?, ?, ?, 0)",
                    (namespace_pk, run_id, scope_digest, membership),
                )
                run_pk = int(cursor.lastrowid or 0)
                cursor.executemany(
                    "INSERT INTO run_members (run_pk, object_pk) VALUES (?, ?)",
                    [(run_pk, object_pk) for object_pk in object_pks],
                )
                membership_rows = len(object_pks)
            else:
                run_pk = int(existing_run[0])
            self._before_publish()
            _verify_staged_membership(cursor, run_pk, namespace, membership)
            cursor.execute("UPDATE runs SET published = 1 WHERE run_pk = ?", (run_pk,))
            head_advanced, generation, head_run_id = self._advance_head(
                cursor,
                namespace_pk=namespace_pk,
                target=target,
                expected_generation=expected_generation,
                run_pk=run_pk,
                run_id=run_id,
            )
            cursor.execute("COMMIT")
        except BaseException:
            cursor.execute("ROLLBACK")
            raise
        finally:
            publish_span.set_counter(
                "canonical_store_write_duration", _elapsed_us(write_started)
            )
        # Magnitudes are written even when they are zero: an absent count
        # cannot be told apart from a span that never reached this line.
        publish_span.set_counter("canonical_store_new_objects", new_objects)
        publish_span.set_counter(
            "canonical_store_reused_objects", len(staged) - new_objects
        )
        publish_span.set_counter("canonical_store_membership_rows", membership_rows)
        publish_span.set_counter("canonical_store_db_bytes", _database_bytes(cursor))
        if head_advanced:
            publish_span.set_counter("canonical_store_head_advance_successes", 1)
        else:
            publish_span.set_counter("canonical_store_head_advance_conflicts", 1)
        return PublishReceipt(
            run_id=run_id,
            analysis_scope_digest=scope_digest,
            head_advanced=head_advanced,
            generation=generation,
            head_run_id=head_run_id,
            object_count=len(staged),
            new_objects=new_objects,
            shared_objects=len(staged) - new_objects,
            family_counts=family_counts,
        )

    def _namespace_pk(self, cursor: sqlite3.Cursor, namespace: str) -> int:
        row = cursor.execute(
            "SELECT namespace_pk FROM namespaces WHERE namespace = ?", (namespace,)
        ).fetchone()
        if row is not None:
            return int(row[0])
        cursor.execute("INSERT INTO namespaces (namespace) VALUES (?)", (namespace,))
        return int(cursor.lastrowid or 0)

    def _advance_head(
        self,
        cursor: sqlite3.Cursor,
        *,
        namespace_pk: int,
        target: str,
        expected_generation: int,
        run_pk: int,
        run_id: str,
    ) -> tuple[bool, int, str]:
        """Compare-and-swap head advancement (law 8) inside the caller's
        transaction: the head moves only from the generation the run was
        derived from; a stale publisher never overwrites a newer head."""
        current = cursor.execute(
            "SELECT h.generation, r.run_id FROM heads h "
            "JOIN runs r ON r.run_pk = h.run_pk "
            "WHERE h.namespace_pk = ? AND h.target = ?",
            (namespace_pk, target),
        ).fetchone()
        current_generation = int(current[0]) if current else 0
        if current_generation != expected_generation:
            return False, current_generation, str(current[1]) if current else ""
        new_generation = expected_generation + 1
        if current is None:
            cursor.execute(
                "INSERT INTO heads (namespace_pk, target, generation, run_pk) "
                "VALUES (?, ?, ?, ?)",
                (namespace_pk, target, new_generation, run_pk),
            )
        else:
            cursor.execute(
                "UPDATE heads SET generation = ?, run_pk = ? "
                "WHERE namespace_pk = ? AND target = ?",
                (new_generation, run_pk, namespace_pk, target),
            )
        # The retained-history root (§8) is recorded at the only moment it
        # can be: the CAS advance itself, in the same transaction.  A run
        # that never advanced a head is never history — it survives a sweep
        # only through a lease or explicit retention.
        cursor.execute(
            "INSERT INTO head_history (namespace_pk, target, generation, run_pk) "
            "VALUES (?, ?, ?, ?)",
            (namespace_pk, target, new_generation, run_pk),
        )
        return True, new_generation, run_id

    # -- read path ---------------------------------------------------------

    def head(self, *, namespace: str, target: str) -> HeadState | None:
        row = self._connection.execute(
            "SELECT h.generation, r.run_id FROM heads h "
            "JOIN namespaces n ON n.namespace_pk = h.namespace_pk "
            "JOIN runs r ON r.run_pk = h.run_pk "
            "WHERE n.namespace = ? AND h.target = ?",
            (namespace, target),
        ).fetchone()
        if row is None:
            return None
        return HeadState(
            namespace=namespace,
            target=target,
            generation=int(row[0]),
            run_id=str(row[1]),
        )

    def run_scope_digest(self, run_id: str) -> str:
        """The scope receipt of one published run (brief §7.1)."""
        return _published_run_row(self._connection, run_id)[2]

    def read_run(self, run_id: str) -> CanonicalModel:
        """Reconstruct one published run as a canonical model.

        Delegates to :func:`_reconstruct_run`, which proves every stored
        byte on the way; any disagreement is a typed refusal, never a
        silently different model.
        """
        run_pk, namespace, scope_digest, membership = _published_run_row(
            self._connection, run_id
        )
        return _reconstruct_run(
            self._connection,
            run_pk=run_pk,
            namespace=namespace,
            scope_digest=scope_digest,
            membership=membership,
            run_id=run_id,
        )

    def project_run(self, run_id: str) -> bytes:
        """Canonical bytes of one published run — law L8's left-hand side:
        byte-identical to ``encode_canonical_json`` of the same model."""
        return encode_canonical_json(self.read_run(run_id))

    # -- bounded export (wave 3) ------------------------------------------

    def _pin_export(self, run_id: str) -> None:
        """Single-snapshot seam (brief §11.1); production no-op.

        Fires once per export, after the export pinned its run identity and
        before any universe read.  That identity is the export's ONE
        mutable read: every later read addresses immutable published
        content through it, so a publication landing after this point can
        no longer reach the export — pinned by the concurrent-publish seam
        test, the analogue of ``_before_publish``.
        """


def acquire_run_lease(
    store: RunStore, run_id: str, *, kind: str, lease_id: str, ttl_seconds: int
) -> int:
    """Grant or renew one lease root on a published run; returns expiry.

    The grant owner is the consumer (an in-flight operation, an MCP
    session, a multi-call export); it clears the root by
    :func:`release_run_lease` or by simply dying — the mandatory
    positive TTL means an aborted owner's grant dissolves at its
    deadline instead of pinning the run forever.  Renewal is
    re-acquiring the same ``lease_id`` for the same run and kind; a
    ``lease_id`` that names a different run or kind is refused, never
    silently rebound.
    """
    if kind not in _LEASE_KINDS:
        raise RunStoreError(
            f"unknown lease kind {kind!r}; leases are {sorted(_LEASE_KINDS)!r}"
        )
    if not lease_id:
        raise RunStoreError("lease_id must be non-empty")
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int):
        raise RunStoreError("ttl_seconds must be an integer")
    if ttl_seconds <= 0:
        raise RunStoreError(
            "ttl_seconds must be positive: an eternal lease has no "
            "representation in this store"
        )
    with _fenced_transaction(store) as cursor:
        run_pk = _published_run_row(store._connection, run_id)[0]
        expires_at = _lease_now() + ttl_seconds
        existing = cursor.execute(
            "SELECT run_pk, kind FROM run_leases WHERE lease_id = ?",
            (lease_id,),
        ).fetchone()
        if existing is None:
            cursor.execute(
                "INSERT INTO run_leases (lease_id, run_pk, kind, expires_at) "
                "VALUES (?, ?, ?, ?)",
                (lease_id, run_pk, kind, expires_at),
            )
        elif (int(existing[0]), str(existing[1])) != (run_pk, kind):
            raise RunStoreError(
                f"lease {lease_id!r} already grants a different run or kind"
            )
        else:
            cursor.execute(
                "UPDATE run_leases SET expires_at = ? WHERE lease_id = ?",
                (expires_at, lease_id),
            )
    return expires_at


def release_run_lease(store: RunStore, lease_id: str) -> bool:
    """Clear one lease root; False when no such grant exists (a second
    release and a release after expiry sweep are both ordinary)."""
    with _fenced_transaction(store) as cursor:
        cursor.execute("DELETE FROM run_leases WHERE lease_id = ?", (lease_id,))
        released = cursor.rowcount == 1
    return released


def retain_run(store: RunStore, run_id: str) -> bool:
    """Set the explicit-retention root on a published run.

    Deliberately durable: its owner is an operator's decision, not a
    process, so it survives every crash and never expires — the one
    root whose clearing is only ever :func:`release_retained_run`.
    Returns False when the run is already retained.
    """
    with _fenced_transaction(store) as cursor:
        run_pk = _published_run_row(store._connection, run_id)[0]
        cursor.execute(
            "INSERT OR IGNORE INTO retained_runs (run_pk) VALUES (?)",
            (run_pk,),
        )
        retained = cursor.rowcount == 1
    return retained


def release_retained_run(store: RunStore, run_id: str) -> bool:
    """Clear the explicit-retention root; False when it was not set."""
    with _fenced_transaction(store) as cursor:
        row = cursor.execute(
            "SELECT run_pk FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise UnknownRunError(f"run {run_id!r} is not a run of this store")
        cursor.execute("DELETE FROM retained_runs WHERE run_pk = ?", (int(row[0]),))
        released = cursor.rowcount == 1
    return released


# ---------------------------------------------------------------------------
# The persisted identity bridge — a rebuildable derived index (ruling §7).
#
# The store's ``run_id`` is an ANALYSIS state; the report's is an EVALUATION
# identity, and the ruling keeps the two names apart.  What is persisted here
# is neither of them renamed: it is the EDGE, addressing one immutable run row
# and one report identity, with the run's own scope receipt proving the pair
# compatible.  The scope receipt is emphatically NOT the key — one scope
# legitimately carries many snapshots, because editing a file leaves the path
# set untouched — so an index keyed by it would answer "a run over these
# paths" where the caller asked for "the run behind THIS document".
#
# Derived means removable: dropping every row costs a recomputation from the
# two artifacts and nothing else, so the edge never becomes a third authority
# and never roots a run against the collector.
# ---------------------------------------------------------------------------


def link_run_report(
    store: RunStore,
    *,
    run_id: str,
    report_run_identity: str,
    expected_scope_digest: str,
) -> RunReportEdge:
    """State one edge, or refuse the pair.

    Idempotent by construction: re-analyzing an unchanged tree republishes
    the same run under the same report identity, and an edge that grew a
    second row for that would make "how many evaluations answered this
    analysis" a count of runs instead of a count of evaluations.

    The row is read inside the writing transaction on purpose — a lookup
    outside it could name a run the collector removes before the insert,
    and the foreign key would then refuse a write whose input was true when
    it was read.
    """
    if not report_run_identity:
        raise RunReportLinkError("an edge must name the report identity it answers")
    with _fenced_transaction(store) as cursor:
        run_pk, _namespace, scope_digest, _membership = _published_run_row(
            cursor, run_id
        )
        if not hmac.compare_digest(scope_digest, expected_scope_digest):
            raise RunReportLinkError(
                f"refusing to link run {run_id[:12]} over scope "
                f"{scope_digest[:12]} to a report that re-derives "
                f"{expected_scope_digest[:12]}: the two halves do not "
                "describe one analyzed scope"
            )
        cursor.execute(
            "INSERT OR IGNORE INTO run_report_links "
            "(report_run_identity, run_pk) VALUES (?, ?)",
            (report_run_identity, run_pk),
        )
    return RunReportEdge(
        run_id=run_id,
        report_run_identity=report_run_identity,
        analysis_scope_digest=scope_digest,
    )


def linked_run(store: RunStore, *, report_run_identity: str) -> RunReportEdge | None:
    """The edge stored for one report identity, or ``None``.

    The scope receipt comes back off the RUN ROW, never off the edge: the
    row is immutable and content-addressed, so a copy on the edge would be a
    second truth about a fact that cannot move.

    Two edges for one identity is a corruption, not a choice — one
    evaluation cannot descend from two analyses — and taking the first would
    be the silent wrong-row answer this whole owner exists to prevent.
    """
    rows = store._connection.execute(
        "SELECT r.run_id, r.analysis_scope_digest FROM run_report_links l "
        "JOIN runs r ON r.run_pk = l.run_pk "
        "WHERE l.report_run_identity = ? AND r.published = 1 "
        "ORDER BY r.run_id",
        (report_run_identity,),
    ).fetchall()
    if not rows:
        return None
    if len(rows) > 1:
        raise RunReportLinkError(
            f"report identity {report_run_identity[:12]} is linked to "
            f"{len(rows)} analysis runs; one evaluation descends from one "
            "analysis, so the index is corrupt and answers nothing"
        )
    return RunReportEdge(
        run_id=str(rows[0][0]),
        report_run_identity=report_run_identity,
        analysis_scope_digest=str(rows[0][1]),
    )


def runs_over_scope(store: RunStore, *, scope_digest: str) -> tuple[str, ...]:
    """Every published run whose scope receipt is ``scope_digest``.

    The recomputation lane's candidate set, and deliberately a SET: this is
    the function that makes the non-uniqueness of the scope receipt visible
    to its caller instead of hiding it behind a ``LIMIT 1``.
    """
    return tuple(
        str(row[0])
        for row in store._connection.execute(
            "SELECT run_id FROM runs "
            "WHERE analysis_scope_digest = ? AND published = 1 ORDER BY run_id",
            (scope_digest,),
        )
    )


def collect_garbage(store: RunStore, *, retain_history: int) -> GcJobReport:
    """Sweep everything unreachable from the §8 roots, atomically.

    A module-level operation over a store, like :func:`export_run` — the
    store owns the connection, the fence, and the transaction, nothing
    else.  Crash injection rides :func:`_fenced_transaction` itself: dying
    after the last delete and before COMMIT must leave every run
    readable byte-identically, one rollback, never a partial sweep.

    One fenced IMMEDIATE transaction: expired leases dissolve,
    history beyond the ``retain_history`` window stops rooting, every run
    is attributed to exactly one hold reason or becomes a victim, victims
    leave with their membership, and an object leaves only when no
    surviving run references it — deleting a run never breaks a
    neighbour through shared immutable objects, and the foreign keys
    refuse even a defective sweep that tries.  The report's zeros are
    measured zeros: a sweep that collected nothing still answers.
    """
    if (
        isinstance(retain_history, bool)
        or not isinstance(retain_history, int)
        or retain_history < 0
    ):
        raise RunStoreError("retain_history must be a non-negative integer")
    with _fenced_transaction(store) as cursor:
        leases_expired, lease_run_pks = _sweep_expired_leases(cursor, _lease_now())
        history_pruned, history_run_pks = _prune_head_history(cursor, retain_history)
        runs = [
            (int(row[0]), int(row[1]))
            for row in cursor.execute(
                "SELECT run_pk, published FROM runs ORDER BY run_pk"
            )
        ]
        held, victims = _attribute_runs(
            runs,
            head_run_pks=_run_pk_column(cursor, "SELECT run_pk FROM heads"),
            history_run_pks=history_run_pks,
            retained_run_pks=_run_pk_column(cursor, "SELECT run_pk FROM retained_runs"),
            lease_run_pks=lease_run_pks,
        )
        victim_rows = [(run_pk,) for run_pk in victims]
        # The bridge index is swept WITH its runs and never among the roots:
        # a derived index that held a run alive would have quietly become an
        # authority, and one left behind would point into a deleted row —
        # which the foreign key would refuse anyway, turning every sweep of a
        # linked run into a failed collection.
        cursor.executemany("DELETE FROM run_report_links WHERE run_pk = ?", victim_rows)
        cursor.executemany("DELETE FROM run_members WHERE run_pk = ?", victim_rows)
        cursor.executemany("DELETE FROM runs WHERE run_pk = ?", victim_rows)
        cursor.execute(
            "DELETE FROM objects WHERE object_pk NOT IN "
            "(SELECT object_pk FROM run_members)"
        )
        objects_collected = cursor.rowcount
    return GcJobReport.build(
        job=_GC_JOB_NAME,
        candidates=len(runs),
        held=held,
        collected={GC_COLLECT_UNREACHABLE: len(victims)},
        detail={
            "history_rows_pruned": history_pruned,
            "leases_expired": leases_expired,
            "objects_collected": objects_collected,
        },
    )


@dataclass(frozen=True, slots=True)
class RunStoreGcJob:
    """The run-store's job under the unified GC protocol.

    ``retain_history`` is the caller's operational policy, injected at
    construction so the orchestrator stays surface-blind.  A fence refusal
    — the store generation moved under this handle — is the one
    anticipated concurrent outcome, answered as a typed refusal report;
    every other failure is a defect and propagates raw.
    """

    store: RunStore
    retain_history: int

    @property
    def name(self) -> str:
        return _GC_JOB_NAME

    def collect(self) -> GcJobReport:
        try:
            return collect_garbage(self.store, retain_history=self.retain_history)
        except StoreFenceError as error:
            return GcJobReport.refused(job=_GC_JOB_NAME, refusal=str(error))


def export_run(store: RunStore, run_id: str, sink: ByteSink) -> ExportEnvelope:
    """Stream one published run's authoritative canonical bytes.

    The store births the bytes (brief §17, wave 3): output is
    byte-identical to ``project_run`` while never materializing the
    complete model.  The export surface is a module-level projection over
    a store, like every pure step in this module — :class:`RunStore` owns
    the connection, the lifecycle, and the snapshot seam, nothing else.

    The whole export runs inside one explicit read transaction: WAL keeps
    that snapshot stable from the first byte to the last (brief §11.1), so
    a sweep or a publication committing in another process mid-export can
    neither tear the stream nor mix generations into it.  Measured before
    this transaction existed: a concurrent collector's commit between run
    resolution and streaming turned the export into a membership-digest
    refusal.
    """
    connection = store._connection
    cursor = connection.cursor()
    cursor.execute("BEGIN")
    try:
        run_pk, namespace, scope_digest, membership = _published_run_row(
            connection, run_id
        )
        store._pin_export(run_id)
        envelope = _stream_export(
            connection,
            sink,
            run_pk=run_pk,
            namespace=namespace,
            scope_digest=scope_digest,
            membership=membership,
            run_id=run_id,
        )
        cursor.execute("COMMIT")
    except BaseException:
        cursor.execute("ROLLBACK")
        raise
    return envelope


def export_head(
    store: RunStore, *, namespace: str, target: str, sink: ByteSink
) -> ExportEnvelope:
    """Export the current head of one target.

    The head is resolved exactly once, before the seam; the export is
    pinned to that run from then on (§11.1) — a concurrent publication
    advancing the head mid-export can no longer mix generations into the
    stream.
    """
    head = store.head(namespace=namespace, target=target)
    if head is None:
        raise UnknownRunError(
            f"target {target!r} has no published head in namespace {namespace!r}"
        )
    return export_run(store, head.run_id, sink)


__all__ = [
    "HeadState",
    "PublishReceipt",
    "RunReportEdge",
    "RunStore",
    "RunStoreGcJob",
    "acquire_run_lease",
    "analysis_scope_digest",
    "collect_garbage",
    "export_head",
    "export_run",
    "link_run_report",
    "linked_run",
    "release_retained_run",
    "release_run_lease",
    "retain_run",
    "runs_over_scope",
]
