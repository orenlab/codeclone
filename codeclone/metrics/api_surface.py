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
    from collections.abc import Mapping, Sequence

    from ..analysis.normalizer import NormalizationConfig
    from ..models import ModuleRegistryHandle
    from ..qualnames import FunctionNode, QualnameCollector

__all__ = [
    "collect_module_api_surface",
    "compare_api_surfaces",
    "is_product_api_module",
    "partition_api_changes",
    "product_api_modules",
]

_API_SIGNATURE_DOMAIN: Final = b"ccapi1:sig\x00"

#: The two change kinds a signature comparison utters. ``removed`` is
#: uttered by ``compare_api_surfaces`` itself, for a symbol that is gone.
_SIGNATURE_BREAK: Final = "signature_break"
_SIGNATURE_CHANGED: Final = "signature_changed"
_POSITIONAL_PARAM_KINDS: Final = frozenset({"pos_only", "pos_or_kw"})
#: How a signature spells ``*args`` / ``**kwargs``. A caller never names
#: either, so renaming one leaves every call binding as before.
_VARIADIC_PREFIXES: Final[Mapping[str, str]] = {"vararg": "*", "kwarg": "**"}

_ApiVerdict = tuple[Literal["signature_break", "signature_changed"], str]

#: What an ADDED parameter means for a caller written against the baseline,
#: keyed by the parameter's ``(kind, has_default)``: the decision table as
#: data, exhaustive over both domains. A parameter the alignment below left
#: without a baseline counterpart is appended by construction -- every earlier
#: positional slot is some baseline parameter's counterpart, and keyword-only
#: parameters are matched by name, so an insertion surfaces there as
#: ``Inserted parameter X before Y``, never here.
#:
#: A call that bound before still binds after an optional positional
#: parameter -- ``pos_or_kw`` or ``pos_only`` -- appended to the positional
#: block, an optional keyword-only parameter anywhere in the keyword block, or
#: a new ``*args`` / ``**kwargs``: ``signature_changed``. A parameter without
#: a default breaks every call that omits it: ``signature_break``. The one
#: exception to a compatible row is a ``*args`` the baseline already had: an
#: optional positional parameter now stands in front of it and takes the
#: first value that used to flow into it (``_added_parameter_verdict``). A
#: collected ``*args`` / ``**kwargs`` never carries a default; its ``True``
#: rows keep the table total rather than leaving a hand-built snapshot to a
#: KeyError.
_ADDED_PARAMETER_VERDICTS: Final[
    Mapping[
        tuple[str, bool], tuple[Literal["signature_break", "signature_changed"], str]
    ]
] = {
    ("pos_only", False): (_SIGNATURE_BREAK, "Added required parameter {name}."),
    ("pos_only", True): (
        _SIGNATURE_CHANGED,
        "Added optional positional-only parameter {name}.",
    ),
    ("pos_or_kw", False): (_SIGNATURE_BREAK, "Added required parameter {name}."),
    ("pos_or_kw", True): (_SIGNATURE_CHANGED, "Added optional parameter {name}."),
    ("vararg", False): (_SIGNATURE_CHANGED, "Added *{name}."),
    ("vararg", True): (_SIGNATURE_CHANGED, "Added *{name}."),
    ("kw_only", False): (_SIGNATURE_BREAK, "Added required parameter {name}."),
    ("kw_only", True): (
        _SIGNATURE_CHANGED,
        "Added optional keyword-only parameter {name}.",
    ),
    ("kwarg", False): (_SIGNATURE_CHANGED, "Added **{name}."),
    ("kwarg", True): (_SIGNATURE_CHANGED, "Added **{name}."),
}


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
    """Added symbols, and every recorded change of a surviving or lost one.

    The second element carries all three change kinds. The edge between a
    baseline symbol and its current form is recorded whether or not it
    breaks a caller; ``partition_api_changes`` splits it into the breaking set
    that ``breaking`` and the api gate count and the compatible
    ``signature_changed`` set that is only reported.
    """

    baseline_symbols = _symbol_index(baseline)
    current_symbols = _symbol_index(current)
    added = tuple(sorted(set(current_symbols) - set(baseline_symbols)))
    changes: list[ApiBreakingChange] = []

    for qualname in sorted(baseline_symbols):
        baseline_symbol = baseline_symbols[qualname]
        current_symbol = current_symbols.get(qualname)
        if current_symbol is None:
            changes.append(
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
        verdict = _signature_change_verdict(
            baseline_symbol=baseline_symbol[0],
            current_symbol=current_symbol[0],
            strict_types=strict_types,
        )
        if verdict is None:
            continue
        change_kind, detail = verdict
        changes.append(
            ApiBreakingChange(
                qualname=qualname,
                filepath=current_symbol[1].filepath,
                start_line=current_symbol[0].start_line,
                end_line=current_symbol[0].end_line,
                symbol_kind=current_symbol[0].kind,
                change_kind=change_kind,
                detail=detail,
            )
        )

    return added, tuple(
        sorted(
            changes,
            key=lambda item: (
                item.filepath,
                item.start_line,
                item.end_line,
                item.qualname,
                item.change_kind,
            ),
        )
    )


def partition_api_changes(
    changes: Sequence[ApiBreakingChange],
) -> tuple[tuple[ApiBreakingChange, ...], tuple[ApiBreakingChange, ...]]:
    """Split recorded changes into ``(breaking, compatible)``, order kept.

    ``signature_changed`` is the one compatible kind. Everything else --
    ``removed``, ``signature_break`` -- is breaking, and so would be a kind
    this function was never taught: the partition fails closed into the gate
    rather than out of it.
    """

    breaking = tuple(
        change for change in changes if change.change_kind != _SIGNATURE_CHANGED
    )
    compatible = tuple(
        change for change in changes if change.change_kind == _SIGNATURE_CHANGED
    )
    return breaking, compatible


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


def _signature_change_verdict(
    *,
    baseline_symbol: PublicSymbol,
    current_symbol: PublicSymbol,
    strict_types: bool,
) -> _ApiVerdict | None:
    """The change kind and detail of one surviving symbol, or ``None``.

    Break reasons are sought first; ``signature_changed`` is the verdict only
    when no reason breaks a caller, so several changes at once take the
    heaviest outcome. The detail is the first reason of that outcome in the
    order the comparison walks: the baseline's parameters in declaration
    order, then the parameters only the current signature has, then the
    return annotation.
    """

    if baseline_symbol.kind != current_symbol.kind:
        return (
            _SIGNATURE_BREAK,
            "Changed public symbol kind from "
            f"{baseline_symbol.kind} to {current_symbol.kind}.",
        )
    if baseline_symbol.kind not in {"function", "method"}:
        return None
    verdicts = _parameter_verdicts(
        baseline=baseline_symbol.params,
        current=current_symbol.params,
        strict_types=strict_types,
    )
    if strict_types and baseline_symbol.returns_hash != current_symbol.returns_hash:
        verdicts.append((_SIGNATURE_BREAK, "Changed return annotation."))
    breaks = [verdict for verdict in verdicts if verdict[0] == _SIGNATURE_BREAK]
    return (breaks or verdicts)[0] if verdicts else None


def _parameter_verdicts(
    *,
    baseline: tuple[ApiParamSpec, ...],
    current: tuple[ApiParamSpec, ...],
    strict_types: bool,
) -> list[_ApiVerdict]:
    """Every parameter-level reason, baseline order first, then additions."""

    baseline_names = frozenset(param.name for param in baseline)
    counterparts = _counterpart_indexes(
        baseline=baseline,
        current=current,
        baseline_names=baseline_names,
    )
    kept_varargs = _kept_varargs(baseline=baseline, current=current)
    matched: set[int] = set()
    verdicts: list[_ApiVerdict] = []
    for param, index in zip(baseline, counterparts, strict=True):
        if index is None:
            index = _index_by_name(current, param.name)
            verdicts.append(
                _missing_parameter_verdict(
                    param,
                    moved=None if index is None else current[index],
                    kept_varargs=kept_varargs,
                    strict_types=strict_types,
                )
            )
        else:
            verdict = _counterpart_verdict(
                baseline_param=param,
                current_param=current[index],
                inserted=_is_insertion(
                    param,
                    current=current,
                    index=index,
                    baseline_names=baseline_names,
                ),
                strict_types=strict_types,
            )
            if verdict is not None:
                verdicts.append(verdict)
        if index is not None:
            matched.add(index)
    verdicts.extend(
        _added_parameter_verdict(param, kept_varargs=kept_varargs)
        for index, param in enumerate(current)
        if index not in matched
    )
    return verdicts


def _kept_varargs(
    *,
    baseline: tuple[ApiParamSpec, ...],
    current: tuple[ApiParamSpec, ...],
) -> str | None:
    """The current name of a ``*args`` the baseline already had, or ``None``.

    Before the change, positional values past the named parameters flowed
    into it; a positional parameter standing in front of it now takes the
    first of them, so a call that bound before binds differently.
    """

    if not any(param.kind == "vararg" for param in baseline):
        return None
    return next((param.name for param in current if param.kind == "vararg"), None)


def _parameter_slots(
    params: Sequence[ApiParamSpec],
) -> tuple[tuple[str, int | str], ...]:
    """Where a caller reaches each parameter.

    Positional parameters by their position in the positional block,
    keyword-only parameters by name, ``*args`` / ``**kwargs`` by kind.
    """

    slots: list[tuple[str, int | str]] = []
    position = 0
    for param in params:
        if param.kind in _POSITIONAL_PARAM_KINDS:
            slots.append(("positional", position))
            position += 1
        elif param.kind == "kw_only":
            slots.append(("keyword", param.name))
        else:
            slots.append((param.kind, 0))
    return tuple(slots)


def _counterpart_indexes(
    *,
    baseline: tuple[ApiParamSpec, ...],
    current: tuple[ApiParamSpec, ...],
    baseline_names: frozenset[str],
) -> tuple[int | None, ...]:
    """The current index each baseline parameter aligns with, or ``None``."""

    current_slots = {
        slot: index for index, slot in enumerate(_parameter_slots(current))
    }
    renamed = _keyword_renames(
        baseline=baseline,
        current=current,
        baseline_names=baseline_names,
    )
    return tuple(
        current_slots.get(slot, renamed.get(param.name))
        for slot, param in zip(_parameter_slots(baseline), baseline, strict=True)
    )


def _keyword_renames(
    *,
    baseline: tuple[ApiParamSpec, ...],
    current: tuple[ApiParamSpec, ...],
    baseline_names: frozenset[str],
) -> dict[str, int]:
    """Keyword-only parameters renamed in place: baseline name -> current index.

    Keyword-only parameters align by name, so a rename is a baseline name the
    current signature lacks altogether at a keyword position the current
    block fills with a name the baseline never had.
    """

    current_names = frozenset(param.name for param in current)
    baseline_keywords = [param.name for param in baseline if param.kind == "kw_only"]
    current_keywords = [
        index for index, param in enumerate(current) if param.kind == "kw_only"
    ]
    return {
        name: index
        for name, index in zip(baseline_keywords, current_keywords, strict=False)
        if name not in current_names and current[index].name not in baseline_names
    }


def _index_by_name(params: tuple[ApiParamSpec, ...], name: str) -> int | None:
    return next(
        (index for index, param in enumerate(params) if param.name == name),
        None,
    )


def _is_insertion(
    baseline_param: ApiParamSpec,
    *,
    current: tuple[ApiParamSpec, ...],
    index: int,
    baseline_names: frozenset[str],
) -> bool:
    """A new parameter took this positional slot and pushed the old one later."""

    candidate = current[index]
    return (
        baseline_param.kind == "pos_or_kw"
        and candidate.name not in baseline_names
        and any(later.name == baseline_param.name for later in current[index + 1 :])
    )


def _missing_parameter_verdict(
    param: ApiParamSpec,
    *,
    moved: ApiParamSpec | None,
    kept_varargs: str | None,
    strict_types: bool,
) -> _ApiVerdict:
    """A baseline parameter no current slot holds: removed, or found by name."""

    if moved is None:
        return (_SIGNATURE_BREAK, f"Removed parameter {param.name}.")
    return _widened_keyword_verdict(
        param,
        moved,
        kept_varargs=kept_varargs,
        strict_types=strict_types,
    ) or (
        _SIGNATURE_BREAK,
        f"Changed parameter kind for {param.name} from {param.kind} to {moved.kind}.",
    )


def _widened_keyword_verdict(
    param: ApiParamSpec,
    moved: ApiParamSpec,
    *,
    kept_varargs: str | None,
    strict_types: bool,
) -> _ApiVerdict | None:
    """A keyword-only parameter that became positional-or-keyword, else ``None``.

    The one compatible change of kind: every keyword call binds as before,
    and a positional value reaches the parameter only where a call used to
    fail -- unless a ``*args`` the baseline already had collected that value.
    """

    if (param.kind, moved.kind) != ("kw_only", "pos_or_kw"):
        return None
    if kept_varargs is not None:
        return (
            _SIGNATURE_BREAK,
            f"Moved parameter {param.name} before *{kept_varargs}.",
        )
    return _binding_verdict(
        baseline_param=param,
        current_param=moved,
        strict_types=strict_types,
    ) or (_SIGNATURE_CHANGED, f"Parameter {param.name} accepts positional calls.")


def _counterpart_verdict(
    *,
    baseline_param: ApiParamSpec,
    current_param: ApiParamSpec,
    inserted: bool,
    strict_types: bool,
) -> _ApiVerdict | None:
    if inserted:
        if current_param.kind == "pos_only":
            return (
                _SIGNATURE_BREAK,
                f"Added positional-only parameter {current_param.name}.",
            )
        return (
            _SIGNATURE_BREAK,
            f"Inserted parameter {current_param.name} before {baseline_param.name}.",
        )
    if baseline_param.kind != current_param.kind:
        return (
            _SIGNATURE_BREAK,
            f"Changed parameter kind for {baseline_param.name} "
            f"from {baseline_param.kind} to {current_param.kind}.",
        )
    renamed: _ApiVerdict | None = None
    if baseline_param.kind != "pos_only" and baseline_param.name != current_param.name:
        renamed = _rename_verdict(baseline_param, current_param)
    if renamed is not None and renamed[0] == _SIGNATURE_BREAK:
        return renamed
    return (
        _binding_verdict(
            baseline_param=baseline_param,
            current_param=current_param,
            strict_types=strict_types,
        )
        or renamed
    )


def _rename_verdict(
    baseline_param: ApiParamSpec,
    current_param: ApiParamSpec,
) -> _ApiVerdict:
    """A renamed ``*args`` / ``**kwargs`` is compatible; any other rename breaks.

    A keyword call names a keyword-reachable parameter, so renaming one fails
    that call. Nothing names ``*args`` or ``**kwargs``: the values they
    collect arrive exactly as before.
    """

    prefix = _VARIADIC_PREFIXES.get(baseline_param.kind)
    if prefix is None:
        return (
            _SIGNATURE_BREAK,
            f"Renamed public parameter {baseline_param.name} to {current_param.name}.",
        )
    return (
        _SIGNATURE_CHANGED,
        f"Renamed {prefix}{baseline_param.name} to {prefix}{current_param.name}.",
    )


def _binding_verdict(
    *,
    baseline_param: ApiParamSpec,
    current_param: ApiParamSpec,
    strict_types: bool,
) -> _ApiVerdict | None:
    """What still breaks once a caller reaches the same parameter."""

    if baseline_param.has_default and not current_param.has_default:
        return (_SIGNATURE_BREAK, f"Parameter {baseline_param.name} became required.")
    if strict_types and baseline_param.annotation_hash != current_param.annotation_hash:
        return (
            _SIGNATURE_BREAK,
            f"Changed type annotation for parameter {baseline_param.name}.",
        )
    return None


def _added_parameter_verdict(
    param: ApiParamSpec,
    *,
    kept_varargs: str | None,
) -> _ApiVerdict:
    return _insertion_before_varargs_verdict(
        param,
        kept_varargs=kept_varargs,
    ) or _table_verdict(param)


def _table_verdict(param: ApiParamSpec) -> _ApiVerdict:
    change_kind, template = _ADDED_PARAMETER_VERDICTS[(param.kind, param.has_default)]
    return change_kind, template.format(name=param.name)


def _insertion_before_varargs_verdict(
    param: ApiParamSpec,
    *,
    kept_varargs: str | None,
) -> _ApiVerdict | None:
    """An optional positional parameter in front of a ``*args`` the baseline had.

    The table calls it compatible; the first positional value that used to
    flow into ``*args`` lands in it now. A required one keeps the table's
    ``Added required parameter`` reason.
    """

    if (
        kept_varargs is None
        or not param.has_default
        or param.kind not in _POSITIONAL_PARAM_KINDS
    ):
        return None
    return (
        _SIGNATURE_BREAK,
        f"Inserted parameter {param.name} before *{kept_varargs}.",
    )
