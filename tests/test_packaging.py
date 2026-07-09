# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path
from typing import cast

from codeclone.config.pyproject_loader import _load_toml


def _package_name(repo_root: Path, package_dir: Path) -> str:
    return ".".join(package_dir.relative_to(repo_root).parts)


def _is_data_only_namespace_package(package_dir: Path) -> bool:
    """True for PEP 420 data dirs (no ``__init__.py``, non-Python payload files).

    Setuptools treats such directories as importable packages and requires them in
    ``[tool.setuptools].packages`` when using an explicit package list.
    """

    if not package_dir.is_dir() or (package_dir / "__init__.py").exists():
        return False
    if package_dir.name.startswith(".") or package_dir.name == "__pycache__":
        return False
    return any(
        child.is_file() and not child.name.startswith(".") and child.suffix != ".py"
        for child in package_dir.iterdir()
    )


def _discover_codeclone_packages(repo_root: Path) -> set[str]:
    """Discover regular packages plus nested data-only namespace dirs from the tree.

    Discovery is filesystem-based so missing ``pyproject.toml`` entries fail the
    test; do not derive expected packages from package-data alone.
    """

    codeclone_root = repo_root / "codeclone"
    packages: set[str] = set()
    regular_package_dirs: list[Path] = []
    for init_path in codeclone_root.rglob("__init__.py"):
        package_dir = init_path.parent
        packages.add(_package_name(repo_root, package_dir))
        regular_package_dirs.append(package_dir)
    # Data-only namespace packages live as children of a regular package.
    for package_dir in regular_package_dirs:
        for child in package_dir.iterdir():
            if _is_data_only_namespace_package(child):
                packages.add(_package_name(repo_root, child))
    return packages


def _load_setuptools_packages(repo_root: Path) -> set[str]:
    pyproject_path = repo_root / "pyproject.toml"
    payload = cast(dict[str, object], _load_toml(pyproject_path))
    tool = cast(dict[str, object], payload["tool"])
    setuptools = cast(dict[str, object], tool["setuptools"])
    packages = setuptools["packages"]
    if not isinstance(packages, list):
        msg = "tool.setuptools.packages must be a list"
        raise AssertionError(msg)
    return {str(item) for item in packages}


def test_setuptools_packages_match_codeclone_subpackages() -> None:
    """Every codeclone package dir must be declared for wheel/sdist builds."""

    repo_root = Path(__file__).resolve().parents[1]
    discovered = _discover_codeclone_packages(repo_root)
    declared = _load_setuptools_packages(repo_root)

    missing = sorted(discovered - declared)
    assert missing == [], (
        "Add missing subpackages to [tool.setuptools].packages in pyproject.toml: "
        + ", ".join(missing)
    )

    orphan = sorted(declared - discovered)
    assert orphan == [], (
        "Remove stale setuptools entries (no matching codeclone package dir): "
        + ", ".join(orphan)
    )


def test_setuptools_packages_are_codeclone_only() -> None:
    """Internal maintainer tooling must not ship as a top-level wheel package."""

    repo_root = Path(__file__).resolve().parents[1]
    declared = _load_setuptools_packages(repo_root)
    non_codeclone = sorted(
        package for package in declared if not package.startswith("codeclone")
    )
    assert non_codeclone == [], (
        "Remove non-codeclone packages from [tool.setuptools].packages: "
        + ", ".join(non_codeclone)
    )
