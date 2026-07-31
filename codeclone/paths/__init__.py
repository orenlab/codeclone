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

if TYPE_CHECKING:
    from ..models import ModuleRegistryHandle


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
    entry = None
    for candidate in (
        normalize_repo_path(relative_path),
        normalize_repo_path(filepath),
    ):
        try:
            entry = module_registry.entries_by_path[candidate]
        except KeyError:
            continue
        break
    if entry is None or entry.identity.python_module is None:
        return False
    # Vocabulary membership is case-insensitive, but the module path itself
    # keeps its case: registry keys are module identities, and lowercasing one
    # before the lookup below turns ``MyPkg.testing`` into an unknown module,
    # silently demoting a distributed package to a test tree.
    module_parts = entry.identity.python_module.module.split(".")
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
        # a nested ``tests/testing/`` package.
        return False
    return all(
        _is_registered_package(
            module_registry,
            ".".join(module_parts[: index + 1]),
        )
        for index in range(test_index + 1)
    )


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
    return filename in _TEST_FILE_NAMES or filename.startswith("test_")
