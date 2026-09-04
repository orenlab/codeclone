# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""External reachability: the evidence layer under the dead-code evaluator.

RULING 2026-09-01 (external reachability) fixes the shape of these pins: the
causal statement is ``source construct -> ExternalReachability(symbol) =
reachable``, asserted on the EVIDENCE and never on the final ``dead``/``live``
verdict, because the world contract can move the verdict without touching the
defect. The evaluator is pinned separately, in both directions, below.

Every population here is built from the facts that ride the cache wire -
candidates with their star-binding, dependency edges with the names they
request, class metrics with their base spellings - because the owner under
test reads nothing else. A rule that needed a walk-time fact would be a rule a
warm run could not apply.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import orjson

from codeclone.metrics.dead_code import classify_liveness
from codeclone.models import ClassMetrics, DeadCandidate, ModuleDep
from tests._ast_metrics_helpers import build_test_module_registry, extract_file_metrics

if TYPE_CHECKING:
    from codeclone.models import ExternalReachability


def _row(qualname: str, state: str, witness: str) -> ExternalReachability:
    # Imported here rather than at module scope so that a build without the
    # owner reports these pins as RED runs, not as a collection error that
    # pytest counts as nothing at all.
    from codeclone.models import ExternalReachability

    return ExternalReachability(qualname=qualname, state=state, witness=witness)  # type: ignore[arg-type]


def _candidate(
    qualname: str,
    *,
    kind: str,
    star_import_bound: bool = False,
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
        import_type="import" if not names else "from_import",
        line=1,
        resolution="analyzed",
        requested_names=names,
    )


def _class(
    qualname: str,
    *bases: str,
    external_base: bool = False,
) -> ClassMetrics:
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
        has_unresolved_external_base=external_base,
    )


def _by_qualname(
    rows: tuple[ExternalReachability, ...],
) -> dict[str, ExternalReachability]:
    return {row.qualname: row for row in rows}


def _assert_rows(
    rows: dict[str, ExternalReachability],
    expected: dict[str, tuple[str, str | None]],
) -> None:
    """Pin the state and, when given, the witness of each named row, as data."""

    for qualname, (state, witness) in expected.items():
        assert rows[qualname].state == state, qualname
        if witness is not None:
            assert rows[qualname].witness == witness, qualname


def _reachability(
    *,
    candidates: tuple[DeadCandidate, ...],
    module_deps: tuple[ModuleDep, ...] = (),
    class_metrics: tuple[ClassMetrics, ...] = (),
    package_modules: frozenset[str] = frozenset(),
    declared_exports: frozenset[str] = frozenset(),
) -> dict[str, ExternalReachability]:
    from codeclone.metrics.external_reachability import collect_external_reachability

    rows = collect_external_reachability(
        definitions=candidates,
        module_deps=module_deps,
        class_metrics=class_metrics,
        package_modules=package_modules,
        declared_exports=declared_exports,
    )
    # One row per candidate, in one deterministic order: a consumer that
    # zips rows against candidates must never see a gap or a shuffle.
    assert [row.qualname for row in rows] == sorted(
        candidate.qualname for candidate in candidates
    )
    return _by_qualname(rows)


# ---------------------------------------------------------------------------
# E1: a public name in a public module is importable by construction.
# ---------------------------------------------------------------------------


def test_a_public_member_of_a_public_module_is_reachable() -> None:
    """The tornado shape: no ``__all__``, no re-export, documented public API."""

    rows = _reachability(
        candidates=(
            _candidate("tornado.web:RequestHandler", kind="class"),
            _candidate("tornado.web:RequestHandler.get_query_argument", kind="method"),
            _candidate("tornado.web:RequestHandler._private", kind="method"),
            _candidate("tornado.web:_hidden", kind="function"),
            _candidate("tornado._impl:Helper", kind="class"),
            _candidate("tornado._impl:Helper.run", kind="method"),
        ),
    )

    _assert_rows(
        rows,
        {
            "tornado.web:RequestHandler": ("reachable", "public_module:tornado.web"),
            "tornado.web:RequestHandler.get_query_argument": (
                "reachable",
                "public_module:tornado.web",
            ),
            # The underscore convention is the one privacy statement Python has.
            "tornado.web:RequestHandler._private": ("not_reachable", ""),
            "tornado.web:_hidden": ("not_reachable", ""),
            # A private module nothing re-exports is not a public import path.
            "tornado._impl:Helper": ("not_reachable", ""),
            "tornado._impl:Helper.run": ("not_reachable", ""),
        },
    )


def test_a_nested_class_needs_every_segment_public() -> None:
    rows = _reachability(
        candidates=(
            _candidate("pkg.mod:Outer.Inner", kind="class"),
            _candidate("pkg.mod:Outer.Inner.run", kind="method"),
            _candidate("pkg.mod:_Outer.Inner", kind="class"),
            _candidate("pkg.mod:_Outer.Inner.run", kind="method"),
        ),
        class_metrics=(
            _class("pkg.mod:Outer.Inner"),
            _class("pkg.mod:_Outer.Inner"),
        ),
    )

    assert rows["pkg.mod:Outer.Inner"].state == "reachable"
    assert rows["pkg.mod:Outer.Inner.run"].state == "reachable"
    assert rows["pkg.mod:_Outer.Inner"].state == "not_reachable"
    assert rows["pkg.mod:_Outer.Inner.run"].state == "not_reachable"


def test_a_nested_class_rides_its_reexported_root() -> None:
    """``pkg/__init__.py`` re-exports ``Outer`` from a PRIVATE module: ``Outer.Inner``
    and its public method reach the world through that root, not through the
    module. Only a private module keeps this rule load-bearing - in a public
    module the direct rule already exposes every segment, which is how a
    mutant that dropped the rule survived the public-module pin above.
    """

    rows = _reachability(
        candidates=(
            _candidate("pkg._impl:Outer", kind="class"),
            _candidate("pkg._impl:Outer.Inner", kind="class"),
            _candidate("pkg._impl:Outer.Inner.run", kind="method"),
            _candidate("pkg._impl:Orphan.Inner", kind="class"),
            _candidate("pkg._impl:Orphan.Inner.run", kind="method"),
        ),
        module_deps=(_dep("pkg", "pkg._impl", "Outer"),),
        class_metrics=(
            _class("pkg._impl:Outer"),
            _class("pkg._impl:Outer.Inner"),
            _class("pkg._impl:Orphan"),
            _class("pkg._impl:Orphan.Inner"),
        ),
        package_modules=frozenset({"pkg"}),
    )

    assert rows["pkg._impl:Outer.Inner"].state == "reachable"
    assert rows["pkg._impl:Outer.Inner"].witness == "package_reexport:pkg"
    assert rows["pkg._impl:Outer.Inner.run"].state == "reachable"
    # A nested class whose root nothing re-exports has no public path.
    assert rows["pkg._impl:Orphan.Inner"].state == "not_reachable"
    assert rows["pkg._impl:Orphan.Inner.run"].state == "not_reachable"


# ---------------------------------------------------------------------------
# E2: a public package ``__init__`` re-exports what it imports by name.
# ---------------------------------------------------------------------------


def test_a_package_init_exposes_what_it_imports_from_a_private_module() -> None:
    """The httpx shape: ``httpx/__init__.py`` does ``from ._client import Client``."""

    rows = _reachability(
        candidates=(
            _candidate("httpx._client:Client", kind="class"),
            _candidate("httpx._client:Client.post", kind="method"),
            _candidate("httpx._client:Client._render", kind="method"),
            _candidate("httpx._client:Orphan", kind="class"),
            _candidate("httpx._client:Orphan.never_called", kind="method"),
        ),
        module_deps=(_dep("httpx", "httpx._client", "Client"),),
        package_modules=frozenset({"httpx"}),
    )

    _assert_rows(
        rows,
        {
            "httpx._client:Client": ("reachable", "package_reexport:httpx"),
            "httpx._client:Client.post": ("reachable", "package_reexport:httpx"),
            "httpx._client:Client._render": ("not_reachable", ""),
            # The re-export names ONE symbol; its siblings stay behind the
            # underscore.
            "httpx._client:Orphan": ("not_reachable", ""),
            "httpx._client:Orphan.never_called": ("not_reachable", ""),
        },
    )


def test_a_named_reexport_chain_is_followed_hop_by_hop() -> None:
    rows = _reachability(
        candidates=(
            _candidate("pkg._impl:Client", kind="class"),
            _candidate("pkg._impl:Client.post", kind="method"),
        ),
        module_deps=(
            _dep("pkg", "pkg.sub", "Client"),
            _dep("pkg.sub", "pkg._impl", "Client"),
        ),
        package_modules=frozenset({"pkg", "pkg.sub"}),
    )

    assert rows["pkg._impl:Client.post"].state == "reachable"
    assert rows["pkg._impl:Client.post"].witness.startswith("package_reexport:")


def test_a_plain_public_module_does_not_reexport_its_named_imports() -> None:
    """PEP 8: an imported name is an implementation detail outside ``__init__``
    unless the module documents it as API - and with no ``__all__`` it does
    not. The boundary of E2' below: the same import, undeclared."""

    rows = _reachability(
        candidates=(
            _candidate("pkg._impl:Client", kind="class"),
            _candidate("pkg._impl:Client.post", kind="method"),
        ),
        module_deps=(_dep("pkg.util", "pkg._impl", "Client"),),
        package_modules=frozenset({"pkg"}),
    )

    assert rows["pkg._impl:Client"].state == "not_reachable"
    assert rows["pkg._impl:Client.post"].state == "not_reachable"


# ---------------------------------------------------------------------------
# E2': a plain module's import is a re-export where its own ``__all__`` says
# so (liveness policy v4). PEP 8 calls an imported name API exactly where the
# module documents it as such, and ``__all__`` is that documentation.
# ---------------------------------------------------------------------------


def test_a_plain_public_module_reexports_the_named_import_its_all_declares() -> None:
    """The maintainer's construction (2026-09-03), five lines: a public flat
    module imports a private module's class and lists it in ``__all__``.
    ``pkg.util.Client`` is a documented public path, so the class and its
    public method are reachable through the declaration; the undeclared
    sibling import stays implementation detail."""

    rows = _reachability(
        candidates=(
            _candidate("pkg._impl:Client", kind="class"),
            _candidate("pkg._impl:Client.post", kind="method"),
            _candidate("pkg._impl:Client._render", kind="method"),
            _candidate("pkg._impl:Orphan", kind="class"),
            _candidate("pkg._impl:Orphan.never_called", kind="method"),
        ),
        module_deps=(_dep("pkg.util", "pkg._impl", "Client", "Orphan"),),
        package_modules=frozenset({"pkg"}),
        declared_exports=frozenset({"pkg.util:Client"}),
    )

    _assert_rows(
        rows,
        {
            "pkg._impl:Client": ("reachable", "declared_reexport:pkg.util"),
            "pkg._impl:Client.post": ("reachable", "declared_reexport:pkg.util"),
            "pkg._impl:Client._render": ("not_reachable", ""),
            # Imported and not declared: implementation detail (PEP 8).
            "pkg._impl:Orphan": ("not_reachable", ""),
            "pkg._impl:Orphan.never_called": ("not_reachable", ""),
        },
    )


def test_a_declaration_reexports_exactly_the_import_it_names() -> None:
    """The opposite error, three ways: a declared name that is not the import
    binds nothing; a private plain module's declaration is a declaration to
    nobody; and a package re-exports what it imports with or without one,
    through the package witness - E2 stands."""

    candidates = (
        _candidate("pkg._impl:Client", kind="class"),
        _candidate("pkg._impl:Client.post", kind="method"),
    )

    rows = _reachability(
        candidates=candidates,
        module_deps=(_dep("pkg.util", "pkg._impl", "Client"),),
        package_modules=frozenset({"pkg"}),
        declared_exports=frozenset({"pkg.util:Other"}),
    )
    assert rows["pkg._impl:Client"].state == "not_reachable"
    assert rows["pkg._impl:Client.post"].state == "not_reachable"

    rows = _reachability(
        candidates=candidates,
        module_deps=(_dep("pkg._util", "pkg._impl", "Client"),),
        package_modules=frozenset({"pkg"}),
        declared_exports=frozenset({"pkg._util:Client"}),
    )
    assert rows["pkg._impl:Client"].state == "not_reachable"
    assert rows["pkg._impl:Client.post"].state == "not_reachable"

    for declared in (frozenset(), frozenset({"pkg:Client"})):
        rows = _reachability(
            candidates=candidates,
            module_deps=(_dep("pkg", "pkg._impl", "Client"),),
            package_modules=frozenset({"pkg"}),
            declared_exports=declared,
        )
        assert rows["pkg._impl:Client.post"] == _row(
            "pkg._impl:Client.post", "reachable", "package_reexport:pkg"
        )


# ---------------------------------------------------------------------------
# E4 and the dynamic hop: a plain module's ``__getattr__`` binds unreadably.
# ---------------------------------------------------------------------------


def test_a_plain_module_getattr_serves_its_declared_names_as_unresolved() -> None:
    """``pkg.api`` declares ``Widget`` and binds it neither by definition, by
    import nor by wildcard; its module-level ``__getattr__`` is what serves
    the name. Which definition it serves cannot be read, so every top-level
    definition of that name is unresolved through that construct, a served
    class carries its public methods, and a name nothing declares is not
    served at all."""

    rows = _reachability(
        candidates=(
            _candidate("pkg.api:__getattr__", kind="function"),
            _candidate("pkg._impl:Widget", kind="class"),
            _candidate("pkg._impl:Widget.render", kind="method"),
            _candidate("pkg._other:Widget", kind="class"),
            _candidate("pkg._impl:Gadget", kind="class"),
        ),
        module_deps=(_dep("pkg.api", "pkg._impl"),),
        package_modules=frozenset({"pkg"}),
        declared_exports=frozenset({"pkg.api:Widget"}),
    )

    _assert_rows(
        rows,
        {
            "pkg._impl:Widget": ("unresolved", "module_getattr:pkg.api"),
            "pkg._impl:Widget.render": ("unresolved", "module_getattr:pkg.api"),
            "pkg._other:Widget": ("unresolved", "module_getattr:pkg.api"),
            "pkg._impl:Gadget": ("not_reachable", ""),
        },
    )


def test_a_declared_name_is_served_only_by_a_reached_dynamic_module() -> None:
    """Both boundaries of E4. Without the ``__getattr__`` a declared name that
    nothing binds is a declaration of nothing; with it, in a private module
    nothing reaches, the served names travel to nobody."""

    candidates = (
        _candidate("pkg._impl:Widget", kind="class"),
        _candidate("pkg._impl:Widget.render", kind="method"),
    )

    rows = _reachability(
        candidates=candidates,
        module_deps=(_dep("pkg.api", "pkg._impl"),),
        package_modules=frozenset({"pkg"}),
        declared_exports=frozenset({"pkg.api:Widget"}),
    )
    assert rows["pkg._impl:Widget"].state == "not_reachable"
    assert rows["pkg._impl:Widget.render"].state == "not_reachable"

    rows = _reachability(
        candidates=(_candidate("pkg._lazy:__getattr__", kind="function"), *candidates),
        module_deps=(_dep("pkg._lazy", "pkg._impl"),),
        package_modules=frozenset({"pkg"}),
        declared_exports=frozenset({"pkg._lazy:Widget"}),
    )
    assert rows["pkg._impl:Widget"].state == "not_reachable"
    assert rows["pkg._impl:Widget.render"].state == "not_reachable"


def test_a_name_imported_through_a_plain_module_getattr_is_unresolved() -> None:
    """The dynamic hop of the binding walk: the package imports ``Widget`` from
    ``pkg._lazy`` by name, and ``_lazy`` binds it only through its
    ``__getattr__``. ``pkg.Widget`` exists at runtime and its definition
    cannot be read, so every top-level ``Widget`` is unresolved through the
    construct - never dead. Without the ``__getattr__`` the import binds
    nothing static and exposes nothing."""

    candidates = (
        _candidate("pkg._impl:Widget", kind="class"),
        _candidate("pkg._impl:Widget.render", kind="method"),
    )
    deps = (_dep("pkg", "pkg._lazy", "Widget"),)

    rows = _reachability(
        candidates=(_candidate("pkg._lazy:__getattr__", kind="function"), *candidates),
        module_deps=deps,
        package_modules=frozenset({"pkg"}),
    )
    _assert_rows(
        rows,
        {
            "pkg._impl:Widget": ("unresolved", "module_getattr:pkg._lazy"),
            "pkg._impl:Widget.render": ("unresolved", "module_getattr:pkg._lazy"),
        },
    )

    rows = _reachability(
        candidates=candidates,
        module_deps=deps,
        package_modules=frozenset({"pkg"}),
    )
    assert rows["pkg._impl:Widget"].state == "not_reachable"
    assert rows["pkg._impl:Widget.render"].state == "not_reachable"


# ---------------------------------------------------------------------------
# E3: ``from x import *`` binds what the target's ``__all__`` rule says.
# ---------------------------------------------------------------------------


def _star_population(*, orphan_bound: bool) -> tuple[DeadCandidate, ...]:
    return (
        _candidate("pkg._impl:Client", kind="class", star_import_bound=True),
        _candidate("pkg._impl:Client.post", kind="method"),
        _candidate("pkg._impl:Orphan", kind="class", star_import_bound=orphan_bound),
        _candidate("pkg._impl:Orphan.never_called", kind="method"),
        _candidate(
            "pkg._impl:orphan_function",
            kind="function",
            star_import_bound=orphan_bound,
        ),
        _candidate("pkg._impl:_hidden", kind="function"),
    )


def test_a_wildcard_with_no_all_binds_every_public_name() -> None:
    """P2, the surviving wildcard defect: ``from ._impl import *`` and no ``__all__``.

    ``pkg.Client``, ``pkg.Orphan`` and ``pkg.orphan_function`` all exist at
    runtime, so every one of them is a public import path - including the
    two the previous engine called dead at high confidence.
    """

    rows = _reachability(
        candidates=_star_population(orphan_bound=True),
        module_deps=(_dep("pkg", "pkg._impl", "*"),),
        package_modules=frozenset({"pkg"}),
    )

    for qualname in (
        "pkg._impl:Client",
        "pkg._impl:Client.post",
        "pkg._impl:Orphan",
        "pkg._impl:Orphan.never_called",
        "pkg._impl:orphan_function",
    ):
        assert rows[qualname].state == "reachable", qualname
        assert rows[qualname].witness == "star_reexport:pkg", qualname
    assert rows["pkg._impl:_hidden"].state == "not_reachable"


def test_a_wildcard_does_not_bind_what_the_target_all_omits() -> None:
    """The binding fact is the target's, and it is read from the candidate."""

    rows = _reachability(
        candidates=_star_population(orphan_bound=False),
        module_deps=(_dep("pkg", "pkg._impl", "*"),),
        package_modules=frozenset({"pkg"}),
    )

    assert rows["pkg._impl:Client.post"].state == "reachable"
    assert rows["pkg._impl:Orphan"].state == "not_reachable"
    assert rows["pkg._impl:Orphan.never_called"].state == "not_reachable"
    assert rows["pkg._impl:orphan_function"].state == "not_reachable"


def test_a_wildcard_chain_carries_the_names_a_reached_module_imports() -> None:
    """``pkg`` stars ``_api``; ``_api`` names ``Client`` from ``_impl``.

    ``pkg.Client`` is ``_impl.Client`` by construction. ``_impl`` itself is
    reached by NAME, so what ``_impl`` imports goes no further: the ceiling
    that keeps a named edge from extending the chain.
    """

    rows = _reachability(
        candidates=(
            _candidate("pkg._impl:Client", kind="class", star_import_bound=True),
            _candidate("pkg._impl:Client.post", kind="method"),
            _candidate("pkg._deep:DeepWidget", kind="class", star_import_bound=True),
            _candidate("pkg._deep:DeepWidget.render_deep", kind="method"),
        ),
        module_deps=(
            _dep("pkg", "pkg._api", "*"),
            _dep("pkg._api", "pkg._impl", "Client"),
            _dep("pkg._impl", "pkg._deep", "DeepWidget"),
        ),
        package_modules=frozenset({"pkg"}),
    )

    assert rows["pkg._impl:Client.post"].state == "reachable"
    assert rows["pkg._impl:Client.post"].witness == "star_reexport:pkg._api"
    assert rows["pkg._deep:DeepWidget.render_deep"].state == "not_reachable"


def test_a_wildcard_chain_is_anchored_at_the_public_frontier() -> None:
    """A private module's wildcard exposes nothing until something public
    carries that module outward; a public plain module's wildcard does."""

    candidates = (
        _candidate("pkg._impl:Client", kind="class", star_import_bound=True),
        _candidate("pkg._impl:Client.post", kind="method"),
    )

    unanchored = _reachability(
        candidates=candidates,
        module_deps=(_dep("pkg._api", "pkg._impl", "*"),),
        package_modules=frozenset({"pkg"}),
    )
    assert unanchored["pkg._impl:Client.post"].state == "not_reachable"

    public_plain = _reachability(
        candidates=candidates,
        module_deps=(_dep("pkg.api", "pkg._impl", "*"),),
        package_modules=frozenset({"pkg"}),
    )
    assert public_plain["pkg._impl:Client.post"].state == "reachable"
    assert public_plain["pkg._impl:Client.post"].witness == "star_reexport:pkg.api"


def test_a_mutual_wildcard_cycle_terminates() -> None:
    rows = _reachability(
        candidates=(
            _candidate("pkg._b:CycleWidget", kind="class", star_import_bound=True),
            _candidate("pkg._b:CycleWidget.render_cycle", kind="method"),
        ),
        module_deps=(
            _dep("pkg", "pkg._a", "*"),
            _dep("pkg._a", "pkg._b", "*"),
            _dep("pkg._b", "pkg._a", "*"),
        ),
        package_modules=frozenset({"pkg"}),
    )

    assert rows["pkg._b:CycleWidget.render_cycle"].state == "reachable"


# ---------------------------------------------------------------------------
# R2 / R3: inheritance carries a method across the public boundary.
# ---------------------------------------------------------------------------


def test_an_exposed_subclass_carries_its_private_base_methods() -> None:
    """The vispy shape: ``GlooFunctions(BaseGlooFunctions)`` is public, the base
    is not, and ``GlooFunctions().set_blend_func`` is literally
    ``BaseGlooFunctions.set_blend_func``."""

    rows = _reachability(
        candidates=(
            _candidate("pkg._base:BaseGlooFunctions", kind="class"),
            _candidate("pkg._base:BaseGlooFunctions.set_blend_func", kind="method"),
            _candidate("pkg._base:_Lonely", kind="class"),
            _candidate("pkg._base:_Lonely.helper", kind="method"),
            _candidate("pkg.gloo:GlooFunctions", kind="class"),
        ),
        module_deps=(_dep("pkg.gloo", "pkg._base", "BaseGlooFunctions"),),
        class_metrics=(
            _class("pkg._base:BaseGlooFunctions"),
            _class("pkg._base:_Lonely"),
            _class("pkg.gloo:GlooFunctions", "BaseGlooFunctions"),
        ),
    )

    assert rows["pkg._base:BaseGlooFunctions.set_blend_func"].state == "reachable"
    assert (
        rows["pkg._base:BaseGlooFunctions.set_blend_func"].witness
        == "exposed_subclass:pkg.gloo:GlooFunctions"
    )
    # The class object itself is not on a public path; only its members are
    # carried, and only through the subclass.
    assert rows["pkg._base:BaseGlooFunctions"].state == "not_reachable"
    # A class with no exposed relative gets nothing from the hierarchy rule.
    assert rows["pkg._base:_Lonely.helper"].state == "not_reachable"


def test_an_exposed_ancestor_carries_a_private_subclass_override() -> None:
    """The nltk shape, made private: ``_FeatureGrammar(CFG)`` overrides a
    method of the exported ``CFG``, so a caller holding a ``CFG`` reference
    dispatches into it."""

    rows = _reachability(
        candidates=(
            _candidate("pkg.grammar:CFG", kind="class"),
            _candidate("pkg.grammar:CFG.leftcorner_parents", kind="method"),
            _candidate("pkg._feat:FeatureGrammar", kind="class"),
            _candidate("pkg._feat:FeatureGrammar.leftcorner_parents", kind="method"),
            _candidate("pkg._feat:FeatureGrammar._scratch", kind="method"),
        ),
        module_deps=(_dep("pkg._feat", "pkg.grammar", "CFG"),),
        class_metrics=(
            _class("pkg.grammar:CFG"),
            _class("pkg._feat:FeatureGrammar", "CFG"),
        ),
    )

    assert rows["pkg._feat:FeatureGrammar.leftcorner_parents"].state == "reachable"
    assert (
        rows["pkg._feat:FeatureGrammar.leftcorner_parents"].witness
        == "exposed_ancestor:pkg.grammar:CFG"
    )
    assert rows["pkg._feat:FeatureGrammar._scratch"].state == "not_reachable"
    assert rows["pkg._feat:FeatureGrammar"].state == "not_reachable"


def test_dotted_base_spellings_resolve_through_the_dependency_edges() -> None:
    """``class Other(wrappers.Base)`` after ``from . import wrappers`` and
    ``class Third(w.Base)`` after ``import pkg._w as w``: the walk records the
    first as a from-import of ``wrappers`` and the second as a bare import
    edge with no alias, so the leaf name plus the edge is all there is."""

    rows = _reachability(
        candidates=(
            _candidate("pkg._w:Base", kind="class"),
            _candidate("pkg._w:Base.run", kind="method"),
            _candidate("pkg.context:Other", kind="class"),
            _candidate("pkg.context:Third", kind="class"),
        ),
        module_deps=(
            _dep("pkg.context", "pkg", "_w"),
            _dep("pkg.context", "pkg._w", "_w"),
            _dep("pkg.context", "pkg._w"),
        ),
        class_metrics=(
            _class("pkg._w:Base"),
            _class("pkg.context:Other", "_w.Base"),
            _class("pkg.context:Third", "w.Base"),
        ),
    )

    assert rows["pkg._w:Base.run"].state == "reachable"
    assert rows["pkg._w:Base.run"].witness in {
        "exposed_subclass:pkg.context:Other",
        "exposed_subclass:pkg.context:Third",
    }


# ---------------------------------------------------------------------------
# The third state: the export semantics cannot be resolved statically.
# ---------------------------------------------------------------------------


def test_a_package_getattr_leaves_its_subtree_unresolved() -> None:
    """PEP 562: a public package ``__getattr__`` can serve any name."""

    rows = _reachability(
        candidates=(
            _candidate("pkg:__getattr__", kind="function"),
            _candidate("pkg._impl:Hidden", kind="class"),
            _candidate("pkg._impl:Hidden.method", kind="method"),
            _candidate("pkg._impl:_really_hidden", kind="function"),
            _candidate("other._impl:Elsewhere", kind="class"),
        ),
        package_modules=frozenset({"pkg", "other"}),
    )

    assert rows["pkg._impl:Hidden"].state == "unresolved"
    assert rows["pkg._impl:Hidden"].witness == "module_getattr:pkg"
    assert rows["pkg._impl:Hidden.method"].state == "unresolved"
    # The hook cannot un-privatise an underscore name, and it cannot reach
    # another package.
    assert rows["pkg._impl:_really_hidden"].state == "not_reachable"
    assert rows["other._impl:Elsewhere"].state == "not_reachable"


def test_a_lazy_loader_package_leaves_its_subtree_unresolved() -> None:
    """The mne shape: ``mne/viz/__init__.py`` does ``import lazy_loader as lazy``
    and ``(__getattr__, __dir__, __all__) = lazy.attach_stub(...)``. The public
    path to ``mne.viz.Brain`` lives in a ``.pyi`` stub the walk never reads, so
    the namespace is dynamic by construction - the same abstention as a
    ``def __getattr__``, read from the one edge that IS on the wire.

    Measured 2026-09-02: without this rule ten ``Brain`` methods, documented
    public API, appeared as high-confidence dead findings under the open world.
    """

    rows = _reachability(
        candidates=(
            _candidate("pkg.viz._brain._brain:Brain", kind="class"),
            _candidate("pkg.viz._brain._brain:Brain.add_skull", kind="method"),
            _candidate("pkg.viz._brain._brain:Brain._draw", kind="method"),
            _candidate("pkg.other._impl:Elsewhere", kind="class"),
        ),
        module_deps=(
            _dep("pkg.viz", "lazy_loader"),
            _dep("pkg.viz._brain", "pkg.viz._brain._brain", "Brain"),
        ),
        package_modules=frozenset({"pkg", "pkg.viz", "pkg.viz._brain", "pkg.other"}),
    )

    _assert_rows(
        rows,
        {
            "pkg.viz._brain._brain:Brain": ("unresolved", "lazy_namespace:pkg.viz"),
            "pkg.viz._brain._brain:Brain.add_skull": (
                "unresolved",
                "lazy_namespace:pkg.viz",
            ),
            # Neither the underscore convention nor a sibling package is touched.
            "pkg.viz._brain._brain:Brain._draw": ("not_reachable", ""),
            "pkg.other._impl:Elsewhere": ("not_reachable", ""),
        },
    )


def test_a_base_no_edge_can_bind_leaves_the_methods_unresolved() -> None:
    """``class Weird(Base)`` where ``Base`` is neither defined, imported nor a
    builtin: the hierarchy above this class is unknown, so its members might
    be overrides of anything. ``Exception`` is a builtin and resolves."""

    rows = _reachability(
        candidates=(
            _candidate("pkg._impl:Weird", kind="class"),
            _candidate("pkg._impl:Weird.method", kind="method"),
            _candidate("pkg._impl:MyError", kind="class"),
            _candidate("pkg._impl:MyError.describe", kind="method"),
        ),
        class_metrics=(
            _class("pkg._impl:Weird", "Base"),
            _class("pkg._impl:MyError", "Exception"),
        ),
    )

    assert rows["pkg._impl:Weird.method"].state == "unresolved"
    assert rows["pkg._impl:Weird.method"].witness == "unresolved_base:Base"
    assert rows["pkg._impl:MyError.describe"].state == "not_reachable"


# ---------------------------------------------------------------------------
# The evaluator: reachability x liveness evidence x world contract.
# ---------------------------------------------------------------------------


def _evaluator_population() -> tuple[DeadCandidate, ...]:
    return (
        _candidate("pkg._impl:Client", kind="class"),
        _candidate("pkg._impl:Client.post", kind="method"),
        _candidate("pkg._impl:Client._render", kind="method"),
        _candidate("pkg._impl:Weird.method", kind="method"),
    )


def _evaluator_reachability() -> tuple[ExternalReachability, ...]:
    return (
        _row("pkg._impl:Client", "reachable", "package_reexport:pkg"),
        _row("pkg._impl:Client.post", "reachable", "package_reexport:pkg"),
        _row("pkg._impl:Client._render", "not_reachable", ""),
        _row("pkg._impl:Weird.method", "unresolved", "unresolved_base:Base"),
    )


def test_open_world_turns_reachable_no_evidence_into_unresolved_not_dead() -> None:
    classification = classify_liveness(
        definitions=_evaluator_population(),
        referenced_names=frozenset(),
        referenced_qualnames=frozenset({"pkg._impl:Client"}),
        external_reachability=_evaluator_reachability(),
        world_contract="open",
    )

    dead = {item.qualname for item in classification.dead_items}
    unresolved = {
        item.qualname: item for item in classification.unresolved_reachability
    }
    # B: reachable, no internal evidence, open world -> unresolved record.
    assert "pkg._impl:Client.post" in unresolved
    assert "pkg._impl:Client.post" not in dead
    row = unresolved["pkg._impl:Client.post"]
    assert row.reason == "externally_reachable"
    assert row.reachability == "reachable"
    assert row.witness == "package_reexport:pkg"
    assert row.world_contract == "open"
    assert row.kind == "method"
    # The third reachability state is its own reason code.
    assert unresolved["pkg._impl:Weird.method"].reason == "reachability_unresolved"
    assert unresolved["pkg._impl:Weird.method"].reachability == "unresolved"
    # C: not reachable and unreferenced is dead under any world.
    assert "pkg._impl:Client._render" in dead
    assert "pkg._impl:Client._render" not in unresolved
    # A: internally live is neither, whatever its reachability says.
    assert "pkg._impl:Client" not in dead
    assert "pkg._impl:Client" not in unresolved


def test_closed_world_keeps_the_dead_verdict_for_reachable_symbols() -> None:
    classification = classify_liveness(
        definitions=_evaluator_population(),
        referenced_names=frozenset(),
        referenced_qualnames=frozenset({"pkg._impl:Client"}),
        external_reachability=_evaluator_reachability(),
        world_contract="closed",
    )

    dead = {item.qualname for item in classification.dead_items}
    assert dead == {
        "pkg._impl:Client.post",
        "pkg._impl:Client._render",
        "pkg._impl:Weird.method",
    }
    assert classification.unresolved_reachability == ()


def test_the_unresolved_lane_is_ordered_like_the_dead_lane() -> None:
    classification = classify_liveness(
        definitions=_evaluator_population(),
        referenced_names=frozenset(),
        referenced_qualnames=frozenset(),
        external_reachability=_evaluator_reachability(),
        world_contract="open",
    )
    rows = classification.unresolved_reachability
    assert [row.qualname for row in rows] == sorted(
        (row.qualname for row in rows),
        key=lambda qualname: (
            f"{qualname.partition(':')[0].replace('.', '/')}.py",
            1,
            2,
            qualname,
        ),
    )


def test_an_opaque_base_abstention_outranks_the_reachability_lane() -> None:
    """Rule 3 already abstains; the new lane must not restate that abstention."""

    candidates = (
        _candidate("pkg.api:Service", kind="class"),
        _candidate("pkg.api:Service.render", kind="method"),
    )
    classification = classify_liveness(
        definitions=candidates,
        referenced_names=frozenset(),
        referenced_qualnames=frozenset({"pkg.api:Service"}),
        class_metrics=(_class("pkg.api:Service", "external.Base", external_base=True),),
        external_reachability=(
            _row("pkg.api:Service.render", "reachable", "public_module:pkg.api"),
        ),
        world_contract="open",
    )

    assert [item.qualname for item in classification.unresolved_overrides] == [
        "pkg.api:Service.render"
    ]
    assert classification.unresolved_reachability == ()
    assert classification.dead_items == ()


# ---------------------------------------------------------------------------
# The named export chain, on a synthetic private module and on the real fixture.
# ---------------------------------------------------------------------------


def _fixture_candidate(qualname: str, *, kind: str = "function") -> DeadCandidate:
    return _candidate(qualname, kind=kind)


def test_reachability_follows_the_package_reexport_and_not_a_sibling_import() -> None:
    """The export chain is a set of NAMES a public package binds, not a set of
    modules a package happens to import from.

    ``_api`` is private, so nothing in it is reachable unless a public path
    carries it. The package re-exports two names; a sibling module imports a
    third for its own use. Being referenced is not being exported.
    """
    from codeclone.metrics.external_reachability import collect_external_reachability

    api_module = "distillations._api"
    package_module = "distillations"
    module_deps = (
        ModuleDep(
            source=package_module,
            target=api_module,
            import_type="from_import",
            line=1,
            resolution="analyzed",
            requested_names=("DocumentedService", "exported_function"),
        ),
        ModuleDep(
            source=f"{package_module}.internal_use",
            target=api_module,
            import_type="from_import",
            line=1,
            resolution="analyzed",
            requested_names=("InternalHelper",),
        ),
    )
    dead_candidates = (
        _fixture_candidate(f"{api_module}:DocumentedService", kind="class"),
        _fixture_candidate(f"{api_module}:DocumentedService.render", kind="method"),
        _fixture_candidate(f"{api_module}:DocumentedService._hidden", kind="method"),
        _fixture_candidate(f"{api_module}:exported_function"),
        _fixture_candidate(f"{api_module}:internal_function"),
        _fixture_candidate(f"{api_module}:InternalHelper", kind="class"),
        _fixture_candidate(
            f"{api_module}:InternalHelper.never_called_public_method", kind="method"
        ),
    )

    rows = {
        row.qualname: row
        for row in collect_external_reachability(
            definitions=dead_candidates,
            module_deps=module_deps,
            class_metrics=(),
            package_modules=frozenset({package_module}),
        )
    }

    reachable = {qualname for qualname, row in rows.items() if row.state == "reachable"}
    # Exactly the two re-exported names and the public method of the class.
    assert reachable == {
        f"{api_module}:DocumentedService",
        f"{api_module}:DocumentedService.render",
        f"{api_module}:exported_function",
    }
    assert rows[f"{api_module}:DocumentedService.render"].witness == (
        f"package_reexport:{package_module}"
    )
    # A private method of an exported class is not on a public path.
    assert rows[f"{api_module}:DocumentedService._hidden"].state == "not_reachable"
    # A non-exported sibling function in a private module is not either.
    assert rows[f"{api_module}:internal_function"].state == "not_reachable"
    # Being referenced is not being exported: a class only a sibling module
    # imports never extends a public path to its methods.
    assert rows[f"{api_module}:InternalHelper"].state == "not_reachable"
    assert (
        rows[f"{api_module}:InternalHelper.never_called_public_method"].state
        == "not_reachable"
    )


def test_reachability_on_the_real_fixture_reads_the_named_export_chain() -> None:
    """The liveness_policy fixture through the real walk and the real owner.

    ``distillations.api`` is a PUBLIC module, so every public member is
    reachable by construction and the ground truth's two method cases both
    read ``reachable`` through the module itself - the direct public path
    outranks the package re-export as the recorded witness. The distinction
    the export chain makes is pinned above on a private module, where it is
    the only construct that can decide.
    """
    from codeclone.metrics.external_reachability import (
        collect_external_reachability,
        package_modules_from_registry,
    )

    fixture_root = Path(__file__).parent / "fixtures" / "liveness_policy"
    ground_truth = orjson.loads((fixture_root / "ground_truth.json").read_bytes())
    registry = build_test_module_registry(root=fixture_root)

    for package_module in ("distillations", "distillations_renamed"):
        api_path = f"{package_module}/api.py"
        api_module = f"{package_module}.api"
        method_cases = {
            case["symbol"]: case["expected"]
            for case in ground_truth["cases"]
            if case["path"] == api_path and "." in case["symbol"]
        }
        # One exported class method, one non-exported class method.
        assert len(method_cases) == 2

        module_deps: list[ModuleDep] = []
        dead_candidates: list[DeadCandidate] = []
        class_metrics: list[ClassMetrics] = []
        for relative_path in (
            f"{package_module}/__init__.py",
            api_path,
            f"{package_module}/internal_use.py",
        ):
            metrics = extract_file_metrics(
                source=(fixture_root / relative_path).read_text(),
                filepath=relative_path,
                module_registry=registry,
            )
            module_deps.extend(metrics.module_deps)
            dead_candidates.extend(metrics.dead_candidates)
            class_metrics.extend(metrics.class_metrics)

        rows = {
            row.qualname: row
            for row in collect_external_reachability(
                definitions=tuple(dead_candidates),
                module_deps=tuple(module_deps),
                class_metrics=tuple(class_metrics),
                package_modules=package_modules_from_registry(registry),
            )
        }
        assert package_module in package_modules_from_registry(registry)

        assert {
            symbol: rows[f"{api_module}:{symbol}"].state for symbol in method_cases
        } == {
            symbol: expected["reachability"]
            for symbol, expected in method_cases.items()
        }
        assert {
            symbol: rows[f"{api_module}:{symbol}"].witness.partition(":")[0]
            for symbol in method_cases
        } == {
            symbol: expected["witness_kind"]
            for symbol, expected in method_cases.items()
        }


def test_the_golden_export_cases_are_exposure_without_internal_use() -> None:
    """The four ground-truth cases that read ``live / export_root`` until
    liveness policy v4 (LP-EXPORT, LP-R-EXPORT, ROOT-EXPORT, R-ROOT-EXPORT),
    through the real walk and the real owner, pinned on their EVIDENCE:
    nothing inside the package binds the symbol (absent from
    ``referenced_qualnames``), the declaration is on the wire, a public path
    exists (``reachable`` through the witness kind the truth names), so the
    open world abstains as ``externally_reachable`` and the closed world calls
    it dead as ``unreferenced``. A verdict-only pin would pass again if some
    other mechanism produced the same verdict for the wrong reason."""
    from codeclone.metrics.external_reachability import (
        collect_external_reachability,
        package_modules_from_registry,
    )

    fixture_root = Path(__file__).parent / "fixtures" / "liveness_policy"
    ground_truth = orjson.loads((fixture_root / "ground_truth.json").read_bytes())
    cases = [
        case
        for case in ground_truth["cases"]
        if case["expected"].get("status") == "unresolved" and "." not in case["symbol"]
    ]
    assert {case["id"] for case in cases} == {
        "LP-EXPORT",
        "LP-R-EXPORT",
        "ROOT-EXPORT",
        "R-ROOT-EXPORT",
    }

    for case in cases:
        tree, _, rest = case["path"].partition("/")
        if tree.startswith("liveprobe"):
            root, source_roots, api_path = fixture_root / tree, ("src",), rest
            files = sorted(
                path.relative_to(root).as_posix()
                for path in (root / "src").rglob("*.py")
            )
        else:
            root, source_roots, api_path = fixture_root, (".",), case["path"]
            files = sorted(
                path.relative_to(root).as_posix() for path in (root / tree).glob("*.py")
            )
        registry = build_test_module_registry(root=root, source_roots=source_roots)
        metrics = {
            filepath: extract_file_metrics(
                source=(root / filepath).read_text(),
                filepath=filepath,
                module_registry=registry,
            )
            for filepath in files
        }
        python_module = registry.entries_by_path[api_path].identity.python_module
        assert python_module is not None
        qualname = f"{python_module.module}:{case['symbol']}"
        expected = case["expected"]
        candidates = tuple(
            candidate
            for file_metrics in metrics.values()
            for candidate in file_metrics.dead_candidates
        )
        referenced_qualnames = frozenset().union(
            *(file_metrics.referenced_qualnames for file_metrics in metrics.values())
        )
        declared_exports = frozenset().union(
            *(file_metrics.declared_exports for file_metrics in metrics.values())
        )
        rows = {
            row.qualname: row
            for row in collect_external_reachability(
                definitions=candidates,
                module_deps=tuple(
                    dep
                    for file_metrics in metrics.values()
                    for dep in file_metrics.module_deps
                ),
                class_metrics=tuple(
                    metric
                    for file_metrics in metrics.values()
                    for metric in file_metrics.class_metrics
                ),
                package_modules=package_modules_from_registry(registry),
                declared_exports=declared_exports,
            )
        }

        # Evidence: no internal use, a declaration, a public path.
        assert qualname not in referenced_qualnames, case["id"]
        assert f"{python_module.package}:{case['symbol']}" in declared_exports, case[
            "id"
        ]
        assert (rows[qualname].state, rows[qualname].witness.partition(":")[0]) == (
            expected["reachability"],
            expected["witness_kind"],
        ), case["id"]
        # Verdicts, both worlds, from that evidence alone.
        verdicts = {
            world: classify_liveness(
                definitions=candidates,
                referenced_names=frozenset().union(
                    *(
                        file_metrics.referenced_names
                        for file_metrics in metrics.values()
                    )
                ),
                referenced_qualnames=referenced_qualnames,
                external_reachability=tuple(rows.values()),
                world_contract=world,
            )
            for world in ("open", "closed")
        }
        assert {
            item.qualname: item.reason
            for item in verdicts["open"].unresolved_reachability
        }[qualname] == "externally_reachable", case["id"]
        assert qualname not in {item.qualname for item in verdicts["open"].dead_items}
        assert {item.qualname: item.reason for item in verdicts["closed"].dead_items}[
            qualname
        ] == expected["reason"], case["id"]
        assert expected["live"] is False, case["id"]


# ---------------------------------------------------------------------------
# Population generality: the rule is the language's; the population and the
# namespace set are the caller's.
# ---------------------------------------------------------------------------


def test_the_namespace_set_is_the_callers_when_given() -> None:
    """E1 exposes by definition only inside the namespaces the caller names.

    The default derives the language's privacy rule over every module the
    facts name, which is the dead-code evaluator's open world. The api-surface
    evaluator hands in the product's public namespaces instead: a public-named
    module of an unshipped tree is a Python module and not a place the project
    promises a name at, so a definition there is not exposed by definition.
    """

    from codeclone.metrics.external_reachability import collect_external_reachability

    candidates = (_candidate("scripts.tool:run", kind="function"),)

    def state(public_modules: frozenset[str] | None) -> tuple[str, str]:
        rows = collect_external_reachability(
            definitions=candidates,
            module_deps=(),
            class_metrics=(),
            package_modules=frozenset(),
            public_modules=public_modules,
        )
        (row,) = rows
        return row.state, row.witness

    assert state(None) == ("reachable", "public_module:scripts.tool")
    assert state(frozenset({"scripts.tool"})) == (
        "reachable",
        "public_module:scripts.tool",
    )
    assert state(frozenset({"pkg"})) == ("not_reachable", "")


def test_any_definition_shape_is_carried_by_a_package_re_export() -> None:
    """The population is not the dead-candidate population.

    A module-level constant is never a dead candidate and is part of an api
    surface; the owner reads the four facts every definition carries and
    nothing that only a candidate has. ``httpx.DEFAULT_TIMEOUT_CONFIG`` is
    this shape: defined in ``httpx._config``, imported by name in the package
    ``__init__``.
    """

    from codeclone.metrics.external_reachability import collect_external_reachability
    from codeclone.models import SymbolDefinition

    definitions = (
        SymbolDefinition(
            qualname="pkg._config:DEFAULT_TIMEOUT",
            local_name="DEFAULT_TIMEOUT",
            kind="constant",
            star_import_bound=True,
        ),
    )
    (row,) = collect_external_reachability(
        definitions=definitions,
        module_deps=(_dep("pkg", "pkg._config", "DEFAULT_TIMEOUT"),),
        class_metrics=(),
        package_modules=frozenset({"pkg"}),
    )
    assert (row.state, row.witness) == ("reachable", "package_reexport:pkg")


def test_the_star_binding_fact_is_read_from_any_definition_shape() -> None:
    """E3 reads ``star_import_bound`` off the definition, whatever carries it."""

    from codeclone.metrics.external_reachability import collect_external_reachability
    from codeclone.models import SymbolDefinition

    def state(star_import_bound: bool) -> tuple[str, str]:
        (row,) = collect_external_reachability(
            definitions=(
                SymbolDefinition(
                    qualname="pkg._star:starred",
                    local_name="starred",
                    kind="function",
                    star_import_bound=star_import_bound,
                ),
            ),
            module_deps=(_dep("pkg", "pkg._star", "*"),),
            class_metrics=(),
            package_modules=frozenset({"pkg"}),
        )
        return row.state, row.witness

    assert state(True) == ("reachable", "star_reexport:pkg")
    assert state(False) == ("not_reachable", "")


def test_a_dynamic_package_is_read_from_the_definitions_it_is_given() -> None:
    """``__getattr__`` is found in the population, so a population that lacks
    the walk's definitions cannot see it: the api evaluator hands both in."""

    from codeclone.metrics.external_reachability import collect_external_reachability
    from codeclone.models import SymbolDefinition

    thing = SymbolDefinition(
        qualname="lazy._impl:Thing",
        local_name="Thing",
        kind="class",
        star_import_bound=True,
    )
    getattr_hook = _candidate("lazy:__getattr__", kind="function")

    def state(*definitions: object) -> tuple[str, str]:
        rows = collect_external_reachability(
            definitions=definitions,  # type: ignore[arg-type]
            module_deps=(),
            class_metrics=(),
            package_modules=frozenset({"lazy"}),
        )
        return next((r.state, r.witness) for r in rows if r.qualname == thing.qualname)

    assert state(thing) == ("not_reachable", "")
    assert state(thing, getattr_hook) == ("unresolved", "module_getattr:lazy")


def test_a_protocol_dunder_method_is_public_when_its_population_says_so() -> None:
    """The leaf's publicity is the caller's vocabulary; the default is the rule.

    ``Beta.__init__`` is private under the plain underscore rule, and that is
    the dead-code reading. An api collector calls the protocol dunders public
    because the language dispatches to them from outside the class, and hands
    that set in; measured without it, a constructor signature left the api
    population (``public_symbols`` 5 -> 4 on the cross-surface fixture).
    """

    from codeclone.metrics.external_reachability import collect_external_reachability

    definitions = (
        _candidate("pkg.mod:Beta", kind="class"),
        _candidate("pkg.mod:Beta.__init__", kind="method"),
        _candidate("pkg.mod:Beta.run", kind="method"),
    )

    def states(public_leaves: frozenset[str]) -> dict[str, str]:
        rows = collect_external_reachability(
            definitions=definitions,
            module_deps=(),
            class_metrics=(_class("pkg.mod:Beta"),),
            package_modules=frozenset(),
            public_leaves=public_leaves,
        )
        return {row.qualname: row.state for row in rows}

    plain = states(frozenset())
    assert plain["pkg.mod:Beta.__init__"] == "not_reachable"
    assert plain["pkg.mod:Beta.run"] == "reachable"
    admitted = states(frozenset({"__init__"}))
    assert admitted["pkg.mod:Beta.__init__"] == "reachable"
    assert admitted["pkg.mod:Beta.run"] == "reachable"


# ---------------------------------------------------------------------------
# The fixed point: raw graph, world-invariant seeds, three-valued closure.
# ---------------------------------------------------------------------------


def _states(
    definitions: tuple[object, ...],
    deps: tuple[ModuleDep, ...],
    *,
    packages: frozenset[str],
    public_modules: frozenset[str],
    class_metrics: tuple[ClassMetrics, ...] = (),
) -> dict[str, tuple[str, str]]:
    from codeclone.metrics.external_reachability import collect_external_reachability

    rows = collect_external_reachability(
        definitions=definitions,  # type: ignore[arg-type]
        module_deps=deps,
        class_metrics=class_metrics,
        package_modules=packages,
        public_modules=public_modules,
    )
    return {row.qualname: (row.state, row.witness) for row in rows}


def test_the_fixed_point_reaches_a_cycle_from_one_public_entry_in_any_order() -> None:
    """RULING 2026-09-02: the discriminator is not local.

    ``_a.__init__`` and ``_b.__init__`` star-import each other and ``_b``
    re-exports ``Foo`` by name. Whether either private ``__init__`` is an
    export surface is decided by the graph, not by its syntax: with no public
    entry all three are unreachable; one proven ``cyclic -> _a`` edge and,
    after convergence, all three are reachable - whatever order the edges
    are read in, which is what kills an order-dependent implementation.
    """

    definitions = (
        _candidate("cyclic._a:a_thing", kind="function", star_import_bound=True),
        _candidate("cyclic._b:b_thing", kind="function", star_import_bound=True),
        _candidate("cyclic._b._impl:Foo", kind="class", star_import_bound=True),
    )
    cycle = (
        _dep("cyclic._a", "cyclic._b", "*"),
        _dep("cyclic._b", "cyclic._a", "*"),
        _dep("cyclic._b", "cyclic._b._impl", "Foo"),
    )
    entry = _dep("cyclic", "cyclic._a", "*")
    packages = frozenset({"cyclic", "cyclic._a", "cyclic._b"})

    def states(deps: tuple[ModuleDep, ...]) -> dict[str, tuple[str, str]]:
        return _states(
            definitions, deps, packages=packages, public_modules=frozenset({"cyclic"})
        )

    assert states(cycle) == {
        "cyclic._a:a_thing": ("not_reachable", ""),
        "cyclic._b:b_thing": ("not_reachable", ""),
        "cyclic._b._impl:Foo": ("not_reachable", ""),
    }
    converged = {
        "cyclic._a:a_thing": ("reachable", "star_reexport:cyclic"),
        "cyclic._b:b_thing": ("reachable", "star_reexport:cyclic._a"),
        "cyclic._b._impl:Foo": ("reachable", "star_reexport:cyclic._b"),
    }
    assert states((entry, *cycle)) == converged
    assert states((*cycle, entry)) == converged
    assert states(tuple(reversed((entry, *cycle)))) == converged


def test_unresolved_is_a_front_of_its_own() -> None:
    """A plain least fixed point reads everything it never reached as
    ``not_reachable``. A namespace a dynamic package could serve is
    ``unresolved`` instead, and so is whatever it carries outward - by a
    wildcard edge, or by a name its ``__init__`` imports. A proven path,
    arriving in any order, still wins.
    """

    definitions = (
        _candidate("pkg:__getattr__", kind="function"),
        _candidate("other._impl:Carried", kind="function", star_import_bound=True),
        # Not star-bound: only the name ``pkg._sub`` imports can carry it, so
        # the package re-export rule is the one input that reaches it.
        _candidate("other._impl:Named", kind="class"),
        _candidate("other._impl:Named.run", kind="method"),
        # Star-bound by nothing and imported by nobody: a wildcard from an
        # unreadable namespace carries the module's star-bound names and
        # nothing else, so this one stays unreached.
        _candidate("other._impl:Unlisted", kind="function"),
        # Two hops out on the unresolved front: the witness travels with it.
        _candidate("third._impl:Far", kind="function", star_import_bound=True),
        _candidate("pkg.pub:Sub", kind="class"),
    )
    deps = (
        _dep("pkg._sub", "other._impl", "*"),
        _dep("pkg._sub", "other._impl", "Named"),
        _dep("other._impl", "third._impl", "*"),
        # A plain public module's import binds the base for the hierarchy and
        # exposes nothing by itself (PEP 8: not a re-export).
        _dep("pkg.pub", "other._impl", "Named"),
    )
    packages = frozenset({"pkg", "pkg._sub", "other", "third"})
    sub_of_named = (_class("pkg.pub:Sub", "Named"),)

    def states(
        definitions: tuple[object, ...], deps: tuple[ModuleDep, ...]
    ) -> dict[str, tuple[str, str]]:
        return _states(
            definitions,
            deps,
            packages=packages,
            public_modules=frozenset({"pkg", "pkg.pub"}),
            class_metrics=sub_of_named,
        )

    # Nothing reaches ``pkg._sub``, so it carries nothing.
    silent = states(definitions[1:], deps)
    assert silent["other._impl:Carried"] == ("not_reachable", "")
    assert silent["other._impl:Named"] == ("not_reachable", "")
    # ``pkg.__getattr__`` can serve ``pkg._sub``; what it carries is unresolved,
    # and only what it carries: the wildcard binds star-bound names, the
    # ``__init__`` binds the name it imports, and ``Unlisted`` is neither.
    front = states(definitions, deps)
    assert front["other._impl:Carried"] == ("unresolved", "module_getattr:pkg")
    assert front["other._impl:Named"] == ("unresolved", "module_getattr:pkg")
    assert front["other._impl:Unlisted"] == ("not_reachable", "")
    assert front["third._impl:Far"] == ("unresolved", "module_getattr:pkg")
    # The subclass in a public module is proven; the method rides the higher
    # rank, not the first construct offered.
    assert front["other._impl:Named.run"] == (
        "reachable",
        "exposed_subclass:pkg.pub:Sub",
    )
    # A proven wildcard edge upgrades the namespace, in either order.
    proven = (*deps, _dep("pkg", "pkg._sub", "*"))
    for order in (proven, tuple(reversed(proven))):
        upgraded = states(definitions, order)
        assert upgraded["other._impl:Carried"] == (
            "reachable",
            "star_reexport:pkg._sub",
        )
        assert upgraded["other._impl:Named"] == ("reachable", "star_reexport:pkg._sub")
        assert upgraded["other._impl:Unlisted"] == ("not_reachable", "")
        assert upgraded["third._impl:Far"] == ("reachable", "star_reexport:other._impl")


def test_a_private_dynamic_package_marks_its_subtree_only_once_reached() -> None:
    """Dynamic packages are inputs to the graph, gated by the fixed point:
    a private ``__getattr__`` package no path reaches marks nothing, and one
    a public wildcard reaches marks what sits below it."""

    definitions = (
        _candidate("pkg._lazy:__getattr__", kind="function"),
        _candidate("pkg._lazy._impl:Thing", kind="class"),
    )
    packages = frozenset({"pkg", "pkg._lazy"})
    unreached = _states(
        definitions, (), packages=packages, public_modules=frozenset({"pkg"})
    )
    assert unreached["pkg._lazy._impl:Thing"] == ("not_reachable", "")
    reached = _states(
        definitions,
        (_dep("pkg", "pkg._lazy", "*"),),
        packages=packages,
        public_modules=frozenset({"pkg"}),
    )
    assert reached["pkg._lazy._impl:Thing"] == (
        "unresolved",
        "module_getattr:pkg._lazy",
    )


def test_the_first_definition_of_a_qualname_decides_its_kind() -> None:
    """Two populations may name one qualname; the first one handed in is the
    one answered for. The kind is what that decides, and it is observable:
    a method of a class whose base no edge binds abstains, a function does
    not, and only the kind tells them apart.
    """

    from codeclone.metrics.external_reachability import collect_external_reachability
    from codeclone.models import SymbolDefinition

    as_function = SymbolDefinition(
        qualname="pkg._m:Outer.inner", local_name="inner", kind="function"
    )
    as_method = _candidate("pkg._m:Outer.inner", kind="method")
    weird_base = (_class("pkg._m:Outer", "Unknown"),)

    def state(*definitions: object) -> tuple[str, str]:
        rows = collect_external_reachability(
            definitions=definitions,  # type: ignore[arg-type]
            module_deps=(),
            class_metrics=weird_base,
            package_modules=frozenset({"pkg"}),
        )
        (row,) = [r for r in rows if r.qualname == "pkg._m:Outer.inner"]
        return row.state, row.witness

    assert state(as_method, as_function) == ("unresolved", "unresolved_base:Unknown")
    assert state(as_function, as_method) == ("not_reachable", "")
