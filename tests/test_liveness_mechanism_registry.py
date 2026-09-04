# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The liveness mechanism ratchet: four rules, and the third is the point.

``export_root`` sat in the live-root vocabulary for months with zero
producers.  Five hand-written copies of the same two-value set kept accepting
it as decodable and nothing anywhere asked whether anything still produced
it.  A vocabulary that grows only by acceptance cannot notice that one of its
words has stopped meaning anything.

The rules enforced here, each by its own test:

1. an emitted mechanism MUST exist in the registry;
2. an active mechanism MUST name exactly one producer, and it MUST resolve;
3. an active mechanism MUST have at least one CAUSAL fixture;
4. a mechanism that is intentionally off MUST be explicitly parked, and a
   parked mechanism MUST stay unproduced.

Rule 3 is the one the precedent in ``tests/test_observability_vocabulary.py``
does not have, and it is why this ratchet is worth building.  That precedent
asks whether a declared name still appears at an emit site, which is a
question about source text: a plausible-looking producer satisfies it
forever.  Rule 3 asks whether RUNNING the named producer can make the
mechanism fire, which is a question about meaning.  Measured on this
registry: giving ``export_root`` the live-root producer's own qualname
satisfies rule 2 completely -- the module imports, the symbol resolves, it is
a callable that really does produce live-root reasons -- and rule 3 still
reds, because no configuration of that producer emits ``export_root``.

Each fixture is CAUSAL, not merely observational: it runs the producer twice,
once with the construct under test and once with only that construct removed,
and the mechanism must fire in the first and not in the second.  A fixture
that fired in both would prove nothing about the construct -- it would be a
fixture the mechanism's absence could not break, which is the hollow shape
this whole file exists to refuse.
"""

from __future__ import annotations

import importlib
import textwrap
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Final, cast

import pytest

from codeclone.metrics.dead_code import classify_liveness
from codeclone.metrics.external_reachability import collect_external_reachability
from codeclone.models import (
    ACTIVE_LIVE_ROOT_REASONS,
    ACTIVE_MECHANISMS,
    EXPOSURE_MECHANISM_STATES,
    EXTERNAL_EXPOSURE_MECHANISMS,
    LIVE_ROOT_REASONS,
    MECHANISMS,
    PARK_REASONS,
    PARK_SUPERSEDED_BY_EVIDENCE_LANE,
    PARKED_MECHANISMS,
    DeadCandidate,
    ExternalReachability,
    FileMetrics,
    LivenessVocabularyError,
    MechanismSpec,
    ModuleDep,
    ReachabilityState,
    UnresolvedReachabilityItem,
    abstention_reason_for_state,
    emit_live_root_reason,
    exposure_witness,
    validate_live_root_reason,
    validate_resolution_rule,
    witness_mechanism,
)
from tests._ast_metrics_helpers import build_test_module_registry, extract_file_metrics

# --------------------------------------------------------------------------
# Harness


def _write(root: Path, tree: Mapping[str, str]) -> None:
    for relative, source in tree.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(source).lstrip("\n"), encoding="utf-8")


def _metrics(root: Path, tree: Mapping[str, str]) -> dict[str, FileMetrics]:
    """Run the real per-file walk over a fixture tree."""
    _write(root, tree)
    registry = build_test_module_registry(root=root)
    return {
        relative: extract_file_metrics(
            source=(root / relative).read_text(encoding="utf-8"),
            filepath=relative,
            module_registry=registry,
        )
        for relative in tree
    }


def _referenced_qualnames(root: Path, tree: Mapping[str, str]) -> frozenset[str]:
    observed: set[str] = set()
    for metrics in _metrics(root, tree).values():
        observed |= set(metrics.referenced_qualnames)
    return frozenset(observed)


def _referenced_names(root: Path, tree: Mapping[str, str]) -> frozenset[str]:
    observed: set[str] = set()
    for metrics in _metrics(root, tree).values():
        observed |= set(metrics.referenced_names)
    return frozenset(observed)


def _candidates(root: Path, tree: Mapping[str, str]) -> dict[str, DeadCandidate]:
    found: dict[str, DeadCandidate] = {}
    for metrics in _metrics(root, tree).values():
        for candidate in metrics.dead_candidates:
            found[candidate.qualname] = candidate
    return found


def _resolution_rules(root: Path, tree: Mapping[str, str]) -> frozenset[str]:
    observed: set[str] = set()
    for metrics in _metrics(root, tree).values():
        for facts in metrics.function_relationship_facts:
            for relationship in facts.relationships:
                if relationship.resolution_rule:
                    observed.add(relationship.resolution_rule)
    return frozenset(observed)


def _candidate(
    qualname: str,
    *,
    kind: str = "method",
    filepath: str | None = None,
    local_name: str | None = None,
    suppressed_rules: tuple[str, ...] = (),
) -> DeadCandidate:
    module, _, local = qualname.partition(":")
    return DeadCandidate(
        qualname=qualname,
        local_name=local_name if local_name is not None else local.rpartition(".")[2],
        filepath=filepath or f"{module.replace('.', '/')}.py",
        start_line=1,
        end_line=2,
        kind=kind,  # type: ignore[arg-type]
        suppressed_rules=suppressed_rules,
    )


def _dead(**kwargs: object) -> frozenset[str]:
    """Qualnames the evaluator reports dead, for one set of inputs."""
    classification = classify_liveness(**kwargs)  # type: ignore[arg-type]
    return frozenset(item.qualname for item in classification.dead_items)


def _exposure_mechanisms(
    *,
    candidates: tuple[DeadCandidate, ...],
    module_deps: tuple[ModuleDep, ...] = (),
    **kwargs: object,
) -> frozenset[str]:
    rows: tuple[ExternalReachability, ...] = tuple(
        collect_external_reachability(
            definitions=candidates,
            module_deps=module_deps,
            **kwargs,  # type: ignore[arg-type]
        )
    )
    return frozenset(
        mechanism
        for row in rows
        if (mechanism := witness_mechanism(row.witness)) is not None
    )


def _exposure_pairs(
    *,
    candidates: tuple[DeadCandidate, ...],
    module_deps: tuple[ModuleDep, ...] = (),
    **kwargs: object,
) -> frozenset[tuple[str, str]]:
    """Every ``(mechanism, state)`` pair one producer run actually emits.

    The sibling above reads the mechanism alone, which is what rule 1 needs.
    The witness door needs the PAIR, because the producer chooses the two on
    independent axes and a mechanism-only reading cannot see that.
    """

    rows: tuple[ExternalReachability, ...] = tuple(
        collect_external_reachability(
            definitions=candidates,
            module_deps=module_deps,
            **kwargs,  # type: ignore[arg-type]
        )
    )
    return frozenset(
        (mechanism, row.state)
        for row in rows
        if (mechanism := witness_mechanism(row.witness)) is not None
    )


def _dep(
    source: str,
    target: str,
    *,
    import_type: str = "from_import",
    requested_names: tuple[str, ...] = (),
) -> ModuleDep:
    return ModuleDep(
        source=source,
        target=target,
        import_type=import_type,  # type: ignore[arg-type]
        line=1,
        resolution="analyzed",
        requested_names=requested_names,
    )


def _class(qualname: str, **kwargs: object) -> object:
    from codeclone.models import ClassMetrics

    defaults: dict[str, object] = {
        "qualname": qualname,
        "filepath": f"{qualname.partition(':')[0].replace('.', '/')}.py",
        "start_line": 1,
        "end_line": 2,
        "cbo": 0,
        "lcom4": 1,
        "method_count": 1,
        "instance_var_count": 0,
        "risk_coupling": False,
        "risk_cohesion": False,
    }
    defaults.update(kwargs)
    return ClassMetrics(**defaults)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Causal fixtures.
#
# Each returns (fired_with_construct, fired_without_construct).  Rule 3
# demands the first and refuses the second: a mechanism that fires either way
# is not evidenced by the fixture, it is merely co-present with it.

#: One ``classify_liveness`` call's keyword inputs.  Deliberately loose:
#: each fixture varies a different subset, and naming the union here would
#: restate the owner's signature in a second place that could drift.
Inputs = dict[str, object]
Fixture = Callable[[Path], "tuple[bool, bool]"]
_FIXTURES: dict[str, Fixture] = {}


def _fixture(*mechanisms: str) -> Callable[[Fixture], Fixture]:
    def register(function: Fixture) -> Fixture:
        for mechanism in mechanisms:
            _FIXTURES[mechanism] = function
        return function

    return register


def _resolution_pair(rule: str, with_source: str, without_source: str) -> Fixture:
    def observe(root: Path) -> tuple[bool, bool]:
        tree_with = {"pkg/__init__.py": "\n", "pkg/m.py": with_source}
        tree_without = {"pkg/__init__.py": "\n", "pkg/m.py": without_source}
        return (
            rule in _resolution_rules(root / "with", tree_with),
            rule in _resolution_rules(root / "without", tree_without),
        )

    return observe


_IMPORTED = """
from ext import helper


def run():
    return helper()
"""
# A shadowed BARE NAME reaches no record: an unresolved reference is dropped
# and only a call is always recorded, so the shadow has to be called for the
# rule to be produced at all.  Measured while building this fixture -- the
# first version rebound the name and merely read it, and the mechanism never
# fired in any configuration.
_SHADOWED = """
from ext import helper


def run(factory):
    helper = factory()
    return helper()
"""
_INERT = """
def run():
    return 1
"""

_FIXTURES["imported_symbol"] = _resolution_pair("imported_symbol", _IMPORTED, _SHADOWED)
_FIXTURES["local_shadowing"] = _resolution_pair("local_shadowing", _SHADOWED, _IMPORTED)
_FIXTURES["imported_module_attribute"] = _resolution_pair(
    "imported_module_attribute",
    """
    import ext


    def run():
        return ext.helper()
    """,
    _INERT,
)
_FIXTURES["ambiguous_import"] = _resolution_pair(
    "ambiguous_import",
    """
    from one import helper
    from two import helper


    def run():
        return helper()
    """,
    _IMPORTED,
)
_FIXTURES["same_module_function"] = _resolution_pair(
    "same_module_function",
    """
    def target():
        return 1


    def run():
        return target()
    """,
    _INERT,
)
_FIXTURES["same_module_class"] = _resolution_pair(
    "same_module_class",
    """
    class Target:
        value = 1


    def run():
        return Target()
    """,
    _INERT,
)
_FIXTURES["same_module_class_method"] = _resolution_pair(
    "same_module_class_method",
    """
    class Target:
        def go(self):
            return 1


    def run():
        return Target.go
    """,
    """
    class Target:
        def go(self):
            return 1


    def run():
        return Target.absent
    """,
)
_FIXTURES["self_or_cls_method"] = _resolution_pair(
    "self_or_cls_method",
    """
    class Target:
        def go(self):
            return 1

        def run(self):
            return self.go()
    """,
    """
    class Target:
        def go(self):
            return 1

        def run(self):
            return self.absent()
    """,
)
_FIXTURES["unresolved_name"] = _resolution_pair(
    "unresolved_name",
    """
    def run():
        return missing()
    """,
    _INERT,
)
_FIXTURES["unresolved_dynamic"] = _resolution_pair(
    "unresolved_dynamic",
    """
    def run(obj):
        return obj.method()
    """,
    _INERT,
)


# --- external exposure ------------------------------------------------------


def _exposure_pair(
    mechanism: str, with_kwargs: Inputs, without_kwargs: Inputs
) -> Fixture:
    def observe(_root: Path) -> tuple[bool, bool]:
        return (
            mechanism in _exposure_mechanisms(**with_kwargs),  # type: ignore[arg-type]
            mechanism in _exposure_mechanisms(**without_kwargs),  # type: ignore[arg-type]
        )

    return observe


_PUBLIC_SERVICE = _candidate("pkg.api:Service", kind="class")
_PRIVATE_SERVICE = _candidate("pkg._api:Service", kind="class")

_FIXTURES["public_module"] = _exposure_pair(
    "public_module",
    {
        "candidates": (_PUBLIC_SERVICE,),
        "class_metrics": (),
        "package_modules": frozenset(),
    },
    {
        "candidates": (_PRIVATE_SERVICE,),
        "class_metrics": (),
        "package_modules": frozenset(),
    },
)

_FIXTURES["package_reexport"] = _exposure_pair(
    "package_reexport",
    {
        "candidates": (_PRIVATE_SERVICE,),
        "module_deps": (_dep("pkg", "pkg._api", requested_names=("Service",)),),
        "class_metrics": (),
        "package_modules": frozenset({"pkg"}),
    },
    {
        "candidates": (_PRIVATE_SERVICE,),
        "module_deps": (),
        "class_metrics": (),
        "package_modules": frozenset({"pkg"}),
    },
)

_STAR_BOUND = DeadCandidate(
    qualname="pkg._api:Service",
    local_name="Service",
    filepath="pkg/_api.py",
    start_line=1,
    end_line=2,
    kind="class",
    star_import_bound=True,
)

_STAR_EDGE = _dep("pkg", "pkg._api", requested_names=("*",))

_FIXTURES["star_reexport"] = _exposure_pair(
    "star_reexport",
    {
        "candidates": (_STAR_BOUND,),
        "module_deps": (_STAR_EDGE,),
        "class_metrics": (),
        "package_modules": frozenset({"pkg"}),
    },
    {
        "candidates": (_PRIVATE_SERVICE,),
        "module_deps": (_STAR_EDGE,),
        "class_metrics": (),
        "package_modules": frozenset({"pkg"}),
    },
)

# The mechanism that escaped the vocabulary. Liveness policy v4 added it as a
# raw f-string, the cherry-pick merged it without a textual conflict, and rule
# 1 stayed green because no fixture here had ever built the construct it needs:
# a PUBLIC PLAIN MODULE (not a package) that imports a name and lists it in
# __all__. The gap was in this corpus, not only in that producer.
_FIXTURES["declared_reexport"] = _exposure_pair(
    "declared_reexport",
    {
        "candidates": (_PRIVATE_SERVICE,),
        "module_deps": (_dep("pkg.api", "pkg._api", requested_names=("Service",)),),
        "class_metrics": (),
        "package_modules": frozenset(),
        "declared_exports": ("pkg.api:Service",),
    },
    # Only the declaration is withdrawn: the same public module still imports
    # the same name, and without the __all__ entry that import is an
    # implementation detail again.
    {
        "candidates": (_PRIVATE_SERVICE,),
        "module_deps": (_dep("pkg.api", "pkg._api", requested_names=("Service",)),),
        "class_metrics": (),
        "package_modules": frozenset(),
        "declared_exports": (),
    },
)

_FIXTURES["lazy_namespace"] = _exposure_pair(
    "lazy_namespace",
    {
        "candidates": (_PRIVATE_SERVICE,),
        "module_deps": (_dep("pkg", "lazy_loader", import_type="import"),),
        "class_metrics": (),
        "package_modules": frozenset({"pkg"}),
    },
    {
        "candidates": (_PRIVATE_SERVICE,),
        "module_deps": (_dep("pkg", "json", import_type="import"),),
        "class_metrics": (),
        "package_modules": frozenset({"pkg"}),
    },
)

_MODULE_GETATTR = _candidate(
    "pkg:__getattr__", kind="function", local_name="__getattr__"
)

_FIXTURES["module_getattr"] = _exposure_pair(
    "module_getattr",
    {
        "candidates": (_PRIVATE_SERVICE, _MODULE_GETATTR),
        "class_metrics": (),
        "package_modules": frozenset({"pkg"}),
    },
    {
        "candidates": (_PRIVATE_SERVICE,),
        "class_metrics": (),
        "package_modules": frozenset({"pkg"}),
    },
)

#: The declared-reexport arm gets its own module and symbol. Both it and the
#: package re-export expose at _REACHABLE and ``_exposure`` keeps the first
#: construct at equal rank, so a shared symbol would let one mask the other --
#: the sibling-masking shape, in a corpus whose whole job is coverage.
_FACADE_TARGET = _candidate("pkg._impl:Helper", kind="class")
#: Carried outward by the wildcard edge, in a module of its own so the carry is
#: not masked by a definition another rule already exposes.
_STAR_CARRIED = DeadCandidate(
    qualname="pkg._star:Carried",
    local_name="Carried",
    filepath="pkg/_star.py",
    start_line=1,
    end_line=2,
    kind="class",
    star_import_bound=True,
)
_BASE_METHOD = _candidate("pkg._api:Base.render")
_BASE_CLASS = _class("pkg._api:Base")
_PUBLIC_CHILD = _class("pkg.api:Child", base_names=("Base",))
_SUBCLASS_DEPS = (_dep("pkg.api", "pkg._api", requested_names=("Base",)),)

_FIXTURES["exposed_subclass"] = _exposure_pair(
    "exposed_subclass",
    {
        "candidates": (_BASE_METHOD,),
        "module_deps": _SUBCLASS_DEPS,
        "class_metrics": (_BASE_CLASS, _PUBLIC_CHILD),
        "package_modules": frozenset(),
    },
    {
        "candidates": (_BASE_METHOD,),
        "module_deps": _SUBCLASS_DEPS,
        "class_metrics": (_BASE_CLASS,),
        "package_modules": frozenset(),
    },
)

_CHILD_METHOD = _candidate("pkg._api:Child.render")
_PRIVATE_CHILD = _class("pkg._api:Child", base_names=("Base",))
_PUBLIC_BASE = _class("pkg.api:Base")
_ANCESTOR_DEPS = (_dep("pkg._api", "pkg.api", requested_names=("Base",)),)

_FIXTURES["exposed_ancestor"] = _exposure_pair(
    "exposed_ancestor",
    {
        "candidates": (_CHILD_METHOD,),
        "module_deps": _ANCESTOR_DEPS,
        "class_metrics": (_PRIVATE_CHILD, _PUBLIC_BASE),
        "package_modules": frozenset(),
    },
    {
        "candidates": (_CHILD_METHOD,),
        "module_deps": _ANCESTOR_DEPS,
        "class_metrics": (_PRIVATE_CHILD,),
        "package_modules": frozenset(),
    },
)

_WIDGET_METHOD = _candidate("pkg._api:Widget.render")

_FIXTURES["unresolved_base"] = _exposure_pair(
    "unresolved_base",
    {
        "candidates": (_WIDGET_METHOD,),
        "class_metrics": (_class("pkg._api:Widget", base_names=("VendorBase",)),),
        "package_modules": frozenset(),
    },
    {
        "candidates": (_WIDGET_METHOD,),
        "class_metrics": (_class("pkg._api:Widget", base_names=()),),
        "package_modules": frozenset(),
    },
)


# --- liveness: the constructs that enter referenced_qualnames ---------------


def _qualname_pair(target: str, with_source: str, without_source: str) -> Fixture:
    def observe(root: Path) -> tuple[bool, bool]:
        return (
            target
            in _referenced_qualnames(
                root / "with", {"pkg/__init__.py": "\n", "pkg/m.py": with_source}
            ),
            target
            in _referenced_qualnames(
                root / "without", {"pkg/__init__.py": "\n", "pkg/m.py": without_source}
            ),
        )

    return observe


_FIXTURES["imported_symbol_reference"] = _qualname_pair(
    "other:thing",
    """
    from other import thing


    def run():
        return thing()
    """,
    """
    from other import thing
    """,
)
_FIXTURES["imported_module_attribute_reference"] = _qualname_pair(
    "other:thing",
    """
    import other


    def run():
        return other.thing()
    """,
    """
    import other
    """,
)
_FIXTURES["same_module_class_attribute_reference"] = _qualname_pair(
    "pkg.m:Target.go",
    """
    class Target:
        def go(self):
            return 1


    def run():
        return Target.go
    """,
    """
    class Target:
        def go(self):
            return 1
    """,
)
# The four __all__ fixtures that stood here were removed with the mechanisms
# they evidenced: liveness policy v4 retracted the arm that folded an __all__
# entry into referenced_qualnames, and rule 4 requires a parked mechanism to
# carry no fixture. Rule 3 named all four by id on the rebased tree before a
# line of this file changed.
_FIXTURES["explicit_reexport_alias"] = _qualname_pair(
    "other:thing",
    """
    from other import thing as thing
    """,
    """
    from other import thing
    """,
)


# --- liveness: the evaluator's own decision points --------------------------


def _classify_pair(
    observe_live: Callable[[Inputs], bool],
    with_kwargs: Inputs,
    without_kwargs: Inputs,
) -> Fixture:
    def observe(_root: Path) -> tuple[bool, bool]:
        return observe_live(with_kwargs), observe_live(without_kwargs)

    return observe


def _is_live(kwargs: Inputs) -> bool:
    """The symbol is not reported dead, and not merely abstained."""
    classification = classify_liveness(**kwargs)  # type: ignore[arg-type]
    definitions = cast("tuple[DeadCandidate, ...]", kwargs["definitions"])
    qualname = definitions[0].qualname
    return (
        qualname not in {item.qualname for item in classification.dead_items}
        and qualname
        not in {item.qualname for item in classification.unresolved_overrides}
        and qualname
        not in {item.qualname for item in classification.unresolved_reachability}
    )


def _non_actionable_pair(live_local: str, dead_local: str, kind: str) -> Fixture:
    def inputs(local: str) -> Inputs:
        return {
            "definitions": (
                _candidate(f"pkg.m:Holder.{local}", kind=kind, local_name=local)
                if kind == "method"
                else _candidate(f"pkg.m:{local}", kind=kind, local_name=local),
            ),
            "referenced_names": frozenset(),
        }

    return _classify_pair(_is_live, inputs(live_local), inputs(dead_local))


_FIXTURES["module_runtime_hook"] = _non_actionable_pair(
    "__getattr__", "plain_helper", "function"
)
_FIXTURES["dunder_method"] = _non_actionable_pair("__len__", "render", "method")
_FIXTURES["visitor_prefix_method"] = _non_actionable_pair(
    "visit_Name", "render", "method"
)
_FIXTURES["xunit_hook_method"] = _non_actionable_pair(
    "setup_method", "render", "method"
)


def _test_lane_inputs(filepath: str) -> Inputs:
    return {
        "definitions": (
            _candidate("pkg.m:helper", kind="function", filepath=filepath),
        ),
        "referenced_names": frozenset(),
    }


_FIXTURES["test_source_lane"] = _classify_pair(
    _is_live,
    _test_lane_inputs("tests/test_helpers.py"),
    _test_lane_inputs("pkg/m.py"),
)

_FIXTURES["bare_name_reference"] = _classify_pair(
    _is_live,
    {
        "definitions": (_candidate("pkg.m:helper", kind="function"),),
        "referenced_names": frozenset({"helper"}),
    },
    {
        "definitions": (_candidate("pkg.m:helper", kind="function"),),
        "referenced_names": frozenset(),
    },
)

_FIXTURES["dead_code_directive"] = _classify_pair(
    _is_live,
    {
        "definitions": (
            _candidate(
                "pkg.m:helper", kind="function", suppressed_rules=("dead-code",)
            ),
        ),
        "referenced_names": frozenset(),
    },
    {
        "definitions": (_candidate("pkg.m:helper", kind="function"),),
        "referenced_names": frozenset(),
    },
)

_FIXTURES["self_dispatch"] = _classify_pair(
    _is_live,
    {
        "definitions": (_candidate("pkg.m:Holder.render"),),
        "referenced_names": frozenset(),
        "class_metrics": (
            _class(
                "pkg.m:Holder",
                self_dispatched_methods=frozenset({"pkg.m:Holder.render"}),
            ),
        ),
    },
    {
        "definitions": (_candidate("pkg.m:Holder.render"),),
        "referenced_names": frozenset(),
        "class_metrics": (_class("pkg.m:Holder"),),
    },
)


def _override_inputs(evidenced: frozenset[str]) -> Inputs:
    return {
        "definitions": (_candidate("pkg.m:Holder.render"),),
        "referenced_names": frozenset(),
        "class_metrics": (
            _class(
                "pkg.m:Holder",
                base_names=("VendorBase",),
                has_unresolved_external_base=True,
                decorator_evidenced_methods=evidenced,
            ),
        ),
    }


_FIXTURES["override_decorator_evidence"] = _classify_pair(
    _is_live,
    _override_inputs(frozenset({"pkg.m:Holder.render"})),
    _override_inputs(frozenset()),
)


def _abstains_as(reason: str) -> Callable[[Inputs], bool]:
    def observe(kwargs: Inputs) -> bool:
        classification = classify_liveness(**kwargs)  # type: ignore[arg-type]
        return any(
            item.reason == reason for item in classification.unresolved_reachability
        )

    return observe


#: The witness this fixture rides with, per state.  One witness for every
#: state was one witness too few: a ``public_module`` witness names a proven
#: public path, so pairing it with ``unresolved`` builds a row saying "here
#: is the import path" under a verdict saying no path could be read.  The
#: producer cannot write that pair BY CONSTRUCTION - ``public_module`` is
#: stamped at exactly one site (``_expose_definitions``) in the same
#: expression as the literal ``_REACHABLE`` rank, and the ``expose`` seam
#: stores rank and witness as the one tuple it was handed - so the
#: state-blind fixture was building an input the analyser cannot produce.
#: (A census would not have licensed this: a pair absent from 17157 rows is a
#: pair that did not occur, not one that cannot.)  ``not_reachable`` carries
#: no witness because that is what the producer writes for it, and because
#: that state never enters the abstention lane at all.
_REACHABILITY_WITNESS: Mapping[str, str] = {
    "reachable": "public_module:pkg.m",
    "not_reachable": "",
    "unresolved": "module_getattr:pkg",
}


def _reachability_inputs(state: str) -> Inputs:
    return {
        "definitions": (_candidate("pkg.m:helper", kind="function"),),
        "referenced_names": frozenset(),
        "world_contract": "open",
        "external_reachability": (
            ExternalReachability("pkg.m:helper", state, _REACHABILITY_WITNESS[state]),  # type: ignore[arg-type]
        ),
    }


_FIXTURES["externally_reachable"] = _classify_pair(
    _abstains_as("externally_reachable"),
    _reachability_inputs("reachable"),
    _reachability_inputs("not_reachable"),
)
_FIXTURES["reachability_unresolved"] = _classify_pair(
    _abstains_as("reachability_unresolved"),
    _reachability_inputs("unresolved"),
    _reachability_inputs("not_reachable"),
)


def _abstains_as_override(kwargs: Inputs) -> bool:
    classification = classify_liveness(**kwargs)  # type: ignore[arg-type]
    return any(
        item.qualname == "pkg.m:Holder.render"
        for item in classification.unresolved_overrides
    )


_FIXTURES["unresolved_external_override"] = _classify_pair(
    _abstains_as_override,
    _override_inputs(frozenset()),
    {
        "definitions": (_candidate("pkg.m:Holder.render"),),
        "referenced_names": frozenset(),
        "class_metrics": (_class("pkg.m:Holder", base_names=("VendorBase",)),),
    },
)


# --- liveness: the walk's own root and exclusion rules -----------------------


def _tree(source: str, name: str = "m") -> dict[str, str]:
    return {"pkg/__init__.py": "\n", f"pkg/{name}.py": source}


def _reason_pair(
    qualname: str, reason: str, with_source: str, without_source: str
) -> Fixture:
    def fired(root: Path, source: str) -> bool:
        found = _candidates(root, _tree(source)).get(qualname)
        return found is not None and found.live_root_reason == reason

    def observe(root: Path) -> tuple[bool, bool]:
        return (
            fired(root / "with", with_source),
            fired(root / "without", without_source),
        )

    return observe


_FIXTURES["external_decorator"] = _reason_pair(
    "pkg.m:handler",
    "external_decorator",
    """
    from ext import register


    @register
    def handler():
        return 1
    """,
    """
    def handler():
        return 1
    """,
)


def _not_a_candidate(qualname: str, with_source: str, without_source: str) -> Fixture:
    """The construct keeps the symbol out of the candidate population."""

    def observe(root: Path) -> tuple[bool, bool]:
        return (
            qualname not in _candidates(root / "with", _tree(with_source)),
            qualname not in _candidates(root / "without", _tree(without_source)),
        )

    return observe


_FIXTURES["protocol_member"] = _not_a_candidate(
    "pkg.m:Shape.render",
    """
    from typing import Protocol


    class Shape(Protocol):
        def render(self) -> int: ...
    """,
    """
    class Shape:
        def render(self) -> int:
            return 1
    """,
)

_FIXTURES["non_runtime_decorator"] = _not_a_candidate(
    "pkg.m:Holder.render",
    """
    from abc import abstractmethod


    class Holder:
        @abstractmethod
        def render(self) -> int: ...
    """,
    """
    class Holder:
        def render(self) -> int:
            return 1
    """,
)

_FIXTURES["pydantic_hook_decorator"] = _not_a_candidate(
    "pkg.m:Model.check",
    """
    from pydantic import field_validator


    class Model:
        @field_validator("value")
        def check(cls, value):
            return value
    """,
    """
    class Model:
        def check(cls, value):
            return value
    """,
)


def _runtime_reachability_targets(root: Path, source: str) -> frozenset[str]:
    observed: set[str] = set()
    for metrics in _metrics(root, _tree(source)).values():
        for fact in metrics.runtime_reachability:
            observed.add(fact.target_qualname)
    return frozenset(observed)


def _runtime_edge(root: Path) -> tuple[bool, bool]:
    registered = """
    from flask import Flask

    app = Flask(__name__)


    @app.route("/")
    def handler():
        return 1
    """
    plain = """
    def handler():
        return 1
    """
    return (
        "pkg.m:handler" in _runtime_reachability_targets(root / "with", registered),
        "pkg.m:handler" in _runtime_reachability_targets(root / "without", plain),
    )


_FIXTURES["runtime_reachability_edge"] = _runtime_edge


def _project_entrypoint(root: Path) -> tuple[bool, bool]:
    from codeclone.core.entrypoints import collect_project_entrypoint_qualnames

    candidate = _candidate("pkg.m:main", kind="function")
    declared = root / "with"
    bare = root / "without"
    _write(
        declared,
        {
            "pyproject.toml": """
            [project]
            name = "demo"
            version = "0.0.1"

            [project.scripts]
            demo = "pkg.m:main"
            """,
        },
    )
    _write(bare, {"pyproject.toml": '[project]\nname = "demo"\nversion = "0.0.1"\n'})
    return (
        "pkg.m:main"
        in collect_project_entrypoint_qualnames(
            root=declared, dead_candidates=(candidate,)
        ),
        "pkg.m:main"
        in collect_project_entrypoint_qualnames(
            root=bare, dead_candidates=(candidate,)
        ),
    )


_FIXTURES["project_entrypoint"] = _project_entrypoint


# --------------------------------------------------------------------------
# Rule 1 - an emitted mechanism MUST exist in the registry.


def test_the_doors_refuse_a_mechanism_no_vocabulary_declares() -> None:
    """Rule 1, runtime half: a producer cannot smuggle a new name past here."""

    for door in (validate_live_root_reason, validate_resolution_rule):
        with pytest.raises(LivenessVocabularyError):
            door("no_such_mechanism")
    with pytest.raises(LivenessVocabularyError):
        exposure_witness("no_such_mechanism", "pkg")
    for reason in LIVE_ROOT_REASONS:
        assert validate_live_root_reason(reason) == reason
    for rule in MECHANISMS:
        if MECHANISMS[rule].witness_type == "resolution_rule":
            assert validate_resolution_rule(rule) == rule


def test_the_reachability_fixture_witness_belongs_to_its_state() -> None:
    """Rule 1, applied to this file's own fixture.

    The witness above is not three literals to be kept in step by hand; it is
    derived from the vocabulary the abstention row itself consults, and this
    re-derives it.  Pinning the literals would only move the magic constant
    into a test, and a comment explaining the choice is an unexecuted claim
    that rots the moment somebody swaps a mechanism.  Swap them and this reds
    before the causal fixtures do, naming the half that moved.
    """

    for state, witness in _REACHABILITY_WITNESS.items():
        if state == "not_reachable":
            # The producer writes no witness here, and the abstention lane
            # never sees this state: `classify_liveness` skips it outright.
            assert witness == "", state
            continue
        mechanism = witness_mechanism(witness)
        assert mechanism is not None, f"{state}: {witness!r} names no mechanism"
        assert state in EXPOSURE_MECHANISM_STATES[mechanism], (
            f"{state}: {mechanism!r} witnesses "
            f"{sorted(EXPOSURE_MECHANISM_STATES[mechanism])}"
        )


@pytest.mark.parametrize(
    ("state", "witness", "rejected_mechanism"),
    [
        # Admitted: single-state mechanisms, at the one state they name.
        ("reachable", "public_module:pkg.m", None),
        ("unresolved", "module_getattr:pkg", None),
        # Admitted: the two mechanisms the producer emits at BOTH states.
        # `type_witness` / `ancestor_witness` manufacture these and take the
        # rank from the related class's own exposure, so the state is chosen
        # on an axis the witness knows nothing about.  Refusing the second row
        # of each pair made a correct program raise.
        ("reachable", "exposed_subclass:pkg.api:Child", None),
        ("unresolved", "exposed_subclass:pkg._dyn:Child", None),
        ("reachable", "exposed_ancestor:pkg.api:Base", None),
        ("unresolved", "exposed_ancestor:pkg._dyn:Base", None),
        # Refused, each by a CONSTRUCTION argument, never by a census.
        ("unresolved", "public_module:pkg.m", "public_module"),
        ("reachable", "module_getattr:pkg", "module_getattr"),
    ],
)
def test_an_abstention_row_is_constructible_where_the_producer_emits_it(
    state: ReachabilityState, witness: str, rejected_mechanism: str | None
) -> None:
    """Both boundaries of the witness door, against the producer's SHAPE.

    The door is an admissibility relation over ``(mechanism, state)``, not a
    function from mechanism to state, because the producer picks the two on
    independent axes: the state is the RANK of the chain it found, the
    witness is the CONSTRUCT that found it.  ``exposed_subclass`` and
    ``exposed_ancestor`` name a related class whose own exposure may sit at
    either rank, so both rows of each pair are legal and both are admitted
    here; the sibling test below observes them coming out of the producer.

    The two refusals are refusals BY CONSTRUCTION, and that is the whole
    standard: ``public_module`` is stamped at exactly one site in the same
    expression as the literal ``_REACHABLE`` rank, and the dynamic witnesses
    are built into ``dynamic_packages`` / ``dynamic_modules`` whose every
    consumer pairs them with ``_UNRESOLVED``.  A pair merely ABSENT from a
    corpus would not be pinned here at all: absence is a fact about the
    corpus, and pinning it would pin a coincidence.

    Both directions are pinned on purpose.  A door that refused everything
    would satisfy the rejection rows alone, and a door that refused nothing
    would satisfy the acceptance rows alone; only the pair can tell them
    apart.  The reason is always the one its state owns, so a rejection here
    is provably about the WITNESS and never about a mismatched reason.
    """

    def build() -> UnresolvedReachabilityItem:
        return UnresolvedReachabilityItem(
            qualname="pkg.m:helper",
            filepath="pkg/m.py",
            start_line=1,
            end_line=2,
            kind="function",
            reachability=state,
            witness=witness,
            world_contract="open",
            reason=abstention_reason_for_state(state),
        )

    if rejected_mechanism is None:
        item = build()
        assert item.reachability == state
        assert item.witness == witness
        assert item.reason == abstention_reason_for_state(state)
        return
    with pytest.raises(LivenessVocabularyError) as raised:
        build()
    message = str(raised.value)
    assert rejected_mechanism in message, message
    assert f"cannot witness state {state!r}" in message, message


#: The two arms that make ``exposed_subclass`` and ``exposed_ancestor`` come
#: out of ONE producer run at BOTH states.  Each arm is a private class whose
#: related class is exposed - once through a public module (proven rank),
#: once through a plain module's ``__getattr__`` serving a declared name
#: (unresolved rank).  Nothing about the arm changes but the RANK of the
#: related class, which is the axis the earlier mechanism-to-state function
#: could not express.
_BOTH_STATES_CANDIDATES: Final = (
    # exposed_subclass @ reachable: the descendant lives in a public module.
    _candidate("psub._impl:SubBase.render"),
    _candidate("psub.api:SubChild", kind="class"),
    # exposed_subclass @ unresolved: the descendant is only ever served by a
    # plain module's __getattr__, so its own exposure sits at the unresolved
    # rank and the subclass witness inherits it.
    _candidate("dsub._impl:SubBase.render"),
    _candidate("dsub._impl:SubChild", kind="class"),
    _candidate("dsub.mod:__getattr__", kind="function", local_name="__getattr__"),
    # exposed_ancestor @ reachable / @ unresolved: the same two shapes, read
    # up the hierarchy instead of down.
    _candidate("panc._api:AncChild.render"),
    _candidate("panc.api:AncBase", kind="class"),
    _candidate("danc._api:AncChild.render"),
    _candidate("danc._impl:AncBase", kind="class"),
    _candidate("danc.mod:__getattr__", kind="function", local_name="__getattr__"),
)
_BOTH_STATES_DEPS: Final = (
    _dep("psub.api", "psub._impl", requested_names=("SubBase",)),
    _dep("panc._api", "panc.api", requested_names=("AncBase",)),
    _dep("danc._api", "danc._impl", requested_names=("AncBase",)),
)
_BOTH_STATES_CLASSES: Final = (
    _class("psub._impl:SubBase"),
    _class("psub.api:SubChild", base_names=("SubBase",)),
    _class("dsub._impl:SubBase"),
    _class("dsub._impl:SubChild", base_names=("SubBase",)),
    _class("panc._api:AncChild", base_names=("AncBase",)),
    _class("panc.api:AncBase"),
    _class("danc._api:AncChild", base_names=("AncBase",)),
    _class("danc._impl:AncBase"),
)
_BOTH_STATES_EXPORTS: Final = ("dsub.mod:SubChild", "danc.mod:AncBase")

#: The mechanisms whose construction admits ONE state, and the state it is.
#: Not a restatement of the owner: the owner is the door's data, and this is
#: the CONSTRUCTION each single-state entry claims, so a widening that is not
#: matched by a producer change reds here instead of passing quietly.
_SINGLE_STATE_BY_CONSTRUCTION: Final[Mapping[str, str]] = {
    "public_module": "reachable",
    "package_reexport": "reachable",
    "declared_reexport": "reachable",
    "star_reexport": "reachable",
    "lazy_namespace": "unresolved",
    "module_getattr": "unresolved",
    "unresolved_base": "unresolved",
}


def test_the_relation_admits_every_pair_the_producer_emits() -> None:
    """The causal half: run the producer, read back the PAIRS it wrote.

    This is the pin the earlier shape failed.  ``EXPOSURE_MECHANISM_STATE``
    mapped one state to each mechanism and every test around it re-read that
    map, so the map agreed with itself for any content; the producer was
    never asked.  Here it is asked, and its answer is the standard.

    The population is reported, not assumed (probe validity): the corpus must
    reach every declared exposure mechanism, and it must reach BOTH states
    for the two class mechanisms - otherwise a narrowing of the relation
    would pass here for want of a distinguishing row rather than for being
    right.
    """

    observed = _exposure_pairs(
        candidates=(
            _PUBLIC_SERVICE,
            _PRIVATE_SERVICE,
            _BASE_METHOD,
            _WIDGET_METHOD,
            _MODULE_GETATTR,
            _FACADE_TARGET,
            _STAR_CARRIED,
            _candidate("pkg._anc:Leaf.render"),
            _candidate("pkg._dyn:Thing", kind="class"),
            _candidate("lazypkg._sub:Lazy", kind="class"),
            *_BOTH_STATES_CANDIDATES,
        ),
        module_deps=(
            _dep("pkg", "pkg._api", requested_names=("Service",)),
            _dep("pkg.api", "pkg._api", requested_names=("Base",)),
            _dep("pkg.facade", "pkg._impl", requested_names=("Helper",)),
            _dep("pkg", "pkg._star", requested_names=("*",)),
            _dep("pkg._anc", "pkg.anc", requested_names=("Root",)),
            _dep("lazypkg", "lazy_loader", import_type="import"),
            *_BOTH_STATES_DEPS,
        ),
        class_metrics=(
            _BASE_CLASS,
            _PUBLIC_CHILD,
            _class("pkg._anc:Leaf", base_names=("Root",)),
            _class("pkg.anc:Root"),
            _class("pkg._api:Widget", base_names=("VendorBase",)),
            *_BOTH_STATES_CLASSES,
        ),
        package_modules=frozenset({"pkg", "lazypkg"}),
        declared_exports=("pkg.facade:Helper", *_BOTH_STATES_EXPORTS),
    )

    # Population witness 1: nothing declared went unmeasured.
    reached = {mechanism for mechanism, _ in observed}
    assert reached == set(EXTERNAL_EXPOSURE_MECHANISMS), sorted(
        set(EXTERNAL_EXPOSURE_MECHANISMS) ^ reached
    )
    # Population witness 2: the distinguishing rows exist.  Without these two
    # assertions the pin below would pass on a corpus that never built the
    # case the whole change is about.
    for mechanism in ("exposed_subclass", "exposed_ancestor"):
        states = {state for name, state in observed if name == mechanism}
        assert states == {"reachable", "unresolved"}, (mechanism, sorted(states))

    # The pin: the door must admit every pair the producer wrote.
    for mechanism, state in sorted(observed):
        assert state in EXPOSURE_MECHANISM_STATES[mechanism], (
            f"the producer emits {mechanism!r} at {state!r}, which the "
            f"relation refuses; it admits "
            f"{sorted(EXPOSURE_MECHANISM_STATES[mechanism])}"
        )

    # The other direction is NOT asserted from this corpus.  A pair this run
    # did not produce is a pair that did not occur here, which is not a pair
    # the producer cannot write; only the construction argument below settles
    # that, and it is stated per mechanism rather than counted.
    for mechanism, state in sorted(_SINGLE_STATE_BY_CONSTRUCTION.items()):
        assert EXPOSURE_MECHANISM_STATES[mechanism] == frozenset({state}), (
            f"{mechanism!r} is admitted at "
            f"{sorted(EXPOSURE_MECHANISM_STATES[mechanism])}, but its producer "
            f"stamps it only at {state!r}; widen it only with a producer "
            f"change that makes the other pair constructible"
        )


def test_a_parked_reason_is_decodable_and_not_emittable() -> None:
    """Acceptance and production are two vocabularies, not one.

    They were one set, and that is exactly how a value nothing produced
    stayed indistinguishable from a value something produced.
    """

    parked = set(LIVE_ROOT_REASONS) - set(ACTIVE_LIVE_ROOT_REASONS)
    assert parked, "no parked live-root reason, so this asymmetry is untested"
    for parked_reason in parked:
        assert validate_live_root_reason(parked_reason) == parked_reason
        with pytest.raises(LivenessVocabularyError):
            emit_live_root_reason(parked_reason)
    # A separate name, not the same one rebound: the parked members come from
    # the typed acceptance vocabulary and the emittable ones from the wider
    # ``str`` production tuple, so one variable would carry two types.
    for active_reason in ACTIVE_LIVE_ROOT_REASONS:
        assert emit_live_root_reason(active_reason) == active_reason


def test_every_mechanism_the_producers_emit_is_declared(tmp_path: Path) -> None:
    """Rule 1, behavioural half: run them, read back what came out.

    Not a scan for string literals.  The corpus below is the fixture corpus,
    so anything a producer invents while answering it lands here.
    """

    observed_rules = _resolution_rules(
        tmp_path / "rules",
        {
            "pkg/__init__.py": "\n",
            "pkg/m.py": textwrap.dedent(
                """
                from ext import helper
                import other


                class Target:
                    def go(self):
                        return 1

                    def run(self):
                        return self.go()


                def call(obj, factory):
                    shadow = factory()
                    return (
                        helper(),
                        other.thing(),
                        Target.go,
                        missing(),
                        obj.method(),
                        shadow(),
                    )
                """
            ),
        },
    )
    assert observed_rules, "no relationship resolved, so no rule was measured"
    declared_rules = {
        identifier
        for identifier, spec in MECHANISMS.items()
        if spec.witness_type == "resolution_rule"
    }
    assert observed_rules <= declared_rules

    observed_exposure = _exposure_mechanisms(
        candidates=(
            _PUBLIC_SERVICE,
            _PRIVATE_SERVICE,
            _BASE_METHOD,
            _WIDGET_METHOD,
            _MODULE_GETATTR,
            _FACADE_TARGET,
            _STAR_CARRIED,
            _candidate("pkg._anc:Leaf.render"),
            _candidate("pkg._dyn:Thing", kind="class"),
            _candidate("lazypkg._sub:Lazy", kind="class"),
        ),
        module_deps=(
            _dep("pkg", "pkg._api", requested_names=("Service",)),
            _dep("pkg.api", "pkg._api", requested_names=("Base",)),
            _dep("pkg.facade", "pkg._impl", requested_names=("Helper",)),
            _dep("pkg", "pkg._star", requested_names=("*",)),
            _dep("pkg._anc", "pkg.anc", requested_names=("Root",)),
            _dep("lazypkg", "lazy_loader", import_type="import"),
        ),
        class_metrics=(
            _BASE_CLASS,
            _PUBLIC_CHILD,
            _class("pkg._anc:Leaf", base_names=("Root",)),
            _class("pkg.anc:Root"),
            _class("pkg._api:Widget", base_names=("VendorBase",)),
        ),
        package_modules=frozenset({"pkg", "lazypkg"}),
        declared_exports=("pkg.facade:Helper",),
    )
    declared_exposure = {
        identifier
        for identifier, spec in MECHANISMS.items()
        if spec.witness_type == "exposure_witness"
    }
    # EQUALITY, and both halves are the rule.
    #
    # ``observed <= declared`` is rule 1 proper: a producer may not emit a
    # mechanism no vocabulary declares. That half was already here, and it
    # stayed green while ``declared_reexport`` escaped -- because a subset
    # assertion also passes on a corpus that reaches nothing, and this one had
    # never built a public plain module with __all__ re-exports.
    #
    # ``declared <= observed`` closes it: every declared exposure mechanism
    # must be REACHED by this sweep. A new mechanism that arrives without a
    # construct here now reds, instead of being admitted by a corpus too
    # narrow to notice it. Each mechanism gets its own carrier on purpose --
    # module_getattr and unresolved_base compete for one row, and
    # package_reexport masks declared_reexport at equal rank.
    assert observed_exposure == declared_exposure


def test_every_acceptance_site_mirrors_the_one_owner() -> None:
    """The five copies of the live-root set must answer as the owner does.

    Four were set literals; the fifth is an if/elif ladder in the discovery
    cache that no set-shaped search finds, which is how a copy stays a copy.
    Each is probed by BEHAVIOUR, so a ladder is covered exactly as a set is.
    """

    from typing import get_args

    from codeclone.cache import _wire_decode
    from codeclone.canonical.identity import LIVE_ROOT_REASONS as canonical_reasons
    from codeclone.core import discovery_cache
    from codeclone.models import LiveRootReason

    assert get_args(LiveRootReason) == LIVE_ROOT_REASONS
    assert canonical_reasons == LIVE_ROOT_REASONS
    assert frozenset(LIVE_ROOT_REASONS) == _wire_decode._LIVE_ROOT_REASONS
    for reason in LIVE_ROOT_REASONS:
        assert discovery_cache._live_root_reason(reason) == reason
    assert discovery_cache._live_root_reason("no_such_reason") is None


# --------------------------------------------------------------------------
# Rule 2 - an active mechanism MUST name exactly ONE producer, and it resolves.


def _resolve(reference: str) -> object:
    module_name, _, qualname = reference.partition(":")
    module = importlib.import_module(module_name)
    found: object = module
    for part in qualname.split("."):
        found = getattr(found, part)
    return found


def test_every_active_mechanism_names_one_resolvable_producer() -> None:
    """Rule 2.

    Exactly one, and it must exist: a mechanism with two owners has no owner,
    and a producer named in prose rots the moment somebody renames it.
    """

    unresolved: list[str] = []
    for identifier in ACTIVE_MECHANISMS:
        spec = MECHANISMS[identifier]
        assert spec.producer, identifier
        assert spec.producer.count(":") == 1, identifier
        try:
            _resolve(spec.producer)
        except (ImportError, AttributeError) as error:
            unresolved.append(f"{identifier}: {spec.producer} ({error})")
    assert unresolved == []


def test_every_semantic_owner_resolves() -> None:
    """Who decides what a mechanism MEANS is executable too.

    A contract constant must exist in ``codeclone.contracts``; anything else
    must be an importable module.  Both forms are real references, so neither
    can quietly stop naming anything.
    """

    for identifier, spec in MECHANISMS.items():
        owner = spec.semantic_owner
        if owner.isupper() or owner.replace("_", "").isupper():
            # Resolved dynamically, like the producers above: a static
            # ``from codeclone import contracts`` writes a ``codeclone`` import
            # edge, and the architecture ratchet reads that as this module
            # reaching ring r4 -- which it does not.
            contracts = importlib.import_module("codeclone.contracts")
            assert hasattr(contracts, owner), f"{identifier}: {owner}"
        else:
            importlib.import_module(owner)


def test_the_spec_refuses_an_active_mechanism_with_no_producer() -> None:
    """ "Active with zero producers" is not representable.

    That state is what ``export_root`` was in for months.  The registry
    refuses to hold it, so the claim cannot be written down at all.
    """

    with pytest.raises(LivenessVocabularyError):
        MechanismSpec(
            id="claim",
            kind="liveness",
            producer="",
            witness_type="none",
            semantic_owner="LIVENESS_POLICY_VERSION",
            summary="a mechanism nothing produces",
        )
    # The park reason here is a REAL one, and that is the whole point of the
    # arm.  It read ``"no_producer"`` -- a reason the first pass declared and
    # rule 4 has since deleted -- so the refusal it raised came from the
    # unknown-reason branch, and the producer check it claims to pin could be
    # deleted outright with this test still green (measured: mutant survived).
    # Asserting on the message closes it: only the producer branch says
    # "unpark it instead".
    with pytest.raises(LivenessVocabularyError, match="unpark it instead"):
        MechanismSpec(
            id="claim",
            kind="liveness",
            producer="codeclone.metrics.dead_code:classify_liveness",
            witness_type="none",
            semantic_owner="LIVENESS_POLICY_VERSION",
            summary="a parked mechanism that still names a producer",
            status="explicitly_parked",
            park_reason=PARK_SUPERSEDED_BY_EVIDENCE_LANE,
        )
    # The opposite arm of the same rule, so neither can stand in for the other:
    # a park reason outside the reviewed vocabulary is refused on its own.
    with pytest.raises(LivenessVocabularyError, match="unknown park reason"):
        MechanismSpec(
            id="claim",
            kind="liveness",
            producer="",
            witness_type="none",
            semantic_owner="LIVENESS_POLICY_VERSION",
            summary="a parked mechanism with a reason nobody reviewed",
            status="explicitly_parked",
            park_reason="no_producer",
        )


def test_the_spec_refuses_an_active_mechanism_carrying_a_park_reason() -> None:
    """The fourth arm of the same law, and it had no input reaching it.

    ``__post_init__`` has four refusals; three were exercised and this one was
    not (measured: the line was uncovered while the ratchet was green). A guard
    no input reaches is theatre, and this file is the last place that should
    ship one -- rule 4 exists precisely because a declared thing nobody
    produces is invisible until something asks.

    Active-with-a-park-reason is the mirror of parked-with-a-producer: both say
    the status and the evidence disagree, and a spec that holds either is a
    registry entry whose own record contradicts it.
    """

    with pytest.raises(LivenessVocabularyError, match="carries a park reason"):
        MechanismSpec(
            id="claim",
            kind="liveness",
            producer="codeclone.metrics.dead_code:classify_liveness",
            witness_type="none",
            semantic_owner="LIVENESS_POLICY_VERSION",
            summary="an active mechanism that also claims to be parked",
            park_reason=PARK_SUPERSEDED_BY_EVIDENCE_LANE,
        )


def test_the_index_refuses_two_mechanisms_under_one_id() -> None:
    """One id, one owner -- enforced when the registry is built, not reviewed.

    Two specs under one id would make ``MECHANISMS`` silently keep the last,
    so a mechanism could be redefined by a later table without a word. This
    guard was likewise unreached by any input; it is exercised here through
    the same private builder the module uses, because that is the only place
    the collision can happen.
    """

    from codeclone.models import _index

    duplicate = MechanismSpec(
        id="external_decorator",
        kind="liveness",
        producer="codeclone.metrics.dead_code:classify_liveness",
        witness_type="none",
        semantic_owner="LIVENESS_POLICY_VERSION",
        summary="a second claim on an id the registry already owns",
    )
    with pytest.raises(LivenessVocabularyError, match="duplicate mechanism id"):
        _index((MECHANISMS["external_decorator"],), (duplicate,))


# --------------------------------------------------------------------------
# Rule 3 - an active mechanism MUST have at least one CAUSAL fixture.


def test_every_active_mechanism_has_a_causal_fixture(tmp_path: Path) -> None:
    """Rule 3, and the reason this ratchet exists.

    For each active mechanism the fixture runs the producer twice and the
    mechanism must fire in the first run and NOT in the second.  Both halves
    are load-bearing.  Without the first, a name nothing can produce stays
    declared for ever -- which is the ``export_root`` defect verbatim, and it
    survived a vocabulary, five acceptance sites and a type alias.  Without
    the second, a fixture that would have fired anyway counts as evidence,
    and the ratchet measures co-presence instead of cause.
    """

    missing = sorted(set(ACTIVE_MECHANISMS) - set(_FIXTURES))
    assert missing == [], f"active mechanisms with no causal fixture: {missing}"

    never_fired: list[str] = []
    fired_without: list[str] = []
    for identifier in ACTIVE_MECHANISMS:
        with_construct, without_construct = _FIXTURES[identifier](tmp_path / identifier)
        if not with_construct:
            never_fired.append(identifier)
        elif without_construct:
            fired_without.append(identifier)
    assert never_fired == [], (
        f"declared active and unproducible by their own fixture: {never_fired}"
    )
    assert fired_without == [], (
        "fired with the construct removed, so the fixture shows co-presence "
        f"and not cause: {fired_without}"
    )


def test_the_fixture_map_claims_nothing_the_registry_does_not(tmp_path: Path) -> None:
    """A fixture for a name no vocabulary declares is a fixture for nothing."""

    assert sorted(set(_FIXTURES) - set(MECHANISMS)) == []
    assert set(_FIXTURES).isdisjoint(PARKED_MECHANISMS)


# --------------------------------------------------------------------------
# Rule 4 - a mechanism that is off MUST be explicitly parked and stay unproduced.


def _observed_live_root_reasons(root: Path) -> frozenset[str]:
    """Every live-root reason the walk emits over a corpus built to root things.

    External decorators, a package re-export chain, an ``__all__`` export and
    a wildcard carry: every construct that has ever been read as a reason to
    call a symbol live.  If a declared reason cannot be produced here, no
    configuration of this build produces it.
    """

    tree = {
        "pkg/__init__.py": """
        from pkg.api import Service, handler

        __all__ = ["Service", "handler"]
        """,
        "pkg/api.py": """
        from ext import register
        from pkg.internal import *


        @register
        def handler():
            return 1


        class Service:
            @register
            def render(self):
                return 2

            def plain(self):
                return 3
        """,
        "pkg/internal.py": """
        __all__ = ["carried"]


        def carried():
            return 1
        """,
    }
    observed: set[str] = set()
    for candidate in _candidates(root, tree).values():
        if candidate.live_root_reason is not None:
            observed.add(candidate.live_root_reason)
    return frozenset(observed)


def test_every_park_reason_is_used_and_fits_the_shape_of_its_retirement() -> None:
    """A park reason is a claim about WHY, and the wrong one is worse than none.

    A test cannot read the semantics, but the two reasons this registry uses
    differ in a structurally observable way and that much is pinned:

    * ``superseded_by_evidence_lane`` says the fact was RELOCATED and is still
      recorded. Only a mechanism whose witness rides a lane can be relocated,
      so it must carry a real witness type -- ``export_root`` still spells a
      ``live_root_reason`` a stored row may hold.
    * ``producer_retracted`` says the rule was REMOVED because it answered the
      wrong question. Nothing records the mechanism, so it must carry
      ``none``. Swapping the two reasons reds here in either direction.

    The first assertion is the registry turning its own rule on itself: a park
    reason no mechanism uses is dead vocabulary, and this file exists because
    dead vocabulary is invisible until something asks. ``no_producer`` was
    declared in the first pass, used by nothing, and is gone.
    """

    assert set(PARKED_MECHANISMS.values()) == set(PARK_REASONS), (
        "a declared park reason that no parked mechanism uses is dead "
        "vocabulary; delete it or use it"
    )
    for identifier, reason in PARKED_MECHANISMS.items():
        witness_type = MECHANISMS[identifier].witness_type
        if reason == PARK_SUPERSEDED_BY_EVIDENCE_LANE:
            assert witness_type != "none", (
                f"{identifier} claims its witness moved lanes, but it has no "
                f"witness to move"
            )
        else:
            assert witness_type == "none", (
                f"{identifier} claims its producer was retracted, but it "
                f"still carries a {witness_type} a consumer can read"
            )


def test_parked_mechanisms_are_reasoned_and_still_unproduced(tmp_path: Path) -> None:
    """Rule 4.

    Parking is not a way past rule 3, it is a statement with a typed reason
    that this build cannot conclude the mechanism.  The moment something does
    produce it, the park is a lie and this test says so.
    """

    assert PARKED_MECHANISMS, "nothing is parked, so parking is untested"
    for identifier, reason in PARKED_MECHANISMS.items():
        spec = MECHANISMS[identifier]
        assert reason in PARK_REASONS, identifier
        assert spec.producer == "", identifier
        assert spec.status == "explicitly_parked", identifier

    observed = _observed_live_root_reasons(tmp_path)
    assert observed, "the corpus rooted nothing, so the sweep measured nothing"
    assert observed <= set(ACTIVE_LIVE_ROOT_REASONS)
    parked_live_roots = set(LIVE_ROOT_REASONS) - set(ACTIVE_LIVE_ROOT_REASONS)
    assert observed.isdisjoint(parked_live_roots), (
        "a parked live-root reason was produced; unpark it or stop producing it"
    )
