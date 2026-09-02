# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import TYPE_CHECKING, Literal

from ..analysis.suppressions import DEAD_CODE_RULE_ID
from ..domain.findings import SYMBOL_KIND_FUNCTION, SYMBOL_KIND_METHOD
from ..domain.quality import CONFIDENCE_HIGH, CONFIDENCE_MEDIUM
from ..models import (
    WORLD_CONTRACTS,
    ClassMetrics,
    DeadCandidate,
    DeadItem,
    ExternalReachability,
    FunctionRelationshipFacts,
    LivenessClassification,
    ModuleRegistryHandle,
    RuntimeReachabilityFact,
    UnresolvedOverrideItem,
    UnresolvedReachabilityItem,
    WorldContract,
)
from ..paths import is_test_filepath

if TYPE_CHECKING:
    from collections.abc import Sequence

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
) -> tuple[DeadItem, ...]:
    """Dead symbols only. Both abstention lanes are excluded by construction."""
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
    ).dead_items


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
) -> LivenessClassification:
    """Tri-state liveness: ``live`` (omitted), ``dead``, or abstained.

    Implements the rule-3 decision table. Evidence rows 1 and 3 (a
    receiver-type-proven reference, a runtime edge) are read from
    ``referenced_qualnames``, the owning class's ``self_dispatched_methods``,
    and ``runtime_reachability``; row 2 from the owning class's
    ``decorator_evidenced_methods``. Name-only matching is never evidence for
    a method whose owner carries an unresolved external base.

    A ``self.<name>()`` call inside the declaring class is row-1 evidence:
    ``self`` binds only the declaring class or a subclass, so the receiver
    type is proven and the reference is method-specific. Without it, ordinary
    private helpers of any externally-based class abstained for want of a
    receiver the caller never had to name.

    Every evidence row resolves to ``live`` (the symbol is omitted). Only the
    absence of all of them abstains; only a symbol outside rule 3 can be dead.

    The second abstention (RULING 2026-09-01) sits after every liveness row
    and before the dead verdict: under the ``open`` world contract a symbol
    with no live evidence that ``external_reachability`` calls reachable, or
    cannot resolve, is ``unresolved`` rather than dead - CodeClone has no
    basis for either answer. Under ``closed`` reachability is moot. The
    default here is ``closed`` because it is the evidence-only reading: a
    caller that states no world gets no world-dependent abstention. The
    PRODUCT default is ``open`` and has one owner, the config spec; the
    pipeline always passes it.
    """
    items: list[DeadItem] = []
    abstentions: list[UnresolvedOverrideItem] = []
    unresolved: list[UnresolvedReachabilityItem] = []
    reachability_by_qualname = (
        {row.qualname: row for row in external_reachability}
        if world_contract == "open"
        else {}
    )
    runtime_reachable_qualnames = _runtime_reachable_qualnames(runtime_reachability)
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
    sources_by_target = (
        collect_test_reference_sources(function_relationship_facts)
        if test_reference_sources is None
        else {
            target: tuple(sorted(set(sources)))
            for target, sources in sorted(test_reference_sources.items())
        }
    )
    for symbol in definitions:
        governing_base = _governing_opaque_base(
            symbol,
            opaque_base_classes=opaque_base_classes,
        )
        if _should_skip_dead_candidate(
            symbol,
            referenced_names=referenced_names,
            referenced_qualnames=referenced_qualnames,
            runtime_reachable_qualnames=runtime_reachable_qualnames,
            self_dispatch_qualnames=self_dispatch_qualnames,
            module_registry=module_registry,
            governed_by_opaque_base=governing_base is not None,
        ):
            continue

        if governing_base is not None:
            # A governed method never reaches the dead branch: row-2 evidence
            # (@override, a framework hook) proves the base dispatches here and
            # makes it LIVE, and without evidence it abstains. Denying only the
            # abstention would fall through below and report @override as dead,
            # inverting the row.
            if symbol.qualname not in decorator_evidence_qualnames:
                abstentions.append(
                    UnresolvedOverrideItem(
                        qualname=symbol.qualname,
                        filepath=symbol.filepath,
                        start_line=symbol.start_line,
                        end_line=symbol.end_line,
                        kind=symbol.kind,
                        class_qualname=governing_base.qualname,
                        base_names=governing_base.base_names,
                    )
                )
            continue

        reachability = reachability_by_qualname.get(symbol.qualname)
        if reachability is not None and reachability.state != "not_reachable":
            unresolved.append(
                UnresolvedReachabilityItem(
                    qualname=symbol.qualname,
                    filepath=symbol.filepath,
                    start_line=symbol.start_line,
                    end_line=symbol.end_line,
                    kind=symbol.kind,
                    reachability=reachability.state,
                    witness=reachability.witness,
                    world_contract=world_contract,
                    reason=(
                        "externally_reachable"
                        if reachability.state == "reachable"
                        else "reachability_unresolved"
                    ),
                )
            )
            continue

        sources = sources_by_target.get(symbol.qualname, ())
        items.append(
            DeadItem(
                qualname=symbol.qualname,
                filepath=symbol.filepath,
                start_line=symbol.start_line,
                end_line=symbol.end_line,
                kind=symbol.kind,
                confidence=_dead_item_confidence(
                    symbol,
                    referenced_names=referenced_names,
                ),
                reason="test_only_reference" if sources else "unreferenced",
                test_reference_sources=sources,
            )
        )

    return LivenessClassification(
        dead_items=tuple(sorted(items, key=_liveness_item_sort_key)),
        unresolved_overrides=tuple(sorted(abstentions, key=_liveness_item_sort_key)),
        unresolved_reachability=tuple(sorted(unresolved, key=_liveness_item_sort_key)),
    )


def _liveness_item_sort_key(
    item: DeadItem | UnresolvedOverrideItem | UnresolvedReachabilityItem,
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
    if not suppressed_definitions:
        return ()
    return find_unused(
        definitions=suppressed_definitions,
        referenced_names=referenced_names,
        referenced_qualnames=referenced_qualnames,
        runtime_reachability=runtime_reachability,
        function_relationship_facts=function_relationship_facts,
        module_registry=module_registry,
        class_metrics=class_metrics,
    )


def _is_non_actionable_candidate(
    symbol: DeadCandidate,
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


def _should_skip_dead_candidate(
    symbol: DeadCandidate,
    *,
    referenced_names: frozenset[str],
    referenced_qualnames: frozenset[str],
    runtime_reachable_qualnames: frozenset[str],
    self_dispatch_qualnames: frozenset[str] = frozenset(),
    module_registry: ModuleRegistryHandle | None,
    governed_by_opaque_base: bool = False,
) -> bool:
    # The bare-name clause is the ONLY behavioural difference rule 3 makes
    # here, and only for a method governed by an opaque external base. A bare
    # name is not method-specific evidence: popular names like get/save/close
    # would revive half a project through an unrelated receiver. Every other
    # path is byte-identical to the pre-rule-3 predicate.
    name_match_is_evidence = not governed_by_opaque_base
    # Self-dispatch is qualname-keyed, so it is admitted for every candidate
    # rather than only for governed ones. Outside rule 3 it is inert: the same
    # call already put the bare name into referenced_names.
    return (
        DEAD_CODE_RULE_ID in symbol.suppressed_rules
        or _is_non_actionable_candidate(
            symbol,
            module_registry=module_registry,
        )
        or symbol.qualname in referenced_qualnames
        or symbol.qualname in runtime_reachable_qualnames
        or symbol.qualname in self_dispatch_qualnames
        or (name_match_is_evidence and symbol.local_name in referenced_names)
    )


def _dead_item_confidence(
    symbol: DeadCandidate,
    *,
    referenced_names: frozenset[str],
) -> Literal["high", "medium"]:
    if symbol.qualname.split(":", 1)[-1] in referenced_names:
        return CONFIDENCE_MEDIUM
    return CONFIDENCE_HIGH


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
