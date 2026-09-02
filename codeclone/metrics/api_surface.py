# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
import hashlib
from dataclasses import replace
from functools import lru_cache
from typing import TYPE_CHECKING, Final, Literal

from ..domain.source_scope import SURFACE_KIND_TEST_SUPPORT
from ..models import (
    ApiBreakingChange,
    ApiParamSpec,
    ApiSurfaceSnapshot,
    ModuleApiSurface,
    PublicSymbol,
)
from ..paths import is_test_filepath
from ._visibility import (
    ModuleVisibility,
    build_module_visibility,
    is_public_method_name,
)
from .api_population import ApiSurfacePopulation

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..analysis.normalizer import NormalizationConfig
    from ..models import ModuleRegistryHandle
    from ..qualnames import FunctionNode, QualnameCollector

__all__ = [
    "collect_module_api_surface",
    "compare_api_surfaces",
    "is_product_api_module",
    "product_api_modules",
]

_API_SIGNATURE_DOMAIN: Final = b"ccapi1:sig\x00"


def is_product_api_module(
    filepath: str,
    *,
    scan_root: str = "",
    module_registry: ModuleRegistryHandle | None = None,
) -> bool:
    """Does this file's public surface belong to the product's contract?

    The api-surface lane answers one question — "did the published contract
    break" — and a repository's own test code is not part of that contract.
    Before the split, deleting a test printed as ``removed | Removed from the
    public API surface`` and renaming a test parameter as ``signature_break``,
    which made ``fail_on_api_break`` unusable: it would fail a run for a
    renamed test.

    The track is not a second rule. It asks the project's existing source-kind
    owner (``codeclone.paths.is_test_filepath``, itself built on
    ``classify_source_kind``) — the same predicate that already decides the
    test lane in ``analysis.units`` and ``metrics.dead_code``. Change the
    owner's verdict and this track follows it; there is nothing here to keep
    in step by hand.

    ``module_registry`` is what lets the owner tell a repository's ``tests/``
    tree from what a distributed package actually ships - both a ``testing``
    subpackage and a module published under a test-shaped name, such as
    ``annotated_types.test_cases`` - so callers that hold a registry must
    pass it. Registry-free the owner is strictly the more cautious of the
    two, which is what the baseline decode bridge relies on. ``scan_root`` is
    equally load-bearing: a run carries absolute file paths, and the owner
    classifies repository-relative ones.
    """

    return not is_test_filepath(
        filepath,
        scan_root=scan_root,
        module_registry=module_registry,
    )


def product_api_modules(
    modules: Sequence[ModuleApiSurface],
    *,
    population: ApiSurfacePopulation,
) -> tuple[ModuleApiSurface, ...]:
    """Keep the product track, and stamp what survives with its surface kind.

    Two jobs, deliberately in one pass, because they are one decision. The
    test/support track leaves the collected population entirely — its symbols
    are not the project's contract in any reading, and keeping them made
    ``fail_on_api_break`` fail a run for a renamed test. Everything else stays
    collected and carries the owner's verdict as data, so the comparison can
    decide what may gate without any consumer re-deriving a population from
    whichever inputs it happens to hold.

    Narrowing what is *collected* by anything finer than the test track is not
    an option here: the collected surface is what the baseline stores, and a
    run that drops modules an earlier build stored reads every one of their
    symbols as ``removed``.

    Order is the caller's; this filters and never reorders, so the sort the
    producer already applied survives.
    """

    kept: list[ModuleApiSurface] = []
    for module in modules:
        kind = population.surface_kind(
            filepath=module.filepath,
            module=module.module,
        )
        if kind == SURFACE_KIND_TEST_SUPPORT:
            continue
        kept.append(replace(module, surface_kind=kind))
    return tuple(kept)


@lru_cache(maxsize=1)
def _api_signature_wire_config() -> NormalizationConfig:
    from ..analysis.normalizer import NormalizationConfig

    return NormalizationConfig(
        ignore_type_annotations=False,
        normalize_constants=False,
        normalize_names=False,
    )


def collect_module_api_surface(
    *,
    tree: ast.Module,
    module_name: str,
    filepath: str,
    collector: QualnameCollector,
    imported_names: frozenset[str],
    include_private_modules: bool = False,
) -> ModuleApiSurface | None:
    visibility = build_module_visibility(
        tree=tree,
        module_name=module_name,
        collector=collector,
        imported_names=imported_names,
        include_private_modules=include_private_modules,
    )
    if not visibility.is_public_module and not visibility.exported_names:
        return None

    symbols: list[PublicSymbol] = []
    public_classes = {
        class_qualname
        for class_qualname, class_node in collector.class_nodes
        if "." not in class_qualname
        and visibility.exported_via(class_node.name) is not None
    }

    for local_name, node in collector.units:
        symbol = _callable_api_symbol(
            module_name=module_name,
            local_name=local_name,
            node=node,
            visibility=visibility,
            public_classes=public_classes,
        )
        if symbol is not None:
            symbols.append(symbol)
    for class_qualname, class_node in collector.class_nodes:
        symbol = _class_api_symbol(
            module_name=module_name,
            class_qualname=class_qualname,
            class_node=class_node,
            visibility=visibility,
        )
        if symbol is not None:
            symbols.append(symbol)

    for constant_name, start_line, end_line in _public_constant_rows(
        tree=tree,
        visibility=visibility,
    ):
        symbol = _constant_api_symbol(
            module_name=module_name,
            constant_name=constant_name,
            start_line=start_line,
            end_line=end_line,
            visibility=visibility,
        )
        if symbol is not None:
            symbols.append(symbol)

    if not symbols:
        return None
    return ModuleApiSurface(
        module=module_name,
        filepath=filepath,
        symbols=tuple(sorted(symbols, key=lambda item: item.qualname)),
        all_declared=visibility.all_declared,
    )


def _callable_api_symbol(
    *,
    module_name: str,
    local_name: str,
    node: FunctionNode,
    visibility: ModuleVisibility,
    public_classes: set[str],
) -> PublicSymbol | None:
    start_line = int(getattr(node, "lineno", 0))
    end_line = int(getattr(node, "end_lineno", 0))
    returns_hash = _annotation_hash(node.returns)
    if "." not in local_name:
        return _build_public_symbol(
            module_name=module_name,
            export_name=node.name,
            local_name=local_name,
            kind="function",
            start_line=start_line,
            end_line=end_line,
            params=_parameter_specs(node=node, is_method=False),
            returns_hash=returns_hash,
            visibility=visibility,
        )
    class_name, _, method_name = local_name.partition(".")
    if class_name not in public_classes or not is_public_method_name(method_name):
        return None
    return _build_public_symbol(
        module_name=module_name,
        export_name=class_name,
        local_name=local_name,
        kind="method",
        start_line=start_line,
        end_line=end_line,
        params=_parameter_specs(node=node, is_method=True),
        returns_hash=returns_hash,
        visibility=visibility,
    )


def _class_api_symbol(
    *,
    module_name: str,
    class_qualname: str,
    class_node: ast.ClassDef,
    visibility: ModuleVisibility,
) -> PublicSymbol | None:
    if "." in class_qualname:
        return None
    return _build_public_symbol(
        module_name=module_name,
        export_name=class_node.name,
        local_name=class_qualname,
        kind="class",
        start_line=int(getattr(class_node, "lineno", 0)),
        end_line=int(getattr(class_node, "end_lineno", 0)),
        visibility=visibility,
    )


def _constant_api_symbol(
    *,
    module_name: str,
    constant_name: str,
    start_line: int,
    end_line: int,
    visibility: ModuleVisibility,
) -> PublicSymbol | None:
    return _build_public_symbol(
        module_name=module_name,
        export_name=constant_name,
        local_name=constant_name,
        kind="constant",
        start_line=start_line,
        end_line=end_line,
        visibility=visibility,
    )


def _build_public_symbol(
    *,
    module_name: str,
    export_name: str,
    local_name: str,
    kind: Literal["function", "class", "method", "constant"],
    start_line: int,
    end_line: int,
    visibility: ModuleVisibility,
    params: tuple[ApiParamSpec, ...] = (),
    returns_hash: str = "",
) -> PublicSymbol | None:
    exported_via = visibility.exported_via(export_name)
    if exported_via is None:
        return None
    return PublicSymbol(
        qualname=f"{module_name}:{local_name}",
        kind=kind,
        start_line=start_line,
        end_line=end_line,
        params=params,
        returns_hash=returns_hash,
        exported_via=exported_via,
    )


def compare_api_surfaces(
    *,
    baseline: ApiSurfaceSnapshot | None,
    current: ApiSurfaceSnapshot | None,
    strict_types: bool,
) -> tuple[tuple[str, ...], tuple[ApiBreakingChange, ...]]:
    baseline_symbols = _symbol_index(baseline)
    current_symbols = _symbol_index(current)
    added = tuple(sorted(set(current_symbols) - set(baseline_symbols)))
    breaking_changes: list[ApiBreakingChange] = []

    for qualname in sorted(baseline_symbols):
        baseline_symbol = baseline_symbols[qualname]
        current_symbol = current_symbols.get(qualname)
        if current_symbol is None:
            breaking_changes.append(
                ApiBreakingChange(
                    qualname=qualname,
                    filepath=baseline_symbol[1].filepath,
                    start_line=baseline_symbol[0].start_line,
                    end_line=baseline_symbol[0].end_line,
                    symbol_kind=baseline_symbol[0].kind,
                    change_kind="removed",
                    detail="Removed from the public API surface.",
                )
            )
            continue
        detail = _signature_break_detail(
            baseline_symbol=baseline_symbol[0],
            current_symbol=current_symbol[0],
            strict_types=strict_types,
        )
        if detail is None:
            continue
        breaking_changes.append(
            ApiBreakingChange(
                qualname=qualname,
                filepath=current_symbol[1].filepath,
                start_line=current_symbol[0].start_line,
                end_line=current_symbol[0].end_line,
                symbol_kind=current_symbol[0].kind,
                change_kind="signature_break",
                detail=detail,
            )
        )

    return added, tuple(
        sorted(
            breaking_changes,
            key=lambda item: (
                item.filepath,
                item.start_line,
                item.end_line,
                item.qualname,
                item.change_kind,
            ),
        )
    )


def _symbol_index(
    snapshot: ApiSurfaceSnapshot | None,
) -> dict[str, tuple[PublicSymbol, ModuleApiSurface]]:
    if snapshot is None:
        return {}
    return {
        symbol.qualname: (symbol, module)
        for module in snapshot.modules
        for symbol in module.symbols
    }


def _parameter_specs(
    *,
    node: FunctionNode,
    is_method: bool,
) -> tuple[ApiParamSpec, ...]:
    args = node.args
    rows: list[ApiParamSpec] = []
    positional = [*args.posonlyargs, *args.args]
    posonly_count = len(args.posonlyargs)
    defaults_offset = len(positional) - len(args.defaults)
    for index, arg in enumerate(positional):
        if _is_implicit_method_receiver(
            is_method=is_method,
            index=index,
            name=arg.arg,
        ):
            continue
        rows.append(
            ApiParamSpec(
                name=arg.arg,
                kind="pos_only" if index < posonly_count else "pos_or_kw",
                has_default=index >= defaults_offset,
                annotation_hash=_annotation_hash(arg.annotation),
            )
        )
    if args.vararg is not None:
        rows.append(
            ApiParamSpec(
                name=args.vararg.arg,
                kind="vararg",
                has_default=False,
                annotation_hash=_annotation_hash(args.vararg.annotation),
            )
        )
    for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        rows.append(
            ApiParamSpec(
                name=arg.arg,
                kind="kw_only",
                has_default=default is not None,
                annotation_hash=_annotation_hash(arg.annotation),
            )
        )
    if args.kwarg is not None:
        rows.append(
            ApiParamSpec(
                name=args.kwarg.arg,
                kind="kwarg",
                has_default=False,
                annotation_hash=_annotation_hash(args.kwarg.annotation),
            )
        )
    return tuple(rows)


def _is_implicit_method_receiver(*, is_method: bool, index: int, name: str) -> bool:
    return is_method and index == 0 and name in {"self", "cls"}


def _annotation_hash(node: ast.AST | None) -> str:
    if node is None:
        return ""
    from ..analysis.binding import EMPTY_BINDINGS
    from ..analysis.wire import emit_wire

    # An annotation is hashed on its own, outside any scope. The signature
    # config preserves every name literally, so no binding evidence is
    # consulted here and none is claimed.
    wire = emit_wire(node, _api_signature_wire_config(), EMPTY_BINDINGS).encode("utf-8")
    return hashlib.sha256(_API_SIGNATURE_DOMAIN + wire).hexdigest()


def _public_constant_rows(
    *,
    tree: ast.Module,
    visibility: ModuleVisibility,
) -> tuple[tuple[str, int, int], ...]:
    rows: list[tuple[str, int, int]] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            rows.extend(
                (
                    target.id,
                    int(getattr(node, "lineno", 0)),
                    int(getattr(node, "end_lineno", 0)),
                )
                for target in node.targets
                if isinstance(target, ast.Name)
                and visibility.exported_via(target.id) is not None
            )
        elif isinstance(node, ast.AnnAssign):
            target = node.target
            if (
                isinstance(target, ast.Name)
                and visibility.exported_via(target.id) is not None
            ):
                rows.append(
                    (
                        target.id,
                        int(getattr(node, "lineno", 0)),
                        int(getattr(node, "end_lineno", 0)),
                    )
                )
    return tuple(sorted(set(rows)))


def _signature_break_detail(
    *,
    baseline_symbol: PublicSymbol,
    current_symbol: PublicSymbol,
    strict_types: bool,
) -> str | None:
    if baseline_symbol.kind != current_symbol.kind:
        return (
            "Changed public symbol kind from "
            f"{baseline_symbol.kind} to {current_symbol.kind}."
        )
    if baseline_symbol.kind not in {"function", "method"}:
        return None
    baseline_params = baseline_symbol.params
    current_params = current_symbol.params
    if len(current_params) != len(baseline_params):
        return "Changed callable parameter count."
    for baseline_param, current_param in zip(
        baseline_params, current_params, strict=True
    ):
        if baseline_param.kind != current_param.kind:
            return (
                f"Changed parameter kind for {baseline_param.name} "
                f"from {baseline_param.kind} to {current_param.kind}."
            )
        if (
            baseline_param.kind != "pos_only"
            and baseline_param.name != current_param.name
        ):
            return (
                f"Renamed public parameter {baseline_param.name} "
                f"to {current_param.name}."
            )
        if baseline_param.has_default and not current_param.has_default:
            return f"Parameter {baseline_param.name} became required."
        if strict_types and (
            baseline_param.annotation_hash != current_param.annotation_hash
        ):
            return f"Changed type annotation for parameter {baseline_param.name}."
    if strict_types and baseline_symbol.returns_hash != current_symbol.returns_hash:
        return "Changed return annotation."
    return None
