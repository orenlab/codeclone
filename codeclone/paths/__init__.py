# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ..domain.source_scope import (
    SOURCE_KIND_FIXTURES,
    SOURCE_KIND_OTHER,
    SOURCE_KIND_PRODUCTION,
    SOURCE_KIND_TESTS,
)

_TEST_FILE_NAMES = {"conftest.py"}
_TEST_DIRECTORY_NAMES = frozenset({"test", "testing", "tests"})
_TEST_MODULE_NAME_PREFIX = "test_"

if TYPE_CHECKING:
    from ..models import ModuleInventoryEntry, ModuleRegistryHandle


def normalize_repo_path(value: str) -> str:
    return value.replace("\\", "/").strip()


def relative_repo_path(filepath: str, *, scan_root: str = "") -> str:
    normalized_path = normalize_repo_path(filepath)
    normalized_root = normalize_repo_path(scan_root).rstrip("/")
    if not normalized_path:
        return normalized_path
    if not normalized_root:
        return normalized_path
    prefix = f"{normalized_root}/"
    if normalized_path.startswith(prefix):
        return normalized_path[len(prefix) :]
    if normalized_path == normalized_root:
        return normalized_path.rsplit("/", maxsplit=1)[-1]
    return normalized_path


def classify_source_kind(
    filepath: str,
    *,
    scan_root: str = "",
    module_registry: ModuleRegistryHandle | None = None,
) -> str:
    rel = relative_repo_path(filepath, scan_root=scan_root)
    parts = [part for part in rel.lower().split("/") if part and part != "."]
    if not parts:
        return SOURCE_KIND_OTHER
    for idx, part in enumerate(parts):
        if part not in _TEST_DIRECTORY_NAMES:
            continue
        if _is_importable_package_tree(
            filepath=filepath,
            relative_path=rel,
            module_registry=module_registry,
        ):
            return SOURCE_KIND_PRODUCTION
        if idx + 1 < len(parts) and parts[idx + 1] == SOURCE_KIND_FIXTURES:
            return SOURCE_KIND_FIXTURES
        return SOURCE_KIND_TESTS
    return SOURCE_KIND_PRODUCTION


def _is_importable_package_tree(
    *,
    filepath: str,
    relative_path: str,
    module_registry: ModuleRegistryHandle | None,
) -> bool:
    """Decide whether a test-named segment sits inside a distributed package.

    A ``tests``/``test``/``testing`` directory is test-kind unless the module
    identity registry proves it is a subpackage of an importable *distributed*
    package of the analysis root. Two registry facts decide it: the owning
    top-level module must not itself be a test-named tree, and every segment
    from that top level down to the test-named segment must be a regular
    package, so the tree is reachable by an ordinary import.
    """
    if module_registry is None:
        return False
    # Vocabulary membership is case-insensitive, but the module path itself
    # keeps its case: registry keys are module identities, and lowercasing one
    # before the chain lookup turns ``MyPkg.testing`` into an unknown module,
    # silently demoting a distributed package to a test tree.
    module_parts = _module_identity_parts(
        module_registry,
        filepath=filepath,
        relative_path=relative_path,
    )
    test_index = next(
        (
            index
            for index, part in enumerate(module_parts)
            if part.lower() in _TEST_DIRECTORY_NAMES
        ),
        None,
    )
    if test_index is None or test_index == 0:
        # A top-level test-named tree (``tests/``, ``testing/``) is importable
        # but never distributed, so nothing under it is production - including
        # a nested ``tests/testing/`` package. An unregistered file lands here
        # too: with no identity there is no test-named segment to find.
        return False
    return _is_regular_package_chain(module_registry, module_parts[: test_index + 1])


def _registry_entry(
    module_registry: ModuleRegistryHandle,
    *,
    filepath: str,
    relative_path: str,
) -> ModuleInventoryEntry | None:
    """Find one file's identity in the module registry, from either shape.

    Both readers of module identity below need this lookup, and a run hands
    them paths in two shapes: the pipeline classifies absolute paths against
    a scan root, while cache- and report-side callers already hold
    repository-relative ones. Trying both is what makes the registry facts
    reachable from either, and keeping it in one place is what stops the two
    readers from drifting into two different lookups.
    """
    for candidate in (
        normalize_repo_path(relative_path),
        normalize_repo_path(filepath),
    ):
        entry = module_registry.entries_by_path.get(candidate)
        if entry is not None:
            return entry
    return None


def _module_identity_parts(
    module_registry: ModuleRegistryHandle,
    *,
    filepath: str,
    relative_path: str,
) -> tuple[str, ...]:
    """The dotted module identity of one file, empty when it has none.

    Emptiness is the single answer to every way the question can fail - the
    file is outside the inventory, or it has no importable module name - so
    the callers below spell out one judgement about identity instead of
    repeating the registry's own failure modes.
    """
    entry = _registry_entry(
        module_registry,
        filepath=filepath,
        relative_path=relative_path,
    )
    if entry is None or entry.identity.python_module is None:
        return ()
    return tuple(entry.identity.python_module.module.split("."))


def _is_regular_package_chain(
    module_registry: ModuleRegistryHandle,
    module_parts: tuple[str, ...],
) -> bool:
    """Is every module these segments name a regular package of the tree?

    This is what "reachable by an ordinary import" means to both callers: a
    namespace directory or a plain folder breaks the chain, and neither
    caller may treat what sits under it as part of a distributed package.
    """
    return all(
        _is_registered_package(module_registry, ".".join(module_parts[: index + 1]))
        for index in range(len(module_parts))
    )


def _is_published_package_module(
    *,
    filepath: str,
    relative_path: str,
    module_registry: ModuleRegistryHandle | None,
) -> bool:
    """Decide whether a test-named *file* is a module its package publishes.

    pytest's filename convention is a repository fact, not a packaging one.
    Read as "test-named anywhere is test code" it deletes a published module
    from the product's contract: a library that ships test helpers for its
    own users - ``annotated_types.test_cases`` is one - would lose them from
    the api-surface lane, and the same file would be exempt from dead-code
    reporting although its symbols are the contract.

    The distinguishing fact is the one ``_is_importable_package_tree``
    already uses for test-named *directories*, asked of a file: the registry
    must prove every segment above the module is a regular package, and no
    segment above it may be in the source-kind directory vocabulary. That
    second clause is what keeps a distribution's own suite out - a shipped
    ``pkg/tests/test_case.py`` is inside a package and is still test code.

    Measured over this project's whole dependency closure (7464 ``.py``
    files under ``site-packages``): of the 860 files the filename convention
    alone calls test-kind, 848 sit in a shipped ``tests``/``test``
    subpackage, 11 are ``conftest.py``, and exactly 1 is a module a package
    publishes. Registry-free the answer is ``False``, so a caller that cannot
    prove the fact keeps the reading it had before.
    """
    if module_registry is None:
        return False
    # The owning packages only - the module's own leaf name is the thing the
    # convention already objected to, and re-reading it here would refuse
    # every file this predicate exists to admit. An unregistered file has no
    # owning packages at all and is refused by the same line.
    owning_parts = _module_identity_parts(
        module_registry,
        filepath=filepath,
        relative_path=relative_path,
    )[:-1]
    if not owning_parts:
        return False
    if any(part.lower() in _TEST_DIRECTORY_NAMES for part in owning_parts):
        return False
    return _is_regular_package_chain(module_registry, owning_parts)


def _is_registered_package(
    module_registry: ModuleRegistryHandle,
    module_name: str,
) -> bool:
    entry = module_registry.entries_by_module.get(module_name)
    return (
        entry is not None
        and entry.identity.python_module is not None
        and entry.identity.python_module.is_package
    )


def is_test_filepath(
    filepath: str,
    *,
    scan_root: str = "",
    module_registry: ModuleRegistryHandle | None = None,
) -> bool:
    source_kind = classify_source_kind(
        filepath,
        scan_root=scan_root,
        module_registry=module_registry,
    )
    if source_kind in {SOURCE_KIND_TESTS, SOURCE_KIND_FIXTURES}:
        return True
    filename = Path(filepath).name.lower()
    if filename in _TEST_FILE_NAMES:
        # ``conftest.py`` is pytest's configuration file, a test artifact by
        # role rather than by name. Every one of the eleven found inside
        # shipped packages of this project's dependency closure (numpy,
        # scipy, sklearn, pyarrow, ...) configures that distribution's own
        # suite, and none is a published symbol, so this stays categorical.
        return True
    if not filename.startswith(_TEST_MODULE_NAME_PREFIX):
        return False
    return not _is_published_package_module(
        filepath=filepath,
        relative_path=relative_repo_path(filepath, scan_root=scan_root),
        module_registry=module_registry,
    )
