# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""Who owns "what counts as this project's public API surface".

Before this module the answer was a predicate — ``is_product_api_module`` —
called from nineteen places with four different input sets, of which fifteen
were incomplete. A predicate with optional inputs is not an owner: each caller
re-argues the population it happens to have, and the argument is re-derived at
every site instead of decided once.

The owner answers two questions, and keeps them apart because they have
different subjects.

The first is per module: which *surface kind* it has, from three inputs, and
every input is here because a current answer is wrong without it:

``scan_root``
    a run carries absolute paths and the source-kind owner classifies
    repository-relative ones, so a checkout under ``/tmp/test/`` loses its
    whole surface without it.
``module_registry``
    separates a distributed ``pkg/testing/`` subpackage, which ships, from the
    repository's own ``tests/`` tree, which does not.
``distributed_packages``
    what the project actually ships. ``benchmarks/``, ``scripts/``,
    ``plugins/`` and ``.github/`` are importable, are ``production`` source
    kind, and are not part of anyone's contract: measured on this repository,
    219 of 5409 collected symbols sit outside the distributed package. Nothing
    held this input before.

The kinds are a partition, not a filter chain, so the *opposite* error of each
verdict is a different verdict rather than the absence of one.

The second is per symbol: whether a public namespace *binds* it. Where a
definition sits is not where it becomes externally observable —
``httpx.Client`` is defined in ``httpx._client`` and bound as ``httpx.Client``
— so module privacy is a statement about the namespace and never a verdict on
a symbol. The verdict comes from the external-reachability owner, the same one
the dead-code evaluator reads, over the namespaces this owner names: a
definition in a public product module, a named import into a public package
``__init__`` (aliased, or through several hops), a wildcard under the target's
``__all__`` rule. A binding the walk cannot read — a package serving names
from a module-level ``__getattr__`` — is ``unresolved``, and unresolved is
included: concluding "not API" from an inability to prove a re-export is how a
gate goes confidently silent exactly where its data is insufficient.

What the owner deliberately does NOT decide: which symbols are collected. The
collected population is the lane's stored payload, and narrowing it against a
baseline written by an earlier build reads every dropped symbol as ``removed``.
Both verdicts ride the collected rows as data — the kind on the module, the
exposure on the symbol — and one projection, :func:`is_api_visible`, turns
them into the population that the family reports and the gate compares.
"""

from __future__ import annotations

import os
from dataclasses import replace
from typing import TYPE_CHECKING, Final

from ..domain.source_scope import (
    SURFACE_KIND_PRODUCT_INTERNAL,
    SURFACE_KIND_PRODUCT_PUBLIC,
    SURFACE_KIND_REPOSITORY_SUPPORT,
    SURFACE_KIND_TEST_SUPPORT,
)
from ..models import ApiSurfaceSnapshot, SymbolDefinition
from ..paths import is_test_filepath
from ._visibility import PUBLIC_METHOD_DUNDERS, is_public_module_name
from .external_reachability import (
    collect_external_reachability,
    reachability_by_qualname,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from ..models import (
        ClassMetrics,
        DeadCandidate,
        ModuleApiSurface,
        ModuleDep,
        ModuleRegistryHandle,
        PublicSymbol,
    )

__all__ = [
    "ApiSurfacePopulation",
    "classify_api_exposure",
    "is_api_visible",
    "is_product_surface",
    "visible_api_surface",
]

#: The kinds whose symbols may be API at all. The other two leave the gate
#: whatever their symbols' exposure says, because an unshipped tree and the
#: test track are not places the project promises a name at.
_PRODUCT_KINDS: Final = frozenset(
    {SURFACE_KIND_PRODUCT_PUBLIC, SURFACE_KIND_PRODUCT_INTERNAL}
)
#: The exposure states on the included side. ``unresolved`` is here by law;
#: ``None`` (never classified) is not, and must never be read as included.
_VISIBLE_EXPOSURES: Final = frozenset({"reachable", "unresolved"})


class ApiSurfacePopulation:
    """The run's answer to "what is this project's public API surface".

    Built once per run where all inputs exist, and read everywhere else.
    ``distributed_packages`` is ``None`` when the repository declares no
    manifest this owner can read: unknown is not "nothing ships", so an
    undeclared manifest keeps every non-test module on the product track — the
    behaviour that already exists — instead of silently emptying the lane.
    ``include_private_modules`` is the run saying its private product modules
    are part of its surface: they become namespaces, and the collector admits
    their public-named definitions even without an ``__all__``.

    Deliberately not a dataclass: the model store owns the repository's data
    shapes, and this is a decision object whose fields are the inputs to one
    verdict.
    """

    __slots__ = (
        "distributed_packages",
        "include_private_modules",
        "module_registry",
        "scan_root",
    )

    def __init__(
        self,
        *,
        scan_root: str = "",
        module_registry: ModuleRegistryHandle | None = None,
        distributed_packages: frozenset[str] | None = None,
        include_private_modules: bool = False,
    ) -> None:
        self.scan_root = scan_root
        self.module_registry = module_registry
        self.distributed_packages = distributed_packages
        self.include_private_modules = include_private_modules

    def surface_kind(self, *, filepath: str, module: str) -> str:
        """The one kind of one module. Exhaustive, and one verdict per module.

        Order is the decision table, not a preference: a test tree that happens
        to be private is test support, and a shipped module that happens to be
        private is product internal. Reversing any pair changes which answer a
        module gets, which is what the mutation battery reds.
        """

        if is_test_filepath(
            filepath,
            scan_root=self.scan_root,
            module_registry=self.module_registry,
        ):
            return SURFACE_KIND_TEST_SUPPORT
        if not self._is_distributed(module):
            return SURFACE_KIND_REPOSITORY_SUPPORT
        if not is_public_module_name(module):
            return SURFACE_KIND_PRODUCT_INTERNAL
        return SURFACE_KIND_PRODUCT_PUBLIC

    def public_namespaces(self) -> frozenset[str]:
        """The modules an external caller can name: the product's public paths.

        Every module of the registry whose kind is ``product_public`` — and,
        when the run says so, ``product_internal``. This is the set the
        reachability owner exposes by definition inside, so a wider set is a
        wider API by construction: a public-named module of the test track or
        of an unshipped tree is a Python module a caller could import and not
        a place the project promises a name at. The registry is the universe
        because a package ``__init__`` that only re-exports collects no symbol
        of its own and still is the namespace everything hangs from.
        """

        registry = self.module_registry
        if registry is None:
            raise ValueError("public namespaces need the run's module registry")
        namespaces: set[str] = set()
        for module, entry in registry.entries_by_module.rows:
            kind = self.surface_kind(
                filepath=self._runtime_path(entry.identity.file.path),
                module=module,
            )
            if kind == SURFACE_KIND_PRODUCT_PUBLIC or (
                self.include_private_modules and kind == SURFACE_KIND_PRODUCT_INTERNAL
            ):
                namespaces.add(module)
        return frozenset(namespaces)

    def _runtime_path(self, path: str) -> str:
        """The registry stores repository-relative paths; the kind owner
        classifies the spelling a run carries, which is rooted."""

        return os.path.join(self.scan_root, path) if self.scan_root else path

    def _is_distributed(self, module: str) -> bool:
        declared = self.distributed_packages
        if declared is None:
            return True
        return any(
            module == package or module.startswith(f"{package}.")
            for package in declared
        )


def classify_api_exposure(
    modules: Sequence[ModuleApiSurface],
    *,
    population: ApiSurfacePopulation,
    definitions: Sequence[DeadCandidate],
    module_deps: Sequence[ModuleDep],
    class_metrics: Sequence[ClassMetrics],
    package_modules: frozenset[str],
    declared_exports: Iterable[str] = (),
) -> tuple[ModuleApiSurface, ...]:
    """Stamp every collected symbol with whether a public namespace binds it.

    The binding universe is the walk's definitions plus the public symbols
    themselves: the walk's because a package's ``__getattr__``, its classes
    and their bases live there and a constant is not among them; the symbols'
    because a module-level constant is api surface and nothing else defines
    it. The namespaces are the population owner's. Order is the caller's;
    this stamps and never reorders.
    """

    if not modules:
        return tuple(modules)
    api_definitions = tuple(
        SymbolDefinition(
            qualname=symbol.qualname,
            local_name=symbol.qualname.partition(":")[2].rpartition(".")[2],
            kind=symbol.kind,
            # The collector admitted this name by the language's own star
            # rule - listed in ``__all__``, or public-named in a module that
            # declares none - so ``from <module> import *`` binds it by
            # construction.
            star_import_bound=True,
        )
        for module in modules
        for symbol in module.symbols
    )
    verdicts = reachability_by_qualname(
        collect_external_reachability(
            definitions=(*definitions, *api_definitions),
            module_deps=module_deps,
            class_metrics=class_metrics,
            package_modules=package_modules,
            declared_exports=declared_exports,
            public_modules=population.public_namespaces(),
            # The collector already called these methods public; the oracle's
            # plain underscore rule would call ``Beta.__init__`` private and
            # drop a constructor signature from the contract.
            public_leaves=PUBLIC_METHOD_DUNDERS,
        )
    )
    return tuple(
        replace(
            module,
            symbols=tuple(
                replace(symbol, exposure=verdicts[symbol.qualname].state)
                for symbol in module.symbols
            ),
        )
        for module in modules
    )


def is_product_surface(module: ModuleApiSurface) -> bool:
    """May this module's symbols be API at all? Reads the stamped kind."""

    return module.surface_kind in _PRODUCT_KINDS


def is_api_visible(module: ModuleApiSurface, symbol: PublicSymbol) -> bool:
    """The one projection from the two stamped verdicts to "this is API".

    Both stamps decide, and both must be present: a product kind on the
    module and an included exposure on the symbol. An unstamped module or
    symbol is not permissive - reading a gap as included would restore the
    definition-site population silently.
    """

    return is_product_surface(module) and symbol.exposure in _VISIBLE_EXPOSURES


def visible_api_surface(
    snapshot: ApiSurfaceSnapshot | None,
) -> ApiSurfaceSnapshot | None:
    """The API in a collected snapshot: the symbols :func:`is_api_visible`
    admits, in the snapshot's own order, modules left empty dropped."""

    if snapshot is None:
        return None
    modules: list[ModuleApiSurface] = []
    for module in snapshot.modules:
        symbols = tuple(
            symbol for symbol in module.symbols if is_api_visible(module, symbol)
        )
        if symbols:
            modules.append(replace(module, symbols=symbols))
    return ApiSurfaceSnapshot(modules=tuple(modules))
