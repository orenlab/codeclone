# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Full-run ingest: the real producer's report document → canonical model.

Backend wave 2 front end of the full-run writer: it maps one complete
legacy report document (the producer's full-run artifact) onto the frozen
canonical model, resolving every ModuleKey-headed symbol key through the
document's **own** module registry — the measured lossless normalization
(F-3 §2.1.8).  Nothing is guessed: a head that is neither a registry
module nor an analyzed path is a typed refusal, because a guessed FILE
identity would silently become a wrong content address in the run-store
and a wrong class-B handle on the wire.

Root-string grammar is the producer's, read from ``semantics/ir.py``
(``_direct_roots``), never re-invented::

    operation:{operation_kind}:{target}   target = "{head}:{local}" | opaque
    producer:{head}:{qualname}
    effect:{effect_kind}:{label}
    unresolved

Measured on the frozen corpus: 21 of 1 080 operation targets carry no
ModuleKey colon — those ride as one opaque dotted head with an empty local
name (see ``OperationTarget``); a target with a colon but an empty local
name is refused, because collapsing ``a.b:`` into ``a.b`` would merge two
distinct producer strings into one identity.

The wave-1 model subset decides what is carried: candidate scoring fields
(``score``, ``independence``, ``semantic_divergence``, ``sink_statuses``)
and contract ``document``/``wire`` payloads stay with the legacy document;
``candidate_id`` / ``violation_id`` are never ingested — they are class-B
values recomputed only by their one formula owner, and the codec proves
the round trip against the legacy values (W25).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from codeclone.canonical.errors import LegacyIngestError
from codeclone.canonical.identity import (
    AnalysisFile,
    DependencyEndpoint,
    EffectLabelRoot,
    EffectRoot,
    FileId,
    KnownModule,
    ModuleId,
    OpaqueDottedHead,
    OperationHead,
    OperationRoot,
    OperationTarget,
    ProducerRoot,
    SymbolId,
    UnresolvedRoot,
)
from codeclone.canonical.model import (
    CandidateRow,
    CanonicalFacts,
    CanonicalModel,
    ContractRow,
    DependencyEdgeRow,
    FileModuleRelation,
    GraphNodeRow,
    SemanticEdge,
    SinkRoleRow,
    ViolationRow,
)


@dataclass(frozen=True, slots=True)
class _RegistryIndex:
    """The document's own module registry, indexed for head resolution."""

    module_to_path: Mapping[str, str]
    analyzed_paths: frozenset[str]
    path_to_module: Mapping[str, str]


def _mapping(value: object, where: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise LegacyIngestError(f"{where} is not an object")
    return cast("Mapping[str, object]", value)


def _sequence(value: object, where: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise LegacyIngestError(f"{where} is not an array")
    return value


def _field(container: Mapping[str, object], key: str, where: str) -> object:
    if key not in container:
        raise LegacyIngestError(f"{where} is missing {key!r}")
    return container[key]


def _string(container: Mapping[str, object], key: str, where: str) -> str:
    value = _field(container, key, where)
    if not isinstance(value, str):
        raise LegacyIngestError(f"{where}.{key} is not a string")
    return value


def _registry_index(document: Mapping[str, object]) -> _RegistryIndex:
    source_facts = _mapping(
        _field(document, "source_facts", "document"), "source_facts"
    )
    registry = _mapping(
        _field(source_facts, "module_registry", "source_facts"),
        "source_facts.module_registry",
    )
    scope = _sequence(
        _field(source_facts, "analysis_scope", "source_facts"),
        "source_facts.analysis_scope",
    )
    analyzed_paths = frozenset(
        _string(_mapping(entry, "analysis_scope entry"), "path", "analysis_scope entry")
        for entry in scope
    )
    by_path = _mapping(
        _field(registry, "entries_by_path", "module_registry"),
        "module_registry.entries_by_path",
    )
    rows = _sequence(_field(by_path, "rows", "entries_by_path"), "entries_by_path.rows")
    module_to_path: dict[str, str] = {}
    path_to_module: dict[str, str] = {}
    for row in rows:
        pair = _sequence(row, "entries_by_path row")
        if len(pair) != 2:
            raise LegacyIngestError("entries_by_path row is not a [path, entry] pair")
        entry = _mapping(pair[1], "entries_by_path entry")
        identity = _mapping(_field(entry, "identity", "registry entry"), "identity")
        file_value = _mapping(_field(identity, "file", "registry identity"), "file")
        path = _string(file_value, "path", "registry file")
        python_module = _field(identity, "python_module", "registry identity")
        if python_module is None:
            continue
        module = _string(
            _mapping(python_module, "python_module"), "module", "python_module"
        )
        if module in module_to_path and module_to_path[module] != path:
            raise LegacyIngestError(
                f"module {module!r} claims two files: "
                f"{module_to_path[module]!r} and {path!r}"
            )
        if path in path_to_module and path_to_module[path] != module:
            raise LegacyIngestError(
                f"file {path!r} claims two modules: "
                f"{path_to_module[path]!r} and {module!r}"
            )
        module_to_path[module] = path
        path_to_module[path] = module
    return _RegistryIndex(
        module_to_path=module_to_path,
        analyzed_paths=analyzed_paths,
        path_to_module=path_to_module,
    )


def _symbol(key: str, index: _RegistryIndex, where: str) -> SymbolId:
    head, separator, qualname = key.partition(":")
    if not separator or not qualname:
        raise LegacyIngestError(
            f"{where}: {key!r} is not a ModuleKey-headed symbol key"
        )
    if head in index.module_to_path:
        return SymbolId(FileId(index.module_to_path[head]), qualname)
    if head in index.analyzed_paths:
        return SymbolId(FileId(head), qualname)
    raise LegacyIngestError(
        f"{where}: symbol head {head!r} is neither a registry module nor an "
        "analyzed path; refusing to guess an identity"
    )


def _operation_head(text: str, index: _RegistryIndex) -> OperationHead:
    if text in index.module_to_path:
        return KnownModule(ModuleId(text))
    if text in index.analyzed_paths:
        return AnalysisFile(FileId(text))
    return OpaqueDottedHead(text)


def _effect_root(root: str, index: _RegistryIndex, where: str) -> EffectRoot:
    if root == "unresolved":
        return UnresolvedRoot()
    family, separator, rest = root.partition(":")
    if not separator:
        raise LegacyIngestError(f"{where}: root {root!r} has no family tag")
    if family == "operation":
        kind, kind_separator, target = rest.partition(":")
        if not kind_separator or not target:
            raise LegacyIngestError(f"{where}: operation root {root!r} has no target")
        head_text, head_separator, local_name = target.partition(":")
        if not head_separator:
            # Measured: 21 of 1 080 corpus targets are one opaque dotted
            # string; the whole target is the head, no local name asserted.
            return OperationRoot(kind, OperationTarget(OpaqueDottedHead(target), ""))
        if not local_name:
            raise LegacyIngestError(
                f"{where}: operation target {target!r} carries a ModuleKey "
                "colon but no local name; collapsing it would merge two "
                "distinct producer strings"
            )
        return OperationRoot(
            kind, OperationTarget(_operation_head(head_text, index), local_name)
        )
    if family == "producer":
        return ProducerRoot(_symbol(rest, index, where))
    if family == "effect":
        kind, kind_separator, label = rest.partition(":")
        if not kind_separator or not label:
            raise LegacyIngestError(f"{where}: effect root {root!r} has no label")
        return EffectLabelRoot(kind, label)
    raise LegacyIngestError(f"{where}: unknown root family in {root!r}")


def _root_set(
    values: object, index: _RegistryIndex, where: str
) -> frozenset[EffectRoot]:
    return frozenset(
        _effect_root(_root_string(item, where), index, where)
        for item in _sequence(values, where)
    )


def _root_string(item: object, where: str) -> str:
    if not isinstance(item, str):
        raise LegacyIngestError(f"{where}: root entry is not a string")
    return item


def _symbol_set(
    values: object, index: _RegistryIndex, where: str
) -> frozenset[SymbolId]:
    return frozenset(
        _symbol(_root_string(item, where), index, where)
        for item in _sequence(values, where)
    )


def _string_tuple(values: object, where: str) -> tuple[str, ...]:
    return tuple(_root_string(item, where) for item in _sequence(values, where))


def canonical_model_from_legacy_document(
    document: Mapping[str, object],
) -> CanonicalModel:
    """Ingest one full legacy report document into the canonical model."""
    index = _registry_index(document)
    source_facts = _mapping(
        _field(document, "source_facts", "document"), "source_facts"
    )
    semantic = _mapping(
        _field(source_facts, "semantic", "source_facts"), "source_facts.semantic"
    )
    metrics = _mapping(_field(document, "metrics", "document"), "metrics")
    families = _mapping(_field(metrics, "families", "metrics"), "metrics.families")

    contracts = frozenset(
        ContractRow(
            function=_symbol(
                _string(_mapping(row, "contract_ir row"), "function", "contract_ir"),
                index,
                "contract_ir.function",
            ),
            effect_signature=_string(
                _mapping(row, "contract_ir row"), "effect_signature", "contract_ir"
            ),
            root_set=_root_set(
                _field(
                    _mapping(row, "contract_ir row"),
                    "provenance_roots",
                    "contract_ir",
                ),
                index,
                "contract_ir.provenance_roots",
            ),
        )
        for row in _sequence(
            _field(
                _mapping(
                    _field(semantic, "contract_ir", "semantic"), "semantic.contract_ir"
                ),
                "contracts",
                "semantic.contract_ir",
            ),
            "contract_ir.contracts",
        )
    )

    graph = _mapping(_field(semantic, "graph", "semantic"), "semantic.graph")
    graph_nodes = frozenset(
        GraphNodeRow(
            function=_symbol(
                _string(_mapping(row, "graph node"), "function", "graph.nodes"),
                index,
                "graph.nodes.function",
            ),
            effect_signature=_string(
                _mapping(row, "graph node"), "effect_signature", "graph.nodes"
            ),
            root_set=_root_set(
                _field(_mapping(row, "graph node"), "producer_root_ids", "graph.nodes"),
                index,
                "graph.nodes.producer_root_ids",
            ),
            output_facts=_string_tuple(
                _field(_mapping(row, "graph node"), "output_facts", "graph.nodes"),
                "graph.nodes.output_facts",
            ),
            resolution_state=_string(
                _mapping(row, "graph node"), "resolution_state", "graph.nodes"
            ),
        )
        for row in _sequence(_field(graph, "nodes", "semantic.graph"), "graph.nodes")
    )

    semantic_edges = frozenset(
        SemanticEdge(
            source=_symbol(
                _string(_mapping(row, "graph edge"), "source", "graph.edges"),
                index,
                "graph.edges.source",
            ),
            target=_symbol(
                _string(_mapping(row, "graph edge"), "target", "graph.edges"),
                index,
                "graph.edges.target",
            ),
        )
        for row in _sequence(_field(graph, "edges", "semantic.graph"), "graph.edges")
    )

    sink_roles = frozenset(
        SinkRoleRow(
            symbol=_symbol(
                _string(_mapping(row, "sink"), "sink_identity", "sinks"),
                index,
                "sinks.sink_identity",
            ),
            authority_status=_string(
                _mapping(row, "sink"), "authority_status", "sinks"
            ),
        )
        for row in _sequence(_field(semantic, "sinks", "semantic"), "semantic.sinks")
    )

    candidates = frozenset(
        CandidateRow(
            level=_string(_mapping(row, "candidate"), "level", "candidates"),
            shared_fact=_string(
                _mapping(row, "candidate"), "shared_fact", "candidates"
            ),
            producer_set=_symbol_set(
                _field(_mapping(row, "candidate"), "producers", "candidates"),
                index,
                "candidates.producers",
            ),
        )
        for row in _sequence(
            _field(semantic, "candidates", "semantic"), "semantic.candidates"
        )
    )

    violations = frozenset(
        _violation(_mapping(row, "violation"), index)
        for row in _sequence(
            _field(semantic, "violations", "semantic"), "semantic.violations"
        )
    )

    dependency_rows = _sequence(
        _field(
            _mapping(
                _field(families, "dependencies", "metrics.families"),
                "metrics.families.dependencies",
            ),
            "items",
            "metrics.families.dependencies",
        ),
        "dependencies.items",
    )
    dependency_edges = frozenset(
        _dependency_edge(_mapping(row, "dependency item"), index)
        for row in dependency_rows
    )

    coupling_rows = _sequence(
        _field(
            _mapping(
                _field(families, "coupling", "metrics.families"),
                "metrics.families.coupling",
            ),
            "items",
            "metrics.families.coupling",
        ),
        "coupling.items",
    )
    coupled_sets = frozenset(
        frozenset(labels)
        for labels in (
            _string_tuple(
                _field(_mapping(row, "coupling item"), "coupled_classes", "coupling"),
                "coupling.coupled_classes",
            )
            for row in coupling_rows
        )
        if labels
    )

    analyzed = frozenset(FileId(path) for path in index.analyzed_paths)
    file_modules = frozenset(
        FileModuleRelation(FileId(path), ModuleId(module))
        for path, module in index.path_to_module.items()
    )
    return CanonicalModel(
        files=analyzed,
        modules=frozenset(ModuleId(m) for m in index.module_to_path),
        analyzed_files=analyzed,
        file_modules=file_modules,
        facts=CanonicalFacts(
            contracts=contracts,
            graph_nodes=graph_nodes,
            sink_roles=sink_roles,
            candidates=candidates,
            semantic_edges=semantic_edges,
            dependency_edges=dependency_edges,
            violations=violations,
        ),
        coupled_sets=coupled_sets,
    ).normalize()


def _endpoint(text: str, index: _RegistryIndex, where: str) -> DependencyEndpoint:
    """The ratified ``MODULE | FILE`` union, resolved by the registry —
    never by the shape of the string (F-3 §2.1.8: the producer decides the
    domain, not the spelling)."""
    if text in index.module_to_path:
        return ModuleId(text)
    if text in index.analyzed_paths:
        return FileId(text)
    raise LegacyIngestError(
        f"{where}: endpoint {text!r} is neither a registry module nor an analyzed path"
    )


def _dependency_edge(
    row: Mapping[str, object], index: _RegistryIndex
) -> DependencyEdgeRow:
    line = _field(row, "line", "dependencies item")
    if isinstance(line, bool) or not isinstance(line, int):
        raise LegacyIngestError("dependencies item line is not an integer")
    is_lazy = _field(row, "is_lazy", "dependencies item")
    if not isinstance(is_lazy, bool):
        raise LegacyIngestError("dependencies item is_lazy is not a boolean")
    return DependencyEdgeRow(
        source=_endpoint(
            _string(row, "source", "dependencies item"), index, "dependencies.source"
        ),
        target=_endpoint(
            _string(row, "target", "dependencies item"), index, "dependencies.target"
        ),
        import_type=_string(row, "import_type", "dependencies item"),
        line=line,
        binding=_string(row, "binding", "dependencies item"),
        is_lazy=is_lazy,
    )


def _violation(row: Mapping[str, object], index: _RegistryIndex) -> ViolationRow:
    suppressed = _field(row, "suppressed", "violation")
    if not isinstance(suppressed, bool):
        raise LegacyIngestError("violation suppressed is not a boolean")
    return ViolationRow(
        contract_id=_string(row, "contract_id", "violation"),
        kind=_string(row, "kind", "violation"),
        sink_identity=_symbol(
            _string(row, "sink_identity", "violation"), index, "violation.sink_identity"
        ),
        canonical_owner=_symbol(
            _string(row, "canonical_owner", "violation"),
            index,
            "violation.canonical_owner",
        ),
        authority_status=_string(row, "authority_status", "violation"),
        effect_signature=_string(row, "effect_signature", "violation"),
        resolution_state=_string(row, "resolution_state", "violation"),
        root_set=_root_set(
            _field(row, "producer_root_ids", "violation"),
            index,
            "violation.producer_root_ids",
        ),
        producer_set=_symbol_set(
            _field(row, "producers", "violation"), index, "violation.producers"
        ),
        suppressed=suppressed,
    )


__all__ = ["canonical_model_from_legacy_document"]
