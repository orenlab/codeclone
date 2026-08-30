# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Setup discovery reads ``pyproject.toml`` through a version-gated parser.

``_tool_codeclone_section_present`` binds the stdlib ``tomllib`` on 3.11+ and
the ``tomli`` backport below it, so each interpreter executes one branch and
leaves the other unmeasured. The ``tomli`` side is already pinned in
``test_cli_setup.py`` by moving the gate downward; this pins the stdlib side
the same way, so the branch is exercised wherever the suite runs.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from codeclone.surfaces.cli.setup.engine import discover as discover_mod


def _stdlib_toml_parser() -> ModuleType:
    """The 3.11+ stdlib parser, or the identical backport this project already
    depends on below 3.11."""

    name = "tomllib" if sys.version_info >= (3, 11) else "tomli"
    return importlib.import_module(name)


@pytest.fixture
def stdlib_toml_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Put the version gate on its 3.11+ side and make ``tomllib`` importable
    there, whatever interpreter is running."""

    monkeypatch.setitem(sys.modules, "tomllib", _stdlib_toml_parser())
    monkeypatch.setattr(discover_mod, "sys", SimpleNamespace(version_info=(3, 11)))


@pytest.mark.usefixtures("stdlib_toml_branch")
def test_setup_discovery_finds_the_tool_section_on_the_stdlib_branch(
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.codeclone]\nmin_loc = 5\n", encoding="utf-8"
    )

    assert discover_mod._tool_codeclone_section_present(tmp_path) is True


@pytest.mark.usefixtures("stdlib_toml_branch")
def test_setup_discovery_reports_no_section_when_the_table_is_absent(
    tmp_path: Path,
) -> None:
    """The stdlib branch reaches the same verdict as the backport branch for a
    project that simply does not configure the tool."""

    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "unconfigured"\n', encoding="utf-8"
    )

    assert discover_mod._tool_codeclone_section_present(tmp_path) is False
