# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Literal

import pytest

from codeclone.canonical.api_identity import signature_variant
from codeclone.canonical.model import ApiParameterFact
from codeclone.domain.source_scope import SURFACE_KIND_PRODUCT_PUBLIC
from codeclone.metrics import api_surface as api_surface_mod
from codeclone.metrics._visibility import ModuleVisibility
from codeclone.metrics.api_population import ApiSurfacePopulation
from codeclone.metrics.api_surface import (
    collect_module_api_surface,
    compare_api_surfaces,
    is_product_api_module,
    product_api_modules,
)
from codeclone.models import (
    ApiParamSpec,
    ApiSurfaceSnapshot,
    ModuleApiSurface,
    PublicSymbol,
)
from codeclone.paths.module_identity.inventory import build_module_registry
from tests._ast_metrics_helpers import tree_collector_and_imports
from tests._pipeline_fixtures import PipelineRun, analysis_boot, run_pipeline_once

from .ast_test_helpers import parse_class_first_member


def test_collect_module_api_surface_skips_self_and_collects_public_symbols() -> None:
    tree, collector, import_names = tree_collector_and_imports(
        """
__all__ = ["run", "Public", "VALUE"]

def run(value: int, *, enabled: bool = True) -> int:
    return value

class Public:
    def __init__(self, dep, *, lazy: bool = False) -> None:
        self.dep = dep

    def method(self, item: str) -> None:
        return None

    def _hidden(self, value: int) -> None:
        return None

VALUE = 1
""",
        module_name="pkg.mod",
    )

    surface = collect_module_api_surface(
        tree=tree,
        module_name="pkg.mod",
        filepath="pkg/mod.py",
        collector=collector,
        imported_names=import_names,
    )

    assert surface is not None
    assert surface.module == "pkg.mod"
    assert [symbol.qualname for symbol in surface.symbols] == [
        "pkg.mod:Public",
        "pkg.mod:Public.__init__",
        "pkg.mod:Public.method",
        "pkg.mod:VALUE",
        "pkg.mod:run",
    ]
    init_symbol = next(
        symbol
        for symbol in surface.symbols
        if symbol.qualname == "pkg.mod:Public.__init__"
    )
    method_symbol = next(
        symbol
        for symbol in surface.symbols
        if symbol.qualname == "pkg.mod:Public.method"
    )
    assert [param.name for param in init_symbol.params] == ["dep", "lazy"]
    assert [param.name for param in method_symbol.params] == ["item"]

    run_symbol = next(
        symbol for symbol in surface.symbols if symbol.qualname == "pkg.mod:run"
    )
    component_digests = (
        *(parameter.annotation_hash for parameter in run_symbol.params),
        run_symbol.returns_hash,
    )
    assert all(len(value) == 64 for value in component_digests)
    assert all(set(value) <= set("0123456789abcdef") for value in component_digests)


def test_api_signature_component_digests_are_parse_stable() -> None:
    source = """
__all__ = ["run"]

def run(left: list[str], /, right: dict[str, int] | None = None) -> tuple[str, ...]:
    return tuple(left)
"""
    first_tree, first_collector, first_imports = tree_collector_and_imports(
        source,
        module_name="pkg.mod",
    )
    second_tree, second_collector, second_imports = tree_collector_and_imports(
        source,
        module_name="pkg.mod",
    )

    first = collect_module_api_surface(
        tree=first_tree,
        module_name="pkg.mod",
        filepath="pkg/mod.py",
        collector=first_collector,
        imported_names=first_imports,
    )
    second = collect_module_api_surface(
        tree=second_tree,
        module_name="pkg.mod",
        filepath="pkg/mod.py",
        collector=second_collector,
        imported_names=second_imports,
    )

    assert first == second
    assert first is not None
    symbol = first.symbols[0]
    assert tuple(parameter.name for parameter in symbol.params) == ("left", "right")
    assert tuple(parameter.annotation_hash for parameter in symbol.params) == (
        "d848e7ea6a2971377d41e7d72f4c7e0f0bf543e857fe1d5a287ba6d5e87d8d8f",
        "6973abc818e5033a061453bfc60e8cfd53c69d48e60c751c06bab4e647b9fc5a",
    )
    assert (
        symbol.returns_hash
        == "482d6d649923a7350f54e3b1d64b23be713f87ba712c546ffe99493fc627479d"
    )


def test_compare_api_surfaces_reports_added_removed_and_signature_breaks() -> None:
    baseline = ApiSurfaceSnapshot(
        modules=(
            ModuleApiSurface(
                module="pkg.mod",
                filepath="pkg/mod.py",
                symbols=(
                    PublicSymbol(
                        qualname="pkg.mod:run",
                        kind="function",
                        start_line=1,
                        end_line=3,
                        params=(
                            ApiParamSpec(
                                name="value",
                                kind="pos_or_kw",
                                has_default=False,
                            ),
                            ApiParamSpec(
                                name="limit",
                                kind="pos_or_kw",
                                has_default=True,
                            ),
                        ),
                    ),
                    PublicSymbol(
                        qualname="pkg.mod:gone",
                        kind="function",
                        start_line=5,
                        end_line=6,
                    ),
                    PublicSymbol(
                        qualname="pkg.mod:Public.method",
                        kind="method",
                        start_line=10,
                        end_line=12,
                        params=(
                            ApiParamSpec(
                                name="enabled",
                                kind="kw_only",
                                has_default=True,
                            ),
                        ),
                    ),
                ),
            ),
        )
    )
    current = ApiSurfaceSnapshot(
        modules=(
            ModuleApiSurface(
                module="pkg.mod",
                filepath="pkg/mod.py",
                symbols=(
                    PublicSymbol(
                        qualname="pkg.mod:added",
                        kind="function",
                        start_line=20,
                        end_line=21,
                    ),
                    PublicSymbol(
                        qualname="pkg.mod:run",
                        kind="function",
                        start_line=1,
                        end_line=3,
                        params=(
                            ApiParamSpec(
                                name="value",
                                kind="pos_or_kw",
                                has_default=False,
                            ),
                            ApiParamSpec(
                                name="amount",
                                kind="pos_or_kw",
                                has_default=True,
                            ),
                        ),
                    ),
                    PublicSymbol(
                        qualname="pkg.mod:Public.method",
                        kind="method",
                        start_line=10,
                        end_line=12,
                        params=(
                            ApiParamSpec(
                                name="enabled",
                                kind="kw_only",
                                has_default=False,
                            ),
                        ),
                    ),
                ),
            ),
        )
    )

    added, breaking = compare_api_surfaces(
        baseline=baseline,
        current=current,
        strict_types=False,
    )

    assert added == ("pkg.mod:added",)
    assert [(item.qualname, item.change_kind) for item in breaking] == [
        ("pkg.mod:run", "signature_break"),
        ("pkg.mod:gone", "removed"),
        ("pkg.mod:Public.method", "signature_break"),
    ]
    assert breaking[0].detail == "Renamed public parameter limit to amount."
    assert breaking[1].detail == "Removed from the public API surface."
    assert breaking[2].detail == "Parameter enabled became required."


def _public_symbol(
    qualname: str,
    kind: Literal["function", "class", "method", "constant"],
    *,
    params: tuple[ApiParamSpec, ...] = (),
    returns_hash: str = "",
) -> PublicSymbol:
    return PublicSymbol(
        qualname=qualname,
        kind=kind,
        start_line=1,
        end_line=1,
        params=params,
        returns_hash=returns_hash,
    )


def test_collect_module_api_surface_skips_private_or_empty_modules() -> None:
    private_tree, private_collector, private_imports = tree_collector_and_imports(
        """
def hidden():
    return 1
""",
        module_name="pkg._internal",
    )
    assert (
        collect_module_api_surface(
            tree=private_tree,
            module_name="pkg._internal",
            filepath="pkg/_internal.py",
            collector=private_collector,
            imported_names=private_imports,
        )
        is None
    )

    empty_tree, empty_collector, empty_imports = tree_collector_and_imports(
        """
def _hidden():
    return 1
""",
        module_name="pkg.public",
    )
    assert (
        collect_module_api_surface(
            tree=empty_tree,
            module_name="pkg.public",
            filepath="pkg/public.py",
            collector=empty_collector,
            imported_names=empty_imports,
        )
        is None
    )


def test_api_surface_helpers_cover_constant_symbols_and_break_variants() -> None:
    visibility = ModuleVisibility(
        module_name="pkg.mod",
        exported_names=frozenset({"CONST", "Public"}),
        all_declared=("CONST", "Public"),
        is_public_module=True,
    )
    annassign_tree = ast.parse("CONST: int = 1")
    constant_rows = api_surface_mod._public_constant_rows(
        tree=annassign_tree,
        visibility=visibility,
    )
    assert constant_rows == (("CONST", 1, 1),)
    assign_tree = ast.parse("Public = 2")
    assign_rows = api_surface_mod._public_constant_rows(
        tree=assign_tree,
        visibility=visibility,
    )
    assert assign_rows == (("Public", 1, 1),)
    assert (
        api_surface_mod._build_public_symbol(
            module_name="pkg.mod",
            export_name="missing",
            local_name="missing",
            kind="constant",
            start_line=1,
            end_line=1,
            visibility=visibility,
        )
        is None
    )
    _outer_class, nested_class = parse_class_first_member(
        """
class Outer:
    class Inner:
        pass
""",
        ast.ClassDef,
    )
    assert (
        api_surface_mod._class_api_symbol(
            module_name="pkg.mod",
            class_qualname="Outer.Inner",
            class_node=nested_class,
            visibility=visibility,
        )
        is None
    )

    method = ast.parse(
        """
def run(self, a: int, /, b, *args: str, c: int, **kwargs: bytes) -> int:
    return 1
"""
    ).body[0]
    assert isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
    params = api_surface_mod._parameter_specs(node=method, is_method=True)
    assert [param.name for param in params] == ["a", "b", "args", "c", "kwargs"]

    class_before = _public_symbol("pkg.mod:Thing", "class")
    class_after = _public_symbol("pkg.mod:Thing", "constant")
    assert api_surface_mod._signature_change_verdict(
        baseline_symbol=class_before,
        current_symbol=class_after,
        strict_types=False,
    ) == ("signature_break", "Changed public symbol kind from class to constant.")
    assert (
        api_surface_mod._signature_change_verdict(
            baseline_symbol=class_before,
            current_symbol=_public_symbol("pkg.mod:Thing", "class"),
            strict_types=False,
        )
        is None
    )

    baseline_param = _public_symbol(
        "pkg.mod:run",
        "function",
        params=(ApiParamSpec(name="value", kind="kw_only", has_default=False),),
    )
    current_param_kind = _public_symbol(
        "pkg.mod:run",
        "function",
        params=(ApiParamSpec(name="value", kind="pos_or_kw", has_default=False),),
    )
    current_param_type = _public_symbol(
        "pkg.mod:run",
        "function",
        params=(
            ApiParamSpec(
                name="value",
                kind="kw_only",
                has_default=False,
                annotation_hash="str",
            ),
        ),
    )
    baseline_typed = _public_symbol(
        "pkg.mod:run",
        "function",
        params=(
            ApiParamSpec(
                name="value",
                kind="kw_only",
                has_default=False,
                annotation_hash="int",
            ),
        ),
        returns_hash="int",
    )
    current_return_type = _public_symbol(
        "pkg.mod:run",
        "function",
        params=baseline_typed.params,
        returns_hash="str",
    )
    # A keyword-only parameter that also takes a positional value binds
    # every call it bound before (the reverse direction is the table's
    # ``parameter-kind-changed`` row).
    assert api_surface_mod._signature_change_verdict(
        baseline_symbol=baseline_param,
        current_symbol=current_param_kind,
        strict_types=False,
    ) == ("signature_changed", "Parameter value accepts positional calls.")
    assert api_surface_mod._signature_change_verdict(
        baseline_symbol=baseline_typed,
        current_symbol=current_param_type,
        strict_types=True,
    ) == ("signature_break", "Changed type annotation for parameter value.")
    assert api_surface_mod._signature_change_verdict(
        baseline_symbol=baseline_typed,
        current_symbol=current_return_type,
        strict_types=True,
    ) == ("signature_break", "Changed return annotation.")
    fewer_params = _public_symbol("pkg.mod:run", "function", params=())
    more_params = _public_symbol(
        "pkg.mod:run",
        "function",
        params=(
            ApiParamSpec(name="a", kind="pos_or_kw", has_default=False),
            ApiParamSpec(name="b", kind="pos_or_kw", has_default=False),
        ),
    )
    # A different parameter count is no verdict on its own any more: the
    # detail names the first parameter that decides it.
    assert api_surface_mod._signature_change_verdict(
        baseline_symbol=fewer_params,
        current_symbol=more_params,
        strict_types=False,
    ) == ("signature_break", "Added required parameter a.")


def test_signature_change_verdict_compares_annotations_only_when_strict() -> None:
    """Without ``strict_types`` a changed annotation moves nothing."""

    def symbol(annotation: str) -> PublicSymbol:
        return _public_symbol(
            "pkg.mod:run",
            "function",
            params=(
                ApiParamSpec(
                    name="value",
                    kind="kw_only",
                    has_default=False,
                    annotation_hash=annotation,
                ),
            ),
            returns_hash=annotation,
        )

    baseline, current = symbol("int"), symbol("str")
    assert (
        api_surface_mod._signature_change_verdict(
            baseline_symbol=baseline,
            current_symbol=current,
            strict_types=False,
        )
        is None
    )


def test_symbol_index_none_snapshot_returns_empty() -> None:
    assert api_surface_mod._symbol_index(None, strict_types=False) == {}


# ── the verdict: "the signature changed" is a fact, "it breaks" a verdict ───
#
# The maintainer's decision table (2026-09-26), one row per line of it. Each
# row is reached from real source through the collector and the public
# comparison, so a row pins what a run records, not what a helper returns.
# ``None`` is "nothing moved": no change is recorded at all.


def _signature_snapshot(source: str) -> ApiSurfaceSnapshot:
    node = ast.parse(source).body[0]
    assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    symbol = PublicSymbol(
        qualname="pkg.mod:run",
        kind="function",
        start_line=1,
        end_line=1,
        params=api_surface_mod._parameter_specs(node=node, is_method=False),
    )
    return ApiSurfaceSnapshot(
        modules=(
            ModuleApiSurface(
                module="pkg.mod", filepath="pkg/mod.py", symbols=(symbol,)
            ),
        )
    )


def _recorded_change(
    baseline_source: str, current_source: str, *, strict_types: bool = False
) -> tuple[str, str] | None:
    added, changes = compare_api_surfaces(
        baseline=_signature_snapshot(baseline_source),
        current=_signature_snapshot(current_source),
        strict_types=strict_types,
    )
    assert added == ()
    if not changes:
        return None
    (change,) = changes
    return change.change_kind, change.detail


_CHANGED = "signature_changed"
_BREAK = "signature_break"

_SIGNATURE_DECISION_TABLE: tuple[tuple[str, str, str, tuple[str, str] | None], ...] = (
    # A call that bound before still binds: recorded, never breaking.
    (
        "optional-positional-appended",
        "def run(a): ...",
        "def run(a, b=None): ...",
        (_CHANGED, "Added optional parameter b."),
    ),
    (
        "optional-keyword-only-added-mid-block",
        "def run(a, *, y=1): ...",
        "def run(a, *, x=1, y=1): ...",
        (_CHANGED, "Added optional keyword-only parameter x."),
    ),
    (
        "varargs-added",
        "def run(a): ...",
        "def run(a, *args): ...",
        (_CHANGED, "Added *args."),
    ),
    (
        "kwargs-added",
        "def run(a): ...",
        "def run(a, **kwargs): ...",
        (_CHANGED, "Added **kwargs."),
    ),
    # The maintainer's caller-compatibility ruling (2026-09-26): what an
    # existing call binds to decides, never what introspection sees.
    (
        "positional-only-with-default-appended",
        "def run(a, /): ...",
        "def run(a, x=1, /): ...",
        (_CHANGED, "Added optional positional-only parameter x."),
    ),
    (
        "positional-only-with-default-opens-the-positional-block",
        "def run(*, k): ...",
        "def run(x=1, /, *, k): ...",
        (_CHANGED, "Added optional positional-only parameter x."),
    ),
    (
        "optional-positional-with-new-varargs",
        "def run(a): ...",
        "def run(a, b=None, *args): ...",
        (_CHANGED, "Added optional parameter b."),
    ),
    (
        "optional-keyword-only-after-varargs",
        "def run(a, *args): ...",
        "def run(a, *args, k=None): ...",
        (_CHANGED, "Added optional keyword-only parameter k."),
    ),
    (
        "optional-keyword-only-before-kwargs",
        "def run(a, **kwargs): ...",
        "def run(a, *, k=None, **kwargs): ...",
        (_CHANGED, "Added optional keyword-only parameter k."),
    ),
    (
        "keyword-only-became-positional",
        "def run(a, *, x=1): ...",
        "def run(a, x=1): ...",
        (_CHANGED, "Parameter x accepts positional calls."),
    ),
    (
        "required-keyword-only-became-positional",
        "def run(a, *, x): ...",
        "def run(a, x): ...",
        (_CHANGED, "Parameter x accepts positional calls."),
    ),
    (
        "kwargs-renamed",
        "def run(a, **kwargs): ...",
        "def run(a, **options): ...",
        (_CHANGED, "Renamed **kwargs to **options."),
    ),
    (
        "varargs-renamed",
        "def run(a, *args): ...",
        "def run(a, *rest): ...",
        (_CHANGED, "Renamed *args to *rest."),
    ),
    # A call that bound before fails or binds differently: breaking.
    (
        "required-positional-appended",
        "def run(a): ...",
        "def run(a, b): ...",
        (_BREAK, "Added required parameter b."),
    ),
    (
        "required-keyword-only-added",
        "def run(a, *, y=1): ...",
        "def run(a, *, x, y=1): ...",
        (_BREAK, "Added required parameter x."),
    ),
    (
        "positional-only-required-appended",
        "def run(a, /): ...",
        "def run(a, x, /): ...",
        (_BREAK, "Added required parameter x."),
    ),
    (
        "positional-only-with-default-inserted",
        "def run(a, /, b=None): ...",
        "def run(a, x=1, /, b=None): ...",
        (_BREAK, "Added positional-only parameter x."),
    ),
    (
        "optional-positional-inserted-before-varargs",
        "def run(a, *args): ...",
        "def run(a, b=None, *args): ...",
        (_BREAK, "Inserted parameter b before *args."),
    ),
    (
        "optional-positional-only-inserted-before-varargs",
        "def run(a, /, *args): ...",
        "def run(a, b=None, /, *args): ...",
        (_BREAK, "Inserted parameter b before *args."),
    ),
    (
        "required-positional-before-varargs-keeps-its-detail",
        "def run(a, *args): ...",
        "def run(a, b, *args): ...",
        (_BREAK, "Added required parameter b."),
    ),
    (
        "varargs-renamed-with-an-insertion-before-it",
        "def run(a, *args): ...",
        "def run(a, b=None, *rest): ...",
        (_BREAK, "Inserted parameter b before *rest."),
    ),
    (
        "optional-inserted-before-a-positional",
        "def run(a, b=1): ...",
        "def run(a, x=None, b=1): ...",
        (_BREAK, "Inserted parameter x before b."),
    ),
    (
        "optional-removed",
        "def run(a, b=1): ...",
        "def run(a): ...",
        (_BREAK, "Removed parameter b."),
    ),
    (
        "varargs-removed",
        "def run(a, *args): ...",
        "def run(a): ...",
        (_BREAK, "Removed parameter args."),
    ),
    (
        "kwargs-removed",
        "def run(a, **kwargs): ...",
        "def run(a): ...",
        (_BREAK, "Removed parameter kwargs."),
    ),
    (
        "parameter-kind-changed",
        "def run(a, b): ...",
        "def run(a, *, b): ...",
        (_BREAK, "Changed parameter kind for b from pos_or_kw to kw_only."),
    ),
    (
        "positional-became-positional-only",
        "def run(a, b): ...",
        "def run(a, b, /): ...",
        (_BREAK, "Changed parameter kind for a from pos_or_kw to pos_only."),
    ),
    (
        "keyword-only-became-positional-only",
        "def run(*, x=1): ...",
        "def run(x=1, /): ...",
        (_BREAK, "Changed parameter kind for x from kw_only to pos_only."),
    ),
    (
        "keyword-only-moved-before-varargs",
        "def run(a, *args, x=1): ...",
        "def run(a, x=1, *args): ...",
        (_BREAK, "Moved parameter x before *args."),
    ),
    (
        "keyword-only-became-positional-and-required",
        "def run(a, *, x=1): ...",
        "def run(a, x): ...",
        (_BREAK, "Parameter x became required."),
    ),
    (
        "positional-only-became-positional",
        "def run(a, /): ...",
        "def run(a): ...",
        (_BREAK, "Changed parameter kind for a from pos_only to pos_or_kw."),
    ),
    (
        "positional-renamed",
        "def run(a, b): ...",
        "def run(a, c): ...",
        (_BREAK, "Renamed public parameter b to c."),
    ),
    (
        "keyword-only-renamed",
        "def run(*, x): ...",
        "def run(*, y): ...",
        (_BREAK, "Renamed public parameter x to y."),
    ),
    (
        "renamed-and-required-reports-the-rename",
        "def run(a, b=1): ...",
        "def run(a, c): ...",
        (_BREAK, "Renamed public parameter b to c."),
    ),
    (
        "keyword-only-named-kwargs-renamed",
        "def run(a, *, kwargs=None): ...",
        "def run(a, *, options=None): ...",
        (_BREAK, "Renamed public parameter kwargs to options."),
    ),
    (
        "default-dropped",
        "def run(a=1): ...",
        "def run(a): ...",
        (_BREAK, "Parameter a became required."),
    ),
    # Several changes at once: the heaviest outcome, first reason of it.
    (
        "optional-and-required-together-break",
        "def run(a): ...",
        "def run(a, b=None, *, k): ...",
        (_BREAK, "Added required parameter k."),
    ),
    (
        "several-compatible-changes-stay-compatible",
        "def run(a): ...",
        "def run(a, b=None, *args, k=1, **kwargs): ...",
        (_CHANGED, "Added optional parameter b."),
    ),
    # Nothing a caller can observe moved: nothing is recorded.
    ("unchanged", "def run(a, b=1): ...", "def run(a, b=1): ...", None),
    ("required-became-optional", "def run(a): ...", "def run(a=1): ...", None),
    ("positional-only-renamed", "def run(a, /): ...", "def run(b, /): ...", None),
)


@pytest.mark.parametrize(
    ("baseline_source", "current_source", "expected"),
    [
        pytest.param(baseline, current, expected, id=row_id)
        for row_id, baseline, current, expected in _SIGNATURE_DECISION_TABLE
    ],
)
def test_signature_change_decision_table(
    baseline_source: str,
    current_source: str,
    expected: tuple[str, str] | None,
) -> None:
    assert _recorded_change(baseline_source, current_source) == expected


#: Under ``strict_types`` a compatible reshaping -- a renamed ``*args`` /
#: ``**kwargs``, a keyword-only parameter that became positional -- still
#: yields to an annotation that changed with it, and stays compatible when the
#: annotation is kept.
_STRICT_SIGNATURE_DECISION_TABLE: tuple[
    tuple[str, str, str, tuple[str, str] | None], ...
] = (
    (
        "kwargs-renamed-annotation-changed",
        "def run(a, **kwargs: int): ...",
        "def run(a, **options: str): ...",
        (_BREAK, "Changed type annotation for parameter kwargs."),
    ),
    (
        "kwargs-renamed-annotation-kept",
        "def run(a, **kwargs: int): ...",
        "def run(a, **options: int): ...",
        (_CHANGED, "Renamed **kwargs to **options."),
    ),
    (
        "varargs-renamed-annotation-changed",
        "def run(*args: int): ...",
        "def run(*rest: str): ...",
        (_BREAK, "Changed type annotation for parameter args."),
    ),
    (
        "keyword-only-became-positional-annotation-changed",
        "def run(a, *, x: int = 1): ...",
        "def run(a, x: str = 1): ...",
        (_BREAK, "Changed type annotation for parameter x."),
    ),
    (
        "keyword-only-became-positional-annotation-kept",
        "def run(a, *, x: int = 1): ...",
        "def run(a, x: int = 1): ...",
        (_CHANGED, "Parameter x accepts positional calls."),
    ),
)


@pytest.mark.parametrize(
    ("baseline_source", "current_source", "expected"),
    [
        pytest.param(baseline, current, expected, id=row_id)
        for row_id, baseline, current, expected in _STRICT_SIGNATURE_DECISION_TABLE
    ],
)
def test_strict_signature_change_decision_table(
    baseline_source: str,
    current_source: str,
    expected: tuple[str, str] | None,
) -> None:
    assert (
        _recorded_change(baseline_source, current_source, strict_types=True) == expected
    )


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        pytest.param("vararg", (_CHANGED, "Added *rest."), id="vararg"),
        pytest.param("kwarg", (_CHANGED, "Added **rest."), id="kwarg"),
    ],
)
def test_added_variadic_parameter_with_a_default_flag_stays_compatible(
    kind: Literal["vararg", "kwarg"],
    expected: tuple[str, str],
) -> None:
    """The table is total over ``(kind, has_default)``.

    A collected ``*args`` / ``**kwargs`` never carries a default, but a
    hand-built snapshot can; its rows answer like the collected ones instead
    of falling through the table.
    """

    baseline = _public_symbol("pkg.mod:run", "function", params=())
    current = _public_symbol(
        "pkg.mod:run",
        "function",
        params=(ApiParamSpec(name="rest", kind=kind, has_default=True),),
    )
    assert (
        api_surface_mod._signature_change_verdict(
            baseline_symbol=baseline,
            current_symbol=current,
            strict_types=False,
        )
        == expected
    )


def test_parameter_reasons_see_varargs_only_where_the_signature_keeps_one() -> None:
    """A ``*args`` the current signature dropped stands in front of nothing.

    The removal breaks and is the reported reason; the optional parameter
    appended beside it is named for what it is, not as an insertion before a
    ``*args`` that no longer exists.
    """

    def params(source: str) -> tuple[ApiParamSpec, ...]:
        node = ast.parse(source).body[0]
        assert isinstance(node, ast.FunctionDef)
        return api_surface_mod._parameter_specs(node=node, is_method=False)

    assert api_surface_mod._parameter_verdicts(
        baseline=params("def run(a, *args): ..."),
        current=params("def run(a, b=None): ..."),
        strict_types=False,
    ) == [
        (_BREAK, "Removed parameter args."),
        (_CHANGED, "Added optional parameter b."),
    ]


def test_compare_records_every_change_and_the_partition_splits_the_verdicts() -> None:
    """The edge stays recorded; only the verdict decides what gates.

    ``compare_api_surfaces`` keeps a compatible change beside the breaking
    ones, and ``partition_api_changes`` is the one split: ``removed`` and
    ``signature_break`` are breaking, ``signature_changed`` is not.
    """

    def module(*symbols: PublicSymbol) -> ApiSurfaceSnapshot:
        return ApiSurfaceSnapshot(
            modules=(
                ModuleApiSurface(
                    module="pkg.mod", filepath="pkg/mod.py", symbols=symbols
                ),
            )
        )

    value = ApiParamSpec(name="value", kind="pos_or_kw", has_default=False)
    optional = ApiParamSpec(name="limit", kind="pos_or_kw", has_default=True)
    required = ApiParamSpec(name="limit", kind="pos_or_kw", has_default=False)
    _added, changes = compare_api_surfaces(
        baseline=module(
            _public_symbol("pkg.mod:extended", "function", params=(value,)),
            _public_symbol("pkg.mod:gone", "function"),
            _public_symbol("pkg.mod:tightened", "function", params=(value,)),
        ),
        current=module(
            _public_symbol("pkg.mod:extended", "function", params=(value, optional)),
            _public_symbol("pkg.mod:tightened", "function", params=(value, required)),
        ),
        strict_types=False,
    )
    assert [(change.qualname, change.change_kind) for change in changes] == [
        ("pkg.mod:extended", "signature_changed"),
        ("pkg.mod:gone", "removed"),
        ("pkg.mod:tightened", "signature_break"),
    ]

    breaking, compatible = api_surface_mod.partition_api_changes(changes)
    assert [change.qualname for change in breaking] == [
        "pkg.mod:gone",
        "pkg.mod:tightened",
    ]
    assert [change.qualname for change in compatible] == ["pkg.mod:extended"]


# ── one public name, several definitions ───────────────────────────────────
#
# ``@overload`` declarations and their implementation, property accessors, a
# constant assigned twice: every definition of one qualname is a form of that
# name, and the comparison takes them as one group. The same rows are driven
# through a stored baseline in ``test_metrics_baseline``, where the
# definitions come back in lane order and without their lines.


def _surface(source: str) -> ApiSurfaceSnapshot:
    """The public surface a run collects from ``source`` as ``pkg.mod``."""

    tree, collector, import_names = tree_collector_and_imports(
        source, module_name="pkg.mod"
    )
    module = collect_module_api_surface(
        tree=tree,
        module_name="pkg.mod",
        filepath="pkg/mod.py",
        collector=collector,
        imported_names=import_names,
    )
    assert module is not None
    return ApiSurfaceSnapshot(modules=(module,))


def _overloaded(
    name: str,
    *forms: str,
    implementation: str,
    implementation_first: bool = False,
) -> str:
    """A module declaring ``name`` once per ``@overload`` form, then its body."""

    overloads = [f"@overload\ndef {name}({form}) -> int: ...\n" for form in forms]
    body = f"def {name}({implementation}) -> int:\n    return 0\n"
    definitions = [body, *overloads] if implementation_first else [*overloads, body]
    return "from typing import overload\n\n\n" + "".join(definitions)


def _plain(name: str, parameters: str) -> str:
    return f"def {name}({parameters}) -> int:\n    return 0\n"


_KEYWORD_FORM = "*, maxsize: int, typed: bool = False"
_CALLABLE_FORM = "func: object, /"
_CACHE_BODY = (
    "func: object | None = None, /, *, maxsize: int = 128, typed: bool = False"
)
_CACHE = _overloaded("cache", _KEYWORD_FORM, _CALLABLE_FORM, implementation=_CACHE_BODY)
_SERIALIZER_FORMS = ("*fields: str, mode: str = ''", "*fields: str, when: str = ''")
_SERIALIZER_BODY = "*fields: str, mode: str = '', when: str = ''"
_ACCESSORS = """class Box:
    @property
    def size(self) -> int:
        return 1

    @size.setter
    def size(self, value: int) -> None:
        pass

    @size.deleter
    def size(self) -> None:
        pass
"""
_BRANCH_DUPLICATES = """import sys

if sys.version_info >= (3, 12):

    def run(value: int) -> int:
        return value

else:

    def run(value: int) -> int:
        return value
"""
_TYPED_AUTH = _overloaded(
    "auth",
    "username: str, password: str",
    "username: bytes, password: bytes",
    implementation="username: bytes | str, password: bytes | str",
)
_KEYWORD_FORM_BREAK = (
    _BREAK,
    "Overload (*, maxsize, typed=...): Added required parameter strict.",
)

_OVERLOAD_SCENARIOS: tuple[tuple[str, str, str, tuple[str, str] | None], ...] = (
    # The same group, whatever order or lines its definitions arrive in.
    ("overloads-unchanged", _CACHE, _CACHE, None),
    (
        "overloads-reordered",
        _CACHE,
        _overloaded("cache", _CALLABLE_FORM, _KEYWORD_FORM, implementation=_CACHE_BODY),
        None,
    ),
    ("accessors-unchanged", _ACCESSORS, _ACCESSORS, None),
    ("constant-assigned-twice", "VALUE = 1\nVALUE = 2\n", "VALUE = 1\n", None),
    # Two definitions of one form are one form: only what changed is reported.
    (
        "branch-duplicates-gain-an-optional-parameter",
        _BRANCH_DUPLICATES,
        _plain("run", "value: int, limit: int = 0"),
        (_CHANGED, "Added optional parameter limit."),
    ),
    # A form that stopped accepting its calls breaks, named by that form.
    (
        "overload-form-gains-required-parameter",
        _CACHE,
        _overloaded(
            "cache",
            f"{_KEYWORD_FORM}, strict: bool",
            _CALLABLE_FORM,
            implementation=f"{_CACHE_BODY}, strict: bool = False",
        ),
        _KEYWORD_FORM_BREAK,
    ),
    (
        "overload-form-gains-required-parameter-implementation-first",
        _CACHE,
        _overloaded(
            "cache",
            f"{_KEYWORD_FORM}, strict: bool",
            _CALLABLE_FORM,
            implementation=f"{_CACHE_BODY}, strict: bool = False",
            implementation_first=True,
        ),
        _KEYWORD_FORM_BREAK,
    ),
    (
        "implementation-drops-a-parameter",
        _CACHE,
        _overloaded(
            "cache",
            _KEYWORD_FORM,
            _CALLABLE_FORM,
            implementation="func: object | None = None, /, *, maxsize: int = 128",
        ),
        (
            _BREAK,
            "Overload (func=..., /, *, maxsize=..., typed=...): "
            "Removed parameter typed.",
        ),
    ),
    (
        "every-form-gains-a-leading-positional",
        _overloaded("serialize", *_SERIALIZER_FORMS, implementation=_SERIALIZER_BODY),
        _overloaded(
            "serialize",
            *(f"field: str, /, {form}" for form in _SERIALIZER_FORMS),
            implementation=f"field: str, /, {_SERIALIZER_BODY}",
        ),
        (
            _BREAK,
            "Overload (*fields, when=...): Added required parameter field.",
        ),
    ),
    # Types are compared nowhere by default: overloads that only type calls
    # the old form already accepted add no form and remove none.
    (
        "typed-overloads-accept-what-the-untyped-form-accepted",
        _plain("auth", "username, password"),
        _TYPED_AUTH,
        None,
    ),
    (
        "typed-overloads-removed-beside-an-implementation-of-the-same-shape",
        _overloaded(
            "default",
            "ctx: int, call: bool = True",
            "ctx: int, call: int = 1",
            implementation="ctx: int, call: bool | int = True",
        ),
        _plain("default", "ctx: int, call: bool | int = True"),
        None,
    ),
    (
        "typed-overloads-beside-a-narrower-form",
        _plain("jar", "cookies, jar=None, overwrite=True"),
        _overloaded(
            "jar",
            "cookies: dict, jar: None = None, overwrite: bool = True",
            "cookies: dict, jar: list, overwrite: bool = True",
            implementation=(
                "cookies: dict, jar: list | None = None, overwrite: bool = True"
            ),
        ),
        (_CHANGED, "Added overload (cookies, jar, overwrite=...)."),
    ),
    # A form pairs with the sibling a call reaches unchanged, not with a
    # narrower one that merely shares its names.
    (
        "a-widened-form-beside-a-narrowed-one",
        _plain("lookup", "key, default=None, strict=True"),
        _overloaded(
            "lookup",
            "key, default, strict=True",
            implementation="key, default=None, strict=True, extra=None",
        ),
        (
            _CHANGED,
            "Overload (key, default=..., strict=...): Added optional parameter extra.",
        ),
    ),
    (
        "a-form-that-lost-a-default-beside-a-renamed-sibling",
        _plain("pick", "key, limit=1"),
        _overloaded("pick", "key, limit", implementation="key, size=1"),
        (_BREAK, "Overload (key, limit=...): Parameter limit became required."),
    ),
    (
        "a-function-beside-a-constant-of-the-same-name",
        _plain("f", "a"),
        "f = 1\n\n\n" + _plain("f", "b"),
        (_BREAK, "Overload (a): Renamed public parameter a to b."),
    ),
    # A form is gone: calls written against it are no longer declared.
    (
        "overload-removed",
        _CACHE,
        _overloaded("cache", _KEYWORD_FORM, implementation=_CACHE_BODY),
        (_BREAK, "Removed overload (func, /)."),
    ),
    (
        "overload-removed-beside-a-compatible-form",
        _CACHE,
        _overloaded(
            "cache",
            f"{_KEYWORD_FORM}, strict: bool = False",
            implementation=_CACHE_BODY,
        ),
        (_BREAK, "Removed overload (func, /)."),
    ),
    # A new form accepts calls nothing made before.
    (
        "overload-added",
        _overloaded("cache", _KEYWORD_FORM, implementation=_CACHE_BODY),
        _overloaded(
            "cache",
            _KEYWORD_FORM,
            "func: object, /, **options: int",
            implementation=_CACHE_BODY,
        ),
        (_CHANGED, "Added overload (func, /, **options)."),
    ),
    (
        "a-kept-form-beside-a-wider-new-one",
        _plain("grow", "item"),
        _overloaded("grow", "item", implementation="item, extra=None"),
        (_CHANGED, "Added overload (item, extra=...)."),
    ),
    # One definition per side: the verdicts the tables above already own.
    (
        "plain-unchanged",
        _plain("cache", _CACHE_BODY),
        _plain("cache", _CACHE_BODY),
        None,
    ),
    (
        "plain-gains-required-parameter",
        _plain("cache", _CACHE_BODY),
        _plain("cache", f"{_CACHE_BODY}, strict: bool"),
        (_BREAK, "Added required parameter strict."),
    ),
    (
        "plain-drops-a-parameter",
        _plain("cache", _CACHE_BODY),
        _plain("cache", "func: object | None = None, /, *, maxsize: int = 128"),
        (_BREAK, "Removed parameter typed."),
    ),
    (
        "plain-gains-a-leading-positional",
        _plain("serialize", _SERIALIZER_BODY),
        _plain("serialize", f"field: str, /, {_SERIALIZER_BODY}"),
        (_BREAK, "Added required parameter field."),
    ),
)


def _group_change(
    baseline: ApiSurfaceSnapshot, current: ApiSurfaceSnapshot
) -> tuple[str, str] | None:
    added, changes = compare_api_surfaces(
        baseline=baseline, current=current, strict_types=False
    )
    assert added == ()
    if not changes:
        return None
    (change,) = changes
    return change.change_kind, change.detail


@pytest.mark.parametrize(
    ("baseline_source", "current_source", "expected"),
    [
        pytest.param(baseline, current, expected, id=row_id)
        for row_id, baseline, current, expected in _OVERLOAD_SCENARIOS
    ],
)
def test_one_name_with_several_definitions_is_compared_as_one_group(
    baseline_source: str,
    current_source: str,
    expected: tuple[str, str] | None,
) -> None:
    assert (
        _group_change(_surface(baseline_source), _surface(current_source)) == expected
    )


def test_group_comparison_ignores_definition_order_and_lines() -> None:
    """The stored baseline hands definitions back in lane order, lines zeroed.

    Keeping whichever definition came last compared one overload with another
    on an unchanged source. The same definitions in the reverse order and
    without their lines are the same group, in both directions.
    """

    current = _surface(_CACHE)
    (module,) = current.modules
    reordered = replace(
        module,
        symbols=tuple(
            replace(symbol, start_line=0, end_line=0)
            for symbol in reversed(module.symbols)
        ),
    )
    baseline = ApiSurfaceSnapshot(modules=(reordered,))
    assert (
        compare_api_surfaces(baseline=baseline, current=current, strict_types=True),
        compare_api_surfaces(baseline=current, current=baseline, strict_types=True),
    ) == (((), ()), ((), ()))


def test_a_group_record_points_at_the_definition_it_names() -> None:
    """A reason about one form lands on that form's current definition.

    The paired reason lands on the current form it was judged against, an
    added form where it is declared, and a reason about a form that is gone,
    or about a name that is gone, on the name's first definition. Lines 5 and
    7 hold the ``@overload`` declarations of an ``_overloaded`` module, 7 and
    9 once its implementation is declared first -- which moves the grown
    form off the line its baseline form holds.
    """

    def location(baseline_source: str, current_source: str) -> tuple[str, int, int]:
        _added, changes = compare_api_surfaces(
            baseline=_surface(baseline_source),
            current=_surface(current_source),
            strict_types=False,
        )
        (change,) = changes
        return change.change_kind, change.start_line, change.end_line

    grown = _overloaded(
        "cache",
        f"{_KEYWORD_FORM}, strict: bool",
        _CALLABLE_FORM,
        implementation=f"{_CACHE_BODY}, strict: bool = False",
        implementation_first=True,
    )
    single = _overloaded("cache", _KEYWORD_FORM, implementation=_CACHE_BODY)
    extended = _overloaded(
        "cache",
        _KEYWORD_FORM,
        "func: object, /, **options: int",
        implementation=_CACHE_BODY,
    )
    assert [
        location(_CACHE, grown),
        location(single, extended),
        location(_CACHE, single),
        location(_CACHE, _plain("other", "value: int")),
    ] == [
        (_BREAK, 7, 7),
        (_CHANGED, 7, 7),
        (_BREAK, 5, 5),
        ("removed", 5, 5),
    ]


def test_a_definition_is_told_apart_by_the_canonical_signature_variant() -> None:
    """One formula owner: the comparison keys a form the way the canon does.

    The canonical api family is keyed ``(SYMBOL, canonical_signature_variant)``
    through ``canonical.api_identity``. Under ``strict_types`` a group's forms
    are that variant plus the symbol kind, with an empty digest spelled as
    absence, exactly as the canonical fact spells it; without it they are the
    variant of the call shape, every digest absent. The population carries
    both digest spellings.
    """

    annotated = _surface(_CACHE).modules[0].symbols
    unannotated = _surface("def cache(func=None, /, *, maxsize=128): ...").modules[0]
    symbols = (*annotated, *unannotated.symbols)
    digests = {
        digest
        for symbol in symbols
        for digest in (
            symbol.returns_hash,
            *(param.annotation_hash for param in symbol.params),
        )
    }
    assert "" in digests
    assert len(digests) > 1

    def canonical(symbol: PublicSymbol, *, typed: bool) -> tuple[str, str]:
        return symbol.kind, signature_variant(
            parameters=tuple(
                ApiParameterFact(
                    name=param.name,
                    kind=param.kind,
                    has_default=param.has_default,
                    annotation_digest=(param.annotation_hash or None)
                    if typed
                    else None,
                )
                for param in symbol.params
            ),
            returns_digest=(symbol.returns_hash or None) if typed else None,
        )

    for symbol in symbols:
        assert [
            api_surface_mod._form_key(symbol, strict_types=strict)
            for strict in (True, False)
        ] == [canonical(symbol, typed=True), canonical(symbol, typed=False)]
    assert len({canonical(symbol, typed=True) for symbol in annotated}) == 3


def test_types_are_part_of_a_form_only_when_types_are_compared() -> None:
    """Both directions of one boundary, on the same two sources.

    Typed overloads added over an untyped function: without ``strict_types``
    nothing a call binds moved, so nothing is recorded; under it the untyped
    form now has typed counterparts, and a changed annotation breaks there as
    it breaks everywhere else.
    """

    baseline = _surface(_plain("auth", "username, password"))
    current = _surface(_TYPED_AUTH)
    recorded = [
        [
            (change.change_kind, change.detail)
            for change in compare_api_surfaces(
                baseline=baseline, current=current, strict_types=strict
            )[1]
        ]
        for strict in (False, True)
    ]
    assert recorded == [
        [],
        [
            (
                _BREAK,
                "Overload (username, password): "
                "Changed type annotation for parameter username.",
            )
        ],
    ]


# ── the gate, end to end: a real baseline, a real run, the real exit code ──

_CLI_ENTRY = "from codeclone.surfaces.cli.workflow import main; main()"
_REPO_ROOT = Path(__file__).resolve().parents[1]
_GATE_SCOPE_ID = "6c2d1e94-b028-4f6b-8a35-9d41c0a72e18"
_GATE_BASELINE_SOURCE = '__all__ = ["run"]\n\n\ndef run(value):\n    return value\n'


def _api_gate_run(
    tmp_path: Path, *, current_source: str
) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    gated, family = _api_gate_family(tmp_path, current_source=current_source)
    summary = family["summary"]
    assert isinstance(summary, dict)
    return gated, summary


def _api_gate_family(
    tmp_path: Path,
    *,
    current_source: str,
    baseline_source: str = _GATE_BASELINE_SOURCE,
) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    """Publish a baseline, change the one public module, gate the run.

    Everything the run reads or writes -- repository, baseline, cache,
    report -- lives under ``tmp_path``. A subprocess, so the exit code is the
    process's own and not an in-process ``SystemExit``.
    """

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        f'[tool.codeclone]\nbaseline_scope_id = "{_GATE_SCOPE_ID}"\n',
        "utf-8",
    )
    module = repo / "api.py"
    module.write_text(baseline_source, "utf-8")
    common = (
        "--baseline",
        str(tmp_path / "codeclone.baseline.json"),
        "--api-surface",
        "--cache-path",
        str(tmp_path / "cache.sqlite3"),
        "--no-progress",
        "--no-color",
    )

    def cli(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-c", _CLI_ENTRY, *args],
            capture_output=True,
            text=True,
            cwd=_REPO_ROOT,
            check=False,
        )

    published = cli(str(repo), *common, "--update-baseline")
    assert published.returncode == 0, published.stdout + published.stderr
    module.write_text(current_source, "utf-8")
    report_path = tmp_path / "report.json"
    gated = cli(str(repo), *common, "--fail-on-api-break", "--json", str(report_path))
    document = json.loads(report_path.read_text("utf-8"))
    family = document["metrics"]["families"]["api_surface"]
    assert isinstance(family, dict)
    return gated, family


def _recorded_rows(family: dict[str, object]) -> list[tuple[object, object]]:
    items = family["items"]
    assert isinstance(items, list)
    return [
        (item["change_kind"], item["detail"])
        for item in items
        if isinstance(item, dict) and item["record_kind"] != "symbol"
    ]


def test_api_break_gate_passes_an_unchanged_overloaded_function(
    tmp_path: Path,
) -> None:
    """Nothing moved: the stored group and the run's group are one group."""

    gated, family = _api_gate_family(
        tmp_path, baseline_source=_CACHE, current_source=_CACHE
    )
    assert gated.returncode == 0, gated.stdout + gated.stderr
    summary = family["summary"]
    assert isinstance(summary, dict)
    assert summary["baseline_diff_available"] is True
    assert (summary["breaking"], summary["changed"]) == (0, 0)
    assert _recorded_rows(family) == []


def test_api_break_gate_fails_an_overload_form_that_gained_a_required_parameter(
    tmp_path: Path,
) -> None:
    """The implementation only grew an optional parameter; the form broke."""

    gated, family = _api_gate_family(
        tmp_path,
        baseline_source=_CACHE,
        current_source=_overloaded(
            "cache",
            f"{_KEYWORD_FORM}, strict: bool",
            _CALLABLE_FORM,
            implementation=f"{_CACHE_BODY}, strict: bool = False",
        ),
    )
    assert gated.returncode == 3, gated.stdout + gated.stderr
    assert _recorded_rows(family) == [_KEYWORD_FORM_BREAK]


def test_api_break_gate_passes_an_appended_optional_parameter(tmp_path: Path) -> None:
    """The release-port case: ``main(argv=None)`` style growth is not a break."""

    gated, summary = _api_gate_run(
        tmp_path,
        current_source=(
            '__all__ = ["run"]\n\n\ndef run(value, limit=None):\n    return value\n'
        ),
    )
    assert gated.returncode == 0, gated.stdout + gated.stderr
    assert summary["baseline_diff_available"] is True
    assert summary["breaking"] == 0


def test_api_break_gate_fails_an_appended_required_parameter(tmp_path: Path) -> None:
    """The opposite boundary on the same pipeline: a real break still fails."""

    gated, summary = _api_gate_run(
        tmp_path,
        current_source=(
            '__all__ = ["run"]\n\n\ndef run(value, limit):\n    return value\n'
        ),
    )
    assert gated.returncode == 3, gated.stdout + gated.stderr
    assert "Api breaking changes" in gated.stdout
    assert summary["baseline_diff_available"] is True
    assert summary["breaking"] == 1


# ── track: the product's contract is not the repository's test code ────────


#: One tree carrying every boundary the track has to decide, as data.
#:
#: Each entry is an input that reaches a different arm of the rule, so no arm
#: of it is unreachable decoration:
#:
#: * ``pkg/mod.py`` — plain product code.
#: * ``pkg/test_helpers.py`` — a ``test_``-named module *inside* a shipped
#:   package, the shape ``annotated_types.test_cases`` publishes. The owner
#:   reads the registry and keeps it on the contract; a bare reading of
#:   pytest's filename convention would delete a published module from it.
#: * ``pkg/testing/tools.py`` — a ``testing`` subpackage the package really
#:   ships. Only the module registry tells it from a repository test tree,
#:   which is why the run's registry is handed to the owner.
#: * ``pkg/tests/test_shipped.py`` — a distribution's own suite, shipped in
#:   the wheel. 848 of the 860 convention-only files in this project's whole
#:   dependency closure have exactly this shape, and none of them is a
#:   published contract.
#: * ``conftest.py`` and ``pkg/conftest.py`` — pytest configuration, outside
#:   and inside a shipped package. The first makes the directory rule alone
#:   insufficient; the second is why the exemption is a fact about modules a
#:   package publishes, not about names that merely look like tests.
#: * ``tests/…`` — the repository's own test tree, including a fixture tree.
#: * ``benchmarks/…`` and ``docs/conf.py`` — repository tooling. The owner
#:   calls both production, so both stay; the track invents no second rule.
_TRACK_TREE_FILES: tuple[tuple[str, str], ...] = (
    ("pkg/__init__.py", ""),
    (
        "pkg/mod.py",
        '__all__ = ["run"]\n\n\ndef run(value: int) -> int:\n    return value\n',
    ),
    ("pkg/test_helpers.py", "def helper(value: int) -> int:\n    return value\n"),
    ("pkg/conftest.py", "def package_fixture(request):\n    return request\n"),
    ("pkg/testing/__init__.py", ""),
    ("pkg/testing/tools.py", "def make_client(value: int) -> int:\n    return value\n"),
    ("pkg/tests/__init__.py", ""),
    (
        "pkg/tests/test_shipped.py",
        "def test_shipped(value: int) -> None:\n    assert value\n",
    ),
    ("conftest.py", "def root_fixture(request):\n    return request\n"),
    ("tests/conftest.py", "def sample_fixture(request):\n    return request\n"),
    ("tests/test_thing.py", "def test_thing(value: int) -> None:\n    assert value\n"),
    (
        "tests/fixtures/sample.py",
        "def sample_case(value: int) -> int:\n    return value\n",
    ),
    ("benchmarks/bench_case.py", "def measure(value: int) -> int:\n    return value\n"),
    ("docs/conf.py", "def setup(app):\n    return app\n"),
)


def _mixed_track_tree(root: Path) -> None:
    """Materialize the boundary tree under ``root``."""

    for relative_path, source in _TRACK_TREE_FILES:
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, "utf-8")


#: Every module the tree above publishes a public symbol from, as the run
#: names them. Stated once so the product and test halves below cannot drift
#: into two different populations.
_TRACK_TREE_SURFACES = (
    "benchmarks/bench_case.py",
    "conftest.py",
    "docs/conf.py",
    "pkg/conftest.py",
    "pkg/mod.py",
    "pkg/test_helpers.py",
    "pkg/testing/tools.py",
    "pkg/tests/test_shipped.py",
    "tests/conftest.py",
    "tests/fixtures/sample.py",
    "tests/test_thing.py",
)

#: The product half: what a consumer asking "did the published contract
#: break" is entitled to see. Written out rather than derived, so it cannot
#: agree with a broken rule by construction.
_PRODUCT_TRACK_SURFACES = (
    "benchmarks/bench_case.py",
    "docs/conf.py",
    "pkg/mod.py",
    "pkg/test_helpers.py",
    "pkg/testing/tools.py",
)

#: The test half, and the reason the gate was unusable.
_TEST_TRACK_SURFACES = (
    "conftest.py",
    "pkg/conftest.py",
    "pkg/tests/test_shipped.py",
    "tests/conftest.py",
    "tests/fixtures/sample.py",
    "tests/test_thing.py",
)


def _api_surface_run(root: Path, cache_path: Path) -> PipelineRun:
    _mixed_track_tree(root)
    boot = analysis_boot(root, min_loc=1, min_stmt=1, skip_metrics=False)
    boot.args.api_surface = True
    _cache, run = run_pipeline_once(boot, cache_path, root=root, warm=False)
    return run


def _metric_surfaces(run: PipelineRun, root: Path) -> list[str]:
    metrics = run.result.project_metrics
    assert metrics is not None
    # The run really produced this lane: an absent snapshot would make every
    # assertion below vacuously true.
    assert metrics.api_surface is not None
    return sorted(
        Path(module.filepath).relative_to(root).as_posix()
        for module in metrics.api_surface.modules
    )


def test_mixed_track_tree_publishes_every_boundary_case(tmp_path: Path) -> None:
    """The instrument is aimed at something.

    Each pin below asserts that some files are absent from the lane. Absence
    proves nothing about a file the collector never saw in the first place,
    so the whole population is measured once, here, without the track rule in
    the way: the collector reaches all nine.
    """

    _mixed_track_tree(tmp_path)
    boot = analysis_boot(tmp_path, min_loc=1, min_stmt=1, skip_metrics=False)
    boot.args.api_surface = True
    _cache, run = run_pipeline_once(
        boot,
        tmp_path / "cache.json",
        root=tmp_path,
        warm=False,
    )
    assert sorted(
        Path(module.filepath).relative_to(tmp_path).as_posix()
        for module in run.processing.api_modules
    ) == sorted(_TRACK_TREE_SURFACES)


def test_product_api_surface_metric_keeps_the_product_track(tmp_path: Path) -> None:
    """Direction one: a product symbol must not fall off the contract.

    Its opposite — a test symbol staying on the contract — is asserted by a
    separate test, so a filter that erred either way reddens a different pin
    and the two errors can never mask each other.
    """

    run = _api_surface_run(tmp_path, tmp_path / "cache.json")
    surfaces = _metric_surfaces(run, tmp_path)
    assert [path for path in surfaces if path in _PRODUCT_TRACK_SURFACES] == sorted(
        _PRODUCT_TRACK_SURFACES
    )


def test_product_api_surface_metric_excludes_the_repository_test_tree(
    tmp_path: Path,
) -> None:
    """Direction two: the lane a gate reads must not carry test code.

    ``fail_on_api_break`` reads ``api_breaking_changes``, which is computed
    from this snapshot. While the snapshot carries ``tests.*``, deleting a
    test prints as ``removed | Removed from the public API surface`` and
    renaming a test parameter as ``signature_break``, so the gate is unusable
    by construction: it would fail a run for a renamed test.
    """

    run = _api_surface_run(tmp_path, tmp_path / "cache.json")
    surfaces = _metric_surfaces(run, tmp_path)
    assert [path for path in surfaces if path in _TEST_TRACK_SURFACES] == []


def test_product_api_surface_metric_publishes_exactly_the_product_track(
    tmp_path: Path,
) -> None:
    """Both halves at once: nothing extra survives, nothing extra is invented."""

    run = _api_surface_run(tmp_path, tmp_path / "cache.json")
    assert _metric_surfaces(run, tmp_path) == sorted(_PRODUCT_TRACK_SURFACES)


def test_product_api_surface_observation_lane_excludes_the_test_tree(
    tmp_path: Path,
) -> None:
    """The baseline lane is probed alone: two consumers, two pins.

    ``ProjectMetrics.api_surface`` and the observation lane are fed from the
    same run but through different calls. A pin on one of them would pass on
    a fix that reached only that one, so the lane that becomes the baseline
    is measured on its own.
    """

    run = _api_surface_run(tmp_path, tmp_path / "cache.json")
    lane = run.result.observation_bundle.structural.api_surface
    assert "api_surface" in run.result.observation_bundle.contract.enabled_lanes
    assert sorted({row.owner.file.path for row in lane}) == sorted(
        _PRODUCT_TRACK_SURFACES
    )


def test_product_api_track_follows_the_source_kind_owner(tmp_path: Path) -> None:
    """The track is the owner's verdict, not a copy of the owner's rule.

    Four files decide this, and not one of their verdicts can be reproduced
    from the path alone:

    * ``pkg/testing/tools.py`` is production only because the registry proves
      ``pkg.testing`` is a shipped subpackage — a path rule reads ``testing``
      as a test directory and drops it.
    * ``pkg/test_helpers.py`` is production only because the registry proves
      the file is an ordinary module of a shipped package — the pytest
      filename convention alone drops it.
    * ``pkg/tests/test_shipped.py`` is test-kind only because the owner's
      directory vocabulary owns ``tests``; a rule that asked "is it inside any
      package?" would publish a distribution's own suite as its contract.
    * ``pkg/conftest.py`` is test-kind only because the owner keeps pytest's
      configuration file categorical, registry or no registry.

    A track that stopped delegating and re-derived any of this fails here.
    """

    _mixed_track_tree(tmp_path)
    registry = build_module_registry(root=tmp_path)
    verdicts = {
        relative_path: is_product_api_module(
            str(tmp_path / relative_path),
            scan_root=str(tmp_path),
            module_registry=registry,
        )
        for relative_path in (
            "pkg/testing/tools.py",
            "pkg/test_helpers.py",
            "pkg/tests/test_shipped.py",
            "pkg/conftest.py",
        )
    }
    assert verdicts == {
        "pkg/testing/tools.py": True,
        "pkg/test_helpers.py": True,
        "pkg/tests/test_shipped.py": False,
        "pkg/conftest.py": False,
    }


def test_product_api_track_reads_repository_relative_paths(tmp_path: Path) -> None:
    """``scan_root`` is load-bearing, not decoration.

    A run carries absolute file paths and the owner classifies
    repository-relative ones. Drop the root and a repository that merely
    lives under a directory called ``test`` — a checkout in ``/tmp/test/…``,
    say — loses its whole public surface.
    """

    disguised_root = tmp_path / "testing" / "checkout"
    (disguised_root / "pkg").mkdir(parents=True)
    module = disguised_root / "pkg" / "mod.py"
    module.write_text("def run(value: int) -> int:\n    return value\n", "utf-8")
    assert is_product_api_module(str(module), scan_root=str(disguised_root))
    assert not is_product_api_module(str(module))


def test_product_api_modules_filters_without_reordering() -> None:
    """The producer's order survives the filter."""

    modules = tuple(
        ModuleApiSurface(module=name, filepath=path, symbols=())
        for name, path in (
            ("b", "pkg/b.py"),
            ("a", "tests/test_a.py"),
            ("c", "pkg/c.py"),
        )
    )
    kept = product_api_modules(modules, population=ApiSurfacePopulation())
    assert [module.module for module in kept] == ["b", "c"]
    assert {module.surface_kind for module in kept} == {SURFACE_KIND_PRODUCT_PUBLIC}
