# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import TYPE_CHECKING, NamedTuple

from ..analysis.suppressions import DEAD_CODE_RULE_ID
from ..domain.findings import SYMBOL_KIND_FUNCTION, SYMBOL_KIND_METHOD
from ..domain.quality import CONFIDENCE_HIGH, CONFIDENCE_MEDIUM
from ..models import (
    WORLD_CONTRACTS,
    ClassMetrics,
    DeadCandidate,
    DeadCodeCandidateKind,
    DeadItem,
    ExternalReachability,
    FunctionRelationshipFacts,
    LivenessClassification,
    LiveRootReason,
    ModuleDep,
    ModuleRegistryHandle,
    NestedDefinition,
    RuntimeReachabilityFact,
    UnresolvedInternalItem,
    UnresolvedOverrideItem,
    UnresolvedReachabilityItem,
    WorldContract,
    abstention_reason_for_state,
    binding_witness,
)
from ..paths import is_test_filepath

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

_DYNAMIC_METHOD_PREFIXES = ("visit_",)
_MODULE_RUNTIME_HOOK_NAMES = {"__getattr__", "__dir__"}
_DYNAMIC_HOOK_NAMES = {
    "setup",
    "teardown",
    "setUp",
    "tearDown",
    "setUpClass",
    "tearDownClass",
    "setup_class",
    "teardown_class",
    "setup_method",
    "teardown_method",
}


def world_contract_from_value(value: object) -> WorldContract:
    """The one spelling of the world-contract vocabulary check.

    Every surface that accepts the value - the CLI flag, the pyproject key,
    the MCP request - funnels through here, so an unknown world is refused
    once, by name, and never silently read as one of the two.
    """

    if isinstance(value, str) and value in WORLD_CONTRACTS:
        return "open" if value == "open" else "closed"
    raise ValueError(
        f"dead_code_world must be one of {', '.join(WORLD_CONTRACTS)}; got {value!r}"
    )


def find_unused(
    *,
    definitions: tuple[DeadCandidate, ...],
    referenced_names: frozenset[str],
    referenced_qualnames: frozenset[str] = frozenset(),
    runtime_reachability: tuple[RuntimeReachabilityFact, ...] = (),
    function_relationship_facts: tuple[FunctionRelationshipFacts, ...] = (),
    test_reference_sources: Mapping[str, tuple[str, ...]] | None = None,
    module_registry: ModuleRegistryHandle | None = None,
    class_metrics: tuple[ClassMetrics, ...] = (),
    external_reachability: Sequence[ExternalReachability] = (),
    world_contract: WorldContract = "closed",
    nested_definitions: tuple[NestedDefinition, ...] = (),
    module_deps: Sequence[ModuleDep] = (),
) -> tuple[DeadItem, ...]:
    """Dead symbols only. Every abstention lane is excluded by construction."""
    return classify_liveness(
        definitions=definitions,
        referenced_names=referenced_names,
        referenced_qualnames=referenced_qualnames,
        runtime_reachability=runtime_reachability,
        function_relationship_facts=function_relationship_facts,
        test_reference_sources=test_reference_sources,
        module_registry=module_registry,
        class_metrics=class_metrics,
        external_reachability=external_reachability,
        world_contract=world_contract,
        nested_definitions=nested_definitions,
        module_deps=module_deps,
    ).dead_items


class _Subject(NamedTuple):
    """One definition as the decision table sees it, whichever population.

    The module-level population (``DeadCandidate``) reads its rule-3 facts
    off ``ClassMetrics``; the function-local population
    (``NestedDefinition``) carries them on the row. Normalising both into one
    record is what keeps the decision table ONE table: a nested method under
    an opaque external base abstains for exactly the reason its module-level
    twin does, and a bare-name coincidence abstains for either. A named tuple
    and not a dataclass: a private working record of the evaluator is not a
    model, and the phase-39S ratchet keeps dataclasses in the model store.
    """

    qualname: str
    local_name: str
    filepath: str
    start_line: int
    end_line: int
    kind: DeadCodeCandidateKind
    suppressed_rules: tuple[str, ...]
    live_root_reason: LiveRootReason | None
    #: ``(class qualname, base names)`` of the opaque external base that
    #: governs this method under rule 3, or ``None`` when rule 3 does not apply.
    governing_base: tuple[str, tuple[str, ...]] | None
    decorator_evidenced: bool
    self_dispatched: bool
    #: A function-local definition: no external namespace can spell it, so
    #: the world contract is never consulted for it.
    nested: bool
    #: The proven flow of this definition's value into a callable the
    #: analyzer cannot resolve (liveness policy v5), or ``None``.
    escape_witness: str | None


class ReexportHops(NamedTuple):
    """What following the from-import edges made of the referenced qualnames.

    ``resolved`` are definition qualnames reached through one or more
    re-export hops; ``dangling_names`` are the local names of referenced
    qualnames that name no definition and that no hop could settle - a
    module constant, a submodule, an aliased re-export, a name a
    ``__getattr__`` serves - which stay bare-name signals so that a symbol
    spelled like them abstains rather than dies.
    """

    resolved: frozenset[str]
    dangling_names: frozenset[str]


def resolve_reexport_hops(
    *,
    referenced_qualnames: frozenset[str],
    definition_qualnames: frozenset[str],
    star_bound_qualnames: frozenset[str],
    module_deps: Sequence[ModuleDep],
) -> ReexportHops:
    """Follow a referenced import target to the definition it re-exports.

    ``from pkg import bootstrap`` in a consumer binds ``pkg:bootstrap``, and
    ``pkg/__init__.py`` only imports the name from ``pkg.runtime``; the
    definition is ``pkg.runtime:bootstrap``. Before liveness policy v5 that
    hop was papered over by the bare-name coincidence - the consumer's
    ``bootstrap()`` call spelled the name, and the spelling revived the
    definition. Measured on this repository at 5f35a50f, most of the 31
    symbols that lost every support once loads were settled were this shape.
    The hop is read from the dependency edges the walk already produced: a
    named from-import edge carries the name to its target, a wildcard edge
    carries every name the target's star rule binds.

    Bounded and cycle-safe: each module is visited once per name. Both
    failure directions are safe - a hop that lands on the wrong definition
    can only over-approximate LIVE, and a hop that finds nothing leaves the
    name a signal, which abstains and never dies.
    """

    named_edges: dict[tuple[str, str], list[str]] = {}
    star_edges: dict[str, list[str]] = {}
    for dep in sorted(
        module_deps, key=lambda item: (item.source, item.target, item.line)
    ):
        if dep.import_type != "from_import":
            continue
        for name in dep.requested_names:
            bucket = (
                star_edges.setdefault(dep.source, [])
                if name == "*"
                else named_edges.setdefault((dep.source, name), [])
            )
            if dep.target not in bucket:
                bucket.append(dep.target)

    def follow(module: str, name: str) -> str | None:
        visited: set[str] = set()
        queue: list[str] = [module]
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            for target in named_edges.get((current, name), ()):
                candidate = f"{target}:{name}"
                if candidate in definition_qualnames:
                    return candidate
                queue.append(target)
            for target in star_edges.get(current, ()):
                candidate = f"{target}:{name}"
                if candidate in star_bound_qualnames:
                    return candidate
                queue.append(target)
        return None

    resolved: set[str] = set()
    dangling: set[str] = set()
    for qualname in sorted(referenced_qualnames):
        if qualname in definition_qualnames:
            continue
        module, separator, local = qualname.partition(":")
        if not separator or not local:
            continue
        found = follow(module, local)
        if found is not None:
            resolved.add(found)
        else:
            dangling.add(local.rpartition(".")[2])
    return ReexportHops(
        resolved=frozenset(resolved),
        dangling_names=frozenset(dangling),
    )


def classify_liveness(
    *,
    definitions: tuple[DeadCandidate, ...],
    referenced_names: frozenset[str],
    referenced_qualnames: frozenset[str] = frozenset(),
    runtime_reachability: tuple[RuntimeReachabilityFact, ...] = (),
    function_relationship_facts: tuple[FunctionRelationshipFacts, ...] = (),
    test_reference_sources: Mapping[str, tuple[str, ...]] | None = None,
    module_registry: ModuleRegistryHandle | None = None,
    class_metrics: tuple[ClassMetrics, ...] = (),
    external_reachability: Sequence[ExternalReachability] = (),
    world_contract: WorldContract = "closed",
    nested_definitions: tuple[NestedDefinition, ...] = (),
    module_deps: Sequence[ModuleDep] = (),
) -> LivenessClassification:
    """Tri-state liveness: ``live`` (omitted), ``dead``, or abstained.

    Implements the rule-3 decision table. Evidence rows 1 and 3 (a
    receiver-type-proven reference, a runtime edge) are read from
    ``referenced_qualnames``, the owning class's ``self_dispatched_methods``,
    and ``runtime_reachability``; row 2 from the owning class's
    ``decorator_evidenced_methods``. Name-only matching is never evidence for
    any symbol (liveness policy v5): it used to revive every method under a
    non-opaque owner through an unrelated receiver, and now abstains.

    A ``self.<name>()`` call inside the declaring class is row-1 evidence:
    ``self`` binds only the declaring class or a subclass, so the receiver
    type is proven and the reference is method-specific.

    Every evidence row resolves to ``live`` (the symbol is omitted). The
    absence of all of them reaches one of three abstentions before the dead
    verdict, in this order:

    * a method governed by an opaque external base with no row-2 evidence is
      ``unresolved_overrides`` (rule 3);
    * a definition whose innermost decorator binds to a local registrar that
      provably hands the value to a callable the analyzer cannot resolve is
      ``unresolved_internal`` with reason ``opaque_internal_escape`` (policy
      v5), in BOTH worlds - the uncertainty is inside the observed program,
      so no world dissolves it; read before the bare-name row because a
      proven flow is the more specific fact than a spelling coincidence;
    * a symbol whose local name is a loaded bare name no binding settles is
      ``unresolved_internal`` with reason ``ambiguous_internal_binding``
      (policy v5), in BOTH worlds - the closed world removes the unknown
      external consumer, it does not turn an ambiguous internal binding into
      proof of absence;
    * under the ``open`` world, a module-level symbol that
      ``external_reachability`` calls reachable, or cannot resolve, is
      ``unresolved_reachability`` (RULING 2026-09-01). A function-local
      definition never reaches this row: nothing outside the module can
      spell it, by construction.

    The default world is ``closed`` because it is the evidence-only reading:
    a caller that states no world gets no world-dependent abstention. The
    PRODUCT default is ``open`` and has one owner, the config spec; the
    pipeline always passes it.
    """
    items: list[DeadItem] = []
    abstentions: list[UnresolvedOverrideItem] = []
    unresolved: list[UnresolvedReachabilityItem] = []
    internal: list[UnresolvedInternalItem] = []
    reachability_by_qualname = (
        {row.qualname: row for row in external_reachability}
        if world_contract == "open"
        else {}
    )
    runtime_reachable_qualnames = _runtime_reachable_qualnames(runtime_reachability)
    sources_by_target = (
        collect_test_reference_sources(function_relationship_facts)
        if test_reference_sources is None
        else {
            target: tuple(sorted(set(sources)))
            for target, sources in sorted(test_reference_sources.items())
        }
    )
    definition_qualnames = frozenset(
        {
            *(symbol.qualname for symbol in definitions),
            *(row.qualname for row in nested_definitions),
        }
    )
    hops = resolve_reexport_hops(
        referenced_qualnames=referenced_qualnames,
        definition_qualnames=definition_qualnames,
        star_bound_qualnames=frozenset(
            symbol.qualname for symbol in definitions if symbol.star_import_bound
        ),
        module_deps=module_deps,
    )
    resolved_qualnames = referenced_qualnames | hops.resolved
    signal_names = referenced_names | hops.dangling_names

    for subject in _subjects(
        definitions,
        nested_definitions,
        class_metrics=class_metrics,
    ):
        if DEAD_CODE_RULE_ID in subject.suppressed_rules:
            continue
        if _is_non_actionable_candidate(subject, module_registry=module_registry):
            continue
        if (
            subject.qualname in resolved_qualnames
            or subject.qualname in runtime_reachable_qualnames
            or subject.self_dispatched
            or subject.live_root_reason is not None
        ):
            continue

        if subject.governing_base is not None:
            # A governed method never reaches the dead branch: row-2 evidence
            # (@override, a framework hook) proves the base dispatches here and
            # makes it LIVE, and without evidence it abstains. Denying only the
            # abstention would fall through below and report @override as dead,
            # inverting the row.
            if subject.decorator_evidenced:
                continue
            class_qualname, base_names = subject.governing_base
            abstentions.append(
                UnresolvedOverrideItem(
                    qualname=subject.qualname,
                    filepath=subject.filepath,
                    start_line=subject.start_line,
                    end_line=subject.end_line,
                    kind=subject.kind,
                    class_qualname=class_qualname,
                    base_names=base_names,
                )
            )
            continue

        if subject.escape_witness is not None:
            # The proven flow forbids DEAD and proves nothing LIVE. Before the
            # bare-name row because the escape is symbol-specific evidence of
            # an uncertainty while the coincidence is not evidence of
            # anything; before the reachability row because the lane is
            # world-invariant and an open-world external abstention must not
            # displace it.
            internal.append(
                UnresolvedInternalItem(
                    qualname=subject.qualname,
                    filepath=subject.filepath,
                    start_line=subject.start_line,
                    end_line=subject.end_line,
                    kind=subject.kind,
                    local_name=subject.local_name,
                    witness=subject.escape_witness,
                    reason="opaque_internal_escape",
                )
            )
            continue

        if subject.local_name in signal_names:
            internal.append(
                UnresolvedInternalItem(
                    qualname=subject.qualname,
                    filepath=subject.filepath,
                    start_line=subject.start_line,
                    end_line=subject.end_line,
                    kind=subject.kind,
                    local_name=subject.local_name,
                    witness=binding_witness(subject.local_name),
                    reason="ambiguous_internal_binding",
                )
            )
            continue

        reachability = (
            None if subject.nested else reachability_by_qualname.get(subject.qualname)
        )
        if reachability is not None and reachability.state != "not_reachable":
            unresolved.append(
                UnresolvedReachabilityItem(
                    qualname=subject.qualname,
                    filepath=subject.filepath,
                    start_line=subject.start_line,
                    end_line=subject.end_line,
                    kind=subject.kind,
                    reachability=reachability.state,
                    witness=reachability.witness,
                    world_contract=world_contract,
                    # Read from the vocabulary owner, never re-spelled here:
                    # the state is the measurement and the reason is its name
                    # on the wire, so a second spelling would be a second
                    # place for them to drift.
                    reason=abstention_reason_for_state(reachability.state),
                )
            )
            continue

        sources = sources_by_target.get(subject.qualname, ())
        items.append(
            DeadItem(
                qualname=subject.qualname,
                filepath=subject.filepath,
                start_line=subject.start_line,
                end_line=subject.end_line,
                kind=subject.kind,
                # Always high under liveness policy v5. ``medium`` used to
                # mean "a bare name matches this symbol's spelling", and that
                # case is now the binding abstention above, never a finding:
                # a dead verdict is only reached once no loaded name spells
                # the symbol at all.
                confidence=CONFIDENCE_HIGH,
                reason="test_only_reference" if sources else "unreferenced",
                test_reference_sources=sources,
            )
        )

    return LivenessClassification(
        dead_items=tuple(sorted(items, key=_liveness_item_sort_key)),
        unresolved_overrides=tuple(sorted(abstentions, key=_liveness_item_sort_key)),
        unresolved_reachability=tuple(sorted(unresolved, key=_liveness_item_sort_key)),
        unresolved_internal=tuple(sorted(internal, key=_liveness_item_sort_key)),
    )


def _subjects(
    definitions: Iterable[DeadCandidate],
    nested_definitions: Iterable[NestedDefinition],
    *,
    class_metrics: Sequence[ClassMetrics],
) -> tuple[_Subject, ...]:
    """Both populations, normalised onto the one record the table reads."""

    opaque_base_classes = {
        metric.qualname: metric
        for metric in class_metrics
        if metric.has_unresolved_external_base
    }
    decorator_evidence_qualnames = frozenset(
        method_qualname
        for metric in class_metrics
        for method_qualname in metric.decorator_evidenced_methods
    )
    self_dispatch_qualnames = frozenset(
        method_qualname
        for metric in class_metrics
        for method_qualname in metric.self_dispatched_methods
    )
    subjects: list[_Subject] = []
    for symbol in definitions:
        governing = _governing_opaque_base(
            symbol,
            opaque_base_classes=opaque_base_classes,
        )
        subjects.append(
            _Subject(
                qualname=symbol.qualname,
                local_name=symbol.local_name,
                filepath=symbol.filepath,
                start_line=symbol.start_line,
                end_line=symbol.end_line,
                kind=symbol.kind,
                suppressed_rules=symbol.suppressed_rules,
                live_root_reason=symbol.live_root_reason,
                governing_base=(
                    (governing.qualname, governing.base_names)
                    if governing is not None
                    else None
                ),
                decorator_evidenced=symbol.qualname in decorator_evidence_qualnames,
                self_dispatched=symbol.qualname in self_dispatch_qualnames,
                nested=False,
                escape_witness=symbol.escape_witness,
            )
        )
    for row in nested_definitions:
        # Rule 3 covers public and protected METHODS only, exactly as
        # ``_governing_opaque_base`` reads it for the module-level population;
        # the owner's base facts ride the row because a function-local class
        # has no ``ClassMetrics``.
        governed = (
            row.kind == SYMBOL_KIND_METHOD
            and not _is_name_mangled_private(row.local_name)
            and row.owner_has_unresolved_external_base
        )
        subjects.append(
            _Subject(
                qualname=row.qualname,
                local_name=row.local_name,
                filepath=row.filepath,
                start_line=row.start_line,
                end_line=row.end_line,
                kind=row.kind,
                suppressed_rules=row.suppressed_rules,
                live_root_reason=row.live_root_reason,
                governing_base=(
                    (row.lexical_parent, row.owner_base_names) if governed else None
                ),
                decorator_evidenced=row.decorator_evidenced,
                self_dispatched=row.self_dispatched,
                nested=True,
                escape_witness=row.escape_witness,
            )
        )
    return tuple(subjects)


def _liveness_item_sort_key(
    item: DeadItem
    | UnresolvedOverrideItem
    | UnresolvedReachabilityItem
    | UnresolvedInternalItem,
) -> tuple[str, int, int, str, str]:
    return (
        item.filepath,
        item.start_line,
        item.end_line,
        item.qualname,
        item.kind,
    )


def _governing_opaque_base(
    symbol: DeadCandidate,
    *,
    opaque_base_classes: Mapping[str, ClassMetrics],
) -> ClassMetrics | None:
    """The opaque-base fact that governs ``symbol``, when rule 3 applies.

    Rule 3 covers public and protected METHODS only. A name-mangled private
    (``__x``, not ``__x__``) is excluded by the decision table: an external
    base cannot override it under Python's identity rules, so it stays
    ordinary dead-eligible code. Classes themselves are never governed.
    """
    if symbol.kind != SYMBOL_KIND_METHOD:
        return None
    if _is_name_mangled_private(symbol.local_name):
        return None
    class_qualname, separator, _method = symbol.qualname.rpartition(".")
    if not separator:
        return None
    return opaque_base_classes.get(class_qualname)


def _is_name_mangled_private(name: str) -> bool:
    return name.startswith("__") and not name.endswith("__")


def find_suppressed_unused(
    *,
    definitions: tuple[DeadCandidate, ...],
    referenced_names: frozenset[str],
    referenced_qualnames: frozenset[str] = frozenset(),
    runtime_reachability: tuple[RuntimeReachabilityFact, ...] = (),
    function_relationship_facts: tuple[FunctionRelationshipFacts, ...] = (),
    module_registry: ModuleRegistryHandle | None = None,
    class_metrics: tuple[ClassMetrics, ...] = (),
    nested_definitions: tuple[NestedDefinition, ...] = (),
    module_deps: Sequence[ModuleDep] = (),
) -> tuple[DeadItem, ...]:
    """What a ``# codeclone: ignore[dead-code]`` directive silences.

    Evidence-only, deliberately: the directive answers "would the dead-code
    rule fire on this symbol's evidence", not "under which world contract".
    Reading it under the open world would make a directive on a reachable
    symbol silence nothing and vanish from the report, and the self-repo
    ratchet that retires a directive once its symbol gains a consumer would
    retire it for the wrong reason.
    """
    suppressed_definitions = tuple(
        replace(symbol, suppressed_rules=())
        for symbol in definitions
        if DEAD_CODE_RULE_ID in symbol.suppressed_rules
    )
    suppressed_nested = tuple(
        replace(row, suppressed_rules=())
        for row in nested_definitions
        if DEAD_CODE_RULE_ID in row.suppressed_rules
    )
    if not suppressed_definitions and not suppressed_nested:
        return ()
    return find_unused(
        definitions=suppressed_definitions,
        referenced_names=referenced_names,
        referenced_qualnames=referenced_qualnames,
        runtime_reachability=runtime_reachability,
        function_relationship_facts=function_relationship_facts,
        module_registry=module_registry,
        class_metrics=class_metrics,
        nested_definitions=suppressed_nested,
        module_deps=module_deps,
    )


def _is_non_actionable_candidate(
    symbol: _Subject | DeadCandidate,
    *,
    module_registry: ModuleRegistryHandle | None,
) -> bool:
    # Test symbols are non-actionable because of their source lane, not because
    # a production symbol happens to use a pytest-like name.
    if is_test_filepath(symbol.filepath, module_registry=module_registry):
        return True

    # Module-level dynamic hooks (PEP 562) are invoked by import/runtime lookup.
    if symbol.kind == SYMBOL_KIND_FUNCTION:
        return symbol.local_name in _MODULE_RUNTIME_HOOK_NAMES
    # Magic methods and visitor callbacks are invoked by runtime dispatch.
    if symbol.kind == SYMBOL_KIND_METHOD:
        return (
            _is_dunder(symbol.local_name)
            or symbol.local_name.startswith(_DYNAMIC_METHOD_PREFIXES)
            or symbol.local_name in _DYNAMIC_HOOK_NAMES
        )
    return False


def _is_dunder(name: str) -> bool:
    return len(name) > 4 and name.startswith("__") and name.endswith("__")


def _runtime_reachable_qualnames(
    facts: tuple[RuntimeReachabilityFact, ...],
) -> frozenset[str]:
    return frozenset(
        fact.target_qualname
        for fact in facts
        if fact.confidence in {CONFIDENCE_HIGH, CONFIDENCE_MEDIUM}
    )


def collect_test_reference_sources(
    facts: tuple[FunctionRelationshipFacts, ...],
) -> dict[str, tuple[str, ...]]:
    sources_by_target: dict[str, set[str]] = {}
    for function_facts in facts:
        for relationship in function_facts.relationships:
            if (
                relationship.origin_lane != "test"
                or relationship.resolution_status != "resolved"
                or relationship.target_qualname is None
            ):
                continue
            sources_by_target.setdefault(relationship.target_qualname, set()).add(
                relationship.source_qualname
            )
    return {
        target: tuple(sorted(sources))
        for target, sources in sorted(sources_by_target.items())
    }
