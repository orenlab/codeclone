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

The wave-1 model subset decides what is carried: contract
``document``/``wire`` payloads stay with the legacy document, and
``candidate_id`` / ``violation_id`` are never ingested — they are class-B
values recomputed only by their one formula owner, and the codec proves
the round trip against the legacy values (W25).

The candidate payload columns (``score``, ``independence``,
``semantic_divergence``, ``sink_statuses``) are not ingested either, and
step 8 settled why rather than deferring it again: ``score`` is a strict
function of ``level``; the other three are conclusions the stored
authority graph already settles (``semantic_edges``,
``graph_nodes.effect_signature``, ``graph_nodes.resolution_state``) —
measured on the self-repo corpus at 7 317/7 317 candidate rows, 0
disagreements.  ``codeclone.canonical.authority_projection`` is their one
owner, and it rebuilds the published row whole.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from codeclone.canonical.analysis_rows import (
    OVERLOADED_MODULE_COUNTERS as _OVERLOADED_COUNTERS,
)
from codeclone.canonical.analysis_rows import (
    OVERLOADED_MODULE_SCORES as _OVERLOADED_SCORES,
)
from codeclone.canonical.analysis_rows import (
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
from codeclone.canonical.comparison_ingest import comparison_facts_from_document
from codeclone.canonical.errors import LegacyIngestError
from codeclone.canonical.identity import (
    DEAD_SYMBOL_GROUP_KIND,
    UNREACHABLE_STATEMENT_GROUP_KIND,
    EffectRoot,
    FileId,
    ModuleId,
    SourceLocation,
    SymbolId,
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
from codeclone.canonical.semantic_grammar import (
    IdentityIndex,
    build_identity_index,
    parse_dead_code_entity,
    parse_endpoint,
    parse_lane_symbol,
    parse_root_set,
    parse_source_locations,
    parse_symbol,
    parse_symbol_set,
    surface_head,
)


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


def _document_identity_index(document: Mapping[str, object]) -> IdentityIndex:
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
    pairs: list[tuple[str, str]] = []
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
        pairs.append((path, module))
    # Read optionally, unlike every other registry field this function needs.
    # The prefix lane can only WIDEN what resolves, so a document that omits
    # it resolves exactly what it resolved before the lane existed, and no
    # document that ingested yesterday is refused today. A present container
    # is still held to its shape: a malformed row is a defect, not an absence.
    prefixes_value = registry.get("package_prefixes")
    prefix_modules: frozenset[str] = frozenset()
    if prefixes_value is not None:
        prefix_modules = frozenset(
            _string(
                _mapping(prefix, "package_prefixes row"),
                "module",
                "package_prefixes row",
            )
            for prefix in _sequence(prefixes_value, "module_registry.package_prefixes")
        )
    # The conflict law over these pairs is the SHARED owner's, not this
    # reader's: the producer path extracts the same pairs from a live
    # registry handle and must be refused by the same rule. The prefix nodes
    # ride the same call for the same reason -- the producer's own
    # ``_is_internal_target`` counts them as internal modules, so a reading
    # that dropped them would refuse the producer's own document.
    return build_identity_index(
        pairs, analyzed_paths=analyzed_paths, prefix_modules=prefix_modules
    )


def _document_root_set(
    values: object, index: IdentityIndex, where: str
) -> frozenset[EffectRoot]:
    """Document-shape reader; the root-family RULE is the owner's."""
    return parse_root_set(index, _string_tuple(values, where), where)


def _root_string(item: object, where: str) -> str:
    if not isinstance(item, str):
        raise LegacyIngestError(f"{where}: root entry is not a string")
    return item


def _document_symbol_set(
    values: object, index: IdentityIndex, where: str
) -> frozenset[SymbolId]:
    """Document-shape reader; the symbol RULE is the owner's."""
    return parse_symbol_set(index, _string_tuple(values, where), where)


def _string_tuple(values: object, where: str) -> tuple[str, ...]:
    return tuple(_root_string(item, where) for item in _sequence(values, where))


def canonical_model_from_legacy_document(
    document: Mapping[str, object],
) -> CanonicalModel:
    """Ingest one full legacy report document into the canonical model."""
    index = _document_identity_index(document)
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
            function=parse_symbol(
                index,
                _string(_mapping(row, "contract_ir row"), "function", "contract_ir"),
                "contract_ir.function",
            ),
            effect_signature=_string(
                _mapping(row, "contract_ir row"), "effect_signature", "contract_ir"
            ),
            root_set=_document_root_set(
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
            function=parse_symbol(
                index,
                _string(_mapping(row, "graph node"), "function", "graph.nodes"),
                "graph.nodes.function",
            ),
            effect_signature=_string(
                _mapping(row, "graph node"), "effect_signature", "graph.nodes"
            ),
            root_set=_document_root_set(
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
            source=parse_symbol(
                index,
                _string(_mapping(row, "graph edge"), "source", "graph.edges"),
                "graph.edges.source",
            ),
            target=parse_symbol(
                index,
                _string(_mapping(row, "graph edge"), "target", "graph.edges"),
                "graph.edges.target",
            ),
        )
        for row in _sequence(_field(graph, "edges", "semantic.graph"), "graph.edges")
    )

    sink_roles = frozenset(
        SinkRoleRow(
            symbol=parse_symbol(
                index,
                _string(_mapping(row, "sink"), "sink_identity", "sinks"),
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
            producer_set=_document_symbol_set(
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

    dependencies_family = _mapping(
        _field(families, "dependencies", "metrics.families"),
        "metrics.families.dependencies",
    )
    dependency_rows = _sequence(
        _field(dependencies_family, "items", "metrics.families.dependencies"),
        "dependencies.items",
    )
    # The ratified split (ruling 2026-08-24 §2): every producer item is one
    # occurrence (location evidence); the relation entity is the item's own
    # triple — projected here, never guessed, so the two families cannot
    # disagree at the source.
    dependency_occurrences = frozenset(
        _dependency_occurrence(_mapping(row, "dependency item"), index)
        for row in dependency_rows
    )
    dependency_relations = frozenset(
        occurrence.relation for occurrence in dependency_occurrences
    )
    cycle_rows = _sequence(
        _field(dependencies_family, "cycle_details", "metrics.families.dependencies"),
        "dependencies.cycle_details",
    )
    dependency_cycles = frozenset(
        _dependency_cycle(_mapping(row, "cycle_details row"), index)
        for row in cycle_rows
    )

    clone_groups = _clone_group_family(document, index)
    suppressed_clone_groups = _suppressed_clone_group_family(document, index)
    structural_groups = _structural_group_family(document, index)
    dead_symbol_groups, unreachable_statement_groups = _dead_code_group_families(
        document, index
    )
    complexity_hotspots, coupling_hotspots, cohesion_hotspots = _design_group_families(
        document, index
    )
    overloaded_modules = _overloaded_module_family(families, index)
    coverage_join, coverage_units = _coverage_join_family(families, index)
    dead_code_summary = _dead_code_summary(families)

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

    (
        coupling_cohesion,
        api_symbols,
        risk_observations,
        adoption_counts,
        dead_code_observations,
    ) = _observation_lane_families(source_facts, index)

    security_rows = _sequence(
        _field(
            _mapping(
                _field(families, "security_surfaces", "metrics.families"),
                "metrics.families.security_surfaces",
            ),
            "items",
            "metrics.families.security_surfaces",
        ),
        "security_surfaces.items",
    )
    security_surfaces = frozenset(
        _security_surface(_mapping(row, "security_surfaces item"), index)
        for row in security_rows
    )

    # The DECLARATION entity, read from the producer's own complexity item.
    # That row is two objects glued together: the declaration (this family)
    # and the risk observation about it; the lane container carries only the
    # second, so the span is read where the producer publishes it -- the
    # same metrics.families door the dependency, coupling and F10 families
    # already use.
    complexity_rows = _sequence(
        _field(
            _mapping(
                _field(families, "complexity", "metrics.families"),
                "metrics.families.complexity",
            ),
            "items",
            "metrics.families.complexity",
        ),
        "complexity.items",
    )
    unit_spans = frozenset(
        _unit_span(_mapping(row, "complexity item"), index) for row in complexity_rows
    )

    run_scalars = _run_scalars(document)
    analysis_population = _analysis_population(document)

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
            analysis=AnalysisFacts(
                contracts=contracts,
                graph_nodes=graph_nodes,
                sink_roles=sink_roles,
                candidates=candidates,
                semantic_edges=semantic_edges,
                dependency_relations=dependency_relations,
                dependency_occurrences=dependency_occurrences,
                dependency_cycles=dependency_cycles,
                clone_groups=clone_groups,
                dead_code_observations=dead_code_observations,
                violations=violations,
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
            ),
            # Canonical epoch E2: the comparison the document published,
            # read by its own oracle module.
            comparison=comparison_facts_from_document(document),
        ),
        coupled_sets=coupled_sets,
    ).normalize()


def _security_surface(
    row: Mapping[str, object], index: IdentityIndex
) -> SecuritySurfaceRow:
    """One F10 fact from the producer's own security_surfaces item.

    Three registry-consistency laws, each a refusal and never a repair:
    the row's ``module`` field must be the registry projection of its own
    file; a MODULE-scope qualname must be that head itself (no local name
    asserted); a class/callable qualname resolves through the document's
    OWN registry and must land on the row's own file (the clone-item
    precedent).  The ``source_kind`` verdict is carried verbatim —
    classified once by the producer, never re-derived here.
    """
    where = "security_surfaces item"
    path = _string(row, "relative_path", where)
    head = surface_head(index, path, f"{where}.relative_path")
    declared_module = _string(row, "module", where)
    if declared_module != head:
        raise LegacyIngestError(
            f"{where}: module {declared_module!r} disagrees with the "
            f"document's own registry projection {head!r} for {path!r}"
        )
    location_scope = _string(row, "location_scope", where)
    qualname_text = _string(row, "qualname", where)
    qualname: str | None
    if location_scope == "module":
        if qualname_text != head:
            raise LegacyIngestError(
                f"{where}: module-scope qualname {qualname_text!r} is not "
                f"the row's own head {head!r}"
            )
        qualname = None
    else:
        symbol = parse_symbol(index, qualname_text, f"{where}.qualname")
        if symbol.file.path != path:
            raise LegacyIngestError(
                f"{where}: qualname {qualname_text!r} disagrees with the "
                f"item's own file {path!r}"
            )
        qualname = symbol.qualname
    return SecuritySurfaceRow(
        file=FileId(path),
        start_line=_lane_int(row, "start_line", where),
        end_line=_lane_int(row, "end_line", where),
        evidence_symbol=_string(row, "evidence_symbol", where),
        qualname=qualname,
        location_scope=location_scope,
        category=_string(row, "category", where),
        capability=_string(row, "capability", where),
        evidence_kind=_string(row, "evidence_kind", where),
        classification_mode=_string(row, "classification_mode", where),
        source_kind=_string(row, "source_kind", where),
    )


def _lane_rows(
    fact_families: Mapping[str, object], lane: str
) -> Sequence[Mapping[str, object]]:
    """One observation lane of ``source_fact_families``, as row mappings."""
    return [
        _mapping(row, f"{lane} observation")
        for row in _sequence(
            _field(fact_families, lane, "source_fact_families"),
            f"source_fact_families.{lane}",
        )
    ]


def _observation_lane_families(
    source_facts: Mapping[str, object], index: IdentityIndex
) -> tuple[
    frozenset[CouplingCohesionRow],
    frozenset[ApiSymbolRow],
    frozenset[RiskObservationRow],
    frozenset[AdoptionCountRow],
    frozenset[DeadCodeObservationRow],
]:
    """The five observation-lane families of ``source_fact_families``.

    One reader per lane, one decoder per row — split from the document
    walk so the walk stays a walk (the F3 landing pushed it over the
    complexity gate's high-risk floor, and the honest answer is structure,
    not a wider allowlist).

    These ``frozenset`` constructions are also where row multiplicity dies.
    The dead-code lane measures 14 826 model rows against 14 827 producer
    rows (@ 95e4210b, 2026-08-30): the collapsed pair is a property and its
    setter — two declarations this lane's row shape cannot tell apart — so
    the collapse loses a real row rather than absorbing a fact stated
    twice, and it happens before any model guard runs, so
    ``_unique_by_key`` never meets the repeat.  See
    ``DeadCodeObservationRow`` for the measurement and for the open
    wire/identity ruling this awaits; two DIFFERING rows under one key stay
    refused by the model law.
    """
    fact_families = _mapping(
        _field(source_facts, "source_fact_families", "source_facts"),
        "source_facts.source_fact_families",
    )
    coupling_cohesion = frozenset(
        _coupling_cohesion_observation(row, index)
        for row in _lane_rows(fact_families, "coupling_cohesion_observations")
    )
    api_symbols = frozenset(
        _api_symbol_observation(row, index)
        for row in _lane_rows(fact_families, "api_surface")
    )
    risk_observations = frozenset(
        _risk_observation(row, index)
        for row in _lane_rows(fact_families, "risk_observations")
    )
    adoption_counts = frozenset(
        _adoption_count(row, index)
        for row in _lane_rows(fact_families, "adoption_counts")
    )
    dead_code_observations = frozenset(
        _dead_code_observation(row, index)
        for row in _lane_rows(fact_families, "dead_code")
    )
    return (
        coupling_cohesion,
        api_symbols,
        risk_observations,
        adoption_counts,
        dead_code_observations,
    )


def _dependency_occurrence(
    row: Mapping[str, object], index: IdentityIndex
) -> DependencyOccurrenceRow:
    line = _field(row, "line", "dependencies item")
    if isinstance(line, bool) or not isinstance(line, int):
        raise LegacyIngestError("dependencies item line is not an integer")
    is_lazy = _field(row, "is_lazy", "dependencies item")
    if not isinstance(is_lazy, bool):
        raise LegacyIngestError("dependencies item is_lazy is not a boolean")
    relation = DependencyRelationRow(
        source=parse_endpoint(
            index, _string(row, "source", "dependencies item"), "dependencies.source"
        ),
        target=parse_endpoint(
            index, _string(row, "target", "dependencies item"), "dependencies.target"
        ),
        dependency_type=_string(row, "import_type", "dependencies item"),
    )
    return DependencyOccurrenceRow(
        relation=relation,
        line=line,
        binding=_string(row, "binding", "dependencies item"),
        is_lazy=is_lazy,
    )


def _dependency_cycle(
    row: Mapping[str, object], index: IdentityIndex
) -> DependencyCycleRow:
    """One F7 fact from the producer's own ``cycle_details`` row.

    The oracle proves the row against the document's OWN registry: every
    member must be a registry module (MODULE-domain law — no identity is
    minted from a string), the aligned ``member_paths`` must be exactly the
    registry's projection (a document at war with its own registry is
    refused, never repaired), and a repeated member is refused loudly — a
    frozenset would silently absorb the arity defect.
    """
    modules = _string_tuple(
        _field(row, "modules", "cycle_details row"), "cycle_details.modules"
    )
    member_paths = _sequence(
        _field(row, "member_paths", "cycle_details row"), "cycle_details.member_paths"
    )
    if len(member_paths) != len(modules):
        raise LegacyIngestError("cycle_details member_paths do not align with modules")
    if len(set(modules)) != len(modules):
        raise LegacyIngestError("cycle_details row names one module twice")
    for module, path in zip(modules, member_paths, strict=True):
        if module not in index.module_to_path:
            raise LegacyIngestError(
                f"cycle_details member {module!r} is not a registry module; "
                "refusing to guess an identity"
            )
        expected = index.module_to_path[module]
        if path != expected:
            raise LegacyIngestError(
                f"cycle_details member path {path!r} disagrees with the "
                f"document's own registry ({expected!r} for {module!r})"
            )
    return DependencyCycleRow(
        kind=_string(row, "kind", "cycle_details row"),
        modules=frozenset(ModuleId(module) for module in modules),
    )


def _dead_code_markers(value: object, where: str) -> tuple[tuple[str, str], ...]:
    pairs = []
    for item in _sequence(value, where):
        pair = _sequence(item, f"{where} pair")
        if len(pair) != 2 or not all(isinstance(part, str) for part in pair):
            raise LegacyIngestError(f"{where} carries a non [key, value] pair")
        pairs.append((str(pair[0]), str(pair[1])))
    return tuple(pairs)


def _dead_code_observation(
    row: Mapping[str, object], index: IdentityIndex
) -> DeadCodeObservationRow:
    """One F4 fact from the producer's own dead_code lane row."""
    where = "dead_code observation"
    reachable = _field(row, "reachable", where)
    abstained = _field(row, "abstained", where)
    if not isinstance(reachable, bool) or not isinstance(abstained, bool):
        raise LegacyIngestError(f"{where} reachable/abstained are not booleans")
    reason = _field(row, "live_root_reason", where)
    if reason is not None and not isinstance(reason, str):
        raise LegacyIngestError(f"{where} live_root_reason is not a string")
    return DeadCodeObservationRow(
        entity=parse_dead_code_entity(index, _string(row, "entity", where)),
        observation_kind=_string(row, "observation_kind", where),
        candidate_kind=_string(row, "candidate_kind", where),
        reference_count=_lane_int(row, "reference_count", where),
        reachable=reachable,
        runtime_marker_count=_lane_int(row, "runtime_marker_count", where),
        source_markers=_dead_code_markers(
            _field(row, "source_markers", where), f"{where} source_markers"
        ),
        live_root_reason=reason,
        abstained=abstained,
    )


# The emitted clone buckets, in the container's own order.  ``suppressed``
# is DELIBERATELY absent: it is a different population (ruling 2026-08-24
# §10 — the known dialect root), and this oracle never reads it.
_CLONE_CONTAINERS: tuple[tuple[str, str], ...] = (
    ("functions", "function"),
    ("blocks", "block"),
    ("segments", "segment"),
)


def _clone_item(
    row: Mapping[str, object], index: IdentityIndex, where: str
) -> CloneItemRow:
    symbol = parse_symbol(index, _string(row, "qualname", where), where)
    declared_path = _string(row, "relative_path", where)
    if symbol.file.path != declared_path:
        raise LegacyIngestError(
            f"{where}: relative_path {declared_path!r} disagrees with the "
            f"item's own resolved identity {symbol.file.path!r}"
        )
    return CloneItemRow(
        symbol=symbol,
        start_line=_lane_int(row, "start_line", where),
        end_line=_lane_int(row, "end_line", where),
    )


def _clone_group(
    row: Mapping[str, object], index: IdentityIndex, kind: str
) -> CloneGroupRow:
    where = f"{kind} clone group"
    declared_kind = _string(row, "clone_kind", where)
    if declared_kind != kind:
        raise LegacyIngestError(
            f"{where}: clone_kind {declared_kind!r} disagrees with its container"
        )
    facts_value = _mapping(_field(row, "facts", where), f"{where}.facts")
    item_rows = [
        _clone_item(_mapping(item, f"{where} item"), index, f"{where} item")
        for item in _sequence(_field(row, "items", where), f"{where}.items")
    ]
    items = frozenset(item_rows)
    if len(items) != len(item_rows):
        raise LegacyIngestError(
            f"{where}: two items share one identity; a set would absorb "
            "the arity defect silently"
        )
    return CloneGroupRow(
        clone_kind=kind,
        group_key=_string(facts_value, "group_key", f"{where}.facts"),
        items=items,
    )


def _finding_groups(
    document: Mapping[str, object], family: str
) -> Mapping[str, object]:
    """One ``findings.groups.<family>`` container of the document — refused
    when absent, like every producer container this oracle reads."""
    findings = _mapping(_field(document, "findings", "document"), "findings")
    groups = _mapping(_field(findings, "groups", "findings"), "findings.groups")
    return _mapping(
        _field(groups, family, "findings.groups"), f"findings.groups.{family}"
    )


def _clone_group_family(
    document: Mapping[str, object], index: IdentityIndex
) -> frozenset[CloneGroupRow]:
    """The F8 family from the document's EMITTED clone containers only."""
    clones = _finding_groups(document, "clones")
    return frozenset(
        _clone_group(_mapping(row, f"{kind} clone group"), index, kind)
        for container_key, kind in _CLONE_CONTAINERS
        for row in _sequence(
            _field(clones, container_key, "findings.groups.clones"),
            f"clones.{container_key}",
        )
    )


# ---------------------------------------------------------------------------
# Canonical epoch E1: the published finding groups, the overloaded modules,
# the external coverage join and the dead-code summary, each read from the
# SAME container the document builder writes — the grouped finding is the
# family, and the oracle reads it where the document publishes it.
# ---------------------------------------------------------------------------


def _suppressed_clone_group(
    row: Mapping[str, object], index: IdentityIndex, kind: str
) -> SuppressedCloneGroupRow:
    where = f"suppressed {kind} clone group"
    emitted = _clone_group(row, index, kind)
    return SuppressedCloneGroupRow(
        clone_kind=emitted.clone_kind,
        group_key=emitted.group_key,
        items=emitted.items,
        suppression_rule=_string(row, "suppression_rule", where),
        suppression_source=_string(row, "suppression_source", where),
        matched_patterns=_string_tuple(
            _field(row, "matched_patterns", where), f"{where}.matched_patterns"
        ),
    )


def _suppressed_clone_group_family(
    document: Mapping[str, object], index: IdentityIndex
) -> frozenset[SuppressedCloneGroupRow]:
    """A1: the SUPPRESSED population, from the container the document
    writes only when at least one group was suppressed — its absence is
    the measured empty population, never an unknown one."""
    clones = _finding_groups(document, "clones")
    if "suppressed" not in clones:
        return frozenset()
    suppressed = _mapping(clones["suppressed"], "findings.groups.clones.suppressed")
    return frozenset(
        _suppressed_clone_group(_mapping(row, f"suppressed {kind} group"), index, kind)
        for container_key, kind in _CLONE_CONTAINERS
        for row in _sequence(
            _field(suppressed, container_key, "clones.suppressed"),
            f"clones.suppressed.{container_key}",
        )
    )


def _group_rows(
    document: Mapping[str, object], family: str
) -> list[Mapping[str, object]]:
    container = _finding_groups(document, family)
    return [
        _mapping(row, f"{family} group")
        for row in _sequence(
            _field(container, "groups", f"findings.groups.{family}"),
            f"findings.groups.{family}.groups",
        )
    ]


def _group_facts(row: Mapping[str, object], where: str) -> Mapping[str, object]:
    return _mapping(_field(row, "facts", where), f"{where}.facts")


def _single_site(
    row: Mapping[str, object], index: IdentityIndex, where: str
) -> CloneItemRow:
    """The one site of a singleton finding group (its ``items[0]``)."""
    items = _sequence(_field(row, "items", where), f"{where}.items")
    if len(items) != 1:
        raise LegacyIngestError(f"{where} is not a singleton group: {len(items)} items")
    return _clone_item(_mapping(items[0], f"{where} item"), index, f"{where} item")


def _structural_group(
    row: Mapping[str, object], index: IdentityIndex
) -> StructuralGroupRow:
    where = "structural group"
    kind = _string(row, "kind", where)
    identity = _string(row, "id", where)
    prefix = f"structural:{kind}:"
    if not identity.startswith(prefix) or len(identity) == len(prefix):
        raise LegacyIngestError(
            f"{where}: id {identity!r} is not spelled from kind {kind!r}"
        )
    signature = _mapping(_field(row, "signature", where), f"{where}.signature")
    debug = _mapping(_field(signature, "debug", where), f"{where}.signature.debug")
    return StructuralGroupRow(
        finding_kind=kind,
        finding_key=identity[len(prefix) :],
        signature=tuple(
            (str(key), _string(debug, str(key), f"{where}.signature.debug"))
            for key in sorted(debug)
        ),
        occurrences=frozenset(
            _clone_item(_mapping(item, f"{where} item"), index, f"{where} item")
            for item in _sequence(_field(row, "items", where), f"{where}.items")
        ),
    )


def _structural_group_family(
    document: Mapping[str, object], index: IdentityIndex
) -> frozenset[StructuralGroupRow]:
    return frozenset(
        _structural_group(row, index) for row in _group_rows(document, "structural")
    )


def _dead_symbol_group(
    row: Mapping[str, object], index: IdentityIndex
) -> DeadSymbolGroupRow:
    where = "dead_code unused_symbol group"
    site = _single_site(row, index, where)
    facts = _group_facts(row, where)
    return DeadSymbolGroupRow(
        symbol=site.symbol,
        start_line=site.start_line,
        end_line=site.end_line,
        candidate_kind=_string(facts, "kind", f"{where}.facts"),
        confidence=_string(facts, "confidence", f"{where}.facts"),
        reason=_string(facts, "reason", f"{where}.facts"),
        test_reference_sources=_string_tuple(
            _field(facts, "test_reference_sources", f"{where}.facts"),
            f"{where}.facts.test_reference_sources",
        ),
    )


def _unreachable_statement_group(
    row: Mapping[str, object], index: IdentityIndex
) -> UnreachableStatementRow:
    where = "dead_code unreachable_statement group"
    site = _single_site(row, index, where)
    facts = _group_facts(row, where)
    return UnreachableStatementRow(
        symbol=site.symbol,
        start_line=site.start_line,
        end_line=site.end_line,
        reason=_string(facts, "reason", f"{where}.facts"),
        statement_count=_lane_int(facts, "statement_count", f"{where}.facts"),
    )


def _dead_code_group_families(
    document: Mapping[str, object], index: IdentityIndex
) -> tuple[frozenset[DeadSymbolGroupRow], frozenset[UnreachableStatementRow]]:
    """A2: the two dead-code group families, told apart by ``kind`` — the
    discriminator the document's own renderers dispatch on."""
    dead_symbols: list[DeadSymbolGroupRow] = []
    regions: list[UnreachableStatementRow] = []
    for row in _group_rows(document, "dead_code"):
        kind = _string(row, "kind", "dead_code group")
        if kind == DEAD_SYMBOL_GROUP_KIND:
            dead_symbols.append(_dead_symbol_group(row, index))
        elif kind == UNREACHABLE_STATEMENT_GROUP_KIND:
            regions.append(_unreachable_statement_group(row, index))
        else:
            raise LegacyIngestError(f"dead_code group carries unknown kind {kind!r}")
    return frozenset(dead_symbols), frozenset(regions)


#: The design categories that are stored families; ``dependency`` and
#: ``coverage`` groups are projected from the families they are derived
#: from (``dependency_cycles``, ``coverage_units``) and never read here.
_PROJECTED_DESIGN_CATEGORIES = frozenset({"dependency", "coverage"})


def _design_group_families(
    document: Mapping[str, object], index: IdentityIndex
) -> tuple[
    frozenset[ComplexityHotspotRow],
    frozenset[CouplingHotspotRow],
    frozenset[CohesionHotspotRow],
]:
    """A2 (design): the three hotspot families, told apart by ``category``."""
    complexity: list[ComplexityHotspotRow] = []
    coupling: list[CouplingHotspotRow] = []
    cohesion: list[CohesionHotspotRow] = []
    for row in _group_rows(document, "design"):
        category = _string(row, "category", "design group")
        if category in _PROJECTED_DESIGN_CATEGORIES:
            continue
        where = f"design {category} group"
        site = _single_site(row, index, where)
        item = _mapping(_sequence(row["items"], where)[0], f"{where} item")
        if category == "complexity":
            complexity.append(
                ComplexityHotspotRow(
                    symbol=site.symbol,
                    start_line=site.start_line,
                    end_line=site.end_line,
                    cyclomatic_complexity=_lane_int(
                        item, "cyclomatic_complexity", where
                    ),
                    nesting_depth=_lane_int(item, "nesting_depth", where),
                )
            )
        elif category == "coupling":
            coupling.append(
                CouplingHotspotRow(
                    symbol=site.symbol,
                    start_line=site.start_line,
                    end_line=site.end_line,
                    cbo=_lane_int(item, "cbo", where),
                    coupled_classes=_string_tuple(
                        _field(item, "coupled_classes", where),
                        f"{where}.coupled_classes",
                    ),
                )
            )
        elif category == "cohesion":
            cohesion.append(
                CohesionHotspotRow(
                    symbol=site.symbol,
                    start_line=site.start_line,
                    end_line=site.end_line,
                    lcom4=_lane_int(item, "lcom4", where),
                    method_count=_lane_int(item, "method_count", where),
                    instance_var_count=_lane_int(item, "instance_var_count", where),
                )
            )
        else:
            raise LegacyIngestError(
                f"design group carries unknown category {category!r}"
            )
    return frozenset(complexity), frozenset(coupling), frozenset(cohesion)


def _analyzed_file(index: IdentityIndex, path: str, where: str) -> FileId:
    if path not in index.analyzed_paths:
        raise LegacyIngestError(
            f"{where}: {path!r} is not an analyzed path; refusing to guess an identity"
        )
    return FileId(path)


def _lane_float(row: Mapping[str, object], key: str, where: str) -> float:
    value = _field(row, key, where)
    if isinstance(value, bool) or not isinstance(value, float):
        raise LegacyIngestError(f"{where} {key} is not a float")
    return value


def _overloaded_module(
    row: Mapping[str, object], index: IdentityIndex
) -> OverloadedModuleRow:
    where = "overloaded_modules item"
    counters = {name: _lane_int(row, name, where) for name in _OVERLOADED_COUNTERS}
    scores = {name: _lane_float(row, name, where) for name in _OVERLOADED_SCORES}
    return overloaded_module_row(
        file=_analyzed_file(index, _string(row, "relative_path", where), where),
        source_kind=_string(row, "source_kind", where),
        candidate_status=_string(row, "candidate_status", where),
        candidate_reasons=_string_tuple(
            _field(row, "candidate_reasons", where), f"{where}.candidate_reasons"
        ),
        counters=counters,
        scores=scores,
    )


def _overloaded_module_family(
    families: Mapping[str, object], index: IdentityIndex
) -> frozenset[OverloadedModuleRow]:
    container = _mapping(
        _field(families, "overloaded_modules", "metrics.families"),
        "metrics.families.overloaded_modules",
    )
    return frozenset(
        _overloaded_module(_mapping(row, "overloaded_modules item"), index)
        for row in _sequence(
            _field(container, "items", "metrics.families.overloaded_modules"),
            "overloaded_modules.items",
        )
    )


def _coverage_unit(row: Mapping[str, object], index: IdentityIndex) -> CoverageUnitRow:
    where = "coverage_join item"
    site = _clone_item(row, index, where)
    return CoverageUnitRow(
        symbol=site.symbol,
        start_line=site.start_line,
        end_line=site.end_line,
        executable_lines=_lane_int(row, "executable_lines", where),
        covered_lines=_lane_int(row, "covered_lines", where),
        coverage_status=_string(row, "coverage_status", where),
    )


def _coverage_join_family(
    families: Mapping[str, object], index: IdentityIndex
) -> tuple[CoverageJoinRecord | None, frozenset[CoverageUnitRow]]:
    """A5: the join's record and units, from the container the document
    writes only when the run was handed a report — its absence is the
    typed absence of the record, never an empty join."""
    if "coverage_join" not in families:
        return None, frozenset()
    container = _mapping(families["coverage_join"], "metrics.families.coverage_join")
    where = "metrics.families.coverage_join.summary"
    summary = _mapping(_field(container, "summary", "coverage_join"), where)
    reason = _field(summary, "invalid_reason", where)
    if reason is not None and not isinstance(reason, str):
        raise LegacyIngestError(f"{where}.invalid_reason is not a string")
    record = CoverageJoinRecord(
        status=_string(summary, "status", where),
        source=_string(summary, "source", where),
        files=_lane_int(summary, "files", where),
        hotspot_threshold_percent=_lane_int(
            summary, "hotspot_threshold_percent", where
        ),
        invalid_reason=reason,
    )
    units = frozenset(
        _coverage_unit(_mapping(row, "coverage_join item"), index)
        for row in _sequence(
            _field(container, "items", "coverage_join"), "coverage_join.items"
        )
    )
    return record, units


def _dead_code_summary(families: Mapping[str, object]) -> DeadCodeSummaryRecord:
    """A7: the dead-code lane's counters, read from the summary the gate
    and every surface read — never re-measured from the lists beside it."""
    container = _mapping(
        _field(families, "dead_code", "metrics.families"), "metrics.families.dead_code"
    )
    where = "metrics.families.dead_code.summary"
    summary = _mapping(_field(container, "summary", "dead_code"), where)
    return DeadCodeSummaryRecord(
        suppressed=_lane_int(summary, "suppressed", where),
        unresolved=_lane_int(summary, "unresolved", where),
        unresolved_internal=_lane_int(summary, "unresolved_internal", where),
        unresolved_external_override=_lane_int(
            summary, "unresolved_external_override", where
        ),
        candidates=_lane_int(summary, "candidates", where),
        nested_candidates=_lane_int(summary, "nested_candidates", where),
        live_roots=_lane_int(summary, "live_roots", where),
        world_contract=_string(summary, "world_contract", where),
    )


def _document_lane_symbol(
    row: Mapping[str, object],
    index: IdentityIndex,
    *,
    source_key: str,
    name_key: str,
    lane: str,
) -> SymbolId:
    """Read a lane row's source path and bare name, then apply the RULE.

    Extraction is document shape and stays here; the identity law lives in
    ``semantic_grammar.parse_lane_symbol`` so the producer path applies the
    same one to the same fact spelled as typed objects.
    """
    holder = _mapping(_field(row, source_key, f"{lane} observation"), source_key)
    file_value = _mapping(
        _field(holder, "file", f"{lane} {source_key}"), f"{source_key}.file"
    )
    return parse_lane_symbol(
        index,
        _string(file_value, "path", f"{lane} {source_key}.file"),
        _string(row, name_key, f"{lane} observation"),
        lane,
    )


def _lane_int(row: Mapping[str, object], key: str, where: str) -> int:
    """One integer field of a lane row, refused typed when it is not one.

    Shared by the F2 and F1 observation decoders — the F5 landing measured
    that duplicating this block across lane oracles mints clone groups.
    """
    value = _field(row, key, where)
    if isinstance(value, bool) or not isinstance(value, int):
        raise LegacyIngestError(f"{where} {key} is not an integer")
    return value


def _coupling_cohesion_observation(
    row: Mapping[str, object], index: IdentityIndex
) -> CouplingCohesionRow:
    """One F2 observation from the producer's own lane row; the identity
    law lives in :func:`_lane_symbol`."""
    symbol = _document_lane_symbol(
        row, index, source_key="source", name_key="qualname", lane="coupling_cohesion"
    )
    return CouplingCohesionRow(
        symbol=symbol,
        dimension=_string(row, "dimension", "coupling_cohesion observation"),
        numerator=_lane_int(row, "numerator", "coupling_cohesion observation"),
    )


def _risk_observation(
    row: Mapping[str, object], index: IdentityIndex
) -> RiskObservationRow:
    """One F1 fact from the producer's own risk lane row.

    The identity law lives in :func:`_lane_symbol`; the declaration site is
    read as a fact of the row — a lane row without one cannot name its
    entity and is refused, never defaulted (the site is a key component,
    ruling 2026-08-26 fork (b)).
    """
    symbol = _document_lane_symbol(
        row, index, source_key="source", name_key="qualname", lane="risk"
    )
    return RiskObservationRow(
        symbol=symbol,
        dimension=_string(row, "dimension", "risk observation"),
        numerator=_lane_int(row, "numerator", "risk observation"),
        start_line=_lane_int(row, "start_line", "risk observation"),
    )


def _unit_span(row: Mapping[str, object], index: IdentityIndex) -> UnitSpanRow:
    """One declaration extent from the producer's own complexity item.

    The item names its unit with the producer's GLUED ``head:local``
    spelling, so identity goes through the one owner that resolves that
    spelling (:func:`parse_symbol`) and the resolved FILE must be the row's
    own path -- refused on disagreement, never repaired.  That is verbatim
    the F10 ``qualname`` law, and it is the reason this reading and the
    producer-native one cannot drift: both resolve the same glued string
    through the same registry.
    """
    where = "complexity item"
    path = _string(row, "relative_path", where)
    symbol = parse_symbol(index, _string(row, "qualname", where), f"{where}.qualname")
    if symbol.file.path != path:
        raise LegacyIngestError(
            f"{where}: qualname {_string(row, 'qualname', where)!r} resolves "
            f"to {symbol.file.path!r}, disagreeing with its own path {path!r}"
        )
    return UnitSpanRow(
        symbol=symbol,
        start_line=_lane_int(row, "start_line", where),
        end_line=_lane_int(row, "end_line", where),
    )


def _adoption_count(
    row: Mapping[str, object], index: IdentityIndex
) -> AdoptionCountRow:
    """One F3 fact from the producer's own adoption lane row.

    The scope resolves through the document's OWN registry via the one
    endpoint spelling (:func:`_endpoint`) — the producer's scope string is
    a registry module name or an analyzed path by construction
    (``analysis/units.py``), so anything else is a typed refusal, never a
    minted identity (the ScopeRef law, ruling 2026-08-24 §2).
    """
    where = "adoption observation"
    return AdoptionCountRow(
        scope=parse_endpoint(
            index, _string(row, "scope", where), "adoption_counts.scope"
        ),
        feature=_string(row, "feature", where),
        numerator=_lane_int(row, "numerator", where),
        denominator=_lane_int(row, "denominator", where),
    )


# The producer's one digest identity for API signature components
# (``observations/projection.py:_component_digest``): a foreign domain or
# algorithm here is a different fact, never silently the same identity.
_API_DIGEST_DOMAIN = "ccapi1:sig"
_API_DIGEST_ALGORITHM = "sha256"


def _api_digest_value(value: object, where: str) -> str | None:
    """One component digest of the api_surface lane, or its typed absence."""
    if value is None:
        return None
    digest = _mapping(value, where)
    domain = _string(digest, "domain", where)
    algorithm = _string(digest, "algorithm", where)
    if domain != _API_DIGEST_DOMAIN or algorithm != _API_DIGEST_ALGORITHM:
        raise LegacyIngestError(
            f"{where} carries a foreign digest identity "
            f"{domain!r}/{algorithm!r}; refusing to read it as a signature"
        )
    text = _string(digest, "value", where)
    if not text:
        raise LegacyIngestError(f"{where} digest value is empty")
    return text


def _api_parameter(row: Mapping[str, object]) -> ApiParameterFact:
    has_default = _field(row, "has_default", "api parameter")
    if not isinstance(has_default, bool):
        raise LegacyIngestError("api parameter has_default is not a boolean")
    return ApiParameterFact(
        name=_string(row, "name", "api parameter"),
        kind=_string(row, "kind", "api parameter"),
        has_default=has_default,
        annotation_digest=_api_digest_value(
            _field(row, "annotation_digest", "api parameter"),
            "api parameter.annotation_digest",
        ),
    )


def _api_symbol_observation(
    row: Mapping[str, object], index: IdentityIndex
) -> ApiSymbolRow:
    """One F5 fact from the producer's own api_surface lane row.

    The identity law lives in :func:`_lane_symbol` (the C5 oracle
    discipline verbatim: no guessed identities).
    """
    symbol = _document_lane_symbol(
        row, index, source_key="owner", name_key="symbol", lane="api_surface"
    )
    parameters = tuple(
        _api_parameter(_mapping(item, "api parameter"))
        for item in _sequence(
            _field(row, "parameters", "api_surface observation"),
            "api_surface.parameters",
        )
    )
    return ApiSymbolRow(
        symbol=symbol,
        symbol_kind=_string(row, "symbol_kind", "api_surface observation"),
        visibility=_string(row, "visibility", "api_surface observation"),
        parameters=parameters,
        returns_digest=_api_digest_value(
            _field(row, "returns_digest", "api_surface observation"),
            "api_surface.returns_digest",
        ),
    )


def _inventory_scalar(container: Mapping[str, object], key: str, where: str) -> int:
    value = _field(container, key, where)
    if isinstance(value, bool) or not isinstance(value, int):
        raise LegacyIngestError(f"{where}.{key} is not an integer")
    return value


def _analysis_population(
    document: Mapping[str, object],
) -> AnalysisPopulation | None:
    """The execution-population witness the document itself pronounces.

    Three meta key states, inherited verbatim from the R3 door
    (``codeclone.api.metric_families``): ``computed_metric_families``
    absent means a legacy document that never declared — the record is
    honestly ABSENT, never fabricated; present (empty included) means
    the run declared what it computed, and the record is built.  The
    oracle emits only the two states the document can witness today —
    ``complete`` for a declared family, ``not_executed`` for a container
    family the declaration withholds; ``disabled`` / ``truncated`` /
    ``unavailable`` join when producers publish their own states
    (producer wiring), because a state the document cannot witness must
    not be invented here.
    """
    meta_value = document.get("meta")
    if not isinstance(meta_value, Mapping):
        return None
    meta = _mapping(meta_value, "meta")
    if "computed_metric_families" not in meta:
        return None
    declared_value = _sequence(
        _field(meta, "computed_metric_families", "meta"),
        "meta.computed_metric_families",
    )
    declared = set()
    for name in declared_value:
        if not isinstance(name, str) or not name:
            raise LegacyIngestError(
                "meta.computed_metric_families carries a non-string name"
            )
        declared.add(name)
    mode = _string(meta, "analysis_mode", "meta")
    if not mode:
        raise LegacyIngestError("meta.analysis_mode is empty")
    profile_value = _mapping(
        _field(meta, "analysis_profile", "meta"), "meta.analysis_profile"
    )
    profile = tuple(
        (name, _inventory_scalar(profile_value, name, "meta.analysis_profile"))
        for name in sorted(profile_value)
    )
    metrics = _mapping(_field(document, "metrics", "document"), "metrics")
    families = _mapping(_field(metrics, "families", "metrics"), "metrics.families")
    universe = sorted({str(name) for name in families} | declared)
    states = tuple(
        (family, "complete" if family in declared else "not_executed")
        for family in universe
    )
    return AnalysisPopulation(
        analysis_mode=mode,
        analysis_profile=profile,
        producer_states=states,
    )


def _run_scalars(document: Mapping[str, object]) -> RunScalars:
    """The F9 record from the document's own inventory scalars.

    Only the observed scalar counters enter the record (ruling 2026-08-24
    §1: strictly derivable values stay out); the witness lists and the file
    registry beside them are identity/witness state, not run scalars.  The
    document's ``analyzed`` / ``cached`` pair enters as its sum: the split is
    the document's execution provenance, the sum is the observed fact.
    """
    inventory = _mapping(_field(document, "inventory", "document"), "inventory")
    files_section = _mapping(_field(inventory, "files", "inventory"), "inventory.files")
    code_section = _mapping(_field(inventory, "code", "inventory"), "inventory.code")
    return RunScalars(
        classes=_inventory_scalar(code_section, "classes", "inventory.code"),
        files_found=_inventory_scalar(files_section, "total_found", "inventory.files"),
        files_observed=(
            _inventory_scalar(files_section, "analyzed", "inventory.files")
            + _inventory_scalar(files_section, "cached", "inventory.files")
        ),
        files_skipped=_inventory_scalar(files_section, "skipped", "inventory.files"),
        functions=_inventory_scalar(code_section, "functions", "inventory.code"),
        methods=_inventory_scalar(code_section, "methods", "inventory.code"),
        parsed_lines=_inventory_scalar(code_section, "parsed_lines", "inventory.code"),
        source_io_skipped=_inventory_scalar(
            files_section, "source_io_skipped", "inventory.files"
        ),
        unsupported_construct_skipped=_inventory_scalar(
            files_section, "unsupported_construct_skipped", "inventory.files"
        ),
    )


def _document_locations(
    value: object, index: IdentityIndex, where: str
) -> tuple[SourceLocation, ...]:
    """The published location structs as the canonical evidence tuple.

    Document SHAPE is read here (``_document_*``, the oracle's own naming
    law); the identity RULE is the grammar owner's. Two of the four
    published slots are deliberately not read: ``qualname`` is the
    violation's own ``sink_identity`` restated by the producer, and
    ``end_line`` equals ``start_line`` because a semantic event carries one
    line and never a span — reading either would store a fact this row
    already carries.

    Ordering and the placement rule both belong to the grammar owner:
    :func:`parse_source_locations` decides the canonical order once for both
    publication paths, so a document's own array order can never reach the
    stored row.
    """

    return parse_source_locations(
        index,
        (
            (
                _string(_mapping(item, where), "relative_path", where),
                _lane_int(_mapping(item, where), "start_line", where),
            )
            for item in _sequence(value, where)
        ),
    )


def _violation(row: Mapping[str, object], index: IdentityIndex) -> ViolationRow:
    suppressed = _field(row, "suppressed", "violation")
    if not isinstance(suppressed, bool):
        raise LegacyIngestError("violation suppressed is not a boolean")
    return ViolationRow(
        contract_id=_string(row, "contract_id", "violation"),
        kind=_string(row, "kind", "violation"),
        sink_identity=parse_symbol(
            index, _string(row, "sink_identity", "violation"), "violation.sink_identity"
        ),
        canonical_owner=parse_symbol(
            index,
            _string(row, "canonical_owner", "violation"),
            "violation.canonical_owner",
        ),
        authority_status=_string(row, "authority_status", "violation"),
        effect_signature=_string(row, "effect_signature", "violation"),
        resolution_state=_string(row, "resolution_state", "violation"),
        root_set=_document_root_set(
            _field(row, "producer_root_ids", "violation"),
            index,
            "violation.producer_root_ids",
        ),
        producer_set=_document_symbol_set(
            _field(row, "producers", "violation"), index, "violation.producers"
        ),
        suppressed=suppressed,
        locations=_document_locations(
            _field(row, "locations", "violation"), index, "violation.locations"
        ),
    )


__all__ = ["canonical_model_from_legacy_document"]
