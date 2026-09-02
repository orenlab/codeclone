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

The owner assigns exactly one *surface kind* per module, from three inputs, and
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

What the owner deliberately does NOT decide: which modules are collected. The
collected population is the lane's stored payload, and narrowing it against a
baseline written by an earlier build reads every dropped symbol as ``removed``.
The kind narrows what may *gate* — it rides the collected row as data, and the
comparison drops both sides of a non-gating module together.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..domain.source_scope import (
    SURFACE_KIND_PRODUCT_INTERNAL,
    SURFACE_KIND_PRODUCT_PUBLIC,
    SURFACE_KIND_REPOSITORY_SUPPORT,
    SURFACE_KIND_TEST_SUPPORT,
)
from ..paths import is_test_filepath
from ._visibility import is_public_module_name

if TYPE_CHECKING:
    from ..models import ModuleRegistryHandle

__all__ = ["ApiSurfacePopulation"]


class ApiSurfacePopulation:
    """The run's answer to "what is this project's public API surface".

    Built once per run where all three inputs exist, and read everywhere else.
    ``distributed_packages`` is ``None`` when the repository declares no
    manifest this owner can read: unknown is not "nothing ships", so an
    undeclared manifest keeps every non-test module on the product track — the
    behaviour that already exists — instead of silently emptying the lane.

    Deliberately not a dataclass: the model store owns the repository's data
    shapes, and this is a decision object whose fields are the inputs to one
    verdict.
    """

    __slots__ = ("distributed_packages", "module_registry", "scan_root")

    def __init__(
        self,
        *,
        scan_root: str = "",
        module_registry: ModuleRegistryHandle | None = None,
        distributed_packages: frozenset[str] | None = None,
    ) -> None:
        self.scan_root = scan_root
        self.module_registry = module_registry
        self.distributed_packages = distributed_packages

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

    def _is_distributed(self, module: str) -> bool:
        declared = self.distributed_packages
        if declared is None:
            return True
        return any(
            module == package or module.startswith(f"{package}.")
            for package in declared
        )
