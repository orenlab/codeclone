# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Core behaviour that only one interpreter would otherwise ever execute.

Three sites in the analysis core are decided by the running interpreter:

* ``core.entrypoints._load_toml_payload`` and ``config.pyproject_loader``'s
  ``_load_toml`` both read TOML through the stdlib ``tomllib`` on 3.11+ and
  through the ``tomli`` backport below it. Each interpreter runs one body and
  never the other, so the unexercised one is reached by moving the version
  gate -- the idiom this repository already uses for the ``tomli`` side in
  ``test_core_branch_coverage.py`` and ``test_cli_config.py``.
* ``analysis.wire`` folds a t-string ``Interpolation`` (PEP 750, 3.14+) by
  matching the node's *type name* rather than by ``isinstance``, precisely so
  the emitter does not need that type to exist at import time. That contract
  is therefore testable on every interpreter; real t-string grammar stays
  covered by the 3.14-gated cases in ``test_wire.py``.
"""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import cast

import pytest

from codeclone.analysis import wire as wire_mod
from codeclone.analysis.binding import EMPTY_BINDINGS
from codeclone.analysis.normalizer import NormalizationConfig
from codeclone.config import pyproject_loader as loader_mod
from codeclone.core import entrypoints as entrypoints_mod


def _stdlib_toml_parser() -> ModuleType:
    """The 3.11+ stdlib parser, or the identical backport this project already
    depends on below 3.11. Binding it as ``tomllib`` lets the 3.11+ body run a
    real parse on an older interpreter rather than a stubbed one."""

    name = "tomllib" if sys.version_info >= (3, 11) else "tomli"
    return importlib.import_module(name)


@pytest.fixture
def stdlib_toml_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Put both version gates on their 3.11+ side and make ``tomllib``
    importable there, whatever interpreter is running.

    ``pyproject_loader`` also reads ``sys.platform`` on the open path, so the
    stand-in carries the real one rather than hiding the host.
    """

    monkeypatch.setitem(sys.modules, "tomllib", _stdlib_toml_parser())
    monkeypatch.setattr(entrypoints_mod, "sys", SimpleNamespace(version_info=(3, 11)))
    monkeypatch.setattr(
        loader_mod,
        "sys",
        SimpleNamespace(version_info=(3, 11), platform=sys.platform),
    )


@pytest.mark.usefixtures("stdlib_toml_branch")
def test_entrypoint_loader_parses_a_project_table_on_the_stdlib_branch(
    tmp_path: Path,
) -> None:
    config = tmp_path / "pyproject.toml"
    config.write_text('[project.scripts]\ntool = "pkg.cli:main"\n', encoding="utf-8")

    assert entrypoints_mod._load_toml_payload(config) == {
        "project": {"scripts": {"tool": "pkg.cli:main"}}
    }


@pytest.mark.usefixtures("stdlib_toml_branch")
def test_entrypoint_loader_rejects_invalid_toml_on_the_stdlib_branch(
    tmp_path: Path,
) -> None:
    config = tmp_path / "pyproject.toml"
    config.write_text("[project", encoding="utf-8")

    assert entrypoints_mod._load_toml_payload(config) == {}


def test_entrypoint_loader_rejects_a_non_table_payload_on_the_stdlib_branch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A parser answering with something other than a table is refused rather
    than passed on as project metadata."""

    class _NonTableParser:
        @staticmethod
        def load(handle: object) -> list[str]:
            del handle
            return ["not", "a", "table"]

    monkeypatch.setitem(sys.modules, "tomllib", cast(ModuleType, _NonTableParser))
    monkeypatch.setattr(entrypoints_mod, "sys", SimpleNamespace(version_info=(3, 11)))
    config = tmp_path / "pyproject.toml"
    config.write_text("[project]\n", encoding="utf-8")

    assert entrypoints_mod._load_toml_payload(config) == {}


@pytest.mark.usefixtures("stdlib_toml_branch")
def test_config_loader_reads_pyproject_on_the_stdlib_branch(
    tmp_path: Path,
) -> None:
    """The repo config reader has the same gate as the entrypoint loader, and
    on 3.10 its stdlib body was never executed by any test."""

    config = tmp_path / "pyproject.toml"
    config.write_text("[tool.codeclone]\nmin_loc = 7\n", encoding="utf-8")

    assert loader_mod._load_toml(config) == {"tool": {"codeclone": {"min_loc": 7}}}


class Interpolation(ast.AST):
    """Stand-in for ``ast.Interpolation`` (PEP 750, 3.14+).

    The emitter matches this node by type name, so a class of the same name
    exercises the production predicate exactly, on every interpreter.
    """

    _fields = ("str",)


def test_wire_folds_a_t_string_interpolation_expression_to_a_constant() -> None:
    """The interpolated expression is normalised away, so two t-strings that
    differ only in what they interpolate hash alike."""

    emitted = wire_mod._emit_capture_or_generic_field(
        Interpolation(), "str", NormalizationConfig(), EMPTY_BINDINGS
    )

    assert emitted == "_CONST_"


def test_wire_folds_only_the_interpolation_expression_field() -> None:
    """Sibling fields of the same node keep the generic emission path."""

    emitted = wire_mod._emit_capture_or_generic_field(
        Interpolation(), "conversion", NormalizationConfig(), EMPTY_BINDINGS
    )

    assert emitted == "None"


def test_wire_folds_no_constant_for_a_differently_named_node() -> None:
    """The fold is keyed on the node's type name, not on the field name."""

    emitted = wire_mod._emit_capture_or_generic_field(
        ast.Pass(), "str", NormalizationConfig(), EMPTY_BINDINGS
    )

    assert emitted == "None"
