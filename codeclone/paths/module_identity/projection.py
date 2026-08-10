# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Module-to-path projection: the single owner of the honest direction.

The inverse of resolution — projecting a dotted module name back onto a
repository file — follows one law: ``<pkg>/__init__.py`` when it exists,
else ``<pkg>.py`` when it exists, else UNRESOLVED (``None``). A path is
never invented; ``module.replace(".", "/") + ".py"`` outside this owner is
the phantom-path bug this module exists to end.

Three oracles answer "does this file exist", all under the same law:

- a known-file set (report inventories, already-resolved run data),
- the filesystem under an analysis root,
- the module registry, whose identity inventory is the strongest source —
  it also covers import mounts, where root-relative candidates cannot.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Container
    from pathlib import Path

    from codeclone.models import ModuleRegistryHandle


def module_path_candidates(module: str) -> tuple[str, str] | None:
    """The only two candidate spellings a dotted module may project to."""

    name = module.strip()
    if not name or name.startswith(".") or name.endswith("."):
        return None
    base = "/".join(name.split("."))
    return (f"{base}/__init__.py", f"{base}.py")


def project_module_path(
    module: str,
    file_exists: Callable[[str], bool],
) -> str | None:
    """Apply the projection law against an existence oracle."""

    candidates = module_path_candidates(module)
    if candidates is None:
        return None
    for candidate in candidates:
        if file_exists(candidate):
            return candidate
    return None


def module_path_from_files(
    module: str,
    files: Container[str],
) -> str | None:
    """Project against a set of known repository-relative file paths."""

    return project_module_path(module, files.__contains__)


def module_path_under_root(
    module: str,
    root: Path,
) -> str | None:
    """Project against the filesystem below an analysis root."""

    return project_module_path(
        module,
        lambda candidate: (root / candidate).is_file(),
    )


def module_path_from_registry(
    module: str,
    registry: ModuleRegistryHandle,
) -> str | None:
    """Project through the identity inventory — the strongest oracle.

    An analyzed or known-internal module carries its real file identity,
    including under non-root import mounts. Modules the registry cannot
    place stay UNRESOLVED; the root-relative candidates are deliberately
    not consulted here because the registry already IS the existence proof.
    """

    entry = registry.entries_by_module.get(module)
    if entry is None:
        return None
    return entry.identity.file.path


__all__ = [
    "module_path_candidates",
    "module_path_from_files",
    "module_path_from_registry",
    "module_path_under_root",
    "project_module_path",
]
