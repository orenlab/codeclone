# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path
from typing import cast

from codeclone.config.pyproject_loader import _load_toml


def _discover_codeclone_packages(repo_root: Path) -> set[str]:
    codeclone_root = repo_root / "codeclone"
    packages: set[str] = set()
    for init_path in codeclone_root.rglob("__init__.py"):
        relative = init_path.parent.relative_to(repo_root)
        packages.add(".".join(relative.parts))
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


def test_wheel_excludes_internal_review_kit(tmp_path: Path) -> None:
    """Built wheel must not install review_kit into site-packages."""

    repo_root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "-o", str(tmp_path)],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = sorted(tmp_path.glob("*.whl"))
    assert len(wheels) == 1

    with zipfile.ZipFile(wheels[0]) as archive:
        names = archive.namelist()
        review_paths = [name for name in names if name.startswith("review_kit/")]
        assert review_paths == []

        top_level_entries = [
            name for name in names if name.endswith(".dist-info/top_level.txt")
        ]
        assert len(top_level_entries) == 1
        top_level = archive.read(top_level_entries[0]).decode().splitlines()
        assert "review_kit" not in top_level
