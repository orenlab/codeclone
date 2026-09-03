# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Internal use is a world-invariant fact; ``__all__`` is an export declaration.

Measured on b4feb0ff (2026-09-03): the ``__all__`` arm of
``_resolve_referenced_qualnames`` folds every static ``__all__`` member into
``referenced_qualnames``, where it is indistinguishable from a call site. On
this repository that one arm holds 104 symbols live under the closed world
(4 dead -> 108) that nothing inside the product binds; 30 of them sit in
private modules or under private names, where the ``__all__`` exports them to
nobody, so they are dead under any world. ``codeclone.api.gc:run_gc``,
``codeclone.cache.gc:CacheStoreGcJob`` and ``codeclone.canonical.store:
RunStoreGcJob`` - the unified GC point, called only by tests - are three of
the 104. No lane names them: the twenty ``live_root_reasons`` on the wire are
all ``external_decorator``, and nothing produces ``export_root`` any more.

The pins below state the ratified model (RULING 2026-09-01, corrected
2026-09-03): a symbol is live for a reason something inside the product gives
it - a production reference, a runtime edge, a framework decorator, a
packaging entry point, a consumer elsewhere in the tree - and an ``__all__``
entry gives none of those. What ``__all__`` decides is exposure, which the
evidence layer reads through ``star_import_bound``, the package re-export
chain and, since liveness policy v4 put the declaration itself on the wire
(``declared_exports``), a public plain module's declared import and the
names a module-level ``__getattr__`` serves - so the declaration keeps its
honest jobs and loses the one it never had.

Every report-layer pin spawns the CLI (``tests/_liveness_report_helpers``):
these are statements about what a user reads.
"""

from __future__ import annotations

import ast
import random
from pathlib import Path
from typing import TYPE_CHECKING

from codeclone.analysis import _module_walk as module_walk_mod
from codeclone.metrics.dead_code import classify_liveness
from codeclone.metrics.external_reachability import collect_external_reachability
from codeclone.models import ClassMetrics, DeadCandidate, ModuleDep
from codeclone.qualnames import QualnameCollector
from tests._ast_metrics_helpers import module_registry_context
from tests._liveness_report_helpers import (
    analysis_report,
    dead_code_family,
    dead_qualnames,
    unresolved_by_qualname,
)

if TYPE_CHECKING:
    from codeclone.models import ExternalReachability, LivenessClassification

_SCOPE_ID = "0192f3aa-6c51-7b28-9d44-1ea5c07b6f3b"

#: The GC shape. ``run_gc`` and ``CacheJob`` are listed in their own module's
#: ``__all__`` and called only from the test tree. ``wired`` is called from
#: production - the control that the lane can still hold a symbol live for a
#: real reason. ``_orphan`` is private and uncalled - the control that the lane
#: fires at all, so "not in dead" is never a statement about an empty set.
_GC_TREE = {
    "pkg/__init__.py": "",
    "pkg/gc.py": """
class CacheJob:
    def collect(self) -> int:
        return 1


def run_gc(jobs):
    return [job.collect() for job in jobs]


def wired() -> int:
    return 3


def _orphan() -> int:
    return 4


__all__ = ["CacheJob", "run_gc", "wired"]
""",
    "pkg/service.py": """
from .gc import wired

VALUE = wired()
""",
    "tests/test_gc.py": """
from pkg.gc import CacheJob, run_gc


def test_dispatch() -> None:
    assert run_gc([CacheJob()]) == [1]
""",
}

#: A package facade: the origin is imported by name and listed in the
#: package's ``__all__``, and nothing inside the tree uses it.
_FACADE_TREE = {
    "pkg/__init__.py": """
from ._impl import Client

__all__ = ["Client"]
""",
    "pkg/_impl.py": """
class Client:
    def post(self) -> int:
        return 1
""",
}

#: An ``__all__`` in a private module that nothing imports: the export
#: declaration reaches nobody, inside or outside.
_PRIVATE_TREE = {
    "pkg/__init__.py": "",
    "pkg/_store.py": """
def helper() -> int:
    return 1


__all__ = ["helper"]
""",
}

#: A consumer inside the tree but outside the package - the shape of the
#: editor plugin hooks that import ``codeclone.workspace_intent.gate``.
_CONSUMER_TREE = {
    "pkg/__init__.py": "",
    "pkg/gate.py": """
def evaluate() -> int:
    return 1
""",
    "plugins/hook.py": """
from pkg.gate import evaluate

RESULT = evaluate()
""",
}

_ENTRY_POINT_TREE = {
    "pkg/__init__.py": "",
    "pkg/cli.py": """
def main() -> int:
    return 0
""",
}
_ENTRY_POINT_PYPROJECT = (
    "",
    "[project]",
    'name = "entry-point-probe"',
    'version = "0.0.0"',
    "",
    "[project.scripts]",
    'probe = "pkg.cli:main"',
)

#: The maintainer's construction (2026-09-03), five lines: a PUBLIC PLAIN
#: module - not a package ``__init__`` - imports a private module's class and
#: lists it in ``__all__``. ``pkg.api.Widget`` is a documented public path
#: (PEP 8), and nothing inside the tree uses it. The minimal form of the
#: change (drop the ``__all__`` arm and nothing else) answered ``dead`` here
#: under the open world - a false DEAD the standing law forbids.
_FLAT_MODULE_TREE = {
    "pkg/__init__.py": "",
    "pkg/api.py": """
from ._impl import Widget

__all__ = ["Widget"]
""",
    "pkg/_impl.py": """
class Widget:
    def render(self) -> int:
        return 1
""",
}

#: The same three files with the declaration removed: the import is an
#: implementation detail of ``pkg.api`` (PEP 8), and no public path exists.
_FLAT_MODULE_UNDECLARED_TREE = {
    **_FLAT_MODULE_TREE,
    "pkg/api.py": """
from ._impl import Widget
""",
}

#: A public plain module that DECLARES a name and serves it through a
#: module-level ``__getattr__``, loading the origin dynamically. Nothing
#: static binds ``Widget`` in ``pkg.api``; the declaration is the only handle
#: the analysis has on what the hook serves.
_LAZY_MODULE_TREE = {
    "pkg/__init__.py": "",
    "pkg/api.py": """
import importlib

__all__ = ["Widget"]


def __getattr__(name: str) -> object:
    if name not in __all__:
        raise AttributeError(name)
    return getattr(importlib.import_module("pkg._impl"), name)
""",
    "pkg/_impl.py": """
class Widget:
    def render(self) -> int:
        return 1
""",
}

#: The same hook with no declaration: it may serve anything, and the analysis
#: can name nothing, so the origin reads on its own evidence.
_LAZY_MODULE_UNDECLARED_TREE = {
    **_LAZY_MODULE_TREE,
    "pkg/api.py": """
import importlib


def __getattr__(name: str) -> object:
    return getattr(importlib.import_module("pkg._impl"), name)
""",
}

#: The api lane reads the same owner. ``_impl`` declares ``Widget`` so the
#: collector admits it under the language rule; whether it is API is then the
#: binding question, answered by ``pkg.api``'s declaration.
_FLAT_API_TREE = {
    **_FLAT_MODULE_TREE,
    "pkg/_impl.py": """
__all__ = ["Widget"]


class Widget:
    def render(self) -> int:
        return 1
""",
}
_FLAT_API_UNDECLARED_TREE = {
    **_FLAT_API_TREE,
    "pkg/api.py": _FLAT_MODULE_UNDECLARED_TREE["pkg/api.py"],
}

_CLOSED = ("--dead-code-world", "closed")


def _dead_items_by_qualname(family: dict[str, object]) -> dict[str, dict[str, object]]:
    items = family["items"]
    assert isinstance(items, list)
    by_qualname: dict[str, dict[str, object]] = {}
    for item in items:
        assert isinstance(item, dict)
        by_qualname[str(item["qualname"])] = dict(item)
    return by_qualname


def _walk(source: str, *, module_name: str) -> module_walk_mod._ModuleWalkResult:
    identity, registry = module_registry_context(
        filepath=f"{module_name.replace('.', '/')}.py",
        module_name=module_name,
    )
    tree = ast.parse(source.lstrip())
    collector = QualnameCollector()
    collector.visit(tree)
    return module_walk_mod._collect_module_walk_data(
        tree=tree,
        source=identity,
        registry=registry,
        collector=collector,
        collect_referenced_names=True,
    )


# ---------------------------------------------------------------------------
# The walk: an ``__all__`` entry is a binding fact, never a reference.
# ---------------------------------------------------------------------------


def test_the_walk_records_an_all_entry_as_a_binding_fact_not_a_reference() -> None:
    """The mechanism, at its source. Listing a definition in ``__all__`` says
    what ``from pkg.gc import *`` binds; it does not reference the definition,
    any more than a module references itself by existing."""

    walk = _walk(_GC_TREE["pkg/gc.py"], module_name="pkg.gc")
    exported = {"pkg.gc:CacheJob", "pkg.gc:run_gc", "pkg.gc:wired"}

    # The binding fact survives, and it follows the language rule exactly.
    assert exported <= set(walk.star_import_bound_qualnames)
    assert "pkg.gc:_orphan" not in walk.star_import_bound_qualnames
    # Nothing in this module references any of its own definitions: the only
    # call is ``job.collect()`` through a parameter, which names no qualname.
    assert exported.isdisjoint(walk.referenced_qualnames)
    # The declaration itself is a fact of its own, keyed by the declaring
    # module: what the exposure owner reads, never the evaluator.
    assert walk.declared_exports == frozenset(exported)


# ---------------------------------------------------------------------------
# The wire: what a user reads, under each world contract.
# ---------------------------------------------------------------------------


def test_a_symbol_held_only_by_its_all_and_its_tests_is_dead_under_the_closed_world(
    tmp_path: Path,
) -> None:
    """Defects A and B on the wire. Under the closed world the unified GC point
    is nameable: dead, with the test-only consumer class spelled out, and a
    class is named exactly as a function is."""

    family = dead_code_family(
        tmp_path, _GC_TREE, "gc-closed", scope_id=_SCOPE_ID, cli_args=_CLOSED
    )
    items = _dead_items_by_qualname(family)

    assert dead_qualnames(family) == {
        "pkg.gc:CacheJob",
        "pkg.gc:run_gc",
        "pkg.gc:_orphan",
    }
    assert unresolved_by_qualname(family) == {}
    assert {
        key: items["pkg.gc:run_gc"][key]
        for key in ("kind", "reason", "confidence", "test_reference_sources")
    } == {
        "kind": "function",
        "reason": "test_only_reference",
        "confidence": "high",
        "test_reference_sources": ["tests.test_gc:test_dispatch"],
    }
    assert {key: items["pkg.gc:CacheJob"][key] for key in ("kind", "reason")} == {
        "kind": "class",
        "reason": "test_only_reference",
    }
    assert items["pkg.gc:_orphan"]["reason"] == "unreferenced"
    summary = family["summary"]
    assert isinstance(summary, dict)
    assert (summary["total"], summary["world_contract"]) == (3, "closed")


def test_the_same_symbols_are_unresolved_not_dead_under_the_open_world(
    tmp_path: Path,
) -> None:
    """The other half of the headline: ``pkg.gc`` is a public door, so the open
    world must not call these dead - and must not stay silent either. The B
    row of the ruling's fixture, for a function and for a class."""

    family = dead_code_family(tmp_path, _GC_TREE, "gc-open", scope_id=_SCOPE_ID)
    unresolved = unresolved_by_qualname(family)

    assert dead_qualnames(family) == {"pkg.gc:_orphan"}
    assert set(unresolved) == {"pkg.gc:CacheJob", "pkg.gc:run_gc"}
    assert {
        qualname: (row["kind"], row["reason"], row["witness"], row["world_contract"])
        for qualname, row in unresolved.items()
    } == {
        "pkg.gc:CacheJob": (
            "class",
            "externally_reachable",
            "public_module:pkg.gc",
            "open",
        ),
        "pkg.gc:run_gc": (
            "function",
            "externally_reachable",
            "public_module:pkg.gc",
            "open",
        ),
    }


def test_a_package_facade_reexport_is_exposure_not_use(tmp_path: Path) -> None:
    """The re-export chain, both worlds. Importing ``Client`` into the package
    namespace and listing it in ``__all__`` puts it on a public path; it does
    not use it. Open: B rows through the package witness. Closed: dead."""

    open_family = dead_code_family(
        tmp_path, _FACADE_TREE, "facade-open", scope_id=_SCOPE_ID
    )
    closed_family = dead_code_family(
        tmp_path, _FACADE_TREE, "facade-closed", scope_id=_SCOPE_ID, cli_args=_CLOSED
    )

    assert dead_qualnames(open_family) == frozenset()
    assert {
        qualname: row["witness"]
        for qualname, row in unresolved_by_qualname(open_family).items()
    } == {
        "pkg._impl:Client": "package_reexport:pkg",
        "pkg._impl:Client.post": "package_reexport:pkg",
    }
    assert dead_qualnames(closed_family) == {
        "pkg._impl:Client",
        "pkg._impl:Client.post",
    }
    assert unresolved_by_qualname(closed_family) == {}


def test_an_all_entry_in_a_private_module_exports_to_nobody(tmp_path: Path) -> None:
    """The 30 of the 104 that are dead under ANY world: a private module's
    ``__all__`` binds names for a wildcard nobody writes. Neither world may
    read the declaration as a consumer."""

    for name, cli_args in (("private-open", ()), ("private-closed", _CLOSED)):
        family = dead_code_family(
            tmp_path, _PRIVATE_TREE, name, scope_id=_SCOPE_ID, cli_args=cli_args
        )
        assert dead_qualnames(family) == {"pkg._store:helper"}, name
        assert _dead_items_by_qualname(family)["pkg._store:helper"]["reason"] == (
            "unreferenced"
        ), name
        assert unresolved_by_qualname(family) == {}, name


def test_a_public_flat_module_all_is_a_public_path_for_its_import(
    tmp_path: Path,
) -> None:
    """The construction that decides the full form. Open: the class and its
    public method are unresolved through the declaration - ``pkg.api``
    documents the import as its API - and nothing is dead. Closed: dead, both,
    because nothing inside the tree uses them and the world says nobody
    outside does either."""

    open_family = dead_code_family(
        tmp_path, _FLAT_MODULE_TREE, "flat-open", scope_id=_SCOPE_ID
    )
    closed_family = dead_code_family(
        tmp_path, _FLAT_MODULE_TREE, "flat-closed", scope_id=_SCOPE_ID, cli_args=_CLOSED
    )

    assert dead_qualnames(open_family) == frozenset()
    assert {
        qualname: row["witness"]
        for qualname, row in unresolved_by_qualname(open_family).items()
    } == {
        "pkg._impl:Widget": "declared_reexport:pkg.api",
        "pkg._impl:Widget.render": "declared_reexport:pkg.api",
    }
    assert dead_qualnames(closed_family) == {
        "pkg._impl:Widget",
        "pkg._impl:Widget.render",
    }
    assert unresolved_by_qualname(closed_family) == {}


def test_an_undeclared_flat_module_import_is_implementation_detail(
    tmp_path: Path,
) -> None:
    """The opposite boundary, under the OPEN world: without the declaration
    the same import puts nothing on a public path (PEP 8), so the open world
    calls the class dead - and must, or the declaration above would be doing
    no work at all."""

    family = dead_code_family(
        tmp_path, _FLAT_MODULE_UNDECLARED_TREE, "flat-undeclared", scope_id=_SCOPE_ID
    )

    assert dead_qualnames(family) == {"pkg._impl:Widget", "pkg._impl:Widget.render"}
    assert unresolved_by_qualname(family) == {}


def test_the_declaration_survives_a_warm_cache(tmp_path: Path) -> None:
    """The declaration rides the dependent cache lane (``dx``) and the owner
    reads only wired facts, so a warm run utters exactly the cold lanes."""

    cold = dead_code_family(
        tmp_path, _FLAT_MODULE_TREE, "flat-warm", scope_id=_SCOPE_ID
    )
    warm = dead_code_family(
        tmp_path,
        _FLAT_MODULE_TREE,
        "flat-warm",
        scope_id=_SCOPE_ID,
        expect_warm_cache=True,
    )

    assert unresolved_by_qualname(cold)["pkg._impl:Widget"]["witness"] == (
        "declared_reexport:pkg.api"
    )
    assert (dead_qualnames(warm), unresolved_by_qualname(warm)) == (
        dead_qualnames(cold),
        unresolved_by_qualname(cold),
    )


def _api_surface_qualnames(payload: dict[str, object]) -> frozenset[str]:
    metrics = payload["metrics"]
    assert isinstance(metrics, dict)
    families = metrics["families"]
    assert isinstance(families, dict)
    family = families["api_surface"]
    assert isinstance(family, dict)
    summary = family["summary"]
    assert isinstance(summary, dict)
    assert summary["enabled"] is True
    items = family["items"]
    assert isinstance(items, list)
    return frozenset(str(item["qualname"]) for item in items)


def test_a_declared_flat_module_reexport_is_api_surface(tmp_path: Path) -> None:
    """The api lane reads the same exposure owner through its own door, so
    the same declaration must reach it: ``pkg.api`` lists an import it
    binds, and the class behind it is API - a binding path from a public
    namespace exists. Without the declaration the same symbol has no path
    and is not API. A pipeline that handed the declaration to the dead-code
    owner alone would leave this gate confidently silent."""

    declared = analysis_report(
        tmp_path,
        _FLAT_API_TREE,
        "flat-api",
        scope_id=_SCOPE_ID,
        cli_args=("--api-surface",),
    )
    undeclared = analysis_report(
        tmp_path,
        _FLAT_API_UNDECLARED_TREE,
        "flat-api-undeclared",
        scope_id=_SCOPE_ID,
        cli_args=("--api-surface",),
    )

    assert {"pkg._impl:Widget", "pkg._impl:Widget.render"} <= _api_surface_qualnames(
        declared
    )
    assert _api_surface_qualnames(undeclared).isdisjoint(
        {"pkg._impl:Widget", "pkg._impl:Widget.render"}
    )


def test_a_flat_module_getattr_serves_its_declared_name_as_unresolved(
    tmp_path: Path,
) -> None:
    """The sibling shape the old ``__all__`` arm covered through the house
    ``_EXPORTS`` convention, stated generally: ``pkg.api`` declares ``Widget``
    and a module-level ``__getattr__`` serves it. Open: unresolved through
    the hook, never dead. Closed: dead."""

    open_family = dead_code_family(
        tmp_path, _LAZY_MODULE_TREE, "lazy-open", scope_id=_SCOPE_ID
    )
    closed_family = dead_code_family(
        tmp_path, _LAZY_MODULE_TREE, "lazy-closed", scope_id=_SCOPE_ID, cli_args=_CLOSED
    )

    assert dead_qualnames(open_family) == frozenset()
    assert {
        qualname: row["witness"]
        for qualname, row in unresolved_by_qualname(open_family).items()
    } == {
        "pkg._impl:Widget": "module_getattr:pkg.api",
        "pkg._impl:Widget.render": "module_getattr:pkg.api",
    }
    assert dead_qualnames(closed_family) == {
        "pkg._impl:Widget",
        "pkg._impl:Widget.render",
    }


def test_a_flat_module_getattr_with_no_declaration_serves_nothing_nameable(
    tmp_path: Path,
) -> None:
    """The boundary of the served set: the declaration is what bounds it. A
    hook with no ``__all__`` may serve anything and the analysis can name
    nothing, so the origin reads on its own evidence - dead - exactly as it
    did before the declaration existed on the wire. Widening this (a served
    set inferred from what the hook loads) is a separate decision."""

    family = dead_code_family(
        tmp_path, _LAZY_MODULE_UNDECLARED_TREE, "lazy-undeclared", scope_id=_SCOPE_ID
    )

    assert dead_qualnames(family) == {"pkg._impl:Widget", "pkg._impl:Widget.render"}
    assert unresolved_by_qualname(family) == {}


# ---------------------------------------------------------------------------
# The seeds: what DOES hold a symbol live under the closed world, and the
# mutation that proves each rule notices a consumer appearing or vanishing.
# ---------------------------------------------------------------------------


def test_a_consumer_outside_the_package_but_inside_the_tree_is_internal_use(
    tmp_path: Path,
) -> None:
    """A plugin hook under ``plugins/`` is production code of this repository:
    its import edge is internal use, so a new consumer is noticed by the walk
    itself - no list of names to keep current. Remove the consumer and the
    symbol is dead; that is the mutation, run as data."""

    with_consumer = dead_code_family(
        tmp_path, _CONSUMER_TREE, "consumer", scope_id=_SCOPE_ID, cli_args=_CLOSED
    )
    without_consumer = dead_code_family(
        tmp_path,
        {
            name: source
            for name, source in _CONSUMER_TREE.items()
            if name != "plugins/hook.py"
        },
        "no-consumer",
        scope_id=_SCOPE_ID,
        cli_args=_CLOSED,
    )

    assert "pkg.gate:evaluate" not in dead_qualnames(with_consumer)
    assert dead_qualnames(without_consumer) == {"pkg.gate:evaluate"}


def test_a_packaging_entry_point_is_a_root_and_its_removal_is_noticed(
    tmp_path: Path,
) -> None:
    """The process boundary a distribution declares: a console script is an
    external root by rule (``codeclone.core.entrypoints``), read from the
    packaging metadata, never from a name list. Drop the script and ``main``
    is dead under the closed world."""

    declared = dead_code_family(
        tmp_path,
        _ENTRY_POINT_TREE,
        "entry-point",
        scope_id=_SCOPE_ID,
        cli_args=_CLOSED,
        pyproject_lines=_ENTRY_POINT_PYPROJECT,
    )
    undeclared = dead_code_family(
        tmp_path,
        _ENTRY_POINT_TREE,
        "no-entry-point",
        scope_id=_SCOPE_ID,
        cli_args=_CLOSED,
    )

    assert "pkg.cli:main" not in dead_qualnames(declared)
    assert dead_qualnames(undeclared) == {"pkg.cli:main"}


# ---------------------------------------------------------------------------
# Determinism: the verdict is a function of the facts, not of their order.
# ---------------------------------------------------------------------------


def _candidate(
    qualname: str, *, kind: str, star_import_bound: bool = False
) -> DeadCandidate:
    module, _, local = qualname.partition(":")
    return DeadCandidate(
        qualname=qualname,
        local_name=local.rpartition(".")[2],
        filepath=f"{module.replace('.', '/')}.py",
        start_line=1,
        end_line=2,
        kind=kind,  # type: ignore[arg-type]
        star_import_bound=star_import_bound,
    )


def _dep(source: str, target: str, *names: str) -> ModuleDep:
    return ModuleDep(
        source=source,
        target=target,
        import_type="from_import",
        line=1,
        resolution="analyzed",
        requested_names=names,
    )


def _class(qualname: str, *bases: str) -> ClassMetrics:
    return ClassMetrics(
        qualname=qualname,
        filepath=f"{qualname.partition(':')[0].replace('.', '/')}.py",
        start_line=1,
        end_line=9,
        cbo=0,
        lcom4=1,
        method_count=1,
        instance_var_count=0,
        risk_coupling="low",
        risk_cohesion="low",
        base_names=tuple(sorted(bases)),
    )


_ORDER_CANDIDATES = (
    _candidate("pkg._impl:Client", kind="class"),
    _candidate("pkg._impl:Client.post", kind="method"),
    _candidate("pkg._impl:Client._render", kind="method"),
    _candidate("pkg._impl:_helper", kind="function"),
    _candidate("pkg.service:build", kind="function"),
    _candidate("pkg.service:_local", kind="function"),
    _candidate("pkg._store:helper", kind="function", star_import_bound=True),
    _candidate("pkg._store:Hidden", kind="class"),
    _candidate("pkg._store:Hidden.run", kind="method"),
    _candidate("pkg.api:Facade", kind="class"),
)
_ORDER_DEPS = (
    _dep("pkg", "pkg._impl", "Client"),
    _dep("pkg.service", "pkg._impl", "Client"),
    _dep("pkg.api", "pkg._store", "*"),
    _dep("pkg.api", "pkg._impl", "Client"),
)
_ORDER_CLASSES = (
    _class("pkg._impl:Client"),
    _class("pkg._store:Hidden", "Client"),
    _class("pkg.api:Facade", "Hidden"),
)
_ORDER_TEST_SOURCES = {
    "pkg._impl:Client.post": ("tests.test_b:test_post", "tests.test_a:test_post"),
    "pkg._impl:_helper": ("tests.test_a:test_helper",),
    "pkg._store:Hidden.run": ("tests.test_c:test_run",),
}


def _verdict(
    seed: int | None,
) -> tuple[tuple[ExternalReachability, ...], dict[str, LivenessClassification]]:
    candidates, deps, classes = (
        list(_ORDER_CANDIDATES),
        list(_ORDER_DEPS),
        list(_ORDER_CLASSES),
    )
    sources = list(_ORDER_TEST_SOURCES.items())
    if seed is not None:
        rng = random.Random(seed)
        for sequence in (candidates, deps, classes, sources):
            rng.shuffle(sequence)
    rows = collect_external_reachability(
        definitions=tuple(candidates),
        module_deps=tuple(deps),
        class_metrics=tuple(classes),
        package_modules=frozenset({"pkg"}),
    )
    return rows, {
        world: classify_liveness(
            definitions=tuple(candidates),
            referenced_names=frozenset({"build"}),
            referenced_qualnames=frozenset({"pkg._impl:Client"}),
            test_reference_sources=dict(sources),
            class_metrics=tuple(classes),
            external_reachability=rows,
            world_contract=world,
        )
        for world in ("open", "closed")
    }


def test_the_verdict_is_independent_of_input_order() -> None:
    """Candidates, dependency edges, class rows and test-reference sources
    arrive in whatever order the workers finish; the reachability rows, the
    dead lane and the unresolved lane must be byte-identical for every
    permutation, and must not be trivially so."""

    reference_rows, reference = _verdict(None)

    # The population is not degenerate: all three reachability states and
    # every evaluator lane are exercised (``Hidden``'s base binds nowhere, so
    # its method is the unresolved row).
    assert {row.state for row in reference_rows} == {
        "reachable",
        "not_reachable",
        "unresolved",
    }
    assert reference["closed"].dead_items and reference["open"].unresolved_reachability
    assert reference["open"].dead_items
    assert {item.reason for item in reference["open"].unresolved_reachability} == {
        "externally_reachable",
        "reachability_unresolved",
    }
    assert any(
        item.reason == "test_only_reference" for item in reference["closed"].dead_items
    )

    for seed in range(12):
        rows, verdicts = _verdict(seed)
        assert rows == reference_rows, seed
        assert verdicts == reference, seed
