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
import json
import sqlite3
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from types import TracebackType
from typing import Final, cast

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
    AnalysisFile,
    DeadCodeEntity,
    DependencyEndpoint,
    EffectLabelRoot,
    EffectRoot,
    FileId,
    KnownModule,
    ModuleId,
    ModuleSymbol,
    OpaqueDottedHead,
    OpaqueEntity,
    OperationHead,
    OperationRoot,
    OperationTarget,
    ProducerRoot,
    SymbolId,
    UnresolvedRoot,
    canonical_key,
    dead_code_entity_key,
)
from codeclone.canonical.model import (
    AdoptionCountRow,
    AnalysisFacts,
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
    STATEMENT_REACHABILITY_POLICY_VERSION,
    STORAGE_SCHEMA_REVISION,
)
from codeclone.utils.sqlite_store import open_sqlite_db

_DOMAIN_PREFIX: Final = f"cc-run-store:{STORAGE_SCHEMA_REVISION}\x00".encode()
_DOMAIN_OBJECT: Final = _DOMAIN_PREFIX + b"object\x00"
_DOMAIN_RUN: Final = _DOMAIN_PREFIX + b"run\x00"
_DOMAIN_SCOPE: Final = _DOMAIN_PREFIX + b"scope\x00"
_DOMAIN_MEMBERSHIP: Final = _DOMAIN_PREFIX + b"membership\x00"
_DOMAIN_CONTRACT_EPOCH: Final = _DOMAIN_PREFIX + b"contract-epoch\x00"

# Layered compatibility witness (brief §4.1).  ``analysis`` layers enter the
# run identity; the ``projection`` layer (wire revision) and the ``storage``
# layer do not — a projection revision never reaches back into semantic run
# identity (brief §5), and storage physics is not semantics.  All layers
# participate in the witness comparison and in the fenced contract epoch.
_WITNESS_LAYERS: Final[tuple[tuple[str, str, str], ...]] = (
    ("authority_analysis", AUTHORITY_ANALYSIS_REVISION, "analysis"),
    ("canonical_model", CANONICAL_MODEL_REVISION, "analysis"),
    ("canonical_wire", CANONICAL_WIRE_REVISION, "projection"),
    ("contract_ir", CONTRACT_IR_VERSION, "analysis"),
    ("module_identity", MODULE_IDENTITY_VERSION, "analysis"),
    ("storage_schema", STORAGE_SCHEMA_REVISION, "storage"),
)

# Family contract namespaces (F-3 §5.0.1): a fact's content address carries
# the revision of the contract that gives it meaning, so a fact identity
# never silently crosses a producer revision.
_FAMILY_NAMESPACE: Final[dict[str, str]] = {
    # F3: counting meaning — what counts as an annotated parameter or a
    # documented public symbol — is owned by the adoption-coverage policy,
    # so a policy bump never lets these facts silently share content
    # addresses across generations.
    "adoption_count": f"adoption_coverage:{ADOPTION_COVERAGE_POLICY_VERSION}",
    "analyzed_file": f"module_identity:{MODULE_IDENTITY_VERSION}",
    # F5: signature meaning is owned by the API signature contract — a
    # signature-algorithm revision never lets these facts silently share
    # content addresses across generations.
    "api_symbol": f"api_surface_signature:{API_SURFACE_SIGNATURE_VERSION}",
    "candidate": f"authority_analysis:{AUTHORITY_ANALYSIS_REVISION}",
    # F8: group_key meaning is owned by the clone fingerprint generation —
    # a fingerprint-generation bump never lets these facts silently share
    # content addresses across generations.
    "clone_group": f"clone_fingerprint:{BASELINE_FINGERPRINT_VERSION}",
    "contract": f"contract_ir:{CONTRACT_IR_VERSION}",
    "coupled_set": f"canonical_model:{CANONICAL_MODEL_REVISION}",
    # F2: the Wave D lane split put coupling/cohesion meaning on the design
    # metrics revision (complexity moved to its own), so a design-metrics
    # recount never lets these facts silently share content addresses.
    "coupling_cohesion_observation": (
        f"design_metrics:{DESIGN_METRICS_ALGORITHM_REVISION}"
    ),
    # F4: TWO policy owners give this family meaning — liveness for symbol
    # rows, statement reachability for unreachable-statement rows — so both
    # revisions enter the content-address namespace and neither can bump
    # silently under the other.
    "dead_code_observation": (
        f"liveness:{LIVENESS_POLICY_VERSION}"
        f":statement_reachability:{STATEMENT_REACHABILITY_POLICY_VERSION}"
    ),
    # F7: the cycle verdict is a canonical-model analysis fact over the
    # relation graph; no separate cycle-algorithm revision exists, and the
    # relation families it reads share this namespace.
    "dependency_cycle": f"canonical_model:{CANONICAL_MODEL_REVISION}",
    "dependency_occurrence": f"canonical_model:{CANONICAL_MODEL_REVISION}",
    "dependency_relation": f"canonical_model:{CANONICAL_MODEL_REVISION}",
    "file": f"module_identity:{MODULE_IDENTITY_VERSION}",
    "file_module": f"module_identity:{MODULE_IDENTITY_VERSION}",
    "graph_node": f"contract_ir:{CONTRACT_IR_VERSION}",
    "module": f"module_identity:{MODULE_IDENTITY_VERSION}",
    # F1: the risk lane rides COMPLEXITY_ALGORITHM_REVISION (the Wave D
    # two-metric split), so a complexity recount never lets these facts
    # silently share content addresses across generations.
    "risk_observation": f"complexity_metrics:{COMPLEXITY_ALGORITHM_REVISION}",
    "run_scalar": f"canonical_model:{CANONICAL_MODEL_REVISION}",
    "semantic_edge": f"contract_ir:{CONTRACT_IR_VERSION}",
    "sink_role": f"authority_analysis:{AUTHORITY_ANALYSIS_REVISION}",
    "violation": f"authority_analysis:{AUTHORITY_ANALYSIS_REVISION}",
}

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
"""


# ---------------------------------------------------------------------------
# Storage row codec — the storage representation of model rows.
# ---------------------------------------------------------------------------


def _payload_bytes(value: object) -> bytes:
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
    half re-derives the other."""
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
    """Every storage row of one normalized model, deterministically ordered."""
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
    (``DeadCodeObservationRow``), wrapped by ``_decode_row``."""
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
    whose refusal ``_decode_row`` wraps into a typed integrity error."""
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
    refusal ``_decode_row`` wraps into a typed integrity error."""
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
    refusal ``_decode_row`` wraps into a typed integrity error."""
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
    refusal ``_decode_row`` wraps into a typed integrity error.  A second
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
    (``RiskObservationRow``), whose refusal ``_decode_row`` wraps into a
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
    )


# One decoder per storage family — the mechanical inverse of _model_rows.
# Dispatch is total over _FAMILY_NAMESPACE; an unknown family is a typed
# integrity refusal at the call site, never a silent skip.
_ROW_DECODERS: Final[dict[str, Callable[[Mapping[str, object], str], object]]] = {
    "adoption_count": _decode_adoption_count_row,
    "analyzed_file": _decode_file_row,
    "api_symbol": _decode_api_symbol_row,
    "candidate": _decode_candidate_row,
    "clone_group": _decode_clone_group_row,
    "contract": _decode_contract_row,
    "coupled_set": _decode_coupled_row,
    "coupling_cohesion_observation": _decode_coupling_cohesion_row,
    "dead_code_observation": _decode_dead_code_observation_row,
    "dependency_cycle": _decode_dependency_cycle_row,
    "dependency_occurrence": _decode_dependency_occurrence_row,
    "dependency_relation": _decode_dependency_relation_row,
    "file": _decode_file_row,
    "file_module": _decode_file_module_row,
    "graph_node": _decode_graph_node_row,
    "module": _decode_module_row,
    "risk_observation": _decode_risk_observation_row,
    "run_scalar": _decode_run_scalar_row,
    "semantic_edge": _decode_semantic_edge_row,
    "sink_role": _decode_sink_role_row,
    "violation": _decode_violation_row,
}


def _decode_row(family: str, row: Mapping[str, object], where: str) -> object:
    decoder = _ROW_DECODERS.get(family)
    if decoder is None:
        raise StoreIntegrityError(f"{where}: unknown stored family {family!r}")
    try:
        return decoder(row, where)
    except CanonicalModelError as error:
        raise StoreIntegrityError(f"{where}: {error}") from error


def _collected_model(collected: Mapping[str, list[object]]) -> CanonicalModel:
    """Assemble decoded family rows into one canonical model."""

    def family(name: str) -> list[object]:
        return collected.get(name, [])

    run_scalar_rows = cast("list[RunScalars]", family("run_scalar"))
    if len(run_scalar_rows) > 1:
        # F9 law: ONE record per analysis snapshot — two stored records are
        # a writer defect, refused loudly, never last-reader-silenced.
        raise StoreIntegrityError(
            "run carries more than one run_scalars record; the family is "
            "one record per analysis snapshot"
        )
    return CanonicalModel(
        files=frozenset(cast("list[FileId]", family("file"))),
        modules=frozenset(cast("list[ModuleId]", family("module"))),
        analyzed_files=frozenset(cast("list[FileId]", family("analyzed_file"))),
        file_modules=frozenset(cast("list[FileModuleRelation]", family("file_module"))),
        facts=CanonicalFacts(
            analysis=AnalysisFacts(
                contracts=frozenset(cast("list[ContractRow]", family("contract"))),
                graph_nodes=frozenset(cast("list[GraphNodeRow]", family("graph_node"))),
                sink_roles=frozenset(cast("list[SinkRoleRow]", family("sink_role"))),
                candidates=frozenset(cast("list[CandidateRow]", family("candidate"))),
                semantic_edges=frozenset(
                    cast("list[SemanticEdge]", family("semantic_edge"))
                ),
                dependency_relations=frozenset(
                    cast("list[DependencyRelationRow]", family("dependency_relation"))
                ),
                dependency_occurrences=frozenset(
                    cast(
                        "list[DependencyOccurrenceRow]",
                        family("dependency_occurrence"),
                    )
                ),
                dependency_cycles=frozenset(
                    cast("list[DependencyCycleRow]", family("dependency_cycle"))
                ),
                clone_groups=frozenset(
                    cast("list[CloneGroupRow]", family("clone_group"))
                ),
                dead_code_observations=frozenset(
                    cast(
                        "list[DeadCodeObservationRow]",
                        family("dead_code_observation"),
                    )
                ),
                violations=frozenset(cast("list[ViolationRow]", family("violation"))),
                coupling_cohesion_observations=frozenset(
                    cast(
                        "list[CouplingCohesionRow]",
                        family("coupling_cohesion_observation"),
                    )
                ),
                api_symbols=frozenset(cast("list[ApiSymbolRow]", family("api_symbol"))),
                risk_observations=frozenset(
                    cast("list[RiskObservationRow]", family("risk_observation"))
                ),
                adoption_counts=frozenset(
                    cast("list[AdoptionCountRow]", family("adoption_count"))
                ),
                run_scalars=run_scalar_rows[0] if run_scalar_rows else None,
            )
        ),
        coupled_sets=frozenset(cast("list[frozenset[str]]", family("coupled_set"))),
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
    canonical digest of the analyzed-file identity set."""
    paths = sorted(file_id.path for file_id in analyzed_files)
    return hashlib.sha256(_DOMAIN_SCOPE + _payload_bytes(paths)).hexdigest()


def _membership_digest(object_ids: Sequence[str]) -> str:
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
    connection: sqlite3.Connection, run_id: str
) -> tuple[int, str, str, str]:
    row = connection.execute(
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
    namespace: str, object_id_value: str, family: str, payload: bytes
) -> object:
    """Prove one stored member against its content address and decode it.

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
    return _decode_row(family, row, f"{family} object")


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
        collected.setdefault(family_name, []).append(
            _decode_member_object(
                namespace, str(object_id_value), family_name, bytes(payload)
            )
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
) -> list[object]:
    """Decode one family of one run, row by row, proving every byte."""
    rows: list[object] = []
    for object_id_value, payload in connection.execute(
        _MEMBER_FAMILY_SQL, (run_pk, family)
    ):
        stored_id = str(object_id_value)
        rows.append(_decode_member_object(namespace, stored_id, family, bytes(payload)))
        object_ids.append(stored_id)
    return rows


def _family_facts(
    connection: sqlite3.Connection, run_pk: int, namespace: str, wire_family: str
) -> AnalysisFacts:
    """One fact family of one run — the bounded provider of the second
    export pass.  Only this family's rows are alive at a time."""
    family = _WIRE_FAMILY_STORAGE[wire_family]
    object_ids: list[str] = []
    rows = _scan_run_family(connection, run_pk, namespace, family, object_ids)
    return _collected_model({family: rows}).facts.analysis


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
        rows = _scan_run_family(connection, run_pk, namespace, family, object_ids)
        if family in _IDENTITY_FAMILIES:
            identity_rows[family] = rows
            continue
        facts = _collected_model({family: rows}).facts.analysis
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
        """
        _require_publish_inputs(namespace, target)
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

        cursor = self._connection.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        try:
            _fence_guard(cursor, self._fence)
            namespace_pk = self._namespace_pk(cursor, namespace)
            new_objects = 0
            object_pks: list[int] = []
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


def export_run(store: RunStore, run_id: str, sink: ByteSink) -> ExportEnvelope:
    """Stream one published run's authoritative canonical bytes.

    The store births the bytes (brief §17, wave 3): output is
    byte-identical to ``project_run`` while never materializing the
    complete model.  The export surface is a module-level projection over
    a store, like every pure step in this module — :class:`RunStore` owns
    the connection, the lifecycle, and the snapshot seam, nothing else.
    """
    run_pk, namespace, scope_digest, membership = _published_run_row(
        store._connection, run_id
    )
    store._pin_export(run_id)
    return _stream_export(
        store._connection,
        sink,
        run_pk=run_pk,
        namespace=namespace,
        scope_digest=scope_digest,
        membership=membership,
        run_id=run_id,
    )


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
    "RunStore",
    "analysis_scope_digest",
    "export_head",
    "export_run",
]
